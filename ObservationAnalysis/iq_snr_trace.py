#!/usr/bin/env python3
"""
iq_snr_trace.py

Estimates SNR vs elapsed time directly from a raw cs16 IQ baseband file,
independent of SatDump's internal (sparse, lock-event-only) SNR reporting.

Method: slice the recording into fixed-duration time windows. For each
window, compute the Welch power spectral density, then compare the mean
PSD inside the signal's occupied bandwidth against the mean PSD in
noise-only guard bands at the edges of the recorded spectrum. The ratio
(in dB) is the SNR estimate for that window.

Usage:
    python3 iq_snr_trace.py <input.raw> <output.csv> \
        [--samplerate 160000] [--symbolrate 72000] [--rolloff 0.5] \
        [--window 1.0] [--dc-exclude 1000]
"""

import argparse
import csv
import numpy as np
from scipy.signal import welch


def main():
    p = argparse.ArgumentParser(description="Estimate SNR vs time from a raw cs16 IQ file.")
    p.add_argument("input_file", help="Path to raw cs16 IQ baseband file")
    p.add_argument("output_csv", help="Path to write the SNR-vs-time CSV")
    p.add_argument("--samplerate", type=float, default=160000.0,
                    help="Sample rate in Hz (default: 160000, the gr-satnogs decimated rate)")
    p.add_argument("--symbolrate", type=float, default=72000.0,
                    help="Symbol rate in baud (default: 72000, Meteor M2-x LRPT)")
    p.add_argument("--rolloff", type=float, default=0.5,
                    help="RRC roll-off factor alpha (default: 0.5, matches the meteor_m2-x_lrpt pipeline)")
    p.add_argument("--window", type=float, default=1.0,
                    help="Analysis window duration in seconds (default: 1.0)")
    p.add_argument("--dc-exclude", type=float, default=1000.0,
                    help="Half-width in Hz to exclude around DC, avoids RTL-SDR's hardware DC spike (default: 1000)")
    p.add_argument("--guard-start", type=float, default=None,
                    help="Start of noise-only guard band, Hz from DC (default: signal edge + 5 kHz)")
    p.add_argument("--guard-end", type=float, default=None,
                    help="End of noise-only guard band, Hz from DC (default: 0.97 x Nyquist)")
    args = p.parse_args()

    fs = args.samplerate
    occupied_bw = args.symbolrate * (1 + args.rolloff)
    signal_half_bw = occupied_bw / 2.0

    nyquist = fs / 2.0
    guard_start = args.guard_start if args.guard_start is not None else signal_half_bw + 5000.0
    guard_end = args.guard_end if args.guard_end is not None else nyquist * 0.97

    if guard_start >= guard_end:
        raise ValueError(
            f"Noise guard band is empty (guard_start={guard_start:.0f} Hz >= "
            f"guard_end={guard_end:.0f} Hz). Occupied bandwidth ({occupied_bw/1000:.1f} kHz) "
            f"may be too close to the sample rate's Nyquist limit ({nyquist/1000:.1f} kHz). "
            f"Try a lower --window or check --samplerate."
        )

    samples_per_window = int(fs * args.window)
    bytes_per_window = samples_per_window * 4  # cs16 = int16 I + int16 Q = 4 bytes/complex sample

    print(f"Sample rate        : {fs:.0f} Hz")
    print(f"Occupied bandwidth : {occupied_bw/1000:.1f} kHz (+/-{signal_half_bw/1000:.1f} kHz)")
    print(f"DC exclusion       : +/-{args.dc_exclude/1000:.2f} kHz")
    print(f"Noise guard band   : {guard_start/1000:.1f}-{guard_end/1000:.1f} kHz (each side)")
    print(f"Window duration    : {args.window:.2f} s ({samples_per_window} samples)")
    print()

    nperseg = min(8192, samples_per_window)

    results = []
    window_index = 0

    with open(args.input_file, "rb") as f:
        while True:
            raw = f.read(bytes_per_window)
            if len(raw) < bytes_per_window:
                break  # drop final partial window

            iq = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
            i_samples = iq[0::2]
            q_samples = iq[1::2]
            complex_samples = i_samples + 1j * q_samples

            freqs, psd = welch(
                complex_samples, fs=fs, nperseg=nperseg,
                return_onesided=False, scaling="density",
            )
            freqs = np.fft.fftshift(freqs)
            psd = np.fft.fftshift(psd)

            signal_mask = (np.abs(freqs) <= signal_half_bw) & (np.abs(freqs) > args.dc_exclude)
            noise_mask = (np.abs(freqs) >= guard_start) & (np.abs(freqs) <= guard_end)

            signal_density = np.mean(psd[signal_mask])
            noise_density = np.mean(psd[noise_mask])

            snr_db = 10 * np.log10(signal_density / noise_density)
            elapsed_s = window_index * args.window

            results.append((elapsed_s, snr_db))
            window_index += 1

    with open(args.output_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["elapsed_seconds", "snr_db"])
        writer.writerows([(round(t, 2), round(s, 3)) for t, s in results])

    print(f"Wrote {len(results)} samples to {args.output_csv}")
    if results:
        snrs = [s for _, s in results]
        print(f"SNR range: {min(snrs):.2f} dB to {max(snrs):.2f} dB, mean {np.mean(snrs):.2f} dB")


if __name__ == "__main__":
    main()

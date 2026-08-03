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

Structure: the numerical core is separated from file and CLI handling so it
can be unit tested. See tests/test_snr_estimator.py.

Usage:
    python3 iq_snr_trace.py <input.raw> <output.csv> \
        [--samplerate 160000] [--symbolrate 72000] [--rolloff 0.5] \
        [--window 1.0] [--dc-exclude 1000]

Note on symbol rate: Meteor M2-x LRPT is OQPSK at 72 kBaud (some modes 80k).
The "FSK 40000" figure shown on SatNOGS transmitter entries is a recording
configuration parameter controlling IQ capture bandwidth, not the modulation
symbol rate, and should not be used here.
"""

import argparse
import csv

import numpy as np
from scipy.signal import welch

BYTES_PER_COMPLEX_SAMPLE = 4  # cs16: int16 I + int16 Q


# ---------------------------------------------------------------------------
# Pure computation — no file or CLI dependencies
# ---------------------------------------------------------------------------

def occupied_bandwidth(symbolrate, rolloff):
    """Occupied bandwidth of a root-raised-cosine shaped signal, in Hz.

    For RRC pulse shaping, occupied BW = symbol rate * (1 + alpha).
    Meteor LRPT: 72000 * 1.5 = 108000 Hz.
    """
    if symbolrate <= 0:
        raise ValueError(f"symbolrate must be positive, got {symbolrate}")
    if not 0.0 <= rolloff <= 1.0:
        raise ValueError(f"rolloff must be in [0, 1], got {rolloff}")
    return symbolrate * (1.0 + rolloff)


def compute_bands(samplerate, symbolrate, rolloff,
                  guard_start=None, guard_end=None, guard_margin=5000.0,
                  nyquist_fraction=0.97):
    """Work out the signal and noise band edges for the given signal parameters.

    Returns a dict with signal_half_bw, guard_start, guard_end, occupied_bw.
    Raises ValueError if no clean noise-only region exists between the signal
    edge and Nyquist — i.e. the sample rate is too low for this signal.
    """
    occupied_bw = occupied_bandwidth(symbolrate, rolloff)
    signal_half_bw = occupied_bw / 2.0
    nyquist = samplerate / 2.0

    if guard_start is None:
        guard_start = signal_half_bw + guard_margin
    if guard_end is None:
        guard_end = nyquist * nyquist_fraction

    if guard_start >= guard_end:
        raise ValueError(
            f"Noise guard band is empty (guard_start={guard_start:.0f} Hz >= "
            f"guard_end={guard_end:.0f} Hz). Occupied bandwidth "
            f"({occupied_bw/1000:.1f} kHz) may be too close to the sample rate's "
            f"Nyquist limit ({nyquist/1000:.1f} kHz)."
        )

    return {
        "occupied_bw": occupied_bw,
        "signal_half_bw": signal_half_bw,
        "guard_start": guard_start,
        "guard_end": guard_end,
        "nyquist": nyquist,
    }


def deinterleave_cs16(raw_bytes):
    """Convert interleaved cs16 bytes (I,Q,I,Q,...) to a complex64 array."""
    iq = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32)
    if iq.size % 2:
        raise ValueError("cs16 buffer has an odd number of int16 values")
    return iq[0::2] + 1j * iq[1::2]


def band_masks(freqs, bands, dc_exclude):
    """Boolean masks selecting the signal band and the noise guard bands.

    Both are symmetric about DC. The signal mask excludes +/- dc_exclude to
    reject the RTL-SDR's hardware DC spike, which would otherwise inflate the
    signal-band power.
    """
    af = np.abs(freqs)
    signal_mask = (af <= bands["signal_half_bw"]) & (af > dc_exclude)
    noise_mask = (af >= bands["guard_start"]) & (af <= bands["guard_end"])
    return signal_mask, noise_mask


def snr_from_window(complex_samples, samplerate, bands, dc_exclude, nperseg):
    """SNR estimate (dB) for a single window of complex baseband samples.

    Note this is strictly (S+N)/N, since the signal band also contains noise.
    At high SNR the difference is negligible; near the noise floor the estimate
    compresses. Validated against synthetic signals as reading consistently
    low by ~1.7 dB, which is treated as a fixed calibration offset.
    """
    freqs, psd = welch(
        complex_samples, fs=samplerate, nperseg=nperseg,
        return_onesided=False, scaling="density",
    )
    freqs = np.fft.fftshift(freqs)
    psd = np.fft.fftshift(psd)

    signal_mask, noise_mask = band_masks(freqs, bands, dc_exclude)
    if not signal_mask.any():
        raise ValueError("signal band mask selected no frequency bins")
    if not noise_mask.any():
        raise ValueError("noise band mask selected no frequency bins")

    signal_density = np.mean(psd[signal_mask])
    noise_density = np.mean(psd[noise_mask])
    if noise_density <= 0:
        raise ValueError("noise band power is non-positive")

    return float(10 * np.log10(signal_density / noise_density))


def iter_windows(fh, bytes_per_window):
    """Yield complete windows of raw bytes from a file handle.

    A trailing partial window is dropped: its differing length would give it
    different spectral statistics and produce one misleading final sample.
    """
    while True:
        raw = fh.read(bytes_per_window)
        if len(raw) < bytes_per_window:
            return
        yield raw


def analyse_file(path, samplerate, symbolrate, rolloff, window_s, dc_exclude,
                 guard_start=None, guard_end=None, max_nperseg=8192):
    """Stream an IQ file and return [(elapsed_seconds, snr_db), ...]."""
    bands = compute_bands(samplerate, symbolrate, rolloff, guard_start, guard_end)
    samples_per_window = int(samplerate * window_s)
    bytes_per_window = samples_per_window * BYTES_PER_COMPLEX_SAMPLE
    nperseg = min(max_nperseg, samples_per_window)

    results = []
    with open(path, "rb") as fh:
        for index, raw in enumerate(iter_windows(fh, bytes_per_window)):
            samples = deinterleave_cs16(raw)
            snr_db = snr_from_window(samples, samplerate, bands, dc_exclude, nperseg)
            results.append((index * window_s, snr_db))
    return results, bands


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description="Estimate SNR vs time from a raw cs16 IQ file.")
    p.add_argument("input_file", help="Path to raw cs16 IQ baseband file")
    p.add_argument("output_csv", help="Path to write the SNR-vs-time CSV")
    p.add_argument("--samplerate", type=float, default=160000.0,
                   help="Sample rate in Hz (default: 160000, the gr-satnogs decimated rate)")
    p.add_argument("--symbolrate", type=float, default=72000.0,
                   help="Symbol rate in baud (default: 72000, Meteor M2-x LRPT)")
    p.add_argument("--rolloff", type=float, default=0.5,
                   help="RRC roll-off factor alpha (default: 0.5)")
    p.add_argument("--window", type=float, default=1.0,
                   help="Analysis window duration in seconds (default: 1.0)")
    p.add_argument("--dc-exclude", type=float, default=1000.0,
                   help="Half-width in Hz excluded around DC (default: 1000)")
    p.add_argument("--guard-start", type=float, default=None,
                   help="Start of noise guard band, Hz from DC (default: signal edge + 5 kHz)")
    p.add_argument("--guard-end", type=float, default=None,
                   help="End of noise guard band, Hz from DC (default: 0.97 x Nyquist)")
    args = p.parse_args()

    results, bands = analyse_file(
        args.input_file, args.samplerate, args.symbolrate, args.rolloff,
        args.window, args.dc_exclude, args.guard_start, args.guard_end,
    )

    samples_per_window = int(args.samplerate * args.window)
    print(f"Sample rate        : {args.samplerate:.0f} Hz")
    print(f"Occupied bandwidth : {bands['occupied_bw']/1000:.1f} kHz "
          f"(+/-{bands['signal_half_bw']/1000:.1f} kHz)")
    print(f"DC exclusion       : +/-{args.dc_exclude/1000:.2f} kHz")
    print(f"Noise guard band   : {bands['guard_start']/1000:.1f}-"
          f"{bands['guard_end']/1000:.1f} kHz (each side)")
    print(f"Window duration    : {args.window:.2f} s ({samples_per_window} samples)")
    print()

    with open(args.output_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["elapsed_seconds", "snr_db"])
        writer.writerows([(round(t, 2), round(s, 3)) for t, s in results])

    print(f"Wrote {len(results)} samples to {args.output_csv}")
    if results:
        snrs = [s for _, s in results]
        print(f"SNR range: {min(snrs):.2f} dB to {max(snrs):.2f} dB, "
              f"mean {np.mean(snrs):.2f} dB")


if __name__ == "__main__":
    main()

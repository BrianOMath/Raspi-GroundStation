"""
Tests for the IQ SNR estimator (iq_snr_trace.py).

These pin the signal-processing assumptions that every SNR value in the
dataset depends on. The risk being guarded against is not crashes but
silently wrong numbers: a changed bandwidth mask or an inverted band
selection would still produce plausible-looking output while shifting
every measurement in the published analysis.
"""

import math

import numpy as np
import pytest

from iq_snr_trace import (
    BYTES_PER_COMPLEX_SAMPLE,
    band_masks,
    compute_bands,
    deinterleave_cs16,
    iter_windows,
    occupied_bandwidth,
    snr_from_window,
)


# ---------------------------------------------------------------------------
# Occupied bandwidth — the core signal assumption
# ---------------------------------------------------------------------------

def test_meteor_occupied_bandwidth_is_108khz():
    """Meteor M2-x LRPT: 72 kBaud OQPSK, RRC alpha 0.5 -> 108 kHz occupied.

    This is the figure the whole estimator is built around. If it changes,
    every SNR value in the dataset changes with it.
    """
    assert occupied_bandwidth(72000, 0.5) == 108000


def test_occupied_bandwidth_scales_with_rolloff():
    assert occupied_bandwidth(72000, 0.0) == 72000     # no excess bandwidth
    assert occupied_bandwidth(72000, 1.0) == 144000    # 100% excess


@pytest.mark.parametrize("rolloff", [-0.1, 1.1, 2.0])
def test_rolloff_outside_zero_to_one_rejected(rolloff):
    with pytest.raises(ValueError, match="rolloff"):
        occupied_bandwidth(72000, rolloff)


@pytest.mark.parametrize("symbolrate", [0, -1000])
def test_non_positive_symbolrate_rejected(symbolrate):
    with pytest.raises(ValueError, match="symbolrate"):
        occupied_bandwidth(symbolrate, 0.5)


# ---------------------------------------------------------------------------
# Band placement
# ---------------------------------------------------------------------------

def test_default_bands_match_operational_configuration():
    """The bands actually used on station 4621: 160 kSPS, 72 kBaud, alpha 0.5."""
    b = compute_bands(160000, 72000, 0.5)
    assert b["signal_half_bw"] == 54000
    assert b["guard_start"] == 59000            # signal edge + 5 kHz margin
    assert b["guard_end"] == pytest.approx(77600)  # 0.97 x Nyquist
    assert b["guard_start"] < b["guard_end"]


def test_guard_band_sits_entirely_outside_the_signal():
    b = compute_bands(160000, 72000, 0.5)
    assert b["guard_start"] > b["signal_half_bw"], "guard band must not overlap signal"


def test_empty_guard_band_raises_rather_than_silently_returning_nonsense():
    """If the sample rate is too low there is no noise-only region.

    Returning a value here would mean measuring the signal against itself.
    """
    with pytest.raises(ValueError, match="guard band is empty"):
        compute_bands(120000, 72000, 0.5)   # 108 kHz signal in 120 kHz -> no room


def test_explicit_guard_band_overrides_defaults():
    b = compute_bands(160000, 72000, 0.5, guard_start=60000, guard_end=70000)
    assert b["guard_start"] == 60000
    assert b["guard_end"] == 70000


# ---------------------------------------------------------------------------
# cs16 handling
# ---------------------------------------------------------------------------

def test_deinterleave_splits_i_and_q_correctly():
    raw = np.array([1, 2, 3, 4, 5, 6], dtype=np.int16).tobytes()
    out = deinterleave_cs16(raw)
    assert np.allclose(out.real, [1, 3, 5])
    assert np.allclose(out.imag, [2, 4, 6])


def test_odd_length_cs16_buffer_rejected():
    raw = np.array([1, 2, 3], dtype=np.int16).tobytes()
    with pytest.raises(ValueError, match="odd number"):
        deinterleave_cs16(raw)


def test_bytes_per_sample_constant_matches_cs16_format():
    """int16 I + int16 Q = 4 bytes. Windowing arithmetic depends on this."""
    assert BYTES_PER_COMPLEX_SAMPLE == 4


# ---------------------------------------------------------------------------
# Windowing
# ---------------------------------------------------------------------------

def test_trailing_partial_window_is_dropped(tmp_path):
    """A short final window has different spectral statistics and would
    produce one misleading sample at the end of every pass."""
    p = tmp_path / "iq.raw"
    p.write_bytes(b"\x00" * 250)          # 2.5 windows of 100 bytes
    with open(p, "rb") as fh:
        assert len(list(iter_windows(fh, 100))) == 2


def test_file_shorter_than_one_window_yields_nothing(tmp_path):
    p = tmp_path / "short.raw"
    p.write_bytes(b"\x00" * 50)
    with open(p, "rb") as fh:
        assert list(iter_windows(fh, 100)) == []


# ---------------------------------------------------------------------------
# Masks
# ---------------------------------------------------------------------------

def test_dc_spike_region_excluded_from_signal_band():
    """The RTL-SDR emits a hardware spur at exactly DC. Including it would
    inflate signal-band power on every window."""
    bands = compute_bands(160000, 72000, 0.5)
    freqs = np.linspace(-80000, 80000, 1601)
    signal_mask, _ = band_masks(freqs, bands, dc_exclude=1000)
    near_dc = np.abs(freqs) <= 1000
    assert not signal_mask[near_dc].any()


def test_masks_are_symmetric_about_dc():
    """Complex baseband: signal straddles DC, so both halves must contribute."""
    bands = compute_bands(160000, 72000, 0.5)
    freqs = np.linspace(-80000, 80000, 1601)
    signal_mask, noise_mask = band_masks(freqs, bands, dc_exclude=1000)
    for mask in (signal_mask, noise_mask):
        assert mask[freqs > 0].sum() == mask[freqs < 0].sum()


def test_signal_and_noise_masks_do_not_overlap():
    bands = compute_bands(160000, 72000, 0.5)
    freqs = np.linspace(-80000, 80000, 1601)
    signal_mask, noise_mask = band_masks(freqs, bands, dc_exclude=1000)
    assert not (signal_mask & noise_mask).any()


# ---------------------------------------------------------------------------
# End-to-end estimator behaviour against synthetic signals of known SNR
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# End-to-end estimator behaviour against synthetic signals of known SNR
#
# NOTE ON TEST SIGNAL CONSTRUCTION
# An earlier validation of this estimator used rectangular-pulse symbols
# (numpy.repeat of a symbol sequence). That produces sinc sidelobes which leak
# ~5% of signal power into the noise guard band, inflating the noise estimate
# and saturating the SNR reading above ~15 dB. The resulting apparent "constant
# negative offset" was an artefact of the test signal, not a property of the
# estimator. Real Meteor LRPT is RRC-shaped and properly band-limited.
#
# These tests therefore build the signal in the frequency domain with a hard
# band limit, giving zero out-of-band leakage by construction.
# ---------------------------------------------------------------------------

def _bandlimited_signal(true_snr_db, fs=160000.0, half_bw=52000.0,
                        n=160000, seed=0):
    """Signal strictly confined to +/-half_bw plus white noise, at a known
    in-band PSD ratio of true_snr_db."""
    rng = np.random.default_rng(seed)
    freqs = np.fft.fftfreq(n, d=1 / fs)
    spec = rng.standard_normal(n) + 1j * rng.standard_normal(n)
    spec[np.abs(freqs) > half_bw] = 0
    sig = np.fft.ifft(spec)
    sig /= np.std(sig)

    noise = rng.standard_normal(n) + 1j * rng.standard_normal(n)
    noise /= np.std(noise)

    occupied_fraction = (2 * half_bw) / fs
    signal_psd = 1.0 / occupied_fraction
    scale = math.sqrt(10 ** (true_snr_db / 10) / signal_psd)
    return sig * scale + noise


def _estimate(true_snr_db, seed=0):
    bands = compute_bands(160000, 72000, 0.5)
    samples = _bandlimited_signal(true_snr_db, seed=seed)
    return snr_from_window(samples, 160000.0, bands, dc_exclude=1000.0, nperseg=8192)


def _analytic_s_plus_n_over_n(true_snr_db):
    """What the estimator should report: it measures (S+N)/N, not S/N."""
    return 10 * math.log10(1 + 10 ** (true_snr_db / 10))


def test_estimator_is_monotonic_in_true_snr():
    """A stronger signal must never estimate lower. Catches sign errors and
    inverted masks, which a single-point check would miss."""
    estimates = [_estimate(snr) for snr in (0, 5, 10, 15, 20, 25)]
    assert estimates == sorted(estimates)


@pytest.mark.parametrize("true_snr_db", [0, 5, 10, 15, 20, 25])
def test_estimator_matches_s_plus_n_over_n_theory(true_snr_db):
    """The estimator compares mean PSD in the signal band against the noise
    band. The signal band contains signal *plus* noise, so the correct
    prediction is 10log10(1 + S/N), not S/N.

    This pins the estimator's known bias: it reads high at low SNR (about
    +3 dB at true 0 dB) and converges to the true value at high SNR. The bias
    is therefore NOT a constant offset, and analyses that assume one are
    approximating.
    """
    estimate = _estimate(true_snr_db)
    expected = _analytic_s_plus_n_over_n(true_snr_db)
    assert estimate == pytest.approx(expected, abs=0.5), (
        f"true {true_snr_db} dB -> estimate {estimate:.2f} dB, "
        f"theory predicts {expected:.2f} dB"
    )


def test_estimator_bias_is_not_constant():
    """Guards the specific misconception that a single fixed offset describes
    the estimator. The bias at 0 dB is several dB larger than at 20 dB.
    """
    bias_low = _estimate(0) - 0
    bias_high = _estimate(20) - 20
    assert bias_low - bias_high > 2.0, (
        f"bias at 0 dB ({bias_low:.2f}) should exceed bias at 20 dB "
        f"({bias_high:.2f}) by several dB"
    )


def test_estimator_does_not_saturate_at_high_snr():
    """Regression test for the rectangular-pulse artefact described above:
    a properly band-limited 25 dB signal must not read like an 8 dB one."""
    assert _estimate(25) > 20.0


def test_pure_noise_gives_snr_near_zero_db():
    """With no signal, signal-band and noise-band densities should match."""
    rng = np.random.default_rng(7)
    n = 160000
    noise = (rng.standard_normal(n) + 1j * rng.standard_normal(n)).astype(np.complex64)
    bands = compute_bands(160000, 72000, 0.5)
    snr = snr_from_window(noise, 160000.0, bands, dc_exclude=1000.0, nperseg=8192)
    assert abs(snr) < 1.0, f"flat noise should give ~0 dB, got {snr:.2f}"


def test_estimator_is_reproducible():
    """Same input must give the same answer — no hidden randomness."""
    assert _estimate(12, seed=3) == _estimate(12, seed=3)

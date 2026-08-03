"""
Integration tests: run the pipeline scripts end-to-end as subprocesses.

These cover the scripts that were not refactored for unit testing
(correlate_snr_elevation.py, enrich_master_dataset.py) by exercising their
command-line interfaces on fixture data, plus a full estimator -> correlator
chain on a synthetic recording.

Network access is never required: API-dependent paths are exercised via a
pre-seeded cache file.
"""

import csv
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parent.parent


def run(script, *args):
    """Run a repo script and return the completed process."""
    return subprocess.run(
        [sys.executable, str(REPO / script), *map(str, args)],
        capture_output=True, text=True,
    )


def write_iq(path, seconds=5, fs=160000, snr_db=15.0, seed=0):
    """Write a synthetic band-limited cs16 IQ recording."""
    rng = np.random.default_rng(seed)
    n = int(fs * seconds)
    freqs = np.fft.fftfreq(n, d=1 / fs)
    spec = rng.standard_normal(n) + 1j * rng.standard_normal(n)
    spec[np.abs(freqs) > 52000] = 0
    sig = np.fft.ifft(spec)
    sig /= np.std(sig)
    noise = rng.standard_normal(n) + 1j * rng.standard_normal(n)
    noise /= np.std(noise)
    scale = math.sqrt(10 ** (snr_db / 10) / (fs / 104000.0))
    iq = sig * scale + noise
    out = np.empty(2 * n, dtype=np.int16)
    out[0::2] = np.clip(iq.real * 3000, -32000, 32000).astype(np.int16)
    out[1::2] = np.clip(iq.imag * 3000, -32000, 32000).astype(np.int16)
    out.tofile(path)


# ---------------------------------------------------------------------------
# SNR estimator CLI
# ---------------------------------------------------------------------------

def test_snr_estimator_cli_produces_expected_csv(tmp_path):
    raw = tmp_path / "iq.raw"
    out = tmp_path / "snr.csv"
    write_iq(raw, seconds=5)

    proc = run("iq_snr_trace.py", raw, out)
    assert proc.returncode == 0, proc.stderr

    rows = list(csv.DictReader(out.open()))
    assert len(rows) == 5, "one row per whole second"
    assert list(rows[0]) == ["elapsed_seconds", "snr_db"]
    assert [float(r["elapsed_seconds"]) for r in rows] == [0, 1, 2, 3, 4]
    assert all(0 < float(r["snr_db"]) < 40 for r in rows)


def test_snr_estimator_reports_configured_bandwidth(tmp_path):
    raw = tmp_path / "iq.raw"
    write_iq(raw, seconds=2)
    proc = run("iq_snr_trace.py", raw, tmp_path / "o.csv")
    assert "108.0 kHz" in proc.stdout, "occupied bandwidth should be reported"


def test_snr_estimator_rejects_impossible_sample_rate(tmp_path):
    """108 kHz of signal cannot fit in 120 kHz with a noise guard band."""
    raw = tmp_path / "iq.raw"
    write_iq(raw, seconds=2)
    proc = run("iq_snr_trace.py", raw, tmp_path / "o.csv", "--samplerate", "120000")
    assert proc.returncode != 0
    assert "guard band is empty" in (proc.stderr + proc.stdout)


# ---------------------------------------------------------------------------
# Estimator -> correlator chain
# ---------------------------------------------------------------------------

TLE0 = "0 METEOR M2-4"
TLE1 = "1 59051U 24039A   26168.88685377  .00000010  00000-0  23925-4 0  9999"
TLE2 = "2 59051  98.7010 128.1761 0007332 159.0156 201.1324 14.22429617119366"


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("skyfield") is None,
    reason="skyfield not installed",
)
def test_geometry_regression_against_known_observation(tmp_path):
    """Regression against SatNOGS observation 14326791.

    SatNOGS independently reported max elevation 32.0 deg and rise/set azimuths
    of 47/142 deg for this pass. Our SGP4 propagation of the same TLE agreed to
    within 0.3 deg. If a library upgrade or a coordinate-handling change breaks
    propagation, this test catches it.
    """
    snr_csv = tmp_path / "snr.csv"
    with snr_csv.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["elapsed_seconds", "snr_db"])
        for t in range(0, 331):
            w.writerow([float(t), 10.0])

    out = tmp_path / "correlated.csv"
    proc = run("correlate_snr_elevation.py", snr_csv, out,
               "--tle0", TLE0, "--tle1", TLE1, "--tle2", TLE2,
               "--lat", 53.35, "--lon", -6.23, "--alt", 4,
               "--start", "2026-06-18T02:54:02Z")
    assert proc.returncode == 0, proc.stderr

    rows = list(csv.DictReader(out.open()))
    assert len(rows) == 331

    elevations = [float(r["elevation_deg"]) for r in rows]
    azimuths = [float(r["azimuth_deg"]) for r in rows]

    assert max(elevations) == pytest.approx(31.7, abs=0.3), "max elevation drifted"
    assert azimuths[0] == pytest.approx(46.7, abs=1.0), "rise azimuth drifted"
    assert azimuths[-1] == pytest.approx(141.2, abs=1.0), "set azimuth drifted"


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("skyfield") is None,
    reason="skyfield not installed",
)
def test_correlator_output_schema(tmp_path):
    """Column order matters: downstream readers index these positions.

    A dashboard bug once parsed column 1 (a timestamp string) where column 0
    (elapsed seconds) was meant, silently plotting the year 2026 as a time
    value. This pins the contract.
    """
    snr_csv = tmp_path / "snr.csv"
    with snr_csv.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["elapsed_seconds", "snr_db"])
        w.writerow([0.0, 12.0])

    out = tmp_path / "c.csv"
    run("correlate_snr_elevation.py", snr_csv, out,
        "--tle0", TLE0, "--tle1", TLE1, "--tle2", TLE2,
        "--lat", 53.35, "--lon", -6.23, "--alt", 4,
        "--start", "2026-06-18T02:54:02Z")

    header = out.open().readline().strip().split(",")
    assert header == ["elapsed_seconds", "utc_time", "elevation_deg",
                      "azimuth_deg", "snr_db"]


# ---------------------------------------------------------------------------
# Dataset enrichment
# ---------------------------------------------------------------------------

def _master_csv(path, rows):
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["obs_id", "elapsed_seconds", "utc_time",
                                           "elevation_deg", "azimuth_deg", "snr_db"])
        w.writeheader()
        w.writerows(rows)


def _seed_cache(outdir, entries):
    (outdir / ".obs_api_cache.json").write_text(json.dumps(entries))


def test_enrichment_separates_meteor_from_other_satellites(tmp_path):
    """The SNR estimator's mask is Meteor-specific; other satellites analysed
    with it return the noise floor and must not enter the analysis dataset."""
    master = tmp_path / "master.csv"
    _master_csv(master, [
        {"obs_id": "1", "elapsed_seconds": 0, "utc_time": "2026-07-20T10:00:00Z",
         "elevation_deg": 30.0, "azimuth_deg": 180, "snr_db": 15},
        {"obs_id": "2", "elapsed_seconds": 0, "utc_time": "2026-07-20T11:00:00Z",
         "elevation_deg": 40.0, "azimuth_deg": 180, "snr_db": 8},
    ])
    _seed_cache(tmp_path, {
        "1": {"norad_cat_id": 59051, "tle0": "0 METEOR M2-4",
              "transmitter_baud": 40000.0,
              "demoddata": [{"payload_demod": "data_1_MSU-MR-1.png"}]},
        "2": {"norad_cat_id": 98293, "tle0": "0 MARINA",
              "transmitter_baud": 9600.0, "demoddata": []},
    })

    proc = run("enrich_master_dataset.py", "--input", master, "--outdir", tmp_path)
    assert proc.returncode == 0, proc.stderr

    meteor = list(csv.DictReader((tmp_path / "all_passes_meteor.csv").open()))
    everything = list(csv.DictReader((tmp_path / "all_passes_enriched.csv").open()))

    assert len(everything) == 2
    assert len(meteor) == 1
    assert meteor[0]["satellite_name"] == "Meteor M2-4"
    assert meteor[0]["decoded"] == "1"


def test_enrichment_marks_undecoded_passes(tmp_path):
    master = tmp_path / "master.csv"
    _master_csv(master, [
        {"obs_id": "9", "elapsed_seconds": 0, "utc_time": "2026-07-20T10:00:00Z",
         "elevation_deg": 25.0, "azimuth_deg": 180, "snr_db": 9},
    ])
    _seed_cache(tmp_path, {
        "9": {"norad_cat_id": 57166, "tle0": "0 METEOR M2-3",
              "transmitter_baud": 40000.0, "demoddata": []},
    })
    run("enrich_master_dataset.py", "--input", master, "--outdir", tmp_path)
    rows = list(csv.DictReader((tmp_path / "all_passes_meteor.csv").open()))
    assert rows[0]["decoded"] == "0"


def test_enrichment_output_has_stable_column_order(tmp_path):
    master = tmp_path / "master.csv"
    _master_csv(master, [
        {"obs_id": "1", "elapsed_seconds": 0, "utc_time": "2026-07-20T10:00:00Z",
         "elevation_deg": 30.0, "azimuth_deg": 180, "snr_db": 15},
    ])
    _seed_cache(tmp_path, {
        "1": {"norad_cat_id": 59051, "tle0": "0 METEOR M2-4",
              "transmitter_baud": 40000.0, "demoddata": []},
    })
    run("enrich_master_dataset.py", "--input", master, "--outdir", tmp_path)
    header = (tmp_path / "all_passes_meteor.csv").open().readline().strip().split(",")
    assert header == ["obs_id", "satellite_norad", "satellite_name",
                      "transmitter_baud", "decoded", "in_scope",
                      "elapsed_seconds", "utc_time", "elevation_deg",
                      "azimuth_deg", "snr_db"]


# ---------------------------------------------------------------------------
# Verification CLI
# ---------------------------------------------------------------------------

def test_verification_cli_reports_cohorts(tmp_path):
    data = tmp_path / "meteor.csv"
    fields = ["obs_id", "satellite_norad", "satellite_name", "transmitter_baud",
              "decoded", "in_scope", "elapsed_seconds", "utc_time",
              "elevation_deg", "azimuth_deg", "snr_db"]
    with data.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for i in range(10):
            w.writerow({"obs_id": str(i), "satellite_norad": "59051",
                        "satellite_name": "Meteor M2-4", "transmitter_baud": "40000.0",
                        "decoded": "1" if i < 9 else "0", "in_scope": "1",
                        "elapsed_seconds": "0", "utc_time": "2026-07-20T10:00:00Z",
                        "elevation_deg": "35.0", "azimuth_deg": "180", "snr_db": "15"})

    proc = run("verify_decode_requirements.py", "--input", data)
    assert proc.returncode == 0, proc.stderr
    assert "REQ-P-01" in proc.stdout
    assert "9/10" in proc.stdout


def test_verification_cli_handles_empty_input(tmp_path):
    """An empty dataset must report nothing rather than crashing."""
    data = tmp_path / "empty.csv"
    data.write_text("obs_id,decoded,utc_time,elevation_deg,satellite_name\n")
    proc = run("verify_decode_requirements.py", "--input", data)
    assert proc.returncode == 0, proc.stderr
    assert "Passes in dataset : 0" in proc.stdout

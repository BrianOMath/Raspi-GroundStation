#!/usr/bin/env python3
"""
rebuild_master_dataset.py

Rebuilds the master SNR dataset from per-pass analysis records, adding the
metadata columns needed for filtering and for machine-learning work:

    satellite_norad, satellite_name, transmitter_baud, decoded

Why this exists
---------------
The original master CSV (`all_passes_snr_elevation.csv`) carries only
obs_id / time / geometry / SNR. That is insufficient because:

  1. The SNR estimator is Meteor-specific (72 kBaud OQPSK -> 108 kHz mask).
     Observations of other satellites scheduled on the station by other
     SatNOGS users are analysed with the wrong occupied-bandwidth mask and
     return the noise floor. Without a satellite ID they cannot be filtered.

  2. Decode success/failure is not recorded, so REQ-P-01 cannot be verified
     programmatically and no classification target exists for ML work.

Decode status is taken from the SatNOGS API rather than local files, because
`satdump_cleanup.sh` removes imagery after 3 days while the API retains the
demoddata list permanently.

Usage
-----
    # rebuild, querying the API for decode status (recommended)
    python3 rebuild_master_dataset.py --token "$SATNOGS_API_TOKEN"

    # rebuild offline from cached .obs_response.json only (no decode labels)
    python3 rebuild_master_dataset.py --no-api

Outputs
-------
    all_passes_enriched.csv      all passes, all satellites, with metadata
    all_passes_meteor.csv        Meteor M2-3 / M2-4 only  <- use this for analysis
    rebuild_report.txt           what was included, excluded, and why
"""

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict

OUTPUT_BASE = "/home/brian/satdump_output"
FOLDER_RE = re.compile(r"^iq_cs16_(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})$")

# NORAD IDs the SNR estimator is configured for (72 kBaud OQPSK LRPT)
METEOR_NORAD = {59051: "Meteor M2-4", 57166: "Meteor M2-3"}

API_OBS = "https://network.satnogs.org/api/observations/{}/"


def fetch_observation(obs_id, token, cache):
    """Fetch an observation record from the SatNOGS API, with on-disk caching."""
    if obs_id in cache:
        return cache[obs_id]
    req = urllib.request.Request(
        API_OBS.format(obs_id),
        headers={"User-Agent": "BRaspi-dataset-rebuild",
                 **({"Authorization": f"Token {token}"} if token else {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        cache[obs_id] = data
        time.sleep(0.3)          # be polite to the API
        return data
    except urllib.error.HTTPError as e:
        print(f"  ! obs {obs_id}: HTTP {e.code}", file=sys.stderr)
    except Exception as e:
        print(f"  ! obs {obs_id}: {e}", file=sys.stderr)
    cache[obs_id] = None
    return None


def decoded_from_api(obs):
    """True if the observation has at least one decoded MSU-MR image."""
    if not obs:
        return None
    demod = obs.get("demoddata") or []
    for d in demod:
        payload = (d.get("payload_demod") or "").lower()
        if "msu-mr" in payload or payload.endswith(".png"):
            return True
    return False


def read_local_metadata(folder_path):
    """Pull obs_id / NORAD / transmitter info from the cached API response."""
    p = os.path.join(folder_path, ".obs_response.json")
    if not os.path.isfile(p):
        return {}
    try:
        with open(p) as fh:
            d = json.load(fh)
        obs = d[0] if isinstance(d, list) and d else d
        if not isinstance(obs, dict):
            print(f"  ! {os.path.basename(folder_path)}: unexpected metadata structure",
                  file=sys.stderr)
            return {}
        return {
            "obs_id": obs.get("id"),
            "norad": obs.get("norad_cat_id"),
            "tle0": (obs.get("tle0") or "").lstrip("0 ").strip(),
            "baud": obs.get("transmitter_baud"),
            "freq": obs.get("observation_frequency"),
        }
    except Exception as e:
        print(f"  ! {os.path.basename(folder_path)}: could not read .obs_response.json ({e})",
              file=sys.stderr)
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=OUTPUT_BASE, help="SatDump output directory")
    ap.add_argument("--token", default=os.environ.get("SATNOGS_API_TOKEN", ""),
                    help="SatNOGS API token (or set SATNOGS_API_TOKEN)")
    ap.add_argument("--no-api", action="store_true",
                    help="Skip API queries; decode labels will be blank")
    ap.add_argument("--outdir", default=".", help="Where to write the output CSVs")
    args = ap.parse_args()

    if not os.path.isdir(args.base):
        sys.exit(f"Output base not found: {args.base}")

    cache_path = os.path.join(args.outdir, ".obs_api_cache.json")
    cache = {}
    if os.path.isfile(cache_path):
        try:
            cache = {int(k): v for k, v in json.load(open(cache_path)).items()}
        except Exception:
            cache = {}

    folders = sorted(f for f in os.listdir(args.base)
                     if FOLDER_RE.match(f) and
                     os.path.isfile(os.path.join(args.base, f, "pass_analysis.csv")))
    print(f"Found {len(folders)} pass folders with analysis data\n")

    fieldnames = ["obs_id", "satellite_norad", "satellite_name", "transmitter_baud",
                  "decoded", "elapsed_seconds", "utc_time", "elevation_deg",
                  "azimuth_deg", "snr_db"]

    all_rows, meteor_rows = [], []
    stats = defaultdict(int)
    per_sat = defaultdict(lambda: {"passes": 0, "rows": 0, "decoded": 0})
    excluded = []

    for folder in folders:
        fpath = os.path.join(args.base, folder)
        meta = read_local_metadata(fpath)
        obs_id = meta.get("obs_id")
        norad = meta.get("norad")

        decoded = None
        if obs_id and not args.no_api:
            obs = fetch_observation(obs_id, args.token, cache)
            decoded = decoded_from_api(obs)
            if obs:                       # prefer live values where available
                norad = obs.get("norad_cat_id", norad)
                meta["tle0"] = (obs.get("tle0") or meta.get("tle0") or "").lstrip("0 ").strip()
                meta["baud"] = obs.get("transmitter_baud", meta.get("baud"))

        sat_name = METEOR_NORAD.get(norad) or meta.get("tle0") or "unknown"
        is_meteor = norad in METEOR_NORAD

        with open(os.path.join(fpath, "pass_analysis.csv"), newline="") as fh:
            rows = list(csv.DictReader(fh))

        for r in rows:
            out = {
                "obs_id": obs_id if obs_id is not None else "",
                "satellite_norad": norad if norad is not None else "",
                "satellite_name": sat_name,
                "transmitter_baud": meta.get("baud") if meta.get("baud") is not None else "",
                "decoded": "" if decoded is None else int(bool(decoded)),
                "elapsed_seconds": r.get("elapsed_seconds", ""),
                "utc_time": r.get("utc_time", ""),
                "elevation_deg": r.get("elevation_deg", ""),
                "azimuth_deg": r.get("azimuth_deg", ""),
                "snr_db": r.get("snr_db", ""),
            }
            all_rows.append(out)
            if is_meteor:
                meteor_rows.append(out)

        key = sat_name
        per_sat[key]["passes"] += 1
        per_sat[key]["rows"] += len(rows)
        if decoded:
            per_sat[key]["decoded"] += 1

        stats["passes"] += 1
        stats["rows"] += len(rows)
        if is_meteor:
            stats["meteor_passes"] += 1
            stats["meteor_rows"] += len(rows)
        else:
            excluded.append((folder, obs_id, norad, sat_name, len(rows)))

    # write outputs
    for name, rows in (("all_passes_enriched.csv", all_rows),
                       ("all_passes_meteor.csv", meteor_rows)):
        path = os.path.join(args.outdir, name)
        with open(path, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(rows)
        print(f"Wrote {path}: {len(rows):,} rows")

    try:
        json.dump({str(k): v for k, v in cache.items()}, open(cache_path, "w"))
    except Exception:
        pass

    # report
    lines = []
    lines.append("Master dataset rebuild report")
    lines.append("=" * 60)
    lines.append(f"Pass folders processed : {stats['passes']}")
    lines.append(f"Total rows             : {stats['rows']:,}")
    lines.append(f"Meteor passes / rows   : {stats['meteor_passes']} / {stats['meteor_rows']:,}")
    lines.append(f"Excluded passes        : {len(excluded)}")
    lines.append("")
    lines.append("By satellite:")
    lines.append(f"  {'satellite':<22} {'passes':>7} {'rows':>9} {'decoded':>8}")
    for sat, s in sorted(per_sat.items(), key=lambda kv: -kv[1]["rows"]):
        lines.append(f"  {sat:<22} {s['passes']:>7} {s['rows']:>9,} {s['decoded']:>8}")
    if excluded:
        lines.append("")
        lines.append("Excluded (non-Meteor — SNR estimator mask does not apply):")
        for folder, oid, norad, name, n in excluded:
            lines.append(f"  {folder}  obs={oid}  norad={norad}  {name}  ({n} rows)")
        lines.append("")
        lines.append("Rationale: iq_snr_trace.py applies a 108 kHz occupied-bandwidth")
        lines.append("mask derived from Meteor's 72 kBaud OQPSK signal. Narrowband")
        lines.append("transmitters analysed with this mask integrate mostly noise and")
        lines.append("return the system noise floor; those SNR values are not valid")
        lines.append("measurements of those signals.")

    report = "\n".join(lines)
    with open(os.path.join(args.outdir, "rebuild_report.txt"), "w") as fh:
        fh.write(report + "\n")
    print()
    print(report)


if __name__ == "__main__":
    main()

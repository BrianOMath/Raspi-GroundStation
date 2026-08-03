#!/usr/bin/env python3
"""
enrich_master_dataset.py

Adds satellite/transmitter metadata and decode labels to the EXISTING master
SNR dataset, by looking up each obs_id against the SatNOGS API.

Use this instead of rebuild_master_dataset.py when the master CSV contains
more history than survives on disk as pass folders (pass folders may have been
pruned; the master CSV is the longer record).

Adds columns: satellite_norad, satellite_name, transmitter_baud, decoded, in_scope

Usage:
    SATNOGS_API_TOKEN=xxxx python3 enrich_master_dataset.py \
        --input  /home/brian/satdump_output/all_passes_snr_elevation.csv \
        --outdir /home/brian/analysis

Outputs:
    all_passes_enriched.csv   every pass, labelled
    all_passes_meteor.csv     Meteor M2-3 / M2-4 only  <- analysis input
    enrich_report.txt
"""

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict

METEOR_NORAD = {59051: "Meteor M2-4", 57166: "Meteor M2-3"}
API_OBS = "https://network.satnogs.org/api/observations/{}/"


def fetch(obs_id, token, cache):
    key = str(obs_id)
    if key in cache:
        return cache[key]
    headers = {"User-Agent": "BRaspi-dataset-enrich"}
    if token:
        headers["Authorization"] = f"Token {token}"
    try:
        with urllib.request.urlopen(
                urllib.request.Request(API_OBS.format(obs_id), headers=headers),
                timeout=30) as r:
            data = json.loads(r.read())
        cache[key] = data
        time.sleep(0.3)
        return data
    except urllib.error.HTTPError as e:
        print(f"  ! obs {obs_id}: HTTP {e.code}", file=sys.stderr)
    except Exception as e:
        print(f"  ! obs {obs_id}: {e}", file=sys.stderr)
    cache[key] = None
    return None


def decoded_from(obs):
    if not obs:
        return None
    for d in (obs.get("demoddata") or []):
        p = (d.get("payload_demod") or "").lower()
        if "msu-mr" in p or p.endswith(".png"):
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="existing master CSV")
    ap.add_argument("--outdir", default=".")
    ap.add_argument("--token", default=os.environ.get("SATNOGS_API_TOKEN", ""))
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    cache_path = os.path.join(args.outdir, ".obs_api_cache.json")
    cache = {}
    if os.path.isfile(cache_path):
        try:
            cache = json.load(open(cache_path))
        except Exception:
            cache = {}

    with open(args.input, newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        sys.exit("Input CSV is empty")

    obs_ids = sorted({r["obs_id"] for r in rows if r.get("obs_id")})
    print(f"Input: {len(rows):,} rows across {len(obs_ids)} observations")
    print(f"Looking up metadata (cached: {len(cache)})...\n")

    meta = {}
    for i, oid in enumerate(obs_ids, 1):
        obs = fetch(oid, args.token, cache)
        norad = obs.get("norad_cat_id") if obs else None
        name = METEOR_NORAD.get(norad) or ((obs.get("tle0") or "").lstrip("0 ").strip()
                                           if obs else "") or "unknown"
        meta[oid] = {
            "norad": norad if norad is not None else "",
            "name": name,
            "baud": (obs.get("transmitter_baud") if obs else None) or "",
            "decoded": decoded_from(obs),
            "in_scope": 1 if norad in METEOR_NORAD else 0,
        }
        if i % 25 == 0:
            print(f"  {i}/{len(obs_ids)}")

    json.dump(cache, open(cache_path, "w"))

    fieldnames = ["obs_id", "satellite_norad", "satellite_name", "transmitter_baud",
                  "decoded", "in_scope", "elapsed_seconds", "utc_time",
                  "elevation_deg", "azimuth_deg", "snr_db"]

    all_out, meteor_out = [], []
    per_sat = defaultdict(lambda: {"passes": set(), "rows": 0, "decoded": set()})

    for r in rows:
        m = meta.get(r.get("obs_id"), {"norad": "", "name": "unknown", "baud": "",
                                       "decoded": None, "in_scope": 0})
        out = {
            "obs_id": r.get("obs_id", ""),
            "satellite_norad": m["norad"],
            "satellite_name": m["name"],
            "transmitter_baud": m["baud"],
            "decoded": "" if m["decoded"] is None else int(bool(m["decoded"])),
            "in_scope": m["in_scope"],
            "elapsed_seconds": r.get("elapsed_seconds", ""),
            "utc_time": r.get("utc_time", ""),
            "elevation_deg": r.get("elevation_deg", ""),
            "azimuth_deg": r.get("azimuth_deg", ""),
            "snr_db": r.get("snr_db", ""),
        }
        all_out.append(out)
        if m["in_scope"]:
            meteor_out.append(out)
        s = per_sat[m["name"]]
        s["passes"].add(r.get("obs_id"))
        s["rows"] += 1
        if m["decoded"]:
            s["decoded"].add(r.get("obs_id"))

    for name, data in (("all_passes_enriched.csv", all_out),
                       ("all_passes_meteor.csv", meteor_out)):
        p = os.path.join(args.outdir, name)
        with open(p, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(data)
        print(f"\nWrote {p}: {len(data):,} rows")

    lines = ["Master dataset enrichment report", "=" * 60,
             f"Input rows        : {len(rows):,}",
             f"Observations      : {len(obs_ids)}",
             f"Meteor rows kept  : {len(meteor_out):,}", "",
             f"  {'satellite':<22} {'passes':>7} {'rows':>9} {'decoded':>8}"]
    for sat, s in sorted(per_sat.items(), key=lambda kv: -kv[1]["rows"]):
        lines.append(f"  {sat:<22} {len(s['passes']):>7} {s['rows']:>9,} {len(s['decoded']):>8}")

    report = "\n".join(lines)
    open(os.path.join(args.outdir, "enrich_report.txt"), "w").write(report + "\n")
    print("\n" + report)


if __name__ == "__main__":
    main()

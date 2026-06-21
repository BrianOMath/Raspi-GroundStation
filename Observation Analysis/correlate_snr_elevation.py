#!/usr/bin/env python3
"""
correlate_snr_elevation.py

Computes satellite elevation/azimuth at each timestamp in an SNR CSV
(produced by iq_snr_trace.py) using a TLE and ground station location,
and writes an enriched CSV with elevation_deg and azimuth_deg columns
added alongside the original snr_db column.

Usage:
    python3 correlate_snr_elevation.py <snr_csv> <output_csv> \
        --tle0 "0 METEOR M2-4" \
        --tle1 "1 59051U 24039A   26168.88685377  .00000010  00000-0  23925-4 0  9999" \
        --tle2 "2 59051  98.7010 128.1761 0007332 159.0156 201.1324 14.22429617119366" \
        --lat 53.35 --lon -6.23 --alt 4 \
        --start "2026-06-18T02:54:02Z"

The --start value should be the UTC timestamp corresponding to elapsed_seconds=0
in the SNR CSV. For IQ files from this pipeline, that's the timestamp embedded
in the IQ filename (iq_cs16_<timestamp>.raw) -- the moment gr-satnogs began
writing the recording, NOT the official SatNOGS observation start time (these
are typically 1-3 seconds apart).
"""

import argparse
import csv
from datetime import datetime, timedelta, timezone

from skyfield.api import EarthSatellite, wgs84, load


def parse_iso_utc(s):
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).astimezone(timezone.utc)


def main():
    p = argparse.ArgumentParser(description="Correlate an SNR-vs-time CSV with elevation/azimuth from a TLE.")
    p.add_argument("input_csv", help="SNR CSV from iq_snr_trace.py (elapsed_seconds, snr_db)")
    p.add_argument("output_csv", help="Output CSV with elevation_deg, azimuth_deg appended")
    p.add_argument("--tle0", required=True, help="TLE line 0 (satellite name)")
    p.add_argument("--tle1", required=True, help="TLE line 1")
    p.add_argument("--tle2", required=True, help="TLE line 2")
    p.add_argument("--lat", type=float, required=True, help="Station latitude, degrees")
    p.add_argument("--lon", type=float, required=True, help="Station longitude, degrees")
    p.add_argument("--alt", type=float, default=0.0, help="Station altitude, metres (default: 0)")
    p.add_argument("--start", required=True,
                    help="UTC timestamp corresponding to elapsed_seconds=0, ISO format (e.g. 2026-06-18T02:54:02Z)")
    args = p.parse_args()

    ts = load.timescale(builtin=True)
    satellite = EarthSatellite(args.tle1, args.tle2, args.tle0, ts)
    station = wgs84.latlon(args.lat, args.lon, elevation_m=args.alt)

    start_dt = parse_iso_utc(args.start)

    print(f"Satellite : {satellite.name}")
    print(f"TLE epoch : {satellite.epoch.utc_strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"Station   : {args.lat:.4f}, {args.lon:.4f}, {args.alt:.0f} m")
    print(f"t=0 at    : {start_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print()

    rows = []
    with open(args.input_csv, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            elapsed = float(row["elapsed_seconds"])
            snr_db = float(row["snr_db"])
            t_dt = start_dt + timedelta(seconds=elapsed)
            t = ts.from_datetime(t_dt)

            difference = satellite - station
            topocentric = difference.at(t)
            alt, az, distance = topocentric.altaz()

            rows.append({
                "elapsed_seconds": elapsed,
                "utc_time": t_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "elevation_deg": round(alt.degrees, 3),
                "azimuth_deg": round(az.degrees, 3),
                "snr_db": snr_db,
            })

    with open(args.output_csv, "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["elapsed_seconds", "utc_time", "elevation_deg", "azimuth_deg", "snr_db"]
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {args.output_csv}")
    if rows:
        max_el_row = max(rows, key=lambda r: r["elevation_deg"])
        print(f"Max elevation in trace : {max_el_row['elevation_deg']:.1f} deg "
              f"at t={max_el_row['elapsed_seconds']:.0f}s")
        print(f"First point            : el {rows[0]['elevation_deg']:.1f} deg, "
              f"az {rows[0]['azimuth_deg']:.1f} deg")
        print(f"Last point             : el {rows[-1]['elevation_deg']:.1f} deg, "
              f"az {rows[-1]['azimuth_deg']:.1f} deg")


if __name__ == "__main__":
    main()

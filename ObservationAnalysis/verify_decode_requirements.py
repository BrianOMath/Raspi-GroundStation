#!/usr/bin/env python3
"""
verify_decode_requirements.py

Computes decode success rate by elevation cohort from the enriched master
dataset, providing programmatic verification evidence for:

    REQ-P-01  : >= 80% of passes with max elevation >= 20 deg yield decoded imagery
    REQ-P-01b : >= 90% of passes with max elevation >= 30 deg yield decoded imagery

Replaces the manual observation tally with a reproducible calculation.

Structure: the statistical and aggregation logic is separated from file and CLI
handling so it can be unit tested. See tests/test_decode_verification.py.

Definitions
-----------
Max elevation is taken as the maximum elevation in the pass's own SNR trace,
cross-checked against SatNOGS-reported max elevation to within 0.3 deg on a
sample observation.

"Decoded" is taken from the SatNOGS API demoddata list -- i.e. the pass produced
imagery that reached the network. A pass that decoded locally but failed to
upload counts as a failure, consistent with the requirement testing end-to-end
unattended operation.

Known limitation
----------------
The population is passes present in the analysis dataset. A pass whose analysis
also failed (e.g. TLE fetch during a network outage) leaves no record and is
therefore invisible here. Because such absences correlate with failure, rates
computed from this dataset are slight over-estimates. The unbiased population is
the SatNOGS observation list for the station over the period.

Usage:
    python3 verify_decode_requirements.py --input all_passes_meteor.csv
    python3 verify_decode_requirements.py --input all_passes_meteor.csv \
        --from 2026-07-12 --to 2026-07-24
"""

import argparse
import csv
import math
from collections import defaultdict


# ---------------------------------------------------------------------------
# Statistics -- pure functions
# ---------------------------------------------------------------------------

def wilson_interval(k, n, z=1.96):
    """Wilson score interval for a binomial proportion.

    Preferred over the normal approximation at small n or proportions near
    0 or 1, where the normal interval can extend outside [0, 1].
    """
    if n <= 0:
        return (0.0, 0.0)
    if k < 0 or k > n:
        raise ValueError(f"k must be in [0, n]; got k={k}, n={n}")
    p = k / n
    d = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / d
    half = (z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))) / d
    return (max(0.0, centre - half), min(1.0, centre + half))


def rule_of_three(n):
    """95% lower confidence bound on success rate given zero failures in n trials."""
    if n <= 0:
        return 0.0
    return 1.0 - 3.0 / n


# ---------------------------------------------------------------------------
# Aggregation -- pure functions over parsed rows
# ---------------------------------------------------------------------------

def parse_decoded(value):
    """Interpret the CSV 'decoded' field. Returns True, False, or None (unknown)."""
    if value in ("1", 1, True):
        return True
    if value in ("0", 0, False):
        return False
    return None


def aggregate_passes(rows, date_from=None, date_to=None):
    """Collapse per-sample rows into one record per observation.

    Returns {obs_id: {"max_el": float, "decoded": bool|None, "sat": str, "date": str}}
    Rows outside the date range, or with unparseable elevation, are skipped.
    """
    passes = {}
    for r in rows:
        oid = r.get("obs_id")
        if not oid:
            continue
        date = (r.get("utc_time") or "")[:10]
        if date_from and date < date_from:
            continue
        if date_to and date > date_to:
            continue
        try:
            el = float(r["elevation_deg"])
        except (ValueError, KeyError, TypeError):
            continue

        p = passes.get(oid)
        if p is None:
            p = passes[oid] = {"max_el": el, "decoded": None,
                               "sat": r.get("satellite_name", ""), "date": date}
        else:
            p["max_el"] = max(p["max_el"], el)

        decoded = parse_decoded(r.get("decoded", ""))
        if decoded is not None:
            p["decoded"] = decoded
    return passes


def cohort(passes, predicate):
    """Successes and total for passes matching an elevation predicate.

    Passes with an unknown decode status are excluded from both counts: they
    are not evidence either way, and counting them as failures would bias
    the result.
    """
    sel = [v for v in passes.values()
           if v["decoded"] is not None and predicate(v["max_el"])]
    n = len(sel)
    k = sum(1 for v in sel if v["decoded"])
    return k, n


def evaluate(k, n, requirement=None):
    """Summarise a cohort: rate, confidence interval, verdict against a requirement."""
    if n == 0:
        return {"k": 0, "n": 0, "rate": None, "ci": (0.0, 0.0),
                "verdict": None, "spans_requirement": False}
    rate = k / n
    lo, hi = wilson_interval(k, n)
    verdict = None
    spans = False
    if requirement is not None:
        verdict = "PASS" if rate >= requirement else "FAIL"
        spans = lo <= requirement <= hi
    return {"k": k, "n": n, "rate": rate, "ci": (lo, hi),
            "verdict": verdict, "spans_requirement": spans}


def normalise_satellite(name):
    """Normalise satellite names for grouping.

    SatNOGS TLE names vary in case over time (e.g. 'MARINA' and 'Marina' for
    the same object), so grouping on the raw string would split one satellite
    into several. NORAD ID remains the authoritative key; this is for display.
    """
    return (name or "").strip().title()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

COHORTS = [
    ("All elevations", lambda e: True, None),
    ("  >= 20 deg  (REQ-P-01)", lambda e: e >= 20, 0.80),
    ("  >= 30 deg  (REQ-P-01b)", lambda e: e >= 30, 0.90),
    ("  20-30 deg  (transition)", lambda e: 20 <= e < 30, None),
    ("  < 20 deg", lambda e: e < 20, None),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--from", dest="date_from", default=None, help="YYYY-MM-DD inclusive")
    ap.add_argument("--to", dest="date_to", default=None, help="YYYY-MM-DD inclusive")
    args = ap.parse_args()

    with open(args.input, newline="") as fh:
        rows = list(csv.DictReader(fh))

    passes = aggregate_passes(rows, args.date_from, args.date_to)
    known = {k: v for k, v in passes.items() if v["decoded"] is not None}
    unknown = len(passes) - len(known)

    period = (f"{min(v['date'] for v in passes.values())} to "
              f"{max(v['date'] for v in passes.values())}") if passes else "n/a"

    print("Decode requirement verification")
    print("=" * 62)
    print(f"Period            : {period}")
    print(f"Passes in dataset : {len(passes)}")
    if unknown:
        print(f"  (excluded, no decode label available: {unknown})")
    print()

    for name, predicate, requirement in COHORTS:
        k, n = cohort(passes, predicate)
        res = evaluate(k, n, requirement)
        if n == 0:
            print(f"{name:<26} no passes")
            continue
        lo, hi = res["ci"]
        line = (f"{name:<26} {k:>4}/{n:<4} = {res['rate']*100:5.1f}%   "
                f"95% CI [{lo*100:4.1f}, {hi*100:5.1f}]")
        if requirement is not None:
            line += f"   vs >={requirement*100:.0f}%: {res['verdict']}"
            if res["spans_requirement"]:
                line += "  (CI spans requirement -- not statistically distinguishable)"
        print(line)
        if k == n:
            print(f"{'':26} zero failures in {n} -- 95% lower bound "
                  f"{rule_of_three(n)*100:.1f}% (rule of three)")

    print()
    print("Breakdown of the >= 20 deg cohort by satellite:")
    bysat = defaultdict(lambda: [0, 0])
    for v in passes.values():
        if v["decoded"] is not None and v["max_el"] >= 20:
            name = normalise_satellite(v["sat"])
            bysat[name][1] += 1
            if v["decoded"]:
                bysat[name][0] += 1
    for sat, (k, n) in sorted(bysat.items()):
        print(f"  {sat:<20} {k:>4}/{n:<4} = {k/n*100:5.1f}%")

    fails = sorted((v["max_el"], oid, v["sat"], v["date"])
                   for oid, v in passes.items()
                   if v["decoded"] is False and v["max_el"] >= 20)
    if fails:
        print()
        print(f"Failed passes with max elevation >= 20 deg ({len(fails)}):")
        for el, oid, sat, date in fails:
            print(f"  obs {oid}  {date}  {sat:<14} max_el {el:5.1f}")


if __name__ == "__main__":
    main()

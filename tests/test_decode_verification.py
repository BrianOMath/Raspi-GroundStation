"""
Tests for the decode-requirement verification logic
(verify_decode_requirements.py).

These guard the calculation that decides whether REQ-P-01 and REQ-P-01b are
recorded as passed or failed in the verification matrix. Errors here would put
wrong verdicts into an engineering document, so the boundary conditions and
exclusion rules are pinned explicitly.
"""

import pytest

from verify_decode_requirements import (
    aggregate_passes,
    cohort,
    evaluate,
    normalise_satellite,
    parse_decoded,
    rule_of_three,
    wilson_interval,
)


def row(obs_id, elevation, decoded="1", date="2026-07-20", sat="Meteor M2-4"):
    """One CSV row as DictReader would produce it — all values are strings."""
    return {
        "obs_id": str(obs_id),
        "satellite_name": sat,
        "decoded": decoded,
        "elapsed_seconds": "0",
        "utc_time": f"{date}T10:00:00Z",
        "elevation_deg": str(elevation),
        "azimuth_deg": "180.0",
        "snr_db": "12.0",
    }


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def test_wilson_interval_brackets_the_point_estimate():
    lo, hi = wilson_interval(48, 61)
    assert lo < 48 / 61 < hi


def test_wilson_interval_matches_published_value():
    """Reference: k=48, n=61 gives approximately [66.9%, 87.1%] at 95%.
    Cross-checked against the standard Wilson score formula."""
    lo, hi = wilson_interval(48, 61)
    assert lo == pytest.approx(0.669, abs=0.005)
    assert hi == pytest.approx(0.871, abs=0.005)


def test_wilson_interval_stays_inside_zero_to_one_at_extremes():
    """The normal approximation would run outside [0, 1] here; Wilson must not."""
    lo, hi = wilson_interval(41, 41)
    assert 0.0 <= lo <= 1.0 and 0.0 <= hi <= 1.0
    assert hi == pytest.approx(1.0, abs=0.01)
    lo, hi = wilson_interval(0, 20)
    assert lo == pytest.approx(0.0, abs=0.01)


def test_wilson_interval_of_empty_sample_is_degenerate():
    assert wilson_interval(0, 0) == (0.0, 0.0)


def test_wilson_interval_rejects_impossible_counts():
    with pytest.raises(ValueError):
        wilson_interval(10, 5)


def test_wilson_interval_narrows_with_sample_size():
    """Same proportion, more data — the interval must tighten."""
    narrow = wilson_interval(80, 100)
    wide = wilson_interval(8, 10)
    assert (narrow[1] - narrow[0]) < (wide[1] - wide[0])


def test_rule_of_three_for_zero_failures():
    """41 successes, no failures -> 95% lower bound of about 92.7%."""
    assert rule_of_three(41) == pytest.approx(0.927, abs=0.001)


def test_rule_of_three_on_empty_sample():
    assert rule_of_three(0) == 0.0


# ---------------------------------------------------------------------------
# Decode flag parsing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("1", True), (1, True), (True, True),
    ("0", False), (0, False), (False, False),
    ("", None), (None, None), ("unknown", None), ("yes", None),
])
def test_decode_flag_parsing(value, expected):
    assert parse_decoded(value) is expected


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def test_max_elevation_taken_across_all_samples_in_a_pass():
    rows = [row(1, 10.0), row(1, 35.5), row(1, 22.0)]
    passes = aggregate_passes(rows)
    assert passes["1"]["max_el"] == 35.5


def test_each_observation_becomes_one_record():
    rows = [row(1, 30), row(1, 31), row(2, 40), row(2, 41)]
    assert len(aggregate_passes(rows)) == 2


def test_rows_without_obs_id_are_skipped():
    rows = [row(1, 30), {**row(2, 40), "obs_id": ""}]
    assert list(aggregate_passes(rows)) == ["1"]


def test_unparseable_elevation_is_skipped_not_fatal():
    rows = [row(1, 30), {**row(1, 0), "elevation_deg": "not-a-number"}]
    passes = aggregate_passes(rows)
    assert passes["1"]["max_el"] == 30


def test_date_filter_is_inclusive_at_both_ends():
    rows = [row(1, 30, date="2026-07-11"),
            row(2, 30, date="2026-07-12"),
            row(3, 30, date="2026-07-24"),
            row(4, 30, date="2026-07-25")]
    passes = aggregate_passes(rows, date_from="2026-07-12", date_to="2026-07-24")
    assert sorted(passes) == ["2", "3"]


# ---------------------------------------------------------------------------
# Cohort boundaries — these decide requirement verdicts
# ---------------------------------------------------------------------------

def test_pass_at_exactly_twenty_degrees_is_inside_the_requirement_cohort():
    """REQ-P-01 says '>= 20 deg'. A pass at exactly 20.0 must count."""
    passes = aggregate_passes([row(1, 20.0)])
    k, n = cohort(passes, lambda e: e >= 20)
    assert (k, n) == (1, 1)


def test_pass_at_exactly_thirty_degrees_is_inside_the_higher_cohort():
    passes = aggregate_passes([row(1, 30.0)])
    k, n = cohort(passes, lambda e: e >= 30)
    assert (k, n) == (1, 1)


def test_transition_band_excludes_thirty_degrees():
    """The 20-30 band is half-open: a 30.0 deg pass belongs to the >=30 cohort
    only, or it would be counted twice."""
    passes = aggregate_passes([row(1, 30.0)])
    k, n = cohort(passes, lambda e: 20 <= e < 30)
    assert n == 0


def test_passes_with_unknown_decode_status_are_excluded_from_both_counts():
    """A pass with no decode label is not evidence either way. Counting it as
    a failure would understate the success rate."""
    rows = [row(1, 30, decoded="1"), row(2, 30, decoded=""), row(3, 30, decoded="0")]
    passes = aggregate_passes(rows)
    k, n = cohort(passes, lambda e: e >= 20)
    assert (k, n) == (1, 2), "the unlabelled pass must not appear in either count"


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------

def test_verdict_passes_when_rate_meets_requirement_exactly():
    """80/100 against a >=80% requirement is a pass, not a fail."""
    assert evaluate(80, 100, 0.80)["verdict"] == "PASS"


def test_verdict_fails_just_below_requirement():
    assert evaluate(79, 100, 0.80)["verdict"] == "FAIL"


def test_marginal_result_is_flagged_as_spanning_the_requirement():
    """48/61 = 78.7% with CI [66.9, 87.1] fails on the point estimate but the
    interval contains 80%, so the result is not statistically distinguishable
    from the requirement. The matrix must say so rather than reporting a bare
    FAIL."""
    res = evaluate(48, 61, 0.80)
    assert res["verdict"] == "FAIL"
    assert res["spans_requirement"] is True


def test_clearly_passing_result_is_not_flagged_as_marginal():
    res = evaluate(98, 100, 0.80)
    assert res["verdict"] == "PASS"
    assert res["spans_requirement"] is False


def test_empty_cohort_produces_no_verdict():
    res = evaluate(0, 0, 0.80)
    assert res["rate"] is None and res["verdict"] is None


# ---------------------------------------------------------------------------
# Satellite name handling
# ---------------------------------------------------------------------------

def test_satellite_name_case_variants_group_together():
    """SatNOGS TLE names change case over time — 'MARINA' and 'Marina' are the
    same object. Grouping on the raw string would split one satellite in two.
    """
    assert normalise_satellite("MARINA") == normalise_satellite("Marina")
    assert normalise_satellite("  meteor m2-4 ") == normalise_satellite("METEOR M2-4")


def test_satellite_name_handles_missing_value():
    assert normalise_satellite(None) == ""
    assert normalise_satellite("") == ""


# ---------------------------------------------------------------------------
# Realistic end-to-end scenario
# ---------------------------------------------------------------------------

def test_known_cohort_scenario_reproduces_expected_counts():
    """Mirrors the hand-counted July verification: 41 passes above 30 deg all
    decoding, 20 passes in the 20-30 band of which 7 decode."""
    rows = []
    for i in range(41):
        rows.append(row(1000 + i, 30 + i * 0.5, decoded="1"))
    for i in range(7):
        rows.append(row(2000 + i, 22 + i * 0.5, decoded="1"))
    for i in range(13):
        rows.append(row(3000 + i, 21 + i * 0.5, decoded="0"))

    passes = aggregate_passes(rows)
    assert cohort(passes, lambda e: e >= 30) == (41, 41)
    assert cohort(passes, lambda e: 20 <= e < 30) == (7, 20)
    assert cohort(passes, lambda e: e >= 20) == (48, 61)

    res = evaluate(*cohort(passes, lambda e: e >= 20), 0.80)
    assert res["rate"] == pytest.approx(0.787, abs=0.001)

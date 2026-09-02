"""Metrics against the numbers the fixture documents.

These are pinned to `fixtures/README.md`. If the fixture is regenerated with a
different profile the expected values change — but they should change *deliberately*,
and a silent drift in a scorecard number is exactly what this catches.
"""

from __future__ import annotations

import pytest

from dq_app.domain import metrics
from dq_app.domain.lifecycle import derive_cohort_current


@pytest.fixture(scope="module")
def current(cohorts, dispositions):
    return derive_cohort_current(cohorts, dispositions)


def test_compression_matches_the_documented_ratio(current, check_runs, cohorts):
    m = metrics.cohort_compression(check_runs, cohorts)
    assert m.numerator == 21 and m.denominator == 6
    assert m.value == pytest.approx(3.5)
    # Documented as below target and deliberately not tuned to clear it.
    assert m.met is False
    assert m.footnote


def test_disposition_coverage(current, dispositions):
    m = metrics.disposition_coverage(current, dispositions)
    assert (m.numerator, m.denominator) == (13, 14)
    assert m.value == pytest.approx(92.857, rel=1e-3)
    assert m.met is True


def test_recommendation_acceptance(current):
    m = metrics.recommendation_acceptance(current)
    assert (m.numerator, m.denominator) == (9, 10)
    assert m.met is True


def test_closure_rate_counts_only_verified_closes(current):
    m = metrics.closure_rate(current)
    assert (m.numerator, m.denominator) == (9, 14)
    assert m.value == pytest.approx(64.29, rel=1e-3)
    assert m.met is False  # six cohorts still open — what an in-flight queue looks like


def test_rejected_and_deferred_do_not_count_as_closures(current):
    """Rolling them in would let the queue be emptied by dismissing it."""
    closed = metrics.closure_rate(current).numerator
    parked = int(current["lifecycle_state"].isin(["closed_rejected", "deferred"]).sum())
    assert parked > 0
    assert closed == int((current["lifecycle_state"] == "closed_verified").sum())


def test_mttr_is_measured_over_closed_cohorts_only(current):
    m = metrics.mttr(current)
    assert m.value == pytest.approx(5.4, abs=0.15)
    # The denominator has to stay visible: nine closed out of fourteen raised.
    assert m.numerator == 9 and m.denominator == 14


def test_recurrence_is_present_and_within_target(current):
    m = metrics.recurrence(current)
    assert m.numerator == 1
    assert m.met is True


def test_precision_is_reported_as_uninstrumented_not_invented():
    m = metrics.cohort_precision()
    assert m.value is None and m.met is None
    assert "not instrumented" in m.display


def test_funnel_is_cumulative(current):
    f = metrics.triage_funnel(current).set_index("stage")["cohorts"]
    assert f["01 recommended"] >= f["02 reviewed"] >= f["03 approved"]
    assert f["03 approved"] >= f["04 executed (claimed)"]
    assert f["— closed verified"] <= f["05 verification attempted"]


def test_every_scorecard_metric_carries_a_target(current, dispositions, check_runs, cohorts):
    card = metrics.scorecard(current, dispositions, check_runs, cohorts)
    for group in card.values():
        for m in group:
            assert m.target, f"{m.key} has no target"
            assert m.help or m.footnote, f"{m.key} has no explanation"


# --- Detection: the data-quality band ---------------------------------------


def test_detection_summary_measures_the_latest_run_only(check_runs):
    """Not a window average. A defect four days old would be understated sevenfold
    by a 30-day mean, which is the opposite of what a monitoring page is for."""
    d = metrics.detection_summary(check_runs)
    latest = check_runs[check_runs["run_id"] == d["run_id"]]

    assert d["run_ts"] == check_runs["run_ts"].max()
    assert d["rules_run"] == len(latest)
    assert d["rules_passing"] + d["rules_breaching"] <= d["rules_run"]
    # The fixture's headline: 21 rules breaching on the final run.
    assert d["rules_breaching"] == 21
    assert d["p1_breaching"] > 0


def test_violations_are_rule_row_pairs_not_distinct_rows(check_runs):
    """The email defect trips six rules on the same 240 contacts, so the violation
    total necessarily exceeds the number of distinct bad rows. The label has to say so."""
    d = metrics.detection_summary(check_runs)
    assert d["violations"] <= d["rules_breaching"] * d["rows_scanned"]
    assert d["violations"] > 0


def test_rows_scanned_does_not_double_count_tables(check_runs):
    """Summing rows_scanned across rules multiplies each table by its rule count.
    Taking the max per table is the only figure that means anything."""
    d = metrics.detection_summary(check_runs)
    latest = check_runs[check_runs["run_id"] == d["run_id"]]
    assert d["rows_scanned"] < latest["rows_scanned"].sum()
    assert d["rows_scanned"] == latest.groupby("target_table")["rows_scanned"].max().sum()


def test_quality_by_table_covers_every_table_in_the_run(check_runs):
    q = metrics.quality_by(check_runs, "target_table")
    d = metrics.detection_summary(check_runs)
    assert len(q) == d["tables"]
    assert q["Breaching"].sum() == d["rules_breaching"]
    assert q["Pass rate"].between(0, 100).all()


def test_worst_rules_are_ordered_and_all_breaching(check_runs):
    w = metrics.worst_rules(check_runs, limit=6)
    assert len(w) == 6
    assert w["Violations"].is_monotonic_decreasing
    assert (w["Violations"] > 0).all()


def test_shadow_rules_are_excluded_from_the_pass_rate(check_runs):
    """A shadow rule runs and records a count but does not raise. Counting it as a
    failure would make promoting a rule look like a regression."""
    d = metrics.detection_summary(check_runs)
    assert d["rules_skipped"] == 2, "fixture no longer carries its two shadow rules"
    assert d["rules_raised"] == d["rules_run"] - d["rules_skipped"]
    assert d["rules_passing"] + d["rules_breaching"] == d["rules_raised"]
    assert d["pass_rate"] == pytest.approx(100 * d["rules_passing"] / d["rules_raised"])


def test_quality_by_table_also_excludes_shadow_rules(check_runs):
    q = metrics.quality_by(check_runs, "target_table")
    d = metrics.detection_summary(check_runs)
    assert q["Rules"].sum() == d["rules_raised"]


def test_every_rule_domain_is_visible_not_just_cohort_domains(check_runs, cohorts):
    """The scorecard's domain filter is the union of both. A domain carrying rules but
    no cohorts is precisely what a monitoring page must not hide — the fixture has one
    (Billing), and it passes, so filtering it out would flatter the pass rate."""
    rule_domains = set(check_runs["business_domain"].dropna())
    cohort_domains = set(cohorts["business_domain"].dropna())
    assert rule_domains - cohort_domains, "fixture no longer exercises this case"

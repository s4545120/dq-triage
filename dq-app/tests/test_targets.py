"""Targets — what the scorecard measures a score against.

Three definitions live in `domain/targets.py` and each is pinned here: an element's
target is the complement of the tolerance the register declares, the headline's is
those targets weighted by the rows the score is weighted by, and a score is read
against its target only where the register's own coverage finding lets it be.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from dq_app.domain import coverage, targets

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "out"


def _run(rows: list[tuple]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["rule_id", "status", "rows_scanned"])


def test_an_element_target_is_the_complement_of_its_tolerance():
    reg = pd.DataFrame({"cde_id": ["A", "B", "C"], "tolerance_pct": [0.0, 0.5, None]})
    assert targets.element_targets(reg) == {"A": 100.0, "B": 99.5, "C": None}


def test_a_registry_without_the_column_has_no_targets():
    """The workspace until `migrate_cde_scope.sql` runs. The page must render with
    no targets rather than assume a hundred, so this returns nothing and not zeros."""
    assert targets.element_targets(pd.DataFrame({"cde_id": ["A"]})) == {}
    assert targets.element_targets(pd.DataFrame()) == {}


def test_the_overall_target_is_weighted_by_the_rows_the_score_is():
    """Two checks, 1,000 rows at a 100% target and 3,000 at 98%: the blend is 98.5,
    not the 99 a plain mean of the two targets would give. It is the figure the
    headline would read with each element exactly on its tolerance."""
    run = _run([("r1", "pass", 1000), ("r2", "breach", 3000)])
    blend = targets.blended_target(run, {"r1": "A", "r2": "B"}, {"A": 100.0, "B": 98.0})
    assert blend == pytest.approx(98.5)


def test_shadow_checks_and_undeclared_targets_are_in_neither_half():
    run = _run([("r1", "pass", 1000), ("r2", "skipped", 9000), ("r3", "breach", 500)])
    blend = targets.blended_target(
        run, {"r1": "A", "r2": "B", "r3": "C"}, {"A": 99.0, "B": 50.0, "C": None})
    assert blend == pytest.approx(99.0)
    assert targets.blended_target(run, {}, {}) is None


def test_only_a_validated_unmismatched_element_is_assessed():
    """A target is a claim about the data. Presence-only coverage and a disputed
    rule both keep the score and lose the verdict; so does a missing tolerance."""
    assert targets.assessed({"covered"}, 97.0, 99.5)
    # One binding validated is enough: the email element's status-code column is
    # watched only for presence, and seven checks still examine the address itself.
    assert targets.assessed({"covered", "unvalidated"}, 97.0, 99.5)
    assert not targets.assessed({"unvalidated"}, 100.0, 99.5)
    assert not targets.assessed({"covered", "scope_mismatch"}, 50.0, 99.5)
    assert not targets.assessed({"no_rule"}, None, 95.0)
    assert not targets.assessed({"covered"}, 97.0, None)


def test_meeting_a_zero_tolerance_target_takes_every_row():
    assert targets.meets(100.0, 100.0)
    assert not targets.meets(99.99, 100.0)
    assert targets.shortfall(94.2, 99.5) == pytest.approx(5.3)
    assert targets.shortfall(None, 99.5) is None


def test_every_fixture_element_declares_a_tolerance_and_every_rule_maps_to_one():
    """The fixture's side of the bargain: twenty elements, each with a target, and
    every attached rule on exactly one of them — which is what lets the blend weight
    a check by a single element's tolerance."""
    if not FIXTURE.exists():
        pytest.skip("fixture not built")
    reg = coverage.current_registry(pd.read_parquet(FIXTURE / "config.cde_registry.parquet"))
    cov = pd.read_parquet(FIXTURE / "results.v_cde_coverage.parquet")

    declared = targets.element_targets(reg)
    assert len(declared) == 20 and all(t is not None for t in declared.values())
    assert set(declared.values()) == {100.0, 99.5, 98.0, 95.0}

    rule_cde = targets.rule_elements(cov)
    assert set(rule_cde) == coverage.attached_rule_ids(cov)
    assert set(rule_cde.values()) <= set(declared)

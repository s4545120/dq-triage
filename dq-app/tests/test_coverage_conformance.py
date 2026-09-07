"""The test that keeps the coverage fold honest.

`domain/coverage.derive_cde_coverage` is a copy of `v_cde_coverage` in
`sql/ddl/11_views_cde.sql`, and this is what proves it is still a copy: the fold runs
over the generated register, rule registry, check runs and profiles, and is compared
column by column against the `v_cde_coverage` output the fixture ships.

Same rule as the lifecycle twin. If this fails after you edited the view, the app has
drifted from the definition. If it fails after you edited the fold, the fold is
wrong. Either way the view wins.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from dq_app.domain.coverage import (
    classify_gap,
    coverage_summary,
    current_registry,
    derive_cde_coverage,
)

KEY = ["cde_id", "target_table", "target_column"]


def _equal(left: pd.Series, right: pd.Series) -> pd.Series:
    """Element-wise equality where two nulls count as equal, and a list compares by
    its contents rather than by identity."""
    def norm(v):
        if isinstance(v, (list, tuple, np.ndarray)):
            return "|".join(sorted(str(x) for x in v))
        return v

    left, right = left.map(norm), right.map(norm)
    null_left, null_right = left.isna(), right.isna()
    both = ~null_left & ~null_right
    same = pd.Series(False, index=left.index)
    same[both] = left[both].astype(str).values == right[both].astype(str).values
    return (null_left & null_right) | same


def test_fold_reproduces_shipped_view(
        cde_registry, rule_registry, check_runs, cde_profiles, shipped_coverage):
    got = derive_cde_coverage(cde_registry, rule_registry, check_runs, cde_profiles)

    assert len(got) == len(shipped_coverage)

    a = shipped_coverage.sort_values(KEY).reset_index(drop=True)
    b = got.sort_values(KEY).reset_index(drop=True)

    shared = [c for c in a.columns if c in b.columns]
    assert shared == list(a.columns), f"fold is missing {set(a.columns) - set(b.columns)}"

    mismatches = {}
    for col in shared:
        eq = _equal(a[col], b[col])
        if not eq.all():
            mismatches[col] = a.loc[~eq, "cde_id"].tolist()
    assert not mismatches, f"fold disagrees with v_cde_coverage: {mismatches}"


def test_registered_before_any_rule(cde_registry, rule_registry):
    """The ordering the component exists to enforce: elements are registered before
    rules are written against them, not tagged onto rules afterwards."""
    assert cde_registry["effective_from"].min() <= rule_registry["effective_from"].min()


def test_current_registry_derives_effective_to(cde_registry):
    cur = current_registry(cde_registry)
    assert "effective_to" in cur.columns
    assert cur["cde_id"].is_unique
    assert (cur["status"] != "retired").all()
    # Latest version only.
    for cde_id, g in cde_registry.groupby("cde_id"):
        if (g["status"] == "retired").any():
            continue
        assert cur[cur["cde_id"] == cde_id]["cde_version"].iloc[0] == g["cde_version"].max()


def test_every_coverage_finding_is_exercised(shipped_coverage):
    """The fixture is built to produce each finding at least once. If one stops being
    reachable, a panel state has become untestable and nobody would notice."""
    assert {"covered", "unvalidated", "scope_mismatch"} <= set(
        shipped_coverage["coverage_gap"])


def test_scope_mismatch_names_the_rules_it_accuses(shipped_coverage, rule_registry):
    mism = shipped_coverage[shipped_coverage["has_scope_mismatch"]]
    assert len(mism), "no scope mismatch in the fixture"
    known = set(rule_registry["rule_id"])
    for _, r in mism.iterrows():
        assert len(r["unscoped_rule_ids"]), f"{r['cde_id']} claims a mismatch with no rule"
        assert set(r["unscoped_rule_ids"]) <= known
        # And the accusation only stands where the binding made a claim to contradict.
        assert r["expected_scope_filter"]


def test_unvalidated_is_about_behaviour_not_the_type_name():
    """A conditional presence check typed 'consistency' is still a presence check.
    Classifying on the literal type 'not_null' would call it covered."""
    assert classify_gap(1, [], ["consistency"]) == "unvalidated"
    assert classify_gap(1, [], ["not_null"]) == "unvalidated"
    assert classify_gap(1, [], ["format"]) == "covered"
    assert classify_gap(0, [], []) == "no_rule"
    # Scope mismatch outranks everything except having no rule at all.
    assert classify_gap(1, ["R"], ["format"]) == "scope_mismatch"


def test_pii_profiles_withhold_values(cde_profiles):
    """The privacy invariant, matching cde_profile_pii_withholds_values in the DDL:
    a PII element's profile declares that values were withheld, and no signature it
    stores is narrow enough to describe one person."""
    pii = cde_profiles[cde_profiles["pii"]]
    assert len(pii), "no PII element in the fixture"
    assert pii["value_stats_withheld"].all()
    for _, r in pii.iterrows():
        for sig in r["top_signatures"]:
            assert sig["signature"] == "<rare>" or sig["row_count"] >= 5


def test_summary_counts_match_the_rows(shipped_coverage):
    s = coverage_summary(shipped_coverage)
    assert s["bindings"] == len(shipped_coverage)
    assert s["covered"] + s["gaps"] == s["bindings"]
    assert s["elements"] == shipped_coverage["cde_id"].nunique()

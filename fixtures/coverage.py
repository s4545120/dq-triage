"""Python twin of `sql/ddl/11_views_cde.sql` v_cde_coverage.

Same standing as `cohort_current()` in build_fixtures.py: if this and the SQL view
ever disagree, the view is right and this is wrong. It is the copy. The app carries
a second copy in `dq_app/domain/coverage.py`, pinned to the parquet this writes by
`tests/test_coverage_conformance.py`, so a change to the view is caught twice.

The join that matters is in `_attached`: a rule covers a binding if it names the
element explicitly OR if it targets that exact column. Both are needed. The column
match carries almost every rule and needs no curation; the explicit tag exists for
cross-table rules, which carry target_column = NULL and would otherwise be invisible
to a coverage view that only knew about columns.
"""

from __future__ import annotations

import pandas as pd


def _current_registry(registry: pd.DataFrame) -> pd.DataFrame:
    latest = (registry.sort_values(["cde_id", "cde_version"])
                      .groupby("cde_id", as_index=False).tail(1))
    return latest[latest["status"] != "retired"]


def _current_rules(rule_registry: pd.DataFrame) -> pd.DataFrame:
    latest = (rule_registry.sort_values(["rule_id", "rule_version"])
                           .groupby("rule_id", as_index=False).tail(1))
    return latest[latest["status"] == "active"]


def _bound(registry: pd.DataFrame) -> list[dict]:
    """One dict per bound column.

    Deliberately NOT a DataFrame. Building one coerces a struct field that is None
    on every row into NaN, and NaN is truthy -- which silently turned "this binding
    declares no scope" into "this binding declares a scope", and reported a scope
    mismatch against every rule in the register.
    """
    rows = []
    for _, c in _current_registry(registry).iterrows():
        if c["status"] != "registered":
            continue
        for b in c["bindings"]:
            if b["binding_status"] != "bound":
                continue
            rows.append(dict(
                cde_id=c["cde_id"], cde_name=c["cde_name"],
                data_class=c["data_class"], criticality=c["criticality"],
                pii=bool(c["pii"]), business_domain=c["business_domain"],
                owner_group=c["owner_group"],
                target_table=b["target_table"], target_column=b["target_column"],
                populated_when=b["populated_when"],
                expected_scope_filter=b["expected_scope_filter"],
                discovered_by=b["discovered_by"],
            ))
    return rows


def _attached(binding: dict, rules: pd.DataFrame) -> pd.DataFrame:
    by_cde = rules["cde_id"] == binding["cde_id"]
    by_column = (
        (rules["target_table"] == binding["target_table"])
        & (rules["target_column"] == binding["target_column"])
    )
    return rules[by_cde | by_column]


# Rule types that check the VALUES rather than their presence or their agreement
# with another column. An element watched only by rules outside this set has
# something looking at it and nothing checking what it contains.
VALIDATING_TYPES = frozenset({"format", "uniqueness", "referential", "variance"})


def _gap(rule_count: int, unscoped: list[str], rule_types: list[str]) -> str:
    if rule_count == 0:
        return "no_rule"
    if unscoped:
        return "scope_mismatch"
    if not VALIDATING_TYPES.intersection(rule_types):
        return "unvalidated"
    return "covered"


def cde_coverage(
    registry: pd.DataFrame,
    rule_registry: pd.DataFrame,
    check_runs: pd.DataFrame,
    profiles: pd.DataFrame,
) -> pd.DataFrame:
    rules = _current_rules(rule_registry)

    latest_ts = check_runs["run_ts"].max() if len(check_runs) else None
    verdicts = (check_runs[check_runs["run_ts"] == latest_ts]
                .set_index("rule_id")[["status", "violation_count"]]
                if latest_ts is not None else pd.DataFrame())

    latest_profile = (
        profiles.sort_values("profile_ts")
                .groupby(["cde_id", "target_table", "target_column"], as_index=False)
                .tail(1)
        if len(profiles) else profiles
    )

    out = []
    for b in _bound(registry):
        att = _attached(b, rules)
        rule_ids = sorted(att["rule_id"].unique().tolist())
        rule_types = sorted(att["rule_type"].dropna().unique().tolist())

        breaching, violations = [], 0
        for rid in rule_ids:
            if rid in verdicts.index:
                v = verdicts.loc[rid]
                if v["status"] == "breach":
                    breaching.append(rid)
                    violations += int(v["violation_count"] or 0)

        # A rule with no scope_filter attached to a binding that declares one is
        # measuring rows the register says never held a value.
        unscoped = sorted(
            att[att["scope_filter"].isna()]["rule_id"].tolist()
        ) if b["expected_scope_filter"] else []

        p = (latest_profile[
                (latest_profile["cde_id"] == b["cde_id"])
                & (latest_profile["target_table"] == b["target_table"])
                & (latest_profile["target_column"] == b["target_column"])]
             if len(latest_profile) else pd.DataFrame())
        pr = p.iloc[0] if len(p) else None

        out.append(dict(
            **b,
            rule_count=len(rule_ids),
            rule_ids=rule_ids,
            rule_types=rule_types,
            has_active_rule=len(rule_ids) > 0,
            breaching_rule_count=len(breaching),
            breaching_rule_ids=breaching,
            latest_violation_rows=int(violations),
            unscoped_rule_ids=unscoped,
            has_scope_mismatch=len(unscoped) > 0,
            last_profiled_ts=pr["profile_ts"] if pr is not None else pd.NaT,
            profiled_rows=int(pr["rows_scanned"]) if pr is not None else None,
            null_pct=pr["null_pct"] if pr is not None else None,
            blank_pct=pr["blank_pct"] if pr is not None else None,
            distinct_pct=pr["distinct_pct"] if pr is not None else None,
            signature_count=int(pr["signature_count"]) if pr is not None else None,
            signature_match_pct=pr["signature_match_pct"] if pr is not None else None,
            sentinel_count=int(pr["sentinel_count"]) if pr is not None else None,
            top_signatures=pr["top_signatures"] if pr is not None else None,
            never_profiled=pr is None,
            coverage_gap=_gap(len(rule_ids), unscoped, rule_types),
        ))
    return pd.DataFrame(out)

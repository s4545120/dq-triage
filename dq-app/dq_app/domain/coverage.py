"""CDE coverage — the Python twin of `sql/ddl/11_views_cde.sql` v_cde_coverage.

Same standing, and the same reason for existing, as `domain/lifecycle.py`: the view
is the definition and this is a labelled copy of it, pinned row for row by
`tests/test_coverage_conformance.py` against the parquet the fixture generator
writes. If the two disagree, the view is right.

WHY A COPY AT ALL, WHEN NOTHING IN A SESSION WRITES A CDE. Because something in a
session writes a *rule*. Promoting a shadow rule is one of the app's two writes, and
the moment it happens the element that rule covers is better covered than the
warehouse's last materialisation of the view says it is. Recomputing here means the
coverage panel answers with the registry as it stands in this session, which is the
same argument that put the lifecycle fold in Python.

Pure functions over DataFrames — no Streamlit, no adapter, no I/O.
"""

from __future__ import annotations

import pandas as pd

# Rule types that check the VALUES rather than their presence or their agreement
# with another column. An element watched only by rules outside this set has
# something looking at it and nothing checking what it contains — which is a
# different and quieter kind of gap than having no rule at all.
VALIDATING_TYPES = frozenset({"format", "uniqueness", "referential", "variance"})

GAP_ORDER = ["no_rule", "scope_mismatch", "unvalidated", "covered"]
CRITICALITY_ORDER = ["critical", "high", "medium", "low"]


def current_registry(registry: pd.DataFrame) -> pd.DataFrame:
    """Latest non-retired version of every element. The twin of
    v_cde_registry_current; effective_to is derived, never stored."""
    if registry.empty:
        return registry
    reg = registry.sort_values(["cde_id", "cde_version"])
    reg = reg.assign(effective_to=reg.groupby("cde_id")["effective_from"].shift(-1))
    latest = reg.groupby("cde_id", as_index=False).tail(1)
    return latest[latest["status"] != "retired"].reset_index(drop=True)


def bound_columns(registry: pd.DataFrame) -> list[dict]:
    """One dict per bound column.

    A list of dicts and not a DataFrame, deliberately. Building a frame here coerces
    a binding field that is None on every row into NaN, and NaN is truthy — which
    reads "this binding declares no scope" as "this binding declares a scope" and
    reports a scope mismatch against every rule in the register.
    """
    rows = []
    for _, c in current_registry(registry).iterrows():
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
    """Rules covering one binding: named explicitly, or targeting that column.

    Both paths are needed. The column match carries almost every rule and needs no
    curation. The explicit `cde_id` exists for cross-table rules, which carry
    target_column = NULL by design and would otherwise be invisible here — a name
    agreement check between two tables is unambiguously a name rule and no column
    join will ever find it.
    """
    by_cde = rules["cde_id"] == binding["cde_id"]
    by_column = (
        (rules["target_table"] == binding["target_table"])
        & (rules["target_column"] == binding["target_column"])
    )
    return rules[by_cde | by_column]


def classify_gap(rule_count: int, unscoped: list[str], rule_types: list[str]) -> str:
    """Worst finding first. `unvalidated` is about what a rule does, not what it is
    called: a conditional presence check typed `consistency` is still a presence
    check, and classifying on the literal type `not_null` would miss it."""
    if rule_count == 0:
        return "no_rule"
    if unscoped:
        return "scope_mismatch"
    if not VALIDATING_TYPES.intersection(rule_types):
        return "unvalidated"
    return "covered"


def derive_cde_coverage(
    registry: pd.DataFrame,
    rule_registry: pd.DataFrame,
    check_runs: pd.DataFrame,
    profiles: pd.DataFrame,
) -> pd.DataFrame:
    """One row per bound column: what watches it, what contradicts it, when it was
    last described."""
    if registry.empty:
        return pd.DataFrame()

    rules = rule_registry.sort_values(["rule_id", "rule_version"])
    rules = rules.groupby("rule_id", as_index=False).tail(1)
    rules = rules[rules["status"] == "active"]

    verdicts = pd.DataFrame()
    if len(check_runs):
        latest_ts = check_runs["run_ts"].max()
        verdicts = (check_runs[check_runs["run_ts"] == latest_ts]
                    .set_index("rule_id")[["status", "violation_count"]])

    latest_profile = profiles
    if len(profiles):
        latest_profile = (profiles.sort_values("profile_ts")
                          .groupby(["cde_id", "target_table", "target_column"],
                                   as_index=False).tail(1))

    out = []
    for b in bound_columns(registry):
        att = _attached(b, rules)
        rule_ids = sorted(att["rule_id"].unique().tolist())
        rule_types = sorted(att["rule_type"].dropna().unique().tolist())

        breaching, violations = [], 0
        for rid in rule_ids:
            if len(verdicts) and rid in verdicts.index:
                v = verdicts.loc[rid]
                if v["status"] == "breach":
                    breaching.append(rid)
                    violations += int(v["violation_count"] or 0)

        # A rule with no scope_filter, attached to a binding that declares one, is
        # measuring rows the register says never held a value.
        unscoped = sorted(att[att["scope_filter"].isna()]["rule_id"].tolist()) \
            if b["expected_scope_filter"] else []

        pr = None
        if len(latest_profile):
            hit = latest_profile[
                (latest_profile["cde_id"] == b["cde_id"])
                & (latest_profile["target_table"] == b["target_table"])
                & (latest_profile["target_column"] == b["target_column"])]
            pr = hit.iloc[0] if len(hit) else None

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
            coverage_gap=classify_gap(len(rule_ids), unscoped, rule_types),
        ))
    return pd.DataFrame(out)


def attached_rule_ids(cov: pd.DataFrame) -> set[str]:
    """Every rule the coverage view attached to a registered element.

    This is the scorecard's scope. It is read back off `v_cde_coverage` rather than
    recomputed from the registry so there is exactly one answer in the system to "is
    this rule about a critical data element" — the same answer the coverage panel
    gives. Deriving it a second time by matching table and column would silently
    disagree: `XREF_NAME_AGREEMENT` spans two tables, carries no `target_column`, and
    attaches only through its explicit `cde_id` tag.
    """
    if cov.empty:
        return set()
    return {r for ids in cov["rule_ids"] for r in (ids if ids is not None else [])}


def coverage_summary(cov: pd.DataFrame) -> dict:
    """The numbers the scorecard panel shows. Kept here so the page does no
    arithmetic of its own."""
    if cov.empty:
        return dict(bindings=0, elements=0, covered=0, covered_pct=None,
                    gaps=0, critical_gaps=0, unprofiled=0, scope_mismatches=0)
    covered = int((cov["coverage_gap"] == "covered").sum())
    critical = cov[cov["criticality"].isin(["critical", "high"])]
    return dict(
        bindings=len(cov),
        elements=int(cov["cde_id"].nunique()),
        covered=covered,
        covered_pct=round(covered / len(cov) * 100, 1),
        gaps=int((cov["coverage_gap"] != "covered").sum()),
        critical_gaps=int((critical["coverage_gap"] != "covered").sum()),
        unprofiled=int(cov["never_profiled"].sum()),
        scope_mismatches=int(cov["has_scope_mismatch"].sum()),
    )

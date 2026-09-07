"""Shared render helpers for the monitored-table pages.

`domain_filter` is where these pages decide what they are looking at, and it applies
two filters, not one: the domains the reader picked, and — always — the checks
`v_cde_coverage` attached to a registered critical data element. The second is not a
control. See `domain/coverage.attached_rule_ids` and the scorecard's module docstring
for why the register, rather than the rule set, owns the denominator.

The scoping is drawn in the filter strip rather than left implicit. A diagnostic page
that quietly hides 14 of 34 checks is worse than one that shows fewer and says so.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dq_app.data import adapter
from dq_app.domain import coverage, metrics
from dq_app.ui import components, theme


def quality_score(run: pd.DataFrame) -> float:
    raised = run[run["status"].isin(["pass", "breach"])]
    if raised.empty:
        return 0.0
    return round(100.0 * len(raised[raised["status"] == "pass"]) / len(raised), 1)


def quality_history(check_run: pd.DataFrame, table: str, window_days: int) -> list[float]:
    scope = check_run[check_run["target_table"] == table].sort_values("run_ts")
    if scope.empty:
        return []

    cutoff = scope["run_ts"].max() - pd.Timedelta(days=window_days)
    rows = []
    for _, day_runs in scope[scope["run_ts"] >= cutoff].groupby(scope["run_ts"].dt.date):
        run_id = day_runs.loc[day_runs["run_ts"].idxmax(), "run_id"]
        rows.append(quality_score(day_runs[day_runs["run_id"] == run_id]))
    return rows


def trend_label(history: list[float]) -> str:
    if len(history) < 2:
        return "No prior run"
    delta = history[-1] - history[-2]
    if abs(delta) < 0.05:
        return "Flat"
    return f"{delta:+.1f} pts"


def status_label(run: pd.DataFrame) -> str:
    breaching = run[run["status"] == "breach"]
    if breaching.empty:
        return "Healthy"
    if (breaching["severity"] == "P1_block").any():
        return "Critical"
    return "Needs attention"


def monitor_inventory(check_run: pd.DataFrame, window_days: int) -> pd.DataFrame:
    run_id = metrics.latest_run_id(check_run)
    if run_id is None:
        return pd.DataFrame()

    latest = check_run[check_run["run_id"] == run_id]
    rows = []
    for table, g in latest.groupby("target_table", sort=False):
        raised = g[g["status"].isin(["pass", "breach"])]
        breaching = g[g["status"] == "breach"]
        history = quality_history(check_run, table, window_days)
        rows.append({
            "Monitor": f"{table.split('.')[-1]} / Primary",
            "Catalog item": table,
            "Status": status_label(g),
            "Overall DQ": history[-1] if history else quality_score(g),
            "Trend": trend_label(history),
            "Quality over time": history,
            "Findings": int(breaching["violation_count"].sum()),
            "Breaching": int(len(breaching)),
            "Rules": int(len(raised)),
            "P1": int((breaching["severity"] == "P1_block").sum()),
            "Evaluated rows": int(g.groupby("target_table")["rows_scanned"].max().sum()),
            "Owner": ", ".join(sorted(set(g["owner_group"].dropna()))),
            "Latest run": g["run_ts"].max(),
            "__table": table,
        })

    status_order = {"Critical": 0, "Needs attention": 1, "Healthy": 2}
    out = pd.DataFrame(rows)
    return (
        out.assign(_status_order=out["Status"].map(status_order).fillna(9))
        .sort_values(["_status_order", "Findings", "Monitor"], ascending=[True, False, True])
        .drop(columns=["_status_order"])
        .reset_index(drop=True)
    )


def applied_rules(check_run: pd.DataFrame, table: str, registry: pd.DataFrame) -> pd.DataFrame:
    run_id = metrics.latest_run_id(check_run)
    if run_id is None:
        return pd.DataFrame()

    rule_name = registry.set_index("rule_id")["rule_name"].to_dict()
    run_now = check_run[
        (check_run["run_id"] == run_id)
        & (check_run["target_table"] == table)
    ]
    hist = (
        check_run[check_run["target_table"] == table]
        .sort_values("run_ts").groupby("rule_id")["violation_count"].apply(list)
    )

    rows = []
    for _, r in run_now.sort_values(["status", "violation_count"],
                                    ascending=[True, False]).iterrows():
        violation_pct = float(r["violation_pct"])
        rows.append({
            "Rule name": rule_name.get(r["rule_id"], r["rule_id"]),
            "Status": {"breach": "Failing", "pass": "Passing"}.get(r["status"], "Shadow"),
            "Overall DQ": max(0.0, round(100.0 - violation_pct, 2)),
            "Findings trend": hist.get(r["rule_id"], []),
            "Attribute": components.opt(r["target_column"]) or "table level",
            "Findings": int(r["violation_count"]),
            "Evaluated rows": int(r["rows_scanned"]),
            "Rate": violation_pct,
            "Limit": float(r["threshold_pct"]),
            "Severity": theme.severity_text(r["severity"]),
            "Rule id": r["rule_id"],
        })
    return pd.DataFrame(rows)


def domain_filter(runs: pd.DataFrame, key_prefix: str) -> tuple[pd.DataFrame, int]:
    """The run set a monitoring page works on: picked domains, CDE-attached checks."""
    cde = adapter.get_cde_coverage()
    cde_rules = coverage.attached_rule_ids(cde)

    with st.container(key=f"{key_prefix}_filter_strip"):
        l1, f1, l2, f2, l3, note = st.columns([0.55, 2.3, 0.55, 1.35, 0.9, 1.9])
        with l1:
            st.markdown('<div class="dq-strip-lab">Domains</div>', unsafe_allow_html=True)
        with f1:
            domains = sorted(set(runs["business_domain"].dropna()))
            picked = st.multiselect("Domain", domains, default=domains,
                                    label_visibility="collapsed",
                                    key=f"{key_prefix}_domains")
        with l2:
            st.markdown('<div class="dq-strip-lab">Period</div>', unsafe_allow_html=True)
        with f2:
            window = st.selectbox("Window", [7, 14, 30, 40], index=2,
                                  format_func=lambda d: f"Last {d} days",
                                  label_visibility="collapsed",
                                  key=f"{key_prefix}_window")
        with l3:
            st.markdown(
                '<div style="padding-top:.42rem">'
                + theme.badge(f"{cde['cde_id'].nunique() if not cde.empty else 0} CDEs",
                              "info", "shield")
                + "</div>",
                unsafe_allow_html=True,
                help="Not a control. This page counts only checks attached to a "
                     "registered critical data element — the register owns the "
                     "denominator, so the figures do not move when someone writes or "
                     "retires an unrelated rule. Checks on unregistered columns still "
                     "run and still raise cohorts; work them from Cohorts.",
            )
        with note:
            last_ts = runs["run_ts"].max()
            st.markdown(
                f'<div class="dq-strip-note">Last run {last_ts:%d %b, %H:%M}<br>'
                f"Next expected {last_ts + pd.Timedelta(days=1):%d %b, %H:%M}</div>",
                unsafe_allow_html=True,
            )

    in_domain = runs[runs["business_domain"].isin(picked)]
    return in_domain[in_domain["rule_id"].isin(cde_rules)], window

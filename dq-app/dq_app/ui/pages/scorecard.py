"""Scorecard — how healthy is the data right now.

This page is about the data, not about the work. It answers "what is wrong, where,
how much, and since when". Everything about triage — how problems were grouped, who
decided what, whether fixes held — lives on the Cohorts and Register pages.

The one thread between them is **Diagnose**: when this page shows a table failing its
checks, it also shows the problems those failures belong to and links straight to
them. Detection that cannot hand you to the diagnosis is where a data-quality tool
usually stops being useful.

Plain words throughout. A steward reading this should not have to know what
`P1_block`, a `rule_expr` or a `check_run` is.
"""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from dq_app.data import adapter
from dq_app.domain import metrics
from dq_app.ui import components, theme


def _quality_score(run: pd.DataFrame) -> float:
    raised = run[run["status"].isin(["pass", "breach"])]
    if raised.empty:
        return 0.0
    return round(100.0 * len(raised[raised["status"] == "pass"]) / len(raised), 1)


def _quality_history(check_run: pd.DataFrame, table: str, window_days: int) -> list[float]:
    scope = check_run[check_run["target_table"] == table].sort_values("run_ts")
    if scope.empty:
        return []

    cutoff = scope["run_ts"].max() - pd.Timedelta(days=window_days)
    rows = []
    for _, day_runs in scope[scope["run_ts"] >= cutoff].groupby(scope["run_ts"].dt.date):
        run_id = day_runs.loc[day_runs["run_ts"].idxmax(), "run_id"]
        rows.append(_quality_score(day_runs[day_runs["run_id"] == run_id]))
    return rows


def _trend_label(history: list[float]) -> str:
    if len(history) < 2:
        return "No prior run"
    delta = history[-1] - history[-2]
    if abs(delta) < 0.05:
        return "Flat"
    return f"{delta:+.1f} pts"


def _status_label(run: pd.DataFrame) -> str:
    breaching = run[run["status"] == "breach"]
    if breaching.empty:
        return "Healthy"
    if (breaching["severity"] == "P1_block").any():
        return "Critical"
    return "Needs attention"


def _dimension_for(rule_type: str) -> str:
    """Map local rule types to the DQ dimensions used in monitoring tools."""
    return {
        "not_null": "Completeness",
        "format": "Validity",
        "sentinel": "Validity",
        "variance": "Validity",
        "consistency": "Consistency",
        "referential": "Consistency",
        "uniqueness": "Uniqueness",
    }.get(rule_type, "Other")


def _dimension_summary(check_run: pd.DataFrame, registry: pd.DataFrame) -> list[dict]:
    run_id = metrics.latest_run_id(check_run)
    if run_id is None:
        return []

    dims = registry[["rule_id", "rule_type"]].drop_duplicates("rule_id").copy()
    dims["Dimension"] = dims["rule_type"].map(_dimension_for)
    run = check_run[check_run["run_id"] == run_id].merge(
        dims[["rule_id", "Dimension"]], on="rule_id", how="left"
    )

    rows = []
    for dim in ["Completeness", "Validity", "Consistency", "Uniqueness"]:
        g = run[run["Dimension"].fillna("Other") == dim]
        raised = g[g["status"].isin(["pass", "breach"])]
        breaching = g[g["status"] == "breach"]
        evaluated = int(raised["rows_scanned"].sum())
        violations = int(raised["violation_count"].sum())
        score = 100.0 * (evaluated - violations) / evaluated if evaluated else None
        rows.append({
            "label": dim,
            "value": "—" if score is None else f"{score:.0f}%",
            "sub": (
                "not instrumented" if score is None
                else f"{len(breaching)} failing · {int(breaching['violation_count'].sum()):,} findings"
            ),
            "tone": (
                None if score is None
                else "success" if score >= 80
                else "critical" if len(breaching) else None
            ),
            "help": (
                f"{dim} score on the latest run: evaluated rows that passed active "
                "checks in this dimension ÷ evaluated rows for active checks in this "
                "dimension. This is aggregate check-level scoring; exact record-level "
                "overall quality would need every failing record key. Shadow checks "
                "are excluded from the denominator."
            ),
        })
    return rows


def _monitor_inventory(check_run: pd.DataFrame, window_days: int) -> pd.DataFrame:
    run_id = metrics.latest_run_id(check_run)
    if run_id is None:
        return pd.DataFrame()

    latest = check_run[check_run["run_id"] == run_id]
    rows = []
    for table, g in latest.groupby("target_table", sort=False):
        raised = g[g["status"].isin(["pass", "breach"])]
        breaching = g[g["status"] == "breach"]
        history = _quality_history(check_run, table, window_days)
        rows.append({
            "Monitor": f"{table.split('.')[-1]} / Primary",
            "Catalog item": table,
            "Status": _status_label(g),
            "Overall DQ": history[-1] if history else _quality_score(g),
            "Trend": _trend_label(history),
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


def _applied_rules(check_run: pd.DataFrame, table: str, registry: pd.DataFrame) -> pd.DataFrame:
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


components.page_chrome()

st.title("DQ monitoring")
st.caption("Operational scorecard for catalog items, applied checks, and the problems behind them.")

runs = adapter.get_check_runs()
cohorts = adapter.get_cohorts()
current = adapter.get_cohort_current()
registry = adapter.get_rule_registry_current()

if runs.empty:
    st.caption("No check runs available.")
    st.stop()

f1, f2, _ = st.columns([2.1, 1.1, 1.8])
with f1:
    domains = sorted(set(runs["business_domain"].dropna()))
    picked = st.multiselect("Domain", domains, default=domains, label_visibility="collapsed")
with f2:
    window = st.selectbox("Window", [7, 14, 30, 40], index=2,
                          format_func=lambda d: f"Last {d} days", label_visibility="collapsed")

scoped = runs[runs["business_domain"].isin(picked)]
if scoped.empty:
    st.caption("No checks in the selected domains.")
    st.stop()

d = metrics.detection_summary(scoped)
rule_name = registry.set_index("rule_id")["rule_name"].to_dict()

# --- Headline ---------------------------------------------------------------
theme.section("Monitoring overview")

components.kpi_row([
    {
        "label": "Checks passing",
        "value": f"{d['pass_rate']:.0f}%",
        "sub": f"{d['rules_passing']} of {d['rules_raised']} checks",
        "tone": "success" if d["pass_rate"] >= 80 else "critical",
        "help": "Share of quality checks that passed on the most recent scheduled run. "
                f"{d['rules_skipped']} more checks ran in shadow mode and are excluded — "
                "they record results but do not raise anything until someone promotes "
                "them. Measured on that one run, not averaged: a problem that started "
                "four days ago would be diluted sevenfold by a monthly average.",
    },
    {
        "label": "Checks failing",
        "value": f"{d['rules_breaching']}",
        "sub": f"{d['p1_breaching']} critical",
        "tone": "critical" if d["p1_breaching"] else None,
        "help": "Checks whose failure rate is over the limit set for them.",
    },
    {
        "label": "Findings",
        "value": f"{d['violations']:,}",
        "sub": "across all failing checks",
        "help": "One finding is one row failing one check. A single bad row can produce "
                "several findings — the 240 malformed email addresses trip six separate "
                "format checks — so this is always more than the number of bad rows. "
                "Counting distinct rows would need the checker to record a key for "
                "every finding, which it currently does only for the samples it keeps.",
    },
    {
        "label": "Under watch",
        "value": f"{d['tables']} tables",
        "sub": f"{d['columns']} columns · {d['rows_scanned']:,} rows",
        "help": "Rows are counted once per table, not once per check.",
    },
    {
        "label": "Last checked",
        "value": f"{d['run_ts']:%H:%M}",
        "sub": f"{d['run_ts']:%d %b} · runs daily",
    },
])

theme.section("DQ dimensions")
components.kpi_row(_dimension_summary(scoped, registry))

# --- What changed -----------------------------------------------------------
theme.section("What changed")

changes = []
for table in sorted(scoped["target_table"].unique()):
    nf = metrics.newly_failing(scoped, table, days=window)
    if not nf.empty:
        changes.append((table, nf))

if not changes:
    st.caption(f"Nothing started failing in the last {window} days. Anything failing "
               "now has been failing for longer than that.")
else:
    for table, nf in changes:
        by_date = nf.groupby(nf["Started failing"].dt.date)
        for day, group in by_date:
            checks = ", ".join(rule_name.get(c, c) for c in group["Check"].head(3))
            more = f" and {len(group) - 3} more" if len(group) > 3 else ""
            st.markdown(
                theme.badge(f"{day:%d %b}", "critical", "alert")
                + f" &nbsp;**{len(group)} check(s)** started failing on "
                f"`{table.split('.')[-1]}` — {checks}{more}. "
                f"{int(group['Failing rows'].sum()):,} rows affected.",
                unsafe_allow_html=True,
                help="Several checks turning on the same date is the signature of one "
                     "upstream change, not of several unrelated problems.",
            )

# --- Monitors ---------------------------------------------------------------
theme.section("All DQ monitors")

inventory = _monitor_inventory(scoped, window)
if inventory.empty:
    st.caption("No monitor results in the selected filters.")
    st.stop()

saved_table = st.session_state.get("scorecard_selected_table")
if saved_table not in set(inventory["__table"]):
    saved_table = inventory.iloc[0]["__table"]
    st.session_state["scorecard_selected_table"] = saved_table

default_row = int(inventory.index[inventory["__table"] == saved_table][0])
selection = st.dataframe(
    inventory,
    key="scorecard_monitor_inventory",
    width="stretch",
    height=min(298, 106 + 48 * len(inventory)),
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row-required",
    selection_default={"selection": {"rows": [default_row]}},
    column_order=[
        "Monitor", "Status", "Overall DQ", "Trend", "Quality over time", "Findings",
        "Breaching", "Rules", "P1", "Evaluated rows", "Owner", "Latest run",
    ],
    column_config={
        "Monitor": st.column_config.TextColumn(width="medium"),
        "Status": st.column_config.TextColumn(width="small"),
        "Overall DQ": st.column_config.ProgressColumn(
            "Overall DQ", min_value=0, max_value=100, format="%.1f%%", width="small"
        ),
        "Trend": st.column_config.TextColumn(
            help="Change in overall DQ since the previous scheduled run."
        ),
        "Quality over time": st.column_config.LineChartColumn(
            "Quality over time", y_min=0, y_max=100, width="medium"
        ),
        "Findings": st.column_config.NumberColumn(format="%d"),
        "Breaching": st.column_config.NumberColumn(format="%d", width="small"),
        "Rules": st.column_config.NumberColumn(format="%d", width="small"),
        "P1": st.column_config.NumberColumn(format="%d", width="small"),
        "Evaluated rows": st.column_config.NumberColumn(format="%d"),
        "Owner": st.column_config.TextColumn(width="medium"),
        "Latest run": st.column_config.DatetimeColumn("Latest run", format="DD MMM HH:mm"),
    },
    lazy=False,
)

selected_rows = list(selection.selection.rows) if selection and selection.selection else []
if selected_rows:
    chosen_table = inventory.iloc[selected_rows[0]]["__table"]
    st.session_state["scorecard_selected_table"] = chosen_table
else:
    chosen_table = saved_table

selected_monitor = inventory[inventory["__table"] == chosen_table].iloc[0]
ti = metrics.table_insights(scoped, chosen_table)
status_tone = {
    "Critical": "critical",
    "Needs attention": "moderate",
    "Healthy": "success",
}.get(str(selected_monitor["Status"]), "neutral")

st.markdown(
    f'<div class="dq-monitor-hd">'
    f'<span>{theme.icon("table", 15)} {html.escape(str(selected_monitor["Monitor"]))}</span>'
    f'{theme.badge(str(selected_monitor["Status"]), status_tone)}'
    f'</div>',
    unsafe_allow_html=True,
)
st.caption(f"`{chosen_table}`")

components.kpi_row([
    {"label": "Checks passing", "value": f"{ti['pass_rate']:.0f}%",
     "sub": f"{ti['checks'] - ti['failing']} of {ti['checks']}",
     "tone": "success" if ti["pass_rate"] >= 80 else "critical"},
    {"label": "Findings", "value": f"{ti['violations']:,}", "sub": f"in {ti['rows']:,} rows"},
    {"label": "Columns affected", "value": f"{ti['columns_failing']}",
     "sub": f"of {ti['columns_checked']} checked"},
    {"label": "Worst check", "value": f"{ti['worst_rate']:.0f}%",
     "sub": rule_name.get(ti["worst_rule"], ti["worst_rule"] or "—")},
    {"label": "Critical failures", "value": f"{ti['p1']}",
     "tone": "critical" if ti["p1"] else None, "sub": "must be fixed"},
])

# --- Applied rules and diagnosis -------------------------------------------
latest_run = metrics.latest_run_id(scoped)
failing = scoped[
    (scoped["run_id"] == latest_run)
    & (scoped["target_table"] == chosen_table)
    & (scoped["status"] == "breach")
]
owner = metrics.cohort_for_rules(cohorts, failing["rule_id"])
cohort_ids = sorted(set(owner.values()))

rules_tab, problems_tab = st.tabs(["Applied rules", "Problem cohorts"])

with rules_tab:
    rule_rows = _applied_rules(scoped, chosen_table, registry)
    rule_search = st.text_input(
        "Search rules",
        placeholder="Search rule name, attribute, id, status",
        label_visibility="collapsed",
        key=f"rule_search_{chosen_table}",
    ).strip().lower()
    if rule_search:
        searchable = rule_rows[
            ["Rule name", "Rule id", "Attribute", "Status", "Severity"]
        ].astype(str).agg(" ".join, axis=1).str.lower()
        rule_rows = rule_rows[searchable.str.contains(rule_search, regex=False, na=False)]

    if rule_rows.empty:
        st.caption("No applied rules match this search.")
    else:
        st.dataframe(
            rule_rows,
            width="stretch",
            hide_index=True,
            height=min(480, 114 + 38 * len(rule_rows)),
            column_config={
                "Rule name": st.column_config.TextColumn(width="large"),
                "Status": st.column_config.TextColumn(width="small"),
                "Overall DQ": st.column_config.ProgressColumn(
                    "Overall DQ", min_value=0, max_value=100, format="%.2f%%", width="small"
                ),
                "Findings trend": st.column_config.LineChartColumn(
                    "Findings trend",
                    help="Findings per scheduled run, oldest first.",
                    width="medium",
                ),
                "Attribute": st.column_config.TextColumn(width="small"),
                "Findings": st.column_config.NumberColumn(format="%d"),
                "Evaluated rows": st.column_config.NumberColumn(format="%d"),
                "Rate": st.column_config.NumberColumn(format="%.2f%%"),
                "Limit": st.column_config.NumberColumn(format="%.2f%%"),
                "Severity": st.column_config.TextColumn(width="small"),
                "Rule id": st.column_config.TextColumn(width="small"),
            },
            lazy=False,
        )
        st.caption(
            "History is one point per daily run, oldest first.",
            help="A flat line means the check has always found this much. A step means "
                 "something changed on a date, which is what the panel above picks up.",
        )

with problems_tab:
    st.markdown(
        f"**{len(cohort_ids)} problem(s)** behind these {len(failing)} failing checks",
        help=theme.COHORT_ONE_LINER,
    )

    if not cohort_ids:
        st.caption("No problem has been raised for these failures yet.")
    else:
        detail = cohorts.set_index("cohort_id")
        state = current.set_index("cohort_id")
        for cid in sorted(cohort_ids,
                          key=lambda c: -int(detail.loc[c, "member_count"])):
            row = state.loc[cid]
            info = detail.loc[cid]
            mine = [r for r, c in owner.items() if c == cid]
            with st.container(border=True):
                body, action = st.columns([5, 1])
                with body:
                    st.markdown(
                        theme.severity_badge(row["severity"])
                        + " " + theme.state_badge(row["lifecycle_state"]),
                        unsafe_allow_html=True,
                    )
                    st.markdown(f"**{str(info['root_cause_hypothesis']).split('.')[0]}.**")
                    st.caption(
                        f"{len(mine)} of this table's failing checks · "
                        f"{', '.join(rule_name.get(r, r) for r in mine[:3])}"
                        + (f" and {len(mine) - 3} more" if len(mine) > 3 else "")
                    )
                with action:
                    if st.button("Diagnose", key=f"diag_{cid}", width="stretch",
                                 type="primary"):
                        st.session_state["selected_cohort"] = cid
                        st.switch_page("dq_app/ui/pages/cohort_detail.py")

# --- Trend ------------------------------------------------------------------
theme.section("Trend")

cutoff = scoped["run_ts"].max() - pd.Timedelta(days=window)
breaches = scoped[(scoped["run_ts"] >= cutoff) & (scoped["status"] == "breach")]
if breaches.empty:
    st.caption("No failing checks in this window.")
else:
    trend = (
        breaches.assign(day=breaches["run_ts"].dt.date)
        .pivot_table(index="day", columns="severity", values="rule_id", aggfunc="count")
        .fillna(0)
    )
    order = [s for s in theme.SEVERITY_ORDER if s in trend.columns]
    st.line_chart(
        trend[order].rename(columns=lambda s: theme.severity_text(s)), height=210,
        color=[theme.TONE[theme.SEVERITY_TONE[s]]["fg"] for s in order],
    )
    st.caption("Failing checks per day, by how serious they are.")

with st.expander("By domain"):
    components.summary_table(
        metrics.quality_by(scoped, "business_domain"), bar="Pass rate"
    )

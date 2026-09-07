"""Monitor detail — checks and cohorts for one watched table."""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from dq_app.data import adapter
from dq_app.domain import metrics
from dq_app.ui import components, monitoring, theme

components.page_chrome()

runs = adapter.get_check_runs()
cohorts = adapter.get_cohorts()
current = adapter.get_cohort_current()
registry = adapter.get_rule_registry_current()

if runs.empty:
    st.caption("No check runs available.")
    st.stop()

scoped, window = monitoring.domain_filter(runs, "monitor_detail")
if scoped.empty:
    st.caption(
        "No checks on registered critical data elements in the selected domains. "
        "Unregistered columns may still be checked — those are worked from Cohorts."
    )
    st.stop()

inventory = monitoring.monitor_inventory(scoped, window)
if inventory.empty:
    st.caption("No monitor results in the selected filters.")
    st.stop()

selected = st.session_state.get("monitors_selected_table")
if selected not in set(inventory["__table"]):
    selected = inventory.iloc[0]["__table"]
    st.session_state["monitors_selected_table"] = selected

rule_name = registry.set_index("rule_id")["rule_name"].to_dict()
selected_monitor = inventory[inventory["__table"] == selected].iloc[0]
status_tone = {
    "Critical": "critical",
    "Needs attention": "moderate",
    "Healthy": "success",
}.get(str(selected_monitor["Status"]), "neutral")

back, picker, badge = st.columns([1.15, 3.5, 1], vertical_alignment="center")
with back:
    if st.button("All monitors", icon=":material/arrow_back:", width="stretch"):
        st.switch_page("dq_app/ui/pages/monitored_tables.py")
with picker:
    options = inventory["__table"].tolist()
    picked = st.selectbox(
        "Monitor",
        options,
        index=options.index(selected),
        format_func=lambda table: inventory[inventory["__table"] == table].iloc[0]["Monitor"],
        label_visibility="collapsed",
    )
    if picked != selected:
        st.session_state["monitors_selected_table"] = picked
        st.rerun()
with badge:
    st.markdown(theme.badge(str(selected_monitor["Status"]), status_tone),
                unsafe_allow_html=True)

st.markdown(
    f'<div class="dq-monitor-hd">'
    f'<span>{theme.icon("table", 15)} {html.escape(str(selected_monitor["Monitor"]))}</span>'
    f'</div>',
    unsafe_allow_html=True,
)
st.caption(f"`{selected}`")

ti = metrics.table_insights(scoped, selected)
components.kpi_row([
    {"label": "Checks passing", "value": f"{ti['pass_rate']:.0f}%",
     "sub": f"{ti['checks'] - ti['failing']} of {ti['checks']}",
     "tone": "success" if ti["pass_rate"] >= 80 else "critical"},
    {"label": "Findings", "value": f"{ti['violations']:,}", "sub": f"in {ti['rows']:,} rows"},
    {"label": "Columns affected", "value": f"{ti['columns_failing']}",
     "sub": f"of {ti['columns_checked']} checked"},
    {"label": "Worst check", "value": f"{ti['worst_rate']:.0f}%",
     "sub": rule_name.get(ti["worst_rule"], ti["worst_rule"] or "-")},
    {"label": "Critical failures", "value": f"{ti['p1']}",
     "tone": "critical" if ti["p1"] else None, "sub": "must be fixed"},
])

latest_run = metrics.latest_run_id(scoped)
failing = scoped[
    (scoped["run_id"] == latest_run)
    & (scoped["target_table"] == selected)
    & (scoped["status"] == "breach")
]
owner = metrics.cohort_for_rules(cohorts, failing["rule_id"])
cohort_ids = sorted(set(owner.values()))

rules_tab, problems_tab, trend_tab = st.tabs([
    "Applied rules",
    "Problem cohorts",
    "History",
])

with rules_tab:
    rule_rows = monitoring.applied_rules(scoped, selected, registry)
    rule_search = st.text_input(
        "Search rules",
        placeholder="Search rule name, attribute, id, status",
        label_visibility="collapsed",
        key=f"rule_search_{selected}",
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
                 "something changed on a date.",
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

with trend_tab:
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

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

import pandas as pd
import streamlit as st

from dq_app.data import adapter
from dq_app.domain import metrics
from dq_app.ui import components, theme

components.page_chrome()

st.title("Scorecard")
st.caption("How healthy the data is right now, and what changed.")

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
theme.section("Data quality")

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

# --- Per table --------------------------------------------------------------
theme.section("By table")

tables = sorted(scoped["target_table"].unique())
short = {t: t.split(".")[-1] for t in tables}
chosen_table = st.segmented_control(
    "Table", tables, default=tables[0], format_func=lambda t: short[t],
    label_visibility="collapsed",
)
if not chosen_table:
    chosen_table = tables[0]

ti = metrics.table_insights(scoped, chosen_table)
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

# --- The bridge: failures belong to problems, and problems can be diagnosed ---
latest_run = metrics.latest_run_id(scoped)
failing = scoped[
    (scoped["run_id"] == latest_run)
    & (scoped["target_table"] == chosen_table)
    & (scoped["status"] == "breach")
]
owner = metrics.cohort_for_rules(cohorts, failing["rule_id"])
cohort_ids = sorted(set(owner.values()))

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

# --- Every check on this table ----------------------------------------------
with st.expander(f"All {ti['checks'] + ti['shadow']} checks on this table"):
    run_now = scoped[(scoped["run_id"] == latest_run) &
                     (scoped["target_table"] == chosen_table)]
    hist = (
        scoped[scoped["target_table"] == chosen_table]
        .sort_values("run_ts").groupby("rule_id")["violation_count"].apply(list)
    )
    rows = []
    for _, r in run_now.sort_values(["status", "violation_count"],
                                    ascending=[True, False]).iterrows():
        failing_now = r["status"] == "breach"
        rows.append({
            "Check": rule_name.get(r["rule_id"], r["rule_id"]),
            "Column": components.opt(r["target_column"]) or "—",
            "Result": {"breach": "Failing", "pass": "Passing"}.get(r["status"], "Shadow"),
            "Severity": theme.severity_text(r["severity"]),
            "Findings": int(r["violation_count"]),
            "Rate": f"{r['violation_pct']:.2f}%",
            "History": theme.sparkline(
                hist.get(r["rule_id"], []), tone="critical" if failing_now else "success"
            ),
        })
    components.summary_table(pd.DataFrame(rows), raw={"History"})
    st.caption(
        "History is one point per daily run, oldest first.",
        help="A flat line means the check has always found this much — a known gap. "
             "A step means something changed on a date, which is what the panel above "
             "picks up.",
    )

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

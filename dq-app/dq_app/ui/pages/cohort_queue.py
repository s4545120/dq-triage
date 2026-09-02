"""Cohort queue — one row per problem, not one per breach.

A table, not a stack of cards. The queue is something a steward scans and sorts, and
a card list forces the hypothesis text on you before you have decided which row you
care about. Selecting a row opens the detail page.

The compression figure leads because it is the queue's whole claim: if it approaches
1:1 this page is an alert list with extra steps.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dq_app.data import adapter
from dq_app.domain import integrity, lifecycle, metrics
from dq_app.ui import components, theme
from dq_app.ui.components import as_list

components.page_chrome()

st.title("Cohorts")
st.caption(theme.COHORT_ONE_LINER)

current = adapter.get_cohort_current()
cohorts = adapter.get_cohorts()
runs = adapter.get_check_runs()

# One definition of compression, in domain/metrics.py — recomputing it here with a
# slightly different denominator is how a headline starts disagreeing with the
# scorecard that reports it.
compression = metrics.cohort_compression(runs, cohorts)
latest_ts = runs["run_ts"].max()

components.kpi_row([
    # The grouping stated as an arrow, because that is the claim: this many alerts
    # became this many problems.
    {"label": "Breaching rules", "value": f"{int(compression.numerator or 0)}",
     "sub": f"latest run · {latest_ts:%d %b %H:%M}",
     "help": "Rules failing on the most recent scheduled check run. Without grouping, "
             "this is how many alerts a steward would be handed."},
    {"label": "Grouped into", "value": f"{int(compression.denominator or 0)} cohorts",
     "sub": f"{compression.display} · target {compression.target}",
     "help": compression.help + " " + compression.footnote},
    {"label": "Needing action", "value":
     f"{int(current['lifecycle_state'].isin(lifecycle.OPEN_STATES).sum())}",
     "sub": "waiting on a person or a run"},
    {"label": "Raised in total", "value": f"{len(current)}",
     "sub": "across the whole window"},
])

with st.expander("What is a cohort?"):
    st.markdown(theme.COHORT_EXPLAINER)

# --- Filters ----------------------------------------------------------------
f1, f2, f3, f4 = st.columns([1, 1.7, 1.2, 1])
with f1:
    sev = st.multiselect("Severity", theme.SEVERITY_ORDER, default=theme.SEVERITY_ORDER,
                         format_func=lambda s: theme.SEVERITY_SHORT[s])
with f2:
    present = [s for s in lifecycle.LIFECYCLE_ORDER if s in set(current["lifecycle_state"])]
    default = [s for s in present if s in lifecycle.OPEN_STATES or s == "deferred"]
    states = st.multiselect("State", present, default=default,
                            format_func=lambda s: theme.STATE_LABEL.get(s, s),
                            help="Defaults to everything still live. Add the closed "
                                 "states to see history.")
with f3:
    domains = sorted(current["business_domain"].dropna().unique())
    doms = st.multiselect("Domain", domains, default=domains)
with f4:
    recurrence_only = st.checkbox("Recurrences only",
                                  help="Cohorts where a rule came back after a verified close.")

view = current[
    current["severity"].isin(sev)
    & current["lifecycle_state"].isin(states)
    & current["business_domain"].isin(doms)
]
if recurrence_only:
    view = view[view["is_recurrence"].astype(bool)]

# --- The queue --------------------------------------------------------------
if view.empty:
    st.caption("No cohorts match these filters.")
    st.stop()

now = pd.Timestamp.now()
detail = cohorts.set_index("cohort_id")

# Column names a steward would use out loud. The database's words — cohort_id,
# lifecycle_state, rank_score — stay in the database.
table = pd.DataFrame({
    "Severity": view["severity"].map(theme.severity_text),
    "Status": view["lifecycle_state"].map(theme.STATE_LABEL),
    "Problem": view["cohort_id"].str.slice(0, 8),
    "What went wrong": [
        str(detail.loc[c, "root_cause_hypothesis"]).split(".")[0][:110]
        for c in view["cohort_id"]
    ],
    "Checks": view["member_count"].astype(int),
    "Findings": view["total_violation_rows"].astype(int),
    "Tables": [len(as_list(t)) for t in view["affected_tables"]],
    "Suggested fix": view["recommended_approach_type"].map(theme.approach_label),
    "Approvals": [
        f"{int(a)}/{int(b)}" for a, b in zip(view["distinct_approvers"], view["approvals_required"])
    ],
    "Age": [(now - t).days for t in view["raised_ts"]],
    "Owner": view["owner_group"],
    "Priority": view["rank_score"].astype(int),
}).reset_index(drop=True)

selection = st.dataframe(
    table,
    width="stretch",
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
    column_config={
        "Problem": st.column_config.TextColumn(width="small",
                                               help="Short id for this problem."),
        "What went wrong": st.column_config.TextColumn(
            width="large", help="First sentence of the suggested explanation."),
        "Checks": st.column_config.NumberColumn(
            format="%d", help="Failing checks grouped into this one problem."),
        "Findings": st.column_config.NumberColumn(
            format="%d", help="Rows x checks. A row failing three checks counts three."),
        "Approvals": st.column_config.TextColumn(help="Different people who approved, "
                                                      "against the number required."),
        "Age": st.column_config.NumberColumn(format="%d d", help="Days since raised."),
        "Priority": st.column_config.ProgressColumn(
            min_value=0, max_value=int(current["rank_score"].max()), format="%d",
            help="Ranking score: how serious, how far it spreads, and how much data it "
                 "touches.",
        ),
    },
)

st.caption(
    f"{len(view)} of {len(current)} problems · most urgent first. Tick a row to "
    "preview it, then open it."
)

# --- Are these problems actually getting resolved? ---------------------------
# These moved here from the Scorecard. Every one of them is a statement about
# cohorts, and a page about the health of the data is the wrong place to answer
# "is the team keeping up".


def _resolution_panel() -> None:
    theme.section("Resolution")
    st.caption(
        "Whether raised problems reach a recorded outcome, and whether fixes hold.",
        help="These are the spec's success metrics. They are only measurable because "
             "every decision is written to the register — detection alone cannot "
             "produce any of them.",
    )

    dispositions = adapter.get_dispositions()
    headline = [
        metrics.closure_rate(current),
        metrics.mttr(current, "P1_block"),
        metrics.disposition_coverage(current, dispositions),
        metrics.recurrence(current),
        metrics.recommendation_acceptance(current),
    ]
    for col, metric in zip(st.columns(len(headline)), headline):
        with col:
            components.metric_tile(metric)

    c1, c2 = st.columns([1.15, 1])
    with c1:
        funnel = metrics.triage_funnel(current)
        components.summary_table(
            funnel.rename(columns={"stage": "Stage", "cohorts": "Problems"})
        )
        st.caption(
            "Cumulative — a problem awaiting verification is counted at every stage it "
            "has already passed.",
            help="The drop from executed to closed verified is fixes that were reported "
                 "and did not hold.",
        )
    with c2:
        tally = (
            current["lifecycle_state"].value_counts()
            .reindex([s for s in lifecycle.LIFECYCLE_ORDER
                      if s in set(current["lifecycle_state"])])
        )
        components.summary_table(pd.DataFrame({
            "State": [theme.STATE_LABEL.get(s, s) for s in tally.index],
            "Problems": tally.values,
        }))

    findings = integrity.check(cohorts, dispositions)
    st.markdown(
        theme.badge(
            "Decision record: complete and consistent" if findings.empty
            else f"Decision record: {len(findings)} control failure(s)",
            "success" if findings.empty else "critical",
            "check" if findings.empty else "alert",
        ),
        unsafe_allow_html=True,
        help="The control test over the register (v_disposition_integrity): every "
             "approval has enough distinct approvers, nothing was executed without one, "
             "every human decision carries a platform identity, and every problem's "
             "chain was opened properly. Detail is on the Register page.",
    )


rows = selection["selection"]["rows"] if selection and "selection" in selection else []
if rows:
    picked = view.iloc[rows[0]]
    st.session_state["selected_cohort"] = picked["cohort_id"]

    st.divider()
    head, act = st.columns([5, 1])
    with head:
        components.cohort_headline(picked)
        st.markdown(f"**{detail.loc[picked['cohort_id'], 'root_cause_hypothesis']}**")
    with act:
        if st.button("Open", type="primary", width="stretch"):
            st.switch_page("dq_app/ui/pages/cohort_detail.py")

_resolution_panel()

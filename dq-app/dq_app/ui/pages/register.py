"""Disposition register — the audit artefact.

The spec's acceptance criterion: every cohort raised in a period is retrievable with
its full event chain, *including the ones nobody actioned and the reason why*. So the
default view is the whole period unfiltered, and cohorts with no human disposition are
listed explicitly rather than being absent. A register that quietly omits the ignored
cohorts answers the easy half of the question.

Nothing here can be edited. The table is `delta.appendOnly`, the app holds no UPDATE
grant, and a correction is a new event with a higher sequence number.
"""

from __future__ import annotations

import streamlit as st

from dq_app.data import adapter
from dq_app.domain import integrity, lifecycle
from dq_app.ui import components, theme

components.page_chrome()

st.title("Register")
st.caption(
    "Every decision taken on every problem, in the order it happened.",
    help="Append-only: nothing is ever updated or deleted, so a correction is a new "
         "entry rather than an edit, and the sequence itself is the evidence.",
)

events = adapter.get_dispositions()
current = adapter.get_cohort_current()
cohorts = adapter.get_cohorts()

min_ts, max_ts = events["event_ts"].min(), events["event_ts"].max()
f1, f2, f3 = st.columns([1.5, 1.5, 1.4])
with f1:
    period = st.date_input("Period", value=(min_ts.date(), max_ts.date()),
                           min_value=min_ts.date(), max_value=max_ts.date())
with f2:
    types = st.multiselect("Event type", lifecycle.EVENT_TYPES,
                           default=lifecycle.EVENT_TYPES,
                           format_func=str.capitalize)
with f3:
    actors = sorted(events["actor_display_name"].dropna().unique())
    who = st.multiselect("Actor", actors, default=actors)

start, end = (period if isinstance(period, tuple) and len(period) == 2
              else (min_ts.date(), max_ts.date()))
view = events[
    (events["event_ts"].dt.date >= start)
    & (events["event_ts"].dt.date <= end)
    & events["event_type"].isin(types)
    & events["actor_display_name"].isin(who)
].sort_values(["event_ts", "cohort_id", "event_seq"])

human = view[view["event_type"].isin(["reviewed", "approved", "executed"])]
components.kpi_row([
    {"label": "Entries", "value": f"{len(view):,}"},
    {"label": "Problems covered", "value": f"{view['cohort_id'].nunique()}"},
    {"label": "People and systems", "value": f"{view['actor_identity'].nunique()}"},
    {"label": "Made by a person", "value": f"{len(human):,}",
     "sub": "the rest by scheduled jobs",
     "help": "Reviews, approvals and reported actions. The remainder were written by "
             "the triage job or the daily check runner."},
])

theme.section("Decisions")

# Eighteen columns is the whole row, and the whole row is what an auditor eventually
# wants — but not on first read. Nine columns carry the story; the rest are one
# toggle away, and the CSV export always carries everything regardless.
PRIMARY = [
    "event_ts", "cohort_id", "event_seq", "event_type", "actor_display_name",
    "actor_source", "decision", "reason", "external_ref",
]
ALL_FIELDS = PRIMARY + [
    "actor_identity", "review_by_date", "approver_ordinal", "executed_summary",
    "verification_passed", "violations_before", "violations_after",
    "approach_type_taken", "app_version",
]

show_all = st.toggle("Show every field", value=False,
                     help="The full stored row. The CSV export includes it either way.")

# Missing text renders as the literal "None" in the grid, which reads as a value.
# Blank is the honest rendering of a field that was never set.
columns = ALL_FIELDS if show_all else PRIMARY
display = view[columns].copy()
for col in display.columns:
    if display[col].dtype == object:
        display[col] = display[col].where(display[col].notna(), "")

st.dataframe(
    display,
    width="stretch",
    hide_index=True,
    column_config={
        "event_ts": st.column_config.DatetimeColumn("When", format="YYYY-MM-DD HH:mm",
                                                    width="medium"),
        "cohort_id": st.column_config.TextColumn("Cohort", width="small"),
        "event_seq": st.column_config.NumberColumn("Seq", format="%d", width="small"),
        "event_type": st.column_config.TextColumn("Event", width="small"),
        "actor_display_name": st.column_config.TextColumn("Actor", width="small"),
        "actor_identity": st.column_config.TextColumn("Identity"),
        "actor_source": st.column_config.TextColumn(
            "Source", width="small",
            help="How the system knows who acted. obo_user is a platform-forwarded "
                 "identity; the rest are jobs. Anything else is a control failure.",
        ),
        "decision": st.column_config.TextColumn("Decision", width="small"),
        "reason": st.column_config.TextColumn("Reason", width="large"),
        "external_ref": st.column_config.TextColumn("Ref", width="small"),
        "executed_summary": st.column_config.TextColumn("Reported action", width="large"),
        "approach_type_taken": st.column_config.TextColumn("Approach"),
        "verification_passed": st.column_config.CheckboxColumn("Passed"),
    },
)

st.download_button(
    "Download period as CSV",
    view.to_csv(index=False).encode("utf-8"),
    file_name=f"dq_register_{start}_{end}.csv",
    mime="text/csv",
    icon=":material/download:",
    help="The rows above, unmodified, for an auditor who wants them outside the app.",
)

# --- Silence is a finding ----------------------------------------------------
theme.section("Problems nobody has decided on")
touched = set(events.loc[events["event_type"] != "recommended", "cohort_id"])
untouched = current[~current["cohort_id"].isin(touched)]
if untouched.empty:
    st.markdown(
        theme.badge("Every cohort carries a recorded decision", "success", "check"),
        unsafe_allow_html=True,
    )
else:
    st.caption(
        f"{len(untouched)} cohort(s) raised with nothing recorded — listed rather than "
        "omitted.",
        help="An auditor asking for every cohort in a period is entitled to the ones "
             "nobody actioned, and to the fact that nobody did.",
    )
    st.dataframe(
        untouched[["cohort_id", "severity", "lifecycle_state", "business_domain",
                   "owner_group", "member_count", "total_violation_rows", "raised_ts"]],
        width="stretch", hide_index=True,
    )

# --- Control test ------------------------------------------------------------
theme.section("Control test")
findings = integrity.check(cohorts, events)
if findings.empty:
    st.markdown(
        theme.badge("v_disposition_integrity returns zero rows", "success", "check"),
        unsafe_allow_html=True,
        help="Run over the whole register, not just the selected period — a control "
             "failure outside the window is still a control failure.",
    )
    with st.expander("What is being tested"):
        for name, why in integrity.FINDING_HELP.items():
            st.markdown(f"**{name}** — {why}")
else:
    st.markdown(
        theme.badge(f"{len(findings)} control failure(s)", "critical", "alert"),
        unsafe_allow_html=True,
    )
    st.dataframe(findings, width="stretch", hide_index=True)
    for f in findings["finding"].unique():
        st.caption(f"**{f}** — {integrity.FINDING_HELP.get(f, '')}")

st.caption(
    "This is a detective control, not a preventive one.",
    help="It records that named people approved and that someone reported executing. "
         "It cannot prevent execution without approval, nor prove that what ran matched "
         "what was approved, because execution happens outside this system by design. "
         "Preventive enforcement for regulated data belongs in change management, "
         "pipeline CI and production grants.",
)

"""Cohort detail — the evidence, the advice, the chain, and the one place a steward
adds to the record.

Tab order follows what a steward has to do: confirm or discard the hypothesis
(Evidence), decide whether the proposed approach fits (Recommendation), then record
the decision (Register). Acting before reading the evidence is the failure mode this
ordering exists to discourage.

Nothing here executes anything. `executed` records a claim that a person acted in
their own pipeline, outside this system — the spec's step 04, and the reason the
register is a detective control rather than a preventive one.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from dq_app.data import adapter
from dq_app.domain import lifecycle
from dq_app.ui import components, theme
from dq_app.ui.components import as_list, opt

components.page_chrome()

current = adapter.get_cohort_current()
cohorts = adapter.get_cohorts()

# The queue links here with ?cohort=<id>. A URL that names what it shows is worth
# having: it can be pasted into a ticket, and it survives a reload.
known = set(current["cohort_id"])
selected = st.query_params.get("cohort") or st.session_state.get("selected_cohort")
if selected not in known:
    selected = None

picker = current["cohort_id"].tolist()


def _label(cid: str) -> str:
    r = current[current["cohort_id"] == cid].iloc[0]
    return (
        f"{theme.SEVERITY_SHORT.get(r['severity'], r['severity'])} · "
        f"{theme.STATE_LABEL.get(r['lifecycle_state'], r['lifecycle_state'])} · {cid[:8]}"
    )


chosen = st.sidebar.selectbox(
    "Cohort", picker, index=picker.index(selected) if selected else 0,
    format_func=_label, key="_cohort_picker",
)
st.session_state["selected_cohort"] = chosen
if st.query_params.get("cohort") not in (None, chosen):
    # The picker wins over a stale query string, so the URL keeps up with the page.
    st.query_params["cohort"] = chosen

row = current[current["cohort_id"] == chosen].iloc[0]
extra = cohorts[cohorts["cohort_id"] == chosen].iloc[0]
events = adapter.get_dispositions()
events = events[events["cohort_id"] == chosen].sort_values("event_seq")

st.title(f"Cohort {chosen[:8]}")
st.caption(
    theme.COHORT_ONE_LINER,
    help="Everything on this page belongs to one problem: the breaches grouped into "
         "it, the hypothesis explaining them, the approach recommended, and the chain "
         "of decisions recorded against it.",
)
components.cohort_headline(row)

components.kpi_row([
    {"label": "Failing checks", "value": f"{int(row['member_count'])}",
     "sub": "grouped into this problem"},
    {"label": "Findings", "value": f"{int(row['total_violation_rows']):,}",
     "sub": "rows × checks",
     "help": "One finding is one row failing one check, so a row failing three checks "
             "counts three times."},
    {"label": "Tables", "value": f"{len(as_list(row['affected_tables']))}",
     "sub": f"{int(extra['blast_radius_count'])} more downstream"},
    {"label": "Approvals", "value":
     f"{int(row['distinct_approvers'])}/{int(row['approvals_required'])}",
     "sub": "different people",
     "help": "The same person approving twice does not count — the requirement is on "
             "distinct named approvers."},
    {"label": "Raised", "value": f"{row['raised_ts']:%d %b}",
     "sub": f"{(pd.Timestamp.now() - row['raised_ts']).days}d ago"},
])
st.caption(
    f"{row['business_domain']} · {row['owner_group']} · run {extra['raised_run_id'][:8]} · "
    f"rank {int(row['rank_score'])}"
)

tab_ev, tab_rec, tab_reg, tab_blast, tab_raw = st.tabs(
    ["Evidence", "Suggested fix", "Decisions", "Impact", "Stored record"]
)

# --- Evidence ---------------------------------------------------------------
with tab_ev:
    st.markdown(f"**{extra['root_cause_hypothesis']}**")
    st.caption(
        extra["evidence_summary"],
        help="The hypothesis is the agent's; this is the profiling it ran. Confirm or "
             "discard it against the numbers below rather than against the prose.",
    )

    theme.section("The checks that are failing")
    components.member_rule_table(
        extra, adapter.get_rule_registry_current(), adapter.get_check_runs()
    )

    theme.section("Examples of the bad data")
    components.violation_samples_view(
        extra, adapter.get_violation_samples(), adapter.get_check_runs()
    )

# --- Recommendation ---------------------------------------------------------
with tab_rec:
    components.recommendation_view(extra, adapter.get_playbook())

    if opt(row["approach_type_taken"]):
        theme.section("What was done")
        followed = row["recommendation_followed"]
        st.markdown(
            theme.badge(theme.approach_label(row["approach_type_taken"]), "neutral")
            + " "
            + (
                theme.badge("Followed the recommendation", "success", "check")
                if followed
                else theme.badge("Diverged", "moderate")
            ),
            unsafe_allow_html=True,
            help="Divergence is not a failure — it is the signal the acceptance metric "
                 "collects. A recommendation stewards keep overriding is one to change.",
        )

# --- Register ---------------------------------------------------------------
with tab_reg:
    left, right = st.columns([3, 2])

    with left:
        theme.section(f"Decision history · {len(events)} entries")
        components.event_timeline(events)
        st.caption(
            "Append-only.",
            help="A correction is a new row with a higher sequence number, never an "
                 "edit — so what you see is what happened, including anything since "
                 "superseded.",
        )

    with right:
        components.approval_gate_view(row, events)

        theme.section("Add a decision")
        allowed = lifecycle.available_events(
            row["lifecycle_state"], int(row["distinct_approvers"]), int(row["approvals_required"])
        )

        if not allowed:
            if row["lifecycle_state"] == "awaiting_verification":
                st.caption(
                    "Nothing to record — the next scheduled check run decides this one.",
                    help="There is no re-check job and no way to mark a cohort verified "
                         "by hand. Closure is never self-certified.",
                )
            else:
                st.caption(f"No further in-app event applies to a "
                           f"{theme.STATE_LABEL.get(row['lifecycle_state'], '')} cohort.")
        else:
            event_type = allowed[0]

            if event_type == "reviewed":
                with st.form("review_form", border=False):
                    decision = st.radio(
                        "Decision", lifecycle.DECISIONS,
                        format_func=lambda d: {
                            "accepted": "Accept — the hypothesis holds",
                            "deferred": "Defer — real, but not now",
                            "rejected": "Reject — the cohort is wrong",
                            "no_action": "No action — accepted as-is",
                        }[d],
                    )
                    reason = st.text_area(
                        "Reason", placeholder="What you checked and what convinced you.",
                        help="Required for defer and reject — enforced here and by a "
                             "CHECK constraint on the table.",
                    )
                    review_by = st.date_input("Review by", value=date.today() + timedelta(days=30),
                                              help="Deferrals only.")
                    if st.form_submit_button("Append to register", type="primary"):
                        try:
                            adapter.append_disposition(
                                chosen, "reviewed", decision=decision, reason=reason or None,
                                review_by_date=review_by if decision == "deferred" else None,
                            )
                            st.rerun()
                        except adapter.WriteRejected as exc:
                            st.error(str(exc), icon=":material/block:")

            elif event_type == "approved":
                st.caption(
                    "Approval authorises a person to act. It runs nothing.",
                    help="There is no execute button in this app by design — the value "
                         "is in diagnosis, and an app that can modify billing data is a "
                         "control question that would gate the whole programme.",
                )
                if st.button("Approve", type="primary"):
                    try:
                        adapter.append_disposition(chosen, "approved")
                        st.rerun()
                    except adapter.WriteRejected as exc:
                        st.error(str(exc), icon=":material/block:")

            elif event_type == "executed":
                with st.form("execute_form", border=False):
                    st.caption(
                        "A self-reported claim.",
                        help="The register states that you reported doing this, and "
                             "when. It does not assert the system observed it — the "
                             "next check run tests whether it worked.",
                    )
                    summary = st.text_area("What was done",
                                           placeholder="Change, pipeline, window.")
                    ref = st.text_input("External reference", placeholder="CRM-4821")
                    taken = st.selectbox(
                        "Approach taken", lifecycle.APPROACH_TYPES,
                        index=lifecycle.APPROACH_TYPES.index(row["recommended_approach_type"])
                        if row["recommended_approach_type"] in lifecycle.APPROACH_TYPES else 0,
                        format_func=theme.approach_label,
                        help="Pre-set to the recommendation. Change it if you did "
                             "something else — that divergence is the acceptance metric.",
                    )
                    if st.form_submit_button("Append to register", type="primary"):
                        try:
                            adapter.append_disposition(
                                chosen, "executed", executed_summary=summary or None,
                                external_ref=ref or None, approach_type_taken=taken,
                                playbook_id=opt(extra.get("playbook_id")),
                            )
                            st.rerun()
                        except adapter.WriteRejected as exc:
                            st.error(str(exc), icon=":material/block:")

# --- Blast radius -----------------------------------------------------------
with tab_blast:
    components.blast_radius_view(extra)
    st.caption(
        "Blast radius is what makes a cohort rankable.",
        help="Two cohorts with equal violation counts are not equally urgent if one "
             "feeds billing and the other feeds a dormant mart.",
    )

# --- Raw record -------------------------------------------------------------
with tab_raw:
    st.caption("Every field as stored, unedited. The views above are a convenience; "
               "this is the record.")
    theme.section("results.cohort")
    # Stringified: one row transposed puts timestamps, arrays and strings in a single
    # column and Arrow has no type for that. The raw view is showing what is stored,
    # not computing on it.
    st.dataframe(extra.astype(str).to_frame("value"), width="stretch")
    theme.section("results.disposition")
    st.dataframe(events, width="stretch", hide_index=True)
    theme.section("v_cohort_current · derived, stored nowhere")
    st.dataframe(row.astype(str).to_frame("value"), width="stretch")

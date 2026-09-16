"""Problem detail — the reasoning, the evidence, and the decision log.

Three blocks, in the order a steward works, and each one labelled with what kind of
claim it is making:

  * **What we think is wrong** — the model's claim, marked as one. A hypothesis and
    the profiling behind it, then the approach recommended.
  * **What we're going by** — measured. The failing checks and the rows that failed.
  * **What was decided** — the append-only chain, and the one control in this app
    that writes anything.

This was five tabs until 2026-09-16: Evidence, Suggested fix, Decisions, Impact,
Stored record. Tabs made a reader choose an order before they knew what was in each
one, and the ordering the tabs implied — evidence first, decision last — was the
right one, so it is now simply the order of the page. *Impact* collapsed into the
facts line and an expander inside the first block; *Stored record* is a disclosure at
the foot, which is where a record nobody reads on the happy path belongs.

Nothing here executes anything. `executed` records a claim that a person acted in
their own pipeline, outside this system — the spec's step 04, and the reason the
register is a detective control rather than a preventive one.

Not in the sidebar. This page means nothing without a selection, so it is reached
from Triage and is registered in `app.py` only so `st.switch_page` can find it.
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

# Triage links here with ?cohort=<id>. A URL that names what it shows is worth having:
# it can be pasted into a ticket, and it survives a reload.
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
    "Problem", picker, index=picker.index(selected) if selected else 0,
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


def _title(hypothesis: str) -> str:
    """The problem as a phrase a person would say, taken from the hypothesis.

    The model already writes the sentence; this takes its first clause. There is no
    stored title column and adding one is a fixture and DDL change, not a UI one — so
    the id stays visible beside this, and it is the id that goes in a ticket.
    """
    first = str(hypothesis).split(".")[0].strip()
    return first if len(first) <= 90 else first[:87].rstrip(" ,;") + "…"


# --- Header -----------------------------------------------------------------

if st.button("← Triage", key="_back"):
    st.switch_page("dq_app/ui/pages/triage.py")

head, gate = st.columns([4, 1.1], vertical_alignment="top")
with head:
    st.title(_title(extra["root_cause_hypothesis"]))
    components.cohort_headline(row)
with gate:
    st.markdown(
        '<div class="dq-quiet" style="text-align:right">approvals<br>'
        f'<b style="font-size:1.1rem;color:{theme.NEUTRAL["text"]}">'
        f'{int(row["distinct_approvers"])} of {int(row["approvals_required"])}</b>'
        "</div>",
        unsafe_allow_html=True,
        help="Different named people. The same person approving twice does not count.",
    )

# One line where five tiles used to be. Everything on it is a fact about the problem
# that a reader needs in order to place it, and none of it is a figure anyone tracks.
st.caption(
    f"`{chosen[:8]}` · {row['business_domain']} · {row['owner_group']} · raised "
    f"{row['raised_ts']:%d %b} ({(pd.Timestamp.now() - row['raised_ts']).days}d ago) · "
    f"{int(row['member_count'])} failing checks · "
    f"{int(row['total_violation_rows']):,} findings · "
    f"{len(as_list(row['affected_tables']))} table(s), "
    f"{int(extra['blast_radius_count'])} more downstream · rank {int(row['rank_score'])}",
    help="Findings are rows × checks: a row failing three checks counts three times. "
         "Rank is how serious, how far it spreads, and how much data it touches — "
         "advisory, and never a severity.",
)

# --- 1. What we think is wrong ----------------------------------------------

with st.container(border=True):
    st.markdown(
        '<div class="dq-blockhd"><b>WHAT WE THINK IS WRONG</b>'
        + theme.badge(
            "generated · a model claim" if row["recommendation_source"] == "generated"
            else "from the playbook",
            "moderate" if row["recommendation_source"] == "generated" else "neutral",
        )
        + "</div>",
        unsafe_allow_html=True,
    )
    st.markdown(f"**{extra['root_cause_hypothesis']}**")
    st.markdown(
        f'<div class="dq-because"><b>Because:</b> {extra["evidence_summary"]}</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Confirm or discard this against the numbers in the next block rather than "
        "against the prose.",
    )

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

    with st.expander(
        f"What else reads these tables · {int(extra['blast_radius_count'])} downstream"
    ):
        components.blast_radius_view(extra)
        st.caption(
            "Blast radius is what makes a problem rankable.",
            help="Two problems with equal violation counts are not equally urgent if "
                 "one feeds billing and the other feeds a dormant mart.",
        )

# --- 2. What we're going by --------------------------------------------------

with st.container(border=True):
    st.markdown(
        '<div class="dq-blockhd"><b>WHAT WE\'RE GOING BY</b>'
        + theme.badge("measured", "neutral")
        + "</div>",
        unsafe_allow_html=True,
    )

    theme.section("The checks that are failing")
    components.member_rule_table(
        extra, adapter.get_rule_registry_current(), adapter.get_check_runs()
    )

    theme.section("The rows that failed")
    components.violation_samples_view(
        extra, adapter.get_violation_samples(), adapter.get_check_runs()
    )

# --- 3. What was decided -----------------------------------------------------

with st.container(border=True):
    st.markdown(
        '<div class="dq-blockhd"><b>WHAT WAS DECIDED</b>'
        + theme.badge(f"{len(events)} entries · append-only", "neutral")
        + "</div>",
        unsafe_allow_html=True,
    )

    left, right = st.columns([3, 2])

    with left:
        components.event_timeline(events)
        st.caption(
            "Append-only.",
            help="A correction is a new row with a higher sequence number, never an "
                 "edit — so what you see is what happened, including anything since "
                 "superseded.",
        )

    with right:
        components.approval_gate_view(row, events)

        theme.section("Record a decision")
        # `available_events` decides what may be authored from this state, and it
        # never offers `verified` to anyone: closure is the check runner's to declare.
        allowed = lifecycle.available_events(
            row["lifecycle_state"], int(row["distinct_approvers"]), int(row["approvals_required"])
        )

        if not allowed:
            if row["lifecycle_state"] == "awaiting_verification":
                st.caption(
                    "Nothing to record — the next scheduled check run decides this one.",
                    help="There is no re-check job and no way to mark a problem verified "
                         "by hand. Closure is never self-certified.",
                )
            else:
                st.caption(f"No further in-app event applies to a "
                           f"{theme.STATE_LABEL.get(row['lifecycle_state'], '')} problem.")
        else:
            event_type = allowed[0]

            if event_type == "reviewed":
                with st.form("review_form", border=False):
                    decision = st.radio(
                        "Decision", lifecycle.DECISIONS,
                        format_func=lambda d: {
                            "accepted": "Accept — the hypothesis holds",
                            "deferred": "Defer — real, but not now",
                            "rejected": "Reject — the grouping is wrong",
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

# --- The record, for the reader who wants the fields --------------------------

with st.expander("Stored record — every field as stored, unedited"):
    st.caption("The blocks above are a convenience; this is the record.")
    theme.section("results.cohort")
    # Stringified: one row transposed puts timestamps, arrays and strings in a single
    # column and Arrow has no type for that. The raw view is showing what is stored,
    # not computing on it.
    st.dataframe(extra.astype(str).to_frame("value"), width="stretch")
    theme.section("results.disposition")
    st.dataframe(events, width="stretch", hide_index=True)
    theme.section("v_cohort_current · derived, stored nowhere")
    st.dataframe(row.astype(str).to_frame("value"), width="stretch")

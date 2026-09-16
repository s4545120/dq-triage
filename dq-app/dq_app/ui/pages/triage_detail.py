"""Problem detail — what state this is in, and everything behind it.

**Two things sit above the tabs and are visible on all of them:** the header, and a
state strip naming whose turn it is with the one event this state permits. Everything
else is reading, and reading is what the tabs hold:

  * **Why we think this** — the model's claim, marked as one, and the approach
    recommended for it.
  * **Evidence** — the failing checks, and the rows behind whichever one you click.
  * **Decisions** — the append-only chain and the approval gate.
  * **Stored record** — every field as stored, for the reader who wants the fields.

**This had five tabs until 2026-09-16 and none between then and 2026-09-17.** The
objection to the first set — Evidence, Suggested fix, Decisions, Impact, Stored record
— was that they made a reader choose an order before knowing what was in each, and
that the decision was buried inside one of them. Both are answered here rather than
avoided: every tab carries its count, so the label says what is behind it, and nothing
you have to *act on* is inside a tab. *Impact* stayed dissolved — blast radius is one
line at the foot of the first tab and a phrase in the header. It never earned a tab.

**Evidence is master–detail.** The page used to print a sample table per failing
check, one after another — nine of them for COH-A. The checks are now one short table
and the rows appear for the check you select. Same rows, same cap, same grants.

Nothing here executes anything. `executed` records a claim that a person acted in
their own pipeline, outside this system — the spec's step 04, and the reason the
register is a detective control rather than a preventive one.

Not in the sidebar. This page means nothing without a selection, so it is reached
from Triage and is registered in `app.py` only so `st.switch_page` can find it.
"""

from __future__ import annotations

import html
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from dq_app.data import adapter
from dq_app.domain import lifecycle
from dq_app.ui import components, theme
from dq_app.ui.components import as_list, opt

# --- The state strip --------------------------------------------------------
# What the strip says, and how loudly. The tone is a second channel only: every
# variant states its outcome in words, because colour never carries meaning alone in
# this app.

STRIP_TONE = {
    "reopened": "critical",
    "awaiting_review": "high",
    "awaiting_approval": "moderate",
    "approved_awaiting_execution": "info",
    "awaiting_verification": "neutral",
    "awaiting_triage": "high",
    "deferred": "neutral",
    "closed_verified": "success",
    "closed_rejected": "neutral",
    "closed_no_action": "neutral",
}

ACTION_LABEL = {
    "reviewed": "Record a review",
    "approved": "Approve",
    "executed": "Record what was done",
}

# Said where there is nothing to author, because "no button" is not an explanation.
NOTHING_TO_DO = {
    "awaiting_verification": "Nothing to record — the next scheduled check run decides "
                             "this one. Closure is never self-certified.",
    "closed_verified": "Closed. The next run passed for every member rule.",
    "closed_rejected": "Closed. The reason is in the chain.",
    "closed_no_action": "Closed with no action. The reason is in the chain.",
}


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
state = row["lifecycle_state"]

# --- Header -----------------------------------------------------------------

back, _ = st.columns([1, 5])
with back:
    if st.button("← Triage", key="_back", width="stretch"):
        st.switch_page("dq_app/ui/pages/triage.py")

age = (pd.Timestamp.now() - row["raised_ts"]).days
st.markdown(
    '<div class="dq-page-hd" style="margin-bottom:.2rem">'
    f'<div class="t">{html.escape(components.problem_title(extra["root_cause_hypothesis"], 110))}'
    "</div>"
    '<div class="dq-factline">'
    + theme.severity_badge(row["severity"])
    + theme.badge(theme.STATE_LABEL.get(state, state), theme.STATE_TONE.get(state, "neutral"))
    + f'<span>{html.escape(str(row["business_domain"]))}</span><i>·</i>'
    f'<code>{html.escape(str(row["owner_group"]))}</code><i>·</i>'
    f'<span>raised {row["raised_ts"]:%-d %b}, {age} days ago</span><i>·</i>'
    f'<span><b>{int(row["member_count"])}</b> failing checks</span><i>·</i>'
    f'<span><b>{int(row["total_violation_rows"]):,}</b> findings</span><i>·</i>'
    f'<span>{len(as_list(row["affected_tables"]))} tables, '
    f'{int(extra["blast_radius_count"])} downstream</span><i>·</i>'
    f'<code>{html.escape(chosen[:8])}</code>'
    "</div></div>",
    unsafe_allow_html=True,
)

# --- The state strip: whose turn, and the one event this state permits -------
# Above the tabs, deliberately. The objection to the old five tabs was not that tabs
# are bad — it was that the decision lived inside one of them.

allowed = lifecycle.available_events(
    state, int(row["distinct_approvers"]), int(row["approvals_required"])
)
# The last reason anyone WROTE, not `row["latest_reason"]` — that one travels with
# `latest_decision`, so on a reopened problem it quotes the review that accepted it
# under a headline saying verification failed. The check runner's reopen reason is
# the one that explains the state the strip is announcing.
_with_reason = events[events["reason"].notna()]
latest_reason = str(_with_reason.iloc[-1]["reason"]) if not _with_reason.empty else None
if latest_reason and len(latest_reason) > 210:
    # On a word boundary, with the ellipsis that says it was cut. A hard slice ended
    # the strip mid-word and ran the next clause straight into the stump.
    latest_reason = latest_reason[:210].rsplit(" ", 1)[0].rstrip(" ,;.") + "…"
tone = STRIP_TONE.get(state, "neutral")

# The tinted box is markup, not a Streamlit container, and the button is positioned
# over it rather than laid out beside it. Both are deliberate. Every Streamlit wrapper
# between a container and a markdown block measures that markdown for itself, and with
# the sentence here wrapping to three lines they settled on the height of one — which
# clipped the gate line off the bottom edge, and stayed clipped through every display,
# flex and height override tried on those wrappers. Drawing the box myself means the
# only element sizing it is one I wrote; taking the button out of flow means nothing
# else can size it either.
_tint = theme.TONE[tone]
with st.container(key="dq_strip"):
    st.markdown(
        # The button's lane is reserved only when there is a button. A closed problem
        # has nothing to author, and a 13rem gutter of nothing reads as a missing
        # control rather than as an absent one.
        f'<div class="dq-strip-box{" has-action" if allowed else ""}" '
        f'style="background:{_tint["bg"]};border-color:{_tint["bd"]}">'
        '<div class="dq-strip-said">'
        f'<b>{html.escape(theme.STATE_MEANING.get(state, str(state)))}.</b> '
        + (f'{html.escape(latest_reason)} ' if latest_reason else "")
        + (f'Next move is <b>{html.escape(components.waiting_on(row))}</b>.'
           if allowed or state not in NOTHING_TO_DO
           else html.escape(NOTHING_TO_DO[state]))
        + "</div>"
        '<div class="dq-strip-gate">'
        f'approvals {int(row["distinct_approvers"])} of '
        f'{int(row["approvals_required"])}'
        + (f' · reopened ×{int(row["reopen_count"])}' if int(row["reopen_count"]) else "")
        + "</div></div>",
        unsafe_allow_html=True,
    )
    if allowed and st.button(ACTION_LABEL.get(allowed[0], "Record a decision"),
                             key="_decide_btn", type="primary"):
        st.session_state["_decide_open"] = True
        st.rerun()

# --- The reading, in four tabs ----------------------------------------------
# Counts in the labels, so a reader knows what is behind a tab before opening it.

why_tab, evidence_tab, decisions_tab, record_tab = st.tabs([
    "Why we think this",
    f"Evidence · {int(row['member_count'])}",
    f"Decisions · {len(events)}",
    "Stored record",
])

with why_tab:
    st.markdown(
        '<div class="dq-blockhd"><b>THE CLAIM</b>'
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
        f'<div class="dq-because"><b>Because:</b> {html.escape(str(extra["evidence_summary"]))}'
        "</div>",
        unsafe_allow_html=True,
    )
    st.caption("Confirm or discard this against the numbers in Evidence rather than "
               "against the prose.")

    theme.section("What to do about it")
    components.recommendation_view(extra, adapter.get_playbook())

    if opt(row["approach_type_taken"]):
        st.markdown(
            '<div class="dq-kvline"><span class="k">What was done:</span> '
            + theme.badge(theme.approach_label(row["approach_type_taken"]), "neutral")
            + " "
            + (theme.badge("Followed the recommendation", "success", "check")
               if row["recommendation_followed"] else theme.badge("Diverged", "moderate"))
            + "</div>",
            unsafe_allow_html=True,
        )
        st.caption(
            "Divergence is not a failure — it is the signal the acceptance metric "
            "collects. A recommendation stewards keep overriding is one to change.")

    # Impact, dissolved. One line, where it is read — not a tab of its own.
    theme.section(f"What else reads these tables · {int(extra['blast_radius_count'])} downstream")
    components.blast_radius_view(extra)
    st.caption("Blast radius is what makes a problem rankable.",
               help="Two problems with equal violation counts are not equally urgent if "
                    "one feeds billing and the other feeds a dormant mart.")

with evidence_tab:
    runs = adapter.get_check_runs()
    registry = adapter.get_rule_registry_current()
    members = as_list(extra["member_rule_ids"])
    reg = registry.set_index("rule_id")
    latest_run = runs.loc[runs["run_ts"].idxmax(), "run_id"]
    now = runs[(runs["run_id"] == latest_run) & (runs["rule_id"].isin(members))].set_index("rule_id")

    mem_rows = []
    for rid in members:
        r = reg.loc[rid] if rid in reg.index else None
        c = now.loc[rid] if rid in now.index else None
        hist = runs[(runs["rule_id"] == rid)
                    & runs["status"].isin(["pass", "breach"])].sort_values("run_ts")
        statuses, stamps = list(hist["status"]), list(hist["run_ts"])
        i = len(statuses) - 1
        while i > 0 and statuses[i - 1] == "breach":
            i -= 1
        mem_rows.append({
            "Rule id": rid,
            "Check": rid if r is None else str(r["rule_name"]),
            "Where": ("—" if r is None else
                      (str(r["target_column"]) if opt(r["target_column"])
                       else str(r["target_table"]).split(".")[-1] + " ↔")),
            "Severity": "—" if r is None else r["severity"],
            "Bad rows": 0 if c is None else int(c["violation_count"]),
            "Of": 0 if c is None else int(c["rows_scanned"]),
            "First seen": f"{stamps[i]:%-d %b}" if i > 0 else "always",
            "Applies to": ("every row" if r is None or opt(r["scope_filter"]) is None
                           else str(r["scope_filter"])),
        })
    mem_rows.sort(key=lambda m: -m["Bad rows"])

    MEM_GRID = ("minmax(9rem,1fr) minmax(5rem,9rem) 3.2rem 4.6rem 4.4rem "
                "minmax(3.5rem,5rem)")

    def _mem_cells(m) -> str:
        return (
            f'<span class="name" title="{html.escape(m["Check"])}">'
            f'{html.escape(m["Check"])}</span>'
            f'<span class="mono" title="{html.escape(m["Applies to"])}">'
            f'{html.escape(m["Where"])}</span>'
            + (f'<span>{theme.severity_badge(m["Severity"], words=False)}</span>'
               if m["Severity"] != "—" else "<span></span>")
            + f'<span class="num">{m["Bad rows"]:,}</span>'
            f'<span class="of">{m["Of"]:,}</span>'
            f'<span class="of" style="text-align:left">{html.escape(m["First seen"])}</span>'
        )

    picked_member = st.session_state.get("_member_pick")
    if picked_member not in members:
        picked_member = mem_rows[0]["Rule id"] if mem_rows else None

    components.row_head(
        ["Check", "Where", "Sev", ("Bad rows", "n"), ("Of", "n"), "First seen"], MEM_GRID)
    with st.container(key="dqrows_members"):
        got = components.clickable_rows(
            mem_rows, MEM_GRID, _mem_cells, "mem", "Rule id",
            lambda m: f"Show the rows that failed {m['Check']}", picked=picked_member)
    if got:
        st.session_state["_member_pick"] = got
        st.rerun()

    # The rows behind the check selected above. One panel, not nine stacked expanders.
    samples = adapter.get_violation_samples()
    mine = samples[samples["rule_id"] == picked_member]
    chosen_row = next((m for m in mem_rows if m["Rule id"] == picked_member), None)
    theme.section("The rows that failed")
    if chosen_row is None or mine.empty:
        st.caption("No rows were sampled for this check. Historical breaches carry "
                   "counts only.")
    else:
        newest = mine[mine["run_id"] == mine["run_id"].iloc[-1]] if len(mine) else mine
        st.caption(
            f"**{chosen_row['Check']}** — {len(newest):,} of "
            f"{chosen_row['Bad rows']:,} captured"
            + (" · a sample, not the set." if len(newest) < chosen_row["Bad rows"] else "."),
            help="The one accepted PII surface in this design. Same rows, same cap and "
                 "same grants as before — what changed is that you see one check's "
                 "rows at a time instead of every check's stacked down the page.",
        )
        components.sample_rows_view(newest)

with decisions_tab:
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

with record_tab:
    st.caption("The tabs above are a convenience; this is the record.")
    theme.section("results.cohort")
    # Stringified: one row transposed puts timestamps, arrays and strings in a single
    # column and Arrow has no type for that. The raw view is showing what is stored,
    # not computing on it.
    st.dataframe(extra.astype(str).to_frame("value"), width="stretch")
    theme.section("results.disposition")
    st.dataframe(events, width="stretch", hide_index=True)
    theme.section("v_cohort_current · derived, stored nowhere")
    st.dataframe(row.astype(str).to_frame("value"), width="stretch")

# --- Recording a decision ----------------------------------------------------
# In a drawer, so it is reachable from every tab and never pushes the reading down
# the page. Still the only control in this app that writes anything, and it still
# writes only to the register.

if st.session_state.get("_decide_open") and allowed:
    with st.container(key="dq_decide_drawer"):
        head, close = st.columns([5, 1], vertical_alignment="center")
        with head:
            st.markdown(
                '<div class="dq-dim-panel-hd">'
                f'<span class="t">{html.escape(ACTION_LABEL.get(allowed[0], "Record a decision"))}'
                "</span>"
                + theme.badge("appends to the register", "info")
                + "</div>",
                unsafe_allow_html=True,
            )
        if close.button("Close", key="_decide_close", width="stretch"):
            st.session_state["_decide_open"] = False
            st.rerun()

        st.markdown(
            f'<div class="dq-because">This problem is '
            f'<b>{html.escape(theme.STATE_LABEL.get(state, state))}</b>, so '
            f'<b>{html.escape(ACTION_LABEL.get(allowed[0], allowed[0]))}</b> is the one '
            "event you can author. What is offered is decided by "
            "<code>lifecycle.available_events</code>, and it never offers "
            "<code>verified</code> to anyone: closure is the check runner's to "
            "declare.</div>",
            unsafe_allow_html=True,
        )

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
                        st.session_state["_decide_open"] = False
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
            if st.button("Approve", type="primary", key="_approve"):
                try:
                    adapter.append_disposition(chosen, "approved")
                    st.session_state["_decide_open"] = False
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
                        st.session_state["_decide_open"] = False
                        st.rerun()
                    except adapter.WriteRejected as exc:
                        st.error(str(exc), icon=":material/block:")

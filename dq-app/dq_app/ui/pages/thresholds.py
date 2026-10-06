"""Thresholds — the detection limits, as advised, and the decisions on the advice.

Every rule has a `fail_threshold_pct`: the line between normal variation and a
breach. The threshold job (`notebooks/06_suggest_thresholds.ipynb`) advises on where
that line should be, once per rule per pass, from two things the page shows side by
side: the tolerance the CDE register declares on the element the rule monitors, which
is a ceiling the advice may never exceed, and where the violation rate has sat across
the run history. This page puts each rule's latest proposal to its reviewer.

**Detection, not triage.** Nothing here reads a cohort or the disposition register,
and nothing on the Triage pages reads this. A limit is a property of a rule; a
problem is a property of a run.

**The decision is the app's third write, and adoption is also its second.** Adopting
appends a `rule_version` to the registry carrying the proposed limit — the same
append that promotes a shadow rule — and records which version on
`results.threshold_review`. Rejecting and deferring write the review row only.
Nothing here changes a threshold without a person's name on the row that did it.

Same shape as Triage: a clickable table, one row per rule, and a panel for the row
picked. `_thr_pick` holds the selection.
"""

from __future__ import annotations

import html
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from dq_app.data import adapter
from dq_app.domain import thresholds
from dq_app.ui import components, theme
from dq_app.ui.components import opt

components.page_chrome()

st.title("Thresholds")

current = adapter.get_threshold_proposal_current()
cdes = adapter.get_cde_registry_current()
cde_name = dict(zip(cdes["cde_id"], cdes["cde_name"])) if len(cdes) else {}

if current.empty:
    st.caption(
        "No threshold proposals yet.",
        help="The threshold job has not run against this catalog. It writes one "
             "proposal per rule per pass to results.threshold_proposal; this page "
             "shows the latest per rule and the decision on it.",
    )
    st.stop()

# --- The counts --------------------------------------------------------------
s = thresholds.summary(current)
components.kpi_row([
    {"label": "Awaiting review", "value": f"{s['open']}", "tone": "high" if s["open"] else None,
     "help": "A proposal that moves a limit and that nobody has decided."},
    {"label": "Deferred", "value": f"{s['deferred']}", "sub": "with a review-by date"},
    {"label": "Adopted", "value": f"{s['adopted']}", "sub": "new rule version appended"},
    {"label": "Rejected", "value": f"{s['rejected']}"},
    {"label": "Keep as is", "value": f"{s['no_change']}",
     "help": "The advice was to keep the current limit, with the reason stated. "
             "Nothing to decide."},
    {"label": "Rules advised", "value": f"{s['proposals']}",
     "sub": f"latest pass {current['proposed_ts'].max():%-d %b}"},
])

# --- The table -----------------------------------------------------------------
STATE_ORDER = {st_: i for i, st_ in enumerate(
    ["open", "deferred", "in_force", "adopted", "rejected", "no_change"])}
view = current.assign(_o=current["review_state"].map(STATE_ORDER)) \
              .sort_values(["_o", "rule_id"])

rows = []
for _, r in view.iterrows():
    rows.append({
        "Proposal id": r["proposal_id"],
        "Check": opt(r["rule_name"]) or r["rule_id"],
        "Rule id": r["rule_id"],
        "Element": cde_name.get(r["cde_id"], r["cde_id"]),
        "Now": float(r["current_threshold_pct"]),
        "Proposed": float(r["proposed_threshold_pct"]),
        "Basis": str(r["basis"]),
        "State": str(r["review_state"]),
        "Reviewer": str(r["reviewer"]),
    })

GRID = ("minmax(9rem,1.3fr) minmax(7rem,1fr) 3.4rem 4.4rem minmax(6.5rem,8.5rem) "
        "minmax(6.5rem,8rem) minmax(7rem,9rem)")


def _cells(m) -> str:
    moved = m["Basis"] != "unchanged"
    return (
        f'<span class="name" title="{html.escape(m["Rule id"])}">{html.escape(m["Check"])}</span>'
        f'<span>{html.escape(m["Element"])}</span>'
        f'<span class="num">{m["Now"]:g}%</span>'
        f'<span class="num">{"<b>" if moved else ""}{m["Proposed"]:g}%{"</b>" if moved else ""}</span>'
        f'<span>{theme.badge(theme.THRESHOLD_BASIS_LABEL.get(m["Basis"], m["Basis"]), theme.THRESHOLD_BASIS_TONE.get(m["Basis"], "neutral"))}</span>'
        f'<span>{theme.badge(theme.THRESHOLD_STATE_LABEL.get(m["State"], m["State"]), theme.THRESHOLD_STATE_TONE.get(m["State"], "neutral"))}</span>'
        f'<span class="mono">{html.escape(m["Reviewer"])}</span>'
    )



# From here down is one fragment: picking a proposal redraws the list, the proposal
# and its decision form, not the figures above, which read no selection. The form's
# `st.rerun()` after a write stays a full-page run -- what it changed is folded above.


@st.fragment
def _proposals() -> None:
    picked = st.session_state.get("_thr_pick")
    if picked not in set(view["proposal_id"]):
        picked = rows[0]["Proposal id"] if rows else None

    components.row_head(
        ["Check", "Element", ("Now", "n"), ("Proposed", "n"), "Basis", "State", "Reviewer"], GRID)
    with st.container(key="dqrows_thr"):
        components.clickable_rows(
            rows, GRID, _cells, "thr", "Proposal id",
            lambda m: f"Open the proposal on {m['Check']}", picked=picked,
            on_pick=components.pick_into("_thr_pick"))

    st.caption(
        "Every rule the threshold job has advised on, latest proposal first. Bold is a "
        "change; the rest is advice to keep the limit, with its reason.",
        help="The tolerance the element declares is a ceiling the advice may never "
             "exceed — enforced by the job's validator and by a CHECK constraint on "
             "the table. Where no tolerance is declared the expected advice is keep: "
             "history alone says where the data is, not where it may be.",
    )

    # --- The proposal picked --------------------------------------------------------
    if picked is None:
        st.stop()
    p = view[view["proposal_id"] == picked].iloc[0]
    state = str(p["review_state"])
    tol = opt(p["tolerance_pct"])

    theme.section(f"{opt(p['rule_name']) or p['rule_id']} · {p['rule_id']}")
    left, right = st.columns([3, 2])
    with left:
        st.markdown(
            theme.badge(theme.THRESHOLD_STATE_LABEL.get(state, state),
                        theme.THRESHOLD_STATE_TONE.get(state, "neutral"))
            + " "
            + theme.badge(theme.THRESHOLD_BASIS_LABEL.get(p["basis"], p["basis"]),
                          theme.THRESHOLD_BASIS_TONE.get(p["basis"], "neutral"))
            + " "
            + theme.severity_badge(p["severity"]) if opt(p["severity"]) else "",
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div class="dq-because"><b>'
            f'{float(p["current_threshold_pct"]):g}% → {float(p["proposed_threshold_pct"]):g}%'
            f'</b> — {html.escape(str(p["rationale"]))}</div>',
            unsafe_allow_html=True,
        )
        st.caption(theme.THRESHOLD_BASIS_MEANING.get(p["basis"], ""))
        if opt(p["latest_decision"]):
            when = p["latest_review_ts"]
            stamp = f" on {when:%-d %b}" if isinstance(when, pd.Timestamp) else ""
            line = (f'<b>{html.escape(theme.THRESHOLD_STATE_LABEL.get(state, state))}</b> by '
                    f'{html.escape(str(p["latest_reviewer"]))}{stamp}')
            if opt(p["latest_reason"]):
                line += f': {html.escape(str(p["latest_reason"]))}'
            if opt(p["review_by_date"]) is not None:
                line += f' · resurfaces {pd.Timestamp(p["review_by_date"]):%-d %b %Y}'
            if opt(p["adopted_rule_version"]) is not None:
                line += f' · rule version {int(p["adopted_rule_version"])}'
            st.markdown(f'<div class="dq-because">{line}</div>', unsafe_allow_html=True)

    with right:
        st.markdown(
            theme.kv("Element", cde_name.get(p["cde_id"], p["cde_id"]))
            + theme.kv("Declared tolerance",
                       f"{float(tol):g}% — the ceiling" if tol is not None else "none declared")
            + theme.kv("Registry now", f"{float(p['registry_threshold_pct']):g}%"
                       if opt(p["registry_threshold_pct"]) is not None else "—")
            + theme.kv("Advised on", f"rule version {int(p['rule_version'])}, "
                                     f"{p['proposed_ts']:%-d %b %Y}")
            + theme.kv("Reviewer", p["reviewer"]),
            unsafe_allow_html=True,
        )
        if opt(p["runs_observed"]) is not None and int(p["runs_observed"]):
            st.markdown(
                '<div class="dq-blockhd"><b>WHERE THE RATE HAS SAT</b></div>'
                + theme.kv("Runs", f"{int(p['runs_observed'])}, "
                                   f"{int(p['runs_breaching'])} breaching the current limit")
                + theme.kv("Min / median", f"{float(p['pct_min']):g}% / {float(p['pct_median']):g}%")
                + theme.kv("p90 / max", f"{float(p['pct_p90']):g}% / {float(p['pct_max']):g}%")
                + theme.kv("Latest run", f"{float(p['latest_violation_pct']):g}%"
                           if opt(p["latest_violation_pct"]) is not None else "—"),
                unsafe_allow_html=True,
            )
        st.caption(
            "Where the violation rate has sat is context, never a basis on its own.",
            help="A flat rate is where the data is, not where it may be. The advice "
                 "rests on the declared tolerance; the history says how far from it "
                 "the data sits.",
        )

    # --- The decision ----------------------------------------------------------------
    if state in thresholds.DECIDABLE:
        theme.section("Decide")
        st.markdown(
            '<div class="dq-because">Adopting appends a new rule version carrying the '
            'proposed limit and records it here. Rejecting and deferring record the '
            'decision only. Nothing changes a limit without a name on the row.</div>',
            unsafe_allow_html=True,
        )
        if not adapter.writes_are_durable():
            st.caption("Writes are session-only here — lost on restart. Deploy to decide.")
        with st.form("threshold_review_form", border=False):
            decision = st.radio(
                "Decision", list(thresholds.DECISIONS),
                format_func=lambda d: {
                    "adopted": f"Adopt — set the limit to {float(p['proposed_threshold_pct']):g}%",
                    "rejected": "Reject — keep the current limit",
                    "deferred": "Defer — decide later",
                }[d],
            )
            reason = st.text_area(
                "Reason", placeholder="What you checked and what convinced you.",
                help="Required for reject and defer — enforced here and by a CHECK "
                     "constraint on the table. On adoption it is carried into the new "
                     "rule version's note.",
            )
            review_by = st.date_input("Review by", value=date.today() + timedelta(days=30),
                                      help="Deferrals only.")
            if st.form_submit_button("Append decision", type="primary"):
                try:
                    adapter.review_threshold(
                        picked, decision, reason=reason or None,
                        review_by_date=review_by if decision == "deferred" else None)
                    st.rerun()
                except adapter.ReviewRejected as exc:
                    st.error(str(exc), icon=":material/block:")
    else:
        st.caption(
            {
                "adopted": "Adopted. The registry carries the new limit as a new rule version.",
                "rejected": "Rejected. The next pass of the threshold job may propose again.",
                "in_force": "The registry already carries this limit.",
                "no_change": "The advice was to keep the limit. There is nothing to decide.",
            }.get(state, ""),
        )


_proposals()

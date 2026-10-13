"""Thresholds — one tolerance per element, as advised, and the decisions on the advice.

**The business decides one number per element (2026-10-08).** `config.cde_registry.
tolerance_pct` is the share of an element's rows the business will accept failing, and
since this date it decides what reaches Triage: a breach whose element sat within its
tolerance is held back (`v_check_escalation`), unless it is a P1. A rule's
`fail_threshold_pct` only decides whether one check reads `breach`; it is a steward's
setting, 0 by default, and nobody is asked to approve it.

Until then this page put every rule's limit to review — 86 proposals over 19 elements
on the threshold job's first real pass, 30 asking for a decision. That was too many
decisions about the wrong thing. They stay in `results.threshold_proposal` as history
and the page says how many; it no longer lists them.

**What the job advises now** (`notebooks/06_suggest_thresholds.ipynb`, one row per
element per pass in `results.tolerance_proposal`): keep the tolerance, tighten it, or
put it to the business. Never a higher number — that is the business accepting worse
data, and a CHECK constraint refuses it.

**Accepting writes the decision and nothing else.** The register changes through the
Elements page: a person proposes the amendment, a second approves it, the onboarding
job applies it, and the advice then reads `In force`. The decision is the app's ninth
write (`results.tolerance_review`); every one opens a confirmation first.

`_tol_pick` holds the element picked.
"""

from __future__ import annotations

import html
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from dq_app.data import adapter
from dq_app.domain import metrics, tolerance
from dq_app.ui import components, onboarding_style, theme
from dq_app.ui.components import opt

components.page_chrome()

st.markdown(
    '<div class="dq-page-hd"><div class="t">Thresholds</div>'
    '<div class="s">One tolerance per key attribute, decided by the business. '
    "It decides which failing checks reach Triage.</div></div>",
    unsafe_allow_html=True,
)

current = adapter.get_tolerance_proposal_current()
old = adapter.get_threshold_proposals()
# Advice on an attribute since retired is history: the register no longer asks anyone
# to decide it. Since 2026-10-12 that is every proposal made on the mock register.
_registered = set(adapter.get_cde_registry_current()["cde_id"])
if len(current):
    current = current[current["cde_id"].isin(_registered)]


def _history_note() -> None:
    if len(old):
        st.caption(
            f"{old['rule_id'].nunique()} rules' earlier limit proposals are kept as history.",
            help="Until 2026-10-08 the threshold job advised on every rule's own limit, "
                 "and this page put each one to review. Rule limits are now a "
                 "steward's setting, 0 by default; the business decides the attribute's "
                 "tolerance instead. The proposals stay in results.threshold_proposal.",
        )


if current.empty:
    st.caption(
        "No tolerance advice yet.",
        help="The threshold job has not advised on tolerances in this catalog. It "
             "writes one row per attribute per pass to results.tolerance_proposal.",
    )
    _history_note()
    st.stop()

# --- What is held back right now ----------------------------------------------
# The point of a tolerance, shown beside the advice about it: which failing checks the
# current figures keep out of Triage.

runs = adapter.get_check_runs()
cde_cov = adapter.get_cde_coverage()
registry = adapter.get_cde_registry_current()
run_id = metrics.queue_run_id(runs)
_run = runs[runs["run_id"] == run_id] if run_id is not None else runs.iloc[0:0]
escalation = tolerance.check_escalation(
    _run, cde_cov, tolerance.element_tolerance(_run, cde_cov, registry))
held_by_cde = (escalation[~escalation["escalates"].astype(bool)]
               .groupby("cde_id")["rule_id"].apply(sorted).to_dict()
               if len(escalation) else {})

# --- The figures ---------------------------------------------------------------
s = tolerance.summary(current)
decide = current[current["review_state"].isin(tolerance.DECIDABLE)]
components.kpi_row([
    {"label": "Awaiting decision", "value": f"{s['open']}",
     "tone": "high" if s["open"] else None,
     "help": "Advice nobody has decided. At most one per attribute."},
    {"label": "Business decisions", "value": str(int((decide["advice"] == "review").sum())),
     "sub": "attribute outside its tolerance",
     "help": "The data gets fixed, or the business accepts more failure. The job "
             "never raises a tolerance itself."},
    {"label": "Tighten", "value": str(int((decide["advice"] == "tighten").sum())),
     "sub": "tolerance looser than the data"},
    {"label": "Held from Triage", "value": str(sum(len(v) for v in held_by_cde.values())),
     "sub": "failing checks, latest run",
     "help": "Failing checks whose attribute sat within its tolerance on the latest run. "
             "Still breaches on the Scorecard and the Rules page; not work in Triage. "
             "A P1 is never held."},
    {"label": "Attributes advised", "value": f"{s['proposals']}",
     "sub": f"latest pass {pd.Timestamp(current['proposed_ts'].max()):%-d %b}"},
])

# --- The list ------------------------------------------------------------------
STATE_ORDER = {k: i for i, k in enumerate(
    ["open", "deferred", "accepted", "in_force", "rejected", "no_change"])}
ADVICE_ORDER = {"review": 0, "tighten": 1, "keep": 2}
view = (current.assign(_o=current["review_state"].map(STATE_ORDER),
                       _a=current["advice"].map(ADVICE_ORDER))
               .sort_values(["_o", "_a", "cde_id"]))


def _pct(v) -> str:
    return "—" if opt(v) is None else f"{float(v):g}%"


rows = [{
    "Proposal id": r["proposal_id"],
    "Attribute": opt(r["cde_name"]) or r["cde_id"],
    "Cde": r["cde_id"],
    "Criticality": opt(r["criticality"]) or "",
    "Now": _pct(r["current_tolerance_pct"]),
    "Advised": _pct(r["proposed_tolerance_pct"]) if r["advice"] == "tighten" else "",
    "Failing": _pct(r["latest_fail_pct"]),
    "Outside": ("—" if opt(r["runs_observed"]) is None
                else f"{int(r['runs_outside'])} of {int(r['runs_observed'])}"),
    "Advice": str(r["advice"]),
    "State": str(r["review_state"]),
} for _, r in view.iterrows()]

GRID = ("minmax(10rem,1.6fr) minmax(5rem,7rem) 4.6rem 5.4rem minmax(7.5rem,9rem) "
        "minmax(7rem,9rem)")


def _cells(m) -> str:
    return (
        f'<span class="name" title="{html.escape(m["Cde"])}">{html.escape(m["Attribute"])}'
        f'<span style="color:var(--dq-text-2)"> · {html.escape(m["Criticality"])}</span></span>'
        f'<span class="num">{m["Now"]}'
        + (f' → <b>{m["Advised"]}</b>' if m["Advised"] else "") + "</span>"
        f'<span class="num">{m["Failing"]}</span>'
        f'<span class="num">{m["Outside"]}</span>'
        f'<span>{theme.badge(theme.TOLERANCE_ADVICE_LABEL.get(m["Advice"], m["Advice"]), theme.TOLERANCE_ADVICE_TONE.get(m["Advice"], "neutral"))}</span>'
        f'<span>{theme.badge(theme.TOLERANCE_STATE_LABEL.get(m["State"], m["State"]), theme.TOLERANCE_STATE_TONE.get(m["State"], "neutral"))}</span>'
    )


DECIDE = "tolerance_review"
PENDING = "_tol_decision"


def _write() -> str | None:
    pid, decision, reason, by = st.session_state.get(PENDING, (None,) * 4)
    try:
        adapter.review_tolerance(pid, decision, reason=reason, review_by_date=by)
    except adapter.ToleranceReviewRejected as exc:
        return str(exc)
    st.session_state.pop(PENDING, None)
    return None


def _to_elements(cde_id: str) -> None:
    st.session_state["_el_pick"] = cde_id
    st.session_state["_el_mode"] = "amend"


# One fragment: picking an element redraws the list, the advice and the form, not the
# figures above, which read no selection. The write is a full run (the confirmation's
# st.rerun), because what it changed is folded above.


@st.fragment
def _advice() -> None:
    picked = st.session_state.get("_tol_pick")
    if picked not in set(view["proposal_id"]):
        picked = rows[0]["Proposal id"] if rows else None

    components.row_head(
        ["Attribute", ("Tolerance", "n"), ("Failing", "n"), ("Runs outside", "n"),
         "Advice", "State"], GRID)
    with st.container(key="dqrows_tol"):
        components.clickable_rows(
            rows, GRID, _cells, "tol", "Proposal id",
            lambda m: f"Open the advice on {m['Attribute']}", picked=picked,
            on_pick=components.pick_into("_tol_pick"))
    st.caption(
        "Failing is rows failed over rows checked across the attribute's checks on the "
        "latest run — the same figure the Scorecard prints against the same target.",
        help="A sum of failures across checks, not a count of distinct bad rows: a row "
             "failing two checks counts twice. check_run stores counts, not keys.")
    _history_note()

    if picked is None:
        return
    p = view[view["proposal_id"] == picked].iloc[0]
    state, advice = str(p["review_state"]), str(p["advice"])

    theme.section(f"{opt(p['cde_name']) or p['cde_id']} · {p['cde_id']}")
    left, right = st.columns([3, 2])
    with left:
        st.markdown(
            theme.badge(theme.TOLERANCE_STATE_LABEL.get(state, state),
                        theme.TOLERANCE_STATE_TONE.get(state, "neutral")) + " "
            + theme.badge(theme.TOLERANCE_ADVICE_LABEL.get(advice, advice),
                          theme.TOLERANCE_ADVICE_TONE.get(advice, "neutral")),
            unsafe_allow_html=True)
        head = (f"{_pct(p['current_tolerance_pct'])} → {_pct(p['proposed_tolerance_pct'])}"
                if advice == "tighten" else f"Tolerance {_pct(p['current_tolerance_pct'])}")
        st.markdown(f'<div class="dq-because"><b>{head}</b> — '
                    f'{html.escape(str(p["rationale"]))}</div>', unsafe_allow_html=True)
        st.caption(theme.TOLERANCE_ADVICE_MEANING.get(advice, ""))
        held = held_by_cde.get(p["cde_id"], [])
        if held:
            st.markdown(
                f'<div class="dq-because"><b>Held from Triage on the latest run:</b> '
                f'{html.escape(", ".join(held))} — failing, but inside this tolerance.'
                "</div>", unsafe_allow_html=True)
        if opt(p["latest_decision"]):
            when = p["latest_review_ts"]
            stamp = f" on {pd.Timestamp(when):%-d %b}" if opt(when) is not None else ""
            line = (f'<b>{html.escape(theme.TOLERANCE_STATE_LABEL.get(state, state))}</b> '
                    f'by {html.escape(str(p["latest_reviewer"]))}{stamp}')
            if opt(p["latest_reason"]):
                line += f': {html.escape(str(p["latest_reason"]))}'
            if opt(p["review_by_date"]) is not None:
                line += f' · resurfaces {pd.Timestamp(p["review_by_date"]):%-d %b %Y}'
            st.markdown(f'<div class="dq-because">{line}</div>', unsafe_allow_html=True)

    with right:
        st.markdown(
            theme.kv("Register now", _pct(p["register_tolerance_pct"]))
            + theme.kv("Advised on", f"attribute version {int(p['cde_version'])}, "
                                     f"{pd.Timestamp(p['proposed_ts']):%-d %b %Y}")
            + theme.kv("Decided by", p["reviewer"]),
            unsafe_allow_html=True)
        if opt(p["runs_observed"]) is not None and int(p["runs_observed"]):
            st.markdown(
                '<div class="dq-blockhd"><b>WHERE THE ELEMENT HAS SAT</b></div>'
                + theme.kv("Runs", f"{int(p['runs_observed'])}, "
                                   f"{int(p['runs_outside'])} outside the tolerance")
                + theme.kv("Failing min / median",
                           f"{_pct(p['fail_pct_min'])} / {_pct(p['fail_pct_median'])}")
                + theme.kv("p90 / max", f"{_pct(p['fail_pct_p90'])} / {_pct(p['fail_pct_max'])}")
                + theme.kv("Latest run", _pct(p["latest_fail_pct"])),
                unsafe_allow_html=True)
        if bool(p["scope_disputed"]):
            st.caption("A rule on this attribute is in scope mismatch, so its failure rate "
                       "measures the rule, not the data. Nothing on it is held back.")

    if state == "accepted" and advice == "tighten":
        st.markdown(
            '<div class="dq-because">Accepted. The register still says '
            f'{_pct(p["register_tolerance_pct"])}: the change itself is an amendment on '
            "the Key attributes page, approved by a second person and applied by the "
            "onboarding job. This advice reads <b>In force</b> once it lands.</div>",
            unsafe_allow_html=True)
        if st.button("Amend in Key attributes", icon=":material/edit:", key="tol_to_elements",
                     on_click=_to_elements, args=(p["cde_id"],)):
            st.switch_page("dq_app/ui/pages/elements.py")

    if state not in tolerance.DECIDABLE:
        st.caption({
            "accepted": "" if advice == "tighten" else
                        "Accepted. The decision it asks for is the business's to make.",
            "rejected": "Rejected. The next pass may advise again if the history changes.",
            "in_force": "The register carries this tolerance.",
            "no_change": "The advice was to keep the tolerance. Nothing to decide.",
        }.get(state, ""))
        return

    theme.section("Decide")
    if not adapter.writes_are_durable():
        st.caption("Writes are session-only here — lost on restart. Deploy to decide.")
    labels = {
        "accepted": (f"Accept — tighten to {_pct(p['proposed_tolerance_pct'])} through "
                     "the Key attributes page" if advice == "tighten" else
                     "Accept — the business will decide: fix the data or amend the tolerance"),
        "rejected": "Reject — the tolerance stays as it is",
        "deferred": "Defer — decide later",
    }
    st.radio("Decision", list(tolerance.DECISIONS), key=f"tol_dec_{picked}",
             format_func=labels.get)
    st.text_area("Reason", key=f"tol_reason_{picked}",
                          placeholder="What you checked and what convinced you.",
                          help="Required to reject or defer — here and by a CHECK "
                               "constraint on the table.")
    st.date_input("Review by", value=date.today() + timedelta(days=30),
                              key=f"tol_by_{picked}", help="Deferrals only.")

    def _ask() -> None:
        # Read the widgets' values from session state, not this run's locals: a click
        # that arrives together with a changed radio or reason runs this callback
        # before the script redraws, and the locals would still hold the old values.
        d = st.session_state[f"tol_dec_{picked}"]
        r = (st.session_state.get(f"tol_reason_{picked}") or "").strip() or None
        by = st.session_state.get(f"tol_by_{picked}")
        st.session_state[PENDING] = (picked, d, r, by if d == "deferred" else None)
        onboarding_style.ask(DECIDE)

    st.button("Record decision", type="primary", key="tol_go", on_click=_ask)

    pending = st.session_state.get(PENDING)
    if pending and pending[0] == picked:
        _, d, r, by = pending
        name = html.escape(str(opt(p["cde_name"]) or p["cde_id"]))
        body = (f"Appends one row to <b>results.tolerance_review</b>, in your name: "
                f"<b>{html.escape(theme.TOLERANCE_STATE_LABEL.get(d, d))}</b> on the advice "
                f"for {name}."
                + (f" Resurfaces {by:%-d %b %Y}." if by else "")
                + " The register is not changed"
                + (" — the tightening is then an amendment on the Key attributes page, approved "
                   "by a second person." if d == "accepted" and advice == "tighten" else ".")
                + " A decision cannot be edited, only followed by another.")
        onboarding_style.confirm(DECIDE, "Record this decision?", body, "Record", _write)


_advice()

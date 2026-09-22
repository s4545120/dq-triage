"""Triage — one row per problem, not one per breach.

A table, not a stack of cards: the queue is something a steward scans and sorts, and
a card list forces the hypothesis text on you before you have decided which row you
care about. Clicking a row opens it — there is no preview step, because a preview is
a second thing to read before the thing you asked for.

**What the queue lists is not "open cohorts".** It is
`metrics.live_cohorts` — for every rule breaching on the latest run, the cohort that
currently owns it. Two consequences worth knowing:

  * A problem someone closed, whose checks are breaching again, is in the queue with
    its closed state showing. That is exactly what should be put in front of a
    steward, and filtering it out because of its lifecycle state would hide it.
  * A rule regrouped into a newer problem is counted once, under the newer one, so
    the row count and the compression ratio under the table can never disagree —
    they read the same function.

The header used to carry four tiles — Breaching rules, Grouped into, Needing action,
Raised in total. Three of them restate the same grouping, so they are now one
sentence, and compression is stated in prose under the table rather than as a metric
of its own. It still has to be said somewhere: if that ratio approaches 1:1 this page
is an alert list with extra steps.

Named "Cohorts" until 2026-09-16. A cohort is our word for it, not the steward's.
"""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from dq_app.data import adapter
from dq_app.domain import lifecycle, metrics
from dq_app.ui import components, theme
from dq_app.ui.components import as_list, opt

# --- The row ----------------------------------------------------------------

# The problem gets whatever the fixed columns do not need. Every other column holds a
# badge, a count or a date, so its width is known and stated in rem — sharing them out
# in `fr` just makes them breathe while the title, the one cell that can use the
# space, ellipsises.
#
# The two text columns are `minmax(floor, ideal)` rather than fixed, and the title
# carries a floor of its own. That ordering is what makes the table narrow sensibly:
# a bare `minmax(0,1fr)` title loses every pixel first, because fixed tracks are
# satisfied before an `fr` track sees any space at all — at 1150px it left "A change
# to the …" beside a state column with room to spare. With floors declared, the state
# and the owner give way first and the title is the last thing to be cut.
QUEUE_GRID = ("minmax(9rem,1fr) 3.2rem minmax(5.6rem,7.6rem) 3.6rem 4.4rem 4.2rem "
              "minmax(3.5rem,8.5rem)")
QUEUE_HEADS = ["Problem", "Sev", "State", ("Checks", "n"), ("Rows", "n"),
               "Raised", "Waiting on"]

def _state_label(row) -> str:
    """The state, with the one date that changes what it means.

    "Deferred" and "Deferred to 18 Sep" are different facts: the second says when it
    comes back, which is the whole content of a deferral.
    """
    state = row["lifecycle_state"]
    label = theme.STATE_LABEL.get(state, str(state).replace("_", " "))
    when = opt(row["review_by_date"])
    if state == "deferred" and when is not None:
        return f"Deferred to {pd.Timestamp(when):%-d %b}"
    return label


def _marks(row, defect: bool, breaching_again: bool) -> list[tuple[str, str]]:
    """The phrases that ride under a problem's title. Words first, tint second.

    Ordered by what a steward needs to know before opening the row. "Rule defect, not
    data" outranks "checks breaching again" on the same row: both are true of COH-B,
    and only the first tells you not to go looking at the data.
    """
    out = []
    if defect:
        out.append(("rule defect, not data", theme.ACCENT))
    elif breaching_again:
        out.append(("checks breaching again", theme.TONE["critical"]["fg"]))
    if bool(row["is_recurrence"]):
        out.append(("recurrence", theme.TONE["moderate"]["fg"]))
    return out


# =============================================================================
# Page
# =============================================================================

components.page_chrome()

current = adapter.get_cohort_current()
cohorts = adapter.get_cohorts()
runs = adapter.get_check_runs()
cde_cov = adapter.get_cde_coverage()
registry = adapter.get_rule_registry_current()

# One definition of compression, in domain/metrics.py — recomputing it here with a
# slightly different denominator is how a headline starts disagreeing with the
# scorecard that reports it. The queue below lists exactly the cohorts it divides by.
compression = metrics.cohort_compression(runs, cohorts)
live = metrics.live_cohorts(runs, cohorts)
live_ids = set(live.values())

st.markdown(
    '<div class="dq-page-hd"><div class="t">Triage</div>'
    f'<div class="s"><b>{int(compression.numerator or 0)} breaching checks, '
    f"{int(compression.denominator or 0)} live problems</b> — one row here is one "
    "thing to decide, not one alert.</div></div>",
    unsafe_allow_html=True,
)

if current.empty:
    st.caption("No problems have been raised.")
    st.stop()

# --- What each scope means --------------------------------------------------
# Four named views, not six independent filters. The old page had a state
# multiselect defaulting to "everything live", which is a control that asks the
# reader to know the lifecycle vocabulary before they can see their own queue.

open_ids = set(current[current["lifecycle_state"].isin(lifecycle.OPEN_STATES)]["cohort_id"])
mine_ids = set(current[current["lifecycle_state"] == "awaiting_review"]["cohort_id"])
closed_ids = set(current[current["lifecycle_state"].str.startswith("closed")]["cohort_id"])

SCOPES = {
    "live": ("Live queue", live_ids,
             "Every problem with a check breaching on the latest run — including ones "
             "that were closed and have come back. This is the set the ratio under "
             "the table divides by."),
    "open": ("Open", open_ids,
             "Open lifecycle states only. Excludes deferred problems and anything "
             "closed, whether or not its checks are breaching again."),
    "mine": ("Waiting on me", mine_ids,
             "Awaiting review — a steward has to accept, defer or reject it."),
    "closed": ("Closed", closed_ids,
               "Every problem with a recorded outcome, whatever the checks are doing "
               "now."),
    "all": ("All", set(current["cohort_id"]), "Everything ever raised."),
}

# --- Filter strip -----------------------------------------------------------

with st.container(key="dq_pillbar"):
    # Each control carries its own label inside its own border — see the
    # `.st-key-dq_pillbar` note in theme.py for what the bordered band was doing wrong.
    f1, f2, f3, gap, act = st.columns(
        [1.85, 1.25, 1.25, 0.45, 1.85], vertical_alignment="center")
    with f1:
        scope = st.selectbox(
            "Show", list(SCOPES), key="_tri_scope",
            format_func=lambda k: f"{SCOPES[k][0]} · {len(SCOPES[k][1])}",
            help=" ".join(f"{v[0]}: {v[2]}" for v in SCOPES.values()),
        )
    with f2:
        sev = st.selectbox("Severity", ["All"] + theme.SEVERITY_ORDER,
                           format_func=lambda s: s if s == "All"
                           else f"{theme.SEVERITY_SHORT[s]} · {theme.SEVERITY_WORD[s]}")
    with f3:
        domains = sorted(current["business_domain"].dropna().unique())
        dom = st.selectbox("Domain", ["All"] + domains)
    with act:
        # A shortcut, not a second filter: the closed history is the one thing a
        # reader looks for that the live queue deliberately does not show.
        to_closed = scope != "closed"
        if st.button(
            f"{len(closed_ids)} closed this period" if to_closed
            else "Back to the live queue",
            key="_tri_closed", width="stretch",
            icon=":material/history:" if to_closed else ":material/inbox:",
            help="Problems with a recorded outcome. They leave the live queue unless "
                 "their checks start breaching again, which is the one thing that "
                 "should pull a closed problem back in front of you.",
        ):
            st.session_state["_tri_scope"] = "closed" if to_closed else "live"
            st.rerun()

view = current[current["cohort_id"].isin(SCOPES[scope][1])]
if sev != "All":
    view = view[view["severity"] == sev]
if dom != "All":
    view = view[view["business_domain"] == dom]
view = view.sort_values("rank_score", ascending=False)

# --- The queue --------------------------------------------------------------

detail = cohorts.set_index("cohort_id")
member_rules = {r.cohort_id: as_list(r.member_rule_ids) for r in cohorts.itertuples()}

latest_run_id = metrics.latest_run_id(runs)
breaching_now = set(
    runs[(runs["run_id"] == latest_run_id) & (runs["status"] == "breach")]["rule_id"]
)
# The register's own verdict on a rule, not a judgement made here. `v_cde_coverage`
# names the rules that contradict a registered scope, which is how COH-B's root cause
# is an assertion the model makes rather than something a human noticed.
unscoped = {i for ids in cde_cov["unscoped_rule_ids"] for i in as_list(ids)} \
    if not cde_cov.empty else set()

if view.empty:
    st.caption("No problems match these filters.")
else:
    rows = []
    for _, r in view.iterrows():
        cid = r["cohort_id"]
        members = member_rules.get(cid, [])
        elements, unattached = components.cohort_elements(members, cde_cov)
        rows.append({
            "cohort_id": cid,
            "Problem": components.problem_title(detail.loc[cid], elements, registry),
            "Claim": components.claim_sentence(
                detail.loc[cid, "root_cause_hypothesis"], limit=200),
            # The title already names the elements, so the second line does not repeat
            # them — it carries the one thing about them the title cannot: how critical
            # the most critical one is. The chips themselves are on the detail page.
            "Criticality": elements[0]["criticality"] if elements else None,
            "Tables": " · ".join(sorted(
                t.split(".")[-1] for t in as_list(r["affected_tables"]))),
            "Severity": r["severity"],
            "State": _state_label(r),
            "State tone": theme.STATE_TONE.get(r["lifecycle_state"], "neutral"),
            "Checks": int(r["member_count"]),
            "Rows": int(r["total_violation_rows"]),
            "Raised": f"{r['raised_ts']:%-d %b}",
            "Waiting on": components.waiting_on(r),
            "Marks": _marks(
                r,
                defect=bool(set(members) & unscoped),
                breaching_again=str(r["lifecycle_state"]).startswith("closed")
                and bool(set(members) & breaching_now),
            ),
        })

    def _cells(row) -> str:
        marks = "".join(
            f'<span class="mark" style="color:{c}"> · {html.escape(t)}</span>'
            for t, c in row["Marks"]
        )
        return (
            '<span class="stack">'
            # The claim rides as the tooltip: the title says what and what kind, the
            # hover says why, and the row stays two lines high.
            f'<span class="t1" title="{html.escape(str(row["Claim"]))}">'
            f'{html.escape(str(row["Problem"]))}</span>'
            '<span class="t2">'
            + (f'<span class="mark" style="color:'
               f'{theme.TONE[theme.CRITICALITY_TONE.get(row["Criticality"], "neutral")]["fg"]}">'
               f'{html.escape(str(row["Criticality"]))} element</span> · '
               if row["Criticality"] else "")
            + f'{html.escape(row["Tables"])}{marks}</span></span>'
            + f'<span>{theme.severity_badge(row["Severity"], words=False)}</span>'
            + f'<span>{theme.badge(row["State"], row["State tone"])}</span>'
            + f'<span class="num">{row["Checks"]:,}</span>'
            f'<span class="num">{row["Rows"]:,}</span>'
            f'<span class="of" style="text-align:left">{html.escape(row["Raised"])}</span>'
            f'<span class="txt">{html.escape(row["Waiting on"])}</span>'
        )

    components.row_head(QUEUE_HEADS, QUEUE_GRID)
    with st.container(key="dqrows_queue"):
        # No `picked`. A row here is a link, not a selection: clicking one leaves the
        # page, so there is nothing for a highlight to mean on the way back. Passing
        # `selected_cohort` — which survives the trip to the detail page and back —
        # left a row tinted every time the queue was opened.
        got = components.clickable_rows(
            rows, QUEUE_GRID, _cells, "tri", "cohort_id",
            lambda r: f"Open {r['Problem']}",
        )
    if got:
        st.session_state["selected_cohort"] = got
        st.switch_page("dq_app/ui/pages/triage_detail.py")

    st.markdown(
        f'<div class="dq-tablefoot">{len(view)} of {len(current)} problems · '
        "most urgent first · click a row to open it</div>",
        unsafe_allow_html=True,
    )

# Compression as prose, at the foot, at reading size. It is the queue's whole
# argument and the one number that says whether this page is worth having, so it is
# stated rather than tucked into a tooltip.
st.markdown(
    '<div class="dq-callout"><strong>What the queue is claiming.</strong> '
    f"{int(compression.numerator or 0)} failing checks arrived; they belong to "
    f"{int(compression.denominator or 0)} problems — <b>{compression.display}</b>, "
    f"against a target of {html.escape(compression.target)}. If that ratio ever "
    "approaches 1 : 1, this page is an alert list with extra steps, which is why it "
    "is stated rather than tucked into a tooltip.</div>",
    unsafe_allow_html=True,
)

with st.expander("How failing checks become one problem"):
    st.markdown(theme.COHORT_EXPLAINER)

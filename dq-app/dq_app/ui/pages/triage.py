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

**Redrawn 2026-10-06 in the Tables page's language**: four figures, the queue in a
card with its views in the header, and two cards under it. The four figures are not
the four tiles removed on 2026-09-16 -- Breaching rules, Grouped into, Needing action
and Raised in total, three of which restated one grouping. Each now answers its own
question: how many problems, how many are mine, how many are P1, and whether the
grouping is working -- compression, stated beside its target as every figure on the
scorecard is. It still has to be said somewhere: if that ratio approaches 1:1 this
page is an alert list with extra steps, and the Grouping card under the queue draws
it, one segment per problem sized by its checks.

Named "Cohorts" until 2026-09-16. A cohort is our word for it, not the steward's.
"""

from __future__ import annotations

import html
from collections import Counter

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
#
# Severity is no longer a column of its own: it is the stripe on the row's left edge
# and the badge leading the title, which is where the Tables page puts a table's
# status. The chevron says the row is a link.
QUEUE_GRID = ("minmax(12rem,1fr) minmax(6rem,8.4rem) 3.6rem 4.6rem 4.2rem "
              "minmax(4rem,8.5rem) 1rem")
QUEUE_HEADS = ["Problem", "State", ("Checks", "n"), ("Rows", "n"), "Raised",
               "Waiting on", ""]
OPEN = "dq_app/ui/pages/triage_detail.py"


def _open(cohort_id: str) -> None:
    st.session_state["selected_cohort"] = cohort_id
    st.switch_page(OPEN)


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
    '<div class="s">Failing checks grouped into problems. One row is one thing to '
    "decide, not one alert.</div></div>",
    unsafe_allow_html=True,
)

if current.empty:
    st.caption("No problems have been raised.")
    st.stop()

# --- What each view means ---------------------------------------------------
# Named views, not independent filters. The old page had a state multiselect
# defaulting to "everything live", which is a control that asks the reader to know
# the lifecycle vocabulary before they can see their own queue.

open_ids = set(current[current["lifecycle_state"].isin(lifecycle.OPEN_STATES)]["cohort_id"])
mine_ids = set(current[current["lifecycle_state"] == "awaiting_review"]["cohort_id"])
closed_ids = set(current[current["lifecycle_state"].str.startswith("closed")]["cohort_id"])

SCOPES = {
    "live": ("Live", live_ids,
             "Every problem with a check breaching on the latest run — including ones "
             "that were closed and have come back. This is the set the grouping ratio "
             "divides by."),
    "mine": ("Waiting on me", mine_ids,
             "Awaiting review — a steward has to accept, defer or reject it."),
    "open": ("Open", open_ids,
             "Open lifecycle states only. Excludes deferred problems and anything "
             "closed, whether or not its checks are breaching again."),
    "closed": ("Closed", closed_ids,
               "Every problem with a recorded outcome, whatever the checks are doing "
               "now. They leave the live queue unless their checks breach again."),
    "all": ("All", set(current["cohort_id"]), "Everything ever raised."),
}

# --- Filters ----------------------------------------------------------------
# The same strip as the Tables page (its key carries the CSS): labels beside their
# controls, and a note on the right saying how fresh the queue is.

with st.container(key="monitor_list_filter_strip"):
    l1, f1, l2, f2, note = st.columns([.55, 1.3, .5, 1.3, 2.2],
                                      vertical_alignment="center")
    l1.markdown('<div class="dq-strip-lab">Severity</div>', unsafe_allow_html=True)
    sev = f1.selectbox("Severity", ["All"] + theme.SEVERITY_ORDER,
                       label_visibility="collapsed", key="_tri_sev",
                       format_func=lambda s: s if s == "All"
                       else f"{theme.SEVERITY_SHORT[s]} · {theme.SEVERITY_WORD[s]}")
    l2.markdown('<div class="dq-strip-lab">Domain</div>', unsafe_allow_html=True)
    domains = sorted(current["business_domain"].dropna().unique())
    dom = f2.selectbox("Domain", ["All"] + domains, label_visibility="collapsed",
                       key="_tri_dom")
    last_ts = runs["run_ts"].max() if not runs.empty else None
    note.markdown(
        '<div class="dq-strip-note dq-tm-last">' + theme.dot("success")
        + (f"Latest run {last_ts:%-d %b, %H:%M}" if last_ts is not None else "No run yet")
        + "</div>",
        unsafe_allow_html=True,
    )

# --- Four figures -------------------------------------------------------------

red, amber = theme.TONE["critical"]["fg"], theme.TONE["high"]["fg"]
live_rows = current[current["cohort_id"].isin(live_ids)]
n_p1 = int((live_rows["severity"] == "P1_block").sum())
ratio_ok = (compression.value or 0) >= 5.0


def _fig(label: str, value: str, colour: str | None = None, dot: str = "",
         sub: str = "") -> str:
    style = f' style="color:{colour}"' if colour else ""
    return (f'<div class="f"><div class="l">{dot}{label}</div>'
            f'<div class="v"{style}>{value}</div>'
            + (f'<div class="c">{sub}</div>' if sub else "") + "</div>")


st.markdown(
    '<div class="dq-tmkpi">'
    + _fig("Live problems", str(len(live_ids)),
           sub=f"from {int(compression.numerator or 0)} failing checks")
    + _fig("Waiting on you", str(len(mine_ids)), amber if mine_ids else None,
           theme.dot("high") if mine_ids else "", sub="awaiting your review")
    + _fig("P1 problems", str(n_p1), red if n_p1 else None, sub="in the live queue")
    + _fig("Grouping" + theme.hint(
               "Failing checks per live problem, from the same function that picks the "
               "rows of the live queue. Near 1 : 1, this page is an alert list with "
               "extra steps.", side="left"),
           html.escape(compression.display), None if ratio_ok else amber,
           sub=f"checks per problem · target {html.escape(compression.target)}")
    + "</div>",
    unsafe_allow_html=True,
)

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


def _row(r) -> dict:
    cid = r["cohort_id"]
    members = member_rules.get(cid, [])
    elements, _ = components.cohort_elements(members, cde_cov)
    return {
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
    }


def _cells(row) -> str:
    marks = "".join(
        f'<span class="mark" style="color:{c}"> · {html.escape(t)}</span>'
        for t, c in row["Marks"]
    )
    crit = row["Criticality"]
    who = row["Waiting on"]
    return (
        f'<span class="stack dq-tmname" style="--dq-stripe:'
        f'{theme.TONE[theme.SEVERITY_TONE.get(row["Severity"], "neutral")]["fg"]}">'
        # The claim rides as the hover text: the title says what and what kind, the
        # hover says why, and the row stays two lines high.
        f'<span class="t1">{theme.severity_badge(row["Severity"], words=False)}'
        f'<span class="nm">{html.escape(str(row["Problem"]))}</span></span>'
        '<span class="t2">'
        + (f'<span class="mark" style="color:'
           f'{theme.TONE[theme.CRITICALITY_TONE.get(crit, "neutral")]["fg"]}">'
           f'{html.escape(str(crit))} element</span> · ' if crit else "")
        + f'{html.escape(row["Tables"])}{marks}</span></span>'
        + f'<span>{theme.badge(row["State"], row["State tone"])}</span>'
        + f'<span class="num">{row["Checks"]:,}</span>'
        f'<span class="num">{row["Rows"]:,}</span>'
        f'<span class="of" style="text-align:left">{html.escape(row["Raised"])}</span>'
        + (f'<span>{theme.badge("You", "high")}</span>' if who == "you"
           else f'<span class="txt">{html.escape(who)}</span>')
        + f'<span class="opn">{theme.icon("arrow_right", 15)}</span>'
    )


def _tip(row) -> list:
    return [row["Problem"], row["Claim"]]


st.session_state.setdefault("_tri_scope", "live")
with st.container(key="dq_tricard"):
    top, ctl = st.columns([1, 2], vertical_alignment="center")
    with ctl:
        q, seg = st.columns([1, 2.1], vertical_alignment="center")
        term = q.text_input("Search problems", placeholder="Search problems",
                            label_visibility="collapsed", icon=":material/search:",
                            key="_tri_search").strip().lower()
        scope = seg.segmented_control(
            "Show", list(SCOPES), key="_tri_scope", label_visibility="collapsed",
            format_func=lambda k: f"{SCOPES[k][0]} {len(SCOPES[k][1])}",
            help=" ".join(f"{v[0]}: {v[2]}" for v in SCOPES.values())) or "live"

    view = current[current["cohort_id"].isin(SCOPES[scope][1])]
    if sev != "All":
        view = view[view["severity"] == sev]
    if dom != "All":
        view = view[view["business_domain"] == dom]
    rows = [_row(r) for _, r in view.sort_values("rank_score", ascending=False).iterrows()]
    if term:
        rows = [x for x in rows if term in
                f"{x['Problem']} {x['Tables']} {x['cohort_id']} {x['Claim']}".lower()]

    top.markdown(
        f'<div class="dq-tmcard-hd"><div class="t">{SCOPES[scope][0]} problems'
        f'<span class="dq-count">{len(rows)}</span></div>'
        '<div class="q">Most urgent first · hover a row for its claim</div></div>',
        unsafe_allow_html=True,
    )
    if rows:
        components.row_head(QUEUE_HEADS, QUEUE_GRID)
        with st.container(key="dqrows_queue"):
            # No `picked`. A row here is a link, not a selection: clicking one leaves
            # the page, so there is nothing for a highlight to mean on the way back.
            # Passing `selected_cohort` — which survives the trip to the detail page
            # and back — left a row tinted every time the queue was opened.
            got = components.clickable_rows(
                rows, QUEUE_GRID, _cells, "tri", "cohort_id",
                lambda r: f"Open {r['Problem']}", tip=_tip)
        if got:
            _open(got)
    else:
        st.markdown('<div class="dq-tmempty">No problem matches.</div>',
                    unsafe_allow_html=True)

st.markdown(
    f'<div class="dq-tmfoot"><span>{len(rows)} of {len(current)} problems ever raised'
    "</span><span>Ranked by the triage job's score, not by the model's confidence"
    + theme.hint("rank_score weighs severity, rows affected and the criticality of the "
                 "elements touched. The model's own confidence is shown on the "
                 "problem and deliberately not an input: ranking on a self-reported "
                 "number lets a confident wrong answer outrank a hedged right one.",
                 side="left")
    + "</span></div>",
    unsafe_allow_html=True,
)

# --- How the checks were grouped, and where to start -------------------------

group, start = st.columns([1.45, 1], gap="medium")

with group, st.container(key="dq_trigroup"):
    per = Counter(live.values())
    order = live_rows.sort_values("rank_score", ascending=False)
    segs = "".join(
        f'<span style="flex:{per[r.cohort_id]} 1 0;background:'
        f'{theme.TONE[theme.SEVERITY_TONE.get(r.severity, "neutral")]["fg"]}" '
        f'title="{per[r.cohort_id]} checks"></span>'
        for r in order.itertuples() if per.get(r.cohort_id))
    st.markdown(
        '<div class="t">How the failing checks were grouped</div>'
        f'<div class="q"><b>{int(compression.numerator or 0)} failing checks</b> on the '
        f'latest run belong to <b>{int(compression.denominator or 0)} problems</b> — '
        f"{html.escape(compression.display)} against a target of "
        f"{html.escape(compression.target)}. Each segment is one problem, sized by "
        "its checks.</div>"
        f'<div class="dq-cov3 dq-trisegs">{segs}</div>'
        f'<div class="dq-legend">'
        + "".join(f'<span>{theme.dot(theme.SEVERITY_TONE[s])}{theme.SEVERITY_SHORT[s]}'
                  "</span>" for s in theme.SEVERITY_ORDER)
        + "</div>",
        unsafe_allow_html=True,
    )
    with st.expander("How failing checks become one problem"):
        st.markdown(theme.COHORT_EXPLAINER)

with start, st.container(key="dq_tristart"):
    waiting = current[current["cohort_id"].isin(mine_ids)]
    first = waiting if not waiting.empty else live_rows
    if first.empty:
        st.markdown('<div class="t">Nothing waiting</div>'
                    '<div class="q">No problem is live or waiting on a review.</div>',
                    unsafe_allow_html=True)
    else:
        top_row = first.sort_values("rank_score", ascending=False).iloc[0]
        title = _row(top_row)["Problem"]
        n = len(waiting)
        st.markdown(
            '<div class="t">Start here</div>'
            + (f'<div class="q"><b>{n} {"problem is" if n == 1 else "problems are"} '
               "waiting on your review.</b> The most urgent:</div>" if n else
               '<div class="q">Nothing is waiting on your review. The most urgent live '
               "problem:</div>"),
            unsafe_allow_html=True,
        )
        if st.button(title, type="tertiary", icon=":material/arrow_forward:",
                     key="_tri_start", help="Opens the problem on its own page."):
            _open(top_row["cohort_id"])

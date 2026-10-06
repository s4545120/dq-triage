"""Scorecard — how the watched data is doing against what it is held to.

**Every figure on this page now stands beside a target.** Until 2026-10-01 the page
reported scores and left the reader to decide whether 97.9% was good. The CDE
register has declared a tolerance on every element since 2026-09-28, so the page can
say it: an element's target is `100 - tolerance_pct`, a check's is `100 -
threshold_pct` off the run row it was judged on, and the headline's is the element
targets weighted by the same rows the score is. `domain/targets.py` is the one
definition of all three, and of which scores are assessed at all.

**Not every score gets a verdict.** An element nothing validates can score 100% on a
presence check; a scope mismatch scores 50% because its rule measures rows the
register says are legitimately empty. Both keep their figure, in neutral, and are
counted as unassessed — "meets target" on the first and "below target" on the second
would each be the page asserting something about the data that the register
contradicts. `targets.assessed` is that rule.

**Four cards.** Overall quality with its trend against the target; monitoring
coverage, counted per element by its worst finding; the element list, largest
shortfall first; and the element picked from it — its score, target, trend, and every
check on it with that check's own pass rate and limit. The six estate tiles, the
`All checks` entry and the dimension grouping went with the move: `domain/metrics.py`
still computes the tiles' figures, and a check's dimension rides on its row and in
its drawer.

**The list reports; it does not advise.** It carries each element's score, target and
how the two compare, and nothing that tells anyone what to do about a shortfall or a
gap in the register — that belongs to whoever authors rules.

**The elements themselves have no page.** `Data elements` was removed on 2026-09-16:
nobody browses a register. The list here is what it was read for, and "Every binding
and what checks it" opens one element in a drawer.

**Checks open.** Any check in the breakdown opens a drawer with the rule in plain
words, the arithmetic, and the rows that actually failed — parsed into columns, from
`results.violation_sample`.

**There is no Run button here and there will not be one.** The check runner is a
scheduled job owned outside this app; this page reads its results. A control that
starts a run is the first step towards a control that fixes a row, which is the one
thing this system promises never to do.
"""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from dq_app.data import adapter
from dq_app.domain import coverage, lifecycle, metrics, targets
from dq_app.ui import components, theme

# --- Scoring ----------------------------------------------------------------
# Every score on this page is weighted by ROWS — evaluated rows that passed, over
# evaluated rows — whether it is the headline, one element or one check. That is what
# a consumer of the data cares about, and it is what makes the three commensurable: an
# element's score is the headline's question asked of a smaller set of rows.


def _row_score(run: pd.DataFrame) -> float | None:
    """Row-weighted quality for one run, or one dimension of one run.

    Shadow checks are excluded from both sides — they record a count but raise
    nothing, so counting their findings would make promoting a rule look like a
    regression in the data.
    """
    raised = run[run["status"].isin(["pass", "breach"])]
    evaluated = int(raised["rows_scanned"].sum())
    if not evaluated:
        return None
    return 100.0 * (evaluated - int(raised["violation_count"].sum())) / evaluated


def _run_index(check_run: pd.DataFrame) -> pd.DataFrame:
    """One row per scheduled run: when, how many checks, how many failed, the score."""
    rows = []
    for run_id, g in check_run.groupby("run_id"):
        raised = g[g["status"].isin(["pass", "breach"])]
        breaching = raised[raised["status"] == "breach"]
        rows.append({
            "run_id": run_id,
            "run_ts": g["run_ts"].max(),
            "checks": int(len(raised)),
            "failing": int(len(breaching)),
            "p1": int((breaching["severity"] == "P1_block").sum()),
            "score": _row_score(g),
        })
    return pd.DataFrame(rows).sort_values("run_ts").reset_index(drop=True)


# --- Dimensions -------------------------------------------------------------
# Moved to theme.py on 2026-10-06 so the Rules page can label a rule with its
# dimension without a second copy of the map. `theme.dimension_for` is still the
# only reader of `theme.DIMENSION_OF`.

_dimension_for = theme.dimension_for
DIMENSIONS = theme.DIMENSIONS


def _tagged(check_run: pd.DataFrame, registry: pd.DataFrame,
            run_id=None) -> pd.DataFrame:
    """Check results carrying the dimension their rule type belongs to.

    `run_id` narrows to a single scheduled run; omit it to tag every run.
    """
    cols = ["rule_id", "rule_type", "rule_name"]
    dims = registry[cols].drop_duplicates("rule_id").copy()
    dims["Dimension"] = dims["rule_type"].map(_dimension_for)
    rows = check_run if run_id is None else check_run[check_run["run_id"] == run_id]
    out = rows.merge(dims, on="rule_id", how="left")
    out["Dimension"] = out["Dimension"].fillna("Other")
    out["rule_name"] = out["rule_name"].fillna(out["rule_id"])
    return out


# --- Check rows ---------------------------------------------------------------


def _where(row, tables: list[str]) -> str:
    """Where the check looks, as a steward would say it.

    A cross-table rule carries `target_column = NULL` by design — a name agreement
    check between two tables is about neither column on its own — and rendering just
    its table reads as a rule on the wrong table. Two tables joined by an arrow is
    what it actually is.
    """
    here = str(row.target_table).split(".")[-1]
    if components.opt(row.target_column):
        return f"{here}.{row.target_column}"
    others = [t.split(".")[-1] for t in tables if t.split(".")[-1] != here]
    return f"{here} \u2194 {others[0]}" if len(others) == 1 else here


def _failing_since(history: pd.DataFrame, rule_id: str) -> str | None:
    """The date this check started failing, or None if it has failed all along.

    "failing since 28 Aug" on six email checks at once is the whole of COH-A's
    evidence — rules clean on every run to the 27th and breaching together on the
    first run after is the shape of a release, not of data drifting. Said only where
    there is a date to give: a check that has always failed has no onset.
    """
    h = history[(history["rule_id"] == rule_id)
                & history["status"].isin(["pass", "breach"])].sort_values("run_ts")
    statuses, stamps = list(h["status"]), list(h["run_ts"])
    if not statuses or statuses[-1] != "breach":
        return None
    i = len(statuses) - 1
    while i > 0 and statuses[i - 1] == "breach":
        i -= 1
    return None if i == 0 else f"{stamps[i]:%-d %b}"


# --- Figures as text ----------------------------------------------------------


def _pct(value) -> str:
    """A score for a row: one decimal, and a whole number printed as one. `pct_text`
    underneath, so 99.96 never prints as 100."""
    shown = theme.pct_text(value, 1)
    return (shown[:-2] if shown.endswith(".0") else shown) + ("%" if value is not None else "")


def _target_text(target: float) -> str:
    return "\u2265 " + _pct(target)


def _pts(points: float) -> str:
    """A distance in points with its unit — whole numbers past ten, where the decimal
    is noise, and never a shortfall rounded to nothing."""
    shown = theme.pct_text(abs(points), 0 if abs(points) >= 10 else 1)
    return f"{shown} {'pt' if shown in ('1', '1.0') else 'pts'}"


def _change_words(now, before) -> str:
    """Since the previous run, in words. Not coloured: on a row whose score is
    already red, a red arrow beside it says the same thing twice, and on an
    unassessed row it would be a verdict the score itself is denied."""
    if now is None or before is None:
        return ""
    change = now - before
    if abs(change) < 0.05:
        return "No change"
    return ("\u2191 " if change > 0 else "\u2193 ") + _pts(change)


# Both lists on this page are drawn with `components.clickable_rows` rather than
# `st.dataframe` — see the comment above that helper for the three reasons.
ROW_GRID = "minmax(0,1fr)"

# What a bar and its figure are painted in. Red is a score under its target and
# nothing else; a met target is the accent, not green, because meeting a tolerance
# is not the same as having no defects; and an unassessed score is grey.
BELOW, MET, UNASSESSED = (theme.TONE["critical"]["fg"], theme.ACCENT,
                          theme.NEUTRAL["text_3"])


def _row_markup(name: str, figure: str, figure_colour: str, bar: str,
                left: str, right: str, dot: str = "", compact: bool = False) -> str:
    """One row of either list: name and figure, the bar, and the line under it.

    `compact` puts the bar ON the second line instead of between the two, for the
    check list: it lives in a fixed-height tab, and at three lines a row an element
    with nine checks showed four of them.
    """
    head = (f'<span class="l1"><span class="nm">{dot}{html.escape(name)}</span>'
            f'<span class="sc" style="color:{figure_colour}">{figure}</span></span>')
    words = f"<span>{html.escape(left)}</span><span>{html.escape(right)}</span>"
    if compact:
        return f'<span class="dq-el c2">{head}<span class="l2">{bar}{words}</span></span>'
    return f'<span class="dq-el">{head}{bar}<span class="l2">{words}</span></span>'


def _element_scores(cde_cov: pd.DataFrame, run_rows: pd.DataFrame) -> dict:
    """cde_id → row-weighted quality of the checks attached to that element.

    The same arithmetic as the headline figure, over one element's share of it —
    which is what makes the two commensurable: an element's score and the page score
    are the same question asked of a smaller set of rows, not two different metrics
    that happen to both be percentages.

    `None` where the element has no check on this run, and it stays `None` rather
    than becoming a zero: an element nothing watches has no quality figure, and
    printing 0% would report the register's gap as a data defect.
    """
    if cde_cov.empty:
        return {}
    by_rule = run_rows.drop_duplicates("rule_id").set_index("rule_id")
    out = {}
    for cde_id, g in cde_cov.groupby("cde_id"):
        # Deduped across bindings: a cross-table rule attaches to all three of the
        # name element's bindings and must not be counted three times.
        ids = {i for lst in g["rule_ids"] for i in components.as_list(lst)}
        mine = by_rule[by_rule.index.isin(ids)]
        out[cde_id] = _row_score(mine) if len(mine) else None
    return out


# The element list's "everything else" entry. Named rather than dropped: a check
# that ran on no registered element is still not something to hide. Since 2026-09-28
# every rule names its element, so on the fixture the entry has nothing to list and
# does not appear.
UNATTACHED = "Not on a registered element"


# The drawer and the Sample rows tab both draw failed rows; so does the Tables
# detail page, which is why the renderer lives in components.
_failed_rows = components.failed_rows


def _check_panel(rule_id: str, tagged_now: pd.DataFrame, registry: pd.DataFrame,
                 samples: pd.DataFrame, cde_cov: pd.DataFrame,
                 cohort_of: dict, history: pd.DataFrame) -> None:
    """One check, opened up: what it looks for, the arithmetic, and the actual rows.

    The rows are the point. They were always captured — the runner samples up to a
    hundred per check — and until this panel existed the only way to see them was to
    open the cohort they belong to, which assumes a cohort was raised and that you
    already believed the check.

    A passing check opens too, since the breakdown lists every check on the element:
    it has the same rule and the same arithmetic, and no failed rows to show.
    """
    row = tagged_now[tagged_now["rule_id"] == rule_id]
    if row.empty:
        return
    row = row.iloc[0]
    reg = registry[registry["rule_id"] == rule_id]
    reg = reg.iloc[0] if not reg.empty else None

    head, close = st.columns([5, 1], vertical_alignment="center")
    with head:
        st.markdown(
            '<div class="dq-dim-panel-hd">'
            f'<span class="t">{html.escape(str(row["rule_name"]))}</span>'
            + theme.severity_badge(row["severity"])
            + theme.badge(row["Dimension"], "neutral")
            + (theme.hint(DIMENSIONS[row["Dimension"]]["long"])
               if row["Dimension"] in DIMENSIONS else "")
            + f'<span class="q"><code>{html.escape(rule_id)}</code> · '
            f'{html.escape(str(row["target_table"]))}</span></div>',
            unsafe_allow_html=True,
        )
    close.button("Close", key="_check_close", width="stretch",
                 on_click=lambda: st.session_state.pop("_check_pick", None))

    bad_rows = int(row["violation_count"])
    # Figures across the panel, prose under them — not figures in a narrow column
    # beside the prose. The drawer is 660px, so a [1, 1.5] split gave the facts about
    # 250px for two figures: "100.00% of rows checked" wrapped onto three lines
    # beside a paragraph that did not, and the two columns read as one broken block.
    st.markdown(
        '<div class="dq-tilegrid compact" '
        'style="grid-template-columns:repeat(2,minmax(0,1fr));margin:.15rem 0 .2rem">'
        '<div class="dq-tile"><div class="lab">Bad rows</div>'
        '<div class="val"'
        + (f' style="color:{theme.TONE["critical"]["fg"]}"' if bad_rows else "")
        + f'>{bad_rows:,}</div>'
        f'<div class="sub">{float(row["violation_pct"]):.2f}% of the rows checked</div>'
        "</div>"
        '<div class="dq-tile"><div class="lab">Rows checked</div>'
        f'<div class="val">{int(row["rows_scanned"]):,}</div>'
        f'<div class="sub">breaches above {float(row["threshold_pct"]):.2f}%</div>'
        "</div></div>",
        unsafe_allow_html=True,
    )
    if reg is not None:
        note = components.opt(reg["note"])
        st.markdown(
            f'<div class="dq-dim-prose"><b>What this check looks for.</b> '
            f'{html.escape(str(reg["rule_name"]))}.'
            + (f" {html.escape(str(note))}" if note else "")
            + "</div>",
            unsafe_allow_html=True,
        )
        # Its own block, not an inline `<code>` span. A rule expression is a hundred
        # characters of SQL; inline code wraps it mid-token against a tinted
        # background and the tail spills past the panel's padding.
        scope = components.opt(reg["scope_filter"])
        st.markdown(
            f'<div class="dq-expr">{html.escape(str(reg["rule_expr"]))}</div>'
            + (f'<div class="dq-expr scope">scoped to '
               f'{html.escape(str(scope))}</div>' if scope else
               '<div class="dq-dim-prose q" style="color:'
               + theme.TONE["moderate"]["fg"] + '">No scope filter — this rule runs '
               "on every row of the table.</div>"),
            unsafe_allow_html=True,
        )

    watched = cde_cov[cde_cov["rule_ids"].apply(
        lambda ids: rule_id in components.as_list(ids))]
    if not watched.empty:
        w = watched.iloc[0]
        st.caption(
            f"Watching **{w['cde_name']}** · {w['criticality']} criticality · "
            f"{'PII' if w['pii'] else 'not PII'}",
            help="Registered critical data element. This check is attached to it, "
                 "which is why it moves the quality figure on this page.",
        )
    else:
        st.caption(
            "Not attached to any registered critical data element, so this check does "
            "not move the quality figure above.",
            help="It still runs, still raises cohorts, and is still worked from "
                 "Triage. What it does not do is change a number whose denominator "
                 "is the register.",
        )

    trend = history[history["rule_id"] == rule_id].sort_values("run_ts")
    if len(trend) > 1:
        breached = trend[trend["status"] == "breach"]["run_ts"]
        st.markdown(
            '<div class="dq-quiet">Bad rows per run '
            + theme.sparkline(list(trend["violation_count"]), width=160, tone="critical")
            + (f" · first breached {breached.min():%d %b}" if len(breached)
               else " · never breached")
            + "</div>",
            unsafe_allow_html=True,
        )

    if bad_rows:
        _failed_rows(rule_id, row, samples)
    else:
        st.caption("No row failed this check on the run shown.")

    cohort_id = cohort_of.get(rule_id)
    if cohort_id:
        if st.button(f"Open the problem this belongs to · {cohort_id[:8]}",
                     key="_check_to_triage", type="primary"):
            st.session_state["selected_cohort"] = cohort_id
            st.switch_page("dq_app/ui/pages/triage_detail.py")
    else:
        st.caption("No problem has been raised for this check yet.")




# =============================================================================
# Page
# =============================================================================

components.page_chrome()

# Scheduled runs only: a shadow-only run has no score, and as "the previous run" it
# turned every change on this page into `nan`.
runs = metrics.scheduled_runs(adapter.get_check_runs())
registry = adapter.get_rule_registry_current()
# A retired rule's runs are history, not a current claim about the data: the page
# reads every run through today's register, so they leave the score, the trend and
# the element list together. Without this they would surface under "Not on a
# registered element", which is for a check that names none -- not one withdrawn.
_all_versions = adapter.get_rule_registry().sort_values("rule_version")
_retired = set(_all_versions.groupby("rule_id").tail(1).query("status == 'retired'").rule_id)
runs = runs[~runs["rule_id"].isin(_retired)]
cde_cov = adapter.get_cde_coverage()


def _page_head(sub: str = "") -> str:
    return ('<div class="dq-page-hd"><div class="t">Data quality scorecard</div>'
            + (f'<div class="s">{html.escape(sub)}</div>' if sub else "") + "</div>")


if runs.empty:
    st.markdown(_page_head(), unsafe_allow_html=True)
    st.caption("No check runs available.")
    st.stop()

# --- Title, and the two controls ----------------------------------------------
# One row: what the page is on the left, which slice of it on the right. The period
# picker that once sat here chose how much history the trend drew, which is a
# question about a chart; the control a reader actually reaches for is which RUN they
# are looking at, because every other figure on the page is one run's worth.

with st.container(key="dq_pillbar"):
    # Each control carries its own label inside its own border — see the
    # `.st-key-dq_pillbar` note in theme.py.
    head, f1, f2 = st.columns([3.1, 1.15, 1.75], vertical_alignment="center")
    with f1:
        # A dropdown, not a chip field. Every domain is selected by default, and a
        # multiselect spends a third of the strip rendering that fact back as chips.
        domains = sorted(set(metrics.domains_of(runs)))
        choice = st.selectbox("Domain", ["All"] + domains)
        picked = domains if choice == "All" else [choice]

    in_domain = runs[metrics.domains_of(runs).isin(picked)]

    with f2:
        # Newest first, and the default. Reading an older run is how someone answers
        # "was this already broken on Friday" without exporting anything.
        run_ts_of = (in_domain.groupby("run_id")["run_ts"].max()
                     .sort_values(ascending=False))
        run_ids = list(run_ts_of.index)
        shown_run = st.selectbox(
            "Run", run_ids, index=0,
            format_func=lambda r: ("Latest · " if r == run_ids[0] else "")
                                  + f"{run_ts_of[r]:%-d %b, %H:%M}",
            help="Which scheduled run this page reports. Every figure except the "
                 "trend lines is one run's worth.",
        )
    head.markdown(
        _page_head(("All domains" if choice == "All" else choice)
                   + " · targets are the tolerances the CDE register declares"),
        unsafe_allow_html=True)

cde_rules = coverage.attached_rule_ids(cde_cov)
if not cde_rules:
    st.caption(
        "No critical data elements are registered, so there is nothing to score. "
        "This page measures the rule set against the register, not against itself."
    )
    st.stop()

# `in_domain` is the whole run the reader asked for; `scoped` is the part the score is
# built on. Since 2026-09-28 every rule names its element and the two are the same
# set; a registry that predates that can still tell them apart.
scoped = in_domain[in_domain["rule_id"].isin(cde_rules)]
if scoped.empty:
    st.caption("No checks on registered elements in the selected domains.")
    st.stop()

run_index = _run_index(scoped)
# The run picked drives the page. It can be missing from the scored index only if no
# CDE-attached check ran on it, in which case the latest scored run is the honest
# fallback.
at = run_index.index[run_index["run_id"] == shown_run]
pos = int(at[0]) if len(at) else len(run_index) - 1
latest_run_id = shown_run

current_run = run_index.iloc[pos]
score = current_run["score"]
prior = run_index.iloc[pos - 1] if pos > 0 else None
score_delta = None if score is None or prior is None else score - float(prior["score"])

latest_scored = scoped[scoped["run_id"] == current_run["run_id"]]
_raised = latest_scored[latest_scored["status"].isin(["pass", "breach"])]
evaluated_rows = int(_raised["rows_scanned"].sum())
passed_rows = evaluated_rows - int(_raised["violation_count"].sum())

# A month of history up to the run being shown. Fixed rather than a control: this is
# the chart under a number, read for its shape, and a period picker beside it invited
# a reader to change the shape until it looked better.
TREND_DAYS = 30


def _in_window(index: pd.DataFrame) -> list:
    """(run_ts, score) for the runs in the trend window, oldest first."""
    part = index[(index["run_ts"] <= current_run["run_ts"])
                 & (index["run_ts"] >= current_run["run_ts"] - pd.Timedelta(days=TREND_DAYS))]
    return [(r.run_ts, r.score) for r in part.itertuples() if r.score is not None]


def _chart(points: list, target, width: int, height: int) -> str:
    return theme.target_chart([(f"{ts:%-d %b}", v) for ts, v in points], target,
                              width=width, height=height)


# --- Targets ------------------------------------------------------------------
# All three kinds come from `domain/targets.py`; this page only prints them.

el_target = targets.element_targets(adapter.get_cde_registry_current())
rule_cde = targets.rule_elements(cde_cov)
overall_target = targets.blended_target(latest_scored, rule_cde, el_target)
overall_gap = targets.shortfall(score, overall_target)
history = _in_window(run_index)


def _period_sentence(points: list, target) -> str:
    """The chart, said once in words: where the line sat against the target, and
    which way it went. Written out because the chart's hover reading gives one run at
    a time and a touch screen gives none; the reading of the whole period is here."""
    if len(points) < 2:
        return ""
    vals = [v for _, v in points]
    stood = ""
    if target is not None:
        under = sum(v < target - 1e-9 for v in vals)
        stood = ("Below target throughout this period." if under == len(vals) else
                 "At or above target throughout this period." if not under else
                 f"Below target on {under} of {len(vals)} runs.")
    change = vals[-1] - vals[0]
    days = max(1, (points[-1][0] - points[0][0]).days)
    moved = ("Flat" if abs(change) < 0.05 else
             f"{'Down' if change < 0 else 'Up'} {_pts(change)}") + f" over {days} days."
    return (f"<b>{stood}</b> " if stood else "") + moved


# --- Top row: the headline against its target, and what is being watched ------

hero, cov_col = st.columns([1.9, 1])

with hero:
    if overall_target is None:
        against = "No target — the register declares no tolerance on these elements."
    elif targets.meets(score, overall_target):
        against = f"Target {_target_text(overall_target)} · met"
    else:
        against = (f"Target {_target_text(overall_target)} · "
                   f'<span class="dq-below">{_pts(overall_gap)} below</span>')
    st.markdown(
        '<div class="dq-card dq-hero">'
        '<div class="ttl">Overall quality'
        + theme.hint(
            "Rows that passed their checks, over rows evaluated, on the run shown. "
            "Weighted by rows, so a check over 2,000 rows counts for more than a "
            "check over 40. Shadow checks are in neither half. The target is each "
            "element's own — 100 minus the tolerance the CDE register declares on "
            "it — weighted by the same rows, so it is the figure this would read if "
            "every element sat exactly on its tolerance. The line is the score per "
            f"run over {TREND_DAYS} days.", side="right")
        + '<span class="dq-lg"><i></i>Pass rate<i class="dash"></i>Target</span></div>'
        f'<div class="val"><span>{theme.pct_text(score, 1)}'
        '<span class="of unit">%</span></span>'
        + (theme.delta(score_delta, " pts", 1) if prior is not None else "")
        + "</div>"
        f'<div class="sub">{against}</div>'
        + _chart(history, overall_target, 600, 150)
        # The operands, not just the percentage: a figure whose numerator and
        # denominator have been thrown away is how a scorecard starts lying.
        + f'<div class="say">{_period_sentence(history, overall_target)} '
        f"{passed_rows:,} of {evaluated_rows:,} checked rows passed on this run.</div>"
        "</div>",
        unsafe_allow_html=True,
    )

# Per ELEMENT, not per binding. Three bindings of Customer name all unvalidated is
# one element nothing validates, not three findings.
_gap_rank = {g: i for i, g in enumerate(theme.COVERAGE_GAP_ORDER)}
_crit_rank = {c: i for i, c in enumerate(theme.CRITICALITY_ORDER)}
_elements = (cde_cov
             .assign(_g=cde_cov["coverage_gap"].map(_gap_rank),
                     _c=cde_cov["criticality"].map(_crit_rank))
             .sort_values("_g")
             .groupby("cde_id", as_index=False).head(1))
_gapc = _elements["coverage_gap"].value_counts().to_dict()
n_elements = coverage.coverage_summary(cde_cov)["elements"]

current = adapter.get_cohort_current()
open_now = current[current["lifecycle_state"].isin(lifecycle.OPEN_STATES)]
waiting_on_a_person = open_now[
    open_now["lifecycle_state"].isin(["reopened", "awaiting_review", "awaiting_approval"])
]

# The same three buckets the bar draws, in the order it draws them. "Out of scope"
# is two findings — nothing checks the element, or a rule contradicts its binding —
# and the tooltip says which.
COVERAGE_SHARES = [
    ("Covered", _gapc.get("covered", 0), theme.ACCENT),
    ("Not validated", _gapc.get("unvalidated", 0), theme.TONE["info"]["bd"]),
    ("Out of scope", _gapc.get("no_rule", 0) + _gapc.get("scope_mismatch", 0),
     theme.NEUTRAL["border_strong"]),
]

# A keyed container rather than one block of markup, because its floor is a control:
# the open-problems count is the page's way into the Triage queue. The row is a
# `clickable_rows` row like every other on this page — the whole band is the target.
with cov_col, st.container(key="dq_covcard"):
    st.markdown(
        '<div class="dq-card dq-cov">'
        '<div class="ttl">Monitoring coverage'
        + theme.hint(
            theme.CDE_ONE_LINER + " Counted by element and by its worst finding: an "
            "element bound to three columns, none of them validated, is one gap. "
            "Covered: a rule examines the values themselves. Not validated: something "
            "watches it, but only that a value is present or agrees with another. "
            f"Out of scope: nothing checks it ({_gapc.get('no_rule', 0)}), or a rule "
            f"contradicts the register's scope ({_gapc.get('scope_mismatch', 0)}).")
        + "</div>"
        f'<div class="val">{COVERAGE_SHARES[0][1]}'
        f'<span class="of">of {n_elements} CDEs covered</span></div>'
        '<div class="dq-cov3">'
        + "".join(f'<span style="flex:{n} 1 0;background:{colour}"></span>'
                  for _, n, colour in COVERAGE_SHARES if n)
        + "</div>"
        + "".join(f'<div class="row"><i style="background:{colour}"></i>{label}'
                  f"<b>{n}</b></div>" for label, n, colour in COVERAGE_SHARES)
        + "</div>",
        unsafe_allow_html=True,
    )
    if components.clickable_rows(
            [{"key": "queue"}], "minmax(0,1fr) auto",
            lambda _: (
                '<span class="stack"><span class="t1">Open problems</span>'
                f'<span class="t2 sans">{len(waiting_on_a_person)} waiting on a person'
                "</span></span>"
                f'<span class="opn">{len(open_now)}{theme.icon("arrow_right", 15)}</span>'),
            "op", "key", lambda _: "Open the Triage queue"):
        st.switch_page("dq_app/ui/pages/triage.py")

# --- Elements on the left, the one picked on the right ------------------------
# Master–detail. The list is every registered element with its score drawn against
# its target; picking one puts that element's trend and every check on it in the card
# beside it. The order is the page's argument: largest shortfall first among the
# scores that can be read against a target, then the rest by how much they matter.

NONE_SCOPE = "__none__"
PRIORITY = 5
# The two cards are the same height by construction, not by luck. The list shows five
# rows and scrolls past that; the element card's header is a fixed set of lines and
# everything that varies in length — nine checks, a hundred sampled rows — sits in a
# tab whose body is this tall and scrolls inside. theme.py stretches both cards to
# the row as well, so a header that wraps to an extra line still cannot stagger the
# two floors.
LIST_BODY = 412
TAB_BODY = 352


# Everything below is one fragment: picking an element, opening a check, switching a
# tab or the Priority / All toggle redraws these two cards and the drawers, not the
# filters, the headline or the coverage card above, none of which reads a selection
# made here. Nothing in it may call `st.rerun()` -- that is a full-page run again --
# so every selection is an `on_click` (`components.pick_into`). A filter changed above
# is a full run, and the fragment is drawn afresh inside it.


@st.fragment
def _elements_and_pane() -> None:
    tagged_now = _tagged(in_domain, registry, latest_run_id)
    ran_now = tagged_now[tagged_now["status"].isin(["pass", "breach"])]
    ran_ids = set(ran_now["rule_id"])
    failing_ids = set(ran_now[ran_now["status"] == "breach"]["rule_id"])
    all_cohorts = adapter.get_cohorts()
    cohort_of = metrics.cohort_for_rules(all_cohorts, set(tagged_now["rule_id"]))
    monitored_tables = sorted(in_domain["target_table"].dropna().unique())
    unattached_ids = ran_ids - set(cde_rules)
    # Rules the register says measure rows they should not. Their breach is a fact about
    # the rule, so their rows are never painted as bad data.
    disputed_ids = {i for lst in cde_cov["unscoped_rule_ids"] for i in components.as_list(lst)}

    _run_rows = in_domain[in_domain["run_id"] == latest_run_id]
    el_scores = _element_scores(cde_cov, _run_rows)
    el_before = (_element_scores(cde_cov, in_domain[in_domain["run_id"] == prior["run_id"]])
                 if prior is not None else {})
    rules_of = {cid: {i for lst in g["rule_ids"] for i in components.as_list(lst)}
                for cid, g in cde_cov.groupby("cde_id")}
    gaps_of = {cid: set(g["coverage_gap"]) for cid, g in cde_cov.groupby("cde_id")}
    columns_of = {cid: [f"{str(r.target_table).split('.')[-1]}.{r.target_column}"
                        for r in g.itertuples()]
                  for cid, g in cde_cov.groupby("cde_id")}

    el_rows = []
    for _, r in _elements.iterrows():
        cid = r["cde_id"]
        el_score, target = el_scores.get(cid), el_target.get(cid)
        is_assessed = targets.assessed(gaps_of[cid], el_score, target)
        met = is_assessed and targets.meets(el_score, target)
        coverage_word = theme.COVERAGE_GAP_LABEL.get(r["coverage_gap"], r["coverage_gap"])
        if not is_assessed:
            # Why there is no verdict, in the register's own word for it. A missing score
            # is a dash, never a zero: nothing watching an element is a gap in the
            # register, and zero percent would report it as a data defect.
            line = (f"No check ran · {coverage_word}" if el_score is None else
                    f"Not assessed · {coverage_word}" if target is not None else
                    f"No target declared · {coverage_word}")
        elif met:
            line = f"Meets target · {_target_text(target)}"
        else:
            line = (f"{_pts(targets.shortfall(el_score, target))} below target · "
                    f"{_target_text(target)}")
        el_rows.append({
            "key": cid, "Element": r["cde_name"], "Criticality": r["criticality"],
            "Kind": theme.data_class_label(r["data_class"]), "Coverage": coverage_word,
            "Score": el_score, "Target": target, "Assessed": is_assessed, "Met": met,
            "Line": line, "Change": _change_words(el_score, el_before.get(cid)),
            "Colour": UNASSESSED if not is_assessed else MET if met else BELOW,
            "_order": ((0, -targets.shortfall(el_score, target), r["cde_name"])
                       if is_assessed else
                       (1, _crit_rank.get(r["criticality"], 9),
                        101.0 if el_score is None else el_score, r["cde_name"])),
        })
    el_rows.sort(key=lambda row: row["_order"])
    n_below = sum(row["Assessed"] and not row["Met"] for row in el_rows)
    n_met = sum(row["Met"] for row in el_rows)

    # Conditional, and normally absent: every rule names its element. It stays for a
    # registry that predates that rule or a run that carried a check whose element has
    # since been retired.
    extra_rows = []
    if unattached_ids:
        extra_rows.append({
            "key": NONE_SCOPE, "Element": UNATTACHED, "Criticality": None, "Kind": "",
            "Coverage": "", "Score": None, "Target": None, "Assessed": False, "Met": False,
            "Line": f"{len(unattached_ids & failing_ids)} of {len(unattached_ids)} failing "
                    "· not scored",
            "Change": "", "Colour": UNASSESSED,
        })

    scope = st.session_state.get("_elem_scope")
    if scope not in {row["key"] for row in el_rows + extra_rows}:
        scope = el_rows[0]["key"]


    def _el_cells(row) -> str:
        dot = ""
        if row["Criticality"]:
            tone = theme.CRITICALITY_TONE.get(row["Criticality"], "neutral")
            dot = f'<i class="dq-eldot" style="background:{theme.TONE[tone]["fg"]}"></i>'
        # Red for a score under its target and for nothing else. A met target and an
        # unassessed score both print in ink; the bar and the line under it tell them
        # apart.
        figure_colour = BELOW if row["Colour"] == BELOW else (
            theme.NEUTRAL["text"] if row["Assessed"] else theme.NEUTRAL["text_2"])
        return _row_markup(
            row["Element"], "—" if row["Score"] is None else _pct(row["Score"]),
            figure_colour, theme.target_bar(row["Score"], row["Target"], row["Colour"]),
            row["Line"], row["Change"], dot)


    def _el_tip(row) -> list:
        if not row["Criticality"]:
            return [row["Element"], row["Line"]]
        cols = columns_of.get(row["key"], [])
        return [row["Element"],
                f"{str(row['Criticality']).capitalize()} criticality · {row['Kind']} · "
                f"{row['Coverage']}",
                (" · ".join(cols), "mono") if cols else None]


    # Keyed so theme.py can let the two cards wrap: side by side on a narrow page they
    # cut every element and check name to a few letters.
    with st.container(key="dq_elsplit"):
        left, right = st.columns([1, 1.5], gap="medium")

    with left, st.container(key="dq_elcard"):
        st.markdown(
            '<div class="dq-elcard-hd"><div class="t">Critical data elements'
            + theme.hint(
                "A score is read against its target only where something validates the "
                "element's values and no rule on it contradicts the register's scope. "
                "An element nothing validates can score 100% on a presence check, and a "
                "scope mismatch scores low because of the rule, not the data — both "
                "keep their figure, in grey, and are counted as unassessed.", side="right")
            + "</div>"
            f'<div class="q">{n_below} below target · {n_met} meeting target · '
            f"{len(el_rows) - n_below - n_met} unassessed</div></div>",
            unsafe_allow_html=True,
        )
        # Five by default: the list is sorted so that the top of it is the answer to
        # "where do I look first", and twenty rows of mostly-fine is how that answer
        # gets scrolled past. Everything is one click away, and counted on the label.
        st.session_state.setdefault("_elist_show", "priority")
        n_priority = min(PRIORITY, len(el_rows))
        show = st.segmented_control(
            "Elements shown", ["priority", "all"], key="_elist_show",
            label_visibility="collapsed",
            format_func=lambda v: (f"Priority {n_priority}" if v == "priority"
                                   else f"All {len(el_rows)}"))
        listed = el_rows + extra_rows if show == "all" else el_rows[:n_priority]
        # Five rows high in both modes: `All` scrolls inside the same box `Priority`
        # fills, so switching between them does not move the card's floor — or the
        # floor of the card beside it.
        with st.container(height=LIST_BODY if len(listed) > n_priority else "content",
                          key="dqrows_elist"):
            components.clickable_rows(
                listed, ROW_GRID, _el_cells, "el", "key",
                lambda row: f"Show {row['Element']}", picked=scope, tip=_el_tip,
                # A check picked under the old element is not in the new one's breakdown,
                # and a drawer left open over a list that no longer shows its check reads
                # as a bug.
                on_pick=components.pick_into("_elem_scope", clear=("_check_pick",)))
        st.markdown(
            '<div class="dq-elfoot"><span>Bars: 0–100%<i></i>Target</span>'
            "<span>Largest target gap first</span></div>",
            unsafe_allow_html=True)

    # --- The right card: one element against its target, and its checks ------------

    sel = next(row for row in el_rows + extra_rows if row["key"] == scope)
    scope_rules = unattached_ids if scope == NONE_SCOPE else rules_of.get(scope, set())
    picked_rule = st.session_state.get("_check_pick")


    def _check_rows(rule_ids: set) -> list[dict]:
        """Every check that ran on these rules, failing first and worst first within
        that. Passing checks are listed too: an element's score is all of its checks, and
        a breakdown showing only the failures cannot be added back up to it."""
        past = in_domain[["rule_id", "run_ts", "status"]]
        rows = []
        for r in ran_now[ran_now["rule_id"].isin(rule_ids)].itertuples():
            breach = r.status == "breach"
            rows.append({
                "Rule id": r.rule_id, "Check": r.rule_name, "Dimension": r.Dimension,
                "Where": _where(r, monitored_tables),
                "Rate": 100.0 - float(r.violation_pct),
                "Target": None if pd.isna(r.threshold_pct) else 100.0 - float(r.threshold_pct),
                "Bad": int(r.violation_count), "Of": int(r.rows_scanned),
                "Breach": breach, "Disputed": breach and r.rule_id in disputed_ids,
                "Since": _failing_since(past, r.rule_id) if breach else None,
            })
        return sorted(rows, key=lambda c: (not c["Breach"], -c["Bad"], c["Check"]))


    def _check_cells(row) -> str:
        colour = (UNASSESSED if row["Disputed"] else BELOW if row["Breach"] else MET)
        figure = (f'{_pct(row["Rate"])}'
                  + (f'<span class="of"> / {_target_text(row["Target"])}</span>'
                     if row["Target"] is not None else ""))
        return _row_markup(
            row["Check"], figure,
            BELOW if colour == BELOW else theme.NEUTRAL["text"],
            theme.target_bar(row["Rate"], row["Target"], colour),
            f"{row['Bad']:,} / {row['Of']:,} failing rows"
            + (f" · since {row['Since']}" if row["Since"] else ""),
            "Rule scope disputed" if row["Disputed"] else
            "Below target" if row["Breach"] else "Meets target", compact=True)


    def _check_tip(row) -> list:
        spec = DIMENSIONS.get(row["Dimension"])
        return [row["Check"], (row["Where"], "mono"),
                f"{row['Dimension']} — {spec['short']}" if spec else row["Dimension"]]


    def _problem_rows(rule_ids: set) -> list[dict]:
        """The problems carrying these rules' failing checks — this page's way into
        Triage for one element. One row per problem, however many of the element's
        checks it holds, titled by `components.problem_title` so a problem has the same
        name here as on the queue and on its own page."""
        mine = {}
        for rule_id in sorted(rule_ids & failing_ids):
            if rule_id in cohort_of:
                mine.setdefault(cohort_of[rule_id], []).append(rule_id)
        state_of = current.set_index("cohort_id")
        rows = []
        for cohort_id, held in mine.items():
            cohort = all_cohorts[all_cohorts["cohort_id"] == cohort_id].iloc[0]
            elements, _ = components.cohort_elements(cohort["member_rule_ids"], cde_cov)
            state = state_of.loc[cohort_id] if cohort_id in state_of.index else None
            waiting = components.waiting_on(state) if state is not None else "\u2014"
            rows.append({
                "cohort_id": cohort_id,
                "Problem": components.problem_title(cohort, elements, registry),
                "State": None if state is None else state["lifecycle_state"],
                "Line": f"{len(held)} of this element's failing "
                        f"{'check' if len(held) == 1 else 'checks'}"
                        + (f" · waiting on {waiting}" if waiting != "\u2014" else ""),
                "Raised": cohort["raised_ts"],
            })
        return sorted(rows, key=lambda row: row["Raised"], reverse=True)


    def _problem_cells(row) -> str:
        return (
            '<span class="stack">'
            f'<span class="t1 wrap">{html.escape(str(row["Problem"]))}</span>'
            f'<span class="t2 sans">{html.escape(row["Line"])}</span></span>'
            + (f'<span>{theme.state_badge(row["State"])}</span>' if row["State"] else "<span></span>")
            + f'<span class="opn">{theme.icon("arrow_right", 15)}</span>'
        )


    checks = _check_rows(scope_rules)
    problems = _problem_rows(scope_rules)

    with right, st.container(key="dq_elpane"):
        if scope == NONE_SCOPE:
            badges = theme.badge("not scored", "neutral")
            where, hist, note = f"{len(unattached_ids)} checks", [], \
                "Not counted in the quality score."
        else:
            er = _elements[_elements["cde_id"] == scope].iloc[0]
            badges = (theme.criticality_badge(er["criticality"])
                      + theme.badge(theme.data_class_label(er["data_class"]), "neutral")
                      + theme.coverage_badge(er["coverage_gap"])
                      + (theme.badge("PII", "high", "shield") if er["pii"] else ""))
            cols = columns_of.get(scope, [])
            where = " · ".join(cols[:3]) + (f" + {len(cols) - 3} more" if len(cols) > 3 else "")
            hist = _in_window(_run_index(in_domain[in_domain["rule_id"].isin(scope_rules)])) \
                if scope_rules else []
            bad = sum(c["Bad"] for c in checks)
            failing = sum(c["Breach"] for c in checks)
            if not sel["Assessed"]:
                # The register's own account of why this score carries no verdict.
                note = theme.COVERAGE_GAP_MEANING.get(er["coverage_gap"], "")
            elif sel["Met"]:
                note = (f"<b>Meets its {_pct(sel['Target'])} target.</b> "
                        + (f"{bad:,} {'row still fails' if bad == 1 else 'rows still fail'} "
                           "a check; passing the threshold does not mean zero defects."
                           if bad else "No row failed a check on this run."))
            else:
                # Failures, not rows: one row can fail more than one check, and
                # `check_run` keeps a count per check and no keys to de-duplicate on.
                note = (f"<b>{_pts(targets.shortfall(sel['Score'], sel['Target']))} below "
                        f"its {_pct(sel['Target'])} target.</b> {bad:,} failures across "
                        f"{failing} of {len(checks)} checks.")

        verdict = ("" if sel["Target"] is None else
                   f'<span>Target {_target_text(sel["Target"])}</span>'
                   + ('<span>Not assessed</span>' if not sel["Assessed"] else
                      '<span>Meets target</span>' if sel["Met"] else
                      f'<span class="dq-below">'
                      f'{_pts(targets.shortfall(sel["Score"], sel["Target"]))} below</span>'))
        change = _change_words(hist[-1][1], hist[-2][1]) if len(hist) > 1 else ""
        # The target is drawn only where the score is assessed against it. A dashed line
        # forty-nine points above a scope mismatch's series is "below target" said with a
        # ruler, and the header has just declined to say it in words.
        drawn_target = sel["Target"] if sel["Assessed"] else None

        # Above the tabs, on all four: which element, and its figure against its target.
        st.markdown(
            '<div class="dq-elhd"><div class="k">Selected element</div>'
            f'<div class="n">{html.escape(sel["Element"])}</div>'
            f'<div class="b">{badges}</div>'
            f'<div class="w">{html.escape(where)}</div>'
            + ('<div class="sr">'
               f'<span class="s" style="color:'
               f'{BELOW if sel["Colour"] == BELOW else theme.NEUTRAL["text"]}">'
               f'{_pct(sel["Score"])}</span>{verdict}</div>'
               if sel["Score"] is not None else
               '<div class="sr"><span class="s">\u2014</span><span>No check ran</span></div>')
            + "</div>",
            unsafe_allow_html=True,
        )

        # Four tabs, each labelled with what is behind it, so the card is one height
        # whatever the element holds. Until 2026-10-01 these were stacked, and an element
        # with nine checks ran the card to three times the height of the list beside it.
        samples = adapter.get_violation_samples()
        with_rows = [c for c in checks if c["Bad"]]
        captured = int(((samples["rule_id"].isin({c["Rule id"] for c in with_rows}))
                        & (samples["run_id"] == latest_run_id)).sum())
        tab_overview, tab_checks, tab_rows, tab_triage = st.tabs([
            "Overview",
            f"Checks · {len(checks)}" if checks else "Checks",
            f"Sample rows · {captured:,}" if captured else "Sample rows",
            f"Triage · {len(problems)}" if problems else "Triage",
        ])

        with tab_overview, st.container(height=TAB_BODY, border=False, key="dq_eltab_overview"):
            if len(hist) > 1 or note:
                st.markdown(
                    '<div class="dq-elover">'
                    + (f'<div class="d">{change} since last run</div>' if change else "")
                    + ('<div><span class="dq-lg"><i></i>30-day trend'
                       + ('<i class="dash"></i>Target' if drawn_target is not None else "")
                       + "</span></div>" + _chart(hist, drawn_target, 580, 140)
                       if len(hist) > 1 else "")
                    + (f'<div class="dq-elnote">{note}</div>' if note else "")
                    + "</div>",
                    unsafe_allow_html=True,
                )
            if scope != NONE_SCOPE:
                st.button("Every binding and what checks it", key="_el_details",
                          icon=":material/open_in_new:", type="tertiary",
                          on_click=lambda: st.session_state.update(_cde_pick=scope))

        with tab_checks:
            if checks:
                with st.container(height=TAB_BODY, border=False, key="dqrows_checks"):
                    components.clickable_rows(
                        checks, ROW_GRID, _check_cells, "ck", "Rule id",
                        lambda row: f"Open {row['Check']}", picked=picked_rule,
                        tip=_check_tip, on_pick=components.pick_into("_check_pick"))
            else:
                with st.container(height=TAB_BODY, border=False, key="dq_eltab_nochecks"):
                    st.caption("No active check ran on this element on the run shown.")

        # The rows behind the counts, one check at a time: each check's sample has its
        # own columns, and stacking nine tables is what the detail page stopped doing.
        # The same rows, the same columns and the same cap as the check drawer — this
        # tab does not widen the one PII surface, it gives it a second door.
        with tab_rows, st.container(height=TAB_BODY, border=False, key="dq_eltab_rows"):
            if not with_rows:
                st.caption("No row failed a check on this element on the run shown.")
            else:
                by_id = {c["Rule id"]: c for c in with_rows}
                shown_check = st.selectbox(
                    "Check", list(by_id), key=f"_rows_check_{scope}",
                    format_func=lambda i: f"{by_id[i]['Check']} · {by_id[i]['Bad']:,} failing")
                _failed_rows(shown_check,
                             tagged_now[tagged_now["rule_id"] == shown_check].iloc[0],
                             samples, heading=False)

        # A row here is a link, not a selection — it leaves the page — so it takes no
        # `picked`.
        with tab_triage:
            if problems:
                with st.container(height=TAB_BODY, border=False, key="dqrows_problems"):
                    got = components.clickable_rows(
                        problems, "minmax(0,1fr) auto auto", _problem_cells, "pb",
                        "cohort_id", lambda row: f"Open {row['Problem']} in Triage")
                if got:
                    st.session_state["selected_cohort"] = got
                    st.switch_page("dq_app/ui/pages/triage_detail.py")
            else:
                with st.container(height=TAB_BODY, border=False, key="dq_eltab_notriage"):
                    st.caption(
                        "No problem has been raised for this element's failing checks yet."
                        if scope_rules & failing_ids else
                        "Nothing on this element is failing, so there is no problem to open.")


    # Held in session rather than read straight off the click, so the panel survives a
    # rerun the list did not cause — and so a link, or a test, can open a check without
    # clicking one. Any check that ran opens, whichever element is picked, so a test or a
    # link that names a check does not first have to pick its element.
    if picked_rule in ran_ids:
        with st.container(key="dq_check_drawer"):
            _check_panel(picked_rule, tagged_now, registry, samples, cde_cov, cohort_of,
                         in_domain[["rule_id", "run_ts", "violation_count", "status"]])
    # The element drawer, and only when no check drawer is open — two fixed panels at the
    # same edge would stack on top of each other.
    elif st.session_state.get("_cde_pick"):
        with st.container(key="dq_element_drawer"):
            components.element_panel(cde_cov, registry, st.session_state["_cde_pick"],
                                     pick_key="_cde_pick")


_elements_and_pane()

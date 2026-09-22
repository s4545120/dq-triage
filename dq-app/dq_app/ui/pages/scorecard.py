"""Scorecard — how healthy is the watched data, and what is being watched.

**Two denominators live on this page, and both are stated where they sit.**

The quality score is scoped: a check counts towards it only if `v_cde_coverage`
attached it to a registered critical data element — 20 of the 34 rules in the fixture.
A quality score whose denominator is "every rule someone happened to write" moves
whenever the rule set does and cannot be compared across two months or two domains.
`domain/coverage.attached_rule_ids` is the single definition of that set, read back
off the coverage view so this page and the coverage panel can never disagree.

Everything else — the estate tiles, the failing-checks table — counts the whole run.
Reporting "2 tables monitored" over only the attached checks would understate what
actually runs, and a diagnostic table that hides 14 of 34 failing checks is worse than
one that shows them all. So the tiles carry "every check that ran" in their heading
and the score carries its scope in the strip above it.

**The elements themselves no longer have a page.** `Data elements` was removed on
2026-09-16: nobody browses a register. What it was actually read for is here — the
scope panel behind the strip badge lists every element and what watches it, and the
element list beside the failing checks lists every element with its score. The model is
untouched; only the browsing surface went.

**The element band reports; it does not advise.** It carries the element, its kind,
its criticality, how it is covered and how it scores, and nothing that tells anyone
what to do about any of that. Recommending a fix for a gap in the register is out of
scope for this app — the band's job is to say what the register holds and how the
data behind it is doing, and the decision about a missing rule belongs to whoever
authors rules.

**A gap and a low score are different findings and the band shows both.** An element
nothing validates can still score 100%: the presence check attached to it passes on
every row, which says nothing about what those rows contain. That is why the coverage
column sits beside the score rather than instead of it — a score with no coverage
behind it is the quietest failure on this page.

**Elements on the left, their failing checks on the right.** Since 2026-09-22 the
element list is the filter: picking one shows that element's score — the headline's
arithmetic over its own checks — its trend, and only the checks that watch it.
`All checks` is the whole run, and `Not on a registered element` is its own entry,
because those are exactly the checks a register-shaped control would otherwise hide.
This replaced an `Element kind` dropdown over one table and an element band under it,
which asked the reader to join the two in their head.

**Failing checks open.** Selecting one shows the rule in plain words, the arithmetic,
and the rows that actually failed — parsed into columns, from
`results.violation_sample`. The samples were always captured; until now they could
only be seen from inside a cohort.

**Dimensions are a grouping, not a headline.** Completeness / Validity / Consistency /
Uniqueness used to be four cards at the top. They are now a toggle on the failing-checks
table, which is where the question they answer ("which kind of thing is wrong") is
actually being asked.

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
from dq_app.domain import coverage, lifecycle, metrics
from dq_app.ui import components, theme

# --- Scoring ----------------------------------------------------------------
# Two different quality numbers live on this page and they are not interchangeable:
#
#   * "Checks run" counts CHECKS. It is what a rule author cares about, and it treats
#     a check over 2,000 rows and a check over 40 alike.
#   * "Overall quality" weights by ROWS — evaluated rows that passed, over evaluated
#     rows. It is what a consumer of the data cares about.
#
# They diverge sharply here and that divergence is informative: most checks fail, but
# they fail on a small share of rows. Showing only one of the two would hide that.


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
# `_DIMENSION_OF` is the only place a rule type is assigned to a dimension. The prose
# below describes the dimensions; the membership of each one is read back off this
# map by `_types_in`, so a new rule type cannot end up described in one place and
# counted in another.

_DIMENSION_OF = {
    "not_null": "Completeness",
    "format": "Validity",
    "sentinel": "Validity",
    "variance": "Validity",
    "consistency": "Consistency",
    "referential": "Consistency",
    "uniqueness": "Uniqueness",
}


def _dimension_for(rule_type: str) -> str:
    """Map local rule types to the DQ dimensions used in monitoring tools."""
    return _DIMENSION_OF.get(rule_type, "Other")


def _types_in(name: str) -> list[str]:
    return [t for t, d in _DIMENSION_OF.items() if d == name]


# The prose survived the demotion from four cards to a grouping. "Validity" is a term
# of art — not a word a steward uses about their own data — and the group header is
# still the only place it gets defined.

DIMENSIONS = [
    {
        "name": "Completeness",
        "icon": "file",
        "short": "Is the value there at all.",
        "long": (
            "Whether a value a record is supposed to carry is actually there. A "
            "completeness check counts the rows where the column is null, blank, or "
            "holds a placeholder standing in for a value nobody ever supplied. It "
            "says nothing about whether the value that is there is any good — that "
            "is Validity's job."
        ),
    },
    {
        "name": "Validity",
        "icon": "shield",
        "short": "Does the value look like what it claims to be.",
        "long": (
            "Whether a value that is present conforms to the shape it is supposed to "
            "have: an email with an @ and a real top-level domain, a mobile number "
            "matching 04########, a date of birth that parses and puts the person "
            "between 18 and 105. Placeholder values that pass a presence check but "
            "mean nothing — 0400000000, a row of nines — are caught here too. A "
            "valid value can still be the wrong value; no automated check can tell."
        ),
    },
    {
        "name": "Consistency",
        "icon": "nodes",
        "short": "Does it agree with the other columns and tables.",
        "long": (
            "Whether a value agrees with the rest of the record and the rest of the "
            "estate. Two columns that have to move together — a document number "
            "present whenever a document type is set — and two tables that have to "
            "tell the same story about the same person. Each side can be perfectly "
            "complete and perfectly valid and still disagree, which is why this is a "
            "dimension of its own."
        ),
    },
    {
        "name": "Uniqueness",
        "icon": "copy",
        "short": "Is it there exactly once.",
        "long": (
            "Whether a value that is supposed to identify one thing identifies "
            "exactly one. A mobile service number live on two subscriptions at once "
            "is not a wrong value in either row — both rows are individually fine, "
            "and the defect only exists in the pair."
        ),
    },
]
DIMENSION_BY_NAME = {d["name"]: d for d in DIMENSIONS}
DIMENSION_ORDER = [d["name"] for d in DIMENSIONS] + ["Other"]

SCORING_NOTE = (
    "Scored by rows: evaluated rows that passed the active checks in this dimension, "
    "over evaluated rows for those checks. This is aggregate check-level scoring — an "
    "exact record-level figure would need a key for every finding, which the runner "
    "keeps only for its samples. Shadow checks are in neither half."
)


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


# --- The failing-checks table ------------------------------------------------


def _problem_titles(cohorts: pd.DataFrame, cde_cov: pd.DataFrame,
                    registry: pd.DataFrame) -> dict:
    """cohort_id → the problem's title. One derivation, in
    `components.problem_title`, shared with the Triage queue and the detail page —
    three copies are three chances for one problem to have three different names."""
    out = {}
    for _, r in cohorts.iterrows():
        elements, _ = components.cohort_elements(r["member_rule_ids"], cde_cov)
        out[r["cohort_id"]] = components.problem_title(r, elements, registry)
    return out


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


def _trend_of(history: pd.DataFrame, rule_id: str) -> tuple[str, str]:
    """When this check started failing, or that it has been failing all along.

    "new 28 Aug" beside nine email checks is the whole of COH-A's evidence — nine
    rules clean on every run to the 27th and breaching together on the first run
    after is the shape of a release, not of data drifting. A column of "steady" with
    one "new" in it is the only place on this page that distinction is visible
    without opening anything.
    """
    h = history[(history["rule_id"] == rule_id)
                & history["status"].isin(["pass", "breach"])].sort_values("run_ts")
    if h.empty:
        return "\u2014", "neutral"
    statuses = list(h["status"])
    stamps = list(h["run_ts"])
    i = len(statuses) - 1
    while i > 0 and statuses[i - 1] == "breach":
        i -= 1
    if i == 0:
        return "steady", "neutral"
    return f"new {stamps[i]:%-d %b}", "critical"


def _failing_frame(tagged_now: pd.DataFrame, attached: set[str], cohort_of: dict,
                   history: pd.DataFrame, tables: list[str]) -> pd.DataFrame:
    """One row per check failing on the run being shown, worst first.

    Both scored and unscored checks are listed. A check on an unregistered column
    still runs, still raises a cohort and still has bad rows behind it — hiding it
    would make this page disagree with the Triage queue, which is where it gets
    worked. What the two kinds do differently is move the figure above, and that is
    said once, in the strip, rather than as a tick per row.
    """
    rows = []
    for r in tagged_now[tagged_now["status"] == "breach"].itertuples():
        trend, trend_tone = _trend_of(history, r.rule_id)
        rows.append({
            "Check": r.rule_name,
            "Where": _where(r, tables),
            "Severity": r.severity,
            "Dimension": r.Dimension,
            "Bad rows": int(r.violation_count),
            "Of": int(r.rows_scanned),
            "Trend": trend,
            "Trend tone": trend_tone,
            "Problem": cohort_of.get(r.rule_id, ""),
            "Scored": r.rule_id in attached,
            "Rule id": r.rule_id,
        })
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(["Bad rows", "Check"],
                           ascending=[False, True]).reset_index(drop=True)


# Both tables on this page are drawn with `components.clickable_rows` rather than
# `st.dataframe` — see the comment above that helper for the three reasons.

# In the right-hand pane, two-thirds of the page wide, so narrower than it was: where
# the check looks is its second line, and dimension is the grouping toggle rather
# than a column.
FAILING_GRID = ("minmax(0,2.2fr) 3rem 4.2rem 3.8rem minmax(0,.85fr) minmax(0,1.6fr)")
FAILING_HEADS = ["Check", "Sev", ("Bad rows", "n"), ("Of", "n"), "Trend", "Problem"]


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


# The element list's "everything else" entry. Named rather than dropped:
# 14 of the 34 checks in the fixture are attached to no registered element, and a
# list that could only ever narrow to the register would hide them behind a control
# that does not say it is hiding anything.
UNATTACHED = "Not on a registered element"


def _check_panel(rule_id: str, tagged_now: pd.DataFrame, registry: pd.DataFrame,
                 samples: pd.DataFrame, cde_cov: pd.DataFrame,
                 cohort_of: dict, history: pd.DataFrame) -> None:
    """One check, opened up: what it looks for, the arithmetic, and the actual rows.

    The rows are the point. They were always captured — the runner samples up to a
    hundred per check — and until this panel existed the only way to see them was to
    open the cohort they belong to, which assumes a cohort was raised and that you
    already believed the check.
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
            + f'<span class="q"><code>{html.escape(rule_id)}</code> · '
            f'{html.escape(str(row["target_table"]))}</span></div>',
            unsafe_allow_html=True,
        )
    if close.button("Close", key="_check_close", width="stretch"):
        # Bumping the nonce rebuilds the table widget, which is the only way to clear
        # a dataframe selection — leave it and the panel reopens on the next rerun.
        st.session_state["_fail_nonce"] = st.session_state.get("_fail_nonce", 0) + 1
        st.session_state.pop("_check_pick", None)
        st.rerun()

    # Figures across the panel, prose under them — not figures in a narrow column
    # beside the prose. The drawer is 660px, so a [1, 1.5] split gave the facts about
    # 250px for two figures: "100.00% of rows checked" wrapped onto three lines
    # beside a paragraph that did not, and the two columns read as one broken block.
    st.markdown(
        '<div class="dq-tilegrid compact" '
        'style="grid-template-columns:repeat(2,minmax(0,1fr));margin:.15rem 0 .2rem">'
        '<div class="dq-tile"><div class="lab">Bad rows</div>'
        f'<div class="val" style="color:{theme.TONE["critical"]["fg"]}">'
        f'{int(row["violation_count"]):,}</div>'
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
        st.markdown(
            '<div class="dq-quiet">Bad rows per run '
            + theme.sparkline(list(trend["violation_count"]), width=160, tone="critical")
            + f" · first breached {trend[trend['status'] == 'breach']['run_ts'].min():%d %b}"
            "</div>",
            unsafe_allow_html=True,
        )

    theme.section("The rows that failed")
    mine = samples[(samples["rule_id"] == rule_id) & (samples["run_id"] == row["run_id"])]
    if mine.empty:
        mine = samples[samples["rule_id"] == rule_id]
        if not mine.empty:
            st.caption("No samples from this run — showing the latest captured for "
                       "this check.")
    if mine.empty:
        st.caption("No rows were sampled for this check. Historical breaches carry "
                   "counts only.")
    else:
        st.caption(
            f"{len(mine):,} of {int(row['violation_count']):,} captured"
            + (" — the runner caps what it keeps per check, so this is a sample, not "
               "the set." if len(mine) < int(row["violation_count"]) else "."),
            help="The one accepted PII surface in this design. The element profile "
                 "stores no values at all, and this panel does not widen what the "
                 "cohort view already showed — same rows, same columns, same cap.",
        )
        components.sample_rows_view(mine)

    cohort_id = cohort_of.get(rule_id)
    if cohort_id:
        if st.button(f"Open the problem this belongs to · {cohort_id[:8]}",
                     key="_check_to_triage", type="primary"):
            st.session_state["selected_cohort"] = cohort_id
            st.switch_page("dq_app/ui/pages/triage_detail.py")
    else:
        st.caption("No problem has been raised for this check yet.")


# --- The scope panel — what the old Data elements page was actually read for --


def _scope_panel(cde_cov: pd.DataFrame, scoped: pd.DataFrame) -> None:
    """Every registered element, what watches it, and whether that counts.

    This is the whole of the deleted `Data elements` page that anyone used: the list,
    the criticality, and the answer to "why is this check not in the score". The rest
    of that page — definitions, expected signatures, profile histograms — was a
    register being browsed, which is not a thing people do.
    """
    s = coverage.coverage_summary(cde_cov)
    attached = coverage.attached_rule_ids(cde_cov)
    head, close = st.columns([5, 1], vertical_alignment="center")
    with head:
        st.markdown(
            '<div class="dq-dim-panel-hd"><span class="t">What the score is built on'
            "</span>"
            + theme.badge(f"{len(attached)} of {scoped['rule_id'].nunique()} checks", "info")
            + f'<span class="q">{html.escape(theme.CDE_ONE_LINER)}</span></div>',
            unsafe_allow_html=True,
        )
    if close.button("Close", key="_scope_close", width="stretch"):
        st.session_state["_scope_open"] = False
        st.rerun()

    _rank = {g: i for i, g in enumerate(theme.COVERAGE_GAP_ORDER)}
    view = (
        cde_cov.groupby(["cde_id", "cde_name", "data_class", "criticality"],
                        as_index=False)
        .agg(Columns=("target_column", "nunique"),
             Checks=("rule_count", "sum"),
             Findings=("latest_violation_rows", "sum"),
             # The element's worst binding names the element. "Needs work" used to
             # stand here and it was an instruction wearing a status's clothes —
             # what the register actually knows is which of the four findings it is.
             Coverage=("coverage_gap", lambda g: min(g, key=lambda x: _rank[x])))
    )
    view["Coverage"] = [theme.COVERAGE_GAP_LABEL.get(g, g) for g in view["Coverage"]]
    view["data_class"] = [theme.data_class_label(c) for c in view["data_class"]]
    view = view.assign(
        _c=view["criticality"].map({c: i for i, c in enumerate(theme.CRITICALITY_ORDER)})
    ).sort_values(["_c", "cde_name"]).drop(columns=["_c"])

    st.dataframe(
        view.rename(columns={"cde_name": "Critical data element",
                             "data_class": "Kind",
                             "criticality": "Criticality"})
        .drop(columns=["cde_id"]),
        width="stretch", hide_index=True,
        column_config={
            "Findings": st.column_config.NumberColumn("Findings", format="%d"),
        },
    )
    st.caption(
        f"{s['elements']} elements over {s['bindings']} columns · "
        f"{s['covered']} columns validated · {s['scope_mismatches']} rule(s) "
        "contradicting a registered scope.",
        help="A column counts as validated when an active rule examines its values. "
             "Checking only that a value is present does not count.",
    )


# =============================================================================
# Page
# =============================================================================

components.page_chrome()

runs = adapter.get_check_runs()
registry = adapter.get_rule_registry_current()
cde_cov = adapter.get_cde_coverage()

st.markdown(
    '<div class="dq-page-hd"><div class="t">Scorecard</div>'
    + (f'<div class="s">How healthy is the watched data, as of the '
       f"<b>{runs['run_ts'].max():%-d %b %H:%M}</b> run.</div>"
       if not runs.empty else "")
    + "</div>",
    unsafe_allow_html=True,
)

if runs.empty:
    st.caption("No check runs available.")
    st.stop()

# --- Filter strip -----------------------------------------------------------
# Two controls and a scope statement. The period picker that used to sit here chose
# how much history the trend drew, which is a question about the chart; the control
# a reader actually reaches for is which RUN they are looking at, because every
# other figure on the page is one run's worth.

with st.container(key="dq_pillbar"):
    # Each control carries its own label inside its own border. The band that used to
    # sit behind them drew three unaligned horizontal lines across the page — see the
    # `.st-key-dq_pillbar` note in theme.py.
    f1, f2, gap, f3 = st.columns([1.2, 1.5, 0.95, 2.6], vertical_alignment="center")
    with f1:
        # A dropdown, not a chip field. Every domain is selected by default, and the
        # multiselect spent a third of the strip rendering that fact back as chips.
        domains = sorted(set(runs["business_domain"].dropna()))
        choice = st.selectbox("Domain", ["All"] + domains)
        picked = domains if choice == "All" else [choice]

    in_domain = runs[runs["business_domain"].isin(picked)]

    with f2:
        # Newest first, and the default. Reading an older run is how someone answers
        # "was this already broken on Friday" without exporting anything.
        run_ts_of = (in_domain.groupby("run_id")["run_ts"].max()
                     .sort_values(ascending=False))
        run_ids = list(run_ts_of.index)
        shown_run = st.selectbox(
            "Run", run_ids, index=0,
            format_func=lambda r: f"{run_ts_of[r]:%-d %b %H:%M}",
            help="Which scheduled run this page reports. Every figure except the "
                 "trend line is one run's worth.",
        )
    with f3:
        # The scoping is drawn, not implied, and it is spelled out rather than
        # abbreviated: a reader who does not already know the denominator cannot
        # recover it from a badge reading "10 CDEs". It is also the only way into the
        # element list now that `Data elements` is gone, which is why it is a button.
        _attached_n = len(coverage.attached_rule_ids(cde_cov))
        _element_n = cde_cov["cde_id"].nunique() if not cde_cov.empty else 0
        if st.button(
            f"Scored on {_attached_n} checks over {_element_n} critical elements",
            key="_scope_btn", width="stretch", icon=":material/shield:",
            help="Not a control. The quality figure counts only checks attached to a "
                 "registered critical data element — the register owns that "
                 "denominator, so it does not move when someone writes or retires an "
                 "unrelated rule. Open it to see every element and what watches it.",
        ):
            st.session_state["_scope_open"] = not st.session_state.get("_scope_open")
            st.rerun()

cde_rules = coverage.attached_rule_ids(cde_cov)
if not cde_rules:
    st.caption(
        "No critical data elements are registered, so there is nothing to score. "
        "This page measures the rule set against the register, not against itself."
    )
    st.stop()

# `in_domain` is the whole run the reader asked for; `scoped` is the part the score is
# built on. Every figure below draws from exactly one of the two, and says which.
scoped = in_domain[in_domain["rule_id"].isin(cde_rules)]
if scoped.empty:
    st.caption("No checks on registered elements in the selected domains.")
    st.stop()

rule_name = registry.set_index("rule_id")["rule_name"].to_dict()
run_index = _run_index(scoped)
# The run picked drives the page. It can be missing from the scored index only if no
# CDE-attached check ran on it, in which case the latest scored run is the honest
# fallback — every figure below still says which set it counts.
at = run_index.index[run_index["run_id"] == shown_run]
pos = int(at[0]) if len(at) else len(run_index) - 1
latest_run_id = shown_run

if st.session_state.get("_scope_open"):
    with st.container(key="dq_scope_panel"):
        _scope_panel(cde_cov, in_domain[in_domain["run_id"] == latest_run_id])

# --- Headline: the score, and what is being watched -------------------------

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
window = run_index.iloc[: pos + 1]
window = window[window["run_ts"] >= current_run["run_ts"] - pd.Timedelta(days=TREND_DAYS)]
history = [(f"{r.run_ts:%-d %b}", r.score) for r in window.itertuples()
           if r.score is not None]

hero, tiles = st.columns([2.05, 3.1])

with hero:
    st.markdown(
        '<div class="dq-card dq-hero">'
        '<div class="lab">Quality of watched data'
        + theme.hint(
            "Rows that passed their checks, over rows evaluated, on the run shown. "
            "Weighted by rows, so a check over 2,000 rows counts for more than a "
            "check over 40. Shadow checks are in neither half. This is the one figure "
            "on the page scoped to the registered elements — the tiles beside it "
            f"count the whole run. The line is the same figure per run, over {TREND_DAYS} "
            "days, and its ends are labelled because there is nothing here to hover.",
            side="right")
        + "</div>"
        f'<div class="val">{theme.pct_text(score, 1)}<span class="of unit">%</span></div>'
        # The operands, not just the percentage: a figure whose numerator and
        # denominator have been thrown away is how a scorecard starts lying.
        f'<div class="sub">{passed_rows:,} of {evaluated_rows:,} checked rows passed'
        + (f' · {theme.delta(score_delta, " pts", 1)} since '
           f'{prior["run_ts"]:%-d %b}' if prior is not None else "")
        + "</div>"
        + theme.trend_chart(history, y_lo=80, y_hi=100)
        + "</div>",
        unsafe_allow_html=True,
    )

# Six counts of the estate. Deliberately unscoped — they describe everything that
# runs, not the part the score is built on, and the heading says so. Counting
# "tables monitored" over the attached checks only would understate the estate,
# which is the opposite of what an inventory figure is for.
d_all = metrics.detection_summary(in_domain[in_domain["run_id"] == latest_run_id])
cde_sum = coverage.coverage_summary(cde_cov)
affected = metrics.records_affected_floor(adapter.get_violation_samples(), in_domain,
                                          latest_run_id)
current = adapter.get_cohort_current()
open_now = current[current["lifecycle_state"].isin(lifecycle.OPEN_STATES)]
waiting_on_a_person = open_now[
    open_now["lifecycle_state"].isin(["reopened", "awaiting_review", "awaiting_approval"])
]

# Per ELEMENT, not per binding. Three bindings of Customer name all unvalidated is
# one element nothing validates, not three findings, and the tile sits beside a count
# of elements.
_worst = (cde_cov.assign(_g=cde_cov["coverage_gap"].map(
    {g: i for i, g in enumerate(theme.COVERAGE_GAP_ORDER)}))
    .sort_values("_g").groupby("cde_id", as_index=False).head(1)
    if not cde_cov.empty else cde_cov)
_gapc = _worst["coverage_gap"].value_counts() if not cde_cov.empty else {}


def _n(mapping, key):
    return int(mapping.get(key, 0)) if len(mapping) else 0


# Table names are the warehouse's word for these. On a tile read by a steward the
# noun the business uses is the one that lands; the table name is a keystroke away
# on the Tables page.
TABLE_NOUN = {"ctct_c": "contacts", "subs_c": "services"}
_tables_now = sorted({t.split(".")[-1] for t in
                      in_domain[in_domain["run_id"] == latest_run_id]["target_table"]
                      .dropna().unique()})

TILES = [
    {"label": "Tables monitored", "value": f"{d_all['tables']}",
     "sub": " · ".join(_tables_now)[:48],
     "help": "Distinct tables a check ran against on the run shown."},
    {"label": "Columns watched", "value": f"{d_all['columns']}",
     "sub": f"across {'both' if len(_tables_now) == 2 else 'those'} tables",
     "help": "Distinct columns a check ran against. Cross-table rules carry no "
             "target column and are not counted here."},
    {"label": "CDEs under watch", "value": f"{cde_sum['elements']}",
     "sub": f"{_n(_gapc, 'covered')} covered · {_n(_gapc, 'unvalidated')} unvalidated "
            f"· {_n(_gapc, 'scope_mismatch') + _n(_gapc, 'no_rule')} out of scope",
     "help": theme.CDE_ONE_LINER + " Counted by element and by its worst finding: an "
             "element bound to three columns, none of them validated, is one gap."},
    {"label": "Checks run", "value": f"{d_all['rules_run']}",
     "sub": f"{d_all['rules_breaching']} failing · {d_all['rules_passing']} passing"
            + (f" · {d_all['rules_skipped']} shadow" if d_all["rules_skipped"] else ""),
     "help": "Every rule the runner evaluated on the run shown. Shadow rules record "
             "a count and raise nothing until someone promotes them."},
    {"label": "Customer records affected", "value": f"≥ {affected['floor']:,}",
     "tone": "critical" if affected["floor"] else None,
     "sub": " · ".join(f"{n:,} {TABLE_NOUN.get(t.split('.')[-1], t.split('.')[-1])}"
                       for t, n in affected["by_table"].items()) or "none",
     "help": "A floor, not a count, and shown with the ≥ for that reason. "
             "results.check_run stores a violation count and no keys, and the runner "
             "caps the rows it samples per check — so for "
             f"{len(affected['truncated'])} of the {affected['checks']} failing "
             "checks the keys held are a sample. This is the union of the keys "
             "actually on hand. Making it exact is a change to the runner: a "
             "distinct_entity_count column would make each check exact without "
             "making the union computable, and only a stored key set does both."},
    {"label": "Problems open", "value": f"{len(open_now)}",
     "sub": f"{len(waiting_on_a_person)} waiting on a person",
     "help": "Problems still live. The rest are closed, deferred, or waiting on the "
             "next scheduled run to verify them."},
]

with tiles:
    cards = []
    for t in TILES:
        colour = (f' style="color:{theme.TONE[t["tone"]]["fg"]}"'
                  if t.get("tone") else "")
        cards.append(
            f'<div class="dq-tile" title="{html.escape(t["help"])}">'
            f'<div class="lab">{html.escape(t["label"])}</div>'
            f'<div class="val"{colour}>{html.escape(t["value"])}</div>'
            + (f'<div class="sub">{html.escape(t["sub"])}</div>' if t.get("sub") else "")
            + "</div>"
        )
    # One markdown block, one CSS grid. Two rows of st.columns is what used to put
    # these tiles on top of the section below them — see .dq-watch in theme.py.
    st.markdown(
        '<div class="dq-watch"><div class="hd">What is being watched'
        f'<span class="q">every check that ran — not only the {_attached_n} the score '
        "is built on</span></div>"
        f'<div class="dq-tilegrid">{"".join(cards)}</div></div>',
        unsafe_allow_html=True,
    )

# --- Elements on the left, their failing checks on the right ------------------
# Master–detail since 2026-09-22. The failing-checks table and the element band used
# to be two tables stacked one above the other, joined only by an `Element kind`
# dropdown; the question a steward arrives with is "how is THIS element doing and
# what is failing on it", and answering it meant reading the band, remembering a
# kind, and filtering the table. Now the element list is the filter: pick one on the
# left and the right pane is that element's score, its trend and only its checks.
#
# Three entries that are not elements, and each is there for a reason:
#   * `All checks` — the whole run, so the table this replaced is still one click
#     away and still agrees with the Triage queue.
#   * `Not on a registered element` — 14 of the 34 rules are attached to nothing.
#     A register-shaped list that could only narrow to the register would hide them
#     behind a control that does not admit to hiding anything.
#
# The list reports and does not advise — see `test_the_element_band_recommends_
# nothing`. It carries each element's score, criticality, coverage and failing
# count; what to do about a gap in the register is not this app's call.

ALL_SCOPE = "__all__"
NONE_SCOPE = "__none__"

tagged_now = _tagged(in_domain, registry, latest_run_id)
all_cohorts = adapter.get_cohorts()
cohort_of = metrics.cohort_for_rules(all_cohorts, set(tagged_now["rule_id"]))
titles = _problem_titles(all_cohorts, cde_cov, registry)
monitored_tables = sorted(in_domain["target_table"].dropna().unique())
failing_all = _failing_frame(tagged_now, cde_rules,
                             {r: titles.get(c, c) for r, c in cohort_of.items()},
                             in_domain, monitored_tables)
failing_ids = set(failing_all["Rule id"]) if not failing_all.empty else set()
ran_ids = set(tagged_now[tagged_now["status"].isin(["pass", "breach"])]["rule_id"])

# One row per ELEMENT carrying its worst finding — the same count the `CDEs under
# watch` tile reports, so the two cannot disagree. Three bindings of Customer name
# with nothing validating them is one element, not three findings.
_elements = (cde_cov
             .assign(_g=lambda x: x["coverage_gap"].map(
                 {g: i for i, g in enumerate(theme.COVERAGE_GAP_ORDER)}),
                 _c=lambda x: x["criticality"].map(
                 {c: i for i, c in enumerate(theme.CRITICALITY_ORDER)}))
             .sort_values(["_c", "_g", "cde_name"])
             .groupby("cde_id", as_index=False).head(1))
_run_rows = in_domain[in_domain["run_id"] == latest_run_id]
el_scores = _element_scores(cde_cov, _run_rows)
rules_of = {cid: {i for lst in g["rule_ids"] for i in components.as_list(lst)}
            for cid, g in cde_cov.groupby("cde_id")}
columns_of = {cid: [f"{str(r.target_table).split('.')[-1]}.{r.target_column}"
                    for r in g.itertuples()]
              for cid, g in cde_cov.groupby("cde_id")}
unattached_ids = ran_ids - set(cde_rules)


def _score_tone(score, gap) -> str:
    """Only a covered element's score is coloured. `Identity document number`
    scores 100% on a presence check while nothing looks at what the column holds,
    and painting that green is the page telling a comfortable lie; a scope mismatch
    is the same problem inverted — 50% in red reads as bad data when the register's
    claim is that the rule is wrong. Both keep the figure and lose the verdict."""
    if score is None or gap != "covered":
        return "neutral"
    return "success" if score >= 99.5 else "moderate" if score >= 95 else "critical"


el_rows = [{
    "key": ALL_SCOPE, "Element": "All checks", "dot": None,
    # Failing and passing rather than "of N": the tile above counts shadow checks
    # in what ran, and "21 of 32" beside "34 checks run" reads as a disagreement.
    "Line": f"{len(failing_ids)} failing · {len(ran_ids) - len(failing_ids)} passing "
            "· every check",
    "Score": score, "Tone": "info",
}]
# Most critical first, then worst score within a criticality — the order a steward
# works in. Sorting on score alone put the two scope mismatches on top, and their low
# scores are the rule's fault, not the data's.
_elements = _elements.assign(
    _s=_elements["cde_id"].map(lambda c: el_scores.get(c) if el_scores.get(c)
                               is not None else 101.0))
for _, r in _elements.sort_values(["_c", "_s", "cde_name"]).iterrows():
    mine = rules_of.get(r["cde_id"], set())
    n_fail = len(mine & failing_ids)
    el_rows.append({
        "key": r["cde_id"], "Element": r["cde_name"],
        "dot": theme.TONE[theme.CRITICALITY_TONE.get(r["criticality"], "neutral")]["fg"],
        "Criticality": r["criticality"],
        # Failing first: it is the number that says whether to click. Coverage in
        # words, kind last because the right pane repeats it.
        "Line": (f"{n_fail} of {len(mine & ran_ids)} failing" if n_fail
                 else "all passing" if mine & ran_ids else "no check ran")
                + f" · {theme.COVERAGE_GAP_LABEL.get(r['coverage_gap'], r['coverage_gap'])}"
                + f" · {theme.data_class_label(r['data_class'])}",
        "Score": el_scores.get(r["cde_id"]),
        "Tone": _score_tone(el_scores.get(r["cde_id"]), r["coverage_gap"]),
    })
el_rows.append({
    "key": NONE_SCOPE, "Element": UNATTACHED, "dot": None,
    "Line": f"{len(unattached_ids & failing_ids)} of {len(unattached_ids)} failing "
            "· not scored",
    "Score": None, "Tone": "neutral",
})

scope = st.session_state.get("_elem_scope", ALL_SCOPE)
if scope not in {r["key"] for r in el_rows}:
    scope = ALL_SCOPE

ELIST_GRID = "minmax(0,1fr) 3.6rem"


def _el_cells(row) -> str:
    # A missing score is a dash, never a zero: nothing watching an element is a gap
    # in the register, and zero percent would report it as a data defect.
    shown = "—" if row["Score"] is None else theme.pct_text(row["Score"], 1) + "%"
    dot = (f'<i class="dq-eldot" style="background:{row["dot"]}" '
           f'title="{html.escape(str(row.get("Criticality", "")))} criticality"></i>'
           if row["dot"] else "")
    return (
        '<span class="stack">'
        f'<span class="t1" title="{html.escape(row["Element"])}">{dot}'
        f'{html.escape(row["Element"])}</span>'
        f'<span class="t2 sans">{html.escape(row["Line"])}</span></span>'
        f'<span class="num" style="color:{theme.TONE[row["Tone"]]["fg"]};'
        f'font-weight:600">{shown}</span>'
    )


# Keyed so theme.py can let the two panes wrap: below about 52rem of page there is
# not room for both, and side by side they cut every element and check name to a
# few letters. Wrapped, the list sits above the table and each gets the full width.
_split = st.container(key="dq_elsplit")
with _split:
    left, right = st.columns([1.3, 2.4], gap="medium")

with left:
    st.markdown(
        '<div class="dq-sectionhd"><span class="t">Critical data elements</span>'
        '<span class="q">pick one to see its checks</span></div>',
        unsafe_allow_html=True,
    )
    components.row_head(["Element", ("Score", "n")], ELIST_GRID)
    with st.container(key="dqrows_elist"):
        got = components.clickable_rows(
            el_rows, ELIST_GRID, _el_cells, "el", "key",
            lambda r: f"Show the checks on {r['Element']}", picked=scope)
    if got:
        st.session_state["_elem_scope"] = got
        # A check picked under the old scope may not be in the new one, and a drawer
        # left open over a table that no longer lists its check reads as a bug.
        st.session_state.pop("_check_pick", None)
        st.rerun()
    _scored = sum(1 for r in el_rows[1:-1] if r["Score"] is not None)
    _covered = int((_elements["coverage_gap"] == "covered").sum())
    st.markdown(
        f'<div class="dq-tablefoot">{len(el_rows) - 2} registered elements · '
        f"{_covered} with a rule examining their values · {_scored} scored on this "
        "run</div>",
        unsafe_allow_html=True,
    )

# --- The right pane: one element's score and its failing checks --------------

if scope == ALL_SCOPE:
    in_scope = failing_all
elif scope == NONE_SCOPE:
    in_scope = failing_all[failing_all["Rule id"].isin(unattached_ids)] \
        if not failing_all.empty else failing_all
else:
    in_scope = failing_all[failing_all["Rule id"].isin(rules_of.get(scope, set()))] \
        if not failing_all.empty else failing_all
in_scope = in_scope.reset_index(drop=True)
picked_rule = st.session_state.get("_check_pick")


def _scope_history(rule_ids: set) -> list:
    """This scope's score per run over the same window as the headline trend, so a
    sparkline here and the line under the headline are the same arithmetic over a
    smaller set of rows."""
    part = in_domain[in_domain["rule_id"].isin(rule_ids)]
    if part.empty:
        return []
    idx = _run_index(part)
    idx = idx[(idx["run_ts"] <= current_run["run_ts"])
              & (idx["run_ts"] >= current_run["run_ts"] - pd.Timedelta(days=TREND_DAYS))]
    return [(r.run_ts, r.score) for r in idx.itertuples() if r.score is not None]


with right:
    sel = next(r for r in el_rows if r["key"] == scope)
    # The heading first, so it sits on the same line as the list's heading across
    # the gutter, and the element card below it starts level with the list itself.
    bar_l, bar_r = st.columns([2.2, 1.3], vertical_alignment="bottom")
    with bar_l:
        st.markdown(
            '<div class="dq-sectionhd"><span class="t">Failing checks</span>'
            f'<span class="q">{len(in_scope)} · click a row for the bad rows</span></div>',
            unsafe_allow_html=True)
    with bar_r:
        grouped = st.toggle(
            "Group by dimension", value=False, key="_fail_group",
            help="Completeness, Validity, Consistency, Uniqueness — the four "
                 "questions a quality programme asks of a column. These used to be "
                 "four cards at the top of the page; they answer 'which kind of "
                 "thing is wrong', which is a question about this table.",
        )
    if scope == ALL_SCOPE:
        badges = theme.badge("every check that ran", "neutral")
        where = f"{len(ran_ids)} checks · {len(cde_rules)} of them scored"
        hist = [(r.run_ts, r.score) for r in window.itertuples() if r.score is not None]
        note = None
    elif scope == NONE_SCOPE:
        badges = theme.badge("not scored", "neutral")
        where = f"{len(unattached_ids)} checks on columns nobody has registered"
        hist = []
        note = ("These checks run and raise problems like any other, and they are "
                "worked in Triage. They do not move the quality figure: only checks "
                "on a registered element count towards it.")
    else:
        er = _elements[_elements["cde_id"] == scope].iloc[0]
        badges = (theme.criticality_badge(er["criticality"])
                  + theme.badge(theme.data_class_label(er["data_class"]), "neutral")
                  + theme.coverage_badge(er["coverage_gap"])
                  + (theme.badge("PII", "high", "shield") if er["pii"] else ""))
        cols = columns_of.get(scope, [])
        where = " · ".join(cols[:3]) + (f" + {len(cols) - 3} more" if len(cols) > 3 else "")
        hist = _scope_history(rules_of.get(scope, set()))
        note = (theme.COVERAGE_GAP_MEANING.get(er["coverage_gap"])
                if er["coverage_gap"] != "covered" else None)

    # Since the previous run, the same comparison the headline makes. First-to-last
    # over the window read noise as a trend on the scope mismatches, whose score
    # wanders ±3 points run to run with nothing changing. Coloured only where the
    # score is: a delta on a figure the register says is the rule's fault is no more
    # a verdict on the data than the figure is.
    _d = (hist[-1][1] - hist[-2][1]) if len(hist) > 1 else None
    _d_txt = ("" if _d is None else
              theme.delta(_d, " pts", 1) if sel["Tone"] not in ("neutral",) else
              f"{_d:+.1f} pts".replace("-", "\u2212"))
    st.markdown(
        '<div class="dq-elhd"><div class="l">'
        f'<div class="n">{html.escape(sel["Element"])}</div>'
        f'<div class="b">{badges}</div>'
        f'<div class="w">{html.escape(where)}</div></div>'
        + ('<div class="r">'
           f'<div class="s" style="color:{theme.TONE[sel["Tone"]]["fg"]}">'
           f'{theme.pct_text(sel["Score"], 1)}<span>%</span></div>'
           + (f'<div class="d">{_d_txt} since {hist[-2][0]:%-d %b}</div>'
              if _d is not None else "")
           + theme.sparkline([v for _, v in hist], width=120, height=26)
           + "</div>" if sel["Score"] is not None else "")
        + "</div>"
        + (f'<div class="dq-note">{html.escape(note)}</div>' if note else ""),
        unsafe_allow_html=True,
    )

    if scope not in (ALL_SCOPE, NONE_SCOPE):
        if st.button("Every binding and what checks it", key="_el_details",
                     icon=":material/open_in_new:", type="tertiary"):
            st.session_state["_cde_pick"] = scope
            st.rerun()

    if in_scope.empty:
        st.caption(
            "Every check on this element passes on the run shown."
            if scope not in (ALL_SCOPE, NONE_SCOPE) else
            "No check is failing on the run shown, in the selected domains.")
    else:
        def _fail_cells(row) -> str:
            problem = row["Problem"]
            return (
                '<span class="stack">'
                f'<span class="t1" title="{html.escape(str(row["Check"]))}">'
                f'{html.escape(str(row["Check"]))}</span>'
                f'<span class="t2">{html.escape(str(row["Where"]))}</span></span>'
                + f'<span>{theme.severity_badge(row["Severity"], words=False)}</span>'
                f'<span class="num">{row["Bad rows"]:,}</span>'
                f'<span class="of">{row["Of"]:,}</span>'
                + f'<span class="txt" style="color:'
                  f'{theme.TONE[row["Trend tone"]]["fg"]}">{html.escape(row["Trend"])}</span>'
                + (f'<span class="link" title="{html.escape(str(problem))}">'
                   f'{html.escape(str(problem))}</span>' if problem else
                   '<span class="of" style="text-align:left">—</span>')
            )

        def _fail_label(row):
            return f"Open {row['Check']}"

        components.row_head(FAILING_HEADS, FAILING_GRID)
        if grouped:
            for name in DIMENSION_ORDER:
                part = in_scope[in_scope["Dimension"] == name]
                if part.empty:
                    continue
                spec = DIMENSION_BY_NAME.get(name)
                dim_rows = tagged_now[tagged_now["Dimension"] == name]
                dim_score = _row_score(dim_rows[dim_rows["rule_id"].isin(cde_rules)])
                st.markdown(
                    f'<div class="dq-dimgrp">{theme.icon(spec["icon"], 15) if spec else ""}'
                    f"<b>{name}</b>"
                    + theme.badge(f"{theme.pct_text(dim_score, 1)}% scored"
                                  if dim_score is not None else "not scored",
                                  "neutral")
                    + f'<span class="q">{html.escape(spec["short"]) if spec else ""}</span>'
                    + (theme.hint(spec["long"] + " " + SCORING_NOTE) if spec else "")
                    + "</div>",
                    unsafe_allow_html=True,
                )
                with st.container(key=f"dqrows_fail_{name}"):
                    got = components.clickable_rows(
                        part.to_dict("records"), FAILING_GRID, _fail_cells, "fc",
                        "Rule id", _fail_label, picked=picked_rule)
                if got:
                    st.session_state["_check_pick"] = got
                    st.rerun()
        else:
            # The pane scrolls past about ten rows, so the list beside it and the
            # table stay roughly the same height. Every failing check stays
            # reachable — this page has to agree with the Triage queue.
            with st.container(height=560 if len(in_scope) > 10 else "content",
                              key="dqrows_fail"):
                got = components.clickable_rows(
                    in_scope.to_dict("records"), FAILING_GRID, _fail_cells, "fc",
                    "Rule id", _fail_label, picked=picked_rule)
            # A rerun rather than reading `got` straight through: the row markup is
            # written before the click is known, so the selected row's tint needs
            # one more pass.
            if got:
                st.session_state["_check_pick"] = got
                st.rerun()

        # The foot reports the scope, not the run. "21 failing · 11 passing" over a
        # table showing two checks describes a set the reader is not looking at.
        st.markdown(
            '<div class="dq-tablefoot">'
            + (f"{len(in_scope)} failing · {d_all['rules_passing']} passing"
               + (f" · {d_all['rules_skipped']} shadow" if d_all["rules_skipped"] else "")
               if scope == ALL_SCOPE else
               f"{len(in_scope)} of {d_all['rules_breaching']} failing checks · "
               f"{sel['Element'].lower() if scope == NONE_SCOPE else sel['Element']}")
            + "</div>",
            unsafe_allow_html=True,
        )

# Held in session rather than read straight off the click, so the panel survives a
# rerun the table did not cause — and so a link, or a test, can open a check without
# clicking one. Any failing check opens, whatever the scope, so a test or a link that
# names a check does not first have to pick its element.
if picked_rule in failing_ids:
    with st.container(key="dq_check_drawer"):
        _check_panel(picked_rule, tagged_now, registry,
                     adapter.get_violation_samples(), cde_cov, cohort_of,
                     in_domain[["rule_id", "run_ts", "violation_count", "status"]])
# The element drawer, and only when no check drawer is open — two fixed panels at the
# same edge would stack on top of each other.
elif st.session_state.get("_cde_pick"):
    with st.container(key="dq_element_drawer"):
        components.element_panel(cde_cov, registry, st.session_state["_cde_pick"],
                                 pick_key="_cde_pick")

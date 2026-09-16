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
issue board below lists the ones nothing valid is watching. The model is untouched;
only the browsing surface went.

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


def _problem_titles(cohorts: pd.DataFrame) -> dict:
    """cohort_id → the problem as a phrase. One derivation, in
    `components.problem_title`, shared with the Triage queue — three copies of a
    `split(".")` is three chances for one problem to have three different names."""
    return {r.cohort_id: components.problem_title(r.root_cause_hypothesis)
            for r in cohorts.itertuples()}


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

FAILING_GRID = ("minmax(0,2.2fr) minmax(0,1.85fr) 3.4rem minmax(0,1fr) "
                "4.4rem 3.6rem minmax(0,1fr) minmax(0,1.6fr)")
FAILING_HEADS = ["Check", "Where", "Sev", "Dimension",
                 ("Bad rows", "n"), ("Of", "n"), "Trend", "Problem"]

GAP_GRID = "minmax(0,1.5fr) 5.5rem minmax(0,4fr) minmax(0,1.15fr)"
GAP_HEADS = ["Element", "Criticality", "Problem", "What to do"]


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

    view = (
        cde_cov.groupby(["cde_id", "cde_name", "criticality"], as_index=False)
        .agg(Columns=("target_column", "nunique"),
             Checks=("rule_count", "sum"),
             Findings=("latest_violation_rows", "sum"),
             Gaps=("coverage_gap", lambda g: sum(x != "covered" for x in g)))
    )
    view["Status"] = [
        "Covered" if not gaps else "Needs work" for gaps in view["Gaps"]
    ]
    view = view.assign(
        _c=view["criticality"].map({c: i for i, c in enumerate(theme.CRITICALITY_ORDER)})
    ).sort_values(["_c", "cde_name"]).drop(columns=["_c", "Gaps"])

    st.dataframe(
        view.rename(columns={"cde_name": "Critical data element",
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


def _element_panel(cde_cov: pd.DataFrame, registry: pd.DataFrame, cde_id: str) -> None:
    """One element, for the reader who clicked Review on the issue board."""
    rows = cde_cov[cde_cov["cde_id"] == cde_id]
    if rows.empty:
        return
    first = rows.iloc[0]

    head, close = st.columns([5, 1], vertical_alignment="center")
    with head:
        st.markdown(
            '<div class="dq-dim-panel-hd">'
            f'<span class="t">{html.escape(str(first["cde_name"]))}</span>'
            + theme.criticality_badge(first["criticality"])
            + (theme.badge("PII", "high", "shield") if first["pii"] else "")
            + f'<span class="q">{html.escape(str(first["business_domain"]))} · '
            f'{html.escape(str(first["owner_group"]))}</span></div>',
            unsafe_allow_html=True,
        )
    if close.button("Close", key="_elem_close", width="stretch"):
        st.session_state.pop("_cde_pick", None)
        st.rerun()

    rule_name = registry.set_index("rule_id")["rule_name"].to_dict()
    body = []
    for _, r in rows.iterrows():
        ids = components.as_list(r["rule_ids"])
        body.append({
            "Column": f"{str(r['target_table']).split('.')[-1]}.{r['target_column']}",
            "Finding": theme.COVERAGE_GAP_LABEL.get(r["coverage_gap"], r["coverage_gap"]),
            "Checks": ", ".join(rule_name.get(i, i) for i in ids) or "nothing",
            "Findings": int(r["latest_violation_rows"]),
            "Populated when": components.opt(r["populated_when"]) or "always",
        })
    st.dataframe(
        pd.DataFrame(body), width="stretch", hide_index=True,
        # Sized deliberately rather than evenly: in a drawer this wide an even split
        # gives the rule name too little and the one-word finding too much.
        column_config={
            "Column": st.column_config.TextColumn(width="small"),
            "Finding": st.column_config.TextColumn(width="small"),
            "Checks": st.column_config.TextColumn(width="medium"),
            "Findings": st.column_config.NumberColumn(format="%d", width="small"),
            "Populated when": st.column_config.TextColumn(width="medium"),
        },
    )

    gap = first["coverage_gap"]
    st.markdown(
        f'<div class="dq-note">{theme.coverage_badge(gap)} '
        f'{html.escape(theme.COVERAGE_GAP_MEANING.get(gap, ""))}</div>',
        unsafe_allow_html=True,
    )
    unscoped = sorted({i for ids in rows["unscoped_rule_ids"]
                       for i in components.as_list(ids)})
    if unscoped:
        st.caption(
            "Rules contradicting this element's registered scope: "
            + ", ".join(f"`{i}`" for i in unscoped)
            + ". The register declares the scope these rules should have had, which "
            "is how a rule defect becomes an assertion the model makes rather than "
            "something a human noticed."
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

# --- Failing checks ---------------------------------------------------------

tagged_now = _tagged(in_domain, registry, latest_run_id)
all_cohorts = adapter.get_cohorts()
cohort_of = metrics.cohort_for_rules(all_cohorts, set(tagged_now["rule_id"]))
titles = _problem_titles(all_cohorts)
monitored_tables = sorted(in_domain["target_table"].dropna().unique())
failing = _failing_frame(tagged_now, cde_rules,
                         {r: titles.get(c, c) for r, c in cohort_of.items()},
                         in_domain, monitored_tables)

hd_l, hd_r = st.columns([2.6, 2.2], vertical_alignment="bottom")
with hd_l:
    st.markdown(
        '<div class="dq-sectionhd"><span class="t">Failing checks</span></div>',
        unsafe_allow_html=True)
with hd_r:
    tog, note = st.columns([1.25, 1.35], vertical_alignment="center")
    with tog:
        grouped = st.toggle(
            "Group by dimension", value=False, key="_fail_group",
            help="Completeness, Validity, Consistency, Uniqueness — the four "
                 "questions a quality programme asks of a column. These used to be "
                 "four cards at the top of the page; they answer 'which kind of "
                 "thing is wrong', which is a question about this table.",
        )
    with note:
        st.markdown('<div class="dq-quiet" style="padding-bottom:.5rem">click a row '
                    "for the bad rows</div>", unsafe_allow_html=True)

picked_rule = st.session_state.get("_check_pick")

if failing.empty:
    st.caption("No check is failing on the run shown, in the selected domains.")
else:
    def _fail_cells(row) -> str:
        problem = row["Problem"]
        return (
            f'<span class="name" title="{html.escape(str(row["Check"]))}">'
            f'{html.escape(str(row["Check"]))}</span>'
            f'<span class="mono" title="{html.escape(str(row["Where"]))}">'
            f'{html.escape(str(row["Where"]))}</span>'
            + f'<span>{theme.severity_badge(row["Severity"], words=False)}</span>'
            + f'<span class="txt">{html.escape(str(row["Dimension"]))}</span>'
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
            part = failing[failing["Dimension"] == name]
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
        # Six rows tall, and the rest scroll. Every failing check stays reachable —
        # this page has to agree with the Triage queue, which works all of them — but
        # the band below it stays on screen instead of being pushed off the bottom.
        with st.container(height=252, key="dqrows_fail"):
            got = components.clickable_rows(
                failing.to_dict("records"), FAILING_GRID, _fail_cells, "fc",
                "Rule id", _fail_label, picked=picked_rule)
        # A rerun rather than reading `got` straight through: the row markup is
        # written before the click is known, so drawing the selected row's tint in
        # this pass is not possible. One extra pass buys a selection that is visible.
        if got:
            st.session_state["_check_pick"] = got
            st.rerun()

    st.markdown(
        '<div class="dq-tablefoot">'
        + (f"+ {len(failing) - 6} more failing · " if len(failing) > 6 and not grouped
           else f"{len(failing)} failing · ")
        + f"{d_all['rules_passing']} passing"
        + (f" · {d_all['rules_skipped']} shadow" if d_all["rules_skipped"] else "")
        + "</div>",
        unsafe_allow_html=True,
    )

    # Held in session rather than read straight off the click, so the panel survives
    # a rerun the table did not cause — and so a link, or a test, can open a check
    # without clicking one.
    if picked_rule in set(failing["Rule id"]):
        # Fixed-position, so opening it never displaces the row the reader just
        # clicked. The veil behind it is the drawer's own ::before — see theme.py.
        with st.container(key="dq_check_drawer"):
            _check_panel(picked_rule, tagged_now, registry,
                         adapter.get_violation_samples(), cde_cov, cohort_of,
                         in_domain[["rule_id", "run_ts", "violation_count", "status"]])

# --- What the register says nothing valid is watching ------------------------
# Everything above this line is measured against the rules that exist, so it can only
# ever say how the checks are doing. This band is measured against the elements the
# business registered as mattering — the one denominator on the page that the rule
# set does not control. A finding here is a defect in the rule set, not in the data.

WHAT_TO_DO = {
    "no_rule": "write a rule",
    "scope_mismatch": "fix the rule's scope",
    "unvalidated": "add a format rule",
}


def _gap_sentence(row) -> str:
    """The finding as a sentence, with the reason the register already knows."""
    gap = row["coverage_gap"]
    if gap == "scope_mismatch":
        # `populated_when` is written for a person: "postpaid services only — a
        # prepaid service has no billing account". The half after the dash is the
        # reason, which is the half worth repeating here; the article in front of it
        # is not, and the cell is narrow.
        when = components.opt(row["populated_when"]) or ""
        why = (when.split("—")[-1] if "—" in when else when).strip()
        for article in ("a ", "an ", "the "):
            if why.lower().startswith(article):
                why = why[len(article):]
                break
        return ("Rule fires outside the element's scope"
                + (f" ({why})" if why else ""))
    if gap == "no_rule":
        return "Registered as critical and nothing checks it"
    return "Something watches it, but nothing checks what it contains"


st.markdown('<div style="height:.4rem"></div>', unsafe_allow_html=True)
st.markdown(
    '<div class="dq-sectionhd"><span class="t">Critical elements nothing valid is '
    "watching</span>"
    '<span class="q">a finding here is a defect in the rule set, not in the data'
    "</span></div>",
    unsafe_allow_html=True,
)

if cde_cov.empty:
    st.caption("No critical data elements are registered.")
else:
    # One row per ELEMENT, carrying its worst finding — the same count the tile above
    # reports, so the two cannot disagree.
    gaps = (cde_cov[cde_cov["coverage_gap"] != "covered"]
            .assign(_g=lambda x: x["coverage_gap"].map(
                {g: i for i, g in enumerate(theme.COVERAGE_GAP_ORDER)}),
                _c=lambda x: x["criticality"].map(
                {c: i for i, c in enumerate(theme.CRITICALITY_ORDER)}))
            .sort_values(["_c", "_g", "cde_name"])
            .groupby("cde_id", as_index=False).head(1)
            .sort_values(["_c", "_g", "cde_name"]))

    if gaps.empty:
        st.caption("Every registered element has an active rule examining its values.")
    else:
        gap_rules = {i for ids in gaps["unscoped_rule_ids"]
                     for i in components.as_list(ids)}
        gap_cohorts = metrics.cohort_for_rules(all_cohorts, gap_rules)

        rows = []
        for _, r in gaps.iterrows():
            cohort_id = next((gap_cohorts[i] for i in components.as_list(
                r["unscoped_rule_ids"]) if i in gap_cohorts), None)
            rows.append({
                "cde_id": r["cde_id"],
                "Element": r["cde_name"],
                "Criticality": r["criticality"],
                "Problem": _gap_sentence(r),
                # Where the fix is, not what it is: a scope mismatch already has a
                # cohort carrying the evidence, and pointing at it is more use than
                # repeating the instruction.
                "Do": (f"see COH {cohort_id[:8]}" if cohort_id
                       else WHAT_TO_DO.get(r["coverage_gap"], "review")),
            })

        def _gap_cells(row) -> str:
            return (
                f'<span class="name" title="{html.escape(str(row["Element"]))}">'
                f'{html.escape(str(row["Element"]))}</span>'
                + f'<span>{theme.criticality_badge(row["Criticality"])}</span>'
                + f'<span class="txt" title="{html.escape(str(row["Problem"]))}">'
                  f'{html.escape(str(row["Problem"]))}</span>'
                + f'<span class="mono">{html.escape(str(row["Do"]))}</span>'
            )

        components.row_head(GAP_HEADS, GAP_GRID)
        with st.container(key="dqrows_gap"):
            got = components.clickable_rows(
                rows, GAP_GRID, _gap_cells, "gap", "cde_id",
                lambda r: f"Open {r['Element']}",
                picked=st.session_state.get("_cde_pick"))
        if got:
            st.session_state["_cde_pick"] = got
            st.rerun()

        st.markdown(
            f'<div class="dq-tablefoot">{len(rows)} of {cde_sum["elements"]} '
            f"registered elements · {cde_sum['scope_mismatches']} rule(s) "
            "contradicting a registered scope</div>",
            unsafe_allow_html=True,
        )

# The element drawer, and only when no check drawer is open — two fixed panels at the
# same edge would stack on top of each other.
if st.session_state.get("_cde_pick") and picked_rule not in set(
        failing["Rule id"] if not failing.empty else []):
    with st.container(key="dq_element_drawer"):
        _element_panel(cde_cov, registry, st.session_state["_cde_pick"])

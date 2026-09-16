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
    """cohort_id → the problem as a phrase, taken from the first clause of the
    hypothesis. Same derivation as the Triage pages: there is no stored title column,
    and adding one is a fixture and DDL change rather than a UI one."""
    out = {}
    for r in cohorts.itertuples():
        first = str(r.root_cause_hypothesis).split(".")[0].strip()
        out[r.cohort_id] = first if len(first) <= 60 else first[:57].rstrip(" ,;") + "…"
    return out


def _failing_frame(tagged_now: pd.DataFrame, attached: set[str],
                   cohort_of: dict) -> pd.DataFrame:
    """One row per check failing on the run being shown, worst first.

    `Scored` says whether the check moves the quality figure above. Both kinds are
    listed: a check on an unregistered column still runs, still raises a cohort and
    still has bad rows behind it — hiding it would make the page disagree with the
    Triage queue, which is where it gets worked.
    """
    rows = []
    for r in tagged_now[tagged_now["status"] == "breach"].itertuples():
        rows.append({
            "Check": r.rule_name,
            "Where": (f"{r.target_table.split('.')[-1]}"
                      + (f".{r.target_column}" if components.opt(r.target_column) else "")),
            "Severity": theme.severity_text(r.severity),
            "Dimension": r.Dimension,
            "Bad rows": int(r.violation_count),
            "Share": float(r.violation_pct),
            "Scored": r.rule_id in attached,
            "Problem": cohort_of.get(r.rule_id, ""),
            "Rule id": r.rule_id,
        })
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(["Bad rows", "Check"], ascending=[False, True]).reset_index(drop=True)


FAILING_COLS = {
    "Check": st.column_config.TextColumn("Check", width="large"),
    "Where": st.column_config.TextColumn("Where", width="small"),
    "Problem": st.column_config.TextColumn(
        "Problem", width="medium",
        help="The problem this check was grouped into, if one has been raised. "
             "Open it from the panel below."),
    "Severity": st.column_config.TextColumn("Severity", width="small"),
    "Bad rows": st.column_config.NumberColumn("Bad rows", format="%d"),
    "Share": st.column_config.NumberColumn("Share", format="%.2f%%"),
    "Scored": st.column_config.CheckboxColumn(
        "Scored", help="Ticked when this check is attached to a registered critical "
                       "data element and therefore moves the quality figure above. "
                       "Unticked checks still run and are still worked from Triage."),
}


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

    facts, prose = st.columns([1, 1.5])
    with facts:
        # Two tiles, not three. At the width this column gets, a third put "24.02%"
        # on two lines with the percent sign orphaned on the second.
        components.kpi_row([
            {"label": "Bad rows", "value": f"{int(row['violation_count']):,}",
             "tone": "critical",
             "sub": f"{float(row['violation_pct']):.2f}% of rows checked"},
            {"label": "Rows checked", "value": f"{int(row['rows_scanned']):,}",
             "sub": f"limit {float(row['threshold_pct']):.2f}%"},
        ])
    with prose:
        if reg is not None:
            note = components.opt(reg["note"])
            st.markdown(
                f'<div class="dq-dim-prose"><b>What this check looks for.</b> '
                f'{html.escape(str(reg["rule_name"]))}.'
                + (f" {html.escape(str(note))}" if note else "")
                + "</div>",
                unsafe_allow_html=True,
            )
            scope = components.opt(reg["scope_filter"])
            st.markdown(
                f'<div class="dq-dim-prose q"><code>{html.escape(str(reg["rule_expr"]))}</code>'
                + (f'<br>scoped to <code>{html.escape(str(scope))}</code>' if scope else
                   '<br><span style="color:' + theme.TONE["moderate"]["fg"] + '">no scope '
                   "filter — this rule runs on every row of the table</span>")
                + "</div>",
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
    st.dataframe(pd.DataFrame(body), width="stretch", hide_index=True,
                 column_config={"Findings": st.column_config.NumberColumn(format="%d")})

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

hd, actions = st.columns([4, 1.15], vertical_alignment="center")
with hd:
    st.markdown(
        '<div class="dq-page-hd"><div class="t">Data Quality Scorecard</div>'
        '<div class="s">How healthy the watched data is, what is being watched, and '
        "which checks are failing right now.</div></div>",
        unsafe_allow_html=True,
    )

if runs.empty:
    st.caption("No check runs available.")
    st.stop()

# --- Filter strip -----------------------------------------------------------

with st.container(key="dq_filter_strip"):
    l1, f1, l2, f2, l3, note = st.columns([0.5, 2.0, 0.5, 1.3, 1.25, 1.85])
    with l1:
        st.markdown('<div class="dq-strip-lab">Domains</div>', unsafe_allow_html=True)
    with f1:
        domains = sorted(set(runs["business_domain"].dropna()))
        picked = st.multiselect("Domain", domains, default=domains,
                                label_visibility="collapsed")
    with l2:
        st.markdown('<div class="dq-strip-lab">Period</div>', unsafe_allow_html=True)
    with f2:
        window = st.selectbox("Window", [7, 14, 30, 40], index=2,
                              format_func=lambda d: f"Last {d} days",
                              label_visibility="collapsed")
    with l3:
        # The scoping is drawn, not implied. It is also the only way into the element
        # list now that `Data elements` is gone, which is why it is a button and not
        # the badge it used to be.
        if st.button(
            f"Scope · {cde_cov['cde_id'].nunique() if not cde_cov.empty else 0} CDEs",
            key="_scope_btn", width="stretch", icon=":material/shield:",
            help="Not a control. The quality figure counts only checks attached to a "
                 "registered critical data element — the register owns that "
                 "denominator, so it does not move when someone writes or retires an "
                 "unrelated rule. Open it to see every element and what watches it.",
        ):
            st.session_state["_scope_open"] = not st.session_state.get("_scope_open")
            st.rerun()
    with note:
        last_ts = runs["run_ts"].max()
        st.markdown(
            f'<div class="dq-strip-note">Last run {last_ts:%d %b, %H:%M}<br>'
            f"Next expected {last_ts + pd.Timedelta(days=1):%d %b, %H:%M}</div>",
            unsafe_allow_html=True,
        )

cde_rules = coverage.attached_rule_ids(cde_cov)
if not cde_rules:
    st.caption(
        "No critical data elements are registered, so there is nothing to score. "
        "This page measures the rule set against the register, not against itself."
    )
    st.stop()

# `in_domain` is the whole run the reader asked for; `scoped` is the part the score is
# built on. Every figure below draws from exactly one of the two, and says which.
in_domain = runs[runs["business_domain"].isin(picked)]
scoped = in_domain[in_domain["rule_id"].isin(cde_rules)]
if scoped.empty:
    st.caption("No checks on registered elements in the selected domains.")
    st.stop()

rule_name = registry.set_index("rule_id")["rule_name"].to_dict()
run_index = _run_index(scoped)
latest_run_id = metrics.latest_run_id(in_domain)

with actions:
    export = in_domain[in_domain["run_id"] == latest_run_id].copy()
    export.insert(0, "rule_name", export["rule_id"].map(rule_name))
    export.insert(1, "scored", export["rule_id"].isin(cde_rules))
    st.download_button(
        "Export report",
        data=export.to_csv(index=False).encode(),
        file_name=f"dq-scorecard-{last_ts:%Y%m%d}.csv",
        mime="text/csv",
        icon=":material/download:",
        width="stretch",
        help="Every check result from the run shown, for the domains selected, as CSV "
             "— including the ones the score does not count, flagged. A read of what "
             "is on this page: it starts nothing and changes nothing.",
    )

if st.session_state.get("_scope_open"):
    with st.container(key="dq_scope_panel"):
        _scope_panel(cde_cov, in_domain[in_domain["run_id"] == latest_run_id])

# --- Headline: the score, and what is being watched -------------------------

score = _row_score(scoped[scoped["run_id"] == run_index.iloc[-1]["run_id"]])
prior_score = float(run_index.iloc[-2]["score"]) if len(run_index) > 1 else None
score_delta = None if score is None or prior_score is None else score - prior_score

if score is None:
    band, band_tone = "Not scored", "neutral"
elif score >= 98:
    band, band_tone = "Healthy", "success"
elif score >= 90:
    band, band_tone = "Needs attention", "moderate"
else:
    band, band_tone = "Critical", "critical"

cutoff = scoped["run_ts"].max() - pd.Timedelta(days=window)
in_window = run_index[run_index["run_ts"] >= cutoff]
history = [(f"{r.run_ts:%-d %b}", r.score) for r in in_window.itertuples()
           if r.score is not None]

hero, tiles = st.columns([2.05, 3.1])

with hero:
    st.markdown(
        '<div class="dq-card dq-hero"><div class="l">'
        f'<div class="hd">{theme.icon("spark", 14)} Overall quality'
        + theme.hint(
            "Rows that passed their checks, over rows evaluated, on the latest "
            "scheduled run. Weighted by rows, so a check over 2,000 rows counts for "
            "more than a check over 40. Shadow checks are in neither half. This is "
            "the one figure on the page scoped to the registered elements — the "
            "tiles beside it count the whole run. The trend is the same figure per "
            "run; the axis starts at 80 because the whole story lives in the top "
            "fifth.", side="right")
        + "</div>"
        f'<div class="val">{theme.pct_text(score)}'
        '<span class="of">/100</span></div>'
        f'<div style="margin:.3rem 0 .35rem">{theme.badge(band, band_tone)}</div>'
        f'<div class="sub">{theme.delta(score_delta, " pts", 1)} vs previous run</div>'
        '</div><div class="r">'
        f'<div class="rl">Last {window} days · {len(history)} runs</div>'
        f"{theme.area_chart(history, y_lo=80, y_hi=100)}"
        "</div></div>",
        unsafe_allow_html=True,
    )

# Six counts of the estate. Deliberately unscoped — they describe everything that
# runs, not the part the score is built on, and the heading says so. Counting
# "tables monitored" over the attached checks only would understate the estate,
# which is the opposite of what an inventory figure is for.
d_all = metrics.detection_summary(in_domain)
cde_sum = coverage.coverage_summary(cde_cov)
affected = metrics.records_affected_floor(adapter.get_violation_samples(), in_domain,
                                          latest_run_id)
current = adapter.get_cohort_current()
open_now = current[current["lifecycle_state"].isin(lifecycle.OPEN_STATES)]
waiting_on_a_person = open_now[
    open_now["lifecycle_state"].isin(["reopened", "awaiting_review", "awaiting_approval"])
]

with tiles:
    st.markdown(
        '<div class="dq-tilehd">What is being watched'
        + theme.hint(
            "Every check that ran in the domains selected — not only the ones the "
            "quality figure is built on. An inventory that counted just the scored "
            "checks would report a smaller estate than the one being monitored.",
            side="left")
        + "</div>",
        unsafe_allow_html=True,
    )
    TILES = [
        {"label": "Tables monitored", "value": f"{d_all['tables']}",
         "sub": ", ".join(sorted({t.split(".")[-1] for t in
                                  in_domain["target_table"].dropna().unique()}))[:48],
         "help": "Distinct tables a check ran against on the latest run."},
        {"label": "Columns watched", "value": f"{d_all['columns']}",
         "sub": "across those tables",
         "help": "Distinct columns a check ran against. Cross-table rules carry no "
                 "target column and are not counted here."},
        {"label": "CDEs under watch", "value": f"{cde_sum['elements']}",
         "sub": f"{cde_sum['covered']} of {cde_sum['bindings']} columns validated",
         "help": theme.CDE_ONE_LINER},
        {"label": "Checks run", "value": f"{d_all['rules_run']}",
         "sub": f"{d_all['rules_breaching']} failing · {d_all['rules_passing']} passing"
                + (f" · {d_all['rules_skipped']} shadow" if d_all["rules_skipped"] else ""),
         "help": "Every rule the runner evaluated on the latest run. Shadow rules "
                 "record a count and raise nothing until someone promotes them."},
        {"label": "Records affected", "value": f"≥ {affected['floor']:,}",
         "tone": "critical" if affected["floor"] else None,
         "sub": " · ".join(f"{n:,} in {t.split('.')[-1]}"
                           for t, n in affected["by_table"].items()) or "none",
         "help": "A floor, not a count, and shown with the ≥ for that reason. "
                 "results.check_run stores a violation count and no keys, and the "
                 "runner caps the rows it samples per check — so for "
                 f"{len(affected['truncated'])} of the {affected['checks']} failing "
                 "checks the keys held are a sample. This is the union of the keys "
                 "actually on hand. Making it exact is a change to the runner: a "
                 "distinct_entity_count column would make each check exact without "
                 "making the union computable, and only a stored key set does both."},
        {"label": "Problems open", "value": f"{len(open_now)}",
         "sub": f"{len(waiting_on_a_person)} waiting on a person",
         "help": "Problems still live. The rest are closed, deferred, or waiting on "
                 "the next scheduled run to verify them."},
    ]
    for chunk in (TILES[:3], TILES[3:]):
        components.kpi_row(chunk)

# --- Failing checks ---------------------------------------------------------

theme.section("Failing checks")

tagged_now = _tagged(in_domain, registry, latest_run_id)
all_cohorts = adapter.get_cohorts()
cohort_of = metrics.cohort_for_rules(all_cohorts, set(tagged_now["rule_id"]))
titles = _problem_titles(all_cohorts)
failing = _failing_frame(tagged_now, cde_rules,
                         {r: titles.get(c, c) for r, c in cohort_of.items()})

ctl1, ctl2 = st.columns([1.15, 3])
with ctl1:
    grouped = st.toggle(
        "Group by dimension", value=False, key="_fail_group",
        help="Completeness, Validity, Consistency, Uniqueness — the four questions a "
             "quality programme asks of a column. These used to be four cards at the "
             "top of the page; they answer 'which kind of thing is wrong', which is a "
             "question about this table.",
    )
with ctl2:
    term = st.text_input("Search checks", placeholder="Search check, column, problem…",
                         label_visibility="collapsed", key="_fail_q").strip().lower()

if failing.empty:
    st.caption("No check is failing on the latest run in the selected domains.")
else:
    view = failing
    if term:
        hay = view[["Check", "Where", "Dimension", "Problem", "Rule id"]] \
            .astype(str).agg(" ".join, axis=1).str.lower()
        view = view[hay.str.contains(term, regex=False, na=False)]

    st.markdown(
        '<div class="dq-quiet" style="margin:-.2rem 0 .5rem">'
        f"{len(view)} failing of {d_all['rules_run']} checks run · select a row to see "
        "what it looks for and the rows that failed"
        "</div>",
        unsafe_allow_html=True,
    )

    nonce = st.session_state.get("_fail_nonce", 0)

    def _table(frame: pd.DataFrame, key: str):
        """One dataframe, one selection. Returns the rule id picked, or None."""
        drop = ["Rule id", "Dimension"]
        event = st.dataframe(
            frame.drop(columns=drop),
            width="stretch", hide_index=True, on_select="rerun",
            selection_mode="single-row", key=key, column_config=FAILING_COLS,
        )
        picks = event.selection.rows if event and event.selection else []
        return frame.iloc[picks[0]]["Rule id"] if picks else None

    if grouped:
        for name in DIMENSION_ORDER:
            part = view[view["Dimension"] == name]
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
            got = _table(part, f"_fail_{name}_{nonce}")
            if got:
                st.session_state["_check_pick"] = got
    else:
        got = _table(view, f"_fail_all_{nonce}")
        if got:
            st.session_state["_check_pick"] = got

    # Held in session rather than read straight off the selection, so the panel
    # survives a rerun the table did not cause — and so a link, or a test, can open
    # a check without clicking one.
    picked_rule = st.session_state.get("_check_pick")
    if picked_rule in set(failing["Rule id"]):
        with st.container(key="dq_check_panel"):
            _check_panel(picked_rule, tagged_now, registry,
                         adapter.get_violation_samples(), cde_cov, cohort_of,
                         in_domain[["rule_id", "run_ts", "violation_count", "status"]])

# --- Issues requiring attention, and what the register says about coverage ---
# Everything above this line is measured against the rules that exist, so it can only
# ever say how the checks are doing. This band is measured against the elements the
# business registered as mattering — the one denominator on the page that the rule
# set does not control. A gap here is a defect in the rule set, not in the data.

st.markdown('<div style="height:.9rem"></div>', unsafe_allow_html=True)
board, rail = st.columns([2.35, 1])

# Five columns, not the seven a full-width table would take. The last cell has to be
# a real button, so these are Streamlit columns rather than markup — and at the width
# this board actually gets, seven of them cut the badges in half. Column and owner
# ride along under the element name, where they cost no width at all.
ISSUE_COLS = [3.2, 1.15, 1.6, 0.85, 1.05]
ISSUE_HEADS = [
    ("Data element", None),
    ("Criticality", "How much the business says this element matters. A property of "
                    "the element, never of a rule — it is not severity."),
    ("Finding", " · ".join(
        f"{theme.COVERAGE_GAP_LABEL[g]}: {theme.COVERAGE_GAP_MEANING[g]}"
        for g in ("no_rule", "scope_mismatch", "unvalidated"))),
    ("Findings", "Rows the breaching rules on this column reported on the latest run."),
    ("", None),
]

with board:
    with st.container(key="dq_issue_board"):
        st.markdown(
            '<div class="dq-ttl">Issues requiring attention'
            + theme.hint(
                theme.CDE_ONE_LINER
                + " A finding here is about the rule set, not the data: nothing is "
                "broken in these columns, nothing is checking them.")
            + "</div>",
            unsafe_allow_html=True,
        )

        if cde_cov.empty:
            st.caption("No critical data elements registered.")
        else:
            gaps = cde_cov[cde_cov["coverage_gap"] != "covered"].assign(
                _g=lambda x: x["coverage_gap"].map(
                    {g: i for i, g in enumerate(theme.COVERAGE_GAP_ORDER)}),
                _c=lambda x: x["criticality"].map(
                    {c: i for i, c in enumerate(theme.CRITICALITY_ORDER)}),
            ).sort_values(["_g", "_c", "cde_name"])

            severe = gaps[gaps["criticality"].isin(["critical", "high"])]
            mismatch = gaps[gaps["has_scope_mismatch"]]

            tabs = st.tabs([
                f"Open  {len(gaps)}",
                f"Critical  {len(severe)}",
                f"Scope mismatch  {len(mismatch)}",
            ])

            for n, (tab, subset, blank) in enumerate([
                (tabs[0], gaps, "Every registered element has a rule examining its values."),
                (tabs[1], severe, "No gap on a critical or high element."),
                (tabs[2], mismatch,
                 "No rule contradicts a registered scope. COH-B's root cause would not "
                 "be visible here."),
            ]):
                with tab:
                    q = st.text_input(
                        "Search issues",
                        placeholder="Search element, column, owner…",
                        label_visibility="collapsed",
                        key=f"_issue_q_{n}",
                    ).strip().lower()
                    rows = subset
                    if q:
                        hay = (
                            rows[["cde_name", "target_column", "owner_group",
                                  "criticality", "coverage_gap"]]
                            .astype(str).agg(" ".join, axis=1).str.lower()
                        )
                        rows = rows[hay.str.contains(q, regex=False, na=False)]

                    if rows.empty:
                        st.caption(blank if not q else "Nothing matches this search.")
                        continue

                    for col, (head, tip) in zip(st.columns(ISSUE_COLS), ISSUE_HEADS):
                        col.markdown(
                            '<div class="dq-th"'
                            + (f' title="{html.escape(tip)}"' if tip else "")
                            + f">{head}</div>",
                            unsafe_allow_html=True)
                    st.markdown('<div class="dq-rowline head"></div>',
                                unsafe_allow_html=True)

                    shown = rows.head(5)
                    for _, r in shown.iterrows():
                        cells = st.columns(ISSUE_COLS, vertical_alignment="top")
                        name = html.escape(str(r["cde_name"]))
                        column = html.escape(str(r["target_column"]))
                        owner = html.escape(str(r["owner_group"]))
                        cells[0].markdown(
                            f'<div class="dq-td" title="{name}">{name}</div>'
                            f'<div class="dq-td q" title="{owner}">'
                            f"<code>{column}</code> · {owner}</div>",
                            unsafe_allow_html=True)
                        cells[1].markdown(
                            '<div class="dq-cell">'
                            + theme.criticality_badge(r["criticality"]) + "</div>",
                            unsafe_allow_html=True)
                        cells[2].markdown(
                            '<div class="dq-cell">'
                            + theme.coverage_badge(r["coverage_gap"]) + "</div>",
                            unsafe_allow_html=True)
                        cells[3].markdown(
                            f'<div class="dq-td n">'
                            f'{int(r["latest_violation_rows"]):,}</div>',
                            unsafe_allow_html=True)
                        # Used to switch to the Data elements page. That page is gone;
                        # the element opens in a panel below this board instead.
                        if cells[4].button(
                            "Review", key=f"_rev_{n}_{r['cde_id']}_{r['target_column']}",
                            width="stretch",
                        ):
                            st.session_state["_cde_pick"] = r["cde_id"]
                            st.rerun()
                        st.markdown('<div class="dq-rowline"></div>',
                                    unsafe_allow_html=True)

                    foot, link = st.columns([2.8, 1.2], vertical_alignment="center")
                    foot.markdown(
                        f'<div class="dq-quiet" style="padding-top:.35rem">Showing '
                        f"{len(shown)} of {len(rows)} · gaps are in the rule set, not "
                        "the data</div>",
                        unsafe_allow_html=True)
                    if link.button("View all elements", key=f"_all_{n}", width="stretch"):
                        st.session_state["_scope_open"] = True
                        st.rerun()

with rail:
    if cde_cov.empty:
        st.markdown(
            '<div class="dq-card"><div class="ttl">Critical element coverage</div>'
            '<div class="sub">No elements registered.</div></div>',
            unsafe_allow_html=True)
    else:
        s = coverage.coverage_summary(cde_cov)
        counts = cde_cov["coverage_gap"].value_counts()
        total = len(cde_cov)
        parts = [
            (100.0 * counts.get("covered", 0) / total, "success"),
            (100.0 * counts.get("unvalidated", 0) / total, "moderate"),
            (100.0 * (counts.get("no_rule", 0) + counts.get("scope_mismatch", 0)) / total,
             "critical"),
        ]
        st.markdown(
            '<div class="dq-card"><div class="ttl">Critical element coverage'
            + theme.hint(
                "A column counts as validated when an active rule examines its values. "
                "Checking only that a value is present does not count. A rule "
                "contradicting a scope is a defect in the rule, not the data.")
            + "</div><div class="
            + '"hd">'
            f'{theme.icon("file", 14)} {s["covered"]} of {s["bindings"]} validated'
            '<span class="sp"></span>'
            f'<span style="font-size:1.35rem;font-weight:620;'
            f'color:{theme.TONE["moderate"]["fg"]}">{theme.pct_text(s["covered_pct"])}%</span></div>'
            + theme.segments(parts)
            + '<div class="dq-legend">'
            f'<span>{theme.dot("success")}{counts.get("covered", 0)} validated</span>'
            f'<span>{theme.dot("moderate")}{counts.get("unvalidated", 0)} '
            "presence only</span>"
            f'<span>{theme.dot("critical")}'
            f'{counts.get("no_rule", 0) + counts.get("scope_mismatch", 0)} '
            "no valid rule</span></div>"
            '<div class="sub" style="margin-top:.6rem">'
            f'<b>{s["critical_gaps"]}</b> gap(s) on critical and high elements · '
            f'<b>{s["scope_mismatches"]}</b> rule(s) contradicting a registered scope'
            "</div></div>",
            unsafe_allow_html=True,
        )

    st.markdown('<div style="height:.7rem"></div>', unsafe_allow_html=True)

    recent = run_index.tail(4).iloc[::-1]
    rows_html = []
    for r in recent.itertuples():
        ok = r.p1 == 0
        rows_html.append(
            f'<div class="dq-run">'
            f'<span class="ic" style="color:'
            f'{theme.TONE["success" if ok else "critical"]["fg"]}">'
            f'{theme.icon("check_circle" if ok else "x_circle", 15)}</span>'
            f'<div class="bd"><div class="t1">{r.failing} of {r.checks} checks '
            f'failing</div><div class="t2">{r.run_ts:%d %b %Y · %H:%M}</div></div>'
            f'<span class="n">{theme.pct_text(r.score, 1)}%</span></div>'
        )
    st.markdown(
        '<div class="dq-card"><div class="ttl">Recent runs'
        + theme.hint(
            "The runner records no job status of its own, so these are check outcomes, "
            "not job outcomes. The mark is red when any P1 check failed. Scored "
            "checks only — this rail reads the same set as the figure above it.")
        + "</div>"
        + "".join(rows_html)
        + "</div>",
        unsafe_allow_html=True,
    )

if st.session_state.get("_cde_pick"):
    with st.container(key="dq_element_panel"):
        _element_panel(cde_cov, registry, st.session_state["_cde_pick"])

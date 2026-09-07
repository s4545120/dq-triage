"""Scorecard — how healthy are the critical data elements right now.

**Every figure on this page is scoped to the registered elements.** A check counts
here only if `v_cde_coverage` attached it to a critical data element — 20 of the 34
rules in the fixture. The other 14 watch columns nobody has registered as mattering;
they still run, still raise cohorts, and are still worked from the Cohorts page, but
they do not move a number here. That is the whole point of the scoping: a quality
score whose denominator is "every rule someone happened to write" moves whenever the
rule set does, and cannot be compared across two months or two domains.

`domain/coverage.attached_rule_ids` is the single definition of that set, read back
off the coverage view so this page and the coverage panel can never disagree.

This page is about the data, not about the work. It answers "how healthy is the
watched estate, how complete is the rule coverage, and how recently did checks run".
Table-level diagnosis lives on the All monitored tables page; triage work lives on
the Cohorts and Register pages.

Plain words throughout. A steward reading this should not have to know what
`P1_block`, a `rule_expr` or a `check_run` is.

**Layout.** Three bands, widest question first: a headline score with its own trend,
the four dimensions that roll up into it, and the critical elements that have no
valid rule looking at them, beside recent run outcomes.

**Each dimension opens.** "Validity" is a term of art and the figure on its card is
weighted by rows while the figure two cards up counts checks, so the pair reads as a
contradiction whenever a dimension is nearly clean. The panel behind each card is
where that is settled: the dimension in plain words, the arithmetic with its actual
operands, both denominators side by side, and every check that fed the number.

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
from dq_app.domain import coverage, metrics
from dq_app.ui import components, theme

# --- Scoring ----------------------------------------------------------------
# Two different quality numbers live on this page and they are not interchangeable:
#
#   * "Checks passing" counts CHECKS — 11 of 32. It is what a rule author cares
#     about, and it treats a check over 2,000 rows and a check over 40 alike.
#   * "Overall quality" weights by ROWS — evaluated rows that passed, over evaluated
#     rows. It is what a consumer of the data cares about, and it is the figure the
#     four dimension cards roll up into.
#
# They diverge sharply here (34% against 92%) and that divergence is informative:
# most checks fail, but they fail on a small share of rows. Showing only one of the
# two would hide that.


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


# Four cards, and behind each one a panel you can open.
#
# The cards alone were not enough, for two reasons a reader hits immediately.
# "Validity" is a term of art — not a word a steward uses about their own data — and
# a one-line tooltip is not room enough to say which checks are in it. And the figure
# on the card is weighted by ROWS while the figure two cards up is counted in CHECKS,
# so whenever a dimension is nearly clean the two read as a flat contradiction:
# Consistency scores 99.9%, which used to print as "100%", directly above the words
# "1 failing". Nothing on the page told you which half to believe.
#
# So the panel is where the number is taken apart: what the dimension means in plain
# words, the arithmetic with its actual operands, and every check that fed it. And
# `theme.pct_text` makes sure a dimension with a failing check never prints a clean
# 100 in the first place.

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
        "example": "Contact email is present · SIM serial is present for SIM-bearing products",
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
        "example": "Contact email is well formed · Mobile service number is not a placeholder",
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
        "example": "Subscriber first name agrees with contact first name",
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
        "example": "Mobile service number is not reused across subscriptions",
    },
]
DIMENSION_BY_NAME = {d["name"]: d for d in DIMENSIONS}

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


def _dimension_facts(now: pd.DataFrame) -> dict:
    """The operands behind one dimension's score, kept beside the score itself.

    A percentage with its numerator and denominator thrown away is how a scorecard
    starts lying — the same discipline `domain/metrics.Metric` applies to the spec
    metrics, applied here.
    """
    raised = now[now["status"].isin(["pass", "breach"])]
    breaching = raised[raised["status"] == "breach"]
    evaluated = int(raised["rows_scanned"].sum())
    failed = int(raised["violation_count"].sum())
    return {
        "score": _row_score(now),
        "checks": int(len(raised)),
        "passing": int((raised["status"] == "pass").sum()),
        "failing": int(len(breaching)),
        "shadow": int((now["status"] == "skipped").sum()),
        "evaluated": evaluated,
        "failed_rows": failed,
        "findings": int(breaching["violation_count"].sum()),
        "p1": int((breaching["severity"] == "P1_block").sum()),
    }


def _dimension_cards(check_run: pd.DataFrame, registry: pd.DataFrame) -> list[dict]:
    """Per-dimension score on the latest run, with the move since the run before it."""
    runs = _run_index(check_run)
    if runs.empty:
        return []
    latest = runs.iloc[-1]["run_id"]
    prior = runs.iloc[-2]["run_id"] if len(runs) > 1 else None

    tagged = _tagged(check_run, registry)

    out = []
    for spec in DIMENSIONS:
        name = spec["name"]
        now = tagged[(tagged["run_id"] == latest) & (tagged["Dimension"] == name)]
        was = (
            tagged[(tagged["run_id"] == prior) & (tagged["Dimension"] == name)]
            if prior is not None else now.iloc[0:0]
        )
        before = _row_score(was)
        card = dict(spec)
        card.update(_dimension_facts(now))
        card["delta"] = (None if card["score"] is None or before is None
                         else card["score"] - before)
        card["help"] = f"{spec['short']} {SCORING_NOTE}"
        out.append(card)
    return out


def _dimension_panel(card: dict, rows: pd.DataFrame) -> None:
    """The card, opened up: what the dimension means and how its number was made.

    `rows` is every check in this dimension on the run being scored, shadow ones
    included — a check excluded from the score is still a check someone wrote, and a
    panel that silently drops it invites the reader to conclude the list is the whole
    rule set.
    """
    score = card["score"]
    tone = ("neutral" if score is None else
            "success" if score >= 98 else "moderate" if score >= 90 else "critical")

    head, close = st.columns([5, 1], vertical_alignment="center")
    with head:
        st.markdown(
            '<div class="dq-dim-panel-hd">'
            f'<span class="ic">{theme.icon(card["icon"], 17)}</span>'
            f'<span class="t">{card["name"]}</span>'
            + theme.badge(f"{theme.pct_text(score, 1)}%" if score is not None
                          else "Not scored", tone)
            + f'<span class="q">{html.escape(card["short"])}</span></div>',
            unsafe_allow_html=True,
        )
    if close.button("Close", key="_dim_close", width="stretch"):
        st.session_state.pop("_dim_pick", None)
        st.rerun()

    prose, sums = st.columns([1.55, 1])
    with prose:
        st.markdown(
            f'<div class="dq-dim-prose">{html.escape(card["long"])}</div>'
            '<div class="dq-dim-prose q"><b>Rule types in this dimension:</b> '
            + ", ".join(f"<code>{t}</code>" for t in sorted(_types_in(card["name"])))
            + f'.<br><b>For example:</b> {html.escape(card["example"])}.</div>',
            unsafe_allow_html=True,
        )
    with sums:
        # The arithmetic, with its operands. Both denominators, because the whole
        # confusion this panel exists to settle is that the page carries two.
        if card["evaluated"]:
            st.markdown(
                '<div class="dq-dim-sum"><div class="k">How the score is made</div>'
                f'<div class="m">{card["evaluated"]:,} rows evaluated '
                f'&minus; {card["failed_rows"]:,} rows failed<br>'
                f'&divide; {card["evaluated"]:,} rows evaluated '
                f'= <b>{theme.pct_text(score, 1)}%</b></div>'
                f'<div class="k" style="margin-top:.55rem">Counted in checks instead'
                '</div>'
                f'<div class="m">{card["passing"]} of {card["checks"]} checks passing '
                f'= <b>{theme.pct_text(100.0 * card["passing"] / card["checks"], 0)}%'
                "</b></div></div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div class="dq-dim-sum"><div class="k">How the score is made</div>'
                '<div class="m">No check in this dimension is attached to a '
                "registered element, so there is nothing to score.</div></div>",
                unsafe_allow_html=True,
            )

    # The reconciliation. Only shown when the two figures actually disagree, because
    # a note that appears under every dimension stops being read under any of them.
    if card["failing"] and score is not None and score >= 98:
        st.markdown(
            '<div class="dq-note">'
            f'{theme.icon("info", 14)}<div><b>Why this reads as almost perfect with '
            f'{card["failing"]} check failing.</b> The score is weighted by rows, not '
            f'by checks: {card["failed_rows"]:,} of {card["evaluated"]:,} evaluated '
            f'rows failed. A check that breaches on a handful of rows barely moves a '
            "row-weighted score, and that gap is the information — the data is nearly "
            "clean, the rule set is not. Both numbers are on this page on purpose, "
            "and neither is rounded up to a clean 100 while a check is failing."
            "</div></div>",
            unsafe_allow_html=True,
        )

    theme.section(f"Checks in {card['name'].lower()}")
    if rows.empty:
        st.caption(
            "No check in this dimension is attached to a registered critical data "
            "element, so none of them reaches this page. They may still run — see "
            "the Rules page."
        )
        return

    table = rows.sort_values(["status", "violation_count"],
                             ascending=[True, False]).copy()
    RESULT = {"pass": ("Passed", "success"), "breach": ("Failed", "critical"),
              "skipped": ("Shadow — not scored", "neutral")}
    out = pd.DataFrame({
        "Check": table["rule_name"],
        # A consistency check can span columns and tables, so it has no single
        # target column — XREF_NAME_AGREEMENT is the case. Printing the bare table
        # name under a heading called "Column" would read as one.
        "Where": table.apply(
            lambda r: f'{str(r["target_table"]).split(".")[-1]}.{r["target_column"]}'
            if pd.notna(r["target_column"])
            else f'{str(r["target_table"]).split(".")[-1]} · across columns',
            axis=1),
        "Severity": [theme.severity_badge(s, words=False) for s in table["severity"]],
        "Result": [theme.badge(*RESULT.get(s, (s, "neutral")))
                   for s in table["status"]],
        "Rows checked": table["rows_scanned"].astype(int),
        "Findings": table["violation_count"].astype(int),
        "Failure rate": [f"{v:.2f}%" for v in table["violation_pct"].astype(float)],
    })
    components.summary_table(out, raw={"Severity", "Result"})
    st.markdown(
        '<div class="dq-quiet" style="margin-top:.4rem">A finding is one row failing '
        "one check, so a row with one bad value can appear under several checks here. "
        "Severity belongs to the check and is copied from the rule registry — nothing "
        "on this page recomputes it, and the criticality of the element it touches "
        "never changes it. Like every figure on this page, this list is only the "
        "checks attached to a registered critical data element — a check on a column "
        "nobody registered still runs and still raises a cohort, but it is not "
        "scored here.</div>",
        unsafe_allow_html=True,
    )


# ============================================================================
# Page
# ============================================================================

components.page_chrome()

runs = adapter.get_check_runs()
registry = adapter.get_rule_registry_current()
cde_cov = adapter.get_cde_coverage()

# --- Header -----------------------------------------------------------------

hd, actions = st.columns([4, 1.15], vertical_alignment="center")
with hd:
    st.markdown(
        '<div class="dq-page-hd"><div class="t">Data Quality Scorecard</div>'
        '<div class="s">Quality, coverage, and recent run outcomes across the '
        "critical data elements under watch.</div></div>",
        unsafe_allow_html=True,
    )

if runs.empty:
    st.caption("No check runs available.")
    st.stop()

# --- Filter strip -----------------------------------------------------------

with st.container(key="dq_filter_strip"):
    l1, f1, l2, f2, l3, note = st.columns([0.5, 2.4, 0.5, 1.35, 0.75, 2.1])
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
        # Not a picker. The environment is decided by DQ_APP_DATA_SOURCE before the
        # process starts, and a dropdown here would imply this app can switch
        # catalogs from the UI, which it cannot and should not.
        st.markdown(
            '<div style="padding-top:.42rem">'
            + (theme.badge("Local fixture", "moderate", "table") if adapter.is_local()
               else theme.badge("Unity Catalog", "success", "link"))
            + "</div>",
            unsafe_allow_html=True,
        )
    with note:
        last_ts = runs["run_ts"].max()
        st.markdown(
            f'<div class="dq-strip-note">Last run {last_ts:%d %b, %H:%M}<br>'
            f"Next expected {last_ts + pd.Timedelta(days=1):%d %b, %H:%M}</div>",
            unsafe_allow_html=True,
        )

# The one filter that is not a user control. Everything below counts only checks the
# coverage view attached to a registered element; see the module docstring.
cde_rules = coverage.attached_rule_ids(cde_cov)
if not cde_rules:
    st.caption(
        "No critical data elements are registered, so there is nothing to score. "
        "This page measures the rule set against the register, not against itself."
    )
    st.stop()

scoped = runs[runs["business_domain"].isin(picked) & runs["rule_id"].isin(cde_rules)]
if scoped.empty:
    st.caption("No checks on registered elements in the selected domains.")
    st.stop()

d = metrics.detection_summary(scoped)
rule_name = registry.set_index("rule_id")["rule_name"].to_dict()
run_index = _run_index(scoped)

with actions:
    latest_run_id = metrics.latest_run_id(scoped)
    export = scoped[scoped["run_id"] == latest_run_id].copy()
    export.insert(0, "rule_name", export["rule_id"].map(rule_name))
    st.download_button(
        "Export report",
        data=export.to_csv(index=False).encode(),
        file_name=f"dq-scorecard-{last_ts:%Y%m%d}.csv",
        mime="text/csv",
        icon=":material/download:",
        width="stretch",
        help="Every check result from the run shown, for the domains selected, as CSV. "
             "A read of what is on this page — it starts nothing and changes nothing.",
    )

# --- Headline: one score, its trend, and the four figures behind it ---------
# Cards carry their explanation through theme.hint() rather than Streamlit's `help=`
# — see that function for why.

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

hero, k1, k2, k3, k4 = st.columns([3.9, 1.1, 1.1, 1.1, 1.15])

with hero:
    st.markdown(
        '<div class="dq-card dq-hero"><div class="l">'
        f'<div class="hd">{theme.icon("spark", 14)} Overall quality'
        + theme.hint(
            "Rows that passed their checks, over rows evaluated, on the latest "
            "scheduled run. Weighted by rows, so a check over 2,000 rows counts for "
            "more than a check over 40 — which is why it reads far higher than the "
            "share of checks passing next to it. Shadow checks are in neither half. "
            "The trend is that same figure per run; the axis starts at 80 because the "
            "whole story lives in the top fifth.", side="right")
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

pass_share = 100.0 * d["rules_passing"] / d["rules_raised"] if d["rules_raised"] else 0.0
with k1:
    st.markdown(
        '<div class="dq-card dq-stat">'
        f'<div class="hd">{theme.icon("check_circle", 14)} Checks passing'
        + theme.hint(
            "Checks that passed on the most recent scheduled run, counted one per "
            "check, and only checks attached to a registered element. "
            + (f"{d['rules_skipped']} more ran in shadow mode and are excluded — they "
               "record results but raise nothing until someone promotes them. "
               if d["rules_skipped"] else
               "Shadow checks would be excluded, but none of the shadow rules is "
               "attached to a registered element, so none reaches this figure. ")
            + "Measured on that one run, not averaged: a problem that started four "
            "days ago would be diluted sevenfold by a monthly average.")
        + "</div>"
        f'<div class="val">{d["rules_passing"]}<span class="of">of '
        f'{d["rules_raised"]}</span></div>'
        f'<div class="sub">{theme.pct_text(pass_share)}% passing</div>'
        f'{theme.meter(pass_share, "success" if pass_share >= 80 else "moderate")}'
        "</div>",
        unsafe_allow_html=True,
    )
with k2:
    fail_share = 100.0 * d["rules_breaching"] / d["rules_raised"] if d["rules_raised"] else 0.0
    st.markdown(
        '<div class="dq-card dq-stat">'
        f'<div class="hd">{theme.icon("alert", 14)} Failed checks'
        + theme.hint(
            "Checks whose failure rate is over the limit set for them. 'Critical' is "
            "P1 — severity belongs to the check, and nothing on this page recomputes it.")
        + "</div>"
        f'<div class="val" style="color:{theme.TONE["critical"]["fg"]}">'
        f'{d["rules_breaching"]}</div>'
        f'<div class="sub" style="color:{theme.TONE["critical"]["fg"]}">'
        f'<b>{d["p1_breaching"]} critical</b></div>'
        f'{theme.meter(fail_share, "critical")}'
        "</div>",
        unsafe_allow_html=True,
    )
with k3:
    st.markdown(
        '<div class="dq-card dq-stat">'
        f'<div class="hd">{theme.icon("table", 14)} Findings'
        + theme.hint(
            "One finding is one row failing one check. A single bad row can produce "
            "several findings — the 240 malformed email addresses trip six separate "
            "format checks — so this is always more than the number of bad rows, and "
            "it is never labelled 'records affected'. Counting distinct rows would "
            "need the runner to record a key for every finding, which it currently "
            "does only for the samples it keeps.")
        + "</div>"
        f'<div class="val">{d["violations"]:,}</div>'
        '<div class="sub">across all failing checks</div>'
        "</div>",
        unsafe_allow_html=True,
    )
with k4:
    cde_sum = coverage.coverage_summary(cde_cov)
    st.markdown(
        '<div class="dq-card dq-stat">'
        f'<div class="hd">{theme.icon("eye", 14)} Under watch'
        + theme.hint(
            "Elements the business registered as critical, which is what this whole "
            "page is scored against. The count comes from the register, not from the "
            f"rule set: all {cde_sum['bindings']} columns are counted here whether or "
            "not a rule looks at them, which is why this figure does not move when "
            "someone writes or retires a check. Rows are counted once per table, not "
            "once per check.")
        + "</div>"
        f'<div class="val">{cde_sum["elements"]}<span class="of">CDEs</span></div>'
        f'<div class="sub">{cde_sum["bindings"]} columns · {d["rows_scanned"]:,} rows</div>'
        "</div>",
        unsafe_allow_html=True,
    )

# --- Dimensions -------------------------------------------------------------
# Each card is a `st.container` rather than a block of markup, because its last row
# has to be a real button and a button cannot live inside markup this app generates —
# the same reason the issue board below is built from columns instead of a table. The
# border is drawn on the container; the markup inside carries `.dq-dim` so the
# equal-height rule in `theme` still finds this row.

theme.section("Data quality dimensions")
st.markdown(
    '<div class="dq-quiet" style="margin:-.35rem 0 .55rem">The four questions a '
    "quality programme asks of a column. Open one to see what it means, how its score "
    "was made, and every check behind it.</div>",
    unsafe_allow_html=True,
)

dim_cards = _dimension_cards(scoped, registry)
picked_dim = st.session_state.get("_dim_pick")

for i, (col, dim) in enumerate(zip(st.columns(len(dim_cards)), dim_cards)):
    if dim["score"] is None:
        value, tone, sub = "—", "neutral", "no check attached to an element"
    else:
        value = f"{theme.pct_text(dim['score'])}%"
        tone = ("success" if dim["score"] >= 98
                else "moderate" if dim["score"] >= 90 else "critical")
        sub = f"{dim['failing']} failing · {dim['findings']:,} findings"
    on = picked_dim == dim["name"]
    with col:
        with st.container(key=f"dq_dim_{dim['name'].lower()}"):
            st.markdown(
                '<div class="dq-dim">'
                + ('<span class="dq-dim-on"></span>' if on else "")
                + f'<div class="hd">{theme.icon(dim["icon"], 15)} {dim["name"]}'
                # The leftmost card has no room to its left for a bubble — stMain
                # is the scroll container and clips anything that leaves it.
                + theme.hint(dim["help"], side="right" if i == 0 else "left")
                + '<span class="sp"></span>'
                f'{theme.delta(dim["delta"], "%", 1)}</div>'
                f'<div class="val" style="color:{theme.TONE[tone]["fg"]}">{value}</div>'
                f'{theme.meter(dim["score"], tone)}'
                f'<div class="sub">{sub}</div>'
                "</div>",
                unsafe_allow_html=True,
            )
            # The label says what opening it gets you, and how much of it there is.
            # "Details" would say neither.
            label = ("Hide breakdown" if on
                     else f"What this means · {dim['checks']} checks")
            if st.button(label, key=f"_dim_{dim['name']}", width="stretch"):
                st.session_state["_dim_pick"] = None if on else dim["name"]
                st.rerun()

if picked_dim in DIMENSION_BY_NAME:
    card = next(c for c in dim_cards if c["name"] == picked_dim)
    latest_id = run_index.iloc[-1]["run_id"]
    tagged_now = _tagged(scoped, registry, latest_id)
    with st.container(key="dq_dimension_panel"):
        _dimension_panel(card, tagged_now[tagged_now["Dimension"] == picked_dim])

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
                    term = st.text_input(
                        "Search issues",
                        placeholder="Search element, column, owner…",
                        label_visibility="collapsed",
                        key=f"_issue_q_{n}",
                    ).strip().lower()
                    rows = subset
                    if term:
                        hay = (
                            rows[["cde_name", "target_column", "owner_group",
                                  "criticality", "coverage_gap"]]
                            .astype(str).agg(" ".join, axis=1).str.lower()
                        )
                        rows = rows[hay.str.contains(term, regex=False, na=False)]

                    if rows.empty:
                        st.caption(blank if not term else "Nothing matches this search.")
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
                        if cells[4].button(
                            "Review", key=f"_rev_{n}_{r['cde_id']}_{r['target_column']}",
                            width="stretch",
                        ):
                            st.session_state["_cde_pick"] = r["cde_id"]
                            st.switch_page("dq_app/ui/pages/cde_registry.py")
                        st.markdown('<div class="dq-rowline"></div>',
                                    unsafe_allow_html=True)

                    foot, link = st.columns([2.8, 1.2], vertical_alignment="center")
                    foot.markdown(
                        f'<div class="dq-quiet" style="padding-top:.35rem">Showing '
                        f"{len(shown)} of {len(rows)} · gaps are in the rule set, not "
                        "the data</div>",
                        unsafe_allow_html=True)
                    if link.button("View all elements", key=f"_all_{n}", width="stretch"):
                        st.switch_page("dq_app/ui/pages/cde_registry.py")

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
            "not job outcomes. The mark is red when any P1 check failed.")
        + "</div>"
        + "".join(rows_html)
        + "</div>",
        unsafe_allow_html=True,
    )

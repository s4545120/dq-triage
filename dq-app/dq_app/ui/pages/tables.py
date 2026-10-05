"""Tables — every monitored table, most urgent first.

Redrawn 2026-10-06 from a design mock. Four figures across the top, the table list as
clickable rows (a row opens that table), and two cards under it: how the rules split
between passing and breaching, and the way in to the P1 failures. Called "All
monitored tables" in the nav until 2026-09-16; its detail page is not a nav entry —
it needs a table picked here to mean anything.

**The figure is checks passing, not row quality**, and the page's foot says so: see
`ui/monitoring` for why these pages count checks and the scorecard counts rows.

**There is no Run button and no table-level action.** The check runner is a scheduled
job; this page reads its results.
"""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from dq_app.data import adapter
from dq_app.domain import metrics
from dq_app.ui import components, monitoring, theme

DETAIL = "dq_app/ui/pages/table_detail.py"
WINDOWS = [7, 14, 30, 40]
# Table · Checks passing · trend · Breaching rules · Findings · Owner · chevron
GRID = ("minmax(9rem,1.45fr) minmax(7rem,1fr) minmax(6.5rem,.95fr) minmax(6.5rem,.85fr) "
        "minmax(3.5rem,.5fr) minmax(10rem,1.15fr) 1rem")


def _open(table: str, rule_id: str | None = None, breaching: bool = False) -> None:
    st.session_state["monitors_selected_table"] = table
    if rule_id:
        st.session_state["_tm_rule_pick"] = rule_id
    if breaching:
        st.session_state["_tm_rule_filter_saved"] = "breaching"
    st.switch_page(DETAIL)


components.page_chrome()

runs = monitoring.scoped_runs(adapter.get_check_runs())
registry = adapter.get_rule_registry_current()

hd, actions = st.columns([4, 1.1], vertical_alignment="center")
hd.markdown(
    '<div class="dq-page-hd"><div class="t">Table monitoring</div>'
    '<div class="s">Quality and rule coverage across your monitored tables.</div></div>',
    unsafe_allow_html=True,
)

if runs.empty:
    st.caption("No checks on registered critical data elements have run yet.")
    st.stop()

# --- Filters ------------------------------------------------------------------

with st.container(key="monitor_list_filter_strip"):
    l1, f1, l2, f2, note = st.columns([.45, 1.5, .45, 1.3, 2.2],
                                      vertical_alignment="center")
    l1.markdown('<div class="dq-strip-lab">Domain</div>', unsafe_allow_html=True)
    domains = sorted(set(metrics.domains_of(runs)))
    choice = f1.selectbox("Domain", ["All"] + domains, label_visibility="collapsed",
                          format_func=lambda d: " + ".join(domains) if d == "All" else d,
                          key="_tm_domain")
    l2.markdown('<div class="dq-strip-lab">Period</div>', unsafe_allow_html=True)
    # Held outside the widget so the detail page opens on the same period.
    saved = st.session_state.get("tm_window", 30)
    window = f2.selectbox("Period", WINDOWS, index=WINDOWS.index(saved),
                          format_func=lambda d: f"Last {d} days",
                          label_visibility="collapsed")
    st.session_state["tm_window"] = window
    last_ts = runs["run_ts"].max()
    errored = (runs[runs["run_ts"] == last_ts]["status"] == "error").any()
    note.markdown(
        '<div class="dq-strip-note dq-tm-last">'
        + theme.dot("high" if errored else "success")
        + f"Last run {last_ts:%-d %b, %H:%M}"
        + (" · some checks errored" if errored else "") + "</div>",
        unsafe_allow_html=True,
    )

scoped = runs if choice == "All" else runs[metrics.domains_of(runs) == choice]
rows = monitoring.table_rows(scoped, window)
if not rows:
    st.caption("No monitored table in this domain has an active check on the latest run.")
    st.stop()

with actions:
    latest = scoped[scoped["run_id"] == metrics.latest_run_id(scoped)].copy()
    latest.insert(0, "rule_name", latest["rule_id"].map(
        registry.drop_duplicates("rule_id").set_index("rule_id")["rule_name"]))
    st.download_button(
        "Export tables", data=latest.to_csv(index=False).encode(),
        file_name=f"dq-tables-{last_ts:%Y%m%d}.csv", mime="text/csv",
        icon=":material/download:", width="stretch",
        help="Every check result from the latest run in this domain, as CSV — the "
             "checks on registered critical data elements, as on the page.")

# --- Four figures -------------------------------------------------------------

need = [r for r in rows if r["Status"] != "Healthy"]
n_checks = sum(r["Checks"] for r in rows)
n_breach = sum(r["Breaching"] for r in rows)
n_p1 = sum(r["P1"] for r in rows)
red = theme.TONE["critical"]["fg"]


def _fig(label: str, value: str, colour: str | None = None, dot: str = "") -> str:
    style = f' style="color:{colour}"' if colour else ""
    return (f'<div class="f"><div class="l">{dot}{label}</div>'
            f'<div class="v"{style}>{value}</div></div>')


st.markdown(
    '<div class="dq-tmkpi">'
    + _fig("Monitored tables", str(len(rows)))
    + _fig("Need attention", str(len(need)), red if need else None,
           theme.dot("critical") if need else "")
    + _fig("Breaching rules", f'{n_breach}<span class="of"> / {n_checks}</span>',
           red if n_breach else None)
    + _fig("P1 failures", str(n_p1), red if n_p1 else None)
    + "</div>",
    unsafe_allow_html=True,
)

# --- The list -----------------------------------------------------------------

n_critical = sum(r["Status"] == "Critical" for r in rows)
with st.container(key="dq_tmcard"):
    top, ctl = st.columns([1.1, 1.7], vertical_alignment="center")
    top.markdown(
        '<div class="dq-tmcard-hd"><div class="t">Monitored tables'
        f'<span class="dq-count">{len(rows)}</span></div>'
        '<div class="q">Prioritised by critical failures.</div></div>',
        unsafe_allow_html=True,
    )
    with ctl:
        q, seg = st.columns([1.35, 1], vertical_alignment="center")
        term = q.text_input("Search tables", placeholder="Search table or owner",
                            label_visibility="collapsed", icon=":material/search:",
                            key="_tm_search").strip().lower()
        st.session_state.setdefault("_tm_show", "all")
        show = seg.segmented_control(
            "Tables shown", ["all", "critical"], key="_tm_show",
            label_visibility="collapsed",
            format_func=lambda v: f"All tables {len(rows)}" if v == "all"
            else f"Critical {n_critical}") or "all"

    view = [r for r in rows if show != "critical" or r["Status"] == "Critical"]
    if term:
        view = [r for r in view
                if term in f"{r['key']} {r['Owner']} {r['Domain']}".lower()]

    components.row_head(["Table", "Checks passing", f"{window}-day trend",
                         "Breaching rules", ("Findings", "n"), "Owner", ""], GRID)

    def _cells(r) -> str:
        tone = monitoring.STATUS_TONE[r["Status"]]
        spark_tone = "critical" if r["Breaching"] else "info"
        return (
            f'<span class="stack dq-tmname" style="--dq-stripe:{theme.TONE[tone]["fg"]}">'
            f'<span class="t1">{html.escape(r["Table"])}'
            f'{theme.badge(r["Status"], tone)}</span>'
            f'<span class="t2 sans">{html.escape(r["Domain"])} · {r["Rows"]:,} rows'
            "</span></span>"
            '<span class="stack">'
            f'<span class="t1 big">{theme.pct_text(r["Score"], 1)}%</span>'
            f'<span class="t2 sans">{r["Passing"]} of {r["Checks"]}</span>'
            + theme.meter(r["Score"], "critical" if r["Breaching"] else "info")
            + "</span>"
            '<span class="stack">'
            + (theme.sparkline([v for _, v in r["History"]], width=120, height=22,
                               tone=spark_tone) or '<span class="t2 sans">—</span>')
            + f'<span class="t2 sans">{html.escape(r["Change"])}</span></span>'
            f'<span class="num lft">{r["Breaching"]} / {r["Checks"]}'
            + (f' {theme.badge(str(r["P1"]) + " P1", "critical")}' if r["P1"] else "")
            + "</span>"
            f'<span class="num">{r["Findings"]:,}</span>'
            f'<span class="dq-owner"><i>{monitoring.initials(r["Owner"])}</i>'
            f'{html.escape(r["Owner"])}</span>'
            f'<span class="opn">{theme.icon("arrow_right", 15)}</span>'
        )

    def _tip(r) -> list:
        return [r["Table"], (r["key"], "mono"),
                f"{r['Breaching']} of {r['Checks']} checks over their limit · "
                f"{r['P1']} P1 · last run {r['Last run']:%-d %b, %H:%M}"]

    if view:
        # A row is a link, not a selection: it leaves the page, so it takes no `picked`.
        with st.container(key="dqrows_tables"):
            got = components.clickable_rows(
                view, GRID, _cells, "tm", "key", lambda r: f"Open {r['Table']}", tip=_tip)
        if got:
            _open(got)
    else:
        st.markdown('<div class="dq-tmempty">No table matches.</div>',
                    unsafe_allow_html=True)

st.markdown(
    '<div class="dq-tmfoot">'
    f"<span>{len(view)} of {len(rows)} monitored tables</span>"
    "<span>Scores reflect checks passing, not row-level quality"
    + theme.hint(
        "A table's figure is its checks within their limit over the checks that ran "
        "on the latest run. Counted over checks on registered critical data elements "
        "only, as the scorecard is; checks on unregistered columns still run and "
        "are worked from Triage. The scorecard's quality figure is weighted by rows "
        "and is a different number.", side="left")
    + "</span></div>",
    unsafe_allow_html=True,
)

# --- Rule health, and where to start -------------------------------------------

health, start = st.columns([1.45, 1], gap="medium")
n_pass = n_checks - n_breach
health.markdown(
    '<div class="dq-card dq-tmhealth"><div class="ttl">Rule health'
    + theme.hint("Every active check on the latest run, across the tables listed: "
                 "within its limit, or over it. Shadow checks are measured but raise "
                 "nothing and are not counted.", side="right")
    + f'</div><div class="q">Across {n_checks} monitored rules.</div>'
    '<div class="dq-cov3">'
    + (f'<span style="flex:{n_pass} 1 0;background:{theme.ACCENT}"></span>' if n_pass else "")
    + (f'<span style="flex:{n_breach} 1 0;background:{theme.TONE["critical"]["bd"]}"></span>'
       if n_breach else "")
    + "</div>"
    f'<div class="dq-legend"><span>{theme.dot("info")}{n_pass} passing</span>'
    f'<span><span class="dq-dot" style="background:{theme.TONE["critical"]["bd"]}"></span>'
    f"{n_breach} breaching</span></div></div>",
    unsafe_allow_html=True,
)

p1_tables = sorted((r for r in rows if r["P1"]), key=lambda r: -r["P1"])
with start, st.container(key="dq_tmstart"):
    if p1_tables:
        st.markdown(
            '<div class="t">Start with critical failures</div>'
            f'<div class="q"><b>{n_p1} P1 {"rule" if n_p1 == 1 else "rules"}</b> '
            f'{"needs" if n_p1 == 1 else "need"} attention across {len(p1_tables)} '
            f'{"table" if len(p1_tables) == 1 else "tables"}.</div>',
            unsafe_allow_html=True,
        )
        worst = p1_tables[0]
        first_p1 = next((r["key"] for r in monitoring.rule_rows(scoped, worst["key"],
                                                                 registry)
                         if r["Breach"] and r["Severity"] == "P1_block"), None)
        if st.button(f"Review critical rules · {worst['Table']}", type="tertiary",
                     icon=":material/arrow_forward:", key="_tm_review_p1",
                     help="Opens the table with the most P1 failures, on its first "
                          "breaching P1 rule."):
            _open(worst["key"], first_p1, breaching=True)
    else:
        st.markdown(
            '<div class="t">No critical failures</div>'
            '<div class="q">No P1 rule is over its limit on the latest run.</div>',
            unsafe_allow_html=True,
        )

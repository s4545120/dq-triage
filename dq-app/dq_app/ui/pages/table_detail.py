"""Table detail — one monitored table: how many of its checks pass, and each rule.

Redrawn 2026-10-06 from a design mock, in the scorecard's layout and on its keyed
containers (`dq_elsplit`, `dq_elcard`, `dq_elpane`), so their CSS applies unchanged.
Top: checks passing over the period against all of them passing, and the latest
run's summary. Under it: the rules applied to the table on the left, breaching first,
and the one picked on the right — its pass rate against its own limit, its trend,
the rows that failed, and its run history.

**A disputed rule is grey, not red.** Where the CDE register says a rule measures
rows it should not (`v_cde_coverage.unscoped_rule_ids` — COH-B's two rules on
`subs_c`), its breach is a fact about the rule. It still counts as breaching — it is
over its limit — but its bar and figure are not painted as bad data, and its pane
says why. The scorecard does the same.

**"Investigate rows" is a tab switch, not a new surface.** It opens the Sample rows
tab: the same `violation_sample` rows, columns and cap as everywhere else.

Reached only from the Tables page; `monitors_selected_table` carries the pick.
"""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from dq_app.data import adapter
from dq_app.domain import metrics, slices
from dq_app.ui import components, monitoring, theme

LIST = "dq_app/ui/pages/tables.py"
WINDOWS = [7, 14, 30, 40]
# The two lower cards are the same height by construction, as on the scorecard.
LIST_BODY = 412
TAB_BODY = 352
BELOW, MET, UNASSESSED = (theme.TONE["critical"]["fg"], theme.ACCENT,
                          theme.NEUTRAL["text_3"])


def _pct(value) -> str:
    shown = theme.pct_text(value, 1)
    return (shown[:-2] if shown.endswith(".0") else shown) + ("%" if value is not None else "")


def _pts(points: float) -> str:
    shown = theme.pct_text(abs(points), 0 if abs(points) >= 10 else 1)
    return f"{shown} {'pt' if shown in ('1', '1.0') else 'pts'}"


components.page_chrome()

runs = monitoring.scoped_runs(adapter.get_check_runs())
registry = adapter.get_rule_registry_current()
tables = monitoring.table_rows(runs, 30)

if not tables:
    st.caption("No checks on registered critical data elements have run yet.")
    st.stop()

selected = st.session_state.get("monitors_selected_table")
if selected not in {t["key"] for t in tables}:
    selected = tables[0]["key"]
    st.session_state["monitors_selected_table"] = selected

# --- Breadcrumb and header ------------------------------------------------------

with st.container(key="dq_tmcrumb", horizontal=True, vertical_alignment="center",
                  gap="small"):
    if st.button("Table monitoring", type="tertiary", key="_tm_back"):
        st.switch_page(LIST)
    st.markdown(f'<span class="dq-crumb">/&nbsp;&nbsp;{html.escape(monitoring.short_name(selected))}'
                "</span>", unsafe_allow_html=True)

saved = st.session_state.get("tm_window", 30)
head, ctl = st.columns([3, 1.5], vertical_alignment="top")
with ctl, st.container(key="dq_tmctl"):
    a, b = st.columns([1.2, 1], vertical_alignment="center")
    window = a.selectbox("Period", WINDOWS, index=WINDOWS.index(saved),
                         format_func=lambda d: f"Last {d} days",
                         label_visibility="collapsed", key="_tm_detail_window")
    st.session_state["tm_window"] = window

t = next(r for r in monitoring.table_rows(runs, window) if r["key"] == selected)
mine = runs[runs["target_table"] == selected]
latest_id = metrics.latest_run_id(runs)
now = mine[mine["run_id"] == latest_id]
rules = monitoring.rule_rows(runs, selected, registry)
tone = monitoring.STATUS_TONE[t["Status"]]

with ctl:
    export = now.copy()
    export.insert(0, "rule_name", export["rule_id"].map(
        registry.drop_duplicates("rule_id").set_index("rule_id")["rule_name"]))
    b.download_button("Export", data=export.to_csv(index=False).encode(),
                      file_name=f"dq-{t['Table']}-{t['Last run']:%Y%m%d}.csv",
                      mime="text/csv", icon=":material/download:", width="stretch",
                      help="This table's check results from the latest run, as CSV.")
    st.markdown(f'<div class="dq-tmrun">Last run: {t["Last run"]:%-d %b, %H:%M}</div>',
                unsafe_allow_html=True)

head.markdown(
    '<div class="dq-tmhead">'
    f'<div class="n">{html.escape(t["Table"])}{theme.badge(t["Status"], tone)}</div>'
    f'<div class="fq">{html.escape(selected)}</div>'
    f'<div class="m">{html.escape(t["Domain"])} · {html.escape(t["Owner"])}</div></div>',
    unsafe_allow_html=True,
)

# --- Checks passing, and the run summary ----------------------------------------

breaching = [r for r in rules if r["Breach"]]
disputed = [r for r in breaching if r["Disputed"]]
score = t["Score"]
p1 = t["P1"]
raised = now[now["status"].isin(monitoring.RAISED)]
bad = raised[raised["status"] == "breach"]
cols_checked = raised["target_column"].dropna().nunique()
cols_failing = bad["target_column"].dropna().nunique()

# The population the latest run drew from, when the run recorded it, and any run in the
# window where the table's slice changed -- a step in the line there is a different set
# of rows, not data moving.
pop = slices.run_population(now, selected)
since = mine["run_ts"].min() if len(mine) else None
moved = [ts for ts in slices.slice_breaks(mine, selected) if since is None or ts >= since]

hero, summary = st.columns([2.2, 1], gap="medium")
hero.markdown(
    '<div class="dq-card dq-hero">'
    '<div class="ttl">Checks passing'
    + theme.hint(
        "Checks within their limit, over the checks that ran, per scheduled run. A "
        "count, not a row-weighted score: one check over 1,000 rows counts the same "
        "as one over 40. The dashed line is every check passing.", side="right")
    + '<span class="dq-lg"><i></i>Checks passing<i class="dash"></i>All passing</span></div>'
    f'<div class="val"><span style="color:{BELOW if breaching else theme.NEUTRAL["text"]}">'
    f'{theme.pct_text(score, 1)}<span class="of unit">%</span></span></div>'
    f'<div class="sub">{t["Passing"]} of {t["Checks"]} rules</div>'
    + theme.target_chart(t["History"], 100.0, 640, 150)
    + '<div class="say">'
    + (f'<b>{len(breaching)} {"rule is" if len(breaching) == 1 else "rules are"}</b> '
       "breaching their configured limits"
       + (f", {len(disputed)} of them a rule the CDE register disputes." if disputed
          else ".")
       if breaching else "<b>Every rule</b> is within its configured limit.")
    + (f" The table's slice changed on {pd.Timestamp(moved[-1]):%-d %b}: runs before it "
       "checked a different set of rows." if moved else "")
    + "</div></div>",
    unsafe_allow_html=True,
)


def _kv(label: str, value: str, colour: str | None = None) -> str:
    style = f' style="color:{colour}"' if colour else ""
    return f'<div class="r"><span>{label}</span><b{style}>{value}</b></div>'


summary.markdown(
    '<div class="dq-card dq-tmsum"><div class="ttl">Run summary'
    + theme.hint("The latest scheduled run on this table. Findings are failed checks "
                 "summed per rule: one row failing two rules is two findings.")
    + "</div>"
    + _kv("Findings", f'{t["Findings"]:,}')
    + _kv("Rows evaluated", f'{t["Rows"]:,}')
    + (_kv("Rows in its slice", f'{pop["slice_rows"]:,} of {pop["table_rows"]:,}')
       if pop and pop["slice_version"] is not None and pop["table_rows"] is not None
       and pop["slice_rows"] is not None else "")
    + _kv("Columns affected", f"{cols_failing} of {cols_checked}")
    + '<div class="gap"></div>'
    + _kv("P1 failures", str(p1), BELOW if p1 else None)
    + '<div class="ft">Findings can overlap across rows.</div></div>',
    unsafe_allow_html=True,
)


# The rule list and the pane beside it are one fragment: picking a rule, the
# Breaching / All toggle, the search and the tabs redraw these two cards and not the
# header, the window control or the figures above, none of which reads a selection
# made here. The window control is outside, so changing it is a full run.


@st.fragment
def _rules_and_pane() -> None:
    # --- Applied rules, and the one picked -------------------------------------------

    # The list page's "Review critical rules" asks for the breaching view; a widget's key
    # cannot be set from another page, so it leaves a note and this applies it once.
    if st.session_state.pop("_tm_rule_filter_saved", None) == "breaching":
        st.session_state["_tm_rule_filter"] = "breaching"
    st.session_state.setdefault("_tm_rule_filter", "breaching" if breaching else "all")

    with st.container(key="dq_elsplit"):
        left, right = st.columns([1, 1.3], gap="medium")

    with left, st.container(key="dq_elcard"):
        st.markdown(
            f'<div class="dq-elcard-hd"><div class="t">Applied rules ({len(rules)})</div></div>',
            unsafe_allow_html=True)
        which = st.segmented_control(
            "Rules shown", ["breaching", "all"], key="_tm_rule_filter",
            label_visibility="collapsed",
            format_func=lambda v: f"Breaching {len(breaching)}" if v == "breaching"
            else f"All {len(rules)}") or "all"
        term = st.text_input("Search rules", placeholder="Search rules or attributes",
                             label_visibility="collapsed", icon=":material/search:",
                             key=f"_tm_rule_search_{selected}").strip().lower()
        listed = breaching if which == "breaching" else rules
        if term:
            listed = [r for r in listed
                      if term in f"{r['Rule']} {r['Column']} {r['key']}".lower()]

        pick = st.session_state.get("_tm_rule_pick")
        if pick not in {r["key"] for r in rules}:
            pick = (listed or rules)[0]["key"] if (listed or rules) else None

        def _colour(r) -> str:
            return UNASSESSED if r["Disputed"] else BELOW if r["Breach"] else MET

        def _cells(r) -> str:
            colour = _colour(r)
            return (
                '<span class="dq-el">'
                f'<span class="l1"><span class="nm">{html.escape(r["Rule"])}</span>'
                f'<span class="sc" style="color:{BELOW if colour == BELOW else theme.NEUTRAL["text"]}">'
                f'{_pct(r["Rate"])}</span></span>'
                + theme.target_bar(r["Rate"], r["Target"], colour)
                + '<span class="l2">'
                f'<span>{html.escape(r["Column"])} · {theme.severity_text(r["Severity"])}</span>'
                f'<span>{r["Findings"]:,} findings · Limit {_pct(r["Limit"])}</span>'
                "</span></span>"
            )

        def _tip(r) -> list:
            return [r["Rule"], (r["key"], "mono"),
                    "Rule scope disputed by the CDE register" if r["Disputed"] else
                    "Over its limit" if r["Breach"] else "Within its limit"]

        if listed:
            with st.container(height=LIST_BODY if len(listed) > 5 else "content",
                              key="dqrows_elist"):
                components.clickable_rows(listed, "minmax(0,1fr)", _cells, "tr", "key",
                                          lambda r: f"Show {r['Rule']}", picked=pick, tip=_tip,
                                          on_pick=components.pick_into("_tm_rule_pick"))
        else:
            st.markdown('<div class="dq-tmempty">No rule matches.</div>',
                        unsafe_allow_html=True)
        st.markdown(
            '<div class="dq-elfoot">'
            f"<span>Showing {len(listed)} of "
            f"{len(breaching) if which == 'breaching' else len(rules)}"
            f"{' breaching' if which == 'breaching' else ''} rules</span>"
            "<span>Bars: pass rate<i></i>Limit</span></div>",
            unsafe_allow_html=True)

    sel = next((r for r in rules if r["key"] == pick), None)

    with right, st.container(key="dq_elpane"):
        if sel is None:
            st.caption("No active rule ran on this table on the latest run.")
            st.stop()

        reg = registry[registry["rule_id"] == sel["key"]]
        reg = reg.iloc[0] if not reg.empty else None
        colour = _colour(sel)
        shortfall = sel["Target"] - sel["Rate"]
        state = ("Disputed scope", "neutral") if sel["Disputed"] else \
            ("Failing", "critical") if sel["Breach"] else ("Passing", "success")
        verdict = (f"Target {_pct(sel['Target'])}"
                   + (" · not assessed: the rule's scope is disputed" if sel["Disputed"] else
                      f' · <span class="dq-below">{_pts(shortfall)} below</span>'
                      if sel["Breach"] else " · within its limit"))
        st.markdown(
            '<div class="dq-elhd"><div class="k">Selected rule</div>'
            f'<div class="n">{html.escape(sel["Rule"])}</div>'
            f'<div class="b">{theme.badge(state[0], state[1])}'
            f'{theme.severity_badge(sel["Severity"])}</div>'
            f'<div class="w">{html.escape(sel["Column"])} · {html.escape(sel["key"])}</div>'
            '<div class="sr">'
            f'<span class="s" style="color:{BELOW if colour == BELOW else theme.NEUTRAL["text"]}">'
            f'{_pct(sel["Rate"])}</span><span>Pass rate</span></div>'
            f'<div class="dq-tmverdict">{verdict}</div></div>',
            unsafe_allow_html=True,
        )

        samples = adapter.get_violation_samples()
        captured = int(((samples["rule_id"] == sel["key"])
                        & (samples["run_id"] == sel["run_id"])).sum())
        labels = ["Overview",
                  f"Sample rows · {captured:,}" if captured else "Sample rows",
                  "History"]
        tab_key = f"_tm_tab_{sel['key']}"

        def _to_rows(label=labels[1], key=tab_key) -> None:
            st.session_state[key] = label

        tab_over, tab_rows, tab_hist = st.tabs(labels, key=tab_key, on_change="rerun")
        rule_runs = mine[(mine["rule_id"] == sel["key"]) & mine["status"].isin(monitoring.RAISED)]

        with tab_over, st.container(height=TAB_BODY, border=False, key="dq_eltab_overview"):
            hist = monitoring.history(rule_runs, window,
                                      lambda g: 100.0 - float(g["violation_pct"].iloc[0]))
            st.markdown(
                '<div class="dq-elover">'
                '<div><span class="dq-lg"><i></i>Pass rate'
                + ('<i class="dash"></i>Limit' if not sel["Disputed"] else "")
                + "</span></div>"
                + theme.target_chart(hist, None if sel["Disputed"] else sel["Target"], 580, 140)
                + '<div class="dq-tmrates">'
                f'<div><span>Failure rate</span><b>{_pct(sel["Failure"])}</b></div>'
                f'<div><span>Allowed failure rate</span><b>{_pct(sel["Limit"])}</b></div>'
                "</div></div>",
                unsafe_allow_html=True,
            )
            if sel["Findings"]:
                with st.container(key="dq_tmalert", horizontal=True,
                                  vertical_alignment="center"):
                    st.markdown(
                        f'<div class="dq-tmalert{" grey" if sel["Disputed"] else ""}">'
                        + theme.icon("alert", 15)
                        + f'<span>{sel["Findings"]:,} of {sel["Rows"]:,} evaluated rows fail '
                        "this rule."
                        + (" The CDE register says the rule measures rows it should not."
                           if sel["Disputed"] else "")
                        + "</span></div>",
                        unsafe_allow_html=True)
                    st.button("Investigate rows", key="_tm_investigate",
                              icon=":material/arrow_forward:", icon_position="right",
                              on_click=_to_rows)
            else:
                st.caption("No row failed this rule on the latest run.")

            cohort_id = metrics.cohort_for_rules(adapter.get_cohorts(), [sel["key"]]).get(sel["key"])
            if sel["Breach"] and cohort_id:
                if st.button(f"Open the problem it belongs to · {cohort_id[:8]}",
                             type="tertiary", key="_tm_to_triage",
                             icon=":material/open_in_new:"):
                    st.session_state["selected_cohort"] = cohort_id
                    st.switch_page("dq_app/ui/pages/triage_detail.py")

        with tab_rows, st.container(height=TAB_BODY, border=False, key="dq_eltab_rows"):
            if sel["Findings"]:
                components.failed_rows(sel["key"], sel, samples, heading=False)
            else:
                st.caption("No row failed this rule on the latest run.")

        with tab_hist, st.container(height=TAB_BODY, border=False, key="dq_eltab_hist"):
            if reg is not None:
                st.markdown(f'<div class="dq-expr">{html.escape(str(reg["rule_expr"]))}</div>'
                            + (f'<div class="dq-expr scope">scoped to '
                               f'{html.escape(str(reg["scope_filter"]))}</div>'
                               if components.opt(reg["scope_filter"]) else ""),
                            unsafe_allow_html=True)
            past = (rule_runs.sort_values("run_ts", ascending=False)
                    .assign(**{"Run": lambda d: d["run_ts"],
                               "Result": lambda d: d["status"].map(
                                   {"breach": "Over limit", "pass": "Within limit"}),
                               "Findings": lambda d: d["violation_count"].astype(int),
                               "Pass rate": lambda d: 100.0 - d["violation_pct"].astype(float),
                               "Limit": lambda d: d["threshold_pct"].astype(float)})
                    [["Run", "Result", "Findings", "Pass rate", "Limit"]])
            st.dataframe(past, hide_index=True, width="stretch",
                         column_config={
                             "Run": st.column_config.DatetimeColumn(format="D MMM, HH:mm"),
                             "Pass rate": st.column_config.NumberColumn(format="%.1f%%"),
                             "Limit": st.column_config.NumberColumn(format="%.1f%%"),
                         })


_rules_and_pane()

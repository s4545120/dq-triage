"""Rule registry — the rules, read by the element they watch, and the promotion write.

Laid out like the scorecard since 2026-10-05: the critical data elements on the left,
the rules naming the one picked on the right, split Active / Shadow, and a drawer for
one rule. Until then this page was a thirteen-column dataframe over 67 rules, a
selectbox of every rule id to inspect one, and a second dataframe of shadow rules
above a second selectbox to promote one — three ways into the same list and none of
them by the thing a steward actually thinks in. Every rule names its element since
2026-09-28, so the element is the natural first cut; `All rules` is the list's first
row for anyone who wants the registry flat.

Same keyed containers as the scorecard (`dq_pillbar`, `dq_elsplit`, `dq_elcard`,
`dq_elpane`, `dqrows_*`, `dq_check_drawer`), so every rule in theme.py that styles
those cards — and the reasons written beside each — applies here unchanged.

Three things worth knowing before reading a number here:

**The registry is append-only and stores no `effective_to`.** A new version is a new
row; the current version is derived at read time. That is why promoting a rule is an
INSERT and why every past version is still in the drawer.

**The `rule_expr` values have been executed, and 33 of 34 agree with the fixture's
Python evaluators.** `sql/out/checkrun.sql` runs each against the mock tables in
`workspace.dq_triage`. The one disagreement is `XREF_NAME_AGREEMENT`, whose `<>` is not
null-safe. The figure in the header is that run's result, not something computed here.

**Expressions print in canonical form.** `dq.fn.is_blank_v1(...)` is rewritten per
layout at seed time, so what this page prints is not necessarily the string the
warehouse holds. A referenced helper is immutable: a change is a `_v2` plus a new
`rule_version`, never an edit.
"""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from dq_app.data import adapter, identity
from dq_app.ui import components, theme
from dq_app.ui.components import opt

components.page_chrome()

ALL = "__all__"
# The list and the rule tabs are fixed-height boxes that scroll inside, so the two
# cards sit level whatever an element holds — the same construction, and the same
# reason, as LIST_BODY / TAB_BODY on the scorecard.
LIST_BODY = 470
TAB_BODY = 410
ROW_GRID = "minmax(0,1fr)"

BELOW, MET, UNASSESSED = (theme.TONE["critical"]["fg"], theme.ACCENT,
                          theme.NEUTRAL["text_3"])
_crit_rank = {c: i for i, c in enumerate(theme.CRITICALITY_ORDER)}
_gap_rank = {g: i for i, g in enumerate(theme.COVERAGE_GAP_ORDER)}


def _pct(v) -> str:
    return "—" if v is None or pd.isna(v) else f"{float(v):.1f}%"


def _row_markup(name: str, figure: str, figure_colour: str, bar: str,
                left: str, right: str, dot: str = "", compact: bool = False) -> str:
    """The scorecard's row: name and figure, the bar, the line under it. Copied rather
    than imported because a page module cannot be imported without running it."""
    head = (f'<span class="l1"><span class="nm">{dot}{html.escape(name)}</span>'
            f'<span class="sc" style="color:{figure_colour}">{figure}</span></span>')
    words = f"<span>{html.escape(left)}</span><span>{html.escape(right)}</span>"
    if compact:
        return f'<span class="dq-el c2">{head}<span class="l2">{bar}{words}</span></span>'
    return f'<span class="dq-el">{head}{bar}<span class="l2">{words}</span></span>'


SHADOW_GREY = "#c5c9d3"


def _stack_bar(failing: int, passing: int, shadow: int) -> str:
    """Rule count by where each stands, as one bar. Not a pass rate: an element whose
    two active rules each fail one row in thirty reads as two failing rules here, and
    the scorecard is where its row-weighted score lives."""
    total = failing + passing + shadow
    if not total:
        return '<span class="dq-sbar"></span>'
    parts = [(failing, BELOW), (passing, MET), (shadow, SHADOW_GREY)]
    return ('<span class="dq-sbar">'
            + "".join(f'<span style="flex:{n} 1 0;background:{c}"></span>'
                      for n, c in parts if n)
            + "</span>")


def _dot(tone: str) -> str:
    return f'<i class="dq-eldot" style="background:{theme.TONE[tone]["fg"]}"></i>'


# --- Data ---------------------------------------------------------------------

registry = adapter.get_rule_registry()
current = adapter.get_rule_registry_current()
runs = adapter.get_check_runs()
elements = adapter.get_cde_registry_current()
cde_cov = adapter.get_cde_coverage()

latest_run_id = runs.loc[runs["run_ts"].idxmax(), "run_id"] if not runs.empty else None
latest = runs[runs["run_id"] == latest_run_id].drop_duplicates("rule_id").set_index("rule_id")
# Rules the register says measure rows they should not. Their breach is a fact about
# the rule, so it is never painted as bad data — as on the scorecard.
disputed_ids = {i for lst in cde_cov["unscoped_rule_ids"] for i in components.as_list(lst)}
worst_gap = (cde_cov.assign(_g=cde_cov["coverage_gap"].map(_gap_rank))
             .sort_values("_g").groupby("cde_id").head(1).set_index("cde_id")["coverage_gap"])
columns_of = {cid: [f"{str(r.target_table).split('.')[-1]}.{r.target_column}"
                    for r in g.itertuples()]
              for cid, g in cde_cov.groupby("cde_id")}
el_by_id = elements.set_index("cde_id")

n_active = int((current["status"] == "active").sum())
n_shadow = int((current["status"] == "shadow").sum())


def _page_head(sub: str) -> str:
    return ('<div class="dq-page-hd"><div class="t">Rule registry</div>'
            f'<div class="s">{sub}</div></div>')


# --- Title and filters ----------------------------------------------------------

with st.container(key="dq_pillbar"):
    head, f1, f2, f3 = st.columns([2.4, 1.05, 1.05, 1.5], vertical_alignment="center")
    with f1:
        sev_choice = st.selectbox(
            "Severity", ["All"] + theme.SEVERITY_ORDER,
            format_func=lambda s: s if s == "All" else
            f"{theme.SEVERITY_SHORT[s]} {theme.SEVERITY_WORD.get(s, '')}".strip())
    with f2:
        domains = sorted(current["business_domain"].dropna().unique())
        dom_choice = st.selectbox("Domain", ["All"] + domains)
    with f3:
        search = st.text_input("Find", placeholder="Find a rule, table or column",
                               label_visibility="collapsed", key="_rule_search")
    head.markdown(_page_head(
        f"{n_active} active · {n_shadow} in shadow · {len(registry)} versions on record"
        " · 33 of 34 expressions verified in the warehouse"
        + theme.hint(
            "Each rule_expr was run against the mock tables in workspace.dq_triage and "
            "its count diffed against the fixture's Python evaluator. 33 agree. "
            "XREF_NAME_AGREEMENT does not: its <> comparison is not null-safe, so it "
            "reports 0 where the evaluator reports 2. That figure is the result of "
            "sql/out/checkrun.sql, not something this page computes.", side="right")),
        unsafe_allow_html=True)

view = current
if sev_choice != "All":
    view = view[view["severity"] == sev_choice]
if dom_choice != "All":
    view = view[view["business_domain"] == dom_choice]
if search:
    hay = (view["rule_id"] + " " + view["rule_name"] + " " + view["target_table"] + " "
           + view["target_column"].fillna("") + " " + view["cde_id"].fillna("")).str.lower()
    view = view[hay.str.contains(search.lower(), regex=False)]
filtered = sev_choice != "All" or dom_choice != "All" or bool(search)


# --- One rule as a row ---------------------------------------------------------

def _rule_row(r) -> dict:
    run = latest.loc[r["rule_id"]] if r["rule_id"] in latest.index else None
    ran = run is not None
    bad = int(run["violation_count"]) if ran else None
    rate = 100.0 - float(run["violation_pct"]) if ran else None
    limit = float(r["fail_threshold_pct"]) if pd.notna(r["fail_threshold_pct"]) else None
    over = ran and limit is not None and float(run["violation_pct"]) > limit
    shadow = r["status"] == "shadow"
    where = str(r["target_table"]).split(".")[-1] + (
        f".{r['target_column']}" if opt(r["target_column"]) else " (join)")
    if not ran:
        state = "Not run"
    elif shadow:
        state = f"Would flag {bad:,}" if bad else "Would pass"
    elif over and r["rule_id"] in disputed_ids:
        state = "Rule scope disputed"
    elif over:
        state = "Failing"
    else:
        state = "Passing"
    return {
        "Rule id": r["rule_id"], "Name": r["rule_name"], "Severity": r["severity"],
        "Status": r["status"], "Where": where, "Rate": rate, "Bad": bad,
        "Target": None if limit is None else 100.0 - limit,
        "Failing": bool(over) and not shadow, "Over": bool(over),
        "Disputed": r["rule_id"] in disputed_ids, "State": state,
        "Version": int(r["rule_version"]), "Type": r["rule_type"],
        "Scoped": bool(opt(r["scope_filter"])), "cde_id": r["cde_id"],
    }


rows = [_rule_row(r) for _, r in view.iterrows()]
# Failing first, worst first; then passing; then what has not run.
rows.sort(key=lambda x: (not x["Failing"], x["Rate"] is None,
                         -(x["Bad"] or 0) if x["Failing"] else 0,
                         theme.SEVERITY_ORDER.index(x["Severity"])
                         if x["Severity"] in theme.SEVERITY_ORDER else 9, x["Name"]))


def _rule_cells(row) -> str:
    colour = (UNASSESSED if row["Status"] == "shadow" or row["Rate"] is None or row["Disputed"]
              else BELOW if row["Failing"] else MET)
    figure = (_pct(row["Rate"])
              + (f'<span class="of"> / ≥ {row["Target"]:.1f}%</span>'
                 if row["Target"] is not None and row["Rate"] is not None else ""))
    return _row_markup(
        row["Name"], figure, BELOW if colour == BELOW else theme.NEUTRAL["text"],
        theme.target_bar(row["Rate"], row["Target"], colour),
        f"{row['Rule id']} · {row['Where']}", row["State"],
        _dot(theme.SEVERITY_TONE.get(row["Severity"], "neutral")), compact=True)


def _rule_tip(row) -> list:
    return [row["Name"], (f"{row['Rule id']} · v{row['Version']}", "mono"),
            f"{theme.SEVERITY_SHORT.get(row['Severity'], row['Severity'])} "
            f"{theme.SEVERITY_WORD.get(row['Severity'], '')} · {row['Type']} · "
            + ("scoped" if row["Scoped"] else "unscoped — every row"),
            (row["Where"], "mono")]


# --- Left: the elements --------------------------------------------------------

def _el_row(cid, name, mine: list[dict], crit=None) -> dict:
    act = [x for x in mine if x["Status"] == "active"]
    shd = [x for x in mine if x["Status"] == "shadow"]
    failing = sum(x["Failing"] for x in act)
    return {
        "key": cid, "Element": name, "Criticality": crit, "N": len(mine),
        "Active": len(act), "Shadow": len(shd), "Failing": failing,
        "Line": f"{len(act)} active · {len(shd)} shadow",
        "Right": (f"{failing} failing" if failing else
                  "No active rule" if not act else "All passing"),
    }


by_el: dict = {}
for x in rows:
    by_el.setdefault(x["cde_id"], []).append(x)

el_rows = []
for cid, er in el_by_id.iterrows():
    mine = by_el.get(cid, [])
    if filtered and not mine:
        continue
    el_rows.append(_el_row(cid, er["cde_name"], mine, er["criticality"]))
el_rows.sort(key=lambda e: (-e["Failing"], _crit_rank.get(e["Criticality"], 9), e["Element"]))
all_row = _el_row(ALL, "All rules", rows)
listed = [all_row] + el_rows

scope = st.session_state.get("_rule_el")
if scope not in {e["key"] for e in listed}:
    scope = ALL


def _el_cells(row) -> str:
    dot = (_dot(theme.CRITICALITY_TONE.get(row["Criticality"], "neutral"))
           if row["Criticality"] else "")
    return _row_markup(
        row["Element"], f"{row['N']} {'rule' if row['N'] == 1 else 'rules'}",
        theme.NEUTRAL["text"] if row["N"] else theme.NEUTRAL["text_2"],
        _stack_bar(row["Failing"], row["Active"] - row["Failing"], row["Shadow"]),
        row["Line"], row["Right"], dot)


def _el_tip(row) -> list:
    if row["key"] == ALL:
        return ["All rules", "Every rule in the registry, whatever element it names"]
    er = el_by_id.loc[row["key"]]
    cols = columns_of.get(row["key"], [])
    return [row["Element"],
            f"{str(er['criticality']).capitalize()} criticality · "
            f"{theme.COVERAGE_GAP_LABEL.get(worst_gap.get(row['key']), '')}",
            (" · ".join(cols), "mono") if cols else None]


with st.container(key="dq_elsplit"):
    left, right = st.columns([1, 1.5], gap="medium")

with left, st.container(key="dq_elcard"):
    n_failing_el = sum(1 for e in el_rows if e["Failing"])
    st.markdown(
        '<div class="dq-elcard-hd"><div class="t">By critical data element'
        + theme.hint("Every rule names the element it watches, so the register is the "
                     "index. The bar splits an element's rules by where each stood on the "
                     "latest run: active and failing, active and passing, or in shadow — "
                     "measured on every run and never raised.", side="right")
        + f'</div><div class="q">{len(el_rows)} elements · {n_failing_el} with a failing '
          f"rule{' · filtered' if filtered else ''}</div></div>",
        unsafe_allow_html=True,
    )
    with st.container(height=LIST_BODY, key="dqrows_rlist"):
        got = components.clickable_rows(
            listed, ROW_GRID, _el_cells, "rel", "key",
            lambda row: f"Show rules on {row['Element']}", picked=scope, tip=_el_tip)
    if got:
        st.session_state["_rule_el"] = got
        st.rerun()
    st.markdown(
        '<div class="dq-elfoot"><span>'
        f'<i class="dq-sbkey" style="background:{BELOW}"></i>Failing'
        f'<i class="dq-sbkey" style="background:{MET}"></i>Passing'
        f'<i class="dq-sbkey" style="background:{SHADOW_GREY}"></i>Shadow</span>'
        "<span>Most failing rules first</span></div>",
        unsafe_allow_html=True)


# --- Right: the rules on the element picked --------------------------------------

sel = next(e for e in listed if e["key"] == scope)
scoped_rows = rows if scope == ALL else by_el.get(scope, [])
active_rows = [x for x in scoped_rows if x["Status"] == "active"]
shadow_rows = [x for x in scoped_rows if x["Status"] == "shadow"]
picked_rule = st.session_state.get("_rule_pick")


def _rule_list(items: list[dict], key: str, empty: str) -> None:
    if not items:
        with st.container(height=TAB_BODY, border=False, key=f"dq_eltab_{key}_none"):
            st.caption(empty)
        return
    with st.container(height=TAB_BODY, border=False, key=f"dqrows_{key}"):
        got = components.clickable_rows(
            items, ROW_GRID, _rule_cells, key, "Rule id",
            lambda row: f"Open {row['Name']}", picked=picked_rule, tip=_rule_tip)
    if got:
        st.session_state["_rule_pick"] = got
        st.rerun()


with right, st.container(key="dq_elpane"):
    if scope == ALL:
        badges = theme.badge(f"{len(el_rows)} elements", "neutral")
        where = "Every table the registry checks"
        kicker = "Whole registry" + (" · filtered" if filtered else "")
    else:
        er = el_by_id.loc[scope]
        gap = worst_gap.get(scope)
        badges = (theme.criticality_badge(er["criticality"])
                  + theme.badge(theme.data_class_label(er["data_class"]), "neutral")
                  + (theme.coverage_badge(gap) if gap else "")
                  + (theme.badge("PII", "high", "shield") if er["pii"] else ""))
        cols = columns_of.get(scope, [])
        where = " · ".join(cols[:3]) + (f" + {len(cols) - 3} more" if len(cols) > 3 else "")
        kicker = "Selected element"
    st.markdown(
        f'<div class="dq-elhd"><div class="k">{kicker}</div>'
        f'<div class="n">{html.escape(sel["Element"])}</div>'
        f'<div class="b">{badges}</div>'
        f'<div class="w">{html.escape(where)}</div>'
        f'<div class="sr"><span class="s">{sel["N"]}</span>'
        f'<span>{"rule" if sel["N"] == 1 else "rules"}</span>'
        f'<span>{sel["Active"]} active · {sel["Shadow"]} in shadow</span>'
        + (f'<span class="dq-below">{sel["Failing"]} failing</span>' if sel["Failing"] else "")
        + "</div></div>",
        unsafe_allow_html=True,
    )

    tabs = [f"Active · {len(active_rows)}", f"Shadow · {len(shadow_rows)}"]
    if scope != ALL:
        tabs.append("Element")
    t = st.tabs(tabs)
    with t[0]:
        _rule_list(active_rows, "ract", "No active rule watches this element"
                   + (" among the rules shown." if filtered else "."))
    with t[1]:
        _rule_list(shadow_rows, "rshd", "No shadow rule waiting"
                   + (" among the rules shown." if filtered else "."))
    if scope != ALL:
        with t[2], st.container(height=TAB_BODY, border=False, key="dq_eltab_overview"):
            tol = er.get("tolerance_pct")
            gap = worst_gap.get(scope)
            st.markdown(
                '<div class="dq-elover">'
                + (f'<div class="dq-dim-prose">{html.escape(str(er["definition"]))}</div>'
                   if opt(er.get("definition")) else "")
                + '<div class="dq-elnote">'
                + (f"<b>Tolerance {float(tol):g}%.</b> " if pd.notna(tol) else
                   "<b>No tolerance declared.</b> ")
                + html.escape(theme.COVERAGE_GAP_MEANING.get(gap, "")) + "</div></div>",
                unsafe_allow_html=True,
            )
            if st.button("Every binding and what checks it", key="_rule_el_details",
                         icon=":material/open_in_new:", type="tertiary"):
                st.session_state.pop("_rule_pick", None)
                st.session_state["_rule_cde_pick"] = scope
                st.rerun()


# --- The drawer: one rule --------------------------------------------------------

def _promote_dialog(r) -> None:
    run = latest.loc[r["rule_id"]] if r["rule_id"] in latest.index else None
    next_v = int(r["rule_version"]) + 1
    who = identity.current()

    @st.dialog("Promote to active", width="medium",
               on_dismiss=lambda: st.session_state.pop("_promote_ask", None))
    def _dialog():
        if run is not None:
            limit = float(r["fail_threshold_pct"])
            breach = float(run["violation_pct"]) > limit
            outcome = (f"On the latest run it measured <b>{int(run['violation_count']):,}"
                       f"</b> of {int(run['rows_scanned']):,} rows ({float(run['violation_pct']):.2f}%) "
                       f"against a limit of {limit:g}%, so from the next run it would "
                       + ("<b>breach</b>, and its breaches go to Triage to be grouped into "
                          "problems." if breach else
                          "<b>pass</b>."))
        else:
            outcome = "It has no run on record, so what it will raise is not yet known."
        st.markdown(
            f'<div class="dq-dim-prose">Appends version <b>{next_v}</b> of '
            f'<code>{html.escape(r["rule_id"])}</code> with status <b>active</b>, in the '
            f'name of <b>{html.escape(who.email)}</b>. {outcome}<br><br>'
            "The registry is append-only: this cannot be undone, only superseded by "
            "another version.</div>",
            unsafe_allow_html=True)
        note = st.text_area("Note", placeholder="Why this rule is ready to raise breaches.",
                            key="_promote_note")
        no, yes = st.columns(2)
        if no.button("Cancel", key="_promote_no", width="stretch"):
            st.session_state.pop("_promote_ask", None)
            st.rerun()
        if yes.button("Promote", key="_promote_yes", type="primary", width="stretch"):
            try:
                adapter.promote_rule(r["rule_id"], note)
            except adapter.WriteRejected as exc:
                st.error(str(exc), icon=":material/block:")
                return
            st.session_state.pop("_promote_ask", None)
            st.toast(f"{r['rule_id']} promoted to active (v{next_v}).",
                     icon=":material/check:")
            st.rerun()

    _dialog()


def _rule_drawer(rule_id: str) -> None:
    r = current[current["rule_id"] == rule_id].iloc[0]
    run = latest.loc[rule_id] if rule_id in latest.index else None
    shadow = r["status"] == "shadow"

    head, close = st.columns([5, 1], vertical_alignment="center")
    with head:
        st.markdown(
            '<div class="dq-dim-panel-hd">'
            f'<span class="t">{html.escape(str(r["rule_name"]))}</span>'
            + theme.severity_badge(r["severity"])
            + theme.badge(r["status"], "success" if r["status"] == "active" else "moderate")
            + theme.badge(r["rule_type"], "neutral")
            + f'<span class="q"><code>{html.escape(rule_id)}</code> · v{int(r["rule_version"])}'
              f' · {html.escape(str(r["target_table"]))}'
            + (f".{html.escape(str(r['target_column']))}" if opt(r["target_column"]) else "")
            + "</span></div>",
            unsafe_allow_html=True,
        )
    if close.button("Close", key="_rule_close", width="stretch"):
        st.session_state.pop("_rule_pick", None)
        st.rerun()

    if run is not None:
        bad = int(run["violation_count"])
        tone = "" if shadow or not bad else f' style="color:{BELOW}"'
        st.markdown(
            '<div class="dq-tilegrid compact" '
            'style="grid-template-columns:repeat(3,minmax(0,1fr));margin:.15rem 0 .2rem">'
            f'<div class="dq-tile"><div class="lab">{"Would flag" if shadow else "Bad rows"}</div>'
            f'<div class="val"{tone}>{bad:,}</div>'
            f'<div class="sub">{float(run["violation_pct"]):.2f}% of rows checked</div></div>'
            '<div class="dq-tile"><div class="lab">Rows checked</div>'
            f'<div class="val">{int(run["rows_scanned"]):,}</div>'
            f'<div class="sub">latest run, {run["run_ts"]:%-d %b}</div></div>'
            '<div class="dq-tile"><div class="lab">Limit</div>'
            f'<div class="val">{float(r["fail_threshold_pct"]):g}%</div>'
            '<div class="sub">breaches above this</div></div></div>',
            unsafe_allow_html=True,
        )
        if shadow:
            st.caption("Shadow: measured on every run and never raised.")

    if shadow:
        if st.button("Promote to active", key="_promote_open", type="primary",
                     icon=":material/arrow_upward:"):
            st.session_state["_promote_ask"] = rule_id
            st.rerun()

    note = opt(r["note"])
    if note:
        st.markdown(f'<div class="dq-dim-prose">{html.escape(str(note))}</div>',
                    unsafe_allow_html=True)
    scope_f = opt(r["scope_filter"])
    join = opt(r.get("join_sql"))
    st.markdown(
        (f'<div class="dq-expr scope">from {html.escape(str(join))}</div>' if join else "")
        + f'<div class="dq-expr">{html.escape(str(r["rule_expr"]))}</div>'
        + (f'<div class="dq-expr scope">scoped to {html.escape(str(scope_f))}</div>'
           if scope_f else
           f'<div class="dq-dim-prose q" style="color:{theme.TONE["moderate"]["fg"]}">'
           "No scope filter — this rule runs on every row of the table.</div>")
        + '<div class="dq-dim-prose q">Expression as written — this app never runs it.</div>',
        unsafe_allow_html=True,
    )

    if opt(r["cde_id"]) and r["cde_id"] in el_by_id.index:
        er = el_by_id.loc[r["cde_id"]]
        st.caption(f"Watching **{er['cde_name']}** · {er['criticality']} criticality · "
                   f"{'PII' if er['pii'] else 'not PII'}")
    if rule_id in disputed_ids:
        st.caption(":red[The CDE register disputes this rule's scope] — it measures rows "
                   "the binding says are legitimately empty.")

    trend = runs[runs["rule_id"] == rule_id].sort_values("run_ts")
    if len(trend) > 1:
        breached = trend[trend["status"] == "breach"]["run_ts"]
        st.markdown(
            '<div class="dq-quiet">Bad rows per run '
            + theme.sparkline(list(trend["violation_count"]), width=180,
                              tone="neutral" if shadow else "critical")
            + (" · measured, never raised" if shadow else
               f" · first breached {breached.min():%-d %b}" if len(breached)
               else " · never breached")
            + "</div>",
            unsafe_allow_html=True,
        )

    st.markdown(
        theme.kv("Domain", f"{r['business_domain']} · {r['owner_group']}")
        + theme.kv("Source layer", r["source_layer"])
        + theme.kv("In shadow since" if shadow else "In force since",
                   f"{pd.Timestamp(r['effective_from']):%-d %b %Y}")
        + theme.kv("Authored by", r["created_by"])
        + (theme.kv("Promoted by", r["promoted_by"]) if opt(r["promoted_by"]) else ""),
        unsafe_allow_html=True,
    )

    versions = registry[registry["rule_id"] == rule_id].sort_values(
        "rule_version", ascending=False)
    theme.section(f"Version history · {len(versions)}")
    st.dataframe(
        versions[["rule_version", "status", "effective_from", "created_by",
                  "fail_threshold_pct", "note"]].rename(columns={
            "rule_version": "Ver", "status": "Status", "effective_from": "From",
            "created_by": "By", "fail_threshold_pct": "Limit", "note": "Note"}),
        width="stretch", hide_index=True,
        column_config={"Limit": st.column_config.NumberColumn(format="%.2f%%")},
    )
    st.caption("Append-only: a change is a new version, never an edit. Who may sign off "
               "a promotion is an open question in the spec — the app records who did "
               "it, not whether they were entitled to.")

    if st.session_state.get("_promote_ask") == rule_id and shadow:
        _promote_dialog(r)


if picked_rule in set(current["rule_id"]):
    with st.container(key="dq_check_drawer"):
        _rule_drawer(picked_rule)
elif st.session_state.get("_rule_cde_pick"):
    with st.container(key="dq_element_drawer"):
        components.element_panel(cde_cov, current, st.session_state["_rule_cde_pick"],
                                 pick_key="_rule_cde_pick")

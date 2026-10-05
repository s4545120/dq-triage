"""Rules — the critical data elements, the rules on the one picked, and one rule in full.

Redrawn 2026-10-06 from a design mock: three cards side by side. CDEs on the left
(search, domain, paged), the picked element's rules in the middle, and the picked
rule on the right — its pass rate against its own target, the rows it failed, and a
Definition & code · Sample rows · History tabset. Until then this page was the
scorecard's two-card layout with a drawer for one rule, and the rule's expression sat
under its version table at the foot of the drawer.

Three things worth knowing before reading a number here:

**Rule logic is the runner's query, not an illustration.** The mock drew a
`CASE WHEN … THEN 'FAIL'` select; nothing runs that. What is printed is the query
`jobs/run_checks.py` runs to fetch the rows a rule flags (`domain/rule_sql.py`, diffed
against the runner by `tests/test_rules_page.py`). Names print in canonical form —
`prod.customer.*`, `dq.fn.is_blank_v1` — and are rewritten per workspace at seed time.
This app never runs it.

**The mock's "Example values" are not here, because nobody wrote any.** A table of
`alex@example.com → Pass` would be text this page invented. What is here instead is
the values the rule actually flagged on its latest run, out of `violation_sample` —
the one accepted PII surface, same rows and cap as the Sample rows tab.

**The registry is append-only and stores no `effective_to`.** Promoting a shadow rule
is an INSERT at `rule_version + 1`, and it asks first. Every past version is under
History.

The `33 of 34 expressions verified` figure is the result of `sql/out/checkrun.sql` in
`workspace.dq_triage`, not something this page computes; `XREF_NAME_AGREEMENT`'s `<>`
is the one that is not null-safe.
"""

from __future__ import annotations

import html
import json

import pandas as pd
import streamlit as st

from dq_app.data import adapter, identity
from dq_app.domain import rule_sql
from dq_app.ui import components, theme
from dq_app.ui.components import opt

components.page_chrome()

# The three cards are the same height by construction: the two lists and the detail
# tabs are fixed-height boxes that scroll inside. Change a row's height or the
# detail header's line count and these need re-measuring, as on the scorecard.
CDE_PAGE = 7
CDE_BODY = 456
RULE_BODY = 576
TAB_BODY = 420
ROW_GRID = "minmax(0,1fr)"

BELOW, MET, UNASSESSED = (theme.TONE["critical"]["fg"], theme.ACCENT,
                          theme.NEUTRAL["text_3"])
_crit_rank = {c: i for i, c in enumerate(theme.CRITICALITY_ORDER)}
_gap_rank = {g: i for i, g in enumerate(theme.COVERAGE_GAP_ORDER)}


def _pct(v, places: int = 1) -> str:
    if v is None or pd.isna(v):
        return "—"
    shown = f"{float(v):.{places}f}"
    return (shown[:-2] if shown.endswith(".0") else shown) + "%"


# --- Data ---------------------------------------------------------------------

registry = adapter.get_rule_registry()
current = adapter.get_rule_registry_current()
runs = adapter.get_check_runs()
elements = adapter.get_cde_registry_current()
cde_cov = adapter.get_cde_coverage()
samples = adapter.get_violation_samples()

# Each rule's own latest measurement. Not the estate's latest run: a shadow check
# measured by the onboarding job is never in "the latest run" (see
# `metrics.latest_run_id`), and its figures would vanish from its own page.
measured = runs[runs["status"] != "error"]
latest = (measured.sort_values("run_ts").drop_duplicates("rule_id", keep="last")
          .set_index("rule_id"))
# Rules the register says measure rows they should not. Their breach is a fact about
# the rule, so it is never painted as bad data — as on the scorecard.
disputed_ids = {i for lst in cde_cov["unscoped_rule_ids"] for i in components.as_list(lst)}
expected_scope = {i: r["expected_scope_filter"] for _, r in cde_cov.iterrows()
                  for i in components.as_list(r["unscoped_rule_ids"])}
worst_gap = (cde_cov.assign(_g=cde_cov["coverage_gap"].map(_gap_rank))
             .sort_values("_g").groupby("cde_id").head(1).set_index("cde_id")["coverage_gap"])
columns_of = {cid: [f"{str(r.target_table).split('.')[-1]}.{r.target_column}"
                    for r in g.itertuples()]
              for cid, g in cde_cov.groupby("cde_id")}
el_by_id = elements.set_index("cde_id")

n_active = int((current["status"] == "active").sum())
n_shadow = int((current["status"] == "shadow").sum())


# --- One rule as a row ---------------------------------------------------------

def _rule_row(r) -> dict:
    run = latest.loc[r["rule_id"]] if r["rule_id"] in latest.index else None
    ran = run is not None
    limit = float(r["fail_threshold_pct"]) if pd.notna(r["fail_threshold_pct"]) else None
    over = ran and limit is not None and float(run["violation_pct"]) > limit
    shadow = r["status"] == "shadow"
    disputed = r["rule_id"] in disputed_ids
    if shadow:
        state, tone = "Shadow", "moderate"
    elif not ran:
        state, tone = "Not run", "neutral"
    elif over and disputed:
        state, tone = "Scope disputed", "neutral"
    elif over:
        state, tone = "Failing", "critical"
    else:
        state, tone = "Passing", "success"
    col = opt(r["target_column"])
    return {
        "Rule id": r["rule_id"], "Name": r["rule_name"], "Severity": r["severity"],
        "Status": r["status"], "Dimension": theme.dimension_for(r["rule_type"]),
        "Column": col if col else "join", "Table": str(r["target_table"]).split(".")[-1],
        "Rate": 100.0 - float(run["violation_pct"]) if ran else None,
        "Bad": int(run["violation_count"]) if ran else None,
        "Rows": int(run["rows_scanned"]) if ran else None,
        "Run ts": run["run_ts"] if ran else None,
        "Run id": run["run_id"] if ran else None,
        "Limit": limit, "Target": None if limit is None else 100.0 - limit,
        "Failing": bool(over) and not shadow, "Disputed": disputed,
        "State": state, "Tone": tone, "cde_id": r["cde_id"],
    }


rows = [_rule_row(r) for _, r in current.iterrows()]
by_el: dict = {}
for x in rows:
    by_el.setdefault(x["cde_id"], []).append(x)
for mine in by_el.values():
    # Failing first, worst first; then passing; then shadow; then what has not run.
    mine.sort(key=lambda x: (
        0 if x["Failing"] else 1 if x["Status"] == "active" and x["Rate"] is not None
        else 2 if x["Status"] == "shadow" else 3,
        -(x["Bad"] or 0) if x["Failing"] else 0,
        theme.SEVERITY_ORDER.index(x["Severity"])
        if x["Severity"] in theme.SEVERITY_ORDER else 9, x["Name"]))


# --- Selection ---------------------------------------------------------------------
# A rule can be asked for on its own (a test, or a link that knows only the rule); its
# element follows from it. Picking an element clears the rule, so the first rule on
# the new element opens.

pick = st.session_state.get("_rule_pick")
if pick not in set(current["rule_id"]):
    pick = None
scope = st.session_state.get("_rule_el")
if pick and scope is None:
    scope = current.loc[current["rule_id"] == pick, "cde_id"].iloc[0]


def _el_row(cid, er) -> dict:
    mine = by_el.get(cid, [])
    return {"key": cid, "Element": er["cde_name"], "Domain": er["business_domain"],
            "Criticality": er["criticality"], "N": len(mine),
            "Failing": sum(x["Failing"] for x in mine), "Gap": worst_gap.get(cid),
            "Hay": " ".join([str(er["cde_name"]), cid, *columns_of.get(cid, []),
                             *(f"{x['Rule id']} {x['Name']}" for x in mine)]).lower()}


all_el = [_el_row(cid, er) for cid, er in el_by_id.iterrows()]
all_el.sort(key=lambda e: (-e["Failing"], _crit_rank.get(e["Criticality"], 9), e["Element"]))
if scope not in {e["key"] for e in all_el}:
    scope = all_el[0]["key"] if all_el else None


# --- Header ------------------------------------------------------------------------

sel_el = next((e for e in all_el if e["key"] == scope), None)
el_rules = by_el.get(scope, [])
if pick is None or pick not in {x["Rule id"] for x in el_rules}:
    pick = el_rules[0]["Rule id"] if el_rules else None
sel = next((x for x in el_rules if x["Rule id"] == pick), None)
tab_key = f"_rule_tab_{pick}"
captured = 0
if sel is not None and sel["Run id"] is not None:
    captured = int(((samples["rule_id"] == pick) & (samples["run_id"] == sel["Run id"])).sum())
TAB_LABELS = ["Definition & code",
              f"Sample rows · {captured:,}" if captured else "Sample rows", "History"]


def _to_tab(label: str) -> None:
    st.session_state[tab_key] = label


crumb = ['<span class="dq-crumb"><b>Rules</b>']
if sel_el:
    crumb.append(f'&nbsp;&nbsp;/&nbsp;&nbsp;{html.escape(sel_el["Element"])}')
if sel:
    crumb.append(f'&nbsp;&nbsp;/&nbsp;&nbsp;{html.escape(sel["Name"])}')
st.markdown("".join(crumb) + "</span>", unsafe_allow_html=True)

head, ctl = st.columns([3, 1.4], vertical_alignment="top")
with head:
    if sel:
        where = f'{sel["Table"]}.{sel["Column"]}' if sel["Column"] != "join" \
            else f'{sel["Table"]} (join)'
        st.markdown(
            '<div class="dq-tmhead dq-rhead">'
            f'<div class="n">{html.escape(sel["Name"])}{theme.badge(sel["State"], sel["Tone"])}</div>'
            f'<div class="m">{html.escape(sel_el["Element"])} · '
            f'<span class="fq">{html.escape(where)}</span></div></div>',
            unsafe_allow_html=True)
    else:
        st.markdown('<div class="dq-tmhead dq-rhead"><div class="n">Rules</div>'
                    '<div class="m">Every rule names the element it watches.</div></div>',
                    unsafe_allow_html=True)
with ctl, st.container(key="dq_rctl"):
    if sel:
        st.button("View run history", icon=":material/history:", key="_rule_hist",
                  on_click=_to_tab, args=(TAB_LABELS[2],), width="stretch")
    st.markdown(
        f'<div class="dq-tmrun">{n_active} active · {n_shadow} in shadow · '
        "33 of 34 expressions verified"
        + theme.hint(
            "Each rule_expr was run against the mock tables in workspace.dq_triage and "
            "its count diffed against the fixture's Python evaluator. 33 agree. "
            "XREF_NAME_AGREEMENT does not: its <> comparison is not null-safe, so it "
            "reports 0 where the evaluator reports 2. That figure is the result of "
            "sql/out/checkrun.sql, not something this page computes.")
        + "</div>",
        unsafe_allow_html=True)


# --- The three cards -----------------------------------------------------------------

with st.container(key="dq_rsplit"):
    c_el, c_rules, c_detail = st.columns([1, 1, 2.2], gap="small")


# Left: the elements.
with c_el, st.container(key="dq_rcde"):
    st.markdown(f'<div class="dq-rcard-hd"><span class="t">CDEs</span>'
                f'<span class="dq-count">{len(all_el)}</span></div>',
                unsafe_allow_html=True)
    term = st.text_input("Search CDEs", placeholder="Search CDEs, columns or rules",
                         label_visibility="collapsed", icon=":material/search:",
                         key="_rule_cde_search").strip().lower()
    domains = sorted({str(e["Domain"]) for e in all_el if opt(e["Domain"])})
    dom = st.selectbox("Domain", ["All domains"] + domains, key="_rule_domain",
                       label_visibility="collapsed")
    listed = [e for e in all_el
              if (not term or term in e["Hay"]) and (dom == "All domains" or e["Domain"] == dom)]
    pages = max(1, -(-len(listed) // CDE_PAGE))
    page = min(st.session_state.get("_rule_cde_page", 0), pages - 1)
    # The page the selection is on, the first time it is drawn — so a rule asked for
    # by id does not open with its element on a page nobody is looking at.
    if "_rule_cde_page" not in st.session_state and scope in {e["key"] for e in listed}:
        page = [e["key"] for e in listed].index(scope) // CDE_PAGE
    shown = listed[page * CDE_PAGE:(page + 1) * CDE_PAGE]

    def _turn(to: int) -> None:
        st.session_state["_rule_cde_page"] = to

    def _el_cells(e) -> str:
        badge = theme.coverage_badge(e["Gap"]) if e["Gap"] else ""
        n = f'{e["N"]} {"rule" if e["N"] == 1 else "rules"}' if e["N"] else "No rules"
        fail = (f' · <span class="dq-below">{e["Failing"]} failing</span>'
                if e["Failing"] else "")
        return (f'<span class="dq-rr"><span class="a"><span class="nm">'
                f'{html.escape(e["Element"])}</span>'
                f'<span class="q">{html.escape(str(e["Domain"]))} · {n}{fail}</span></span>'
                f"{badge}</span>")

    def _el_tip(e) -> list:
        cols = columns_of.get(e["key"], [])
        return [e["Element"],
                f"{str(e['Criticality']).capitalize()} criticality · "
                + theme.COVERAGE_GAP_MEANING.get(e["Gap"], ""),
                (" · ".join(cols), "mono") if cols else None]

    with st.container(height=CDE_BODY, border=False, key="dqrows_rcde"):
        if shown:
            got = components.clickable_rows(
                shown, ROW_GRID, _el_cells, "rc", "key",
                lambda e: f"Show rules on {e['Element']}", picked=scope, tip=_el_tip)
            if got:
                st.session_state["_rule_el"] = got
                st.session_state.pop("_rule_pick", None)
                st.rerun()
        else:
            st.markdown('<div class="dq-tmempty">No element matches.</div>',
                        unsafe_allow_html=True)

    with st.container(key="dq_rpager", horizontal=True, vertical_alignment="center"):
        st.markdown(f'<span class="dq-rpage">Showing {len(shown)} of {len(listed)}</span>',
                    unsafe_allow_html=True)
        # Callbacks, not a button then `st.rerun()`: a rerun called here stops the run
        # before the detail card's tabs are drawn, and a widget not drawn in a run
        # loses its state — the open tab snapped back to the first on every page turn.
        st.button("Previous page", icon=":material/chevron_left:", key="_rule_prev",
                  disabled=page == 0, on_click=_turn, args=(page - 1,))
        st.button("Next page", icon=":material/chevron_right:", key="_rule_next",
                  disabled=page >= pages - 1, type="primary", on_click=_turn,
                  args=(page + 1,))

# Middle: the rules on that element.
with c_rules, st.container(key="dq_rrules"):
    st.markdown(f'<div class="dq-rcard-hd"><span class="t">Rules</span>'
                f'<span class="dq-count">{len(el_rules)}</span></div>',
                unsafe_allow_html=True)
    rterm = st.text_input("Search rules", placeholder="Search rules",
                          label_visibility="collapsed", icon=":material/search:",
                          key=f"_rule_search_{scope}").strip().lower()
    rlisted = [x for x in el_rules
               if not rterm or rterm in f"{x['Name']} {x['Rule id']} {x['Column']}".lower()]

    def _rule_cells(x) -> str:
        line = x["Dimension"]
        if x["Status"] == "shadow" and x["Bad"] is not None:
            line += f" · would flag {x['Bad']:,}" if x["Bad"] else " · would pass"
        return (f'<span class="dq-rr"><span class="a"><span class="nm">'
                f'{html.escape(x["Name"])}</span>'
                f'<span class="q">{html.escape(line)}</span></span>'
                f'{theme.badge(x["State"], x["Tone"])}</span>')

    def _rule_tip(x) -> list:
        return [x["Name"], (f"{x['Rule id']} · {x['Table']}.{x['Column']}", "mono"),
                f"{theme.severity_text(x['Severity'])} · {x['Dimension']} — "
                + theme.DIMENSIONS.get(x["Dimension"], {}).get("short", "")]

    with st.container(height=RULE_BODY, border=False, key="dqrows_rrules"):
        if rlisted:
            got = components.clickable_rows(
                rlisted, ROW_GRID, _rule_cells, "rr", "Rule id",
                lambda x: f"Open {x['Name']}", picked=pick, tip=_rule_tip)
            if got:
                st.session_state["_rule_el"] = scope
                st.session_state["_rule_pick"] = got
                st.rerun()
        else:
            st.markdown('<div class="dq-tmempty">'
                        + ("No rule matches." if el_rules else
                           "No rule watches this element. The register knows the column "
                           "matters; the rule set does not yet.")
                        + "</div>", unsafe_allow_html=True)


# --- Promotion -------------------------------------------------------------------

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
            outcome = (f"On its latest measurement it flagged <b>{int(run['violation_count']):,}"
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


# --- Right: one rule -----------------------------------------------------------------

def _flagged_values(rule_id: str, run_id, column: str) -> pd.DataFrame:
    """The distinct values of the rule's own column among the rows it flagged."""
    mine = samples[(samples["rule_id"] == rule_id) & (samples["run_id"] == run_id)]
    values = []
    for raw in mine["sample_row"]:
        try:
            values.append(json.loads(raw).get(column))
        except (TypeError, ValueError, AttributeError):
            continue
    if not values:
        return pd.DataFrame()
    shown = pd.Series(["NULL" if v is None else repr(v) if str(v).strip() == "" else str(v)
                       for v in values])
    return (shown.value_counts().rename_axis("Value").reset_index(name="Rows")
            .assign(Result="Fail"))[["Value", "Result", "Rows"]]


def _stat(label: str, value: str, colour: str | None = None, sub: str = "") -> str:
    style = f' style="color:{colour}"' if colour else ""
    return (f'<div><span class="l">{label}</span><b{style}>{value}</b>'
            + (f'<span class="s">{sub}</span>' if sub else "") + "</div>")


with c_detail, st.container(key="dq_rdetail"):
    if sel is None:
        st.markdown('<div class="dq-rdet-hd"><div class="k">Rule details</div>'
                    f'<div class="n">{html.escape(sel_el["Element"]) if sel_el else "—"}</div>'
                    "</div>", unsafe_allow_html=True)
        st.markdown('<div class="dq-tmempty">No rule to show. '
                    + html.escape(theme.COVERAGE_GAP_MEANING.get(sel_el["Gap"], "")
                                  if sel_el else "") + "</div>",
                    unsafe_allow_html=True)
        if sel_el and st.button("Every binding and what checks it", type="tertiary",
                                key="_rule_el_details", icon=":material/open_in_new:"):
            st.session_state["_rule_cde_pick"] = scope
            st.rerun()
    else:
        r = current[current["rule_id"] == pick].iloc[0]
        shadow = sel["Status"] == "shadow"
        dim = sel["Dimension"]
        st.markdown(
            '<div class="dq-rdet-hd"><div class="k">Rule details</div>'
            f'<div class="n">{html.escape(sel["Name"])}</div>'
            '<div class="b">'
            + theme.badge(dim, "neutral")
            + (theme.hint(theme.DIMENSIONS[dim]["long"]) if dim in theme.DIMENSIONS else "")
            + theme.severity_badge(sel["Severity"])
            + (theme.badge("Shadow — measured, never raised", "moderate") if shadow else "")
            + f'<span class="id">{html.escape(pick)} · v{int(r["rule_version"])}</span>'
            + "</div></div>",
            unsafe_allow_html=True)

        ran = sel["Rate"] is not None
        rate_colour = (UNASSESSED if shadow or sel["Disputed"] else
                       BELOW if sel["Failing"] else None)
        st.markdown(
            '<div class="dq-rstats">'
            + _stat("Pass rate", _pct(sel["Rate"]) if ran else "—", rate_colour,
                    "scope disputed" if sel["Disputed"] and sel["Failing"] else "")
            + _stat("Target", f'≥ {_pct(sel["Target"])}' if sel["Target"] is not None else "—")
            + _stat("Would flag" if shadow else "Failed rows",
                    f'{sel["Bad"]:,}<span class="of"> / {sel["Rows"]:,}</span>' if ran else "—",
                    BELOW if sel["Failing"] and not sel["Disputed"] else None)
            + _stat("Last run", f'{sel["Run ts"]:%-d %b, %H:%M}' if ran else "Not run")
            + "</div>",
            unsafe_allow_html=True)

        if shadow:
            if st.button("Promote to active", key="_promote_open", type="primary",
                         icon=":material/arrow_upward:"):
                st.session_state["_promote_ask"] = pick
                st.rerun()

        if st.session_state.get(tab_key) not in TAB_LABELS:
            st.session_state.pop(tab_key, None)
        t_def, t_rows, t_hist = st.tabs(TAB_LABELS, key=tab_key, on_change="rerun")

        with t_def, st.container(height=TAB_BODY, border=False, key="dq_rtab_def"):
            note = opt(r["note"])
            scope_f = opt(r["scope_filter"])
            st.markdown(
                '<div class="dq-rsec">What this rule checks</div>'
                f'<div class="dq-dim-prose"><b>{html.escape(sel["Name"])}.</b> '
                f'{html.escape(theme.DIMENSIONS.get(dim, {}).get("short", ""))}'
                + (f' It is {theme.severity_text(sel["Severity"]).lower()} severity.'
                   if sel["Severity"] in theme.SEVERITY_WORD else "")
                + "</div>"
                + (f'<div class="dq-dim-prose q">{html.escape(str(note))}</div>' if note else "")
                + '<div class="dq-rscope"><span>Scope: '
                + (f"rows of {html.escape(sel['Table'])} where <code>{html.escape(str(scope_f))}</code>"
                   if scope_f else
                   f"every row of the join, driven by {html.escape(sel['Table'])}"
                   if sel["Column"] == "join" else f"all rows in {html.escape(sel['Table'])}")
                + f'</span><span>Allowed failure rate: ≤ {_pct(sel["Limit"], 2)}</span></div>'
                + (f'<div class="dq-rwarn">The CDE register disputes this scope: the binding '
                   f"says the column is only populated where "
                   f'<code>{html.escape(str(expected_scope.get(pick)))}</code>, and this rule '
                   "measures every row. The rule is wrong, not the data.</div>"
                   if sel["Disputed"] else ""),
                unsafe_allow_html=True)

            st.markdown(
                '<div class="dq-rsec row"><span>Rule logic</span>'
                '<span class="dq-rchip">Databricks SQL</span></div>',
                unsafe_allow_html=True)
            st.code(rule_sql.rule_logic(r), language="sql", line_numbers=True, wrap_lines=True)
            st.markdown(
                '<div class="dq-dim-prose q">'
                + ("The query the check runner runs for this rule's verdict. "
                   if rule_sql.shape(r) == "variance" else
                   "The query the check runner runs for the rows this rule flags. ")
                + f"The rule passes when flagged ÷ evaluated rows ≤ {_pct(sel['Limit'], 2)}. "
                "Names are canonical and rewritten per workspace; this app never runs it."
                "</div>",
                unsafe_allow_html=True)

            if sel["Column"] != "join" and sel["Bad"]:
                vals = _flagged_values(pick, sel["Run id"], sel["Column"])
                if not vals.empty:
                    st.markdown(
                        '<div class="dq-rsec">Flagged values'
                        '<span class="sub">From the sampled rows on its latest run — '
                        "real values, not illustrations</span></div>",
                        unsafe_allow_html=True)
                    st.dataframe(vals.head(8), hide_index=True, width="stretch")
            if sel["Bad"]:
                st.button(f"View {sel['Bad']:,} {'flagged' if shadow else 'failed'} rows",
                          type="tertiary", key="_rule_to_rows",
                          icon=":material/arrow_forward:", icon_position="right",
                          on_click=_to_tab, args=(TAB_LABELS[1],))
            if st.button(f"About {sel_el['Element']}", type="tertiary",
                         key="_rule_el_details", icon=":material/open_in_new:"):
                st.session_state["_rule_cde_pick"] = scope
                st.rerun()

        with t_rows, st.container(height=TAB_BODY, border=False, key="dq_rtab_rows"):
            if sel["Bad"]:
                components.failed_rows(pick, {"run_id": sel["Run id"],
                                              "violation_count": sel["Bad"]},
                                       samples, heading=False)
            else:
                st.caption("No row failed this rule on its latest run." if ran else
                           "This rule has not been measured yet.")

        with t_hist, st.container(height=TAB_BODY, border=False, key="dq_rtab_hist"):
            mine = measured[measured["rule_id"] == pick].sort_values("run_ts")
            if len(mine) > 1:
                points = [(f"{ts:%-d %b}", 100.0 - float(v))
                          for ts, v in zip(mine["run_ts"], mine["violation_pct"])]
                st.markdown(
                    '<div><span class="dq-lg"><i></i>Pass rate'
                    + ('<i class="dash"></i>Target' if not sel["Disputed"] else "")
                    + "</span></div>"
                    + theme.target_chart(points, None if sel["Disputed"] else sel["Target"],
                                         620, 140),
                    unsafe_allow_html=True)
            past = (mine.sort_values("run_ts", ascending=False)
                    .assign(**{"Run": lambda d: d["run_ts"],
                               "Result": lambda d: d["status"].map(
                                   {"breach": "Over limit", "pass": "Within limit",
                                    "skipped": "Shadow"}).fillna(d["status"]),
                               "Flagged": lambda d: d["violation_count"].astype(int),
                               "Pass rate": lambda d: 100.0 - d["violation_pct"].astype(float),
                               "Limit": lambda d: d["threshold_pct"].astype(float)})
                    [["Run", "Result", "Flagged", "Pass rate", "Limit"]])
            theme.section(f"Runs · {len(past)}")
            st.dataframe(past, hide_index=True, width="stretch", height=220,
                         column_config={
                             "Run": st.column_config.DatetimeColumn(format="D MMM, HH:mm"),
                             "Pass rate": st.column_config.NumberColumn(format="%.1f%%"),
                             "Limit": st.column_config.NumberColumn(format="%.2f%%"),
                         })
            versions = registry[registry["rule_id"] == pick].sort_values(
                "rule_version", ascending=False)
            theme.section(f"Versions · {len(versions)}")
            st.dataframe(
                versions[["rule_version", "status", "effective_from", "created_by",
                          "fail_threshold_pct", "note"]].rename(columns={
                    "rule_version": "Ver", "status": "Status", "effective_from": "From",
                    "created_by": "By", "fail_threshold_pct": "Limit", "note": "Note"}),
                width="stretch", hide_index=True,
                column_config={"Limit": st.column_config.NumberColumn(format="%.2f%%")},
            )
            st.caption(
                "Append-only: a change is a new version, never an edit. "
                + (f"Promoted by {r['promoted_by']}. " if opt(r["promoted_by"]) else "")
                + "Who may sign off a promotion is an open question in the spec — the app "
                "records who did it, not whether they were entitled to.")

        if st.session_state.get("_promote_ask") == pick and shadow:
            _promote_dialog(r)


if st.session_state.get("_rule_cde_pick"):
    with st.container(key="dq_element_drawer"):
        components.element_panel(cde_cov, current, st.session_state["_rule_cde_pick"],
                                 pick_key="_rule_cde_pick")

"""The Slice card on a table's onboarding page — which rows of it are checked.

One card, three states: the slice in force with what the last run counted under it; a
proposal waiting for a second person, with Approve and Reject (Withdraw for its author);
and the editor. The editor builds a STRUCTURED slice -- column, operator, values, and
optionally membership in another table -- never SQL: `domain/slices.render` writes the
predicate, and "Count rows" runs it before anything is written, so the person sees what
the slice keeps and the warehouse has already accepted it.

Every write goes through `onboarding_style.confirm`, like every other onboarding write.
Widget keys start `onbsl_`.
"""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from dq_app.data import adapter, identity
from dq_app.domain import slices
from dq_app.ui import onboarding_style as ui

_OPS = list(slices.OPS)                       # "=", "in", "not_in", "not_null"
_MAX = 4                                      # conditions on this table


def _pct(n, d) -> str:
    return f"{n:,} of {d:,} rows ({100 * n / d:.0f}%)" if d else f"{n:,} rows"


def _sql(text: str | None) -> str:
    if not text:
        return '<span class="onb-cap">whole table — no filter</span>'
    return f'<code style="white-space:pre-wrap">{html.escape(text)}</code>'


def _conditions(prefix: str, columns: list[str], start: list[dict], count_key: str,
                limit: int) -> list[dict]:
    """Rows of column / operator / values. Plain widgets rather than a data editor, so a
    test can drive them."""
    n = st.session_state.setdefault(count_key, max(len(start), 0))
    out = []
    for i in range(n):
        seed = start[i] if i < len(start) else {}
        c1, c2, c3 = st.columns([1.2, 1, 1.6])
        if columns:
            opts = [""] + columns
            col = c1.selectbox("Column", opts, key=f"{prefix}_col_{i}",
                               index=opts.index(seed["column"]) if seed.get("column") in opts else 0,
                               label_visibility="collapsed" if i else "visible")
        else:
            col = c1.text_input("Column", seed.get("column", ""), key=f"{prefix}_col_{i}",
                                label_visibility="collapsed" if i else "visible")
        op = c2.selectbox("Operator", _OPS, key=f"{prefix}_op_{i}",
                          index=_OPS.index(seed["op"]) if seed.get("op") in _OPS else 0,
                          format_func=lambda o: slices.OPS[o],
                          label_visibility="collapsed" if i else "visible")
        vals = c3.text_input("Values, comma-separated", ", ".join(seed.get("values", [])),
                             key=f"{prefix}_val_{i}", disabled=op == "not_null",
                             label_visibility="collapsed" if i else "visible")
        out.append({"column": col, "op": op,
                    "values": [v.strip() for v in vals.split(",") if v.strip()]})
    if n < limit and st.button("Add a condition", key=f"{prefix}_add", type="tertiary"):
        st.session_state[count_key] = n + 1
        st.rerun()
    return out


def draw(table: str, m: dict, n_active: int, col_type: dict[str, str],
         check_runs: pd.DataFrame) -> None:
    me = identity.current().email
    now, pend = slices.in_force(m), slices.pending(m)
    pop = slices.run_population(check_runs, table)

    with st.container(key="onbcard_slice"):
        ui.head("Slice", "Which rows of the table are checked")
        if not adapter.has_slice_columns():
            st.markdown('<div class="onb-ev">This catalog\'s table register predates '
                        'slices, so every check reads the whole table. '
                        '<code>onboard.py install</code> adds them.</div>',
                        unsafe_allow_html=True)
            return

        line = (f"<b>{html.escape(slices.describe(now['spec']))}</b>"
                if now["filter"] else "<b>The whole table.</b>")
        if now["version"] is not None:
            line += f' <span class="onb-cap">· since version {now["version"]}</span>'
        counted = ""
        if pop is not None and pop["slice_rows"] is not None:
            counted = (f'<br>The last run checked {_pct(pop["slice_rows"], pop["table_rows"])}'
                       if pop["table_rows"] else
                       f'<br>The last run checked {pop["slice_rows"]:,} rows')
            counted += "." if pop["slice_version"] == now["version"] else \
                ", under the slice before this one."
        st.markdown(f'<div class="onb-ev">{line}<br>{_sql(now["filter"])}{counted}</div>',
                    unsafe_allow_html=True)

        if pend:
            _pending(table, pend, m, me)
        else:
            _editor(table, now, n_active, col_type)


def _pending(table: str, pend: dict, m: dict, me: str) -> None:
    own = str(pend["by"]).lower() == str(me).lower()
    may_approve = not own or adapter.self_approval_waived()
    st.markdown(
        '<div class="onb-ev" style="border-left:3px solid #c3c6fb;padding-left:.7rem;'
        'margin-top:.5rem"><b>A change is waiting for a second person.</b><br>'
        f'Proposed by {html.escape(str(pend["by"]))}: '
        f'<b>{html.escape(slices.describe(pend["spec"]))}</b><br>{_sql(pend["filter"])}'
        + (f'<br><span class="onb-cap">Why: “{html.escape(str(m.get("note") or ""))}”</span>'
           if m.get("slice_change") == "proposed" and m.get("note") else "")
        + "</div>", unsafe_allow_html=True)
    reason = st.text_input("Reason", key="onbsl_reason",
                           placeholder="Required to reject — kept with the table's history")
    b1, b2, _ = st.columns([1, 1, 2])
    if may_approve and b1.button("Approve slice", key="onbsl_approve",
                                 use_container_width=True):
        ui.ask("slice_approve")
    if b2.button("Withdraw" if own else "Reject", key="onbsl_reject",
                 use_container_width=True):
        ui.ask("slice_reject")
    if not may_approve:
        st.caption("You proposed it, so someone else approves it.")

    def _decide(decision: str):
        def _go():
            try:
                adapter.decide_slice(table, decision, reason)
            except adapter.SliceRejected as exc:
                return str(exc)
            return None
        return _go

    ui.confirm("slice_approve", "Approve this slice?",
               f"From the next run every check on <b>{html.escape(table)}</b> reads only "
               f"<b>{html.escape(slices.describe(pend['spec']))}</b>.<br>{_sql(pend['filter'])}"
               "<br>Scores before and after are over different rows; the trend marks the run "
               "where it changed.", "Approve", _decide("approved"))
    ui.confirm("slice_reject", "Withdraw this slice change?" if own else "Reject this slice change?",
               (f'Reason: “{html.escape(reason)}”<br>' if reason.strip() else
                '<b style="color:#b91c1c">Add a reason first — it is required.</b><br>')
               + "The slice in force stays as it is.", "Withdraw" if own else "Reject",
               _decide("rejected"))


def _editor(table: str, now: dict, n_active: int, col_type: dict[str, str]) -> None:
    propose = slices.needs_second_person(n_active)
    columns = sorted(col_type)
    with st.expander("Change the slice" if now["filter"] else "Check only some rows"):
        st.caption("Only rows matching every condition are checked. "
                   + ("A check on this table is active, so a second person approves a "
                      "change." if propose else
                      "Nothing on this table is active yet, so the slice takes effect "
                      "from the next run."))
        where = _conditions("onbsl_w", columns, now["spec"].get("where", []),
                            "onbsl_n", _MAX)
        seed = now["spec"].get("member_of") or {}
        member = None
        if st.checkbox("…and whose key appears in another table", value=bool(seed),
                       key="onbsl_member"):
            c1, c2, c3 = st.columns([1.2, 1.6, 1.2])
            opts = [""] + columns
            mcol = (c1.selectbox("This table's column", opts, key="onbsl_m_col",
                                 index=opts.index(seed["column"]) if seed.get("column") in opts else 0)
                    if columns else c1.text_input("This table's column", seed.get("column", ""),
                                                  key="onbsl_m_col"))
            mtab = c2.text_input("Other table (catalog.schema.table)", seed.get("table", ""),
                                 key="onbsl_m_tab")
            mkey = c3.text_input("Its matching column", seed.get("key", ""), key="onbsl_m_key")
            mcols = []
            if mtab.count(".") == 2:
                mc = adapter.get_catalog_columns(mtab.strip())
                mcols = sorted(mc["column_name"]) if len(mc) else []
            st.caption("…where, in that table:")
            mwhere = _conditions("onbsl_mw", mcols, seed.get("where", []), "onbsl_mn", 2)
            member = {"column": mcol, "table": mtab, "key": mkey, "where": mwhere}
        spec = slices.normalise({"where": where, "member_of": member})
        note = st.text_input("Why", key="onbsl_note",
                             placeholder="Why these rows — "
                             + ("required; the approver reads it" if propose else "optional"))

        built_key = slices.dumps(spec)
        cached = st.session_state.get("_onbsl_built")
        built = cached["result"] if cached and cached["spec"] == built_key else None
        c1, c2, _ = st.columns([1, 1, 2])
        if c1.button("Count rows", key="onbsl_count", use_container_width=True):
            try:
                built = adapter.build_slice(table, spec)
                st.session_state["_onbsl_built"] = {"spec": built_key, "result": built,
                                                    "error": None}
            except adapter.SliceRejected as exc:
                built = None
                st.session_state["_onbsl_built"] = {"spec": built_key, "result": None,
                                                    "error": str(exc)}
        cached = st.session_state.get("_onbsl_built")
        if cached and cached["spec"] == built_key and cached["error"]:
            st.error(cached["error"], icon=":material/block:")
        if built:
            kept = (_pct(built["slice_rows"], built["table_rows"])
                    if built["slice_rows"] is not None else
                    "a count this data source cannot make")
            st.markdown(f'<div class="onb-ev">Keeps <b>{kept}</b>.<br>{_sql(built["filter"])}'
                        "</div>", unsafe_allow_html=True)
        label = "Propose slice" if propose else "Set slice"
        if c2.button(label, key="onbsl_write", use_container_width=True,
                     disabled=built is None):
            ui.ask("slice_write")

    def _go():
        try:
            adapter.set_slice(table, spec, note)
        except adapter.SliceRejected as exc:
            return str(exc)
        st.session_state.pop("_onbsl_built", None)
        return None

    body = (f"<b>{html.escape(slices.describe(spec))}</b><br>"
            f"{_sql(built['filter'] if built else None)}<br>")
    if built and built["slice_rows"] is not None:
        body += f"Keeps {_pct(built['slice_rows'], built['table_rows'])}.<br>"
    body += ("A second person must approve it before any run uses it." if propose else
             "From the next run every check on the table reads only these rows.")
    ui.confirm("slice_write", "Propose this slice?" if propose else "Set this slice?",
               body, "Propose" if propose else "Set slice", _go)

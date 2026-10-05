"""Onboarding — the tables selected for checking, and the step each one is on.

Drawn to the design mock (the "Onboarding Screens" canvas, artboard 1): four tiles,
the selected tables as clickable rows, and the five steps with the person's ones in
bold. A row opens that table's own page (`onboarding_table.py`), which carries the
review and the promotion; "Add tables" opens the Unity Catalog picker.

A table is selected by a row in `config.monitored_table`; how far it has got is
derived (`domain.onboarding.derive_status`), never stored. `_onb_pick` carries the row
clicked to the table page.
"""

from __future__ import annotations

import html

import streamlit as st

from dq_app.data import adapter
from dq_app.domain import onboarding
from dq_app.ui import components
from dq_app.ui import onboarding_style as ui
from dq_app.ui.components import opt

components.page_chrome()
ui.inject()

head, act = st.columns([4, 1], vertical_alignment="bottom")
with head:
    st.title("Onboarding")
    st.markdown('<div class="onb-cap">Tables selected for data quality checks, and the step '
                'each one is on</div>', unsafe_allow_html=True)
with act:
    if st.button("Add tables", key="onb_add", type="primary", icon=":material/add:",
                 use_container_width=True):
        st.switch_page("dq_app/ui/pages/onboarding_add.py")

status = adapter.get_onboarding_status()
s = onboarding.summary(status)
ui.kpi_row([
    ("Selected", s["selected"], "tables in the pipeline"),
    ("Waiting on you", s["waiting"],
     f'{s["waiting_bindings"]} column bindings to review' if s["waiting_bindings"]
     else "tables ready for a decision", "high" if s["waiting"] else None),
    ("In shadow", s["shadow"], f'{s["shadow_checks"]} checks measured, none raising'),
    ("Active", s["active"], "breaches reach Triage"),
])

left, right = st.columns([2.6, 1])
with left, st.container(key="onbcard_rows"):
    ui.head("Selected tables", "Click a table to continue its step" if len(status) else "")
    if status.empty:
        st.markdown('<div class="onb-ev" style="padding:.4rem 0 1rem">No tables are '
                    'selected yet. Add one from Unity Catalog.</div>', unsafe_allow_html=True)
    else:
        # Flexible columns may shrink to nothing and truncate: fixed minimums summed past
        # the card's width at 1440px and pushed "Last run" out over the card beside it.
        GRID = ("minmax(0,2fr) minmax(0,1.1fr) minmax(7.5rem,1.1fr) 4rem "
                "minmax(0,.9fr) minmax(0,.9fr)")
        rows = []
        for _, r in status.iterrows():
            cat, sch, name = r["target_table"].split(".")
            checks = (f'{int(r["rules_active"])} active' if r["rules_active"]
                      else f'{int(r["rules_shadow"])} in shadow' if r["rules_shadow"] else "—")
            last = opt(r["last_run_ts"])
            rows.append({
                "Code": r["table_code"], "Name": name, "Where": f"{cat}.{sch}",
                "Owner": opt(r["owner_group"]) or "—", "Stage": r["stage"],
                "Bound": int(r["columns_bound"]), "Checks": checks,
                "Last": f"{last:%-d %b}" if last is not None else "—",
            })

        def _cells(m) -> str:
            return (
                f'<span class="stack"><span class="name">{html.escape(m["Name"])}</span>'
                f'<span class="t2">{html.escape(m["Where"])}</span></span>'
                f'<span class="mono">{html.escape(m["Owner"])}</span>'
                f'<span>{ui.stage_badge(m["Stage"])}</span>'
                f'<span class="num">{m["Bound"]}</span>'
                f'<span class="t2" style="font-size:.84rem">{html.escape(m["Checks"])}</span>'
                f'<span class="mono">{html.escape(m["Last"])}</span>'
            )

        components.row_head(["Table", "Owner", "Step", ("Columns", "n"), "Checks",
                             "Last run"], GRID)
        with st.container(key="dqrows_onb"):
            got = components.clickable_rows(rows, GRID, _cells, "onb", "Code",
                                            lambda m: f"Open {m['Where']}.{m['Name']}")
        if got:
            st.session_state["_onb_pick"] = got
            st.switch_page("dq_app/ui/pages/onboarding_table.py")

with right, st.container(key="onbcard_how"):
    ui.head("How a table gets checked")
    st.markdown(
        '<div class="onb-hw">'
        '<i>1</i><span><b>You select it</b> from Unity Catalog</span>'
        '<i>2</i><span>A job proposes which columns hold which registered element</span>'
        '<i>3</i><span><b>The element\'s owner approves</b> each binding</span>'
        '<i>4</i><span>Checks are generated in shadow and measured, raising nothing</span>'
        '<i>5</i><span><b>A person promotes</b> them after seeing the numbers</span>'
        '</div><div class="onb-rule" style="margin-top:.4rem"></div>'
        '<div class="onb-cap">Steps in bold are a person\'s, and every one is recorded with '
        'a name. Whoever suggests a binding cannot also approve it.</div>',
        unsafe_allow_html=True)

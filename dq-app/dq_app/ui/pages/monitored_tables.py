"""All monitored tables — high-level inventory."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dq_app.data import adapter
from dq_app.domain import metrics
from dq_app.ui import components, monitoring, theme


def _filter_inventory(inventory: pd.DataFrame) -> pd.DataFrame:
    with st.container(key="monitor_list_controls"):
        q, status, trend = st.columns([2.5, 1.2, 1.2])
        with q:
            term = st.text_input(
                "Search monitors",
                placeholder="Search monitor, catalog item or owner",
                label_visibility="collapsed",
            ).strip().lower()
        with status:
            status_filter = st.selectbox(
                "Status",
                ["All statuses", "Critical", "Needs attention", "Healthy"],
                label_visibility="collapsed",
            )
        with trend:
            trend_filter = st.selectbox(
                "Trend",
                ["All trends", "Flat", "Improving", "Declining"],
                label_visibility="collapsed",
            )

    view = inventory
    if term:
        hay = (
            view[["Monitor", "Catalog item", "Status", "Owner"]]
            .astype(str).agg(" ".join, axis=1).str.lower()
        )
        view = view[hay.str.contains(term, regex=False, na=False)]
    if status_filter != "All statuses":
        view = view[view["Status"] == status_filter]
    if trend_filter == "Flat":
        view = view[view["Trend"] == "Flat"]
    elif trend_filter == "Improving":
        view = view[view["Trend"].str.startswith("+", na=False)]
    elif trend_filter == "Declining":
        view = view[view["Trend"].str.startswith("-", na=False)]
    return view.reset_index(drop=True)


components.page_chrome()

runs = adapter.get_check_runs()
registry = adapter.get_rule_registry_current()

hd, actions = st.columns([4, 1.15], vertical_alignment="center")
with hd:
    st.markdown(
        '<div class="dq-page-hd"><div class="t">All Monitored Tables</div>'
        '<div class="s">Every watched catalog item, with current quality, trend, '
        "findings and rule coverage — counted over the registered critical data "
        "elements.</div></div>",
        unsafe_allow_html=True,
    )

if runs.empty:
    st.caption("No check runs available.")
    st.stop()

scoped, window = monitoring.domain_filter(runs, "monitor_list")
if scoped.empty:
    st.caption(
        "No checks on registered critical data elements in the selected domains. "
        "Unregistered columns may still be checked — those are worked from Cohorts."
    )
    st.stop()

rule_name = registry.set_index("rule_id")["rule_name"].to_dict()
latest_run_id = metrics.latest_run_id(scoped)
last_ts = scoped["run_ts"].max()

with actions:
    export = scoped[scoped["run_id"] == latest_run_id].copy()
    export.insert(0, "rule_name", export["rule_id"].map(rule_name))
    st.download_button(
        "Export monitors",
        data=export.to_csv(index=False).encode(),
        file_name=f"dq-monitors-{last_ts:%Y%m%d}.csv",
        mime="text/csv",
        icon=":material/download:",
        width="stretch",
        help="Every check result from the latest run in the selected domains, as CSV. Scoped to checks on registered critical data elements, like the "
             "page itself.",
    )

theme.section("Monitor inventory")

inventory = monitoring.monitor_inventory(scoped, window)
if inventory.empty:
    st.caption("No monitor results in the selected filters.")
    st.stop()

view = _filter_inventory(inventory)
if view.empty:
    st.caption("No monitors match these filters.")
    st.stop()

saved_table = st.session_state.get("monitors_selected_table")
if saved_table not in set(view["__table"]):
    saved_table = view.iloc[0]["__table"]
    st.session_state["monitors_selected_table"] = saved_table

default_row = int(view.index[view["__table"] == saved_table][0])
selection = st.dataframe(
    view,
    key="monitors_inventory",
    width="stretch",
    height=min(430, 106 + 48 * len(view)),
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row-required",
    selection_default={"selection": {"rows": [default_row]}},
    column_order=[
        "Monitor", "Status", "Overall DQ", "Trend", "Quality over time", "Findings",
        "Breaching", "Rules", "P1", "Evaluated rows", "Owner", "Latest run",
    ],
    column_config={
        "Monitor": st.column_config.TextColumn(width="medium"),
        "Status": st.column_config.TextColumn(width="small"),
        "Overall DQ": st.column_config.ProgressColumn(
            "Overall DQ", min_value=0, max_value=100, format="%.1f%%", width="small"
        ),
        "Trend": st.column_config.TextColumn(
            help="Change in overall DQ since the previous scheduled run."
        ),
        "Quality over time": st.column_config.LineChartColumn(
            "Quality over time", y_min=0, y_max=100, width="medium"
        ),
        "Findings": st.column_config.NumberColumn(format="%d"),
        "Breaching": st.column_config.NumberColumn(format="%d", width="small"),
        "Rules": st.column_config.NumberColumn(format="%d", width="small"),
        "P1": st.column_config.NumberColumn(format="%d", width="small"),
        "Evaluated rows": st.column_config.NumberColumn(format="%d"),
        "Owner": st.column_config.TextColumn(width="medium"),
        "Latest run": st.column_config.DatetimeColumn("Latest run", format="DD MMM HH:mm"),
    },
    lazy=False,
)

selected_rows = list(selection.selection.rows) if selection and selection.selection else []
chosen_table = view.iloc[selected_rows[0]]["__table"] if selected_rows else saved_table
st.session_state["monitors_selected_table"] = chosen_table

footer, action = st.columns([3.2, 1], vertical_alignment="center")
with footer:
    st.caption(f"Showing {len(view)} of {len(inventory)} monitored tables.")
with action:
    if st.button("Open monitor", type="primary", width="stretch",
                 icon=":material/arrow_forward:"):
        st.switch_page("dq_app/ui/pages/monitor_detail.py")

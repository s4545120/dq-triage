"""Rule registry — the rules, their history, and the app's only other write.

Two things worth knowing before reading a number here:

**The registry is append-only and stores no `effective_to`.** A new version is a new
row; the current version is derived at read time. That is why promoting a rule is an
INSERT and why every past version is still here.

**No `rule_expr` on this page has ever been parsed by anything.** Every violation
count in the system came from the fixture's Python evaluators. Until a workspace runs
each expression against the pilot data and the results are diffed against
`results.check_run`, the SQL and the numbers are two independent claims that happen
to agree.
"""

from __future__ import annotations

import streamlit as st

from dq_app.data import adapter
from dq_app.ui import components, theme
from dq_app.ui.components import opt

components.page_chrome()

st.title("Rule registry")

registry = adapter.get_rule_registry()
current = adapter.get_rule_registry_current()
runs = adapter.get_check_runs()

latest_run = runs.loc[runs["run_ts"].idxmax(), "run_id"]
latest = runs[runs["run_id"] == latest_run].set_index("rule_id")

components.kpi_row([
    {"label": "Active", "value": f"{int((current['status'] == 'active').sum())}"},
    {"label": "Shadow", "value": f"{int((current['status'] == 'shadow').sum())}",
     "sub": "evaluated, not raising",
     "help": "A shadow rule runs and records results but does not raise breaches until "
             "it is promoted."},
    {"label": "Tables covered", "value": f"{int(current['target_table'].nunique())}"},
    {"label": "Versions on record", "value": f"{len(registry)}",
     "sub": "append-only history"},
    {"label": "Expressions verified", "value": "0",
     "tone": "critical",
     "sub": f"of {len(current)}",
     "help": "No rule_expr in this registry has been executed. Every count in the app "
             "came from the fixture's Python evaluators. First job with a workspace: "
             "run each expression against the pilot data and diff it against "
             "results.check_run."},
])

# --- Current rules ----------------------------------------------------------
f1, f2, f3 = st.columns([1, 1, 2])
with f1:
    status = st.multiselect("Status", ["active", "shadow"], default=["active", "shadow"])
with f2:
    sev = st.multiselect("Severity", theme.SEVERITY_ORDER, default=theme.SEVERITY_ORDER,
                         format_func=lambda s: theme.SEVERITY_SHORT[s])
with f3:
    search = st.text_input("Search", placeholder="Rule, name, table or column",
                           label_visibility="collapsed")

view = current[current["status"].isin(status) & current["severity"].isin(sev)]
if search:
    hay = (
        view["rule_id"].str.lower() + " " + view["rule_name"].str.lower() + " "
        + view["target_table"].str.lower() + " " + view["target_column"].fillna("").str.lower()
    )
    view = view[hay.str.contains(search.lower(), regex=False)]

display = view.assign(
    Violations=view["rule_id"].map(latest["violation_count"]),
    Run=view["rule_id"].map(latest["status"]),
    Scope=view["scope_filter"].fillna("").ne("").map({True: "scoped", False: "unscoped"}),
    Sev=view["severity"].map(theme.SEVERITY_SHORT),
).rename(columns={
    "rule_id": "Rule", "rule_name": "Name", "target_table": "Table",
    "target_column": "Column", "rule_type": "Type", "status": "Status",
    "fail_threshold_pct": "Limit", "owner_group": "Owner", "rule_version": "Ver",
})

st.dataframe(
    display[["Rule", "Name", "Table", "Column", "Type", "Sev", "Status", "Scope",
             "Violations", "Run", "Limit", "Owner", "Ver"]],
    width="stretch",
    hide_index=True,
    column_config={
        "Violations": st.column_config.NumberColumn(format="%d", help="Latest run."),
        "Limit": st.column_config.NumberColumn(format="%.2f%%"),
        "Scope": st.column_config.TextColumn(
            help="Whether the rule restricts itself to the rows it should apply to. An "
                 "unscoped rule on a table with mixed product lines reports rows that "
                 "are legitimately empty — a rule defect, not a data defect.",
        ),
    },
)

# --- One rule ---------------------------------------------------------------
theme.section("Inspect")
rule_id = st.selectbox("Rule", sorted(current["rule_id"]), key="_rule_pick",
                       label_visibility="collapsed")
versions = registry[registry["rule_id"] == rule_id].sort_values("rule_version")
head = versions.iloc[-1]

c1, c2 = st.columns([3, 2])
with c1:
    st.markdown(f"**{head['rule_name']}**")
    st.markdown(
        theme.severity_badge(head["severity"])
        + " " + theme.badge(head["status"], "success" if head["status"] == "active" else "moderate")
        + " " + theme.badge(head["rule_type"], "neutral"),
        unsafe_allow_html=True,
    )
    st.markdown(
        theme.kv("Target", f"{head['target_table']}.{opt(head['target_column']) or '*'}")
        + theme.kv("Domain", f"{head['business_domain']} · {head['owner_group']}")
        + theme.kv("Source layer", head["source_layer"])
        + theme.kv("Threshold", f"{head['fail_threshold_pct']}%")
        + theme.kv("Scope filter", opt(head["scope_filter"]) or "unscoped — every row"),
        unsafe_allow_html=True,
    )
    st.code(head["rule_expr"], language="sql")
    st.caption("Expression as written — never executed by this repo.")
    if opt(head["note"]):
        st.caption(head["note"])

with c2:
    history = runs[runs["rule_id"] == rule_id].sort_values("run_ts")
    if not history.empty:
        st.line_chart(history.set_index("run_ts")["violation_count"], height=180,
                      color=theme.SERIES[0])
        last = history.iloc[-1]
        st.markdown(
            theme.kv("Latest", f"{int(last['violation_count']):,} of "
                               f"{int(last['rows_scanned']):,} ({last['violation_pct']:.2f}%)")
            + theme.kv("Status", last["status"])
            + theme.kv("Message", opt(last["message"]) or "—"),
            unsafe_allow_html=True,
        )

with st.expander(f"Version history · {len(versions)}"):
    st.dataframe(
        versions[["rule_version", "status", "effective_from", "created_by", "promoted_by",
                  "promoted_at", "fail_threshold_pct", "scope_filter", "note"]],
        width="stretch", hide_index=True,
    )

# --- Promotion: the app's only other write ----------------------------------
theme.section("Promote a shadow rule")
shadow = current[current["status"] == "shadow"]
if shadow.empty:
    st.caption("No shadow rules waiting.")
else:
    st.dataframe(
        shadow[["rule_id", "rule_name", "target_table", "severity", "rule_version", "note"]],
        width="stretch", hide_index=True,
    )
    with st.form("promote", border=False):
        target = st.selectbox("Rule", sorted(shadow["rule_id"]))
        note = st.text_area("Note", placeholder="Why this rule is ready to raise breaches.")
        if st.form_submit_button("Promote to active", type="primary"):
            try:
                adapter.promote_rule(target, note)
                st.rerun()
            except adapter.WriteRejected as exc:
                st.error(str(exc), icon=":material/block:")
    st.caption(
        "Promotion appends a new version; it does not update the shadow row.",
        help="Who may sign off a promotion is an open question in the spec and is "
             "deliberately not resolved in code. The app records who did it; it does "
             "not assert they were entitled to.",
    )

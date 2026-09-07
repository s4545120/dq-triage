"""Critical data elements — what the business registered as mattering, and whether
anything actually checks it.

Every other surface in this app starts from something that broke. This one starts
from something that matters and asks whether anyone is looking, which is the only
way a coverage number means anything: measured against the rule set, coverage is
always 100% by construction.

**Read-only, on purpose.** Registering an element is an append to `config.cde_registry`
and would be a third write for an app whose whole claim is that it makes two. For the
PoC the register is seeded and the app reads it. The write path is small when it is
wanted — the table is append-only and versioned exactly like the rule registry — but
it is a decision about the app's grants, not a UI change, and it has not been taken.

**Nothing here shows a value.** The profile stores masked signatures and counts.
Where an element is PII, shapes seen on fewer than five rows are folded into `<rare>`
before they are stored at all, so this page could not show one if it tried.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dq_app.data import adapter
from dq_app.domain import coverage as coverage_domain
from dq_app.ui import components, theme
from dq_app.ui.components import opt

components.page_chrome()

st.title("Critical data elements")
st.caption(theme.CDE_ONE_LINER)

registry = adapter.get_cde_registry_current()
profiles = adapter.get_cde_profile()
cov = adapter.get_cde_coverage()
rules = adapter.get_rule_registry_current()

if registry.empty:
    st.info("No critical data elements registered.", icon=":material/info:")
    st.stop()

summary = coverage_domain.coverage_summary(cov)

components.kpi_row([
    {"label": "Elements registered", "value": f"{summary['elements']}",
     "sub": f"{summary['bindings']} bound columns"},
    {"label": "Columns covered", "value": f"{summary['covered_pct']:.0f}%",
     "sub": f"{summary['covered']} of {summary['bindings']}",
     "tone": "success" if summary["covered_pct"] >= 80 else "moderate",
     "help": "A column is covered when at least one active rule examines its values — "
             "a format, uniqueness, referential or variance check. Presence checks "
             "alone do not count."},
    {"label": "Gaps on critical/high", "value": f"{summary['critical_gaps']}",
     "tone": "critical" if summary["critical_gaps"] else "success",
     "sub": "elements that matter most"},
    {"label": "Scope mismatches", "value": f"{summary['scope_mismatches']}",
     "tone": "high" if summary["scope_mismatches"] else "success",
     "sub": "rule contradicts the binding",
     "help": "The binding says the column is only populated for certain rows; the "
             "rule measures every row. Those rules report legitimate gaps as defects."},
    {"label": "Never profiled", "value": f"{summary['unprofiled']}",
     "tone": "moderate" if summary["unprofiled"] else "success"},
])

with st.expander("Why the register comes first"):
    st.markdown("""
**Coverage needs a denominator that the rule set does not control.** Ask "what
proportion of our rules pass?" and the answer describes the rules. Ask "what
proportion of the fields we said were critical has anything checking it?" and the
answer describes the business. The second question needs a list written down before
the rules were, which is what this register is.

**Registration is a definition, not a location.** An element is registered with a
business meaning, a data class, a criticality tier and an expected signature. Where
it physically lives is a *binding*, and an element can have several — customer name
lands in three columns here. In the full design, bindings are proposed by a
classification sweep over column names, value signatures and Unity Catalog lineage,
and confirmed by a steward. In this PoC every binding is hand-authored, which is what
`discovered_by = manual` on all of them means.

**Only a registered element is profiled.** The profile job takes its worklist from
this register, so an unregistered column is never described and can never produce a
proposed rule. That ordering is the control: it stops discovery from quietly deciding
what counts as critical.

**Criticality is not severity.** Criticality says how much an element matters and
belongs to the element. Severity says how loudly a check complains and belongs to the
rule. Nothing here adjusts a severity — a check run copies severity verbatim from the
rule registry and no downstream step touches it.
""")

# --- Coverage, worst first --------------------------------------------------
theme.section("Coverage")

gap_rank = {g: i for i, g in enumerate(theme.COVERAGE_GAP_ORDER)}
crit_rank = {c: i for i, c in enumerate(theme.CRITICALITY_ORDER)}
ordered = cov.assign(
    _gap=cov["coverage_gap"].map(gap_rank),
    _crit=cov["criticality"].map(crit_rank),
).sort_values(["_gap", "_crit", "cde_name"])

f1, f2 = st.columns([1, 1])
with f1:
    gaps = st.multiselect(
        "Finding", theme.COVERAGE_GAP_ORDER, default=theme.COVERAGE_GAP_ORDER,
        format_func=lambda g: theme.COVERAGE_GAP_LABEL[g])
with f2:
    crits = st.multiselect(
        "Criticality", theme.CRITICALITY_ORDER, default=theme.CRITICALITY_ORDER,
        format_func=str.title)

view = ordered[ordered["coverage_gap"].isin(gaps) & ordered["criticality"].isin(crits)]

components.summary_table(
    pd.DataFrame({
        "Element": view["cde_name"],
        "Column": view["target_table"].str.split(".").str[-1] + "." + view["target_column"],
        "Criticality": [theme.criticality_badge(c) for c in view["criticality"]],
        "PII": ["yes" if p else "" for p in view["pii"]],
        "Finding": [theme.coverage_badge(g) for g in view["coverage_gap"]],
        "Rules": view["rule_count"],
        "Types": [", ".join(t) if len(t) else "—" for t in view["rule_types"]],
        "Breaching": view["breaching_rule_count"],
        "Rows flagged": view["latest_violation_rows"],
    }),
    raw={"Criticality", "Finding"},
)

findings = view[view["coverage_gap"] != "covered"]
if not findings.empty:
    st.caption(
        f"{len(findings)} of {len(view)} bound columns carry a finding. "
        "A finding is about the rule set, not about the data."
    )

for gap in theme.COVERAGE_GAP_ORDER[:-1]:
    hit = view[view["coverage_gap"] == gap]
    if hit.empty:
        continue
    with st.expander(
            f"{theme.COVERAGE_GAP_LABEL[gap]} · {len(hit)} "
            f"column{'s' if len(hit) != 1 else ''}"):
        st.caption(theme.COVERAGE_GAP_MEANING[gap])
        for _, r in hit.iterrows():
            line = f"**{r['cde_name']}** · `{r['target_column']}`"
            if r["unscoped_rule_ids"]:
                line += (" — unscoped rule"
                         f"{'s' if len(r['unscoped_rule_ids']) != 1 else ''}: "
                         + ", ".join(f"`{x}`" for x in r["unscoped_rule_ids"]))
                if opt(r["expected_scope_filter"]):
                    line += f", binding expects `{r['expected_scope_filter']}`"
            elif r["rule_ids"]:
                line += " — only: " + ", ".join(f"`{x}`" for x in r["rule_ids"])
            st.markdown(line)

# --- One element ------------------------------------------------------------
theme.section("Inspect")

names = registry.sort_values("cde_name")
picked = st.selectbox(
    "Element", names["cde_id"].tolist(),
    format_func=lambda c: names.set_index("cde_id").loc[c, "cde_name"],
    key="_cde_pick", label_visibility="collapsed")
cde = registry.set_index("cde_id").loc[picked]

c1, c2 = st.columns([3, 2])
with c1:
    st.markdown(f"**{cde['cde_name']}**")
    st.markdown(
        theme.criticality_badge(cde["criticality"])
        + " " + theme.badge(cde["data_class"], "neutral")
        + (" " + theme.badge("PII", "info") if cde["pii"] else "")
        + " " + theme.badge(cde["status"], "success"),
        unsafe_allow_html=True,
    )
    st.markdown(cde["definition"])
    st.markdown(
        theme.kv("Business term", opt(cde["business_term"]) or "—")
        + theme.kv("Domain", f"{cde['business_domain']} · {cde['owner_group']}")
        + theme.kv("Registered", f"{cde['effective_from']:%Y-%m-%d} by {opt(cde['registered_by']) or '—'}")
        + theme.kv("Regulatory basis", opt(cde["regulatory_basis"]) or "—"),
        unsafe_allow_html=True,
    )
    if opt(cde["expected_signature"]):
        st.code(cde["expected_signature"], language="regex")
        st.caption("Expected signature — matched against real values by the profile job.")
    else:
        st.caption(
            "No expected signature. A person's name has no shape, and asserting one "
            "is how a data quality rule starts rejecting people.")
    if opt(cde["note"]):
        st.caption(cde["note"])

with c2:
    st.markdown("**Bindings**")
    components.summary_table(pd.DataFrame([
        {
            "Column": f"{b['target_table'].split('.')[-1]}.{b['target_column']}",
            "Scope": opt(b["expected_scope_filter"]) or "all rows",
            "Status": b["binding_status"],
            "Found by": b["discovered_by"],
        }
        for b in cde["bindings"]
    ]))
    populated = [b for b in cde["bindings"] if opt(b["populated_when"])]
    if populated:
        st.caption("Populated when: " + "; ".join(
            f"{b['target_column']} — {b['populated_when']}" for b in populated))

# --- Profile ----------------------------------------------------------------
mine = profiles[profiles["cde_id"] == picked]
if mine.empty:
    st.info("This element has never been profiled.", icon=":material/info:")
else:
    st.markdown("**Profile**")
    for _, pr in mine.iterrows():
        left, right = st.columns([2, 3])
        with left:
            st.markdown(f"`{pr['target_column']}`")
            st.markdown(
                theme.kv("Rows in scope", f"{int(pr['rows_scanned']):,}")
                + theme.kv("Blank", f"{pr['blank_pct']:.2f}%")
                + theme.kv("Distinct", f"{pr['distinct_pct']:.2f}% of populated")
                + theme.kv("Length", f"{opt(pr['min_length'])}–{opt(pr['max_length'])} chars")
                + theme.kv("Sentinels", f"{int(pr['sentinel_count']):,}")
                + theme.kv("Matches signature",
                           "—" if pd.isna(pr["signature_match_pct"])
                           else f"{pr['signature_match_pct']:.2f}%")
                + theme.kv("Distinct shapes", f"{int(pr['signature_count']):,}"),
                unsafe_allow_html=True,
            )
        with right:
            # numpy array from parquet: `or []` would ask for its truth value.
            raw_sigs = pr["top_signatures"]
            sigs = [] if raw_sigs is None else list(raw_sigs)
            if sigs:
                components.summary_table(
                    pd.DataFrame({
                        "Shape": [s["signature"] for s in sigs],
                        "Rows": [int(s["row_count"]) for s in sigs],
                        "Share": [round(float(s["pct"]), 2) for s in sigs],
                    }),
                    bar="Share",
                )
                st.caption(
                    "Masked shapes: digits 9, letters X, whitespace _, punctuation kept. "
                    "A minority shape is usually the defect."
                    + ("  `<rare>` folds every shape seen on fewer than five rows — this "
                       "element is PII and a shape seen once describes one person."
                       if bool(pr["value_stats_withheld"]) else ""))

# --- Rules attached to this element ----------------------------------------
mine_cov = cov[cov["cde_id"] == picked]
attached = sorted({r for ids in mine_cov["rule_ids"] for r in ids})
st.markdown("**Rules covering this element**")
if not attached:
    st.warning(
        "No active rule covers this element. It is registered as "
        f"**{cde['criticality']}** and nothing checks it.",
        icon=":material/warning:")
else:
    show = rules[rules["rule_id"].isin(attached)]
    components.summary_table(pd.DataFrame({
        "Rule": show["rule_id"],
        "Name": show["rule_name"],
        "Type": show["rule_type"],
        "Severity": [theme.severity_text(s) for s in show["severity"]],
        "Scope": [opt(s) or "unscoped — every row" for s in show["scope_filter"]],
        "Linked by": ["element tag" if c == picked else "column match"
                      for c in show["cde_id"]],
    }))
    st.caption(
        "A rule attaches to an element by matching its column, or by naming the "
        "element outright. The second exists for cross-table rules, which carry no "
        "target column and no column join could ever find.")

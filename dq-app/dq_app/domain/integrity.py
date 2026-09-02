"""The control test, in the app.

Python twin of `{catalog}.results.v_disposition_integrity` (`sql/ddl/08_views.sql`).
The view is the definition; this is a copy, kept because an auditor looking at the
register should be able to see the control's result on the same screen as the
register rather than being told to go and run a query.

Every row returned is a **control failure**, not a warning. An empty result is the
only acceptable state. `fixtures/verify.py` runs the same four clauses over the
fixture as a build gate — three copies of one rule is one too many, which is why
both this module and verify.py name the view as the original.
"""

from __future__ import annotations

import pandas as pd

from dq_app.domain.lifecycle import approvals_required

FINDING_HELP = {
    "insufficient_distinct_approvers": (
        "A cohort reached approval on fewer distinct identities than its severity "
        "requires — typically the same person approving twice. The control is on "
        "distinct identities, not row count, which is why adding a third approval "
        "row from an existing approver would not clear it."
    ),
    "executed_without_approval": (
        "Execution was claimed with no approval event before it in the sequence. "
        "The register cannot prevent this — execution happens outside the system — "
        "so detecting it after the fact is the entire control."
    ),
    "identity_not_from_platform": (
        "A human event carries an identity that did not come from the platform's "
        "forwarded token. If identity can be typed, the register is not evidence."
    ),
    "missing_recommended_event": (
        "A cohort exists with no `recommended` event opening its chain, so the "
        "triage job failed part-way. Nothing downstream of it can be trusted."
    ),
}


def check(cohort: pd.DataFrame, disposition: pd.DataFrame) -> pd.DataFrame:
    """Returns one row per control failure. Empty DataFrame means the control passes."""
    findings: list[dict] = []

    # 1. Approved on too few DISTINCT identities.
    approved = disposition[disposition["event_type"] == "approved"]
    if not approved.empty:
        sev = cohort.set_index("cohort_id")["severity"]
        for cid, g in approved.groupby("cohort_id"):
            if cid not in sev.index:
                continue
            need = approvals_required(sev[cid])
            have = g["actor_identity"].nunique()
            if have < need:
                findings.append(
                    {
                        "cohort_id": cid,
                        "finding": "insufficient_distinct_approvers",
                        "detail": f"severity {sev[cid]} requires {need} distinct approvers, "
                        f"found {have} across {len(g)} approval rows",
                    }
                )

    # 2. Execution recorded without a prior approval.
    for cid, g in disposition.groupby("cohort_id"):
        approvals = g[g["event_type"] == "approved"]["event_seq"]
        for _, e in g[g["event_type"] == "executed"].iterrows():
            if not (approvals < e["event_seq"]).any():
                findings.append(
                    {
                        "cohort_id": cid,
                        "finding": "executed_without_approval",
                        "detail": f"executed at {e['event_ts']} with no prior approved event",
                    }
                )

    # 3. A human event whose identity did not come from the platform.
    human = disposition[disposition["event_type"].isin(["reviewed", "approved", "executed"])]
    bad = human[(human["actor_source"] != "obo_user") | human["actor_identity"].isna()]
    for _, r in bad.iterrows():
        findings.append(
            {
                "cohort_id": r["cohort_id"],
                "finding": "identity_not_from_platform",
                "detail": f"{r['event_type']} at seq {r['event_seq']} has "
                f"actor_source = {r['actor_source'] or 'NULL'}",
            }
        )

    # 4. A cohort whose chain was never opened.
    opened = set(disposition.loc[disposition["event_type"] == "recommended", "cohort_id"])
    for cid in cohort.loc[~cohort["cohort_id"].isin(opened), "cohort_id"]:
        findings.append(
            {
                "cohort_id": cid,
                "finding": "missing_recommended_event",
                "detail": "cohort has no recommended event opening its chain",
            }
        )

    return pd.DataFrame(findings, columns=["cohort_id", "finding", "detail"])

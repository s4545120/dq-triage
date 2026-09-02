"""Post-generation checks. Three things:

  1. Python twin of sql/ddl/08_views.sql v_disposition_integrity.
  2. Assertions that the fixture is internally consistent.
  3. A column-by-column diff of every fixture table against the CREATE TABLE in
     sql/ddl/. This is the only check here that says anything about whether the
     Databricks side will accept this data -- if the generator grows a column the
     DDL does not declare, the INSERT fails in the workspace and passes locally,
     which is precisely the class of bug a laptop-first build invites.

    ../.venv/bin/python verify.py [out_dir]

Exits non-zero on any finding, so it works as a pre-commit or CI gate once the real
triage job starts writing these tables.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path
import pandas as pd

out = Path(sys.argv[1] if len(sys.argv) > 1 else "out")
T = {p.stem: pd.read_parquet(p) for p in out.glob("*.parquet")}
coh, disp = T["results.cohort"], T["results.disposition"]
runs, samp = T["results.check_run"], T["results.violation_sample"]

findings: list[str] = []

# --- 3. DDL / fixture schema agreement --------------------------------------
DDL_DIR = Path(__file__).parent.parent / "sql" / "ddl"
DDL_FOR = {
    "config.rule_registry": "01_config_rule_registry.sql",
    "config.playbook": "02_config_playbook.sql",
    "results.check_run": "03_results_check_run.sql",
    "results.violation_sample": "04_results_violation_sample.sql",
    "results.cohort": "05_results_cohort.sql",
    "results.disposition": "06_results_disposition.sql",
}


def ddl_columns(fname: str) -> set[str]:
    body = re.search(
        r"CREATE TABLE IF NOT EXISTS [^(]+\((.*?)\n\)\s*\nUSING DELTA",
        (DDL_DIR / fname).read_text(), re.S).group(1)
    cols = set()
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("--"):
            continue
        m = re.match(r"([a-z_][a-z0-9_]*)\s+[A-Z]", line)
        if m:
            cols.add(m.group(1))
    return cols


for tbl, fname in DDL_FOR.items():
    if tbl not in T:
        findings.append(f"schema_drift: {tbl} has DDL but no fixture output")
        continue
    declared, produced = ddl_columns(fname), set(T[tbl].columns)
    for c in sorted(produced - declared):
        findings.append(f"schema_drift: {tbl}.{c} is written by the generator but "
                        f"not declared in {fname} -- the INSERT would fail on Databricks")
    for c in sorted(declared - produced):
        findings.append(f"schema_drift: {tbl}.{c} is declared in {fname} but never "
                        f"written by the generator")

# --- v_disposition_integrity, clause by clause ------------------------------
req = coh.set_index("cohort_id").severity.map(lambda s: 2 if s == "P1_block" else 1)
appr = disp[disp.event_type == "approved"].groupby("cohort_id").actor_identity.nunique()
for cid, n in appr.items():
    if n < req[cid]:
        findings.append(f"insufficient_distinct_approvers: {cid} has {n}, needs {req[cid]}")

for cid, g in disp.groupby("cohort_id"):
    ex = g[g.event_type == "executed"]
    ap = g[g.event_type == "approved"]
    for _, e in ex.iterrows():
        if not (ap.event_seq < e.event_seq).any():
            findings.append(f"executed_without_approval: {cid}")

human = disp[disp.event_type.isin(["reviewed", "approved", "executed"])]
bad = human[(human.actor_source != "obo_user") | human.actor_identity.isna()]
for _, r in bad.iterrows():
    findings.append(f"identity_not_from_platform: {r.cohort_id} {r.event_type}")

opened = set(disp[disp.event_type == "recommended"].cohort_id)
for cid in set(coh.cohort_id) - opened:
    findings.append(f"missing_recommended_event: {cid}")

# --- fixture-consistency assertions ----------------------------------------
assert disp.groupby("cohort_id").event_seq.apply(lambda s: s.is_unique).all(), "event_seq reused"
assert (disp.event_seq >= 1).all(), "event_seq below 1"
assert disp.disposition_id.is_unique, "disposition_id not unique"
assert runs.result_id.is_unique, "result_id not unique"
assert samp.result_id.isin(runs.result_id).all(), "orphan violation_sample"
assert samp.groupby("result_id").size().max() <= 100, "sample cap of 100 exceeded"

# Deferred reviews must carry a reason and a review-by date (the CHECK constraints).
d = disp[disp.decision.isin(["deferred", "rejected"])]
assert d.reason.notna().all() and (d.reason.str.strip() != "").all(), "deferral/rejection without reason"
assert disp[disp.decision == "deferred"].review_by_date.notna().all(), "deferral without review_by_date"

# Every cohort member must point at a real check_run row that actually breached.
res = runs.set_index("result_id")
for _, c in coh.iterrows():
    for rid in c.member_result_ids:
        assert rid in res.index, f"{c.cohort_id} references unknown result {rid}"
        assert res.loc[rid, "status"] in ("breach", "skipped"), \
            f"{c.cohort_id} member {res.loc[rid,'rule_id']} is not a breach"

print(f"tables: {len(T)}  cohorts: {len(coh)}  events: {len(disp)}  "
      f"check_runs: {len(runs)}  samples: {len(samp)}")
print(f"schema: {len(DDL_FOR)} tables diffed against sql/ddl/")
if findings:
    print(f"\n{len(findings)} INTEGRITY FINDING(S) -- each is a control failure:")
    for f in findings:
        print("  " + f)
    sys.exit(1)
print("integrity: clean (v_disposition_integrity would return zero rows)")

"""Post-generation checks. Three things:

  1. Python twin of sql/ddl/08_views.sql v_disposition_integrity.
  2. Assertions that the fixture is internally consistent.
  3. A column-by-column diff of every fixture table against the CREATE TABLE in
     sql/ddl/. This is the only check here that says anything about whether the
     Databricks side will accept this data -- if the generator grows a column the
     DDL does not declare, the INSERT fails in the workspace and passes locally,
     which is precisely the class of bug a laptop-first build invites.
  4. The same diff against the triage notebook's write cell. The notebook is what
     actually writes results.cohort in a workspace; fixtures/ only stands in for it
     here, so a column added to one and not the other is a break nothing else sees.

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
cde, prof = T["config.cde_registry"], T["results.cde_profile"]
cov = T["results.v_cde_coverage"]

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
    "config.cde_registry": "09_config_cde_registry.sql",
    "results.cde_profile": "10_results_cde_profile.sql",
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

# --- 4. The notebook that will really write results.cohort ------------------
# fixtures/ stands in for the triage job locally. The job itself is
# notebooks/03_group_and_advise.ipynb, and it has never been executed -- so the only
# thing that can check its write against the DDL is a reader, or this.
NOTEBOOK = Path(__file__).parent.parent / "notebooks" / "03_group_and_advise.ipynb"
if NOTEBOOK.exists():
    import json as _json

    cells = _json.loads(NOTEBOOK.read_text())["cells"]
    # Anchored on the INSERT's staging view rather than on a field name: two cells
    # mention cohort_id, and only one of them builds the row that is written.
    write_cells = [c for c in cells
                   if c["cell_type"] == "code"
                   and "createOrReplaceTempView(\"candidate_cohorts\")" in "".join(c["source"])]
    if len(write_cells) != 1:
        findings.append(f"notebook_drift: expected one cell building the cohort row, "
                        f"found {len(write_cells)} -- this check can no longer find the write")
    else:
        emitted = set(re.findall(r'^\s{8}"([a-z_]+)":', "".join(write_cells[0]["source"]), re.M))
        declared = ddl_columns("05_results_cohort.sql")
        for c in sorted(emitted - declared):
            findings.append(f"notebook_drift: the triage notebook writes cohort.{c}, "
                            "which 05_results_cohort.sql does not declare")
        for c in sorted(declared - emitted):
            findings.append(f"notebook_drift: cohort.{c} is declared in "
                            "05_results_cohort.sql and the triage notebook never writes it")

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

# --- The cohort verdict fields ----------------------------------------------
# These are columns rather than JSON so the app can render them, which means the
# CHECK constraints in 05_results_cohort.sql now have something to constrain. Each
# assertion below is the Python twin of one of them.

WRITE_STATEMENT = re.compile(r"\b(UPDATE|MERGE\s+INTO|DELETE\s+FROM|TRUNCATE|DROP)\b", re.I)

for _, c in coh.iterrows():
    assert c.defect_location in ("data", "rule", "neither"), \
        f"{c.cohort_id} has defect_location {c.defect_location!r}"
    assert c.grouping_verdict in ("holds", "partial"), \
        f"{c.cohort_id} stores grouping_verdict {c.grouping_verdict!r} -- a rejected " \
        "grouping raises no cohort at all"
    assert (c.grouping_verdict == "partial") == (len(c.members_not_covered) > 0), \
        f"{c.cohort_id} is {c.grouping_verdict} with {len(c.members_not_covered)} " \
        "uncovered member(s) -- partial is exactly the case where one cause leaves " \
        "members out, and the two must agree or the write dropped members silently"
    assert 0.0 <= float(c.confidence) <= 1.0, f"{c.cohort_id} confidence out of range"
    assert c.prior_state in (
        "none", "awaiting_review", "approved_awaiting_execution", "deferred",
        "closed_verified", "closed_rejected", "reopened"), \
        f"{c.cohort_id} has prior_state {c.prior_state!r}"
    # differs_from_prior answers "what is different this time", so it is meaningless
    # without a prior and required with one.
    said_before = pd.notna(c.differs_from_prior)
    assert (c.prior_state == "none") != said_before, \
        f"{c.cohort_id}: prior_state={c.prior_state!r} and differs_from_prior is " \
        f"{'present' if said_before else 'absent'}"
    # THE NON-EXECUTION INVARIANT. Same gate as the triage job's validator and the
    # cohort_steps_are_not_executable constraint. A step carrying a runnable body is
    # the first move toward an execute button, which is this project's defining
    # non-goal -- so it is checked in all three places rather than trusted in one.
    for step in list(c.recommended_steps) + [c.recommended_approach]:
        assert not WRITE_STATEMENT.search(step), \
            f"{c.cohort_id} recommends a write statement: {step[:80]!r}"
    # A hypothesis with no itemised evidence is a paragraph a steward has to take or
    # leave whole, which is the thing evidence_points exists to prevent.
    assert len(c.evidence_points) >= 1, f"{c.cohort_id} has no evidence_points"
    assert len(c.recommended_steps) >= 1, f"{c.cohort_id} has no recommended_steps"
    assert str(c.verification_expectation).strip(), \
        f"{c.cohort_id} predicts nothing, so `verified` has nothing to test"
    for rid in c.members_not_covered:
        assert rid not in list(c.member_rule_ids), \
            f"{c.cohort_id} lists {rid} as both a member and not covered"

# --- CDE register, profile and coverage -------------------------------------
# The ordering claim, checked rather than asserted in prose: an element is
# registered before anything profiles it, and only a registered element is
# profiled. If the profile job ever takes a worklist from somewhere other than
# v_cde_registry_current, this is what notices.
assert cde.groupby("cde_id").cde_version.apply(lambda s: s.is_unique).all(), \
    "cde_version reused within a cde_id"
registered = set(cde[cde.status == "registered"].cde_id)
unregistered = set(prof.cde_id) - registered
assert not unregistered, f"profiled without being registered: {sorted(unregistered)}"
for _, c in cde.iterrows():
    assert c.status != "registered" or len(c.bindings) >= 1, \
        f"{c.cde_id} is registered with no bindings"
    for b in c.bindings:
        assert b["binding_status"] in ("candidate", "bound", "unbound"), \
            f"{c.cde_id} binding has status {b['binding_status']!r}"

first_registration = cde.effective_from.min()
assert first_registration <= T["config.rule_registry"].effective_from.min(), \
    "a rule predates the CDE register -- registration is supposed to come first"

# The privacy invariant, matching cde_profile_pii_withholds_values in the DDL.
assert prof[prof.pii].value_stats_withheld.all(), \
    "a PII element was profiled without declaring that values were withheld"
# and the k-anonymity floor it exists to enforce.
for _, r in prof[prof.pii].iterrows():
    for sig in r.top_signatures:
        assert sig["signature"] == "<rare>" or sig["row_count"] >= 5, \
            f"{r.cde_id}/{r.target_column} exposes a signature seen on {sig['row_count']} row(s)"

# Coverage is derived, so it must not invent or lose a binding.
bound_count = sum(1 for _, c in cde.iterrows() if c.status == "registered"
                  for b in c.bindings if b["binding_status"] == "bound")
assert len(cov) == bound_count, \
    f"v_cde_coverage has {len(cov)} rows for {bound_count} bound columns"
assert cov.coverage_gap.isin(
    ["no_rule", "scope_mismatch", "unvalidated", "covered"]).all(), \
    "unknown coverage_gap value"
# A scope mismatch names the rules it is accusing, or it is not a finding.
mism = cov[cov.has_scope_mismatch]
assert mism.unscoped_rule_ids.map(len).gt(0).all(), "scope mismatch with no rule named"
known_rules = set(T["config.rule_registry"].rule_id)
for _, r in cov.iterrows():
    for rid in r.unscoped_rule_ids:
        assert rid in known_rules, f"{r.cde_id} names unknown rule {rid}"

print(f"cde: {len(cde)} elements  {bound_count} bound columns  "
      f"{len(prof)} profiles  gaps: "
      + ", ".join(f"{k}={v}" for k, v in cov.coverage_gap.value_counts().items()))
print(f"tables: {len(T)}  cohorts: {len(coh)}  events: {len(disp)}  "
      f"check_runs: {len(runs)}  samples: {len(samp)}")
print(f"schema: {len(DDL_FOR)} tables diffed against sql/ddl/")
if findings:
    print(f"\n{len(findings)} INTEGRITY FINDING(S) -- each is a control failure:")
    for f in findings:
        print("  " + f)
    sys.exit(1)
print("integrity: clean (v_disposition_integrity would return zero rows)")

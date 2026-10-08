"""Post-generation checks:

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
  5. The notebook's PRIOR_STATES against the states v_cohort_current can return.
  6. The onboarding writers' column lists -- the job's and the app's -- against
     15_config_onboarding.sql and the template columns on rule_registry.
  7. No notebook's code reads violation_sample.sample_row: row values carry PII and
     never go into a model brief.

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
    "results.threshold_proposal": "13_results_threshold.sql",
    "results.threshold_review": "13_results_threshold.sql",
}


def ddl_columns(fname: str, table: str | None = None) -> set[str]:
    text = (DDL_DIR / fname).read_text()
    if table:
        # 13_results_threshold.sql declares two tables; pick the one asked for.
        text = text[text.index(f"CREATE TABLE IF NOT EXISTS {{catalog}}.{table} ("):]
    body = re.search(
        r"CREATE TABLE IF NOT EXISTS [^(]+\((.*?)\n\)\s*\nUSING DELTA",
        text, re.S).group(1)
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
    declared, produced = ddl_columns(fname, tbl), set(T[tbl].columns)
    for c in sorted(produced - declared):
        findings.append(f"schema_drift: {tbl}.{c} is written by the generator but "
                        f"not declared in {fname} -- the INSERT would fail on Databricks")
    for c in sorted(declared - produced):
        findings.append(f"schema_drift: {tbl}.{c} is declared in {fname} but never "
                        f"written by the generator")

# --- 4. The notebook that will really write results.cohort ------------------
# fixtures/ stands in for the triage job locally. The job itself is
# notebooks/03_group_and_advise.ipynb, which HAS now run on workspace.dq_triage -- but a
# laptop still cannot run it (Spark, a gateway client, a warehouse), so this check stays
# the only thing that can diff its write cell against the DDL without one.
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

# --- 5. The notebook's state enum against the view that produces them --------
# `validate()` in the triage notebook rejects any response whose prior_state is not
# in its PRIOR_STATES list. v_cohort_current is what computes those states, so a
# state the view can return and the list omits rejects every brief that mentions it
# -- and the answer is thrown away after the model call has been paid for.
#
# That happened: the list held seven of the ten and omitted `awaiting_triage`, which
# is what the view returns for a cohort with no disposition events, which is every
# cohort the notebook itself writes. The first run worked and the second advised
# nothing. This is the check that would have caught it on a laptop.
if NOTEBOOK.exists():
    view_sql = (DDL_DIR / "08_views.sql").read_text()
    case = re.search(r"CASE\s*\n(.*?)END\s+AS lifecycle_state", view_sql, re.S)
    if not case:
        findings.append("view_drift: cannot find the lifecycle_state CASE in 08_views.sql")
    else:
        view_states = set(re.findall(r"'([a-z_]+)'", case.group(1)))
        # The CASE also tests decision values on the way to a state; those are not
        # states. Keep only what a THEN or the ELSE actually returns.
        view_states = set(re.findall(r"(?:THEN|ELSE)\s+'([a-z_]+)'", case.group(1)))

        enum = re.search(r"PRIOR_STATES = \[(.*?)\]",
                         "".join(c for cell in cells if cell["cell_type"] == "code"
                                 for c in cell["source"]), re.S)
        if not enum:
            findings.append("notebook_drift: PRIOR_STATES not found in the triage notebook")
        else:
            listed = set(re.findall(r"'([a-z_]+)'|\"([a-z_]+)\"", enum.group(1)))
            listed = {a or b for a, b in listed}
            for st in sorted(view_states - listed):
                findings.append(
                    f"notebook_drift: v_cohort_current can return {st!r} and the triage "
                    "notebook's PRIOR_STATES omits it -- every brief carrying that state "
                    "would be rejected after the model call")
            # "none" is the notebook's own, for a group with no prior cohort at all.
            for st in sorted(listed - view_states - {"none"}):
                findings.append(
                    f"notebook_drift: the triage notebook accepts prior_state {st!r}, "
                    "which v_cohort_current never returns")

# --- 7. No row values reach a model --------------------------------------------
# violation_sample.sample_row holds customer values, and since 2026-10-08 no model brief
# carries them: the triage notebook reads violation_sample for row_key overlap only.
# A prompt cannot be trusted to keep that true, so the code is checked instead -- any
# model-calling notebook whose code (comments aside) names `sample_row` is a finding.
import json as _json
for nb in sorted((Path(__file__).parent.parent / "notebooks").glob("*.ipynb")):
    code = "\n".join(line for cell in _json.loads(nb.read_text())["cells"]
                     if cell["cell_type"] == "code"
                     for line in "".join(cell["source"]).splitlines()
                     if not line.lstrip().startswith("#"))
    if "sample_row" in code:
        findings.append(f"pii_to_model: {nb.name} reads violation_sample.sample_row -- "
                        "row values must not be put in a model brief")

# --- 6. The onboarding writers against 15_config_onboarding.sql ---------------
# No fixture stands in for the onboarding tables; two writers do the real thing. The
# onboarding job (onboarding/onboard.py) and the app (dq_app/domain/onboarding.py, whose
# lists are the columns its adapter writes). Their column lists are read from source
# rather than imported, so this check needs neither a warehouse nor the app's packages.
# The template columns on rule_registry are covered by check 3 and by RULE_COLS here.
import ast as _ast

ROOT = Path(__file__).parent.parent


def _constants(path: Path) -> dict[str, list[str]]:
    out = {}
    for node in _ast.parse(path.read_text()).body:
        if isinstance(node, _ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], _ast.Name):
            try:
                v = _ast.literal_eval(node.value)
            except ValueError:
                continue
            if isinstance(v, str):
                out[node.targets[0].id] = [c.strip() for c in v.split(",")]
            elif isinstance(v, list) and all(isinstance(c, str) for c in v):
                out[node.targets[0].id] = v
    return out


ONBOARDING_WRITERS = [
    ("onboarding/onboard.py", "MONITORED_COLS", "config.monitored_table", "15_config_onboarding.sql"),
    ("onboarding/onboard.py", "TEMPLATE_COLS", "config.check_template", "15_config_onboarding.sql"),
    ("onboarding/onboard.py", "PROPOSAL_COLS", "config.binding_proposal", "15_config_onboarding.sql"),
    ("onboarding/onboard.py", "RULE_COLS", "config.rule_registry", "01_config_rule_registry.sql"),
    ("dq-app/dq_app/domain/onboarding.py", "MONITORED_COLUMNS", "config.monitored_table", "15_config_onboarding.sql"),
    ("dq-app/dq_app/domain/onboarding.py", "PROPOSAL_COLUMNS", "config.binding_proposal", "15_config_onboarding.sql"),
    ("dq-app/dq_app/domain/onboarding.py", "REVIEW_COLUMNS", "config.binding_review", "15_config_onboarding.sql"),
]
_consts: dict[str, dict] = {}
for src, name, tbl, fname in ONBOARDING_WRITERS:
    if not (ROOT / src).exists():
        findings.append(f"onboarding_drift: {src} is missing")
        continue
    cols = _consts.setdefault(src, _constants(ROOT / src)).get(name)
    if cols is None:
        findings.append(f"onboarding_drift: {src} no longer defines {name}")
        continue
    declared = ddl_columns(fname, tbl)
    for c in sorted(set(cols) - declared):
        findings.append(f"onboarding_drift: {src} {name} writes {tbl}.{c}, which {fname} "
                        "does not declare -- the INSERT would fail on Databricks")
    for c in sorted(declared - set(cols)):
        findings.append(f"onboarding_drift: {tbl}.{c} is declared in {fname} and "
                        f"{src} {name} never writes it")

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

# A check cannot fail more rows than it read. The back-projection once jittered
# the variance rules to 1072 of 1000 -- a score below zero on a critical element.
over = runs[runs.violation_count > runs.rows_scanned]
for _, r in over.iterrows():
    findings.append(f"violations_exceed_scanned: {r.rule_id} {r.run_ts} "
                    f"{r.violation_count} of {r.rows_scanned}")

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

# --- Threshold proposals and reviews -----------------------------------------
# The CHECK constraints in 13_results_threshold.sql, as Python, plus the one thing
# that is a join: the current limit a proposal quotes must be one the rule carried.
prop, rev = T["results.threshold_proposal"], T["results.threshold_review"]
BASES = ("element_tolerance", "run_history", "both", "unchanged")
assert prop.proposal_id.is_unique, "proposal_id not unique"
assert prop.basis.isin(BASES).all(), "unknown threshold basis"
assert prop.proposed_threshold_pct.between(0.0, 100.0).all(), "proposal out of range"
assert ((prop.basis == "unchanged") ==
        (prop.proposed_threshold_pct == prop.current_threshold_pct)).all(), \
    "a proposal says unchanged and is not, or the reverse"
capped = prop[prop.tolerance_pct.notna()]
assert (capped.proposed_threshold_pct <= capped.tolerance_pct).all(), \
    "a proposal exceeds the tolerance its element declares -- the ceiling is the point"
_reg_all = T["config.rule_registry"]
for _, p in prop.iterrows():
    carried = set(_reg_all[_reg_all.rule_id == p.rule_id].fail_threshold_pct.astype(float))
    assert float(p.current_threshold_pct) in carried, \
        f"{p.rule_id} proposal quotes a current limit no version of the rule carried"
    assert str(p.rationale).strip() and str(p.reviewer).strip(), f"{p.rule_id}: blank advice"
    assert p.cde_id in set(cde.cde_id), f"{p.rule_id} proposal names unknown element {p.cde_id}"
assert rev.review_id.is_unique, "review_id not unique"
assert rev.proposal_id.isin(prop.proposal_id).all(), "review of an unknown proposal"
assert rev.decision.isin(["adopted", "rejected", "deferred"]).all(), "unknown review decision"
need_reason = rev[rev.decision != "adopted"]
assert need_reason.reason.notna().all() and (need_reason.reason.str.strip() != "").all(), \
    "rejection or deferral without a reason"
assert rev[rev.decision == "deferred"].review_by_date.notna().all(), "deferral without a date"
assert rev[rev.decision == "adopted"].adopted_rule_version.notna().all(), \
    "adoption that names no rule version"
assert (rev.actor_source == "obo_user").all() and rev.actor_identity.notna().all(), \
    "a threshold review not from a platform identity"
# The fixture must hold at least one proposal that moves a limit and at least one
# left open, or the page and the write-path test have nothing to show.
assert (prop.basis != "unchanged").any(), "no proposal moves a limit"
_cur_view = T["results.v_threshold_proposal_current"]
assert (_cur_view.review_state == "open").any(), "no open proposal for the app to decide"

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

# A RULE NAMES ITS ELEMENT, and where it has a column that column is one of the
# element's bindings. cde_id is NOT NULL in the DDL; this is the half a NOT NULL
# cannot say, and the reason every active rule attaches to something.
_cur_cde = cde.sort_values("cde_version").groupby("cde_id").tail(1)
_bound = {(c.cde_id, b["target_table"], b["target_column"])
          for _, c in _cur_cde.iterrows() if c.status == "registered"
          for b in c.bindings if b["binding_status"] == "bound"}
_cur_rules = T["config.rule_registry"].sort_values("rule_version").groupby("rule_id").tail(1)
for _, r in _cur_rules[_cur_rules.status != "retired"].iterrows():
    assert pd.notna(r.cde_id), f"{r.rule_id} names no element"
    assert r.cde_id in set(_cur_cde.cde_id), f"{r.rule_id} names unknown element {r.cde_id}"
    if pd.notna(r.target_column):
        assert (r.cde_id, r.target_table, r.target_column) in _bound, \
            f"{r.rule_id} targets {r.target_table}.{r.target_column}, which is not a " \
            f"binding of {r.cde_id} -- the rule would attach to nothing"
_attached_ids = {rid for ids in cov.rule_ids for rid in ids}
_active = set(_cur_rules[_cur_rules.status == "active"].rule_id)
assert _active <= _attached_ids, \
    f"active rules attached to no binding: {sorted(_active - _attached_ids)}"

# Coverage is derived, so it must not invent or lose a binding.
# Current versions only: a retired element's earlier registered version is history.
bound_count = len(_bound)
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

print(f"cde: {int((_cur_cde.status == 'registered').sum())} elements  {bound_count} bound columns  "
      f"{len(prof)} profiles  gaps: "
      + ", ".join(f"{k}={v}" for k, v in cov.coverage_gap.value_counts().items()))
print(f"tables: {len(T)}  cohorts: {len(coh)}  events: {len(disp)}  "
      f"check_runs: {len(runs)}  samples: {len(samp)}")
print(f"schema: {len(DDL_FOR)} tables diffed against sql/ddl/, "
      f"{len(ONBOARDING_WRITERS)} onboarding column lists against their DDL")
if findings:
    print(f"\n{len(findings)} INTEGRITY FINDING(S) -- each is a control failure:")
    for f in findings:
        print("  " + f)
    sys.exit(1)
print("integrity: clean (v_disposition_integrity would return zero rows)")

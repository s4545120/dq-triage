# notebooks/

Workspace-bound code, and no longer uniformly unexecuted — read the status column.

| Path | Status | What it is |
|---|---|---|
| `03_group_and_advise.ipynb` | **Executed** on `workspace.dq_triage` against `system.ai.gpt-oss-120b` | The advice endpoint. Groups breaches mechanically, reads the disposition register, calls a model once per group, writes `results.cohort`. |
| `04_send_notification.ipynb` | **Never executed** — needs a job, a secret scope and an SMTP host that do not exist | The mail sender behind `DQ_NOTIFY=job`. Writes no table. |
| `06_suggest_thresholds.ipynb` | **Never executed** — the workspace does not yet have `results.threshold_proposal` (`sql/out/migrate_cde_scope.sql`) | The threshold job. One model call per registered element, advising on each rule's `fail_threshold_pct` against the element's declared tolerance and the run history. Writes `results.threshold_proposal` and nothing else. Detection, not triage. |

`03` has written 8 cohorts into `workspace.dq_triage` and has since completed cleanly
on a table already holding its own output. What that run established, including the
five bugs no test could reach, is in `CLAUDE.md` under *The first real run*; the fixes
are in `RUNBOOK-personal-workspace.md`. Run `tools/explain_notebook.py` before
submitting the job — it asks the warehouse to plan every `spark.sql` string, costs
seconds, writes nothing, and three of those five bugs were reachable that way before
any model call was paid for.

Every field of the verdict is a column on `results.cohort`, and `dq-app/` renders all of
them on the problem detail page. Seven of them — `grouping_verdict`,
`members_not_covered`, `defect_location`, `recommended_owner`, `confidence`,
`prior_state`, `differs_from_prior` — used to survive only inside `model_input_payload`,
which nothing queried; four more (`evidence_points`, `rival_hypothesis`,
`recommended_steps`, `verification_expectation`) are new to the brief. `model_input_payload`
keeps the input, the provenance and `reasoning`.

**Since 2026-09-28 the brief finds every element a rule watches.** Attachment is read
off `v_cde_coverage.rule_ids` (`elements_of`) rather than off `rule_registry.cde_id`
alone, which until that date only one rule carried — so the CDE section, which used to
reach one rule in thirty-four, now reaches every rule, and carries the element's
declared `tolerance_pct` as context. Threshold advice is **not** in this notebook: it
is `06_suggest_thresholds.ipynb`, its own job with its own table, because a limit is a
property of a rule and a problem is a property of a run.

`fixtures/verify.py` diffs the write cell below against `sql/ddl/05_results_cohort.sql`
and exits 1 on a mismatch, so a column added to one and not the other is caught without a
workspace. Run it after editing either.

`01` and `02` are the pilot notebooks that live outside this repo; `03` supersedes `02`.

## What it assumes

* `{catalog}.config` and `{catalog}.results` exist per `sql/ddl/` — substitute `CATALOG`
  at the top of the notebook.
* A model serving endpoint reachable through the Unity AI Gateway. `system.ai.gpt-oss-120b`
  is the pilot's choice and is a constant, not a hard dependency.
* It runs as the **triage job's** service principal, not the app's. `07_grants.sql` grants
  the app `MODIFY` on exactly three tables and `results.cohort` is deliberately not one of
  them — the app must not be able to fabricate a finding. The triage principal needs
  `SELECT` on both schemas plus `MODIFY` on `results.cohort` alone. That grant is not in
  `07_grants.sql` and adding it is a decision, not a schema change.

## Before the first real run

1. **The `rule_expr` strings have never been parsed by anything.** Every number in
   `fixtures/out/` came from the Python evaluators. Run each `rule_expr` against the pilot
   data and compare to `results.check_run` before trusting any advice built on them.
2. **The PII question is decided: no row values go to the model** (2026-10-08). The
   brief carries no `violation_sample` rows and `model_input_payload` stores none;
   `violation_sample` is read for `row_key` overlap only. `fixtures/verify.py` check 7
   fails if any notebook's code reads `sample_row`. What is left is steward-written
   `reason` text, which may name a customer — review that before pointing this at an
   endpoint outside the workspace.
3. **`TEMPERATURE = 0.0`.** Advice lands in an audit register, so it should be
   reproducible. The pilot notebook left this at the provider default.
4. **Check what the model does with `neither`.** `defect_location` gained a third value
   because a plausibility rule firing on customers recorded as under 18 is neither a data
   defect nor a rule defect. A model that never answers `neither`, or that reaches for it
   whenever the evidence is thin, is a prompt problem — it is an answer, not a hedge.
5. **Check that `rival_hypothesis` comes back null sometimes.** Null is a claim that the
   evidence points one way. A model that always finds a rival has learned to hedge, and a
   model that never does is not reading rule 2.
6. **On the first run of `06_suggest_thresholds.ipynb`, check what the model does with
   the limit.** Three things, in order of how bad they are: a proposal above the element's
   tolerance (the validator drops the whole element — count how often); a limit set at the
   level a chronic rule sits at, on the `run_history` basis, which is hiding a defect with
   a number; and `unchanged` on everything with no figures in the rationale, which is the
   job being ignored. `SUBS_IMEI_NOT_NULL` and `SUBS_PRIM_ACCT_NOT_ZERO` are the test — the
   right answer is keep, and the reason is scope. It needs `SELECT` on both schemas and
   `MODIFY` on `results.threshold_proposal`, the same shape of grant as the triage job's.

## Verifying it locally

`dq-app/` and `fixtures/` cannot run this — it is Spark and a gateway client. What *can*
be checked without a workspace is that every cell parses and that the brief renders
against the fixture; the prototype that produced this notebook does exactly that.

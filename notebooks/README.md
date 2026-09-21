# notebooks/

Workspace-bound code. **Never executed** — same status as `sql/ddl/`, for the same
reason: there is no workspace yet.

| Path | What it is |
|---|---|
| `03_group_and_advise.ipynb` | The advice endpoint. Groups breaches mechanically, reads the disposition register, calls a model once per group, writes `results.cohort`. |

Every field of the verdict is a column on `results.cohort`, and `dq-app/` renders all of
them on the problem detail page. Seven of them — `grouping_verdict`,
`members_not_covered`, `defect_location`, `recommended_owner`, `confidence`,
`prior_state`, `differs_from_prior` — used to survive only inside `model_input_payload`,
which nothing queried; four more (`evidence_points`, `rival_hypothesis`,
`recommended_steps`, `verification_expectation`) are new to the brief. `model_input_payload`
keeps the input, the provenance and `reasoning`.

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
  the app `MODIFY` on exactly two tables and `results.cohort` is deliberately not one of
  them — the app must not be able to fabricate a finding. The triage principal needs
  `SELECT` on both schemas plus `MODIFY` on `results.cohort` alone. That grant is not in
  `07_grants.sql` and adding it is a decision, not a schema change.

## Before the first real run

1. **The `rule_expr` strings have never been parsed by anything.** Every number in
   `fixtures/out/` came from the Python evaluators. Run each `rule_expr` against the pilot
   data and compare to `results.check_run` before trusting any advice built on them.
2. **Decide the PII question.** The briefs carry `violation_sample` rows — real email
   addresses, names, dates of birth, service numbers — and steward-written `reason` text
   that may name a customer. A `system.ai.*` endpoint keeps that inside the workspace
   boundary; an external provider does not. `REDACT_PII = True` masks the sample values at
   the cost of the evidence the model reasons from.
3. **`TEMPERATURE = 0.0`.** Advice lands in an audit register, so it should be
   reproducible. The pilot notebook left this at the provider default.
4. **Check what the model does with `neither`.** `defect_location` gained a third value
   because a plausibility rule firing on customers recorded as under 18 is neither a data
   defect nor a rule defect. A model that never answers `neither`, or that reaches for it
   whenever the evidence is thin, is a prompt problem — it is an answer, not a hedge.
5. **Check that `rival_hypothesis` comes back null sometimes.** Null is a claim that the
   evidence points one way. A model that always finds a rival has learned to hedge, and a
   model that never does is not reading rule 2.

## Verifying it locally

`dq-app/` and `fixtures/` cannot run this — it is Spark and a gateway client. What *can*
be checked without a workspace is that every cell parses and that the brief renders
against the fixture; the prototype that produced this notebook does exactly that.

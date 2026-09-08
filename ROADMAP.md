# Roadmap — foundation to cohorts to LLM

Six stages, in dependency order. Each ends at a **gate**: a number or a decision that
says whether to continue. The gates are the point of this document — every one of them
is already computed somewhere in this repo, so no new instrumentation is needed to know
whether to proceed.

**The LLM enters at Stage 5, and there are two insertion points, not one.** Everything
before that is deterministic, and every stage before that is independently useful. If
the model turns out to be mediocre you lose an increment, not the programme.

| Stage | What | LLM | Gate |
|---|---|---|---|
| 1 | Foundation — the DDL runs | No | `sql/VERIFY.md` passes |
| 2 | Rules produce real verdicts | No | `rule_expr` numbers match the fixture |
| 3 | Cohorts form | No | compression ≥ 5:1 |
| 4 | Playbook recommendations | No | the residual is measurable |
| 5a | Root-cause hypothesis | **Yes** | stewards call the hypotheses usable |
| 5b | Remediation advice | **Yes** | backtest beats playbook-only |
| 6 | Retrieval over closed cohorts | Yes | enough closed cohorts to retrieve from |

---

## Stage 1 — Foundation

Run `sql/VERIFY.md` against a sandpit catalog. It creates 3 schemas, 8 tables, 5 views,
4 functions and 23 CHECK constraints, and proves each one bites.

Two things this stage produces that nothing else can:

- **The negative-test output.** Constraints that reject bad rows, and three tables that
  refuse `UPDATE` even for their owner. This is the evidence behind the register's
  claim and it cannot be demonstrated from a laptop.
- **The grant proof queries** from `ddl/07_grants.sql` §3 — in particular 3b returning
  zero rows, which is the headline claim: the app holds nothing outside the `dq`
  catalog.

You will also discover here that the DDL is missing two principals. `07_grants.sql`
covers the app SP, stewards and approvers. The **check runner** and the **triage job**
both write results tables and appear nowhere. That is a real gap, not an oversight to
work around — write their grants, keep them separate, and resist collapsing them into
one principal for convenience. One god-principal demonstrates nothing.

**Gate:** every check in `VERIFY.md` passes, and the output is saved with the control
documentation.

## Stage 2 — Rules produce real verdicts

The check runner writes `results.check_run`. This is the first stage that needs data,
and it settles the repo's oldest open gap: **no `rule_expr` string has ever been parsed
by anything.** Every figure in `fixtures/out/` came from the Python evaluators.

Run each expression **exactly as stored** and diff against
`fixtures/out/results.check_run.parquet`. Where they disagree, resolve it before doing
anything else — the fixture is either validated or invalidated here, and every number
downstream inherits the answer. Regex escaping and NULL semantics are where I would
look first.

Then the rule shapes. Of 35 registry rows, ~25 are row-level predicates that a
`count_if` template handles. The other 10 are not:

| Shape | Rows | Needs |
|---|---|---|
| Window uniqueness | 3 | `OVER (PARTITION BY …)` wrapper |
| Table-level variance | 2 | aggregate over the whole table, `{table}` placeholder |
| Cross-table | 5 | a join the registry does not currently store |

The cross-table five are the open problem. `XREF_NAME_AGREEMENT` has no
`target_column` and references aliases `s.` and `c.` with nothing recording what they
bind to. That is a schema question, and it surfaces here.

**Only after the diff is clean**, introduce the helper functions from
`sql/ddl/12_functions.sql` as new rule versions — 13 rules, all v1→v2 — and prove the
diff is still zero. A refactor that provably changed nothing, on data already
validated. Doing this before the diff merges two experiments and you learn nothing from
either.

Two counts must survive that refactor: `SUBS_IMEI_NOT_NULL` still reports ~700, and
`SUBS_SIM_NOT_NULL` still reports zero. If either moves, the function is wrong, not the
rule. Those two are the worked example behind cohort COH-B and the non-empty
`scope_mismatch` bucket.

**Gate:** every active rule produces a verdict, and any number differing from the
fixture has an explanation.

## Stage 3 — Cohorts, with no model

Group breaches deterministically: same `run_id`, shared lineage ancestor, correlated
onset against rule history, shared `owner_group`. Write `results.cohort` with
`root_cause_hypothesis` NULL and `recommendation_source = 'none'`.

An empty hypothesis column looks like a bug and is not. The grouping has to be proven
before anything explains it, and **grouping should stay deterministic permanently** —
not just at this stage. `member_result_ids` is an audit trail, cohort precision is a
spec metric, and a model that regroups differently on each run makes both
unmeasurable. What a model adds later is the explanation and the ranking, never the
membership.

The triage job also appends the `recommended` event (01) to `results.disposition`. That
is the second writer to that table, alongside the app.

**Gate: compression ≥ 5:1** (breaches ÷ cohorts). Near 1:1 means the grouping is not
working, and no model repairs that — it would only write fluent prose about 30 separate
non-problems.

## Stage 4 — Playbook recommendations, still no model

Resolve `rule_id` match, then `rule_type` match, against `config.playbook`. Rank
candidates by prior use and **downweight high `recurrence_rate`** — the DDL documents
that column as meaning "this approach patches symptoms", which makes it the difference
between a lookup and a recommendation. Everything unmatched stays `'none'`.

This stage is shippable on its own. The register is valuable without advice, and the
spec says so: *"Recommendation can follow one release later."*

**Gate:** you can state what share of cohorts receive a recommendation. In the fixture
it is 4 of 6. In production it could be 80% or 30%, and **that residual is the LLM's
entire job.** Until it is measured, any claim about the model's value is a guess.

## Stage 5a — The LLM's first job is the hypothesis, not the advice

The `cohort_triage` endpoint comes first, because **advice quality is capped by
hypothesis quality.** A wrong hypothesis produces fluent, confident, wrong advice,
which is worse than silence.

It writes `root_cause_hypothesis` and `evidence_summary`, and refines `rank_score`.

Build the input as a view first — `results.v_cohort_context` — assembling the
deterministic signals:

| Signal | Source | Answers |
|---|---|---|
| Profile shape | `cde_profile` — `null_pct`, `blank_pct`, `sentinel_count`, `distinct_pct` | what kind of wrong |
| Onset shape | `check_run` history | step change, drift, always, or spiky |
| Scope mismatch | `v_cde_coverage.unscoped_rule_ids` | is the rule wrong |
| Co-breach pattern | same-run `check_run` | shared upstream, or one table |
| Upstream lineage | Unity Catalog | one cause or several |
| Pipeline run history | Lakeflow | did the load fail |

Read that view yourself before wiring a model to it. If a competent steward could not
recommend an approach from it, neither can a model — and the fix is more signal, not a
bigger prompt.

**Gate:** stewards say the hypotheses are usable. That is a conversation, not a metric,
and it is the right instrument at this stage.

## Stage 5b — Then advice, for the residual only

The `remediation_advice` endpoint fills `recommended_approach` where Stage 4 found
nothing. `ai_query()` from SQL is enough — cohort volume is tens per run, not
thousands, so this is a batch statement in the triage job, not a service.

Four rules:

1. **Structured output**, typed at the SQL level. Never parse free text.
2. **Validate against the enum before writing.** `recommended_approach_type` has a
   CHECK constraint — a hallucinated value does not produce a bad recommendation, it
   aborts the insert and fails the run.
3. **Abstain rather than guess.** `'none'` exists for this. A model that always answers
   trains stewards to stop reading.
4. **Prose, never runnable SQL.** `manual_sql` is a legitimate approach type, so the
   model may say a fix needs hand-written SQL. It must not emit a ready-to-paste
   `UPDATE` — that reintroduces the execute path through a text column, which is the
   programme's defining non-goal.

Turn on **inference tables** on the serving endpoint. They log request and response to
Delta automatically, which lets `model_input_payload` hold a reference rather than a
copy — otherwise the ≤100-row violation samples get duplicated into a permanent audit
table with no retention policy, and pruning samples silently fails to remove them.

Put `prompt_version` and `model_version` inside the payload JSON. No DDL change, and it
is what keeps a six-month-old recommendation explainable.

**Gate:** backtest on held-out closed cohorts beats playbook-only.

## Stage 6 — Retrieval, once there is something to retrieve

Vector Search over closed cohorts **with their outcomes**, in three corpora:

- **verified-closed** — what worked. Positive examples.
- **recurred** — what was tried and came back. Negative examples, and the thing that
  stops the model recommending patches.
- **rejected / `no_action`** — the rule was wrong, not the data. The corpus everyone
  forgets, and the one that stops the model recommending fixes for data that is fine.

This is what makes the system improve without anyone maintaining a playbook — the
disposition register becomes the training corpus, and the playbook shrinks to curated
house policy for cases you want to control tightly.

Needs a real corpus. At 14 cohorts, nearest-neighbour returns noise.

---

## What the LLM never does

Unchanged from the spec and the architecture doc, and worth restating because it is
what keeps the AI layer bounded:

- It never computes pass or fail. That is the check runner, in SQL, deterministically.
- It never decides cohort membership. Deterministic, permanently — see Stage 3.
- It never writes business data, and never triggers a job.
- It never auto-approves. Every output is advice a named human accepts or rejects.
- It sees aggregated results and ≤100-row samples, and nothing else. Raising that cap
  is a governance change, not a config change.

## Measures, and what each is good for

| Measure | Speed | Watch for |
|---|---|---|
| Cohort compression ≥ 5:1 | days | near 1:1 means grouping failed |
| Recommendation coverage | days | defines the LLM's scope |
| Advice followed ≥ 50% | weeks | high can mean good advice **or** passive anchoring |
| MTTR < 5d P1, < 15d P2 | weeks | the queue nobody works |
| Closure rate ≥ 75% | weeks | |
| Recurrence < 10% at 30d | months | **the real one** — patches versus fixes |

If the model's recommendations recur more often than stewards' own choices, it is
suggesting patches. That is the finding worth the whole exercise, and only recurrence
surfaces it.

## Still open, and not resolved by any stage here

- **Ownership of the check runner** is unconfirmed. Stage 2 cannot start without it.
- **Detective versus preventive control** — blocking before any regulated table is
  onboarded. The register is detective by construction.
- **Who may approve**, and whether that set is a governed Databricks group. Until it
  is, the two-approver rule is decorative.
- **`scope_fingerprint`** — how verification scope is pinned so the next run is
  compared like-for-like. NULL everywhere today.
- **Payload egress.** Whether inference may leave the workspace boundary is a
  governance decision, not an engineering one, because the payload includes the one
  accepted PII surface in this design.

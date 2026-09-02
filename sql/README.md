# DDL for the DQ Triage Agent

Schema contracts for `dq-triage-agent-spec.md` v1.0. **This repo owns the SHAPE of
these tables; Databricks owns their CONTENTS.** No data rows are checked in here.

Naming follows the triage spec and its architecture diagram throughout —
`config.rule_registry`, `results.check_run`, severities `P1_block` / `P2_alert` /
`P3_monitor`. There is no second model to reconcile against; this directory is the
source of truth for these six tables.

Nothing in this directory has been executed — there is no workspace connection yet.
It is written to be run as-is once there is one, and reviewed on a laptop before then.

## Running it

Substitute the placeholders, then run in order:

| Placeholder | What it is |
|---|---|
| `{catalog}` | the DQ catalog, default `dq` |
| `{app_sp}` | the app service principal's application id |
| `{steward_group}` | Databricks account group for stewards |
| `{approver_group}` | Databricks account group for approvers — see the open question in `07_grants.sql` |

```bash
for f in sql/ddl/0*.sql; do
  sed -e "s/{catalog}/dq/g" -e "s/{app_sp}/$APP_SP/g" \
      -e "s/{steward_group}/dq-stewards/g" -e "s/{approver_group}/dq-approvers/g" "$f"
done > /tmp/dq_ddl.sql
```

Run `00`–`06` as the catalog owner, `07` as a metastore admin, `08` last.

| File | Table | Written by |
|---|---|---|
| `00_schemas.sql` | catalog + `config` / `results` schemas | — |
| `01_config_rule_registry.sql` | `config.rule_registry` | stewards, via the app (append-only) |
| `02_config_playbook.sql` | `config.playbook` | stewards, out of band |
| `03_results_check_run.sql` | `results.check_run` | check runner |
| `04_results_violation_sample.sql` | `results.violation_sample` | check runner |
| `05_results_cohort.sql` | `results.cohort` | triage job |
| `06_results_disposition.sql` | `results.disposition` | **the app** (append-only) |
| `07_grants.sql` | — | metastore admin |
| `08_views.sql` | three views | — |

## Three decisions worth knowing before you review this

### 1. Unity Catalog has no `INSERT` privilege — the spec's wording needs amending

The spec and architecture doc both say the app service principal is *"granted `INSERT`
on `dq.results` and nothing else"*. There is no such grant. UC's table-level write
privilege is `MODIFY`, and `MODIFY` permits `UPDATE`, `DELETE` and `MERGE` as well.

The intent is achievable, but with two mechanisms rather than one:

- `MODIFY` on exactly two tables, **named individually** — never on the schema, because
  a schema-level grant silently extends to every table added later;
- `delta.appendOnly = true` on both of those tables, which makes `UPDATE` and `DELETE`
  fail for every principal, owner included.

**The headline claim is unaffected.** "The app cannot modify business data" rests on the
*absence* of any grant on `prod.*`, and absence is the strongest form of that argument.
What needed shoring up was the narrower claim that the app can only ever append to its
own register. `07_grants.sql` §3 has the proof queries; run them and keep the output.

Worth correcting the wording in both documents so an auditor is not told something that
`SHOW GRANTS` will contradict.

### 2. Neither app-written table has a status column, and that is the point

`results.disposition` is an event log; `config.rule_registry` is versioned. Where a
cohort has got to, and which version of a rule is live, are **computed at read time** by
`08_views.sql`. There is deliberately no stored `effective_to`, no `current_state`, no
`closed_ts` — writing one would create a second source of truth that can drift from the
event chain, which is the failure the append-only design exists to prevent.

The cost is that `v_cohort_current` carries the whole state machine in one `CASE`
expression. That is the right place for it: one definition, in SQL, that the app reads.
`fixtures/build_fixtures.py` has a Python twin for local use, labelled as the copy.

### 3. The two-approver rule cannot be a table constraint

*"A cohort cannot reach `approved` without the required number of **distinct** approver
identities"* is a property of a **set** of rows. A Delta `CHECK` constraint evaluates one
row at a time and cannot express it — two approval rows carrying the same identity will
insert without complaint.

So enforcement needs both halves, and neither substitutes for the other:

1. **the control** — the approval gate in the app's domain layer, unit-tested, refusing
   to write a second approval from an identity that already approved;
2. **the evidence** — `v_disposition_integrity`, scheduled, alerting on any non-empty
   result.

`fixtures/verify.py --inject-control-failure` exercises (2) against a fixture built with
a deliberate duplicate approver, so the control test is itself tested.

## Status: written, reviewed, never executed

No statement in `sql/ddl/` has been run against Databricks. The only machine check that
has happened is `fixtures/verify.py`, which diffs every `CREATE TABLE` here against the
columns the fixture generator produces — that catches schema drift, and nothing else. It
does not parse SQL and it does not know what Databricks accepts.

Run `00`–`08` in a scratch catalog first. These are the constructs to watch, roughly in
order of how likely they are to need a change:

| Construct | Where | Why it might not work first time |
|---|---|---|
| `CLUSTER BY` (liquid clustering) | every table | Needs DBR 13.3+ and a UC managed table. On an older runtime, swap for `PARTITIONED BY` or drop it — it is a performance choice, nothing depends on it. |
| `ALTER TABLE … ADD CONSTRAINT … CHECK` | 01, 02, 03, 05, 06 | Triggers a Delta writer-protocol upgrade. Fine on an empty table; if a constraint is ever added to a populated table it validates every existing row first. |
| `delta.appendOnly = true` | 01, 06 | Load-bearing — this is the enforcement the grant model cannot express. Confirm with `DESCRIBE DETAIL` after creation; if it did not stick, the audit story is weaker than the README claims. |
| `MAX_BY(x, CASE WHEN … THEN event_seq END)` | 08, `v_cohort_current` | Behaviour when every ordering value is NULL (a cohort with no `reviewed` event) needs confirming. COH-F in the fixture is exactly that case — check it returns NULL rather than erroring. |
| `system.information_schema.schema_privileges` | 07 §3c | Confirm the view exists and is readable by whoever runs the proof queries. |
| `split_part(str, '@', -1)` | 01, `CTCT_EML_DOMAIN_TLD` | Relies on negative `partNum` counting from the end. |
| `SELECT * EXCEPT (rn)` | 08, `v_rule_registry_current` | Databricks-specific syntax. |

### The rule expressions have never been parsed by anything

`config.rule_registry.rule_expr` holds SQL that the check runner will interpolate into a
statement. Those strings were written by hand and **no SQL engine has seen them**. The
numbers in `fixtures/out/` came from the Python evaluators in `rules.py`, which are a
separate implementation of the same intent.

Backslash escaping is the specific thing to test. The stored value for
`CTCT_EML_WHITESPACE` is `EML_ID RLIKE '\\s'` — two literal backslashes, which Spark's
string-literal parser should reduce to `\s` and then read as the whitespace class. That
should be right, but "should" is doing real work in that sentence, and it is wrong in a
direction that fails silently: a mis-escaped regex matches nothing and the rule reports a
clean pass.

**First thing to do with a workspace:** run each `rule_expr` against the pilot data and
check the counts match `fixtures/out/results.check_run.parquet` for the final run. Any
rule where SQL and Python disagree is a bug in one of them, and that comparison is the
cheapest correctness test this project has.

## Not yet decided, and marked in the DDL where it bites

- **`check_run.scope_fingerprint`** is a placeholder for the spec's open engineering
  question about pinning verification scope. The column exists so adding it later is not
  a migration; the hashing rule is undecided, so write `NULL` and let verification fall
  back to matching on `rule_id` + `target_table`.
- **Retention** on `violation_sample` and `disposition` depends on the unanswered question
  of whether the register is formal audit evidence or an internal working record. No
  retention policy is set here.
- **Who may approve** — `{approver_group}` has to exist and have an owner. Until it does,
  the two-approver rule counts distinct identities without anyone having said which
  identities are eligible.
- **Who writes `results.check_run`** — nothing in this repo does. The triage spec lists a
  dependency on "the check runner (Phase 1) producing `check_run` at volume", and cohorts
  cannot form without it: `results.cohort.member_result_ids` points at `check_run` rows.
  `fixtures/` stands in for it locally, which is enough to build and demo the app and not
  enough to run it. Confirm who owns that job before the first workspace deployment.

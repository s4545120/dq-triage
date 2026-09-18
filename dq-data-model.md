# Data model

Eight tables, five views. `dq-architecture-diagram.md` covers layers, identity and
per-surface access; this covers **keys and relationships**, which it doesn't.

Names below are the spec's two-schema layout. The sandpit renders them into one schema
with a prefix (`dq.results.check_run` → `workspace.dq_triage.dq_results_check_run`) —
same model, see `sql/render.py`.

## The shape

```
                        CONFIG — what we intend                RESULTS — what happened
                        ─────────────────────────              ───────────────────────

  cde_registry ..................................................... cde_profile
  PK cde_id + cde_version                                       PK profile_id
  append-only                          ┌── cde_id ──────────────►  FK cde_id
  bindings[] {target_table,            │                           one row per binding
              target_column,           │                           per profile run
              expected_scope_filter}   │
         │                             │
         │ cde_id (nullable)           │
         ▼                             │
  rule_registry ───────────────────────┘
  PK rule_id + rule_version                                        check_run
  append-only — no effective_to,        ── rule_id ────────────►   PK result_id
  current version derived at read          + rule_version          one row per rule
         │                                                         PER RUN
         │ rule_id (nullable)                                           │
         ▼                                                              │ result_id
  playbook                                                              ▼
  PK playbook_id                                                   violation_sample
  matches a rule by rule_id,                                       PK sample_id
  else by rule_type                                                FK result_id
  NO fix_body / fix_sql / job_id                                   ≤100 rows per breach
         │                                                              ▲
         │ playbook_id                                                  │
         │                                                              │
         └──────────────────►  cohort  ◄──── member_result_ids[] ───────┘
                               PK cohort_id
                               member_rule_ids[]  ──► rule_registry
                               ARRAYS, not a bridge table
                               NO status column
                                      │
                                      │ cohort_id
                                      ▼
                               disposition
                               PK disposition_id
                               UK cohort_id + event_seq
                               append-only — THE AUDIT REGISTER
                               recommended → reviewed → approved
                                          → executed → verified → reopened
```

## Four choices that look odd and are not

**Cohort members are arrays, not a bridge table.** `member_rule_ids[]` and
`member_result_ids[]` are `ARRAY<STRING>`. The spec budgets two new tables; a
`cohort_member` bridge would make it three. Arrays are queryable in Delta (`explode`,
`array_contains`) and cohorts are tens of members, not thousands. Revisit only if
members need attributes of their own.

**`cohort` has no status column.** Where a cohort has got to is derived from the
disposition event chain at read time — `v_cohort_current`, and its Python twin
`domain/lifecycle.py`. A status column here would be a second source of truth that can
disagree with the register, which is the failure mode append-only exists to prevent.

**`rule_registry` has no `effective_to`.** It is append-only, so a new version is a new
row with a higher `rule_version`. "Current" is the highest version, derived at read.
Same for `cde_registry`.

**`playbook` has no executable body.** No `fix_body`, `fix_sql`, `job_id` or
`notebook_path`. A body column is the first step towards an execute button, and
execution is the defining non-goal. A playbook entry is an approach and a track record,
nothing more.

## Who writes what

| Table | Written by | Append-only |
|---|---|---|
| `config.cde_registry` | stewards, seeded | ✅ |
| `config.rule_registry` | **the app** — shadow→active promotion only | ✅ |
| `config.playbook` | stewards, seeded | |
| `results.check_run` | the check runner | |
| `results.violation_sample` | the check runner | |
| `results.cde_profile` | the profile job | |
| `results.cohort` | the triage job (notebook 03) | |
| `results.disposition` | **the app** (`reviewed`/`approved`/`executed`) and the check runner (`verified`/`reopened`) | ✅ |

**The app writes exactly two tables**, both `INSERT` only, both `delta.appendOnly`. That
is the whole write surface, and it is enforced by the grant rather than by code —
`sql/ddl/07_grants.sql`, or `sql/grants_sandpit.sql` for the sandpit.

Nothing in this model writes business data. The check runner *reads* the production
tables; nobody here writes them.

## The five views

| View | Derived from | Also computed in Python |
|---|---|---|
| `v_rule_registry_current` | `rule_registry` | — |
| `v_cde_registry_current` | `cde_registry` | — |
| `v_cohort_current` | `cohort` + `disposition` | `domain/lifecycle.py` |
| `v_cde_coverage` | `cde_registry` + `rule_registry` + `check_run` + `cde_profile` | `domain/coverage.py` |
| `v_disposition_integrity` | `disposition` | `domain/integrity.py` |

The last three have Python twins because the app must reflect a session-recorded event
*before* any warehouse could re-run the view. `tests/test_lifecycle_conformance.py` and
`tests/test_coverage_conformance.py` assert the twins reproduce the shipped view output
row for row — change the SQL and those tests tell you whether the copy kept up.

The app queries none of the views. It reads the eight base tables and folds.

## Two join paths worth knowing

**A rule to its critical data element** goes through `rule_registry.cde_id`, never by
matching table and column. `XREF_NAME_AGREEMENT` spans two tables and has no
`target_column`; it attaches only through its `cde_id` tag, so a table/column match
would silently drop it.

**A cohort to its evidence** goes `cohort.member_result_ids[]` → `check_run.result_id` →
`violation_sample.result_id`. Going via `rule_id` instead would pull in every run's
samples, not the run the cohort was raised from.

# Verifying the DDL in a workspace

Companion to `README.md`. That file says what the tables are and why; this one says
how to prove they landed. **Nothing in `ddl/` has ever been executed** — this is the
procedure for the first time it is, and the output of Steps 6 and 9 is the evidence
behind the control claim, so keep it.

Run against a sandpit catalog (`dq_poc`), never `dq`. The real name stays unclaimed
until the shape is proven.

## What "passed" looks like

| | Expected |
|---|---|
| Schemas | 3 — `config`, `results`, `fn` |
| Tables | 8 |
| Views | 5 |
| Functions | 4 |
| CHECK constraints | 23 |
| `delta.appendOnly` tables | 3 |
| Negative tests | all rejected |
| Grant proof queries | as stated in `ddl/07_grants.sql` |

---

## Before you start — two things that will bite

**`ADD CONSTRAINT` is not idempotent.** The tables are `CREATE TABLE IF NOT EXISTS`,
so re-running *looks* safe. It is not: the 23 `ALTER TABLE ... ADD CONSTRAINT`
statements fail on a second pass with "constraint already exists". Run once cleanly,
or drop the catalog and start again. Do not discover this halfway through.

**`CREATE CATALOG` needs metastore-level privilege**, not workspace admin. Confirm it
before you begin, or have the catalog pre-created and skip that statement in `00`.

---

## Step 1 — Substitute and stage

```bash
for f in sql/ddl/*.sql; do
  sed -e "s/{catalog}/dq_poc/g" \
      -e "s/{app_sp}/$APP_SP/g" \
      -e "s/{check_runner_sp}/$RUNNER_SP/g" \
      -e "s/{steward_group}/dq-poc-stewards/g" \
      -e "s/{approver_group}/dq-poc-approvers/g" "$f" > /tmp/ddl_$(basename $f)
done

# Any remaining {placeholder} outside a comment is a substitution you missed.
grep -rn "{[a-z_]*}" /tmp/ddl_*.sql | grep -v -- "--"
```

`12_functions.sql` introduces `{check_runner_sp}`, which `README.md`'s placeholder
table predates. Both the app SP and the check-runner SP must exist before `07` and
`12` respectively.

## Step 2 — Run in dependency order

| Order | Files | Run as |
|---|---|---|
| 1 | `00` | metastore admin — catalog creation |
| 2 | `01`–`06`, `09`, `10` | catalog owner |
| 3 | `12` | catalog owner — `fn` schema and functions |
| 4 | `08`, `11` | catalog owner — views read everything above |
| 5 | `07` | metastore admin — grants |

Views last is the rule that matters: `11_views_cde.sql` reads `cde_registry`,
`cde_profile`, `rule_registry` and `check_run`, so it fails if any is missing.

**Before running, read the constructs table in `README.md` § "Status: written,
reviewed, never executed".** It lists every construct here that might not work first
time — liquid clustering, the `ARRAY<STRUCT<>>` columns, `MAX_BY` over an all-NULL
ordering, `SELECT * EXCEPT`, `LATERAL VIEW explode`, `split_part` with a negative
index — with what to do about each. That table is the pre-flight; this file is the
proof afterwards.

## Step 3 — Inventory

```sql
SELECT table_schema, table_name, table_type
FROM   dq_poc.information_schema.tables
ORDER  BY table_schema, table_name;

SELECT routine_schema, routine_name
FROM   dq_poc.information_schema.routines;
```

Tables (8): `config.rule_registry`, `config.playbook`, `config.cde_registry`,
`results.check_run`, `results.violation_sample`, `results.cohort`,
`results.disposition`, `results.cde_profile`.

Views (5): `config.v_rule_registry_current`, `config.v_cde_registry_current`,
`results.v_cohort_current`, `results.v_disposition_integrity`,
`results.v_cde_coverage`.

Functions (4): `fn.is_blank_v1`, `fn.is_valid_email_v1`, `fn.is_au_mobile_v1`,
`fn.is_sentinel_v1`.

## Step 4 — Constraint inventory: expect 23

```sql
SELECT table_name, constraint_name
FROM   dq_poc.information_schema.check_constraints
ORDER  BY table_name, constraint_name;
```

| Table | Constraints |
|---|---|
| `config.rule_registry` | 3 |
| `config.playbook` | 2 |
| `config.cde_registry` | 4 |
| `results.check_run` | 2 |
| `results.violation_sample` | 0 |
| `results.cohort` | 3 |
| `results.disposition` | 7 |
| `results.cde_profile` | 2 |

`violation_sample` having none is correct, not an omission. A table that is short
means an earlier statement in that file errored without anyone noticing — the
`CREATE TABLE` succeeded and the `ALTER` did not.

## Step 5 — appendOnly on three tables

```sql
DESCRIBE DETAIL dq_poc.config.rule_registry;
DESCRIBE DETAIL dq_poc.config.cde_registry;
DESCRIBE DETAIL dq_poc.results.disposition;
```

Read the `properties` map — all three must carry `delta.appendOnly = true`.

Note this is **three tables, not the two** `07_grants.sql` discusses. That file
counts only the tables the *app* writes; `cde_registry` is append-only for the same
design reason but the app never writes it.

## Step 6 — Negative tests

The step people skip, and the only one that proves anything. A constraint that
exists but does not bite is decoration. **Every statement here must fail.**

```sql
-- severity enum
INSERT INTO dq_poc.results.check_run
  (result_id, run_id, run_ts, rule_id, rule_version, target_table, status, severity)
VALUES ('t','t',current_timestamp(),'t',1,'t','pass','P4_nope');

-- a cohort with no members
INSERT INTO dq_poc.results.cohort
  (cohort_id, raised_run_id, raised_ts, member_result_ids, member_rule_ids,
   member_count, affected_tables, severity, recommendation_source)
VALUES ('t','t',current_timestamp(),array(),array(),0,array(),'P1_block','none');

-- a human event without OBO identity — the control the register rests on
INSERT INTO dq_poc.results.disposition
  (disposition_id, cohort_id, event_seq, event_type, actor_identity,
   actor_source, event_ts, ingest_ts)
VALUES ('t','t',1,'approved','someone@example.com','local_standin',
        current_timestamp(), current_timestamp());

-- a deferral with no reason
INSERT INTO dq_poc.results.disposition
  (disposition_id, cohort_id, event_seq, event_type, decision, reason,
   actor_identity, actor_source, event_ts, ingest_ts)
VALUES ('t2','t',2,'reviewed','deferred',NULL,'s@example.com','obo_user',
        current_timestamp(), current_timestamp());

-- a PII profile that retained values
INSERT INTO dq_poc.results.cde_profile
  (profile_id, profile_run_id, profile_ts, cde_id, cde_version,
   target_table, target_column, pii, value_stats_withheld)
VALUES ('t','t',current_timestamp(),'t',1,'t','t',TRUE,FALSE);
```

Then the append-only test. Insert one **valid** disposition row, then confirm both of
these are rejected — for the table owner too, not just the app SP:

```sql
UPDATE dq_poc.results.disposition SET reason = 'edited' WHERE disposition_id = '<id>';
DELETE FROM dq_poc.results.disposition               WHERE disposition_id = '<id>';
```

Keep this output. It is the evidence behind the register's claim, and it is the one
thing that cannot be demonstrated from a laptop.

## Step 7 — Query every view

`CREATE OR REPLACE VIEW` does not always validate column references at creation
time, so a view can succeed and then fail on first read.

```sql
SELECT * FROM dq_poc.config.v_rule_registry_current  LIMIT 1;
SELECT * FROM dq_poc.config.v_cde_registry_current   LIMIT 1;
SELECT * FROM dq_poc.results.v_cohort_current        LIMIT 1;
SELECT * FROM dq_poc.results.v_disposition_integrity LIMIT 1;
SELECT * FROM dq_poc.results.v_cde_coverage          LIMIT 1;
```

Empty results are fine — this tests that they compile against real column names.
Then diff the column lists against the shipped twins,
`fixtures/out/results.v_cohort_current.parquet` and
`results.v_cde_coverage.parquet`. A name or type mismatch here is exactly what
`fixtures/verify.py`'s schema diff catches locally, and the two must agree.

## Step 8 — Functions, and the NULL behaviour in particular

```sql
SELECT dq_poc.fn.is_blank_v1(NULL)             AS t_blank_null,      -- TRUE
       dq_poc.fn.is_blank_v1('  ')             AS t_blank_ws,        -- TRUE
       dq_poc.fn.is_blank_v1('x')              AS f_blank_value,     -- FALSE
       dq_poc.fn.is_valid_email_v1(NULL)       AS n_email_null,      -- NULL
       dq_poc.fn.is_valid_email_v1('a@b.com')  AS t_email_good,      -- TRUE
       dq_poc.fn.is_valid_email_v1('a@b')      AS f_email_no_tld,    -- FALSE
       dq_poc.fn.is_au_mobile_v1(NULL)         AS n_mobile_null,     -- NULL
       dq_poc.fn.is_au_mobile_v1('0412345678') AS t_mobile_good,     -- TRUE
       dq_poc.fn.is_au_mobile_v1('61412345678')AS f_mobile_intl,     -- FALSE
       dq_poc.fn.is_sentinel_v1('N/A')         AS t_sentinel,        -- TRUE
       dq_poc.fn.is_sentinel_v1(NULL)          AS n_sentinel_null;   -- NULL
```

**The three NULL results are the ones that matter.** If any returns FALSE instead of
NULL, the regex escaping did not survive substitution as intended, and every format
rule's `violation_count` will shift the moment a rule references the function. See
the header of `ddl/12_functions.sql` for why the NULL asymmetry is deliberate.

## Step 9 — Grants proof

`ddl/07_grants.sql` carries queries `3a`–`3e`. Run them and save the output:

| Query | Expected |
|---|---|
| 3a | exactly two rows — app SP writes `disposition` and `rule_registry` |
| 3b | zero rows — nothing outside the catalog. The headline claim |
| 3c | zero rows — no schema-level MODIFY |
| 3d | `appendOnly` true on both app-written tables |
| 3e | no UPDATE / DELETE / MERGE in either table's history |

Plus the query at the foot of `ddl/12_functions.sql`: no principal other than the
schema owner holds anything but `EXECUTE` on `dq_poc.fn`. A `CREATE FUNCTION` or
`MODIFY` grant there means someone can silently change what a historical verdict
meant.

---

## What this does not prove

Passing every step above means the **shape** is right. It says nothing about whether
the numbers are.

Two known gaps remain open after this runbook, both requiring seeded data rather
than empty tables:

- **The `rule_expr` strings have still never been parsed.** Every figure in
  `fixtures/out/` came from the Python evaluators. Running each expression against
  the pilot data and diffing against `results.check_run.parquet` is a separate
  exercise, and it is the one most likely to find something.
- **Ten of the 35 registry rows need execution paths that do not exist** — 3 window
  uniqueness, 2 table-level variance, 5 cross-table. The cross-table five reference
  aliases `s.` and `c.` with nothing in the registry recording what they bind to.

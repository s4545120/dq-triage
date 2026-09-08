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

## Variant: one schema, no catalog or grant privileges

If you can create tables in an existing sandpit schema but cannot create a catalog or
issue grants, most of this runbook still applies. The two schemas collapse into name
prefixes and two files drop out.

### First, probe what you actually have

```sql
SELECT current_catalog(), current_schema();

-- Can you create a view? a function? Run these; both should succeed and are cheap.
CREATE OR REPLACE VIEW  <schema>._probe_v AS SELECT 1 AS x;
CREATE OR REPLACE FUNCTION <schema>._probe_f(a INT) RETURNS INT RETURN a + 1;
DROP VIEW <schema>._probe_v;  DROP FUNCTION <schema>._probe_f;
```

If `CREATE FUNCTION` is refused, skip `12` entirely — the four helpers are additive
and no rule references them yet. If `CREATE VIEW` is refused, you lose Step 7 and with
it the check that `v_cohort_current` and `v_cde_coverage` agree with their Python
twins, which is a real loss but not a blocking one.

### Render the sandpit SQL

`sql/render.py` writes a runnable copy to `sql/out/`. `sql/ddl/` stays the source of
truth and keeps its placeholders — `sql/out/` is generated and gitignored, the same
way `fixtures/out/` is.

```bash
python3 sql/render.py
# or: python3 sql/render.py --catalog c --schema s --prefix dq_
```

Defaults to `sdpt_data_trnf.udp_brnz` with prefix `dq_`. It exits non-zero if any
statement still carries an unsubstituted placeholder, so a clean exit means every
file will parse.

Names become:

```
{catalog}.config.rule_registry  ->  sdpt_data_trnf.udp_brnz.dq_config_rule_registry
{catalog}.results.check_run     ->  sdpt_data_trnf.udp_brnz.dq_results_check_run
{catalog}.fn.is_blank_v1        ->  sdpt_data_trnf.udp_brnz.dq_fn_is_blank_v1
```

`config_` / `results_` / `fn_` are kept rather than flattened away. Nine characters,
and they preserve — in the only place left to preserve it — the split that
`07_grants.sql` argues is what makes the grant model expressible at all. They also
stop these tables colliding with anything else in a shared bronze schema.

Output is renumbered into run order, so run `sql/out/*.sql` in filename order:

| Rendered | From | |
|---|---|---|
| `00`–`07` | `01`–`06`, `09`, `10` | the 8 tables and 23 constraints |
| `08_functions.sql` | `12` | the 4 helpers, minus its schema and grants |
| `09_views.sql`, `10_views_cde.sql` | `08`, `11` | the 5 views, last |

Two files are dropped and the script says so:

- **`00_schemas.sql`** — the schema exists, and `CREATE CATALOG` is out of reach.
- **`07_grants.sql`** — you cannot grant. This one is the control; see below.

Everything else is byte-identical to `sql/ddl/` apart from object names. Columns,
constraints, comments and view bodies are untouched.

### Which checks still work

| Step | Works? | |
|---|---|---|
| 3 — Inventory | Yes | 8 tables, 5 views, 4 functions, one schema |
| 4 — 23 constraints | Yes | unchanged |
| 5 — appendOnly on 3 tables | Yes | a table property, set by whoever creates the table |
| 6 — Negative tests | **Yes** | the most valuable step, fully available |
| 7 — Query every view | Yes, if you can create views | |
| 8 — Functions and NULLs | Yes, if you can create functions | |
| 9 — Grant proofs | **No** | |

Use `<catalog>.information_schema` rather than `system.information_schema` for Steps 3
and 4 — the former is readable with `USE CATALOG`, the latter often is not.

### What this variant does not prove — and it is the important half

**The entire control claim is untestable here.** `07_grants.sql` §3 is the evidence
that the app service principal can write two tables and nothing else, and holds nothing
outside the catalog. Without grant privileges you cannot run it, cannot create the
service principals, and therefore cannot demonstrate the one claim the whole design
makes.

So be precise about what a green run means: **the shape is right and the constraints
bite.** It says nothing about whether the permission model holds. Do not let a
successful sandpit run be reported as "the DDL is verified" without that qualifier —
the grants are not a deployment detail, they are the control.

Two smaller consequences:

- `appendOnly` is testable, so you can still show the register refuses `UPDATE` and
  `DELETE`. That is genuinely half the audit story, and worth capturing.
- The `config` / `results` split becomes cosmetic. `07_grants.sql` argues the split is
  what makes the grant model expressible in two statements rather than ten; flattened,
  that argument is deferred rather than disproved, and must be re-tested when a real
  catalog is available.

Everything in Stage 2 of `ROADMAP.md` — uploading the pilot CSVs, running the
`rule_expr` strings, diffing against the fixture — works fine in this variant, and is
the highest-value thing available to you here.

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

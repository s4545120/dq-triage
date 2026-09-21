# Running this on a personal Databricks workspace

Target: **`workspace.dq_triage`**, prefix `dq_`. Everything under `sql/out/` is rendered
for exactly those names — re-render with `sql/render.py --catalog … --schema …` if you
change them, and re-run `seed.py`, `checkrun.py` and `mocktables.py` with the same
arguments, or the four outputs will disagree with each other.

`sql/VERIFY.md` is the full procedure and its *Variant* section covers this layout.
This file is the short version plus the three things it doesn't cover: the schema
`render.py` drops, the CSV load, and where the notebook fits.

## What this run does and does not prove

**Proves:** the eight tables and 23 constraints are valid Delta DDL; the five views
return what their Python twins return; and — for the first time — that the `rule_expr`
SQL in `config.rule_registry` produces the numbers in `fixtures/out/`. That comparison
has never been made and is the first item under *Known gaps* in `CLAUDE.md`.

**Proves half the control.** `render.py` drops `07_grants.sql`, but the Databricks App
has a service principal of its own, so `sql/grants_sandpit.sql` renders the grant model
for this layout and step 10 issues it: `MODIFY` on exactly two tables, `SELECT` table by
table rather than schema-wide, and `delta.appendOnly` behind both. Its § 4 proof queries
are the evidence.

**Does not prove the human half.** There are no steward or approver groups here, and the
spec's open question — who is authorised to approve — is unanswered. The app can count
two distinct identities; nobody has said which identities are eligible. Until that group
exists and has an owner, the two-approver control is decorative.

## Order

Run each step in a SQL editor or a notebook cell against a SQL warehouse. Everything
is idempotent **except** steps 3 and 7 — see the notes.

### 1 · Create the schema

`render.py` drops `00_schemas.sql` because a sandpit usually cannot create a catalog.
You can create a schema, so:

```sql
CREATE SCHEMA IF NOT EXISTS workspace.dq_triage
  COMMENT 'DQ Triage Agent — sandpit. Two schemas collapsed to one with a dq_ prefix.';
```

### 2 · Probe what you actually have

Cheap, and it tells you which later steps are even available. From `sql/VERIFY.md`:

```sql
CREATE OR REPLACE VIEW workspace.dq_triage.dq_probe_v AS SELECT 1 AS x;
CREATE OR REPLACE FUNCTION workspace.dq_triage.dq_probe_f(a INT) RETURNS INT RETURN a + 1;
```

If `CREATE FUNCTION` is refused, skip banner `[9/11]` in the next step — the four helpers
are additive and no rule references them. If `CREATE VIEW` is refused you lose banners
`[10/11]` and `[11/11]`, and with them the view checks in step 8. Leave both objects in
place until the end so a later failure is unambiguous.

### 3 · Create the tables — `sql/out/ALL.sql`

1,255 lines: eight tables, 23 constraints, four functions, five views, each behind a
numbered banner.

**Run once.** `ADD CONSTRAINT` is not idempotent and a second pass fails on all 23. If it
stops partway, fix that one statement and continue from its banner rather than
restarting. For a safety margin, stop after banner `[8/11]` — all tables and constraints —
confirm, then run `[9/11]`–`[11/11]`.

### 4 · Create and load the two mock source tables — `sql/out/mocktables.sql`

Creates `dq_mock_ctct_c` (36 columns) and `dq_mock_subs_c`, every column `STRING`. That
is deliberate: the fixture reads the CSVs as `dtype=str` with blanks kept as empty
strings, and type inference on load previously made four rules fail the diff for reasons
that were the load, not the rules.

Then load these two files, which are **not in the repo**:

```
~/Downloads/mock_ctct_c_1000 (1).csv   ->  workspace.dq_triage.dq_mock_ctct_c
~/Downloads/mock_subs_c_1000 (1).csv   ->  workspace.dq_triage.dq_mock_subs_c
```

Either `COPY INTO` from a Volume, or the workspace UI's file upload into the table
`mocktables.sql` just created. If you use the UI, check it did not re-infer types — the
target table is already correct, so upload *into the existing table* rather than letting
the UI create one.

Expect 1000 rows each.

### 5 · Seed the config tables — `sql/out/seed.sql`

51 rows: 35 `rule_registry`, 6 `playbook`, 10 `cde_registry`, with `target_table`
rewritten from `prod.customer.*` to the two mock tables. Nothing in `results.*` is
seeded here.

Then `sql/out/verify_seed.sql` — it checks the escaping survived the round trip.

### 6 · The comparison that has never been made — `sql/out/checkrun.sql`

34 queries, each running a rule's real SQL against the mock tables and diffing the count
against the fixture's expected number.

**Expect 34 PASS.** A FAIL here is the finding, not an error to work around: it means the
`rule_expr` stored in the registry does not produce the number every figure in
`fixtures/out/` was built on. Read the verdict column before going further.

### 7 · Load the results tables

In this order — each depends on the last:

| file | what it writes |
|---|---|
| `checkrun_insert.sql` | the 34 verdicts, computed in Databricks. **The first real data in the design.** |
| `samples_insert.sql`  | `violation_sample` — which rows, joined back to the run above |
| `seed_results.sql`    | the 39 days of history, cohorts and the disposition register |

**Run `checkrun_insert.sql` once.** `check_run` is not `appendOnly`, so a second pass
adds a duplicate run rather than failing.

`seed_results.sql` carries its own header on what is real and what is synthetic — read
it before quoting any number from this workspace.

### 8 · Verify — `sql/out/verify_results.sql`

Expected row counts: **1360 / 40 / 1028 / 14 / 65 / 12**.

Checks 4 and 5 are the ones that matter — they exercise `v_cohort_current` and
`v_cde_coverage`, which have never been queried against Unity Catalog data, only against
their parquet twins. The rest is arithmetic.

> This file had no generator and was hand-written against the old sandpit names. It has
> been retargeted to `workspace.dq_triage`, but `render.py` will not maintain it — if you
> re-render for a different target, fix this one by hand or give it a generator.

### 9 · Run the advice endpoint — `notebooks/03_group_and_advise.ipynb`

Import it into the workspace and run top to bottom. It is already set for this layout:

```python
SANDPIT = True
CATALOG, SCHEMA, PREFIX = "workspace", "dq_triage", "dq_"
```

which resolves to `workspace.dq_triage.dq_results_check_run` and so on. Set
`SANDPIT = False` for the spec's two-schema layout.

Notes for a personal workspace:

* `MODEL_NAME = "system.ai.gpt-oss-120b"` — the same endpoint your `02` notebook uses.
* **Blast radius will be empty.** It reads `system.access.table_lineage`, which needs
  system tables enabled. The cell fails soft and prints why, rather than stopping the run.
* **Decide the PII question first.** The briefs carry `violation_sample` rows — real-shaped
  email addresses, names, dates of birth — plus steward-written `reason` text. A
  `system.ai.*` endpoint keeps that inside your workspace. `REDACT_PII = True` masks the
  values at the cost of the evidence the model reasons from.
* It writes only `results.cohort`, by `INSERT`, skipping cohort ids that already exist —
  so re-running it is safe.

### 10 · Grant the app, then deploy it — `sql/grants_sandpit.sql`

The app has its own service principal, so the control `07_grants.sql` describes is
testable here rather than merely asserted. Run `sql/grants_sandpit.sql` in a SQL
editor — 12 grants, table by table rather than schema-wide, for the reason stated at
the head of that file — then its § 4 proof queries and keep the output.

**Until those grants are issued the deployed app will fail every read.** It runs as
its service principal, not as you; running the app locally proves the queries, not
the grant.

```bash
databricks sync dq-app /Users/<you>/dq-triage/dq-app --full
databricks apps start  dq-triage
databricks apps deploy dq-triage \
  --source-code-path /Workspace/Users/<you>/dq-triage/dq-app
```

The app needs the warehouse attached as a resource **named `sql-warehouse`** —
`app.yaml` reads its id through `valueFrom: sql-warehouse`, and an app with no
warehouse attached fails with a readable message from `databricks_source._cursor`
rather than a connection timeout.

To read the same data from a laptop without deploying: `dq-app/run-workspace.sh`.
Reads work, writes are refused — see the header of that script.

### Migrating an existing workspace after a DDL change

`sql/out/*.sql` is `CREATE TABLE IF NOT EXISTS`, so re-running it against a schema
that already exists changes nothing. A column added to `sql/ddl/` needs an `ALTER`:

```sql
ALTER TABLE workspace.dq_triage.dq_results_cohort ADD COLUMNS (…);
ALTER TABLE workspace.dq_triage.dq_results_cohort ADD CONSTRAINT … CHECK (…);
```

Take the column definitions verbatim from the re-rendered `sql/out/` file so the two
cannot drift, and write every new CHECK as `x IS NULL OR …` — rows already in the
table will have NULL in the new column and a constraint they violate is rejected at
`ADD CONSTRAINT` time. Then replace the seeded rows for that table: delete **by
explicit id list**, never an unqualified `DELETE FROM`, and re-insert from the
regenerated `sql/out/seed_results.sql`.

`fixtures/verify.py` check 4 diffs the notebook's write cell against the DDL, so a
column added to one and not the other is caught before you get here.

## If you change the target names

```bash
python3 sql/render.py     --catalog C --schema S --prefix P
python3 sql/seed.py       --catalog C --schema S --prefix P --src-prefix dq_mock_
python3 sql/mocktables.py --catalog C --schema S --src-prefix dq_mock_
python3 sql/checkrun.py   --catalog C --schema S --prefix P --src-prefix dq_mock_
```

Then fix `sql/out/verify_results.sql` by hand and set `CATALOG`/`SCHEMA`/`PREFIX` in the
notebook's config cell. `render.py` exits non-zero if any statement still carries an
unsubstituted placeholder, so a clean exit means every file will parse.

## Known deviations — accepted, not bugs

Recorded 2026-09-18 after the first real run, so they are not rediscovered as defects.

**`XREF_NAME_AGREEMENT` reads 0 where the fixture reads 2.** The CSVs were loaded
through the UI rather than `COPY INTO`, so blank fields landed as `NULL` instead of `''`.
`'' <> 'John'` is TRUE; `NULL <> 'John'` is NULL, so the rule finds nothing. Row counts
are otherwise correct — this is representation, not a load failure. It costs one rule of
34 and shows up in two places: `check_run` (1 row `pass` instead of `breach`) and
`violation_sample` (1026 rows instead of 1028). `sql/out/mocktables.sql` Option A fixes
it whenever that is worth doing; for a POC it is not.

**The latest check run is dated when you ran it**, not 2026-09-02. `checkrun_insert.sql`
stamps `current_timestamp()`. Harmless, but it means the newest run in the workspace and
the newest run in the fixture are different days.

**`check_run.message` is worded differently** between `checkrun_insert.sql` and the
fixture generator. Cosmetic; nothing reads it.

**`results.cohort` has more rows than the fixture** once notebook 03 has run — the
fixture's 14 seeded cohorts plus whatever the notebook raised.

## Running notebook 03 as a job — three bugs it hid, fixed 2026-09-21

The notebook had only ever been run interactively. Submitted as a serverless job it
failed three times before it wrote anything, and each failure was in code no test
could reach. Recorded so they are not rediscovered.

```bash
databricks workspace import /Users/<you>/dq-triage/notebooks/03_group_and_advise \
  --file notebooks/03_group_and_advise.ipynb --format JUPYTER --overwrite
databricks jobs submit --json @job.json --no-wait
```

with `job.json` declaring a serverless environment that installs `openai`, and the
task passing Lakeflow's own run id through as a parameter:

```json
{"tasks": [{"task_key": "advise",
            "notebook_task": {"notebook_path": "/Users/<you>/dq-triage/notebooks/03_group_and_advise",
                              "base_parameters": {"triage_job_run_id": "{{job.run_id}}"}},
            "environment_key": "advise_env"}],
 "environments": [{"environment_key": "advise_env",
                   "spec": {"client": "3", "dependencies": ["openai"]}}]}
```

1. **`currentRunId()` is not whitelisted on serverless or shared access mode.** It
   raises `Py4JSecurityException` on the first cell. The notebook now reads the run
   id from the job parameter above and falls back to the context only when there is
   no parameter.
2. **`LATERAL VIEW` must follow the joins, not precede them.** `FROM c LATERAL VIEW
   explode(…) JOIN v ON …` is a parse error. Check every statement before running
   anything:

   ```bash
   ../.venv/bin/python tools/explain_notebook.py notebooks/03_group_and_advise.ipynb
   ```

   Seconds, no compute, nothing written, and it exits non-zero on the first statement
   that will not run. **Note what it had to learn:** Databricks raises a parse error
   but returns an *analysis* error — an unresolved column, a missing table — as a row
   of plan text. A checker that only catches exceptions reports success on
   `SELECT v.no_such_column`, which is how the verification cell got through two
   rounds of this before the tool inspected the plan itself.
3. **`spark.createDataFrame(rows)` cannot infer a type for a column that is None in
   every row** — `rival_hypothesis` when the model offers no rival — and fails with
   `CANNOT_DETERMINE_TYPE` *after* every model call has been paid for. It now takes
   its schema from `spark.table(COHORT).schema`.
4. **`v_cohort_current` does not carry the verdict columns**, and the verification
   cell selected them from it. It answers where a cohort has got to, which is the
   register's question; the verdict is the cohort's own and lives on the base table.
   The cell joins the two now, which is also what the app does. Do not widen the view
   to make a query convenient — `tests/test_lifecycle_conformance.py` pins its Python
   twin row for row.
5. **The notebook could write exactly once**, and this is the one to remember.
   `validate`'s `PRIOR_STATES` listed six of the ten states `v_cohort_current` can
   return. Among the four missing was `awaiting_triage` — what the view returns for a
   cohort with no disposition events, which is every cohort this notebook writes. Run
   it a second time and each brief carries a prior cohort in state `awaiting_triage`;
   prompt rule 12 says set `prior_state` from the most recent one; the model does; the
   validator rejects it as an invalid enum value. Every brief rejected, every model
   call paid for, nothing written. (`recommended` is an event type, not a state — the
   view never returns it.)

   It surfaced as `CANNOT_INFER_EMPTY_SCHEMA` from the summary cell, which built a
   DataFrame from an empty `advised` — so the visible error had nothing to do with
   the cause and the seven real messages were above it in the loop output. That cell
   now prints `rejected` first and unconditionally.

   **If you add a state to `sql/ddl/08_views.sql`, add it to `PRIOR_STATES` in the
   same change.** A state the view can return and the enum omits rejects every brief
   that mentions it. `fixtures/verify.py` check 5 diffs the two and exits 1 on drift,
   so run it rather than waiting for a run with prior history to tell you.

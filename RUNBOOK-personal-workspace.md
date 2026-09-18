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

**Does not prove the control.** `07_grants.sql` is dropped: a personal workspace has no
service principal and no steward/approver groups, so `MODIFY` on exactly two tables plus
`delta.appendOnly` — the mechanism behind "the app cannot fabricate a finding" — is not
exercised here at all. A green run on this workspace says the shape works. It says
nothing about the grant model.

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

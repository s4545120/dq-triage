# DQ Triage Agent

Cohort triage, recommendation and an audit register on top of an existing DQ detection
stack. Databricks Apps + Streamlit, Unity Catalog, Lakeflow.

- **Spec (authoritative):** `dq-triage-agent-spec.md` v1.0, 2026-09-01
- **Architecture:** `dq-architecture-diagram.md`

**The one claim the whole design makes:** nothing in this system writes business data.
The app's only writes are its own append-only audit register and shadow→active rule
promotion. Production tables are read by the check runner and written by nobody here.
Most of the rules below exist to keep that claim true.

## Current state — read before editing anything

| Path | Status |
|---|---|
| `sql/ddl/` | Current. Written to spec v1.0. **Never executed** — no workspace access yet. |
| `fixtures/` | Current. Local Parquet dataset generated from the pilot CSVs. Verified. |
| `dq-app/` | Current. Rewritten to spec v1.0, runs on the fixture. Never run against a workspace. |

### `dq-app/` was rewritten to v1.0 on 2026-09-02

The v0.1 execution app is gone: `executor.py`, `states.py`, the `incidents` table with
its mutable `state` column, the `fix_registry` with an executable `fix_body`, and the
free-text approver field were all deleted rather than adapted. What survived is what was
worth keeping — the adapter seam, `theme.py`, and the pure-logic-in-`domain/` discipline.

It reads `fixtures/out/*.parquet` through `dq_app/data/local_source.py`, selected by
`DQ_APP_DATA_SOURCE=local` (the default). `databricks_source.py` is rewritten to the v1.0
tables and, like `sql/ddl/`, has never been executed.

```bash
cd dq-app && ../.venv/bin/streamlit run app.py     # local, no workspace
cd dq-app && ../.venv/bin/python -m pytest tests -q
```

**The app's Python copy of `v_cohort_current` is pinned by a test.** `domain/lifecycle.py`
folds the event log into current state because a session-recorded event has to appear in
the queue before any warehouse could re-run the view. `tests/test_lifecycle_conformance.py`
asserts that fold reproduces the shipped `results.v_cohort_current.parquet` row for row.
Change the view in `sql/ddl/08_views.sql` and that test tells you whether the copy kept up.

**Local writes are session-only.** `fixtures/out/` is generated and gated by `verify.py`,
so the app never edits it. Events recorded in the UI live in `st.session_state`.

## Invariants — things that look like bugs and are not

**Execution is the defining non-goal.** No `UPDATE`/`MERGE`/`DELETE` on business data, no
job triggering, no execute button. `config.playbook` deliberately has no `fix_body`,
`fix_sql`, `job_id` or `notebook_path` — a body column is the first step to an execute
button. If someone asks for one, that is a scope change to escalate, not a schema change.

**`results.disposition` is an event log, not a status column.** Append-only, enforced by
`delta.appendOnly = true`. A correction is a new row with a higher `event_seq`, never an
edit. `config.rule_registry` is append-only for the same reason, which is why it has no
stored `effective_to`. Current state for both is derived at read time in
`sql/ddl/08_views.sql` — that view is the single definition; the Python twin in
`fixtures/build_fixtures.py` is labelled as the copy.

**Two rules in `fixtures/rules.py` are deliberately unscoped and must stay broken:**
`SUBS_IMEI_NOT_NULL` and `SUBS_PRIM_ACCT_NOT_ZERO`. They report 700 false breaches (all
Fixed Broadband / prepaid rows that legitimately lack the column). They are the worked
example behind cohort COH-B, whose root cause is a rule defect rather than a data defect.
Their correctly-scoped twins — `SUBS_SIM_NOT_NULL`, `SUBS_BILL_OFFR_NOT_ZERO` — return
zero on the same data. Adding a `scope_filter` to the first pair destroys the demo.

**Nine rules pass and two are in shadow, on purpose.** A fixture where everything breaches
cannot exercise the pass path and leaves closure rate with no denominator.

**Unity Catalog has no `INSERT` privilege.** The spec's wording ("granted `INSERT` on
`dq.results`") is not expressible — `MODIFY` is the finest-grained write privilege and it
permits `UPDATE`/`DELETE` too. The enforceable equivalent is table-level `MODIFY` on
exactly two tables plus `delta.appendOnly`. See `sql/README.md`.

## Commands

Use the project venv — system `python3` has no pandas.

```bash
cd fixtures && ../.venv/bin/python build_fixtures.py && ../.venv/bin/python verify.py
```

`verify.py` must exit 0 after any change to `rules.py`, `build_fixtures.py`, or a
`CREATE TABLE` in `sql/ddl/`. It checks register integrity **and** diffs every fixture
table's columns against the DDL — that diff is what catches a column the generator writes
but the DDL does not declare, which fails in a workspace and passes locally.

```bash
../.venv/bin/python build_fixtures.py --inject-control-failure --out out_bad
../.venv/bin/python verify.py out_bad   # must exit 1
```

## Conventions

- Pilot CSVs live in `~/Downloads` and are **not committed**. Paths are at the top of
  `build_fixtures.py`.
- `fixtures/out/` is generated; do not edit by hand or commit.
- DDL uses `{catalog}` / `{app_sp}` / `{steward_group}` / `{approver_group}` placeholders,
  substituted at run time. This repo owns the *shape* of the tables; Databricks owns their
  *contents* — no data rows are checked in.
- Naming follows the triage spec throughout: `config.rule_registry`, `results.check_run`,
  severities `P1_block` / `P2_alert` / `P3_monitor`. There is no other model to reconcile
  against.

## Known gaps, deliberately unresolved

- **Nothing writes `results.check_run`.** `fixtures/` stands in locally. Ownership of that
  job is unconfirmed and cohorts cannot form without it.
- **The `rule_expr` SQL strings have never been parsed by anything.** Every number in
  `fixtures/out/` came from the Python evaluators. First job with a workspace: run each
  `rule_expr` against the pilot data and compare to `results.check_run.parquet`.
- `check_run.scope_fingerprint` is `NULL` everywhere — the spec's open question on pinning
  verification scope.
- Detective vs preventive control, retention, and who may approve are open questions in
  the spec. Do not resolve them in code.

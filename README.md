# DQ Triage Agent

Cohort triage, recommendation and an audit register on top of an existing data-quality
detection stack. Databricks Apps + Streamlit, Unity Catalog, Lakeflow.

Detection stops at a ticket. Stewards then diagnose ad hoc, fix things off-platform,
and no record survives of what was wrong, what was done, or whether it worked. Two
costs follow: the same problem gets re-diagnosed every time it recurs, and nobody can
answer *"is data quality actually improving?"* — because detection metrics measure how
much we found, not how much got resolved.

This closes that gap without touching the data.

**The one claim the whole design makes: nothing here writes business data.** The app's
only writes are its own append-only audit register and shadow→active rule promotion.
Production tables are read by the check runner and written by nobody in this repo. Most
of the design exists to keep that claim true — and it is enforced by Unity Catalog
grants, not by code review.

## Layout

| Path | What it is | Status |
|---|---|---|
| [`dq-triage-agent-spec.md`](dq-triage-agent-spec.md) | The authoritative spec, v1.0 | Current |
| [`dq-architecture-diagram.md`](dq-architecture-diagram.md) | How the pieces fit together | Current |
| [`sql/`](sql/) | Unity Catalog DDL, grants and views | Written and reviewed, **never executed** — no workspace access yet |
| [`fixtures/`](fixtures/) | A complete local `dq.*` dataset generated from the pilot CSVs | Current, verified |
| [`dq-app/`](dq-app/) | The Streamlit app, built to spec v1.0 | Runs locally on the fixture; never run against a workspace |

## Running it

Nothing here needs a Databricks workspace, a network, or credentials.

```bash
python3 -m venv .venv && .venv/bin/pip install -r dq-app/requirements.txt
```

Build the local dataset from the pilot CSVs, then check it:

```bash
cd fixtures && ../.venv/bin/python build_fixtures.py && ../.venv/bin/python verify.py
```

Run the app:

```bash
cd dq-app && ../.venv/bin/streamlit run app.py
```

Run the tests — pure logic, page renders, and the register write path:

```bash
cd dq-app && ../.venv/bin/python -m pytest tests -q
```

## Three things worth knowing before reading the code

**Current state is derived, never stored.** `results.disposition` is an append-only
event log with no status column, and `config.rule_registry` is append-only with no
stored `effective_to`. A correction is a new row with a higher sequence number, never
an edit. [`sql/ddl/08_views.sql`](sql/ddl/08_views.sql) is the single definition of
that derivation; the Python twin in `dq-app/dq_app/domain/lifecycle.py` is a labelled
copy, pinned to it by a conformance test that compares the two row for row.

**Execution is the defining non-goal.** No `UPDATE`, `MERGE` or `DELETE` on business
data, no job triggering, no execute button. `config.playbook` deliberately has no
`fix_body`, `fix_sql`, `job_id` or `notebook_path` — a body column is the first step to
an execute button. Approval *for* execution is fully in scope and recorded as a
first-class event; the system performing the execution is not.

**The register is a detective control, not a preventive one.** It records that named
people approved and that someone reported executing. It cannot prevent execution
without approval, nor prove that what ran matched what was approved — execution happens
outside the system by design. Preventive enforcement for regulated data has to live in
change management, pipeline CI and production grants. See the open questions in the spec.

## Known gaps, deliberately unresolved

- **Nothing writes `results.check_run` yet.** `fixtures/` stands in locally. Ownership
  of that job is unconfirmed, and cohorts cannot form without it.
- **The `rule_expr` SQL strings have never been parsed by anything.** Every number in
  the app came from the fixture's Python evaluators. First job with a workspace: run
  each expression against the pilot data and diff it against `results.check_run`.
- **Violation samples do not line up with cohorts.** The runner sampled only the final
  run, while each cohort's `member_result_ids` point at the run that raised it — so no
  cohort carries evidence rows from its own raising run. The app says so on screen
  rather than substituting silently; the fix belongs in the sampling.
- `check_run.scope_fingerprint` is `NULL` everywhere — the spec's open question about
  pinning verification scope.
- Detective vs preventive control, retention, and who may approve are open questions in
  the spec, and are not resolved in code.

## Data

The pilot CSVs are **not in this repo** and are not committed. Paths are at the top of
`fixtures/build_fixtures.py`. `fixtures/out/` is generated output and is gitignored —
no data rows are checked in anywhere. This repo owns the *shape* of the tables;
Databricks owns their *contents*.

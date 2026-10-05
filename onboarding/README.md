# Onboarding test

Onboards source tables end to end in a disposable schema, `workspace.dq_onboard`.
Nothing here writes to `dq_triage`. `DROP SCHEMA workspace.dq_onboard CASCADE` resets it.

The tables are the repo's DDL since 2026-10-06 — `sql/ddl/15_config_onboarding.sql`,
`16_views_onboarding.sql` and the template columns in `01` — and `onboard.py setup`
renders and runs them (it needs `sql/` beside this folder, so it runs from a laptop,
not from the jobs' copy). `fixtures/verify.py` diffs every column list this folder and
the app write against that DDL.

| Step | Who | Command |
|---|---|---|
| Set up schema, clones, the onboarding DDL, mock table, UC tags | job | `onboard.py setup` (idempotent) |
| The onboarding DDL and templates on a real schema | job | `onboard.py --schema dq_triage install` |
| Select every table already carrying an active rule | job | `onboard.py --schema dq_triage adopt` |
| Propose bindings from UC tags and value patterns | job | `onboard.py discover` |
| **Approve or reject the proposals** | **person** | `review.sql` step 1 |
| Write approved bindings into the element register | job | `onboard.py apply` |
| Generate shadow rules from templates | job | `onboard.py generate` |
| Run the checks (real serverless job) | job | `onboard.py run` |
| **Promote the table's rules** | **person** | `review.sql` step 2 |
| Run again; breaches now count | job | `onboard.py run` |
| Where the table has got to | — | `onboard.py status` |

Run from this folder with `../.venv/bin/python`.

## What it adds

- `config.monitored_table`: which tables are selected, with row key and owner. Stage is
  derived by `v_onboarding_status`, never stored.
- `config.check_template`: 15 templates lifted from registered rules. `templates.py`
  proves each one reproduces its source rule on its source column.
- `config.binding_proposal` + `binding_review`: a job proposes, a person decides.
- `template_id` / `template_version` on `config.rule_registry`.
- `jobs/run_checks.py`: table selection, a row key per table, and one failing table no
  longer stops the run.

## Simplified review

Two SQL appends, each signed with `current_user()`: a review row per binding, and a new
`rule_version` per promoted rule. Only the apply job writes `cde_registry`, one version
per element per run, so two reviewers can't collide on a version number.

## The mock table

`mock_lead.py` lists every column, the discovery path it exercises, and every planted
defect with its count. The first check run should find each of them.

## The jobs (since 2026-10-05)

Two jobs, split by what their results can do:

| Job | Runs | Does | Can raise a problem? |
|---|---|---|---|
| `dq-onboard steps` (172834918560011) | When `dq_config_monitored_table` or `dq_config_binding_review` changes (table-update trigger; settles 61 s) | `onboard.py steps`: discover, apply approved bindings, generate shadow checks, measure only new shadow checks (`run_checks.py --shadow-only`) | No: everything it writes is shadow or config |
| `dq-checks` (851061192655949) | Daily 03:00 Australia/Sydney | `run_checks.py` on every selected table | Yes: the only source of active results |

So a table goes: submit → proposals within minutes → review → shadow numbers within minutes
→ promote → live from the next 03:00 run. The app triggers neither job; they watch the
tables. Pause either from Jobs & Pipelines.

### In `dq_triage` (since 2026-10-06)

The same two jobs with `--schema dq_triage`: `dq-triage onboard steps` (906515649279596)
and `dq-triage checks` (568071030107709, daily 03:00). Every step takes `--schema`;
the default is `dq_onboard`.

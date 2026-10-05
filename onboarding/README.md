# Onboarding test

Onboards one mock source table end to end in a disposable schema,
`workspace.dq_onboard`, to try the scale-out design before any of it reaches
`sql/ddl/`. Nothing here writes to `dq_triage`. `DROP SCHEMA workspace.dq_onboard
CASCADE` resets it.

| Step | Who | Command |
|---|---|---|
| Set up schema, clones, new tables, mock table, UC tags | job | `onboard.py setup` |
| Propose bindings from UC tags and value patterns | job | `onboard.py discover` |
| **Approve or reject the proposals** | **person** | `review.sql` step 1 |
| Write approved bindings into the element register | job | `onboard.py apply` |
| Generate shadow rules from templates | job | `onboard.py generate` |
| Run the checks (real serverless job) | job | `onboard.py run` |
| **Promote the table's rules** | **person** | `review.sql` step 2 |
| Run again; breaches now count | job | `onboard.py run` |
| Where the table has got to | — | `onboard.py status` |

Run from this folder with `../.venv/bin/python`.

## What it prototypes

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

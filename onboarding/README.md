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
| **Propose an element; a second person approves** | **person** | the app's Elements page |
| Write approved element changes into the register | job | `onboard.py apply_elements` |
| Propose bindings from UC tags and value patterns | job | `onboard.py discover` |
| **Approve or reject the proposals** | **person** | `review.sql` step 1 |
| Write approved bindings into the element register | job | `onboard.py apply` |
| Generate shadow rules from templates | job | `onboard.py generate` |
| Run the checks (real serverless job) | job | `onboard.py run` |
| **Promote the table's rules** | **person** | `review.sql` step 2 |
| Run again; breaches now count | job | `onboard.py run` |
| Where the table has got to | — | `onboard.py status` |

**Slices** (2026-10-06) are set in the app, on the table's onboarding page, never here.
`install` adds their seven `monitored_table` and three `check_run` columns to a schema
that predates them; `run_checks.py` applies a selected table's slice to every check.

Run from this folder with `../.venv/bin/python`.

## What it adds

- `config.monitored_table`: which tables are selected, with row key and owner. Stage is
  derived by `v_onboarding_status`, never stored.
- `config.check_template`: 17 templates lifted from registered rules. `templates.py`
  proves each one reproduces its source rule on its source column. One of them,
  `TPL_PATTERN` (2026-10-08), is not tied to a class: it checks a value against its
  element's own `expected_signature`, and is generated only where the element declares
  one and its class has no format check lifted from the migration queries (email,
  phone, name structure, ID numeric), and only for elements in `CONFIRMED_SIGNATURES` --
  the four the migration queries cover. Every other signature was profiled from pilot
  data. All four have a format check of their own, so today it generates for none of
  them; it is the mechanism for the next element whose signature is confirmed.
- **Date formats are the column's.** The DOB templates carry a `{datefmt}` slot instead
  of the mock table's `yyyy-MM-dd HH:mm:ss`. `generate` measures each STRING DOB column
  against 13 candidate formats in one aggregate (`date_format_probe`) and takes the best
  one if at least 95% of values parse and no format with the fields in a different order
  also does. Ambiguous day/month, or nothing over 95%, means no date check, and the run
  says why. A DATE or TIMESTAMP column is checked through `date_format(col, ...)`, and
  gets no parse check. `TPL_DOB_PARSEABLE` (lifted from `CTCT_BRTH_PARSEABLE`) is the
  class's format check. A generated rule is written again, in shadow, whenever its
  expression or scope would come out different (`templates.restated`), and never just
  because a template's version moved.
- `config.binding_proposal` + `binding_review`: a job proposes, a person decides.
- `template_id` / `template_version` on `config.rule_registry`.
- `jobs/run_checks.py`: table selection, a row key per table, and one failing table no
  longer stops the run.

## Elements (2026-10-08)

`sql/ddl/17_config_cde_onboarding.sql` and `18_views_cde_onboarding.sql`. A person
proposes to register, amend or retire an element (`config.cde_proposal`), a second
person decides (`config.cde_review`), and `apply_elements` -- first in `steps` and
`pipeline` -- writes the change onto `cde_registry`. `elements.py` is what it refuses:
an id ever used before, an amendment or retirement written against attributes that have
changed since, an amendment that changes nothing or reclasses a bound element, and an
unmarked self-approval. The app's twin (`dq_app/domain/elements.refusal`) tells the
reviewer the same before they approve.

* **A new element lands as status `proposed`, with no binding**, because 09 refuses a
  `registered` row with none. Discovery reads `proposed` elements too; the first applied
  binding moves the element to `registered`, and unbinding its last column (decommission,
  exclusion) moves it back. Before this, unbinding an element's only column would have
  hit that constraint.
* **Retiring takes the element's rules with it**: `retire_rules_of_retired_elements`
  writes a retired version of every rule still naming a retired element, as a separate
  pass so a run that fails between the two writes finishes on the next.
* Each version written starts its note with `[cde_proposal <id>]`;
  `v_cde_proposal_current` reads that back as `applied`.
* `install` creates both tables and the view. The app needs `MODIFY` on the two
  tables (07_grants.sql), granted in **no** schema yet, and the steps job needs
  `cde_review` added to its table-update trigger (done in `resources/dq_jobs.yml`, not
  on the live jobs).

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
the default is `dq_onboard`. `--catalog` (default `workspace`) and `--fn-prefix` (default
`<catalog>.dq_triage.dq_fn_`, where the shared helpers live) point the same code
somewhere else; both are read when a name is built, as `--schema` is.

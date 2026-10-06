# The jobs bundle — DRAFT, never deployed

`databricks.yml` + `resources/dq_jobs.yml` define the two jobs that run today by hand:

| Bundle key | Replaces (triage target) | Replaces (onboard target) |
|---|---|---|
| `onboard_steps` | `dq-triage onboard steps` 906515649279596 | `dq-onboard steps` 172834918560011 |
| `checks` | `dq-triage checks` 568071030107709 | `dq-checks` 851061192655949 |

What changes compared with the jobs as they are:

* **Who it runs as.** A service principal (`var.job_sp`), not `lijinrui46@gmail.com`.
* **Where the code comes from.** Git, synced to the deployer's home, not files copied by
  hand into a personal folder.
* **Failures are reported.** A failure or slow run emails `var.alert_email`. The steps
  job now times out at 30 min (warning at 10 min) and the checks job at 2 h (warning at
  1 h). Before this, neither had any limit.

Trigger, schedule, queueing and parameters are the same as before.
`databricks bundle validate -t triage` passes with placeholder values.

## Before the first deploy (someone else's step)

1. **An admin creates the job principal**, e.g. `dq-jobs`. Do not reuse the app's
   principal (`fa379f33-…`): its grants are exactly the app's six appends.
2. **The deployer gets the *Service Principal User* role on it**, or `run_as` is refused.
   Ideally the deployer is the principal itself, from CI, so `var.root` lands in the
   principal's home and no person can edit what runs.
3. **Run `grants_job_sp.sql`**, rendered for the schema. That's five `MODIFY`s, all on
   append-only tables, plus `SELECT` on the schema and `EXECUTE` on the helper functions.
   For a real estate, also grant `SELECT` on every source schema in scope (see the file).

## Cutover: bind, don't duplicate

Two steps jobs on one trigger would both run `discover`, and each would append the same
proposal to an append-only table. **Bind the bundle to the existing jobs** so the deploy
updates them in place and keeps their run history:

```bash
databricks bundle deployment bind onboard_steps 906515649279596 -t triage
```

```bash
databricks bundle deployment bind checks 568071030107709 -t triage
```

Then deploy with the trigger and schedule paused (the defaults). Run each job once by
hand, which proves the principal's grants, then deploy unpaused:

```bash
databricks bundle deploy -t triage --var job_sp=<app-id> --var alert_email=<group-mailbox>
```

```bash
databricks bundle run onboard_steps -t triage --var job_sp=<app-id> --var alert_email=<group-mailbox>
```

```bash
databricks bundle deploy -t triage --var job_sp=<app-id> --var alert_email=<group-mailbox> --var steps_trigger=UNPAUSED --var checks_schedule=UNPAUSED
```

While the trigger is paused, a Submit or binding decision in the app may not start a run
when the trigger resumes. Run `onboard_steps` by hand once afterwards; every step is
idempotent, so an extra run does nothing. Once both targets are moved,
`/Workspace/Users/lijinrui46@gmail.com/dq-onboard-jobs` can be removed.

## Not yet ready for a company workspace

* **One schema, sandpit layout.** Both jobs take `--catalog` and `--fn-prefix` (since
  2026-10-06 for `onboard.py`), but both build table names as
  `<catalog>.<schema>.dq_<group>_<table>`. The spec's two-schema layout
  (`dq.config` / `dq.results`) is not supported, so a `prod` target means one schema laid
  out the sandpit's way. That's why the `prod` block in `databricks.yml` is commented out.
* **What the app offers and what the job can read are different sets.** The Add tables
  page lists what the *app's* principal can see. The job can only check what the *job's*
  principal can read. Until the two match, a table can be selected in the app and then
  fail in the job, and the failure email is the only sign.
* The checks job retries once after 10 min. A retry after a partial write is safe in the
  reading, because a second run on the same day replaces the first (`metrics.scheduled_runs`).
  It still leaves the partial run's rows in `check_run`.

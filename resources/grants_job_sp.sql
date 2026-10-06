-- Grants for the JOB service principal -- DRAFT, never run.
--
-- 07_grants.sql grants the APP principal and says, at line 90, that the onboarding job
-- and the check runner "run as their own job identity ... those grants belong to the
-- job's owner and are not made here". This is that file. Until now the jobs ran as a
-- person whose ownership of the schema covered all of it.
--
-- Placeholders: {catalog} {schema} {job_sp} (application id, in backticks). For the
-- onboard target, {fn_schema} is dq_triage: dq_onboard calls dq_triage's helpers rather
-- than cloning them. For dq_triage itself, {fn_schema} = {schema}.
--
-- Five MODIFYs, every one on an appendOnly table -- the jobs, like the app, only append.
-- The two tables that trigger the steps job (monitored_table, binding_review) get
-- SELECT only: a job able to write its own trigger tables could re-trigger itself.

GRANT USE CATALOG ON CATALOG {catalog}                     TO `{job_sp}`;
GRANT USE SCHEMA, SELECT ON SCHEMA {catalog}.{schema}      TO `{job_sp}`;

-- The shared helper functions that rule_expr calls.
GRANT USE SCHEMA, EXECUTE ON SCHEMA {catalog}.{fn_schema}  TO `{job_sp}`;

-- onboard.py steps
GRANT MODIFY ON TABLE {catalog}.{schema}.dq_config_binding_proposal TO `{job_sp}`;  -- discover
GRANT MODIFY ON TABLE {catalog}.{schema}.dq_config_cde_registry    TO `{job_sp}`;  -- apply, unbind
GRANT MODIFY ON TABLE {catalog}.{schema}.dq_config_rule_registry   TO `{job_sp}`;  -- generate

-- run_checks.py (both jobs: steps measures shadow, checks measures everything selected)
GRANT MODIFY ON TABLE {catalog}.{schema}.dq_results_check_run        TO `{job_sp}`;
GRANT MODIFY ON TABLE {catalog}.{schema}.dq_results_violation_sample TO `{job_sp}`;

-- Every table a person selects for onboarding, wherever it lives. NOT granted here and
-- not grantable in advance: the job can only check a table its principal can read, and
-- the Add tables page lists what the APP principal can see, which is a different set.
-- Until those two are reconciled, a table can be selected in the app and then fail in
-- the job. One line per source schema once someone decides which schemas are in scope:
--
--   GRANT USE CATALOG ON CATALOG <src_catalog>                       TO `{job_sp}`;
--   GRANT USE SCHEMA, SELECT ON SCHEMA <src_catalog>.<src_schema>    TO `{job_sp}`;
--
-- Discovery also reads <src_catalog>.information_schema.columns and .column_tags, and
-- generate reads system.information_schema.columns; both show only what the grants
-- above make visible, so they need nothing extra.

-- Proof: exactly five MODIFYs for the job principal.
-- SELECT table_name, privilege_type
-- FROM   {catalog}.information_schema.table_privileges
-- WHERE  grantee = '{job_sp}' AND privilege_type = 'MODIFY'
-- ORDER  BY table_name;

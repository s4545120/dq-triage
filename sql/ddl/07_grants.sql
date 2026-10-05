-- Grants — the two-identity model, and the one claim the architecture makes
--
-- Substitute {catalog}, {app_sp} (the app's service principal application id) and
-- {steward_group} / {approver_group} (Databricks account groups) before execution.
-- Run as a metastore admin or the owner of the dq catalog.
--
-- ================================================================
-- READ THIS FIRST: a correction to the spec's wording
-- ================================================================
--
-- The spec and architecture doc both say the app service principal is "granted
-- INSERT on dq.results and nothing else". Unity Catalog has no INSERT privilege.
-- The table-level write privilege is MODIFY, and MODIFY permits INSERT, UPDATE,
-- DELETE and MERGE. There is no way to grant append-without-overwrite in UC alone.
--
-- The claim is still achievable, but it takes two mechanisms rather than one:
--
--   (a) MODIFY on named tables only (six since 2026-10-05, listed below) — never on
--       the schema.
--       Schema-level MODIFY would silently extend to every table added later.
--   (b) delta.appendOnly = true on every one of those tables (set in 01, 06, 13 and
--       15), which
--       makes UPDATE and DELETE fail for every principal, owner included.
--
-- Clearing (b) requires ALTER TABLE, which the app's SP cannot run (it is not the
-- owner) and which is recorded in Delta table history if anyone else does it.
--
-- The headline claim — "the app cannot modify business data" — is unaffected and
-- remains provable from grants alone, because it rests on the ABSENCE of any grant
-- on prod.*. Absence is the strongest form of this argument. Do not weaken it by
-- granting the SP anything outside the dq catalog for convenience.
--
-- What to tell an auditor: the app cannot touch business data (grant absence, and
-- OBO scope confinement); it cannot rewrite its own audit register (appendOnly);
-- and if the register were ever tampered with, Delta history records it. That is a
-- detective control. It is not preventive, and the spec says so.

-- ---------------------------------------------------------------
-- 1. The app service principal — read everything in dq, append to six tables
-- ---------------------------------------------------------------

GRANT USE CATALOG ON CATALOG {catalog} TO `{app_sp}`;
GRANT USE SCHEMA  ON SCHEMA  {catalog}.config  TO `{app_sp}`;
GRANT USE SCHEMA  ON SCHEMA  {catalog}.results TO `{app_sp}`;

GRANT SELECT ON SCHEMA {catalog}.config  TO `{app_sp}`;
GRANT SELECT ON SCHEMA {catalog}.results TO `{app_sp}`;

-- The triage half's three writes. Table-level, never schema-level.
-- Two until 2026-09-28; the third is the reviewer's decision on a threshold
-- proposal, which had nowhere else to live -- adopting one is an append to
-- rule_registry (already granted), but a rejection or deferral recorded nowhere is
-- a proposal that comes back every pass. See 13_results_threshold.sql.
GRANT MODIFY ON TABLE {catalog}.results.disposition       TO `{app_sp}`;
GRANT MODIFY ON TABLE {catalog}.config.rule_registry      TO `{app_sp}`;
GRANT MODIFY ON TABLE {catalog}.results.threshold_review  TO `{app_sp}`;

-- Onboarding, since 2026-10-05: three more, and THESE ARE A DECISION, NOT A DEPLOY.
-- Until someone takes it they are granted only in the dq_onboard test schema. Running
-- this file as it stands takes it: comment the three out to deploy without onboarding,
-- and the Onboarding pages say "No tables are selected yet" and write nothing.
--   * monitored_table  -- a person selecting, pausing or decommissioning a table
--   * binding_proposal -- a person suggesting a binding the discovery job missed
--   * binding_review   -- a person approving or rejecting a binding
-- Each is an append signed with the platform identity, and 15_config_onboarding.sql
-- constrains what each may say. Promotion of generated checks needs no new grant: it
-- is the rule_registry append above. The element register is NOT among them -- an
-- approved binding reaches config.cde_registry through the onboarding job.
GRANT MODIFY ON TABLE {catalog}.config.monitored_table    TO `{app_sp}`;
GRANT MODIFY ON TABLE {catalog}.config.binding_proposal   TO `{app_sp}`;
GRANT MODIFY ON TABLE {catalog}.config.binding_review     TO `{app_sp}`;

-- Deliberately NOT granted, and each omission is load-bearing:
--   * anything at all on any prod catalog          -> the headline claim
--   * MODIFY on results.cohort / check_run         -> the app cannot fabricate a finding
--   * MODIFY on results.threshold_proposal         -> the app cannot fabricate advice
--                                                     to then adopt; the threshold job
--                                                     writes it, as the triage job
--                                                     writes cohort
--   * MODIFY on results.violation_sample           -> the app cannot alter the evidence
--   * MODIFY on config.playbook                    -> approaches change by review, not in-app
--   * MODIFY on config.cde_registry                -> no app writes the element register;
--                                                     in-app CDE registration would be a
--                                                     further grant and a further decision
--   * MODIFY on config.check_template              -> templates are seeded from the repo,
--                                                     where templates.py proves each one
--   * CREATE TABLE / MANAGE anywhere               -> the SP cannot grant itself more
--   * ALTER on any table above                     -> the SP cannot clear delta.appendOnly
--
-- The onboarding job (discovery, apply, generate) and the check runner run as their
-- own job identity, not as this principal. They write binding_proposal (method
-- uc_tag / value_signature / name_match), cde_registry, rule_registry (shadow rows
-- only) and check_run; those grants belong to the job's owner and are not made here.

-- ---------------------------------------------------------------
-- 2. Human groups — under OBO these bound what a signed-in user can do
-- ---------------------------------------------------------------
--
-- Spec open question, unanswered: "Who is authorised to be an approver, and is that
-- list managed as a Databricks group?" The two-approver rule is only meaningful if
-- the eligible set is governed. Until {approver_group} exists and has an owner who
-- maintains it, the two-approver control is decorative — the app can count two
-- distinct identities but nobody has said which identities are eligible.

GRANT USE CATALOG ON CATALOG {catalog} TO `{steward_group}`;
GRANT SELECT ON SCHEMA {catalog}.config  TO `{steward_group}`;
GRANT SELECT ON SCHEMA {catalog}.results TO `{steward_group}`;

GRANT USE CATALOG ON CATALOG {catalog} TO `{approver_group}`;
GRANT SELECT ON SCHEMA {catalog}.results TO `{approver_group}`;

-- ---------------------------------------------------------------
-- 3. The proof queries — run these, keep the output
-- ---------------------------------------------------------------
--
-- These are the evidence a workspace admin shows. Run them after every grant change
-- and on a schedule; save the results with the control documentation.

-- 3a. Everything the app SP can write, anywhere in the metastore.
--     EXPECTED: exactly six rows — dq.results.disposition, dq.config.rule_registry,
--     dq.results.threshold_review, and the onboarding three: dq.config.monitored_table,
--     dq.config.binding_proposal, dq.config.binding_review. Three if onboarding was
--     not granted. Any other row is a control failure.
SELECT table_catalog, table_schema, table_name, privilege_type
FROM   system.information_schema.table_privileges
WHERE  grantee = '{app_sp}'
  AND  privilege_type IN ('MODIFY', 'ALL_PRIVILEGES')
ORDER  BY table_catalog, table_schema, table_name;

-- 3b. Any grant at all to the app SP outside the dq catalog.
--     EXPECTED: zero rows. This is the headline claim.
SELECT table_catalog, table_schema, table_name, privilege_type
FROM   system.information_schema.table_privileges
WHERE  grantee = '{app_sp}'
  AND  table_catalog <> '{catalog}';

-- 3c. Schema-level write grants to the app SP.
--     EXPECTED: zero rows. A schema-level MODIFY would extend to tables not yet created.
SELECT catalog_name, schema_name, privilege_type
FROM   system.information_schema.schema_privileges
WHERE  grantee = '{app_sp}'
  AND  privilege_type IN ('MODIFY', 'ALL_PRIVILEGES');

-- 3d. appendOnly is still set on every app-written table.
--     EXPECTED: all six report true. Run DESCRIBE DETAIL and read the properties map.
DESCRIBE DETAIL {catalog}.results.disposition;
DESCRIBE DETAIL {catalog}.config.rule_registry;
DESCRIBE DETAIL {catalog}.results.threshold_review;
DESCRIBE DETAIL {catalog}.config.monitored_table;
DESCRIBE DETAIL {catalog}.config.binding_proposal;
DESCRIBE DETAIL {catalog}.config.binding_review;

-- 3e. Has anyone rewritten the register? Non-INSERT operations on an appendOnly
--     table should be impossible; this proves it stayed that way.
--     EXPECTED: only WRITE / CREATE TABLE / OPTIMIZE / VACUUM operations. Any
--     UPDATE, DELETE, MERGE, or a SET TBLPROPERTIES that clears appendOnly is a
--     control failure and needs explaining.
--
--     DESCRIBE HISTORY is a statement, not a table expression -- it cannot be
--     wrapped in SELECT ... FROM (...). Run it and read the `operation` column,
--     or filter it from a notebook where it can be turned into a DataFrame:
--
--         spark.sql("DESCRIBE HISTORY {catalog}.results.disposition") \
--              .filter("operation NOT IN ('WRITE','CREATE TABLE','OPTIMIZE',"
--                      "'VACUUM START','VACUUM END')") \
--              .select("version", "timestamp", "userName", "operation",
--                      "operationParameters") \
--              .show(truncate=False)

DESCRIBE HISTORY {catalog}.results.disposition;

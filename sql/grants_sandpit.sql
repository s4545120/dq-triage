-- =====================================================================
-- grants_sandpit.sql — 07_grants.sql rendered for workspace.dq_triage
--
-- HAND-WRITTEN, NOT GENERATED. sql/render.py drops 07_grants.sql entirely
-- because a sandpit usually cannot grant at all. This workspace can: the
-- Databricks App has its own service principal, so the control the spec
-- describes is testable here rather than merely asserted.
--
-- If you re-render for a different catalog/schema, fix this file by hand.
-- Same caveat as sql/out/verify_results.sql.
--
--   app service principal : fa379f33-6f41-416f-b603-3464badd0adb
--   app name              : app-2a8ouv dq-triage
--   target                : workspace.dq_triage, prefix dq_
--
-- ONE DIFFERENCE FROM 07_grants.sql, AND IT MATTERS
--
-- The original grants SELECT at SCHEMA level on dq.config and dq.results.
-- That is safe there because the business tables live in a different catalog
-- the app has nothing on. Here the schema split was folded into a name prefix,
-- so `workspace.dq_triage` ALSO holds dq_mock_ctct_c and dq_mock_subs_c — the
-- stand-ins for production. A schema-level SELECT would hand the app read
-- access to the very tables the design says it never touches.
--
-- So SELECT is granted table by table. It is more verbose and it is the only
-- rendering that preserves the claim.
-- =====================================================================

-- ---------------------------------------------------------------
-- 1. Traversal
-- ---------------------------------------------------------------

GRANT USE CATALOG ON CATALOG workspace              TO `fa379f33-6f41-416f-b603-3464badd0adb`;
GRANT USE SCHEMA  ON SCHEMA  workspace.dq_triage    TO `fa379f33-6f41-416f-b603-3464badd0adb`;

-- ---------------------------------------------------------------
-- 2. Read — the eight tables the app actually queries, and only those
-- ---------------------------------------------------------------
--
-- The five views are deliberately NOT granted. The app never queries them:
-- v_cohort_current and v_cde_coverage are folded in Python by domain/lifecycle.py
-- and domain/coverage.py so a session-recorded event appears before any warehouse
-- could re-run the view. Grant them only if that ever changes.

GRANT SELECT ON TABLE workspace.dq_triage.dq_config_rule_registry     TO `fa379f33-6f41-416f-b603-3464badd0adb`;
GRANT SELECT ON TABLE workspace.dq_triage.dq_config_playbook          TO `fa379f33-6f41-416f-b603-3464badd0adb`;
GRANT SELECT ON TABLE workspace.dq_triage.dq_config_cde_registry      TO `fa379f33-6f41-416f-b603-3464badd0adb`;
GRANT SELECT ON TABLE workspace.dq_triage.dq_results_check_run        TO `fa379f33-6f41-416f-b603-3464badd0adb`;
GRANT SELECT ON TABLE workspace.dq_triage.dq_results_violation_sample TO `fa379f33-6f41-416f-b603-3464badd0adb`;
GRANT SELECT ON TABLE workspace.dq_triage.dq_results_cohort           TO `fa379f33-6f41-416f-b603-3464badd0adb`;
GRANT SELECT ON TABLE workspace.dq_triage.dq_results_disposition      TO `fa379f33-6f41-416f-b603-3464badd0adb`;
GRANT SELECT ON TABLE workspace.dq_triage.dq_results_cde_profile      TO `fa379f33-6f41-416f-b603-3464badd0adb`;

-- ---------------------------------------------------------------
-- 3. Write — the only two statements in the whole application
-- ---------------------------------------------------------------
--
-- MODIFY, not INSERT: Unity Catalog has no INSERT privilege, and MODIFY permits
-- UPDATE and DELETE too. delta.appendOnly = true on both tables is what closes
-- that gap — see sql/README.md.

GRANT MODIFY ON TABLE workspace.dq_triage.dq_results_disposition      TO `fa379f33-6f41-416f-b603-3464badd0adb`;
GRANT MODIFY ON TABLE workspace.dq_triage.dq_config_rule_registry     TO `fa379f33-6f41-416f-b603-3464badd0adb`;

-- Deliberately NOT granted, each omission load-bearing:
--   * anything on dq_mock_ctct_c / dq_mock_subs_c  -> the headline claim
--   * MODIFY on dq_results_cohort / check_run      -> the app cannot fabricate a finding
--   * MODIFY on dq_results_violation_sample        -> the app cannot alter the evidence
--   * MODIFY on dq_config_playbook                 -> approaches change by review, not in-app
--   * CREATE TABLE / MANAGE anywhere               -> the SP cannot grant itself more
--   * ALTER on dq_results_disposition              -> the SP cannot clear delta.appendOnly

-- =====================================================================
-- 4. The proof queries — run these, keep the output
-- =====================================================================
-- This is the evidence. Run after every grant change; save the results with the
-- control documentation.

-- 4a. Everything the app SP can write, anywhere in the metastore.
--     EXPECTED: exactly two rows — dq_results_disposition and dq_config_rule_registry.
--     Any other row is a control failure.
SELECT table_catalog, table_schema, table_name, privilege_type
FROM   system.information_schema.table_privileges
WHERE  grantee = 'fa379f33-6f41-416f-b603-3464badd0adb'
  AND  privilege_type IN ('MODIFY', 'ALL_PRIVILEGES')
ORDER  BY table_catalog, table_schema, table_name;

-- 4b. Any grant at all to the app SP on the mock SOURCE tables.
--     EXPECTED: zero rows. THIS IS THE HEADLINE CLAIM in sandpit form — the
--     original 07_grants.sql asks the same question as "anything outside the dq
--     catalog", which means nothing here because everything shares one schema.
SELECT table_catalog, table_schema, table_name, privilege_type
FROM   system.information_schema.table_privileges
WHERE  grantee = 'fa379f33-6f41-416f-b603-3464badd0adb'
  AND  table_name IN ('dq_mock_ctct_c', 'dq_mock_subs_c');

-- 4c. Schema-level write grants to the app SP.
--     EXPECTED: zero rows. A schema-level MODIFY would extend to tables not yet
--     created — and in this layout, to the mock source tables as well.
SELECT catalog_name, schema_name, privilege_type
FROM   system.information_schema.schema_privileges
WHERE  grantee = 'fa379f33-6f41-416f-b603-3464badd0adb'
  AND  privilege_type IN ('MODIFY', 'ALL_PRIVILEGES', 'SELECT');

-- 4d. appendOnly still set on both app-written tables. Read the properties map.
--     EXPECTED: delta.appendOnly = true in both.
DESCRIBE DETAIL workspace.dq_triage.dq_results_disposition;
DESCRIBE DETAIL workspace.dq_triage.dq_config_rule_registry;

-- 4e. The negative test. Run as yourself — it must be REFUSED by the table
--     property, independently of any grant.
--     EXPECTED: an error naming delta.appendOnly. If this succeeds, the register
--     is not append-only and the audit claim is void.
-- UPDATE workspace.dq_triage.dq_results_disposition
--    SET reason = 'tampered' WHERE event_seq = 1;

-- =====================================================================
-- 5. Human groups — NOT rendered
-- =====================================================================
-- 07_grants.sql § 2 grants a steward group and an approver group. A personal
-- workspace has neither, and the spec's open question — "who is authorised to be
-- an approver, and is that list managed as a Databricks group?" — is unanswered.
-- Until that group exists and has an owner who maintains it, the two-approver
-- control is decorative: the app can count two distinct identities, but nobody
-- has said which identities are eligible. Left out rather than faked.

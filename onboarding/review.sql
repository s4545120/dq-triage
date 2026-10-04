-- =====================================================================
-- review.sql — the simplified human review for the onboarding test.
--
-- Two decisions, each an append signed with current_user(). Run them in the
-- SQL editor against the Serverless Starter Warehouse. Nothing here edits a
-- row; a wrong decision is corrected by a later one.
-- =====================================================================


-- ---------------------------------------------------------------------
-- Step 1 — binding proposals. Run after `onboard.py discover`.
-- ---------------------------------------------------------------------

-- 1a. What is waiting. Read the evidence column before approving.
SELECT proposal_id, target_column, cde_id, method, confidence, evidence
FROM   workspace.dq_onboard.dq_config_v_binding_proposal_open
ORDER  BY target_column;

-- 1b. Approve all of them, or add  AND target_column IN (...)  to choose.
INSERT INTO workspace.dq_onboard.dq_config_binding_review
SELECT proposal_id, 'approved', current_user(), current_timestamp(), 'onboarding test review'
FROM   workspace.dq_onboard.dq_config_v_binding_proposal_open;

-- 1c. Reject one instead (put its column in the WHERE). A rejected column is
--     never proposed again until someone tags it.
-- INSERT INTO workspace.dq_onboard.dq_config_binding_review
-- SELECT proposal_id, 'rejected', current_user(), current_timestamp(), '<why>'
-- FROM   workspace.dq_onboard.dq_config_v_binding_proposal_open
-- WHERE  target_column = '<COLUMN>';


-- ---------------------------------------------------------------------
-- Step 2 — promote the table's generated rules. Run after the first
-- `onboard.py run` has measured them in shadow.
-- ---------------------------------------------------------------------

-- 2a. What shadow measured, per rule, on the latest run.
SELECT c.rule_id, c.violation_count, c.rows_scanned, c.violation_pct, r.fail_threshold_pct
FROM   workspace.dq_onboard.dq_results_check_run c
JOIN   workspace.dq_onboard.dq_config_v_rule_registry_current r USING (rule_id)
WHERE  c.run_ts = (SELECT max(run_ts) FROM workspace.dq_onboard.dq_results_check_run)
  AND  r.template_id IS NOT NULL
ORDER  BY c.violation_pct DESC;

-- 2b. Promote every shadow rule generated for the table: a new rule_version
--     each, status active, promoted_by you. Same append the app's promotion makes.
INSERT INTO workspace.dq_onboard.dq_config_rule_registry
  (rule_id, rule_version, rule_name, target_table, target_column, cde_id, rule_type,
   rule_expr, scope_filter, fail_threshold_pct, severity, business_domain, owner_group,
   source_layer, status, effective_from, created_by, created_at, promoted_by,
   promoted_at, note, join_sql, template_id, template_version)
SELECT rule_id, rule_version + 1, rule_name, target_table, target_column, cde_id, rule_type,
       rule_expr, scope_filter, fail_threshold_pct, severity, business_domain, owner_group,
       source_layer, 'active', current_timestamp(), created_by, created_at, current_user(),
       current_timestamp(), concat(note, ' Promoted after shadow review.'), join_sql,
       template_id, template_version
FROM   workspace.dq_onboard.dq_config_v_rule_registry_current
WHERE  target_table = 'workspace.dq_onboard.dq_src_crm_lead'
  AND  status = 'shadow'
  AND  template_id IS NOT NULL;

-- =====================================================================
-- retire_vulnerable_customer.sql — written 2026-10-01 for workspace.dq_triage.
--
-- Retires CDE_VULNERABLE_CUSTOMER and its only rule, CTCT_SPCL_CARE_VARIANCE.
-- Both registries are appendOnly, so retiring is an INSERT of a new version with
-- status = 'retired', carrying everything else forward from the current version.
-- Nothing is deleted: the check runs, COH-F and both histories stay as they were.
-- The fixture models the same two versions (fixtures/cdes.py, fixtures/rules.py).
--
-- Rule first: the element must not be retired while a current rule names it.
-- =====================================================================

-- Step 0 — the guard. EXPECTED: one row each, status registered / active,
-- CDE at v1 (added by migrate_cde_scope part 2) and the rule at v2 (its cde_id version).
-- If either already reads 'retired', or is missing, this has run: stop.
SELECT cde_id, cde_version, status FROM workspace.dq_triage.dq_config_v_cde_registry_current WHERE cde_id = 'CDE_VULNERABLE_CUSTOMER';
SELECT rule_id, rule_version, status FROM workspace.dq_triage.dq_config_v_rule_registry_current WHERE rule_id = 'CTCT_SPCL_CARE_VARIANCE';

-- Step 1 — retire the rule.
INSERT INTO workspace.dq_triage.dq_config_rule_registry (rule_id, rule_version, rule_name, target_table, target_column, cde_id, rule_type, rule_expr, scope_filter, join_sql, fail_threshold_pct, severity, business_domain, owner_group, source_layer, status, effective_from, created_by, created_at, promoted_by, promoted_at, note)
SELECT rule_id, rule_version + 1, rule_name, target_table, target_column, cde_id,
       rule_type, rule_expr, scope_filter, join_sql, fail_threshold_pct,
       severity, business_domain, owner_group, source_layer,
       'retired',
       current_timestamp(), current_user(), current_timestamp(),
       promoted_by, promoted_at,
       'v2: retired 2026-10-01, with CDE_VULNERABLE_CUSTOMER. A count of distinct values cannot tell a defaulted flag from a population with no vulnerable customers, and failing it marked all 1000 rows. The runs before this date stand; nothing runs it after.'
FROM   workspace.dq_triage.dq_config_rule_registry
WHERE  rule_id = 'CTCT_SPCL_CARE_VARIANCE'
  AND  rule_version = (SELECT max(rule_version) FROM workspace.dq_triage.dq_config_rule_registry WHERE rule_id = 'CTCT_SPCL_CARE_VARIANCE')
  AND  status <> 'retired';

-- Step 2 — retire the element.
INSERT INTO workspace.dq_triage.dq_config_cde_registry (cde_id, cde_version, cde_name, business_term, data_class, definition, expected_signature, criticality, pii, regulatory_basis, tolerance_pct, bindings, business_domain, owner_group, status, effective_from, registered_by, registered_at, note)
SELECT cde_id, cde_version + 1, cde_name, business_term, data_class, definition,
       expected_signature, criticality, pii, regulatory_basis, tolerance_pct,
       bindings, business_domain, owner_group,
       'retired',
       current_timestamp(), current_user(), current_timestamp(),
       'v2: retired 2026-10-01. Its only rule, CTCT_SPCL_CARE_VARIANCE, asked whether the flag ever varied, and on a 1000-row pilot extract an all-\'N\' column cannot tell a defaulted field from a population with no vulnerable customers -- so every run scored the element 0% for a question the data cannot answer. Retired with its rule rather than deleted. COH-F, raised on 2026-08-30 with that rule as a member, is left as raised. Re-register when the business can state how many customers it expects to carry the flag.'
FROM   workspace.dq_triage.dq_config_cde_registry
WHERE  cde_id = 'CDE_VULNERABLE_CUSTOMER'
  AND  cde_version = (SELECT max(cde_version) FROM workspace.dq_triage.dq_config_cde_registry WHERE cde_id = 'CDE_VULNERABLE_CUSTOMER')
  AND  status <> 'retired';

-- Step 3 — verification. EXPECTED: zero rows from each of the first two; the
-- third shows both at their retired versions.
SELECT cde_id FROM workspace.dq_triage.dq_config_v_cde_registry_current WHERE cde_id = 'CDE_VULNERABLE_CUSTOMER';
SELECT rule_id FROM workspace.dq_triage.dq_config_v_rule_registry_current WHERE rule_id = 'CTCT_SPCL_CARE_VARIANCE';
SELECT 'rule' AS kind, rule_id AS id, rule_version AS v, status FROM workspace.dq_triage.dq_config_rule_registry
WHERE  rule_id = 'CTCT_SPCL_CARE_VARIANCE'
UNION ALL
SELECT 'cde', cde_id, cde_version, status FROM workspace.dq_triage.dq_config_cde_registry
WHERE  cde_id = 'CDE_VULNERABLE_CUSTOMER'
ORDER  BY kind, v;

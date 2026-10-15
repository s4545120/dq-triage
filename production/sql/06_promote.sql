-- =====================================================================
-- 06_promote.sql — shadow -> active. The app's Promote button, as SQL.
-- target: sdpt_data_trnf.udp_brnz, prefix dq_
--
-- Every rule is registered in SHADOW: measured, never raised. Only an active rule
-- can breach, so until this runs nothing reaches the triage notebook. Promotion
-- is a person's decision, and current_user() is the name the register keeps.
--
-- Run it after the pipeline has measured the rules at least once, and after
-- reading 6a. Re-runnable: a rule already active is not touched.
-- =====================================================================

-- 6a — what each shadow rule measured on its latest run. Read this first: a rule
-- flagging most of its table is more likely a wrong rule than bad data, and
-- promoting it fills triage with one problem that is not a data defect.
SELECT r.target_table, r.rule_id, r.severity, c.rows_scanned, c.violation_count,
       round(c.violation_pct, 2) AS violation_pct, c.run_ts
FROM   sdpt_data_trnf.udp_brnz.dq_config_v_rule_registry_current r
LEFT JOIN (SELECT *, row_number() OVER (PARTITION BY rule_id ORDER BY run_ts DESC) AS n
           FROM sdpt_data_trnf.udp_brnz.dq_results_check_run) c ON c.rule_id = r.rule_id AND c.n = 1
WHERE  r.status = 'shadow'
ORDER  BY violation_pct DESC NULLS FIRST, r.rule_id;

-- 6b — promote. As written it promotes every MEASURED shadow rule on every table.
-- Narrow it by uncommenting a line below; start with one table.
INSERT INTO sdpt_data_trnf.udp_brnz.dq_config_rule_registry (rule_id, rule_version, rule_name, target_table, target_column, cde_id, rule_type, rule_expr, scope_filter, join_sql, fail_threshold_pct, severity, business_domain, owner_group, source_layer, status, effective_from, created_by, created_at, promoted_by, promoted_at, note)
SELECT r.rule_id, r.rule_version + 1, r.rule_name, r.target_table, r.target_column, r.cde_id, r.rule_type, r.rule_expr, r.scope_filter, r.join_sql, r.fail_threshold_pct, r.severity, r.business_domain, r.owner_group, r.source_layer, 'active', current_timestamp(), current_user(), current_timestamp(), current_user(), current_timestamp(), 'Promoted by SQL (production/sql/06_promote.sql) after its shadow measurement was reviewed.'
FROM   sdpt_data_trnf.udp_brnz.dq_config_v_rule_registry_current r
WHERE  r.status = 'shadow'
  AND  EXISTS (SELECT 1 FROM sdpt_data_trnf.udp_brnz.dq_results_check_run c WHERE c.rule_id = r.rule_id
                                     AND c.status IN ('skipped', 'pass', 'breach'))
  -- AND r.target_table = 'prod.udp_brnz_nrt_tech_view.table_bus_org_hist'
  -- AND r.rule_id IN ('...', '...')
;

-- 6c — EXPECTED: the rules you meant, now 'active'.
SELECT target_table, status, COUNT(*) AS rules FROM sdpt_data_trnf.udp_brnz.dq_config_v_rule_registry_current
GROUP BY 1, 2 ORDER BY 1, 2;

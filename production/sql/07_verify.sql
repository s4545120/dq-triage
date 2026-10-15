-- =====================================================================
-- 07_verify.sql — read-only. After each pipeline run.
-- target: sdpt_data_trnf.udp_brnz, prefix dq_
-- =====================================================================

-- 7a — the latest runs. A shadow-only day reads all 'skipped'; 'error' needs 7b.
SELECT run_id, min(run_ts) AS run_ts, status, COUNT(*) AS checks
FROM   sdpt_data_trnf.udp_brnz.dq_results_check_run
WHERE  run_id IN (SELECT run_id FROM sdpt_data_trnf.udp_brnz.dq_results_check_run
                  GROUP BY run_id ORDER BY max(run_ts) DESC LIMIT 3)
GROUP  BY run_id, status ORDER BY run_ts DESC, status;

-- 7b — every error on the latest run, with the warehouse's reason. Usually a
-- source table or column this principal cannot read, or a helper function missing.
SELECT rule_id, target_table, message
FROM   sdpt_data_trnf.udp_brnz.dq_results_check_run
WHERE  status = 'error' AND run_id = (SELECT max_by(run_id, run_ts) FROM sdpt_data_trnf.udp_brnz.dq_results_check_run)
ORDER  BY target_table, rule_id;

-- 7c — rows read vs current records vs slice, per table on the latest run. population
-- rows well below table rows is 05_current_records.sql working.
SELECT target_table, max(table_rows) AS table_rows, max(population_rows) AS current_records,
       max(slice_rows) AS in_slice
FROM   sdpt_data_trnf.udp_brnz.dq_results_check_run
WHERE  run_id = (SELECT max_by(run_id, run_ts) FROM sdpt_data_trnf.udp_brnz.dq_results_check_run)
GROUP  BY target_table ORDER BY 1;

-- 7d — breaches on the latest run, and which reach triage. A breach whose key
-- attribute is within its tolerance is held back (not P1).
SELECT rule_id, severity, violation_count, rows_scanned, cde_id, escalates, held_reason
FROM   sdpt_data_trnf.udp_brnz.dq_results_v_check_escalation
WHERE  run_id = (SELECT max_by(run_id, run_ts) FROM sdpt_data_trnf.udp_brnz.dq_results_check_run)
ORDER  BY escalates DESC, violation_count DESC;

-- 7e — what the triage notebook wrote. Every cohort it writes reads
-- 'awaiting_triage' and is listed by v_disposition_integrity as
-- missing_recommended_event: known, see CLAUDE.md 'The notebook never opens the chain'.
SELECT c.cohort_id, c.raised_ts, c.member_count, c.defect_location, c.confidence,
       v.lifecycle_state
FROM   sdpt_data_trnf.udp_brnz.dq_results_cohort c
JOIN   sdpt_data_trnf.udp_brnz.dq_results_v_cohort_current v USING (cohort_id)
ORDER  BY c.raised_ts DESC;

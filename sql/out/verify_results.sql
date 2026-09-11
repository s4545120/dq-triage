-- =====================================================================
-- verify_results.sql — the sandpit end to end.
--
-- Everything is loaded. This checks it hangs together, and in particular
-- exercises the five VIEWS, which have never been queried against real
-- Unity Catalog data — only against the fixture's parquet twins.
--
-- Checks 4 and 5 are the ones that matter. The rest are arithmetic.
-- =====================================================================

-- 1. Row counts. EXPECTED: 1360 / 40 / 1028 / 14 / 65 / 12
SELECT 'check_run'        AS t, count(*) AS actual, 1360 AS expected
  FROM sdpt_data_trnf.udp_brnz.dq_results_check_run
UNION ALL SELECT 'check_run distinct runs', count(DISTINCT run_id), 40
  FROM sdpt_data_trnf.udp_brnz.dq_results_check_run
UNION ALL SELECT 'violation_sample', count(*), 1028
  FROM sdpt_data_trnf.udp_brnz.dq_results_violation_sample
UNION ALL SELECT 'cohort', count(*), 14
  FROM sdpt_data_trnf.udp_brnz.dq_results_cohort
UNION ALL SELECT 'disposition', count(*), 65
  FROM sdpt_data_trnf.udp_brnz.dq_results_disposition
UNION ALL SELECT 'cde_profile', count(*), 12
  FROM sdpt_data_trnf.udp_brnz.dq_results_cde_profile;

-- 2. The registry view resolves versions. EXPECTED: 34 (35 rows, MSISDN has two)
SELECT count(*) AS actual, 34 AS expected
FROM   sdpt_data_trnf.udp_brnz.dq_config_v_rule_registry_current;

-- 3. Your real run is the latest, and stands alone with samples behind it.
--    EXPECTED: 1 run, 34 verdicts, 21 breach / 11 pass / 2 skipped
SELECT run_id, count(*) AS verdicts,
       count_if(status='breach')  AS breach,
       count_if(status='pass')    AS pass,
       count_if(status='skipped') AS skipped
FROM   sdpt_data_trnf.udp_brnz.dq_results_check_run
WHERE  run_ts = (SELECT max(run_ts) FROM sdpt_data_trnf.udp_brnz.dq_results_check_run)
GROUP  BY run_id;

-- 4. v_cohort_current — the event log folded into state.
--    This is the view the whole append-only design rests on: a cohort has no
--    status column, so where it has got to is DERIVED here, every read.
--    EXPECTED, exactly:
--      closed_verified 9 | reopened 1 | closed_rejected 1
--      deferred 1 | approved_awaiting_execution 1 | awaiting_review 1
SELECT lifecycle_state, count(*) AS n
FROM   sdpt_data_trnf.udp_brnz.dq_results_v_cohort_current
GROUP  BY lifecycle_state ORDER BY n DESC;

-- 5. v_disposition_integrity — the control check. EXPECTED: ZERO ROWS.
--    Any row is a control failure: a duplicate approver, a human event with no
--    platform identity, or a cohort that was never recommended. This is the
--    query that would be scheduled and alerted on in production.
SELECT * FROM sdpt_data_trnf.udp_brnz.dq_results_v_disposition_integrity;

-- 6. v_cde_coverage — what the register asserts about the rule set.
--    EXPECTED: covered 5 | unvalidated 5 | scope_mismatch 2
--    scope_mismatch MUST be 2. Those are SUBS_IMEI_NOT_NULL and
--    SUBS_PRIM_ACCT_NOT_ZERO — deliberately unscoped rules that the CDE
--    bindings prove wrong. An empty bucket means the CDE model is not working.
SELECT coverage_gap, count(*) AS n
FROM   sdpt_data_trnf.udp_brnz.dq_results_v_cde_coverage
GROUP  BY coverage_gap ORDER BY n DESC;

-- 7. The registry has no uniqueness enforcement. EXPECTED: zero rows.
SELECT rule_id, rule_version, count(*) AS n
FROM   sdpt_data_trnf.udp_brnz.dq_config_rule_registry
GROUP  BY rule_id, rule_version HAVING count(*) > 1;

-- 8. Every cohort's members resolve to real verdicts. EXPECTED: zero rows.
SELECT c.cohort_id, size(c.member_result_ids) AS members, count(r.result_id) AS found
FROM   sdpt_data_trnf.udp_brnz.dq_results_cohort c
LATERAL VIEW explode(c.member_result_ids) e AS mid
LEFT   JOIN sdpt_data_trnf.udp_brnz.dq_results_check_run r ON r.result_id = e.mid
GROUP  BY c.cohort_id, size(c.member_result_ids)
HAVING count(r.result_id) <> size(c.member_result_ids);

-- =====================================================================
-- 23_views_bi.sql — two views for the AI/BI dashboard and its Genie space
--
-- Neither adds a fact. One names the runs every dashboard trend should count; the
-- other is results.cohort without the column a dashboard viewer should not see.
-- Both are read by tools/dashboard_datasets.py's queries (production/dashboard/).
--
-- Reads 03 and 05 only. Appended to sql/render.py's order like 15-22.
-- =====================================================================

-- ---------------------------------------------------------------
-- v_scheduled_run — the runs a trend counts
-- ---------------------------------------------------------------
-- dq-app/dq_app/domain/metrics.scheduled_runs, in SQL. A run whose every verdict is
-- 'skipped' measured shadow rules only and is not a run to a reader: it has no score,
-- and counted as "the previous run" it turned every delta into nan. Of the runs left,
-- a day's last one replaces the earlier ones, the day being Sydney's. Nothing is
-- removed from check_run: cohorts reference its rows by result_id.
--
-- run_ts is read as UTC, which is what the check runner writes and what a serverless
-- session's time zone is.

CREATE OR REPLACE VIEW {catalog}.results.v_scheduled_run
COMMENT 'One row per scheduled check run: runs with at least one verdict other than skipped, and of those the last run of each Sydney day. What every dashboard trend and "latest run" counts.'
AS
WITH runs AS (
  SELECT run_id,
         MAX(run_ts)                                                        AS run_ts,
         COUNT(*)                                                           AS checks,
         SUM(CASE WHEN status <> 'skipped' THEN 1 ELSE 0 END)               AS raised_checks
  FROM   {catalog}.results.check_run
  GROUP  BY run_id
),
dated AS (
  SELECT run_id, run_ts, checks,
         to_date(from_utc_timestamp(run_ts, 'Australia/Sydney'))           AS run_day
  FROM   runs
  WHERE  raised_checks > 0
)
SELECT run_id, run_ts, run_day, checks,
       run_ts = MAX(run_ts) OVER ()                                         AS is_latest
FROM (
  SELECT d.*, ROW_NUMBER() OVER (PARTITION BY run_day ORDER BY run_ts DESC) AS n
  FROM   dated d
)
WHERE n = 1;

-- ---------------------------------------------------------------
-- v_cohort_for_bi — results.cohort without the model's input
-- ---------------------------------------------------------------
-- model_input_payload holds the brief sent to the model and its reasoning. Briefs
-- written since 2026-10-08 carry no row values, but the eight cohorts written before
-- then hold violation samples in it, and a dashboard is shared more widely than the
-- stewards who may see failing values. Every other column passes through unchanged.

CREATE OR REPLACE VIEW {catalog}.results.v_cohort_for_bi
COMMENT 'results.cohort without model_input_payload, for the dashboard and its Genie space. Nothing else is changed.'
AS
SELECT cohort_id, raised_run_id, raised_ts, member_result_ids, member_rule_ids, member_count,
       affected_tables, total_violation_rows, root_cause_hypothesis, evidence_summary,
       evidence_points, rival_hypothesis, confidence, defect_location, grouping_verdict,
       members_not_covered, blast_radius_tables, blast_radius_count, severity,
       business_domain, owner_group, rank_score, recommended_approach,
       recommended_approach_type, recommended_steps, recommended_owner,
       verification_expectation, prior_state, differs_from_prior, playbook_id,
       recommendation_source, model_endpoint, triage_job_run_id, is_recurrence
FROM   {catalog}.results.cohort;

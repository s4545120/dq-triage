"""The AI/BI dashboard's datasets, one SQL query each.

tools/build_production.py renders these into production/dashboard/ for one schema; paste
each into the dashboard's Data tab under the name given. `$Q` stands for the sandpit's
object prefix, `<catalog>.<schema>.dq_`, so `$Qresults_check_run` is the check_run table.

Rules every query here keeps:

* **Runs come from `results_v_scheduled_run`** (sql/ddl/23), so a shadow-only run is
  never "the latest run" or "the previous run", and a day counts once.
* **A score is failures summed over rows checked**, never an average of percentages.
* **Every dataset that a global filter applies to carries that filter's field under one
  name**: run_day (run_week on the weekly trend datasets), business_domain, cde_name, target_table,
  severity, lifecycle_state.
* **No violation_sample, no model_input_payload.** The dashboard is shared more widely
  than the stewards who may see failing values.
"""

from __future__ import annotations

# The latest scheduled run, inlined wherever a dataset reads only that run.
LATEST = "(SELECT run_id FROM $Qresults_v_scheduled_run WHERE is_latest)"

DIMENSION = """CASE r.rule_type
         WHEN 'not_null' THEN 'Completeness'
         WHEN 'format' THEN 'Validity' WHEN 'sentinel' THEN 'Validity' WHEN 'variance' THEN 'Validity'
         WHEN 'consistency' THEN 'Consistency' WHEN 'referential' THEN 'Consistency'
         WHEN 'uniqueness' THEN 'Uniqueness' ELSE 'Other' END"""

DATASETS: list[tuple[str, str, str]] = [

("ds_quality_trend", "Overall quality per week (the last scheduled run of each week, Monday-start). No overall threshold: thresholds live on rules. Executive summary: "
 "Overall quality counter (value, sparkline). Whole register: the page's only "
 "filter is Run date.", """
WITH cdes AS (                               -- every key attribute still registered
  SELECT cde_id FROM $Qconfig_v_cde_registry_current WHERE status <> 'retired'
),
attached AS (                           -- active rules on a registered key attribute in scope
  SELECT DISTINCT x.rule_id
  FROM   $Qresults_v_cde_coverage cv LATERAL VIEW explode(cv.rule_ids) x AS rule_id
  WHERE  cv.cde_id IN (SELECT cde_id FROM cdes)
),
scored AS (
  SELECT k.run_id, SUM(k.rows_scanned) AS rows_checked, SUM(k.violation_count) AS rows_failed
  FROM   $Qresults_check_run k
  JOIN   attached a ON a.rule_id = k.rule_id
  WHERE  k.status IN ('pass', 'breach')
  GROUP  BY k.run_id
)
SELECT r.run_id, r.run_ts, r.run_day, r.run_week, r.is_latest,
       s.rows_checked, s.rows_failed,
       100.0 * (s.rows_checked - s.rows_failed) / s.rows_checked                AS score_pct,
       100.0 * (s.rows_checked - s.rows_failed) / s.rows_checked
         - LAG(100.0 * (s.rows_checked - s.rows_failed) / s.rows_checked)
             OVER (ORDER BY r.run_ts)                                           AS change_pts
FROM   (SELECT w.*, CAST(date_trunc('WEEK', w.run_day) AS DATE) AS run_week
        FROM   $Qresults_v_scheduled_run w
        QUALIFY ROW_NUMBER() OVER (PARTITION BY date_trunc('WEEK', w.run_day)
                                   ORDER BY w.run_ts DESC) = 1) r
JOIN   scored s ON s.run_id = r.run_id
-- Newest first: a counter reads row 1 unaggregated, so row 1 must be the latest week.
ORDER  BY r.run_ts DESC
"""),

("ds_element_scores", "One row per week (its last scheduled run) and key attribute: the score, "
 "how many of its active rules ran and how many are over their own threshold, and its "
 "status. No attribute threshold: since 2026-10-22 a threshold lives on the rule, and a "
 "CDE is Failing when any of its rules breaches. Disputed scope reads Scope disputed. "
 "change_pts is against last week. Domain view: Score counter, CDE counters, CDE scores.", """
WITH cdes AS (                               -- every key attribute still registered
  SELECT cde_id FROM $Qconfig_v_cde_registry_current WHERE status <> 'retired'
),
coverage AS (
  SELECT cde_id, MAX(target_table) AS target_table FROM $Qresults_v_cde_coverage GROUP BY cde_id
),
breaches AS (                           -- per run and CDE: rules that ran, rules over their limit
  SELECT k.run_id, a.cde_id,
         COUNT(DISTINCT k.rule_id)                                              AS rules_ran,
         COUNT(DISTINCT CASE WHEN k.status = 'breach' THEN k.rule_id END)       AS rules_breaching
  FROM   $Qresults_check_run k
  JOIN   (SELECT DISTINCT cv.cde_id, x.rule_id
          FROM   $Qresults_v_cde_coverage cv LATERAL VIEW explode(cv.rule_ids) x AS rule_id) a
         ON a.rule_id = k.rule_id
  WHERE  k.status IN ('pass', 'breach')
  GROUP  BY k.run_id, a.cde_id
),
scored AS (
  SELECT t.run_id, t.run_ts, t.cde_id, t.cde_name, t.criticality, t.rows_evaluated,
         t.rows_failed, t.score_pct, t.scope_disputed,
         r.run_day, r.run_week, r.is_latest, c.business_domain, v.target_table,
         COALESCE(b.rules_ran, 0) AS rules_ran, COALESCE(b.rules_breaching, 0) AS rules_breaching
  FROM   $Qresults_v_element_tolerance t
  JOIN   (SELECT w.*, CAST(date_trunc('WEEK', w.run_day) AS DATE) AS run_week
        FROM   $Qresults_v_scheduled_run w
        QUALIFY ROW_NUMBER() OVER (PARTITION BY date_trunc('WEEK', w.run_day)
                                   ORDER BY w.run_ts DESC) = 1) r ON r.run_id = t.run_id
  JOIN   $Qconfig_v_cde_registry_current c ON c.cde_id = t.cde_id
  LEFT JOIN coverage v ON v.cde_id = t.cde_id
  LEFT JOIN breaches b ON b.run_id = t.run_id AND b.cde_id = t.cde_id
)
SELECT run_id, run_ts, run_day, run_week, is_latest, cde_id, cde_name, criticality,
       business_domain, target_table, rows_evaluated, rows_failed, score_pct,
       rules_ran, rules_breaching, scope_disputed,
       score_pct - LAG(score_pct) OVER (PARTITION BY cde_id ORDER BY run_ts)    AS change_pts,
       CASE WHEN scope_disputed THEN 'Scope disputed'
            WHEN rules_breaching > 0 THEN 'Failing'
            ELSE 'Passing' END                                                  AS status,
       CASE WHEN rules_breaching > 0 AND NOT scope_disputed THEN 1 ELSE 0 END   AS is_failing
FROM   scored
WHERE  cde_id IN (SELECT cde_id FROM cdes)
ORDER  BY run_ts DESC, rules_breaching DESC, cde_name
"""),

("ds_coverage", "One row per binding: what checks each bound column. On no stage-1 widget; "
 "kept for Genie.", """
SELECT cde_id, cde_name, criticality, business_domain, target_table, target_column,
       coverage_gap,
       CASE coverage_gap WHEN 'covered' THEN 'Covered'
                         WHEN 'unvalidated' THEN 'Not validated'
                         WHEN 'no_rule' THEN 'No active rule'
                         WHEN 'scope_mismatch' THEN 'Scope disputed' END        AS coverage,
       rule_count, breaching_rule_count
FROM   $Qresults_v_cde_coverage
"""),

("ds_check_latest", "One row per check on the latest scheduled run. Domain view: "
 "Breaches (widget filter is_breach = 1) and the Rules breaching and P1 counters. "
 "days_failing counts days since the current breach streak began.", f"""
WITH hist AS (
  SELECT k.rule_id, k.run_ts, k.status
  FROM   $Qresults_check_run k JOIN $Qresults_v_scheduled_run r ON r.run_id = k.run_id
),
last_ok AS (SELECT rule_id, MAX(run_ts) AS ok_ts FROM hist WHERE status <> 'breach' GROUP BY rule_id),
since AS (                              -- first breach of the current streak
  SELECT h.rule_id, MIN(h.run_ts) AS failing_since
  FROM   hist h LEFT JOIN last_ok o ON o.rule_id = h.rule_id
  WHERE  h.status = 'breach' AND (o.ok_ts IS NULL OR h.run_ts > o.ok_ts)
  GROUP  BY h.rule_id
),
k AS (
  SELECT c.*, ROW_NUMBER() OVER (PARTITION BY c.rule_id ORDER BY c.result_id) AS n
  FROM   $Qresults_check_run c WHERE c.run_id = {LATEST}
)
SELECT k.run_id, k.run_ts, to_date(from_utc_timestamp(k.run_ts, 'Australia/Sydney')) AS run_day,
       k.rule_id, r.rule_name, r.cde_id, e.cde_name, k.target_table, k.target_column,
       r.rule_type, {DIMENSION} AS dimension,
       k.severity, left(k.severity, 2) AS sev, e.business_domain, r.status AS rule_status,
       k.status AS verdict,
       CASE WHEN k.status = 'breach' THEN 'Breach'
            WHEN k.status = 'skipped' AND r.status = 'shadow' THEN 'Shadow'
            WHEN k.status = 'skipped' THEN 'Skipped'
            WHEN k.status = 'error' THEN 'Error' ELSE 'Pass' END                AS health,
       k.rows_scanned, k.violation_count, k.violation_pct,
       100 - k.violation_pct                                                    AS pass_rate_pct,
       k.threshold_pct, s.failing_since,
       DATEDIFF(to_date(from_utc_timestamp(k.run_ts, 'Australia/Sydney')),
                to_date(from_utc_timestamp(s.failing_since, 'Australia/Sydney'))) + 1 AS days_failing,
       k.message,
       CASE WHEN k.status = 'breach' THEN 1 ELSE 0 END                          AS is_breach,
       CASE WHEN k.status = 'breach' AND k.severity = 'P1_block' THEN 1 ELSE 0 END AS is_p1_breach,
       CASE WHEN r.status = 'active' THEN 1 ELSE 0 END                          AS is_active,
       CASE WHEN r.status = 'active' AND k.status IN ('pass', 'breach') THEN 1 ELSE 0 END AS is_scored
FROM   k
JOIN   $Qconfig_v_rule_registry_current r ON r.rule_id = k.rule_id
LEFT JOIN $Qconfig_v_cde_registry_current e ON e.cde_id = r.cde_id
LEFT JOIN since s ON s.rule_id = k.rule_id
WHERE  k.n = 1 AND r.status <> 'retired'
"""),

("ds_check_history", "One row per scheduled run and active check. Tables: Failed rows per "
 "table over time.", f"""
SELECT r.run_id, r.run_ts, r.run_day, k.rule_id, k.target_table, g.cde_id, e.cde_name,
       k.severity, e.business_domain, k.status AS verdict,
       k.rows_scanned, k.violation_count, k.violation_pct
FROM   $Qresults_check_run k
JOIN   $Qresults_v_scheduled_run r ON r.run_id = k.run_id
JOIN   $Qconfig_v_rule_registry_current g ON g.rule_id = k.rule_id AND g.status = 'active'
LEFT JOIN $Qconfig_v_cde_registry_current e ON e.cde_id = g.cde_id
WHERE  k.status IN ('pass', 'breach')
"""),

("ds_rules", "One row per current rule with its OWN latest measurement, so a shadow rule "
 "shows what it found. Tables: Rules. Pipeline: Shadow rules waiting for promotion.", f"""
WITH m AS (
  SELECT k.rule_id, k.run_ts, k.status, k.rows_scanned, k.violation_count, k.violation_pct,
         LAG(k.violation_pct) OVER (PARTITION BY k.rule_id ORDER BY k.run_ts)    AS previous_pct,
         COUNT(*) OVER (PARTITION BY k.rule_id)                                  AS runs_measured,
         MIN(k.run_ts) OVER (PARTITION BY k.rule_id)                             AS measured_since,
         ROW_NUMBER() OVER (PARTITION BY k.rule_id ORDER BY k.run_ts DESC, k.result_id) AS n
  FROM   $Qresults_check_run k
  WHERE  k.status <> 'error'
)
SELECT r.rule_id, r.rule_name, r.rule_version, r.cde_id, e.cde_name, r.target_table,
       r.target_column, r.rule_type, {DIMENSION} AS dimension, r.severity,
       e.business_domain, r.status AS rule_status, r.fail_threshold_pct,
       r.join_sql IS NOT NULL                                                    AS is_cross_table,
       r.promoted_by, r.promoted_at,
       m.run_ts AS measured_ts, m.status AS verdict, m.rows_scanned, m.violation_count,
       m.violation_pct, m.violation_pct - m.previous_pct                         AS change_pct,
       m.runs_measured, m.measured_since,
       CASE WHEN r.status = 'shadow' AND m.violation_pct > r.fail_threshold_pct
            THEN 1 ELSE 0 END                                                    AS would_breach
FROM   $Qconfig_v_rule_registry_current r
LEFT JOIN $Qconfig_v_cde_registry_current e ON e.cde_id = r.cde_id
LEFT JOIN m ON m.rule_id = r.rule_id AND m.n = 1
WHERE  r.status <> 'retired'
"""),

("ds_table_latest", "One row per selected source table on the latest scheduled run: the "
 "app's Tables page as a dataset. How many key attributes the table carries and how many are "
 "monitored, its active rules, how many pass, breach or are P1, and its rows. The domain "
 "is its key attributes' (the register's), not the monitored table's own label. Domain view: "
 "Monitored tables. Pipeline: Rows each run reads.", f"""
WITH bound AS (                              -- key attributes bound to each table, and their domain
  SELECT target_table, COUNT(DISTINCT cde_id) AS cdes_registered,
         MAX(business_domain)                 AS business_domain
  FROM   $Qresults_v_cde_coverage
  GROUP  BY target_table
),
k AS (
  SELECT c.target_table,
         MAX(c.run_ts)                                                          AS run_ts,
         COUNT(DISTINCT CASE WHEN c.status IN ('pass', 'breach') THEN g.cde_id END) AS cdes_monitored,
         SUM(CASE WHEN c.status IN ('pass', 'breach') THEN 1 ELSE 0 END)        AS active_rules,
         SUM(CASE WHEN c.status = 'pass' THEN 1 ELSE 0 END)                     AS passing,
         SUM(CASE WHEN c.status = 'breach' THEN 1 ELSE 0 END)                   AS breaching,
         SUM(CASE WHEN c.status = 'breach' AND c.severity = 'P1_block' THEN 1 ELSE 0 END) AS p1_breaching,
         SUM(CASE WHEN c.status = 'error' THEN 1 ELSE 0 END)                    AS errors,
         MAX(c.table_rows)                                                      AS table_rows,
         MAX(c.population_rows)                                                 AS current_records,
         MAX(c.slice_rows)                                                      AS slice_rows
  FROM   $Qresults_check_run c
  LEFT JOIN $Qconfig_v_rule_registry_current g ON g.rule_id = c.rule_id
  WHERE  c.run_id = {LATEST}
  GROUP  BY c.target_table
)
SELECT m.target_table, regexp_extract(m.target_table, '([^.]+)$', 1)            AS table_name,
       m.table_code, COALESCE(b.business_domain, m.business_domain)             AS business_domain,
       m.owner_group, k.run_ts,
       COALESCE(b.cdes_registered, 0) AS cdes_registered, COALESCE(k.cdes_monitored, 0) AS cdes_monitored,
       COALESCE(k.active_rules, 0) AS active_rules, k.passing, k.breaching, k.p1_breaching,
       k.errors,
       100.0 * k.passing / NULLIF(k.active_rules, 0)                            AS passing_pct,
       CASE WHEN k.breaching > 0 OR k.errors > 0 THEN 1 ELSE 0 END              AS needs_attention,
       k.table_rows, k.current_records, k.slice_rows
FROM   $Qconfig_v_monitored_table_current m
LEFT JOIN k ON k.target_table = m.target_table
LEFT JOIN bound b ON b.target_table = m.target_table
WHERE  m.status = 'selected'
ORDER  BY k.breaching DESC NULLS LAST, m.target_table
"""),

("ds_problems", "One row per problem (cohort). is_live marks the problems owning a check "
 "that escalates on the latest run, the Triage queue's default. Triage: every problem "
 "widget.", f"""
WITH esc AS (
  SELECT DISTINCT rule_id FROM $Qresults_v_check_escalation
  WHERE  run_id = {LATEST} AND escalates
),
owner AS (                              -- a rule regrouped into a newer problem counts there
  SELECT m.rule_id, MAX_BY(c.cohort_id, c.raised_ts) AS cohort_id
  FROM   $Qresults_v_cohort_for_bi c LATERAL VIEW explode(c.member_rule_ids) m AS rule_id
  GROUP  BY m.rule_id
),
live AS (
  SELECT o.cohort_id, COUNT(*) AS live_checks
  FROM   esc e JOIN owner o ON o.rule_id = e.rule_id
  GROUP  BY o.cohort_id
),
named AS (                              -- the attributes its checks watch, two by name
  SELECT c.cohort_id,
         array_join(slice(array_sort(collect_set(e.cde_name)), 1, 2), ' and ')   AS attributes,
         COUNT(DISTINCT e.cde_id)                                               AS attribute_count
  FROM   (SELECT cohort_id, explode(member_rule_ids) AS rule_id
          FROM   $Qresults_v_cohort_for_bi) c                -- LATERAL VIEW cannot precede a JOIN
  JOIN   $Qconfig_v_rule_registry_current r ON r.rule_id = c.rule_id
  JOIN   $Qconfig_v_cde_registry_current e ON e.cde_id = r.cde_id
  GROUP  BY c.cohort_id
)
SELECT c.cohort_id, c.raised_ts, to_date(from_utc_timestamp(c.raised_ts, 'Australia/Sydney')) AS raised_day,
       c.severity, c.business_domain, c.owner_group,
       concat(COALESCE(n.attributes, array_join(c.affected_tables, ', ')), ' — ',
              CASE c.defect_location WHEN 'data' THEN 'wrong data'
                                     WHEN 'rule' THEN 'rule flags valid rows'
                                     WHEN 'neither' THEN 'needs a business call'
                                     ELSE 'not yet advised' END)                AS problem,
       regexp_extract(c.root_cause_hypothesis, '^[^.:]*', 0)                    AS claim,
       CASE c.defect_location WHEN 'data' THEN 'Wrong data'
                              WHEN 'rule' THEN 'Rule flags valid rows'
                              WHEN 'neither' THEN 'Needs a business call' END   AS verdict,
       c.confidence, c.member_count, c.total_violation_rows, size(c.affected_tables) AS tables,
       v.lifecycle_state,
       CASE WHEN v.lifecycle_state LIKE 'closed%' THEN 1 ELSE 0 END             AS is_closed,
       CASE v.lifecycle_state WHEN 'awaiting_triage' THEN 'the triage job'
                              WHEN 'awaiting_review' THEN 'a steward'
                              WHEN 'awaiting_approval' THEN 'an approver'
                              WHEN 'awaiting_verification' THEN 'the next run'
                              WHEN 'approved_awaiting_execution' THEN c.owner_group
                              WHEN 'reopened' THEN c.owner_group
                              ELSE '—' END                                      AS waiting_on,
       v.distinct_approvers, v.approvals_required, v.review_by_date,
       CASE WHEN v.lifecycle_state NOT LIKE 'closed%'
            THEN datediff(current_date(), to_date(c.raised_ts)) END             AS age_days,
       l.cohort_id IS NOT NULL                                                  AS is_live,
       COALESCE(l.live_checks, 0)                                               AS live_checks,
       c.rank_score
FROM   $Qresults_v_cohort_for_bi c
JOIN   $Qresults_v_cohort_current v ON v.cohort_id = c.cohort_id
LEFT JOIN live l ON l.cohort_id = c.cohort_id
LEFT JOIN named n ON n.cohort_id = c.cohort_id
"""),

("ds_problem_flow", "Problems raised and closed, one row per event. Triage: Raised vs "
 "closed per week.", """
SELECT date_trunc('WEEK', raised_ts) AS week, 'Raised' AS flow, cohort_id, severity,
       business_domain
FROM   $Qresults_v_cohort_current
UNION ALL
SELECT date_trunc('WEEK', CASE WHEN lifecycle_state = 'closed_verified' THEN verified_ts
                               ELSE reviewed_ts END),
       'Closed', cohort_id, severity, business_domain
FROM   $Qresults_v_cohort_current
WHERE  lifecycle_state LIKE 'closed%'
"""),

("ds_resolution", "One row per problem with the flags the resolution counters average. "
 "Triage: Closure rate, MTTR, Disposition coverage, Recurrence, Advice followed, "
 "Decision-record gaps.", """
WITH gaps AS (
  SELECT cohort_id, COUNT(*) AS integrity_gaps
  FROM   $Qresults_v_disposition_integrity
  GROUP  BY cohort_id
)
SELECT v.cohort_id, v.raised_ts, v.severity, v.business_domain,
       CASE WHEN v.lifecycle_state LIKE 'closed%' THEN 1 ELSE 0 END             AS is_closed,
       v.mttr_days,
       CASE WHEN v.lifecycle_state <> 'awaiting_triage'
             AND v.latest_decision IS NOT NULL THEN 1 ELSE 0 END                AS has_decision,
       CASE WHEN c.is_recurrence THEN 1 ELSE 0 END                              AS is_recurrence,
       CASE WHEN v.recommendation_followed THEN 1
            WHEN v.recommendation_followed = FALSE THEN 0 END                   AS advice_followed,
       COALESCE(g.integrity_gaps, 0)                                            AS integrity_gaps
FROM   $Qresults_v_cohort_current v
JOIN   $Qresults_v_cohort_for_bi c ON c.cohort_id = v.cohort_id
LEFT JOIN gaps g ON g.cohort_id = v.cohort_id
"""),

("ds_decisions", "The audit register, one row per event. Triage: Decision log.", """
SELECT d.event_ts, d.cohort_id, c.severity, c.business_domain,
       regexp_extract(c.root_cause_hypothesis, '^[^.:]*', 0)                    AS claim,
       d.event_seq, d.event_type, d.decision, d.actor_display_name, d.actor_identity,
       d.actor_source, d.reason, d.review_by_date, d.approver_ordinal,
       d.violations_before, d.violations_after, d.verification_passed
FROM   $Qresults_disposition d
JOIN   $Qresults_v_cohort_for_bi c ON c.cohort_id = d.cohort_id
"""),

("ds_escalation", "Every breach on the latest scheduled run, escalated or held. Triage: "
 "Held back counter.", f"""
SELECT x.run_id, x.run_ts, x.rule_id, x.severity, x.violation_count, x.rows_scanned,
       x.cde_id, e.cde_name, e.business_domain, x.element_score_pct, x.element_target_pct,
       x.escalates, x.held_reason,
       CASE WHEN x.escalates THEN 0 ELSE 1 END                                  AS is_held
FROM   $Qresults_v_check_escalation x
LEFT JOIN $Qconfig_v_cde_registry_current e ON e.cde_id = x.cde_id
WHERE  x.run_id = {LATEST}
"""),

("ds_run_health", "One row per calendar day of the last 90, with that day's scheduled run "
 "if there was one. Pipeline: Last run, Days without a run, Checks run, Errors, Run time, "
 "Checks per run, Duration and cost.", """
WITH days AS (
  SELECT explode(sequence(date_sub(current_date(), 89), current_date())) AS run_day
),
runs AS (
  SELECT r.run_day, r.run_id, r.run_ts, r.is_latest,
         COUNT(*)                                                               AS checks,
         SUM(CASE WHEN k.status = 'pass' THEN 1 ELSE 0 END)                     AS pass,
         SUM(CASE WHEN k.status = 'breach' THEN 1 ELSE 0 END)                   AS breach,
         SUM(CASE WHEN k.status = 'skipped' THEN 1 ELSE 0 END)                  AS skipped,
         SUM(CASE WHEN k.status = 'error' THEN 1 ELSE 0 END)                    AS errors,
         SUM(k.duration_sec) / 60.0                                             AS duration_min,
         SUM(k.dbu_estimate)                                                    AS dbu_estimate
  FROM   $Qresults_v_scheduled_run r
  JOIN   $Qresults_check_run k ON k.run_id = r.run_id
  GROUP  BY r.run_day, r.run_id, r.run_ts, r.is_latest
)
SELECT d.run_day, r.run_id, r.run_ts, COALESCE(r.is_latest, FALSE) AS is_latest,
       r.checks, r.pass, r.breach, r.skipped, r.errors, r.duration_min, r.dbu_estimate,
       CASE WHEN r.run_id IS NULL THEN 1 ELSE 0 END                             AS no_run,
       -- A counter shows a number, not a date: how stale the latest run is, in hours.
       CASE WHEN r.is_latest
            THEN (unix_timestamp(current_timestamp()) - unix_timestamp(r.run_ts)) / 3600.0
       END                                                                      AS hours_since_run
FROM   days d
LEFT JOIN runs r ON r.run_day = d.run_day
"""),

("ds_run_errors", "Every check that errored on the latest scheduled run, with the "
 "warehouse's message. Pipeline: Errors on the latest run.", f"""
SELECT k.run_ts, k.rule_id, k.target_table, k.severity, k.business_domain, k.message
FROM   $Qresults_check_run k
WHERE  k.run_id = {LATEST} AND k.status = 'error'
"""),

("ds_register_changes", "Every version of a rule, key attribute or monitored table, with "
 "who made it. Pipeline: Register changes, Promotions counter.", """
WITH rules AS (
  SELECT created_at AS changed_ts, 'Rule' AS object, rule_id AS id, rule_version AS version,
         status, created_by AS changed_by, note,
         LAG(status) OVER (PARTITION BY rule_id ORDER BY rule_version)           AS was
  FROM   $Qconfig_rule_registry
),
attrs AS (
  SELECT registered_at AS changed_ts, 'Key attribute' AS object, cde_id AS id,
         cde_version AS version, status, registered_by AS changed_by, note,
         LAG(tolerance_pct) OVER (PARTITION BY cde_id ORDER BY cde_version)      AS was_tol,
         tolerance_pct
  FROM   $Qconfig_cde_registry
)
SELECT changed_ts, object, id, version, status, changed_by, note,
       CASE WHEN version = 1 THEN 'registered'
            WHEN status = 'active' AND was = 'shadow' THEN 'promoted'
            WHEN status = 'retired' AND was <> 'retired' THEN 'retired'
            ELSE 'new version' END                                              AS change,
       CASE WHEN status = 'active' AND was = 'shadow' THEN 1 ELSE 0 END         AS is_promotion
FROM   rules
UNION ALL
SELECT changed_ts, object, id, version, status, changed_by, note,
       CASE WHEN version = 1 THEN 'registered'
            WHEN status = 'retired' THEN 'retired'
            WHEN NOT (tolerance_pct <=> was_tol) THEN 'tolerance'
            ELSE 'new version' END,
       0
FROM   attrs
UNION ALL
SELECT effective_from, 'Table', target_table, table_version, status, selected_by, note,
       CASE WHEN table_version = 1 THEN 'selected' ELSE status END, 0
FROM   $Qconfig_monitored_table
"""),

("ds_tolerance", "The latest tolerance advice per key attribute and where it has got to. "
 "Pipeline: Tolerance advice.", """
SELECT p.cde_id, p.cde_name, p.criticality, e.business_domain, p.proposed_ts,
       p.register_tolerance_pct AS tolerance_pct, p.advice, p.proposed_tolerance_pct,
       p.runs_observed, p.runs_outside, p.latest_fail_pct, p.rationale, p.review_state,
       p.latest_reviewer, p.latest_reason
FROM   $Qresults_v_tolerance_proposal_current p
LEFT JOIN $Qconfig_v_cde_registry_current e ON e.cde_id = p.cde_id
"""),
("ds_exec_weekly", "One row per week (its last scheduled run) with the executive summary's "
 "headline counts. Counters show the latest row and compare it with last week (run_week, "
 "days-ago offset -7). New failures are breaching now and not on last week's run. "
 "A CDE is failing when any of its active rules breaches its own threshold (rule-level "
 "thresholds since 2026-10-22). Executive summary: CDEs under monitoring, CDEs failing, Active "
 "rules, Rules breaching, P1 breaches, New breaches, CDEs not monitored. Whole register: no "
 "filter but Run date.", """
WITH cdes AS (                               -- every key attribute still registered
  SELECT cde_id FROM $Qconfig_v_cde_registry_current WHERE status <> 'retired'
),
runs AS (
  SELECT run_id, run_ts, run_day, run_week, is_latest,
         LAG(run_id) OVER (ORDER BY run_ts)                                     AS prev_run_id
  FROM   (SELECT w.*, CAST(date_trunc('WEEK', w.run_day) AS DATE) AS run_week
        FROM   $Qresults_v_scheduled_run w
        QUALIFY ROW_NUMBER() OVER (PARTITION BY date_trunc('WEEK', w.run_day)
                                   ORDER BY w.run_ts DESC) = 1)
),
checks AS (                             -- pass/breach = an active check that ran
  SELECT k.run_id,
         COUNT(DISTINCT CASE WHEN k.status = 'breach' THEN k.rule_id END)       AS breaching,
         COUNT(DISTINCT CASE WHEN k.status = 'breach' AND k.severity = 'P1_block'
                             THEN k.rule_id END)                                AS p1_failing,
         COUNT(DISTINCT CASE WHEN k.status IN ('pass', 'breach') THEN k.rule_id END) AS active_checks,
         COUNT(DISTINCT CASE WHEN k.status IN ('pass', 'breach') THEN k.target_table END)
                                                                                AS tables_monitored,
         COUNT(DISTINCT CASE WHEN k.status IN ('pass', 'breach') THEN g.cde_id END)
                                                                                AS cdes_monitored,
         COUNT(DISTINCT CASE WHEN k.status = 'breach' THEN g.cde_id END)       AS cdes_failing
  FROM   $Qresults_check_run k
  JOIN   $Qconfig_v_rule_registry_current g ON g.rule_id = k.rule_id
  WHERE  g.cde_id IN (SELECT cde_id FROM cdes)
  GROUP  BY k.run_id
),
registered AS (                         -- the denominator for "CDEs monitored"
  SELECT COUNT(*) AS cdes_registered FROM $Qconfig_v_cde_registry_current
  WHERE  status <> 'retired' AND cde_id IN (SELECT cde_id FROM cdes)
),
new_failures AS (                       -- breaching on this run, not on the run before
  SELECT r.run_id, COUNT(DISTINCT k.rule_id)                                    AS new_failures
  FROM   runs r
  JOIN   $Qresults_check_run k ON k.run_id = r.run_id AND k.status = 'breach'
  JOIN   $Qconfig_v_rule_registry_current g ON g.rule_id = k.rule_id
         AND g.cde_id IN (SELECT cde_id FROM cdes)
  LEFT JOIN $Qresults_check_run p
         ON p.run_id = r.prev_run_id AND p.rule_id = k.rule_id AND p.status = 'breach'
  WHERE  r.prev_run_id IS NOT NULL AND p.rule_id IS NULL
  GROUP  BY r.run_id
)
SELECT r.run_day, r.run_week, r.run_ts, r.is_latest,
       COALESCE(k.cdes_monitored, 0) AS cdes_monitored, g.cdes_registered,
       COALESCE(k.tables_monitored, 0) AS tables_monitored,
       COALESCE(k.active_checks, 0) AS active_checks,
       COALESCE(k.cdes_failing, 0) AS cdes_failing,
       -- registered but no active rule ran on it
       g.cdes_registered - COALESCE(k.cdes_monitored, 0)                        AS cdes_not_monitored,
       COALESCE(k.breaching, 0) AS breaching, COALESCE(k.p1_failing, 0) AS p1_failing,
       COALESCE(n.new_failures, 0) AS new_failures
FROM   runs r
LEFT JOIN checks k ON k.run_id = r.run_id
LEFT JOIN new_failures n ON n.run_id = r.run_id
CROSS JOIN registered g
ORDER  BY r.run_ts DESC
"""),

("ds_domain_scores", "One row per week (its last scheduled run) and business domain: the "
 "domain's score (rows passed over rows checked across its CDEs), its CDEs under monitoring "
 "and failing, and its active and breaching rules. No domain threshold since 2026-10-22. "
 "Executive summary: the Business view tiles, one per domain.", """
WITH cdes AS (                               -- every key attribute still registered
  SELECT cde_id FROM $Qconfig_v_cde_registry_current WHERE status <> 'retired'
),
breaches AS (                           -- per run and CDE: rules that ran, rules over their limit
  SELECT k.run_id, a.cde_id,
         COUNT(DISTINCT k.rule_id)                                              AS rules_ran,
         COUNT(DISTINCT CASE WHEN k.status = 'breach' THEN k.rule_id END)       AS rules_breaching
  FROM   $Qresults_check_run k
  JOIN   (SELECT DISTINCT cv.cde_id, x.rule_id
          FROM   $Qresults_v_cde_coverage cv LATERAL VIEW explode(cv.rule_ids) x AS rule_id) a
         ON a.rule_id = k.rule_id
  WHERE  k.status IN ('pass', 'breach')
  GROUP  BY k.run_id, a.cde_id
),
s AS (
  SELECT t.run_id, c.business_domain, t.cde_id, t.rows_evaluated, t.rows_failed,
         COALESCE(b.rules_ran, 0) AS rules_ran, COALESCE(b.rules_breaching, 0) AS rules_breaching
  FROM   $Qresults_v_element_tolerance t
  JOIN   $Qconfig_v_cde_registry_current c ON c.cde_id = t.cde_id
  LEFT JOIN breaches b ON b.run_id = t.run_id AND b.cde_id = t.cde_id
  WHERE  t.cde_id IN (SELECT cde_id FROM cdes)
)
SELECT r.run_day, r.run_week, r.run_ts, r.is_latest, s.business_domain,
       COUNT(*)                                                                 AS cdes_monitored,
       COUNT_IF(s.rules_breaching > 0)                                          AS cdes_failing,
       SUM(s.rules_ran)                                                         AS active_rules,
       SUM(s.rules_breaching)                                                   AS rules_breaching,
       100.0 * (SUM(s.rows_evaluated) - SUM(s.rows_failed)) / SUM(s.rows_evaluated) AS score_pct
FROM   s
JOIN   (SELECT w.*, CAST(date_trunc('WEEK', w.run_day) AS DATE) AS run_week
        FROM   $Qresults_v_scheduled_run w
        QUALIFY ROW_NUMBER() OVER (PARTITION BY date_trunc('WEEK', w.run_day)
                                   ORDER BY w.run_ts DESC) = 1) r ON r.run_id = s.run_id
GROUP  BY r.run_day, r.run_week, r.run_ts, r.is_latest, s.business_domain
ORDER  BY r.run_ts DESC, s.business_domain
"""),
("ds_dimension_scores", "One row per scheduled run and DQ dimension: rows checked and failed "
 "by the active checks of that dimension, its score, and how many of them breach. Executive "
 "summary's By DQ dimension tiles until 2026-10-21; kept for Genie. No threshold: a threshold belongs to a key attribute, "
 "not to a dimension.", f"""
WITH attached AS (                      -- active rules on a registered key attribute
  SELECT DISTINCT x.rule_id
  FROM   $Qresults_v_cde_coverage cv LATERAL VIEW explode(cv.rule_ids) x AS rule_id
),
k AS (
  SELECT c.run_id, c.rule_id, c.status, c.rows_scanned, c.violation_count,
         ROW_NUMBER() OVER (PARTITION BY c.run_id, c.rule_id ORDER BY c.result_id) AS n
  FROM   $Qresults_check_run c
  WHERE  c.status IN ('pass', 'breach')
),
d AS (
  SELECT k.*, {DIMENSION} AS dimension
  FROM   k
  JOIN   attached a ON a.rule_id = k.rule_id
  JOIN   $Qconfig_v_rule_registry_current r ON r.rule_id = k.rule_id
  WHERE  k.n = 1
)
SELECT s.run_day, s.run_ts, s.is_latest, d.dimension,
       COUNT(*)                                                                 AS checks,
       COUNT_IF(d.status = 'breach')                                            AS checks_breaching,
       SUM(d.rows_scanned)                                                      AS rows_checked,
       SUM(d.violation_count)                                                   AS rows_failed,
       100.0 * (SUM(d.rows_scanned) - SUM(d.violation_count)) / SUM(d.rows_scanned) AS score_pct
FROM   d
JOIN   $Qresults_v_scheduled_run s ON s.run_id = d.run_id
GROUP  BY s.run_day, s.run_ts, s.is_latest, d.dimension
-- Newest first, so a counter per dimension (widget filter dimension = ...) reads row 1.
ORDER  BY s.run_ts DESC, d.dimension
"""),
]


# Stage 1 is the executive and detailed summaries. The rest serve the triage and pipeline
# pages, kept for a later stage; build_production.py writes them to dashboard/later/.
STAGE_1 = ("ds_quality_trend", "ds_element_scores", "ds_coverage", "ds_check_latest",
           "ds_exec_weekly", "ds_domain_scores", "ds_table_latest")


def render(prefix: str) -> list[tuple[str, str, str]]:
    """(name, what, sql) for every dataset, `$Q` replaced by `<catalog>.<schema>.<prefix>`."""
    return [(n, what, sql.replace("$Q", prefix).strip() + "\n") for n, what, sql in DATASETS]

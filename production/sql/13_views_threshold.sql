-- DEPLOY STEP 13 of 16 — copied from sql/ddl/14_views_threshold.sql
-- by tools/build_production.py. Placeholders are NOT substituted.
--
-- Threshold views — where each rule's latest proposal has got to
--
-- Substitute {catalog} before execution. Runs after 13, which creates the tables
-- this reads, and after 08, which creates v_rule_registry_current.
--
-- Same discipline as 08_views.sql: the review state is derived here and NOWHERE
-- ELSE. threshold_review is append-only and threshold_proposal carries no status
-- column, so "what is the standing of this proposal" is a window function over
-- both, not a field. The app's Python twin is dq-app/dq_app/domain/thresholds.py,
-- pinned to this view by a conformance test; change one, run the test.
--
-- NO current_date() HERE, ON PURPOSE. A deferral stays `deferred` and carries its
-- review_by_date; whether that date has passed is the page's to say. A view whose
-- output changes overnight with nothing written cannot be pinned by a test and
-- cannot be reproduced for an auditor.

CREATE OR REPLACE VIEW {catalog}.results.v_threshold_proposal_current
COMMENT 'The latest proposal per rule with its latest review folded in. review_state: no_change (the advice was keep), open (a change nobody has decided), adopted, rejected, deferred (with review_by_date), in_force (the registry already carries the proposed limit, by adoption or otherwise).'
AS
WITH latest_proposal AS (
  SELECT p.*,
         ROW_NUMBER() OVER (PARTITION BY p.rule_id ORDER BY p.proposed_ts DESC, p.proposal_id) AS rn
  FROM   {catalog}.results.threshold_proposal p
),
latest_review AS (
  SELECT r.*,
         ROW_NUMBER() OVER (PARTITION BY r.proposal_id ORDER BY r.event_ts DESC, r.review_id) AS rn
  FROM   {catalog}.results.threshold_review r
)
SELECT
  p.proposal_id,
  p.proposal_run_id,
  p.proposed_ts,
  p.rule_id,
  p.rule_version,
  reg.rule_name,
  reg.rule_type,
  reg.severity,
  reg.owner_group,
  p.cde_id,
  p.target_table,
  p.target_column,
  p.current_threshold_pct,
  p.proposed_threshold_pct,
  reg.fail_threshold_pct                              AS registry_threshold_pct,
  p.tolerance_pct,
  p.basis,
  p.rationale,
  p.reviewer,
  p.runs_observed,
  p.pct_min,
  p.pct_median,
  p.pct_p90,
  p.pct_max,
  p.runs_breaching,
  p.latest_violation_pct,
  p.model_endpoint,
  r.decision                                          AS latest_decision,
  r.event_ts                                          AS latest_review_ts,
  r.actor_display_name                                AS latest_reviewer,
  r.reason                                            AS latest_reason,
  r.review_by_date,
  r.adopted_rule_version,
  CASE
    WHEN p.basis = 'unchanged'                        THEN 'no_change'
    WHEN r.decision = 'adopted'                       THEN 'adopted'
    WHEN r.decision = 'rejected'                      THEN 'rejected'
    WHEN r.decision = 'deferred'                      THEN 'deferred'
    WHEN reg.fail_threshold_pct = p.proposed_threshold_pct THEN 'in_force'
    ELSE                                                   'open'
  END                                                 AS review_state
FROM latest_proposal p
LEFT JOIN latest_review r
  ON  r.proposal_id = p.proposal_id AND r.rn = 1
LEFT JOIN {catalog}.config.v_rule_registry_current reg
  ON  reg.rule_id = p.rule_id
WHERE p.rn = 1;

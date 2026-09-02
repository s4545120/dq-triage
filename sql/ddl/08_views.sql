-- Views — derived state, because none of it is stored
--
-- Substitute {catalog} before execution.
--
-- Two tables in this model deliberately have no status column: the register is an
-- event log, and the registry is append-only. That is the right call for audit and
-- the wrong shape for a UI, which needs to ask "show me open P1 cohorts". These
-- views are the bridge. They are the ONLY place current-state logic should live —
-- if the app computes it in pandas as well, the two will disagree.

-- ---------------------------------------------------------------
-- v_rule_registry_current — the rule as it stands now
-- ---------------------------------------------------------------
-- effective_to is derived rather than stored, so promoting a rule stays an INSERT.

CREATE OR REPLACE VIEW {catalog}.config.v_rule_registry_current
COMMENT 'Latest version of every rule, with effective_to derived from the next version. Query this, not the base table, unless you want rule history.'
AS
WITH versioned AS (
  SELECT
    r.*,
    LEAD(r.effective_from) OVER (PARTITION BY r.rule_id ORDER BY r.rule_version) AS effective_to,
    ROW_NUMBER()           OVER (PARTITION BY r.rule_id ORDER BY r.rule_version DESC) AS rn
  FROM {catalog}.config.rule_registry r
)
SELECT * EXCEPT (rn)
FROM   versioned
WHERE  rn = 1
  AND  status <> 'retired';

-- ---------------------------------------------------------------
-- v_cohort_current — where each cohort has got to
-- ---------------------------------------------------------------
-- Folds the event log into one row per cohort. This is what the Cohort Queue
-- filters and what the Scorecard aggregates.
--
-- lifecycle_state is COMPUTED HERE AND NOWHERE ELSE. It is not a column anyone
-- writes. The precedence below is the whole state machine:
--   a failed verification reopens, and reopening outranks the approval that
--   preceded it, so a reopened cohort returns to the queue rather than sitting
--   closed and wrong.

CREATE OR REPLACE VIEW {catalog}.results.v_cohort_current
COMMENT 'One row per cohort with its derived lifecycle state, approver count and MTTR. Computed from the disposition event log at read time — there is no stored status anywhere.'
AS
WITH ev AS (
  SELECT
    cohort_id,
    MAX(event_seq)                                                                     AS last_seq,
    MAX(CASE WHEN event_type = 'reviewed' THEN event_ts END)                           AS reviewed_ts,
    MAX(CASE WHEN event_type = 'executed' THEN event_ts END)                           AS executed_ts,
    MAX(CASE WHEN event_type = 'verified' THEN event_ts END)                           AS verified_ts,
    COUNT_IF(event_type = 'approved')                                                  AS approval_rows,
    COUNT(DISTINCT CASE WHEN event_type = 'approved' THEN actor_identity END)          AS distinct_approvers,
    COUNT_IF(event_type = 'reopened')                                                  AS reopen_count,
    MAX_BY(decision,  CASE WHEN event_type = 'reviewed' THEN event_seq END)            AS latest_decision,
    MAX_BY(reason,    CASE WHEN event_type = 'reviewed' THEN event_seq END)            AS latest_reason,
    MAX_BY(review_by_date, CASE WHEN event_type = 'reviewed' THEN event_seq END)       AS review_by_date,
    MAX_BY(actor_identity, CASE WHEN event_type = 'reviewed' THEN event_seq END)       AS reviewed_by,
    MAX_BY(verification_passed, CASE WHEN event_type = 'verified' THEN event_seq END)  AS last_verification_passed,
    MAX_BY(violations_before,   CASE WHEN event_type = 'verified' THEN event_seq END)  AS violations_before,
    MAX_BY(violations_after,    CASE WHEN event_type = 'verified' THEN event_seq END)  AS violations_after,
    MAX_BY(approach_type_taken, CASE WHEN event_type = 'executed' THEN event_seq END)  AS approach_type_taken,
    MAX_BY(event_type, event_seq)                                                      AS last_event_type
  FROM {catalog}.results.disposition
  GROUP BY cohort_id
)
SELECT
  c.cohort_id,
  c.raised_ts,
  c.severity,
  c.business_domain,
  c.owner_group,
  c.member_count,
  c.affected_tables,
  c.total_violation_rows,
  c.root_cause_hypothesis,
  c.recommended_approach,
  c.recommended_approach_type,
  c.recommendation_source,
  c.rank_score,

  CASE
    WHEN ev.cohort_id IS NULL                                        THEN 'awaiting_triage'
    WHEN ev.last_verification_passed = TRUE                          THEN 'closed_verified'
    WHEN ev.reopen_count > 0
     AND ev.last_event_type IN ('reopened', 'verified')              THEN 'reopened'
    WHEN ev.latest_decision = 'rejected'                             THEN 'closed_rejected'
    WHEN ev.latest_decision = 'no_action'                            THEN 'closed_no_action'
    WHEN ev.latest_decision = 'deferred'                             THEN 'deferred'
    WHEN ev.executed_ts IS NOT NULL                                  THEN 'awaiting_verification'
    WHEN ev.distinct_approvers >= CASE WHEN c.severity = 'P1_block' THEN 2 ELSE 1 END
                                                                     THEN 'approved_awaiting_execution'
    WHEN ev.latest_decision = 'accepted'                             THEN 'awaiting_approval'
    ELSE                                                                  'awaiting_review'
  END                                                                AS lifecycle_state,

  ev.distinct_approvers,
  CASE WHEN c.severity = 'P1_block' THEN 2 ELSE 1 END                AS approvals_required,
  ev.reopen_count,
  ev.latest_decision,
  ev.latest_reason,
  ev.review_by_date,
  ev.reviewed_by,
  ev.reviewed_ts,
  ev.executed_ts,
  ev.verified_ts,
  ev.violations_before,
  ev.violations_after,
  ev.approach_type_taken,

  -- Recommendation acceptance: did the steward do what was recommended?
  CASE WHEN ev.approach_type_taken IS NULL THEN NULL
       ELSE ev.approach_type_taken = c.recommended_approach_type END AS recommendation_followed,

  -- MTTR clock: raised -> verified closed. NULL until it actually closes, so a
  -- cohort nobody touched cannot flatter the average by being excluded silently —
  -- report it alongside disposition coverage, never on its own.
  CASE WHEN ev.last_verification_passed = TRUE
       THEN datediff(SECOND, c.raised_ts, ev.verified_ts) / 86400.0 END AS mttr_days
FROM {catalog}.results.cohort c
LEFT JOIN ev ON ev.cohort_id = c.cohort_id;

-- ---------------------------------------------------------------
-- v_disposition_integrity — the control test
-- ---------------------------------------------------------------
-- Every row this returns is a control failure. Schedule it; alert on non-empty.
-- See the note at the foot of 06 for why this cannot be a table constraint.

CREATE OR REPLACE VIEW {catalog}.results.v_disposition_integrity
COMMENT 'Control test over the register. A non-empty result is a control failure, not a warning. Distinct-approver enforcement cannot be a CHECK constraint because it is a property of a set of rows.'
AS
-- Approved on too few DISTINCT identities (the same person approving twice).
SELECT
  c.cohort_id,
  'insufficient_distinct_approvers' AS finding,
  concat('severity ', c.severity, ' requires ',
         CAST(CASE WHEN c.severity = 'P1_block' THEN 2 ELSE 1 END AS STRING),
         ' distinct approvers, found ',
         CAST(COUNT(DISTINCT d.actor_identity) AS STRING),
         ' across ', CAST(COUNT(*) AS STRING), ' approval rows') AS detail
FROM {catalog}.results.cohort c
JOIN {catalog}.results.disposition d
  ON d.cohort_id = c.cohort_id AND d.event_type = 'approved'
GROUP BY c.cohort_id, c.severity
HAVING COUNT(DISTINCT d.actor_identity) < CASE WHEN c.severity = 'P1_block' THEN 2 ELSE 1 END

UNION ALL

-- Execution recorded without the approval that should have preceded it.
SELECT
  d.cohort_id,
  'executed_without_approval',
  concat('executed at ', CAST(MIN(d.event_ts) AS STRING), ' with no prior approved event')
FROM {catalog}.results.disposition d
WHERE d.event_type = 'executed'
  AND NOT EXISTS (
    SELECT 1 FROM {catalog}.results.disposition a
    WHERE a.cohort_id = d.cohort_id
      AND a.event_type = 'approved'
      AND a.event_seq  < d.event_seq)
GROUP BY d.cohort_id

UNION ALL

-- An in-app event whose identity did not come from the platform.
SELECT
  d.cohort_id,
  'identity_not_from_platform',
  concat(d.event_type, ' at seq ', CAST(d.event_seq AS STRING),
         ' has actor_source = ', COALESCE(d.actor_source, 'NULL'))
FROM {catalog}.results.disposition d
WHERE d.event_type IN ('reviewed', 'approved', 'executed')
  AND (d.actor_source <> 'obo_user' OR d.actor_identity IS NULL)

UNION ALL

-- A cohort that exists but was never even recommended — the triage job failed to
-- open the chain, so nothing downstream can be trusted for it.
SELECT
  c.cohort_id,
  'missing_recommended_event',
  'cohort has no recommended event opening its chain'
FROM {catalog}.results.cohort c
WHERE NOT EXISTS (
  SELECT 1 FROM {catalog}.results.disposition d
  WHERE d.cohort_id = c.cohort_id AND d.event_type = 'recommended');

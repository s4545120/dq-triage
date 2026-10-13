-- Consistency checks proposed in the app — a check across two tables, written from a
-- spec, decided by a second person, written to the rule register by the job
--
-- Substitute {catalog} before execution. Runs after 01 (the view reads rule_registry).
--
-- WHAT THIS IS (2026-10-13). The Consistency page's "New check" builder writes a check
-- as a SPEC: kind, tables, key columns, compared columns, policies -- structured fields,
-- never SQL a person typed. A second person approves or rejects it. Then
-- `onboard.py apply_consistency` renders the spec with onboarding/consistency.py and
-- writes the rule to config.rule_registry IN SHADOW. Promotion is the usual decision on
-- the Rules page. Same shape as a binding and a key-attribute change.
--
-- TWO APP WRITES, THE TENTH AND ELEVENTH, AND A DECISION, NOT A DEPLOY. 07_grants.sql
-- names them. The rule register is not one of them: no app writes a consistency rule.
--
-- WHAT IS STORED AS WELL AS THE SPEC. The rule the app rendered (join_sql, rule_expr,
-- scope_filter), so the reviewer approves exactly what will run and the job can refuse a
-- spec it renders differently; the logic fingerprint, so a duplicate is refused; and what
-- the proposer's test measured, so the review can set it beside a test run now.
--
-- APPEND-ONLY. A proposal is never edited: a changed mind is a new proposal. A proposal
-- has at most one decision.

CREATE TABLE IF NOT EXISTS {catalog}.config.consistency_proposal (
  proposal_id      STRING    NOT NULL COMMENT 'uuid',
  proposed_at      TIMESTAMP NOT NULL,
  rule_id          STRING    NOT NULL COMMENT 'the id the rule will carry, assigned now so the review names it. CS_ + 8 hex',
  rule_name        STRING    NOT NULL,
  kind             STRING    NOT NULL COMMENT 'orphan | agreement | totals -- shown as Missing record / Same value / Same total',
  spec             STRING    NOT NULL COMMENT 'the check as JSON, see onboarding/consistency.py. The source of truth: the job renders the rule from it',
  target_table     STRING    NOT NULL COMMENT 'the table a failure is reported against',
  other_tables     ARRAY<STRING> NOT NULL COMMENT 'every other table the check reads',
  cde_id           STRING    NOT NULL COMMENT 'the key attribute the rule names',
  severity         STRING    NOT NULL,
  rule_type        STRING    NOT NULL,
  target_column    STRING,
  join_sql         STRING    NOT NULL COMMENT 'as the app rendered it from the spec',
  rule_expr        STRING    NOT NULL,
  scope_filter     STRING,
  fingerprint      STRING    NOT NULL COMMENT 'onboarding/consistency.fingerprint of the rendered rule',
  test_compared    BIGINT             COMMENT 'rows (groups, for totals) the proposer''s test compared. NULL: not tested (no warehouse)',
  test_failing     BIGINT,
  test_match_pct   DOUBLE             COMMENT 'lowest share of rows finding a match across the links. NULL for totals or untested',
  test_fanout      BIGINT             COMMENT 'keys matching more than one record, summed over the links. The proposer acknowledged it when non-zero',
  proposed_by      STRING    NOT NULL,
  reason           STRING    NOT NULL COMMENT 'why this check'
)
USING DELTA
CLUSTER BY (proposal_id)
COMMENT 'A consistency check proposed in the app, as a spec. The rule register is written by the onboarding job once a second person approves. Append-only.'
TBLPROPERTIES (delta.appendOnly = true);

ALTER TABLE {catalog}.config.consistency_proposal
  ADD CONSTRAINT consistency_proposal_kind_enum
  CHECK (kind IN ('orphan', 'agreement', 'totals'));

ALTER TABLE {catalog}.config.consistency_proposal
  ADD CONSTRAINT consistency_proposal_severity_enum
  CHECK (severity IN ('P1_block', 'P2_alert', 'P3_monitor'));

ALTER TABLE {catalog}.config.consistency_proposal
  ADD CONSTRAINT consistency_proposal_has_reason
  CHECK (length(trim(reason)) > 0 AND length(trim(rule_name)) > 0);

ALTER TABLE {catalog}.config.consistency_proposal
  ADD CONSTRAINT consistency_proposal_signed_by_a_person
  CHECK (proposed_by NOT LIKE 'job:%');

ALTER TABLE {catalog}.config.consistency_proposal
  ADD CONSTRAINT consistency_proposal_rule_id_shape
  CHECK (rule_id RLIKE '^CS_[0-9A-F]{8}$');

CREATE TABLE IF NOT EXISTS {catalog}.config.consistency_review (
  proposal_id   STRING    NOT NULL,
  decision      STRING    NOT NULL COMMENT 'approved | rejected',
  reviewed_by   STRING    NOT NULL,
  reviewed_at   TIMESTAMP NOT NULL,
  reason        STRING             COMMENT 'required to reject. A waived self-approval starts [second approver waived]',
  test_compared BIGINT             COMMENT 'what the test measured when the reviewer opened the proposal. NULL: not tested',
  test_failing  BIGINT
)
USING DELTA
CLUSTER BY (proposal_id)
COMMENT 'A second person deciding a consistency proposal. One decision per proposal. Append-only.'
TBLPROPERTIES (delta.appendOnly = true);

ALTER TABLE {catalog}.config.consistency_review
  ADD CONSTRAINT consistency_review_decision_enum
  CHECK (decision IN ('approved', 'rejected'));

ALTER TABLE {catalog}.config.consistency_review
  ADD CONSTRAINT consistency_review_rejection_has_reason
  CHECK (decision <> 'rejected' OR length(trim(reason)) > 0);

ALTER TABLE {catalog}.config.consistency_review
  ADD CONSTRAINT consistency_review_signed_by_a_person
  CHECK (reviewed_by NOT LIKE 'job:%');

-- Where a proposal has got to. `applied` is read off the rule register: the job starts
-- the note of the version it writes with `[consistency_proposal <id>]`.
-- dq_app/domain/consistency.proposal_state is the labelled copy.
CREATE OR REPLACE VIEW {catalog}.config.v_consistency_proposal_current AS
SELECT p.*,
       r.decision, r.reviewed_by, r.reviewed_at, r.reason AS review_reason,
       r.test_compared AS review_test_compared, r.test_failing AS review_test_failing,
       CASE WHEN r.decision = 'rejected' THEN 'rejected'
            WHEN r.decision = 'approved' AND EXISTS (
                   SELECT 1 FROM {catalog}.config.rule_registry x
                   WHERE  x.rule_id = p.rule_id
                     AND  x.note LIKE concat('[consistency_proposal ', p.proposal_id, ']%'))
                 THEN 'applied'
            WHEN r.decision = 'approved' THEN 'approved'
            ELSE 'open' END AS state
FROM   {catalog}.config.consistency_proposal p
LEFT JOIN {catalog}.config.consistency_review r ON r.proposal_id = p.proposal_id;

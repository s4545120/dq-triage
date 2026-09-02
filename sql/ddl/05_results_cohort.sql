-- cohort — grouped breaches, one root-cause hypothesis, one recommendation
--
-- Substitute {catalog} before execution.
--
-- The first of the two new tables. Written by the triage job (L4), read by the
-- queue, the workbench and the scorecard. The app never writes it.
--
-- MEMBERS ARE AN ARRAY, NOT A BRIDGE TABLE. The spec budgets "two new tables"; a
-- cohort_member bridge would make it three. The array is queryable in Delta
-- (explode / array_contains) and cohorts are small — tens of members, not
-- thousands. Revisit only if members need attributes of their own.
--
-- EVERYTHING THE MODEL PRODUCED IS LABELLED AS SUCH. root_cause_hypothesis is a
-- hypothesis and the UI must render it as one. recommendation_source distinguishes
-- a playbook entry from a drafted suggestion, which the spec requires be "clearly
-- labelled as generated". model_input_payload stores what the endpoint was shown,
-- because the parent architecture doc requires every AI output be stored with its
-- input for audit.
--
-- A COHORT IS NOT A STATUS. There is no state column here. Where a cohort has got
-- to is derived from the disposition event log — see 08_views.sql. Adding a status
-- column here would create a second source of truth that can disagree with the
-- register, which is the failure mode the append-only design exists to prevent.

CREATE TABLE IF NOT EXISTS {catalog}.results.cohort (
  cohort_id            STRING    NOT NULL COMMENT 'uuid, stable for the life of the cohort',
  raised_run_id        STRING    NOT NULL COMMENT 'the check run whose breaches formed this cohort',
  raised_ts            TIMESTAMP NOT NULL COMMENT 'when the triage job raised it — the start of the MTTR clock',
  member_result_ids    ARRAY<STRING> NOT NULL COMMENT 'check_run.result_id for every breach in this cohort',
  member_rule_ids      ARRAY<STRING> NOT NULL COMMENT 'distinct rule_ids, denormalised for filtering without an explode',
  member_count         INT       NOT NULL COMMENT 'size of member_result_ids — the numerator of cohort compression',
  affected_tables      ARRAY<STRING> NOT NULL COMMENT 'distinct target_tables across members',
  total_violation_rows BIGINT             COMMENT 'sum of member violation_counts; rows may be double-counted across rules, so this is an indicator not a total',
  root_cause_hypothesis STRING            COMMENT 'the agents proposed cause. A HYPOTHESIS — the UI must not render it as a finding',
  evidence_summary     STRING             COMMENT 'what in the data led to the hypothesis, so a steward can confirm or discard quickly',
  blast_radius_tables  ARRAY<STRING>      COMMENT 'downstream tables from Unity Catalog lineage, beyond those directly breached',
  blast_radius_count   INT                COMMENT 'size of blast_radius_tables, denormalised for ranking',
  severity             STRING    NOT NULL COMMENT 'highest severity among members; drives the approver count in the register',
  business_domain      STRING             COMMENT 'owning domain',
  owner_group          STRING             COMMENT 'accountable team',
  rank_score           DOUBLE             COMMENT 'triage ranking, higher first. Advisory — a steward can work the queue in any order',
  recommended_approach STRING             COMMENT 'the approach to take, in prose',
  recommended_approach_type STRING        COMMENT 'pipeline_rerun | upstream_ticket | source_correction | manual_sql | accept_and_document',
  playbook_id          STRING             COMMENT 'the playbook entry used; NULL when the recommendation was drafted',
  recommendation_source STRING   NOT NULL COMMENT 'playbook | generated | none. generated MUST be surfaced as generated in the UI',
  model_endpoint       STRING             COMMENT 'which serving endpoint produced this, for reproducibility',
  model_input_payload  STRING             COMMENT 'JSON of exactly what the endpoint was shown — required for audit by the parent architecture doc',
  triage_job_run_id    STRING             COMMENT 'the Lakeflow run that produced this row',
  is_recurrence        BOOLEAN            COMMENT 'the triage jobs assertion that a member rule re-cohorted within 30 days of a verified close. An ASSERTION, not the metric: the scorecard recomputes recurrence from the disposition register, and a disagreement between the two means the triage jobs recurrence window is wrong'
)
USING DELTA
CLUSTER BY (raised_ts, severity)
COMMENT 'One row per problem, not per breach. Written by the triage job. Carries no status — where a cohort has got to lives in the disposition register.';

ALTER TABLE {catalog}.results.cohort
  ADD CONSTRAINT cohort_severity_enum
  CHECK (severity IN ('P1_block', 'P2_alert', 'P3_monitor'));

ALTER TABLE {catalog}.results.cohort
  ADD CONSTRAINT cohort_recommendation_source_enum
  CHECK (recommendation_source IN ('playbook', 'generated', 'none'));

-- A cohort with no members is a triage-job defect, not a valid row.
ALTER TABLE {catalog}.results.cohort
  ADD CONSTRAINT cohort_has_members
  CHECK (member_count >= 1);

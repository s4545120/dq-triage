-- playbook — remediation APPROACHES as reference material
--
-- Substitute {catalog} before execution.
--
-- READ THIS BEFORE ADDING A COLUMN. There is deliberately no `fix_body`, no
-- `fix_sql`, no `job_id` and no `notebook_path`. The spec calls the playbook
-- "documentation, not a runtime" and executing fixes is the programme's defining
-- non-goal. A body column is the first step to an execute button, and an execute
-- button reopens the control question that keeping execution out was meant to close.
-- If someone asks for one, that is a scope change to escalate, not a schema change.
--
-- prior_use_count and recurrence_rate are maintained by the triage job from the
-- disposition register — they are derived, denormalised here so the workbench can
-- show "this approach has been used 14 times and recurred 3 times" without a join
-- at render time.

CREATE TABLE IF NOT EXISTS {catalog}.config.playbook (
  playbook_id      STRING    NOT NULL COMMENT 'stable identifier, e.g. PB_UPSTREAM_CRM_EXPORT',
  rule_id          STRING             COMMENT 'rule this approach applies to; NULL for approaches that apply by rule_type instead',
  rule_type        STRING             COMMENT 'applies to any rule of this type where rule_id is NULL',
  approach_name    STRING    NOT NULL COMMENT 'short name shown as the recommendation heading',
  approach_type    STRING    NOT NULL COMMENT 'pipeline_rerun | upstream_ticket | source_correction | manual_sql | accept_and_document',
  description      STRING    NOT NULL COMMENT 'what to do, in prose, for a human to carry out in their own change process',
  typical_owner    STRING             COMMENT 'who usually carries this out — a team, not a person',
  prior_use_count  INT                COMMENT 'derived: times this approach was the recorded action on a closed cohort',
  recurrence_count INT                COMMENT 'derived: times a cohort closed with this approach re-cohorted within 30 days',
  recurrence_rate  DOUBLE             COMMENT 'derived: recurrence_count / prior_use_count. High means this approach patches symptoms',
  last_used_ts     TIMESTAMP          COMMENT 'derived: most recent close using this approach',
  status           STRING    NOT NULL COMMENT 'active | deprecated',
  created_by       STRING             COMMENT 'authoring identity',
  created_at       TIMESTAMP          COMMENT 'when authored'
)
USING DELTA
CLUSTER BY (rule_id)
COMMENT 'Rule-to-approach reference material. Non-executable by design — see the header note before adding any column that holds runnable content.';

ALTER TABLE {catalog}.config.playbook
  ADD CONSTRAINT playbook_approach_type_enum
  CHECK (approach_type IN ('pipeline_rerun', 'upstream_ticket', 'source_correction', 'manual_sql', 'accept_and_document'));

-- An approach must attach to something: a specific rule or a rule_type, not neither.
ALTER TABLE {catalog}.config.playbook
  ADD CONSTRAINT playbook_has_target
  CHECK (rule_id IS NOT NULL OR rule_type IS NOT NULL);

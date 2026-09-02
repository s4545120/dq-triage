-- rule_registry — what we check
--
-- Versioned source of truth for the schema contract. See dq-triage-agent-spec.md.
-- Substitute {catalog} before execution.
--
-- Ownership boundary: this repo owns the SHAPE of the table. Databricks owns its
-- CONTENTS — rule rows are inserted at runtime, never checked in here.
--
-- APPEND-ONLY, LIKE THE REGISTER. A rule is never edited in place. Promoting a
-- shadow rule to active, or changing a threshold, INSERTS a new (rule_id,
-- rule_version) row. There is deliberately no stored effective_to: closing the
-- prior row would require an UPDATE, which would force a broader grant on the app's
-- service principal and break the uniform "the app only ever appends" story.
-- effective_to is derived with LEAD() in v_rule_registry_current (08_views.sql).
--
-- The current version of a rule is the highest rule_version per rule_id. Retiring a
-- rule is an insert with status = 'retired', not a delete.
--
-- SCOPE_FILTER IS NOT OPTIONAL POLISH. Profiling the pilot data found 900 breaches
-- that were legitimate product variation: Fixed Broadband rows have no IMEI or SIM,
-- prepaid rows have no billing account. A not-null rule without a scope_filter
-- reports those as defects and destroys cohort precision. Treat a NULL scope_filter
-- on a column that is conditionally populated as a rule-authoring defect.

CREATE TABLE IF NOT EXISTS {catalog}.config.rule_registry (
  rule_id            STRING    NOT NULL COMMENT 'stable identifier, survives versioning, e.g. CTCT_EML_FMT',
  rule_version       INT       NOT NULL COMMENT 'incremented on every change; (rule_id, rule_version) is the logical key',
  rule_name          STRING    NOT NULL COMMENT 'human-readable, shown in the queue and scorecard',
  target_table       STRING    NOT NULL COMMENT 'catalog.schema.table being checked',
  target_column      STRING             COMMENT 'NULL for table-level and cross-table rules',
  rule_type          STRING    NOT NULL COMMENT 'not_null | format | uniqueness | consistency | referential | sentinel | variance | freshness | volume',
  rule_expr          STRING    NOT NULL COMMENT 'SQL boolean expression that is TRUE for a VIOLATING row; the check runner counts where this holds',
  scope_filter       STRING             COMMENT 'SQL predicate narrowing the rows in scope, e.g. PROD_TYPE_KEY <> 0. NULL means the whole table — see header note',
  fail_threshold_pct DOUBLE    NOT NULL COMMENT 'violation_pct at or above which the run is a breach; 0.0 means any violation breaches',
  severity           STRING    NOT NULL COMMENT 'P1_block | P2_alert | P3_monitor — drives the approver count in the disposition register',
  business_domain    STRING             COMMENT 'owning domain, used for scorecard breakout',
  owner_group        STRING             COMMENT 'accountable team; ideally a Databricks group name so it resolves to people',
  source_layer       STRING             COMMENT 'L0 | L1 | L2 | L3 — which detection layer emits this rule, from the parent architecture doc',
  status             STRING    NOT NULL COMMENT 'shadow | active | retired. Shadow rules are measured but never raise a cohort',
  effective_from     TIMESTAMP NOT NULL COMMENT 'when this version took effect. There is no effective_to — it is derived, see header',
  created_by         STRING             COMMENT 'authoring identity, from OBO where the app wrote the row',
  created_at         TIMESTAMP          COMMENT 'when this version was authored',
  promoted_by        STRING             COMMENT 'identity that promoted shadow -> active; NULL while shadow. Spec Open Question: who is authorised to do this is unspecified',
  promoted_at        TIMESTAMP          COMMENT 'when the promotion happened',
  note               STRING             COMMENT 'why this rule exists or why this version changed. Free text, read by humans in the Rule Registry Studio; the place to record that a scope_filter was added and what it excludes'
)
USING DELTA
CLUSTER BY (target_table, rule_id)
COMMENT 'The rule registry. Rows, not files — this is what lets a rule be promoted with an INSERT rather than a pull request and a redeploy. Append-only so the app never needs UPDATE on anything.'
TBLPROPERTIES (delta.appendOnly = true);

ALTER TABLE {catalog}.config.rule_registry
  ADD CONSTRAINT rule_registry_severity_enum
  CHECK (severity IN ('P1_block', 'P2_alert', 'P3_monitor'));

ALTER TABLE {catalog}.config.rule_registry
  ADD CONSTRAINT rule_registry_status_enum
  CHECK (status IN ('shadow', 'active', 'retired'));

ALTER TABLE {catalog}.config.rule_registry
  ADD CONSTRAINT rule_registry_version_positive
  CHECK (rule_version >= 1);

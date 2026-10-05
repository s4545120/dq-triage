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
-- JOIN_SQL EXISTS BECAUSE A CROSS-TABLE RULE HAS NO SINGLE TARGET_TABLE. A rule
-- comparing a subscription's first name with its contact's needs both tables and the
-- key that relates them, and target_table can name only one. Before this column the
-- three cross-table rules in the pilot carried their joins in Python -- real, correct,
-- and invisible to Databricks -- so the registry could describe them but nothing
-- reading the registry could run them. That was the gap; this is the fix.
--
-- WHAT IT HOLDS, AND WHAT IT DELIBERATELY DOES NOT. Everything that would follow the
-- word FROM: the joined table expression, its aliases, and the ON condition. NOT a
-- whole SELECT, and NOT the predicate. rule_expr remains the predicate and refers to
-- the aliases join_sql introduces, so the thing that decides what counts as a
-- violation is stored exactly once. The earlier Python version stored a full SELECT
-- with its own WHERE, which meant every cross-table rule held two copies of its
-- predicate that nothing kept in step.
--
-- target_table STAYS NOT NULL on a cross-table rule and names the DRIVING table --
-- the one whose rows the verdict counts. The runner reads join_sql in place of it
-- when building the query, but check_run, the scorecard and lineage all need a single
-- table to attribute a breach to, and "it is a join" is not an answer a steward can
-- act on.
--
-- SAME TRUST BOUNDARY AS rule_expr. This is SQL, interpolated into a query, and that
-- is the point: the registry is trusted config, authored by stewards and append-only.
-- It is not user input and must never be fed from one.

-- A RULE NAMES ITS ELEMENT, SINCE 2026-09-28. cde_id is NOT NULL. Before, a rule
-- attached to an element by column match or by an optional tag, 14 of 34 attached to
-- nothing, and the quality score and the coverage view had a different denominator
-- from the check runner. Now the register is the worklist: the runner executes the
-- active rules whose element is registered, and a column nobody has declared an
-- element for is a column nobody is monitoring -- which is what "registration
-- precedes discovery" was always supposed to mean. In a workspace seeded before this
-- date the column is nullable and sql/out/migrate_cde_scope.sql fills it with a new
-- rule_version per rule; the verification query there asserts no current active rule
-- is left without one.
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
  cde_id             STRING    NOT NULL COMMENT 'the critical data element this rule monitors, from config.cde_registry. NOT NULL since 2026-09-28: DQ runs on registered elements, so a rule names its element or it is not a monitoring rule. Where the rule has a target_column it must be a bound column of that element; a cross-table rule (target_column NULL) attaches to every binding of it. v_cde_coverage joins on this, narrowed by the column where there is one -- no longer on a column match alone'
  rule_type          STRING    NOT NULL COMMENT 'not_null | format | uniqueness | consistency | referential | sentinel | variance | freshness | volume',
  rule_expr          STRING    NOT NULL COMMENT 'SQL boolean expression that is TRUE for a VIOLATING row; the check runner counts where this holds',
  scope_filter       STRING             COMMENT 'SQL predicate narrowing the rows in scope, e.g. PROD_TYPE_KEY <> 0. NULL means the whole table — see header note',
  join_sql           STRING             COMMENT 'For a cross-table rule: the FROM-clause body the check runner reads instead of target_table — the joined table expression with its aliases and ON condition, e.g. "prod.customer.subs_c s JOIN prod.customer.ctct_c c ON s.CTCT_KEY = c.CTCT_KEY". NOT a full SELECT: rule_expr stays the predicate and references these aliases, so the predicate is stored once. NULL for every single-table rule, which is almost all of them — see header note',
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
  note               STRING             COMMENT 'why this rule exists or why this version changed. Free text, read by humans in the Rule Registry Studio; the place to record that a scope_filter was added and what it excludes',
  -- Last, not beside the other identity columns: ALTER TABLE ADD COLUMN appends at the
  -- end, so this is where they sit on every table that predates them, and a positional
  -- INSERT written against this file must line up with those tables too.
  template_id        STRING             COMMENT 'set when the onboarding generator wrote this rule from config.check_template; NULL for a hand-written rule. A column that already has hand-written rules is never given template rules',
  template_version   INT                COMMENT 'the template version the rule was generated from; NULL exactly when template_id is'
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

ALTER TABLE {catalog}.config.rule_registry
  ADD CONSTRAINT rule_registry_template_versioned
  CHECK ((template_id IS NULL) = (template_version IS NULL));

-- check_run — every verdict, one row per rule per run
--
-- Substitute {catalog} before execution.
--
-- Written by the check runner (Phase 1), read by everything else. The triage job
-- reads it to form cohorts; verification reads it to decide whether a cohort closes.
-- The app never writes it.
--
-- VERIFICATION SCOPE. `scope_fingerprint` exists to answer the spec's open
-- engineering question — how a cohort's verification is compared like-for-like once
-- the underlying partition has moved on. The intent is a hash of (scope_filter,
-- partition bounds, rows_scanned band) so a later run can be judged comparable or
-- not. THE HASHING RULE IS NOT DECIDED. The column is here so adding it later is not
-- a schema migration; until the question is answered, write NULL and have
-- verification fall back to comparing rule_id + target_table alone, which is what
-- the fixture generator does.
--
-- CLUSTER BY (run_ts, rule_id): the two dominant reads are "the latest run" for the
-- queue and "this rule's history" for recurrence and volume baselines.

CREATE TABLE IF NOT EXISTS {catalog}.results.check_run (
  result_id         STRING    NOT NULL COMMENT 'uuid, unique per verdict — this is what a cohort references as a member breach',
  run_id            STRING    NOT NULL COMMENT 'groups every verdict produced by one scheduled pass',
  run_ts            TIMESTAMP NOT NULL COMMENT 'start of the run',
  rule_id           STRING    NOT NULL COMMENT 'the rule evaluated',
  rule_version      INT       NOT NULL COMMENT 'the version evaluated; pins the verdict to the threshold in force at the time',
  source_layer      STRING             COMMENT 'denormalised from the registry so layer coverage is a single-table query',
  target_table      STRING    NOT NULL COMMENT 'catalog.schema.table that was checked',
  target_column     STRING             COMMENT 'NULL for table-level and cross-table rules',
  rows_scanned      BIGINT             COMMENT 'rows in scope after scope_filter — the denominator for violation_pct',
  violation_count   BIGINT             COMMENT 'rows where rule_expr held',
  violation_pct     DOUBLE             COMMENT 'violation_count / rows_scanned * 100',
  threshold_pct     DOUBLE             COMMENT 'fail_threshold_pct in force at run time, copied from the registry — never recomputed',
  status            STRING    NOT NULL COMMENT 'pass | breach | error | skipped. skipped is a real state (shadow rule, or scope empty), not a failure',
  severity          STRING    NOT NULL COMMENT 'copied verbatim from the registry at run time; never computed or adjusted downstream',
  business_domain   STRING             COMMENT 'denormalised from the registry for scorecard breakout',
  owner_group       STRING             COMMENT 'denormalised from the registry',
  scope_fingerprint STRING             COMMENT 'pins the comparison scope for verification — see header note. Write NULL until the hashing rule is decided',
  message           STRING             COMMENT 'human-readable, e.g. "81 of 1000 rows have no @ in EML_ID, limit 0.0%"',
  duration_sec      DOUBLE             COMMENT 'wall time for this check',
  dbu_estimate      DOUBLE             COMMENT 'rough cost attribution, used to argue about rule economics'
)
USING DELTA
CLUSTER BY (run_ts, rule_id)
COMMENT 'The verdict layer. Single auditable source of truth for what is broken and how severely. Written only by the check runner; the app reads it and never writes.';

ALTER TABLE {catalog}.results.check_run
  ADD CONSTRAINT check_run_status_enum
  CHECK (status IN ('pass', 'breach', 'error', 'skipped'));

ALTER TABLE {catalog}.results.check_run
  ADD CONSTRAINT check_run_severity_enum
  CHECK (severity IN ('P1_block', 'P2_alert', 'P3_monitor'));

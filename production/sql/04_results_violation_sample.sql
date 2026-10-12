-- DEPLOY STEP 04 of 16 — copied from sql/ddl/04_results_violation_sample.sql
-- by tools/build_production.py. Placeholders are NOT substituted.
--
-- violation_sample — up to 100 example bad rows per breach
--
-- Substitute {catalog} before execution.
--
-- The cap is a boundary, not a performance tweak. It bounds how much production data
-- is copied out of its source table. No sample value goes to a model endpoint (since
-- 2026-10-08: notebook 03 reads row_key only), but raising the cap still widens the
-- copy, so it is a governance change, not a config change.
--
-- A sample row is not the whole source row. jobs/run_checks.sample_keep stores the
-- table's key columns and the columns the rule reads (its expression, scope, join and
-- target column) and drops the rest, so a malformed-email sample carries the key and
-- the address, not the contact's date of birth or ID number (since 2026-10-12; samples
-- captured before then hold whole rows).
--
-- sample_row is JSON rather than a struct on purpose: the shape differs per target
-- table, and a struct would force a schema migration every time a new table is
-- onboarded. The cost is that the workbench renders it generically.
--
-- Samples are the shortest-lived data here and the most sensitive. Set a retention
-- policy — see the spec's open question on whether the register is formal audit
-- evidence, which governs this table too.

CREATE TABLE IF NOT EXISTS {catalog}.results.violation_sample (
  sample_id    STRING    NOT NULL COMMENT 'uuid',
  result_id    STRING    NOT NULL COMMENT 'the check_run verdict this sample belongs to',
  run_id       STRING    NOT NULL COMMENT 'denormalised so samples can be pruned by run without a join',
  rule_id      STRING    NOT NULL COMMENT 'denormalised for the workbench lookup',
  target_table STRING    NOT NULL COMMENT 'denormalised; also tells the renderer which key columns to expect',
  row_key      STRING             COMMENT 'primary key of the offending row, so a steward can find it in the source',
  sample_row   STRING    NOT NULL COMMENT 'JSON object: the offending row''s key columns and the columns the rule reads, nothing else',
  captured_ts  TIMESTAMP NOT NULL COMMENT 'when the sample was taken'
)
USING DELTA
CLUSTER BY (run_id, rule_id)
COMMENT 'Bounded evidence for a breach — at most 100 rows. The cap is the AI-exposure boundary from the parent architecture doc, not a performance setting.';

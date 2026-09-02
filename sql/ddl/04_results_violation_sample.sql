-- violation_sample — up to 100 example bad rows per breach
--
-- Substitute {catalog} before execution.
--
-- The cap is a boundary, not a performance tweak. The AI layer sees aggregated
-- results and these samples and nothing else (parent architecture doc). Raising the
-- cap widens what a model endpoint sees of production data, so it is a governance
-- change, not a config change.
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
  sample_row   STRING    NOT NULL COMMENT 'JSON object of the offending row, redacted per the columns the rule needs',
  captured_ts  TIMESTAMP NOT NULL COMMENT 'when the sample was taken'
)
USING DELTA
CLUSTER BY (run_id, rule_id)
COMMENT 'Bounded evidence for a breach — at most 100 rows. The cap is the AI-exposure boundary from the parent architecture doc, not a performance setting.';

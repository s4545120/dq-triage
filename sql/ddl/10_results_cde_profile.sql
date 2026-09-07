-- cde_profile — what the data in a critical element actually looks like
--
-- Substitute {catalog} before execution.
--
-- Written by the profile job, read by the CDE register and the coverage panel. The
-- app never writes it. One row per (binding, profile run).
--
-- WHY THIS IS NOT A ROW IN check_run. It was tempting: add rule_type = 'profile'
-- and reuse the verdict layer. Don't. check_run is the verdict layer — its status
-- enum is pass | breach | error | skipped, and every row carries a threshold and a
-- violation_pct. A profile has no threshold and reaches no verdict; forcing one in
-- means either inventing a fake threshold or adding a fifth status that means "not
-- actually a check", and either way the scorecard starts counting non-verdicts in
-- denominators that are supposed to mean "checks that ran". A profile describes;
-- a check judges. Separate tables.
--
-- NO VALUES, EVER, FOR A PII ELEMENT. The registered CDEs are date of birth, name,
-- email, identity document number — that is what makes them critical, and it is
-- also what makes a profile table dangerous. results.violation_sample already holds
-- up to 100 real bad rows per breach; that is one accepted PII surface and there is
-- no case for opening a second. So where the CDE is flagged pii, this table stores
-- COUNTS, DISTRIBUTIONS AND MASKED SIGNATURES ONLY. value_stats_withheld records
-- that the withholding happened, so an empty min/max is legible as a deliberate
-- omission rather than a failed profile.
--
-- WHAT A SIGNATURE IS. Character classes with run lengths, values discarded:
-- digits -> 9, letters -> X, whitespace -> _, punctuation kept because it is
-- structure rather than content. So an address becomes X{4}.X{5}@X{7}.X{3} and a
-- timestamp becomes 9{4}-9{2}-9{2}_9{2}:9{2}:9{2}. Two things follow, and both are
-- the reason to do it this way. It is not reversible to a value. And a minority
-- signature IS the defect, visible without anyone writing a rule for it first —
-- the fourteen dates that read 9{2}-9{2}-9{4} against a column that is otherwise
-- 9{4}-9{2}-9{2} are the CTCT_BRTH_PARSEABLE breach, found by describing the
-- column rather than by asserting anything about it.
--
-- CLUSTER BY (profile_ts, cde_id): the dominant reads are "the latest profile" for
-- the register and "this element over time" for drift.

CREATE TABLE IF NOT EXISTS {catalog}.results.cde_profile (
  profile_id          STRING    NOT NULL COMMENT 'uuid, unique per (binding, run)',
  profile_run_id      STRING    NOT NULL COMMENT 'groups every profile produced by one pass',
  profile_ts          TIMESTAMP NOT NULL COMMENT 'start of the profiling pass',
  cde_id              STRING    NOT NULL COMMENT 'the registered element profiled',
  cde_version         INT       NOT NULL COMMENT 'the version whose binding list was used; pins the profile to the definition in force at the time',
  data_class          STRING             COMMENT 'denormalised from the registry so a profile is readable without a join',
  criticality         STRING             COMMENT 'denormalised from the registry, for ranking the coverage panel',
  pii                 BOOLEAN            COMMENT 'denormalised from the registry — the flag that governed what this row is allowed to contain',
  target_table        STRING    NOT NULL COMMENT 'catalog.schema.table of the binding profiled',
  target_column       STRING    NOT NULL COMMENT 'column of the binding profiled',
  scope_filter        STRING             COMMENT 'the binding expected_scope_filter applied, if any. NULL means the whole table was profiled',
  rows_scanned        BIGINT             COMMENT 'rows in scope after scope_filter — the denominator for every pct here',
  null_count          BIGINT             COMMENT 'SQL NULLs',
  null_pct            DOUBLE             COMMENT 'null_count / rows_scanned * 100',
  blank_count         BIGINT             COMMENT 'present but empty or whitespace-only. Counted apart from NULL because a warehouse load that writes empty strings and one that writes NULLs are different defects with different owners',
  blank_pct           DOUBLE             COMMENT 'blank_count / rows_scanned * 100',
  populated_count     BIGINT             COMMENT 'rows_scanned - null_count - blank_count; the denominator for signature_match_pct',
  distinct_count      BIGINT             COMMENT 'distinct populated values',
  distinct_pct        DOUBLE             COMMENT 'distinct_count / populated_count * 100. Near 100 for an identifier, near 0 for a code — this is what says whether a column is what the registry claims it is',
  min_length          INT                COMMENT 'shortest populated value, in characters. A length, not a value',
  max_length          INT                COMMENT 'longest populated value, in characters',
  signature_count     INT                COMMENT 'distinct masked signatures across populated values. 1 means perfectly uniform shape',
  top_signatures      ARRAY<STRUCT<
                        signature: STRING,
                        row_count: BIGINT,
                        pct:       DOUBLE
                      >> COMMENT 'the most common masked signatures, descending. See the header for the masking rule. The minority entries are where the defects are',
  signature_match_pct DOUBLE             COMMENT 'share of populated values matching the registry expected_signature. NULL where the CDE declares none',
  sentinel_count      BIGINT             COMMENT 'populated values that are placeholders — unknown, n/a, service-number-unknown. Present but meaningless, which no null check catches',
  value_stats_withheld BOOLEAN  NOT NULL COMMENT 'TRUE when the CDE is pii and exemplar values were therefore not retained. Records that the omission was deliberate',
  profiled_by         STRING             COMMENT 'the job identity that produced this row',
  duration_sec        DOUBLE             COMMENT 'wall time for this binding'
)
USING DELTA
CLUSTER BY (profile_ts, cde_id)
COMMENT 'What each registered CDE binding actually contains — distributions and masked signatures, never values for a PII element. Written by the profile job; the app reads it and never writes.';

ALTER TABLE {catalog}.results.cde_profile
  ADD CONSTRAINT cde_profile_criticality_enum
  CHECK (criticality IS NULL OR criticality IN ('critical', 'high', 'medium', 'low'));

-- The privacy invariant, expressed where it cannot be forgotten: a PII element's
-- profile must declare that values were withheld.
ALTER TABLE {catalog}.results.cde_profile
  ADD CONSTRAINT cde_profile_pii_withholds_values
  CHECK (pii IS NOT TRUE OR value_stats_withheld = TRUE);

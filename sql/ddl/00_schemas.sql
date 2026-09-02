-- Catalog and schemas for the DQ Triage Agent.
--
-- Substitute {catalog} before execution (default: dq).
--
-- Two schemas, split by who writes them:
--   config   — human-authored reference data (rules, playbook approaches)
--   results  — machine-authored output (verdicts, samples, cohorts) plus the
--              one human-authored table that matters, `disposition`
--
-- The split is not cosmetic: it is what makes the grant model in 07_grants.sql
-- expressible in two statements instead of ten.

CREATE CATALOG IF NOT EXISTS {catalog}
  COMMENT 'Data quality platform. Holds no business data — only rules, verdicts and the audit register.';

CREATE SCHEMA IF NOT EXISTS {catalog}.config
  COMMENT 'Human-authored reference data: what we check, and what approaches exist for fixing it.';

CREATE SCHEMA IF NOT EXISTS {catalog}.results
  COMMENT 'Check verdicts, violation samples, cohorts, and the append-only disposition register.';

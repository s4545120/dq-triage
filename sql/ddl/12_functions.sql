-- Shared predicate helpers — the idioms that repeat across rule_expr
--
-- Substitute {catalog} and {check_runner_sp} before execution.
--
-- Additive. Nothing in 00-11 changes, and no rule is obliged to use these: a
-- rule_expr is still an arbitrary SQL boolean and always will be. These exist for
-- the four idioms that are written out longhand in more than one rule today, where
-- two copies can drift apart without anyone noticing.
--
-- Measured across the 35 registry rows the fixture ships:
--
--   IS NULL OR trim(x) = ''          8 rules
--   the email regex, longhand        2 rules
--   ^04[0-9]{8}$                     2 rules  (same concept, two tables, two columns)
--   the sentinel value list          1 rule   (and it will grow)
--
-- That is the whole case. It is not large. The email regex is the one that matters
-- most — it is long enough that nobody will spot the day the two copies diverge.
--
-- ================================================================
-- READ THIS FIRST: two things here are load-bearing
-- ================================================================
--
-- 1. NULL BEHAVIOUR IS INHERITED, NOT DESIGNED.
--
--    Every function below reproduces exactly what the expression it replaces did
--    with a NULL input. That produces a deliberate asymmetry:
--
--      is_blank_v1(NULL)        -> TRUE   (NULL-absorbing)
--      is_valid_email_v1(NULL)  -> NULL   (NULL-propagating)
--      is_au_mobile_v1(NULL)    -> NULL   (NULL-propagating)
--      is_sentinel_v1(NULL)     -> NULL   (NULL-propagating)
--
--    This is not an oversight to tidy up. `count_if` does not count a NULL
--    predicate, so a NULL email is currently NOT a format violation — it is caught
--    by CTCT_EML_NOT_NULL instead, and counting it twice would double-count the
--    same row across two rules. Make is_valid_email_v1 return FALSE for NULL and
--    every format rule's violation_count changes silently. Do not "fix" this.
--
-- 2. THE _v1 SUFFIX IS THE AUDIT MECHANISM.
--
--    config.rule_registry pins rule_version so a verdict can be explained from the
--    threshold in force at the time. There is no function_version column, and a
--    check_run row records no function state. So a function that is ALTERed in
--    place retroactively changes the meaning of every historical verdict that used
--    it, and nothing records that it happened.
--
--    The rule is therefore: these are immutable once a rule references them.
--    A change is a NEW function (_v2) plus a NEW rule_version on every dependent
--    rule, which is exactly the append-only discipline the registry already has.
--    CREATE OR REPLACE on a referenced function is a control failure, not a fix.
--
-- ================================================================
-- What these deliberately do NOT cover
-- ================================================================
--
-- A UC scalar function takes column values and returns a boolean. Three of the four
-- rule shapes in the registry cannot be expressed that way and are untouched here:
--
--   window uniqueness   3 rules   count(*) OVER (PARTITION BY x) > 1
--   table-level variance 2 rules  (SELECT count(DISTINCT c) FROM {table}) <= 1
--   cross-table          3 rules  aliased s. / c. — needs a join the registry
--                                 does not currently store
--
-- Those need execution paths in the check runner, not helpers. The cross-table three
-- are the open one: XREF_NAME_AGREEMENT has no target_column and references aliases
-- s. and c. with nothing in the registry saying what they bind to. The joins DO exist
-- — fixtures/rules.py carries a join_sql per rule — but config.rule_registry has no
-- column to hold one, so they reach Databricks only via sql/checkrun.py.

CREATE SCHEMA IF NOT EXISTS {catalog}.fn
  COMMENT 'Shared predicate helpers referenced by config.rule_registry.rule_expr. Immutable once referenced — see 12_functions.sql.';


-- ---------------------------------------------------------------
-- is_blank_v1 — absent, or present and empty
-- ---------------------------------------------------------------
-- Replaces: X IS NULL OR trim(X) = ''   (8 rules)
--
-- NULL-absorbing on purpose: a not_null rule must count a NULL as a violation, so
-- this returns TRUE rather than NULL. It is the only function here that does.
--
-- Note this conflates SQL NULL with whitespace-only, which the rules already did.
-- results.cde_profile keeps them apart (null_count vs blank_count) because a load
-- writing empty strings and one writing NULLs are different defects with different
-- owners. The rules do not make that distinction and this does not add it.

CREATE OR REPLACE FUNCTION {catalog}.fn.is_blank_v1(x STRING)
RETURNS BOOLEAN
COMMENT 'TRUE when x is NULL, empty, or whitespace-only. NULL-absorbing: is_blank_v1(NULL) is TRUE, not NULL.'
RETURN x IS NULL OR trim(x) = '';


-- ---------------------------------------------------------------
-- is_valid_email_v1 — the shape of an address, not its deliverability
-- ---------------------------------------------------------------
-- Replaces the regex written longhand in CTCT_EML_FMT and CTCT_EML_STTS_CONSISTENT.
--
-- The regex is copied byte-for-byte from the registry, doubled backslashes and all
-- — that is the Spark SQL string-literal form, and changing the escaping changes
-- what the regex engine sees.
--
-- Deliberately positive ("is valid") rather than a violation predicate, so the rule
-- reads NOT {catalog}.fn.is_valid_email_v1(EML_ID). NULL-propagating: a NULL address
-- is not a format violation, it is a not_null violation, and CTCT_EML_NOT_NULL
-- already counts it.
--
-- This checks shape only. It does not check that the domain resolves, that the TLD
-- exists, or that anyone reads mail there. The five narrower email rules
-- (NO_AT, WHITESPACE, DOMAIN_TLD, DOUBLE_DOT, TRAILING_DOT) stay as they are: they
-- exist to say WHICH way an address is malformed, which a single boolean cannot.

CREATE OR REPLACE FUNCTION {catalog}.fn.is_valid_email_v1(x STRING)
RETURNS BOOLEAN
COMMENT 'TRUE when x has the shape of an email address. NULL in, NULL out. Shape only — no domain or deliverability check.'
RETURN x RLIKE '^[^@\\s.]+(\\.[^@\\s.]+)*@[^@\\s.]+(\\.[^@\\s.]+)+$';


-- ---------------------------------------------------------------
-- is_au_mobile_v1 — Australian mobile number format
-- ---------------------------------------------------------------
-- Replaces ^04[0-9]{8}$ in CTCT_MOBL_FMT (ctct_c.MOBL_NO) and SUBS_MSISDN_FMT
-- (subs_c.PRIM_RSRC_VALU_TXT).
--
-- This is the strongest case of the four. The same business concept is checked on
-- two tables under two unrelated column names, so a correction to one would very
-- plausibly never reach the other. Naming the concept once is the point.
--
-- Format only: ten digits opening 04. It does not check that the prefix is an
-- allocated carrier range or that the number is in service — SUBS_MSISDN_SENTINEL
-- covers the placeholder case separately.

CREATE OR REPLACE FUNCTION {catalog}.fn.is_au_mobile_v1(x STRING)
RETURNS BOOLEAN
COMMENT 'TRUE when x is ten digits opening 04. NULL in, NULL out. Format only — no carrier-range or in-service check.'
RETURN x RLIKE '^04[0-9]{8}$';


-- ---------------------------------------------------------------
-- is_sentinel_v1 — present, but meaningless
-- ---------------------------------------------------------------
-- Replaces the value list in SUBS_MSISDN_SENTINEL.
--
-- One rule uses it today. It is here anyway because the sentinel list is the thing
-- most likely to grow — every new source system arrives with its own placeholder
-- vocabulary — and a growing list copied across rules is the drift case this file
-- exists to prevent. results.cde_profile.sentinel_count is profiling the same idea
-- from the other direction; when that list and this one disagree, one of them is
-- stale.
--
-- Adding a value to this list changes what every dependent rule counts. That is a
-- _v2 and a new rule_version, not an edit — see the header.
--
-- NULL-propagating: lower(trim(NULL)) IN (...) is NULL, and an absent value is a
-- not_null violation rather than a sentinel one.

CREATE OR REPLACE FUNCTION {catalog}.fn.is_sentinel_v1(x STRING)
RETURNS BOOLEAN
COMMENT 'TRUE when x is a placeholder standing in for a real value. NULL in, NULL out. Adding a value here is a _v2, not an edit.'
RETURN lower(trim(x)) IN (
  'service-number-unknown', 'unknown', 'n/a', 'na', 'none', 'null', ''
);


-- ---------------------------------------------------------------
-- Grants
-- ---------------------------------------------------------------
--
-- These are here rather than in 07_grants.sql on purpose. 07 makes one argument —
-- what the APP service principal can write, and that it can write nothing else —
-- and its proof queries are read against that claim. Adding a second principal's
-- grants to that file would blunt it. Nothing here grants the app anything.
--
-- EXECUTE only, and only to the check runner. A function the runner can execute but
-- nobody can replace is the shape that makes the _v1 discipline enforceable rather
-- than merely documented: keep ownership of {catalog}.fn with the platform team.

GRANT USE CATALOG ON CATALOG {catalog}          TO `{check_runner_sp}`;
GRANT USE SCHEMA  ON SCHEMA  {catalog}.fn       TO `{check_runner_sp}`;
GRANT EXECUTE     ON SCHEMA  {catalog}.fn       TO `{check_runner_sp}`;

-- Proof query. EXPECTED: no principal other than the schema owner holds anything
-- but EXECUTE on {catalog}.fn. A CREATE FUNCTION or MODIFY grant here means someone
-- can silently change what a historical verdict meant.
SELECT grantee, privilege_type
FROM   system.information_schema.schema_privileges
WHERE  catalog_name = '{catalog}' AND schema_name = 'fn'
ORDER  BY grantee;

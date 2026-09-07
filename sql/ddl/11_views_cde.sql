-- CDE views — current definitions, and the coverage question they exist to answer
--
-- Substitute {catalog} before execution. Runs after 09 and 10, which create the
-- tables these read, and after 08, which creates v_rule_registry_current.
--
-- Same discipline as 08_views.sql: current state is derived here and NOWHERE ELSE.
-- The registry is append-only, so "the CDE as it stands now" is a window function,
-- not a column. If the app recomputes it in pandas as well, the two will disagree.

-- ---------------------------------------------------------------
-- v_cde_registry_current — the element as it stands now
-- ---------------------------------------------------------------
-- effective_to is derived rather than stored, so re-tiering an element, adding a
-- binding or retiring one all stay INSERTs.

CREATE OR REPLACE VIEW {catalog}.config.v_cde_registry_current
COMMENT 'Latest version of every critical data element, with effective_to derived from the next version. Query this, not the base table, unless you want registration history. This is also the profile job worklist — an element absent here cannot be profiled.'
AS
WITH versioned AS (
  SELECT
    c.*,
    LEAD(c.effective_from) OVER (PARTITION BY c.cde_id ORDER BY c.cde_version) AS effective_to,
    ROW_NUMBER()           OVER (PARTITION BY c.cde_id ORDER BY c.cde_version DESC) AS rn
  FROM {catalog}.config.cde_registry c
)
SELECT * EXCEPT (rn)
FROM   versioned
WHERE  rn = 1
  AND  status <> 'retired';

-- ---------------------------------------------------------------
-- v_cde_coverage — one row per bound column, and whether anything watches it
-- ---------------------------------------------------------------
-- The view the whole component exists for. Every other table here describes what
-- broke; this one describes what is not being looked at.
--
-- A RULE ATTACHES TO A BINDING TWO WAYS, and it needs both. The obvious way is a
-- column match. That misses every cross-table rule, because those carry
-- target_column = NULL by design — XREF_NAME_AGREEMENT checks that a subscription's
-- first name agrees with its contact's, which is unambiguously a name rule and
-- unreachable by any column join. So config.rule_registry.cde_id exists to let a
-- rule say which element it covers, and the join below is the OR of the two. A rule
-- matching both ways still attaches once.
--
-- SCOPE MISMATCH IS A RULE DEFECT, DETECTED STRUCTURALLY. Where a binding declares
-- expected_scope_filter — this element is only populated for these rows — and an
-- attached rule carries no scope_filter at all, that rule is measuring rows the
-- register says should never have held a value. It will report legitimate product
-- variation as breaches. That is not a hypothetical: on the pilot data it is 700
-- rows across two rules, and it is what cohort COH-B is about. The register makes
-- the contradiction machine-visible; a human still decides what to do about it.

CREATE OR REPLACE VIEW {catalog}.results.v_cde_coverage
COMMENT 'One row per bound CDE column: how many active rules watch it, of what types, whether any of them contradicts the binding scope, and when it was last profiled. A row with rule_count = 0 on a critical element is the finding this component was built to produce.'
AS
WITH bound AS (
  SELECT
    c.cde_id, c.cde_version, c.cde_name, c.data_class, c.criticality, c.pii,
    c.business_domain, c.owner_group,
    b.target_table, b.target_column, b.populated_when, b.expected_scope_filter,
    b.discovered_by
  FROM {catalog}.config.v_cde_registry_current c
  LATERAL VIEW explode(c.bindings) exploded AS b
  WHERE c.status = 'registered'
    AND b.binding_status = 'bound'
),
active_rules AS (
  SELECT rule_id, rule_type, severity, scope_filter, cde_id, target_table, target_column
  FROM   {catalog}.config.v_rule_registry_current
  WHERE  status = 'active'
),
latest_run AS (
  SELECT MAX(run_ts) AS run_ts FROM {catalog}.results.check_run
),
verdicts AS (
  SELECT k.rule_id, k.status, k.violation_count
  FROM   {catalog}.results.check_run k
  JOIN   latest_run lr ON k.run_ts = lr.run_ts
),
attached AS (
  SELECT
    b.*,
    r.rule_id,
    r.rule_type,
    r.severity,
    r.scope_filter,
    v.status          AS latest_status,
    v.violation_count AS latest_violations
  FROM bound b
  LEFT JOIN active_rules r
    ON  r.cde_id = b.cde_id
    OR (r.target_table = b.target_table AND r.target_column = b.target_column)
  LEFT JOIN verdicts v ON v.rule_id = r.rule_id
),
rolled AS (
  SELECT
    cde_id, cde_version, cde_name, data_class, criticality, pii,
    business_domain, owner_group,
    target_table, target_column, populated_when, expected_scope_filter, discovered_by,

    COUNT(DISTINCT rule_id)                                          AS rule_count,
    array_sort(collect_set(rule_id))                                 AS rule_ids,
    array_sort(collect_set(rule_type))                               AS rule_types,
    COUNT(DISTINCT CASE WHEN latest_status = 'breach'
                        THEN rule_id END)                            AS breaching_rule_count,
    array_sort(collect_set(CASE WHEN latest_status = 'breach'
                                THEN rule_id END))                   AS breaching_rule_ids,
    COALESCE(SUM(CASE WHEN latest_status = 'breach'
                      THEN latest_violations END), 0)                AS latest_violation_rows,
    array_sort(collect_set(
      CASE WHEN expected_scope_filter IS NOT NULL AND rule_id IS NOT NULL
                AND scope_filter IS NULL
           THEN rule_id END))                                        AS unscoped_rule_ids
  FROM attached
  GROUP BY
    cde_id, cde_version, cde_name, data_class, criticality, pii,
    business_domain, owner_group,
    target_table, target_column, populated_when, expected_scope_filter, discovered_by
),
profiled AS (
  SELECT * FROM (
    SELECT
      p.cde_id, p.target_table, p.target_column,
      p.profile_ts, p.rows_scanned, p.null_pct, p.blank_pct, p.distinct_pct,
      p.signature_count, p.signature_match_pct, p.sentinel_count, p.top_signatures,
      ROW_NUMBER() OVER (PARTITION BY p.cde_id, p.target_table, p.target_column
                         ORDER BY p.profile_ts DESC) AS rn
    FROM {catalog}.results.cde_profile p
  ) WHERE rn = 1
)
SELECT
  g.cde_id,
  g.cde_name,
  g.data_class,
  g.criticality,
  g.pii,
  g.business_domain,
  g.owner_group,
  g.target_table,
  g.target_column,
  g.populated_when,
  g.expected_scope_filter,
  g.discovered_by,

  g.rule_count,
  g.rule_ids,
  g.rule_types,
  g.rule_count > 0                                    AS has_active_rule,
  g.breaching_rule_count,
  g.breaching_rule_ids,
  g.latest_violation_rows,
  g.unscoped_rule_ids,
  size(g.unscoped_rule_ids) > 0                       AS has_scope_mismatch,

  p.profile_ts                                        AS last_profiled_ts,
  p.rows_scanned                                      AS profiled_rows,
  p.null_pct,
  p.blank_pct,
  p.distinct_pct,
  p.signature_count,
  p.signature_match_pct,
  p.sentinel_count,
  p.top_signatures,
  p.profile_ts IS NULL                                AS never_profiled,

  -- The gap classification the coverage panel sorts on. Precedence, worst first:
  -- an element nobody checks outranks one checked by a rule that contradicts its
  -- own binding scope, which outranks one where nothing checks the VALUES.
  --
  -- 'unvalidated' is deliberately about what a rule does, not what it is called. The
  -- identity document number is watched by one rule typed 'consistency' -- if a
  -- document type is recorded, the number must be present -- which is a presence
  -- check wearing another name. Classifying on rule_type = 'not_null' would have
  -- called that element covered. The set below is the rule types that examine the
  -- values themselves; everything else asserts presence or agreement.
  --
  -- 'covered' is the absence of all three. It is not a claim that the rules are
  -- GOOD, only that something is looking at the contents.
  CASE
    WHEN g.rule_count = 0                             THEN 'no_rule'
    WHEN size(g.unscoped_rule_ids) > 0                THEN 'scope_mismatch'
    WHEN size(array_intersect(g.rule_types,
              array('format', 'uniqueness',
                    'referential', 'variance'))) = 0  THEN 'unvalidated'
    ELSE                                                   'covered'
  END                                                 AS coverage_gap
FROM rolled g
LEFT JOIN profiled p
  ON  p.cde_id       = g.cde_id
  AND p.target_table = g.target_table
  AND p.target_column = g.target_column;

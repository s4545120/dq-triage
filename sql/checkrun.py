r"""Generate the Stage 2 check run: every rule executed, diffed against the fixture.

    python3 sql/checkrun.py

Writes sql/out/checkrun.sql — one statement producing one row per rule, with the
fixture's expected numbers inline and a verdict column. Zero FAIL rows means the SQL
in config.rule_registry agrees with the Python evaluators that produced every figure
in fixtures/out/. That comparison has never been made.

WHY THIS IS NOT JUST count_if(rule_expr)

The registry holds four rule shapes and only one of them fits that template:

  row_level    27 rules  count_if(expr)
  uniqueness    3 rules  a window function — needs a subquery, not an aggregate
  variance      2 rules  a whole-table test; violation_count is rows_scanned or 0
  cross_table   3 rules  needs a join the registry has nowhere to store

The joins for the last three live in fixtures/rules.py as `join_sql` — real, correct,
and invisible to Databricks because config.rule_registry has no column for them. They
are emitted here from that source, which is exactly why this file has to be generated
rather than written by hand: it is carrying a dependency the schema does not yet
express. Adding a `join_sql` column to the registry is the fix; until then this script
is where that knowledge lives.

EXPECTED VALUES come from the final run in results.check_run.parquet — 34 verdicts,
21 breach, 11 pass, 2 skipped. Shadow rules are included and marked, because a shadow
rule still runs; it just does not raise.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

import pandas as pd

ROOT = pathlib.Path(__file__).parent.parent
FIX = ROOT / "fixtures" / "out"
OUT = pathlib.Path(__file__).parent / "out"
sys.path.insert(0, str(ROOT / "fixtures"))


def shape(rule) -> str:
    e = rule.rule_expr
    if rule.rule_id.startswith("XREF_"):
        return "cross_table"
    if "OVER (PARTITION BY" in e:
        return "uniqueness"
    if "{table}" in e:
        return "variance"
    return "row_level"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default="sdpt_data_trnf")
    ap.add_argument("--schema", default="udp_brnz")
    ap.add_argument("--src-prefix", default="dq_mock_")
    ap.add_argument("--prefix", default="dq_")
    a = ap.parse_args()

    q = f"{a.catalog}.{a.schema}."
    rewrite = {
        "prod.customer.ctct_c": f"{q}{a.src_prefix}ctct_c",
        "prod.customer.subs_c": f"{q}{a.src_prefix}subs_c",
    }
    tbl = lambda t: rewrite.get(t, t)

    import rules as fixture_rules
    joins = {r.rule_id: r.join_sql for r in fixture_rules.RULES if getattr(r, "join_sql", None)}

    reg = pd.read_parquet(FIX / "config.rule_registry.parquet")
    cur = reg.sort_values("rule_version").groupby("rule_id").tail(1)

    cr = pd.read_parquet(FIX / "results.check_run.parquet")
    last = cr[cr.run_ts == cr.run_ts.max()].set_index("rule_id")

    blocks, counts = [], {}
    for _, r in cur.sort_values("rule_id").iterrows():
        if r.rule_id not in last.index:
            continue
        exp = last.loc[r.rule_id]
        sh = shape(r)
        counts[sh] = counts.get(sh, 0) + 1
        t = tbl(r.target_table)
        where = f"\n  WHERE  {r.scope_filter}" if pd.notna(r.scope_filter) else ""
        hdr = (f"  SELECT '{r.rule_id}' AS rule_id, '{sh}' AS shape,"
               f" '{r.status}' AS reg_status,")

        if sh == "row_level":
            blocks.append(f"{hdr}\n         count(*) AS rows_scanned,"
                          f"\n         count_if({r.rule_expr}) AS violation_count,"
                          f"\n         {exp.rows_scanned} AS exp_scanned,"
                          f" {exp.violation_count} AS exp_violations"
                          f"\n  FROM   {t}{where}")
        elif sh == "uniqueness":
            blocks.append(f"{hdr}\n         count(*) AS rows_scanned,"
                          f"\n         count_if(dup) AS violation_count,"
                          f"\n         {exp.rows_scanned} AS exp_scanned,"
                          f" {exp.violation_count} AS exp_violations"
                          f"\n  FROM   (SELECT {r.rule_expr} AS dup FROM {t}{where})")
        elif sh == "variance":
            expr = r.rule_expr.replace("{table}", t)
            blocks.append(f"{hdr}\n         count(*) AS rows_scanned,"
                          f"\n         CASE WHEN {expr} THEN count(*) ELSE 0 END AS violation_count,"
                          f"\n         {exp.rows_scanned} AS exp_scanned,"
                          f" {exp.violation_count} AS exp_violations"
                          f"\n  FROM   {t}{where}")
        else:  # cross_table
            j = joins[r.rule_id]
            for k, v in rewrite.items():
                j = j.replace(k, v)
            scope = ("LEFT JOIN" if "LEFT JOIN" in j else "JOIN")
            s_tbl, c_tbl = tbl("prod.customer.subs_c"), tbl("prod.customer.ctct_c")
            on = "s.CTCT_KEY = c.CTCT_KEY"
            pred = r.rule_expr
            blocks.append(
                f"{hdr}\n         count(*) AS rows_scanned,"
                f"\n         count_if({pred}) AS violation_count,"
                f"\n         {exp.rows_scanned} AS exp_scanned,"
                f" {exp.violation_count} AS exp_violations"
                f"\n  -- join from fixtures/rules.py join_sql; config.rule_registry cannot store it"
                f"\n  FROM   {s_tbl} s {scope} {c_tbl} c ON {on}")

    body = "\nUNION ALL\n".join(blocks)
    sql = f'''-- =====================================================================
-- checkrun.sql — GENERATED by sql/checkrun.py. Do not edit; re-generate.
-- target: {a.catalog}.{a.schema}
--
-- Every rule in the registry, executed, with the fixture's numbers inline.
-- ONE result set. Sort by verdict and read the FAIL rows.
--
-- THIS IS THE COMPARISON THAT HAS NEVER BEEN MADE. Every violation_count in
-- fixtures/out/ came from Python evaluators in fixtures/rules.py. The rule_expr
-- SQL strings alongside them have never been parsed by anything. If these agree,
-- the fixture is validated. If they do not, one of the two is wrong and the
-- difference is the most useful thing this sandpit will tell you.
--
-- Shapes: {", ".join(f"{k} {v}" for k, v in sorted(counts.items()))}
--
-- Two to watch regardless of the verdict column:
--   SUBS_IMEI_NOT_NULL   ~700  (deliberately unscoped — must stay broken)
--   SUBS_SIM_NOT_NULL       0  (its correctly-scoped twin, same data)
-- =====================================================================

WITH actual AS (
{body}
)
SELECT rule_id, shape, reg_status,
       rows_scanned, exp_scanned,
       violation_count, exp_violations,
       CASE WHEN rows_scanned = exp_scanned
             AND violation_count = exp_violations THEN 'PASS' ELSE 'FAIL' END AS verdict
FROM   actual
ORDER  BY verdict DESC, shape, rule_id;
'''
    OUT.mkdir(exist_ok=True)
    (OUT / "checkrun.sql").write_text(sql)

    # ---- the INSERT form: the same 34 queries, writing verdicts -------------
    # Metadata rides in a VALUES block rather than being repeated into every
    # per-rule SELECT, so the blocks above stay byte-identical between the
    # diagnostic and the writer. threshold_pct and severity are COPIED from the
    # registry, never recomputed — check_run's header says so and the scorecard
    # depends on it.
    import uuid as _uuid
    run_id = str(_uuid.uuid5(_uuid.NAMESPACE_URL, "dq-triage/sandpit/run-001"))
    meta_rows = []
    for _, r in cur.sort_values("rule_id").iterrows():
        if r.rule_id not in last.index:
            continue
        lit = lambda v: "NULL" if pd.isna(v) else ("'" + str(v).replace("'", "\\'") + "'")
        meta_rows.append(
            f"    ('{r.rule_id}', {int(r.rule_version)}, {lit(r.source_layer)}, "
            f"'{tbl(r.target_table)}', {lit(r.target_column)}, "
            f"{float(r.fail_threshold_pct)}, '{r.severity}', "
            f"{lit(r.business_domain)}, {lit(r.owner_group)}, '{r.status}')")

    ins = f"""-- =====================================================================
-- checkrun_insert.sql — GENERATED by sql/checkrun.py. Do not edit.
-- target: {a.catalog}.{a.schema}
--
-- The same {sum(counts.values())} queries as checkrun.sql, writing verdicts instead of
-- comparing them. THIS IS THE FIRST THING IN THE DESIGN THAT PRODUCES DATA.
--
-- RUN ONCE per intended run. check_run is not appendOnly, so a second run adds a
-- second run_id rather than failing — which is correct behaviour for a real
-- runner and a trap for a manual one. The run_id below is FIXED, so re-running
-- gives you two runs sharing an id. Delete them first, or edit run_id.
--
-- What is copied and never computed:
--   threshold_pct   from config.rule_registry.fail_threshold_pct
--   severity        from config.rule_registry.severity
-- Recomputing either downstream is the defect check_run's header warns about.
--
-- scope_fingerprint is NULL — the hashing rule is an open spec question.
-- duration_sec and dbu_estimate are NULL: a single statement cannot attribute
-- per-rule cost, which a real Lakeflow runner can and should.
--
-- Expected afterwards: 21 breach, 11 pass, 2 skipped.
-- =====================================================================

INSERT INTO {q}{a.prefix if hasattr(a, 'prefix') else 'dq_'}results_check_run
  (result_id, run_id, run_ts, rule_id, rule_version, source_layer,
   target_table, target_column, rows_scanned, violation_count, violation_pct,
   threshold_pct, status, severity, business_domain, owner_group,
   scope_fingerprint, message, duration_sec, dbu_estimate)
WITH actual AS (
{body}
),
meta (rule_id, rule_version, source_layer, target_table, target_column,
      threshold_pct, severity, business_domain, owner_group, reg_status) AS (VALUES
{",".join(chr(10) + m for m in meta_rows)}
)
SELECT uuid()                                   AS result_id,
       '{run_id}'                               AS run_id,
       current_timestamp()                      AS run_ts,
       m.rule_id, m.rule_version, m.source_layer,
       m.target_table, m.target_column,
       a.rows_scanned, a.violation_count,
       CASE WHEN a.rows_scanned = 0 THEN 0.0
            ELSE a.violation_count / a.rows_scanned * 100 END AS violation_pct,
       m.threshold_pct,
       CASE WHEN m.reg_status = 'shadow' THEN 'skipped'
            WHEN a.rows_scanned = 0      THEN 'skipped'
            WHEN a.violation_count / a.rows_scanned * 100 > m.threshold_pct
                                         THEN 'breach'
            ELSE 'pass' END                     AS status,
       m.severity, m.business_domain, m.owner_group,
       CAST(NULL AS STRING)                     AS scope_fingerprint,
       format_string('%d of %d rows violate %s, limit %s%%',
                     a.violation_count, a.rows_scanned, m.rule_id,
                     CAST(m.threshold_pct AS STRING))  AS message,
       CAST(NULL AS DOUBLE)                     AS duration_sec,
       CAST(NULL AS DOUBLE)                     AS dbu_estimate
FROM   actual a JOIN meta m ON m.rule_id = a.rule_id;
"""
    (OUT / "checkrun_insert.sql").write_text(ins)
    print(f"wrote sql/out/checkrun.sql — {sum(counts.values())} rules (diagnostic)")
    print(f"wrote sql/out/checkrun_insert.sql — same rules, writing verdicts")
    for k, v in sorted(counts.items()):
        print(f"    {k:12} {v}")
    print("\ncross-table joins sourced from fixtures/rules.py join_sql —")
    print("the registry has no column for them, which is the finding, not a workaround")
    return 0


if __name__ == "__main__":
    sys.exit(main())

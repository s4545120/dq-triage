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
    print(f"wrote sql/out/checkrun.sql — {sum(counts.values())} rules")
    for k, v in sorted(counts.items()):
        print(f"    {k:12} {v}")
    print("\ncross-table joins sourced from fixtures/rules.py join_sql —")
    print("the registry has no column for them, which is the finding, not a workaround")
    return 0


if __name__ == "__main__":
    sys.exit(main())

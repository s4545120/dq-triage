#!/usr/bin/env python3
"""The check runner — DRAFT. Reads config.rule_registry, writes results.check_run.

    # as a Databricks job, Python file task, serverless or a small cluster
    python jobs/run_checks.py --catalog dq

This is the job `CLAUDE.md` lists first under *Known gaps*: nothing else in the design
writes `results.check_run`, and cohorts cannot form without it. `sql/out/checkrun.sql`
is a one-off comparison harness, not this; `sql/out/checkrun_insert.sql` writes verdicts
but hardcodes its `run_id`, which its own header calls a trap.

ONE PASS PER TABLE, NOT ONE QUERY PER RULE
------------------------------------------
The harness runs 34 separate queries because it only had to run once. That does not
scale: at 400 rules it is 400 table scans. Here every row-level rule on a table is
folded into ONE aggregate, by moving `scope_filter` out of a WHERE clause and into the
`count_if`:

    -- instead of, per rule:  SELECT count_if(expr) FROM t WHERE scope
    SELECT count_if(scope_a)                 AS s__RULE_A,
           count_if(scope_a AND (expr_a))    AS v__RULE_A,
           count_if(scope_b)                 AS s__RULE_B,
           count_if(scope_b AND (expr_b))    AS v__RULE_B
    FROM   t

That is exactly equivalent, and the equivalence is worth spelling out because it rests
on three-valued logic. `WHERE scope` keeps rows where scope is TRUE, discarding FALSE
and NULL; `count_if(scope)` counts exactly the same rows. `count_if(scope AND expr)`
counts rows where both are TRUE, because `TRUE AND NULL` is NULL and `count_if` does
not count a NULL predicate — which is also why a NULL-propagating rule like the email
format check does not count an absent address as a format violation. Change either
side of that and violation counts move silently.

On the pilot registry this turns 26 row-level queries over 2 tables into 2, and the
same shape gives ~85% of any rule set one scan per table. The remaining three shapes
cannot join that aggregate and each gets its own query -- see the builders below.

PROFILING SHOULD RIDE THIS PASS
-------------------------------
`results.cde_profile` needs null rate, blank rate, cardinality and length range per
bound column: all aggregates over the tables this already scans. Adding them to
`batch_row_level`'s SELECT makes profiling nearly free. Only the masked-signature
histogram needs its own pass, because it is a GROUP BY over a per-value transform, and
that is where sampling belongs. Not done here -- it is a separate job's output and
mixing the two writes would blur which job owns which table.

WHAT THIS DRAFT DOES NOT SOLVE
------------------------------
* **Cross-table joins now come from `config.rule_registry.join_sql`** (added
  2026-09-28), so every part of a rule is data and this file hardcodes nothing about
  any rule. A cross-table rule whose `join_sql` is NULL is still written as
  `status = 'error'` rather than skipped, so a registry gap appears in the data
  instead of three rules silently vanishing from a run.
* **`scope_fingerprint` stays NULL.** The hashing rule is an open spec question and
  `03_results_check_run.sql` says to write NULL until it is answered.
* **`rule_version` is whatever the registry's current version says.** Correct for a
  forward-running job, and worth knowing that the fixture stamps the current version on
  historical runs, which this does not attempt to reproduce.
* **`duration_sec` per rule is only honest for the shapes that get their own query.**
  A batched rule shares one scan with its table-mates, so the batch's wall time is
  divided across them and the column says so in `message`. Per-rule cost attribution is
  a real casualty of batching and should be argued about before anyone bills on it.

TRUST BOUNDARY. `rule_expr` and `scope_filter` are arbitrary SQL interpolated into a
query, by design -- a rule_expr IS SQL and always will be. The registry is trusted
config, authored by stewards and append-only. What is NOT trusted is `rule_id`, which
becomes a column alias here, so it is validated against a strict identifier pattern
and the run aborts on a bad one rather than emitting mangled SQL.
"""

from __future__ import annotations

import argparse
import re
import uuid
from dataclasses import dataclass, field

RULE_ID_OK = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,120}$")

# The canonical prefix on the shared predicate helpers as config.rule_registry stores
# them. A deployment whose catalog IS `dq` needs no rewrite at all; every other one
# does, and this is now the THIRD place that rewrite is written -- sql/seed.py and
# sql/checkrun.py are the other two, and all three must agree or they execute different
# SQL from the same registry. The real fix is to stop storing a name that needs
# rewriting: either the registry holds the resolved name for its own catalog, or the
# three callers share one substitution helper. Until then, keep them in step.
FN_CANONICAL = "dq.fn."
SAMPLE_CAP = 100          # the AI-exposure boundary, not a performance setting


@dataclass
class Rule:
    """One row of v_rule_registry_current, as this job needs it."""
    rule_id: str
    rule_version: int
    rule_type: str
    rule_expr: str
    target_table: str
    target_column: str | None
    scope_filter: str | None
    fail_threshold_pct: float
    severity: str
    status: str                       # active | shadow  (retired is filtered out)
    source_layer: str | None = None
    business_domain: str | None = None
    owner_group: str | None = None
    join_sql: str | None = None       # from the registry once the column exists
    sample_columns: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Shape classification — pure, and the one place it is decided
# ---------------------------------------------------------------------------

def shape(r: Rule) -> str:
    """Which execution path a rule takes.

    Deliberately keyed on the EXPRESSION, not on rule_type: rule_type is the steward's
    vocabulary (`format`, `consistency`, `sentinel`) and says nothing about whether the
    predicate is a row test, a window or a whole-table aggregate. Two rules typed
    `consistency` here take different paths.
    """
    if not _blank(r.join_sql):
        return "cross_table"
    if "OVER (PARTITION BY" in r.rule_expr:
        return "uniqueness"
    if "{table}" in r.rule_expr:
        return "variance"
    return "row_level"


def _blank(v) -> bool:
    """True when a field carries no value: None, NaN, or whitespace only.

    NaN IS THE ONE THAT BITES. A registry read through pandas turns a column that is
    NULL on some rows into float NaN, and NaN is TRUTHY -- so a bare
    `if not r.scope_filter` reads "this rule has no scope" as "this rule has a scope"
    and interpolates the literal string `nan` into the SQL. dq_app/domain/coverage.py
    carries the same warning for CDE bindings, where it produced a scope mismatch
    against every rule in the register. `v != v` is true only for NaN and needs no
    import, which keeps the builders free of a pandas dependency.
    """
    return v is None or v != v or not str(v).strip()


def normalise(rules: list[Rule], fn_prefix: str | None) -> list[Rule]:
    """Rewrite the helper prefix in every rule_expr, once, before anything is planned.

    Normalising on load rather than at each use is the same choice sql/seed.py makes:
    one substitution point means the batched aggregate, the single queries and the
    sample query cannot disagree about which function they are calling.
    """
    if not fn_prefix or fn_prefix == FN_CANONICAL:
        return rules
    for r in rules:
        if FN_CANONICAL in r.rule_expr:
            r.rule_expr = r.rule_expr.replace(FN_CANONICAL, fn_prefix)
    return rules


def scope_sql(r: Rule) -> str:
    """The scope predicate, or TRUE. Parenthesised because it is ANDed with the rule."""
    if _blank(r.scope_filter):
        return "TRUE"
    return f"({r.scope_filter})"


def _alias(prefix: str, rule_id: str) -> str:
    if not RULE_ID_OK.match(rule_id):
        raise ValueError(
            f"rule_id {rule_id!r} is not a safe SQL identifier and this job turns "
            f"rule_ids into column aliases. Fix the registry rather than relaxing this."
        )
    return f"{prefix}__{rule_id}"


# ---------------------------------------------------------------------------
# SQL builders — pure functions, testable without a warehouse
# ---------------------------------------------------------------------------

def batch_row_level(table: str, rules: list[Rule]) -> str:
    """ONE aggregate covering every row-level rule on one table.

    Two counters per rule: the scope size (the denominator) and the violations. Both
    must come from the same scan, or rows_scanned and violation_count could describe
    different snapshots of a table that is still being written to.
    """
    parts = []
    for r in rules:
        sc = scope_sql(r)
        parts.append(f"  count_if({sc}) AS {_alias('s', r.rule_id)}")
        parts.append(f"  count_if({sc} AND ({r.rule_expr})) AS {_alias('v', r.rule_id)}")
    return "SELECT\n" + ",\n".join(parts) + f"\nFROM {table}"


def uniqueness_sql(table: str, r: Rule) -> str:
    """A window function cannot live in the batched aggregate, so this is its own query.

    Could several uniqueness rules on one table share a subquery? Only if they shared a
    scope_filter, and SUBS_MSISDN_UNIQUE has one while the key-uniqueness rules do not.
    Three rules is not worth a special case that would break the moment a fourth
    arrived with a fourth scope.
    """
    where = "" if _blank(r.scope_filter) else f"\n  WHERE {r.scope_filter}"
    return (f"SELECT count(*) AS rows_scanned,\n"
            f"       count_if(dup) AS violation_count\n"
            f"FROM  (SELECT {r.rule_expr} AS dup FROM {table}{where})")


def variance_sql(table: str, r: Rule) -> str:
    """A whole-table test. When it holds, every row in scope is implicated, which is why
    violation_count is rows_scanned and not 1 -- the rule is a statement about the
    column, so the blast radius is the column."""
    expr = r.rule_expr.replace("{table}", table)
    where = "" if _blank(r.scope_filter) else f"\n  WHERE {r.scope_filter}"
    return (f"SELECT count(*) AS rows_scanned,\n"
            f"       CASE WHEN {expr} THEN count(*) ELSE 0 END AS violation_count\n"
            f"FROM   {table}{where}")


def cross_table_sql(r: Rule, resolve: dict[str, str]) -> str:
    """A join the registry has no column for. `resolve` is the table-name map."""
    join = r.join_sql
    for k, v in resolve.items():
        join = join.replace(k, v)
    where = "" if _blank(r.scope_filter) else f"\n  WHERE {r.scope_filter}"
    return (f"SELECT count(*) AS rows_scanned,\n"
            f"       count_if({r.rule_expr}) AS violation_count\n"
            f"FROM   {join}{where}")


def sample_sql(r: Rule, table: str, resolve: dict[str, str], cap: int = SAMPLE_CAP) -> str:
    """Up to `cap` offending rows for a breach. Raising the cap widens what the AI layer
    sees of production data, so it is a governance change -- see 04's header."""
    sh = shape(r)
    if sh == "cross_table":
        join = r.join_sql
        for k, v in resolve.items():
            join = join.replace(k, v)
        src, pred = join, r.rule_expr
    elif sh == "uniqueness":
        src, pred = f"(SELECT *, {r.rule_expr} AS __dup FROM {table})", "__dup"
    elif sh == "variance":
        src, pred = table, "TRUE"
    else:
        src, pred = table, f"({r.rule_expr})"
    scope = "" if _blank(r.scope_filter) else f" AND {r.scope_filter}"
    return f"SELECT * FROM {src}\nWHERE  {pred}{scope}\nLIMIT  {cap}"


# ---------------------------------------------------------------------------
# The verdict — the one place status is decided
# ---------------------------------------------------------------------------

def verdict(r: Rule, scanned: int, violations: int) -> tuple[str, float, str]:
    """(status, violation_pct, message). Mirrors fixtures/build_fixtures.py exactly.

    `skipped` is a real state and not a failure: a shadow rule is MEASURED and not
    raised, and an empty scope means the question did not apply this run. Both keep
    their violation_count so a shadow rule can be promoted on evidence.
    """
    pct = round(violations / scanned * 100, 4) if scanned else 0.0
    if r.status == "shadow":
        return "skipped", pct, f"shadow rule: measured {violations} violations, not raised"
    if scanned == 0:
        return "skipped", 0.0, "scope empty this run: nothing to check"
    if violations == 0:
        return "pass", pct, f"0 of {scanned} rows in scope violate"
    if pct > r.fail_threshold_pct:
        return ("breach", pct,
                f"{violations} of {scanned} rows in scope violate ({pct:.2f}%), "
                f"limit {r.fail_threshold_pct:.2f}%")
    return ("pass", pct,
            f"{violations} of {scanned} rows violate ({pct:.2f}%), "
            f"within limit {r.fail_threshold_pct:.2f}%")


def plan(rules: list[Rule], resolve: dict[str, str]) -> dict:
    """Group rules into the queries that will run. Pure, so a test can assert the shape
    of a run without touching a warehouse: `len(plan(...)['batched'])` is the number of
    table scans the row-level rules will cost."""
    batched: dict[str, list[Rule]] = {}
    singles: list[tuple[Rule, str]] = []
    unresolved: list[Rule] = []
    for r in rules:
        table = resolve.get(r.target_table, r.target_table)
        sh = shape(r)
        if sh == "row_level":
            batched.setdefault(table, []).append(r)
        elif sh == "uniqueness":
            singles.append((r, uniqueness_sql(table, r)))
        elif sh == "variance":
            singles.append((r, variance_sql(table, r)))
        else:
            if not _blank(r.join_sql):
                singles.append((r, cross_table_sql(r, resolve)))
            else:
                unresolved.append(r)
    return {"batched": batched, "singles": singles, "unresolved": unresolved}


# ---------------------------------------------------------------------------
# Execution — the only part that needs Spark
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default="dq")
    ap.add_argument("--schema", default=None,
                    help="Set for the single-schema sandpit layout rendered by "
                         "sql/render.py. Leave unset for the two-schema layout "
                         "sql/ddl/ declares.")
    ap.add_argument("--prefix", default="dq_")
    ap.add_argument("--fn-prefix", default=None,
                    help="Replaces `dq.fn.` in rule_expr. Must match what sql/seed.py "
                         "was run with. Omit when the registry already holds names "
                         "runnable in this catalog.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the SQL this run would execute and write nothing.")
    a = ap.parse_args()

    def t(schema: str, table: str) -> str:
        if not a.schema:
            return f"{a.catalog}.{schema}.{table}"
        return f"{a.catalog}.{a.schema}.{a.prefix}{schema}_{table}"

    from pyspark.sql import SparkSession           # noqa: PLC0415 -- job-only import
    import datetime as dt

    spark = SparkSession.builder.getOrCreate()
    run_id, run_ts = str(uuid.uuid4()), dt.datetime.now(dt.timezone.utc)

    # THE WORKLIST IS THE CDE REGISTER. A rule runs only if it is current, active or
    # shadow, AND names a registered element: cde_id is NOT NULL on the registry, and
    # an element retired from config.cde_registry takes its rules out of the run with
    # it. A rule on no registered element is not a monitoring rule, and this join is
    # where that sentence becomes true.
    reg = spark.sql(f"""
        SELECT r.*
        FROM   {t('config', 'v_rule_registry_current')} r
        JOIN   {t('config', 'v_cde_registry_current')} e
          ON   e.cde_id = r.cde_id AND e.status = 'registered'
        WHERE  r.status IN ('active', 'shadow')
    """).toPandas()
    rules = [Rule(**{k: v for k, v in row.items() if k in Rule.__annotations__})
             for row in reg.to_dict("records")]
    fn = a.fn_prefix or (f"{a.catalog}.{a.schema}.{a.prefix}fn_" if a.schema
                         else f"{a.catalog}.fn.")
    rules = normalise(rules, fn)

    # In a real deployment the registry already holds production table names and this
    # map is empty. It exists for the sandpit, where sql/seed.py rewrote
    # prod.customer.* to the mock tables, and for any environment whose registry was
    # seeded with names from another one -- the portability problem sql/seed.py's header
    # records. Same map for cross-table joins as for everything else.
    resolve: dict[str, str] = {}
    if a.schema:
        resolve = {"prod.customer.ctct_c": t("", "mock_ctct_c").replace("..", "."),
                   "prod.customer.subs_c": t("", "mock_subs_c").replace("..", ".")}
    p = plan(rules, resolve)

    if p["unresolved"]:
        print(f"!! {len(p['unresolved'])} cross-table rules have no join and will be "
              f"written as status='error': "
              f"{', '.join(r.rule_id for r in p['unresolved'])}")

    if a.dry_run:
        for table, rs in p["batched"].items():
            print(f"\n-- batched: {len(rs)} row-level rules, ONE scan of {table}")
            print(batch_row_level(table, rs))
        for r, sql in p["singles"]:
            print(f"\n-- {shape(r)}: {r.rule_id}\n{sql}")
        return 0

    measured: dict[str, tuple[int, int]] = {}
    for table, rs in p["batched"].items():
        row = spark.sql(batch_row_level(table, rs)).collect()[0].asDict()
        for r in rs:
            measured[r.rule_id] = (int(row[_alias("s", r.rule_id)] or 0),
                                   int(row[_alias("v", r.rule_id)] or 0))
    for r, sql in p["singles"]:
        row = spark.sql(sql).collect()[0].asDict()
        measured[r.rule_id] = (int(row["rows_scanned"] or 0),
                               int(row["violation_count"] or 0))

    verdicts, samples = [], []
    for r in rules:
        if r.rule_id not in measured:
            verdicts.append(dict(
                result_id=str(uuid.uuid4()), run_id=run_id, run_ts=run_ts,
                rule_id=r.rule_id, rule_version=int(r.rule_version),
                source_layer=r.source_layer, target_table=r.target_table,
                target_column=r.target_column, rows_scanned=None,
                violation_count=None, violation_pct=None,
                threshold_pct=float(r.fail_threshold_pct), status="error",
                severity=r.severity, business_domain=r.business_domain,
                owner_group=r.owner_group, scope_fingerprint=None,
                message="not executed: cross-table rule with no join_sql in the "
                        "registry",
                duration_sec=None, dbu_estimate=None))
            continue
        scanned, viol = measured[r.rule_id]
        status, pct, msg = verdict(r, scanned, viol)
        result_id = str(uuid.uuid4())
        verdicts.append(dict(
            result_id=result_id, run_id=run_id, run_ts=run_ts,
            rule_id=r.rule_id, rule_version=int(r.rule_version),
            source_layer=r.source_layer, target_table=r.target_table,
            target_column=r.target_column, rows_scanned=scanned,
            violation_count=viol, violation_pct=pct,
            # Copied, never recomputed -- 03's header calls recomputation the defect.
            threshold_pct=float(r.fail_threshold_pct), severity=r.severity,
            status=status, business_domain=r.business_domain,
            owner_group=r.owner_group,
            scope_fingerprint=None,      # open question, see 03_results_check_run.sql
            message=msg, duration_sec=None, dbu_estimate=None))
        if status == "breach":
            tgt = resolve.get(r.target_table, r.target_table)
            rows = spark.sql(sample_sql(r, tgt, resolve)).limit(SAMPLE_CAP).toPandas()
            import json
            for _, sr in rows.iterrows():
                d = {k: (None if v is None else str(v)) for k, v in sr.to_dict().items()}
                samples.append(dict(
                    sample_id=str(uuid.uuid4()), result_id=result_id, run_id=run_id,
                    rule_id=r.rule_id, target_table=r.target_table,
                    row_key=str(d.get("SUBS_KEY") or d.get("CTCT_KEY") or ""),
                    sample_row=json.dumps(d), captured_ts=run_ts))

    spark.createDataFrame(verdicts).write.mode("append").saveAsTable(
        t("results", "check_run"))
    if samples:
        spark.createDataFrame(samples).write.mode("append").saveAsTable(
            t("results", "violation_sample"))

    by = {}
    for v in verdicts:
        by[v["status"]] = by.get(v["status"], 0) + 1
    print(f"run {run_id}: {len(verdicts)} verdicts {by}, {len(samples)} samples, "
          f"{len(p['batched'])} batched scans + {len(p['singles'])} single queries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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

DATA SLICES (2026-10-06)
------------------------
A table's slice (`config.monitored_table.slice_filter`) is the population every check on
it draws from. It is applied HERE, at run time, rather than written into each rule, so
changing a slice is one table version and not an append per rule -- which means the rule
row alone no longer says what was measured, and every verdict is stamped with the
`slice_version` it ran under and the table's `table_rows` / `slice_rows`.

* Row-level rules: the batched aggregate reads the sliced relation, and `count(*)` over
  it is `slice_rows`. The slice cannot be ANDed into each `count_if` instead: Spark
  allows an IN-subquery only in a filter, and a membership slice is one.
* Uniqueness, variance: their FROM is the sliced relation, so a key is unique WITHIN the
  slice and a column varies within it.
* Cross-table: only the DRIVING table (`target_table`) is sliced. Slicing the other side
  too would make a subscription whose contact sits outside the contact table's slice an
  orphan, which is a statement about the slice, not the data. The POPULATION below is
  different and goes on every side.
* `table_rows` is a bare `count(*)`, which Delta answers from the log.

The slice is built by the app from a structured spec (dq_app/domain/slices.py) and is
trusted config like `rule_expr`.

THE POPULATION (2026-10-12)
---------------------------
A history table holds every version of a record. `config.table_population`
(sql/ddl/21) says how to find the current one: the newest version of each
`record_key` by `version_by`, dropped when it is a deletion. `current()` builds that
relation, and it is applied UNDER the slice -- the slice narrows current records, never
raw versions -- so every count nests: table_rows >= population_rows >= slice_rows.

* Latest first, deletions after. Filtering `OP_TYPE <> 'D'` in the same SELECT as the
  window would run before it and make a deleted record's previous version current.
* On EVERY table of a join, not just the driving one. An orphan check that matched a
  child against any old version of its parent would pass on a parent deleted last week;
  dropping a deleted parent is what makes the child an orphan, which is the truth.
* Ties are broken arbitrarily, so a declaration names enough columns to be total.
* Stamped on every verdict as `population_version` / `population_rows`. A table with
  no declaration reads exactly as before, and every builder below emits the same SQL
  for it -- `dq_app/domain/rule_sql.py`'s copy is diffed against these on that basis.

JOINS SHARE A QUERY TOO (2026-10-12)
------------------------------------
Cross-table rules whose join comes out identical -- same tables, same ON, same
population and slice -- are folded into one aggregate the same way row-level rules on
a table are: `count_if(scope)` and `count_if(scope AND expr)` per rule over one join.
The equivalence argument is the one above. Two exceptions run alone: a rule whose
`scope_filter` holds a subquery (Spark allows one only in a WHERE, where the single
query keeps it) and a join no other rule shares, whose SQL is then exactly what it was.

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
COLUMN_OK = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,254}$")

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


@dataclass(frozen=True)
class Population:
    """One table's current-record declaration, from config.table_population."""
    record_key: tuple[str, ...] = ()
    version_by: tuple[str, ...] = ()
    deleted_column: str | None = None
    deleted_value: str | None = None
    version: int | None = None

    def narrows(self) -> bool:
        return bool(self.version_by) or not _blank(self.deleted_column)


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


def _col(name: str) -> str:
    """A declared column, backticked. Column names come from config, not from a steward
    typing SQL, so one that is not a plain identifier stops the run."""
    if not COLUMN_OK.match(str(name)):
        raise ValueError(f"population column {name!r} is not a plain identifier")
    return f"`{name}`"


def _lit(v) -> str:
    """A string literal. Spark's literals take backslash escapes, so both are escaped."""
    return "'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'"


def current(table: str, pop: Population | None) -> str:
    """The table's current records: the newest version per record, then deletions out.

    Two nested SELECTs because the order matters: a WHERE beside the QUALIFY would drop
    deleted versions BEFORE the window picks the newest, and the version before the
    deletion would come back as the record.

    A row with a NULL in its record key is kept, every one of them: it cannot be tied
    to its other versions, and the window would otherwise put every keyless row in one
    partition and keep one -- hiding exactly the rows a missing-key check exists to
    count. Found on the mock contact table, where it hid planted defects."""
    if pop is None or not pop.narrows():
        return table
    src = table
    if pop.version_by:
        keys = ", ".join(_col(k) for k in pop.record_key)
        keyless = " OR ".join(f"{_col(k)} IS NULL" for k in pop.record_key)
        order = ", ".join(f"{_col(c)} DESC NULLS LAST" for c in pop.version_by)
        src = (f"(SELECT * FROM {table} QUALIFY row_number() OVER "
               f"(PARTITION BY {keys} ORDER BY {order}) = 1 OR {keyless})")
    if not _blank(pop.deleted_column):
        src = (f"(SELECT * FROM {src} WHERE NOT ({_col(pop.deleted_column)} <=> "
               f"{_lit(pop.deleted_value)}))")
    return src


def relation(table: str, slice_filter: str | None, pop: Population | None = None) -> str:
    """The table, or the rows of it in its slice. Parenthesised so it stands anywhere a
    table name does -- after FROM, before a join alias, inside a variance expression.
    The population, when declared, is underneath: the slice narrows current records."""
    base = current(table, pop)
    if _blank(slice_filter):
        return base
    return f"(SELECT * FROM {base} WHERE {slice_filter})"


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
    parts = ["  count(*) AS __slice_rows"]
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


def _join(r: Rule, resolve: dict[str, str], slices: dict[str, str] | None,
          pops: dict[str, Population] | None = None) -> str:
    """`join_sql` with table names resolved, every table with a declared population
    replaced by its current records, and the DRIVING table also by its slice.
    Resolution first, so both are found under the physical name."""
    join = r.join_sql
    for k, v in resolve.items():
        join = join.replace(k, v)
    driving = resolve.get(r.target_table, r.target_table)
    swap: dict[str, str] = {}
    for name, pop in (pops or {}).items():
        phys = resolve.get(name, name)
        if phys != driving and pop.narrows():
            swap[phys] = current(phys, pop)
    sf = (slices or {}).get(r.target_table)
    dp = (pops or {}).get(r.target_table)
    if not _blank(sf) or (dp is not None and dp.narrows()):
        swap[driving] = relation(driving, sf, dp)
    if swap:
        # Whole names only: a plain replace would also rewrite `..._subs_c_hist`. One
        # pass over every name, longest first, so no replacement is scanned again.
        names = sorted(swap, key=len, reverse=True)
        pat = "|".join(re.escape(n) for n in names)
        join = re.sub(rf"(?<![\w.`])(?:{pat})(?![\w`])",
                      lambda m: swap[m.group(0)], join)
    return join


def cross_table_sql(r: Rule, resolve: dict[str, str],
                    slices: dict[str, str] | None = None,
                    pops: dict[str, Population] | None = None) -> str:
    """A join the registry has no column for. `resolve` is the table-name map."""
    join = _join(r, resolve, slices, pops)
    where = "" if _blank(r.scope_filter) else f"\n  WHERE {r.scope_filter}"
    return (f"SELECT count(*) AS rows_scanned,\n"
            f"       count_if({r.rule_expr}) AS violation_count\n"
            f"FROM   {join}{where}")


def batch_cross_table(join: str, rules: list[Rule]) -> str:
    """ONE aggregate over one join for every cross-table rule that shares it. The same
    two counters per rule as `batch_row_level`, and the same equivalence: what the
    single query's WHERE keeps, `count_if(scope)` counts."""
    parts = ["  count(*) AS __joined_rows"]
    for r in rules:
        sc = scope_sql(r)
        parts.append(f"  count_if({sc}) AS {_alias('s', r.rule_id)}")
        parts.append(f"  count_if({sc} AND ({r.rule_expr})) AS {_alias('v', r.rule_id)}")
    return "SELECT\n" + ",\n".join(parts) + f"\nFROM {join}"


def _joins_batchable(r: Rule) -> bool:
    """A scope holding a subquery cannot move into a count_if; Spark refuses it there."""
    return _blank(r.scope_filter) or not re.search(r"\bSELECT\b", str(r.scope_filter),
                                                    re.IGNORECASE)


def sample_sql(r: Rule, table: str, resolve: dict[str, str], cap: int = SAMPLE_CAP,
               slices: dict[str, str] | None = None,
               pops: dict[str, Population] | None = None) -> str:
    """Up to `cap` offending rows for a breach. Raising the cap widens what the AI layer
    sees of production data, so it is a governance change -- see 04's header. `table`
    is already the sliced relation when the table has a slice (and its current records
    when it declares a population)."""
    sh = shape(r)
    if sh == "cross_table":
        src, pred = _join(r, resolve, slices, pops), r.rule_expr
    elif sh == "uniqueness":
        src, pred = f"(SELECT *, {r.rule_expr} AS __dup FROM {table})", "__dup"
    elif sh == "variance":
        src, pred = table, "TRUE"
    else:
        src, pred = table, f"({r.rule_expr})"
    scope = "" if _blank(r.scope_filter) else f" AND {r.scope_filter}"
    return f"SELECT * FROM {src}\nWHERE  {pred}{scope}\nLIMIT  {cap}"


def sample_keep(r: Rule, columns: list[str], keys: list[str] | None) -> list[int]:
    """Which columns of a sample row are stored: the row's key and the columns the rule
    reads, never the rest of the row. Positions, not names, because a join's `SELECT *`
    can return the same name twice.

    `sample_sql` stays `SELECT *` -- it is also the rule logic the app prints -- and the
    projection is applied to its result instead. "Reads" is a whole-word, case-insensitive
    match of the column name in the expression, scope, join and target column. That
    over-includes rather than under-includes: a column whose name happens to be an alias
    is kept, a column the rule tests is never dropped."""
    text = " ".join(str(v) for v in (r.rule_expr, r.scope_filter, r.join_sql, r.target_column)
                    if not _blank(v))
    key_set = {k.lower() for k in (keys or ["SUBS_KEY", "CTCT_KEY"])}
    return [i for i, c in enumerate(columns)
            if c.lower() in key_set
            or re.search(rf"(?<!\w){re.escape(c)}(?!\w)", text, re.IGNORECASE)]


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


def plan(rules: list[Rule], resolve: dict[str, str],
         slices: dict[str, str] | None = None,
         pops: dict[str, Population] | None = None) -> dict:
    """Group rules into the queries that will run. Pure, so a test can assert the shape
    of a run without touching a warehouse: `len(plan(...)['batched'])` is the number of
    table scans the row-level rules will cost, `len(plan(...)['joined'])` the joins the
    cross-table rules will cost beyond the singles. `slices` maps a registry table name
    to its slice predicate and `pops` to its population; `batched` is keyed by the
    relation the scan reads and `joined` by the join."""
    batched: dict[str, list[Rule]] = {}
    joined: dict[str, list[Rule]] = {}
    singles: list[tuple[Rule, str]] = []
    unresolved: list[Rule] = []
    for r in rules:
        table = relation(resolve.get(r.target_table, r.target_table),
                         (slices or {}).get(r.target_table),
                         (pops or {}).get(r.target_table))
        sh = shape(r)
        if sh == "row_level":
            batched.setdefault(table, []).append(r)
        elif sh == "uniqueness":
            singles.append((r, uniqueness_sql(table, r)))
        elif sh == "variance":
            singles.append((r, variance_sql(table, r)))
        elif _blank(r.join_sql):
            unresolved.append(r)
        elif _joins_batchable(r):
            joined.setdefault(_join(r, resolve, slices, pops), []).append(r)
        else:
            singles.append((r, cross_table_sql(r, resolve, slices, pops)))
    # A join only one rule reads stays the single query it always was.
    for join in [j for j, rs in joined.items() if len(rs) == 1]:
        r = joined.pop(join)[0]
        singles.append((r, cross_table_sql(r, resolve, slices, pops)))
    return {"batched": batched, "joined": joined, "singles": singles,
            "unresolved": unresolved}


# ---------------------------------------------------------------------------
# Execution — the only part that needs Spark
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
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
    ap.add_argument("--tables", default=None,
                    help="Comma-separated target tables to check. Without it the run takes "
                         "the selected tables from config.monitored_table when that table "
                         "exists, and every table otherwise.")
    ap.add_argument("--shadow-only", action="store_true",
                    help="Run only shadow rules. For the event-triggered onboarding job: a "
                         "shadow result raises nothing, so measuring new checks the moment "
                         "they are generated is safe, while active results stay on the "
                         "daily schedule.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the SQL this run would execute and write nothing.")
    a = ap.parse_args(argv)

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

    # WHICH TABLES. config.monitored_table is the selection and carries each table's row
    # key; a schema without it (the dq_triage sandpit) runs everything, as before.
    selected, row_keys, sliced = select_tables(spark, t("config", "monitored_table"), a.tables)
    slices = {k: f for k, (f, _v) in sliced.items()}
    if slices:
        print(f"sliced: {', '.join(sorted(slices))}")
    pops = read_populations(spark, t("config", "table_population"))
    if pops:
        print(f"current records only: {', '.join(sorted(pops))}")
    if selected is not None:
        rules = [r for r in rules if r.target_table in selected]
        print(f"checking {len(selected)} selected tables: {', '.join(sorted(selected))}")
    if a.shadow_only:
        rules = [r for r in rules if r.status == "shadow"]
        print(f"shadow only: {len(rules)} rules")
        if not rules:
            return 0

    # In a real deployment the registry already holds production table names and this
    # map is empty. It exists for the sandpit, where sql/seed.py rewrote
    # prod.customer.* to the mock tables, and for any environment whose registry was
    # seeded with names from another one -- the portability problem sql/seed.py's header
    # records. Same map for cross-table joins as for everything else.
    resolve: dict[str, str] = {}
    if a.schema:
        resolve = {"prod.customer.ctct_c": t("", "mock_ctct_c").replace("..", "."),
                   "prod.customer.subs_c": t("", "mock_subs_c").replace("..", ".")}
    p = plan(rules, resolve, slices, pops)

    if p["unresolved"]:
        print(f"!! {len(p['unresolved'])} cross-table rules have no join and will be "
              f"written as status='error': "
              f"{', '.join(r.rule_id for r in p['unresolved'])}")

    if a.dry_run:
        for table, rs in p["batched"].items():
            print(f"\n-- batched: {len(rs)} row-level rules, ONE scan of {table}")
            print(batch_row_level(table, rs))
        for join, rs in p["joined"].items():
            print(f"\n-- joined: {len(rs)} cross-table rules, ONE join")
            print(batch_cross_table(join, rs))
        for r, sql in p["singles"]:
            print(f"\n-- {shape(r)}: {r.rule_id}\n{sql}")
        return 0

    # One table failing must not stop the others: a query that raises becomes an
    # `error` verdict for exactly the rules it carried, with the reason in `message`.
    measured: dict[str, tuple[int, int]] = {}
    failed: dict[str, str] = {}
    # (table_rows, population_rows, slice_rows) per registry table name, stamped on
    # every verdict on it. Each extra count runs only when something narrowed the table.
    population: dict[str, tuple[int | None, int | None, int | None]] = {}

    def _count(rel: str) -> int | None:
        try:
            return int(spark.sql(f"SELECT count(*) AS n FROM {rel}").collect()[0]["n"])
        except Exception:                           # noqa: BLE001 -- population unknown
            return None

    for table, rs in p["batched"].items():
        try:
            row = spark.sql(batch_row_level(table, rs)).collect()[0].asDict()
        except Exception as exc:                    # noqa: BLE001 -- recorded, not hidden
            for r in rs:
                failed[r.rule_id] = f"not executed: {table} scan failed: {_first_line(exc)}"
            continue
        name = rs[0].target_table
        phys, pop = resolve.get(name, name), pops.get(name)
        sliced_n = int(row["__slice_rows"] or 0)
        narrowed = pop is not None and pop.narrows()
        if narrowed:
            current_n = sliced_n if _blank(slices.get(name)) else _count(current(phys, pop))
        else:
            current_n = None
        whole = (_count(phys) if narrowed or not _blank(slices.get(name))
                 else sliced_n)
        population[name] = (whole, current_n, sliced_n)
        for r in rs:
            measured[r.rule_id] = (int(row[_alias("s", r.rule_id)] or 0),
                                   int(row[_alias("v", r.rule_id)] or 0))
    for join, rs in p["joined"].items():
        try:
            row = spark.sql(batch_cross_table(join, rs)).collect()[0].asDict()
        except Exception as exc:                    # noqa: BLE001 -- recorded, not hidden
            for r in rs:
                failed[r.rule_id] = f"not executed: shared join failed: {_first_line(exc)}"
            continue
        for r in rs:
            measured[r.rule_id] = (int(row[_alias("s", r.rule_id)] or 0),
                                   int(row[_alias("v", r.rule_id)] or 0))
    for r, sql in p["singles"]:
        try:
            row = spark.sql(sql).collect()[0].asDict()
        except Exception as exc:                    # noqa: BLE001
            failed[r.rule_id] = f"not executed: query failed: {_first_line(exc)}"
            continue
        measured[r.rule_id] = (int(row["rows_scanned"] or 0),
                               int(row["violation_count"] or 0))

    def _stamp(name: str) -> dict:
        tr, pr, sr = population.get(name, (None, None, None))
        pop = pops.get(name)
        return dict(slice_version=sliced.get(name, (None, None))[1],
                    table_rows=tr, slice_rows=sr, population_rows=pr,
                    population_version=pop.version if pop is not None and pop.narrows()
                    else None)

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
                message=failed.get(r.rule_id, "not executed: cross-table rule with no "
                                              "join_sql in the registry"),
                duration_sec=None, dbu_estimate=None, **_stamp(r.target_table)))
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
            message=msg, duration_sec=None, dbu_estimate=None, **_stamp(r.target_table)))
        if status == "breach":
            tgt = relation(resolve.get(r.target_table, r.target_table),
                           slices.get(r.target_table), pops.get(r.target_table))
            # Sampling reads the rows themselves, so a predicate that only errors on some
            # values (a date cast meeting '31-02-1988' under ANSI) can fail here after the
            # count succeeded. The verdict stands; the missing sample is said in the
            # message instead of taking every other table's verdicts down with it.
            try:
                df = spark.sql(sample_sql(r, tgt, resolve, slices=slices, pops=pops))
                keep = sample_keep(r, df.columns, row_keys.get(r.target_table))
                # Renamed by position first: a join's duplicate names cannot be selected.
                names = [f"{c}#{i}" for i, c in enumerate(df.columns)]
                rows = (df.toDF(*names).select(*[f"`{names[i]}`" for i in keep])
                          .toDF(*[df.columns[i] for i in keep])
                          .limit(SAMPLE_CAP).toPandas())
            except Exception as exc:                # noqa: BLE001 -- recorded, not hidden
                verdicts[-1]["message"] += f" | samples not captured: {_first_line(exc)}"
                continue
            import json
            for _, sr in rows.iterrows():
                d = {k: (None if v is None else str(v)) for k, v in sr.to_dict().items()}
                samples.append(dict(
                    sample_id=str(uuid.uuid4()), result_id=result_id, run_id=run_id,
                    rule_id=r.rule_id, target_table=r.target_table,
                    row_key=row_key(d, row_keys.get(r.target_table)),
                    sample_row=json.dumps(d), captured_ts=run_ts))

    # Written against the target table's own schema. Inferring it fails outright:
    # scope_fingerprint, duration_sec and dbu_estimate are None on every row, and Spark
    # cannot infer a type for a column with no values (CANNOT_DETERMINE_TYPE -- the same
    # failure notebook 03 hit on its first job run).
    append(spark, verdicts, t("results", "check_run"))
    if samples:
        append(spark, samples, t("results", "violation_sample"))

    by = {}
    for v in verdicts:
        by[v["status"]] = by.get(v["status"], 0) + 1
    print(f"run {run_id}: {len(verdicts)} verdicts {by}, {len(samples)} samples, "
          f"{len(p['batched'])} batched scans + {len(p['joined'])} shared joins + "
          f"{len(p['singles'])} single queries")
    return 0


def select_tables(spark, monitored: str, cli: str | None):
    """(selected tables or None for all, {table: row key columns},
    {table: (slice_filter, slice_version)}).

    --tables wins; otherwise the current version of each config.monitored_table row
    with status 'selected'. A missing monitored_table means no selection exists, which
    is the sandpit's state, and every table runs. The latest version carries the slice
    in force (a pending proposal is not in force); a table that predates the slice
    columns reads as unsliced."""
    keys: dict[str, list[str]] = {}
    sliced: dict[str, tuple[str | None, int | None]] = {}
    try:
        rows = spark.sql(f"""
            SELECT * FROM (
              SELECT *, ROW_NUMBER() OVER (PARTITION BY target_table
                                           ORDER BY table_version DESC) AS rn
              FROM {monitored}) WHERE rn = 1""").collect()
    except Exception:                               # noqa: BLE001 -- table absent
        rows = []
    for r in rows:
        d = r.asDict()
        keys[d["target_table"]] = list(d["row_key"] or [])
        if not _blank(d.get("slice_filter")) or d.get("slice_version") is not None:
            sv = d.get("slice_version")
            sliced[d["target_table"]] = (d.get("slice_filter"),
                                         None if sv is None else int(sv))
    if cli:
        return {x.strip() for x in cli.split(",") if x.strip()}, keys, sliced
    if rows:
        return {r["target_table"] for r in rows if r["status"] == "selected"}, keys, sliced
    return None, keys, sliced


def read_populations(spark, table: str) -> dict[str, Population]:
    """{registry table name: its population in force}, from the latest version of each
    config.table_population row. A schema without the table, or a table with no row,
    reads every table whole -- what every run did before 2026-10-12."""
    try:
        rows = spark.sql(f"""
            SELECT * FROM (
              SELECT *, ROW_NUMBER() OVER (PARTITION BY target_table
                                           ORDER BY population_version DESC) AS rn
              FROM {table}) WHERE rn = 1""").collect()
    except Exception:                               # noqa: BLE001 -- table absent
        return {}
    return {d["target_table"]: population_of(d) for d in (r.asDict() for r in rows)}


def population_of(d: dict) -> Population:
    """One table_population row as the runner reads it. Pure, so a test can build one."""
    return Population(record_key=tuple(d.get("record_key") or ()),
                      version_by=tuple(d.get("version_by") or ()),
                      deleted_column=None if _blank(d.get("deleted_column"))
                      else d["deleted_column"],
                      deleted_value=d.get("deleted_value"),
                      version=None if d.get("population_version") is None
                      else int(d["population_version"]))


def row_key(sample: dict, keys: list[str] | None) -> str:
    """The sampled row's identity, from the table's declared key columns. The fallback is
    the two sandpit keys this job used to hardcode, for a schema with no selection."""
    if keys:
        return "|".join(str(sample.get(k) or "") for k in keys)
    return str(sample.get("SUBS_KEY") or sample.get("CTCT_KEY") or "")


def append(spark, rows: list[dict], table: str) -> None:
    schema = spark.table(table).schema
    data = [tuple(row.get(f.name) for f in schema.fields) for row in rows]
    spark.createDataFrame(data, schema).write.mode("append").saveAsTable(table)


def _first_line(exc: Exception) -> str:
    return next((ln for ln in str(exc).splitlines() if ln.strip()), type(exc).__name__)[:300]


if __name__ == "__main__":
    # Exit only on failure: a serverless Python task runs under IPython, which reports
    # SystemExit(0) as a failed task even though the run wrote everything it should.
    rc = main()
    if rc:
        raise SystemExit(rc)

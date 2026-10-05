"""A rule as the query the check runner runs for it — for reading, never for running.

The Rules page prints this under "Rule logic". It is not an illustration: for every
shape but variance it is `jobs/run_checks.sample_sql` without its `LIMIT` — the query
that fetches the rows a rule flags — and for variance, whose sample is every row in
scope, it is `variance_sql`, the count the verdict comes from.
`tests/test_rules_page.py` diffs both against the runner for every rule in the
registry, so if the runner changes how it builds a query this copy is told.

It is a copy rather than an import because only `dq-app/` ships to the container.
Names stay canonical (`prod.customer.ctct_c`, `dq.fn.is_blank_v1`): they are rewritten
per workspace at seed time, and the page says so beside the code.
"""

from __future__ import annotations


def _blank(v) -> bool:
    return v is None or v != v or not str(v).strip()


def shape(rule) -> str:
    """Same decision as `run_checks.shape`: keyed on the expression, not rule_type."""
    if not _blank(rule.get("join_sql")):
        return "cross_table"
    if "OVER (PARTITION BY" in str(rule["rule_expr"]):
        return "uniqueness"
    if "{table}" in str(rule["rule_expr"]):
        return "variance"
    return "row_level"


def rule_logic(rule) -> str:
    """The runner's query for one registry row (a dict or a pandas Series)."""
    table, expr, scope_f = rule["target_table"], str(rule["rule_expr"]), rule.get("scope_filter")
    sh = shape(rule)
    if sh == "variance":
        where = "" if _blank(scope_f) else f"\n  WHERE {scope_f}"
        return (f"SELECT count(*) AS rows_scanned,\n"
                f"       CASE WHEN {expr.replace('{table}', table)} THEN count(*) "
                f"ELSE 0 END AS violation_count\n"
                f"FROM   {table}{where}")
    if sh == "cross_table":
        src, pred = rule["join_sql"], expr
    elif sh == "uniqueness":
        src, pred = f"(SELECT *, {expr} AS __dup FROM {table})", "__dup"
    else:
        src, pred = table, f"({expr})"
    scope = "" if _blank(scope_f) else f" AND {scope_f}"
    return f"SELECT * FROM {src}\nWHERE  {pred}{scope}"

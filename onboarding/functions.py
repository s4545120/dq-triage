"""Which function a rule implements: a UC function, a DQX check, or inline SQL.

Since 2026-10-23 `config.rule_registry` records it in two columns:

* `function_source` -- `uc` (a stored Unity Catalog function, `dq.fn.<name>`), `dqx` (a
  check function from the Databricks Labs DQX library) or `sql` (an expression no
  function covers yet).
* `function_name` -- the function: `is_valid_email_v1` for uc, `is_not_null` for dqx,
  NULL for sql.

This is a RECORD, not an execution path: the check runner still runs `rule_expr`, the
SQL. A dqx name says which DQX check the SQL is equivalent to, so a rule can move to
DQX later without its meaning changing. `classify` is conservative: it names a DQX check
only when the whole expression is that check on one column, and everything else is
`sql` until someone writes a function for it.

Pure: no warehouse, no pandas. The fixture, the key-attribute register, the onboarding
job and the migration all call it, so a rule is classified the same way everywhere.
"""

from __future__ import annotations

import re

SOURCES = ("uc", "dqx", "sql")

# DQX row- and dataset-level check functions this register maps onto.
DQX_CHECKS = ("is_not_null", "is_not_null_and_not_empty", "is_in_list", "regex_match",
              "is_not_in_future", "is_unique", "foreign_key")

_ID = r"[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)?"          # col or alias.col
# One column as the rules write it: bare, or inside cast(... AS STRING) and any of
# trim / upper / lower. Parentheses are matched loosely; fullmatch keeps it to one column.
_V = (r"(?:(?:upper|lower|trim)\(\s*)*(?:cast\(\s*)?" + _ID
      + r"(?:\s+AS\s+STRING\s*\))?(?:\s*\))*")
_RE = r"'(?:[^']|'')*'"
_UC = re.compile(r"\bdq\.fn\.(\w+)\s*\(|\b\w*?fn_(\w+_v\d+)\s*\(")
_LIT = r"'(?:[^']|'')*'|-?\d+(?:\.\d+)?"


def _norm(expr: str) -> str:
    return re.sub(r"\s+", " ", (expr or "").strip()).rstrip(";")


def classify(rule_expr: str | None, rule_type: str | None = None,
             join_sql: str | None = None) -> tuple[str, str | None]:
    """(function_source, function_name) for one rule."""
    e = _norm(rule_expr or "")
    m = _UC.search(e)
    if m:
        return "uc", m.group(1) or m.group(2)
    if rule_type == "uniqueness":
        return "dqx", "is_unique"
    if rule_type == "referential" and join_sql:
        return "dqx", "foreign_key"
    if re.fullmatch(rf"\(?{_V} IS NULL\)?", e, re.I):
        return "dqx", "is_not_null"
    if re.fullmatch(rf"\(?({_ID}) IS NULL OR trim\((?:cast\()?\1(?: AS STRING\))?\) = ''\)?",
                    e, re.I):
        return "dqx", "is_not_null_and_not_empty"
    # regex_match covers both senses: DQX takes negate=True for a pattern that must not match.
    if re.fullmatch(rf"(?:{_ID} IS NOT NULL AND )?(?:NOT \(?)?{_V} (?:NOT )?RLIKE {_RE}\)?", e, re.I):
        return "dqx", "regex_match"
    if re.fullmatch(rf"(?:{_ID} IS NOT NULL AND )?{_V} NOT IN \((?:\s*(?:{_LIT})\s*,?)+\)", e, re.I):
        return "dqx", "is_in_list"
    if re.fullmatch(rf"\(?(?:to_date\(\s*)?(?:timestamp_millis\(\s*)?(?:try_cast\(\s*)?{_V}"
                    rf"(?:\s+AS\s+BIGINT\s*\))?(?:\s*\))* > current_(?:date|timestamp)\(\)\)?",
                    e, re.I):
        return "dqx", "is_not_in_future"
    return "sql", None


def problem(source: str | None, name: str | None) -> str | None:
    """Why a (source, name) pair is not storable, or None. The table's CHECK says the
    same: a known source, a name for uc and dqx, none for sql."""
    if source is None:
        return None if name is None else "a function name needs a source"
    if source not in SOURCES:
        return f"function_source must be one of {', '.join(SOURCES)}"
    if source == "sql":
        return None if name is None else "an inline-SQL rule names no function"
    if not name:
        return f"a {source} rule names its function"
    if source == "dqx" and name not in DQX_CHECKS:
        return f"{name} is not a DQX check this register knows"
    return None

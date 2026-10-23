#!/usr/bin/env python3
"""Record which function every rule implements: a UC function, a DQX check, or inline SQL.

    .venv/bin/python sql/migrate_rule_function.py --schema dq_triage            # EXPLAIN only
    .venv/bin/python sql/migrate_rule_function.py --schema dq_triage --apply
    .venv/bin/python sql/migrate_rule_function.py --schema dq_onboard --apply --no-backfill

Since 2026-10-23 `config.rule_registry` carries `function_source` (uc | dqx | sql) and
`function_name`, declared at the end of sql/ddl/01 where ADD COLUMNS puts them. This
script, in order:

1. adds the two columns if they are missing, and the two CHECK constraints;
2. re-creates `v_rule_registry_current` (sql/ddl/08), because a view freezes its column
   list at creation and would not show the new columns;
3. unless --no-backfill, appends ONE new rule_version for every current, non-retired
   rule whose function is not yet recorded, classified by onboarding/functions.py and
   everything else carried forward. A record, not a behaviour change: the runner still
   runs rule_expr, and each note says so.

It reads the register to classify, so unlike the other migrations it talks to the
warehouse. Without --apply every statement is EXPLAINed and nothing is written.
RE-RUNNABLE: step 3 is guarded on function_source IS NULL, so a second run inserts 0.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).parent.parent
sys.path[:0] = [str(ROOT / "onboarding"), str(pathlib.Path(__file__).parent)]

import functions  # noqa: E402
import render  # noqa: E402
import wh  # noqa: E402
from migrate_cde_scope import RULE_COLUMNS, lit  # noqa: E402

COLS = RULE_COLUMNS + ["template_id", "template_version", "function_source", "function_name"]
NOTE = ("Records the function this rule implements (function_source / function_name, "
        "2026-10-23). No behaviour change: the runner still runs rule_expr.")
_BAD = ("UNRESOLVED", "Error occurred", "PARSE_SYNTAX", "AnalysisException", "cannot be resolved")


def statements(conn, catalog: str, schema: str, prefix: str, backfill: bool):
    q = f"{catalog}.{schema}.{prefix}"
    reg = f"{q}config_rule_registry"
    have = {r["column_name"] for r in wh.run(conn, f"""
        SELECT column_name FROM {catalog}.information_schema.columns
        WHERE table_schema = '{schema}' AND table_name = '{prefix}config_rule_registry'""")}
    out = []
    if "function_source" not in have:
        out.append(("columns", "ddl", f"ALTER TABLE {reg} ADD COLUMNS "
                                      "(function_source STRING, function_name STRING)"))
    out.append(("check:source", "constraint",
                f"ALTER TABLE {reg} ADD CONSTRAINT rule_registry_function_source_enum "
                "CHECK (function_source IS NULL OR function_source IN ('uc', 'dqx', 'sql'))"))
    out.append(("check:named", "constraint",
                f"ALTER TABLE {reg} ADD CONSTRAINT rule_registry_function_named "
                "CHECK ((function_name IS NULL) = (function_source IS NULL OR function_source = 'sql'))"))
    view = next(s for s in render.statements(render.render(
        (ROOT / "sql/ddl/08_views.sql").read_text(), catalog, schema, prefix))
        if "v_rule_registry_current" in s.split("\n", 1)[0])
    out.append(("view", "view", view))
    if backfill and "function_source" in have:
        rules = wh.run(conn, f"""SELECT rule_id, rule_expr, rule_type, join_sql
            FROM {q}config_v_rule_registry_current WHERE function_source IS NULL""")
        if rules:
            pairs = ", ".join(
                f"({lit(r['rule_id'])}, {lit(s)}, {lit(n)})"
                for r in rules
                for s, n in [functions.classify(r["rule_expr"], r["rule_type"], r["join_sql"])])
            sel = [{"rule_version": "r.rule_version + 1", "effective_from": "current_timestamp()",
                    "created_by": "current_user()", "created_at": "current_timestamp()",
                    "note": f"concat({lit(NOTE + ' ')}, coalesce(r.note, ''))",
                    "function_source": "f.src", "function_name": "f.name"}.get(c, f"r.{c}")
                   for c in COLS]
            out.append(("backfill", "insert",
                        f"INSERT INTO {reg} ({', '.join(COLS)})\n"
                        f"SELECT {', '.join(sel)}\n"
                        f"FROM (SELECT x.*, ROW_NUMBER() OVER (PARTITION BY x.rule_id "
                        f"ORDER BY x.rule_version DESC) AS rn FROM {reg} x) r\n"
                        f"JOIN (SELECT * FROM VALUES {pairs} AS v(rule_id, src, name)) f "
                        f"ON f.rule_id = r.rule_id\n"
                        f"WHERE r.rn = 1 AND r.status <> 'retired' AND r.function_source IS NULL"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default="workspace")
    ap.add_argument("--schema", default="dq_triage")
    ap.add_argument("--prefix", default="dq_")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--no-backfill", action="store_true")
    a = ap.parse_args()
    with wh.connect() as conn:
        # Two passes when the columns are new: the backfill reads them, so it is planned
        # only once they exist.
        for round_ in (1, 2):
            stmts = statements(conn, a.catalog, a.schema, a.prefix, not a.no_backfill)
            for label, kind, sql in stmts:
                if not a.apply:
                    if kind in ("ddl", "constraint"):
                        print(f"{label}: (DDL, not planned) {sql[:90]}")
                        continue
                    body = re.split(r"\nAS\s*\n", sql, maxsplit=1)[1] if kind == "view" else sql
                    plan = "\n".join(str(r) for r in wh.run(conn, "EXPLAIN " + body))
                    ok = not any(w in plan for w in _BAD) and (kind != "insert" or "AppendData" in plan)
                    print(f"{label}: {'planned clean' if ok else 'FAIL ' + plan[:500]}")
                    continue
                try:
                    res = wh.run(conn, sql)
                except Exception as e:  # an existing constraint is not an error
                    if kind == "constraint" and "already exists" in str(e).lower():
                        print(f"{label}: already there"); continue
                    raise
                n = res[0].get("num_inserted_rows") if (kind == "insert" and res) else None
                print(f"{label}: done" + (f", {n} rows" if n is not None else ""))
            if not a.apply or round_ == 2:
                break
        if a.apply:
            for r in wh.run(conn, f"""SELECT function_source, function_name, COUNT(*) AS rules
                FROM {a.catalog}.{a.schema}.{a.prefix}config_v_rule_registry_current
                GROUP BY 1, 2 ORDER BY 3 DESC"""):
                print(dict(r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

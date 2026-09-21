"""EXPLAIN every SQL statement in a notebook against a warehouse, without running it.

    ../.venv/bin/python tools/explain_notebook.py notebooks/03_group_and_advise.ipynb

The triage notebook is the only thing that writes `results.cohort` in a workspace, it
takes fifteen minutes to run because most of that is model calls, and a broken query
in its last cell fails *after* every one of those calls has been paid for. Three of
the four failures on the first real run were SQL that had never been parsed by
anything -- the same class of gap `CLAUDE.md` records for the `rule_expr` strings.

This substitutes the notebook's table constants into each `spark.sql` string and asks
the warehouse to plan it. Seconds, no compute, nothing written.

ANALYSIS ERRORS DO NOT RAISE. A parse error comes back as an exception; an unresolved
column comes back as a *result row* containing the message, so a checker that only
catches exceptions reports success on `SELECT v.no_such_column`. That is exactly how
the verification cell got through this check twice. The plan text is inspected.

What it cannot check: anything the notebook builds at run time from data it has not
fetched yet. Those are substituted with stand-ins below, so the shape is checked and
the values are not.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

PROFILE = "dbc-19c77b90-423e"
WAREHOUSE = "ebf2cf6b81ca710b"
CATALOG, SCHEMA, PREFIX = "workspace", "dq_triage", "dq_"


def _t(group: str, name: str) -> str:
    return f"{CATALOG}.{SCHEMA}.{PREFIX}{group}_{name}"


NAMES = {
    "CHECK_RUN": _t("results", "check_run"),
    "VIOLATION_SAMPLE": _t("results", "violation_sample"),
    "COHORT": _t("results", "cohort"),
    "DISPOSITION": _t("results", "disposition"),
    "COHORT_CURRENT": _t("results", "v_cohort_current"),
    "CDE_COVERAGE": _t("results", "v_cde_coverage"),
    "RULE_REGISTRY": _t("config", "rule_registry"),
    "PLAYBOOK": _t("config", "playbook"),
    "CDE_REGISTRY": _t("config", "cde_registry"),
}

# Run-time values the notebook does not have yet. Shape is checked, values are not,
# and each stand-in has to be the right SHAPE or the checker reports a failure of its
# own making -- a bare SOME_VALUE where a number belongs reads as an unresolved
# column. That is a false positive, and a checker that cries wolf gets ignored.
STANDINS = {
    '{", ".join(repr(r) for r in sorted(set(failing.rule_id)))}': "'CTCT_EML_FMT'",
    "{quoted}": "'CTCT_EML_FMT'",
    "{run_id}": "SOME_RUN",
    "{SAMPLES_PER_RULE}": "6",
    "{OVERLAP_MIN_RATIO}": "0.5",
}

# Statements that read something built at run time and so cannot be planned ahead of
# it. Only one: the INSERT selects from `candidate_cohorts`, a temp view the write
# cell creates from the model's answers. Skipped by name rather than by silently
# tolerating TABLE_OR_VIEW_NOT_FOUND, which would also hide a real typo.
RUNTIME_ONLY = ("candidate_cohorts",)

# Databricks reports these in the plan text rather than raising.
IN_PLAN = re.compile(r"(UNRESOLVED_COLUMN|UNRESOLVED_ROUTINE|TABLE_OR_VIEW_NOT_FOUND"
                     r"|AnalysisException|cannot be resolved|DATATYPE_MISMATCH)", re.I)


def statements(nb: dict):
    for i, cell in enumerate(nb["cells"]):
        if cell["cell_type"] != "code":
            continue
        src = "".join(cell["source"])
        for m in re.finditer(r'spark\.sql\(f?"""(.*?)"""', src, re.S):
            yield i, m.group(1)
        for m in re.finditer(r'spark\.sql\(\s*\n?\s*f?"([^"]{20,})"', src):
            yield i, m.group(1)


def resolve(sql: str) -> str:
    for k, v in NAMES.items():
        sql = sql.replace("{" + k + "}", v)
    for k, v in STANDINS.items():
        sql = sql.replace(k, v)
    return re.sub(r"\{[^{}]*\}", "SOME_VALUE", sql).strip()


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "notebooks/03_group_and_advise.ipynb")
    nb = json.loads(path.read_text())

    from databricks import sql as dbsql
    from databricks.sdk.core import Config

    cfg = Config(profile=PROFILE)
    found = list(statements(nb))
    bad = 0
    with dbsql.connect(server_hostname=cfg.host.replace("https://", ""),
                       http_path=f"/sql/1.0/warehouses/{WAREHOUSE}",
                       credentials_provider=lambda: cfg.authenticate) as conn:
        for cell, raw in found:
            q = resolve(raw)
            head = q.splitlines()[0][:62]
            if any(name in q for name in RUNTIME_ONLY):
                print(f"cell {cell:>2}  skip  {head}\n          reads a view built at run time")
                continue
            try:
                with conn.cursor() as cur:
                    cur.execute("EXPLAIN " + q)
                    plan = "\n".join(str(v) for r in cur.fetchall() for v in r)
                hit = IN_PLAN.search(plan)
                if hit:
                    bad += 1
                    line = next((l for l in plan.splitlines() if IN_PLAN.search(l)), plan[:200])
                    print(f"cell {cell:>2}  FAIL  {head}\n          {line.strip()[:190]}")
                else:
                    print(f"cell {cell:>2}  ok    {head}")
            except Exception as exc:
                bad += 1
                line = next((l for l in str(exc).splitlines() if l.strip()), str(exc))
                print(f"cell {cell:>2}  FAIL  {head}\n          {line[:190]}")

    print(f"\n{len(found)} statements, {bad} that will not run")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())

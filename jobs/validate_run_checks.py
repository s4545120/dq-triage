#!/usr/bin/env python3
"""Prove jobs/run_checks.py measures what the 34-query harness measures.

    DATABRICKS_CONFIG_PROFILE=<p> python3 jobs/validate_run_checks.py \
        --catalog workspace --schema dq_triage --warehouse <id>

READ-ONLY. Builds the run plan from the fixture's registry, executes the SELECTs the
runner would execute against a real catalog, computes verdicts through the runner's own
`verdict()`, and diffs status / rows_scanned / violation_count against the fixture's
final check_run -- the numbers the Python evaluators produced and that sql/out/checkrun.sql
already confirmed the longhand SQL reproduces.

The claim under test is the batching: that folding N row-level rules into one aggregate
with the scope moved into count_if gives the same counts as N queries with a WHERE. That
rests on three-valued logic, so it is proven rather than argued.

A FAIL here means the batching is not equivalent and nothing should be built on it.
XREF_NAME_AGREEMENT is expected to fail on violation_count: its stored `<>` is not
null-safe and reports 0 where the evaluator reports 2. That is the pre-existing defect
CLAUDE.md records, not a fault in the runner.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from run_checks import (Rule, batch_row_level, normalise, plan, shape,  # noqa: E402
                        verdict, _alias)

FIX = pathlib.Path(__file__).parent.parent / "fixtures" / "out"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default="workspace")
    ap.add_argument("--schema", default="dq_triage")
    ap.add_argument("--src-prefix", default="dq_mock_")
    ap.add_argument("--warehouse", default="ebf2cf6b81ca710b")
    a = ap.parse_args()

    from databricks import sql as dbsql
    from databricks.sdk.core import Config

    reg = pd.read_parquet(FIX / "config.rule_registry.parquet")
    cur = reg.sort_values("rule_version").groupby("rule_id", as_index=False).tail(1)
    cur = cur[cur["status"].isin(["active", "shadow"])]
    fields = set(Rule.__annotations__)
    rules = [Rule(**{k: v for k, v in row.items() if k in fields})
             for row in cur.to_dict("records")]

    rules = normalise(rules, f"{a.catalog}.{a.schema}.dq_fn_")

    q = f"{a.catalog}.{a.schema}."
    resolve = {"prod.customer.ctct_c": f"{q}{a.src_prefix}ctct_c",
               "prod.customer.subs_c": f"{q}{a.src_prefix}subs_c"}
    p = plan(rules, resolve)

    print(f"{len(rules)} rules -> {len(p['batched'])} batched scan(s) "
          f"+ {len(p['singles'])} single quer(ies) "
          f"+ {len(p['unresolved'])} unresolved")
    for table, rs in p["batched"].items():
        print(f"    batched  {len(rs):2} rules  {table}")
    for r, _ in p["singles"]:
        print(f"    {shape(r):11} {r.rule_id}")

    cfg = Config()
    measured: dict[str, tuple[int, int]] = {}
    with dbsql.connect(server_hostname=cfg.host.replace("https://", ""),
                       http_path=f"/sql/1.0/warehouses/{a.warehouse}",
                       credentials_provider=lambda: cfg.authenticate) as conn:
        def one(sql: str) -> dict:
            with conn.cursor() as c:
                c.execute(sql)
                row = c.fetchall()[0]
                return dict(zip([d[0] for d in c.description], row))

        for table, rs in p["batched"].items():
            row = one(batch_row_level(table, rs))
            for r in rs:
                measured[r.rule_id] = (int(row[_alias("s", r.rule_id).lower()]
                                           if _alias("s", r.rule_id).lower() in row
                                           else row[_alias("s", r.rule_id)]),
                                       int(row[_alias("v", r.rule_id).lower()]
                                           if _alias("v", r.rule_id).lower() in row
                                           else row[_alias("v", r.rule_id)]))
        for r, sql in p["singles"]:
            row = one(sql)
            measured[r.rule_id] = (int(row["rows_scanned"]), int(row["violation_count"]))

    runs = pd.read_parquet(FIX / "results.check_run.parquet")
    exp = runs[runs.run_ts == runs.run_ts.max()].set_index("rule_id")

    out, fails = [], 0
    for r in rules:
        if r.rule_id not in measured:
            out.append((r.rule_id, "-", "-", "-", "-", "-", "-", "UNRESOLVED")); fails += 1
            continue
        scanned, viol = measured[r.rule_id]
        status, _, _ = verdict(r, scanned, viol)
        e = exp.loc[r.rule_id]
        ok = (status == e.status and scanned == int(e.rows_scanned)
              and viol == int(e.violation_count))
        if not ok:
            fails += 1
        out.append((r.rule_id, shape(r), status, e.status, scanned,
                    int(e.rows_scanned), f"{viol} vs {int(e.violation_count)}",
                    "PASS" if ok else "FAIL"))

    print(f"\n{'rule_id':26} {'shape':11} {'status':8} {'exp':8} {'scan':>6} "
          f"{'exp':>6}  {'violations':18} verdict")
    for row in sorted(out, key=lambda x: (x[-1] != "FAIL", x[0])):
        print(f"{row[0]:26} {row[1]:11} {row[2]:8} {row[3]:8} {str(row[4]):>6} "
              f"{str(row[5]):>6}  {row[6]:18} {row[7]}")
    print(f"\n{len(out) - fails} PASS, {fails} FAIL of {len(out)}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())

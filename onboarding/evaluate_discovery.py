#!/usr/bin/env python3
"""How well would discovery bind these tables? Read-only.

    cd onboarding
    ../.venv/bin/python evaluate_discovery.py --schema dq_triage
    ../.venv/bin/python evaluate_discovery.py --schema dq_triage --tables a.b.c,d.e.f

For every column of each selected table (or the ones named), asks `discovery.decide`
-- the function the discovery job runs -- what it would propose, ignoring existing
bindings and earlier proposals, and compares the answer with the column's current
binding. Writes nothing.

The "right answer" is the bindings people approved, which are themselves one person's
judgement. A proposal for a column nobody bound is counted as spurious, though it may be
a binding nobody made yet: read those rows before calling them wrong.

Names added to discovery.NAME_HINTS from the tables measured here will score well on
those same tables; that measures coverage of this estate's conventions, not how
discovery does on a table it has never seen.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discovery
import wh
from wh import connect, lit, run, t

OUTCOMES = ["correct", "wrong element", "undecided", "missed", "spurious"]


def evaluate(conn, table: str, elements: list[dict], truth: dict) -> list[tuple]:
    known = {e["cde_id"] for e in elements}
    names = {e["cde_id"]: e["cde_name"] for e in elements}
    signed = [e for e in elements if e["expected_signature"]]
    cat, sch, name = table.split(".")
    typed = {r["column_name"]: r["data_type"] for r in run(conn, f"""
        SELECT column_name, data_type FROM {cat}.information_schema.columns
        WHERE table_schema = '{sch}' AND table_name = '{name}' ORDER BY ordinal_position""")}
    tags = {r["column_name"]: r["tag_value"] for r in run(conn, f"""
        SELECT column_name, tag_value FROM {cat}.information_schema.column_tags
        WHERE schema_name = '{sch}' AND table_name = '{name}' AND tag_name = 'cde'""")}
    texts = [c for c in typed if typed[c] == "STRING" and c not in tags]
    agg = {}
    if texts and signed:
        parts = []
        for c in texts:
            parts.append(f"count_if(trim(`{c}`) <> '') AS `n__{c}`")
            for k, e in enumerate(signed):
                parts.append(f"count_if(trim(`{c}`) <> '' AND `{c}` RLIKE "
                             f"{lit(e['expected_signature'])}) AS `m__{c}__{k}`")
        agg = run(conn, f"SELECT {', '.join(parts)} FROM {table}")[0]

    rows = []
    for c in typed:
        pct = n = None
        if c in texts and agg:
            n = agg[f"n__{c}"] or 0
            pct = {e["cde_id"]: (100.0 * (agg[f"m__{c}__{k}"] or 0) / n if n else 0.0)
                   for k, e in enumerate(signed)}
        d = discovery.decide(c, typed[c], known=known, names=names, tag=tags.get(c),
                             nonblank=n, match_pct=pct)
        want, got = truth.get((table, c)), d["cde_id"]
        if got and want:
            outcome = "correct" if got == want else "wrong element"
        elif got:
            outcome = "spurious"
        elif want:
            outcome = "undecided" if "patterns" in d["why"] or "several" in d["why"] else "missed"
        else:
            continue                                   # unbound and left alone: right
        rows.append((c, outcome, want, got, d.get("method", ""), d.get("confidence", ""),
                     d.get("evidence") or d.get("why")))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--schema", default=wh.TEST_SCHEMA)
    ap.add_argument("--tables", help="comma-separated; default every selected table")
    a = ap.parse_args()
    wh.use_schema(a.schema)
    with connect() as conn:
        elements = run(conn, f"""SELECT cde_id, cde_name, expected_signature
            FROM {t('config', 'v_cde_registry_current')} WHERE status = 'registered'""")
        truth = {(r["target_table"], r["target_column"]): r["cde_id"] for r in run(conn, f"""
            SELECT target_table, target_column, cde_id FROM {t('config', 'v_binding_current')}""")}
        tables = ([x.strip() for x in a.tables.split(",")] if a.tables else
                  [r["target_table"] for r in run(conn, f"""
                      SELECT target_table FROM {t('config', 'v_monitored_table_current')}
                      WHERE status = 'selected' ORDER BY target_table""")])
        total = Counter()
        for table in tables:
            rows = evaluate(conn, table, elements, truth)
            bound = sum(1 for k in truth if k[0] == table)
            count = Counter(r[1] for r in rows)
            total.update(count)
            total["bound"] += bound
            print(f"\n{table}: {bound} bound  " +
                  "  ".join(f"{o} {count.get(o, 0)}" for o in OUTCOMES))
            for c, outcome, want, got, method, conf, why in rows:
                if outcome != "correct":
                    print(f"    {outcome:<13} {c:<20} bound {want or '-':<22} "
                          f"proposed {got or '-':<22} {why}")
        print(f"\nTOTAL: {total['bound']} bound  " +
              "  ".join(f"{o} {total.get(o, 0)}" for o in OUTCOMES))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

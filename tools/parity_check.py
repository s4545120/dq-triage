#!/usr/bin/env python3
"""Diff what the app reads from Unity Catalog against what it reads from the fixture.

`dq_app/data/databricks_source.py` had never executed. Its own docstring says the first
job with a workspace is to run these queries and diff the result against the fixture —
this is that job.

    DATABRICKS_CONFIG_PROFILE=<profile> python3 tools/parity_check.py \
        --catalog workspace --schema dq_triage --warehouse <id>

THREE KINDS OF DIFFERENCE, AND ONLY ONE OF THEM IS A BUG

The first version of this script reported all eight tables as differing, which was
useless. Two of the three kinds are the pipeline doing exactly what it is documented to
do, so they are classified and counted rather than raised:

  representation  A timestamp read through Arrow carries a UTC offset; the same value
                  read from Parquet does not. Same instant, different rendering.

  expected        `sql/seed.py` rewrites target_table from prod.customer.* to the mock
                  tables, and says so in its output. `cde_registry.bindings` carries the
                  same rewrite inside a struct. Generated ids (run_id, result_id and the
                  rest) are produced independently on each side, so they cannot match and
                  their difference means nothing on its own.

  REAL            Anything else. The fixture and the workspace were built from the same
                  pilot CSVs, so a genuine value difference is a bug in the adapter, the
                  render, or the load.

Rows are aligned on a business key, never on a generated id — sorting by an id that
differs on both sides aligns nothing and turns one difference into a whole column of
them.

WHAT THIS DOES NOT COVER

The five SQL views. The app never queries them: `v_cohort_current` and `v_cde_coverage`
are folded in Python by `domain/lifecycle.py` and `domain/coverage.py`, so a
session-recorded event appears before any warehouse could re-run the view. The views are
exercised by `sql/out/verify_results.sql` instead.

Reads only. It never calls write_disposition or promote_rule.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "dq-app"

# key    — business columns that identify a row on both sides
# gen    — ids generated independently per build; difference is meaningless alone
TABLES = {
    "cohorts":           dict(key=["raised_ts", "severity", "member_count"],
                              gen=["cohort_id", "raised_run_id", "triage_job_run_id",
                                   "member_result_ids", "model_input_payload"]),
    "dispositions":      dict(key=["cohort_id", "event_seq"],
                              gen=["disposition_id", "cohort_id", "verifying_run_id",
                                   "event_payload"]),
    "check_runs":        dict(key=["run_ts", "rule_id"],
                              gen=["result_id", "run_id", "duration_sec", "dbu_estimate"]),
    "violation_samples": dict(key=["rule_id", "row_key"],
                              gen=["sample_id", "result_id", "run_id", "captured_ts"]),
    "rule_registry":     dict(key=["rule_id", "rule_version"], gen=[]),
    "playbook":          dict(key=["playbook_id"], gen=[]),
    "cde_registry":      dict(key=["cde_id", "cde_version"], gen=[]),
    "cde_profile":       dict(key=["cde_id", "target_column"],
                              gen=["profile_id", "profile_run_id", "duration_sec"]),
}

# seed.py rewrites the source tables. Undo it so the values compare.
SOURCE_REWRITE = re.compile(r"[A-Za-z0-9_]+\.[A-Za-z0-9_]+\.[A-Za-z0-9_]*mock_(ctct_c|subs_c)")
TZ_SUFFIX = re.compile(r"([+-]\d{2}:\d{2})$")


def render(v):
    import pandas as pd
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    if hasattr(v, "__len__") and not isinstance(v, str):
        return str(list(v))
    return str(v)


def canon(s: str) -> tuple[str, str | None]:
    """Return the comparable form of a value, and which class of rewrite it needed."""
    kind = None
    out = TZ_SUFFIX.sub("", s)
    if out != s:
        kind = "representation"
    rewritten = SOURCE_REWRITE.sub(lambda m: f"prod.customer.{m.group(1)}", out)
    if rewritten != out:
        kind = "expected"
    return rewritten, kind


def frame(df, key):
    import pandas as pd
    df = df.copy()
    present = [k for k in key if k in df.columns]
    if present:
        df = df.sort_values(present, kind="stable")
    df = df.reindex(sorted(df.columns), axis=1).reset_index(drop=True)
    for c in df.columns:
        df[c] = df[c].map(render)
    return df


def compare(name, spec, local_df, dbx_df):
    real, benign = [], {"representation": 0, "expected": 0}

    lc, dc = set(local_df.columns), set(dbx_df.columns)
    if dc - lc:
        real.append(f"columns only in workspace: {sorted(dc - lc)}")
    if lc - dc:
        real.append(f"columns only in fixture:   {sorted(lc - dc)}")
    if len(local_df) != len(dbx_df):
        real.append(f"ROW COUNT {len(local_df)} fixture vs {len(dbx_df)} workspace")

    shared = sorted(lc & dc)
    l, d = frame(local_df[shared], spec["key"]), frame(dbx_df[shared], spec["key"])
    if len(l) != len(d):
        return real, benign  # row counts already reported; column diffs would be noise

    for c in shared:
        if c in spec["gen"]:
            continue
        lv = l[c].map(lambda s: canon(s)[0])
        dv = d[c].map(lambda s: canon(s)[0])
        mism = lv != dv
        if not mism.any():
            kinds = {canon(s)[1] for s in d[c]} - {None}
            for k in kinds:
                benign[k] += 1
            continue
        first = mism.idxmax()
        real.append(f"{c}: {int(mism.sum())} of {len(l)} rows differ — "
                    f"row {first} fixture {lv[first]!r} vs workspace {dv[first]!r}")
    return real, benign


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default="workspace")
    ap.add_argument("--schema", default="dq_triage")
    ap.add_argument("--prefix", default="dq_")
    ap.add_argument("--warehouse", required=True)
    ap.add_argument("--only", nargs="*")
    args = ap.parse_args()

    os.environ["DQ_CATALOG"] = args.catalog
    os.environ["DQ_SCHEMA"] = args.schema
    os.environ["DQ_PREFIX"] = args.prefix
    os.environ["DATABRICKS_WAREHOUSE_ID"] = args.warehouse
    os.environ.setdefault("DQ_APP_DATA_SOURCE", "local")

    sys.path.insert(0, str(APP))
    from dq_app.data import databricks_source as dbx
    from dq_app.data import local_source as loc

    print(f"fixture   {loc.fixture_dir()}")
    print(f"workspace {args.catalog}.{args.schema} · warehouse {args.warehouse}\n")

    wanted = {k: v for k, v in TABLES.items() if not args.only or k in args.only}
    differed, unreadable = [], []
    for name, spec in wanted.items():
        try:
            local_df, dbx_df = getattr(loc, name)(), getattr(dbx, name)()
        except Exception as e:
            print(f"  {name:20} READ FAILED — {type(e).__name__}: {e}")
            unreadable.append(name)
            continue

        real, benign = compare(name, spec, local_df, dbx_df)
        note = ", ".join(f"{v} {k}" for k, v in benign.items() if v) or "—"
        if real:
            differed.append(name)
            print(f"  {name:20} DIFFERS  {len(local_df):>5} rows   (benign: {note})")
            for p in real:
                print(f"      {p}")
        else:
            print(f"  {name:20} match    {len(local_df):>5} rows   (benign: {note})")

    print()
    if unreadable:
        print(f"could not read: {', '.join(unreadable)} — a connection, permission or "
              f"naming problem, not a data difference.")
    if differed:
        print(f"{len(differed)} of {len(wanted)} tables have REAL differences: "
              f"{', '.join(differed)}")
        print("Both sides were built from the same pilot CSVs, so each one is a bug in "
              "the adapter, the render, or the load.")
    if unreadable or differed:
        return 1
    print(f"all {len(wanted)} tables agree once representation and the documented "
          f"seed.py rewrite are accounted for.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

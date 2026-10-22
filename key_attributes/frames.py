"""The key-attribute migration applied to a local fixture directory, in pandas.

    python key_attributes/frames.py --base fixtures/out --out key_attributes/out
    DQ_FIXTURE_DIR=../key_attributes/out ../.venv/bin/streamlit run app.py

The labelled copy of sql/migrate_key_attributes.py, for two readers: the app tests,
which render every page against the state the migration leaves, and anyone who wants
to see that state locally without a workspace. Same three retirements, same register,
same rules, same five tables. Every other file is copied unchanged -- check runs,
problems and decisions stay as history, which is the point.

Not a fixture of its own: it is the base fixture plus the migration, and nothing here
is gated by fixtures/verify.py. key_attributes/out/ is generated and gitignored.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import register as ka  # noqa: E402
import universe  # noqa: E402

WHEN = pd.Timestamp("2026-10-12 09:00:00")
WHO = "key-attribute-migration@example.com"

ELEMENT_NOTE = ("Retired 2026-10-12 with the rest of the mock register: the register is "
                "now the key attributes from DQ_ATTR_PRIORI.xlsx.")
RULE_NOTE = ("Retired 2026-10-12: its element was mock data, retired with the rest of the "
             "mock register.")
TABLE_NOTE = "Decommissioned 2026-10-12: it holds no key attribute."


def _latest(df: pd.DataFrame, key: str, version: str) -> pd.DataFrame:
    return df.sort_values(version).groupby(key).tail(1)


def _append(df: pd.DataFrame, rows: list[dict] | pd.DataFrame) -> pd.DataFrame:
    new = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    if new.empty:
        return df
    new = new.reindex(columns=df.columns)
    out = pd.concat([df.astype(object), new.astype(object)], ignore_index=True)
    for c in df.columns:                 # keep the base frame's dtypes where they hold
        try:
            out[c] = out[c].astype(df[c].dtype)
        except (TypeError, ValueError):
            pass
    return out


def retire(df: pd.DataFrame, key: str, version: str, keep, stamp: dict) -> pd.DataFrame:
    latest = _latest(df, key, version)
    gone = latest[(latest["status"] != "retired") & ~latest.apply(keep, axis=1)].copy()
    gone[version] = gone[version].astype(int) + 1
    gone["status"] = "retired"
    for k, v in stamp.items():
        gone[k] = v
    return _append(df, gone)


def cde_rows() -> list[dict]:
    return [dict(
        cde_id=a.cde_id, cde_version=1, cde_name=a.name, business_term=None,
        data_class=a.data_class, definition=a.definition, expected_signature=None,
        criticality=ka.CRITICALITY, pii=a.pii, regulatory_basis=None,
        tolerance_pct=ka.TOLERANCE[a.cde_id],
        bindings=[dict(target_table=a.table, target_column=a.column,
                       populated_when=a.populated_when, expected_scope_filter=None,
                       binding_status="bound", discovered_by="manual", confidence=1.0)],
        business_domain=a.domain, owner_group=ka.OWNER_GROUP, status="registered",
        effective_from=WHEN, registered_by=WHO, registered_at=WHEN,
        note=f"Registered 2026-10-12 from {ka.SHEET}.") for a in ka.KEY_ATTRIBUTES]


def rule_rows() -> list[dict]:
    return [dict(
        rule_id=r.rule_id, rule_version=1, rule_name=r.rule_name, target_table=r.table,
        target_column=r.column, cde_id=r.cde_id, rule_type=r.rule_type, rule_expr=r.rule_expr,
        join_sql=None, scope_filter=r.scope_filter,
        fail_threshold_pct=float(ka.TOLERANCE[r.cde_id]),  # thresholds live on rules
        severity=r.severity, business_domain=ka.TABLE_DOMAIN[r.table],
        owner_group=ka.OWNER_GROUP, source_layer="L2", status="shadow", effective_from=WHEN,
        created_by=WHO, created_at=WHEN, promoted_by=None, promoted_at=pd.NaT, note=r.note,
        template_id=None, template_version=None) for r in universe.all_rules()]


def table_rows() -> list[dict]:
    return [dict(
        target_table=t, table_version=1, table_code=ka.TABLE_CODE[t], row_key=ka.ROW_KEY[t],
        owner_group=ka.OWNER_GROUP, business_domain=ka.TABLE_DOMAIN[t],
        schedule_group="daily_0300", scan_mode="full", status="selected", effective_from=WHEN,
        selected_by=WHO, note="Selected 2026-10-12 as a key-attribute source table. "
        + ka.LATEST_RECORD_GAP) for t in ka.TABLES]


def apply(base: Path, out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    for f in base.glob("*.parquet"):
        shutil.copy2(f, out / f.name)

    cde = pd.read_parquet(base / "config.cde_registry.parquet")
    cde = retire(cde, "cde_id", "cde_version", lambda r: str(r["cde_id"]).startswith("KA_"),
                 dict(effective_from=WHEN, registered_at=WHEN, registered_by=WHO,
                      note=ELEMENT_NOTE))
    cde = _append(cde, cde_rows())
    cde.to_parquet(out / "config.cde_registry.parquet", index=False)

    reg = pd.read_parquet(base / "config.rule_registry.parquet")
    reg = retire(reg, "rule_id", "rule_version", lambda r: str(r["cde_id"]).startswith("KA_"),
                 dict(effective_from=WHEN, created_at=WHEN, created_by=WHO, note=RULE_NOTE))
    reg = _append(reg, rule_rows())
    reg.to_parquet(out / "config.rule_registry.parquet", index=False)

    mon_path = base / "config.monitored_table.parquet"
    if mon_path.exists():
        mon = pd.read_parquet(mon_path)
        mon = retire(mon, "target_table", "table_version",
                     lambda r: r["target_table"] in ka.TABLES,
                     dict(effective_from=WHEN, selected_by=WHO, note=TABLE_NOTE))
        mon = _append(mon, table_rows())
    else:
        mon = pd.DataFrame(table_rows())
    mon.to_parquet(out / "config.monitored_table.parquet", index=False)

    # The shipped coverage view describes the old register; the app recomputes coverage
    # from the registers, so the stale copy is removed rather than left to contradict it.
    (out / "results.v_cde_coverage.parquet").unlink(missing_ok=True)
    return out


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=str(root / "fixtures" / "out"))
    ap.add_argument("--out", default=str(root / "key_attributes" / "out"))
    a = ap.parse_args()
    out = apply(Path(a.base), Path(a.out))
    print(f"wrote {out}: {len(ka.KEY_ATTRIBUTES)} key attributes, "
          f"{len(universe.all_rules())} shadow rules, the mock register retired")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

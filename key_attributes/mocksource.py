"""Mock source tables for the key attributes, in Unity Catalog.

    python key_attributes/mocksource.py              # writes sql/out/mock_source.sql
    python key_attributes/mocksource.py --apply      # also creates the tables

MOCK DATA, AND SAYS SO. The real source (prod.udp_brnz_nrt_tech_view.*) is not
reachable from this workspace, so this builds tables with the same schema and table
names in `workspace` -- workspace.udp_brnz_nrt_tech_view.table_contact_hist and the
rest -- and the register is pointed at them (sql/migrate_key_attributes_source.py). Every
table comment starts MOCK. Nothing here is real customer data: names, emails and
numbers are generated from a fixed seed.

WHAT IS IN THEM. Only the columns the rules read, plus the record key and the history
columns the analysis ranked on (ECF_NSRT_TS, SCN, offset, OP_TYPE). Each record has
one to three versions, and about 2% end on a deleted version, the shape the latest-
record gap (register.LATEST_RECORD_GAP) is about. Clean values are generated; then the
values in key_attributes/probe.py that are expected to fail are planted into the
latest versions, a few to a few dozen rows each, so every rule has something to find.
The probe proved what each of those values does, so a planted count is a count the
rule should report.

Epoch-millisecond dates are BIGINT, as the analysis queries treat them. Everything
else is STRING, which every rule reads through cast(... AS STRING) anyway.

`workspace.sdpt_sfmig.sf_mig_attribs_analytics` is the migration-scope table, with a
pipe-delimited contact_id_migrate, for when a slice can read it. Nothing reads it yet.
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "onboarding"))

import probe  # noqa: E402
import register as ka  # noqa: E402
from rules import PHONE_PLACEHOLDERS  # noqa: E402

CATALOG = "workspace"
SCHEMA = "udp_brnz_nrt_tech_view"
SCOPE_TABLE = f"{CATALOG}.sdpt_sfmig.sf_mig_attribs_analytics"
SEED = 20261012
N = {ka.CONTACT: 2000, ka.ADDRESS: 1500, ka.BUS_ORG: 600, ka.CONTACT_ROLE: 2000,
     ka.CUSTOMER: 1200}
EPOCH = {"BIRTH_DATE", "EFF_DT", "END_DT"}
HISTORY = ["ECF_NSRT_TS", "SCN", "offset", "OP_TYPE"]

FIRST = ["Olivia", "Jack", "Isla", "Noah", "Charlotte", "William", "Amelia", "Oliver",
         "Mia", "Leo", "Ava", "Henry", "Grace", "Lucas", "Chloe", "Thomas", "Zoe", "Ethan",
         "Ruby", "James", "Mary-Jane", "Siobhán", "Nguyen", "Priya", "Mohammed"]
LAST = ["Smith", "Nguyen", "Williams", "Brown", "Jones", "Taylor", "Wilson", "O'Brien",
        "Martin", "Anderson", "Thompson", "Lee", "White", "Harris", "Kelly", "Chen",
        "Singh", "Walker", "Young", "Ryan", "Murphy", "Patel", "Clarke", "Hall"]
MIDDLE = ["Anne", "James", "Rose", "John", "Marie", "Lee", "Grace", "Paul"]
DOMAINS = ["gmail.com", "outlook.com", "bigpond.com", "optusnet.com.au", "yahoo.com.au",
           "icloud.com", "example.org"]
STREETS = ["George St", "King William Rd", "Collins St", "Queen St", "Murray St",
           "Bourke St", "Pitt St", "Adelaide Tce"]
STATES = ["NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT", "NT"]
ORGS = ["Harbour Bakery", "Ridge Logistics", "Southern Dental", "Bluegum Cafe",
        "Coastline Plumbing", "Summit Accounting", "Riverbend Motors", "Kestrel Studio"]


def _ms(d: datetime) -> int:
    return int(d.replace(tzinfo=timezone.utc).timestamp() * 1000)


def _mobile(rng: random.Random) -> str:
    while True:
        v = "04" + "".join(rng.choice("0123456789") for _ in range(8))
        if v not in PHONE_PLACEHOLDERS and "0000000" not in v:
            return v


def _landline(rng: random.Random) -> str:
    return "0" + rng.choice("2378") + "".join(rng.choice("123456789") for _ in range(8))


def _clean(table: str, i: int, rng: random.Random) -> dict:
    """One clean latest version of record i."""
    if table == ka.CONTACT:
        f, l = rng.choice(FIRST), rng.choice(LAST)
        dob = datetime(1940, 1, 1) + timedelta(days=rng.randrange(0, 365 * 64))
        return {"CONTACT_ID": str(5_000_000 + i), "FIRST_NAME": f, "LAST_NAME": l,
                "MIDDLE_NAME": rng.choice(MIDDLE) if rng.random() < .35 else None,
                "PHONE": _mobile(rng) if rng.random() < .8 else _landline(rng),
                "E_MAIL": f"{f.lower().replace('-', '')}.{l.lower().replace(chr(39), '')}"
                          f"{rng.randrange(1, 99)}@{rng.choice(DOMAINS)}",
                "BIRTH_DATE": _ms(dob.replace(hour=12)), "STATUS": "1"}
    if table == ka.ADDRESS:
        eff = datetime(2005, 1, 1) + timedelta(days=rng.randrange(0, 365 * 19))
        st = rng.choice(STATES)
        unit = rng.random() < .3
        return {"OBJID": str(7_000_000 + i), "EFF_DT": _ms(eff.replace(hour=12)),
                "END_DT": None if rng.random() < .85 else _ms((eff + timedelta(days=900)).replace(hour=12)),
                "X_ADDRESS_ID": f"GA{st}{rng.randrange(10**8, 10**9)}" if st != "ACT" else
                                f"GAACT{rng.randrange(10**8, 10**9)}",
                "X_SUB_ADDRESS_NUMBER": f"Unit {rng.randrange(1, 40)}" if unit else None,
                "STREET_NUMBER": str(rng.randrange(1, 400)),
                "ADDRESS_3": rng.choice(["Level 2", "Suite 14", "Building B"]) if rng.random() < .2 else None,
                "ADDRESS_4": None, "X_INTERNATIONAL_ADDRESS": "N", "STATE": st,
                "STREET_NAME": rng.choice(STREETS)}
    if table == ka.BUS_ORG:
        name = rng.choice(ORGS)
        return {"OBJID": str(8_000_000 + i), "ORG_ID": str(300_000 + i), "NAME": name,
                "PHONE": _landline(rng), "X_NUMBER_OF_EMPLOYEE": str(rng.randrange(1, 250)),
                "X_NUMBER_OF_OFFICE": str(rng.randrange(1, 12)),
                "WEB_SITE": (f"https://www.{name.lower().replace(' ', '')}.com.au"
                             if rng.random() < .6 else None),
                "ESTABLISH_DATE": str(_ms(datetime(1960 + rng.randrange(0, 64), rng.randrange(1, 13), 15, 12))),
                "X_ARBN": str(rng.randrange(10**8, 10**9)) if rng.random() < .03 else None}
    if table == ka.CONTACT_ROLE:
        return {"OBJID": str(9_000_000 + i), "CONTACT_ID": str(5_000_000 + i % N[ka.CONTACT]),
                "ROLE_NAME": "Default"}
    if table == ka.CUSTOMER:
        return {"OBJID": str(6_000_000 + i), "CUSTOMER_ID": str(1_000_000 + i)}
    raise KeyError(table)


def _columns(table: str) -> list[str]:
    return list(_clean(table, 0, random.Random(0))) + HISTORY


def _rows(table: str) -> list[dict]:
    rng = random.Random(f"{SEED}:{table}")
    base = datetime(2026, 9, 1, 3)
    rows = []
    latest: list[int] = []
    for i in range(N[table]):
        rec = _clean(table, i, rng)
        versions = rng.choice([1, 1, 2, 2, 3])
        for v in range(versions):
            row = dict(rec)
            last = v == versions - 1
            if not last and table == ka.CONTACT:
                row["PHONE"] = _mobile(rng)             # an older number, since replaced
            row["ECF_NSRT_TS"] = (base - timedelta(days=30 * (versions - v))).isoformat(" ")
            row["SCN"] = str(1_000_000 + i * 10 + v)
            row["offset"] = str(v)
            row["OP_TYPE"] = "D" if last and rng.random() < .02 else ("I" if v == 0 else "U")
            rows.append(row)
            if last:
                latest.append(len(rows) - 1)
    # Plant every failing probe value into the latest versions.
    for t, col, value, comp, expect in probe.CASES:
        if t != table or not expect:
            continue
        if col in EPOCH and value is not None and not value.lstrip("-").isdigit():
            continue                                    # a BIGINT column cannot hold it
        for idx in rng.sample(latest, rng.randint(3, 40)):
            rows[idx][col] = int(value) if col in EPOCH and value is not None else value
            for k, v in comp.items():
                rows[idx][k] = int(v) if k in EPOCH else v
    # The 1753 sentinel is the analysis's largest address finding: a sixth of rows.
    if table == ka.ADDRESS:
        for idx in rng.sample(latest, len(latest) // 6):
            rows[idx]["EFF_DT"] = _ms(datetime(1753, 1, 1, 12))
    return rows


def _lit(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, int):
        return str(v)
    return "'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'"


def statements(catalog: str = CATALOG) -> list[str]:
    out = [f"CREATE SCHEMA IF NOT EXISTS {catalog}.{SCHEMA} COMMENT "
           "'MOCK copies of prod.udp_brnz_nrt_tech_view tables for the key attributes. "
           "Generated by key_attributes/mocksource.py; not real data.'",
           f"CREATE SCHEMA IF NOT EXISTS {catalog}.sdpt_sfmig COMMENT "
           "'MOCK migration-scope table. Generated by key_attributes/mocksource.py.'"]
    for table in ka.TABLES:
        name = f"{catalog}.{SCHEMA}.{table.split('.')[-1]}"
        cols = _columns(table)
        decl = ", ".join(f"`{c}` {'BIGINT' if c in EPOCH else 'STRING'}" for c in cols)
        out.append(f"CREATE OR REPLACE TABLE {name} ({decl}) COMMENT "
                   f"'MOCK of {table}: generated rows with planted defects, seed {SEED}. "
                   "Not real data.'")
        rows = _rows(table)
        for k in range(0, len(rows), 400):
            vals = ",\n".join("(" + ", ".join(_lit(r.get(c)) for c in cols) + ")"
                              for r in rows[k:k + 400])
            out.append(f"INSERT INTO {name} ({', '.join(f'`{c}`' for c in cols)}) VALUES\n{vals}")
    # Migration scope: contact ids, sometimes two to a row, pipe-delimited; 80% in scope.
    rng = random.Random(f"{SEED}:scope")
    ids = [str(5_000_000 + i) for i in range(N[ka.CONTACT])]
    vals = []
    while ids:
        take = [ids.pop() for _ in range(min(len(ids), rng.choice([1, 1, 1, 2])))]
        vals.append(f"('{'|'.join(take)}', {1 if rng.random() < .8 else 0})")
    out.append(f"CREATE OR REPLACE TABLE {SCOPE_TABLE} (contact_id_migrate STRING, "
               "migration_scope_flag INT) COMMENT 'MOCK of "
               "sdpt_data_trnf.sdpt_sfmig.sf_mig_attribs_analytics. Not real data.'")
    for k in range(0, len(vals), 500):
        out.append(f"INSERT INTO {SCOPE_TABLE} VALUES " + ", ".join(vals[k:k + 500]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    stmts = statements()
    out = ROOT.parent / "sql" / "out" / "mock_source.sql"
    out.write_text("-- GENERATED by key_attributes/mocksource.py. MOCK data. Do not edit.\n\n"
                   + ";\n\n".join(stmts) + ";\n")
    print(f"wrote {out} ({len(stmts)} statements)")
    if a.apply:
        import wh
        with wh.connect() as conn:
            for s in stmts:
                wh.run(conn, s)
            for t in ka.TABLES:
                name = f"{CATALOG}.{SCHEMA}.{t.split('.')[-1]}"
                n = wh.run(conn, f"SELECT count(*) AS n FROM {name}")[0]["n"]
                print(f"  {name}: {n} rows")
            print(f"  {SCOPE_TABLE}: "
                  f"{wh.run(conn, f'SELECT count(*) AS n FROM {SCOPE_TABLE}')[0]['n']} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

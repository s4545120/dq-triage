#!/usr/bin/env python3
"""Generate the migration for a workspace seeded before 2026-09-28: DQ on CDEs.

    python3 sql/migrate_cde_scope.py --catalog workspace --schema dq_triage --prefix dq_

Writes sql/out/migrate_cde_scope.sql. Four parts, and the order matters.

PART 1 -- THE TOLERANCE. config.cde_registry gains tolerance_pct (ADD COLUMN, which
appendOnly permits) and every element already registered gets a new cde_version
declaring one. A tolerance is a declaration about the element, so a new version is
the right shape and each note is a real note -- unlike migrate_join_sql.py's rows,
which carried no change and had to say so.

PART 2 -- THE SECOND TEN ELEMENTS. Ten new cde_ids, at cde_version 1, with the
prod.customer.* rewrite applied inside their bindings as sql/seed.py applies it. They
exist because every rule must now name an element and 14 rules watched columns nobody
had registered. One person's starting point; the notes say so.

PART 3 -- EVERY RULE NAMES ITS ELEMENT. sql/ddl/ declares cde_id NOT NULL. This
workspace cannot ALTER the column to NOT NULL: historical versions hold NULL and
appendOnly blocks the UPDATE that would fill them. So the column stays nullable here,
every current rule gets a new rule_version carrying its cde_id, and the verification
query at the end asserts what the constraint would: no current non-retired rule without
one. A fresh deployment from sql/ddl/ gets the NOT NULL for free.

PART 4 -- THE VIEWS AND THE NEW TABLES. v_cde_coverage's join changed (a rule attaches
by naming its element, narrowed by column) and must be re-created; the threshold tables
and their view are new. Those are CREATE OR REPLACE VIEW / CREATE TABLE statements
already rendered into sql/out/ by render.py, so this file tells you which to run rather
than duplicating them.

NOT RUN. Read it before applying. There is no rollback -- reverting any of it is
another INSERT.
"""

from __future__ import annotations

import argparse
import pathlib

import pandas as pd

ROOT = pathlib.Path(__file__).parent.parent
FIX = ROOT / "fixtures" / "out"
OUT = pathlib.Path(__file__).parent / "out"

ORIGINAL_TEN = [
    "CDE_CUST_EMAIL", "CDE_CUST_MSISDN", "CDE_CUST_DOB", "CDE_CUST_NAME",
    "CDE_CUST_IDENT_DOC", "CDE_CUST_MOBILE", "CDE_CUST_LANDLINE", "CDE_SIM_SERIAL",
    "CDE_DEVICE_IMEI", "CDE_BILLING_ACCOUNT",
]

TOL_COMMENT = ("the stated organisational tolerance for violating rows on this element, "
               "as a percentage of rows in scope. A CEILING on fail_threshold_pct for any "
               "rule attached to a binding of this element -- a rule may be stricter, "
               "never looser. NULL means no tolerance has been declared.")

BINDING_FIELDS = ["target_table", "target_column", "populated_when",
                  "expected_scope_filter", "binding_status", "discovered_by", "confidence"]

CDE_COLUMNS = ["cde_id", "cde_version", "cde_name", "business_term", "data_class",
               "definition", "expected_signature", "criticality", "pii", "regulatory_basis",
               "tolerance_pct", "bindings", "business_domain", "owner_group", "status",
               "effective_from", "registered_by", "registered_at", "note"]

RULE_COLUMNS = ["rule_id", "rule_version", "rule_name", "target_table", "target_column",
                "cde_id", "rule_type", "rule_expr", "scope_filter", "join_sql",
                "fail_threshold_pct", "severity", "business_domain", "owner_group",
                "source_layer", "status", "effective_from", "created_by", "created_at",
                "promoted_by", "promoted_at", "note"]


def lit(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)) or v is pd.NaT:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, pd.Timestamp):
        return f"TIMESTAMP '{v.strftime('%Y-%m-%d %H:%M:%S')}'"
    return "'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'"


def binding_lit(b: dict, rewrite: dict) -> str:
    fields = []
    for name in BINDING_FIELDS:
        v = b.get(name)
        if name == "target_table" and v is not None:
            v = rewrite.get(v, v)
        if hasattr(v, "item"):
            v = v.item()
        fields.append(f"'{name}', {lit(v)}")
    return "named_struct(" + ", ".join(fields) + ")"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default="workspace")
    ap.add_argument("--schema", default="dq_triage")
    ap.add_argument("--prefix", default="dq_")
    ap.add_argument("--src-prefix", default="dq_mock_")
    a = ap.parse_args()

    q = f"{a.catalog}.{a.schema}."
    cde = f"{q}{a.prefix}config_cde_registry"
    cde_cur = f"{q}{a.prefix}config_v_cde_registry_current"
    reg = f"{q}{a.prefix}config_rule_registry"
    reg_cur = f"{q}{a.prefix}config_v_rule_registry_current"
    cov = f"{q}{a.prefix}results_v_cde_coverage"
    rewrite = {"prod.customer.ctct_c": f"{q}{a.src_prefix}ctct_c",
               "prod.customer.subs_c": f"{q}{a.src_prefix}subs_c"}

    cdes = pd.read_parquet(FIX / "config.cde_registry.parquet")
    cdes = cdes.sort_values("cde_version").groupby("cde_id", as_index=False).tail(1)
    originals = cdes[cdes.cde_id.isin(ORIGINAL_TEN)].sort_values("cde_id")
    new = cdes[~cdes.cde_id.isin(ORIGINAL_TEN)].sort_values("cde_id")
    rules = pd.read_parquet(FIX / "config.rule_registry.parquet")
    rules = rules.sort_values("rule_version").groupby("rule_id", as_index=False).tail(1)
    rules = rules.sort_values("rule_id")

    p = [
        "-- =====================================================================",
        "-- migrate_cde_scope.sql — GENERATED by sql/migrate_cde_scope.py. Do not edit.",
        f"-- target: {a.catalog}.{a.schema}, prefix {a.prefix}",
        "--",
        "-- DQ on CDEs. A tolerance on every element, ten more elements, every rule",
        "-- naming its element, and the threshold tables. Four parts, in order. See",
        "-- the generator's docstring for why each takes the shape it does.",
        "-- =====================================================================",
        "",
        "-- ---------------------------------------------------------------------",
        "-- Step 0 — where is this workspace? EXPECTED before: 0 rows, 10 elements,",
        "-- every current rule cde_id NULL but one. After: 1 row, 20, none NULL.",
        "-- ---------------------------------------------------------------------",
        "SELECT column_name FROM information_schema.columns",
        f"WHERE  table_schema = '{a.schema}' AND table_name = '{a.prefix}config_cde_registry'",
        "  AND  column_name = 'tolerance_pct';",
        f"SELECT COUNT(*) AS elements FROM {cde_cur};",
        f"SELECT COUNT(*) AS rules_without_element FROM {reg_cur} WHERE cde_id IS NULL;",
        "",
        "-- =====================================================================",
        "-- Part 1 — tolerance_pct on config.cde_registry, and a declaration per",
        f"-- element already registered ({len(originals)} new versions)",
        "-- =====================================================================",
        f"ALTER TABLE {cde}",
        f"  ADD COLUMN tolerance_pct DOUBLE COMMENT {lit(TOL_COMMENT)};",
        "",
        f"ALTER TABLE {cde}",
        "  ADD CONSTRAINT cde_registry_tolerance_range",
        "  CHECK (tolerance_pct IS NULL OR (tolerance_pct >= 0.0 AND tolerance_pct <= 100.0));",
        "",
        "-- EXPLICIT column list: ADD COLUMN appends tolerance_pct at the END of the table",
        "-- while sql/ddl/ declares it after regulatory_basis, so a positional INSERT would",
        "-- load garbage without erroring. bindings is written from the FIXTURE, with the",
        "-- seed's table-name rewrite applied, not copied off the row superseded: the",
        "-- fixture bound EML_STTS_CD to CDE_CUST_EMAIL after the workspace was seeded, and",
        "-- copying forward left the two status-code rules attached to nothing.",
    ]
    for _, r in originals.iterrows():
        tol = float(r.tolerance_pct)
        note = (f"v2: tolerance_pct declared at {tol}% -- the share of rows in scope that may "
                f"violate before the business calls this element broken, and the ceiling any "
                f"rule watching it may set as fail_threshold_pct. Set from the criticality "
                f"tier ({r.criticality}) in fixtures/cdes.py: one person's starting point "
                f"for a conversation with the business, not an agreed policy.")
        p += [
            "",
            f"-- {r.cde_id}  -> v2   tolerance {tol}%  ({r.criticality})",
            f"INSERT INTO {cde} ({', '.join(CDE_COLUMNS)})",
            "SELECT cde_id, cde_version + 1, cde_name, business_term, data_class, definition,",
            "       expected_signature, criticality, pii, regulatory_basis,",
            f"       {lit(tol)},",
            "       array(" + ", ".join(binding_lit(b, rewrite) for b in r.bindings) + "),",
            "       business_domain, owner_group, status,",
            "       current_timestamp(), current_user(), current_timestamp(),",
            f"       {lit(note)}",
            f"FROM   {cde}",
            f"WHERE  cde_id = {lit(r.cde_id)}",
            f"  AND  cde_version = (SELECT max(cde_version) FROM {cde} WHERE cde_id = {lit(r.cde_id)});",
        ]

    p += [
        "",
        "-- =====================================================================",
        f"-- Part 2 — the second ten elements ({len(new)} rows, cde_version 1)",
        "-- =====================================================================",
        "-- Registered so that every rule can name an element. Tiers, tolerances and",
        "-- regulatory bases are one person's starting point; each note says so.",
        f"INSERT INTO {cde} ({', '.join(CDE_COLUMNS)}) VALUES",
    ]
    vals = []
    for _, r in new.iterrows():
        row = []
        for c in CDE_COLUMNS:
            v = r[c]
            if c == "bindings":
                row.append("array(" + ", ".join(binding_lit(b, rewrite) for b in v) + ")")
            elif c in ("effective_from", "registered_at"):
                row.append("current_timestamp()")
            elif c == "registered_by":
                row.append("current_user()")
            else:
                if hasattr(v, "item"):
                    v = v.item()
                row.append(lit(v))
        vals.append("  (" + ", ".join(row) + ")")
    p.append(",\n".join(vals) + ";")

    p += [
        "",
        "-- =====================================================================",
        f"-- Part 3 — every rule names its element ({len(rules)} new rule versions)",
        "-- =====================================================================",
        "-- The column stays nullable in this workspace (see the generator docstring);",
        "-- each current rule gets a version carrying its cde_id, everything else",
        "-- carried forward from the version superseded, and the verification below",
        "-- asserts what the NOT NULL would. No behaviour change: the rule measures",
        "-- exactly what it measured; it now says which element that is.",
    ]
    for _, r in rules.iterrows():
        note = (f"cde_id = {r.cde_id}: this rule names its element. NO behaviour change -- "
                f"config.rule_registry.cde_id became NOT NULL on 2026-09-28 and the check "
                f"runner's worklist is now the CDE register. Do not look for a difference "
                f"in what this version measures.")
        p += [
            "",
            f"-- {r.rule_id}  -> {r.cde_id}   [{r.status}]",
            f"INSERT INTO {reg} ({', '.join(RULE_COLUMNS)})",
            "SELECT rule_id, rule_version + 1, rule_name, target_table, target_column,",
            f"       {lit(r.cde_id)},",
            "       rule_type, rule_expr, scope_filter, join_sql, fail_threshold_pct,",
            "       severity, business_domain, owner_group, source_layer, status,",
            "       current_timestamp(), current_user(), current_timestamp(),",
            "       promoted_by, promoted_at,",
            f"       {lit(note)}",
            f"FROM   {reg}",
            f"WHERE  rule_id = {lit(r.rule_id)}",
            f"  AND  rule_version = (SELECT max(rule_version) FROM {reg} WHERE rule_id = {lit(r.rule_id)});",
        ]

    p += [
        "",
        "-- =====================================================================",
        "-- Part 4 — views and the threshold tables: run the rendered files",
        "-- =====================================================================",
        "-- v_cde_coverage's attachment join changed, so re-create it, and the",
        "-- threshold tables and their view are new. Both are in sql/out/ already:",
        "--   sql/out/11_views_cde.sql          CREATE OR REPLACE VIEW — safe to re-run",
        "--   sql/out/09_results_threshold.sql  two tables + constraints — run ONCE",
        "--   sql/out/12_views_threshold.sql    CREATE OR REPLACE VIEW — reads both",
        "-- Then, where you can grant (not in a sandpit):",
        "--   GRANT MODIFY ON TABLE <threshold_review> TO `<app_sp>`;   -- the third write",
        "--   GRANT MODIFY ON TABLE <threshold_proposal> TO `<threshold_job_sp>`;",
        "",
        "-- =====================================================================",
        "-- Part 5 — verification, read-only",
        "-- =====================================================================",
        "",
        "-- 5a — EXPECTED: zero rows. What the NOT NULL in sql/ddl/ would have refused.",
        "SELECT rule_id, rule_version, status",
        f"FROM   {reg_cur} WHERE cde_id IS NULL ORDER BY rule_id;",
        "",
        "-- 5b — EXPECTED: zero rows. A rule with a column names an element that binds it.",
        "SELECT r.rule_id, r.cde_id, r.target_table, r.target_column",
        f"FROM   {reg_cur} r",
        f"LEFT JOIN (SELECT c.cde_id, b.target_table, b.target_column",
        f"           FROM {cde_cur} c LATERAL VIEW explode(c.bindings) x AS b",
        "           WHERE c.status = 'registered' AND b.binding_status = 'bound') e",
        "  ON  e.cde_id = r.cde_id AND e.target_table = r.target_table",
        "  AND e.target_column = r.target_column",
        "WHERE r.target_column IS NOT NULL AND e.cde_id IS NULL;",
        "",
        f"-- 5c — EXPECTED: {len(cdes)} elements, every tolerance_pct non-null.",
        "SELECT COUNT(*) AS elements, COUNT(tolerance_pct) AS with_tolerance",
        f"FROM   {cde_cur} WHERE status = 'registered';",
        "",
        "-- 5d — EXPECTED: every active rule attached to at least one binding. Zero rows.",
        "SELECT r.rule_id",
        f"FROM   {reg_cur} r",
        "WHERE  r.status = 'active'",
        f"  AND  NOT EXISTS (SELECT 1 FROM {cov} v WHERE array_contains(v.rule_ids, r.rule_id));",
        "",
        "-- 5e — the coverage picture after. EXPECTED to include no_rule now: two",
        "-- elements exist to carry a shadow rule and start with no active rule.",
        f"SELECT coverage_gap, COUNT(*) FROM {cov} GROUP BY coverage_gap ORDER BY 1;",
        "",
    ]
    (OUT / "migrate_cde_scope.sql").write_text("\n".join(p) + "\n")
    print(f"wrote sql/out/migrate_cde_scope.sql — 1 ALTER COLUMN, 1 constraint, "
          f"{len(originals)} tolerance versions, {len(new)} new elements, "
          f"{len(rules)} rule versions")
    print("\nNOT RUN.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

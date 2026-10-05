#!/usr/bin/env python3
"""Onboard a selected table end to end, in a disposable schema.

    cd onboarding
    ../.venv/bin/python onboard.py setup      # schema, clones, new tables, mock source, tags
    ../.venv/bin/python onboard.py discover   # JOB:    propose bindings
    #   -> PERSON: review.sql step 1, approve or reject the proposals
    ../.venv/bin/python onboard.py apply      # JOB:    approved proposals -> cde_registry
    ../.venv/bin/python onboard.py generate   # JOB:    templates x bound columns -> shadow rules
    ../.venv/bin/python onboard.py run        # JOB:    jobs/run_checks.py on the selected table
    #   -> PERSON: review.sql step 2, promote the table's rules
    ../.venv/bin/python onboard.py run        # breaches now count
    ../.venv/bin/python onboard.py status     # where every selected table has got to

The jobs here run from a laptop against the warehouse for speed; in a deployment they
are Lakeflow tasks. The check run is the exception and is submitted as a real serverless
job, because jobs/run_checks.py is the code under test.

HUMAN REVIEW IS TWO SQL STATEMENTS (review.sql), and both are appends signed with
current_user(): a binding review row, and a rule_version promoting a rule. The jobs
never approve anything, and a job is the only thing that writes cde_registry -- one
version per element per apply, so two reviewers cannot collide on a cde_version.

THE TABLES ARE THE REPO'S DDL since 2026-10-06: sql/ddl/15_config_onboarding.sql and
16_views_onboarding.sql, plus the template columns in 01. setup renders and runs them;
nothing here declares a table's shape any more, and fixtures/verify.py diffs the column
lists this file writes against them.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

# A serverless Python task execs this file, so `__file__` is undefined there; the path
# is in argv[0]. The sibling modules are imported from beside it either way.
try:
    _HERE = Path(__file__).resolve().parent
except NameError:
    _HERE = Path(sys.argv[0]).resolve().parent
sys.path.insert(0, str(_HERE))
import mock_lead
import templates as tpl
from wh import (CATALOG, PREFIX, SCHEMA, SOURCE_SCHEMA, connect, in_databricks, lit, run, src,
                t)

HERE = _HERE
LEAD = src("crm_lead")
SIGNATURE_THRESHOLD_PCT = 95.0   # Ataccama's "detection threshold": share of non-blank values
SIGNATURE_MIN_VALUES = 20        # too few values and a match rate means nothing
NAME_MATCH_CONFIDENCE = 0.6      # a column name is a weaker claim than a tag or the values

# Column names that say which element a column holds, compared with case and every
# non-alphanumeric character removed. The fallback for a catalog nobody can tag --
# `samples` is read-only -- and for columns whose values have no fixed shape. A name is
# proposed only when it matches exactly one element; the owner still decides.
NAME_HINTS = {
    "CDE_CUST_EMAIL": ["email", "emailaddress", "emailaddr", "emlid", "eml"],
    "CDE_CUST_NAME": ["firstname", "givenname", "lastname", "familyname", "surname",
                      "frstnm", "lastnm", "fullname", "legalname"],
    "CDE_CUST_DOB": ["dob", "birthdate", "dateofbirth", "brthts", "birthts"],
    "CDE_CUST_MOBILE": ["mobile", "mobileno", "mobilenumber", "mobilephone", "moblno"],
    "CDE_CUST_LANDLINE": ["phone", "phoneno", "phonenumber", "homephone", "landline", "phnno"],
    "CDE_CUST_KEY": ["customerid", "custid", "contactid", "customerkey", "ctctid", "ctctkey"],
}

# What this job writes to the onboarding tables, in sql/ddl/15_config_onboarding.sql's
# order. Every INSERT names its columns: fixtures/verify.py diffs these against the DDL,
# and a positional INSERT would load a reordered table without an error.
MONITORED_COLS = ("target_table, table_version, table_code, row_key, owner_group, "
                  "business_domain, schedule_group, scan_mode, status, effective_from, "
                  "selected_by, note")
TEMPLATE_COLS = ("template_id, template_version, data_class, check_code, title, input_type, "
                 "rule_type, rule_expr, scope_filter, severity, source_rule, created_by, "
                 "created_at")
PROPOSAL_COLS = ("proposal_id, proposed_at, target_table, target_column, cde_id, method, "
                 "confidence, evidence, proposed_by")

# The one table this test onboards. Re-running setup appends nothing if it exists.
MONITORED = dict(
    target_table=LEAD, table_code="LEAD", row_key=["LEAD_ID"], owner_group="dq-stewards-sales",
    business_domain="Sales", schedule_group="daily_0300", scan_mode="full",
)


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------

def setup(conn) -> None:
    S = f"{CATALOG}.{SCHEMA}"
    stmts = [
        f"CREATE SCHEMA IF NOT EXISTS {S} COMMENT 'Onboarding test. Disposable: DROP SCHEMA "
        f"{S} CASCADE resets it. Cloned from {SOURCE_SCHEMA} on creation.'",
        # The two registers are cloned so the test starts from the real elements and
        # rules, and nothing it appends lands in dq_triage.
        f"CREATE TABLE IF NOT EXISTS {t('config', 'cde_registry')} DEEP CLONE "
        f"{t('config', 'cde_registry', SOURCE_SCHEMA)}",
        f"CREATE TABLE IF NOT EXISTS {t('config', 'rule_registry')} DEEP CLONE "
        f"{t('config', 'rule_registry', SOURCE_SCHEMA)}",
        # The rest of what the app reads, so every page works against this schema and
        # not only Onboarding. Copies: nothing the app writes here reaches dq_triage.
        *[f"CREATE TABLE IF NOT EXISTS {t(g, n)} DEEP CLONE {t(g, n, SOURCE_SCHEMA)}"
          for g, n in [("config", "playbook"), ("results", "cohort"),
                       ("results", "disposition"), ("results", "cde_profile"),
                       ("results", "threshold_proposal"), ("results", "threshold_review")]],
        f"CREATE TABLE IF NOT EXISTS {t('results', 'check_run')} LIKE "
        f"{t('results', 'check_run', SOURCE_SCHEMA)}",
        f"CREATE TABLE IF NOT EXISTS {t('results', 'violation_sample')} LIKE "
        f"{t('results', 'violation_sample', SOURCE_SCHEMA)}",
    ]
    for s in stmts:
        run(conn, s)

    # The clone predates the template columns; dq_triage has not taken them yet. ADD
    # COLUMNS appends at the end, which is where sql/ddl/01 declares them.
    have = {r["column_name"] for r in run(conn, f"""
        SELECT column_name FROM {CATALOG}.information_schema.columns
        WHERE table_schema = '{SCHEMA}' AND table_name = '{PREFIX}config_rule_registry'""")}
    if "template_id" not in have:
        run(conn, f"ALTER TABLE {t('config', 'rule_registry')} ADD COLUMNS ("
                  f"template_id STRING, template_version INT)")
    _try(conn, f"ALTER TABLE {t('config', 'rule_registry')} ADD CONSTRAINT "
               f"rule_registry_template_versioned "
               f"CHECK ((template_id IS NULL) = (template_version IS NULL))")

    # Everything else is the repo's DDL, rendered for this schema exactly as
    # sql/render.py renders it for dq_triage. The onboarding tables are no longer
    # declared here: a second CREATE TABLE is a second shape, and they had drifted.
    for f in DDL_FILES:
        _run_ddl(conn, f)
    _seed_templates(conn)
    _mock_source(conn)
    _select(conn)
    print(f"setup done: {S}")


# The repo's DDL that setup runs, in sql/render.py's order. 15 is the onboarding tables;
# the views follow it because SELECT * views freeze their columns at creation, so they
# are re-created after the ALTER above. 08 and 11 also give this schema the triage views.
DDL_FILES = ["15_config_onboarding.sql", "08_views.sql", "11_views_cde.sql",
             "14_views_threshold.sql", "16_views_onboarding.sql"]


def _run_ddl(conn, fname: str) -> None:
    """One sql/ddl file, rendered for this schema and run a statement at a time. Only
    from a laptop: the job's copy of this package carries no sql/ directory."""
    sys.path.insert(0, str(HERE.parent / "sql"))
    import render
    text = render.render((HERE.parent / "sql" / "ddl" / fname).read_text(),
                        CATALOG, SCHEMA, PREFIX)
    n = 0
    for stmt in render.statements(text):
        # ADD CONSTRAINT is not idempotent, and re-running setup must be.
        (_try if "ADD CONSTRAINT" in stmt else run)(conn, stmt)
        n += 1
    print(f"ddl: {fname}, {n} statements")


def _seed_templates(conn) -> None:
    have = {(r["template_id"], r["template_version"]) for r in
            run(conn, f"SELECT template_id, template_version FROM {t('config', 'check_template')}")}
    vals = []
    for tp in tpl.TEMPLATES:
        if (tp.template_id, tpl.TEMPLATE_VERSION) in have:
            continue
        vals.append("(" + ", ".join([
            lit(tp.template_id), lit(tpl.TEMPLATE_VERSION), lit(tp.data_class), lit(tp.check),
            lit(tp.title), lit(tp.input_type), lit(tp.rule_type), lit(tp.rule_expr),
            lit(tp.scope_filter), lit(tp.severity), lit(tp.source_rule),
            "current_user()", "current_timestamp()"]) + ")")
    if vals:
        run(conn, f"INSERT INTO {t('config', 'check_template')} ({TEMPLATE_COLS}) VALUES\n"
                  + ",\n".join(vals))
    print(f"templates: {len(vals)} added, {len(have)} already present")


def _mock_source(conn) -> None:
    cols = ", ".join(f"{c} STRING" for c in mock_lead.COLUMNS)
    run(conn, f"CREATE TABLE IF NOT EXISTS {LEAD} ({cols}) COMMENT 'Mock CRM lead extract for "
              f"the onboarding test. See onboarding/mock_lead.py for every planted defect.'")
    if run(conn, f"SELECT count(*) AS n FROM {LEAD}")[0]["n"] == 0:
        rows = mock_lead.rows()
        for i in range(0, len(rows), 250):
            vals = ",\n".join("(" + ", ".join(lit(r[c]) for c in mock_lead.COLUMNS) + ")"
                              for r in rows[i:i + 250])
            run(conn, f"INSERT INTO {LEAD} VALUES\n{vals}")
        print(f"mock source: {len(rows)} rows into {LEAD}")
    for col, cde in mock_lead.TAGS.items():
        run(conn, f"ALTER TABLE {LEAD} ALTER COLUMN {col} SET TAGS ('cde' = {lit(cde)})")
    print(f"tags: {len(mock_lead.TAGS)} columns tagged with key 'cde'")


def _select(conn) -> None:
    if run(conn, f"SELECT 1 FROM {t('config', 'monitored_table')} "
                 f"WHERE target_table = {lit(LEAD)}"):
        return
    m = MONITORED
    keys = "array(" + ", ".join(lit(k) for k in m["row_key"]) + ")"
    run(conn, f"""INSERT INTO {t('config', 'monitored_table')} ({MONITORED_COLS}) VALUES (
  {lit(m['target_table'])}, 1, {lit(m['table_code'])}, {keys}, {lit(m['owner_group'])},
  {lit(m['business_domain'])}, {lit(m['schedule_group'])}, {lit(m['scan_mode'])}, 'selected',
  current_timestamp(), current_user(), 'Onboarding test: mock CRM lead extract.')""")
    print(f"selected: {LEAD}")


# ---------------------------------------------------------------------------
# discover (job)
# ---------------------------------------------------------------------------

def discover(conn) -> None:
    elements = run(conn, f"""SELECT cde_id, cde_name, data_class, expected_signature
        FROM {t('config', 'v_cde_registry_current')} WHERE status = 'registered'""")
    known = {e["cde_id"] for e in elements}
    signed = [e for e in elements if e["expected_signature"]]
    tables = [r["target_table"] for r in run(conn, f"""
        SELECT target_table FROM {t('config', 'v_monitored_table_current')}
        WHERE status = 'selected'""")]

    for table in tables:
        cat, sch, name = table.split(".")
        typed = {r["column_name"]: r["data_type"] for r in run(conn, f"""
            SELECT column_name, data_type FROM {cat}.information_schema.columns
            WHERE table_schema = '{sch}' AND table_name = '{name}'
            ORDER BY ordinal_position""")}
        cols = list(typed)
        bound = {r["target_column"] for r in run(conn, f"""
            SELECT target_column FROM {t('config', 'v_binding_current')}
            WHERE target_table = {lit(table)}""")}
        # Every column anyone has proposed, decided or not. A rejected column is not
        # proposed again by name or pattern -- the owner already said no -- only by a
        # tag added since, which is someone stating it deliberately.
        prior = {}
        for r in run(conn, f"""
            SELECT p.target_column, p.method, r.decision FROM {t('config', 'binding_proposal')} p
            LEFT JOIN {t('config', 'binding_review')} r ON r.proposal_id = p.proposal_id
            WHERE p.target_table = {lit(table)}"""):
            prior.setdefault(r["target_column"], []).append((r["method"], r["decision"]))
        tags = {r["column_name"]: r["tag_value"] for r in run(conn, f"""
            SELECT column_name, tag_value FROM {cat}.information_schema.column_tags
            WHERE schema_name = '{sch}' AND table_name = '{name}' AND tag_name = 'cde'""")}

        def _settled(c: str) -> bool:
            seen = prior.get(c, [])
            if any(d != "rejected" for _, d in seen):
                return True                     # open or approved: nothing to add
            if seen and c in tags and not any(m == "uc_tag" for m, _ in seen):
                return False                    # rejected before, tagged since
            return bool(seen)

        pending = {c for c in prior if _settled(c)}
        todo = [c for c in cols if c not in bound and c not in pending]
        proposals, report = [], []

        # 1. UC tags: someone already said what the column is.
        for c in [c for c in todo if c in tags]:
            if tags[c] in known:
                proposals.append((c, tags[c], "uc_tag", 1.0, f"column tag cde = {tags[c]}"))
            else:
                report.append((c, "tag names an element that is not registered", tags[c]))

        # 2. Value signatures, one aggregate over the table for every untagged text column.
        untagged = [c for c in todo if c not in tags]
        unnamed = []                 # left for step 3
        non_text = [c for c in untagged if typed[c] != "STRING"]
        untagged = [c for c in untagged if typed[c] == "STRING"]
        unnamed += non_text
        if untagged and signed:
            parts = []
            for c in untagged:
                parts.append(f"count_if(trim({c}) <> '') AS n__{c}")
                for k, e in enumerate(signed):
                    parts.append(f"count_if(trim({c}) <> '' AND {c} RLIKE "
                                 f"{lit(e['expected_signature'])}) AS m__{c}__{k}")
            agg = run(conn, f"SELECT {', '.join(parts)} FROM {table}")[0]
            for c in untagged:
                n = agg[f"n__{c}"] or 0
                if n < SIGNATURE_MIN_VALUES:
                    unnamed.append(c)
                    continue
                rates = sorted(((100.0 * (agg[f"m__{c}__{k}"] or 0) / n, e)
                                for k, e in enumerate(signed)), key=lambda x: -x[0])
                hits = [(pct, e) for pct, e in rates if pct >= SIGNATURE_THRESHOLD_PCT]
                if len(hits) == 1:
                    pct, e = hits[0]
                    proposals.append((c, e["cde_id"], "value_signature", round(pct / 100, 4),
                                      f"{pct:.1f}% of {n} non-blank values match "
                                      f"{e['cde_name']}'s pattern; no other element's does"))
                elif hits:
                    report.append((c, f"matches {len(hits)} elements' patterns; tag it to say "
                                      f"which", ", ".join(e["cde_id"] for _, e in hits)))
                elif rates and rates[0][0] >= 50:
                    report.append((c, f"near miss: best match {rates[0][0]:.1f}% "
                                      f"({rates[0][1]['cde_id']}), below "
                                      f"{SIGNATURE_THRESHOLD_PCT:.0f}%", ""))
                else:
                    unnamed.append(c)
        else:
            unnamed += untagged

        # 3. Column names, for what neither a tag nor the values settled.
        for c in unnamed:
            key = "".join(ch for ch in c.lower() if ch.isalnum())
            hits = [cde for cde, names in NAME_HINTS.items() if key in names and cde in known]
            if len(hits) == 1:
                proposals.append((c, hits[0], "name_match", NAME_MATCH_CONFIDENCE,
                                  f"column name {c!r} names this element "
                                  f"({typed[c]})"))
            elif hits:
                report.append((c, "name matches several elements", ", ".join(hits)))
            else:
                report.append((c, "nothing identifies it", typed[c]))

        if proposals:
            vals = ",\n".join(
                f"({lit(str(uuid.uuid4()))}, current_timestamp(), {lit(table)}, {lit(c)}, "
                f"{lit(cde)}, {lit(m)}, {conf}, {lit(ev)}, 'job:onboard-discover')"
                for c, cde, m, conf, ev in proposals)
            run(conn, f"INSERT INTO {t('config', 'binding_proposal')} ({PROPOSAL_COLS}) "
                      f"VALUES\n{vals}")

        print(f"\n{table}: {len(cols)} columns, {len(bound)} already bound, "
              f"{len(pending)} already proposed")
        print(f"  proposed ({len(proposals)}):")
        for c, cde, m, conf, ev in proposals:
            print(f"    {c:<14} -> {cde:<20} {m:<16} {conf:.2f}  {ev}")
        print(f"  not proposed ({len(report)}):")
        for c, why, extra in report:
            print(f"    {c:<14} {why}{'  [' + extra + ']' if extra else ''}")
    print("\nNext: a person reviews the open proposals -- review.sql, step 1.")


# ---------------------------------------------------------------------------
# apply (job): approved proposals become bindings
# ---------------------------------------------------------------------------

def apply(conn) -> None:
    approved = run(conn, f"""
        SELECT p.*, r.reviewed_by, r.reason
        FROM   {t('config', 'binding_proposal')} p
        JOIN   (SELECT *, ROW_NUMBER() OVER (PARTITION BY proposal_id ORDER BY reviewed_at DESC) rn
                FROM {t('config', 'binding_review')}) r
               ON r.proposal_id = p.proposal_id AND r.rn = 1 AND r.decision = 'approved'
        LEFT ANTI JOIN {t('config', 'v_binding_current')} b
               ON b.target_table = p.target_table AND b.target_column = p.target_column""")
    # THE SECOND APPROVER, again. The app refuses a person approving their own
    # suggestion; this refuses to apply one that reached the table some other way.
    # A waived self-approval (the dq-onboard test app) carries the marker in its reason;
    # without it, a self-approval is refused whatever wrote it.
    own = [p for p in approved if not str(p["proposed_by"]).startswith("job:")
           and str(p["proposed_by"]).lower() == str(p["reviewed_by"]).lower()
           and not str(p.get("reason") or "").startswith("[second approver waived]")]
    for p in own:
        print(f"refused: {p['target_column']} -> {p['cde_id']} was approved by the person "
              f"who suggested it ({p['reviewed_by']}); it needs a second approver")
    approved = [p for p in approved if p not in own]
    by_cde: dict[str, list[dict]] = {}
    for p in approved:
        by_cde.setdefault(p["cde_id"], []).append(p)

    reg = t("config", "cde_registry")
    cols = ("cde_id, cde_version, cde_name, business_term, data_class, definition, "
            "expected_signature, criticality, pii, regulatory_basis, tolerance_pct, bindings, "
            "business_domain, owner_group, status, effective_from, registered_by, registered_at, "
            "note")
    for cde, ps in by_cde.items():
        structs = ", ".join(
            f"named_struct('target_table', {lit(p['target_table'])}, 'target_column', "
            f"{lit(p['target_column'])}, 'populated_when', CAST(NULL AS STRING), "
            f"'expected_scope_filter', CAST(NULL AS STRING), 'binding_status', 'bound', "
            f"'discovered_by', {lit(p['method'])}, 'confidence', CAST({p['confidence']} AS DOUBLE))"
            for p in ps)
        names = ", ".join(f"{p['target_table'].split('.')[-1]}.{p['target_column']}" for p in ps)
        who = ", ".join(sorted({p["reviewed_by"] for p in ps}))
        # ONE new version per element per apply, built from the latest version, so the
        # bindings array is never written from a stale copy.
        run(conn, f"""INSERT INTO {reg} ({cols})
SELECT cde_id, cde_version + 1, cde_name, business_term, data_class, definition,
       expected_signature, criticality, pii, regulatory_basis, tolerance_pct,
       concat(bindings, array({structs})), business_domain, owner_group, status,
       current_timestamp(), 'job:onboard-apply', current_timestamp(),
       {lit(f'Binds {names}: proposals approved by {who}. Nothing else about the element changed.')}
FROM   {reg}
WHERE  cde_id = {lit(cde)}
  AND  cde_version = (SELECT max(cde_version) FROM {reg} WHERE cde_id = {lit(cde)})""")
        print(f"{cde}: +{len(ps)} binding(s) ({names})")
    if not by_cde:
        print("nothing approved and unapplied")


# ---------------------------------------------------------------------------
# generate (job): templates x bound columns -> shadow rules
# ---------------------------------------------------------------------------

RULE_COLS = ("rule_id, rule_version, rule_name, target_table, target_column, cde_id, rule_type, "
             "rule_expr, scope_filter, fail_threshold_pct, severity, business_domain, owner_group, "
             "source_layer, status, effective_from, created_by, created_at, promoted_by, "
             "promoted_at, note, join_sql, template_id, template_version")


def generate(conn) -> None:
    targets = run(conn, f"""
        SELECT b.cde_id, b.cde_name, b.data_class, b.tolerance_pct, b.target_table,
               b.target_column, b.expected_scope_filter, m.table_code,
               -- The table's own, else the element's: a check with no domain vanished
               -- from every domain filter in the app.
               coalesce(m.owner_group, e.owner_group) AS owner_group,
               coalesce(m.business_domain, e.business_domain) AS business_domain,
               c.data_type
        FROM   {t('config', 'v_binding_current')} b
        JOIN   {t('config', 'v_cde_registry_current')} e ON e.cde_id = b.cde_id
        JOIN   {t('config', 'v_monitored_table_current')} m
               ON m.target_table = b.target_table AND m.status = 'selected'
        -- system.information_schema spans every catalog; {CATALOG}.information_schema
        -- covers only its own, which silently dropped every table selected from `samples`.
        JOIN   system.information_schema.columns c
               ON concat_ws('.', c.table_catalog, c.table_schema, c.table_name) = b.target_table
              AND c.column_name = b.target_column""")
    existing = {(r["template_id"], r["target_table"], r["target_column"]): r for r in run(conn, f"""
        SELECT rule_id, rule_version, template_id, template_version, target_table, target_column
        FROM {t('config', 'v_rule_registry_current')} WHERE template_id IS NOT NULL""")}
    taken = {r["rule_id"] for r in run(conn, f"SELECT DISTINCT rule_id FROM {t('config', 'rule_registry')}")}
    # A template may call a helper the repo declares and this workspace has not been
    # given yet. One such rule would fail the whole table, because the runner checks
    # every row-level rule on a table in one query -- so it is refused here instead.
    deployed = {r["routine_name"] for r in run(conn, f"""
        SELECT routine_name FROM {CATALOG}.information_schema.routines
        WHERE routine_schema = '{SOURCE_SCHEMA}'""")}

    # A column someone has already written rules for is left to them. Templates are
    # for columns with nothing: on dq_mock_ctct_c, generating anyway produced 25 copies of
    # registered rules -- 17 word for word, 8 the same check written with the newer
    # helpers, which an expression comparison cannot see but the measured counts did.
    handwritten = {(r["target_table"], r["target_column"]) for r in run(conn, f"""
        SELECT DISTINCT target_table, target_column FROM {t('config', 'v_rule_registry_current')}
        WHERE template_id IS NULL AND target_column IS NOT NULL""")}

    vals, skipped = [], []
    for b in targets:
        if (b["target_table"], b["target_column"]) in handwritten:
            skipped.append(f"{b['target_column']}: already has hand-written rules; no "
                           "templates applied")
            continue
        for tp in tpl.for_class(b["data_class"]):
            key = (tp.template_id, b["target_table"], b["target_column"])
            if key in existing and existing[key]["template_version"] == tpl.TEMPLATE_VERSION:
                continue
            missing = sorted(set(tpl.helpers(tp)) - deployed)
            if missing:
                skipped.append(f"{b['target_column']}: {tp.template_id} calls "
                               f"{', '.join(missing)}, not deployed in this workspace")
                continue
            if b["data_type"] != tp.input_type:
                skipped.append(f"{b['target_column']}: {tp.template_id} expects "
                               f"{tp.input_type}, column is {b['data_type']}")
                continue
            expr, scope = tp.instantiate(b["target_column"])
            if b["expected_scope_filter"]:
                scope = f"({scope}) AND ({b['expected_scope_filter']})" if scope \
                    else b["expected_scope_filter"]
            rule_id = f"{b['table_code']}_{b['target_column']}_{tp.check}"
            version = existing[key]["rule_version"] + 1 if key in existing else 1
            if key not in existing and rule_id in taken:
                skipped.append(f"{rule_id}: id already used by a rule not from this template")
                continue
            # The element's tolerance is the ceiling on any rule's limit; the generated
            # rule starts AT the ceiling and the threshold job may tighten it in shadow.
            limit = float(b["tolerance_pct"]) if b["tolerance_pct"] is not None else 0.0
            name = tp.title.replace("{element}", b["cde_name"]) + f" ({b['target_column']})"
            note = (f"Generated from {tp.template_id} v{tpl.TEMPLATE_VERSION} (lifted from "
                    f"{tp.source_rule}) on the binding {b['target_column']} -> {b['cde_id']}. "
                    f"Limit set to the element's tolerance.")
            vals.append("(" + ", ".join([
                lit(rule_id), lit(version), lit(name), lit(b["target_table"]),
                lit(b["target_column"]), lit(b["cde_id"]), lit(tp.rule_type), lit(expr),
                lit(scope), repr(limit), lit(tp.severity), lit(b["business_domain"]),
                lit(b["owner_group"]), "'L2'", "'shadow'", "current_timestamp()",
                "'job:onboard-generate'", "current_timestamp()", "NULL", "NULL", lit(note),
                "NULL", lit(tp.template_id), lit(tpl.TEMPLATE_VERSION)]) + ")")
    if vals:
        run(conn, f"INSERT INTO {t('config', 'rule_registry')} ({RULE_COLS}) VALUES\n"
                  + ",\n".join(vals))
    print(f"generated {len(vals)} shadow rules over {len({(b['target_table'], b['target_column']) for b in targets})} bound columns")
    for s in skipped:
        print(f"  skipped: {s}")


# ---------------------------------------------------------------------------
# run (real serverless job): jobs/run_checks.py on the selected tables
# ---------------------------------------------------------------------------

def run_checks(_conn) -> None:
    me = json.loads(subprocess.check_output(
        ["databricks", "current-user", "me", "-o", "json"]))["userName"]
    remote = f"/Users/{me}/dq-triage/jobs/run_checks.py"
    subprocess.check_call(["databricks", "workspace", "mkdirs", str(Path(remote).parent)])
    subprocess.check_call(["databricks", "workspace", "import", remote, "--file",
                           str(HERE.parent / "jobs" / "run_checks.py"), "--format", "AUTO",
                           "--overwrite"])
    job = {"run_name": "dq-onboard: run_checks",
           "tasks": [{"task_key": "run_checks", "environment_key": "env",
                      "spark_python_task": {"python_file": remote, "parameters": [
                          "--catalog", CATALOG, "--schema", SCHEMA, "--prefix", PREFIX,
                          "--fn-prefix", f"{CATALOG}.{SOURCE_SCHEMA}.{PREFIX}fn_"]}}],
           "environments": [{"environment_key": "env", "spec": {"client": "3"}}]}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(job, f)
    out = subprocess.run(["databricks", "jobs", "submit", "--json", f"@{f.name}", "-o", "json"],
                         capture_output=True, text=True)
    print(out.stdout[-1500:] or out.stderr[-1500:])
    if out.returncode:
        raise SystemExit(out.returncode)


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

def status(conn) -> None:
    for r in run(conn, f"SELECT * FROM {t('config', 'v_onboarding_status')}"):
        print(f"{r['target_table']}\n  stage: {r['stage']}")
        for k in ("proposals_open", "columns_bound", "rules_shadow", "rules_active", "runs",
                  "last_run_ts"):
            print(f"  {k:<15} {r[k]}")
    latest = run(conn, f"""
        WITH last AS (SELECT target_table, max(run_ts) AS ts FROM {t('results', 'check_run')}
                      GROUP BY target_table)
        SELECT c.rule_id, c.status, c.violation_count, c.rows_scanned, c.violation_pct, c.message
        FROM   {t('results', 'check_run')} c JOIN last l
               ON l.target_table = c.target_table AND l.ts = c.run_ts
        WHERE  c.target_table = {lit(LEAD)} ORDER BY c.rule_id""")
    if latest:
        print("\n  latest run:")
        for r in latest:
            print(f"    {r['rule_id']:<30} {r['status']:<8} {r['violation_count']!s:>5} / "
                  f"{r['rows_scanned']!s:<5} {r['message'] if r['status'] == 'error' else ''}")


def unbind_retired(conn) -> None:
    """Remove a decommissioned table's columns from the element register.

    The app retires the table and its checks; this job is the register's only writer,
    so it drops the bindings -- one new version per element, written from the latest,
    the same way apply adds them. Left in place, coverage would keep counting columns
    nothing checks any more."""
    gone = {r["target_table"] for r in run(conn, f"""
        SELECT target_table FROM {t('config', 'v_monitored_table_current')}
        WHERE status = 'retired'""")}
    if not gone:
        print("no decommissioned tables")
        return
    reg = t("config", "cde_registry")
    hits = run(conn, f"""SELECT DISTINCT cde_id, target_table, target_column
        FROM {t('config', 'v_binding_current')}
        WHERE target_table IN ({', '.join(lit(g) for g in sorted(gone))})""")
    by_cde: dict[str, list[str]] = {}
    for h in hits:
        by_cde.setdefault(h["cde_id"], []).append(f"{h['target_table'].split('.')[-1]}.{h['target_column']}")
    cols = ("cde_id, cde_version, cde_name, business_term, data_class, definition, "
            "expected_signature, criticality, pii, regulatory_basis, tolerance_pct, bindings, "
            "business_domain, owner_group, status, effective_from, registered_by, registered_at, "
            "note")
    gone_list = ", ".join(lit(g) for g in sorted(gone))
    for cde, names in by_cde.items():
        note = f"Unbinds {', '.join(names)}: the table was decommissioned. Nothing else changed."
        run(conn, f"""INSERT INTO {reg} ({cols})
SELECT cde_id, cde_version + 1, cde_name, business_term, data_class, definition,
       expected_signature, criticality, pii, regulatory_basis, tolerance_pct,
       filter(bindings, b -> NOT array_contains(array({gone_list}), b.target_table)),
       business_domain, owner_group, status, current_timestamp(), 'job:onboard-unbind',
       current_timestamp(), {lit(note)}
FROM   {reg}
WHERE  cde_id = {lit(cde)}
  AND  cde_version = (SELECT max(cde_version) FROM {reg} WHERE cde_id = {lit(cde)})""")
        print(f"{cde}: unbound {', '.join(names)}")
    if not by_cde:
        print("decommissioned tables hold no bindings")


def unmeasured_tables(conn) -> list[str]:
    """Selected tables carrying a shadow rule version that no check run has measured."""
    return [r["target_table"] for r in run(conn, f"""
        SELECT DISTINCT r.target_table
        FROM   {t('config', 'v_rule_registry_current')} r
        JOIN   {t('config', 'v_monitored_table_current')} m
               ON m.target_table = r.target_table AND m.status = 'selected'
        LEFT ANTI JOIN {t('results', 'check_run')} c
               ON c.rule_id = r.rule_id AND c.rule_version = r.rule_version
        WHERE  r.status = 'shadow'""")]


def measure_shadow(conn) -> None:
    """Measure newly generated shadow checks now, on their tables only.

    Safe to run the moment they exist: `--shadow-only` means every verdict written is
    `skipped` -- measured, raising nothing -- and no active rule runs here. Active
    results come from the daily dq-checks job, never from an event."""
    tables = unmeasured_tables(conn)
    if not tables:
        print("no unmeasured shadow checks")
        return
    if not in_databricks():
        print(f"unmeasured shadow checks on {', '.join(tables)}: the check runner needs "
              "Spark, so they are measured when this runs as a Lakeflow task")
        return
    sys.path.insert(0, str(HERE.parent / "jobs"))
    import run_checks   # noqa: PLC0415 -- the job's own runner, imported where Spark exists
    print(f"measuring shadow checks on {', '.join(tables)}")
    rc = run_checks.main(["--catalog", CATALOG, "--schema", SCHEMA, "--prefix", PREFIX,
                          "--fn-prefix", f"{CATALOG}.{SOURCE_SCHEMA}.{PREFIX}fn_",
                          "--tables", ",".join(tables), "--shadow-only"])
    if rc:
        raise SystemExit(rc)


def steps(conn) -> None:
    """What the event-triggered job runs when a table is submitted or a binding decided:
    every step that needs no person, then a shadow-only measurement of anything new."""
    print("== discover"); discover(conn)
    print("\n== apply"); apply(conn)
    print("\n== unbind decommissioned tables"); unbind_retired(conn)
    print("\n== generate"); generate(conn)
    print("\n== measure new shadow checks"); measure_shadow(conn)


def pipeline(conn) -> None:
    """What the Lakeflow job runs before the check runner: every step that needs no
    person, in order. Each is idempotent, so a run with nothing new does nothing."""
    print("== discover"); discover(conn)
    print("\n== apply"); apply(conn)
    print("\n== generate"); generate(conn)


def _try(conn, sql: str) -> None:
    try:
        run(conn, sql)
    except Exception as exc:                       # noqa: BLE001 -- constraint already there
        if "already exists" not in str(exc).lower():
            raise


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["setup", "discover", "apply", "generate", "run", "status",
                                     "pipeline", "steps"])
    step = ap.parse_args().step
    if step == "setup":
        miss = tpl.equivalence()
        if miss:
            print(f"templates do not reproduce their source rules: {miss}")
            return 1
    with connect() as conn:
        {"setup": setup, "discover": discover, "apply": apply, "generate": generate,
         "run": run_checks, "status": status, "pipeline": pipeline, "steps": steps}[step](conn)
    return 0


if __name__ == "__main__":
    # A serverless Python task runs under IPython, which reports SystemExit(0) as a
    # failed task; exit only on failure (the same fix as jobs/run_checks.py).
    rc = main()
    if rc:
        sys.exit(rc)

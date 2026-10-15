#!/usr/bin/env python3
"""Assemble production/ — the SQL and the jobs, rendered for ONE sandpit schema.

    .venv/bin/python tools/build_production.py
    .venv/bin/python tools/build_production.py --catalog sdpt_data_trnf --schema udp_brnz \\
        --prefix dq_ --source-catalog prod

Everything in production/ is rendered for the names given here, so the SQL files, the
job bundle and the two notebooks agree with each other. Change a name by re-running
this, never by editing production/ by hand.

WHAT IS IN IT. The pipeline without the app: the DDL (sql/render.py's sandpit layout,
one schema, `dq_<group>_<table>`), the key-attribute register and its 119 rules, the
placeholder tolerances, the current-record declaration, a SQL promote step (the app's
Promote button, as a statement a person runs), the check runner, the triage notebook
and the tolerance-advice notebook, and a Databricks Asset Bundle that schedules them.

WHAT IS NOT. The app (`dq-app/`), and with it everything that only an app write starts:
onboarding/ and its steps job (they react to monitored_table / binding_review /
consistency_review appends, which only the app makes), notebook 04 (mails on an
accepted review, which only the app records), fixtures/, and sql/out/ (rendered for
workspace.dq_triage, with mock sources and seeded history).
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import sys

ROOT = pathlib.Path(__file__).parent.parent
OUT = ROOT / "production"
sys.path.insert(0, str(ROOT / "sql"))
sys.path.insert(0, str(ROOT / "key_attributes"))

import render  # noqa: E402
import migrate_key_attributes as mka  # noqa: E402
import migrate_key_attribute_tolerance as mtol  # noqa: E402
import migrate_key_attributes_source as msrc  # noqa: E402
import migrate_table_population as mpop  # noqa: E402
import register as ka  # noqa: E402
from migrate_cde_scope import RULE_COLUMNS, lit  # noqa: E402

MODEL = "system.ai.gpt-oss-120b"
NOTEBOOK_NAMES = 'CATALOG, SCHEMA, PREFIX = "workspace", "dq_triage", "dq_"'


def banner(title: str, *lines: str) -> str:
    bar = "-- " + "=" * 69
    return "\n".join([bar, f"-- {title}", *(f"-- {l}" if l else "--" for l in lines), bar])


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

def preflight(cat: str, sch: str, pre: str, tables: list[str]) -> str:
    probe = f"{cat}.{sch}.{pre}probe"
    out = [banner(
        "00_preflight.sql — read-only apart from two probe objects it drops again.",
        f"target: {cat}.{sch}, prefix {pre}",
        "",
        "Run in the SQL editor, statement by statement. Every one should succeed. A",
        "failure tells you which later step cannot run, before anything is created.")]
    out += ["", "-- 0a — who you are, and that the schema exists.",
            "SELECT current_user() AS me, current_catalog() AS catalog_now;",
            f"DESCRIBE SCHEMA {cat}.{sch};",
            "",
            "-- 0b — you can create a view and a function here. 01_ddl.sql creates both; without",
            "-- CREATE FUNCTION no rule that calls a helper can run.",
            f"CREATE OR REPLACE VIEW {probe}_v AS SELECT 1 AS x;",
            f"CREATE OR REPLACE FUNCTION {probe}_f(a INT) RETURNS INT RETURN a + 1;",
            f"SELECT {probe}_f(1) AS should_be_2;",
            f"DROP VIEW {probe}_v;",
            f"DROP FUNCTION {probe}_f;",
            "",
            "-- 0c — nothing of ours is here yet. EXPECTED: zero rows. If rows come back the DDL",
            "-- has run before: 01_ddl.sql is NOT re-runnable (ADD CONSTRAINT fails a second",
            "-- time), so skip it, or use a fresh schema.",
            f"SELECT table_name FROM {cat}.information_schema.tables",
            f"WHERE  table_schema = '{sch}' AND table_name LIKE '{pre}%' ORDER BY 1;",
            "",
            "-- 0d — the five source tables are readable. EXPECTED: five rows, each with rows > 0.",
            "-- A permission error here means every check on that table will be recorded as an",
            "-- error: ask for USE CATALOG / USE SCHEMA / SELECT on it before going further.",
            "\nUNION ALL\n".join(f"SELECT '{t}' AS source_table, COUNT(*) AS `rows` FROM {t}"
                                 for t in tables) + ";",
            "",
            "-- 0e — the columns 05_current_records.sql reads. EXPECTED: zero rows (none missing).",
            "-- A row means that table has no CDC columns of that name: drop its INSERT from 05",
            "-- and its checks will read every version of every record.",
            "WITH need AS (SELECT t, c FROM VALUES " + ", ".join(
                f"('{t}', '{c}')" for t in tables
                for c in [*mpop.VERSION_BY, "OP_TYPE", *ka.ROW_KEY[_canon(t)]]) + " AS v(t, c))",
            "SELECT n.t AS source_table, n.c AS missing_column FROM need n",
            "LEFT ANTI JOIN system.information_schema.columns s",
            "  ON concat_ws('.', s.table_catalog, s.table_schema, s.table_name) = n.t",
            " AND lower(s.column_name) = lower(n.c)",
            "ORDER BY 1, 2;",
            "",
            f"-- 0f — not a query: check Serving > Endpoints shows {MODEL} as Ready. Both",
            "-- notebooks call it. If it is missing, change MODEL_NAME in both notebooks; the",
            "-- triage task would otherwise fail AFTER the checks have written, which is safe.",
            ""]
    return "\n".join(out)


def _canon(table: str) -> str:
    """The register's own name for a source table, whatever catalog it was rendered on."""
    return next(t for t in ka.TABLES if t.split(".", 1)[1] == table.split(".", 1)[1])


def ddl(cat: str, sch: str, pre: str) -> tuple[str, dict]:
    files = sorted((f for f in render.DDL.glob("*.sql") if f.name not in render.SKIP),
                   key=lambda f: render.ORDER.index(f.name[:2]))
    texts = []
    for f in files:
        text = f.read_text()
        if f.name.startswith("12"):
            text = render.strip_12(text)
        texts.append((f.name, render.render(text, cat, sch, pre)))
    for name, text in texts:
        for n, line in enumerate(text.splitlines(), 1):
            if not line.lstrip().startswith("--") and re.search(r"\{[a-z_]+\}", line):
                raise SystemExit(f"unrendered placeholder in {name}:{n}: {line.strip()}")
    c = render.counts([t for _, t in texts])
    head = banner(
        "01_ddl.sql — every table, constraint, function and view. RUN ONCE.",
        f"target: {cat}.{sch}, prefix {pre}. Rendered from sql/ddl/ by sql/render.py's rules:",
        "the config/results/fn schemas become name prefixes in this one schema.",
        "",
        f"Expected when complete: {c['tables']} tables, {c['views']} views, "
        f"{c['functions']} functions, {c['constraints']} CHECK constraints.",
        "",
        "ADD CONSTRAINT is not idempotent: a second pass fails on every constraint. If it",
        "stops partway, fix that one statement and continue from its banner.",
        "Comments inside still say {catalog} and describe two schemas: they are the source",
        "text, kept so this file reads against sql/ddl/. The statements are rendered.")
    parts = [head]
    for i, (name, text) in enumerate(texts, 1):
        parts.append(f"\n\n{banner(f'[{i}/{len(texts)}]  sql/ddl/{name}')}\n\n{text}")
    return "".join(parts) + "\n", c


def from_build(lines: list[str], title: str, *why: str) -> str:
    return banner(title, *why) + "\n\n" + "\n".join(lines) + "\n"


def promote(cat: str, sch: str, pre: str) -> str:
    q = f"{cat}.{sch}.{pre}"
    reg, reg_cur = f"{q}config_rule_registry", f"{q}config_v_rule_registry_current"
    run = f"{q}results_check_run"
    sel = [{"rule_version": "r.rule_version + 1", "status": "'active'",
            "effective_from": "current_timestamp()", "created_by": "current_user()",
            "created_at": "current_timestamp()", "promoted_by": "current_user()",
            "promoted_at": "current_timestamp()",
            "note": "'Promoted by SQL (production/sql/06_promote.sql) after its shadow "
                    "measurement was reviewed.'"}.get(c, f"r.{c}") for c in RULE_COLUMNS]
    return "\n".join([
        banner("06_promote.sql — shadow -> active. The app's Promote button, as SQL.",
               f"target: {cat}.{sch}, prefix {pre}",
               "",
               "Every rule is registered in SHADOW: measured, never raised. Only an active rule",
               "can breach, so until this runs nothing reaches the triage notebook. Promotion",
               "is a person's decision, and current_user() is the name the register keeps.",
               "",
               "Run it after the pipeline has measured the rules at least once, and after",
               "reading 6a. Re-runnable: a rule already active is not touched."),
        "",
        "-- 6a — what each shadow rule measured on its latest run. Read this first: a rule",
        "-- flagging most of its table is more likely a wrong rule than bad data, and",
        "-- promoting it fills triage with one problem that is not a data defect.",
        "SELECT r.target_table, r.rule_id, r.severity, c.rows_scanned, c.violation_count,",
        "       round(c.violation_pct, 2) AS violation_pct, c.run_ts",
        f"FROM   {reg_cur} r",
        f"LEFT JOIN (SELECT *, row_number() OVER (PARTITION BY rule_id ORDER BY run_ts DESC) AS n",
        f"           FROM {run}) c ON c.rule_id = r.rule_id AND c.n = 1",
        "WHERE  r.status = 'shadow'",
        "ORDER  BY violation_pct DESC NULLS FIRST, r.rule_id;",
        "",
        "-- 6b — promote. As written it promotes every MEASURED shadow rule on every table.",
        "-- Narrow it by uncommenting a line below; start with one table.",
        f"INSERT INTO {reg} ({', '.join(RULE_COLUMNS)})",
        f"SELECT {', '.join(sel)}",
        f"FROM   {reg_cur} r",
        "WHERE  r.status = 'shadow'",
        f"  AND  EXISTS (SELECT 1 FROM {run} c WHERE c.rule_id = r.rule_id",
        "                                     AND c.status IN ('skipped', 'pass', 'breach'))",
        f"  -- AND r.target_table = '{ka.TABLES[1]}'",
        "  -- AND r.rule_id IN ('...', '...')",
        ";",
        "",
        "-- 6c — EXPECTED: the rules you meant, now 'active'.",
        f"SELECT target_table, status, COUNT(*) AS rules FROM {reg_cur}",
        "GROUP BY 1, 2 ORDER BY 1, 2;",
        ""])


def verify(cat: str, sch: str, pre: str) -> str:
    q = f"{cat}.{sch}.{pre}"
    return "\n".join([
        banner("07_verify.sql — read-only. After each pipeline run.",
               f"target: {cat}.{sch}, prefix {pre}"),
        "",
        "-- 7a — the latest runs. A shadow-only day reads all 'skipped'; 'error' needs 7b.",
        "SELECT run_id, min(run_ts) AS run_ts, status, COUNT(*) AS checks",
        f"FROM   {q}results_check_run",
        f"WHERE  run_id IN (SELECT run_id FROM {q}results_check_run",
        "                  GROUP BY run_id ORDER BY max(run_ts) DESC LIMIT 3)",
        "GROUP  BY run_id, status ORDER BY run_ts DESC, status;",
        "",
        "-- 7b — every error on the latest run, with the warehouse's reason. Usually a",
        "-- source table or column this principal cannot read, or a helper function missing.",
        "SELECT rule_id, target_table, message",
        f"FROM   {q}results_check_run",
        f"WHERE  status = 'error' AND run_id = (SELECT max_by(run_id, run_ts) FROM {q}results_check_run)",
        "ORDER  BY target_table, rule_id;",
        "",
        "-- 7c — rows read vs current records vs slice, per table on the latest run. population",
        "-- rows well below table rows is 05_current_records.sql working.",
        "SELECT target_table, max(table_rows) AS table_rows, max(population_rows) AS current_records,",
        "       max(slice_rows) AS in_slice",
        f"FROM   {q}results_check_run",
        f"WHERE  run_id = (SELECT max_by(run_id, run_ts) FROM {q}results_check_run)",
        "GROUP  BY target_table ORDER BY 1;",
        "",
        "-- 7d — breaches on the latest run, and which reach triage. A breach whose key",
        "-- attribute is within its tolerance is held back (not P1).",
        "SELECT rule_id, severity, violation_count, rows_scanned, cde_id, escalates, held_reason",
        f"FROM   {q}results_v_check_escalation",
        f"WHERE  run_id = (SELECT max_by(run_id, run_ts) FROM {q}results_check_run)",
        "ORDER  BY escalates DESC, violation_count DESC;",
        "",
        "-- 7e — what the triage notebook wrote. Every cohort it writes reads",
        "-- 'awaiting_triage' and is listed by v_disposition_integrity as",
        "-- missing_recommended_event: known, see CLAUDE.md 'The notebook never opens the chain'.",
        "SELECT c.cohort_id, c.raised_ts, c.member_count, c.defect_location, c.confidence,",
        "       v.lifecycle_state",
        f"FROM   {q}results_cohort c",
        f"JOIN   {q}results_v_cohort_current v USING (cohort_id)",
        "ORDER  BY c.raised_ts DESC;",
        ""])


# ---------------------------------------------------------------------------
# Notebooks and the bundle
# ---------------------------------------------------------------------------

def notebook(src: pathlib.Path, dst: pathlib.Path, cat: str, sch: str, pre: str) -> None:
    nb = json.loads(src.read_text())
    hits = 0
    for cell in nb["cells"]:
        text = "".join(cell["source"])
        if NOTEBOOK_NAMES in text:
            text = text.replace(NOTEBOOK_NAMES,
                                f'CATALOG, SCHEMA, PREFIX = "{cat}", "{sch}", "{pre}"'
                                "   # rendered by tools/build_production.py")
            cell["source"] = text.splitlines(keepends=True)
            hits += 1
    if hits != 1:
        raise SystemExit(f"{src.name}: expected one `{NOTEBOOK_NAMES}` line, found {hits}")
    dst.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n")


BUNDLE = """# GENERATED by tools/build_production.py — do not edit; re-run the generator.
#
# The pipeline as a Databricks Asset Bundle, rendered for {cat}.{sch} (prefix {pre}).
# Runs as whoever deploys it: in a sandpit that is you, and your own grants are what the
# jobs have. From this folder:
#
#   databricks bundle validate -t sandpit -p <profile>
#   databricks bundle deploy   -t sandpit -p <profile>
#   databricks bundle run dq_daily -t sandpit -p <profile>

bundle:
  name: dq-sandpit

include:
  - resources/*.yml

# Only what the jobs execute; sql/ is run by a person in the SQL editor.
sync:
  exclude:
    - sql/**
    - README.md

variables:
  daily_schedule:
    description: PAUSED or UNPAUSED. Deploy PAUSED, run by hand until a run is clean.
    default: PAUSED

targets:
  sandpit:
    default: true
    mode: development
    # host comes from the CLI profile (-p); set it here instead to pin the workspace:
    # workspace:
    #   host: https://<your-workspace>
"""

JOBS = """# GENERATED by tools/build_production.py — do not edit; re-run the generator.
# Target: {cat}.{sch}, prefix {pre}. Source tables in {src_cat}.

resources:
  jobs:
    dq_daily:
      name: dq {sch} daily checks and triage
      description: >-
        Runs every active and shadow rule on the selected key-attribute tables in
        {cat}.{sch} (results.check_run, results.violation_sample), then groups the
        breaches that escalate and asks {model} for a verdict on each group
        (results.cohort). Writes no business data.

      schedule:
        quartz_cron_expression: "0 0 3 * * ?"
        timezone_id: Australia/Sydney
        pause_status: ${{var.daily_schedule}}

      # Two runs at once would both write a check run for the same day.
      max_concurrent_runs: 1
      queue:
        enabled: true
      timeout_seconds: 7200

      # Uncomment and set an address to hear about a failed run:
      # email_notifications:
      #   on_failure: [you@example.com]

      environments:
        - environment_key: checks_env
          spec:
            client: "3"
        - environment_key: triage_env
          spec:
            client: "3"
            dependencies: [openai]

      tasks:
        - task_key: run_checks
          environment_key: checks_env
          spark_python_task:
            python_file: ../jobs/run_checks.py
            parameters:
              - "--catalog"
              - "{cat}"
              - "--schema"
              - "{sch}"
              - "--prefix"
              - "{pre}"
              - "--fn-prefix"
              - "{cat}.{sch}.{pre}fn_"
          max_retries: 1
          min_retry_interval_millis: 600000

        # Exits early, and succeeds, when nothing escalates: true of every run until a
        # rule is promoted (sql/06_promote.sql), because a shadow rule never breaches.
        - task_key: triage
          depends_on:
            - task_key: run_checks
          environment_key: triage_env
          notebook_task:
            notebook_path: ../notebooks/03_group_and_advise.ipynb
            base_parameters:
              triage_job_run_id: "{{{{job.run_id}}}}"
          max_retries: 0

    dq_tolerance_advice:
      name: dq {sch} tolerance advice
      description: >-
        On demand. One {model} call per key attribute, advising on its tolerance against
        the run history; writes results.tolerance_proposal and nothing else. Worth running
        only once there are a few weeks of runs.
      max_concurrent_runs: 1
      environments:
        - environment_key: advice_env
          spec:
            client: "3"
            dependencies: [openai]
      tasks:
        - task_key: advise
          environment_key: advice_env
          notebook_task:
            notebook_path: ../notebooks/06_suggest_thresholds.ipynb
            base_parameters:
              job_run_id: "{{{{job.run_id}}}}"
              only_cde: ""
"""


# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--catalog", default="sdpt_data_trnf")
    ap.add_argument("--schema", default="udp_brnz")
    ap.add_argument("--prefix", default="dq_")
    ap.add_argument("--source-catalog", default="prod",
                    help="catalog holding udp_brnz_nrt_tech_view.table_*_hist. `prod` is "
                         "the register's own name for them; anything else adds "
                         "sql/04_source_catalog.sql to point the register there")
    a = ap.parse_args()
    cat, sch, pre, src_cat = a.catalog, a.schema, a.prefix, a.source_catalog
    tables = [msrc.on(t, src_cat) for t in ka.TABLES]

    if OUT.exists():
        shutil.rmtree(OUT)
    for d in ("sql", "jobs", "notebooks", "resources"):
        (OUT / d).mkdir(parents=True)

    sql: list[tuple[str, str, str]] = []

    def put(name: str, text: str, what: str) -> None:
        (OUT / "sql" / name).write_text(text)
        sql.append((name, what, f"{text.count(chr(10))} lines"))

    put("00_preflight.sql", preflight(cat, sch, pre, tables),
        "read-only checks: privileges, source tables readable, CDC columns present")
    text, c = ddl(cat, sch, pre)
    put("01_ddl.sql", text, f"{c['tables']} tables, {c['views']} views, {c['functions']} "
        f"functions, {c['constraints']} constraints. **Run once**")
    lines, _ = mka.build(cat, sch, pre)
    put("02_key_attributes.sql", from_build(
        lines, "02_key_attributes.sql — the register: 22 key attributes, their rules in "
               "SHADOW, and the five source tables selected.",
        "Copied from sql/migrate_key_attributes.py's output. On a fresh schema parts 1-3",
        "retire nothing (there is no mock register here) and their INSERTs add 0 rows.",
        "Re-runnable: every INSERT is guarded."),
        f"22 key attributes, {len(mka.universe.all_rules())} shadow rules, 5 tables selected")
    lines, _ = mtol.build(cat, sch, pre)
    put("03_tolerances.sql", from_build(
        lines, "03_tolerances.sql — a PLACEHOLDER tolerance on each key attribute.",
        "Not business-approved. It decides which breaches reach triage. Re-runnable."),
        "placeholder tolerance per attribute; decides what escalates")
    if src_cat != "prod":
        lines, _ = msrc.build(src_cat, cat, sch, pre)
        put("04_source_catalog.sql", from_build(
            lines, f"04_source_catalog.sql — point the register at {src_cat}.*",
            "Moves every binding and rule onto the same schema and table",
            f"names in {src_cat}, decommissions the prod.* tables and selects these."),
            f"moves bindings and rules from prod.* to {src_cat}.*")
    put("05_current_records.sql", from_build(
        mpop.build(src_cat, cat, sch, pre),
        "05_current_records.sql — check the current record, not every CDC version.",
        "Without it the three uniqueness rules flag every record with two versions."),
        "current record per source table (newest version, OP_TYPE 'D' dropped)")
    put("06_promote.sql", promote(cat, sch, pre),
        "shadow -> active, after reviewing the shadow measurements")
    put("07_verify.sql", verify(cat, sch, pre), "read-only checks after each run")
    sql.sort()

    shutil.copy2(ROOT / "jobs" / "run_checks.py", OUT / "jobs" / "run_checks.py")
    for nb in ("03_group_and_advise.ipynb", "06_suggest_thresholds.ipynb"):
        notebook(ROOT / "notebooks" / nb, OUT / "notebooks" / nb, cat, sch, pre)
    fmt = dict(cat=cat, sch=sch, pre=pre, src_cat=src_cat, model=MODEL)
    (OUT / "databricks.yml").write_text(BUNDLE.format(**fmt))
    (OUT / "resources" / "dq_pipeline.yml").write_text(JOBS.format(**fmt))

    readme = (ROOT / "tools" / "production_README.md").read_text().format(
        **fmt, fn=f"{cat}.{sch}.{pre}fn_", tables="\n".join(f"* `{t}`" for t in tables),
        source_step=("" if src_cat == "prod" else
                     f"   * `04_source_catalog.sql` moves the register onto `{src_cat}`.\n"),
        sql_rows="\n".join(f"| `sql/{n}` | {w} |" for n, w, _ in sql))
    (OUT / "README.md").write_text(readme)

    for n, _, size in sql:
        print(f"  sql/{n:26} {size}")
    print(f"  jobs/run_checks.py, notebooks/03 + 06, databricks.yml, resources/dq_pipeline.yml")
    print(f"\nproduction/ rendered for {cat}.{sch} (prefix {pre}), sources in {src_cat}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

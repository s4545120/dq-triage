"""Unity Catalog implementation. Same function signatures as `local_source`.

Nothing here has ever run: this repo has had no workspace access, so treat every
query below as reviewed-but-unexecuted, the same status as `sql/ddl/`. The first
job with a workspace is to run these and diff the result against the fixture.

## What this module is permitted to write

Two statements, both `INSERT`:

  * `results.disposition` — one row per register event; and
  * `config.rule_registry` — a new row when a shadow rule is promoted to active.

There is no `UPDATE`, no `MERGE`, no `DELETE`, and no job trigger anywhere in this
file, and there is no code path that could construct one. That is not the guarantee
though — the guarantee is the grant. `sql/ddl/07_grants.sql` gives the app's service
principal `MODIFY` on exactly those two tables and nothing on any `prod.*` table,
and both are `delta.appendOnly = true`. A workspace admin can demonstrate the claim
from Unity Catalog alone, without reading this file. See `sql/README.md` for why
`MODIFY` rather than the spec's `INSERT`: Unity Catalog has no `INSERT` privilege.
"""

from __future__ import annotations

import contextlib
import os

import pandas as pd

DQ_CATALOG = os.getenv("DQ_CATALOG", "dq")

# Sandpit naming. The DDL assumes a catalog of its own with a `config` and a
# `results` schema; a sandpit gives you one schema in someone else's catalog, so
# `sql/render.py` folds the schema split into a name prefix. Set DQ_SCHEMA and the
# app reads the rendered layout instead:
#
#     DQ_SCHEMA unset   ->  dq.results.check_run
#     DQ_SCHEMA=udp_brnz ->  <catalog>.udp_brnz.dq_results_check_run
#
# This is the same substitution render.py performs, and it has to stay the same one.
# Change the prefix rule in one place and the app queries objects the DDL never
# created. Nothing else about the SQL differs between the two layouts.
DQ_SCHEMA = os.getenv("DQ_SCHEMA", "").strip()
DQ_PREFIX = os.getenv("DQ_PREFIX", "dq_")


def _t(schema: str, table: str) -> str:
    """Qualify one object for whichever of the two layouts is configured."""
    if not DQ_SCHEMA:
        return f"{DQ_CATALOG}.{schema}.{table}"
    return f"{DQ_CATALOG}.{DQ_SCHEMA}.{DQ_PREFIX}{schema}_{table}"


# --- Connection -------------------------------------------------------------
#
# Databricks Apps injects the app's own service principal credentials into the
# container, and the SDK's Config picks them up with no arguments. The warehouse is
# not discovered: it is attached to the app as a resource and surfaced under
# DATABRICKS_WAREHOUSE_ID by the `valueFrom` entry in app.yaml. An app with no
# warehouse attached fails here with a readable message, not a connection timeout.
#
# A fresh connection per statement, not a cached one. A warehouse drops idle
# sessions, and a module-level connection that has been dropped fails every query
# afterwards until the app restarts. Reads are wrapped in st.cache_data upstream, so
# the connect cost is paid rarely; correctness under an idle timeout is worth more.

WAREHOUSE_ID = os.getenv("DATABRICKS_WAREHOUSE_ID", "").strip()


@contextlib.contextmanager
def _cursor():
    """One cursor on the app's SQL warehouse, closed with its connection."""
    try:
        from databricks import sql as dbsql
        from databricks.sdk.core import Config
    except ImportError as exc:  # pragma: no cover — environment-dependent
        raise RuntimeError(
            "databricks-sql-connector and databricks-sdk are not installed. Add them "
            "to requirements.txt, or run with DQ_APP_DATA_SOURCE=local."
        ) from exc

    if not WAREHOUSE_ID:
        raise RuntimeError(
            "DATABRICKS_WAREHOUSE_ID is empty. Attach a SQL warehouse to the app as a "
            "resource, then map it in app.yaml with `valueFrom: <the resource key>`."
        )

    cfg = Config()
    with dbsql.connect(
        server_hostname=cfg.host,
        http_path=f"/sql/1.0/warehouses/{WAREHOUSE_ID}",
        credentials_provider=lambda: cfg.authenticate,
    ) as conn:
        with conn.cursor() as cur:
            yield cur


def _q(sql: str) -> pd.DataFrame:
    with _cursor() as cur:
        cur.execute(sql)
        return cur.fetchall_arrow().to_pandas()


def _exec(sql: str) -> None:
    """A statement with no result set. The two INSERTs at the foot of this file are
    the only callers, and the grant rather than this docstring is what keeps that
    true — see the module docstring."""
    with _cursor() as cur:
        cur.execute(sql)


def _lit(value) -> str:
    """SQL literal. Only ever used for values the app itself constructs — never
    for a user string, which goes through a parameter marker below."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


# --- Reads ------------------------------------------------------------------


def cohorts() -> pd.DataFrame:
    return _q(f"SELECT * FROM {_t('results', 'cohort')}")


def dispositions() -> pd.DataFrame:
    return _q(f"SELECT * FROM {_t('results', 'disposition')}")


def check_runs() -> pd.DataFrame:
    # 60 days: enough for the 30-day recurrence window plus the history the
    # per-rule sparklines draw. Widen this and the app pulls the whole table.
    return _q(
        f"""
        SELECT * FROM {_t('results', 'check_run')}
        WHERE run_ts >= current_timestamp() - INTERVAL 60 DAYS
        """
    )


def violation_samples() -> pd.DataFrame:
    return _q(
        f"""
        SELECT s.* FROM {_t('results', 'violation_sample')} s
        JOIN {_t('results', 'check_run')} r ON r.result_id = s.result_id
        WHERE r.run_ts >= current_timestamp() - INTERVAL 60 DAYS
        """
    )


def rule_registry() -> pd.DataFrame:
    # Full history, every version. The app derives `effective_to` the same way
    # v_rule_registry_current does — the registry is append-only and stores none.
    return _q(f"SELECT * FROM {_t('config', 'rule_registry')}")


def playbook() -> pd.DataFrame:
    return _q(f"SELECT * FROM {_t('config', 'playbook')}")


def cde_registry() -> pd.DataFrame:
    """Every version of every critical data element.

    The base table, not v_cde_registry_current, for the same reason rule_registry()
    reads the base table: the app derives current state itself so a rule promoted in
    this session is reflected immediately, and the CDE register is folded by the same
    code path. The view remains the definition — see domain/coverage.py.
    """
    return _q(f"SELECT * FROM {_t('config', 'cde_registry')}")


def cde_profile() -> pd.DataFrame:
    return _q(f"SELECT * FROM {_t('results', 'cde_profile')}")


# --- Writes -----------------------------------------------------------------

_DISPOSITION_COLUMNS = [
    "disposition_id", "cohort_id", "event_seq", "event_type", "event_ts", "ingest_ts",
    "actor_identity", "actor_display_name", "actor_source", "decision", "reason",
    "review_by_date", "approver_ordinal", "executed_summary", "external_ref",
    "executed_ts", "verifying_run_id", "verification_passed", "violations_before",
    "violations_after", "approach_type_taken", "playbook_id", "event_payload",
    "app_version",
]


def write_disposition(row: dict) -> None:
    """Append one register event.

    `INSERT` only, by construction and by grant. `event_seq` is computed by the
    caller from the events it just read, which races if two stewards act on the
    same cohort in the same second — the table tolerates that (gaps are acceptable,
    reuse is not, and a duplicate seq is caught by the integrity view rather than
    silently overwriting, because nothing here can overwrite).
    """
    cols = ", ".join(_DISPOSITION_COLUMNS)
    vals = ", ".join(_lit(row.get(c)) for c in _DISPOSITION_COLUMNS)
    _exec(f"INSERT INTO {_t('results', 'disposition')} ({cols}) VALUES ({vals})")


def promote_rule(row: dict) -> None:
    """Promote a shadow rule by appending a new version with status `active`.

    Not an `UPDATE` of the existing row: `config.rule_registry` is append-only and
    stores no `effective_to`, so history stays intact and the current version is
    derived at read time by `v_rule_registry_current`.
    """
    cols = ", ".join(row.keys())
    vals = ", ".join(_lit(v) for v in row.values())
    _exec(f"INSERT INTO {_t('config', 'rule_registry')} ({cols}) VALUES ({vals})")


def durable() -> bool:
    return True

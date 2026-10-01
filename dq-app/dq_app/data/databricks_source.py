"""Unity Catalog implementation. Same function signatures as `local_source`.

Executed, against `workspace.dq_triage` — the single-schema layout `sql/render.py`
renders, not the two-schema one `sql/ddl/` declares. The deployed app reads Unity
Catalog through this module, and `run-workspace.sh` points a laptop at the same
tables: reads work there, writes are refused. See the note on writes below.

The first real read is what put `_naive_timestamps` in this file. Unity Catalog hands
back tz-aware timestamps and the fixture's Parquet is naive, so the detail page's age
line raised `Cannot subtract tz-naive and tz-aware datetime-like objects` the first
time the adapter was ever run. Normalising here rather than on the page is the point
of having a seam — the fixture is what the tests are pinned to, and the two sources
have to stay interchangeable.

## What this module is permitted to write

Two statements, both `INSERT`:

  * `results.disposition` — one row per register event; and
  * `config.rule_registry` — a new row when a shadow rule is promoted to active.

There is no `UPDATE`, no `MERGE`, no `DELETE`, and no job trigger anywhere in this
file, and there is no code path that could construct one. (`data/notify.py` does
trigger a job, when `DQ_NOTIFY=job` — a mail sender that touches no table. It is
kept out of this module deliberately: what is permitted to write and what is
permitted to reach outside the container are two different questions.) That is not the guarantee
though — the guarantee is the grant. `sql/ddl/07_grants.sql` gives the app's service
principal `MODIFY` on exactly those two tables and nothing on any `prod.*` table,
and both are `delta.appendOnly = true`. A workspace admin can demonstrate the claim
from Unity Catalog alone, without reading this file. See `sql/README.md` for why
`MODIFY` rather than the spec's `INSERT`: Unity Catalog has no `INSERT` privilege.
"""

from __future__ import annotations

import contextlib
import os

import numpy as np
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
        return _naive_timestamps(cur.fetchall_arrow().to_pandas())


def _naive_timestamps(df: pd.DataFrame) -> pd.DataFrame:
    """Drop the timezone from every timestamp column, converting to UTC first.

    Unity Catalog hands back tz-aware timestamps; the fixture's parquet is tz-naive.
    Pandas refuses to subtract one from the other, so a page that works on the
    fixture raises `Cannot subtract tz-naive and tz-aware datetime-like objects` in
    workspace mode — which is what the detail page's `raised_ts` age line did the
    first time this adapter was ever run.

    Normalising here rather than in the pages is the point of having an adapter: the
    two sources must be interchangeable, and the fixture is the one with 80-odd
    tests pinned to it. TIMESTAMP in this DDL is UTC, so converting and dropping the
    tz loses nothing that was stored.
    """
    for col in df.columns:
        if isinstance(df[col].dtype, pd.DatetimeTZDtype):
            df[col] = df[col].dt.tz_convert("UTC").dt.tz_localize(None)
    return df


def _exec(sql: str) -> None:
    """A statement with no result set. The two INSERTs at the foot of this file are
    the only callers, and the grant rather than this docstring is what keeps that
    true — see the module docstring."""
    with _cursor() as cur:
        cur.execute(sql)


def _lit(value) -> str:
    """SQL literal. Only ever used for values the app itself constructs — never
    for a user string, which goes through a parameter marker below."""
    # Every pandas missing marker, not only None and float NaN: the register row sets
    # `executed_ts = pd.NaT` on every non-execution event, and str(pd.NaT) is 'NaT',
    # which the warehouse refuses to cast to TIMESTAMP. A row off `to_dict()` (as in
    # promote_rule) can carry pd.NA or numpy scalars for the same reason.
    if value is None or (pd.api.types.is_scalar(value) and pd.isna(value)):
        return "NULL"
    if isinstance(value, np.generic):
        value = value.item()
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


def confirm_disposition(disposition_id: str) -> bool:
    """Is that event actually in the register? One targeted read, no side effects.

    `write_disposition` returning without raising is good evidence the row landed,
    but it is not the row. This reads it back, and it exists so that the outbound
    notification in `data/notify.py` is derived from a row that was *observed* in
    the table rather than one the app believes it wrote. See that module for why
    the difference is worth a round trip.

    A `SELECT 1` on the primary key, so it costs a warehouse round trip and nothing
    else. False on any failure: a notification not sent is the safe direction.
    """
    try:
        found = _q(
            f"SELECT 1 AS ok FROM {_t('results', 'disposition')} "
            f"WHERE disposition_id = {_lit(disposition_id)} LIMIT 1"
        )
    except Exception:  # noqa: BLE001 — the write already succeeded; see notify.py.
        return False
    return not found.empty


def append_rule_version(row: dict) -> None:
    """A new version of a rule — a promotion, or an adopted threshold.

    Not an `UPDATE` of the existing row: `config.rule_registry` is append-only and
    stores no `effective_to`, so history stays intact and the current version is
    derived at read time by `v_rule_registry_current`.
    """
    cols = ", ".join(row.keys())
    vals = ", ".join(_lit(v) for v in row.values())
    _exec(f"INSERT INTO {_t('config', 'rule_registry')} ({cols}) VALUES ({vals})")


def promote_rule(row: dict) -> None:
    append_rule_version(row)


def threshold_proposals() -> pd.DataFrame:
    return _q(f"SELECT * FROM {_t('results', 'threshold_proposal')}")


def threshold_reviews() -> pd.DataFrame:
    return _q(f"SELECT * FROM {_t('results', 'threshold_review')}")


_THRESHOLD_REVIEW_COLUMNS = [
    "review_id", "proposal_id", "event_ts", "ingest_ts", "actor_identity",
    "actor_display_name", "actor_source", "decision", "reason", "review_by_date",
    "adopted_rule_version", "app_version",
]


def write_threshold_review(row: dict) -> None:
    """Append one reviewer decision. The app's third write; `INSERT` only, by
    construction and by grant (07_grants.sql)."""
    cols = ", ".join(_THRESHOLD_REVIEW_COLUMNS)
    vals = ", ".join(_lit(row.get(c)) for c in _THRESHOLD_REVIEW_COLUMNS)
    _exec(f"INSERT INTO {_t('results', 'threshold_review')} ({cols}) VALUES ({vals})")


def durable() -> bool:
    return True

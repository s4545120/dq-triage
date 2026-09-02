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

import functools
import os

import pandas as pd

DQ_CATALOG = os.getenv("DQ_CATALOG", "dq")


@functools.lru_cache(maxsize=1)
def _session():
    """Lazily built, so importing this module never fails on a machine with no
    credentials — the local source has to stay usable regardless."""
    try:
        from databricks.connect import DatabricksSession
    except ImportError as exc:  # pragma: no cover — environment-dependent
        raise RuntimeError(
            "databricks-connect is not installed. Add it to requirements.txt and "
            "pip install, or run with DQ_APP_DATA_SOURCE=local."
        ) from exc
    return DatabricksSession.builder.serverless().getOrCreate()


def _q(sql: str) -> pd.DataFrame:
    return _session().sql(sql).toPandas()


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
    return _q(f"SELECT * FROM {DQ_CATALOG}.results.cohort")


def dispositions() -> pd.DataFrame:
    return _q(f"SELECT * FROM {DQ_CATALOG}.results.disposition")


def check_runs() -> pd.DataFrame:
    # 60 days: enough for the 30-day recurrence window plus the history the
    # per-rule sparklines draw. Widen this and the app pulls the whole table.
    return _q(
        f"""
        SELECT * FROM {DQ_CATALOG}.results.check_run
        WHERE run_ts >= current_timestamp() - INTERVAL 60 DAYS
        """
    )


def violation_samples() -> pd.DataFrame:
    return _q(
        f"""
        SELECT s.* FROM {DQ_CATALOG}.results.violation_sample s
        JOIN {DQ_CATALOG}.results.check_run r ON r.result_id = s.result_id
        WHERE r.run_ts >= current_timestamp() - INTERVAL 60 DAYS
        """
    )


def rule_registry() -> pd.DataFrame:
    # Full history, every version. The app derives `effective_to` the same way
    # v_rule_registry_current does — the registry is append-only and stores none.
    return _q(f"SELECT * FROM {DQ_CATALOG}.config.rule_registry")


def playbook() -> pd.DataFrame:
    return _q(f"SELECT * FROM {DQ_CATALOG}.config.playbook")


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
    _session().sql(f"INSERT INTO {DQ_CATALOG}.results.disposition ({cols}) VALUES ({vals})")


def promote_rule(row: dict) -> None:
    """Promote a shadow rule by appending a new version with status `active`.

    Not an `UPDATE` of the existing row: `config.rule_registry` is append-only and
    stores no `effective_to`, so history stays intact and the current version is
    derived at read time by `v_rule_registry_current`.
    """
    cols = ", ".join(row.keys())
    vals = ", ".join(_lit(v) for v in row.values())
    _session().sql(f"INSERT INTO {DQ_CATALOG}.config.rule_registry ({cols}) VALUES ({vals})")


def durable() -> bool:
    return True

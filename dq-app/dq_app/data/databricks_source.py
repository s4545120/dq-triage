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
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor

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


_CFG = None
_CFG_LOCK = threading.Lock()


def _config(Config):
    """One SDK Config for the process. Building one per query re-ran authentication
    every time -- from a laptop that is a `databricks auth token` subprocess per query,
    and a page probing a dozen tables at once had those subprocesses race for the OS
    keyring and fail. The SDK refreshes the token inside one Config on its own."""
    global _CFG
    with _CFG_LOCK:
        if _CFG is None:
            _CFG = Config()
        return _CFG


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

    cfg = _config(Config)
    with dbsql.connect(
        server_hostname=cfg.host,
        http_path=f"/sql/1.0/warehouses/{WAREHOUSE_ID}",
        credentials_provider=lambda: cfg.authenticate,
    ) as conn:
        with conn.cursor() as cur:
            yield cur


def _q(sql: str, params: dict | None = None) -> pd.DataFrame:
    with _cursor() as cur:
        cur.execute(sql, params)
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


def _param(value):
    """One bound parameter value. Every pandas missing marker becomes None, and numpy
    scalars and pandas timestamps become the plain Python types the connector binds."""
    if value is None or (pd.api.types.is_scalar(value) and pd.isna(value)):
        return None
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    return value


def _guarded_insert(table: str, row: dict, columns: list[str], guard: str,
                    guard_params: dict, readback: dict) -> bool:
    """Append `row` only if `guard` holds, then read it back. True if it landed.

    The write is decided against the table as it stands, not against the cached read
    the caller validated on. `adapter` computes `event_seq` / `rule_version` from a
    read that can be up to five minutes old, and a second steward may have acted
    since: appending blind would put two events at one `event_seq`, or two rows at
    one `rule_version`, and the append-only table could never take either back. So
    the INSERT selects its own values `WHERE <guard>` — the guard says "nothing has
    been appended here since I looked" — and a refused write appends nothing.

    Every value is a bound parameter. This is the path free text reaches (a review's
    `reason`, a promotion's `note`), and quote-doubling is not escaping on Databricks:
    its string literals honour backslash escapes, so a reason ending `\\` turned the
    doubled quote that followed it back into a string terminator.

    What is left is a window of one statement, not five minutes. Under Delta's default
    WriteSerializable isolation, two appends whose guards were both evaluated before
    either committed can both land. `delta.isolationLevel = 'Serializable'` on the
    three written tables should make the second fail instead, since this INSERT reads
    its own table; that is not set, and not yet tested on a warehouse.
    """
    # An array column cannot be bound: the connector refuses a Python list ("Could not
    # infer parameter type"), which is how selecting a table first failed on the
    # deployed app -- `row_key` is ARRAY<STRING>. It travels as JSON text and is turned
    # back into an array inside the INSERT, so it is still a bound value, never SQL.
    arrays = {i for i, c in enumerate(columns)
              if isinstance(row.get(c), (list, tuple, np.ndarray))}
    params = {f"v{i}": (json.dumps([str(x) for x in row.get(c)]) if i in arrays
                        else _param(row.get(c)))
              for i, c in enumerate(columns)}
    params.update({f"g_{k}": _param(v) for k, v in guard_params.items()})
    select = ", ".join(f"from_json(:v{i}, 'array<string>')" if i in arrays else f":v{i}"
                       for i in range(len(columns)))
    with _cursor() as cur:
        cur.execute(
            f"INSERT INTO {table} ({', '.join(columns)}) "
            f"SELECT {select} WHERE {guard}",
            params,
        )
        where = " AND ".join(f"{k} = :r_{k}" for k in readback)
        cur.execute(f"SELECT 1 AS ok FROM {table} WHERE {where} LIMIT 1",
                    {f"r_{k}": _param(v) for k, v in readback.items()})
        return bool(cur.fetchall())


def write_disposition(row: dict) -> bool:
    """Append one register event, unless the cohort has moved on since the caller read it.

    `INSERT` only, by construction and by grant. `event_seq` is computed by the
    caller from the events it read; the guard refuses the row if any event on the
    cohort already sits at or above that sequence. False means nothing was written.
    """
    table = _t("results", "disposition")
    return _guarded_insert(
        table, row, _DISPOSITION_COLUMNS,
        guard=(f"NOT EXISTS (SELECT 1 FROM {table} "
               "WHERE cohort_id = :g_cohort_id AND event_seq >= :g_event_seq)"),
        guard_params={"cohort_id": row["cohort_id"], "event_seq": row["event_seq"]},
        readback={"disposition_id": row["disposition_id"]},
    )


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
            "WHERE disposition_id = :disposition_id LIMIT 1",
            {"disposition_id": disposition_id},
        )
    except Exception:  # noqa: BLE001 — the write already succeeded; see notify.py.
        return False
    return not found.empty


def append_rule_version(row: dict) -> bool:
    """A new version of a rule — a promotion, or an adopted threshold.

    Not an `UPDATE` of the existing row: `config.rule_registry` is append-only and
    stores no `effective_to`, so history stays intact and the current version is
    derived at read time by `v_rule_registry_current`. Refused (False) if the rule
    already has a version at or above this one — someone else changed it since.
    """
    table = _t("config", "rule_registry")
    return _guarded_insert(
        table, row, list(row.keys()),
        guard=(f"NOT EXISTS (SELECT 1 FROM {table} "
               "WHERE rule_id = :g_rule_id AND rule_version >= :g_rule_version)"),
        guard_params={"rule_id": row["rule_id"], "rule_version": row["rule_version"]},
        readback={"rule_id": row["rule_id"], "rule_version": row["rule_version"],
                  "created_by": row["created_by"]},
    )


def append_rule_versions(rows: list[dict]) -> set[str]:
    """Several new rule versions in ONE statement, each under `append_rule_version`'s
    guard. Returns the rule_ids that landed, read back rather than assumed.

    The rows ride in a VALUES list and the guard is evaluated per row against the table
    as it stands, so a rule someone changed since the page was read is left out while
    the rest land. Every value is still a bound parameter.
    """
    if not rows:
        return set()
    table = _t("config", "rule_registry")
    cols = list(rows[0].keys())
    params, tuples = {}, []
    for i, row in enumerate(rows):
        names = []
        for j, c in enumerate(cols):
            params[f"r{i}c{j}"] = _param(row.get(c))
            names.append(f":r{i}c{j}")
        tuples.append("(" + ", ".join(names) + ")")
    collist = ", ".join(cols)
    with _cursor() as cur:
        cur.execute(
            f"INSERT INTO {table} ({collist}) "
            f"SELECT {collist} FROM (VALUES {', '.join(tuples)}) AS v({collist}) "
            f"WHERE NOT EXISTS (SELECT 1 FROM {table} x "
            "WHERE x.rule_id = v.rule_id AND x.rule_version >= v.rule_version)",
            params,
        )
        ids = {f"q{i}": r["rule_id"] for i, r in enumerate(rows)}
        cur.execute(
            f"SELECT rule_id, rule_version, created_by FROM {table} "
            f"WHERE rule_id IN ({', '.join(':' + k for k in ids)})", ids)
        seen = {(r[0], int(r[1]), r[2]) for r in cur.fetchall()}
    return {r["rule_id"] for r in rows
            if (r["rule_id"], int(r["rule_version"]), r["created_by"]) in seen}


def promote_rule(row: dict) -> bool:
    return append_rule_version(row)


def _q_optional(table: str, columns: list[str]) -> pd.DataFrame:
    """A table this catalog may not have yet. The onboarding tables exist only where
    onboarding has been set up (the dq_onboard test schema today), and a missing table
    means nothing is being onboarded -- not an error to put in front of a reader."""
    try:
        return _q(f"SELECT * FROM {table}")
    except Exception as exc:  # noqa: BLE001 -- only a missing table is swallowed
        if "TABLE_OR_VIEW_NOT_FOUND" not in str(exc):
            raise
        return pd.DataFrame({c: pd.Series(dtype="object") for c in columns})


def monitored_tables() -> pd.DataFrame:
    from dq_app.domain.onboarding import MONITORED_COLUMNS
    return _q_optional(_t("config", "monitored_table"), MONITORED_COLUMNS)


def binding_proposals() -> pd.DataFrame:
    from dq_app.domain.onboarding import PROPOSAL_COLUMNS
    return _q_optional(_t("config", "binding_proposal"), PROPOSAL_COLUMNS)


def binding_reviews() -> pd.DataFrame:
    from dq_app.domain.onboarding import REVIEW_COLUMNS
    return _q_optional(_t("config", "binding_review"), REVIEW_COLUMNS)


def check_templates() -> pd.DataFrame:
    return _q_optional(_t("config", "check_template"),
                       ["template_id", "template_version", "data_class", "check_code", "title"])


# --- Onboarding: browsing Unity Catalog -------------------------------------------------
# Through system.information_schema, which lists only what the querying principal may
# see. Today that principal is the app's service principal; browsing as the signed-in
# user needs the app's user-authorization scope and the user's token on this cursor.

def _ident(fqn: str) -> str:
    """catalog.schema.table as a quoted identifier. The parts come from
    information_schema, but they are quoted anyway: a backtick in a name is legal."""
    parts = fqn.split(".")
    if len(parts) != 3 or not all(parts):
        raise ValueError(f"not a three-part table name: {fqn!r}")
    return ".".join("`" + p.replace("`", "``") + "`" for p in parts)


def catalog_tables() -> pd.DataFrame:
    df = _q("""
        SELECT table_catalog, table_schema, table_name, table_type, table_owner
        FROM   system.information_schema.tables
        WHERE  table_schema <> 'information_schema' AND table_catalog <> 'system'""")
    df["size_bytes"] = None
    df["readable"] = None
    return df


def catalog_columns(fqn: str | None = None) -> pd.DataFrame:
    """Columns of one table (`catalog.schema.table`) or of every table in one schema
    (`catalog.schema`) -- the second is how the table list gets column and tag counts
    for every row in one statement."""
    where, params = "", None
    if fqn:
        parts = fqn.split(".")
        where = "WHERE c.table_catalog = :c AND c.table_schema = :s"
        params = {"c": parts[0], "s": parts[1]}
        if len(parts) == 3:
            where += " AND c.table_name = :t"
            params["t"] = parts[2]
    return _q(f"""
        SELECT c.table_catalog, c.table_schema, c.table_name, c.column_name,
               c.data_type, c.ordinal_position, g.tag_value AS tag_cde
        FROM   system.information_schema.columns c
        LEFT JOIN system.information_schema.column_tags g
               ON  g.catalog_name = c.table_catalog AND g.schema_name = c.table_schema
               AND g.table_name = c.table_name AND g.column_name = c.column_name
               AND g.tag_name = 'cde'
        {where}
        ORDER  BY c.table_catalog, c.table_schema, c.table_name, c.ordinal_position""",
        params)


def table_probe(fqn: str) -> dict:
    """Size, and whether this principal can read it. Two cheap statements: DESCRIBE
    DETAIL reads the Delta log, and a LIMIT 0 select plans without scanning."""
    out = {"size_bytes": None, "readable": False}
    ident = _ident(fqn)
    try:
        d = _q(f"DESCRIBE DETAIL {ident}")
        if len(d) and "sizeInBytes" in d:
            out["size_bytes"] = _param(d.iloc[0]["sizeInBytes"])
    except Exception:  # noqa: BLE001 -- a view has no detail; size stays unknown
        pass
    try:
        _q(f"SELECT 1 FROM {ident} LIMIT 0")
        out["readable"] = True
    except Exception:  # noqa: BLE001 -- not readable is the answer, not an error
        pass
    return out


_GRANTED = "(p.grantee = current_user() OR is_account_group_member(p.grantee))"


def readable_tables(catalog: str, schema: str) -> set[str]:
    """Every table in one schema this principal can SELECT, in ONE statement.

    Read from the privilege views rather than by trying a SELECT on each table: the
    per-table probe was two statements a table on a fresh connection each, and a
    dozen-table schema took a minute to list. Owner, a table grant, or SELECT inherited
    from the schema or catalog -- directly or through a group. `select_table` still
    makes the exact per-table check at the moment a table is submitted.
    """
    df = _q(f"""
        SELECT t.table_name FROM system.information_schema.tables t
        WHERE t.table_catalog = :c AND t.table_schema = :s AND (
          t.table_owner = current_user() OR is_account_group_member(t.table_owner)
          OR EXISTS (SELECT 1 FROM system.information_schema.table_privileges p
                     WHERE p.table_catalog = t.table_catalog AND p.table_schema = t.table_schema
                       AND p.table_name = t.table_name
                       AND p.privilege_type IN ('SELECT', 'ALL PRIVILEGES') AND {_GRANTED})
          OR EXISTS (SELECT 1 FROM system.information_schema.schema_privileges p
                     WHERE p.catalog_name = t.table_catalog AND p.schema_name = t.table_schema
                       AND p.privilege_type IN ('SELECT', 'ALL PRIVILEGES') AND {_GRANTED})
          OR EXISTS (SELECT 1 FROM system.information_schema.catalog_privileges p
                     WHERE p.catalog_name = t.table_catalog
                       AND p.privilege_type IN ('SELECT', 'ALL PRIVILEGES') AND {_GRANTED}))""",
        {"c": catalog, "s": schema})
    return set(df["table_name"]) if len(df) else set()


def _sizes_on_one_connection(fqns: list[str]) -> dict[str, float | None]:
    out = {}
    with _cursor() as cur:
        for fqn in fqns:
            try:
                cur.execute(f"DESCRIBE DETAIL {_ident(fqn)}")
                cols = [d[0] for d in cur.description]
                row = cur.fetchone()
                size = row[cols.index("sizeInBytes")] if row and "sizeInBytes" in cols else None
                out[fqn] = float(size) if size is not None else None
            except Exception:  # noqa: BLE001 -- a view has no size; that is the answer
                out[fqn] = None
    return out


def table_sizes(fqns: tuple[str, ...], workers: int = 4) -> dict[str, float | None]:
    """Delta size of each table: one DESCRIBE DETAIL apiece, but on a few connections
    reused across the batch rather than a new one per statement -- opening the
    connection, not the statement, was most of each probe's cost."""
    fqns = list(fqns)
    if not fqns:
        return {}
    n = min(workers, len(fqns))
    chunks = [fqns[i::n] for i in range(n)]
    out: dict[str, float | None] = {}
    with ThreadPoolExecutor(max_workers=n) as pool:
        for part in pool.map(_sizes_on_one_connection, chunks):
            out.update(part)
    return out


# --- Onboarding: three appends -----------------------------------------------------------

def write_monitored_table(row: dict) -> bool:
    """Select (or re-version) a table. Refused if a version at or above this exists."""
    table = _t("config", "monitored_table")
    return _guarded_insert(
        table, row, list(row.keys()),
        guard=(f"NOT EXISTS (SELECT 1 FROM {table} WHERE target_table = :g_target_table "
               "AND table_version >= :g_table_version)"),
        guard_params={"target_table": row["target_table"],
                      "table_version": row["table_version"]},
        readback={"target_table": row["target_table"], "table_version": row["table_version"]},
    )


def write_binding_proposal(row: dict) -> bool:
    """A person's suggested binding. Lands in the same queue as the discovery job's."""
    table = _t("config", "binding_proposal")
    return _guarded_insert(
        table, row, list(row.keys()),
        guard=f"NOT EXISTS (SELECT 1 FROM {table} WHERE proposal_id = :g_proposal_id)",
        guard_params={"proposal_id": row["proposal_id"]},
        readback={"proposal_id": row["proposal_id"]},
    )


def write_binding_review(row: dict) -> bool:
    """One decision per proposal. Refused if the proposal already has one."""
    table = _t("config", "binding_review")
    return _guarded_insert(
        table, row, list(row.keys()),
        guard=f"NOT EXISTS (SELECT 1 FROM {table} WHERE proposal_id = :g_proposal_id)",
        guard_params={"proposal_id": row["proposal_id"]},
        readback={"proposal_id": row["proposal_id"], "reviewed_by": row["reviewed_by"]},
    )


def threshold_proposals() -> pd.DataFrame:
    return _q(f"SELECT * FROM {_t('results', 'threshold_proposal')}")


def threshold_reviews() -> pd.DataFrame:
    return _q(f"SELECT * FROM {_t('results', 'threshold_review')}")


_THRESHOLD_REVIEW_COLUMNS = [
    "review_id", "proposal_id", "event_ts", "ingest_ts", "actor_identity",
    "actor_display_name", "actor_source", "decision", "reason", "review_by_date",
    "adopted_rule_version", "app_version",
]


def write_threshold_review(row: dict, *, reviews_seen: int) -> bool:
    """Append one reviewer decision. The app's third write; `INSERT` only, by
    construction and by grant (07_grants.sql). Refused (False) if the proposal has
    gained a review since the caller counted `reviews_seen` of them."""
    table = _t("results", "threshold_review")
    return _guarded_insert(
        table, row, _THRESHOLD_REVIEW_COLUMNS,
        guard=(f"(SELECT count(*) FROM {table} "
               "WHERE proposal_id = :g_proposal_id) = :g_reviews_seen"),
        guard_params={"proposal_id": row["proposal_id"], "reviews_seen": reviews_seen},
        readback={"review_id": row["review_id"]},
    )


def durable() -> bool:
    return True

"""Warehouse access for the onboarding test, and the names of everything it touches.

The test lives in its own schema, `workspace.dq_onboard` (and `use_schema` points the
same code at `dq_triage`, where onboarding runs for real since 2026-10-06), laid out the way sql/render.py
lays out the sandpit (`dq_<group>_<table>`), so jobs/run_checks.py can run against it
with `--schema dq_onboard`. Nothing here reads from or writes to `dq_triage` except the
one-time clone in `onboard.py setup`. Dropping the schema resets the test.
"""

from __future__ import annotations

import os

PROFILE = "dbc-19c77b90-423e"
WAREHOUSE = "ebf2cf6b81ca710b"
CATALOG, SCHEMA, PREFIX = "workspace", "dq_onboard", "dq_"
SOURCE_SCHEMA = "dq_triage"
TEST_SCHEMA = SCHEMA


def use_schema(name: str) -> None:
    """Point every name built here at another schema -- `onboard.py --schema dq_triage`.
    Read at call time by t() and src(), so it must run before the first statement."""
    global SCHEMA
    SCHEMA = name

# Rules in the registry call the shared helpers by their resolved sandpit name. The
# onboarding schema reuses dq_triage's functions rather than cloning them, so a
# template instantiated here calls exactly what the registered rules call.
FN_RESOLVED = f"{CATALOG}.{SOURCE_SCHEMA}.{PREFIX}fn_"


def t(group: str, name: str, schema: str | None = None) -> str:
    return f"{CATALOG}.{schema or SCHEMA}.{PREFIX}{group}_{name}"


def src(name: str) -> str:
    """A source table the test onboards. `src` is not a group in the triage layout; it
    marks a table that stands in for a business system."""
    return f"{CATALOG}.{SCHEMA}.{PREFIX}src_{name}"


def in_databricks() -> bool:
    return bool(os.getenv("DATABRICKS_RUNTIME_VERSION"))


class _SparkConn:
    """Inside a Lakeflow task there is no CLI profile, and no need for one: the same
    statements run through the task's own Spark session."""

    def __init__(self):
        from pyspark.sql import SparkSession
        self.spark = SparkSession.builder.getOrCreate()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def connect():
    if in_databricks():
        return _SparkConn()
    from databricks import sql as dbsql
    from databricks.sdk.core import Config

    cfg = Config(profile=PROFILE)
    return dbsql.connect(server_hostname=cfg.host.replace("https://", ""),
                         http_path=f"/sql/1.0/warehouses/{WAREHOUSE}",
                         credentials_provider=lambda: cfg.authenticate)


def run(conn, sql: str) -> list[dict]:
    if isinstance(conn, _SparkConn):
        return [r.asDict() for r in conn.spark.sql(sql).collect()]
    with conn.cursor() as cur:
        cur.execute(sql)
        if cur.description is None:
            return []
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def lit(v) -> str:
    """A SQL literal. Only for values this package generates or reads from the registry."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'"

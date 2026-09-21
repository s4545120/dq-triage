"""The Unity Catalog adapter's pure parts.

Everything else in `databricks_source` needs a warehouse. These do not, and they
cover the seam where the two sources have to agree: the fixture is what 80-odd tests
are pinned to, so anything Unity Catalog hands back differently has to be reshaped
here rather than in the pages.
"""

from __future__ import annotations

import pandas as pd

from dq_app.data import databricks_source as src


def test_timestamps_come_back_naive_like_the_fixture():
    """Unity Catalog returns tz-aware timestamps and the fixture's parquet is naive.
    Pandas refuses to subtract one from the other, so the detail page's `raised_ts`
    age line raised `Cannot subtract tz-naive and tz-aware datetime-like objects`
    the first time this adapter was run against a workspace."""
    aware = pd.DataFrame({
        "raised_ts": pd.to_datetime(["2026-08-28 03:00:00"]).tz_localize("UTC"),
        "cohort_id": ["x"],
    })
    out = src._naive_timestamps(aware)

    assert out["raised_ts"].dt.tz is None
    # The thing the page actually does.
    assert (pd.Timestamp.now() - out["raised_ts"].iloc[0]).days >= 0


def test_a_non_utc_timestamp_is_converted_not_just_stripped():
    """Dropping the offset without converting would move the reading by hours and
    quietly change an MTTR. TIMESTAMP in this DDL is UTC."""
    df = pd.DataFrame({"ts": pd.to_datetime(["2026-08-28 13:00:00"]).tz_localize("Australia/Sydney")})
    out = src._naive_timestamps(df)
    assert out["ts"].iloc[0] == pd.Timestamp("2026-08-28 03:00:00")


def test_naive_input_is_left_alone():
    """Local mode never reaches this, but a mixed frame must not be mangled."""
    df = pd.DataFrame({"ts": pd.to_datetime(["2026-08-28 03:00:00"]), "n": [1]})
    out = src._naive_timestamps(df.copy())
    assert out["ts"].iloc[0] == pd.Timestamp("2026-08-28 03:00:00")
    assert out["n"].iloc[0] == 1


def test_the_sandpit_layout_matches_what_render_py_produces():
    """`_t` performs the same rewrite as sql/render.py. Change one and the app
    queries objects the DDL never created."""
    import importlib

    import os
    os.environ["DQ_CATALOG"] = "workspace"
    os.environ["DQ_SCHEMA"] = "dq_triage"
    os.environ["DQ_PREFIX"] = "dq_"
    mod = importlib.reload(src)
    try:
        assert mod._t("results", "cohort") == "workspace.dq_triage.dq_results_cohort"
        assert mod._t("config", "rule_registry") == "workspace.dq_triage.dq_config_rule_registry"
    finally:
        for k in ("DQ_CATALOG", "DQ_SCHEMA", "DQ_PREFIX"):
            os.environ.pop(k, None)
        importlib.reload(src)

"""Shared fixtures. The tests read the generated Parquet directly rather than going
through the adapter, so they need no Streamlit runtime and no session state."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FIXTURE_DIR = ROOT.parent / "fixtures" / "out"


def _load(name: str) -> pd.DataFrame:
    path = FIXTURE_DIR / f"{name}.parquet"
    if not path.exists():
        pytest.skip(f"fixture not built: {path} — run fixtures/build_fixtures.py")
    return pd.read_parquet(path)


@pytest.fixture(scope="session")
def cohorts():
    return _load("results.cohort")


@pytest.fixture(scope="session")
def dispositions():
    return _load("results.disposition")


@pytest.fixture(scope="session")
def shipped_view():
    return _load("results.v_cohort_current")


@pytest.fixture(scope="session")
def check_runs():
    return _load("results.check_run")

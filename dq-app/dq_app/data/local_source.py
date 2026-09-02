"""Reads the local fixture — `fixtures/out/*.parquet` — with no workspace at all.

This is the source the app runs on today. The fixture is a complete `dq.*` dataset
built from the two pilot CSVs by `fixtures/build_fixtures.py`: real violation counts,
real bad rows in `violation_sample`, 40 back-projected daily runs, 14 cohorts and a
65-event register. See `fixtures/README.md` for exactly which parts are measured and
which are synthesised — the distinction matters before quoting any number from here.

## Writes go to session state, never to the parquet

`fixtures/out/` is generated output, gated by `fixtures/verify.py`, and hand-editing
it would break the one thing it is for. So a review or approval recorded in the app
is appended to `st.session_state` and lives as long as the browser tab. The register
still behaves correctly — append-only, monotonic `event_seq`, derived state — it
simply does not survive a restart, and the UI says so rather than implying a durable
write that did not happen.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import streamlit as st

_PENDING_KEY = "_pending_disposition_events"
_PENDING_RULES_KEY = "_pending_rule_versions"


def fixture_dir() -> Path:
    """`DQ_FIXTURE_DIR`, else `fixtures/out` beside the repo's dq-app/ directory."""
    env = os.getenv("DQ_FIXTURE_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return (Path(__file__).resolve().parents[3] / "fixtures" / "out").resolve()


def _read(table: str) -> pd.DataFrame:
    path = fixture_dir() / f"{table}.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"No fixture at {path}.\n\n"
            "Build it first:\n"
            "    cd fixtures && ../.venv/bin/python build_fixtures.py\n"
            "or point DQ_FIXTURE_DIR at an existing out/ directory."
        )
    return pd.read_parquet(path)


# --- Reads ------------------------------------------------------------------


def cohorts() -> pd.DataFrame:
    return _read("results.cohort")


def dispositions() -> pd.DataFrame:
    """The register as generated. Session-recorded events are layered on by the
    adapter, not here, so this stays cacheable."""
    return _read("results.disposition")


def check_runs() -> pd.DataFrame:
    return _read("results.check_run")


def violation_samples() -> pd.DataFrame:
    return _read("results.violation_sample")


def rule_registry() -> pd.DataFrame:
    return _read("config.rule_registry")


def playbook() -> pd.DataFrame:
    return _read("config.playbook")


# --- Writes -----------------------------------------------------------------


def write_disposition(row: dict) -> None:
    st.session_state.setdefault(_PENDING_KEY, []).append(row)


def promote_rule(row: dict) -> None:
    st.session_state.setdefault(_PENDING_RULES_KEY, []).append(row)


def pending_events() -> list[dict]:
    return list(st.session_state.get(_PENDING_KEY, []))


def pending_rules() -> list[dict]:
    return list(st.session_state.get(_PENDING_RULES_KEY, []))


def discard_pending() -> None:
    st.session_state[_PENDING_KEY] = []
    st.session_state[_PENDING_RULES_KEY] = []


def durable() -> bool:
    """False — writes here are session-scoped. The UI uses this to label them."""
    return False

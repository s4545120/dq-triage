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
_PENDING_REVIEWS_KEY = "_pending_threshold_reviews"
_PENDING_ONB = {"monitored": "_pending_monitored_tables",
                "proposal": "_pending_binding_proposals",
                "review": "_pending_binding_reviews"}


# Deployed, only `dq-app/` is shipped — the app source path is the folder holding
# app.yaml, and `fixtures/` sits above it and is gitignored besides. So the app also
# carries its own copy of the fixture inside the package. The bundled-fixture test
# fails if that copy has drifted from `fixtures/out/`.
_BUNDLED = Path(__file__).resolve().parents[1] / "fixture_data"


def fixture_dir() -> Path:
    """`DQ_FIXTURE_DIR`, else `fixtures/out` above the repo's dq-app/ directory, else
    the copy bundled in the package — which is what a deployed app reads."""
    env = os.getenv("DQ_FIXTURE_DIR")
    if env:
        return Path(env).expanduser().resolve()
    repo = (Path(__file__).resolve().parents[3] / "fixtures" / "out").resolve()
    if repo.is_dir():
        return repo
    return _BUNDLED.resolve()


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


def cde_registry() -> pd.DataFrame:
    return _read("config.cde_registry")


def cde_profile() -> pd.DataFrame:
    return _read("results.cde_profile")


def threshold_proposals() -> pd.DataFrame:
    return _read("results.threshold_proposal")


def _read_optional(table: str, columns: list[str]) -> pd.DataFrame:
    """A table the fixture does not carry reads as empty, with its columns."""
    try:
        return _read(table)
    except FileNotFoundError:
        return pd.DataFrame({c: pd.Series(dtype="object") for c in columns})


def monitored_tables() -> pd.DataFrame:
    from dq_app.domain.onboarding import MONITORED_COLUMNS
    return _read_optional("config.monitored_table", MONITORED_COLUMNS)


def binding_proposals() -> pd.DataFrame:
    from dq_app.domain.onboarding import PROPOSAL_COLUMNS
    return _read_optional("config.binding_proposal", PROPOSAL_COLUMNS)


def binding_reviews() -> pd.DataFrame:
    from dq_app.domain.onboarding import REVIEW_COLUMNS
    return _read_optional("config.binding_review", REVIEW_COLUMNS)


def check_templates() -> pd.DataFrame:
    return _read_optional("config.check_template",
                          ["template_id", "template_version", "data_class", "check_code", "title"])


def threshold_reviews() -> pd.DataFrame:
    """As generated. Session-recorded reviews are layered on by the adapter."""
    return _read("results.threshold_review")


# --- Writes -----------------------------------------------------------------


def write_disposition(row: dict) -> bool:
    """Append, unless the cohort already has an event at or above this `event_seq`.
    The same guard `databricks_source` puts in its INSERT, so a test can drive the
    refusal without a warehouse. False means nothing was appended."""
    seqs = [e["event_seq"] for e in pending_events() if e["cohort_id"] == row["cohort_id"]]
    base = dispositions()
    seqs += base.loc[base["cohort_id"] == row["cohort_id"], "event_seq"].tolist()
    if any(s >= row["event_seq"] for s in seqs):
        return False
    st.session_state.setdefault(_PENDING_KEY, []).append(row)
    return True


def append_rule_version(row: dict) -> bool:
    """A new version of a rule: a promotion, or an adopted threshold. The same
    append either way, which is the point of the registry being append-only.
    Refused if the rule already has a version at or above this one."""
    versions = [r["rule_version"] for r in pending_rules() if r["rule_id"] == row["rule_id"]]
    base = rule_registry()
    versions += base.loc[base["rule_id"] == row["rule_id"], "rule_version"].tolist()
    if any(v >= row["rule_version"] for v in versions):
        return False
    st.session_state.setdefault(_PENDING_RULES_KEY, []).append(row)
    return True


def append_rule_versions(rows: list[dict]) -> set[str]:
    """Each row under the same guard as `append_rule_version`; the ids that landed."""
    return {r["rule_id"] for r in rows if append_rule_version(r)}


def promote_rule(row: dict) -> bool:
    return append_rule_version(row)


def write_threshold_review(row: dict, *, reviews_seen: int) -> bool:
    """Refused if the proposal has gained a review since the caller counted them."""
    base = threshold_reviews()
    count = int((base["proposal_id"] == row["proposal_id"]).sum()) + sum(
        1 for r in pending_threshold_reviews() if r["proposal_id"] == row["proposal_id"])
    if count != reviews_seen:
        return False
    st.session_state.setdefault(_PENDING_REVIEWS_KEY, []).append(row)
    return True


def pending_events() -> list[dict]:
    return list(st.session_state.get(_PENDING_KEY, []))


def pending_rules() -> list[dict]:
    return list(st.session_state.get(_PENDING_RULES_KEY, []))


def pending_threshold_reviews() -> list[dict]:
    return list(st.session_state.get(_PENDING_REVIEWS_KEY, []))


# --- Onboarding: the catalog, and three session-only writes ----------------------------
# The fixture has no Unity Catalog. A test that needs one writes `catalog.tables` and
# `catalog.columns` parquet beside the fixture; without them the picker is empty.

_CATALOG_TABLE_COLUMNS = ["table_catalog", "table_schema", "table_name", "table_type",
                          "table_owner", "size_bytes", "readable"]
_CATALOG_COLUMN_COLUMNS = ["table_catalog", "table_schema", "table_name", "column_name",
                           "data_type", "ordinal_position", "tag_cde"]


def catalog_tables() -> pd.DataFrame:
    return _read_optional("catalog.tables", _CATALOG_TABLE_COLUMNS)


def catalog_columns(fqn: str | None = None) -> pd.DataFrame:
    df = _read_optional("catalog.columns", _CATALOG_COLUMN_COLUMNS)
    if fqn and len(df):
        parts = fqn.split(".")
        df = df[(df["table_catalog"] == parts[0]) & (df["table_schema"] == parts[1])]
        if len(parts) == 3:
            df = df[df["table_name"] == parts[2]]
    return df.sort_values("ordinal_position") if len(df) else df


def readable_tables(catalog: str, schema: str) -> set[str]:
    t = catalog_tables()
    if t.empty:
        return set()
    t = t[(t["table_catalog"] == catalog) & (t["table_schema"] == schema)]
    return set(t.loc[t["readable"].astype(bool), "table_name"])


def table_sizes(fqns: tuple[str, ...]) -> dict[str, float | None]:
    return {f: table_probe(f)["size_bytes"] for f in fqns}


def table_probe(fqn: str) -> dict:
    t = catalog_tables()
    if len(t):
        hit = t[t["table_catalog"] + "." + t["table_schema"] + "." + t["table_name"] == fqn]
        if len(hit):
            return {"size_bytes": hit.iloc[0]["size_bytes"], "readable": bool(hit.iloc[0]["readable"])}
    return {"size_bytes": None, "readable": False}


def slice_population(fqn: str, slice_filter: str | None) -> tuple[None, None]:
    """The fixture carries no source rows, so a slice cannot be counted locally. The
    page says so rather than inventing a figure."""
    return None, None


def _append_pending(kind: str, row: dict) -> bool:
    st.session_state.setdefault(_PENDING_ONB[kind], []).append(row)
    return True


def pending_onboarding(kind: str) -> list[dict]:
    return list(st.session_state.get(_PENDING_ONB[kind], []))


def write_monitored_table(row: dict) -> bool:
    """Refused if the table already has a version at or above this one."""
    seen = [r["table_version"] for r in pending_onboarding("monitored")
            if r["target_table"] == row["target_table"]]
    base = monitored_tables()
    if len(base):
        seen += base.loc[base["target_table"] == row["target_table"], "table_version"].tolist()
    if any(int(v) >= int(row["table_version"]) for v in seen):
        return False
    return _append_pending("monitored", row)


def write_binding_proposal(row: dict) -> bool:
    return _append_pending("proposal", row)


def write_binding_review(row: dict) -> bool:
    """One decision per proposal: refused if it already has one."""
    base = binding_reviews()
    decided = set(base["proposal_id"]) if len(base) else set()
    decided |= {r["proposal_id"] for r in pending_onboarding("review")}
    if row["proposal_id"] in decided:
        return False
    return _append_pending("review", row)


def write_binding_exclusion(row: dict) -> bool:
    """A rejection appended to an approved proposal: refused unless the proposal has an
    approval and no rejection yet."""
    base = binding_reviews()
    seen = (base[base["proposal_id"] == row["proposal_id"]].to_dict("records")
            if len(base) else [])
    seen += [r for r in pending_onboarding("review") if r["proposal_id"] == row["proposal_id"]]
    decisions = {r["decision"] for r in seen}
    if "approved" not in decisions or "rejected" in decisions:
        return False
    return _append_pending("review", row)


def discard_pending() -> None:
    for key in _PENDING_ONB.values():
        st.session_state[key] = []
    st.session_state[_PENDING_KEY] = []
    st.session_state[_PENDING_RULES_KEY] = []
    st.session_state[_PENDING_REVIEWS_KEY] = []


def confirm_disposition(disposition_id: str) -> bool:
    """Always False. Nothing written here reaches a table, so there is no row to
    read back and nothing an outbound notification could be derived from — which is
    exactly why local and fixture modes can never emit one. See data/notify.py."""
    return False


def durable() -> bool:
    """False — writes here are session-scoped. The UI uses this to label them."""
    return False

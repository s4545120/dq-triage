"""Two people, one stale read: the second write is refused, not appended.

The adapter stamps `event_seq` and `rule_version` from a read that can be five
minutes old. Every write is therefore guarded at the source — append only if nothing
has landed since — because an append-only table can never take back a second event
at the same sequence. Each test here takes the first person's read, lets a second
person write, then submits from the first person's now-stale view.

The local source holds the same guard as the warehouse one, which is what lets this
run without a workspace. The warehouse half is pinned below by what it sends.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP_DIR = Path(__file__).resolve().parents[1]
OUT = APP_DIR.parent / "fixtures" / "out"


def _load(name: str) -> pd.DataFrame:
    path = OUT / f"{name}.parquet"
    if not path.exists():
        pytest.skip("fixture not built")
    return pd.read_parquet(path)


def _run(script, **session) -> AppTest:
    at = AppTest.from_function(script, default_timeout=90)
    at.session_state["_app_dir"] = str(APP_DIR)
    for k, v in session.items():
        at.session_state[k] = v
    at.run()
    assert not at.exception, [e.message for e in at.exception]
    return at


def _two_reviews_of_one_problem():
    import sys

    import streamlit as st
    sys.path.insert(0, st.session_state["_app_dir"])
    from dq_app.data import adapter

    cid = st.session_state["_cid"]
    stale = adapter.get_dispositions()
    adapter.append_disposition(cid, "reviewed", decision="accepted", reason="first")
    real = adapter.get_dispositions
    adapter.get_dispositions = lambda: stale
    try:
        adapter.append_disposition(cid, "reviewed", decision="accepted", reason="second")
        st.session_state["refused"] = None
    except adapter.WriteRejected as exc:
        st.session_state["refused"] = str(exc)
    finally:
        adapter.get_dispositions = real


def test_a_decision_made_on_a_stale_read_is_refused():
    from dq_app.domain.lifecycle import derive_cohort_current

    current = derive_cohort_current(_load("results.cohort"), _load("results.disposition"))
    cid = current[current["lifecycle_state"] == "awaiting_review"].iloc[0]["cohort_id"]

    at = _run(_two_reviews_of_one_problem, _cid=cid)

    written = at.session_state["_pending_disposition_events"]
    assert [e["reason"] for e in written] == ["first"], "the stale decision was appended"
    assert "after you opened it" in at.session_state["refused"]


def _two_promotions_of_one_rule():
    import sys

    import streamlit as st
    sys.path.insert(0, st.session_state["_app_dir"])
    from dq_app.data import adapter

    rid = st.session_state["_rid"]
    stale = adapter.get_rule_registry()
    adapter.promote_rule(rid, "first")
    real = adapter.get_rule_registry
    adapter.get_rule_registry = lambda: stale
    try:
        adapter.promote_rule(rid, "second")
        st.session_state["refused"] = None
    except adapter.WriteRejected as exc:
        st.session_state["refused"] = str(exc)
    finally:
        adapter.get_rule_registry = real


def test_a_promotion_made_on_a_stale_read_is_refused():
    reg = _load("config.rule_registry").sort_values("rule_version")
    latest = reg.groupby("rule_id").tail(1)
    rid = latest[latest["status"] == "shadow"].iloc[0]["rule_id"]

    at = _run(_two_promotions_of_one_rule, _rid=rid)

    written = at.session_state["_pending_rule_versions"]
    assert [r["note"] for r in written] == ["first"], "two rows at one rule_version"
    assert rid in at.session_state["refused"]


def _two_reviews_of_one_proposal():
    import sys

    import streamlit as st
    sys.path.insert(0, st.session_state["_app_dir"])
    from dq_app.data import adapter

    pid = st.session_state["_pid"]
    stale_reviews = adapter.get_threshold_reviews()
    stale_current = adapter.get_threshold_proposal_current()
    adapter.review_threshold(pid, "rejected", reason="first")
    real = adapter.get_threshold_reviews, adapter.get_threshold_proposal_current
    adapter.get_threshold_reviews = lambda: stale_reviews
    adapter.get_threshold_proposal_current = lambda: stale_current
    try:
        adapter.review_threshold(pid, "rejected", reason="second")
        st.session_state["refused"] = None
    except adapter.ReviewRejected as exc:
        st.session_state["refused"] = str(exc)
    finally:
        adapter.get_threshold_reviews, adapter.get_threshold_proposal_current = real


def test_a_threshold_review_made_on_a_stale_read_is_refused():
    cur = _load("results.v_threshold_proposal_current")
    pid = cur[cur["review_state"] == "open"].iloc[0]["proposal_id"]

    at = _run(_two_reviews_of_one_proposal, _pid=pid)

    written = at.session_state["_pending_threshold_reviews"]
    assert [r["reason"] for r in written] == ["first"]
    assert "after you opened it" in at.session_state["refused"]


# --- The warehouse half: what databricks_source actually sends ------------------


class _FakeCursor:
    def __init__(self, landed: bool):
        self.calls: list[tuple[str, dict]] = []
        self._landed = landed

    def execute(self, sql, params=None):
        self.calls.append((sql, params or {}))

    def fetchall(self):
        return [(1,)] if self._landed else []


def _patched(monkeypatch, landed: bool) -> _FakeCursor:
    import contextlib

    from dq_app.data import databricks_source as src

    cur = _FakeCursor(landed)
    monkeypatch.setattr(src, "_cursor", contextlib.contextmanager(lambda: (yield cur)))
    return cur


def test_the_register_insert_is_guarded_and_binds_every_value(monkeypatch):
    """Free text never reaches the SQL string. A reason ending in a backslash used to
    turn the doubled quote after it back into a terminator."""
    from dq_app.data import databricks_source as src

    cur = _patched(monkeypatch, landed=True)
    hostile = "looks fine\\', 'forged') --"
    row = {c: None for c in src._DISPOSITION_COLUMNS}
    row.update(disposition_id="d-1", cohort_id="c-1", event_seq=4, reason=hostile,
               event_ts=pd.Timestamp("2026-10-01 09:00:00"), executed_ts=pd.NaT)

    assert src.write_disposition(row) is True

    insert, params = cur.calls[0]
    assert insert.startswith("INSERT INTO") and "NOT EXISTS" in insert
    assert "event_seq >= :g_event_seq" in insert
    assert hostile not in insert and "forged" not in insert
    assert hostile in params.values()
    assert params["g_cohort_id"] == "c-1" and params["g_event_seq"] == 4
    assert all(not isinstance(v, (pd.Timestamp, type(pd.NaT))) for v in params.values())
    readback, rparams = cur.calls[1]
    assert readback.startswith("SELECT") and rparams == {"r_disposition_id": "d-1"}


def test_a_refused_insert_reports_false(monkeypatch):
    from dq_app.data import databricks_source as src

    _patched(monkeypatch, landed=False)
    row = {"rule_id": "R", "rule_version": 3, "created_by": "a@example.com", "note": "x"}
    assert src.append_rule_version(row) is False

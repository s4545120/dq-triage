"""The register append, end to end through the page.

This is the app's primary write, and the one thing on which the audit claim rests.
It is exercised through the real page rather than by calling the adapter, because
the parts that go wrong in practice are the wiring — a form field that never reaches
the adapter, an identity that never gets stamped, a lifecycle state that does not
move once the event lands.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP_DIR = Path(__file__).resolve().parents[1]
DETAIL = str(APP_DIR / "dq_app/ui/pages/cohort_detail.py")


def _cohort_awaiting_review() -> str:
    import sys

    sys.path.insert(0, str(APP_DIR))
    from dq_app.domain.lifecycle import derive_cohort_current

    out = APP_DIR.parent / "fixtures" / "out"
    if not (out / "results.cohort.parquet").exists():
        pytest.skip("fixture not built")
    current = derive_cohort_current(
        pd.read_parquet(out / "results.cohort.parquet"),
        pd.read_parquet(out / "results.disposition.parquet"),
    )
    waiting = current[current["lifecycle_state"] == "awaiting_review"]
    assert not waiting.empty, "fixture no longer has a cohort awaiting review"
    return waiting.iloc[0]["cohort_id"]


def test_recording_a_review_advances_the_derived_state():
    """No status column is written. The state moves because the event log changed."""
    cohort_id = _cohort_awaiting_review()

    at = AppTest.from_file(DETAIL, default_timeout=60)
    at.session_state["selected_cohort"] = cohort_id
    at.run()
    assert not at.exception

    before = len(at.get("dataframe"))  # sanity: the page rendered its tables
    assert before

    at.radio[0].set_value("accepted")
    at.text_area[0].set_value("Checked against the release calendar; the hypothesis holds.")
    at.button[0].click().run()
    assert not at.exception, [e.message for e in at.exception]

    events = at.session_state["_pending_disposition_events"]
    assert len(events) == 1
    event = events[0]
    assert event["cohort_id"] == cohort_id
    assert event["event_type"] == "reviewed"
    assert event["decision"] == "accepted"
    assert event["actor_identity"], "no identity was stamped on the event"
    # Locally the identity is a stand-in, and it is labelled as one rather than
    # borrowing the platform's `obo_user` — the table's CHECK constraint would
    # reject this row, which is the point.
    assert event["actor_source"] == "local_standin"

    # The state moved because the event log changed, so re-derive it the way the app
    # does rather than trusting the page — then confirm the page is showing it.
    from dq_app.domain.lifecycle import derive_cohort_current

    out = APP_DIR.parent / "fixtures" / "out"
    register = pd.concat(
        [pd.read_parquet(out / "results.disposition.parquet"), pd.DataFrame(events)],
        ignore_index=True,
    )
    derived = derive_cohort_current(pd.read_parquet(out / "results.cohort.parquet"), register)
    state = derived.loc[derived["cohort_id"] == cohort_id, "lifecycle_state"].iloc[0]
    assert state == "awaiting_approval"

    rendered = " ".join(m.value for m in at.markdown).lower()
    assert "awaiting approval" in rendered


def test_a_deferral_without_a_reason_is_refused():
    """A CHECK constraint on the table, enforced in the page so the user sees a
    sentence rather than a driver error."""
    cohort_id = _cohort_awaiting_review()

    at = AppTest.from_file(DETAIL, default_timeout=60)
    at.session_state["selected_cohort"] = cohort_id
    at.run()

    at.radio[0].set_value("deferred")
    at.text_area[0].set_value("   ")
    at.button[0].click().run()

    assert not at.exception
    written = (
        at.session_state["_pending_disposition_events"]
        if "_pending_disposition_events" in at.session_state
        else []
    )
    assert not written, "a deferral with no reason reached the register"
    assert any("reason" in e.value.lower() for e in at.error)

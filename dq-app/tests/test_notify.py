"""The outbound notification path — what triggers it, and the four things that stop it.

This is the app's only outward side effect, and unlike the register write it leaves
no trace of its own. So the tests here are weighted towards refusal: most of them
assert that nothing is sent.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from dq_app.data import notify as transport  # noqa: E402
from dq_app.domain import notify  # noqa: E402

ROUTES = {"*": ("dq-stewards@example.com",)}


def _event(**over) -> dict:
    base = {
        "disposition_id": "11111111-2222-3333-4444-555555555555",
        "cohort_id": "f588b56a-c8ba-5d11-9dcf-82bdaf94450b",
        "event_seq": 4,
        "event_type": "reviewed",
        "decision": "accepted",
        "actor_source": "obo_user",
        "actor_display_name": "R. Delacroix",
        "actor_identity": "r.delacroix@example.com",
        "reason": "CRM export change confirmed with the CRM team",
        "event_ts": datetime(2026, 9, 26, 13, 40),
    }
    base.update(over)
    return base


def _cohort(**over) -> dict:
    base = {
        "severity": "P1_block",
        "member_count": 9,
        "total_violation_rows": 533,
        "affected_tables": ["prod.customer.ctct_c", "prod.customer.subs_c"],
        "owner_group": "Customer Data",
    }
    base.update(over)
    return base


# --- The trigger ------------------------------------------------------------


def test_an_accepted_review_by_a_platform_user_is_the_trigger():
    assert notify.should_notify(_event()) is True


@pytest.mark.parametrize("decision", ["rejected", "deferred", "no_action"])
def test_every_other_review_decision_sends_nothing(decision):
    """`reviewed` alone is not the trigger. A rejection is also a review, and
    notifying on event type would mail an owner about a problem just dismissed."""
    assert notify.should_notify(_event(decision=decision)) is False


@pytest.mark.parametrize("event_type", ["approved", "executed", "recommended", "verified"])
def test_no_other_event_type_triggers(event_type):
    assert notify.should_notify(_event(event_type=event_type)) is False


def test_a_local_standin_never_triggers():
    """The schema already refuses this row. A send is an outbound side effect and
    does not get to rely on a constraint in a table it is not reading."""
    assert notify.should_notify(_event(actor_source="local_standin")) is False


def test_should_notify_tolerates_a_row_missing_everything():
    assert notify.should_notify({}) is False


# --- Routing ----------------------------------------------------------------


def test_a_bare_address_list_is_the_catch_all():
    assert notify.parse_routes("dq@example.com, ops@example.com") == {
        "*": ("dq@example.com", "ops@example.com")
    }


def test_routes_parse_per_owner_group():
    routes = notify.parse_routes("*: dq@example.com; Customer Data: crm@example.com")
    assert notify.recipients_for("Customer Data", routes) == ("crm@example.com",)
    assert notify.recipients_for("Network", routes) == ("dq@example.com",)


def test_an_unrouted_group_with_no_catch_all_reaches_nobody():
    routes = notify.parse_routes("Customer Data: crm@example.com")
    assert notify.recipients_for("Network", routes) == ()


def test_compose_returns_none_when_nobody_is_routed():
    assert notify.compose(_event(), _cohort(), routes={}) is None


# --- The message ------------------------------------------------------------


def test_the_message_carries_the_facts_and_its_own_provenance():
    msg = notify.compose(
        _event(), _cohort(),
        title="Customer email address — wrong data",
        routes=ROUTES,
        app_url="https://dq-triage.example.com",
    )
    assert msg is not None
    assert msg.subject == "[DQ P1] Customer email address — wrong data"
    assert msg.recipients == ("dq-stewards@example.com",)
    for fragment in [
        "Customer email address — wrong data",
        "P1 Critical",
        "533",
        "prod.customer.ctct_c, prod.customer.subs_c",
        "R. Delacroix",
        "CRM export change confirmed with the CRM team",
        "results.disposition",
        "event_seq 4",
    ]:
        assert fragment in msg.body_text, fragment


def test_the_message_says_the_app_acted_on_nothing():
    """The non-execution claim travels with the message. A recipient reading that a
    defect was 'confirmed' should not infer that anything was done about it."""
    msg = notify.compose(_event(), _cohort(), routes=ROUTES)
    assert "does not modify business data" in msg.body_text
    assert "has not acted on this problem" in msg.body_text


def test_a_missing_title_falls_back_rather_than_failing():
    msg = notify.compose(_event(), _cohort(), routes=ROUTES)
    assert "f588b56a" in msg.subject


def test_the_typed_reason_is_escaped_in_the_html_body():
    """`reason` is free text a steward typed into a form."""
    msg = notify.compose(
        _event(reason='<script>alert("x")</script>'), _cohort(), routes=ROUTES
    )
    assert "<script>" not in msg.body_html
    assert "&lt;script&gt;" in msg.body_html


# --- The transport ----------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ["DQ_NOTIFY", "DQ_NOTIFY_TO", "DQ_NOTIFY_JOB_ID", "DQ_APP_URL"]:
        monkeypatch.delenv(var, raising=False)


def test_the_transport_is_off_unless_asked_for():
    """Default off. A deploy that does not opt in cannot emit anything, and neither
    can any test or demo that forgets to."""
    assert transport.transport() == "off"
    assert transport.enabled() is False
    assert transport.dispatch(_event(), _cohort(), confirmed=True) == "off"


def test_an_unconfirmed_write_sends_nothing(monkeypatch):
    """The whole ordering argument in one assertion: no observed register row, no
    message. This is what local mode returns for every event it ever records."""
    monkeypatch.setenv("DQ_NOTIFY", "log")
    monkeypatch.setenv("DQ_NOTIFY_TO", "dq@example.com")
    assert transport.dispatch(_event(), _cohort(), confirmed=False) == "unconfirmed"


def test_a_confirmed_accepted_review_sends(monkeypatch):
    monkeypatch.setenv("DQ_NOTIFY", "log")
    monkeypatch.setenv("DQ_NOTIFY_TO", "dq@example.com")
    assert transport.dispatch(_event(), _cohort(), confirmed=True) == "sent"


def test_a_confirmed_rejection_still_sends_nothing(monkeypatch):
    monkeypatch.setenv("DQ_NOTIFY", "log")
    monkeypatch.setenv("DQ_NOTIFY_TO", "dq@example.com")
    out = transport.dispatch(_event(decision="rejected"), _cohort(), confirmed=True)
    assert out == "no_trigger"


def test_the_job_transport_refuses_without_a_job_id(monkeypatch):
    """And reports it rather than raising — the register write already succeeded."""
    monkeypatch.setenv("DQ_NOTIFY", "job")
    monkeypatch.setenv("DQ_NOTIFY_TO", "dq@example.com")
    assert transport.dispatch(_event(), _cohort(), confirmed=True) == "failed"


def test_local_mode_can_never_confirm_a_write():
    from dq_app.data import local_source

    assert local_source.confirm_disposition("anything") is False


# --- The disclosure on the page ---------------------------------------------
# A steward can cause a message to be sent by clicking "Append to register", so the
# form has to admit it before the click. These tests exist because the mechanism
# shipped once without them and the page said nothing at all.

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402

DETAIL = str(APP_DIR / "dq_app/ui/pages/triage_detail.py")


def _open_review_form(cohort_id: str):
    at = AppTest.from_file(DETAIL, default_timeout=60)
    at.session_state["selected_cohort"] = cohort_id
    at.run()
    for button in at.button:
        if str(button.label).startswith("Record a"):
            return button.click().run()
    raise AssertionError(f"no decision button: {[b.label for b in at.button]}")


def _awaiting_review() -> str:
    from dq_app.domain.lifecycle import derive_cohort_current

    out = APP_DIR.parent / "fixtures" / "out"
    if not (out / "results.cohort.parquet").exists():
        pytest.skip("fixture not built")
    import pandas as pd

    current = derive_cohort_current(
        pd.read_parquet(out / "results.cohort.parquet"),
        pd.read_parquet(out / "results.disposition.parquet"),
    )
    waiting = current[current["lifecycle_state"] == "awaiting_review"]
    assert not waiting.empty, "fixture no longer has a cohort awaiting review"
    return waiting.iloc[0]["cohort_id"]


def _captions(at) -> str:
    return " ".join(str(c.value) for c in at.caption)


def test_the_form_says_nothing_about_email_when_notification_is_off():
    """The default. A page that explained a disabled feature would be noise."""
    at = _open_review_form(_awaiting_review())
    assert not at.exception, [e.message for e in at.exception]
    assert "email" not in _captions(at).lower()


@pytest.fixture
def durable(monkeypatch):
    """Pretend the write path is the workspace one.

    The disclosure is about what accepting WOULD do, and on a laptop the answer is
    "nothing" whatever the routing says — so the routed cases cannot be tested
    without this."""
    from dq_app.data import local_source

    monkeypatch.setattr(local_source, "durable", lambda: True)


def test_the_form_admits_a_laptop_sends_nothing(monkeypatch):
    """Configured, but session-only writes are never read back, so nothing goes."""
    monkeypatch.setenv("DQ_NOTIFY", "log")
    monkeypatch.setenv("DQ_NOTIFY_TO", "*: crm-owners@example.com")
    at = _open_review_form(_awaiting_review())
    assert not at.exception, [e.message for e in at.exception]
    said = _captions(at)
    assert "session-only" in said
    assert "crm-owners@example.com" not in said


def test_the_form_names_the_recipients_before_the_submit_button(monkeypatch, durable):
    monkeypatch.setenv("DQ_NOTIFY", "log")
    monkeypatch.setenv("DQ_NOTIFY_TO", "*: crm-owners@example.com")
    at = _open_review_form(_awaiting_review())
    assert not at.exception, [e.message for e in at.exception]
    said = _captions(at)
    assert "crm-owners@example.com" in said
    assert "Defer, reject and no action send nothing" in said


def test_an_unrouted_domain_is_disclosed_as_sending_nothing(monkeypatch, durable):
    """On, but no route for this owner group. Silence here would read as 'off'."""
    monkeypatch.setenv("DQ_NOTIFY", "log")
    monkeypatch.setenv("DQ_NOTIFY_TO", "nobody-matches-this: x@example.com")
    at = _open_review_form(_awaiting_review())
    assert not at.exception, [e.message for e in at.exception]
    assert "has no" in _captions(at) and "notification route" in _captions(at)

"""The rules that are not merely a projection of the data."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from dq_app.domain import lifecycle


def _events(rows: list[dict]) -> pd.DataFrame:
    cols = ["event_seq", "event_type", "actor_identity", "decision"]
    return pd.DataFrame(rows or [], columns=cols)


# --- Approval policy --------------------------------------------------------


def test_p1_needs_two_approvers_others_need_one():
    assert lifecycle.approvals_required("P1_block") == 2
    assert lifecycle.approvals_required("P2_alert") == 1
    assert lifecycle.approvals_required("P3_monitor") == 1


def test_same_person_approving_twice_is_refused():
    """Row count is not the control. Two rows from one identity is one approver."""
    prior = _events([{"event_seq": 3, "event_type": "approved",
                      "actor_identity": "p.nguyen@example.com", "decision": None}])
    with pytest.raises(lifecycle.EventRejected, match="distinct"):
        lifecycle.validate_event(
            "approved", actor_email="p.nguyen@example.com", prior_events=prior
        )


def test_a_second_distinct_approver_is_accepted():
    prior = _events([{"event_seq": 3, "event_type": "approved",
                      "actor_identity": "p.nguyen@example.com", "decision": None}])
    lifecycle.validate_event(
        "approved", actor_email="s.whitfield@example.com", prior_events=prior
    )


# --- What a person may author ----------------------------------------------


@pytest.mark.parametrize("event_type", ["recommended", "verified", "reopened"])
def test_job_only_events_cannot_be_authored_in_app(event_type):
    """A steward marking their own work verified would make closure self-certified."""
    with pytest.raises(lifecycle.EventRejected):
        lifecycle.validate_event(event_type, actor_email="a@b.com", prior_events=_events([]))


# --- Constraints the table also enforces ------------------------------------


@pytest.mark.parametrize("decision", ["deferred", "rejected"])
def test_reason_required_for_deferral_and_rejection(decision):
    with pytest.raises(lifecycle.EventRejected, match="reason"):
        lifecycle.validate_event(
            "reviewed", actor_email="a@b.com", prior_events=_events([]),
            decision=decision, reason="   ", review_by_date=date.today(),
        )


def test_deferral_requires_a_review_by_date():
    with pytest.raises(lifecycle.EventRejected, match="review-by"):
        lifecycle.validate_event(
            "reviewed", actor_email="a@b.com", prior_events=_events([]),
            decision="deferred", reason="Waiting on the source team.", review_by_date=None,
        )


# --- Sequence ---------------------------------------------------------------


def test_event_seq_starts_at_one_and_never_reuses():
    assert lifecycle.next_event_seq(_events([])) == 1
    prior = _events([
        {"event_seq": 1, "event_type": "recommended", "actor_identity": None, "decision": None},
        {"event_seq": 4, "event_type": "reviewed", "actor_identity": "a@b.com",
         "decision": "accepted"},
    ])
    # Gaps are acceptable; reuse is not — so it follows the maximum, not the count.
    assert lifecycle.next_event_seq(prior) == 5


# --- The precedence that makes reopening work -------------------------------


def test_failed_verification_outranks_the_approval_before_it():
    """The bug this ordering prevents: a cohort sitting closed and wrong."""
    ev = {
        "last_verification_passed": False, "reopen_count": 1, "last_event_type": "reopened",
        "latest_decision": "accepted", "executed_ts": pd.Timestamp("2026-08-31"),
        "distinct_approvers": 2,
    }
    assert lifecycle._state("P1_block", ev) == "reopened"


def test_a_passed_verification_closes_regardless_of_what_precedes_it():
    ev = {
        "last_verification_passed": True, "reopen_count": 1, "last_event_type": "verified",
        "latest_decision": "accepted", "executed_ts": pd.Timestamp("2026-08-31"),
        "distinct_approvers": 2,
    }
    assert lifecycle._state("P1_block", ev) == "closed_verified"


def test_one_approver_does_not_clear_a_p1_gate():
    ev = {
        "last_verification_passed": None, "reopen_count": 0, "last_event_type": "approved",
        "latest_decision": "accepted", "executed_ts": pd.NaT, "distinct_approvers": 1,
    }
    assert lifecycle._state("P1_block", ev) == "awaiting_approval"
    assert lifecycle._state("P2_alert", ev) == "approved_awaiting_execution"


# --- What the UI may offer --------------------------------------------------


def test_nothing_offers_verification_to_a_human():
    for state in lifecycle.LIFECYCLE_ORDER:
        assert "verified" not in lifecycle.available_events(state)
        assert "reopened" not in lifecycle.available_events(state)


def test_awaiting_verification_offers_nothing():
    """The next scheduled run decides it. There is no re-check job to press."""
    assert lifecycle.available_events("awaiting_verification") == []


def test_terminal_states_offer_nothing():
    for state in lifecycle.TERMINAL_STATES:
        assert lifecycle.available_events(state) == []

"""The control test, and proof that it can fail.

A control that has only ever been observed passing is not evidence of anything. The
fixture is clean by construction, so each clause is also driven with a deliberately
corrupted register to show it reports the failure.
"""

from __future__ import annotations

import pandas as pd

from dq_app.domain import integrity


def test_the_generated_register_is_clean(cohorts, dispositions):
    findings = integrity.check(cohorts, dispositions)
    assert findings.empty, findings.to_string()


def test_same_approver_twice_is_reported(cohorts, dispositions):
    """The control is on distinct identities. Rewriting the second approval of a P1
    cohort to the first approver's identity leaves the row count untouched and must
    still fail — that distinction is the whole reason the view exists."""
    p1 = cohorts[cohorts["severity"] == "P1_block"]["cohort_id"]
    approvals = dispositions[
        (dispositions["event_type"] == "approved") & dispositions["cohort_id"].isin(p1)
    ]
    target = approvals.groupby("cohort_id").filter(lambda g: len(g) >= 2)
    assert not target.empty, "fixture no longer contains a two-approver P1 cohort"

    cohort_id = target["cohort_id"].iloc[0]
    rows = target[target["cohort_id"] == cohort_id].sort_values("event_seq")
    corrupted = dispositions.copy()
    corrupted.loc[rows.index[1], "actor_identity"] = rows.iloc[0]["actor_identity"]

    findings = integrity.check(cohorts, corrupted)
    assert "insufficient_distinct_approvers" in set(findings["finding"])


def test_a_third_approval_row_from_an_existing_approver_does_not_clear_it(
    cohorts, dispositions
):
    p1 = cohorts[cohorts["severity"] == "P1_block"]["cohort_id"]
    approvals = dispositions[
        (dispositions["event_type"] == "approved") & dispositions["cohort_id"].isin(p1)
    ]
    target = approvals.groupby("cohort_id").filter(lambda g: len(g) >= 2)
    cohort_id = target["cohort_id"].iloc[0]
    rows = target[target["cohort_id"] == cohort_id].sort_values("event_seq")

    corrupted = dispositions.copy()
    corrupted.loc[rows.index[1], "actor_identity"] = rows.iloc[0]["actor_identity"]
    extra = corrupted.loc[[rows.index[0]]].copy()
    extra["event_seq"] = corrupted["event_seq"].max() + 1
    corrupted = pd.concat([corrupted, extra], ignore_index=True)

    findings = integrity.check(cohorts, corrupted)
    assert "insufficient_distinct_approvers" in set(findings["finding"])


def test_execution_without_prior_approval_is_reported(cohorts, dispositions):
    corrupted = dispositions[
        ~(
            (dispositions["event_type"] == "approved")
            & (dispositions["cohort_id"] == dispositions[
                dispositions["event_type"] == "executed"]["cohort_id"].iloc[0])
        )
    ]
    findings = integrity.check(cohorts, corrupted)
    assert "executed_without_approval" in set(findings["finding"])


def test_a_typed_identity_is_reported(cohorts, dispositions):
    """If identity can be entered rather than forwarded, the register is not evidence."""
    corrupted = dispositions.copy()
    idx = corrupted[corrupted["event_type"] == "approved"].index[0]
    corrupted.loc[idx, "actor_source"] = "local_standin"
    findings = integrity.check(cohorts, corrupted)
    assert "identity_not_from_platform" in set(findings["finding"])


def test_a_cohort_with_no_opening_event_is_reported(cohorts, dispositions):
    corrupted = dispositions[
        ~(
            (dispositions["event_type"] == "recommended")
            & (dispositions["cohort_id"] == cohorts["cohort_id"].iloc[0])
        )
    ]
    findings = integrity.check(cohorts, corrupted)
    assert "missing_recommended_event" in set(findings["finding"])


def test_every_finding_type_has_an_explanation():
    for name in [
        "insufficient_distinct_approvers",
        "executed_without_approval",
        "identity_not_from_platform",
        "missing_recommended_event",
    ]:
        assert integrity.FINDING_HELP.get(name)

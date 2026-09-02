"""Cohort lifecycle — derived state, approval gating, and what may happen next.

Pure logic. No Streamlit, no Spark, no I/O. Importable and testable on its own.

## This module is a COPY, and the copy is deliberate

`sql/ddl/08_views.sql` defines `v_cohort_current`, and that view is the single
definition of `lifecycle_state`. Nothing is stored: `results.disposition` is an
append-only event log with no status column, so current state is folded out of the
events at read time.

The app needs the same fold in Python for one reason only — when a steward records
an event in-session, the queue has to reflect it before the event has reached a
warehouse that could re-run the view. Rather than keep two code paths (read the
view / recompute locally) and let them drift, the app always recomputes here, and
`tests/test_lifecycle_conformance.py` asserts this function reproduces the shipped
`results.v_cohort_current.parquet` row for row.

If you change the CASE ladder in `08_views.sql`, change it here and the test will
tell you whether you got it right. If you change it here alone, the test fails.
That is the arrangement.
"""

from __future__ import annotations

import pandas as pd

# --- Vocabulary -------------------------------------------------------------
# The event types the register accepts. Ordered as the spec's table 01-05, with
# `reopened` appended because a failed verification emits one.
EVENT_TYPES = [
    "recommended",
    "reviewed",
    "approved",
    "executed",
    "verified",
    "reopened",
]

# Who is allowed to author each event type. `obo_user` means a signed-in human
# whose identity came from the platform; the other two are jobs.
EVENT_ACTOR_SOURCE = {
    "recommended": "triage_job",
    "reviewed": "obo_user",
    "approved": "obo_user",
    "executed": "obo_user",
    "verified": "check_runner",
    "reopened": "check_runner",
}

DECISIONS = ["accepted", "deferred", "rejected", "no_action"]

APPROACH_TYPES = [
    "pipeline_rerun",
    "upstream_ticket",
    "source_correction",
    "manual_sql",
    "accept_and_document",
]

# Every branch of the CASE ladder in v_cohort_current, in queue-priority order:
# the states that still want a human come first.
LIFECYCLE_ORDER = [
    "reopened",
    "awaiting_review",
    "awaiting_approval",
    "approved_awaiting_execution",
    "awaiting_verification",
    "deferred",
    "awaiting_triage",
    "closed_verified",
    "closed_rejected",
    "closed_no_action",
]

OPEN_STATES = {
    "reopened",
    "awaiting_review",
    "awaiting_approval",
    "approved_awaiting_execution",
    "awaiting_verification",
    "awaiting_triage",
}
TERMINAL_STATES = {"closed_verified", "closed_rejected", "closed_no_action"}
# `deferred` is neither: it is parked, and resurfaces on its review_by_date.

SEVERITY_ORDER = ["P1_block", "P2_alert", "P3_monitor"]


def approvals_required(severity: str) -> int:
    """P1 needs two distinct named approvers; P2/P3 need one.

    Distinct is the whole point — the same person approving twice satisfies a row
    count and fails the control. See `v_disposition_integrity`.
    """
    return 2 if severity == "P1_block" else 1


# --- The fold ---------------------------------------------------------------


def _max_by(group: pd.DataFrame, value_col: str, mask: pd.Series):
    """SQL `MAX_BY(value, CASE WHEN mask THEN event_seq END)`.

    Value from the highest-`event_seq` row where mask holds; NULL if none do.
    """
    sub = group[mask]
    if sub.empty:
        return None
    return sub.loc[sub["event_seq"].idxmax(), value_col]


def _fold_events(group: pd.DataFrame) -> dict:
    is_reviewed = group["event_type"] == "reviewed"
    is_approved = group["event_type"] == "approved"
    is_executed = group["event_type"] == "executed"
    is_verified = group["event_type"] == "verified"

    return {
        "last_seq": group["event_seq"].max(),
        "reviewed_ts": group.loc[is_reviewed, "event_ts"].max() if is_reviewed.any() else pd.NaT,
        "executed_ts": group.loc[is_executed, "event_ts"].max() if is_executed.any() else pd.NaT,
        "verified_ts": group.loc[is_verified, "event_ts"].max() if is_verified.any() else pd.NaT,
        "approval_rows": int(is_approved.sum()),
        "distinct_approvers": int(group.loc[is_approved, "actor_identity"].nunique()),
        "reopen_count": int((group["event_type"] == "reopened").sum()),
        "latest_decision": _max_by(group, "decision", is_reviewed),
        "latest_reason": _max_by(group, "reason", is_reviewed),
        "review_by_date": _max_by(group, "review_by_date", is_reviewed),
        "reviewed_by": _max_by(group, "actor_identity", is_reviewed),
        "reviewed_by_name": _max_by(group, "actor_display_name", is_reviewed),
        "last_verification_passed": _max_by(group, "verification_passed", is_verified),
        "violations_before": _max_by(group, "violations_before", is_verified),
        "violations_after": _max_by(group, "violations_after", is_verified),
        "approach_type_taken": _max_by(group, "approach_type_taken", is_executed),
        "external_ref": _max_by(group, "external_ref", is_executed),
        "last_event_type": group.loc[group["event_seq"].idxmax(), "event_type"],
    }


def _state(cohort_severity: str, ev: dict | None) -> str:
    """The CASE ladder from v_cohort_current, in the same precedence order.

    The order is the state machine. In particular a failed verification outranks
    the approval that preceded it, so a reopened cohort returns to the queue
    rather than sitting closed and wrong.
    """
    if ev is None:
        return "awaiting_triage"
    if ev["last_verification_passed"] is True:
        return "closed_verified"
    if ev["reopen_count"] > 0 and ev["last_event_type"] in ("reopened", "verified"):
        return "reopened"
    if ev["latest_decision"] == "rejected":
        return "closed_rejected"
    if ev["latest_decision"] == "no_action":
        return "closed_no_action"
    if ev["latest_decision"] == "deferred":
        return "deferred"
    if pd.notna(ev["executed_ts"]):
        return "awaiting_verification"
    if ev["distinct_approvers"] >= approvals_required(cohort_severity):
        return "approved_awaiting_execution"
    if ev["latest_decision"] == "accepted":
        return "awaiting_approval"
    return "awaiting_review"


def derive_cohort_current(cohort: pd.DataFrame, disposition: pd.DataFrame) -> pd.DataFrame:
    """One row per cohort with its derived lifecycle state. The Python twin of
    `{catalog}.results.v_cohort_current` — see the module docstring."""
    folded = {
        cid: _fold_events(g.sort_values("event_seq"))
        for cid, g in disposition.groupby("cohort_id", sort=False)
    }

    rows = []
    for c in cohort.to_dict("records"):
        ev = folded.get(c["cohort_id"])
        required = approvals_required(c["severity"])
        state = _state(c["severity"], ev)

        mttr = None
        if ev and ev["last_verification_passed"] is True and pd.notna(ev["verified_ts"]):
            mttr = (ev["verified_ts"] - c["raised_ts"]).total_seconds() / 86400.0

        taken = ev["approach_type_taken"] if ev else None
        rows.append(
            {
                # Straight from the cohort table.
                "cohort_id": c["cohort_id"],
                "raised_ts": c["raised_ts"],
                "severity": c["severity"],
                "business_domain": c["business_domain"],
                "owner_group": c["owner_group"],
                "member_count": c["member_count"],
                "affected_tables": c["affected_tables"],
                "total_violation_rows": c["total_violation_rows"],
                "root_cause_hypothesis": c["root_cause_hypothesis"],
                "recommended_approach": c["recommended_approach"],
                "recommended_approach_type": c["recommended_approach_type"],
                "recommendation_source": c["recommendation_source"],
                "rank_score": c["rank_score"],
                "is_recurrence": c["is_recurrence"],
                # Derived.
                "lifecycle_state": state,
                "distinct_approvers": ev["distinct_approvers"] if ev else 0,
                "approvals_required": required,
                "reopen_count": ev["reopen_count"] if ev else 0,
                "latest_decision": ev["latest_decision"] if ev else None,
                "latest_reason": ev["latest_reason"] if ev else None,
                "review_by_date": ev["review_by_date"] if ev else None,
                "reviewed_by": ev["reviewed_by"] if ev else None,
                "reviewed_ts": ev["reviewed_ts"] if ev else pd.NaT,
                "executed_ts": ev["executed_ts"] if ev else pd.NaT,
                "verified_ts": ev["verified_ts"] if ev else pd.NaT,
                "violations_before": ev["violations_before"] if ev else None,
                "violations_after": ev["violations_after"] if ev else None,
                "approach_type_taken": taken,
                "external_ref": ev["external_ref"] if ev else None,
                # Did the steward do what was recommended? NULL until they did
                # something, so "not yet actioned" never counts as disagreement.
                "recommendation_followed": (
                    None if taken is None else taken == c["recommended_approach_type"]
                ),
                "mttr_days": mttr,
            }
        )

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["_sev"] = out["severity"].map({s: i for i, s in enumerate(SEVERITY_ORDER)})
    out["_state"] = out["lifecycle_state"].map({s: i for i, s in enumerate(LIFECYCLE_ORDER)})
    return out.sort_values(
        ["_state", "_sev", "rank_score"], ascending=[True, True, False]
    ).drop(columns=["_sev", "_state"]).reset_index(drop=True)


# --- What the UI may offer next ---------------------------------------------


def available_events(state: str, distinct_approvers: int = 0, required: int = 1) -> list[str]:
    """Which in-app events are legal from here.

    Note what is absent and stays absent: nothing in this list executes anything.
    `executed` records a claim that a person acted outside the system — the spec's
    step 04 — and `verified` is not here at all, because only the check runner
    emits it. A steward cannot mark their own work verified.
    """
    if state in TERMINAL_STATES:
        return []
    if state in ("awaiting_review", "awaiting_triage", "reopened", "deferred"):
        return ["reviewed"]
    if state == "awaiting_approval":
        return ["approved"]
    if state == "approved_awaiting_execution":
        return ["executed"]
    if state == "awaiting_verification":
        return []  # the next scheduled check run closes it; nobody else can
    return []


class EventRejected(ValueError):
    """An event the domain rules refuse. Raised before anything is written anywhere."""


# Only a person authors these. `recommended` belongs to the triage job; `verified`
# and `reopened` belong to the check runner. Nothing in the app may forge them.
AUTHORABLE_IN_APP = ("reviewed", "approved", "executed")


def validate_event(
    event_type: str,
    *,
    actor_email: str | None,
    prior_events: pd.DataFrame,
    decision: str | None = None,
    reason: str | None = None,
    review_by_date=None,
) -> None:
    """Refuse an event before it is written. Raises `EventRejected` with a message
    written for the person who will read it.

    Three classes of refusal, and they exist for different reasons:

      * **Wrong author.** A steward marking their own work verified would make
        closure self-certified, so `verified` is not authorable here at all.
      * **Table CHECK constraints, enforced early.** A deferral with no reason or no
        review-by date is rejected by `sql/ddl/06_results_disposition.sql`; checking
        here too turns a driver error into a sentence.
      * **The set-level rule the table cannot enforce.** "Two *distinct* approvers"
        is a property of a set of rows, and a Delta CHECK sees one row at a time —
        so a repeat approval is refused here and *detected* afterwards by
        `v_disposition_integrity`, which is the control that actually counts.
    """
    if event_type not in AUTHORABLE_IN_APP:
        raise EventRejected(
            f"'{event_type}' is not an event a person may author in this app. "
            "`recommended` comes from the triage job; `verified` and `reopened` come "
            "from the check runner. A steward cannot mark their own work verified."
        )
    if decision in ("deferred", "rejected") and not (reason or "").strip():
        raise EventRejected(f"A '{decision}' decision requires a reason.")
    if decision == "deferred" and review_by_date is None:
        raise EventRejected(
            "A deferred cohort requires a review-by date, or it disappears instead of "
            "coming back."
        )
    if event_type == "approved":
        already = prior_events[
            (prior_events["event_type"] == "approved")
            & (prior_events["actor_identity"] == actor_email)
        ]
        if len(already):
            raise EventRejected(
                "You have already approved this cohort. The requirement is two "
                "*distinct* approvers — a second row from the same identity adds "
                "nothing and would be reported by the integrity control."
            )


def next_event_seq(prior_events: pd.DataFrame) -> int:
    """Monotonic per cohort, starting at 1. Gaps are acceptable; reuse is not."""
    if prior_events.empty:
        return 1
    return int(prior_events["event_seq"].max()) + 1


def approval_gate(row) -> tuple[bool, str]:
    """(satisfied, human-readable reason) for the approval requirement.

    The reason string is what the detail page shows next to the gate, so it has to
    say *distinct*, or a reader will assume two rows is two approvers.
    """
    have, need = int(row["distinct_approvers"]), int(row["approvals_required"])
    if have >= need:
        return True, f"{have} of {need} distinct approvers recorded"
    return False, f"{have} of {need} distinct approvers — {need - have} more required"

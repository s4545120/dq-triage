"""The seam. Every page imports from HERE and never from a source module directly.

That one rule is what makes the local → workspace switch an env-var change rather
than a rewrite:

    DQ_APP_DATA_SOURCE=local        # default — reads fixtures/out/*.parquet
    DQ_APP_DATA_SOURCE=databricks   # requires `databricks auth login`

Both sources return the same DataFrame shapes. If you add a column to one, add it
to the other, or the pages will work on a laptop and fail in the workspace.

## Two things this module does beyond dispatching

**Derived state.** `lifecycle_state` and the current rule version are not stored
anywhere — the register and the registry are both append-only. They are folded out
of the events here, by `domain.lifecycle`, which is a labelled copy of
`sql/ddl/08_views.sql` pinned to it by a conformance test.

**Writes.** Exactly two of them exist in the whole app: appending a register event,
and promoting a shadow rule. Both are `INSERT`. There is no third, and adding one
that touched a `prod.*` table would contradict the grants the app runs under.

The CDE register is read-only here for the same reason. Registering an element is an
append to `config.cde_registry` and would be that third write, which is a decision
about the app's Unity Catalog grants rather than a UI change. Until it is taken, the
register is seeded and this module only reads it.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import date, datetime

import pandas as pd
import streamlit as st

from dq_app.data import identity
from dq_app.data import notify as _notify_transport
from dq_app.domain import coverage, lifecycle, thresholds

APP_VERSION = "dq-triage-app/1.0.0"

_SOURCE = os.getenv("DQ_APP_DATA_SOURCE", "local").strip().lower()

if _SOURCE == "databricks":
    from dq_app.data import databricks_source as _impl
elif _SOURCE == "local":
    from dq_app.data import local_source as _impl
else:
    raise ValueError(
        f"Unknown DQ_APP_DATA_SOURCE={_SOURCE!r}. Expected 'local' or 'databricks'."
    )


def active_source() -> str:
    return _SOURCE


def is_local() -> bool:
    return _SOURCE == "local"


def writes_are_durable() -> bool:
    return _impl.durable()


# --- Cached reads -----------------------------------------------------------
# ttl keeps the workspace source from serving stale results indefinitely; the
# local source is re-read cheaply anyway.

_CACHE = dict(ttl=300, show_spinner=False)


@st.cache_data(**_CACHE)
def get_cohorts() -> pd.DataFrame:
    return _impl.cohorts()


@st.cache_data(**_CACHE)
def _base_dispositions() -> pd.DataFrame:
    return _impl.dispositions()


@st.cache_data(**_CACHE)
def get_check_runs() -> pd.DataFrame:
    return _impl.check_runs()


@st.cache_data(**_CACHE)
def get_violation_samples() -> pd.DataFrame:
    return _impl.violation_samples()


@st.cache_data(**_CACHE)
def _base_rule_registry() -> pd.DataFrame:
    return _impl.rule_registry()


def get_rule_registry() -> pd.DataFrame:
    """Every version of every rule, including any promoted in this session.
    Append-only — this is the history, not the current state."""
    base = _base_rule_registry()
    pending = getattr(_impl, "pending_rules", lambda: [])()
    if not pending:
        return base
    return pd.concat([base, pd.DataFrame(pending)], ignore_index=True)


@st.cache_data(**_CACHE)
def get_playbook() -> pd.DataFrame:
    return _impl.playbook()


@st.cache_data(**_CACHE)
def get_cde_registry() -> pd.DataFrame:
    """Every version of every critical data element. Append-only, so this is the
    history; `get_cde_registry_current()` is the current state."""
    return _impl.cde_registry()


@st.cache_data(**_CACHE)
def get_cde_profile() -> pd.DataFrame:
    return _impl.cde_profile()


def get_dispositions() -> pd.DataFrame:
    """The register, including anything recorded in this session but not yet durable."""
    base = _base_dispositions()
    pending = getattr(_impl, "pending_events", lambda: [])()
    if not pending:
        return base
    return pd.concat([base, pd.DataFrame(pending)], ignore_index=True)


def get_cohort_current() -> pd.DataFrame:
    """One row per cohort with derived lifecycle state — the Python twin of
    `v_cohort_current`. See `domain/lifecycle.py` for why it is computed and not read."""
    return lifecycle.derive_cohort_current(get_cohorts(), get_dispositions())


def get_rule_registry_current() -> pd.DataFrame:
    """Latest non-retired version of each rule, with `effective_to` derived.

    The Python twin of `v_rule_registry_current`. `effective_to` is derived rather
    than stored so that promoting a rule stays an INSERT.
    """
    reg = get_rule_registry().sort_values(["rule_id", "rule_version"])
    reg = reg.assign(effective_to=reg.groupby("rule_id")["effective_from"].shift(-1))
    latest = reg.groupby("rule_id", as_index=False).tail(1)
    return latest[latest["status"] != "retired"].reset_index(drop=True)


@st.cache_data(**_CACHE)
def get_threshold_proposals() -> pd.DataFrame:
    return _impl.threshold_proposals()


@st.cache_data(**_CACHE)
def _base_threshold_reviews() -> pd.DataFrame:
    return _impl.threshold_reviews()


def get_threshold_reviews() -> pd.DataFrame:
    """Every reviewer decision, including any recorded in this session."""
    base = _base_threshold_reviews()
    pending = getattr(_impl, "pending_threshold_reviews", lambda: [])()
    if not pending:
        return base
    return pd.concat([base, pd.DataFrame(pending)], ignore_index=True)


def get_threshold_proposal_current() -> pd.DataFrame:
    """One row per rule: its latest proposal with the latest review folded in — the
    Python twin of `v_threshold_proposal_current`, computed so a review recorded in
    this session shows before any warehouse could re-run the view."""
    return thresholds.derive_proposal_current(
        get_threshold_proposals(), get_threshold_reviews(), get_rule_registry())


def get_cde_registry_current() -> pd.DataFrame:
    """Latest non-retired version of each element, with `effective_to` derived.
    The Python twin of `v_cde_registry_current`."""
    return coverage.current_registry(get_cde_registry())


def get_cde_coverage() -> pd.DataFrame:
    """One row per bound CDE column — the Python twin of `v_cde_coverage`.

    Recomputed rather than read because it depends on the rule registry, and
    promoting a shadow rule is one of the app's two writes: a promotion made in this
    session changes what is covered, and the panel has to say so before any
    warehouse could re-materialise the view.
    """
    return coverage.derive_cde_coverage(
        get_cde_registry(), get_rule_registry(), get_check_runs(), get_cde_profile())


def clear_cache() -> None:
    st.cache_data.clear()


# --- Writes: there are two, and this is both of them -------------------------


# The domain refuses events; this is the same exception under the name the pages use.
WriteRejected = lifecycle.EventRejected


def append_disposition(
    cohort_id: str,
    event_type: str,
    *,
    decision: str | None = None,
    reason: str | None = None,
    review_by_date: date | None = None,
    executed_summary: str | None = None,
    external_ref: str | None = None,
    approach_type_taken: str | None = None,
    playbook_id: str | None = None,
    title: str | None = None,
) -> dict:
    """Append one event to the register. The app's primary write.

    Validation lives in `domain.lifecycle.validate_event` — pure, and tested without
    a Streamlit runtime. What happens here is only the stamping: identity from the
    platform, sequence from the events already on the cohort, and the write itself.

    `title` is the caller's already-rendered problem title, carried through only so
    an outbound notification can use the same words the page does.
    `ui/components.problem_title` is the one definition of what a problem is called,
    and deriving it a second time down here would let one cohort go out under two
    names. Omit it and nothing breaks: the subject falls back to the cohort id.
    """
    who = identity.current()
    prior_all = get_dispositions()
    prior = prior_all[prior_all["cohort_id"] == cohort_id]

    lifecycle.validate_event(
        event_type,
        actor_email=who.email,
        prior_events=prior,
        decision=decision,
        reason=reason,
        review_by_date=review_by_date,
    )

    now = datetime.now()
    approver_ordinal = (
        float(len(prior[prior["event_type"] == "approved"]) + 1)
        if event_type == "approved"
        else None
    )

    row = {
        "disposition_id": str(uuid.uuid4()),
        "cohort_id": cohort_id,
        "event_seq": lifecycle.next_event_seq(prior),
        "event_type": event_type,
        "event_ts": now,
        "ingest_ts": now,
        "actor_identity": who.email,
        "actor_display_name": who.display_name,
        "actor_source": who.source,
        "decision": decision,
        "reason": reason,
        "review_by_date": review_by_date,
        "approver_ordinal": approver_ordinal,
        "executed_summary": executed_summary,
        "external_ref": external_ref,
        # Self-reported, so event_ts and executed_ts are the same instant here and
        # would differ if the owner reported an action taken earlier.
        "executed_ts": now if event_type == "executed" else pd.NaT,
        "verifying_run_id": None,
        "verification_passed": None,
        "violations_before": None,
        "violations_after": None,
        "approach_type_taken": approach_type_taken,
        "playbook_id": playbook_id,
        "event_payload": json.dumps({"recorded_by": "app", "source": _SOURCE}),
        "app_version": APP_VERSION,
    }
    _impl.write_disposition(row)
    clear_cache()
    _notify(row, title)
    return row


def notification_enabled() -> bool:
    """Is any outbound notification configured? Off unless `DQ_NOTIFY` says so."""
    return _notify_transport.enabled()


def notification_recipients(cohort) -> tuple[str, ...]:
    """Who accepting this problem would email, for the decision form to disclose.

    Through the seam rather than importing `data.notify` in a page, for the reason
    the module docstring gives: a page asks this module, never a source module.
    Empty when notification is off, which is the default and which the page renders
    as silence.
    """
    return _notify_transport.recipients_preview(cohort)


def _notify(row: dict, title: str | None) -> None:
    """Offer the event to the notification transport, which is off by default.

    Everything here is wrapped, and the result is discarded. The register write has
    already succeeded by this point: whether a message went out must not change what
    the page tells the steward about their own decision, and an exception raised here
    would surface as a failed write, which would be a lie.

    The read-back is what `data/notify.dispatch` means by `confirmed` — see that
    module for why a send is derived from an observed row rather than an assumed one.
    """
    if not _notify_transport.enabled():
        return
    try:
        confirmed = _impl.confirm_disposition(row["disposition_id"])
        all_cohorts = get_cohorts()
        match = all_cohorts[all_cohorts["cohort_id"] == row["cohort_id"]]
        cohort = None if match.empty else match.iloc[0].to_dict()
        _notify_transport.dispatch(row, cohort, title=title, confirmed=confirmed)
    except Exception:  # noqa: BLE001 — a notification can never fail a write.
        logging.getLogger("dq_app.notify").exception(
            "notification path failed after a successful register write"
        )


def promote_rule(rule_id: str, note: str) -> dict:
    """Promote a shadow rule to active by appending a new version. The app's only
    other write, and an INSERT for the same reason as the register.

    Who is authorised to do this is an open question in the spec, deliberately
    unresolved here — the app records who did it, not whether they were allowed to.
    """
    reg = get_rule_registry()
    versions = reg[reg["rule_id"] == rule_id]
    if versions.empty:
        raise WriteRejected(f"No rule {rule_id} in the registry.")
    latest = versions.sort_values("rule_version").iloc[-1]
    if latest["status"] != "shadow":
        raise WriteRejected(
            f"{rule_id} is '{latest['status']}', not 'shadow'. Only a shadow rule is "
            "promoted; changing an active rule is a new version with a changed expression."
        )

    who = identity.current()
    now = datetime.now()
    row = latest.to_dict()
    row.update(
        {
            "rule_version": int(latest["rule_version"]) + 1,
            "status": "active",
            "effective_from": now,
            "created_by": who.email,
            "created_at": now,
            "promoted_by": who.email,
            "promoted_at": now,
            "note": note,
        }
    )
    _impl.append_rule_version(row)
    clear_cache()
    return row


# The domain refuses reviews; this is the same exception under the name the page uses.
ReviewRejected = thresholds.ReviewRejected


def review_threshold(
    proposal_id: str,
    decision: str,
    *,
    reason: str | None = None,
    review_by_date: date | None = None,
) -> dict:
    """Decide a threshold proposal. The app's third write — and, on adoption, the
    second one too.

    Adopting appends a `rule_version` carrying the proposed limit, exactly as
    `promote_rule` appends one carrying a new status: same table, same grant, same
    append. The review row then records which version that was. Rejecting and
    deferring write the review row only. Validation is `domain.thresholds.
    validate_review`, pure and tested without a runtime; what happens here is the
    stamping and the two inserts.

    The order is adopt-then-record, deliberately: a review row claiming an adoption
    that never landed in the registry is the worse of the two failures.
    """
    current = get_threshold_proposal_current()
    match = current[current["proposal_id"] == proposal_id]
    if match.empty:
        raise ReviewRejected("That proposal is not the latest for its rule, or does not exist.")
    p = match.iloc[0]
    who = identity.current()
    thresholds.validate_review(
        decision, reason=reason, review_by_date=review_by_date,
        state=str(p["review_state"]))

    now = datetime.now()
    adopted_version = None
    if decision == "adopted":
        reg = get_rule_registry()
        versions = reg[reg["rule_id"] == p["rule_id"]].sort_values("rule_version")
        latest = versions.iloc[-1]
        adopted_version = int(latest["rule_version"]) + 1
        row = latest.to_dict()
        row.update({
            "rule_version": adopted_version,
            "fail_threshold_pct": float(p["proposed_threshold_pct"]),
            "effective_from": now,
            "created_by": who.email,
            "created_at": now,
            "note": (f"v{adopted_version}: fail_threshold_pct "
                     f"{float(latest['fail_threshold_pct']):g}% -> "
                     f"{float(p['proposed_threshold_pct']):g}%, adopting threshold "
                     f"proposal {proposal_id[:8]} ({p['basis']}). "
                     + (reason or "").strip()).strip(),
        })
        _impl.append_rule_version(row)

    review = {
        "review_id": str(uuid.uuid4()),
        "proposal_id": proposal_id,
        "event_ts": now,
        "ingest_ts": now,
        "actor_identity": who.email,
        "actor_display_name": who.display_name,
        "actor_source": who.source,
        "decision": decision,
        "reason": (reason or None),
        "review_by_date": review_by_date if decision == "deferred" else None,
        "adopted_rule_version": adopted_version,
        "app_version": APP_VERSION,
    }
    _impl.write_threshold_review(review)
    clear_cache()
    return review

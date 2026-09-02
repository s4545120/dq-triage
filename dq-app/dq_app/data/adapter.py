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
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import date, datetime

import pandas as pd
import streamlit as st

from dq_app.data import identity
from dq_app.domain import lifecycle

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
) -> dict:
    """Append one event to the register. The app's primary write.

    Validation lives in `domain.lifecycle.validate_event` — pure, and tested without
    a Streamlit runtime. What happens here is only the stamping: identity from the
    platform, sequence from the events already on the cohort, and the write itself.
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
    return row


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
    _impl.promote_rule(row)
    clear_cache()
    return row

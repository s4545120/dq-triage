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

**Writes.** Three tables, all `INSERT`: a register event, a new rule version (a
promotion or an adopted threshold) and a threshold review. Adding one that touched a
`prod.*` table would contradict the grants the app runs under.

Every write is guarded. The sequence or version it stamps is computed from a cached
read, so each source appends only if nothing has landed on that cohort, rule or
proposal since — and returns False otherwise, which this module turns into a
rejection the page shows. Appending blind would let two stewards put two events at
one `event_seq`, and an append-only table cannot take either back.

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
from dq_app.domain import coverage, lifecycle, onboarding, thresholds

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


@st.cache_data(**_CACHE)
def _base_monitored_tables() -> pd.DataFrame:
    return _impl.monitored_tables()


@st.cache_data(**_CACHE)
def _base_binding_proposals() -> pd.DataFrame:
    return _impl.binding_proposals()


@st.cache_data(**_CACHE)
def _base_binding_reviews() -> pd.DataFrame:
    return _impl.binding_reviews()


def _with_pending(base: pd.DataFrame, kind: str) -> pd.DataFrame:
    pending = getattr(_impl, "pending_onboarding", lambda _k: [])(kind)
    if not pending:
        return base
    return pd.concat([base, pd.DataFrame(pending)], ignore_index=True)


def get_monitored_tables() -> pd.DataFrame:
    """Every version of every row in config.monitored_table, including selections made
    in this session. Empty where the catalog has no onboarding tables."""
    return _with_pending(_base_monitored_tables(), "monitored")


def get_binding_proposals() -> pd.DataFrame:
    return _with_pending(_base_binding_proposals(), "proposal")


def get_binding_reviews() -> pd.DataFrame:
    return _with_pending(_base_binding_reviews(), "review")


# The catalog changes slowly and listing it is the slow part of Add tables, so it is
# held for an hour rather than five minutes. A table selected is still checked exactly
# (`probe_table`) at the moment it is submitted.
_CATALOG_CACHE = dict(ttl=3600, show_spinner=False)


@st.cache_data(**_CATALOG_CACHE)
def get_catalog_tables() -> pd.DataFrame:
    """Every table this principal can see in Unity Catalog, `system` excluded."""
    return _impl.catalog_tables()


@st.cache_data(**_CATALOG_CACHE)
def get_readable_tables(catalog: str, schema: str) -> set[str]:
    return _impl.readable_tables(catalog, schema)


@st.cache_data(**_CATALOG_CACHE)
def get_table_sizes(fqns: tuple[str, ...]) -> dict:
    return _impl.table_sizes(tuple(fqns))


@st.cache_data(**_CATALOG_CACHE)
def get_catalog_columns(fqn: str) -> pd.DataFrame:
    return _impl.catalog_columns(fqn)


@st.cache_data(**_CACHE)
def probe_table(fqn: str) -> dict:
    return _impl.table_probe(fqn)



@st.cache_data(**_CACHE)
def get_check_templates() -> pd.DataFrame:
    """The checks a bound column would get, by data class. Empty where the catalog has
    no template table (the fixture, dq_triage)."""
    return _impl.check_templates()


def get_onboarding_status() -> pd.DataFrame:
    """One row per selected table with its stage -- the Python twin of
    v_onboarding_status, computed so a promotion made in this session moves the stage."""
    return onboarding.derive_status(
        get_monitored_tables(), get_binding_proposals(), get_binding_reviews(),
        get_cde_registry(), get_rule_registry_current(), get_check_runs())


# --- Onboarding writes ---------------------------------------------------------------------
# Selecting a table, suggesting a binding and deciding one. Each is an append signed with
# the platform identity -- refused from a laptop against Unity Catalog, the same guard as
# promotion -- and none of them writes the element register: the apply job does that, so
# no two reviewers ever race for a cde_version.

OnboardingRejected = onboarding.OnboardingRejected


def select_table(target_table: str, row_key: list[str], owner_group: str,
                 schedule_group: str = "daily_0300", scan_mode: str = "full",
                 note: str | None = None) -> dict:
    who = identity.current()
    _require_platform_identity(who, "Selecting a table", OnboardingRejected)
    if not row_key:
        raise OnboardingRejected("Choose the column(s) that identify a row.")
    if not (owner_group or "").strip():
        raise OnboardingRejected("Name the group accountable for this table.")
    # Uncached on purpose: this is the exact check, made at the moment of the write.
    probe = _impl.table_probe(target_table)
    if not probe["readable"]:
        raise OnboardingRejected(
            f"{target_table} cannot be read with the checks' identity, so every run would "
            "fail. Ask its owner to grant SELECT first.")
    size = probe["size_bytes"]
    if size is not None and float(size) > onboarding.SCAN_LIMIT_BYTES:
        raise OnboardingRejected(
            f"{target_table} is too large for a full daily scan. Large tables wait on "
            "partition scans.")
    existing = get_monitored_tables()
    mine = existing[existing["target_table"] == target_table] if len(existing) else existing
    current = onboarding.current_monitored(existing, ("selected", "paused"))
    if len(current) and target_table in set(current["target_table"]):
        st_ = current.loc[current["target_table"] == target_table, "status"].iloc[0]
        raise OnboardingRejected(
            f"{target_table} is already onboarded" + (" and paused — resume it on its page."
                                                     if st_ == "paused" else "."))
    # Codes of every table ever onboarded, retired ones too: a reused code would give a
    # new table's checks the rule ids of a decommissioned one's.
    taken = set(onboarding.latest_monitored(existing)["table_code"]) if len(existing) else set()
    version = int(mine["table_version"].max()) + 1 if len(mine) else 1
    code = (mine.sort_values("table_version").iloc[-1]["table_code"] if len(mine)
            else onboarding.table_code(target_table, taken))
    row = {
        "target_table": target_table, "table_version": version, "table_code": code,
        "row_key": list(row_key), "owner_group": owner_group.strip(),
        "business_domain": None, "schedule_group": schedule_group, "scan_mode": scan_mode,
        "status": "selected", "effective_from": datetime.now(), "selected_by": who.email,
        "note": note,
    }
    if not _impl.write_monitored_table(row):
        clear_cache()
        raise OnboardingRejected(f"{target_table} changed since you opened it. Refresh and "
                                 "check its current state.")
    clear_cache()
    return row


def set_table_status(target_table: str, status: str, note: str) -> dict:
    """Pause, resume or retire a table: a new version of its config.monitored_table row.
    Pausing and resuming leave its checks as they are; the daily run checks only
    `selected` tables. See `decommission_table` for retiring."""
    who = identity.current()
    _require_platform_identity(who, "Changing a table's status", OnboardingRejected)
    latest = onboarding.latest_monitored(get_monitored_tables())
    row = latest[latest["target_table"] == target_table] if len(latest) else latest
    if row.empty:
        raise OnboardingRejected(f"{target_table} is not onboarded.")
    cur = row.iloc[0].to_dict()
    if status not in onboarding.TRANSITIONS.get(cur["status"], set()):
        raise OnboardingRejected(f"{target_table} is {cur['status']}; it cannot become {status}.")
    if not (note or "").strip():
        raise OnboardingRejected("Say why. The reason is kept with the table's history.")
    cur.update({"table_version": int(cur["table_version"]) + 1, "status": status,
                "effective_from": datetime.now(), "selected_by": who.email,
                "note": note.strip(), "row_key": list(cur["row_key"])})
    if not _impl.write_monitored_table(cur):
        clear_cache()
        raise OnboardingRejected(f"{target_table} changed since you opened it. Refresh and "
                                 "check its current state.")
    clear_cache()
    return cur


def decommission_table(target_table: str, note: str) -> tuple[int, list[str]]:
    """Retire a table and every check on it. Returns (checks retired, refusals).

    The table first, so the daily run stops checking it even if a check's retirement is
    refused; then every current check in one guarded append, as promotion does.
    Bindings on the element register are removed by the onboarding job, which is the
    only writer of that register. Results and Triage problems are history and stay.
    """
    set_table_status(target_table, "retired", note)
    who = identity.current()
    now = datetime.now()
    current = get_rule_registry_current()
    rows = []
    for _, r in current[current["target_table"] == target_table].iterrows():
        row = r.drop(labels=["effective_to"], errors="ignore").to_dict()
        row.update({"rule_version": int(r["rule_version"]) + 1, "status": "retired",
                    "effective_from": now, "created_by": who.email, "created_at": now,
                    "note": f"Retired with its table: {note.strip()}"})
        rows.append(row)
    landed = _impl.append_rule_versions(rows) if rows else set()
    refused = [f"{r['rule_id']}: changed since you opened it, so it was not retired."
               for r in rows if r["rule_id"] not in landed]
    clear_cache()
    return len(landed), refused


def suggest_binding(target_table: str, target_column: str, cde_id: str, reason: str) -> dict:
    who = identity.current()
    _require_platform_identity(who, "Suggesting a binding", OnboardingRejected)
    if not (reason or "").strip():
        raise OnboardingRejected("Say what makes you sure. The owner decides on it.")
    cdes = get_cde_registry_current()
    if cde_id not in set(cdes["cde_id"]):
        raise OnboardingRejected(f"{cde_id} is not a registered element.")
    bound = {(b["target_table"], b["target_column"])
             for b in coverage.bound_columns(get_cde_registry())}
    if (target_table, target_column) in bound:
        raise OnboardingRejected(f"{target_column} is already bound.")
    row = {
        "proposal_id": str(uuid.uuid4()), "proposed_at": datetime.now(),
        "target_table": target_table, "target_column": target_column, "cde_id": cde_id,
        "method": "suggested", "confidence": 1.0, "evidence": reason.strip(),
        "proposed_by": who.email,
    }
    if not _impl.write_binding_proposal(row):
        clear_cache()
        raise OnboardingRejected("The suggestion was not recorded. Refresh and try again.")
    clear_cache()
    return row


def self_approval_waived() -> bool:
    """Whether this deployment waives the second-approver rule on binding suggestions.
    Off unless DQ_ONBOARD_ALLOW_SELF_APPROVAL=1 -- set on the dq-onboard test app only.
    A self-approval made under it is marked in its reason (`onboarding.WAIVER_MARK`)."""
    return os.getenv("DQ_ONBOARD_ALLOW_SELF_APPROVAL", "").strip() == "1"


def review_binding(proposal_id: str, decision: str, reason: str | None = None) -> dict:
    who = identity.current()
    _require_platform_identity(who, "Deciding a binding", OnboardingRejected)
    open_p = onboarding.open_proposals(get_binding_proposals(), get_binding_reviews(),
                                       get_cde_registry())
    match = open_p[open_p["proposal_id"] == proposal_id] if len(open_p) else open_p
    if match.empty:
        raise OnboardingRejected("That proposal is already decided, or no longer open.")
    proposal = match.iloc[0].to_dict()
    waived = self_approval_waived()
    onboarding.validate_review(proposal, who.email, decision, reason, allow_self=waived)
    reason = (reason or "").strip() or None
    if waived and decision == "approved" and onboarding.is_own(proposal, who.email):
        reason = f"{onboarding.WAIVER_MARK} {reason or ''}".strip()
    row = {"proposal_id": proposal_id, "decision": decision, "reviewed_by": who.email,
           "reviewed_at": datetime.now(), "reason": reason}
    if not _impl.write_binding_review(row):
        clear_cache()
        raise OnboardingRejected("Someone decided this proposal since you opened it. "
                                 "The page has been refreshed.")
    clear_cache()
    return row


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
    if not _impl.write_disposition(row):
        clear_cache()
        raise WriteRejected(
            "Someone else recorded a decision on this problem after you opened it, so "
            "yours was not written. The page has been refreshed; read what they recorded "
            "and decide again.")
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


def _require_platform_identity(who: identity.Identity, what: str, exc=None) -> None:
    """Refuse a durable rule-registry write the platform has not vouched for.

    The register is protected from a laptop by two CHECK constraints on
    `actor_source`. The rule registry has no such column: run against Unity Catalog
    from a laptop, a promotion would append a version signed `created_by` /
    `promoted_by` with a demo persona's address, indistinguishable from a real one.
    Session-only writes on the fixture are a demo and stay allowed.
    """
    if writes_are_durable() and not who.is_platform:
        raise (exc or WriteRejected)(
            f"{what} signs the rule registry with your name, and there is no platform "
            "identity here -- this is a laptop, not the deployed app. Deploy to do it.")


def _promotion_row(rule_id: str, note: str, who, now) -> dict:
    """The new version a promotion appends. Refuses a rule that is not in shadow."""
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
    return row


def promote_rule(rule_id: str, note: str) -> dict:
    """Promote a shadow rule to active by appending a new version. The app's only
    other write, and an INSERT for the same reason as the register.

    Who is authorised to do this is an open question in the spec, deliberately
    unresolved here — the app records who did it, not whether they were allowed to.
    """
    who = identity.current()
    _require_platform_identity(who, "Promoting a rule")
    row = _promotion_row(rule_id, note, who, datetime.now())
    if not _impl.append_rule_version(row):
        clear_cache()
        raise WriteRejected(
            f"{rule_id} gained a new version after you opened it, so the promotion was "
            "not written. The page has been refreshed; check its current state.")
    clear_cache()
    return row


def promote_rules(rule_ids: list[str], note: str) -> tuple[list[str], list[str]]:
    """Promote several shadow rules in one append. Returns (promoted, refused reasons).

    One statement instead of one per rule: promoting a table's 21 checks one at a time
    took over a minute on the deployed app. The guard is still per rule -- a rule that
    gained a version since the page was read is refused, and only that rule.
    """
    who = identity.current()
    _require_platform_identity(who, "Promoting rules")
    now = datetime.now()
    rows, refused = [], []
    for rid in rule_ids:
        try:
            rows.append(_promotion_row(rid, note, who, now))
        except WriteRejected as exc:
            refused.append(f"{rid}: {exc}")
    landed = _impl.append_rule_versions(rows) if rows else set()
    for r in rows:
        if r["rule_id"] not in landed:
            refused.append(f"{r['rule_id']}: gained a new version after you opened it, so "
                           "its promotion was not written.")
    clear_cache()
    return [r["rule_id"] for r in rows if r["rule_id"] in landed], refused


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
    if decision == "adopted":
        _require_platform_identity(who, "Adopting a limit", ReviewRejected)
    thresholds.validate_review(
        decision, reason=reason, review_by_date=review_by_date,
        state=str(p["review_state"]))

    reviews = get_threshold_reviews()
    reviews_seen = int((reviews["proposal_id"] == proposal_id).sum())
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
        if not _impl.append_rule_version(row):
            clear_cache()
            raise ReviewRejected(
                f"{p['rule_id']} gained a new version after you opened this proposal, so "
                "nothing was written. The page has been refreshed; review it again.")

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
    if not _impl.write_threshold_review(review, reviews_seen=reviews_seen):
        clear_cache()
        if adopted_version is not None:
            # The limit landed and the record of deciding it did not: someone reviewed
            # the same proposal in between. The registry row names the proposal in its
            # note, so the adoption is traceable, but the reviewer has to be told.
            raise ReviewRejected(
                f"The new limit was written as {p['rule_id']} v{adopted_version}, but "
                "someone else reviewed this proposal at the same moment, so your review "
                "row was not. Their decision is now the one on record; reconcile the two "
                "before acting further.")
        raise ReviewRejected(
            "Someone else reviewed this proposal after you opened it, so your decision "
            "was not written. The page has been refreshed; read theirs.")
    clear_cache()
    return review

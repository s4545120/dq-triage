"""Threshold proposals — where each rule's latest proposal has got to, and what a
reviewer may do about it.

Pure. No Streamlit, no I/O.

**`derive_proposal_current` is a labelled COPY of `v_threshold_proposal_current`**
(`sql/ddl/14_views_threshold.sql`), for the same reason `lifecycle.derive_cohort_current`
copies `v_cohort_current`: a review recorded in this session has to change the
proposal's state on the page before any warehouse could re-run the view.
`tests/test_thresholds.py` pins this fold to the view's shipped output row for row.
Change the view and that test says whether the copy kept up.

**What a proposal is.** The threshold job's advice on one rule's `fail_threshold_pct`,
made against the tolerance the CDE register declares on the element (the ceiling)
and the run history. Detection advice, about the rule; nothing here touches a cohort
or the disposition register.

**What a review is.** Adopt, reject or defer. Adopting appends a rule version
carrying the proposed limit — the same append the app performs to promote a shadow
rule — and records which version. Rejecting and deferring are recorded on
`results.threshold_review` and nowhere else; without that row a rejected proposal is
indistinguishable from one nobody has looked at.
"""

from __future__ import annotations

import pandas as pd

BASES = ("element_tolerance", "run_history", "both", "unchanged")
DECISIONS = ("adopted", "rejected", "deferred")
STATES = ("open", "deferred", "adopted", "rejected", "in_force", "no_change")

# The one decision a state permits. Only an open or deferred proposal is decided;
# everything else is history, or advice that asked for nothing.
DECIDABLE = ("open", "deferred")


class ReviewRejected(ValueError):
    """A review the domain rules refuse. Raised before anything is written."""


def validate_review(decision: str, *, reason: str | None, review_by_date,
                    state: str) -> None:
    """Refuse a review before it is written, with a sentence for the person.

    The table's CHECK constraints, enforced early so a driver error becomes a
    sentence; and the one thing a CHECK cannot see, which is that the proposal is
    in a state that admits a decision at all. Identity is not checked here: the
    table's `threshold_review_has_identity` constraint refuses a laptop stand-in in
    the workspace, and locally the write is session-only and labelled as such —
    the same arrangement the disposition register has.
    """
    if decision not in DECISIONS:
        raise ReviewRejected(f"'{decision}' is not a decision. Adopt, reject or defer.")
    if state not in DECIDABLE:
        raise ReviewRejected(
            f"This proposal is {state.replace('_', ' ')}; there is nothing to decide. "
            "A new proposal from the next pass of the threshold job reopens it.")
    if decision in ("rejected", "deferred") and not (reason or "").strip():
        raise ReviewRejected(f"A '{decision}' decision requires a reason.")
    if decision == "deferred" and review_by_date is None:
        raise ReviewRejected(
            "A deferred proposal requires a review-by date, or it disappears instead "
            "of coming back.")


def derive_proposal_current(
    proposals: pd.DataFrame, reviews: pd.DataFrame, rule_registry: pd.DataFrame,
) -> pd.DataFrame:
    """One row per rule: its latest proposal with the latest review folded in.

    `review_state`: `no_change` (the advice was keep), `open`, `adopted`, `rejected`,
    `deferred` (with `review_by_date`), `in_force` (the registry already carries the
    proposed limit, by adoption or otherwise). No `current_date()` anywhere, on
    purpose: whether a deferral is due is the page's to say, so this fold reproduces
    the view on any day.
    """
    cols = ["proposal_id", "proposal_run_id", "proposed_ts", "rule_id", "rule_version",
            "rule_name", "rule_type", "severity", "owner_group", "cde_id", "target_table",
            "target_column", "current_threshold_pct", "proposed_threshold_pct",
            "registry_threshold_pct", "tolerance_pct", "basis", "rationale", "reviewer",
            "runs_observed", "pct_min", "pct_median", "pct_p90", "pct_max",
            "runs_breaching", "latest_violation_pct", "model_endpoint", "latest_decision",
            "latest_review_ts", "latest_reviewer", "latest_reason", "review_by_date",
            "adopted_rule_version", "review_state"]
    if proposals is None or proposals.empty:
        return pd.DataFrame(columns=cols)

    reg = rule_registry.sort_values("rule_version").groupby("rule_id").tail(1)
    reg = reg[reg["status"] != "retired"].set_index("rule_id")
    latest_p = (proposals.sort_values(["proposed_ts", "proposal_id"], ascending=[False, True])
                         .groupby("rule_id").head(1))
    latest_r = pd.DataFrame()
    if reviews is not None and len(reviews):
        latest_r = (reviews.sort_values(["event_ts", "review_id"], ascending=[False, True])
                           .groupby("proposal_id").head(1).set_index("proposal_id"))

    out = []
    for _, p in latest_p.iterrows():
        r = latest_r.loc[p["proposal_id"]] if p["proposal_id"] in latest_r.index else None
        g = reg.loc[p["rule_id"]] if p["rule_id"] in reg.index else None
        registry_pct = None if g is None else float(g["fail_threshold_pct"])
        decision = None if r is None else r["decision"]
        if p["basis"] == "unchanged":
            state = "no_change"
        elif decision == "adopted":
            state = "adopted"
        elif decision == "rejected":
            state = "rejected"
        elif decision == "deferred":
            state = "deferred"
        elif registry_pct is not None and registry_pct == float(p["proposed_threshold_pct"]):
            state = "in_force"
        else:
            state = "open"
        out.append(dict(
            proposal_id=p["proposal_id"], proposal_run_id=p["proposal_run_id"],
            proposed_ts=p["proposed_ts"], rule_id=p["rule_id"], rule_version=p["rule_version"],
            rule_name=None if g is None else g["rule_name"],
            rule_type=None if g is None else g["rule_type"],
            severity=None if g is None else g["severity"],
            owner_group=None if g is None else g["owner_group"],
            cde_id=p["cde_id"], target_table=p["target_table"], target_column=p["target_column"],
            current_threshold_pct=p["current_threshold_pct"],
            proposed_threshold_pct=p["proposed_threshold_pct"],
            registry_threshold_pct=registry_pct,
            tolerance_pct=p["tolerance_pct"], basis=p["basis"], rationale=p["rationale"],
            reviewer=p["reviewer"], runs_observed=p["runs_observed"], pct_min=p["pct_min"],
            pct_median=p["pct_median"], pct_p90=p["pct_p90"], pct_max=p["pct_max"],
            runs_breaching=p["runs_breaching"],
            latest_violation_pct=p["latest_violation_pct"],
            model_endpoint=p["model_endpoint"],
            latest_decision=decision,
            latest_review_ts=None if r is None else r["event_ts"],
            latest_reviewer=None if r is None else r["actor_display_name"],
            latest_reason=None if r is None else r["reason"],
            review_by_date=None if r is None else r["review_by_date"],
            adopted_rule_version=None if r is None else r["adopted_rule_version"],
            review_state=state,
        ))
    return pd.DataFrame(out, columns=cols)


def summary(current: pd.DataFrame) -> dict:
    """Counts by state, for the tiles."""
    counts = current["review_state"].value_counts().to_dict() if len(current) else {}
    return {s: int(counts.get(s, 0)) for s in STATES} | {"proposals": int(len(current))}

"""The threshold job's output, hand-authored, and the fixture twin of its view.

Companion to `build_fixtures.py` the way `cdes.py` and `profile.py` are. On Databricks
`notebooks/06_suggest_thresholds.ipynb` writes `results.threshold_proposal` from one
model call per registered element; here the same rows are written by hand from what
the run history actually shows, so the advice is defensible -- but no model produced
it, `model_endpoint` says so, and `model_input_payload` is a stub.

WHAT A PROPOSAL IS. Advice on one rule's fail_threshold_pct, made from two things and
labelled with which: the tolerance the CDE register declares on the element the rule
monitors (organisational -- the ceiling), and where violation_pct has sat across the
run history (empirical). It is DETECTION advice, about the rule. It has nothing to do
with triage, a cohort or a disposition, and nothing here reads those.

WHAT THE BUILDER FILLS IN, SO THE HAND CANNOT MISSTATE IT. The current limit and the
rule_version come off the rule registry; the tolerance comes off the element; the
history statistics are computed from results.check_run. The hand supplies only the
proposed figure, the basis and the rationale. A proposal above the element's
tolerance is refused here, as it is by the notebook's validator and the table's
CHECK constraint.

Nine proposals: three that move a limit and six that say keep, which is the shape to
expect. Two are decided -- one rejected, one deferred -- and one is left open for the
app's write-path test to adopt.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pandas as pd

MODEL_ENDPOINT = None          # hand-authored: no endpoint produced these
PROPOSAL_JOB = "job:dq-threshold-advisor"
BASES = ("element_tolerance", "run_history", "both", "unchanged")

# rule_id -> (proposed_threshold_pct, basis, rationale)
PROPOSALS: dict[str, tuple[float, str, str]] = {
    "CTCT_MOBL_NOT_NULL": (0.5, "element_tolerance",
        "A missing contact mobile is a collection gap, and Customer contact mobile "
        "number declares a 0.5% tolerance for it. The rate has sat between 1.6% and "
        "1.9% on all 40 runs, so at 0.5% the rule still breaches today and nothing is "
        "hidden; what changes is that the contactability campaign has a line to get "
        "under, rather than a rule that keeps breaching on three rows forever."),
    "CTCT_PHN_FMT": (1.0, "both",
        "Customer contact landline number is medium criticality with a 2.0% tolerance, "
        "and the history sits at a 1.9% median with a 2.8% peak. A limit at the full "
        "2.0% would have passed 12 of the 27 breaching runs, including the run that "
        "closed this rule before it recurred. 1.0% sits under the recurrence level so "
        "the rule keeps reporting it, and above zero so one malformed landline no "
        "longer raises a problem."),
    "SUBS_NTWK_NOT_NULL": (2.0, "element_tolerance",
        "Network technology declares a 2.0% tolerance and the rate has sat between "
        "1.4% and 1.7% on every run. At 2.0% the rule passes today, and that is what "
        "the tolerance means: the business has said this share of services may lack "
        "the value. The figure is the medium-tier default rather than one Subscription "
        "has agreed to, which is what the reviewer should confirm before adopting."),
    "SUBS_IMEI_NOT_NULL": (0.0, "unchanged",
        "The breach is scope, not level. Every one of the 200 rows is a fixed-broadband "
        "service that never carries an IMEI, and scoped to PROD_TYPE_KEY <> 0 the same "
        "rule returns zero. Raising the limit to the 20% the history sits at would pass "
        "200 rows of nothing and blind the rule to a real handset without an IMEI. "
        "Device IMEI declares a 2.0% tolerance; keep 0.0 and fix the scope."),
    "SUBS_PRIM_ACCT_NOT_ZERO": (0.0, "unchanged",
        "Same defect. All 500 rows are prepaid services with no billing account by "
        "definition, and the twin rule scoped to POSTPAID returns zero. A limit of 50% "
        "is not a tolerance, it is the prepaid share of the base. Primary billing "
        "account declares 0.5%; keep 0.0 and add the scope filter."),
    "CTCT_EML_FMT": (0.0, "unchanged",
        "Zero violations on every run to 2026-08-27 and 240 on every run since: the "
        "population's normal is zero and the breach is a release, not a rate. A limit "
        "above zero would hide the next one. Customer email address declares a 0.5% "
        "tolerance; that is the ceiling for the element, not a target for a rule "
        "whose baseline is clean."),
    "SUBS_MSISDN_SENTINEL": (0.0, "unchanged",
        "Mobile service number is tiered critical with a declared tolerance of 0.0%, "
        "and a placeholder in place of a number is never an acceptable value. Twelve "
        "rows at 1.2% on every run is a stuck provisioning path, not a rate to "
        "tolerate."),
    "CTCT_BRTH_PLAUSIBLE": (0.0, "unchanged",
        "27 contacts aged 16-17 is 2.7%, above the element's 0.5% tolerance, and the "
        "question is whether they are minors or mis-keyed years -- a consent and "
        "credit-check review, not a limit. A limit at 3% would answer it by hiding "
        "them. Keep 0.0 until Compliance has looked."),
    "XREF_NAME_AGREEMENT": (0.0, "unchanged",
        "Customer name is a KYC element with a 0.5% tolerance, and two rows is 0.2%: "
        "a limit at the tolerance would pass them unseen. If the two are deed-poll "
        "changes the right disposition is no_action on the rows, not a limit that "
        "stops the rule reporting the next pair. Keep 0.0."),
}


def _stats(runs: pd.DataFrame, rule_id: str, threshold: float) -> dict:
    h = runs[(runs.rule_id == rule_id) & runs.status.isin(["pass", "breach"])]
    pct = h.violation_pct.astype(float)
    latest = h.sort_values("run_ts").iloc[-1] if len(h) else None
    return dict(
        runs_observed=int(len(h)),
        pct_min=round(float(pct.min()), 4) if len(h) else None,
        pct_median=round(float(pct.median()), 4) if len(h) else None,
        pct_p90=round(float(pct.quantile(0.9)), 4) if len(h) else None,
        pct_max=round(float(pct.max()), 4) if len(h) else None,
        runs_breaching=int((h.status == "breach").sum()),
        latest_violation_pct=(round(float(latest.violation_pct), 4)
                              if latest is not None else None),
    )


def build_threshold_proposals(
    runs: pd.DataFrame, rule_registry: pd.DataFrame, cde_registry: pd.DataFrame,
    proposed_ts, det_uuid,
) -> pd.DataFrame:
    """results.threshold_proposal. One pass, nine rules."""
    reg = (rule_registry.sort_values("rule_version").groupby("rule_id").tail(1)
                        .set_index("rule_id"))
    cdes = (cde_registry.sort_values("cde_version").groupby("cde_id").tail(1)
                        .set_index("cde_id"))
    run_id = det_uuid("threshold-run", proposed_ts.date().isoformat())
    rows = []
    for rule_id, (proposed, basis, rationale) in PROPOSALS.items():
        r = reg.loc[rule_id]
        tol = cdes.loc[r.cde_id, "tolerance_pct"]
        tol = None if pd.isna(tol) else float(tol)
        current = float(r.fail_threshold_pct)
        assert basis in BASES, (rule_id, basis)
        assert (basis == "unchanged") == (float(proposed) == current), \
            f"{rule_id}: basis {basis!r} but {proposed} vs {current}"
        assert tol is None or float(proposed) <= tol, \
            f"{rule_id}: {proposed}% is above the {tol}% tolerance {r.cde_id} declares"
        rows.append(dict(
            proposal_id=det_uuid("threshold", run_id, rule_id),
            proposal_run_id=run_id,
            proposed_ts=proposed_ts,
            rule_id=rule_id,
            rule_version=int(r.rule_version),
            cde_id=r.cde_id,
            target_table=r.target_table,
            target_column=None if pd.isna(r.target_column) else r.target_column,
            current_threshold_pct=current,
            proposed_threshold_pct=float(proposed),
            tolerance_pct=tol,
            basis=basis,
            rationale=rationale,
            reviewer=r.owner_group,
            **_stats(runs, rule_id, current),
            model_endpoint=MODEL_ENDPOINT,
            model_input_payload=json.dumps({
                "_fixture": "hand-authored, no model invoked",
                "rule_id": rule_id, "cde_id": r.cde_id,
            }),
            job_run_id=det_uuid("threshold-job", proposed_ts.date().isoformat()),
        ))
    return pd.DataFrame(rows)


def build_threshold_reviews(
    proposals: pd.DataFrame, det_uuid, steward_a, steward_b, app_version: str,
) -> pd.DataFrame:
    """Two decisions, neither an adoption. Adopting also appends a rule version,
    and the fixture registry is built before the proposals exist; the adoption path
    is exercised through the app instead, by tests/test_thresholds.py."""
    by_rule = proposals.set_index("rule_id")
    phn, ntwk = by_rule.loc["CTCT_PHN_FMT"], by_rule.loc["SUBS_NTWK_NOT_NULL"]
    t0 = pd.Timestamp(phn.proposed_ts)
    rows = [
        dict(
            review_id=det_uuid("threshold-review", phn.proposal_id, "1"),
            proposal_id=phn.proposal_id,
            event_ts=t0 + timedelta(days=1, hours=3),
            ingest_ts=t0 + timedelta(days=1, hours=3),
            actor_identity=steward_a[0], actor_display_name=steward_a[1],
            actor_source="obo_user",
            decision="rejected",
            reason=("Recurrence on this rule is under a root-cause pass (COH-D). Not "
                    "moving the limit while the rule is the only thing telling us it "
                    "came back."),
            review_by_date=None, adopted_rule_version=None, app_version=app_version,
        ),
        dict(
            review_id=det_uuid("threshold-review", ntwk.proposal_id, "1"),
            proposal_id=ntwk.proposal_id,
            event_ts=t0 + timedelta(days=2, hours=5),
            ingest_ts=t0 + timedelta(days=2, hours=5),
            actor_identity=steward_b[0], actor_display_name=steward_b[1],
            actor_source="obo_user",
            decision="deferred",
            reason=("2.0% is the tier default, not a figure Subscription has agreed. "
                    "Taking it to the domain forum before adopting."),
            review_by_date=(t0 + timedelta(days=60)).date(),
            adopted_rule_version=None, app_version=app_version,
        ),
    ]
    return pd.DataFrame(rows)


def proposal_current(
    proposals: pd.DataFrame, reviews: pd.DataFrame, rule_registry: pd.DataFrame,
) -> pd.DataFrame:
    """Fixture twin of v_threshold_proposal_current (sql/ddl/14_views_threshold.sql).
    The view is the definition; the app's copy in dq-app/dq_app/domain/thresholds.py
    is pinned to this output by a conformance test."""
    reg = (rule_registry.sort_values("rule_version").groupby("rule_id").tail(1))
    reg = reg[reg.status != "retired"].set_index("rule_id")
    latest_p = (proposals.sort_values(["proposed_ts", "proposal_id"], ascending=[False, True])
                         .groupby("rule_id").head(1))
    latest_r = (reviews.sort_values(["event_ts", "review_id"], ascending=[False, True])
                       .groupby("proposal_id").head(1).set_index("proposal_id")
                if len(reviews) else pd.DataFrame())
    out = []
    for _, p in latest_p.iterrows():
        r = latest_r.loc[p.proposal_id] if p.proposal_id in latest_r.index else None
        g = reg.loc[p.rule_id] if p.rule_id in reg.index else None
        registry_pct = None if g is None else float(g.fail_threshold_pct)
        decision = None if r is None else r.decision
        if p.basis == "unchanged":
            state = "no_change"
        elif decision == "adopted":
            state = "adopted"
        elif decision == "rejected":
            state = "rejected"
        elif decision == "deferred":
            state = "deferred"
        elif registry_pct is not None and registry_pct == float(p.proposed_threshold_pct):
            state = "in_force"
        else:
            state = "open"
        out.append(dict(
            proposal_id=p.proposal_id, proposal_run_id=p.proposal_run_id,
            proposed_ts=p.proposed_ts, rule_id=p.rule_id, rule_version=p.rule_version,
            rule_name=None if g is None else g.rule_name,
            rule_type=None if g is None else g.rule_type,
            severity=None if g is None else g.severity,
            owner_group=None if g is None else g.owner_group,
            cde_id=p.cde_id, target_table=p.target_table, target_column=p.target_column,
            current_threshold_pct=p.current_threshold_pct,
            proposed_threshold_pct=p.proposed_threshold_pct,
            registry_threshold_pct=registry_pct,
            tolerance_pct=p.tolerance_pct, basis=p.basis, rationale=p.rationale,
            reviewer=p.reviewer, runs_observed=p.runs_observed, pct_min=p.pct_min,
            pct_median=p.pct_median, pct_p90=p.pct_p90, pct_max=p.pct_max,
            runs_breaching=p.runs_breaching, latest_violation_pct=p.latest_violation_pct,
            model_endpoint=p.model_endpoint,
            latest_decision=decision,
            latest_review_ts=None if r is None else r.event_ts,
            latest_reviewer=None if r is None else r.actor_display_name,
            latest_reason=None if r is None else r.reason,
            review_by_date=None if r is None else r.review_by_date,
            adopted_rule_version=None if r is None else r.adopted_rule_version,
            review_state=state,
        ))
    return pd.DataFrame(out)

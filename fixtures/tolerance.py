"""Element tolerance: the fixture twins of the escalation views, and the threshold
job's per-element advice, hand-authored.

Companion to `build_fixtures.py` the way `thresholds.py` is.

THE TWINS. `element_tolerance` and `check_escalation` are the fixture side of
`v_element_tolerance` and `v_check_escalation` (sql/ddl/20_views_tolerance.sql);
`proposal_current` of `v_tolerance_proposal_current`. The views are the definition.
The app's copies in dq-app/dq_app/domain/tolerance.py are pinned to this output by
tests/test_tolerance.py, and were diffed against the SQL on the live workspace on
2026-10-08 (748 element rows and 761 breach rows, no difference). Written
independently of the app's, so the test compares two readings of the view.

THE ADVICE. On Databricks `notebooks/06_suggest_thresholds.ipynb` writes
`results.tolerance_proposal`, one row per element per pass. Here the same rows are
written by hand from what the run history shows. No model produced them,
`model_endpoint` says so, and `model_input_payload` is a stub. The builder fills in
every figure -- the current tolerance, the version and the statistics; the hand
supplies only the advice, the proposed figure for a tightening, and the rationale. A
proposal that raises a tolerance is refused here, as it is by the notebook and the
table.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pandas as pd

MODEL_ENDPOINT = None          # hand-authored: no endpoint produced these
ADVICE = ("keep", "tighten", "review")
P1 = "P1_block"

# cde_id -> (advice, proposed tolerance for a tightening else None, rationale)
PROPOSALS: dict[str, tuple[str, float | None, str]] = {
    "CDE_BILLING_ACCOUNT": ("keep", None,
        "The rule on this element is in scope mismatch: it counts prepaid services, "
        "which legitimately carry no primary account, so roughly half the rows fail on "
        "every run. That figure measures the rule, not the data. Fix the rule's scope "
        "(COH-B) before anyone reads this element against a tolerance."),
    "CDE_DEVICE_IMEI": ("keep", None,
        "In scope mismatch, like the billing account: about 20% fail on every run "
        "because fixed-broadband services have no handset. The tolerance is not the "
        "question until the rule is scoped (COH-B)."),
    "CDE_CUST_NAME": ("tighten", 0.3,
        "Failures have sat between 0.1% and 0.2% on all 40 runs against a 0.5% "
        "tolerance. At 0.5% a regression to more than double today's rate would be "
        "held back from triage. 0.3% is above every run so far, so nothing escalates "
        "today, and below the point where a real change would hide."),
    "CDE_RECORD_LIFECYCLE": ("tighten", 1.0,
        "Never more than 0.55% failing in 40 runs, against a 2.0% tolerance that is "
        "the medium-tier default rather than a figure anyone agreed. 1.0% keeps every "
        "run so far inside and halves what could go unescalated."),
    "CDE_NETWORK_TECH": ("keep", None,
        "1.4% to 1.7% failing on every run, inside the 2.0% tolerance, so its one "
        "breaching check is held back from triage. That is the tolerance doing what it "
        "says. Keep it, but it is the tier default: if Subscription has a different "
        "figure in mind, that figure belongs in the register."),
    "CDE_SUBS_KEY": ("keep", None,
        "Zero tolerance, and nothing has failed in 40 runs. Nothing to tighten."),
    "CDE_CUST_KEY": ("keep", None,
        "Zero tolerance. 17 of 40 runs were outside it and the latest is clean. A key "
        "has no acceptable failure rate, so there is nothing to change."),
    "CDE_CUST_EMAIL": ("keep", None,
        "Inside 0.5% until 28 August, outside on all six runs since at 5.8%. That is a "
        "regression and it is in triage (COH-A); a tolerance is not the answer to it."),
    "CDE_BILL_OFFER": ("keep", None,
        "Outside on 23 of 40 runs, at up to 14.2%, but clean on the latest. The "
        "excursions were a defect that has been fixed, not a level the business has "
        "to accept."),
    "CDE_SIM_SERIAL": ("keep", None,
        "Outside on 19 of 40 runs at up to 6.75%, clean on the latest. Same shape as "
        "the billing offer: a fixed defect, not a tolerance question."),
    "CDE_SUBS_STATUS": ("keep", None,
        "Outside on 14 of 40 runs at up to 12%, clean on the latest."),
    "CDE_CUST_DOB": ("review", None,
        "About 2% failing on every one of 40 runs against a 0.5% tolerance. Either the "
        "unparseable and implausible dates get fixed, or the business accepts a higher "
        "share. That is the business's decision; this job does not raise a tolerance."),
    "CDE_CUST_MOBILE": ("review", None,
        "Outside 0.5% on all 40 runs, at 0.8% to 2.6%. The missing mobiles are a "
        "collection gap (COH-D). Decide whether the gap is being closed or accepted."),
    "CDE_CUST_MSISDN": ("review", None,
        "Critical, zero tolerance, and 1% to 1.6% failing on every run. Every failure "
        "escalates. If that is right, the work is the data; if some placeholder numbers "
        "are expected, the register should say how many."),
    "CDE_SUBS_ACTIVATION": ("review", None,
        "1.0% failing on all 40 runs against 0.5%: the same ten subscriptions with an "
        "activation after their opening. Fix them or accept them, but say which."),
    "CDE_CUST_IDENT_DOC": ("review", None,
        "Zero tolerance, outside on 30 of 40 runs at up to 1.9%. Clean on the latest "
        "run, but a zero tolerance on a presence check that has failed most days needs "
        "confirming."),
    "CDE_CUST_LANDLINE": ("review", None,
        "Outside 2.0% on 19 of 40 runs, including the latest at 2.4%. The landline "
        "format defect keeps recurring around the line; decide whether 2.0% is the "
        "line or the defect is fixed."),
    "CDE_BENEFIT_TEXT": ("keep", None,
        "Nothing measures this element yet: its only rule is in shadow. No basis for "
        "advice until a check runs."),
    "CDE_PREF_LANGUAGE": ("keep", None,
        "Nothing measures this element yet: its only rule is in shadow. No basis for "
        "advice until a check runs."),
}


def _as_list(v) -> list:
    return [] if v is None else list(v)


def element_tolerance(runs: pd.DataFrame, cde_cov: pd.DataFrame,
                      cde_registry: pd.DataFrame) -> pd.DataFrame:
    """Fixture twin of v_element_tolerance."""
    reg = cde_registry.sort_values("cde_version").groupby("cde_id").tail(1)
    reg = reg[reg.status != "retired"].set_index("cde_id")
    pairs = (cde_cov[["cde_id", "rule_ids"]]
             .assign(rule_id=lambda d: d.rule_ids.map(_as_list))
             .explode("rule_id").dropna(subset=["rule_id"])[["cde_id", "rule_id"]]
             .drop_duplicates())
    disputed = set(cde_cov.loc[cde_cov.coverage_gap == "scope_mismatch", "cde_id"])
    raised = (runs[runs.status.isin(["pass", "breach"])]
              .sort_values("result_id").drop_duplicates(["run_id", "rule_id"]))
    j = raised.merge(pairs, on="rule_id")
    g = (j.groupby(["run_id", "cde_id"])
          .agg(run_ts=("run_ts", "max"), checks_raised=("rule_id", "size"),
               rows_evaluated=("rows_scanned", "sum"), rows_failed=("violation_count", "sum"))
          .reset_index())
    g = g[g.cde_id.isin(reg.index)]
    g["cde_name"] = g.cde_id.map(reg.cde_name)
    g["criticality"] = g.cde_id.map(reg.criticality)
    g["score_pct"] = 100.0 * (g.rows_evaluated - g.rows_failed) / g.rows_evaluated
    g["tolerance_pct"] = g.cde_id.map(reg.tolerance_pct).astype(float)
    g["target_pct"] = 100.0 - g.tolerance_pct
    g["scope_disputed"] = g.cde_id.isin(disputed)
    g["within_tolerance"] = (g.tolerance_pct.notna() & ~g.scope_disputed
                             & (g.score_pct >= g.target_pct - 1e-9))
    return g[["run_id", "run_ts", "cde_id", "cde_name", "criticality", "checks_raised",
              "rows_evaluated", "rows_failed", "score_pct", "tolerance_pct", "target_pct",
              "scope_disputed", "within_tolerance"]].sort_values(["cde_id", "run_ts"])\
            .reset_index(drop=True)


def check_escalation(runs: pd.DataFrame, cde_cov: pd.DataFrame,
                     element_tol: pd.DataFrame) -> pd.DataFrame:
    """Fixture twin of v_check_escalation. Every breach escalates since 2026-10-22."""
    pairs = (cde_cov[["cde_id", "rule_ids"]]
             .assign(rule_id=lambda d: d.rule_ids.map(_as_list))
             .explode("rule_id").dropna(subset=["rule_id"])[["cde_id", "rule_id"]]
             .drop_duplicates())
    b = (runs[runs.status == "breach"].sort_values("result_id")
         .drop_duplicates(["run_id", "rule_id"]))
    b = b[["run_id", "run_ts", "rule_id", "severity", "violation_count", "rows_scanned"]]
    b = b.merge(pairs, on="rule_id", how="left")
    t = element_tol[["run_id", "cde_id", "score_pct", "target_pct", "within_tolerance"]]
    b = b.merge(t, on=["run_id", "cde_id"], how="left")
    inside = b.within_tolerance.fillna(False).astype(bool)
    # Since 2026-10-22 every breach escalates: the threshold is the rule's own.
    held = inside & False
    return pd.DataFrame({
        "run_id": b.run_id, "run_ts": b.run_ts, "rule_id": b.rule_id,
        "severity": b.severity, "violation_count": b.violation_count,
        "rows_scanned": b.rows_scanned, "cde_id": b.cde_id,
        "element_score_pct": b.score_pct, "element_target_pct": b.target_pct,
        "element_within_tolerance": inside, "escalates": ~held,
        "held_reason": held.map({True: "element_within_tolerance", False: None}),
    }).sort_values(["run_ts", "rule_id"]).reset_index(drop=True)


def build_tolerance_proposals(element_tol: pd.DataFrame, cde_registry: pd.DataFrame,
                              proposed_ts, det_uuid) -> pd.DataFrame:
    """One proposal per registered element, figures off the register and the history."""
    reg = cde_registry.sort_values("cde_version").groupby("cde_id").tail(1)
    reg = reg[reg.status != "retired"].set_index("cde_id")
    assert set(PROPOSALS) == set(reg.index), (
        f"advice for {sorted(set(PROPOSALS) ^ set(reg.index))} is missing or extra")
    run_id = det_uuid("tolerance-run", proposed_ts.isoformat())
    rows = []
    for cde_id, (advice, proposed, rationale) in sorted(PROPOSALS.items()):
        e = reg.loc[cde_id]
        cur = None if pd.isna(e.tolerance_pct) else float(e.tolerance_pct)
        assert advice in ADVICE, advice
        new = proposed if advice == "tighten" else cur
        if advice == "tighten":
            assert cur is not None and new < cur, f"{cde_id}: a tightening must lower it"
        h = element_tol[element_tol.cde_id == cde_id].sort_values("run_ts")
        fail = 100.0 - h.score_pct
        rows.append(dict(
            proposal_id=det_uuid("tolerance-proposal", run_id, cde_id),
            proposal_run_id=run_id, proposed_ts=proposed_ts,
            cde_id=cde_id, cde_version=int(e.cde_version),
            current_tolerance_pct=cur, proposed_tolerance_pct=new,
            advice=advice, rationale=rationale, reviewer=e.owner_group,
            runs_observed=int(len(h)) if len(h) else None,
            runs_outside=int((~h.within_tolerance).sum()) if len(h) else None,
            fail_pct_min=round(float(fail.min()), 4) if len(h) else None,
            fail_pct_median=round(float(fail.median()), 4) if len(h) else None,
            fail_pct_p90=round(float(fail.quantile(0.9)), 4) if len(h) else None,
            fail_pct_max=round(float(fail.max()), 4) if len(h) else None,
            latest_fail_pct=round(float(fail.iloc[-1]), 4) if len(h) else None,
            scope_disputed=bool(h.scope_disputed.iloc[0]) if len(h) else False,
            model_endpoint=MODEL_ENDPOINT,
            model_input_payload=json.dumps({
                "note": "hand-authored fixture; no model call was made",
                "cde_id": cde_id,
            }),
            job_run_id=det_uuid("threshold-job", proposed_ts.date().isoformat()),
        ))
    df = pd.DataFrame(rows)
    for c in ("runs_observed", "runs_outside"):
        df[c] = df[c].astype("Int32")
    df["cde_version"] = df["cde_version"].astype("int32")
    return df


def build_tolerance_reviews(proposals: pd.DataFrame, det_uuid, steward_a, steward_b,
                            app_version: str) -> pd.DataFrame:
    """Three decisions: a tightening accepted (the register has not caught up, so it
    reads `accepted`, not `in_force`), one review deferred, one rejected. Customer
    name's tightening is left open for the app's write-path test."""
    by = proposals.set_index("cde_id")
    t0 = pd.Timestamp(by.iloc[0].proposed_ts)

    def row(cde_id, n, who, decision, reason=None, by_date=None):
        p = by.loc[cde_id]
        ts = t0 + timedelta(days=n, hours=2 + n)
        return dict(review_id=det_uuid("tolerance-review", p.proposal_id, "1"),
                    proposal_id=p.proposal_id, event_ts=ts, ingest_ts=ts,
                    actor_identity=who[0], actor_display_name=who[1],
                    actor_source="obo_user", decision=decision, reason=reason,
                    review_by_date=by_date, app_version=app_version)

    return pd.DataFrame([
        row("CDE_RECORD_LIFECYCLE", 1, steward_b, "accepted"),
        row("CDE_CUST_MSISDN", 1, steward_a, "deferred",
            "Asking Network how many placeholder numbers they expect before deciding "
            "between a fix and a non-zero tolerance.", (t0 + timedelta(days=45)).date()),
        row("CDE_SUBS_ACTIVATION", 2, steward_b, "rejected",
            "The ten subscriptions are a migration artefact being corrected in the "
            "November release. The tolerance stays; the data gets fixed."),
    ])


def proposal_current(proposals: pd.DataFrame, reviews: pd.DataFrame,
                     cde_registry: pd.DataFrame) -> pd.DataFrame:
    """Fixture twin of v_tolerance_proposal_current."""
    reg = cde_registry.sort_values("cde_version").groupby("cde_id").tail(1)
    reg = reg[reg.status != "retired"].set_index("cde_id")
    lp = (proposals.sort_values(["proposed_ts", "proposal_id"], ascending=[False, True])
                   .groupby("cde_id").head(1))
    lr = (reviews.sort_values(["event_ts", "review_id"], ascending=[False, True])
                 .groupby("proposal_id").head(1).set_index("proposal_id")
          if len(reviews) else pd.DataFrame())
    out = []
    for _, p in lp.iterrows():
        r = lr.loc[p.proposal_id] if p.proposal_id in lr.index else None
        e = reg.loc[p.cde_id] if p.cde_id in reg.index else None
        register = None if e is None or pd.isna(e.tolerance_pct) else float(e.tolerance_pct)
        decision = None if r is None else r.decision
        if p.advice == "keep":
            state = "no_change"
        elif p.advice == "tighten" and register is not None \
                and register == float(p.proposed_tolerance_pct):
            state = "in_force"
        elif decision in ("rejected", "deferred", "accepted"):
            state = decision
        else:
            state = "open"
        out.append(dict(
            proposal_id=p.proposal_id, proposal_run_id=p.proposal_run_id,
            proposed_ts=p.proposed_ts, cde_id=p.cde_id, cde_version=p.cde_version,
            cde_name=None if e is None else e.cde_name,
            criticality=None if e is None else e.criticality,
            owner_group=None if e is None else e.owner_group,
            current_tolerance_pct=p.current_tolerance_pct,
            proposed_tolerance_pct=p.proposed_tolerance_pct,
            register_tolerance_pct=register, advice=p.advice, rationale=p.rationale,
            reviewer=p.reviewer, runs_observed=p.runs_observed,
            runs_outside=p.runs_outside, fail_pct_min=p.fail_pct_min,
            fail_pct_median=p.fail_pct_median, fail_pct_p90=p.fail_pct_p90,
            fail_pct_max=p.fail_pct_max, latest_fail_pct=p.latest_fail_pct,
            scope_disputed=p.scope_disputed, model_endpoint=p.model_endpoint,
            latest_decision=decision,
            latest_review_ts=None if r is None else r.event_ts,
            latest_reviewer=None if r is None else r.actor_display_name,
            latest_reason=None if r is None else r.reason,
            review_by_date=None if r is None else r.review_by_date,
            review_state=state,
        ))
    return pd.DataFrame(out)

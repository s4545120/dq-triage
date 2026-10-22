"""Tolerance — is each element inside what the business accepts, and which breaches
does that let through to triage.

Pure. No Streamlit, no I/O.

**The business decides one number per element.** `config.cde_registry.tolerance_pct`
is the share of an element's rows the business will accept failing. A rule's
`fail_threshold_pct` decides whether one check reads `breach`; it is a steward's
setting, 0 by default, and nobody is asked to approve it. What reaches triage is
decided here, per element.

**These are labelled COPIES of two views** in `sql/ddl/19_views_tolerance.sql`:
`element_tolerance` of `v_element_tolerance` and `check_escalation` of
`v_check_escalation`. The notebooks read the views; the app recomputes them, because
promoting a shadow rule changes what an element's checks are, and the queue has to
follow in-session. `tests/test_tolerance.py` pins both to the fixture's output.

**An element's score is the scorecard's**: rows passed over rows evaluated across its
checks that raised a verdict, each check once however many bindings it attaches to.
A sum of failures, not a count of distinct bad rows — `check_run` stores no keys.

**Within tolerance is narrower than `targets.assessed`, on purpose.** The scorecard
will not say an element MEETS its target unless something validates what the column
holds; that is a claim about the data. Here the question is only whether the failures
that were measured fit inside what the business accepts, which needs a declared
tolerance, a score, and no binding in scope mismatch. A scope mismatch is never within
tolerance: its failures are a rule defect, and holding them back would hide the
finding the register exists to raise.

**A breach escalates unless its element sat within tolerance — and a `P1_block`
always escalates.** Severity belongs to the rule; the element decides how much failure
is acceptable, never how serious one check's failure is. A held breach is still a
breach on every other page.
"""

from __future__ import annotations

import pandas as pd

RAISED = ("pass", "breach")
ALWAYS_ESCALATES = "P1_block"
HELD_WITHIN_TOLERANCE = "element_within_tolerance"

ELEMENT_COLUMNS = ["run_id", "run_ts", "cde_id", "cde_name", "criticality",
                   "checks_raised", "rows_evaluated", "rows_failed", "score_pct",
                   "tolerance_pct", "target_pct", "scope_disputed", "within_tolerance"]
ESCALATION_COLUMNS = ["run_id", "run_ts", "rule_id", "severity", "violation_count",
                      "rows_scanned", "cde_id", "element_score_pct", "element_target_pct",
                      "element_within_tolerance", "escalates", "held_reason"]


def _as_list(value) -> list:
    if value is None:
        return []
    try:
        return list(value)
    except TypeError:
        return []


def row_score(run: pd.DataFrame) -> float | None:
    """Row-weighted quality of a set of check rows: rows passed over rows evaluated,
    over the checks that raised a verdict. None when nothing was evaluated.

    Shadow checks are excluded from both sides — they record a count but raise
    nothing, so counting their findings would make promoting a rule look like a
    regression in the data.
    """
    raised = run[run["status"].isin(RAISED)]
    evaluated = int(raised["rows_scanned"].sum())
    if not evaluated:
        return None
    return 100.0 * (evaluated - int(raised["violation_count"].sum())) / evaluated


def attached(cde_cov: pd.DataFrame) -> dict[str, set]:
    """cde_id → the rule ids attached to it, off `v_cde_coverage.rule_ids`."""
    out: dict[str, set] = {}
    for row in cde_cov.itertuples():
        out.setdefault(row.cde_id, set()).update(_as_list(row.rule_ids))
    return out


def element_scores(cde_cov: pd.DataFrame, run_rows: pd.DataFrame) -> dict:
    """cde_id → the element's row-weighted score on one run's rows, or None where no
    check on it raised a verdict. None stays None rather than becoming a zero: an
    element nothing watched has no quality figure."""
    if cde_cov.empty:
        return {}
    by_rule = run_rows.drop_duplicates("rule_id").set_index("rule_id")
    out = {}
    for cde_id, ids in attached(cde_cov).items():
        mine = by_rule[by_rule.index.isin(ids)]
        out[cde_id] = row_score(mine) if len(mine) else None
    return out


def scope_disputed(cde_cov: pd.DataFrame) -> set:
    """Elements with any binding in scope mismatch."""
    if cde_cov.empty:
        return set()
    return set(cde_cov.loc[cde_cov["coverage_gap"] == "scope_mismatch", "cde_id"])


def within(score, tolerance_pct, disputed: bool) -> bool:
    """The one definition of an element sitting inside what the business accepts."""
    if score is None or tolerance_pct is None or pd.isna(tolerance_pct) or disputed:
        return False
    return float(score) >= 100.0 - float(tolerance_pct) - 1e-9


def _registry(cde_registry_current: pd.DataFrame) -> pd.DataFrame:
    reg = cde_registry_current
    if "cde_version" in reg.columns:
        reg = reg.sort_values("cde_version").groupby("cde_id").tail(1)
    if "status" in reg.columns:
        reg = reg[reg["status"] != "retired"]
    return reg.set_index("cde_id")


def element_tolerance(check_run: pd.DataFrame, cde_cov: pd.DataFrame,
                      cde_registry_current: pd.DataFrame) -> pd.DataFrame:
    """Twin of `v_element_tolerance`: one row per run and element with a check that
    raised a verdict on that run."""
    if check_run.empty or cde_cov.empty or cde_registry_current.empty:
        return pd.DataFrame(columns=ELEMENT_COLUMNS)
    reg = _registry(cde_registry_current)
    has_tol = "tolerance_pct" in reg.columns
    disputed = scope_disputed(cde_cov)
    rule_cde = attached(cde_cov)

    raised = (check_run[check_run["status"].isin(RAISED)]
              .sort_values("result_id").drop_duplicates(["run_id", "rule_id"]))
    out = []
    for cde_id, ids in sorted(rule_cde.items()):
        if cde_id not in reg.index:
            continue
        mine = raised[raised["rule_id"].isin(ids)]
        e = reg.loc[cde_id]
        tol = e["tolerance_pct"] if has_tol else None
        tol = None if tol is None or pd.isna(tol) else float(tol)
        for run_id, g in mine.groupby("run_id"):
            evaluated = int(g["rows_scanned"].sum())
            failed = int(g["violation_count"].sum())
            score = 100.0 * (evaluated - failed) / evaluated if evaluated else None
            out.append(dict(
                run_id=run_id, run_ts=g["run_ts"].max(), cde_id=cde_id,
                cde_name=e.get("cde_name"), criticality=e.get("criticality"),
                checks_raised=int(len(g)), rows_evaluated=evaluated, rows_failed=failed,
                score_pct=score, tolerance_pct=tol,
                target_pct=None if tol is None else 100.0 - tol,
                scope_disputed=cde_id in disputed,
                within_tolerance=within(score, tol, cde_id in disputed),
            ))
    return pd.DataFrame(out, columns=ELEMENT_COLUMNS)


def check_escalation(check_run: pd.DataFrame, cde_cov: pd.DataFrame,
                     element_tol: pd.DataFrame) -> pd.DataFrame:
    """Twin of `v_check_escalation`: one row per breaching check per run, and whether
    it goes to triage."""
    if check_run.empty:
        return pd.DataFrame(columns=ESCALATION_COLUMNS)
    rule_cde = {r: c for c, ids in attached(cde_cov).items() for r in ids}
    tol = ({} if element_tol.empty else
           {(r.run_id, r.cde_id): r for r in element_tol.itertuples()})
    breaches = (check_run[check_run["status"] == "breach"]
                .sort_values("result_id").drop_duplicates(["run_id", "rule_id"]))
    out = []
    for b in breaches.itertuples():
        cde_id = rule_cde.get(b.rule_id)
        t = tol.get((b.run_id, cde_id))
        inside = bool(t.within_tolerance) if t is not None else False
        out.append(dict(
            run_id=b.run_id, run_ts=b.run_ts, rule_id=b.rule_id, severity=b.severity,
            violation_count=b.violation_count, rows_scanned=b.rows_scanned, cde_id=cde_id,
            element_score_pct=None if t is None else t.score_pct,
            element_target_pct=None if t is None else t.target_pct,
            element_within_tolerance=inside,
            # Since 2026-10-22 every breach escalates: a threshold is the rule's own
            # (fail_threshold_pct), and the element's tolerance holds nothing back.
            escalates=True,
            held_reason=None,
        ))
    return pd.DataFrame(out, columns=ESCALATION_COLUMNS)


def held_on_run(check_run: pd.DataFrame, cde_cov: pd.DataFrame,
                cde_registry_current: pd.DataFrame, run_id) -> set:
    """The breaching checks on one run that do NOT go to triage. Always empty since
    2026-10-22, when every breach began to escalate; kept so callers keep one shape."""
    if check_run.empty or run_id is None:
        return set()
    run = check_run[check_run["run_id"] == run_id]
    esc = check_escalation(run, cde_cov,
                           element_tolerance(run, cde_cov, cde_registry_current))
    return set(esc.loc[~esc["escalates"].astype(bool), "rule_id"]) if len(esc) else set()


# --- The threshold job's advice, per element ----------------------------------
#
# Since 2026-10-08 notebook 06 advises on each element's TOLERANCE, not on 86 rule
# limits: keep it, tighten it, or put it to the business. Never a higher number.
# `derive_proposal_current` is a labelled COPY of `v_tolerance_proposal_current`
# (sql/ddl/20_views_tolerance.sql), for the reason thresholds.py gives: a review made
# in this session has to change the page before a warehouse could re-run the view.
#
# Accepting writes the review row and nothing else. The register changes through the
# Elements page's amendment -- proposed by a person, approved by a second, applied by
# the onboarding job -- and the state reads `in_force` once it lands.

ADVICE = ("keep", "tighten", "review")
DECISIONS = ("accepted", "rejected", "deferred")
STATES = ("open", "deferred", "accepted", "rejected", "in_force", "no_change")
DECIDABLE = ("open", "deferred")

PROPOSAL_COLUMNS = ["proposal_id", "proposal_run_id", "proposed_ts", "cde_id", "cde_version",
                    "current_tolerance_pct", "proposed_tolerance_pct", "advice", "rationale",
                    "reviewer", "runs_observed", "runs_outside", "fail_pct_min",
                    "fail_pct_median", "fail_pct_p90", "fail_pct_max", "latest_fail_pct",
                    "scope_disputed", "model_endpoint", "model_input_payload", "job_run_id"]
REVIEW_COLUMNS = ["review_id", "proposal_id", "event_ts", "ingest_ts", "actor_identity",
                  "actor_display_name", "actor_source", "decision", "reason",
                  "review_by_date", "app_version"]
CURRENT_COLUMNS = ["proposal_id", "proposal_run_id", "proposed_ts", "cde_id", "cde_version",
                   "cde_name", "criticality", "owner_group", "current_tolerance_pct",
                   "proposed_tolerance_pct", "register_tolerance_pct", "advice", "rationale",
                   "reviewer", "runs_observed", "runs_outside", "fail_pct_min",
                   "fail_pct_median", "fail_pct_p90", "fail_pct_max", "latest_fail_pct",
                   "scope_disputed", "model_endpoint", "latest_decision", "latest_review_ts",
                   "latest_reviewer", "latest_reason", "review_by_date", "review_state"]


class ReviewRejected(ValueError):
    """A review the domain rules refuse. Raised before anything is written."""


def _num(v):
    return None if v is None or pd.isna(v) else float(v)


def derive_proposal_current(proposals: pd.DataFrame, reviews: pd.DataFrame,
                            cde_registry_current: pd.DataFrame) -> pd.DataFrame:
    """One row per element: its latest proposal with the latest review folded in.

    `review_state`: `no_change` (keep), `in_force` (a tightening the register now
    carries -- it outranks the decision), `rejected`, `deferred` (with
    `review_by_date`), `accepted`, `open`. No `current_date()`, on purpose.
    """
    if proposals is None or proposals.empty:
        return pd.DataFrame(columns=CURRENT_COLUMNS)
    reg = _registry(cde_registry_current) if len(cde_registry_current) else pd.DataFrame()
    latest_p = (proposals.sort_values(["proposed_ts", "proposal_id"], ascending=[False, True])
                         .groupby("cde_id").head(1))
    latest_r = pd.DataFrame()
    if reviews is not None and len(reviews):
        latest_r = (reviews.sort_values(["event_ts", "review_id"], ascending=[False, True])
                           .groupby("proposal_id").head(1).set_index("proposal_id"))
    out = []
    for _, p in latest_p.iterrows():
        r = latest_r.loc[p["proposal_id"]] if p["proposal_id"] in latest_r.index else None
        e = reg.loc[p["cde_id"]] if p["cde_id"] in reg.index else None
        register = None if e is None or "tolerance_pct" not in reg.columns \
            else _num(e["tolerance_pct"])
        decision = None if r is None else r["decision"]
        if p["advice"] == "keep":
            state = "no_change"
        elif (p["advice"] == "tighten" and register is not None
              and register == _num(p["proposed_tolerance_pct"])):
            state = "in_force"
        elif decision in DECISIONS:
            state = decision
        else:
            state = "open"
        out.append(dict(
            proposal_id=p["proposal_id"], proposal_run_id=p["proposal_run_id"],
            proposed_ts=p["proposed_ts"], cde_id=p["cde_id"], cde_version=p["cde_version"],
            cde_name=None if e is None else e.get("cde_name"),
            criticality=None if e is None else e.get("criticality"),
            owner_group=None if e is None else e.get("owner_group"),
            current_tolerance_pct=p["current_tolerance_pct"],
            proposed_tolerance_pct=p["proposed_tolerance_pct"],
            register_tolerance_pct=register, advice=p["advice"], rationale=p["rationale"],
            reviewer=p["reviewer"], runs_observed=p["runs_observed"],
            runs_outside=p["runs_outside"], fail_pct_min=p["fail_pct_min"],
            fail_pct_median=p["fail_pct_median"], fail_pct_p90=p["fail_pct_p90"],
            fail_pct_max=p["fail_pct_max"], latest_fail_pct=p["latest_fail_pct"],
            scope_disputed=p["scope_disputed"], model_endpoint=p["model_endpoint"],
            latest_decision=decision,
            latest_review_ts=None if r is None else r["event_ts"],
            latest_reviewer=None if r is None else r["actor_display_name"],
            latest_reason=None if r is None else r["reason"],
            review_by_date=None if r is None else r["review_by_date"],
            review_state=state,
        ))
    return pd.DataFrame(out, columns=CURRENT_COLUMNS)


def validate_review(decision: str, *, reason: str | None, review_by_date,
                    state: str) -> None:
    """Refuse a review before it is written, with a sentence for the person. The
    table's CHECK constraints, early, plus the state the proposal must be in."""
    if decision not in DECISIONS:
        raise ReviewRejected(f"'{decision}' is not a decision. Accept, reject or defer.")
    if state not in DECIDABLE:
        raise ReviewRejected(
            f"This advice is {state.replace('_', ' ')}; there is nothing to decide. "
            "The next pass of the threshold job reopens it if the history changes.")
    if decision in ("rejected", "deferred") and not (reason or "").strip():
        raise ReviewRejected(f"A '{decision}' decision requires a reason.")
    if decision == "deferred" and review_by_date is None:
        raise ReviewRejected(
            "A deferral requires a review-by date, or it disappears instead of coming back.")


def summary(current: pd.DataFrame) -> dict:
    """Counts by state, for the figures."""
    counts = current["review_state"].value_counts().to_dict() if len(current) else {}
    return {s: int(counts.get(s, 0)) for s in STATES} | {"proposals": int(len(current))}

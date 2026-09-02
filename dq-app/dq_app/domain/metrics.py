"""Scorecard metrics, exactly as the spec defines them, with their targets attached.

Pure logic. Every metric carries its own numerator, denominator and target, because
a number without its denominator is how a scorecard starts lying: MTTR over closed
cohorts looks excellent precisely when nothing is being closed. `Metric.footnote`
exists so the UI cannot show the value without the caveat.

Source of truth for the definitions is `dq-triage-agent-spec.md` § Success Metrics.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from dq_app.domain.lifecycle import TERMINAL_STATES  # noqa: F401  (vocabulary anchor)

# Short severity names for labels. Duplicated from the UI layer on purpose — the
# domain does not import the UI, and a metric's label travels with the metric.
_SHORT = {"P1_block": "P1", "P2_alert": "P2", "P3_monitor": "P3"}


@dataclass
class Metric:
    key: str
    label: str
    value: float | None
    display: str
    target: str
    met: bool | None  # None = cannot be judged (no denominator, or not instrumented)
    numerator: float | None = None
    denominator: float | None = None
    help: str = ""
    footnote: str = ""

    @property
    def basis(self) -> str:
        if self.numerator is None or self.denominator is None:
            return ""
        n = f"{self.numerator:g}"
        d = f"{self.denominator:g}"
        return f"{n} ÷ {d}"


def _pct(n: float, d: float) -> float | None:
    return None if not d else 100.0 * n / d


# --- Detection: the state of the data itself ---------------------------------
# These come before anything about cohorts. They are what a data-quality programme
# monitors day to day, they existed before this triage layer, and a scorecard that
# opens with triage throughput is answering a question nobody asked first.


def latest_run_id(check_run: pd.DataFrame):
    return None if check_run.empty else check_run.loc[check_run["run_ts"].idxmax(), "run_id"]


def detection_summary(check_run: pd.DataFrame) -> dict:
    """Headline data-quality figures for the most recent scheduled run.

    On the latest run only, not averaged over the window: "is the data good right
    now" is the question, and a 30-day mean of a defect that appeared four days ago
    understates it by a factor of seven.

    **`violations` counts rule-row pairs, not distinct bad rows.** A contact whose
    email trips six format rules contributes six. Deduplicating to distinct rows
    needs a row key on every violation, which the check runner only captures for
    sampled rows — so the honest label is "violations", never "records affected".
    """
    run_id = latest_run_id(check_run)
    if run_id is None:
        return {}
    run = check_run[check_run["run_id"] == run_id]
    breaching = run[run["status"] == "breach"]
    passing = run[run["status"] == "pass"]
    # Shadow rules run and record a count but do not raise. They neither passed nor
    # failed in the sense the pass rate means, so they are excluded from its
    # denominator and reported on their own — counting them as failures would make
    # promoting a rule look like a regression.
    skipped = run[~run["status"].isin(["pass", "breach"])]
    raised = len(run) - len(skipped)

    return {
        "run_id": run_id,
        "run_ts": run["run_ts"].max(),
        "rules_run": len(run),
        "rules_raised": raised,
        "rules_passing": len(passing),
        "rules_breaching": len(breaching),
        "rules_skipped": len(skipped),
        "pass_rate": _pct(len(passing), raised),
        "violations": int(breaching["violation_count"].sum()),
        "tables": int(run["target_table"].nunique()),
        "columns": int(run["target_column"].nunique()),
        "worst_rate": float(run["violation_pct"].max()) if len(run) else 0.0,
        "p1_breaching": int((breaching["severity"] == "P1_block").sum()),
        "rows_scanned": int(run.groupby("target_table")["rows_scanned"].max().sum()),
    }


def quality_by(check_run: pd.DataFrame, by: str = "target_table") -> pd.DataFrame:
    """Per-table (or per-domain) quality on the latest run.

    Pass rate here is over *rules*, not rows: a table with one catastrophic breach and
    nineteen clean rules scores 95%, which is why the violation count sits next to it.
    Neither number is sufficient alone, so both are always shown.
    """
    run_id = latest_run_id(check_run)
    if run_id is None:
        return pd.DataFrame()
    run = check_run[check_run["run_id"] == run_id]

    rows = []
    for key, g in run.groupby(by, sort=False):
        breaching = g[g["status"] == "breach"]
        # Same exclusion as detection_summary: shadow rules are not counted against
        # a table's pass rate.
        raised = int(g["status"].isin(["pass", "breach"]).sum())
        rows.append({
            by.replace("target_", "").replace("business_", "").replace("_", " ").title(): key,
            "Rules": raised,
            "Breaching": len(breaching),
            "Pass rate": round(_pct(raised - len(breaching), raised) or 0, 1),
            "Violations": int(breaching["violation_count"].sum()),
            "Worst rate": round(float(g["violation_pct"].max()), 2) if len(g) else 0.0,
            "P1": int((breaching["severity"] == "P1_block").sum()),
        })
    return pd.DataFrame(rows).sort_values("Violations", ascending=False).reset_index(drop=True)


def worst_rules(check_run: pd.DataFrame, limit: int = 8) -> pd.DataFrame:
    """The rules doing the most complaining on the latest run."""
    run_id = latest_run_id(check_run)
    if run_id is None:
        return pd.DataFrame()
    run = check_run[(check_run["run_id"] == run_id) & (check_run["status"] == "breach")]
    out = run.nlargest(limit, "violation_count")[
        ["rule_id", "target_table", "severity", "violation_count", "violation_pct",
         "threshold_pct"]
    ]
    return out.rename(columns={
        "rule_id": "Rule", "target_table": "Table", "severity": "Severity",
        "violation_count": "Violations", "violation_pct": "Rate",
        "threshold_pct": "Limit",
    }).reset_index(drop=True)


def cohort_for_rules(cohort: pd.DataFrame, rule_ids) -> dict[str, str]:
    """Which cohort is currently carrying each rule.

    The bridge between "this check is failing" and "here is the problem it belongs
    to". Later cohorts supersede earlier ones for the same rule, which matches how a
    rule that re-breaches after a close ends up in a fresh cohort rather than
    reopening an old one.
    """
    wanted = set(rule_ids)
    owner: dict[str, str] = {}
    for row in cohort.sort_values("raised_ts").itertuples():
        for rule_id in row.member_rule_ids:
            if rule_id in wanted:
                owner[rule_id] = row.cohort_id
    return owner


def table_insights(check_run: pd.DataFrame, table: str) -> dict:
    """Everything worth saying about one table on the latest run."""
    run_id = latest_run_id(check_run)
    if run_id is None:
        return {}
    run = check_run[(check_run["run_id"] == run_id) & (check_run["target_table"] == table)]
    raised = run[run["status"].isin(["pass", "breach"])]
    breaching = run[run["status"] == "breach"]
    worst = breaching.nlargest(1, "violation_count")

    return {
        "table": table,
        "rows": int(run["rows_scanned"].max()) if len(run) else 0,
        "checks": len(raised),
        "failing": len(breaching),
        "pass_rate": _pct(len(raised) - len(breaching), len(raised)),
        "violations": int(breaching["violation_count"].sum()),
        "columns_checked": int(run["target_column"].nunique()),
        "columns_failing": int(breaching["target_column"].nunique()),
        "p1": int((breaching["severity"] == "P1_block").sum()),
        "worst_rule": None if worst.empty else worst.iloc[0]["rule_id"],
        "worst_rate": 0.0 if worst.empty else float(worst.iloc[0]["violation_pct"]),
        "shadow": int((~run["status"].isin(["pass", "breach"])).sum()),
    }


def newly_failing(check_run: pd.DataFrame, table: str, days: int = 14) -> pd.DataFrame:
    """Checks that were clean and are not any more, with the date it changed.

    This is the insight a count cannot give. A check failing for forty runs is a
    known gap someone has decided to live with; a check that went from clean to
    failing on a specific date is an event, and the date is the first thing anyone
    investigating will ask for.
    """
    run_id = latest_run_id(check_run)
    if run_id is None:
        return pd.DataFrame()

    scope = check_run[check_run["target_table"] == table].sort_values("run_ts")
    cutoff = scope["run_ts"].max() - pd.Timedelta(days=days)
    rows = []
    for rule_id, g in scope.groupby("rule_id"):
        states = g[["run_ts", "status", "violation_count"]].reset_index(drop=True)
        if states.iloc[-1]["status"] != "breach":
            continue
        clean = states["status"] != "breach"
        if not clean.any():
            continue  # never seen clean in this window: chronic, not an event
        first_bad = states.index[states["status"] == "breach"]
        # The first breach after the most recent clean run is where it turned.
        last_clean = clean[::-1].idxmax()
        turned = [i for i in first_bad if i > last_clean]
        if not turned:
            continue
        at = states.loc[turned[0]]
        if at["run_ts"] < cutoff:
            continue
        rows.append({
            "Check": rule_id,
            "Started failing": at["run_ts"],
            "Failing rows": int(states.iloc[-1]["violation_count"]),
            "Clean before": states.loc[last_clean, "run_ts"],
        })
    return pd.DataFrame(rows).sort_values("Started failing") if rows else pd.DataFrame()


# --- Leading ----------------------------------------------------------------


def cohort_compression(check_run: pd.DataFrame, cohort: pd.DataFrame) -> Metric:
    """Breaches ÷ cohorts, on the breaches that are live right now. Target ≥5:1.

    The denominator is not "cohorts raised on the latest run". Cohorts are not
    re-raised on every run — a cohort persists until it is disposed of, so on any
    given day most breaching rules belong to a cohort raised days earlier, and
    counting only today's new cohorts would divide 21 breaches by 0.

    What is counted instead is the **live cohort for each currently-breaching rule**:
    for every rule breaching on the latest run, the most recent cohort containing it.
    That is the set a steward is actually looking at, so the ratio says what it
    claims to — how many alerts collapsed into how many items of work.

    (The clustering window — per run, rolling 24h, or until disposition — is an open
    engineering question in the spec. This measurement reads whatever window the
    triage job actually used rather than assuming one.)
    """
    if check_run.empty or cohort.empty:
        return Metric("compression", "Cohort compression", None, "—", "≥ 5.0 : 1", None)

    latest_run = check_run.loc[check_run["run_ts"].idxmax(), "run_id"]
    breaching = set(
        check_run.loc[
            (check_run["run_id"] == latest_run) & (check_run["status"] == "breach"), "rule_id"
        ]
    )

    live: dict[str, str] = {}
    for row in cohort.sort_values("raised_ts").itertuples():
        for rule_id in row.member_rule_ids:
            if rule_id in breaching:
                live[rule_id] = row.cohort_id  # later cohorts supersede earlier ones

    n_breaches, n_cohorts = len(breaching), len(set(live.values()))
    value = n_breaches / n_cohorts if n_cohorts else None
    return Metric(
        key="compression",
        label="Grouping",
        value=value,
        display=f"{value:.1f} : 1" if value else "—",
        target="≥ 5.0 : 1",
        met=None if value is None else value >= 5.0,
        numerator=n_breaches,
        denominator=n_cohorts,
        help="Called cohort compression in the spec. Failing checks on the latest "
        "run ÷ the problems covering them. "
        "If it approaches 1:1 the grouping is not working and the queue is just an "
        "alert list with extra steps.",
        footnote="Bounded by how many tables are in scope. The spec's ≥5:1 assumes "
        "its worked example of 30 breaches across 12 tables; a two-table pilot "
        "cannot reach it. Re-measure when more tables onboard — do not tune the "
        "clustering to hit the number.",
    )


def disposition_coverage(current: pd.DataFrame, disposition: pd.DataFrame) -> Metric:
    """Cohorts with a recorded human disposition ÷ cohorts raised. Target ≥90%.

    `recommended` does not count — the triage job writes that one itself, so
    counting it would score the agent for talking to itself.
    """
    human = disposition[disposition["event_type"] != "recommended"]
    n = int(current["cohort_id"].isin(human["cohort_id"]).sum())
    d = len(current)
    value = _pct(n, d)
    return Metric(
        key="coverage",
        label="Decisions recorded",
        value=value,
        display=f"{value:.1f}%" if value is not None else "—",
        target="≥ 90%",
        met=None if value is None else value >= 90.0,
        numerator=n,
        denominator=d,
        help="Called disposition coverage in the spec. Problems carrying at least "
        "one entry beyond the agent's own "
        "`recommended` ÷ all cohorts raised, against a target of 90% within 10 "
        "business days. This is the metric that catches a queue nobody is working.",
    )


def recommendation_acceptance(current: pd.DataFrame) -> Metric:
    """Cohorts whose recorded action matched the recommended approach. Target ≥50%."""
    judged = current[current["recommendation_followed"].notna()]
    n = int(judged["recommendation_followed"].astype(bool).sum())
    d = len(judged)
    value = _pct(n, d)
    return Metric(
        key="acceptance",
        label="Advice followed",
        value=value,
        display=f"{value:.1f}%" if value is not None else "—",
        target="≥ 50%",
        met=None if value is None else value >= 50.0,
        numerator=n,
        denominator=d,
        help="Called recommendation acceptance in the spec. Of problems where "
        "someone recorded what they actually did, the share "
        "where that matched the recommended approach type. A proxy for whether the "
        "advice is any good.",
        footnote="Read with suspicion when high: the spec's own open question is "
        "whether this measures good advice or passive agreement with the agent.",
    )


def cohort_precision() -> Metric:
    """Not instrumented. Shown anyway, so its absence is visible rather than quiet."""
    return Metric(
        key="precision",
        label="Grouping accuracy",
        value=None,
        display="not instrumented",
        target="≥ 80%",
        met=None,
        help="Called cohort precision in the spec. Problems a steward confirms as "
        "correctly grouped ÷ problems reviewed.",
        footnote="Needs the merge/split affordance (spec P1) to capture a steward's "
        "correction. Until that exists there is no signal to measure, and an "
        "invented number here would be worse than a blank.",
    )


# --- Lagging ----------------------------------------------------------------


def closure_rate(current: pd.DataFrame) -> Metric:
    """Verified-closed ÷ cohorts raised. Target ≥75%."""
    n = int((current["lifecycle_state"] == "closed_verified").sum())
    d = len(current)
    value = _pct(n, d)
    return Metric(
        key="closure",
        label="Verified fixed",
        value=value,
        display=f"{value:.1f}%" if value is not None else "—",
        target="≥ 75%",
        met=None if value is None else value >= 75.0,
        numerator=n,
        denominator=d,
        help="Called closure rate in the spec. Only a problem the next check run "
        "confirmed as fixed counts. A rejected or deferred problem is a "
        "legitimate disposition but it is not a closure, and rolling them in would "
        "let the queue be emptied by dismissing it.",
    )


def mttr(current: pd.DataFrame, severity: str | None = None) -> Metric:
    """Raised → verified closed, in days. Target <5 business days P1, <15 P2."""
    scope = current if severity is None else current[current["severity"] == severity]
    closed = scope[scope["mttr_days"].notna()]
    value = float(closed["mttr_days"].mean()) if len(closed) else None
    # The spec sets a target per severity, not an aggregate one. An overall MTTR is
    # therefore reported but never judged — a blended number that mixes a 5-day P1
    # limit with a 15-day P2 limit has no threshold it could be compared against.
    target = {
        "P1_block": "< 5 d",
        "P2_alert": "< 15 d",
        "P3_monitor": "no target set",
    }.get(severity or "", "< 5 d P1 · < 15 d P2 — not judged in aggregate")
    limit = {"P1_block": 5.0, "P2_alert": 15.0}.get(severity or "")
    return Metric(
        key=f"mttr_{severity or 'all'}",
        label="Time to fix" + (f" · {_SHORT.get(severity, severity)}" if severity else ""),
        value=value,
        display=f"{value:.1f} d" if value is not None else "—",
        target=target,
        met=None if (value is None or limit is None) else value < limit,
        numerator=len(closed),
        denominator=len(scope),
        help="Called MTTR in the spec. Mean days from a problem being raised to the "
        "next check run confirming it fixed. Counted over fixed problems only — read "
        "it next to how many were fixed at all, never alone.",
        footnote="Calendar days, not business days. The spec states its target in "
        "business days; converting needs a working-calendar the fixture has no "
        "basis for, so this is the stricter reading of the two.",
    )


def recurrence(current: pd.DataFrame) -> Metric:
    """Cohorts flagged as a rule re-cohorting after a verified close. Target <10% at 30d."""
    n = int(current["is_recurrence"].astype(bool).sum())
    d = len(current)
    value = _pct(n, d)
    return Metric(
        key="recurrence",
        label="Came back",
        value=value,
        display=f"{value:.1f}%" if value is not None else "—",
        target="< 10%",
        met=None if value is None else value < 10.0,
        numerator=n,
        denominator=d,
        help="Called recurrence in the spec. The same check failing again within "
        "30 days of a verified fix, against a "
        "target below 10%. The spec calls this the primary signal of root-cause "
        "versus symptom: a cohort that keeps coming back was patched, not resolved.",
    )


def scorecard(
    current: pd.DataFrame, disposition: pd.DataFrame, check_run: pd.DataFrame, cohort: pd.DataFrame
) -> dict[str, list[Metric]]:
    """Every spec metric in two groups, ready to render."""
    return {
        "Leading — days to weeks": [
            cohort_compression(check_run, cohort),
            cohort_precision(),
            recommendation_acceptance(current),
            disposition_coverage(current, disposition),
        ],
        "Lagging — weeks to months": [
            # Split by severity, because that is how the spec sets the target. The
            # aggregate is on the breakdown tab, where it cannot be mistaken for a
            # number that passed or failed something.
            mttr(current, "P1_block"),
            mttr(current, "P2_alert"),
            closure_rate(current),
            recurrence(current),
        ],
    }


# --- Breakdowns -------------------------------------------------------------


def breakdown(current: pd.DataFrame, by: str) -> pd.DataFrame:
    """The lagging metrics split by domain or severity — the spec asks for both."""
    rows = []
    for key, g in current.groupby(by, sort=False):
        closed = g[g["mttr_days"].notna()]
        rows.append(
            {
                by: key,
                "cohorts": len(g),
                "open": int(g["lifecycle_state"].isin(
                    ["awaiting_review", "awaiting_approval", "approved_awaiting_execution",
                     "awaiting_verification", "reopened", "awaiting_triage"]).sum()),
                "closed verified": int((g["lifecycle_state"] == "closed_verified").sum()),
                "closure rate %": round(_pct((g["lifecycle_state"] == "closed_verified").sum(), len(g)) or 0, 1),
                "MTTR days": round(float(closed["mttr_days"].mean()), 2) if len(closed) else None,
                "recurrences": int(g["is_recurrence"].astype(bool).sum()),
                "breach rows": int(g["total_violation_rows"].sum()),
            }
        )
    return pd.DataFrame(rows)


def triage_funnel(current: pd.DataFrame) -> pd.DataFrame:
    """Cohorts that have reached each stage of the register, cumulatively.

    Cumulative on purpose: a cohort sitting at `awaiting_verification` has been
    reviewed and approved, and a funnel that showed it only in its current bucket
    would suggest review had stalled.
    """
    reached_review = current["latest_decision"].notna()
    reached_approval = current["distinct_approvers"] > 0
    reached_execution = current["executed_ts"].notna()
    reached_verified = current["verified_ts"].notna()
    closed = current["lifecycle_state"] == "closed_verified"
    return pd.DataFrame(
        [
            {"stage": "01 recommended", "cohorts": len(current)},
            {"stage": "02 reviewed", "cohorts": int(reached_review.sum())},
            {"stage": "03 approved", "cohorts": int(reached_approval.sum())},
            {"stage": "04 executed (claimed)", "cohorts": int(reached_execution.sum())},
            {"stage": "05 verification attempted", "cohorts": int(reached_verified.sum())},
            {"stage": "— closed verified", "cohorts": int(closed.sum())},
        ]
    )

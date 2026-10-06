"""Onboarding — how far each selected table has got, derived and never stored.

A table is selected by a row in `config.monitored_table`. Everything after that is
read off the registers: a binding proposal waiting for a person, bindings on the
element register, rules on the rule register, runs in `check_run`. So the stage
cannot disagree with what exists, and promoting a table's rules is the only write
promotion needs — the same rule-version append the Rules page makes.

`derive_status` is the labelled copy of `v_onboarding_status`, the view
`onboarding/onboard.py` creates in the test schema. Computed rather than read for the
reason every other view here is: a promotion made in this session has to move the
table's stage before any warehouse could re-run the view.

A binding decision is a `config.binding_review` append (`adapter.review_binding`), and
so is excluding a column at promotion (`excludable_columns`, `excluded_bindings`).
"""

from __future__ import annotations

import pandas as pd

from dq_app.domain import coverage

MONITORED_COLUMNS = [
    "target_table", "table_version", "table_code", "row_key", "owner_group",
    "business_domain", "schedule_group", "scan_mode", "status", "effective_from",
    "selected_by", "note",
    # The slice, domain/slices.py. Spelled out rather than imported: fixtures/verify.py
    # reads this list as a literal and diffs it against the DDL.
    "slice_filter", "slice_spec", "slice_version", "slice_change",
    "slice_proposed_filter", "slice_proposed_spec", "slice_proposed_by",
]
PROPOSAL_COLUMNS = [
    "proposal_id", "proposed_at", "target_table", "target_column", "cde_id", "method",
    "confidence", "evidence", "proposed_by",
]
REVIEW_COLUMNS = ["proposal_id", "decision", "reviewed_by", "reviewed_at", "reason"]

# (stage, who acts, what it means). The order is the onboarding sequence.
STAGES = [
    ("awaiting discovery", "job", "Nothing proposed yet: the discovery job has not run."),
    ("bindings awaiting review", "person",
     "A job has proposed which columns hold which element. An owner decides."),
    ("awaiting rule generation", "job",
     "Columns are bound. The generator has not written their checks yet."),
    ("shadow, not yet run", "job", "Checks exist in shadow. No run has measured them."),
    ("shadow, awaiting promotion", "person",
     "Checks are measured but raise nothing. A person promotes them."),
    ("active", "", "Breaches raise problems in Triage."),
]
STAGE_INDEX = {s: i for i, (s, _, _) in enumerate(STAGES)}


def empty(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype="object") for c in columns})


def latest_monitored(monitored: pd.DataFrame) -> pd.DataFrame:
    """Latest version of every table's row, whatever its status."""
    if monitored.empty:
        return monitored
    return (monitored.sort_values(["target_table", "table_version"])
            .groupby("target_table", as_index=False).tail(1).reset_index(drop=True))


def current_monitored(monitored: pd.DataFrame,
                      statuses: tuple[str, ...] = ("selected",)) -> pd.DataFrame:
    """Latest version of each table's row with one of `statuses` -- by default the
    tables being checked. Onboarding also shows `paused`; `retired` is gone."""
    latest = latest_monitored(monitored)
    if latest.empty:
        return latest
    return latest[latest["status"].isin(statuses)].reset_index(drop=True)


# Pausing stops the checks and keeps everything; resuming starts them again;
# decommissioning (retired) is permanent -- re-onboarding is a new selection.
TRANSITIONS = {"selected": {"paused", "retired"}, "paused": {"selected", "retired"}}


def bindings_on(cde_registry: pd.DataFrame, table: str) -> list[dict]:
    """The bound columns of `table`, as `coverage.bound_columns` reads them."""
    return [b for b in coverage.bound_columns(cde_registry) if b["target_table"] == table]


def open_proposals(proposals: pd.DataFrame, reviews: pd.DataFrame,
                   cde_registry: pd.DataFrame) -> pd.DataFrame:
    """Proposals nobody has decided, for columns that are not already bound."""
    if proposals.empty:
        return proposals
    decided = set(reviews["proposal_id"]) if not reviews.empty else set()
    bound = {(b["target_table"], b["target_column"])
             for b in coverage.bound_columns(cde_registry)}
    keep = [pid not in decided and (t, c) not in bound
            for pid, t, c in zip(proposals["proposal_id"], proposals["target_table"],
                                 proposals["target_column"])]
    return proposals[keep].reset_index(drop=True)


def stage_of(proposals_open: int, columns_bound: int, rules_shadow: int,
             rules_active: int, runs: int) -> str:
    """The same CASE as v_onboarding_status, in the same order."""
    if proposals_open > 0:
        return "bindings awaiting review"
    if columns_bound == 0:
        return "awaiting discovery"
    if rules_shadow + rules_active == 0:
        return "awaiting rule generation"
    if rules_active == 0 and runs == 0:
        return "shadow, not yet run"
    if rules_active == 0:
        return "shadow, awaiting promotion"
    return "active"


def derive_status(monitored: pd.DataFrame, proposals: pd.DataFrame, reviews: pd.DataFrame,
                  cde_registry: pd.DataFrame, rule_current: pd.DataFrame,
                  check_runs: pd.DataFrame) -> pd.DataFrame:
    """One row per selected table with its counts and stage."""
    cols = ["target_table", "table_code", "owner_group", "proposals_open", "columns_bound",
            "rules_shadow", "rules_active", "runs", "last_run_ts", "stage"]
    sel = current_monitored(monitored, ("selected", "paused"))
    if sel.empty:
        return empty(cols)
    open_p = open_proposals(proposals, reviews, cde_registry)
    out = []
    for _, m in sel.iterrows():
        t = m["target_table"]
        rules = rule_current[rule_current["target_table"] == t]
        runs = check_runs[check_runs["target_table"] == t]
        row = dict(
            target_table=t, table_code=m["table_code"], owner_group=m["owner_group"],
            proposals_open=int((open_p["target_table"] == t).sum()) if not open_p.empty else 0,
            columns_bound=len({b["target_column"] for b in bindings_on(cde_registry, t)}),
            rules_shadow=int((rules["status"] == "shadow").sum()),
            rules_active=int((rules["status"] == "active").sum()),
            runs=int(runs["run_id"].nunique()),
            last_run_ts=runs["run_ts"].max() if len(runs) else None,
        )
        row["stage"] = "paused" if m["status"] == "paused" else stage_of(
            row["proposals_open"], row["columns_bound"], row["rules_shadow"],
            row["rules_active"], row["runs"])
        out.append(row)
    return pd.DataFrame(out, columns=cols)


def shadow_evidence(rule_current: pd.DataFrame, check_runs: pd.DataFrame,
                    table: str) -> pd.DataFrame:
    """Every current rule on `table` with what its latest run measured.

    `would_breach` asks the runner's own question of a shadow measurement: is the
    rate above the rule's limit? A shadow rule is recorded as `skipped` whatever it
    measured, so the verdict a promotion would produce has to be recomputed here —
    with the limit as it stands now, which is what the next run will judge on.
    """
    cols = ["rule_id", "rule_name", "cde_id", "target_column", "status", "severity",
            "fail_threshold_pct", "violation_count", "rows_scanned", "violation_pct",
            "runs_measured", "would_breach", "promoted_by", "promoted_at"]
    rules = rule_current[rule_current["target_table"] == table]
    if rules.empty:
        return empty(cols)
    runs = check_runs[check_runs["target_table"] == table]
    latest = (runs.sort_values("run_ts").groupby("rule_id", as_index=False).tail(1)
              .set_index("rule_id") if len(runs) else pd.DataFrame())
    counts = runs.groupby("rule_id")["run_id"].nunique() if len(runs) else pd.Series(dtype=int)
    out = []
    for _, r in rules.iterrows():
        m = latest.loc[r["rule_id"]] if r["rule_id"] in latest.index else None
        pct = None if m is None or pd.isna(m["violation_pct"]) else float(m["violation_pct"])
        limit = float(r["fail_threshold_pct"])
        out.append(dict(
            rule_id=r["rule_id"], rule_name=r["rule_name"], cde_id=r["cde_id"],
            target_column=r["target_column"], status=r["status"], severity=r["severity"],
            fail_threshold_pct=limit,
            violation_count=None if m is None else m["violation_count"],
            rows_scanned=None if m is None else m["rows_scanned"],
            violation_pct=pct,
            runs_measured=int(counts.get(r["rule_id"], 0)),
            would_breach=None if pct is None else bool(pct > limit and
                                                       (m["violation_count"] or 0) > 0),
            promoted_by=r.get("promoted_by"), promoted_at=r.get("promoted_at"),
        ))
    return pd.DataFrame(out, columns=cols).sort_values(
        ["would_breach", "violation_pct"], ascending=[False, False], na_position="last"
    ).reset_index(drop=True)


# --- Selecting a table ---------------------------------------------------------------
# Measured on the workspace's smallest warehouse (2X-Small serverless), one batched scan
# of ten row checks: 153 MB in 5.3 s, 1.56 GB in 14.3 s, 15.2 GB in 93.8 s. A fixed
# start-up cost plus a read rate. It is an upper bound: Delta reads only the columns
# the checks name, and this is the size of every column.
SCAN_OVERHEAD_S = 4.0
SCAN_BYTES_PER_S = 160e6
# Above this a daily full scan is refused until partition scans exist -- which wait on
# the scope_fingerprint decision. ~1 billion rows of a typical fact table.
SCAN_LIMIT_BYTES = 200e9

SCAN_MODES = ("full",)
SCHEDULES = ("daily_0300",)


def estimate_scan_seconds(size_bytes) -> float | None:
    if size_bytes is None or pd.isna(size_bytes):
        return None
    return SCAN_OVERHEAD_S + float(size_bytes) / SCAN_BYTES_PER_S


def scan_label(size_bytes) -> str:
    s = estimate_scan_seconds(size_bytes)
    if s is None:
        return "size unknown"
    if size_bytes > SCAN_LIMIT_BYTES:
        return "too large for a daily full scan"
    if s < 10:
        return "under 10 s"
    if s < 90:
        return f"about {round(s / 5) * 5:.0f} s"
    return f"about {s / 60:.0f} min"


def suggest_row_key(columns: list[str], primary_key: list[str] | None = None) -> list[str]:
    """The declared primary key, else the first column whose name says it is a key."""
    if primary_key:
        return list(primary_key)
    for c in columns:
        low = c.lower()
        if low in ("id", "key") or low.endswith(("_id", "_key", "id", "key")):
            return [c]
    return columns[:1]


def table_code(target_table: str, taken: set[str]) -> str:
    """A short upper-case code for generated rule ids, unique among selected tables."""
    import re
    base = re.sub(r"[^A-Za-z0-9]+", "_", target_table.split(".")[-1]).strip("_").upper()[:16]
    base = base or "TBL"
    code, n = base, 2
    while code in taken:
        code, n = f"{base}{n}", n + 1
    return code


# --- Reviewing a binding ---------------------------------------------------------------

class OnboardingRejected(ValueError):
    """A selection, suggestion or review the rules refuse. Nothing was written."""


DECISIONS = ("approved", "rejected")


def is_own(proposal: dict, reviewer: str) -> bool:
    by = proposal.get("proposed_by")
    return is_person(by) and str(by).lower() == str(reviewer).lower()


def is_person(proposed_by) -> bool:
    """A job's proposals are signed `job:<name>`; anything else is a person."""
    return bool(proposed_by) and not str(proposed_by).startswith("job:")


# Written at the start of a self-approval's reason when the second-approver rule is
# waived, so the record says the rule was bypassed -- and the apply job accepts a
# self-approval only when it carries this, so the waiver cannot leak past the app setting.
WAIVER_MARK = "[second approver waived]"


def validate_review(proposal: dict, reviewer: str, decision: str, reason: str | None,
                    allow_self: bool = False) -> None:
    """The rules on a binding decision.

    THE SECOND APPROVER. A binding a person suggested cannot be approved by that person:
    one person would then both assert what a column holds and sign it off. A job's
    proposal has no such author, so its reviewer is the second party. Rejecting your own
    suggestion is allowed -- withdrawing a claim needs no witness.
    """
    if decision not in DECISIONS:
        raise OnboardingRejected(f"Unknown decision {decision!r}.")
    if (decision == "approved" and not allow_self and is_person(proposal.get("proposed_by"))
            and str(proposal["proposed_by"]).lower() == str(reviewer).lower()):
        raise OnboardingRejected(
            "You suggested this binding, so a second person must approve it.")
    if decision == "rejected" and not (reason or "").strip():
        raise OnboardingRejected("Say why you are rejecting it. The reason is kept with "
                                 "the decision, and stops the same proposal coming back.")


# --- Excluding a column at promotion ------------------------------------------------------
# The last look at a table is the Promote card, with every check measured. A column
# whose numbers show the binding was wrong is EXCLUDED there: its shadow checks get a
# retired version, and a second review -- `rejected`, reason starting EXCLUSION_MARK --
# is appended to the proposal that bound it. That second review is the one place a
# proposal carries two decisions, and the latest one wins everywhere: the apply job
# reads the latest review per proposal so it does not re-apply the binding, discovery
# treats the column as settled, and the onboarding job's unbind step drops the binding
# whose latest decision is this rejection. No new table and no new grant: it is the
# binding_review append the review form already makes.

EXCLUSION_MARK = "[excluded at promotion]"


def latest_reviews(reviews: pd.DataFrame) -> pd.DataFrame:
    if reviews.empty:
        return reviews
    return (reviews.sort_values("reviewed_at").groupby("proposal_id", as_index=False)
            .tail(1))


def excludable_columns(proposals: pd.DataFrame, reviews: pd.DataFrame,
                       table: str) -> dict[str, str]:
    """{column: proposal_id} for the columns of `table` whose binding came from a
    proposal whose latest decision is an approval -- the bindings a person can take back.
    A binding registered by hand has no proposal to record the exclusion against."""
    if proposals.empty or reviews.empty:
        return {}
    latest = latest_reviews(reviews)
    ok = set(latest.loc[latest["decision"] == "approved", "proposal_id"])
    p = proposals[(proposals["target_table"] == table) & proposals["proposal_id"].isin(ok)]
    p = p.sort_values("proposed_at")
    return dict(zip(p["target_column"], p["proposal_id"]))       # latest proposal wins


def excluded_bindings(proposals: pd.DataFrame, reviews: pd.DataFrame) -> set[tuple]:
    """(table, column, cde_id) of every binding excluded at promotion: the latest
    decision about that column and element is a rejection carrying EXCLUSION_MARK.
    A later approval of a new proposal for the same pair undoes it. The SQL twin is
    `unbind_excluded` in onboarding/onboard.py."""
    if proposals.empty or reviews.empty:
        return set()
    j = proposals.merge(reviews, on="proposal_id")
    j = j.sort_values("reviewed_at").groupby(
        ["target_table", "target_column", "cde_id"], as_index=False).tail(1)
    hit = j[(j["decision"] == "rejected")
            & j["reason"].fillna("").str.startswith(EXCLUSION_MARK)]
    return set(zip(hit["target_table"], hit["target_column"], hit["cde_id"]))


# --- How the pages say it ---------------------------------------------------------------
# The stage names above are the view's; these are the steward's.
STAGE_LABEL = {
    "awaiting discovery": "Discovery queued",
    "bindings awaiting review": "Bindings to review",
    "awaiting rule generation": "Generating checks",
    "shadow, not yet run": "Checks not yet measured",
    "shadow, awaiting promotion": "Ready to promote",
    "active": "Active",
    "paused": "Paused",
}
STAGE_TONE = {
    "awaiting discovery": "info", "bindings awaiting review": "high",
    "awaiting rule generation": "info", "shadow, not yet run": "info",
    "shadow, awaiting promotion": "high", "active": "success", "paused": "neutral",
}
# The six steps a reader sees, and which one each stage is standing on.
STEPS = ["Selected", "Discovered", "Review bindings", "Checks in shadow", "Promote", "Active"]
# 1-based, so it reads like the badges: "3 Review bindings". Active marks every step done.
STEP_OF = {"awaiting discovery": 2, "bindings awaiting review": 3,
           "awaiting rule generation": 4, "shadow, not yet run": 4,
           "shadow, awaiting promotion": 5, "active": 6, "paused": None}
STEP_PERSON = {3, 5}          # the steps a person takes, marked "· you" when current


def summary(status: pd.DataFrame) -> dict:
    """The four figures across the top of Onboarding."""
    if status.empty:
        return dict(selected=0, waiting=0, waiting_bindings=0, shadow=0,
                    shadow_checks=0, active=0, paused=0)
    paused = int((status["stage"] == "paused").sum())
    status = status[status["stage"] != "paused"]
    waiting = status["stage"].isin(["bindings awaiting review", "shadow, awaiting promotion"])
    shadow = status["stage"].isin(["shadow, not yet run", "shadow, awaiting promotion"])
    return dict(
        selected=len(status),
        waiting=int(waiting.sum()),
        waiting_bindings=int(status["proposals_open"].sum()),
        shadow=int(shadow.sum()),
        shadow_checks=int(status.loc[shadow, "rules_shadow"].sum()),
        active=int((status["stage"] == "active").sum()),
        paused=paused,
    )

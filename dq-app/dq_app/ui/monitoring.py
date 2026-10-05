"""Shared figures for the two Tables pages — the inventory and one table opened up.

**What these pages count.** Checks attached to a registered critical data element
(`domain/coverage.attached_rule_ids`), with retired rules dropped — the same set the
scorecard scores, so a table's figures and the scorecard's never disagree about which
checks exist. The scoping is not a control; see `domain/coverage` and the scorecard's
docstring for why the register, rather than the rule set, owns the denominator.

**What they measure is different from the scorecard, and says so.** A table's
"checks passing" is a count — checks within their limit over checks that ran —
because the question on these pages is which rules a table is breaking. The
scorecard's figure is row-weighted. Both pages print "checks passing, not row-level
quality" where the figure stands, so the two numbers are never read as one.

Redrawn 2026-10-06 from a design mock: the inventory is clickable rows, not an
`st.dataframe`, and the detail page is the scorecard's layout — a figure against its
target, then a rule list beside one rule opened up.
"""

from __future__ import annotations

import pandas as pd

from dq_app.data import adapter
from dq_app.domain import coverage, metrics
from dq_app.ui import components, theme

RAISED = ["pass", "breach"]
STATUS_ORDER = {"Critical": 0, "Needs attention": 1, "Healthy": 2}
STATUS_TONE = {"Critical": "critical", "Needs attention": "high", "Healthy": "success"}


def scoped_runs(runs: pd.DataFrame) -> pd.DataFrame:
    """The runs these pages read: checks on a registered element, retired rules out.

    Retired as the scorecard retires them: a retired rule's history is not a current
    claim about the table, and without this the vulnerable-customer variance check
    would still count against `ctct_c` on every run before 2026-10-01.
    """
    versions = adapter.get_rule_registry().sort_values("rule_version")
    retired = set(versions.groupby("rule_id").tail(1).query("status == 'retired'").rule_id)
    attached = coverage.attached_rule_ids(adapter.get_cde_coverage())
    return runs[runs["rule_id"].isin(attached) & ~runs["rule_id"].isin(retired)]


def checks_passing(run: pd.DataFrame) -> float | None:
    """Checks within their limit over checks that ran. `None` when none ran."""
    raised = run[run["status"].isin(RAISED)]
    if raised.empty:
        return None
    return 100.0 * int((raised["status"] == "pass").sum()) / len(raised)


def status_label(run: pd.DataFrame) -> str:
    breaching = run[run["status"] == "breach"]
    if breaching.empty:
        return "Healthy"
    if (breaching["severity"] == "P1_block").any():
        return "Critical"
    return "Needs attention"


def owner_label(group) -> str:
    """`dq-stewards-billing` as a person would say it: Billing stewards."""
    group = components.opt(group)
    if not group:
        return "No owner"
    if str(group).startswith("dq-stewards-"):
        return f"{str(group)[len('dq-stewards-'):].replace('-', ' ').capitalize()} stewards"
    return str(group)


def initials(name: str) -> str:
    words = [w for w in name.replace("-", " ").split() if w[:1].isalpha()]
    return "".join(w[0] for w in words[:2]).upper() or "?"


def short_name(table: str) -> str:
    return str(table).split(".")[-1]


def change_words(history: list[tuple]) -> str:
    """The last step of a history in words. Not coloured — see the scorecard."""
    if len(history) < 2:
        return "No prior run"
    change = history[-1][1] - history[-2][1]
    if abs(change) < 0.05:
        return "No change"
    return ("↑ " if change > 0 else "↓ ") + f"{abs(change):.1f} pts"


def history(runs: pd.DataFrame, window_days: int, score) -> list[tuple]:
    """(label, score) per scheduled run inside the window, oldest first.

    One point per RUN rather than per day: a shadow-only measurement is never a run
    (`metrics.latest_run_id` says why), so runs that measured no active check are
    dropped rather than drawn as a dip.
    """
    raised = runs[runs["status"].isin(RAISED)]
    if raised.empty:
        return []
    cutoff = raised["run_ts"].max() - pd.Timedelta(days=window_days)
    out = []
    for _, g in raised[raised["run_ts"] >= cutoff].groupby("run_id"):
        value = score(g)
        if value is not None:
            out.append((g["run_ts"].max(), value))
    return [(f"{ts:%-d %b}", v) for ts, v in sorted(out, key=lambda p: p[0])]


def _mode(values: pd.Series):
    values = values.dropna()
    return None if values.empty else values.value_counts().index[0]


def table_rows(scoped: pd.DataFrame, window_days: int) -> list[dict]:
    """One dict per monitored table on the latest run, most urgent first."""
    run_id = metrics.latest_run_id(scoped)
    if run_id is None:
        return []
    latest = scoped[scoped["run_id"] == run_id]
    rows = []
    for table, g in latest.groupby("target_table", sort=False):
        raised = g[g["status"].isin(RAISED)]
        if raised.empty:
            continue
        breaching = raised[raised["status"] == "breach"]
        # The value most of its checks carry: a table with one billing rule among
        # fifteen customer ones is a customer table.
        owner = owner_label(_mode(raised["owner_group"]))
        hist = history(scoped[scoped["target_table"] == table], window_days, checks_passing)
        rows.append({
            "key": table,
            "Table": short_name(table),
            "Domain": _mode(raised["business_domain"]) or "",
            "Status": status_label(g),
            "Checks": len(raised),
            "Passing": int((raised["status"] == "pass").sum()),
            "Score": checks_passing(g),
            "History": hist,
            "Change": change_words(hist),
            "Breaching": len(breaching),
            "P1": int((breaching["severity"] == "P1_block").sum()),
            "Findings": int(breaching["violation_count"].sum()),
            "Rows": int(raised["rows_scanned"].max()),
            "Owner": owner,
            "Last run": g["run_ts"].max(),
        })
    return sorted(rows, key=lambda r: (STATUS_ORDER[r["Status"]], -r["P1"],
                                       -r["Findings"], r["Table"]))


def disputed_rules() -> set:
    """Rules the CDE register says measure rows they should not — a scope mismatch.
    Their breach is a fact about the rule, so no page paints their rows as bad data."""
    cde = adapter.get_cde_coverage()
    return {i for lst in cde["unscoped_rule_ids"] for i in components.as_list(lst)}


def rule_rows(scoped: pd.DataFrame, table: str, registry: pd.DataFrame) -> list[dict]:
    """Every check that ran on `table` on the latest run, failing and worst first."""
    run_id = metrics.latest_run_id(scoped)
    if run_id is None:
        return []
    name = registry.drop_duplicates("rule_id").set_index("rule_id")["rule_name"].to_dict()
    disputed = disputed_rules()
    now = scoped[(scoped["run_id"] == run_id) & (scoped["target_table"] == table)
                 & scoped["status"].isin(RAISED)]
    rows = []
    for r in now.to_dict("records"):
        breach = r["status"] == "breach"
        limit = 0.0 if pd.isna(r["threshold_pct"]) else float(r["threshold_pct"])
        rows.append({
            "key": r["rule_id"],
            "Rule": name.get(r["rule_id"], r["rule_id"]),
            "Column": components.opt(r["target_column"]) or "table level",
            "Severity": r["severity"],
            "Breach": breach,
            "Disputed": breach and r["rule_id"] in disputed,
            "Rate": 100.0 - float(r["violation_pct"]),
            "Failure": float(r["violation_pct"]),
            "Limit": limit,
            "Target": 100.0 - limit,
            "Findings": int(r["violation_count"]),
            "Rows": int(r["rows_scanned"]),
            "run_id": r["run_id"],
            "violation_count": int(r["violation_count"]),
        })
    # A disputed breach after the real ones: it is a rule to fix, not data to fix.
    return sorted(rows, key=lambda c: (not c["Breach"], c["Disputed"], -c["Findings"],
                                       c["Rule"]))

"""Targets — what a quality score is measured against.

**An element's target is the complement of its tolerance.** `config.cde_registry.
tolerance_pct` is the share of rows the business will accept failing on an element, so
the score that element has to reach is `100 - tolerance_pct`. Nothing here invents a
target: an element whose register row declares no tolerance has none, and the page
says so rather than assuming a hundred.

**The overall target is the same tolerances, weighted the way the score is.** The
headline figure is rows passed over rows evaluated, so each check counts in proportion
to the rows it scanned. Weighting each check's element target by those same rows gives
the figure the headline would show if every element sat exactly on its tolerance —
which makes the two commensurable, where a flat "95%" beside a row-weighted score
would be a line drawn at a height nobody chose.

**Not every score is assessed against its target, and `assessed` is the one
definition of which are.** A target is a claim about the DATA. An element nothing
validates can score 100% on a presence check, and "meets target" beside that is the
quietest lie a scorecard can tell; a scope mismatch scores low because the rule
measures rows the register says are legitimately empty, and "below target" there
blames the data for a rule defect. Both keep their figure and lose the verdict.

A check's own target is not here: it is `100 - threshold_pct` off the run row, the
limit that check was actually judged against on that run.
"""

from __future__ import annotations

import pandas as pd

_RAISED = ("pass", "breach")


def element_targets(cde_registry_current: pd.DataFrame) -> dict:
    """cde_id → the score the element has to reach, or None where the register
    declares no tolerance. A registry that predates the column has no targets at all,
    which is the state of the workspace until `migrate_cde_scope.sql` runs."""
    if cde_registry_current.empty or "tolerance_pct" not in cde_registry_current.columns:
        return {}
    return {
        r.cde_id: None if pd.isna(r.tolerance_pct) else 100.0 - float(r.tolerance_pct)
        for r in cde_registry_current.itertuples()
    }


def rule_elements(cde_cov: pd.DataFrame) -> dict:
    """rule_id → the element it is attached to, read back off the coverage view for
    the same reason `coverage.attached_rule_ids` is: the view is the one definition
    of attachment, and re-deriving it by matching columns is how two pages come to
    disagree."""
    out = {}
    for row in cde_cov.itertuples():
        ids = row.rule_ids
        for rule_id in ([] if ids is None else list(ids)):
            out[rule_id] = row.cde_id
    return out


def blended_target(run_rows: pd.DataFrame, rule_cde: dict, targets: dict) -> float | None:
    """The overall target for one run: each raised check's element target, weighted by
    the rows that check scanned. None when no check on the run has a declared target.

    Shadow checks are in neither half, as in the score this sits beside.
    """
    raised = run_rows[run_rows["status"].isin(_RAISED)].drop_duplicates("rule_id")
    weight = total = 0.0
    for r in raised.itertuples():
        target = targets.get(rule_cde.get(r.rule_id))
        if target is None:
            continue
        weight += float(r.rows_scanned)
        total += float(r.rows_scanned) * target
    return total / weight if weight else None


def assessed(gaps, score, target) -> bool:
    """Whether an element's score may be read against its target.

    `gaps` are the coverage findings across the element's bindings. It takes a
    binding something actually validates, no binding whose rule contradicts the
    register's scope, a check that ran, and a declared tolerance.
    """
    gaps = set(gaps)
    return (score is not None and target is not None
            and "covered" in gaps and "scope_mismatch" not in gaps)


def shortfall(score, target) -> float | None:
    """Points below target; zero or negative when the target is met."""
    if score is None or target is None:
        return None
    return float(target) - float(score)


def meets(score, target) -> bool:
    gap = shortfall(score, target)
    return gap is not None and gap <= 1e-9

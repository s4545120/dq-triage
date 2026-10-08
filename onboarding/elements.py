"""Whether the onboarding job may apply an approved CDE proposal -- pure, so it is tested
without a warehouse.

The app writes a proposal (config.cde_proposal) and a second person's decision
(config.cde_review); `onboard.py apply_elements` turns an approved one into a new
config.cde_registry version. This is what it checks first. The app's twin is
`dq_app/domain/elements.refusal`, which says the same thing to the reviewer before the
job ever runs; the two are pinned to each other by `test_elements.py` here and
`tests/test_elements.py` there agreeing on the same cases.
"""

from __future__ import annotations

import math

# The element's attributes: everything on a cde_registry row but its identity, its
# bindings and its version bookkeeping. A proposal carries all of them, as they will be.
ATTRS = ("cde_name", "business_term", "data_class", "definition", "expected_signature",
         "criticality", "pii", "regulatory_basis", "tolerance_pct", "business_domain",
         "owner_group")

WAIVER_MARK = "[second approver waived]"   # dq_app/domain/onboarding.py says the same


def marker(proposal_id: str) -> str:
    """Starts the note on every register version written for a proposal. The view
    v_cde_proposal_current reads it back as `applied_version`."""
    return f"[cde_proposal {proposal_id}]"


def _norm(v):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if isinstance(v, str):
        return v.strip() or None
    return v


def attrs_of(row: dict) -> dict:
    return {a: _norm(row.get(a)) for a in ATTRS}


def changed(before: dict, after: dict) -> list[str]:
    """The attributes that differ, in ATTRS order."""
    b, a = attrs_of(before), attrs_of(after)
    return [k for k in ATTRS if b[k] != a[k]]


def is_self_approval(p: dict) -> bool:
    """Approved by its own author without the waiver mark: refused whatever wrote it."""
    return (str(p.get("proposed_by") or "").lower() == str(p.get("reviewed_by") or "").lower()
            and not str(p.get("review_reason") or "").startswith(WAIVER_MARK))


def refusal(p: dict, versions: list[dict]) -> str | None:
    """Why `p` cannot be applied to an element whose register rows are `versions`
    (every version, any order), or None if it can.

    * register -- the id must never have been used, retired included: a new element
      cannot inherit an old one's history, rules or results.
    * amend / retire -- the element must exist and not be retired, and its attributes
      must be what the author saw at `based_on_version`. Bindings move under it all the
      time (the apply step adds them), so only the attributes are compared: an amend
      carries the whole attribute set, and applying it over someone else's change would
      silently undo that change.
    * amend -- must change something, and may not change the data class of an element
      with bound columns: their checks were generated for the old class.
    """
    if is_self_approval(p):
        return (f"approved by the person who proposed it ({p.get('reviewed_by')}); "
                "it needs a second approver")
    change = p.get("change")
    if change == "register":
        if versions:
            return f"{p['cde_id']} is already used by the register, retired included"
        return None
    if change not in ("amend", "retire"):
        return f"unknown change {change!r}"
    if not versions:
        return f"{p['cde_id']} is not on the register"
    latest = max(versions, key=lambda v: v["cde_version"])
    if latest["status"] == "retired":
        return f"{p['cde_id']} is retired"
    seen = next((v for v in versions if v["cde_version"] == p.get("based_on_version")), None)
    if seen is None:
        return f"{p['cde_id']} has no version {p.get('based_on_version')}"
    moved = changed(seen, latest)
    if moved:
        return (f"{p['cde_id']} changed since the proposal was written "
                f"({', '.join(moved)}); propose again from the current version")
    if change == "amend":
        diff = changed(latest, p)
        if not diff:
            return "the amendment changes nothing"
        bound = latest.get("bindings")
        if "data_class" in diff and bound is not None and len(bound):
            return ("the data class of an element with bound columns cannot change: their "
                    "checks were generated for the old class. Retire it and register anew")
    return None

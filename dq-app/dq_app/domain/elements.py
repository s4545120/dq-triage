"""CDE onboarding — proposing, deciding and reading changes to the element register.

A person proposes to register, amend or retire a critical data element
(`config.cde_proposal`); a SECOND person decides it (`config.cde_review`); the onboarding
job's `apply_elements` step writes the approved change onto `config.cde_registry`. The
app writes the first two and never the register, so "no app writes the element
register" stays true -- the same shape as a binding (domain/onboarding.py).

Twins kept here, labelled:

* `proposal_state` is the copy of `v_cde_proposal_current`
  (sql/ddl/18_views_cde_onboarding.sql): a decision recorded in this session has to
  move the page before any warehouse re-runs the view.
* `refusal` is the copy of `onboarding/elements.refusal`, the job's check before it
  applies an approved proposal. The app runs it so a reviewer is told an approval will
  not apply before giving it, rather than finding the proposal stuck at `approved`.

A REGISTERED ELEMENT STARTS UNBOUND, and the register calls that status 'proposed'
(09's `cde_registry_registered_has_bindings`). The page says "not yet bound".
"""

from __future__ import annotations

import math
import re

import pandas as pd

from dq_app.domain.onboarding import WAIVER_MARK, OnboardingRejected

# Written to config.cde_proposal and config.cde_review, in sql/ddl/17's order.
# Spelled out: fixtures/verify.py reads these lists as literals and diffs them.
PROPOSAL_COLUMNS = [
    "proposal_id", "proposed_at", "cde_id", "change", "based_on_version", "cde_name",
    "business_term", "data_class", "definition", "expected_signature", "criticality", "pii",
    "regulatory_basis", "tolerance_pct", "business_domain", "owner_group", "proposed_by",
    "reason",
]
REVIEW_COLUMNS = ["proposal_id", "decision", "reviewed_by", "reviewed_at", "reason"]

ATTRS = ("cde_name", "business_term", "data_class", "definition", "expected_signature",
         "criticality", "pii", "regulatory_basis", "tolerance_pct", "business_domain",
         "owner_group")
ATTR_LABEL = {
    "cde_name": "Name", "business_term": "Business term", "data_class": "Data class",
    "definition": "Definition", "expected_signature": "Expected value pattern",
    "criticality": "Criticality", "pii": "Personal data", "regulatory_basis": "Regulatory basis",
    "tolerance_pct": "Tolerance", "business_domain": "Domain", "owner_group": "Owner group",
}
CHANGES = ("register", "amend", "retire")
CHANGE_LABEL = {"register": "Register", "amend": "Amend", "retire": "Retire"}
# The classes 09 lists, closed by 17's cde_proposal_data_class_enum. A new one is a DDL
# change and a check template, not a word in a form.
DATA_CLASSES = ("email_address", "person_name", "date_of_birth", "phone_number", "msisdn",
                "national_id", "device_id", "account_id", "other")
CRITICALITIES = ("critical", "high", "medium", "low")
STATES = ("open", "approved", "applied", "rejected")
STATE_LABEL = {"open": "Awaiting review", "approved": "Approved · awaiting the job",
               "applied": "Applied", "rejected": "Rejected"}
DECISIONS = ("approved", "rejected")
ID_SHAPE = re.compile(r"^CDE_[A-Z0-9_]+$")


def _empty(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype="object") for c in columns})


def _norm(v):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, str):
        return v.strip() or None
    if hasattr(v, "item"):          # numpy scalar
        return v.item()
    return v


def attrs_of(row) -> dict:
    row = dict(row)
    return {a: _norm(row.get(a)) for a in ATTRS}


def changed(before, after) -> list[str]:
    b, a = attrs_of(before), attrs_of(after)
    return [k for k in ATTRS if b[k] != a[k]]


def suggest_id(name: str, taken: set[str]) -> str:
    """`CDE_` and the name in upper snake case, made unique against every id the register
    or a proposal has ever held."""
    stem = re.sub(r"[^A-Z0-9]+", "_", (name or "").upper()).strip("_")[:40] or "ELEMENT"
    cid, n = f"CDE_{stem}", 2
    while cid in taken:
        cid, n = f"CDE_{stem}_{n}", n + 1
    return cid


def signature_problem(pattern: str | None) -> str | None:
    """Why a value pattern will not do what its author means on Spark, or None.

    Discovery runs it with Spark RLIKE, which is Java regex. Python's compile catches
    what both refuse; POSIX classes are the trap both ACCEPT -- Java reads `[[:space:]]`
    as a set of the letters `: s p a c e`, which is how the DQ Queries' title and address
    checks came to be wrong (CLAUDE.md, "Bugs in the source queries")."""
    if not pattern:
        return None
    if re.search(r"\[\[:[a-z]+:\]", pattern):
        return ("POSIX classes like [[:space:]] are a set of letters in Spark's regex. "
                "Use \\s, \\d, \\p{Alpha} and so on.")
    try:
        re.compile(pattern)
    except re.error as exc:
        return f"Not a valid pattern: {exc}."
    return None


# --- Which checks a bound column gets ------------------------------------------------------
# The app reads config.check_template, which says each template's class but not which
# ones check a value's FORMAT. The precedence rule (onboarding/templates.for_class) needs
# that: an element's own pattern (TPL_PATTERN) is generated only where its class has no
# format check of its own. This is the labelled copy of the `checks_format` flags, pinned
# to the job's by tests/test_elements.py.
ANY_CLASS = "*"
PATTERN_TEMPLATE = "TPL_PATTERN"
FORMAT_TEMPLATES = frozenset({"TPL_EMAIL_FMT", "TPL_PHONE_AU_FMT", "TPL_NAME_STRUCTURE",
                              "TPL_ID_NUMERIC", "TPL_DOB_PARSEABLE"})
# Copy of onboarding/templates.CONFIRMED_SIGNATURES: the elements whose signature the
# business has confirmed. Every other signature was profiled from pilot data, so no
# pattern check is generated from it.
CONFIRMED_SIGNATURES = frozenset({"CDE_CUST_NAME", "CDE_CUST_DOB", "CDE_CUST_EMAIL",
                                  "CDE_CUST_MOBILE", "CDE_CUST_LANDLINE"})


def templates_for(templates: pd.DataFrame, data_class, signature,
                  cde_id: str | None = None) -> pd.DataFrame:
    """The template rows a column bound to such an element gets, latest version each."""
    if templates.empty:
        return templates
    # Latest version of each, in the table's own order (the generator's order).
    newest = templates.groupby("template_id")["template_version"].transform("max")
    t = templates[templates["template_version"] == newest].drop_duplicates("template_id")
    own = t[t["data_class"] == data_class]
    if _norm(signature) and cde_id in CONFIRMED_SIGNATURES \
            and not own["template_id"].isin(FORMAT_TEMPLATES).any():
        own = pd.concat([own, t[t["template_id"] == PATTERN_TEMPLATE]])
    return own.reset_index(drop=True)


def check_words(templates: pd.DataFrame) -> list[str]:
    """Each template's title as a reader says it: "is present", "matches its expected
    pattern"."""
    return [str(x).replace("{element}", "").strip() for x in templates.get("title", [])]


# --- State --------------------------------------------------------------------------------

def proposal_state(proposals: pd.DataFrame, reviews: pd.DataFrame,
                   registry: pd.DataFrame) -> pd.DataFrame:
    """Every proposal with its decision and state -- the twin of v_cde_proposal_current."""
    cols = PROPOSAL_COLUMNS + ["decision", "reviewed_by", "reviewed_at", "review_reason",
                               "applied_version", "state"]
    if proposals.empty:
        return _empty(cols)
    out = proposals.reindex(columns=list(dict.fromkeys([*proposals.columns,
                                                        *PROPOSAL_COLUMNS])))
    if len(reviews):
        r = (reviews.sort_values("reviewed_at").groupby("proposal_id", as_index=False).tail(1)
             .rename(columns={"reason": "review_reason"}))
        out = out.merge(r, on="proposal_id", how="left")
    else:
        for c in ("decision", "reviewed_by", "reviewed_at", "review_reason"):
            out[c] = None
    applied = {}
    if len(registry) and "note" in registry:
        for note, v in zip(registry["note"], registry["cde_version"]):
            m = re.match(r"^\[cde_proposal ([^\]]+)\]", str(note or ""))
            if m:
                pid = m.group(1)
                applied[pid] = min(int(v), applied.get(pid, int(v)))
    out["applied_version"] = out["proposal_id"].map(applied)

    def _state(d, pid):
        d = _norm(d)
        if d is None:
            return "open"
        if d == "rejected":
            return "rejected"
        return "applied" if pid in applied else "approved"

    out["state"] = [_state(d, p) for d, p in zip(out["decision"], out["proposal_id"])]
    return out[cols].sort_values("proposed_at", ascending=False).reset_index(drop=True)


def open_for(state: pd.DataFrame, cde_id: str) -> pd.DataFrame:
    """Proposals on `cde_id` not yet decided or not yet applied: at most one at a time."""
    if state.empty:
        return state
    return state[(state["cde_id"] == cde_id) & state["state"].isin(("open", "approved"))]


def versions_of(registry: pd.DataFrame, cde_id: str) -> list[dict]:
    if registry.empty:
        return []
    return registry[registry["cde_id"] == cde_id].to_dict("records")


def latest_version(registry: pd.DataFrame, cde_id: str) -> dict | None:
    vs = versions_of(registry, cde_id)
    return max(vs, key=lambda v: v["cde_version"]) if vs else None


def is_bound(row: dict | None) -> bool:
    b = row.get("bindings") if row else None
    return b is not None and len(b) > 0


def is_self_approval(p: dict) -> bool:
    return (str(p.get("proposed_by") or "").lower() == str(p.get("reviewed_by") or "").lower()
            and not str(_norm(p.get("review_reason")) or "").startswith(WAIVER_MARK))


def refusal(p: dict, versions: list[dict]) -> str | None:
    """Why the onboarding job will not apply `p`, or None. The twin of
    `onboarding/elements.refusal` -- see that docstring for each rule."""
    if _norm(p.get("reviewed_by")) and is_self_approval(p):
        return "approved by the person who proposed it; it needs a second approver"
    change = p.get("change")
    if change == "register":
        return "the id is already used by the register" if versions else None
    if not versions:
        return f"{p['cde_id']} is not on the register"
    latest = max(versions, key=lambda v: v["cde_version"])
    if latest["status"] == "retired":
        return f"{p['cde_id']} is retired"
    seen = next((v for v in versions
                 if v["cde_version"] == _norm(p.get("based_on_version"))), None)
    if seen is None:
        return f"{p['cde_id']} has no version {p.get('based_on_version')}"
    moved = changed(seen, latest)
    if moved:
        return (f"the element changed since this was written "
                f"({', '.join(ATTR_LABEL[m].lower() for m in moved)})")
    if change == "amend":
        diff = changed(latest, p)
        if not diff:
            return "the amendment changes nothing"
        if "data_class" in diff and is_bound(latest):
            return ("the data class of an element with bound columns cannot change: "
                    "their checks were generated for the old class")
    return None


# --- Validation -------------------------------------------------------------------------

def validate_proposal(change: str, cde_id: str, attrs: dict, reason: str, *,
                      registry: pd.DataFrame, state: pd.DataFrame,
                      based_on_version: int | None) -> None:
    """What the app refuses before anything is written. 17's constraints refuse the
    same shapes again; this says why in words."""
    if change not in CHANGES:
        raise OnboardingRejected(f"Unknown change {change!r}.")
    if not (reason or "").strip():
        raise OnboardingRejected("Say why. The reviewer decides on it, and it is kept on "
                                 "the register.")
    if not ID_SHAPE.match(cde_id or ""):
        raise OnboardingRejected("An element id is CDE_ followed by capitals, digits and "
                                 "underscores.")
    if len(open_for(state, cde_id)):
        raise OnboardingRejected(f"{cde_id} already has a change waiting. Decide that one "
                                 "first, or reject it.")
    versions = versions_of(registry, cde_id)
    taken = set(state["cde_id"]) if len(state) else set()
    if change == "register":
        if versions or cde_id in taken:
            raise OnboardingRejected(f"{cde_id} is already used, and ids are never reused. "
                                     "Choose another.")
    else:
        why = refusal({"cde_id": cde_id, "change": change,
                       "based_on_version": based_on_version, **attrs}, versions)
        if why:
            raise OnboardingRejected(why[0].upper() + why[1:] + ".")
    if change == "retire":
        return
    a = attrs_of(attrs)
    if not a["cde_name"]:
        raise OnboardingRejected("Give the element a name.")
    if not a["definition"]:
        raise OnboardingRejected("Say what the element means. That is what a reviewer "
                                 "agrees to.")
    if a["data_class"] not in DATA_CLASSES:
        raise OnboardingRejected(f"Data class must be one of {', '.join(DATA_CLASSES)}.")
    if a["criticality"] not in CRITICALITIES:
        raise OnboardingRejected(f"Criticality must be one of {', '.join(CRITICALITIES)}.")
    if a["pii"] is None:
        raise OnboardingRejected("Say whether the element is personal data.")
    tol = a["tolerance_pct"]
    if tol is not None and not 0.0 <= float(tol) <= 100.0:
        raise OnboardingRejected("Tolerance is a share of rows, between 0 and 100.")
    sig = signature_problem(a["expected_signature"])
    if sig:
        raise OnboardingRejected(sig)


def validate_review(proposal: dict, reviewer: str, decision: str, reason: str | None,
                    allow_self: bool = False) -> None:
    """A person cannot approve their own proposal; rejecting it (withdrawing) is fine."""
    if decision not in DECISIONS:
        raise OnboardingRejected(f"Unknown decision {decision!r}.")
    if (decision == "approved" and not allow_self
            and str(proposal.get("proposed_by") or "").lower() == str(reviewer).lower()):
        raise OnboardingRejected("You proposed this, so a second person must approve it.")
    if decision == "rejected" and not (reason or "").strip():
        raise OnboardingRejected("Say why you are rejecting it. The reason is kept with "
                                 "the decision.")


# --- What a change would touch -------------------------------------------------------------

def rules_on(rule_current: pd.DataFrame, cde_id: str) -> pd.DataFrame:
    if rule_current.empty:
        return rule_current
    r = rule_current[(rule_current["cde_id"] == cde_id) & (rule_current["status"] != "retired")]
    return r.reset_index(drop=True)


def over_tolerance(rule_current: pd.DataFrame, cde_id: str, tolerance) -> list[str]:
    """Rules on the element whose limit is looser than `tolerance`. The register's
    tolerance is a ceiling on every rule's fail_threshold_pct; lowering it below a
    rule's limit leaves that rule for the threshold job to advise on. Reported, never
    changed here."""
    tol = _norm(tolerance)
    r = rules_on(rule_current, cde_id)
    if tol is None or r.empty:
        return []
    lim = pd.to_numeric(r["fail_threshold_pct"], errors="coerce")
    return sorted(r.loc[lim > float(tol), "rule_id"].tolist())


def retire_impact(cde_id: str, latest: dict | None, rule_current: pd.DataFrame,
                  cohorts: pd.DataFrame) -> dict:
    """What retiring would take with it: its bindings leave coverage, its rules get a
    retired version, and problems carrying its rules stay as history."""
    r = rules_on(rule_current, cde_id)
    ids = set(r["rule_id"]) if len(r) else set()
    problems = []
    if ids and len(cohorts):
        for cid, members in zip(cohorts["cohort_id"], cohorts["member_rule_ids"]):
            if ids & set(list(members) if members is not None else []):
                problems.append(cid)
    bindings = list(latest.get("bindings")) if is_bound(latest) else []
    return {
        "bindings": [f"{str(b['target_table']).split('.')[-1]}.{b['target_column']}"
                     for b in bindings],
        "active": sorted(r.loc[r["status"] == "active", "rule_id"]) if len(r) else [],
        "shadow": sorted(r.loc[r["status"] == "shadow", "rule_id"]) if len(r) else [],
        "problems": sorted(problems),
    }

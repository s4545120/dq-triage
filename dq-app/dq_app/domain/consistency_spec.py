"""Cross-table consistency checks, written from a spec rather than by hand.

Each spec renders to the fields of one `config.rule_registry` row (`rule_expr`,
`join_sql`, `scope_filter`, `rule_type`, `target_table`, `target_column`) and runs
through the check runner's existing cross-table path -- no new runner shape, no DDL.
The runner already reads every side of the join on its current records and batches
rules that share a join (jobs/run_checks.py, 2026-10-12).

Three kinds:

* `Orphan`    -- a child row whose key finds no parent. The NULL-key policy is a
  required field with no default, because the tools disagree (DQX and dbt ignore a
  NULL foreign key, Soda fails it) and so do the cases: a contact role with no contact
  id is a defect, an order with no promotion code is not.
* `Agreement` -- a fact stored on two tables, compared per matched pair. Null-safe by
  construction (`<=>`), which is the whole point: `XREF_NAME_AGREEMENT` was written
  with `<>` and missed every pair with a NULL on one side. Both sides go through one
  named comparison, so a blank and a NULL are the same value and a phone number is
  compared as digits. The empty-on-one-side policy is required too.
* `Reconcile` -- an aggregate on one table against an aggregate on another, overall or
  per group, within an absolute or relative tolerance. Rendered as a FULL OUTER JOIN of
  the two grouped aggregates, so the runner counts GROUPS: rows_scanned is the groups on
  either side, a violation is a group out of tolerance or present on one side only --
  which DQX's `aggr_matches_dataset` does not report and this does.

`unsafe_comparisons` is the lint: a cross-table expression comparing with `<>` or `!=`.
fixtures/verify.py runs it over the registry.

Trusted config, like everything the registry holds: table names, ON conditions,
filters and aggregate expressions are SQL. Identifiers this module invents (aliases,
`__g0`, `__v`) are fixed; group and column names are checked as identifiers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
QUALIFIED = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$")   # alias.column

# One comparison per kind of value. `{x}` is the column; the result is NULL for "no
# value", so a blank string and a NULL compare equal. The helpers are canonical names,
# rewritten per layout like every other rule's.
COMPARE = {
    "exact":     "{x}",
    "text":      "nullif(lower(regexp_replace(trim({x}), '\\\\s+', ' ')), '')",
    "phone_au":  "nullif(dq.fn.au_phone_digits_v1({x}), '')",
    "day":       "try_cast({x} AS DATE)",
    "number":    "try_cast({x} AS DECIMAL(38, 6))",
}
# try_cast, not CAST: the warehouse runs ANSI mode, where one unparseable value raises
# and takes every rule in the shared join down with it. An unparseable value compares
# as no value, so with empty_one_side='differs' it is still counted.


def _ident(name: str, what: str) -> str:
    if not IDENT.match(str(name)):
        raise ValueError(f"{what} {name!r} is not a plain identifier")
    return name


def _qualified(ref: str, what: str) -> str:
    if not QUALIFIED.match(str(ref)):
        raise ValueError(f"{what} {ref!r} must be alias.column")
    return ref


def _num(v: float, what: str) -> str:
    v = float(v)
    if v < 0 or v != v:
        raise ValueError(f"{what} must be zero or more")
    return repr(v)


@dataclass(frozen=True)
class Step:
    """One table joined onto the path: `JOIN <table> <alias> ON <on>`."""
    table: str
    alias: str
    on: str


def path(table: str, alias: str, *steps: Step, kind: str = "JOIN") -> str:
    """A join_sql body: the driving table, then each step in order."""
    _ident(alias, "alias")
    out = f"{table} {alias}"
    for s in steps:
        out += f" {kind} {s.table} {_ident(s.alias, 'alias')} ON {s.on}"
    return out


# --- Orphans --------------------------------------------------------------------------

NULL_KEY = ("ignore", "fail")


@dataclass(frozen=True)
class Orphan:
    """Every `child` row's `child_key` finds a `parent` row with `parent_key`."""
    child: str
    child_key: tuple[str, ...]
    parent: str
    parent_key: tuple[str, ...]
    null_key: str                     # ignore | fail -- required, see the module doc

    def render(self) -> dict:
        if self.null_key not in NULL_KEY:
            raise ValueError(f"null_key must be one of {NULL_KEY}, got {self.null_key!r}")
        if not self.child_key or len(self.child_key) != len(self.parent_key):
            raise ValueError("child_key and parent_key need the same number of columns")
        ck = [_ident(c, "child key") for c in self.child_key]
        pk = [_ident(c, "parent key") for c in self.parent_key]
        on = " AND ".join(f"ch.{c} = pa.{p}" for c, p in zip(ck, pk))
        # The parent's key is NULL after a LEFT JOIN only when nothing matched: the
        # match was on it, so a matched parent cannot carry a NULL there.
        expr = f"pa.{pk[0]} IS NULL"
        scope = (None if self.null_key == "fail"
                 else " AND ".join(f"ch.{c} IS NOT NULL" for c in ck))
        return dict(rule_type="referential", target_table=self.child,
                    target_column=ck[0] if len(ck) == 1 else None,
                    join_sql=f"{self.child} ch LEFT JOIN {self.parent} pa ON {on}",
                    rule_expr=expr, scope_filter=scope)


# --- Agreement ------------------------------------------------------------------------

EMPTY_ONE_SIDE = ("differs", "skip")


@dataclass(frozen=True)
class Agreement:
    """`left` and `right` (each `alias.column`) hold the same value on every matched
    pair of `join_sql`. `target_table` is the table `left` is on: the breach is
    reported against it."""
    join_sql: str
    target_table: str
    left: str
    right: str
    compare: str                      # a key of COMPARE
    empty_one_side: str               # differs | skip -- required
    tolerance: float = 0.0            # `number` only: an absolute difference allowed

    def render(self) -> dict:
        if self.compare not in COMPARE:
            raise ValueError(f"compare must be one of {sorted(COMPARE)}, got {self.compare!r}")
        if self.empty_one_side not in EMPTY_ONE_SIDE:
            raise ValueError(f"empty_one_side must be one of {EMPTY_ONE_SIDE}")
        if self.tolerance and self.compare != "number":
            raise ValueError("a tolerance applies to the number comparison only")
        lv = COMPARE[self.compare].format(x=_qualified(self.left, "left"))
        rv = COMPARE[self.compare].format(x=_qualified(self.right, "right"))
        expr = f"NOT ({lv} <=> {rv})"
        if self.tolerance:
            expr += (f" AND ({lv} IS NULL OR {rv} IS NULL OR "
                     f"abs({lv} - {rv}) > {_num(self.tolerance, 'tolerance')})")
        # Both empty is agreement and needs no scope: NULL <=> NULL is true.
        scope = (None if self.empty_one_side == "differs"
                 else f"{lv} IS NOT NULL AND {rv} IS NOT NULL")
        return dict(rule_type="consistency", target_table=self.target_table,
                    target_column=self.left.split(".", 1)[1], join_sql=self.join_sql,
                    rule_expr=expr, scope_filter=scope)


# --- Aggregate reconciliation ---------------------------------------------------------

@dataclass(frozen=True)
class Side:
    """One aggregate: `measure` (e.g. `count(*)`, `sum(AMT)`) over `table`, rows kept
    by `where`, grouped by `group_by`."""
    table: str
    measure: str
    where: str | None = None
    group_by: tuple[str, ...] = ()

    def sql(self, alias: str) -> str:
        groups = [_ident(g, "group column") for g in self.group_by]
        cols = [f"{g} AS __g{i}" for i, g in enumerate(groups)]
        cols += [f"{self.measure} AS __v", "1 AS __present"]
        where = f" WHERE {self.where}" if self.where else ""
        group = f" GROUP BY {', '.join(groups)}" if groups else ""
        return f"(SELECT {', '.join(cols)} FROM {self.table}{where}{group}) {alias}"


@dataclass(frozen=True)
class Reconcile:
    """`left`'s aggregate equals `right`'s, per group when grouped, within
    max(abs_tolerance, rel_tolerance * |right|). Reported against `left.table`."""
    left: Side
    right: Side
    abs_tolerance: float = 0.0
    rel_tolerance: float = 0.0

    def render(self) -> dict:
        if len(self.left.group_by) != len(self.right.group_by):
            raise ValueError("both sides need the same number of group columns")
        n = len(self.left.group_by)
        lhs, rhs = self.left.sql("l"), self.right.sql("r")
        if n:
            on = " AND ".join(f"l.__g{i} <=> r.__g{i}" for i in range(n))
            join = f"{lhs} FULL OUTER JOIN {rhs} ON {on}"
        else:
            join = f"{lhs} CROSS JOIN {rhs}"          # an ungrouped aggregate is one row
        tol = (f"greatest({_num(self.abs_tolerance, 'abs_tolerance')}, "
               f"{_num(self.rel_tolerance, 'rel_tolerance')} * abs(r.__v))")
        expr = ("l.__present IS NULL OR r.__present IS NULL OR "
                "(NOT (l.__v <=> r.__v) AND (l.__v IS NULL OR r.__v IS NULL OR "
                f"abs(l.__v - r.__v) > {tol}))")
        return dict(rule_type="consistency", target_table=self.left.table,
                    target_column=None, join_sql=join, rule_expr=expr, scope_filter=None)


# --- The lint -------------------------------------------------------------------------

_LITERAL = re.compile(r"'(?:\\.|[^'\\])*'")


def unsafe_comparisons(rule_expr: str, join_sql: str | None) -> list[str]:
    """The `<>` / `!=` comparisons in a cross-table rule. NULL on either side makes them
    unknown, and count_if drops an unknown row, so the disagreement this kind of rule
    exists to catch -- a value on one side, none on the other -- is never counted.
    Single-table rules are not linted: comparing a column to a literal with `<>`
    against a NULL is a completeness question, which a not-null rule asks."""
    if join_sql is None or join_sql != join_sql or not str(join_sql).strip():
        return []                       # None, NaN (a NULL read through pandas), blank
    text = _LITERAL.sub("''", str(rule_expr))
    return [text[max(0, m.start() - 30):m.end() + 30].strip()
            for m in re.finditer(r"<>|!=", text)]


# --- A stored proposal (2026-10-13) ------------------------------------------------------
# The app's builder writes a check as a SPEC -- structured fields, never SQL -- to
# config.consistency_proposal (sql/ddl/22). A second person decides it, and
# `onboard.py apply_consistency` renders the spec HERE and writes the rule in shadow.
# The app renders the same spec with its twin (dq_app/domain/consistency.render_spec) to
# show and test it; the proposal stores what the app rendered, and the job refuses one
# whose spec renders differently here. tests pin the two renderers to the same output.
#
#   orphan     {"kind": "orphan", "hops": [HOP], "null_key": "fail" | "ignore"}
#   agreement  {"kind": "agreement", "hops": [HOP, HOP?], "left": COL, "right": COL,
#               "compare": COMPARE key, "empty_one_side": "differs" | "skip",
#               "tolerance": number}
#   totals     {"kind": "totals", "left": SIDE, "right": SIDE,
#               "abs_tolerance": number, "rel_tolerance": number}
#   HOP        {"from": table, "to": table, "keys": [[from_col, to_col], ...]}
#   SIDE       {"table": table, "agg": "count" | "count_distinct" | "sum",
#               "column": COL | null, "group_by": COL | null}

import hashlib  # noqa: E402
import json  # noqa: E402

KINDS = ("orphan", "agreement", "totals")
AGGS = ("count", "count_distinct", "sum")
WAIVER_MARK = "[second approver waived]"   # dq_app/domain/onboarding.py says the same
MAX_HOPS = 2


def _hops(spec: dict, most: int) -> list[dict]:
    hops = spec.get("hops") or []
    if not 1 <= len(hops) <= most:
        raise ValueError(f"a {spec['kind']} check takes 1 to {most} links, got {len(hops)}")
    for i, h in enumerate(hops):
        if not h.get("keys"):
            raise ValueError("every link needs at least one key pair")
        for a, b in h["keys"]:
            _ident(a, "key column")
            _ident(b, "key column")
        if i and h["from"] != hops[i - 1]["to"]:
            raise ValueError("each link must start where the one before it ends")
    return hops


def _measure(side: dict) -> str:
    agg, col = side.get("agg"), side.get("column")
    if agg not in AGGS:
        raise ValueError(f"agg must be one of {AGGS}, got {agg!r}")
    if agg == "count":
        return "count(*)"
    _ident(col, "measured column")
    return f"count(DISTINCT {col})" if agg == "count_distinct" else f"sum({col})"


def render_spec(spec: dict, rel=None) -> dict:
    """The rule fields a spec renders to. `rel` maps a table name to what is written in
    its place in the SQL -- the app passes the table's current-record relation to TEST a
    spec; the stored rule always carries the plain names."""
    rel = rel or (lambda t: t)
    kind = spec.get("kind")
    if kind == "orphan":
        (h,) = _hops(spec, 1)
        d = Orphan(rel(h["from"]), tuple(k[0] for k in h["keys"]), rel(h["to"]),
                   tuple(k[1] for k in h["keys"]), spec.get("null_key")).render()
        d["target_table"] = h["from"]
        return d
    if kind == "agreement":
        hops = _hops(spec, MAX_HOPS)
        steps = [Step(rel(h["to"]), f"t{i + 1}",
                      " AND ".join(f"t{i}.{a} = t{i + 1}.{b}" for a, b in h["keys"]))
                 for i, h in enumerate(hops)]
        join = path(rel(hops[0]["from"]), "t0", *steps)
        left = f"t0.{_ident(spec.get('left'), 'compared column')}"
        right = f"t{len(hops)}.{_ident(spec.get('right'), 'compared column')}"
        d = Agreement(join, hops[0]["from"], left, right, spec.get("compare"),
                      spec.get("empty_one_side"), float(spec.get("tolerance") or 0)).render()
        return d
    if kind == "totals":
        sides = []
        for s in (spec["left"], spec["right"]):
            g = s.get("group_by")
            sides.append(Side(rel(s["table"]), _measure(s),
                              group_by=(_ident(g, "group column"),) if g else ()))
        d = Reconcile(sides[0], sides[1], float(spec.get("abs_tolerance") or 0),
                      float(spec.get("rel_tolerance") or 0)).render()
        d["target_table"] = spec["left"]["table"]
        return d
    raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")


def tables_of(spec: dict) -> list[str]:
    """Every table a spec reads, first the one a failure is reported against."""
    if spec["kind"] == "totals":
        out = [spec["left"]["table"], spec["right"]["table"]]
    else:
        out = [spec["hops"][0]["from"]] + [h["to"] for h in spec["hops"]]
    return list(dict.fromkeys(out))


def _norm(v) -> str:
    if v is None or v != v:
        return ""
    return re.sub(r"\s+", " ", str(v).strip()).lower()


def fingerprint(rule: dict) -> str:
    """What a rule DOES, not what it is called: its join, predicate and scope, case and
    whitespace folded. Two rules with one fingerprint are one check written twice."""
    body = " | ".join(_norm(rule.get(k)) for k in ("join_sql", "rule_expr", "scope_filter"))
    return hashlib.sha256(body.encode()).hexdigest()[:16]


def marker(proposal_id: str) -> str:
    """Starts the note on the rule version the job writes for a proposal; the view
    v_consistency_proposal_current reads it back as `applied`."""
    return f"[consistency_proposal {proposal_id}]"


def refusal(p: dict, rules: list[dict], registered: set[str]) -> str | None:
    """Why the job may not apply approved proposal `p` (a row of
    v_consistency_proposal_current), or None. `rules` is every version of every rule;
    `registered` the key attributes that can carry one. The app's twin shows the same
    reason to the reviewer before the job runs."""
    if (str(p.get("proposed_by") or "").lower() == str(p.get("reviewed_by") or "").lower()
            and not str(p.get("review_reason") or "").startswith(WAIVER_MARK)):
        return "approved by the person who proposed it"
    if any(r["rule_id"] == p["rule_id"] for r in rules):
        return f"rule id {p['rule_id']} is already used"
    if p["cde_id"] not in registered:
        return f"{p['cde_id']} is not a registered key attribute"
    try:
        again = render_spec(json.loads(p["spec"]))
    except (ValueError, KeyError, TypeError) as exc:
        return f"the spec does not render: {exc}"
    for k in ("join_sql", "rule_expr", "scope_filter"):
        if _norm(again.get(k)) != _norm(p.get(k)):
            return f"the job renders {k} differently from the proposal"
    latest: dict[str, dict] = {}
    for r in rules:
        if r["rule_id"] not in latest or r["rule_version"] > latest[r["rule_id"]]["rule_version"]:
            latest[r["rule_id"]] = r
    fp = fingerprint(again)
    for r in latest.values():
        if r.get("status") != "retired" and fingerprint(r) == fp:
            return f"{r['rule_id']} already does the same check"
    return None

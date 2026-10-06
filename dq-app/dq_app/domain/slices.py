"""Data slices — which rows of a monitored table are the population being checked.

A slice belongs to the TABLE (`config.monitored_table`), where a `scope_filter` belongs
to a RULE: the slice says which rows anyone cares about at all (`migration_scope_flag =
1`), a scope filter which of those a check applies to (postpaid only). The check runner
ANDs the two, so a rule missing its own scope is still a scope mismatch under any slice
-- COH-B is untouched by this module.

STRUCTURED, NEVER FREE SQL. A person picks columns, an operator and literal values, and
`render` builds the predicate: identifiers are checked against the table's real columns
and quoted, literals are typed against the column and escaped. A slice is SQL the runner
interpolates into every query on the table, so a text box here would be a way to make
the runner run anything. The one shape beyond plain conditions is MEMBERSHIP -- "rows
whose key appears in another table where ..." -- because the case that asked for slices
keeps its scope flag in a different table from the rows it scopes.

A SLICE CAN HIDE DEFECTS. "Exclude the rows that fail" is a one-line slice. So:

* while no check on the table is active, nothing is scored and one person sets the
  slice (`slice_change = 'set'`);
* once a check is active, a change is a PROPOSAL (`'proposed'`) that a second person
  approves or rejects -- the same rule as a person's binding suggestion, waived on the
  same test deployments and marked the same way;
* every run records the rows in the table and the rows in the slice (`check_run.
  table_rows`, `slice_rows`), so a slice that grows to hide failures shows up as the
  population shrinking.

HOW THE ROW CARRIES IT. Every `monitored_table` version holds the slice IN FORCE
(`slice_filter`, `slice_spec`, `slice_version` -- the table_version it took effect at)
and any PENDING proposal (`slice_proposed_*`), so the latest version is the whole state
and the runner's existing "latest version per table" read needs no fold. `slice_change`
says what that one version did to the slice. `carry_forward` is the one definition of
what a version that does not touch the slice copies from the one before.
"""

from __future__ import annotations

import json
import re

import pandas as pd

SLICE_COLUMNS = ["slice_filter", "slice_spec", "slice_version", "slice_change",
                 "slice_proposed_filter", "slice_proposed_spec", "slice_proposed_by"]
CHANGES = ("set", "proposed", "approved", "rejected")

# Operators a person can pick, and the words the page uses for them. `not_in` is here
# because excluding test accounts is a real slice; it is also the operator a person
# would use to hide rows, which is what the second approver and the row counts are for.
OPS = {"=": "is", "in": "is one of", "not_in": "is not one of", "not_null": "is present"}

# Unity Catalog's data_type strings. Anything else is rendered as a quoted string.
_INT = re.compile(r"^(tinyint|smallint|int|integer|bigint|long|byte|short)$", re.I)
_NUM = re.compile(r"^(float|double|real|decimal(\(\d+,\s*\d+\))?|numeric.*)$", re.I)
_BOOL = re.compile(r"^boolean$", re.I)
_TABLE_PART = re.compile(r"^[A-Za-z0-9_\-]{1,255}$")


class SliceRejected(ValueError):
    """A slice the rules refuse. Nothing was written."""


# --- The spec -----------------------------------------------------------------------------
# {"where": [{"column": c, "op": op, "values": [...]}, ...],
#  "member_of": {"column": c, "table": "cat.sch.tbl", "key": k,
#                "where": [{"column": ..., "op": ..., "values": [...]}]}}   (optional)
# An empty spec -- no conditions, no membership -- is the whole table.

def normalise(spec: dict | None) -> dict:
    """The canonical form: trimmed, empty parts dropped, so two specs that say the same
    thing compare and serialise equal."""
    spec = spec or {}

    def conds(cs):
        out = []
        for c in cs or []:
            col = str(c.get("column") or "").strip()
            op = str(c.get("op") or "").strip()
            vals = [str(v).strip() for v in (c.get("values") or []) if str(v).strip()]
            if col or op or vals:
                out.append({"column": col, "op": op,
                            "values": [] if op == "not_null" else vals})
        return out

    out: dict = {"where": conds(spec.get("where"))}
    m = spec.get("member_of")
    if m and any(str(m.get(k) or "").strip() for k in ("column", "table", "key")):
        out["member_of"] = {"column": str(m.get("column") or "").strip(),
                            "table": str(m.get("table") or "").strip(),
                            "key": str(m.get("key") or "").strip(),
                            "where": conds(m.get("where"))}
    return out


def is_whole_table(spec: dict | None) -> bool:
    s = normalise(spec)
    return not s["where"] and "member_of" not in s


def dumps(spec: dict | None) -> str:
    return json.dumps(normalise(spec), sort_keys=True)


def loads(text) -> dict:
    if text is None or (isinstance(text, float) and pd.isna(text)) or not str(text).strip():
        return normalise(None)
    return normalise(json.loads(text))


# --- Rendering ----------------------------------------------------------------------------

def _ident(name: str) -> str:
    return "`" + name.replace("`", "``") + "`"


def _table_ident(fqn: str) -> str:
    parts = fqn.split(".")
    if len(parts) != 3 or not all(_TABLE_PART.match(p) for p in parts):
        raise SliceRejected(f"{fqn!r} is not a catalog.schema.table name.")
    return ".".join(_ident(p) for p in parts)


def _literal(value: str, data_type: str | None, column: str) -> str:
    t = (data_type or "").strip()
    if _INT.match(t):
        if not re.fullmatch(r"-?\d+", value):
            raise SliceRejected(f"{column} holds whole numbers; {value!r} is not one.")
        return value
    if _NUM.match(t):
        try:
            float(value)
        except ValueError:
            raise SliceRejected(f"{column} holds numbers; {value!r} is not one.") from None
        return value
    if _BOOL.match(t):
        if value.lower() not in ("true", "false"):
            raise SliceRejected(f"{column} is true or false; {value!r} is neither.")
        return value.lower()
    # Spark string literals honour backslash escapes, so the backslash goes first.
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _conditions(conds: list[dict], types: dict[str, str], where: str) -> list[str]:
    out = []
    for c in conds:
        col, op, vals = c["column"], c["op"], c["values"]
        if col not in types:
            raise SliceRejected(f"{where} has no column {col!r}.")
        if op not in OPS:
            raise SliceRejected(f"Unknown operator {op!r}.")
        q = _ident(col)
        if op == "not_null":
            out.append(f"{q} IS NOT NULL")
            continue
        if not vals:
            raise SliceRejected(f"Give a value for {col}.")
        lits = [_literal(v, types[col], col) for v in vals]
        if op == "=":
            if len(lits) != 1:
                raise SliceRejected(f"{col} 'is' takes one value; use 'is one of' for several.")
            out.append(f"{q} = {lits[0]}")
        else:
            out.append(f"{q} {'NOT IN' if op == 'not_in' else 'IN'} ({', '.join(lits)})")
    return out


def render(spec: dict | None, types: dict[str, str],
           member_types: dict[str, str] | None = None) -> str | None:
    """The predicate the runner ANDs onto every check on the table, or None for the whole
    table. `types` is {column: data_type} for the sliced table, `member_types` the same
    for the membership table. Raises SliceRejected on anything it cannot build safely."""
    s = normalise(spec)
    parts = _conditions(s["where"], types, "This table")
    m = s.get("member_of")
    if m:
        if not (m["column"] and m["table"] and m["key"]):
            raise SliceRejected("Membership needs this table's column, the other table and "
                                "its matching column.")
        if m["column"] not in types:
            raise SliceRejected(f"This table has no column {m['column']!r}.")
        mt = member_types or {}
        if not mt:
            raise SliceRejected(f"{m['table']} has no columns this app can read.")
        if m["key"] not in mt:
            raise SliceRejected(f"{m['table']} has no column {m['key']!r}.")
        inner = _conditions(m["where"], mt, m["table"])
        sub = f"SELECT {_ident(m['key'])} FROM {_table_ident(m['table'])}"
        if inner:
            sub += " WHERE " + " AND ".join(inner)
        parts.append(f"{_ident(m['column'])} IN ({sub})")
    if not parts:
        return None
    return " AND ".join(f"({p})" for p in parts)


def describe(spec: dict | None) -> str:
    """The slice in words, for a reader who does not read SQL."""
    s = normalise(spec)

    def words(c):
        if c["op"] == "not_null":
            return f"{c['column']} is present"
        return f"{c['column']} {OPS.get(c['op'], c['op'])} {', '.join(c['values'])}"

    parts = [words(c) for c in s["where"]]
    m = s.get("member_of")
    if m:
        tail = f"{m['column']} appears as {m['key']} in {m['table']}"
        if m["where"]:
            tail += " where " + " and ".join(words(c) for c in m["where"])
        parts.append(tail)
    return " and ".join(parts) if parts else "the whole table"


# --- The state on a monitored_table row ---------------------------------------------------

def _val(row, key):
    v = row.get(key) if hasattr(row, "get") else None
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


def pending(row) -> dict | None:
    """The proposal waiting for a second person on this version, or None. A decided
    proposal stays on its deciding version as the record of what was decided; it is
    pending only until then."""
    by = _val(row, "slice_proposed_by")
    if by is None or _val(row, "slice_change") in ("approved", "rejected"):
        return None
    return {"filter": _val(row, "slice_proposed_filter"),
            "spec": loads(_val(row, "slice_proposed_spec")), "by": by}


def in_force(row) -> dict:
    v = _val(row, "slice_version")
    return {"filter": _val(row, "slice_filter"), "spec": loads(_val(row, "slice_spec")),
            "version": None if v is None else int(v)}


def carry_forward(prev: dict) -> dict:
    """The slice fields a new version copies from `prev` when it does not change the
    slice itself -- a pause, a resume, a decommission. The slice in force always; a
    pending proposal only while it is pending; `slice_change` never, because it says
    what THIS version did."""
    out = {k: _val(prev, k) for k in ("slice_filter", "slice_spec", "slice_version")}
    if out["slice_version"] is not None:
        out["slice_version"] = int(out["slice_version"])     # pandas reads an INT as float
    p = pending(prev)
    out.update(slice_change=None,
               slice_proposed_filter=p["filter"] if p else None,
               slice_proposed_spec=_val(prev, "slice_proposed_spec") if p else None,
               slice_proposed_by=p["by"] if p else None)
    return out


def needs_second_person(active_checks: int) -> bool:
    """Once any check on the table is active, a slice change can move a score someone is
    reading, so it needs a second person. Before that nothing is scored."""
    return active_checks > 0


WAIVER_MARK = "[second approver waived]"


def validate_decision(proposed_by: str, reviewer: str, decision: str, reason: str | None,
                      allow_self: bool = False) -> None:
    """Approving your own proposal is refused unless waived; rejecting it -- withdrawing
    it -- is not. A rejection says why. Same rule as `onboarding.validate_review`."""
    if decision not in ("approved", "rejected"):
        raise SliceRejected(f"Unknown decision {decision!r}.")
    own = str(proposed_by or "").lower() == str(reviewer or "").lower()
    if decision == "approved" and own and not allow_self:
        raise SliceRejected("You proposed this slice, so a second person must approve it.")
    if decision == "rejected" and not (reason or "").strip():
        raise SliceRejected("Say why. The reason is kept with the table's history.")


# --- What a run measured ------------------------------------------------------------------

def run_population(check_runs: pd.DataFrame, table: str) -> dict | None:
    """{'table_rows', 'slice_rows', 'slice_version', 'run_ts'} for `table` on its latest
    run that recorded them, or None when no run did (a run before slices existed, or a
    table with no row-level check)."""
    need = {"table_rows", "slice_rows"}
    if check_runs.empty or not need <= set(check_runs.columns):
        return None
    r = check_runs[(check_runs["target_table"] == table) & check_runs["table_rows"].notna()]
    if r.empty:
        return None
    last = r.sort_values("run_ts").iloc[-1]
    sv = last.get("slice_version")
    return {"table_rows": int(last["table_rows"]),
            "slice_rows": None if pd.isna(last["slice_rows"]) else int(last["slice_rows"]),
            "slice_version": None if sv is None or pd.isna(sv) else int(sv),
            "run_ts": last["run_ts"]}


def slice_breaks(check_runs: pd.DataFrame, table: str) -> list:
    """The run_ts of every run on `table` whose slice differs from the run before: where
    a trend line changes population and must not be read as data moving."""
    if check_runs.empty or "slice_version" not in check_runs.columns:
        return []
    r = check_runs[check_runs["target_table"] == table][["run_ts", "slice_version"]]
    if r.empty:
        return []
    per_run = r.groupby("run_ts")["slice_version"].max().sort_index()
    out, prev = [], None
    for ts, v in per_run.items():
        v = None if pd.isna(v) else int(v)
        if prev is not None and v != prev[0]:
            out.append(ts)
        prev = (v,)
    return out

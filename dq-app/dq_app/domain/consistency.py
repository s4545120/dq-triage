"""Cross-table consistency checks, read off the rule register.

A consistency check is any current rule with a `join_sql`. What the Consistency page
shows is folded here, pure:

* **Relationships are derived, not declared.** There is no relationship register yet
  (CLAUDE.md, *Consistency checks from a spec*), so a relationship is the driving
  table and the other tables a cross-table rule's join reads. Two rules over the same
  tables are one relationship. When a register exists this is the function to replace.
* **The kind is read off the rule's shape**, the way `onboarding/consistency.py`
  renders it: a `referential` rule is an orphan check, a join of two aggregates
  (`__present`) is a totals reconciliation, any other is an agreement. A rule written
  by hand gets the same reading.
* **`consistency_spec` is a byte-for-byte copy of `onboarding/consistency.py`**,
  because only `dq-app/` ships: the renderer, the lint and the job's refusal rules. A
  test compares the two files. Everything below that is the app's own: the proposal
  fold (twin of v_consistency_proposal_current), the checks a proposal must pass before
  it is written, and the read-only SQL its test runs.
"""

from __future__ import annotations

import json
import re
import uuid

import pandas as pd

from dq_app.domain import consistency_spec as spec_mod
from dq_app.domain.consistency_spec import unsafe_comparisons  # noqa: F401 -- re-exported

# The three kinds, in the reader's words. The spec and the job say orphan / agreement /
# totals; nothing a reader sees does.
KIND_LABEL = {"orphan": "Missing record", "agreement": "Same value", "totals": "Same total"}
KINDS = tuple(KIND_LABEL.values())
KIND_MEANING = {
    "Missing record": "A row points to a record that isn’t there",
    "Same value": "A value differs between the two tables",
    "Same total": "A count or sum differs between the two tables",
}

# A table named in a join: catalog.schema.table, not alias.column.
_TABLE = re.compile(r"(?<![\w.`])([A-Za-z_]\w*\.[A-Za-z_]\w*\.[A-Za-z_]\w*)(?![\w.])")
_LITERAL = re.compile(r"'(?:\\.|[^'\\])*'")


def _blank(v) -> bool:
    return v is None or v != v or not str(v).strip()


def tables_of(join_sql: str) -> list[str]:
    """Every table a join reads, in the order it names them, once each."""
    seen: list[str] = []
    for t in _TABLE.findall(_LITERAL.sub("''", str(join_sql))):
        if t not in seen:
            seen.append(t)
    return seen


def kind_of(rule) -> str:
    if rule["rule_type"] == "referential":
        return "Missing record"
    if "__present" in str(rule["join_sql"]):
        return "Same total"
    return "Same value"


def short(table: str) -> str:
    return str(table).split(".")[-1]


def checks(current: pd.DataFrame, latest: pd.DataFrame) -> list[dict]:
    """One dict per current cross-table rule, with its own latest measurement.

    `current` is the register's current versions; `latest` is indexed by rule_id and
    holds each rule's latest measured run (what the Rules page reads)."""
    rows = []
    live = current[current["status"].isin(["active", "shadow"])]
    for _, r in live.iterrows():
        if _blank(r.get("join_sql")):
            continue
        tables = tables_of(r["join_sql"])
        driving = r["target_table"]
        others = [t for t in tables if t != driving]
        run = latest.loc[r["rule_id"]] if r["rule_id"] in latest.index else None
        ran = run is not None
        limit = float(r["fail_threshold_pct"]) if pd.notna(r["fail_threshold_pct"]) else 0.0
        shadow = r["status"] == "shadow"
        over = ran and float(run["violation_pct"]) > limit
        state = ("Shadow" if shadow else "Not run" if not ran
                 else "Failing" if over else "Passing")
        rows.append({
            "key": r["rule_id"], "Name": r["rule_name"], "Kind": kind_of(r),
            "Driving": driving, "Others": others,
            "Relationship": " → ".join([short(driving)] + [short(t) for t in others]),
            "rel_key": "|".join([driving] + sorted(others)),
            "Severity": r["severity"], "Status": r["status"], "State": state,
            "cde_id": r["cde_id"],
            "Checked": int(run["rows_scanned"]) if ran else None,
            "Failing rows": int(run["violation_count"]) if ran else None,
            "Rate": 100.0 - float(run["violation_pct"]) if ran else None,
            "Run ts": run["run_ts"] if ran else None,
            "Run id": run["run_id"] if ran else None,
            "Unsafe": unsafe_comparisons(r["rule_expr"], r["join_sql"]),
            "rule_expr": r["rule_expr"], "join_sql": r["join_sql"],
            "scope_filter": None if _blank(r.get("scope_filter")) else r["scope_filter"],
        })
    order = {"Failing": 0, "Not run": 1, "Shadow": 2, "Passing": 3}
    sev = {"P1_block": 0, "P2_alert": 1, "P3_monitor": 2}
    return sorted(rows, key=lambda c: (order[c["State"]], sev.get(c["Severity"], 9),
                                       c["Relationship"], c["key"]))


def relationships(rows: list[dict]) -> list[dict]:
    """The relationships the checks read, each with its checks' states counted."""
    out: dict[str, dict] = {}
    for c in rows:
        rel = out.setdefault(c["rel_key"], {
            "key": c["rel_key"], "Driving": c["Driving"], "Others": c["Others"],
            "Label": c["Relationship"], "Checks": [], "Failing": 0, "Passing": 0,
            "Shadow": 0, "Not run": 0, "Kinds": [], "On": []})
        rel["Checks"].append(c["key"])
        rel[c["State"]] += 1
        if c["Kind"] not in rel["Kinds"]:
            rel["Kinds"].append(c["Kind"])
        on = link_keys(c["join_sql"])
        if on and on not in rel["On"]:
            rel["On"].append(on)
    return sorted(out.values(), key=lambda r: (-r["Failing"], r["Label"]))


def summary(rows: list[dict]) -> dict:
    """The page's four figures. Disagreeing rows are a floor: one row can fail two
    checks, and a totals check counts groups, not rows, so it adds nothing here."""
    failing = [c for c in rows if c["State"] == "Failing"]
    return {
        "relationships": len({c["rel_key"] for c in rows}),
        "checks": len(rows),
        "active": sum(c["Status"] == "active" for c in rows),
        "shadow": sum(c["Status"] == "shadow" for c in rows),
        "failing": len(failing),
        "failing_p1": sum(c["Severity"] == "P1_block" for c in failing),
        "rows_floor": max([c["Failing rows"] or 0 for c in failing
                           if c["Kind"] != "Same total"], default=0),
        "unsafe": sum(bool(c["Unsafe"]) for c in rows),
    }


# --- Reading a join for people (2026-10-13, the page redraw) ------------------------------

_ALIASED = re.compile(r"(?<![\w.`])([A-Za-z_]\w*\.[A-Za-z_]\w*\.[A-Za-z_]\w*)\s+"
                      r"(?:AS\s+)?([A-Za-z_]\w*)\b", re.IGNORECASE)
_KEYWORDS = {"on", "join", "left", "right", "full", "inner", "outer", "cross", "where"}
_PAIR = re.compile(r"\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)\s*=\s*([A-Za-z_]\w*)\.([A-Za-z_]\w*)")
_REF = re.compile(r"\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)\b")


def aliases(join_sql) -> dict[str, str]:
    """alias -> short table name, for every table a join names with an alias."""
    out = {}
    for t, a in _ALIASED.findall(_LITERAL.sub("''", str(join_sql or ""))):
        if a.lower() not in _KEYWORDS:
            out[a] = short(t)
    return out


def resolve(text: str, join_sql) -> str:
    """`s.CTCT_KEY = c.CTCT_KEY` -> `subs_c.CTCT_KEY = ctct_c.CTCT_KEY`: a reader knows
    the tables, not the aliases the SQL gave them."""
    names = aliases(join_sql)
    return _REF.sub(lambda m: f"{names.get(m.group(1), m.group(1))}.{m.group(2)}", str(text))


def link_pairs(join_sql) -> list[tuple[str, str]]:
    """Every `a.X = b.Y` the join matches on, as (`table.X`, `table.Y`) in join order."""
    names = aliases(join_sql)
    out = []
    for a, x, b, y in _PAIR.findall(_LITERAL.sub("''", str(join_sql or ""))):
        if a in names and b in names:
            out.append((f"{names[a]}.{x}", f"{names[b]}.{y}"))
    return out


def link_keys(join_sql) -> str | None:
    """The key column(s) a link matches on, said once: `CTCT_KEY`, or `ORG_ID → CONTACT_ID`
    when a join runs through a third table. None for a join of two totals."""
    cols = []
    for a, b in link_pairs(join_sql):
        x, y = a.split(".", 1)[1], b.split(".", 1)[1]
        cols.append(x if x == y else f"{x} = {y}")
    return " → ".join(dict.fromkeys(cols)) or None


def rate_label(c: dict) -> str:
    """The one figure a check row carries under its failed count."""
    if c["Checked"] is None:
        return "not measured"
    if c["Kind"] == "Same total":
        return "match" if not c["Failing rows"] else f"{c['Failing rows']} off"
    word = "found" if c["Kind"] == "Missing record" else "match"
    return f"{c['Rate']:.1f}% {word}".replace(".0% ", "% ")


def compared_columns(c: dict) -> list[str]:
    """The columns a Same value check compares, as they appear in its sample rows (the
    runner keeps plain column names). Two names when the sides differ; one when both
    tables call it the same, because a sample then keeps one value of the two."""
    if c["Kind"] != "Same value":
        return []
    names = aliases(c["join_sql"])
    cols = [col for a, col in _REF.findall(_LITERAL.sub("''", str(c["rule_expr"])))
            if a in names]
    return list(dict.fromkeys(cols))


def _empty(v) -> bool:
    return v is None or (isinstance(v, float) and v != v) or not str(v).strip()


def split_diff(left, right) -> tuple[str, str]:
    """(the part of `right` it shares with `left`, the part that differs). A shared start
    shorter than three characters is no shared start: the whole value differs."""
    a, b = str(left), str(right)
    n = 0
    while n < min(len(a), len(b)) and a[n] == b[n]:
        n += 1
    return (b[:n], b[n:]) if n >= 3 else ("", b)


def sample_view(rows: list[dict], c: dict) -> dict:
    """A check's sample rows for the side-by-side table: {'keys', 'left', 'right', 'rows',
    'counts'}. Each row carries its key values, both compared values (None = empty), the
    differing part of the right value, and why it failed. `left`/`right` are None when
    the check has no two distinct compared columns -- the page then shows the rows as
    stored."""
    cols = compared_columns(c)
    if len(cols) != 2:
        return {"keys": [], "left": None, "right": None, "rows": [], "counts": {}}
    left, right = cols
    # The driving table's key: the first column the runner kept that is not compared.
    keys = [k for k in (rows[0].keys() if rows else []) if k not in cols][:1]
    out, counts = [], {}
    for r in rows:
        lv, rv = r.get(left), r.get(right)
        if _empty(lv) or _empty(rv):
            why, same, diff = "One side empty", "" if _empty(rv) else str(rv), ""
        else:
            why = "Different"
            same, diff = split_diff(lv, rv)
        counts[why] = counts.get(why, 0) + 1
        out.append({"key": [r.get(k) for k in keys], "left": None if _empty(lv) else str(lv),
                    "right": None if _empty(rv) else str(rv), "same": same, "diff": diff,
                    "why": why})
    return {"keys": keys, "left": left, "right": right, "rows": out, "counts": counts}


def history(runs: pd.DataFrame, rule_id: str, n: int = 5) -> list[tuple[pd.Timestamp, int]]:
    """A check's failed count on its last `n` measured days, oldest first."""
    if runs.empty:
        return []
    mine = runs[(runs["rule_id"] == rule_id) & runs["violation_count"].notna()]
    if mine.empty:
        return []
    mine = mine.sort_values("run_ts").assign(_d=lambda d: pd.to_datetime(d["run_ts"]).dt.date)
    last = mine.drop_duplicates("_d", keep="last").tail(n)
    return [(pd.Timestamp(r["run_ts"]), int(r["violation_count"])) for _, r in last.iterrows()]


def plain_words(c: dict) -> list[str]:
    """How the two sides are matched and what fails, said without SQL. Read off the
    expression's shape; a hand-written rule gets the generic sentence."""
    other = ", ".join(short(t) for t in c["Others"]) or "the other table"
    me = short(c["Driving"])
    on = re.search(r"\bON\s+(.+?)(?:\s+(?:LEFT\s+|FULL\s+OUTER\s+|CROSS\s+)?JOIN\b|$)",
                   str(c["join_sql"]), re.IGNORECASE)
    match = resolve(on.group(1).strip(), c["join_sql"]) if on else None
    lines = []
    if c["Kind"] == "Missing record":
        lines.append(f"Each row of {me} is looked up on {other}"
                     + (f" by {match}." if match else "."))
        lines.append("It fails when no record is found.")
        lines.append("A row with no key is out of scope." if c["scope_filter"]
                     else "A row with no key fails too: it cannot find a record.")
    elif c["Kind"] == "Same total":
        lines.append(f"An aggregate over {me} is compared with one over {other}"
                     + (", group by group." if "GROUP BY" in str(c["join_sql"]) else "."))
        lines.append("It fails for a total outside its tolerance, or a group found on "
                     "one side only.")
    else:
        lines.append(f"Each row of {me} is paired with its record on {other}"
                     + (f" by {match}." if match else "."))
        lines.append("It fails when the two values differ.")
        if "<=>" in str(c["rule_expr"]):
            lines.append("A value on one side and none on the other counts as different.")
    if c["Unsafe"]:
        lines.append("This comparison is not null-safe: a pair with a value missing on "
                     "one side is never counted, so the real figure can be higher.")
    return lines


# --- Proposals (2026-10-13) --------------------------------------------------------------
# The builder writes a check as a spec to config.consistency_proposal; a second person
# decides it in config.consistency_review; the onboarding job writes the rule in shadow.
# Column lists are diffed against sql/ddl/22 by fixtures/verify.py check 6.

PROPOSAL_COLUMNS = [
    "proposal_id", "proposed_at", "rule_id", "rule_name", "kind", "spec", "target_table",
    "other_tables", "cde_id", "severity", "rule_type", "target_column", "join_sql",
    "rule_expr", "scope_filter", "fingerprint", "test_compared", "test_failing",
    "test_match_pct", "test_fanout", "proposed_by", "reason"]
REVIEW_COLUMNS = ["proposal_id", "decision", "reviewed_by", "reviewed_at", "reason",
                  "test_compared", "test_failing"]
SEVERITIES = ("P1_block", "P2_alert", "P3_monitor")
# Below this share of rows finding a match, the key is almost certainly wrong (or the
# same value is stored in two formats), and a proposal is refused.
MIN_MATCH_PCT = 50.0
SAMPLE_LIMIT = 10
WAIVER_MARK = spec_mod.WAIVER_MARK


def new_rule_id() -> str:
    return "CS_" + uuid.uuid4().hex[:8].upper()


def proposal_state(proposals: pd.DataFrame, reviews: pd.DataFrame,
                   registry: pd.DataFrame) -> pd.DataFrame:
    """Every proposal with its decision and state: open / approved / applied / rejected.
    The labelled twin of v_consistency_proposal_current (sql/ddl/22)."""
    if proposals is None or proposals.empty:
        return pd.DataFrame(columns=PROPOSAL_COLUMNS + [
            "decision", "reviewed_by", "reviewed_at", "review_reason",
            "review_test_compared", "review_test_failing", "state"])
    rev = (reviews if reviews is not None and len(reviews) else
           pd.DataFrame(columns=REVIEW_COLUMNS))
    rev = rev.sort_values("reviewed_at").drop_duplicates("proposal_id", keep="first")
    rev = rev.rename(columns={"reason": "review_reason", "test_compared": "review_test_compared",
                              "test_failing": "review_test_failing"})
    out = proposals.merge(rev, on="proposal_id", how="left")
    notes = registry[["rule_id", "note"]].dropna() if len(registry) else \
        pd.DataFrame(columns=["rule_id", "note"])

    def _state(r) -> str:
        if r.get("decision") == "rejected":
            return "rejected"
        if r.get("decision") == "approved":
            mark = spec_mod.marker(r["proposal_id"])
            mine = notes[notes["rule_id"] == r["rule_id"]]
            return "applied" if any(str(n).startswith(mark) for n in mine["note"]) \
                else "approved"
        return "open"

    out["state"] = [_state(r) for r in out.to_dict("records")]
    return out


# --- Current records, as the runner reads them ---------------------------------------------

_COL = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,254}$")


def _col(name: str) -> str:
    if not _COL.match(str(name)):
        raise ValueError(f"population column {name!r} is not a plain identifier")
    return f"`{name}`"


def _lit(v) -> str:
    return "'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'"


def _seq(v) -> list:
    if v is None or (isinstance(v, float) and v != v):
        return []
    return list(v)


def current(table: str, pop: dict | None) -> str:
    """A table's current records under its config.table_population row. Copy of
    jobs/run_checks.current, pinned to it by a test: the test a proposer runs must count
    what the runner will."""
    if not pop:
        return table
    keys, order = _seq(pop.get("record_key")), _seq(pop.get("version_by"))
    dcol = pop.get("deleted_column")
    dcol = None if _blank(dcol) else dcol
    if not order and dcol is None:
        return table
    src = table
    if order:
        k = ", ".join(_col(x) for x in keys)
        keyless = " OR ".join(f"{_col(x)} IS NULL" for x in keys)
        o = ", ".join(f"{_col(c)} DESC NULLS LAST" for c in order)
        src = (f"(SELECT * FROM {table} QUALIFY row_number() OVER "
               f"(PARTITION BY {k} ORDER BY {o}) = 1 OR {keyless})")
    if dcol is not None:
        src = f"(SELECT * FROM {src} WHERE NOT ({_col(dcol)} <=> {_lit(pop.get('deleted_value'))}))"
    return src


def populations_by_table(pops: pd.DataFrame) -> dict[str, dict]:
    """The declaration in force per table: the latest population_version."""
    if pops is None or pops.empty:
        return {}
    latest = pops.sort_values("population_version").drop_duplicates("target_table", keep="last")
    return {r["target_table"]: r for r in latest.to_dict("records")}


# --- What a test runs: read-only SELECTs, built from the spec ---------------------------------

def test_queries(spec: dict, pops: dict[str, dict]) -> dict:
    """{'count': SQL, 'sample': SQL, 'hops': [{'match': SQL, 'fanout': SQL}]} for a spec,
    every table read on its current records. Built from the spec, so a proposer runs no
    SQL they typed."""
    rel = lambda t: current(t, pops.get(t))  # noqa: E731
    r = spec_mod.render_spec(spec, rel=rel)
    scope = "TRUE" if _blank(r["scope_filter"]) else f"({r['scope_filter']})"
    count = (f"SELECT count_if({scope}) AS compared, "
             f"count_if({scope} AND ({r['rule_expr']})) AS failing\nFROM {r['join_sql']}")
    kind = spec["kind"]
    if kind == "orphan":
        cols = ", ".join(f"ch.{a} AS `{a}`" for a, _ in spec["hops"][0]["keys"])
    elif kind == "agreement":
        n = len(spec["hops"])
        keys = ", ".join(f"t0.{a} AS `{a}`" for a, _ in spec["hops"][0]["keys"])
        cols = f"{keys}, t0.{spec['left']} AS left_value, t{n}.{spec['right']} AS right_value"
    else:
        g = "l.__g0 AS left_group, r.__g0 AS right_group, " if spec["left"].get("group_by") else ""
        cols = f"{g}l.__v AS left_total, r.__v AS right_total"
    sample = (f"SELECT {cols}\nFROM {r['join_sql']}\nWHERE {scope} AND ({r['rule_expr']})\n"
              f"LIMIT {SAMPLE_LIMIT}")
    hops = []
    for h in spec.get("hops") or []:
        on = " AND ".join(f"f.{a} = m.k{i}" for i, (a, _) in enumerate(h["keys"]))
        to_keys = ", ".join(f"{b} AS k{i}" for i, (_, b) in enumerate(h["keys"]))
        grp = ", ".join(b for _, b in h["keys"])
        not_null = " AND ".join(f"{b} IS NOT NULL" for _, b in h["keys"])
        hops.append({
            "from": h["from"], "to": h["to"],
            "match": (f"SELECT count(*) AS total, count_if(m.__hit IS NOT NULL) AS matched\n"
                      f"FROM {rel(h['from'])} f\nLEFT JOIN (SELECT DISTINCT {to_keys}, "
                      f"1 AS __hit FROM {rel(h['to'])}) m ON {on}"),
            "fanout": (f"SELECT count(*) AS keys FROM (SELECT {grp} FROM {rel(h['to'])} "
                       f"WHERE {not_null} GROUP BY {grp} HAVING count(*) > 1)"),
        })
    return {"count": count, "sample": sample, "hops": hops}


def summarise(results: dict) -> dict:
    """The test's figures from what `test_queries` returned when run."""
    hops = results.get("hops") or []
    pcts = [100.0 * h["matched"] / h["total"] for h in hops if h.get("total")]
    return {"compared": int(results["compared"]), "failing": int(results["failing"]),
            "match_pct": round(min(pcts), 1) if pcts else None,
            "fanout": sum(int(h.get("fanout") or 0) for h in hops),
            "hops": hops, "sample": results.get("sample")}


def type_checks(spec: dict, columns: dict[str, dict[str, str]]) -> list[dict]:
    """One line per key pair: do the two columns' types match? `columns` maps a table to
    {column: type} from the catalog; a table with none (the local fixture) reads
    unknown."""
    out = []
    for h in spec.get("hops") or []:
        for a, b in h["keys"]:
            ta, tb = _type_of(columns.get(h["from"]), a), _type_of(columns.get(h["to"]), b)
            ok = None if ta is None or tb is None else ta == tb
            out.append({"from": f"{short(h['from'])}.{a}", "to": f"{short(h['to'])}.{b}",
                        "from_type": ta, "to_type": tb, "ok": ok})
    return out


def _type_of(cols: dict[str, str] | None, name: str) -> str | None:
    for c, t in (cols or {}).items():
        if c.lower() == str(name).lower():
            return str(t).upper()
    return None


# --- What a proposal must pass before it is written -------------------------------------------

def validate_proposal(spec: dict, name: str, cde_id: str, severity: str, reason: str, *,
                      test: dict | None, fanout_ack: bool, registry: pd.DataFrame,
                      state: pd.DataFrame, registered: set[str]) -> dict:
    """The rendered rule, or ValueError saying what to fix. `registry` is every rule
    version; `state` is proposal_state."""
    if not (name or "").strip():
        raise ValueError("Give the check a name.")
    if not (reason or "").strip():
        raise ValueError("Say why this check is needed.")
    if severity not in SEVERITIES:
        raise ValueError("Pick a severity.")
    if cde_id not in registered:
        raise ValueError("Pick the key attribute the check reports on.")
    try:
        rendered = spec_mod.render_spec(spec)
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"The check is not complete: {exc}") from exc
    fp = spec_mod.fingerprint(rendered)
    if len(registry):
        latest = registry.sort_values("rule_version").drop_duplicates("rule_id", keep="last")
        for r in latest[latest["status"] != "retired"].to_dict("records"):
            if spec_mod.fingerprint(r) == fp:
                raise ValueError(f"{r['rule_id']} already does the same check.")
    if len(state):
        live = state[state["state"].isin(["open", "approved"])]
        if (live["fingerprint"] == fp).any():
            raise ValueError("The same check is already proposed and waiting.")
    if test is not None:
        if test.get("match_pct") is not None and test["match_pct"] < MIN_MATCH_PCT:
            raise ValueError(f"Only {test['match_pct']:.0f}% of rows found a match. That "
                             "usually means the wrong key column.")
        if test.get("fanout") and not fanout_ack:
            raise ValueError("Some keys match more than one record. Confirm that each "
                             "pair should be compared, or pick a different key.")
    return {**rendered, "fingerprint": fp}


def validate_review(proposal: dict, who: str, decision: str, reason: str | None, *,
                    allow_self: bool) -> None:
    if decision not in ("approved", "rejected"):
        raise ValueError("Pick approve or reject.")
    if decision == "rejected" and not (reason or "").strip():
        raise ValueError("Say why you are rejecting it.")
    if (str(proposal.get("proposed_by") or "").lower() == str(who or "").lower()
            and not allow_self):
        raise ValueError("You can’t review your own proposal.")


def spec_of(p: dict) -> dict:
    return json.loads(p["spec"]) if isinstance(p.get("spec"), str) else p["spec"]


def proposal_words(p: dict) -> list[str]:
    """What a proposal checks, in a sentence or two, read off its spec."""
    s = spec_of(p)
    k = s["kind"]
    if k == "orphan":
        h = s["hops"][0]
        keys = ", ".join(f"{a} → {b}" for a, b in h["keys"])
        return [f"Each {short(h['from'])} row is looked up on {short(h['to'])} by {keys}.",
                "A row with no key fails too." if s["null_key"] == "fail"
                else "A row with no key is skipped."]
    if k == "agreement":
        first, last = s["hops"][0]["from"], s["hops"][-1]["to"]
        via = f" via {short(s['hops'][0]['to'])}" if len(s["hops"]) > 1 else ""
        how = {"phone_au": "as phone digits", "text": "ignoring spaces and case",
               "day": "as dates", "number": "as numbers", "exact": "exactly"}[s["compare"]]
        return [f"{short(first)}.{s['left']} against {short(last)}.{s['right']}{via}, "
                f"compared {how}.",
                "If one side is empty, it counts as different."
                if s["empty_one_side"] == "differs" else "If one side is empty, it is skipped."]
    left, right = s["left"], s["right"]

    def _m(x):
        return {"count": "rows", "count_distinct": f"distinct {x.get('column')}",
                "sum": f"sum of {x.get('column')}"}[x["agg"]]
    by = f", per {left['group_by']}" if left.get("group_by") else ""
    tol = []
    if float(s.get("abs_tolerance") or 0):
        tol.append(f"±{s['abs_tolerance']:g}")
    if float(s.get("rel_tolerance") or 0):
        tol.append(f"±{100 * float(s['rel_tolerance']):g}%")
    return [f"{_m(left)} on {short(left['table'])} against {_m(right)} on "
            f"{short(right['table'])}{by}.",
            f"Allowed difference: {' or '.join(tol)}." if tol else "They must match exactly."]


def test_error_words(err: str, tables: list[str]) -> str:
    """A failed test, said in words. The common case on the warehouse is the app's
    principal having no read access to a source table -- the raw message names a
    privilege and a securable, which is not what a steward can act on."""
    e = str(err or "")
    if any(k in e for k in ("PERMISSION_DENIED", "INSUFFICIENT_PERMISSIONS",
                            "does not have USE SCHEMA", "does not have SELECT")):
        return ("The app can’t read " + ", ".join(short(t) for t in tables) + ". Grant "
                "its service principal USE SCHEMA and SELECT on the source schema, then "
                "run the test again.")
    if "TABLE_OR_VIEW_NOT_FOUND" in e:
        return "A table this check reads no longer exists, or the app cannot see it."
    return f"The test could not run: {e}"

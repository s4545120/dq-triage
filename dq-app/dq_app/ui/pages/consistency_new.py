"""New check — propose a consistency check between two tables.

Built 2026-10-13 from the mockup ("Consistency checks mockup", screen 3). A drill-down
of the Consistency page. The builder produces a SPEC -- kind, tables, key columns,
compared columns, policies -- never SQL. The rule is rendered from it
(`domain/consistency_spec.render_spec`, a byte copy of onboarding/consistency.py) and
shown read-only.

**What is written, and when.** Nothing until "Propose…" is confirmed. Then one row in
config.consistency_proposal, signed with the platform identity. A second person decides
it on the review page, and the onboarding job writes the rule in shadow. The app never
writes the rule register for a consistency check.

**The test is read-only and runs on current records**, every table read the way the
runner will read it (`domain/consistency.test_queries`). On the warehouse a proposal
needs a test of exactly what is proposed: change a field and the test must be run
again. Below `MIN_MATCH_PCT` of rows finding a match it is refused. On the local fixture
there are no source rows, so nothing is tested and the page says so.

**Tables are the onboarded ones**; on the fixture, where none is selected, the tables
the register's rules check. Columns come from Unity Catalog, or on the fixture from the
register's bindings, without types.
"""

from __future__ import annotations

import html
import json
import re

import pandas as pd
import streamlit as st

from dq_app.data import adapter, identity
from dq_app.data.adapter import OnboardingRejected
from dq_app.domain import consistency as cs
from dq_app.domain import consistency_spec as spec_mod
from dq_app.domain import metrics
from dq_app.ui import components, theme
from dq_app.ui import onboarding_style as ui

HOME = "dq_app/ui/pages/consistency.py"
REVIEW = "dq_app/ui/pages/consistency_review.py"
TEST = "_csn_test"
DIRECT = "(direct)"
NONE = "(none)"
COMPARE_LABEL = {"phone_au": "Phone digits", "text": "Text, ignoring spaces and case",
                 "day": "Date", "number": "Number", "exact": "Exactly as stored"}
SUGGEST = {"phone_number": "phone_au", "msisdn": "phone_au", "person_name": "text",
           "email_address": "text", "date_of_birth": "day"}
AGG_LABEL = {"count": "Rows", "count_distinct": "Distinct values", "sum": "Sum"}
SEV_LABEL = {"P3_monitor": "P3 · Monitor", "P2_alert": "P2 · Alert", "P1_block": "P1 · Block"}

components.page_chrome()

me = identity.current().email
registry = adapter.get_rule_registry_current()
elements = adapter.get_cde_registry_current()
elements = elements[elements["status"] != "retired"]
retired = metrics.retired_rule_ids(adapter.get_rule_registry())


# --- Tables and columns -----------------------------------------------------------------

def _tables() -> tuple[list[str], bool]:
    """(tables, from_catalog). Onboarded tables; on the fixture, the register's."""
    mon = adapter.get_monitored_tables()
    if len(mon):
        cur = mon.sort_values("table_version").drop_duplicates("target_table", keep="last")
        sel = sorted(cur.loc[cur["status"] == "selected", "target_table"])
        if sel:
            return sel, True
    live = registry[~registry["rule_id"].isin(retired) & (registry["status"] != "retired")]
    return sorted(live["target_table"].dropna().unique()), False


def _bound(table: str) -> dict[str, str]:
    """column -> the key attribute bound to it on `table`."""
    out = {}
    for e in elements.to_dict("records"):
        for b in components.as_list(e["bindings"]):
            if b.get("target_table") == table and b.get("binding_status", "bound") == "bound":
                out[b["target_column"]] = e["cde_id"]
    return out


def _catalog(table: str) -> pd.DataFrame:
    """The table's columns from Unity Catalog; empty when the app cannot see it (the
    adapter does not keep an empty listing, so a grant shows on the next load)."""
    try:
        return adapter.get_catalog_columns(table)
    except Exception:  # noqa: BLE001 -- a table we cannot list falls back to the register
        return pd.DataFrame()


@st.cache_data(ttl=600, show_spinner=False)
def _known_columns(table: str) -> list[str]:
    """Off the catalog (the local fixture): every column the register shows this table
    has -- bound columns, rule target columns, the columns stored in its single-table
    rules' samples, and the columns its existing joins match on."""
    cols = set(_bound(table))
    mon = adapter.get_monitored_tables()
    if len(mon):
        cur = mon[mon["target_table"] == table].sort_values("table_version")
        if len(cur):
            cols |= set(components.as_list(cur.iloc[-1]["row_key"]))
    mine = registry[registry["target_table"] == table]
    cols |= set(mine["target_column"].dropna())
    single = set(mine.loc[mine["join_sql"].isna(), "rule_id"])
    samples = adapter.get_violation_samples()
    for raw in samples.loc[samples["rule_id"].isin(single), "sample_row"].head(400):
        try:
            cols |= set(json.loads(raw))
        except (TypeError, ValueError):
            pass
    for r in registry.dropna(subset=["join_sql"]).to_dict("records"):
        text = f"{r['join_sql']} {r['rule_expr']}"
        for alias in re.findall(rf"{re.escape(table)}\s+(\w+)", r["join_sql"]):
            cols |= set(re.findall(rf"\b{alias}\.([A-Za-z_]\w*)", text))
    return sorted(c for c in cols if isinstance(c, str))


# Tables whose columns the catalog would not list this run. On the warehouse that means
# the app's principal has no access to the table; the page says so rather than offer a
# short list as if it were the table.
UNLISTED: list[str] = []


def _columns(table: str) -> tuple[list[str], dict[str, str]]:
    """(column names, {column: type}). Types are empty off the catalog."""
    cat = _catalog(table)
    if len(cat) and "column_name" in cat:
        return list(cat["column_name"]), dict(zip(cat["column_name"], cat["data_type"]))
    if table not in UNLISTED:
        UNLISTED.append(table)
    return _known_columns(table), {}


tables, from_catalog = _tables()

# --- Header -----------------------------------------------------------------------------

st.markdown(
    '<div class="dq-page-hd"><div class="t">New check</div>'
    '<div class="s">Compare two tables. Someone else approves it before it runs.</div>'
    "</div>",
    unsafe_allow_html=True,
)
if st.button("Back to Consistency", icon=":material/arrow_back:", type="tertiary",
             key="_csn_back"):
    st.switch_page(HOME)

# Filled once the spec is known (below): the message stays while the form still holds
# what was proposed, so its button is still there on the run its click causes.
flash_slot = st.container()

if len(tables) < 1:
    st.info("No tables are onboarded yet. Onboard two tables first.")
    st.stop()
if not from_catalog:
    st.caption("No tables are onboarded here, so the tables the register’s rules check "
               "are offered instead, with their bound columns and no types.")


def _step(n: int, title: str) -> None:
    st.markdown(f'<div class="dq-csn-step"><span class="n">{n}</span>{title}</div>',
                unsafe_allow_html=True)


form, side = st.columns([1.7, 1], gap="large")

with form, st.container(key="dq_csn_form"):
    # 1. Type
    _step(1, "Type")
    kind = st.segmented_control(
        "Type", list(cs.KIND_LABEL), key="_csn_kind", default="agreement",
        format_func=cs.KIND_LABEL.get, label_visibility="collapsed") or "agreement"
    st.caption(cs.KIND_MEANING[cs.KIND_LABEL[kind]])

    # 2. Tables
    _step(2, "Tables")
    a, b = st.columns(2)
    left_t = a.selectbox("Check", tables, key="_csn_left", format_func=cs.short)
    right_opts = [t for t in tables if t != left_t] or tables
    right_t = b.selectbox("Against", right_opts, key="_csn_right", format_func=cs.short)
    via_t = None
    if kind == "agreement":
        via = st.selectbox("Link", [DIRECT] + [t for t in tables if t not in (left_t, right_t)],
                           key="_csn_via", format_func=lambda t: t if t == DIRECT else
                           f"via {cs.short(t)}")
        via_t = None if via == DIRECT else via

    spec: dict = {"kind": kind}
    lcols, ltypes = _columns(left_t)
    rcols, rtypes = _columns(right_t)
    types = {left_t: ltypes, right_t: rtypes}

    def _pick(label: str, table: str, cols: list[str], key: str, prefer=None,
              blank: bool = False):
        """A column picker. `blank`: start empty rather than on the first column, for a
        choice with no sensible default."""
        if not cols:
            st.caption(f"No columns known for {cs.short(table)}.")
            return None
        idx = cols.index(prefer) if prefer in cols else (None if blank else 0)
        t = types.get(table, {})
        return st.selectbox(label, cols, index=idx, key=key, placeholder="Pick a column",
                            format_func=lambda c: f"{c} · {t[c]}" if c in t else c)

    def _common_key(a: list[str], b: list[str]) -> str | None:
        """A key-shaped column both tables have, the likeliest join."""
        common = [c for c in a if c in set(b) and c.upper().endswith(("_ID", "_KEY"))]
        return common[0] if common else None

    # 3. Match rows on
    if kind in ("orphan", "agreement"):
        _step(3, "Match rows on")
        hops = []
        if via_t:
            vcols, vtypes = _columns(via_t)
            types[via_t] = vtypes
            c1, c2 = st.columns(2)
            with c1:
                k1 = _pick(cs.short(left_t), left_t, lcols, f"_csn_k1_{left_t}_{via_t or right_t}",
                           prefer=_common_key(lcols, vcols))
            with c2:
                k2 = _pick(cs.short(via_t), via_t, vcols, f"_csn_k2_{left_t}_{via_t or right_t}", prefer=k1)
            c3, c4 = st.columns(2)
            with c3:
                k3 = _pick(cs.short(via_t), via_t, vcols, f"_csn_k3_{via_t}_{right_t}",
                           prefer=_common_key(vcols, rcols))
            with c4:
                k4 = _pick(cs.short(right_t), right_t, rcols, f"_csn_k4_{via_t}_{right_t}", prefer=k3)
            if all((k1, k2, k3, k4)):
                hops = [{"from": left_t, "to": via_t, "keys": [[k1, k2]]},
                        {"from": via_t, "to": right_t, "keys": [[k3, k4]]}]
        else:
            c1, c2 = st.columns(2)
            guess = _common_key(lcols, rcols)
            with c1:
                k1 = _pick(cs.short(left_t), left_t, lcols, f"_csn_k1_{left_t}_{via_t or right_t}", prefer=guess)
            with c2:
                k2 = _pick(cs.short(right_t), right_t, rcols, f"_csn_k2_{left_t}_{via_t or right_t}", prefer=k1)
            if k1 and k2:
                hops = [{"from": left_t, "to": right_t, "keys": [[k1, k2]]}]
        spec["hops"] = hops

    # 4. Compare
    if kind == "orphan":
        _step(4, "If the key is empty")
        null_key = st.radio("If the key is empty", ["fail", "ignore"], index=None,
                            key="_csn_nullkey", horizontal=True,
                            format_func={"fail": "Counts as missing",
                                         "ignore": "Skip the row"}.get,
                            label_visibility="collapsed")
        spec["null_key"] = null_key
    elif kind == "agreement":
        _step(4, "Compare")
        c1, c2 = st.columns(2)
        with c1:
            lc = _pick(cs.short(left_t), left_t, lcols, f"_csn_lc_{left_t}", blank=True)
        with c2:
            rc_ = _pick(cs.short(right_t), right_t, rcols, f"_csn_rc_{right_t}", prefer=lc, blank=True)
        # Whichever compared column is bound says what kind of value this is.
        bound = _bound(left_t).get(lc) or _bound(right_t).get(rc_)
        dclass = (elements.set_index("cde_id").loc[bound, "data_class"]
                  if bound in set(elements["cde_id"]) else None)
        suggested = SUGGEST.get(dclass, "exact")
        d1, d2 = st.columns(2)
        compare = d1.selectbox(
            "Compare as", list(COMPARE_LABEL), index=list(COMPARE_LABEL).index(suggested),
            key=f"_csn_cmp_{lc}_{rc_}", format_func=lambda k: COMPARE_LABEL[k]
            + (" (suggested)" if k == suggested and dclass else ""))
        empty = d2.radio("If one side is empty", ["differs", "skip"], index=None,
                         key="_csn_empty", horizontal=True,
                         format_func={"differs": "Count as different", "skip": "Skip"}.get)
        tol = 0.0
        if compare == "number":
            tol = st.number_input("Allowed difference", min_value=0.0, value=0.0,
                                  key="_csn_tol")
        spec.update(left=lc, right=rc_, compare=compare, empty_one_side=empty, tolerance=tol)
    else:
        _step(3, "Totals")

        def _side(label: str, table: str, cols: list[str], key: str) -> dict:
            st.markdown(f"**{label}** · `{cs.short(table)}`")
            agg = st.selectbox("Measure", list(AGG_LABEL), key=f"{key}_agg",
                               format_func=AGG_LABEL.get)
            col = None
            if agg != "count":
                col = _pick("Of column", table, cols, f"{key}_col")
            grp = st.selectbox("Per", [NONE] + cols, key=f"{key}_grp")
            return {"table": table, "agg": agg, "column": col,
                    "group_by": None if grp == NONE else grp}

        c1, c2 = st.columns(2)
        with c1:
            ls = _side("Check", left_t, lcols, f"_csn_l_{left_t}")
        with c2:
            rs = _side("Against", right_t, rcols, f"_csn_r_{right_t}")
        _step(4, "Allowed difference")
        t1, t2 = st.columns(2)
        abs_t = t1.number_input("Absolute", min_value=0.0, value=0.0, key="_csn_abs")
        rel_t = t2.number_input("Percent of the Against total", min_value=0.0, value=0.0,
                                key="_csn_rel")
        spec.update(left=ls, right=rs, abs_tolerance=abs_t, rel_tolerance=rel_t / 100.0)

    if from_catalog and UNLISTED:
        st.warning(
            "The app can’t list the columns of "
            + ", ".join(f"**{cs.short(t)}**" for t in UNLISTED)
            + ": it has no access to "
            + ("that table" if len(UNLISTED) == 1 else "those tables")
            + ". Only the columns the register already knows are offered, so a key "
            "column may be missing. Grant the app’s service principal `USE SCHEMA` and "
            "`SELECT` on the schema to see them all.", icon=":material/lock:")

    # Is the spec complete enough to render?
    try:
        rendered = spec_mod.render_spec(spec)
        incomplete = None
    except (ValueError, KeyError, TypeError) as exc:
        rendered, incomplete = None, str(exc)

    key = json.dumps(spec, sort_keys=True)
    flash = st.session_state.get("_csn_flash")
    if flash and flash["spec"] == key:
        with flash_slot:
            st.success(flash["text"], icon=":material/check_circle:")
            if st.button("Open the proposal", key="_csn_open_rev",
                         icon=":material/open_in_new:"):
                st.session_state.pop("_csn_flash", None)
                st.switch_page(REVIEW)
    elif flash:
        st.session_state.pop("_csn_flash", None)

    # 5. Test
    _step(5, "Test")
    tested = st.session_state.get(TEST)
    fresh = tested is not None and tested["spec"] == key
    if incomplete:
        st.caption("Finish the steps above first.")
    elif st.button("Run test", key="_csn_run", icon=":material/play_arrow:"):
        try:
            with st.spinner("Testing on current records…"):
                res = adapter.test_consistency(spec)
            st.session_state[TEST] = {"spec": key, "result": res, "error": None}
        except Exception as exc:  # noqa: BLE001 -- said on the page, nothing written
            st.session_state[TEST] = {"spec": key, "result": None,
                                      "error": str(exc).splitlines()[0][:300]}
        tested, fresh = st.session_state[TEST], True

    test = tested["result"] if fresh else None
    if fresh and tested["error"]:
        st.error(cs.test_error_words(tested["error"], spec_mod.tables_of(spec)),
                 icon=":material/error:")
    elif fresh and test is None:
        st.caption("Nothing to test against here: the local fixture has no source rows. "
                   "On the warehouse the test runs on current records.")
    elif tested is not None and not fresh and not incomplete:
        st.caption("Something changed since the last test. Run it again.")

    if rendered and kind != "totals":
        lines = []
        for t in cs.type_checks(spec, types):
            if t["ok"] is None:
                lines.append(("·", f"{t['from']} = {t['to']}: types unknown here", "neutral"))
            elif t["ok"]:
                lines.append(("✓", f"{t['from']} = {t['to']}: both {t['from_type']}", "success"))
            else:
                lines.append(("!", f"{t['from']} is {t['from_type']}, {t['to']} is "
                                   f"{t['to_type']}", "high"))
        if test:
            for h in test["hops"]:
                pct = 100.0 * h["matched"] / h["total"] if h["total"] else 0.0
                tone = "success" if pct >= cs.MIN_MATCH_PCT else "critical"
                lines.append(("✓" if tone == "success" else "!",
                              f"{pct:.0f}% of {cs.short(h['from'])} rows found a "
                              f"{cs.short(h['to'])} record ({h['matched']:,} of {h['total']:,})",
                              tone))
                if h["fanout"]:
                    lines.append(("!", f"{h['fanout']:,} {cs.short(h['to'])} keys match more "
                                       "than one record", "high"))
        st.markdown(
            '<div class="dq-csn-checks">' + "".join(
                f'<div class="l"><span class="i" style="color:{theme.TONE[t]["fg"]};'
                f'background:{theme.TONE[t]["bg"]}">{i}</span>{html.escape(x)}</div>'
                for i, x, t in lines) + "</div>",
            unsafe_allow_html=True,
        )
    fanout_ack = False
    if test and test["fanout"]:
        fanout_ack = st.checkbox("Compare every pair anyway", key="_csn_fanack",
                                 help="Each match is compared, so one record can pass on "
                                      "one and fail on another.")
    if test:
        st.markdown(f"**{test['compared']:,}** compared · "
                    f"**{test['failing']:,}** {'failing' if kind != 'agreement' else 'different'}")
        if test["sample"] is not None and len(test["sample"]):
            st.dataframe(test["sample"], hide_index=True, width="stretch")
            st.caption(f"Up to {cs.SAMPLE_LIMIT} rows.")
    if rendered:
        with st.expander("Show SQL"):
            st.code("FROM  " + rendered["join_sql"] + "\nWHERE " + rendered["rule_expr"]
                    + ("" if not rendered["scope_filter"] else
                       "\n  AND " + rendered["scope_filter"]), language="sql", wrap_lines=True)


# --- Summary ------------------------------------------------------------------------------

def _suggested_cde(spec: dict, here: dict[str, str], there: dict[str, str]) -> str | None:
    """The key attribute a check most likely reports on: the one bound to the column it
    compares, else to its key. A totals spec's sides are dicts (table, measure, group),
    not column names -- read the column out of them, never look the dict up."""
    if spec["kind"] == "totals":
        side = spec.get("left") or {}
        return here.get(side.get("column")) or here.get(side.get("group_by"))
    if spec["kind"] == "agreement" and (spec.get("left") or spec.get("right")):
        hit = here.get(spec.get("left")) or there.get(spec.get("right"))
        if hit:
            return hit
    hops = spec.get("hops") or []
    return here.get(hops[0]["keys"][0][0]) if hops and hops[0].get("keys") else None


def _still_to_do(incomplete, name, why, kind, fresh, test, fanout_ack, *,
                 needs_test: bool) -> list[str]:
    """What stands between the form and a proposal, in the order a person fixes it.
    The same rules `consistency.validate_proposal` enforces at write time."""
    todo = []
    if incomplete:
        todo.append("Finish the steps on the left.")
    elif needs_test and not (fresh and test):
        todo.append("Run the test on what you’re proposing.")
    elif test:
        if test.get("match_pct") is not None and test["match_pct"] < cs.MIN_MATCH_PCT:
            todo.append(f"Only {test['match_pct']:.0f}% of rows found a match: check the "
                        "key columns.")
        if test.get("fanout") and not fanout_ack:
            todo.append("Tick “Compare every pair anyway”, or pick a key that matches "
                        "one record.")
    if not (name or "").strip():
        todo.append("Give it a name.")
    if not (why or "").strip():
        todo.append("Say why the check is needed.")
    return todo


def _default_name() -> str:
    if kind == "orphan" and spec.get("hops"):
        return f"Every {cs.short(left_t)} row has a {cs.short(right_t)} record"
    if kind == "agreement" and spec.get("left") and spec.get("right"):
        return f"{cs.short(left_t)} {spec['left']} = {cs.short(right_t)} {spec['right']}"
    if kind == "totals":
        return f"{cs.short(left_t)} and {cs.short(right_t)} totals match"
    return ""


with side, st.container(key="dq_csn_side"):
    st.markdown('<div class="dq-csn-sidehd">Summary</div>', unsafe_allow_html=True)
    # Keyed on the default, so changing what is compared names the check afresh rather
    # than keeping a name written for the columns picked first.
    suggested_name = _default_name()
    name = st.text_input("Name", value=suggested_name, key=f"_csn_name_{suggested_name}")
    bound_here = _bound(left_t)
    ids = list(dict.fromkeys(list(bound_here.values()) + list(elements["cde_id"])))
    names = elements.set_index("cde_id")["cde_name"].to_dict()
    pref = _suggested_cde(spec, bound_here, _bound(right_t))
    cde = st.selectbox("Key attribute", ids, key=f"_csn_cde_{pref}",
                       index=ids.index(pref) if pref in ids else 0,
                       format_func=lambda c: names.get(c, c))
    sev = st.selectbox("Severity", list(SEV_LABEL), key="_csn_sev", format_func=SEV_LABEL.get)
    why = st.text_area("Why", key="_csn_why", height=90,
                       placeholder="What goes wrong if these disagree?")
    # Everything Propose would refuse, said BEFORE the click: the button stays disabled
    # until the list is empty. Found on dq_triage, where the first proposal was refused
    # twice inside the dialog (no reason, then fan-out not acknowledged).
    todo = _still_to_do(incomplete, name, why, kind, fresh, test, fanout_ack,
                        needs_test=not adapter.is_local())
    if todo:
        st.markdown('<div class="dq-csn-todo"><b>Before you propose</b><ul>'
                    + "".join(f"<li>{html.escape(t)}</li>" for t in todo) + "</ul></div>",
                    unsafe_allow_html=True)
    if st.button("Propose…", type="primary", key="_csn_propose", width="stretch",
                 disabled=bool(todo)):
        ui.ask("cs_propose")
    st.markdown(
        '<div class="dq-csn-then"><b>Then</b><ol><li>Someone else approves it</li>'
        "<li>It runs in shadow (not counted)</li><li>It’s promoted on the Rules page</li>"
        "</ol></div>",
        unsafe_allow_html=True,
    )


def _propose():
    try:
        row = adapter.propose_consistency(spec, name, cde, sev, why, test if fresh else None,
                                          fanout_ack)
    except OnboardingRejected as exc:
        return str(exc)
    st.session_state["_cs_proposal"] = row["proposal_id"]
    st.session_state["_csn_flash"] = {
        "spec": json.dumps(spec, sort_keys=True),
        "text": f"Proposed {row['rule_name']} ({row['rule_id']}). It now waits for "
                "someone else to review it."}
    st.session_state.pop(TEST, None)
    return None


ui.confirm(
    "cs_propose", "Propose this check?",
    f'Writes one proposal to <span class="onb-mono">config.consistency_proposal</span>, '
    f'signed <b>{html.escape(me)}</b>. No rule is written until someone else approves it.'
    + (f'<br>Why: “{html.escape(why)}”' if (why or "").strip() else
       '<br><b style="color:#b91c1c">Say why first.</b>'),
    "Propose", _propose)

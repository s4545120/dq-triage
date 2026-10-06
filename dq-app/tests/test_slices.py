"""Data slices: the structured spec and its SQL, who may change one, the runner applying
it, and the Slice card on a table's onboarding page.

Page tests reuse test_onboarding's fixture copy -- `prod.sales.crm_lead` part way
through onboarding -- with the slice columns on its monitored_table row and a column
listing for the table, which is what the editor offers and `render` checks against.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

from dq_app.domain import slices

ROOT = Path(__file__).resolve().parents[2]
TYPES = {"STATUS_CD": "string", "MIG_FLAG": "int", "AMT": "decimal(10,2)",
         "IS_TEST": "boolean", "CTCT_ID": "string"}


# --- The spec, pure ----------------------------------------------------------------------

def test_the_whole_table_is_no_filter():
    assert slices.render({}, TYPES) is None
    assert slices.render({"where": [{"column": "", "op": "", "values": []}]}, TYPES) is None
    assert slices.describe({}) == "the whole table"


def test_conditions_are_typed_quoted_and_anded():
    sql = slices.render({"where": [
        {"column": "MIG_FLAG", "op": "=", "values": ["1"]},
        {"column": "STATUS_CD", "op": "in", "values": ["A", "B"]},
        {"column": "IS_TEST", "op": "not_in", "values": ["TRUE"]},
        {"column": "AMT", "op": "not_null", "values": ["ignored"]},
    ]}, TYPES)
    assert sql == ("(`MIG_FLAG` = 1) AND (`STATUS_CD` IN ('A', 'B')) AND "
                   "(`IS_TEST` NOT IN (true)) AND (`AMT` IS NOT NULL)")


def test_a_value_cannot_break_out_of_its_literal():
    sql = slices.render({"where": [{"column": "STATUS_CD", "op": "=",
                                    "values": ["x' OR 1=1 --\\"]}]}, TYPES)
    assert sql == r"(`STATUS_CD` = 'x\' OR 1=1 --\\')"


@pytest.mark.parametrize("cond, says", [
    ({"column": "NOPE", "op": "=", "values": ["1"]}, "no column"),
    ({"column": "MIG_FLAG", "op": "=", "values": ["1; DROP"]}, "whole numbers"),
    ({"column": "AMT", "op": "=", "values": ["abc"]}, "numbers"),
    ({"column": "IS_TEST", "op": "=", "values": ["yes"]}, "true or false"),
    ({"column": "STATUS_CD", "op": "=", "values": ["A", "B"]}, "one value"),
    ({"column": "STATUS_CD", "op": "LIKE", "values": ["A%"]}, "Unknown operator"),
    ({"column": "STATUS_CD", "op": "in", "values": []}, "Give a value"),
])
def test_what_render_refuses(cond, says):
    with pytest.raises(slices.SliceRejected, match=says):
        slices.render({"where": [cond]}, TYPES)


def test_membership_is_an_in_subquery_on_the_other_tables_real_columns():
    spec = {"member_of": {"column": "CTCT_ID", "table": "prod.mig.attribs", "key": "CONTACT_ID",
                          "where": [{"column": "migration_scope_flag", "op": "=",
                                     "values": ["1"]}]}}
    sql = slices.render(spec, TYPES, {"CONTACT_ID": "string", "migration_scope_flag": "int"})
    assert sql == ("(`CTCT_ID` IN (SELECT `CONTACT_ID` FROM `prod`.`mig`.`attribs` "
                   "WHERE `migration_scope_flag` = 1))")
    assert "appears as CONTACT_ID in prod.mig.attribs" in slices.describe(spec)
    with pytest.raises(slices.SliceRejected, match="catalog.schema.table"):
        slices.render({"member_of": {**spec["member_of"], "table": "prod.x` ; --.t"}},
                      TYPES, {"CONTACT_ID": "string", "migration_scope_flag": "int"})
    with pytest.raises(slices.SliceRejected, match="no column 'CONTACT_ID'"):
        slices.render(spec, TYPES, {"OTHER": "string"})


def test_the_spec_round_trips_and_compares_canonically():
    a = {"where": [{"column": " MIG_FLAG ", "op": "=", "values": [" 1 ", ""]}]}
    b = {"where": [{"column": "MIG_FLAG", "op": "=", "values": ["1"]}], "member_of": None}
    assert slices.dumps(a) == slices.dumps(b)
    assert slices.loads(slices.dumps(a)) == slices.normalise(b)
    assert slices.loads(None) == slices.normalise({})


# --- Who may change it, pure ---------------------------------------------------------

def test_one_person_while_nothing_is_active_two_after():
    assert not slices.needs_second_person(0)
    assert slices.needs_second_person(1)


def test_the_author_cannot_approve_but_can_withdraw():
    with pytest.raises(slices.SliceRejected, match="second person"):
        slices.validate_decision("a@x.com", "A@x.com", "approved", None)
    slices.validate_decision("a@x.com", "a@x.com", "approved", None, allow_self=True)
    slices.validate_decision("a@x.com", "a@x.com", "rejected", "changed my mind")
    with pytest.raises(slices.SliceRejected, match="Say why"):
        slices.validate_decision("a@x.com", "b@x.com", "rejected", " ")


def test_a_pending_proposal_is_carried_until_decided_and_then_dropped():
    proposed = dict(slice_filter="(`A` = 1)", slice_spec="{}", slice_version=2.0,
                    slice_change="proposed", slice_proposed_filter="(`A` = 2)",
                    slice_proposed_spec="{}", slice_proposed_by="a@x.com")
    paused = slices.carry_forward(proposed)
    assert paused["slice_change"] is None and paused["slice_version"] == 2
    assert slices.pending(paused)["filter"] == "(`A` = 2)"
    decided = {**proposed, "slice_change": "rejected"}
    assert slices.pending(decided) is None
    after = slices.carry_forward(decided)
    assert after["slice_proposed_by"] is None and after["slice_filter"] == "(`A` = 1)"


def test_population_and_breaks_read_off_the_runs():
    runs = pd.DataFrame([
        dict(target_table="t", run_ts=pd.Timestamp("2026-10-01"), slice_version=None,
             table_rows=1000, slice_rows=1000),
        dict(target_table="t", run_ts=pd.Timestamp("2026-10-02"), slice_version=None,
             table_rows=1000, slice_rows=1000),
        dict(target_table="t", run_ts=pd.Timestamp("2026-10-03"), slice_version=4,
             table_rows=1000, slice_rows=812),
    ])
    assert slices.run_population(runs, "t")["slice_rows"] == 812
    assert slices.slice_breaks(runs, "t") == [pd.Timestamp("2026-10-03")]
    assert slices.run_population(runs.drop(columns=["table_rows"]), "t") is None


# --- The runner ----------------------------------------------------------------------

@pytest.fixture
def rc():
    sys.path.insert(0, str(ROOT / "jobs"))
    import run_checks
    yield run_checks
    sys.path.remove(str(ROOT / "jobs"))


def _rule(rc, rid, expr, table="c.s.subs", **kw):
    return rc.Rule(rid, 1, "format", expr, table, kw.pop("col", "X"), kw.pop("scope", None),
                   0.0, "P2_alert", "active", **kw)


def test_every_shape_reads_the_sliced_relation(rc):
    sl = {"c.s.subs": "(`MIG_FLAG` = 1)"}
    p = rc.plan([_rule(rc, "ROW", "X IS NULL", scope="Y = 'P'"),
                 _rule(rc, "UNQ", "count(*) OVER (PARTITION BY X) > 1"),
                 _rule(rc, "VAR", "(SELECT count(DISTINCT X) FROM {table}) = 1"),
                 _rule(rc, "OTHER", "X IS NULL", table="c.s.ctct")], {}, sl)
    sliced = "(SELECT * FROM c.s.subs WHERE (`MIG_FLAG` = 1))"
    assert set(p["batched"]) == {sliced, "c.s.ctct"}
    batch = rc.batch_row_level(sliced, p["batched"][sliced])
    assert batch.startswith("SELECT\n  count(*) AS __slice_rows")
    assert f"FROM {sliced}" in batch and "(Y = 'P')" in batch     # scope still ANDed
    singles = dict((r.rule_id, sql) for r, sql in p["singles"])
    assert f"FROM {sliced}" in singles["UNQ"]
    assert singles["VAR"].count(sliced) == 2                    # the expression and the FROM


def test_only_the_driving_table_of_a_join_is_sliced(rc):
    x = _rule(rc, "XREF", "c.K IS NULL", col=None,
              join_sql="c.s.subs s LEFT JOIN c.s.ctct c ON s.K = c.K")
    sql = rc.cross_table_sql(x, {}, {"c.s.subs": "(`F` = 1)", "c.s.ctct": "(`G` = 1)"})
    assert "(SELECT * FROM c.s.subs WHERE (`F` = 1)) s LEFT JOIN c.s.ctct c" in sql
    assert "`G`" not in sql


def test_a_table_whose_name_extends_the_driving_one_is_left_alone(rc):
    x = _rule(rc, "XREF", "h.K IS NULL", col=None,
              join_sql="c.s.subs s JOIN c.s.subs_hist h ON s.K = h.K")
    sql = rc.cross_table_sql(x, {}, {"c.s.subs": "(`F` = 1)"})
    assert "JOIN c.s.subs_hist h" in sql and sql.count("WHERE (`F` = 1)") == 1


def test_no_slice_is_the_query_it_always_was(rc):
    r = _rule(rc, "ROW", "X IS NULL")
    assert rc.plan([r], {}, {})["batched"] == rc.plan([r], {})["batched"]
    assert rc.relation("c.s.subs", None) == "c.s.subs"


# --- Through the page ----------------------------------------------------------------

from test_onboarding import LEAD, _confirm, _read, _text, _write, build  # noqa: E402
from test_onboarding import page  # noqa: E402,F401 -- the fixture

LEAD_COLS = {"LEAD_ID": "string", "EMAIL": "string", "HOME_PHONE": "string",
             "MIG_FLAG": "int", "REGION": "string"}


def sliceable(tmp: Path, *, active: bool = False, **slice_cols) -> Path:
    d = build(tmp)
    m = _read(d, "config.monitored_table")
    for c in slices.SLICE_COLUMNS:
        m[c] = pd.Series([slice_cols.get(c)], dtype="object")
    _write(d, "config.monitored_table", m)
    cat, sch, name = LEAD.split(".")
    _write(d, "catalog.columns", pd.DataFrame([
        dict(table_catalog=cat, table_schema=sch, table_name=name, column_name=c,
             data_type=t, ordinal_position=i, tag_cde=None)
        for i, (c, t) in enumerate(LEAD_COLS.items())]))
    if active:
        reg = _read(d, "config.rule_registry")
        row = reg[reg["rule_id"] == "LEAD_EMAIL_FMT"].iloc[-1].to_dict()
        row.update(rule_version=2, status="active", promoted_by="owner@example.com")
        _write(d, "config.rule_registry", pd.concat([reg, pd.DataFrame([row])],
                                                     ignore_index=True))
    return d


def _fill(at, column="MIG_FLAG", op="=", value="1", note="Migration scope only."):
    if not [s for s in at.selectbox if s.key == "onbsl_w_col_0"]:
        [b for b in at.button if b.key == "onbsl_w_add"][0].click().run()
    [s for s in at.selectbox if s.key == "onbsl_w_col_0"][0].set_value(column).run()
    [s for s in at.selectbox if s.key == "onbsl_w_op_0"][0].set_value(op).run()
    [t for t in at.text_input if t.key == "onbsl_w_val_0"][0].set_value(value).run()
    [t for t in at.text_input if t.key == "onbsl_note"][0].set_value(note).run()
    [b for b in at.button if b.key == "onbsl_count"][0].click().run()
    assert not at.exception, [e.message for e in at.exception]


def _written(at) -> list[dict]:
    return list(at.session_state["_pending_monitored_tables"]) \
        if "_pending_monitored_tables" in at.session_state else []


def test_a_schema_without_the_columns_says_so_and_offers_no_editor(page, tmp_path):
    at = page(build(tmp_path), table=True)
    assert "predates slices" in _text(at)
    assert not [b for b in at.button if b.key == "onbsl_count"]


def test_with_nothing_active_one_person_sets_it_after_counting(page, tmp_path):
    at = page(sliceable(tmp_path), table=True)
    assert "The whole table." in _text(at)
    write = [b for b in at.button if b.key == "onbsl_write"][0]
    assert write.disabled, "offered before the slice was counted"
    _fill(at)
    assert "Keeps" in _text(at) and "(`MIG_FLAG` = 1)" in _text(at)
    [b for b in at.button if b.key == "onbsl_write"][0].click().run()
    assert not _written(at), "wrote before confirming"
    _confirm(at, "slice_write")
    assert not at.exception, [e.message for e in at.exception]
    [row] = _written(at)
    assert (row["slice_change"], row["table_version"], row["slice_version"]) == ("set", 2, 2)
    assert row["slice_filter"] == "(`MIG_FLAG` = 1)" and row["status"] == "selected"
    assert slices.loads(row["slice_spec"])["where"][0]["column"] == "MIG_FLAG"
    assert "MIG_FLAG is 1" in _text(at)


def test_a_column_the_table_does_not_have_is_refused_before_anything_is_offered(page, tmp_path):
    at = page(sliceable(tmp_path), table=True)
    _fill(at, column="MIG_FLAG", value="one")
    assert "whole numbers" in " ".join(str(e.value) for e in at.error)
    assert [b for b in at.button if b.key == "onbsl_write"][0].disabled


def test_once_a_check_is_active_a_change_is_a_proposal_the_author_cannot_approve(page, tmp_path):
    at = page(sliceable(tmp_path, active=True), table=True)
    _fill(at)
    [b for b in at.button if b.key == "onbsl_write"][0].click().run()
    _confirm(at, "slice_write")
    [row] = _written(at)
    assert row["slice_change"] == "proposed" and row["slice_filter"] is None
    assert row["slice_proposed_filter"] == "(`MIG_FLAG` = 1)"
    assert row["slice_proposed_by"] == row["selected_by"] == "m.okonkwo@example.com"
    body = _text(at)
    assert "waiting for a second person" in body and "The whole table." in body
    assert not [b for b in at.button if b.key == "onbsl_approve"]
    assert [str(b.label) for b in at.button if b.key == "onbsl_reject"] == ["Withdraw"]


def test_a_second_person_approves_exactly_what_was_proposed(page, tmp_path):
    d = sliceable(tmp_path, active=True, slice_change="proposed",
                  slice_proposed_filter="(`MIG_FLAG` = 1)",
                  slice_proposed_spec=slices.dumps({"where": [
                      {"column": "MIG_FLAG", "op": "=", "values": ["1"]}]}),
                  slice_proposed_by="steward@example.com")
    m = _read(d, "config.monitored_table")
    m["selected_by"], m["note"] = "steward@example.com", "Migration scope only."
    _write(d, "config.monitored_table", m)
    at = page(d, table=True)
    assert "Why: “Migration scope only.”" in _text(at)
    [b for b in at.button if b.key == "onbsl_approve"][0].click().run()
    _confirm(at, "slice_approve")
    assert not at.exception, [e.message for e in at.exception]
    [row] = _written(at)
    assert (row["slice_change"], row["slice_version"], row["table_version"]) == \
        ("approved", 2, 2)
    assert row["slice_filter"] == row["slice_proposed_filter"] == "(`MIG_FLAG` = 1)"
    assert row["selected_by"] == "m.okonkwo@example.com"
    assert slices.pending(row) is None


def test_the_adapter_refuses_the_authors_approval_even_without_the_page(tmp_path, monkeypatch):
    d = sliceable(tmp_path, active=True, slice_change="proposed",
                  slice_proposed_filter="(`MIG_FLAG` = 1)", slice_proposed_spec="{}",
                  slice_proposed_by="m.okonkwo@example.com")
    monkeypatch.setenv("DQ_FIXTURE_DIR", str(d))
    import streamlit as st
    st.cache_data.clear()
    from dq_app.data import adapter
    with pytest.raises(adapter.SliceRejected, match="second person"):
        adapter.decide_slice(LEAD, "approved")
    with pytest.raises(adapter.SliceRejected, match="already waiting"):
        adapter.set_slice(LEAD, {"where": [{"column": "REGION", "op": "=",
                                            "values": ["AU"]}]}, "x")


def test_pausing_keeps_the_slice_and_any_pending_change(page, tmp_path):
    d = sliceable(tmp_path, active=True, slice_filter="(`MIG_FLAG` = 1)",
                  slice_spec=slices.dumps({"where": [
                      {"column": "MIG_FLAG", "op": "=", "values": ["1"]}]}),
                  slice_version=1, slice_change="proposed",
                  slice_proposed_filter=None, slice_proposed_spec="{}",
                  slice_proposed_by="steward@example.com")
    at = page(d, table=True)
    [t for t in at.text_input if t.key == "onbt_manage_reason"][0].set_value("Source down.").run()
    [b for b in at.button if str(b.label) == "Pause checking"][0].click().run()
    _confirm(at, "pause")
    [row] = _written(at)
    assert row["status"] == "paused" and row["slice_change"] is None
    assert (row["slice_filter"], row["slice_version"]) == ("(`MIG_FLAG` = 1)", 1)
    assert slices.pending(row)["by"] == "steward@example.com"

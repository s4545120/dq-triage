"""The population and the shared joins, in the check runner.

A history table's current records (config.table_population, sql/ddl/21) are applied
under the slice and on every side of a join; cross-table rules sharing a join share one
query. What these pin is the SQL: what it must contain, in what order, and that a table
with no declaration -- every table before 2026-10-12 -- gets exactly what it got before.
The counts were checked on the warehouse; see CLAUDE.md.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def rc():
    sys.path.insert(0, str(ROOT / "jobs"))
    import run_checks
    yield run_checks
    sys.path.remove(str(ROOT / "jobs"))


def _rule(rc, rid, expr, table="c.s.role", **kw):
    return rc.Rule(rid, 1, "consistency", expr, table, kw.pop("col", None),
                   kw.pop("scope", None), 0.0, "P2_alert", "active", **kw)


def _hist(rc, key="K", version=1):
    return rc.Population(record_key=(key,), version_by=("TS", "SCN"),
                         deleted_column="OP_TYPE", deleted_value="D", version=version)


JOIN = "c.s.role r LEFT JOIN c.s.contact c ON r.K = c.K"


# --- Nothing declared: nothing changes ------------------------------------------------

def test_a_table_with_no_population_reads_as_it_always_did(rc):
    rules = [_rule(rc, "ROW", "X IS NULL", col="X"),
             _rule(rc, "UNQ", "count(*) OVER (PARTITION BY X) > 1", col="X"),
             _rule(rc, "XREF", "c.K IS NULL", join_sql=JOIN)]
    assert rc.plan(rules, {}, {}, {}) == rc.plan(rules, {})
    assert rc.relation("c.s.role", None, None) == "c.s.role"
    assert rc.current("c.s.role", rc.Population()) == "c.s.role"
    assert rc.cross_table_sql(rules[2], {}, None, {}) == rc.cross_table_sql(rules[2], {})


def test_an_empty_declaration_puts_a_table_back_on_all_its_rows(rc):
    empty = rc.population_of({"target_table": "c.s.role", "population_version": 2,
                              "record_key": None, "version_by": None,
                              "deleted_column": None, "deleted_value": None})
    assert not empty.narrows() and rc.current("c.s.role", empty) == "c.s.role"


# --- The current record ---------------------------------------------------------------

def test_the_newest_version_is_picked_before_deletions_are_dropped(rc):
    sql = rc.current("c.s.contact", _hist(rc))
    inner = ("(SELECT * FROM c.s.contact QUALIFY row_number() OVER (PARTITION BY `K` "
             "ORDER BY `TS` DESC NULLS LAST, `SCN` DESC NULLS LAST) = 1 OR `K` IS NULL)")
    # The deletion filter wraps the window, never sits beside it: beside it, it would
    # run first and bring a deleted record's previous version back as current.
    assert sql == f"(SELECT * FROM {inner} WHERE NOT (`OP_TYPE` <=> 'D'))"


def test_a_row_with_no_key_is_kept_not_collapsed(rc):
    pop = rc.Population(record_key=("A", "B"), version_by=("TS",))
    assert "= 1 OR `A` IS NULL OR `B` IS NULL)" in rc.current("t", pop)


def test_deletions_alone_need_no_window(rc):
    pop = rc.Population(deleted_column="IS_DEL", deleted_value="Y")
    assert rc.current("t", pop) == "(SELECT * FROM t WHERE NOT (`IS_DEL` <=> 'Y'))"


def test_the_slice_narrows_current_records_not_raw_versions(rc):
    sql = rc.relation("c.s.contact", "(`MIG` = 1)", _hist(rc))
    assert sql == f"(SELECT * FROM {rc.current('c.s.contact', _hist(rc))} WHERE (`MIG` = 1))"


def test_declared_names_are_identifiers_and_values_are_escaped(rc):
    with pytest.raises(ValueError):
        rc.current("t", rc.Population(record_key=("K; DROP",), version_by=("TS",)))
    pop = rc.Population(deleted_column="F", deleted_value="it's \\ here")
    assert "'it\\'s \\\\ here'" in rc.current("t", pop)


def test_every_shape_on_the_table_reads_its_current_records(rc):
    pops = {"c.s.role": _hist(rc)}
    cur = rc.current("c.s.role", _hist(rc))
    p = rc.plan([_rule(rc, "ROW", "X IS NULL", col="X"),
                 _rule(rc, "UNQ", "count(*) OVER (PARTITION BY X) > 1", col="X"),
                 _rule(rc, "VAR", "(SELECT count(DISTINCT X) FROM {table}) = 1", col="X")],
                {}, {}, pops)
    assert list(p["batched"]) == [cur]
    singles = {r.rule_id: sql for r, sql in p["singles"]}
    assert f"FROM {cur}" in singles["UNQ"]       # a key unique among current records
    assert singles["VAR"].count(cur) == 2


def test_a_sample_is_drawn_from_current_records(rc):
    pops = {"c.s.role": _hist(rc), "c.s.contact": _hist(rc)}
    x = _rule(rc, "XREF", "c.K IS NULL", join_sql=JOIN)
    sql = rc.sample_sql(x, "c.s.role", {}, pops=pops)
    assert rc.current("c.s.contact", _hist(rc)) in sql


# --- Joins ----------------------------------------------------------------------------

def test_every_side_of_a_join_reads_current_records_and_only_the_driving_one_is_sliced(rc):
    pops = {"c.s.role": _hist(rc), "c.s.contact": _hist(rc)}
    x = _rule(rc, "XREF", "c.K IS NULL", join_sql=JOIN)
    sql = rc.cross_table_sql(x, {}, {"c.s.role": "(`F` = 1)", "c.s.contact": "(`G` = 1)"},
                             pops)
    driving = rc.relation("c.s.role", "(`F` = 1)", _hist(rc))
    other = rc.current("c.s.contact", _hist(rc))
    assert f"FROM   {driving} r LEFT JOIN {other} c ON r.K = c.K" in sql
    assert "`G`" not in sql


def test_resolution_happens_before_the_population_is_found(rc):
    x = _rule(rc, "XREF", "c.K IS NULL", table="prod.s.role",
              join_sql="prod.s.role r LEFT JOIN prod.s.contact c ON r.K = c.K")
    resolve = {"prod.s.role": "w.s.role", "prod.s.contact": "w.s.contact"}
    sql = rc.cross_table_sql(x, resolve, {}, {"prod.s.contact": _hist(rc)})
    assert f"LEFT JOIN {rc.current('w.s.contact', _hist(rc))} c" in sql
    assert "prod." not in sql


def test_a_name_that_extends_a_declared_one_is_left_alone(rc):
    x = _rule(rc, "XREF", "h.K IS NULL",
              join_sql="c.s.role r JOIN c.s.contact_hist h ON r.K = h.K "
                       "JOIN c.s.contact c ON c.K = r.K")
    sql = rc.cross_table_sql(x, {}, {}, {"c.s.contact": _hist(rc)})
    assert "JOIN c.s.contact_hist h" in sql
    assert sql.count("QUALIFY") == 1


def test_a_self_join_reads_current_records_on_both_sides(rc):
    x = _rule(rc, "DUP", "a.E = b.E", table="c.s.contact",
              join_sql="c.s.contact a JOIN c.s.contact b ON a.K < b.K")
    sql = rc.cross_table_sql(x, {}, {}, {"c.s.contact": _hist(rc)})
    assert sql.count("QUALIFY") == 2


def test_rules_sharing_a_join_share_one_query(rc):
    a = _rule(rc, "ORPHAN", "c.K IS NULL", join_sql=JOIN)
    b = _rule(rc, "AFTER", "r.START_TS < c.CREATED_TS", join_sql=JOIN, scope="c.K IS NOT NULL")
    lone = _rule(rc, "LONE", "o.K IS NULL", join_sql="c.s.role r LEFT JOIN c.s.org o ON r.O = o.O")
    p = rc.plan([a, b, lone], {}, {}, {})
    assert [[r.rule_id for r in rs] for rs in p["joined"].values()] == [["ORPHAN", "AFTER"]]
    # A join nobody else reads is still the single query it was.
    assert [(r.rule_id, sql) for r, sql in p["singles"]] == \
        [("LONE", rc.cross_table_sql(lone, {}))]
    sql = rc.batch_cross_table(JOIN, p["joined"][JOIN])
    assert sql.startswith("SELECT\n  count(*) AS __joined_rows")
    assert "count_if(TRUE) AS s__ORPHAN" in sql
    assert "count_if(TRUE AND (c.K IS NULL)) AS v__ORPHAN" in sql
    assert "count_if((c.K IS NOT NULL)) AS s__AFTER" in sql
    assert "count_if((c.K IS NOT NULL) AND (r.START_TS < c.CREATED_TS)) AS v__AFTER" in sql
    assert sql.endswith(f"FROM {JOIN}")


def test_a_scope_with_a_subquery_keeps_its_own_query(rc):
    a = _rule(rc, "A", "c.K IS NULL", join_sql=JOIN)
    b = _rule(rc, "B", "c.K IS NULL", join_sql=JOIN,
              scope="r.K IN (SELECT K FROM c.s.scope)")
    p = rc.plan([a, b], {}, {}, {})
    assert p["joined"] == {}
    assert {r.rule_id for r, _ in p["singles"]} == {"A", "B"}


def test_the_same_join_under_different_populations_is_two_joins(rc):
    a = _rule(rc, "A", "c.K IS NULL", join_sql=JOIN)
    b = _rule(rc, "B", "c.K IS NULL", join_sql=JOIN, table="c.s.contact")
    # B drives from contact, which is sliced; A does not see that slice.
    p = rc.plan([a, b, _rule(rc, "A2", "c.K IS NULL", join_sql=JOIN)],
                {}, {"c.s.contact": "(`G` = 1)"}, {})
    assert sorted(sorted(r.rule_id for r in rs) for rs in p["joined"].values()) == [["A", "A2"]]
    assert [r.rule_id for r, _ in p["singles"]] == ["B"]


def test_population_of_reads_a_registry_row(rc):
    pop = rc.population_of({"target_table": "t", "population_version": 3,
                            "record_key": ["K"], "version_by": ["TS", "SCN"],
                            "deleted_column": "OP_TYPE", "deleted_value": "D"})
    assert pop == rc.Population(("K",), ("TS", "SCN"), "OP_TYPE", "D", 3)

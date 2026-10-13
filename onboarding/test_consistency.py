"""Cross-table consistency specs: what each renders to, what it refuses, and that the
check runner runs them on its existing path. The counts were proved on the warehouse
over adversarial values (CLAUDE.md, *Consistency checks from a spec*)."""

from __future__ import annotations

import pathlib
import sys

import pytest

import consistency as cs

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "jobs"))
import run_checks as rc  # noqa: E402

ROLE, CTCT = "w.s.role", "w.s.contact"


def _rule(rid, d):
    return rc.Rule(rid, 1, d["rule_type"], d["rule_expr"], d["target_table"],
                   d["target_column"], d["scope_filter"], 0.0, "P2_alert", "shadow",
                   join_sql=d["join_sql"])


# --- Orphans ---------------------------------------------------------------------------

def test_an_orphan_is_a_left_join_with_no_parent():
    d = cs.Orphan(ROLE, ("CONTACT_ID",), CTCT, ("CONTACT_ID",), "fail").render()
    assert d["join_sql"] == f"{ROLE} ch LEFT JOIN {CTCT} pa ON ch.CONTACT_ID = pa.CONTACT_ID"
    assert d["rule_expr"] == "pa.CONTACT_ID IS NULL"
    assert d["scope_filter"] is None                   # a NULL key finds no parent: fails
    assert (d["rule_type"], d["target_table"], d["target_column"]) == \
        ("referential", ROLE, "CONTACT_ID")


def test_ignoring_a_null_key_takes_it_out_of_scope():
    d = cs.Orphan(ROLE, ("A", "B"), CTCT, ("X", "Y"), "ignore").render()
    assert d["scope_filter"] == "ch.A IS NOT NULL AND ch.B IS NOT NULL"
    assert "ch.A = pa.X AND ch.B = pa.Y" in d["join_sql"] and d["target_column"] is None


def test_the_null_key_policy_has_no_default():
    with pytest.raises(TypeError):
        cs.Orphan(ROLE, ("K",), CTCT, ("K",))          # noqa -- deliberately missing
    with pytest.raises(ValueError):
        cs.Orphan(ROLE, ("K",), CTCT, ("K",), "maybe").render()
    with pytest.raises(ValueError):
        cs.Orphan(ROLE, ("K", "J"), CTCT, ("K",), "fail").render()


# --- Agreement -------------------------------------------------------------------------

JOIN = cs.path("w.s.org", "o", cs.Step(ROLE, "r", "r.ORG_ID = o.ORG_ID AND r.IS_PRIMARY"),
               cs.Step(CTCT, "c", "c.CONTACT_ID = r.CONTACT_ID"))


def test_a_path_is_a_join_body():
    assert JOIN == ("w.s.org o JOIN w.s.role r ON r.ORG_ID = o.ORG_ID AND r.IS_PRIMARY "
                    "JOIN w.s.contact c ON c.CONTACT_ID = r.CONTACT_ID")


def test_agreement_is_null_safe_and_compares_normalised_values():
    d = cs.Agreement(JOIN, "w.s.org", "o.PHONE", "c.PHONE", "phone_au", "differs").render()
    assert d["rule_expr"] == ("NOT (nullif(dq.fn.au_phone_digits_v1(o.PHONE), '') <=> "
                              "nullif(dq.fn.au_phone_digits_v1(c.PHONE), ''))")
    assert d["scope_filter"] is None and d["target_column"] == "PHONE"
    assert cs.unsafe_comparisons(d["rule_expr"], d["join_sql"]) == []


def test_skipping_one_empty_side_scopes_to_pairs_with_both():
    d = cs.Agreement(JOIN, "w.s.org", "o.NAME", "c.NAME", "text", "skip").render()
    assert d["scope_filter"].endswith("IS NOT NULL") and d["scope_filter"].count("IS NOT NULL") == 2


def test_a_number_may_carry_a_tolerance_and_nothing_else_may():
    d = cs.Agreement(JOIN, "w.s.org", "o.N", "c.N", "number", "differs", 0.5).render()
    assert "abs(try_cast(o.N AS DECIMAL(38, 6)) - try_cast(c.N AS DECIMAL(38, 6))) > 0.5" \
        in d["rule_expr"]
    with pytest.raises(ValueError):
        cs.Agreement(JOIN, "w.s.org", "o.N", "c.N", "text", "differs", 0.5).render()
    with pytest.raises(ValueError):
        cs.Agreement(JOIN, "w.s.org", "o.N", "c.N", "number", "differs", -1).render()


def test_agreement_refuses_what_it_cannot_name():
    with pytest.raises(ValueError):
        cs.Agreement(JOIN, "w.s.org", "PHONE", "c.PHONE", "exact", "differs").render()
    with pytest.raises(ValueError):
        cs.Agreement(JOIN, "w.s.org", "o.PHONE", "c.PHONE", "fuzzy", "differs").render()
    with pytest.raises(ValueError):
        cs.Agreement(JOIN, "w.s.org", "o.PHONE", "c.PHONE", "exact", "ignore").render()


# --- Reconciliation --------------------------------------------------------------------

def test_a_grouped_reconciliation_is_a_full_outer_join_of_two_aggregates():
    d = cs.Reconcile(cs.Side("w.s.a", "sum(AMT)", "STATUS = 'A'", ("ST",)),
                     cs.Side("w.s.b", "sum(AMT)", None, ("STATE",)), rel_tolerance=0.1).render()
    assert d["join_sql"] == (
        "(SELECT ST AS __g0, sum(AMT) AS __v, 1 AS __present FROM w.s.a "
        "WHERE STATUS = 'A' GROUP BY ST) l FULL OUTER JOIN "
        "(SELECT STATE AS __g0, sum(AMT) AS __v, 1 AS __present FROM w.s.b "
        "GROUP BY STATE) r ON l.__g0 <=> r.__g0")
    # A group on one side only is a violation, not a NULL the count drops.
    assert d["rule_expr"].startswith("l.__present IS NULL OR r.__present IS NULL OR ")
    assert "greatest(0.0, 0.1 * abs(r.__v))" in d["rule_expr"]
    assert (d["target_table"], d["target_column"], d["scope_filter"]) == ("w.s.a", None, None)


def test_an_ungrouped_reconciliation_is_one_row():
    d = cs.Reconcile(cs.Side("w.s.a", "count(*)"), cs.Side("w.s.b", "count(*)")).render()
    assert " CROSS JOIN " in d["join_sql"] and "GROUP BY" not in d["join_sql"]


def test_both_sides_group_the_same_way():
    with pytest.raises(ValueError):
        cs.Reconcile(cs.Side("a", "count(*)", group_by=("X",)), cs.Side("b", "count(*)")).render()
    with pytest.raises(ValueError):
        cs.Reconcile(cs.Side("a", "count(*)", group_by=("X; --",)),
                     cs.Side("b", "count(*)", group_by=("Y",))).render()


# --- Through the runner ----------------------------------------------------------------

def test_two_orphan_policies_on_one_link_share_one_query():
    a = _rule("IGN", cs.Orphan(ROLE, ("CONTACT_ID",), CTCT, ("CONTACT_ID",), "ignore").render())
    b = _rule("FAIL", cs.Orphan(ROLE, ("CONTACT_ID",), CTCT, ("CONTACT_ID",), "fail").render())
    p = rc.plan([a, b], {})
    assert [[r.rule_id for r in rs] for rs in p["joined"].values()] == [["IGN", "FAIL"]]
    assert p["singles"] == []


def test_a_reconciliation_reads_current_records_on_both_sides():
    pop = rc.Population(("K",), ("TS",), "OP_TYPE", "D", 1)
    r = _rule("REC", cs.Reconcile(cs.Side(ROLE, "count(DISTINCT CONTACT_ID)"),
                                  cs.Side(CTCT, "count(*)")).render())
    sql = rc.cross_table_sql(r, {}, {}, {ROLE: pop, CTCT: pop})
    assert f"FROM {rc.current(ROLE, pop)})" in sql and f"FROM {rc.current(CTCT, pop)})" in sql


# --- The lint --------------------------------------------------------------------------

def test_the_lint_finds_the_comparison_that_misses_nulls():
    expr = "lower(trim(s.SUBS_FRST_NM)) <> lower(trim(c.FRST_NM))"   # XREF_NAME_AGREEMENT
    assert len(cs.unsafe_comparisons(expr, "a s JOIN b c ON s.K = c.K")) == 1
    assert len(cs.unsafe_comparisons("s.ECF_OPEN_TS != c.CTCT_ADD_TS", "a s JOIN b c")) == 1


def test_the_lint_ignores_single_table_rules_and_string_literals():
    assert cs.unsafe_comparisons("STATUS <> 'X'", None) == []
    assert cs.unsafe_comparisons("STATUS <> 'X'", float("nan")) == []      # NULL via pandas
    assert cs.unsafe_comparisons("c.NOTE = 'a <> b'", "a s JOIN b c") == []


# --- A stored proposal: what the job renders, and what it refuses -----------------------------

import json  # noqa: E402

AGREE = {"kind": "agreement",
         "hops": [{"from": "w.s.org", "to": "w.s.role", "keys": [["ORG_ID", "ORG_ID"]]},
                  {"from": "w.s.role", "to": "w.s.contact", "keys": [["CONTACT_ID", "CONTACT_ID"]]}],
         "left": "PHONE", "right": "PHONE", "compare": "phone_au", "empty_one_side": "differs"}


def _proposal(spec, **kw):
    r = cs.render_spec(spec)
    return {"proposal_id": "p1", "rule_id": "CS_0000000A", "cde_id": "CDE_X",
            "spec": json.dumps(spec), "proposed_by": "a@x.com", "reviewed_by": "b@x.com",
            "review_reason": None, **{k: r[k] for k in ("join_sql", "rule_expr", "scope_filter")},
            **kw}


def test_a_two_link_agreement_renders_one_join_with_numbered_aliases():
    r = cs.render_spec(AGREE)
    assert r["join_sql"] == ("w.s.org t0 JOIN w.s.role t1 ON t0.ORG_ID = t1.ORG_ID "
                             "JOIN w.s.contact t2 ON t1.CONTACT_ID = t2.CONTACT_ID")
    assert r["rule_expr"].startswith("NOT (nullif(dq.fn.au_phone_digits_v1(t0.PHONE)")
    assert "t2.PHONE" in r["rule_expr"] and r["target_table"] == "w.s.org"
    assert cs.tables_of(AGREE) == ["w.s.org", "w.s.role", "w.s.contact"]


def test_links_must_chain_and_keys_must_be_identifiers():
    bad = json.loads(json.dumps(AGREE))
    bad["hops"][1]["from"] = "w.s.other"
    with pytest.raises(ValueError):
        cs.render_spec(bad)
    bad = json.loads(json.dumps(AGREE))
    bad["hops"][0]["keys"] = [["ORG_ID; --", "ORG_ID"]]
    with pytest.raises(ValueError):
        cs.render_spec(bad)
    with pytest.raises(ValueError):
        cs.render_spec({**AGREE, "hops": AGREE["hops"] * 2})       # at most two links


def test_a_spec_renders_with_a_relation_in_place_of_each_table_but_reports_the_table():
    r = cs.render_spec(AGREE, rel=lambda t: f"(SELECT * FROM {t})")
    assert r["join_sql"].startswith("(SELECT * FROM w.s.org) t0")
    assert r["target_table"] == "w.s.org"


def test_totals_measures_are_built_not_typed():
    s = {"kind": "totals", "left": {"table": "a.b.c", "agg": "sum", "column": "AMT",
                                    "group_by": "ST"},
         "right": {"table": "a.b.d", "agg": "count_distinct", "column": "K", "group_by": "STATE"},
         "rel_tolerance": 0.1}
    r = cs.render_spec(s)
    assert "sum(AMT) AS __v" in r["join_sql"] and "count(DISTINCT K) AS __v" in r["join_sql"]
    with pytest.raises(ValueError):
        cs.render_spec({**s, "left": {**s["left"], "agg": "avg"}})
    with pytest.raises(ValueError):
        cs.render_spec({**s, "left": {**s["left"], "column": "AMT) FROM x --"}})


def test_the_job_applies_a_clean_approval():
    assert cs.refusal(_proposal(AGREE), [], {"CDE_X"}) is None


def test_the_job_refuses_what_it_must():
    p = _proposal(AGREE)
    assert "proposed it" in cs.refusal({**p, "reviewed_by": "A@x.com"}, [], {"CDE_X"})
    assert cs.refusal({**p, "reviewed_by": "a@x.com",
                       "review_reason": f"{cs.WAIVER_MARK} ok"}, [], {"CDE_X"}) is None
    assert "already used" in cs.refusal(p, [{"rule_id": "CS_0000000A", "rule_version": 1}],
                                        {"CDE_X"})
    assert "not a registered" in cs.refusal(p, [], set())
    assert "differently" in cs.refusal({**p, "rule_expr": "TRUE"}, [], {"CDE_X"})
    twin = {"rule_id": "OLD", "rule_version": 2, "status": "active",
            **{k: p[k] for k in ("join_sql", "rule_expr", "scope_filter")}}
    assert "OLD already does" in cs.refusal(p, [twin], {"CDE_X"})
    assert cs.refusal(p, [{**twin, "status": "retired"}], {"CDE_X"}) is None


def test_the_fingerprint_ignores_case_and_spacing_and_nothing_else():
    a = cs.render_spec(AGREE)
    b = {k: (v.upper().replace(" ", "  ") if isinstance(v, str) else v) for k, v in a.items()}
    assert cs.fingerprint(a) == cs.fingerprint(b)
    assert cs.fingerprint(a) != cs.fingerprint({**a, "scope_filter": "t0.X IS NOT NULL"})

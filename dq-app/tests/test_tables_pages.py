"""The two Tables pages, redrawn 2026-10-06: the inventory and one table opened up.

Pinned here: the inventory's figures agree with each other and with the scope the
scorecard uses; a row opens its table; the detail page lists every rule, opens on a
breaching one, says when the register disputes a rule's scope, and "Investigate rows"
lands on the sample rows.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402

from dq_app.data import adapter  # noqa: E402
from dq_app.ui import monitoring  # noqa: E402

APP_DIR = Path(__file__).resolve().parents[1]
LIST = "dq_app/ui/pages/tables.py"
DETAIL = "dq_app/ui/pages/table_detail.py"


def _run(page: str, **session):
    at = AppTest.from_file(str(APP_DIR / page), default_timeout=90)
    for k, v in session.items():
        at.session_state[k] = v
    at.run()
    assert not at.exception, [e.message for e in at.exception]
    return at


def _body(at) -> str:
    return " ".join(str(m.value) for m in at.markdown) + " " + \
        " ".join(str(c.value) for c in at.caption)


@pytest.fixture(scope="module")
def tables():
    return monitoring.table_rows(monitoring.scoped_runs(adapter.get_check_runs()), 30)


def test_retired_rules_are_not_counted(tables):
    """The vulnerable-customer variance rule was retired on 2026-10-01; the fixture's
    runs predate that and still carry it. The table must not count it."""
    scoped = monitoring.scoped_runs(adapter.get_check_runs())
    assert "CTCT_SPCL_CARE_VARIANCE" not in set(scoped["rule_id"])


def test_the_four_figures_add_up_to_the_rows(tables):
    at = _run(LIST)
    body = _body(at)
    checks = sum(t["Checks"] for t in tables)
    breaching = sum(t["Breaching"] for t in tables)
    assert f"{breaching}" in body and f"/ {checks}" in body
    assert f"Across {checks} monitored rules." in body
    assert f"{checks - breaching} passing" in body
    assert all(t["Passing"] + t["Breaching"] == t["Checks"] for t in tables)


def test_every_table_is_a_row_that_opens_it(tables):
    at = _run(LIST)
    for t in tables:
        assert any(b.key == f"_open_dqrow_tm_{t['key']}" for b in at.button), t["key"]
    first = tables[0]["key"]
    next(b for b in at.button if b.key == f"_open_dqrow_tm_{first}").click().run()
    assert at.session_state["monitors_selected_table"] == first


def test_the_list_says_its_figure_is_checks_not_rows():
    assert "checks passing, not row-level quality" in _body(_run(LIST))


def test_critical_filter_shows_only_critical_tables(tables):
    at = _run(LIST, _tm_show="critical")
    critical = {t["key"] for t in tables if t["Status"] == "Critical"}
    shown = {str(b.key)[len("_open_dqrow_tm_"):] for b in at.button
             if str(b.key).startswith("_open_dqrow_tm_")}
    assert shown == critical


def test_review_critical_rules_opens_a_p1_rule(tables):
    at = _run(LIST)
    at.button(key="_tm_review_p1").click().run()
    picked = at.session_state["_tm_rule_pick"]
    rows = monitoring.rule_rows(monitoring.scoped_runs(adapter.get_check_runs()),
                                at.session_state["monitors_selected_table"],
                                adapter.get_rule_registry_current())
    row = next(r for r in rows if r["key"] == picked)
    assert row["Breach"] and row["Severity"] == "P1_block"


def test_the_detail_page_lists_every_rule_on_the_table(tables):
    for t in tables:
        at = _run(DETAIL, monitors_selected_table=t["key"], _tm_rule_filter="all")
        ids = {str(b.key)[len("_open_dqrow_tr_"):] for b in at.button
               if str(b.key).startswith("_open_dqrow_tr_")}
        assert len(ids) == t["Checks"], t["key"]
        assert f"Applied rules ({t['Checks']})" in _body(at)


def test_the_detail_page_opens_on_a_breaching_rule(tables):
    at = _run(DETAIL, monitors_selected_table=tables[0]["key"])
    assert "Failing" in _body(at) or "Disputed scope" in _body(at)


def test_a_disputed_rule_says_so_and_is_not_assessed():
    """COH-B's rule on subs_c: over its limit, but the register says it measures rows
    it should not. The pane must not call it a shortfall."""
    subs = next(t for t in monitoring.table_rows(
        monitoring.scoped_runs(adapter.get_check_runs()), 30) if t["key"].endswith("subs_c"))
    at = _run(DETAIL, monitors_selected_table=subs["key"],
              _tm_rule_pick="SUBS_PRIM_ACCT_NOT_ZERO")
    body = _body(at)
    assert "Disputed scope" in body
    assert "not assessed" in body
    assert "pts below" not in body.split("Selected rule")[1].split("Pass rate")[1][:120]


def test_investigate_rows_opens_the_sample_rows_tab(tables):
    at = _run(DETAIL, monitors_selected_table=tables[0]["key"])
    at.button(key="_tm_investigate").click().run()
    pick = next(k for k in at.session_state.filtered_state if k.startswith("_tm_tab_"))
    assert str(at.session_state[pick]).startswith("Sample rows")

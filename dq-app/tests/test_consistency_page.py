"""The Consistency page and the folding behind it (domain/consistency.py).

On the fixture: one relationship (subs_c → ctct_c) and four checks on it -- the orphan
check, the two agreement rules, and the totals reconciliation written from
onboarding/consistency.Reconcile, in shadow.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from dq_app.data import adapter
from dq_app.domain import consistency as cs
from dq_app.domain import metrics

APP_DIR = Path(__file__).resolve().parents[1]
PAGE = "dq_app/ui/pages/consistency.py"


@pytest.fixture(scope="module")
def checks():
    runs = adapter.get_check_runs()
    measured = metrics.last_per_day(runs[runs["status"] != "error"])
    latest = (measured.sort_values("run_ts").drop_duplicates("rule_id", keep="last")
              .set_index("rule_id"))
    return cs.checks(adapter.get_rule_registry_current(), latest)


def _onboarding_consistency():
    path = APP_DIR.parent / "onboarding" / "consistency.py"
    spec = importlib.util.spec_from_file_location("onboarding_consistency", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["onboarding_consistency"] = mod
    spec.loader.exec_module(mod)
    return mod


# --- The folding -----------------------------------------------------------------------

def test_the_fixture_has_one_relationship_and_one_check_of_every_kind(checks):
    assert {c["key"]: c["Kind"] for c in checks} == {
        "XREF_SUBS_CTCT_ORPHAN": "Missing record", "XREF_NAME_AGREEMENT": "Same value",
        "XREF_OPEN_TS_AGREEMENT": "Same value", "XREF_SUBS_CTCT_COUNT": "Same total"}
    rels = cs.relationships(checks)
    assert [(r["Label"], len(r["Checks"])) for r in rels] == [("subs_c → ctct_c", 4)]


def test_states_come_from_each_checks_own_latest_run(checks):
    by = {c["key"]: c for c in checks}
    assert by["XREF_NAME_AGREEMENT"]["State"] == "Failing"
    assert by["XREF_NAME_AGREEMENT"]["Failing rows"] == 2
    assert by["XREF_SUBS_CTCT_ORPHAN"]["State"] == "Passing"
    assert by["XREF_SUBS_CTCT_COUNT"]["State"] == "Shadow"
    assert by["XREF_SUBS_CTCT_COUNT"]["Checked"] == 1         # one group: ungrouped
    assert [c["State"] for c in checks][:2] == ["Failing", "Failing"]   # failing first


def test_the_summary_counts_a_floor_and_leaves_totals_out_of_it(checks):
    s = cs.summary(checks)
    assert (s["relationships"], s["checks"], s["active"], s["shadow"]) == (1, 4, 3, 1)
    assert (s["failing"], s["failing_p1"], s["unsafe"]) == (2, 0, 2)
    assert s["rows_floor"] == 11            # the larger of 2 and 11, never their sum


def test_tables_are_read_off_the_join_aliases_and_literals_aside():
    assert cs.tables_of("a.b.c x LEFT JOIN a.b.d y ON x.K = y.K AND y.N = 'p.q.r'") == \
        ["a.b.c", "a.b.d"]
    assert cs.tables_of("(SELECT count(*) AS __v FROM a.b.c) l CROSS JOIN "
                        "(SELECT count(*) AS __v FROM a.b.c) r") == ["a.b.c"]


def test_the_lint_copy_agrees_with_the_one_in_onboarding(checks):
    onb = _onboarding_consistency()
    exprs = [(c["rule_expr"], c["join_sql"]) for c in checks] + [
        ("STATUS <> 'X'", None), ("c.N = 'a <> b'", "t c"), ("a != b", "t a JOIN u b"),
        ("x <> y", float("nan"))]
    for e, j in exprs:
        assert cs.unsafe_comparisons(e, j) == onb.unsafe_comparisons(e, j)


def test_plain_words_say_what_fails_and_flag_an_unsafe_comparison(checks):
    by = {c["key"]: c for c in checks}
    orphan = cs.plain_words(by["XREF_SUBS_CTCT_ORPHAN"])
    assert orphan[0] == "Each row of subs_c is looked up on ctct_c by s.CTCT_KEY = c.CTCT_KEY."
    assert "A row with no key fails too" in orphan[2]
    assert any("not null-safe" in x for x in cs.plain_words(by["XREF_NAME_AGREEMENT"]))
    assert "group found on one side only" in " ".join(cs.plain_words(by["XREF_SUBS_CTCT_COUNT"]))


# --- The page -----------------------------------------------------------------------------

def _run(**session):
    at = AppTest.from_file(str(APP_DIR / PAGE), default_timeout=90)
    for k, v in session.items():
        at.session_state[k] = v
    at.run()
    assert not at.exception, [e.message for e in at.exception]
    return at


def _body(at) -> str:
    return " ".join(str(m.value) for m in at.markdown)


def test_the_page_lists_every_check_and_warns_about_the_two_unsafe_ones():
    body = _body(_run())
    for name in ("Every subscription resolves to a contact",
                 "Subscriber first name agrees with contact first name",
                 "Subscriptions and contacts carry the same number of customers"):
        assert name in body
    assert "2 checks compare with" in body


def test_picking_a_check_opens_its_rows_and_definition():
    at = _run(_cs_pick="XREF_NAME_AGREEMENT")
    body = _body(at)
    assert "How the two sides are matched" in body
    assert "2 of 2 captured." in [c.value for c in at.caption]
    assert any("XREF" not in c.value and "lower(trim(s.SUBS_FRST_NM))" in c.value
               for c in at.code)
    assert any(b.label == "Open in Rules" for b in at.button)


def test_a_relationship_filters_the_checks_and_nothing_here_writes():
    rel = "prod.customer.subs_c|prod.customer.ctct_c"
    assert "On subs_c → ctct_c." in _body(_run(_cs_rel=rel))
    # Promotion lives on the Rules page; this page has no write of its own.
    src = (APP_DIR / PAGE).read_text()
    assert "adapter.promote" not in src and "record_event" not in src

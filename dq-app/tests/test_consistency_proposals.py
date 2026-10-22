"""Proposing a consistency check and having someone else review it (2026-10-13).

The builder writes a spec to config.consistency_proposal; a second person decides it in
config.consistency_review; the onboarding job writes the rule in shadow. Locally both
writes are session-only, and nothing can be tested (no source rows), which the pages say.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from dq_app.domain import consistency as cs
from dq_app.domain import consistency_spec as spec_mod

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parent
NEW = str(APP / "dq_app/ui/pages/consistency_new.py")
REV = str(APP / "dq_app/ui/pages/consistency_review.py")
HOME = str(APP / "dq_app/ui/pages/consistency.py")
SUBS, CTCT = "prod.customer.subs_c", "prod.customer.ctct_c"
SPEC = {"kind": "agreement", "hops": [{"from": SUBS, "to": CTCT, "keys": [["CTCT_KEY", "CTCT_KEY"]]}],
        "left": "SUBS_FRST_NM", "right": "FRST_NM", "compare": "text",
        "empty_one_side": "differs", "tolerance": 0.0}


# --- Copies stay copies ------------------------------------------------------------------------

def test_the_apps_renderer_is_the_jobs_byte_for_byte():
    """Only dq-app ships, so it carries onboarding/consistency.py as consistency_spec.
    Change one, copy it over the other."""
    assert (APP / "dq_app/domain/consistency_spec.py").read_bytes() == \
        (ROOT / "onboarding/consistency.py").read_bytes()


@pytest.fixture
def rc():
    sys.path.insert(0, str(ROOT / "jobs"))
    import run_checks
    yield run_checks
    sys.path.remove(str(ROOT / "jobs"))


@pytest.mark.parametrize("pop", [
    {"record_key": ["K"], "version_by": ["TS", "SCN"], "deleted_column": "OP_TYPE",
     "deleted_value": "D"},
    {"record_key": ["A", "B"], "version_by": ["TS"], "deleted_column": None,
     "deleted_value": None},
    {"record_key": None, "version_by": None, "deleted_column": "IS_DEL", "deleted_value": "Y"},
    None,
])
def test_a_test_reads_current_records_exactly_as_the_runner_does(rc, pop):
    runner = rc.current("t", None if pop is None else rc.population_of(pop))
    assert cs.current("t", pop) == runner


# --- What a test runs ---------------------------------------------------------------------------

def test_a_test_is_select_only_on_current_records():
    pop = {SUBS: {"record_key": ["SUBS_KEY"], "version_by": ["TS"], "deleted_column": None,
                  "deleted_value": None}}
    q = cs.test_queries(SPEC, pop)
    cur = cs.current(SUBS, pop[SUBS])
    for sql in [q["count"], q["sample"]] + [h[k] for h in q["hops"] for k in ("match", "fanout")]:
        assert sql.lstrip().upper().startswith("SELECT")
        assert not any(w in sql.upper() for w in ("INSERT", "UPDATE", "DELETE", "MERGE"))
    assert cur in q["count"] and cur in q["hops"][0]["match"]
    assert f"LIMIT {cs.SAMPLE_LIMIT}" in q["sample"]
    s = cs.summarise({"compared": 10, "failing": 2, "sample": None,
                      "hops": [{"total": 8, "matched": 6, "fanout": 1}]})
    assert (s["match_pct"], s["fanout"]) == (75.0, 1)


def test_types_are_checked_per_key_and_unknown_off_the_catalog():
    t = cs.type_checks(SPEC, {SUBS: {"CTCT_KEY": "string"}, CTCT: {"CTCT_KEY": "BIGINT"}})
    assert t[0]["ok"] is False and t[0]["to_type"] == "BIGINT"
    assert cs.type_checks(SPEC, {})[0]["ok"] is None


# --- What a proposal must pass --------------------------------------------------------------------

def _validate(**kw):
    args = dict(spec=SPEC, name="Names agree", cde_id="CDE_CUST_NAME", severity="P3_monitor",
                reason="copied at migration", test=None, fanout_ack=False,
                registry=pd.DataFrame(columns=["rule_id", "rule_version", "status",
                                               "join_sql", "rule_expr", "scope_filter"]),
                state=cs.proposal_state(pd.DataFrame(), pd.DataFrame(), pd.DataFrame()),
                registered={"CDE_CUST_NAME"})
    args.update(kw)
    spec = args.pop("spec")
    return cs.validate_proposal(spec, args.pop("name"), args.pop("cde_id"),
                                args.pop("severity"), args.pop("reason"), **args)


def test_a_complete_proposal_renders_and_carries_its_fingerprint():
    r = _validate()
    assert r["fingerprint"] == spec_mod.fingerprint(spec_mod.render_spec(SPEC))


@pytest.mark.parametrize("kw, says", [
    ({"reason": " "}, "why"),
    ({"name": ""}, "name"),
    ({"severity": "P9"}, "severity"),
    ({"cde_id": "CDE_NOPE"}, "key attribute"),
    ({"spec": {**SPEC, "empty_one_side": None}}, "not complete"),
    ({"test": {"compared": 9, "failing": 0, "match_pct": 12.0, "fanout": 0}}, "wrong key"),
    ({"test": {"compared": 9, "failing": 0, "match_pct": 99.0, "fanout": 3}}, "more than one"),
])
def test_a_proposal_is_refused_with_a_reason(kw, says):
    with pytest.raises(ValueError, match=says):
        _validate(**kw)


def test_fanout_is_allowed_once_acknowledged():
    _validate(test={"compared": 9, "failing": 0, "match_pct": 99.0, "fanout": 3}, fanout_ack=True)


def test_the_same_check_cannot_be_proposed_twice_or_over_an_existing_rule():
    r = spec_mod.render_spec(SPEC)
    existing = pd.DataFrame([{"rule_id": "OLD", "rule_version": 1, "status": "shadow", **r}])
    with pytest.raises(ValueError, match="OLD already"):
        _validate(registry=existing)
    waiting = pd.DataFrame([{"proposal_id": "p", "rule_id": "CS_00000001",
                             "fingerprint": spec_mod.fingerprint(r), "proposed_at": 1}])
    state = cs.proposal_state(waiting, pd.DataFrame(), pd.DataFrame(columns=["rule_id", "note"]))
    with pytest.raises(ValueError, match="already proposed"):
        _validate(state=state)


def test_a_review_needs_someone_else_and_a_rejection_needs_a_reason():
    p = {"proposed_by": "a@x.com"}
    with pytest.raises(ValueError, match="own"):
        cs.validate_review(p, "A@x.com", "approved", None, allow_self=False)
    cs.validate_review(p, "a@x.com", "approved", None, allow_self=True)
    with pytest.raises(ValueError, match="why"):
        cs.validate_review(p, "b@x.com", "rejected", " ", allow_self=False)


def test_state_moves_open_approved_applied_and_rejected():
    props = pd.DataFrame([{"proposal_id": i, "rule_id": f"CS_0000000{i}", "fingerprint": i,
                           "proposed_at": 1} for i in "123"])
    revs = pd.DataFrame([{"proposal_id": "2", "decision": "approved", "reviewed_at": 1,
                          "reviewed_by": "b", "reason": None},
                         {"proposal_id": "3", "decision": "approved", "reviewed_at": 1,
                          "reviewed_by": "b", "reason": None}])
    reg = pd.DataFrame([{"rule_id": "CS_00000003", "note": "[consistency_proposal 3] x"}])
    st = cs.proposal_state(props, revs, reg).set_index("proposal_id")["state"].to_dict()
    assert st == {"1": "open", "2": "approved", "3": "applied"}


# --- Through the pages ----------------------------------------------------------------------------

def _propose() -> AppTest:
    at = AppTest.from_file(NEW, default_timeout=90)
    at.run()
    at.selectbox(key="_csn_left").set_value(SUBS).run()
    at.selectbox(key="_csn_right").set_value(CTCT).run()
    assert (at.selectbox(key=f"_csn_k1_{SUBS}_{CTCT}").value,
            at.selectbox(key=f"_csn_k2_{SUBS}_{CTCT}").value) == ("CTCT_KEY", "CTCT_KEY")
    at.selectbox(key=f"_csn_lc_{SUBS}").set_value("SUBS_FRST_NM")
    at.selectbox(key=f"_csn_rc_{CTCT}").set_value("FRST_NM").run()
    cmp_key = next(s.key for s in at.selectbox if (s.key or "").startswith("_csn_cmp_"))
    at.selectbox(key=cmp_key).set_value("text")
    at.radio(key="_csn_empty").set_value("differs")
    at.text_area(key="_csn_why").input("Copied from the contact at migration.").run()
    assert not at.exception, [e.message for e in at.exception]
    return at


def test_nothing_is_written_until_the_proposal_is_confirmed():
    at = _propose()
    at.button(key="_csn_propose").click().run()
    assert not at.session_state["_pending_consistency_proposals"] \
        if "_pending_consistency_proposals" in at.session_state else True
    assert any(b.label == "Propose" for b in at.button)       # the dialog asks first


def test_a_proposal_is_reviewed_by_someone_else_and_shows_on_the_consistency_page():
    at = _propose()
    at.button(key="_csn_propose").click().run()
    next(b for b in at.button if (b.key or "").startswith("_onb_ask_yes")).click().run()
    assert not at.exception, [e.message for e in at.exception]
    rows = at.session_state["_pending_consistency_proposals"]
    assert len(rows) == 1 and rows[0]["rule_name"] == "subs_c SUBS_FRST_NM = ctct_c FRST_NM"
    assert json.loads(rows[0]["spec"])["compare"] == "text" and rows[0]["test_compared"] is None
    assert "<=>" in rows[0]["rule_expr"]

    rv = AppTest.from_file(REV, default_timeout=90)
    rv.session_state["_cs_proposal"] = rows[0]["proposal_id"]
    rv.session_state["_pending_consistency_proposals"] = rows
    rv.run()
    assert "You can’t review your own proposal." in [c.value for c in rv.caption]
    rv.session_state["_local_identity"] = "p.nguyen@example.com"
    rv.run()
    rv.radio(key="_csr_dec").set_value("rejected").run()
    rv.button(key="_csr_submit").click().run()
    next(b for b in rv.button if (b.key or "").startswith("_onb_ask_yes")).click().run()
    assert "_pending_consistency_reviews" not in rv.session_state or \
        not rv.session_state["_pending_consistency_reviews"]      # no reason: refused
    rv.text_area(key="_csr_reason").input("Names are captured separately on purpose.").run()
    rv.button(key="_csr_submit").click().run()
    next(b for b in rv.button if (b.key or "").startswith("_onb_ask_yes")).click().run()
    assert not rv.exception, [e.message for e in rv.exception]
    (review,) = rv.session_state["_pending_consistency_reviews"]
    assert (review["decision"], review["reviewed_by"]) == ("rejected", "p.nguyen@example.com")

    waiting = AppTest.from_file(HOME, default_timeout=90)
    waiting.session_state["_pending_consistency_proposals"] = rows
    waiting.run()
    assert "Needs review" in " ".join(str(m.value) for m in waiting.markdown)
    home = AppTest.from_file(HOME, default_timeout=90)
    home.session_state["_pending_consistency_reviews"] = [review]
    home.session_state["_pending_consistency_proposals"] = rows
    home.run()
    body = " ".join(str(m.value) for m in home.markdown)
    # Waiting, it is listed; decided, it leaves the Proposals card (the review page
    # keeps it, with its decision).
    assert ">Proposals<" not in body and "Needs review" not in body
    rv.run()
    assert "Rejected" in " ".join(str(m.value) for m in rv.markdown)


def test_changing_a_table_picks_its_key_afresh():
    """A key picker keeps its value across reruns; keyed only by position it kept the
    previous table's key after the table changed (found on the warehouse: OBJID offered
    as contact_role's link to contact). Keyed by its tables, it re-picks."""
    at = AppTest.from_file(NEW, default_timeout=90)
    at.run()
    at.selectbox(key="_csn_left").set_value(CTCT).run()
    at.selectbox(key="_csn_right").set_value(SUBS).run()
    first = at.selectbox(key=f"_csn_k1_{CTCT}_{SUBS}").value
    at.selectbox(key="_csn_left").set_value(SUBS).run()
    at.selectbox(key="_csn_right").set_value(CTCT).run()
    assert at.selectbox(key=f"_csn_k1_{SUBS}_{CTCT}").value == "CTCT_KEY"
    assert first == "CTCT_KEY"


def test_the_review_page_without_a_pick_says_so():
    at = AppTest.from_file(REV, default_timeout=90)
    at.run()
    assert not at.exception
    assert any("Pick a proposal" in str(i.value) for i in at.info)


def test_a_table_the_app_cannot_list_is_said_and_offers_its_row_key(monkeypatch):
    """On the warehouse the app's principal may have no access to a source schema; the
    catalog then lists no columns and the builder falls back to what the register knows
    (found on dq_triage: contact_role offered ROLE_NAME only). It must say so, and the
    table's declared row key must be among the fallback columns."""
    from dq_app.data import adapter
    mon = pd.DataFrame([
        {"target_table": t, "table_version": 1, "status": "selected", "row_key": [k]}
        for t, k in ((SUBS, "SUBS_KEY"), (CTCT, "CTCT_KEY"))])
    monkeypatch.setattr(adapter, "get_monitored_tables", lambda: mon)
    monkeypatch.setattr(adapter, "get_catalog_columns", lambda fqn: pd.DataFrame())
    at = AppTest.from_file(NEW, default_timeout=90)
    at.run()
    assert not at.exception, [e.message for e in at.exception]
    assert any("can’t list the columns" in w.value for w in at.warning)
    left = at.selectbox(key="_csn_left").value
    opts = at.selectbox(key=f"_csn_k1_{left}_{at.selectbox(key='_csn_right').value}").options
    assert {"CTCT_KEY", "SUBS_KEY"} & set(opts)


@pytest.mark.parametrize("kind", ["orphan", "agreement", "totals"])
def test_every_kind_renders_and_can_be_finished(kind):
    """Same total crashed the deployed page on its first use: its sides are dicts, and the
    summary looked one up as a column name. Each kind is now built through to a rendered
    rule, untested (no warehouse here), with Propose enabled."""
    at = AppTest.from_file(NEW, default_timeout=90)
    at.run()
    at.segmented_control(key="_csn_kind").set_value(kind).run()
    at.selectbox(key="_csn_left").set_value(SUBS).run()
    at.selectbox(key="_csn_right").set_value(CTCT).run()
    assert not at.exception, [e.message for e in at.exception]
    if kind == "orphan":
        at.radio(key="_csn_nullkey").set_value("fail")
    elif kind == "agreement":
        at.selectbox(key=f"_csn_lc_{SUBS}").set_value("SUBS_FRST_NM")
        at.selectbox(key=f"_csn_rc_{CTCT}").set_value("FRST_NM").run()
        at.radio(key="_csn_empty").set_value("differs")
    else:
        at.selectbox(key=f"_csn_l_{SUBS}_agg").set_value("count_distinct").run()
        at.selectbox(key=f"_csn_l_{SUBS}_col").set_value("CTCT_KEY")
        at.selectbox(key=f"_csn_r_{CTCT}_agg").set_value("count")
    at.text_area(key="_csn_why").input("why").run()
    assert not at.exception, [e.message for e in at.exception]
    assert any(c.value.startswith("FROM") for c in at.code)          # the rule rendered
    assert not at.button(key="_csn_propose").disabled


def test_a_permission_error_is_said_in_words():
    raw = ("[INSUFFICIENT_PERMISSIONS] Insufficient privileges: User does not have USE SCHEMA "
           "on Schema 'workspace.udp_brnz_nrt_tech_view'. SQLSTATE: 42501")
    words = cs.test_error_words(raw, [SUBS, CTCT])
    assert words.startswith("The app can’t read subs_c, ctct_c") and "SQLSTATE" not in words
    assert cs.test_error_words("boom", [SUBS]) == "The test could not run: boom"


def test_an_empty_column_listing_is_asked_again_next_time(monkeypatch):
    """Before a read grant the catalog lists nothing; after it, everything. The empty
    answer must not be served from the cache for the hour that a real listing is."""
    from dq_app.data import adapter, local_source
    mon = pd.DataFrame([{"target_table": t, "table_version": 1, "status": "selected",
                         "row_key": ["K"]} for t in (SUBS, CTCT)])
    monkeypatch.setattr(adapter, "get_monitored_tables", lambda: mon)
    adapter._catalog_columns.clear()
    state = {"granted": False}

    def listing(fqn=None):
        if not state["granted"]:
            return pd.DataFrame()
        return pd.DataFrame({"column_name": ["CTCT_KEY", "SUBS_FRST_NM"],
                             "data_type": ["string", "string"]})
    monkeypatch.setattr(local_source, "catalog_columns", listing)
    adapter._empty_columns.clear()
    at = AppTest.from_file(NEW, default_timeout=90)
    at.run()
    assert any("can’t list the columns" in w.value for w in at.warning)
    state["granted"] = True
    adapter._empty_columns.clear()          # the half-minute memo has run out
    at.run()
    assert not any("can’t list the columns" in w.value for w in at.warning)
    adapter._catalog_columns.clear()


def test_an_empty_column_listing_is_not_asked_again_on_every_rerun(monkeypatch):
    """Not caching the empty answer at all had Add tables ask the warehouse again on
    every keystroke and pick in a schema it cannot list. It is held for half a minute."""
    from dq_app.data import adapter, local_source
    adapter._catalog_columns.clear()
    adapter._empty_columns.clear()
    monkeypatch.setattr(adapter, "is_local", lambda: False)    # the memo is for the warehouse
    asked = []
    monkeypatch.setattr(local_source, "catalog_columns",
                        lambda fqn=None: asked.append(fqn) or pd.DataFrame())
    for _ in range(3):
        assert adapter.get_catalog_columns("a.b").empty
    assert asked == ["a.b"]
    monkeypatch.setattr(adapter, "_EMPTY_COLUMNS_TTL", 0.0)
    adapter.get_catalog_columns("a.b")
    assert asked == ["a.b", "a.b"]
    adapter._empty_columns.clear()


def test_propose_stays_disabled_and_says_what_is_missing_until_it_can_be_written():
    """Propose used to accept the click and refuse inside the dialog -- twice for the
    first real proposal (no reason, then fan-out not acknowledged). The page now lists
    what is left and keeps the button disabled until the list is empty."""
    at = AppTest.from_file(NEW, default_timeout=90)
    at.run()
    at.selectbox(key="_csn_left").set_value(SUBS).run()
    at.selectbox(key="_csn_right").set_value(CTCT).run()
    at.segmented_control(key="_csn_kind").set_value("orphan").run()

    def todo() -> str:
        return " ".join(str(m.value) for m in at.markdown if "Before you propose" in str(m.value))

    assert at.button(key="_csn_propose").disabled
    assert "Finish the steps" in todo() and "Say why" in todo()
    at.radio(key="_csn_nullkey").set_value("fail").run()
    assert "Finish the steps" not in todo() and "Say why" in todo()
    assert at.button(key="_csn_propose").disabled
    at.text_area(key="_csn_why").input("Every role belongs to a contact.").run()
    assert todo() == "" and not at.button(key="_csn_propose").disabled

"""The Rules page: CDEs | rules on the one picked | one rule in full.

Redrawn 2026-10-06. What is pinned here is what the redraw could have quietly broken:
every rule still reachable through its element, the rule logic being the runner's
query and not an illustration, a disputed rule not painted as bad data, the values
shown being ones the rule actually flagged, and promotion still asking first.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402

from dq_app.data import adapter  # noqa: E402
from dq_app.domain import rule_sql  # noqa: E402

APP_DIR = Path(__file__).resolve().parents[1]
RULES = "dq_app/ui/pages/rule_registry.py"


def _run(**session):
    at = AppTest.from_file(str(APP_DIR / RULES), default_timeout=90)
    for k, v in session.items():
        at.session_state[k] = v
    at.run()
    assert not at.exception, (session, [e.message for e in at.exception])
    return at


def _body(at) -> str:
    return " ".join(str(m.value) for m in at.markdown)


def _runner():
    path = APP_DIR.parent / "jobs" / "run_checks.py"
    spec = importlib.util.spec_from_file_location("run_checks", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run_checks"] = mod   # a dataclass resolves its annotations through it
    spec.loader.exec_module(mod)
    return mod


def test_rule_logic_is_the_runners_query_for_every_rule():
    """`domain/rule_sql.py` is a copy because only dq-app ships. This is what keeps
    it one: every rule in the registry, against `jobs/run_checks.py` itself — the
    sample query less its LIMIT, and for variance the verdict query."""
    rc = _runner()
    reg = adapter.get_rule_registry_current()
    fields = rc.Rule.__dataclass_fields__
    for _, r in reg.iterrows():
        rule = rc.Rule(**{k: (None if (r[k] != r[k]) else r[k]) for k in fields
                          if k in r.index and k != "sample_columns"})
        got = rule_sql.rule_logic(r)
        assert rule_sql.shape(r) == rc.shape(rule), r["rule_id"]
        if rc.shape(rule) == "variance":
            want = rc.variance_sql(r["target_table"], rule)
        else:
            want = re.sub(r"\nLIMIT\s+\d+$", "",
                          rc.sample_sql(rule, r["target_table"], {}))
        assert got == want, r["rule_id"]


def test_rules_are_listed_by_the_element_they_name():
    """Every rule names its element, so the middle card for an element has to account
    for exactly the rules naming it — and nothing else."""
    reg = adapter.get_rule_registry_current()
    dob = reg[reg["cde_id"] == "CDE_CUST_DOB"]
    at = _run(_rule_el="CDE_CUST_DOB")
    body = _body(at)
    assert "Customer date of birth" in body
    listed = {k.removeprefix("_open_dqrow_rr_") for k in
              (b.key for b in at.button) if k and k.startswith("_open_dqrow_rr_")}
    assert listed == set(dob["rule_id"])


def test_a_rule_asked_for_by_id_opens_on_its_element():
    """A link that knows only the rule — and a test — must land on the right
    element with the rule open, not on the first element with the rule missing."""
    rule_id = "SUBS_IMEI_NOT_NULL"
    at = _run(_rule_pick=rule_id)
    listed = [b.key for b in at.button if b.key and b.key.startswith("_open_dqrow_rr_")]
    assert f"_open_dqrow_rr_{rule_id}" in listed
    assert f"{rule_id} · v" in _body(at)


def test_a_disputed_rule_is_not_painted_as_failing():
    """COH-B's rule breaches its limit, but the CDE register says the rule is wrong.
    Its badge, its figure and its definition all have to say so."""
    at = _run(_rule_pick="SUBS_IMEI_NOT_NULL")
    body = _body(at)
    assert "Scope disputed" in body
    assert "The CDE register disputes this scope" in body
    head = next(str(m.value) for m in at.markdown if "dq-rhead" in str(m.value))
    assert "Failing" not in head


def test_flagged_values_are_values_the_rule_flagged():
    """The mock's "Example values" were illustrations; nobody wrote any, so the page
    shows what the rule actually flagged instead. Every value in that table must be
    in a sampled row of the rule's latest run."""
    rule_id = "CTCT_EML_FMT"
    at = _run(_rule_pick=rule_id)
    frame = next(d.value for d in at.dataframe if "Result" in d.value.columns)
    samples = adapter.get_violation_samples()
    runs = adapter.get_check_runs()
    run_id = runs[runs["rule_id"] == rule_id].sort_values("run_ts")["run_id"].iloc[-1]
    seen = {str(json.loads(raw).get("EML_ID")) for raw in
            samples[(samples["rule_id"] == rule_id) & (samples["run_id"] == run_id)]["sample_row"]}
    assert set(frame["Value"]) <= seen
    assert set(frame["Result"]) == {"Fail"}


def test_turning_a_page_keeps_the_open_tab():
    """The pager turns pages by callback. With a button and `st.rerun()` the run
    stopped before the tabs were drawn and History snapped back to Definition."""
    at = _run()
    next(b for b in at.button if b.key == "_rule_hist").click().run()
    key = next(k for k in at.session_state.filtered_state if k.startswith("_rule_tab_"))
    assert at.session_state[key] == "History"
    next(b for b in at.button if b.key == "_rule_next").click().run()
    assert not at.exception
    assert at.session_state[key] == "History"
    assert at.session_state["_rule_cde_page"] == 1


def test_the_cde_search_finds_an_element_by_its_rules():
    """The severity filter and the registry-wide search went with the redraw. What
    replaces the search is that the CDE box matches an element's columns and the
    rules on it, so a rule id still finds its way in."""
    at = _run()
    next(t for t in at.text_input if t.key == "_rule_cde_search").input("SUBS_IMEI_NOT").run()
    assert not at.exception
    els = [b.key for b in at.button if b.key and b.key.startswith("_open_dqrow_rc_")]
    reg = adapter.get_rule_registry_current()
    cde = reg.loc[reg["rule_id"] == "SUBS_IMEI_NOT_NULL", "cde_id"].iloc[0]
    assert els == [f"_open_dqrow_rc_{cde}"]
    next(t for t in at.text_input if t.key == "_rule_cde_search").input("zzz").run()
    assert "No element matches." in _body(at)


def test_promoting_asks_first_and_writes_only_on_confirm():
    """Every write button opens a confirmation first. Opening the dialog must
    append nothing; confirming appends exactly one version."""
    reg = adapter.get_rule_registry_current()
    rule_id = sorted(reg[reg["status"] == "shadow"]["rule_id"])[0]
    at = _run(_rule_pick=rule_id)
    next(b for b in at.button if b.key == "_promote_open").click().run()
    assert not at.exception
    assert "_pending_rule_versions" not in at.session_state \
        or not at.session_state["_pending_rule_versions"]
    assert "Appends version" in _body(at)

    next(b for b in at.button if b.key == "_promote_yes").click().run()
    assert not at.exception, [e.message for e in at.exception]
    written = at.session_state["_pending_rule_versions"]
    assert len(written) == 1
    assert written[0]["rule_id"] == rule_id and written[0]["status"] == "active"

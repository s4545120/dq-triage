"""CDE onboarding: proposing, deciding and reading changes to the element register.

The fixture carries no element proposals, so the page tests that need some write a copy
of it with a `config.cde_proposal` / `config.cde_review` parquet and point the app at the
copy with DQ_FIXTURE_DIR, as test_onboarding.py does. The shipped fixture is never edited.
"""

from __future__ import annotations

import importlib.util
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from dq_app.domain import elements
from dq_app.domain.onboarding import OnboardingRejected

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "out"
APP_DIR = Path(__file__).resolve().parents[1]
JOB_ELEMENTS = APP_DIR.parent / "onboarding" / "elements.py"
PAGE = "dq_app/ui/pages/elements.py"
ME = "m.okonkwo@example.com"          # the local stand-in identity
OTHER = "p.nguyen@example.com"


@pytest.fixture(autouse=True)
def _forget_the_fixture_copy():
    yield
    import streamlit as st
    st.cache_data.clear()


@pytest.fixture(scope="module")
def registry():
    if not FIXTURE_DIR.is_dir():
        pytest.skip("fixture not built")
    return pd.read_parquet(FIXTURE_DIR / "config.cde_registry.parquet")


def _latest(registry, cde_id):
    return elements.latest_version(registry, cde_id)


ATTRS = dict(cde_name="Marketing consent", business_term=None, data_class="other",
             definition="Whether the customer agreed to marketing contact.",
             expected_signature=None, criticality="high", pii=False, regulatory_basis="Spam Act",
             tolerance_pct=0.5, business_domain="Customer", owner_group="dq-stewards")


def _empty_state():
    return elements.proposal_state(pd.DataFrame(columns=elements.PROPOSAL_COLUMNS),
                                   pd.DataFrame(columns=elements.REVIEW_COLUMNS),
                                   pd.DataFrame())


# --- Pure ---------------------------------------------------------------------------------

def test_a_suggested_id_is_upper_snake_and_never_one_already_taken():
    assert elements.suggest_id("Marketing consent", set()) == "CDE_MARKETING_CONSENT"
    assert elements.suggest_id("Marketing consent", {"CDE_MARKETING_CONSENT"}) == \
        "CDE_MARKETING_CONSENT_2"
    assert elements.ID_SHAPE.match(elements.suggest_id("  é?! ", set()))


def test_a_posix_class_is_refused_because_spark_reads_it_as_letters():
    assert "POSIX" in elements.signature_problem("^[[:alpha:]]+$")
    assert "valid" in elements.signature_problem("^(unclosed")
    assert elements.signature_problem(r"^\d{7}$") is None
    assert elements.signature_problem(None) is None


def test_a_registration_needs_a_reason_a_name_a_definition_and_a_new_id(registry):
    ok = dict(registry=registry, state=_empty_state(), based_on_version=None)
    elements.validate_proposal("register", "CDE_MARKETING_CONSENT", ATTRS, "Regulated.", **ok)
    with pytest.raises(OnboardingRejected, match="Say why"):
        elements.validate_proposal("register", "CDE_MARKETING_CONSENT", ATTRS, " ", **ok)
    with pytest.raises(OnboardingRejected, match="name"):
        elements.validate_proposal("register", "CDE_MARKETING_CONSENT",
                                   {**ATTRS, "cde_name": ""}, "x", **ok)
    with pytest.raises(OnboardingRejected, match="means"):
        elements.validate_proposal("register", "CDE_MARKETING_CONSENT",
                                   {**ATTRS, "definition": None}, "x", **ok)
    with pytest.raises(OnboardingRejected, match="never reused"):
        elements.validate_proposal("register", "CDE_CUST_EMAIL", ATTRS, "x", **ok)
    # Retired ids too: the vulnerable-customer flag was retired on 2026-10-01.
    with pytest.raises(OnboardingRejected, match="never reused"):
        elements.validate_proposal("register", "CDE_VULNERABLE_CUSTOMER", ATTRS, "x", **ok)
    with pytest.raises(OnboardingRejected, match="CDE_"):
        elements.validate_proposal("register", "marketing", ATTRS, "x", **ok)
    with pytest.raises(OnboardingRejected, match="Tolerance"):
        elements.validate_proposal("register", "CDE_MARKETING_CONSENT",
                                   {**ATTRS, "tolerance_pct": 150.0}, "x", **ok)


def test_one_change_at_a_time_per_element(registry):
    el = _latest(registry, "CDE_CUST_EMAIL")
    waiting = pd.DataFrame([dict(proposal_id="p1", proposed_at=datetime(2026, 10, 8),
                                 cde_id="CDE_CUST_EMAIL", change="retire",
                                 based_on_version=int(el["cde_version"]), proposed_by=OTHER,
                                 reason="r")])
    state = elements.proposal_state(waiting, pd.DataFrame(columns=elements.REVIEW_COLUMNS),
                                    registry)
    with pytest.raises(OnboardingRejected, match="already has a change waiting"):
        elements.validate_proposal("amend", "CDE_CUST_EMAIL",
                                   {**elements.attrs_of(el), "tolerance_pct": 1.0}, "x",
                                   registry=registry, state=state,
                                   based_on_version=int(el["cde_version"]))


def test_an_amendment_must_change_something_and_cannot_reclass_a_bound_element(registry):
    el = _latest(registry, "CDE_CUST_EMAIL")
    kw = dict(registry=registry, state=_empty_state(), based_on_version=int(el["cde_version"]))
    with pytest.raises(OnboardingRejected, match="changes nothing"):
        elements.validate_proposal("amend", "CDE_CUST_EMAIL", elements.attrs_of(el), "x", **kw)
    with pytest.raises(OnboardingRejected, match="data class"):
        elements.validate_proposal("amend", "CDE_CUST_EMAIL",
                                   {**elements.attrs_of(el), "data_class": "other"}, "x", **kw)
    elements.validate_proposal("amend", "CDE_CUST_EMAIL",
                               {**elements.attrs_of(el), "tolerance_pct": 1.0}, "x", **kw)


def test_only_a_second_person_approves():
    mine = {"proposed_by": ME}
    with pytest.raises(OnboardingRejected, match="second person"):
        elements.validate_review(mine, ME.upper(), "approved", None)
    elements.validate_review(mine, ME, "rejected", "withdrawn")
    elements.validate_review(mine, OTHER, "approved", None)
    elements.validate_review(mine, ME, "approved", None, allow_self=True)
    with pytest.raises(OnboardingRejected, match="why"):
        elements.validate_review(mine, OTHER, "rejected", "")


def test_state_reads_applied_off_the_register_marker(registry):
    props = pd.DataFrame([
        dict(proposal_id=pid, proposed_at=datetime(2026, 10, 8, h), cde_id="CDE_X",
             change="register", proposed_by=ME, reason="r")
        for pid, h in (("p-open", 1), ("p-ok", 2), ("p-done", 3), ("p-no", 4))])
    revs = pd.DataFrame([
        dict(proposal_id="p-ok", decision="approved", reviewed_by=OTHER,
             reviewed_at=datetime(2026, 10, 8, 5), reason=None),
        dict(proposal_id="p-done", decision="approved", reviewed_by=OTHER,
             reviewed_at=datetime(2026, 10, 8, 5), reason=None),
        dict(proposal_id="p-no", decision="rejected", reviewed_by=OTHER,
             reviewed_at=datetime(2026, 10, 8, 5), reason="no")])
    reg = pd.concat([registry, pd.DataFrame([dict(
        cde_id="CDE_X", cde_version=1, status="proposed", bindings=[],
        note=elements_marker("p-done") + " Registered: r")])], ignore_index=True)
    st = elements.proposal_state(props, revs, reg).set_index("proposal_id")
    assert st["state"].to_dict() == {"p-no": "rejected", "p-done": "applied",
                                     "p-ok": "approved", "p-open": "open"}
    assert st.loc["p-done", "applied_version"] == 1


def elements_marker(pid):
    return _job().marker(pid)


def _job():
    spec = importlib.util.spec_from_file_location("job_elements", JOB_ELEMENTS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_app_and_the_job_refuse_the_same_proposals(registry):
    """`elements.refusal` is the app's copy of the job's check. Same verdict on every
    case, or a reviewer is told an approval will apply when the job will refuse it."""
    job = _job()
    assert job.ATTRS == elements.ATTRS
    el = _latest(registry, "CDE_CUST_EMAIL")
    v = int(el["cde_version"])
    base = elements.attrs_of(el)
    cases = [
        dict(change="register", cde_id="CDE_NEW", based_on_version=None, **ATTRS),
        dict(change="register", cde_id="CDE_CUST_EMAIL", based_on_version=None, **ATTRS),
        dict(change="amend", cde_id="CDE_CUST_EMAIL", based_on_version=v,
             **{**base, "tolerance_pct": 3.0}),
        dict(change="amend", cde_id="CDE_CUST_EMAIL", based_on_version=v, **base),
        dict(change="amend", cde_id="CDE_CUST_EMAIL", based_on_version=v,
             **{**base, "data_class": "other"}),
        dict(change="amend", cde_id="CDE_CUST_EMAIL", based_on_version=v - 1,
             **{**base, "tolerance_pct": 3.0}),
        dict(change="retire", cde_id="CDE_CUST_EMAIL", based_on_version=v),
        dict(change="retire", cde_id="CDE_VULNERABLE_CUSTOMER", based_on_version=1),
        dict(change="retire", cde_id="CDE_NOPE", based_on_version=1),
    ]
    for c in cases:
        for reviewer, mark in ((OTHER, None), (ME, None), (ME, "[second approver waived] x")):
            p = {**c, "proposed_by": ME, "reviewed_by": reviewer, "review_reason": mark}
            versions = elements.versions_of(registry, c["cde_id"])
            assert (job.refusal(p, versions) is None) == \
                (elements.refusal(p, versions) is None), (c, reviewer, mark)


def test_lowering_a_tolerance_lists_the_checks_left_looser_than_it():
    rules = pd.DataFrame([
        dict(rule_id="A", cde_id="CDE_X", status="active", fail_threshold_pct=0.0),
        dict(rule_id="B", cde_id="CDE_X", status="active", fail_threshold_pct=2.0),
        dict(rule_id="C", cde_id="CDE_X", status="retired", fail_threshold_pct=9.0),
        dict(rule_id="D", cde_id="CDE_Y", status="active", fail_threshold_pct=9.0)])
    assert elements.over_tolerance(rules, "CDE_X", 1.0) == ["B"]
    assert elements.over_tolerance(rules, "CDE_X", None) == []


def test_retiring_names_what_goes_with_it(registry):
    rules = pd.read_parquet(FIXTURE_DIR / "config.rule_registry.parquet")
    current = rules.sort_values("rule_version").groupby("rule_id").tail(1)
    cohorts = pd.read_parquet(FIXTURE_DIR / "results.cohort.parquet")
    imp = elements.retire_impact("CDE_CUST_EMAIL", _latest(registry, "CDE_CUST_EMAIL"),
                                 current, cohorts)
    assert imp["bindings"] and imp["active"]
    assert imp["problems"], "COH-A carries the email checks"


# --- Through the page ---------------------------------------------------------------------

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402


def build(tmp: Path, proposals: list[dict] = (), reviews: list[dict] = ()) -> Path:
    if not FIXTURE_DIR.is_dir():
        pytest.skip("fixture not built")
    out = tmp / "out"
    shutil.copytree(FIXTURE_DIR, out)
    full = [{c: p.get(c) for c in elements.PROPOSAL_COLUMNS} for p in proposals]
    if full:
        pd.DataFrame(full).to_parquet(out / "config.cde_proposal.parquet", index=False)
    if reviews:
        pd.DataFrame(list(reviews)).to_parquet(out / "config.cde_review.parquet", index=False)
    return out


@pytest.fixture
def page(monkeypatch):
    def _open(fixture_dir: Path | None = None, **session):
        import streamlit as st
        st.cache_data.clear()
        if fixture_dir:
            monkeypatch.setenv("DQ_FIXTURE_DIR", str(fixture_dir))
        at = AppTest.from_file(str(APP_DIR / PAGE), default_timeout=90)
        for k, v in session.items():
            at.session_state[k] = v
        at.run()
        assert not at.exception, [e.message for e in at.exception]
        return at
    return _open


def _text(at) -> str:
    return (" ".join(str(m.value) for m in at.markdown) + " "
            + " ".join(str(c.value) for c in at.caption))


def _confirm(at, name: str):
    at.button(key=f"_onb_ask_yes_{name}").click().run()
    assert not at.exception, [e.message for e in at.exception]


def _pending(at, kind: str) -> list[dict]:
    key = {"p": "_pending_cde_proposals", "r": "_pending_cde_reviews"}[kind]
    return list(at.session_state[key]) if key in at.session_state else []


def test_the_page_lists_the_register_and_how_registration_works(page):
    at = page()
    body = _text(at)
    assert at.title[0].value == "Critical data elements" and "Elements · 19" in body
    assert "A second person approves" in body
    assert "Customer email address" in body


def test_proposing_an_element_writes_one_proposal_and_nothing_on_the_register(page):
    at = page()
    at.button(key="el_new").click().run()
    at.text_input(key="_el_f_new_name").set_value("Marketing consent")
    at.text_area(key="_el_f_new_def").set_value("Whether the customer agreed to marketing.")
    at.text_area(key="_el_new_reason").set_value("Spam Act evidence.")
    at.button(key="el_new_go").click().run()
    assert not _pending(at, "p"), "nothing is written before the confirmation"
    _confirm(at, "el_propose")
    [p] = _pending(at, "p")
    assert (p["cde_id"], p["change"], p["proposed_by"], p["based_on_version"]) == \
        ("CDE_MARKETING_CONSENT", "register", ME, None)
    assert p["cde_name"] == "Marketing consent" and p["reason"] == "Spam Act evidence."
    assert "Changes awaiting review · 1" in _text(at)
    # Your own proposal cannot be approved by you.
    assert at.button(key=f"el_rv_ok_{p['proposal_id']}").disabled


def test_amending_carries_the_version_it_was_written_against(page, registry):
    el = _latest(registry, "CDE_CUST_EMAIL")
    v = int(el["cde_version"])
    at = page(_el_pick="CDE_CUST_EMAIL", _el_mode="amend")
    at.number_input(key=f"_el_f_amend_CDE_CUST_EMAIL_{v}_tol").set_value(1.0).run()
    at.text_area(key="_el_amend_reason_CDE_CUST_EMAIL").set_value("Business accepts 1%.")
    at.button(key="el_amend_go").click().run()
    _confirm(at, "el_propose")
    [p] = _pending(at, "p")
    assert (p["change"], p["based_on_version"], p["tolerance_pct"]) == ("amend", v, 1.0)
    assert p["cde_name"] == el["cde_name"], "an amendment carries the whole attribute set"


def test_retiring_shows_what_goes_with_it_before_anything_is_written(page):
    at = page(_el_pick="CDE_CUST_EMAIL", _el_mode="retire")
    body = _text(at)
    assert "leave coverage" in body and "retired version" in body and "as history" in body
    at.button(key="el_retire_go").click().run()
    at.button(key="_onb_ask_yes_el_propose").click().run()
    assert "Say why" in " ".join(str(e.value) for e in at.error)
    assert not _pending(at, "p")


def test_a_reviewer_approves_someone_elses_and_cannot_reject_without_a_reason(page, tmp_path,
                                                                              registry):
    el = _latest(registry, "CDE_CUST_EMAIL")
    d = build(tmp_path, proposals=[
        dict(proposal_id="p-theirs", proposed_at=datetime(2026, 10, 8, 9), cde_id="CDE_NEW_ONE",
             change="register", proposed_by=OTHER, reason="Needed.", **ATTRS),
        dict(proposal_id="p-mine", proposed_at=datetime(2026, 10, 8, 10),
             cde_id="CDE_CUST_EMAIL", change="amend", based_on_version=int(el["cde_version"]),
             proposed_by=ME, reason="Looser.", **{**elements.attrs_of(el), "tolerance_pct": 2.0})])
    at = page(d)
    body = _text(at)
    assert "Changes awaiting review · 2" in body and "Waiting on you" in body
    assert at.button(key="el_rv_ok_p-mine").disabled
    assert not at.button(key="el_rv_ok_p-theirs").disabled

    at.button(key="el_rv_no_p-theirs").click().run()
    _confirm_refused = at.button(key="_onb_ask_yes_el_review").click().run()
    assert "Say why" in " ".join(str(e.value) for e in _confirm_refused.error)
    assert not _pending(at, "r")
    at.button(key="_onb_ask_no_el_review").click().run()

    at.button(key="el_rv_ok_p-theirs").click().run()
    _confirm(at, "el_review")
    [r] = _pending(at, "r")
    assert (r["proposal_id"], r["decision"], r["reviewed_by"]) == ("p-theirs", "approved", ME)
    assert "Approved · awaiting the job" in _text(at)


def test_a_stale_amendment_is_flagged_before_anyone_approves_it(page, tmp_path, registry):
    el = _latest(registry, "CDE_CUST_EMAIL")
    d = build(tmp_path, proposals=[dict(
        proposal_id="p-stale", proposed_at=datetime(2026, 10, 8), cde_id="CDE_CUST_EMAIL",
        change="amend", based_on_version=int(el["cde_version"]) - 1, proposed_by=OTHER,
        reason="Old view.", **{**elements.attrs_of(el), "tolerance_pct": 4.0})])
    at = page(d)
    assert "will not apply this" in _text(at)


def test_the_adapter_refuses_the_authors_approval_even_without_the_page(tmp_path, monkeypatch):
    d = build(tmp_path, proposals=[dict(
        proposal_id="p-mine", proposed_at=datetime(2026, 10, 8), cde_id="CDE_NEW_ONE",
        change="register", proposed_by=ME, reason="Needed.", **ATTRS)])

    def script():
        import sys
        import streamlit as st
        sys.path.insert(0, st.session_state["_app_dir"])
        from dq_app.data import adapter
        try:
            adapter.review_element("p-mine", "approved")
            st.session_state["out"] = "written"
        except adapter.OnboardingRejected as exc:
            st.session_state["out"] = str(exc)

    import streamlit as st
    st.cache_data.clear()
    monkeypatch.setenv("DQ_FIXTURE_DIR", str(d))
    at = AppTest.from_function(script, default_timeout=90)
    at.session_state["_app_dir"] = str(APP_DIR)
    at.run()
    assert "second person" in at.session_state["out"]


def test_a_durable_proposal_without_a_platform_identity_is_refused(monkeypatch):
    from dq_app.data import adapter
    monkeypatch.setattr(adapter, "writes_are_durable", lambda: True)
    with pytest.raises(OnboardingRejected, match="platform identity"):
        adapter.propose_element("register", "CDE_X_Y", ATTRS, "why")


# --- Which checks a bound column gets ------------------------------------------------------

def _job_templates():
    import sys
    sys.path.insert(0, str(APP_DIR.parent / "onboarding"))
    import templates
    return templates


def test_the_apps_format_flags_are_the_jobs():
    """`elements.FORMAT_TEMPLATES` is the app's copy of `checks_format`. If they drift,
    the page promises a pattern check the generator will not write, or hides one it will."""
    job = _job_templates()
    assert elements.FORMAT_TEMPLATES == {tp.template_id for tp in job.TEMPLATES
                                         if tp.checks_format}
    assert elements.PATTERN_TEMPLATE in job.BY_ID and job.ANY_CLASS == elements.ANY_CLASS
    assert elements.CONFIRMED_SIGNATURES == job.CONFIRMED_SIGNATURES


def test_the_page_names_the_same_checks_the_generator_writes():
    job = _job_templates()
    # As the table holds them after an upgrade: a superseded version beside each v2.
    rows = pd.DataFrame([dict(template_id=tp.template_id, template_version=v,
                              data_class=tp.data_class, title=tp.title)
                         for tp in job.TEMPLATES for v in range(1, tp.version + 1)])
    for cls, sig, cid in [("date_of_birth", r"^\d{4}$", "CDE_CUST_DOB"),
                          ("date_of_birth", None, "CDE_CUST_DOB"),
                          ("email_address", "x", "CDE_CUST_EMAIL"),
                          ("national_id", r"^\d{7}$", "CDE_CUST_IDENT_DOC"),
                          ("other", None, "CDE_NETWORK_TECH")]:
        app = list(elements.templates_for(rows, cls, sig, cid)["template_id"])
        assert app == [tp.template_id for tp in job.for_class(cls, sig, cid)], (cls, sig)
    words = elements.check_words(elements.templates_for(rows, "date_of_birth", r"^\d{4}$",
                                                        "CDE_CUST_DOB"))
    assert "is a date in the column's format" in words
    assert "matches its expected pattern" not in words


def test_a_schema_without_the_tables_or_the_grants_says_so_and_writes_nothing():
    from dq_app.data import adapter

    def missing(_row):
        raise RuntimeError("[TABLE_OR_VIEW_NOT_FOUND] dq_config_cde_proposal cannot be found")

    def denied(_row):
        raise RuntimeError("[INSUFFICIENT_PERMISSIONS] User does not have MODIFY on Table")

    with pytest.raises(OnboardingRejected, match="not installed"):
        adapter._element_write(missing, {})
    with pytest.raises(OnboardingRejected, match="no grant"):
        adapter._element_write(denied, {})
    with pytest.raises(ValueError):
        adapter._element_write(lambda _r: (_ for _ in ()).throw(ValueError("other")), {})

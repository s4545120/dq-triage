"""Onboarding: the derived stage, and promotion through the page.

The fixture onboards nothing, so these tests build a copy of it with one table part
way through onboarding -- `prod.sales.crm_lead`, its email column bound to the email
element, two shadow checks on it and one shadow run -- and point the app at the copy
with DQ_FIXTURE_DIR. The shipped fixture is never edited.
"""

from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from dq_app.domain import onboarding

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "out"
APP_DIR = Path(__file__).resolve().parents[1]
PAGE = "dq_app/ui/pages/onboarding.py"
TABLE = "dq_app/ui/pages/onboarding_table.py"
LEAD = "prod.sales.crm_lead"
RUN_TS = datetime(2026, 10, 5, 3, 0)


@pytest.fixture(autouse=True)
def _forget_the_fixture_copy():
    """Streamlit's data cache outlives a test, and its keys do not include the fixture
    folder. Left behind, this file's synthetic run -- dated after the fixture's last --
    became "the latest run" for every scorecard test that followed."""
    yield
    import streamlit as st
    st.cache_data.clear()


# --- The stage, pure ------------------------------------------------------------------

@pytest.mark.parametrize("counts, stage", [
    ((0, 0, 0, 0, 0), "awaiting discovery"),
    ((3, 0, 0, 0, 0), "bindings awaiting review"),
    ((1, 4, 9, 0, 2), "bindings awaiting review"),    # a new proposal pauses even a run table
    ((0, 4, 0, 0, 0), "awaiting rule generation"),
    ((0, 4, 9, 0, 0), "shadow, not yet run"),
    ((0, 4, 9, 0, 1), "shadow, awaiting promotion"),
    ((0, 4, 0, 9, 3), "active"),
    ((0, 4, 2, 9, 3), "active"),                      # a later template's shadow checks
])
def test_stage_follows_what_exists(counts, stage):
    assert onboarding.stage_of(*counts) == stage


def test_every_stage_has_a_place_in_the_sequence():
    assert [s for s, _, _ in onboarding.STAGES] == list(onboarding.STAGE_INDEX)


# --- A fixture copy with one table being onboarded --------------------------------------

def _read(d: Path, name: str) -> pd.DataFrame:
    return pd.read_parquet(d / f"{name}.parquet")


def _write(d: Path, name: str, df: pd.DataFrame) -> None:
    df.to_parquet(d / f"{name}.parquet", index=False)


def build(tmp: Path, *, open_proposal: bool = False, measured: bool = True,
          second_column: bool = False) -> Path:
    if not FIXTURE_DIR.is_dir():
        pytest.skip("fixture not built")
    out = tmp / "out"
    shutil.copytree(FIXTURE_DIR, out)

    _write(out, "config.monitored_table", pd.DataFrame([dict(
        target_table=LEAD, table_version=1, table_code="LEAD", row_key=["LEAD_ID"],
        owner_group="dq-stewards-sales", business_domain="Sales",
        schedule_group="daily_0300", scan_mode="full", status="selected",
        effective_from=RUN_TS, selected_by="steward@example.com", note="test")]))

    # Bind EMAIL to the email element: a new version carrying one more binding.
    cde = _read(out, "config.cde_registry")
    cde["bindings"] = cde["bindings"].map(list)
    latest = cde[cde["cde_id"] == "CDE_CUST_EMAIL"].sort_values("cde_version").iloc[-1].to_dict()
    latest["cde_version"] = int(latest["cde_version"]) + 1
    latest["effective_from"] = RUN_TS
    latest["bindings"] = list(latest["bindings"]) + [dict(
        target_table=LEAD, target_column="EMAIL", populated_when=None,
        expected_scope_filter=None, binding_status="bound",
        discovered_by="value_signature", confidence=0.974)]
    extra_cde = []
    if second_column:
        # HOME_PHONE bound to the landline element through an approved proposal: the
        # column a test excludes at promotion.
        land = cde[cde["cde_id"] == "CDE_CUST_LANDLINE"].sort_values("cde_version").iloc[-1].to_dict()
        land["cde_version"] = int(land["cde_version"]) + 1
        land["effective_from"] = RUN_TS
        land["bindings"] = list(land["bindings"]) + [dict(
            target_table=LEAD, target_column="HOME_PHONE", populated_when=None,
            expected_scope_filter=None, binding_status="bound",
            discovered_by="name_match", confidence=0.6)]
        extra_cde.append(land)
    _write(out, "config.cde_registry", pd.concat([cde, pd.DataFrame([latest] + extra_cde)],
                                                   ignore_index=True))

    props = [dict(proposal_id="p-email", proposed_at=RUN_TS, target_table=LEAD,
                  target_column="EMAIL", cde_id="CDE_CUST_EMAIL", method="value_signature",
                  confidence=0.974, evidence="97.4% match", proposed_by="job")]
    revs = [dict(proposal_id="p-email", decision="approved", reviewed_by="owner@example.com",
                 reviewed_at=RUN_TS, reason="checked")]
    if open_proposal:
        props.append(dict(proposal_id="p-phone", proposed_at=RUN_TS, target_table=LEAD,
                          target_column="HOME_PHONE", cde_id="CDE_CUST_LANDLINE",
                          method="value_signature", confidence=0.993, evidence="99.3%",
                          proposed_by="job"))
    if second_column:
        props.append(dict(proposal_id="p-home", proposed_at=RUN_TS, target_table=LEAD,
                          target_column="HOME_PHONE", cde_id="CDE_CUST_LANDLINE",
                          method="name_match", confidence=0.6, evidence="column name",
                          proposed_by="job:onboard-discover"))
        revs.append(dict(proposal_id="p-home", decision="approved",
                         reviewed_by="owner@example.com", reviewed_at=RUN_TS, reason=None))
    _write(out, "config.binding_proposal", pd.DataFrame(props))
    _write(out, "config.binding_review", pd.DataFrame(revs))

    # Two shadow checks generated on the binding.
    reg = _read(out, "config.rule_registry")
    base = reg[reg["rule_id"] == "CTCT_EML_FMT"].sort_values("rule_version").iloc[-1].to_dict()
    rules = []
    checks = [("LEAD_EMAIL_FMT", "Customer email address is a well-formed address", "EMAIL",
               "CDE_CUST_EMAIL"),
              ("LEAD_EMAIL_NOT_NULL", "Customer email address is present", "EMAIL",
               "CDE_CUST_EMAIL")]
    if second_column:
        checks.append(("LEAD_HOME_PHONE_FMT", "Landline is a valid number", "HOME_PHONE",
                       "CDE_CUST_LANDLINE"))
    for rid, name, col, cde_id in checks:
        r = dict(base)
        r.update(rule_id=rid, rule_version=1, rule_name=name, target_table=LEAD,
                 target_column=col, cde_id=cde_id, status="shadow", fail_threshold_pct=0.5,
                 effective_from=RUN_TS, created_at=RUN_TS, created_by="job:onboard-generate",
                 promoted_by=None, promoted_at=None, note="generated")
        rules.append(r)
    _write(out, "config.rule_registry", pd.concat([reg, pd.DataFrame(rules)],
                                                    ignore_index=True))

    if measured:
        runs = _read(out, "results.check_run")
        row = runs.iloc[0].to_dict()
        new = []
        measures = [("LEAD_EMAIL_FMT", 25, 980, "EMAIL"), ("LEAD_EMAIL_NOT_NULL", 0, 1000, "EMAIL")]
        if second_column:
            measures.append(("LEAD_HOME_PHONE_FMT", 600, 1000, "HOME_PHONE"))
        for rid, v, n, col in measures:
            r = dict(row)
            r.update(result_id=f"res-{rid}", run_id="run-lead-1", run_ts=RUN_TS, rule_id=rid,
                     rule_version=1, target_table=LEAD, target_column=col,
                     rows_scanned=n, violation_count=v, violation_pct=round(100 * v / n, 4),
                     threshold_pct=0.5, status="skipped", message="shadow rule")
            new.append(r)
        _write(out, "results.check_run", pd.concat([runs, pd.DataFrame(new)],
                                                     ignore_index=True))
    return out


def test_derive_status_reads_the_copy(tmp_path):
    d = build(tmp_path)
    from dq_app.domain import coverage  # noqa: F401 -- bound_columns via onboarding
    reg = _read(d, "config.rule_registry").sort_values(["rule_id", "rule_version"])
    current = reg.groupby("rule_id", as_index=False).tail(1)
    s = onboarding.derive_status(
        _read(d, "config.monitored_table"), _read(d, "config.binding_proposal"),
        _read(d, "config.binding_review"), _read(d, "config.cde_registry"), current,
        _read(d, "results.check_run"))
    assert len(s) == 1
    row = s.iloc[0]
    assert (row["columns_bound"], row["rules_shadow"], row["rules_active"], row["runs"]) == \
        (1, 2, 0, 1)
    assert row["stage"] == "shadow, awaiting promotion"

    ev = onboarding.shadow_evidence(current, _read(d, "results.check_run"), LEAD)
    verdict = dict(zip(ev["rule_id"], ev["would_breach"]))
    assert verdict == {"LEAD_EMAIL_FMT": True, "LEAD_EMAIL_NOT_NULL": False}


# --- Through the page ------------------------------------------------------------------

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402


@pytest.fixture
def page(monkeypatch):
    """Open a page against a fixture copy. The list page by default; `table=True` opens
    the per-table page for LEAD, which is where review and promotion live."""
    def _open(fixture_dir: Path | None = None, table: bool = False, **session):
        import streamlit as st
        st.cache_data.clear()
        if fixture_dir:
            monkeypatch.setenv("DQ_FIXTURE_DIR", str(fixture_dir))
        if table:
            session.setdefault("_onb_pick", "LEAD")
        at = AppTest.from_file(str(APP_DIR / (TABLE if table else PAGE)), default_timeout=90)
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
    """Click Confirm in the dialog a write button opened."""
    at.button(key=f"_onb_ask_yes_{name}").click().run()


def _promote_button(at):
    return [b for b in at.button if str(b.label).startswith("Promote ")]


def test_the_fixture_onboards_nothing_and_the_page_says_so(page):
    at = page()
    body = _text(at)
    assert "No tables are selected yet" in body
    assert "Selected" in body and "Waiting on you" in body and "Active" in body


def test_the_list_shows_each_table_with_its_step_and_the_four_figures(page, tmp_path):
    at = page(build(tmp_path))
    body = _text(at)
    assert "crm_lead" in body and "prod.sales" in body
    assert "Ready to promote" in body
    assert "2 in shadow" in body
    assert "2 checks measured, none raising" in body
    assert "How a table gets checked" in body


def test_the_table_page_shows_the_stage_bindings_and_shadow_verdicts(page, tmp_path):
    at = page(build(tmp_path), table=True)
    body = _text(at)
    assert "crm_lead" in body
    assert "Ready to promote" in body and "Step 5 of 6" in body
    assert "Waiting on you: promote the checks" in body
    assert "approved by owner@example.com" in body
    assert "would breach" in body and "would pass" in body
    assert ">1</b> would breach" in body
    assert [str(b.label) for b in _promote_button(at)] == ["Promote 2 checks"]


def test_promoting_appends_an_active_version_of_every_shadow_check(page, tmp_path):
    at = page(build(tmp_path), table=True)
    _promote_button(at)[0].click().run()
    assert "_pending_rule_versions" not in at.session_state, "wrote before confirming"
    body = _text(at)
    assert "become active" in body and "1 would breach" in body
    _confirm(at, "promote")
    assert not at.exception, [e.message for e in at.exception]

    versions = at.session_state["_pending_rule_versions"]
    assert sorted(v["rule_id"] for v in versions) == ["LEAD_EMAIL_FMT", "LEAD_EMAIL_NOT_NULL"]
    for v in versions:
        assert v["status"] == "active" and v["rule_version"] == 2
        assert v["promoted_by"] and v["promoted_by"] == v["created_by"]
        assert "shadow review of crm_lead" in v["note"]

    # The stage is derived, so the promotion moved it with no other write.
    body = _text(at)
    assert "Their breaches reach Triage" in body
    assert not _promote_button(at)
    assert "All 2 checks are active" in body
    assert "Checks active" in body


def test_an_open_proposal_holds_promotion_back(page, tmp_path):
    at = page(build(tmp_path, open_proposal=True), table=True)
    body = _text(at)
    assert "Bindings to review" in body and "Proposed bindings · 1" in body
    assert "Finish reviewing the bindings first" in body
    assert not _promote_button(at)


def test_unmeasured_checks_are_not_offered_for_promotion(page, tmp_path):
    at = page(build(tmp_path, measured=False), table=True)
    body = _text(at)
    assert "Checks not yet measured" in body
    assert "have not been measured yet" in body
    assert not _promote_button(at)


# --- The identity guard ------------------------------------------------------------------

def test_a_durable_promotion_without_a_platform_identity_is_refused(monkeypatch):
    """From a laptop against Unity Catalog, a promotion would be signed with a demo
    persona. The register has CHECK constraints for this; the rule registry relies on
    this guard."""
    from dq_app.data import adapter, identity
    persona = identity.Identity("m.okonkwo@example.com", "M. Okonkwo", "local_standin")
    monkeypatch.setattr(adapter, "writes_are_durable", lambda: True)
    with pytest.raises(adapter.WriteRejected, match="no platform identity"):
        adapter._require_platform_identity(persona, "Promoting a rule")

    platform = identity.Identity("steward@example.com", "Steward", "obo_user")
    adapter._require_platform_identity(platform, "Promoting a rule")

    monkeypatch.setattr(adapter, "writes_are_durable", lambda: False)
    adapter._require_platform_identity(persona, "Promoting a rule")   # session-only demo


# --- Selecting, suggesting, deciding -------------------------------------------------------

ADD = "dq_app/ui/pages/onboarding_add.py"
NEW = "samples.bakehouse.sales_customers"


def with_catalog(d: Path, *, readable: bool = True, size: float = 20055.0) -> Path:
    """A Unity Catalog the local source can browse: one schema, two tables."""
    _write(d, "catalog.tables", pd.DataFrame([
        dict(table_catalog="samples", table_schema="bakehouse", table_name="sales_customers",
             table_type="MANAGED", table_owner="samples", size_bytes=size, readable=readable),
        dict(table_catalog="samples", table_schema="bakehouse", table_name="sales_suppliers",
             table_type="MANAGED", table_owner="samples", size_bytes=4000.0, readable=True),
    ]))
    cols = ["customerID", "first_name", "last_name", "email_address", "phone_number"]
    _write(d, "catalog.columns", pd.DataFrame([
        dict(table_catalog="samples", table_schema="bakehouse", table_name="sales_customers",
             column_name=c, data_type="STRING", ordinal_position=i, tag_cde=None)
        for i, c in enumerate(cols)]))
    return d


def _open_add(page, d):
    """The Add tables page with the catalog's one schema open and the table chosen.
    The caller has already pointed DQ_FIXTURE_DIR at `d` with monkeypatch."""
    import streamlit as st
    st.cache_data.clear()
    session = {"_add_cat": "samples", "_add_sch": "bakehouse",
               "_add_pick": re.sub(r"[^A-Za-z0-9]+", "_", NEW)}
    at = AppTest.from_file(str(APP_DIR / ADD), default_timeout=90)
    for k, v in session.items():
        at.session_state[k] = v
    at.run()
    assert not at.exception, [e.message for e in at.exception]
    return at


def _button(at, label):
    hits = [b for b in at.button if str(b.label) == label]
    assert hits, [str(b.label) for b in at.button]
    return hits[0]


def test_the_tree_the_rows_and_cancel_select_without_a_full_rerun(page, tmp_path, monkeypatch):
    """The browse half of Add tables is a fragment, so each of its controls is a
    callback rather than a button then `st.rerun()`. Clicked here, not set in session:
    a pick, a Cancel, and a schema opened from the tree, which must drop the pick and
    list the new schema's tables -- the schema is read inside the fragment."""
    d = with_catalog(build(tmp_path))
    tables = pd.read_parquet(d / "catalog.tables.parquet")
    extra = dict(tables.iloc[1])
    extra.update(table_schema="nyctaxi", table_name="trips")
    _write(d, "catalog.tables", pd.concat([tables, pd.DataFrame([extra])], ignore_index=True))
    monkeypatch.setenv("DQ_FIXTURE_DIR", str(d))
    at = _open_add(page, d)
    assert "Selection · 1 table" in _text(at)

    _button(at, "Cancel").click().run()
    assert not at.exception
    assert "_add_pick" not in at.session_state and "Choose a table" in _text(at)

    suppliers = re.sub(r"[^A-Za-z0-9]+", "_", "samples.bakehouse.sales_suppliers")
    at.button(key=f"_open_dqrow_add_{suppliers}").click().run()
    assert at.session_state["_add_pick"] == suppliers
    assert "samples.bakehouse.sales_suppliers" in _text(at)

    _button(at, "nyctaxi").click().run()
    assert not at.exception
    assert at.session_state["_add_sch"] == "nyctaxi"
    assert "_add_pick" not in at.session_state
    assert "trips" in _text(at) and "sales_suppliers" not in _text(at)


def test_suggest_row_key_and_scan_label():
    assert onboarding.suggest_row_key(["first_name", "customerID"]) == ["customerID"]
    assert onboarding.suggest_row_key(["a", "b"], primary_key=["b"]) == ["b"]
    assert onboarding.scan_label(20_055) == "under 10 s"
    assert onboarding.scan_label(1.56e9) == "about 15 s"
    assert onboarding.scan_label(3e11) == "too large for a daily full scan"


def test_nothing_is_written_until_the_table_is_submitted(page, tmp_path, monkeypatch):
    """Choosing a table and continuing writes nothing; one Submit, confirmed, writes the
    selection. The first build wrote on "Select" and a user found the table onboarding
    before they had reached any Submit."""
    d = with_catalog(build(tmp_path))
    monkeypatch.setenv("DQ_FIXTURE_DIR", str(d))
    at = _open_add(page, d)
    body = _text(at)
    assert "sales_customers" in body and "Under 10 s" in body
    _button(at, "Continue").click().run()
    assert not at.session_state["_pending_monitored_tables"] \
        if "_pending_monitored_tables" in at.session_state else True
    assert "Onboard sales_customers" in _text(at) and "Not submitted yet" in _text(at)

    _button(at, "Submit for onboarding").click().run()
    assert "_pending_monitored_tables" not in at.session_state or \
        not at.session_state["_pending_monitored_tables"], "wrote before confirming"
    assert "Row key: <b>customerID</b>" in _text(at)
    _confirm(at, "submit")
    assert not at.exception, [e.message for e in at.exception]

    rows = at.session_state["_pending_monitored_tables"]
    assert len(rows) == 1
    r = rows[0]
    assert r["target_table"] == NEW and r["status"] == "selected"
    assert r["row_key"] == ["customerID"] and r["selected_by"] == "m.okonkwo@example.com"
    assert r["table_code"] == "SALES_CUSTOMERS" and r["table_version"] == 1
    assert "sales_customers is submitted" in _text(at)


def test_an_unreadable_table_cannot_be_continued(page, tmp_path, monkeypatch):
    d = with_catalog(build(tmp_path), readable=False)
    monkeypatch.setenv("DQ_FIXTURE_DIR", str(d))
    at = _open_add(page, d)
    assert not [b for b in at.button if str(b.label) == "Continue"]
    assert "grant SELECT" in _text(at)


def test_a_table_too_large_for_a_daily_scan_cannot_be_continued(page, tmp_path, monkeypatch):
    d = with_catalog(build(tmp_path), size=3e11)
    monkeypatch.setenv("DQ_FIXTURE_DIR", str(d))
    at = _open_add(page, d)
    assert not [b for b in at.button if str(b.label) == "Continue"]
    assert "Too large for a daily scan" in _text(at)


def test_suggestions_are_submitted_with_the_table_signed_by_their_author(page, tmp_path,
                                                                          monkeypatch):
    d = with_catalog(build(tmp_path))
    monkeypatch.setenv("DQ_FIXTURE_DIR", str(d))
    at = _open_add(page, d)
    _button(at, "Continue").click().run()
    sel = [s for s in at.selectbox if s.label == "email_address"][0]
    sel.set_value("CDE_CUST_EMAIL").run()
    # A suggestion without a reason holds the Submit back.
    assert [b for b in at.button if str(b.label) == "Submit for onboarding"][0].disabled
    [t for t in at.text_input if t.key == "_sg_why_email_address"][0].set_value("It is.").run()
    _button(at, "Submit for onboarding").click().run()
    assert "you can't approve your own" in _text(at)
    _confirm(at, "submit")
    assert not at.exception, [e.message for e in at.exception]
    assert len(at.session_state["_pending_monitored_tables"]) == 1
    props = at.session_state["_pending_binding_proposals"]
    assert len(props) == 1
    p = props[0]
    assert (p["target_column"], p["cde_id"], p["method"]) == \
        ("email_address", "CDE_CUST_EMAIL", "suggested")
    assert p["proposed_by"] == "m.okonkwo@example.com" and p["evidence"] == "It is."
    assert "1 suggestion sent" in _text(at)


def test_the_author_of_a_suggestion_cannot_approve_it():
    me = "m.okonkwo@example.com"
    mine = {"proposed_by": me}
    with pytest.raises(onboarding.OnboardingRejected, match="second person"):
        onboarding.validate_review(mine, me, "approved", None)
    with pytest.raises(onboarding.OnboardingRejected, match="second person"):
        onboarding.validate_review({"proposed_by": "M.Okonkwo@Example.com"}, me, "approved", None)
    onboarding.validate_review(mine, me, "rejected", "withdrawn")       # withdrawing is fine
    onboarding.validate_review(mine, "p.nguyen@example.com", "approved", None)
    onboarding.validate_review({"proposed_by": "job:onboard-discover"}, me, "approved", None)
    with pytest.raises(onboarding.OnboardingRejected, match="why"):
        onboarding.validate_review(mine, "p.nguyen@example.com", "rejected", "  ")


def test_reviewing_records_one_decision_and_refuses_the_authors_approval(page, tmp_path):
    d = build(tmp_path, open_proposal=True)
    props = _read(d, "config.binding_proposal")
    props.loc[props["proposal_id"] == "p-phone", "proposed_by"] = "m.okonkwo@example.com"
    props.loc[props["proposal_id"] == "p-phone", "method"] = "suggested"
    extra = props[props["proposal_id"] == "p-phone"].assign(
        proposal_id="p-mob", target_column="MOBILE", cde_id="CDE_CUST_MOBILE",
        proposed_by="job:onboard-discover", method="uc_tag")
    _write(d, "config.binding_proposal", pd.concat([props, extra], ignore_index=True))

    at = page(d, table=True)
    body = _text(at)
    assert "Proposed bindings · 2" in body
    assert "A second person must approve it" in body and "Suggested by you" in body
    # The author's own suggestion offers no Approve.
    phone = [g for g in at.button_group if g.key == "_rv_p-phone"][0]
    assert list(phone.options) == ["Reject"]
    [g for g in at.button_group if g.key == "_rv_p-mob"][0].set_value("Approve").run()
    _button(at, "Record 1 decision").click().run()
    assert "Record 1 decision?" not in _text(at)  # the title is the dialog's, not markdown
    _confirm(at, "review")
    assert not at.exception, [e.message for e in at.exception]
    revs = at.session_state["_pending_binding_reviews"]
    assert [(r["proposal_id"], r["decision"], r["reviewed_by"]) for r in revs] == \
        [("p-mob", "approved", "m.okonkwo@example.com")]


def test_adapter_refuses_the_authors_approval_even_without_the_page(tmp_path, monkeypatch):
    """The page hides the button; the adapter is what actually refuses."""
    d = build(tmp_path, open_proposal=True)
    props = _read(d, "config.binding_proposal")
    props.loc[props["proposal_id"] == "p-phone", "proposed_by"] = "m.okonkwo@example.com"
    _write(d, "config.binding_proposal", props)

    def script():
        import sys
        import streamlit as st
        sys.path.insert(0, st.session_state["_app_dir"])
        from dq_app.data import adapter
        try:
            adapter.review_binding("p-phone", "approved")
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


def test_cancelling_a_confirmation_writes_nothing(page, tmp_path):
    at = page(build(tmp_path), table=True)
    _promote_button(at)[0].click().run()
    at.button(key="_onb_ask_no_promote").click().run()
    assert not at.exception, [e.message for e in at.exception]
    assert not at.session_state["_pending_rule_versions"] \
        if "_pending_rule_versions" in at.session_state else True
    assert "_onb_ask" not in at.session_state
    assert _promote_button(at), "the page still offers promotion"


def test_the_waiver_lets_an_author_approve_and_marks_the_record(page, tmp_path, monkeypatch):
    """DQ_ONBOARD_ALLOW_SELF_APPROVAL=1 (the dq-onboard test app only) waives the second
    approver. The page says so, the author may approve, and the decision's reason
    carries the waiver mark -- which is what the apply job requires to accept it."""
    d = build(tmp_path, open_proposal=True)
    props = _read(d, "config.binding_proposal")
    props.loc[props["proposal_id"] == "p-phone", "proposed_by"] = "m.okonkwo@example.com"
    props.loc[props["proposal_id"] == "p-phone", "method"] = "suggested"
    _write(d, "config.binding_proposal", props)
    monkeypatch.setenv("DQ_ONBOARD_ALLOW_SELF_APPROVAL", "1")

    at = page(d, table=True)
    assert "Second approver waived on this app" in _text(at)
    phone = [g for g in at.button_group if g.key == "_rv_p-phone"][0]
    assert list(phone.options) == ["Approve", "Reject"]
    phone.set_value("Approve").run()
    _button(at, "Record 1 decision").click().run()
    _confirm(at, "review")
    assert not at.exception, [e.message for e in at.exception]
    rev = at.session_state["_pending_binding_reviews"][0]
    assert rev["decision"] == "approved" and rev["reviewed_by"] == "m.okonkwo@example.com"
    assert rev["reason"].startswith(onboarding.WAIVER_MARK)


def test_without_the_waiver_the_rule_holds():
    me = "m.okonkwo@example.com"
    with pytest.raises(onboarding.OnboardingRejected, match="second person"):
        onboarding.validate_review({"proposed_by": me}, me, "approved", None)
    onboarding.validate_review({"proposed_by": me}, me, "approved", None, allow_self=True)


# --- Excluding a column at promotion -------------------------------------------------------

def test_an_approved_binding_is_excludable_and_a_later_rejection_excludes_it():
    props = pd.DataFrame([
        dict(proposal_id="p1", proposed_at=RUN_TS, target_table=LEAD, target_column="A",
             cde_id="E1"),
        dict(proposal_id="p2", proposed_at=RUN_TS, target_table=LEAD, target_column="B",
             cde_id="E2"),
        dict(proposal_id="p3", proposed_at=RUN_TS, target_table=LEAD, target_column="C",
             cde_id="E3")])
    t0, t1 = RUN_TS, datetime(2026, 10, 6)
    revs = pd.DataFrame([
        dict(proposal_id="p1", decision="approved", reviewed_at=t0, reason=None),
        dict(proposal_id="p2", decision="approved", reviewed_at=t0, reason=None),
        dict(proposal_id="p2", decision="rejected", reviewed_at=t1,
             reason=f"{onboarding.EXCLUSION_MARK} holds account notes"),
        dict(proposal_id="p3", decision="rejected", reviewed_at=t0, reason="not a phone")])
    assert onboarding.excludable_columns(props, revs, LEAD) == {"A": "p1"}
    # Only the exclusion: a first-time rejection never bound anything.
    assert onboarding.excluded_bindings(props, revs) == {(LEAD, "B", "E2")}
    # A later approval of a new proposal for the same pair binds it again.
    props2 = pd.concat([props, pd.DataFrame([dict(
        proposal_id="p4", proposed_at=t1, target_table=LEAD, target_column="B", cde_id="E2")])])
    revs2 = pd.concat([revs, pd.DataFrame([dict(
        proposal_id="p4", decision="approved", reviewed_at=datetime(2026, 10, 7), reason=None)])])
    assert onboarding.excluded_bindings(props2, revs2) == set()
    assert onboarding.excludable_columns(props2, revs2, LEAD) == {"A": "p1", "B": "p4"}


def test_excluding_a_column_retires_its_checks_and_takes_its_binding_back(page, tmp_path):
    at = page(build(tmp_path, second_column=True), table=True)
    assert [str(b.label) for b in _promote_button(at)] == ["Promote 3 checks"]
    at.checkbox(key="_onb_inc_HOME_PHONE").uncheck().run()
    assert [str(b.label) for b in _promote_button(at)] == ["Promote 2 checks"]
    assert "1 column</b> excluded, 1 check retired" in _text(at)

    # No reason: the dialog says so and the adapter refuses; nothing is written.
    _promote_button(at)[0].click().run()
    assert "An exclusion needs a reason" in _text(at)
    _confirm(at, "promote")
    assert not at.session_state["_pending_rule_versions"] \
        if "_pending_rule_versions" in at.session_state else True

    at.button(key="_onb_ask_no_promote").click().run()
    at.text_input(key="onbt_ex_reason").input("Holds the account's fax number").run()
    _promote_button(at)[0].click().run()
    assert "Excluded" in _text(at) and "HOME_PHONE" in _text(at)
    _confirm(at, "promote")
    assert not at.exception, [e.message for e in at.exception]

    versions = {v["rule_id"]: v for v in at.session_state["_pending_rule_versions"]}
    assert {k: v["status"] for k, v in versions.items()} == {
        "LEAD_EMAIL_FMT": "active", "LEAD_EMAIL_NOT_NULL": "active",
        "LEAD_HOME_PHONE_FMT": "retired"}
    assert "fax number" in versions["LEAD_HOME_PHONE_FMT"]["note"]
    assert pd.isna(versions["LEAD_HOME_PHONE_FMT"].get("promoted_by"))
    revs = [r for r in at.session_state["_pending_binding_reviews"] if r["proposal_id"] == "p-home"]
    assert len(revs) == 1 and revs[0]["decision"] == "rejected"
    assert revs[0]["reason"] == f"{onboarding.EXCLUSION_MARK} Holds the account's fax number"

    body = _text(at)
    assert "All 2 checks are active" in body
    assert "excluded at promotion" in body


def test_a_binding_registered_by_hand_cannot_be_excluded(page, tmp_path):
    d = build(tmp_path, second_column=True)
    revs = _read(d, "config.binding_review")
    _write(d, "config.binding_review", revs[revs["proposal_id"] != "p-home"])
    props = _read(d, "config.binding_proposal")
    _write(d, "config.binding_proposal", props[props["proposal_id"] != "p-home"])
    at = page(d, table=True)
    assert at.checkbox(key="_onb_inc_HOME_PHONE").disabled
    assert not at.checkbox(key="_onb_inc_EMAIL").disabled


# --- Pause, resume, decommission ----------------------------------------------------------

def test_transitions_are_pause_resume_and_a_permanent_retire():
    assert onboarding.TRANSITIONS["selected"] == {"paused", "retired"}
    assert onboarding.TRANSITIONS["paused"] == {"selected", "retired"}
    assert "retired" not in onboarding.TRANSITIONS          # nothing comes back from retired


def _manage(at, action: str, reason: str = "Source system switched off."):
    [t for t in at.text_input if t.key == "onbt_manage_reason"][0].set_value(reason).run()
    label = {"pause": "Pause checking", "resume": "Resume checking",
             "decommission": "Decommission"}[action]
    _button(at, label).click().run()
    _confirm(at, action)
    assert not at.exception, [e.message for e in at.exception]


def test_pausing_keeps_the_checks_and_the_table_on_the_list(page, tmp_path):
    d = build(tmp_path)
    at = page(d, table=True)
    _manage(at, "pause")
    rows = at.session_state["_pending_monitored_tables"]
    assert [(r["status"], r["table_version"]) for r in rows] == [("paused", 2)]
    assert rows[0]["note"] == "Source system switched off."
    assert "_pending_rule_versions" not in at.session_state or \
        not at.session_state["_pending_rule_versions"], "pausing touched the checks"
    body = _text(at)
    assert "Paused" in body and "Resume checking" in [str(b.label) for b in at.button]


def test_decommissioning_retires_the_table_and_every_check_on_it(page, tmp_path):
    d = build(tmp_path)
    at = page(d, table=True)
    _manage(at, "decommission")
    tables = at.session_state["_pending_monitored_tables"]
    assert [(r["status"], r["table_version"]) for r in tables] == [("retired", 2)]
    versions = at.session_state["_pending_rule_versions"]
    assert sorted(v["rule_id"] for v in versions) == ["LEAD_EMAIL_FMT", "LEAD_EMAIL_NOT_NULL"]
    assert all(v["status"] == "retired" and v["rule_version"] == 2 for v in versions)
    assert all("Retired with its table" in v["note"] for v in versions)


def test_a_status_change_needs_a_reason(page, tmp_path):
    d = build(tmp_path)
    at = page(d, table=True)
    _button(at, "Pause checking").click().run()
    assert "Add a reason first" in _text(at)
    _confirm(at, "pause")
    assert "_pending_monitored_tables" not in at.session_state or \
        not at.session_state["_pending_monitored_tables"]

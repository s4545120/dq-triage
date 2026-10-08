"""Element tolerance: the twins that pin the app to the views, the escalation gate, the
per-element advice and its decision through the Thresholds page.

`domain/tolerance.py` copies three views in sql/ddl/20_views_tolerance.sql. These tests
pin the copies to the fixture's own twins (fixtures/tolerance.py, written separately);
the app's copies were also diffed against the SQL on the live workspace on 2026-10-08.
If a conformance test fails after you edited a view, the app drifted. The view wins.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from dq_app.domain import metrics, tolerance
from dq_app.domain.tolerance import ReviewRejected, validate_review

APP_DIR = Path(__file__).resolve().parents[1]
FIXTURE = APP_DIR.parent / "fixtures" / "out"
PAGE = "dq_app/ui/pages/thresholds.py"


def _load(name: str) -> pd.DataFrame:
    p = FIXTURE / f"{name}.parquet"
    if not p.exists():
        pytest.skip("fixture not built")
    return pd.read_parquet(p)


def _registry():
    return _load("config.cde_registry")


def _norm(v):
    if isinstance(v, (list, tuple, np.ndarray)):
        return "|".join(str(x) for x in v)
    if isinstance(v, (pd.Timestamp, date)):
        return str(pd.Timestamp(v))
    if isinstance(v, (float, np.floating)) and not pd.isna(v):
        return round(float(v), 9)
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return None
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    return v


def _same(mine: pd.DataFrame, shipped: pd.DataFrame, key: list[str]) -> None:
    assert list(mine.columns) == list(shipped.columns)
    a = mine.sort_values(key).reset_index(drop=True)
    b = shipped.sort_values(key).reset_index(drop=True)
    assert len(a) == len(b)
    for c in a.columns:
        assert [_norm(x) for x in a[c]] == [_norm(x) for x in b[c]], c


# --- The twins ------------------------------------------------------------------


def test_element_tolerance_reproduces_the_shipped_view():
    runs, cov = _load("results.check_run"), _load("results.v_cde_coverage")
    _same(tolerance.element_tolerance(runs, cov, _registry()),
          _load("results.v_element_tolerance"), ["run_id", "cde_id"])


def test_check_escalation_reproduces_the_shipped_view():
    runs, cov = _load("results.check_run"), _load("results.v_cde_coverage")
    et = tolerance.element_tolerance(runs, cov, _registry())
    _same(tolerance.check_escalation(runs, cov, et),
          _load("results.v_check_escalation"), ["run_id", "rule_id"])


def test_proposal_fold_reproduces_the_shipped_view():
    _same(tolerance.derive_proposal_current(
              _load("results.tolerance_proposal"), _load("results.tolerance_review"),
              _registry()),
          _load("results.v_tolerance_proposal_current"), ["cde_id"])


def test_the_scorecard_scores_elements_with_the_gate_s_arithmetic():
    """One arithmetic: the page's element score IS the gate's, not a copy of it."""
    src = (APP_DIR / "dq_app/ui/pages/scorecard.py").read_text()
    assert "_element_scores = tolerance.element_scores" in src
    assert "_row_score = tolerance.row_score" in src


# --- The gate --------------------------------------------------------------------


def test_a_p1_breach_always_escalates():
    esc = _load("results.v_check_escalation")
    p1 = esc[esc["severity"] == "P1_block"]
    assert len(p1) and p1["escalates"].all()


def test_a_p1_escalates_even_inside_a_tolerant_element():
    """The fixture has no P1 inside a tolerant element, so build one: two breaching
    checks on an element at 99.9% against a 0.5% tolerance, one P2 and one P1."""
    ts = pd.Timestamp("2026-10-08 03:00")
    runs = pd.DataFrame([
        dict(run_id="r", run_ts=ts, result_id=f"x{i}", rule_id=rid, status="breach",
             severity=sev, rows_scanned=1000, violation_count=1)
        for i, (rid, sev) in enumerate([("R_P2", "P2_alert"), ("R_P1", "P1_block")])])
    cov = pd.DataFrame([dict(cde_id="E", cde_name="E", coverage_gap="covered",
                             rule_ids=["R_P1", "R_P2"])])
    reg = pd.DataFrame([dict(cde_id="E", cde_version=1, cde_name="E", criticality="high",
                             status="registered", tolerance_pct=0.5)])
    et = tolerance.element_tolerance(runs, cov, reg)
    assert bool(et.iloc[0]["within_tolerance"])
    esc = tolerance.check_escalation(runs, cov, et).set_index("rule_id")
    assert bool(esc.loc["R_P1", "escalates"]) and pd.isna(esc.loc["R_P1", "held_reason"])
    assert not bool(esc.loc["R_P2", "escalates"])
    assert esc.loc["R_P2", "held_reason"] == "element_within_tolerance"


def test_a_scope_mismatch_is_never_held_back():
    """COH-B. Its failures are a rule defect; holding them back would hide the finding
    the register exists to raise."""
    et, esc = _load("results.v_element_tolerance"), _load("results.v_check_escalation")
    disputed = set(et[et["scope_disputed"]]["cde_id"])
    assert {"CDE_BILLING_ACCOUNT", "CDE_DEVICE_IMEI"} <= disputed
    assert not et[et["scope_disputed"]]["within_tolerance"].any()
    assert esc[esc["cde_id"].isin(disputed)]["escalates"].all()


def test_within_needs_a_tolerance_a_score_and_no_dispute():
    assert tolerance.within(99.6, 0.5, False)
    assert not tolerance.within(99.4, 0.5, False)
    assert not tolerance.within(100.0, None, False), "no tolerance is not acceptance"
    assert not tolerance.within(None, 0.5, False)
    assert not tolerance.within(100.0, 2.0, True)


def test_the_queue_leaves_out_what_the_tolerance_holds():
    runs, cov, cohorts = (_load("results.check_run"), _load("results.v_cde_coverage"),
                          _load("results.cohort"))
    held = tolerance.held_on_run(runs, cov, _registry(), metrics.queue_run_id(runs))
    assert held == {"SUBS_NTWK_NOT_NULL", "XREF_NAME_AGREEMENT", "XREF_OPEN_TS_AGREEMENT"}
    before, after = metrics.live_cohorts(runs, cohorts), metrics.live_cohorts(runs, cohorts, held)
    assert set(before) - set(after) == held
    c = metrics.cohort_compression(runs, cohorts, held)
    assert (c.numerator, c.denominator) == (len(after), len(set(after.values())))


# --- The advice ------------------------------------------------------------------


def test_no_proposal_raises_a_tolerance():
    p = _load("results.tolerance_proposal")
    declared = p[p["current_tolerance_pct"].notna()]
    assert (declared["proposed_tolerance_pct"] <= declared["current_tolerance_pct"]).all()
    t = p[p["advice"] == "tighten"]
    assert len(t) and (t["proposed_tolerance_pct"] < t["current_tolerance_pct"]).all()
    other = p[p["advice"] != "tighten"]
    assert (other["proposed_tolerance_pct"] == other["current_tolerance_pct"]).all()


def test_a_scope_mismatch_is_advised_keep_and_says_why():
    p = _load("results.tolerance_proposal").set_index("cde_id")
    for cde in ("CDE_BILLING_ACCOUNT", "CDE_DEVICE_IMEI"):
        assert p.loc[cde, "advice"] == "keep"
        assert "scope" in p.loc[cde, "rationale"].lower()


def test_one_proposal_per_element():
    cur = _load("results.v_tolerance_proposal_current")
    assert cur["cde_id"].is_unique
    reg = _registry().sort_values("cde_version").groupby("cde_id").tail(1)
    assert set(cur["cde_id"]) == set(reg[reg["status"] != "retired"]["cde_id"])


def test_a_tightening_the_register_carries_reads_in_force():
    props, revs, reg = (_load("results.tolerance_proposal"), _load("results.tolerance_review"),
                        _registry())
    t = props[props["advice"] == "tighten"].iloc[0]
    reg = reg.copy()
    last = reg[reg["cde_id"] == t["cde_id"]]["cde_version"].max()
    reg.loc[(reg["cde_id"] == t["cde_id"]) & (reg["cde_version"] == last),
            "tolerance_pct"] = t["proposed_tolerance_pct"]
    cur = tolerance.derive_proposal_current(props, revs, reg).set_index("cde_id")
    assert cur.loc[t["cde_id"], "review_state"] == "in_force"


def test_reject_and_defer_need_a_reason_and_defer_needs_a_date():
    with pytest.raises(ReviewRejected, match="reason"):
        validate_review("rejected", reason=" ", review_by_date=None, state="open")
    with pytest.raises(ReviewRejected, match="review-by"):
        validate_review("deferred", reason="later", review_by_date=None, state="open")
    with pytest.raises(ReviewRejected, match="nothing to decide"):
        validate_review("accepted", reason=None, review_by_date=None, state="no_change")
    validate_review("accepted", reason=None, review_by_date=None, state="open")


def test_summary_counts_every_state():
    cur = _load("results.v_tolerance_proposal_current")
    s = tolerance.summary(cur)
    assert sum(s[k] for k in tolerance.STATES) == s["proposals"] == len(cur)
    assert s["open"] and s["accepted"] and s["deferred"] and s["rejected"] and s["no_change"]


# --- Through the pages ---------------------------------------------------------------

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402


def _run(page: str = PAGE, **session):
    at = AppTest.from_file(str(APP_DIR / page), default_timeout=90)
    for k, v in session.items():
        at.session_state[k] = v
    at.run()
    assert not at.exception, [e.message for e in at.exception]
    return at


def _text(at) -> str:
    return " ".join(str(m.value) for m in at.markdown) + " " + " ".join(
        str(c.value) for c in at.caption)


def _open():
    cur = _load("results.v_tolerance_proposal_current")
    return cur[cur["review_state"] == "open"].sort_values("cde_id").iloc[0]


def test_the_page_lists_one_row_per_element_and_no_rule_limits():
    at = _run()
    body = _text(at)
    for _, r in _load("results.v_tolerance_proposal_current").iterrows():
        assert str(r["cde_name"]) in body
    assert "Business decision" in body and "Tighten" in body
    assert "earlier limit proposals are kept as history" in body
    # The per-rule list is gone: no rule id from the old table is printed.
    old = _load("results.threshold_proposal")
    assert not any(rid in body for rid in old["rule_id"])


def test_deciding_asks_first_and_writes_one_review_on_confirm():
    p = _open()
    at = _run(_tol_pick=p["proposal_id"])
    at.radio(key=f"tol_dec_{p['proposal_id']}").set_value("accepted")
    at.button(key="tol_go").click().run()
    assert not at.exception, [e.message for e in at.exception]
    assert not at.session_state["_pending_tolerance_reviews"] \
        if "_pending_tolerance_reviews" in at.session_state else True, \
        "written before the confirmation"
    at.button(key="_onb_ask_yes_tolerance_review").click().run()
    assert not at.exception, [e.message for e in at.exception]
    written = at.session_state["_pending_tolerance_reviews"]
    assert len(written) == 1
    assert written[0]["proposal_id"] == p["proposal_id"]
    assert written[0]["decision"] == "accepted"
    # Nothing but the review: the register and the rule registry are untouched.
    for key in ("_pending_rule_versions", "_pending_cde_proposals"):
        assert key not in at.session_state or not at.session_state[key]


def test_a_rejection_without_a_reason_is_refused():
    p = _open()
    at = _run(_tol_pick=p["proposal_id"])
    at.radio(key=f"tol_dec_{p['proposal_id']}").set_value("rejected")
    at.text_area(key=f"tol_reason_{p['proposal_id']}").set_value("  ")
    at.button(key="tol_go").click().run()
    at.button(key="_onb_ask_yes_tolerance_review").click().run()
    assert not at.exception
    assert "_pending_tolerance_reviews" not in at.session_state \
        or not at.session_state["_pending_tolerance_reviews"]
    assert any("reason" in str(e.value).lower() for e in at.error)


def test_a_decided_advice_offers_no_form():
    cur = _load("results.v_tolerance_proposal_current")
    done = cur[cur["review_state"] == "rejected"].iloc[0]
    at = _run(_tol_pick=done["proposal_id"])
    assert not [b for b in at.button if b.key == "tol_go"]
    assert str(done["latest_reviewer"]) in _text(at)


def test_an_accepted_tightening_points_at_the_elements_page():
    cur = _load("results.v_tolerance_proposal_current")
    acc = cur[(cur["review_state"] == "accepted") & (cur["advice"] == "tighten")].iloc[0]
    at = _run(_tol_pick=acc["proposal_id"])
    assert [b for b in at.button if b.key == "tol_to_elements"]
    assert "Elements page" in _text(at)


def test_the_triage_queue_says_what_it_held_back():
    at = _run("dq_app/ui/pages/triage.py")
    body = _text(at)
    assert "3 within tolerance" in body
    assert "within their element's agreed tolerance" in body
    assert "Network technology" in body

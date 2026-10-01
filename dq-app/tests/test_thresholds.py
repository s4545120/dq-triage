"""Threshold proposals: the fold that pins the app to the view, the review rules,
and the third write end to end through the page.

Same discipline as the lifecycle and coverage twins. `derive_proposal_current` is a
copy of `v_threshold_proposal_current`; if the conformance test fails after you
edited the view, the app drifted; if after you edited the fold, the fold is wrong.
The view wins.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from dq_app.domain import thresholds
from dq_app.domain.thresholds import ReviewRejected, derive_proposal_current, validate_review

APP_DIR = Path(__file__).resolve().parents[1]
FIXTURE = APP_DIR.parent / "fixtures" / "out"
PAGE = "dq_app/ui/pages/thresholds.py"


def _load(name: str) -> pd.DataFrame:
    p = FIXTURE / f"{name}.parquet"
    if not p.exists():
        pytest.skip("fixture not built")
    return pd.read_parquet(p)


@pytest.fixture(scope="session")
def proposals():
    return _load("results.threshold_proposal")


@pytest.fixture(scope="session")
def reviews():
    return _load("results.threshold_review")


@pytest.fixture(scope="session")
def shipped_current():
    return _load("results.v_threshold_proposal_current")


# --- The fold ----------------------------------------------------------------


def _norm(v):
    if isinstance(v, (list, tuple, np.ndarray)):
        return "|".join(str(x) for x in v)
    if isinstance(v, (pd.Timestamp, date)):
        return str(pd.Timestamp(v))
    return v


def test_fold_reproduces_shipped_view(proposals, reviews, rule_registry, shipped_current):
    got = derive_proposal_current(proposals, reviews, rule_registry)
    assert len(got) == len(shipped_current)
    a = shipped_current.sort_values("rule_id").reset_index(drop=True)
    b = got.sort_values("rule_id").reset_index(drop=True)
    assert list(a.columns) == list(b.columns), (set(a.columns) ^ set(b.columns))
    bad = {}
    for col in a.columns:
        x, y = a[col].map(_norm), b[col].map(_norm)
        same = (x.isna() & y.isna()) | (x.astype(str) == y.astype(str))
        if not same.all():
            bad[col] = a.loc[~same, "rule_id"].tolist()
    assert not bad, f"fold disagrees with v_threshold_proposal_current: {bad}"


def test_every_state_the_page_draws_is_reachable(shipped_current):
    """open, deferred, rejected and no_change from the fixture; adopted through
    the write path below. A state nobody can reach is a panel nobody can test."""
    assert {"open", "deferred", "rejected", "no_change"} <= set(shipped_current["review_state"])


def test_a_review_in_session_changes_the_state(proposals, reviews, rule_registry):
    cur = derive_proposal_current(proposals, reviews, rule_registry)
    open_ = cur[cur["review_state"] == "open"].iloc[0]
    later = pd.concat([reviews, pd.DataFrame([{
        "review_id": "x", "proposal_id": open_["proposal_id"],
        "event_ts": pd.Timestamp("2026-09-30"), "ingest_ts": pd.Timestamp("2026-09-30"),
        "actor_identity": "a@example.com", "actor_display_name": "A",
        "actor_source": "obo_user", "decision": "rejected", "reason": "no",
        "review_by_date": None, "adopted_rule_version": None, "app_version": "t",
    }])], ignore_index=True)
    again = derive_proposal_current(proposals, later, rule_registry)
    assert again.set_index("rule_id").loc[open_["rule_id"], "review_state"] == "rejected"


def test_the_registry_carrying_the_limit_reads_in_force(proposals, reviews, rule_registry):
    cur = derive_proposal_current(proposals, reviews, rule_registry)
    open_ = cur[cur["review_state"] == "open"].iloc[0]
    reg = rule_registry.copy()
    bump = reg[reg["rule_id"] == open_["rule_id"]].sort_values("rule_version").iloc[-1].to_dict()
    bump["rule_version"] += 1
    bump["fail_threshold_pct"] = open_["proposed_threshold_pct"]
    again = derive_proposal_current(proposals, reviews,
                                    pd.concat([reg, pd.DataFrame([bump])], ignore_index=True))
    assert again.set_index("rule_id").loc[open_["rule_id"], "review_state"] == "in_force"


# --- The review rules ----------------------------------------------------------


def test_reject_and_defer_need_a_reason_and_defer_needs_a_date():
    with pytest.raises(ReviewRejected):
        validate_review("rejected", reason=" ", review_by_date=None, state="open")
    with pytest.raises(ReviewRejected):
        validate_review("deferred", reason="later", review_by_date=None, state="open")
    validate_review("deferred", reason="later", review_by_date=date(2026, 12, 1), state="open")
    validate_review("adopted", reason=None, review_by_date=None, state="deferred")


def test_only_an_open_or_deferred_proposal_can_be_decided():
    for state in ("adopted", "rejected", "in_force", "no_change"):
        with pytest.raises(ReviewRejected):
            validate_review("adopted", reason=None, review_by_date=None, state=state)


# --- The invariants over what is stored ------------------------------------------


def test_no_proposal_exceeds_the_tolerance_its_element_declares(proposals):
    """The ceiling. A CHECK on the table, the job's validator, verify.py, and here."""
    capped = proposals[proposals["tolerance_pct"].notna()]
    assert len(capped), "no capped proposal in the fixture"
    assert (capped["proposed_threshold_pct"] <= capped["tolerance_pct"]).all()
    assert ((proposals["basis"] == "unchanged")
            == (proposals["proposed_threshold_pct"] == proposals["current_threshold_pct"])).all()


def test_a_rule_defect_is_answered_with_keep(proposals, cohorts):
    """COH-B's two rules sit at 20% and 50% on every run. Raising the limit until
    they pass is the wrong answer a model asked about limits will reach for; the
    fixture's advice on both is keep, and the reason is scope."""
    defect = cohorts[cohorts["defect_location"] == "rule"].iloc[0]
    for rid in defect["member_rule_ids"]:
        p = proposals[proposals["rule_id"] == rid]
        assert len(p) and (p["basis"] == "unchanged").all(), rid
        assert "scope" in p.iloc[0]["rationale"].lower()


# --- The third write, through the page --------------------------------------------

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402


def _open_proposal():
    cur = _load("results.v_threshold_proposal_current")
    return cur[cur["review_state"] == "open"].iloc[0]


def _run(**session):
    at = AppTest.from_file(str(APP_DIR / PAGE), default_timeout=90)
    for k, v in session.items():
        at.session_state[k] = v
    at.run()
    assert not at.exception, [e.message for e in at.exception]
    return at


def _submit(at):
    for b in at.button:
        if "Append decision" in str(b.label):
            return b
    raise AssertionError(f"no decision button: {[b.label for b in at.button]}")


def test_the_page_lists_every_proposal_with_its_state_and_reviewer():
    at = _run()
    body = " ".join(str(m.value) for m in at.markdown)
    cur = _load("results.v_threshold_proposal_current")
    for _, r in cur.iterrows():
        assert r["rule_id"] in body
        assert r["reviewer"] in body
    assert "Awaiting review" in body and "Keep as is" in body


def test_adopting_appends_a_rule_version_and_records_which():
    p = _open_proposal()
    at = _run(_thr_pick=p["proposal_id"])
    at.radio[0].set_value("adopted")
    at.text_area[0].set_value("Agreed with the element's tolerance.")
    _submit(at).click().run()
    assert not at.exception, [e.message for e in at.exception]

    reviews = at.session_state["_pending_threshold_reviews"]
    versions = at.session_state["_pending_rule_versions"]
    assert len(reviews) == 1 and len(versions) == 1
    review, version = reviews[0], versions[0]
    assert review["decision"] == "adopted"
    assert review["proposal_id"] == p["proposal_id"]
    assert version["rule_id"] == p["rule_id"]
    assert float(version["fail_threshold_pct"]) == float(p["proposed_threshold_pct"])
    assert review["adopted_rule_version"] == version["rule_version"] == int(p["rule_version"]) + 1
    # Status carried forward: adopting a limit is not a promotion.
    reg = _load("config.rule_registry")
    assert version["status"] == reg[reg["rule_id"] == p["rule_id"]].sort_values(
        "rule_version").iloc[-1]["status"]
    assert p["proposal_id"][:8] in version["note"]

    rendered = " ".join(str(m.value) for m in at.markdown)
    assert "Adopted" in rendered


def test_a_rejection_without_a_reason_is_refused():
    p = _open_proposal()
    at = _run(_thr_pick=p["proposal_id"])
    at.radio[0].set_value("rejected")
    at.text_area[0].set_value("  ")
    _submit(at).click().run()
    assert not at.exception
    for key in ("_pending_threshold_reviews", "_pending_rule_versions"):
        assert key not in at.session_state or not at.session_state[key]
    assert any("reason" in str(e.value).lower() for e in at.error)


def test_a_decided_proposal_offers_no_form():
    cur = _load("results.v_threshold_proposal_current")
    done = cur[cur["review_state"] == "rejected"].iloc[0]
    at = _run(_thr_pick=done["proposal_id"])
    assert not [b for b in at.button if "Append decision" in str(b.label)]
    body = " ".join(str(m.value) for m in at.markdown)
    assert "Rejected" in body and str(done["latest_reviewer"]) in body


def test_summary_counts_every_state():
    cur = _load("results.v_threshold_proposal_current")
    s = thresholds.summary(cur)
    assert sum(s[k] for k in thresholds.STATES) == s["proposals"] == len(cur)

"""Every page renders against the fixture without raising.

Not a substitute for looking at the app, but it catches the class of break that a
pure-logic suite never sees: a column renamed in the fixture, a `column_config` key
that no longer matches, a page reading a field the adapter stopped returning.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP_DIR = Path(__file__).resolve().parents[1]
PAGES = [
    "dq_app/ui/pages/scorecard.py",
    "dq_app/ui/pages/monitored_tables.py",
    "dq_app/ui/pages/monitor_detail.py",
    "dq_app/ui/pages/cohort_queue.py",
    "dq_app/ui/pages/cohort_detail.py",
    "dq_app/ui/pages/register.py",
    "dq_app/ui/pages/rule_registry.py",
    "dq_app/ui/pages/cde_registry.py",
]


@pytest.mark.parametrize("page", PAGES)
def test_page_renders(page):
    at = AppTest.from_file(str(APP_DIR / page), default_timeout=60)
    at.run()
    assert not at.exception, [e.message for e in at.exception]


def test_detail_page_opens_the_cohort_it_was_handed():
    """The queue hands the detail page a cohort id through session state. If that
    contract breaks, the Open button silently shows the wrong cohort."""
    import pandas as pd

    cohort_path = APP_DIR.parent / "fixtures" / "out" / "results.cohort.parquet"
    if not cohort_path.exists():
        pytest.skip("fixture not built")
    target = pd.read_parquet(cohort_path).sort_values("member_count").iloc[-1]["cohort_id"]

    at = AppTest.from_file(str(APP_DIR / "dq_app/ui/pages/cohort_detail.py"), default_timeout=60)
    at.session_state["selected_cohort"] = target
    at.run()
    assert not at.exception, [e.message for e in at.exception]
    assert any(target[:8] in str(h.value) for h in at.title)


def test_cde_page_renders_every_registered_element():
    """The Inspect panel branches on what an element has: a signature or none, a
    scoped binding or none, a profile or none, rules or none. Rendering one element
    exercises one branch, so render all of them."""
    import pandas as pd

    path = APP_DIR.parent / "fixtures" / "out" / "config.cde_registry.parquet"
    if not path.exists():
        pytest.skip("fixture not built")

    for cde_id in pd.read_parquet(path)["cde_id"]:
        at = AppTest.from_file(
            str(APP_DIR / "dq_app/ui/pages/cde_registry.py"), default_timeout=60)
        at.session_state["_cde_pick"] = cde_id
        at.run()
        assert not at.exception, (cde_id, [e.message for e in at.exception])


def test_cde_page_shows_how_a_cross_table_rule_attaches():
    """XREF_NAME_AGREEMENT covers the name element and carries no target column, so
    it can only attach by the explicit tag. If that path breaks, the page reports a
    KYC element as watched by nothing and gives no clue why."""
    at = AppTest.from_file(
        str(APP_DIR / "dq_app/ui/pages/cde_registry.py"), default_timeout=60)
    at.session_state["_cde_pick"] = "CDE_CUST_NAME"
    at.run()
    assert not at.exception, [e.message for e in at.exception]

    body = " ".join(str(m.value) for m in at.markdown)
    assert "XREF_NAME_AGREEMENT" in body
    assert "element tag" in body


def test_scorecard_opens_every_dimension_panel():
    """Each dimension panel branches on what its dimension has: a score or none, a
    failing check or none, checks attached to a registered element or none. Opening
    one exercises one branch, so open all four."""
    from dq_app.ui.pages import scorecard  # noqa: F401  (import guard only)

    for name in ["Completeness", "Validity", "Consistency", "Uniqueness"]:
        at = AppTest.from_file(
            str(APP_DIR / "dq_app/ui/pages/scorecard.py"), default_timeout=60)
        at.session_state["_dim_pick"] = name
        at.run()
        assert not at.exception, (name, [e.message for e in at.exception])
        body = " ".join(str(m.value) for m in at.markdown)
        assert "How the score is made" in body, name


def test_a_dimension_with_a_failing_check_never_reads_as_a_clean_100():
    """Consistency scores 99.9% with one check failing. Printed at zero decimals that
    is "100%", sitting directly above the words "1 failing" — the card contradicting
    itself, with nothing to tell the reader which half is wrong. `theme.pct_text` is
    what stops it, and this is the case that motivated it."""
    from dq_app.ui import theme

    assert theme.pct_text(99.9) == "99.9"
    assert theme.pct_text(99.96) == "99.96"
    assert theme.pct_text(100.0) == "100"
    assert theme.pct_text(0.0) == "0"
    assert theme.pct_text(None) == "—"

    at = AppTest.from_file(
        str(APP_DIR / "dq_app/ui/pages/scorecard.py"), default_timeout=60)
    at.run()
    assert not at.exception, [e.message for e in at.exception]

    # A card reading 100% is fine when nothing in it is failing — Uniqueness is
    # genuinely clean. What must never happen is 100% over a non-zero failing count.
    cards = [str(m.value) for m in at.markdown if 'class="dq-dim"' in str(m.value)]
    assert len(cards) == 4, cards
    for card in cards:
        failing = int(re.search(r"(\d+) failing", card).group(1))
        shown = re.search(r'class="val"[^>]*>([\d.]+|—)%?<', card).group(1)
        assert not (shown == "100" and failing), card

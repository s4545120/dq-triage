"""Every page renders against the fixture without raising.

Not a substitute for looking at the app, but it catches the class of break that a
pure-logic suite never sees: a column renamed in the fixture, a `column_config` key
that no longer matches, a page reading a field the adapter stopped returning.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP_DIR = Path(__file__).resolve().parents[1]
PAGES = [
    "dq_app/ui/pages/scorecard.py",
    "dq_app/ui/pages/cohort_queue.py",
    "dq_app/ui/pages/cohort_detail.py",
    "dq_app/ui/pages/register.py",
    "dq_app/ui/pages/rule_registry.py",
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

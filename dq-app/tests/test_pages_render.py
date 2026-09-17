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
    "dq_app/ui/pages/tables.py",
    "dq_app/ui/pages/table_detail.py",
    "dq_app/ui/pages/triage.py",
    "dq_app/ui/pages/triage_detail.py",
    "dq_app/ui/pages/rule_registry.py",
]

SCORECARD = "dq_app/ui/pages/scorecard.py"


def _run(page: str, **session):
    at = AppTest.from_file(str(APP_DIR / page), default_timeout=90)
    for k, v in session.items():
        at.session_state[k] = v
    at.run()
    assert not at.exception, (page, session, [e.message for e in at.exception])
    return at


def _body(at) -> str:
    return " ".join(str(m.value) for m in at.markdown)


@pytest.mark.parametrize("page", PAGES)
def test_page_renders(page):
    _run(page)


def test_every_registered_page_exists_and_every_link_is_registered():
    """`app.py` registers six pages and links four. A drill-down that falls out of
    `PAGES` stops being reachable by `st.switch_page` with no error until someone
    clicks the button; a nav key with no page is an immediate crash on boot."""
    app = (APP_DIR / "app.py").read_text()

    registered = set(re.findall(r'"(\w+)": st\.Page\("([^"]+)"', app))
    assert registered, "no pages found in app.py"
    for _, path in registered:
        assert (APP_DIR / path).exists(), path

    keys = {k for k, _ in registered}
    linked = set(re.findall(r'"(\w+)"', re.search(r"SIDEBAR = \{(.*?)\n\}", app,
                                                  re.S).group(1)))
    # Group labels are in that block too; only the ones that look like page keys matter.
    assert (linked & keys) <= keys
    assert {"scorecard", "tables", "triage", "rules"} <= keys

    # The two drill-downs are registered and deliberately not linked.
    assert {"table_detail", "triage_detail"} <= keys
    assert not ({"table_detail", "triage_detail"} & linked)


def test_switch_page_targets_all_exist():
    """A renamed page file with a stale `switch_page` string fails only when clicked."""
    for path in (APP_DIR / "dq_app/ui/pages").glob("*.py"):
        for target in re.findall(r'st\.switch_page\("([^"]+)"\)', path.read_text()):
            assert (APP_DIR / target).exists(), (path.name, target)


def test_detail_page_opens_the_problem_it_was_handed():
    """Triage hands the detail page a cohort id through session state. If that
    contract breaks, Open silently shows the wrong problem.

    The title is the hypothesis, not the id, so the id is asserted where it actually
    appears — the facts line under the heading, which became part of the header markup
    when the page moved to tabs."""
    import pandas as pd

    cohort_path = APP_DIR.parent / "fixtures" / "out" / "results.cohort.parquet"
    if not cohort_path.exists():
        pytest.skip("fixture not built")
    target = pd.read_parquet(cohort_path).sort_values("member_count").iloc[-1]["cohort_id"]

    at = _run("dq_app/ui/pages/triage_detail.py", selected_cohort=target)
    assert target[:8] in _body(at)


def test_detail_page_renders_every_lifecycle_state():
    """The decision form branches on what `available_events` allows from the state:
    a review form, a bare Approve, an execute form, or nothing at all. Rendering one
    problem exercises one branch, so render them all."""
    import pandas as pd

    path = APP_DIR.parent / "fixtures" / "out" / "results.v_cohort_current.parquet"
    if not path.exists():
        pytest.skip("fixture not built")
    current = pd.read_parquet(path)

    for cohort_id in current["cohort_id"]:
        _run("dq_app/ui/pages/triage_detail.py", selected_cohort=cohort_id)

    # Guard the guard: if the fixture ever stops covering the interesting states this
    # test quietly becomes four renders of the same branch.
    assert {"reopened", "awaiting_review", "approved_awaiting_execution"} <= set(
        current["lifecycle_state"]
    )


def test_scorecard_opens_every_failing_check():
    """The check panel branches on what a check has: an element or none, samples or
    none, a cohort or none, a scope filter or none. Opening one exercises one branch,
    so open every check that is failing on the latest run."""
    import pandas as pd

    path = APP_DIR.parent / "fixtures" / "out" / "results.check_run.parquet"
    if not path.exists():
        pytest.skip("fixture not built")
    runs = pd.read_parquet(path)
    latest = runs.loc[runs["run_ts"].idxmax(), "run_id"]
    failing = runs[(runs["run_id"] == latest) & (runs["status"] == "breach")]["rule_id"]
    assert len(failing) > 1

    for rule_id in failing:
        at = _run(SCORECARD, _check_pick=rule_id)
        assert "The rows that failed" in _body(at), rule_id


def test_the_check_panel_shows_the_actual_rows():
    """The whole point of the drill-down. A check with samples must put their columns
    on the page, not a JSON blob — `SUBS_MSISDN_SENTINEL` is the case that matters,
    because twelve rows holding one literal is only legible down a column."""
    at = _run(SCORECARD, _check_pick="SUBS_MSISDN_SENTINEL")
    frames = [df.value for df in at.dataframe]
    assert any("PRIM_RSRC_VALU_TXT" in f.columns for f in frames), \
        "sampled rows are not rendered as columns"
    values = [f["PRIM_RSRC_VALU_TXT"].tolist() for f in frames
              if "PRIM_RSRC_VALU_TXT" in f.columns]
    assert any("service-number-unknown" in v for v in values)


def test_the_check_panel_names_the_element_a_cross_table_rule_attaches_to():
    """XREF_NAME_AGREEMENT covers the name element and carries no target column, so
    it can only attach by the explicit `cde_id` tag. If that path breaks, the panel
    reports a KYC check as watching nothing and gives no clue why. This assertion
    moved here from the deleted Data elements page."""
    at = _run(SCORECARD, _check_pick="XREF_NAME_AGREEMENT")
    shown = " ".join(str(c.value) for c in at.caption)
    assert "Customer name" in shown, shown


def test_the_check_panel_says_when_a_check_is_not_scored():
    """Two denominators live on the scorecard and the panel is where the difference
    becomes concrete. `SUBS_IMEI_NOT_NULL` is attached to an element, so it is
    scored; a check on an unregistered column must say plainly that it is not."""
    import pandas as pd

    cov_path = APP_DIR.parent / "fixtures" / "out" / "results.v_cde_coverage.parquet"
    runs_path = APP_DIR.parent / "fixtures" / "out" / "results.check_run.parquet"
    if not cov_path.exists():
        pytest.skip("fixture not built")

    cov = pd.read_parquet(cov_path)
    attached = {r for ids in cov["rule_ids"] for r in (list(ids) if ids is not None else [])}
    runs = pd.read_parquet(runs_path)
    latest = runs.loc[runs["run_ts"].idxmax(), "run_id"]
    failing = set(runs[(runs["run_id"] == latest) & (runs["status"] == "breach")]["rule_id"])

    unscored = sorted(failing - attached)
    assert unscored, "fixture no longer has a failing check outside the register"

    at = _run(SCORECARD, _check_pick=unscored[0])
    shown = " ".join(str(c.value) for c in at.caption)
    assert "does not move the quality figure" in shown


def test_the_scope_panel_replaces_the_data_elements_page():
    """`Data elements` was deleted. Everything anyone used it for has to be reachable
    from the scorecard, or the page was not folded in — it was dropped."""
    at = _run(SCORECARD, _scope_open=True)
    frames = [df.value for df in at.dataframe]
    listing = [f for f in frames if "Critical data element" in f.columns]
    assert listing, "the scope panel lists no elements"
    assert len(listing[0]) >= 10
    assert "Criticality" in listing[0].columns


def test_the_element_band_lists_every_element_with_its_kind_and_score():
    """The band is an inventory, not an issue queue. Every registered element is on
    it — a covered element is as much a fact about the register as a gap — and each
    carries the two things the band exists to report: what kind of element it is and
    how the data behind it scores."""
    at = _run(SCORECARD)
    rows = [str(m.value) for m in at.markdown
            if 'class="dq-rowgrid' in str(m.value) and "head" not in str(m.value)[:60]]
    band = [r for r in rows if "Customer email address" in r]
    assert band, "the element band does not list Customer email address"
    assert "Email address" in band[0], "the element's kind is not on its row"
    assert "%" in band[0], "the element's score is not on its row"

    body = _body(at)
    assert "10 registered elements" in body, "the band is not listing every element"
    # Covered elements are listed too, so the band cannot be read as a gap list.
    assert any("Mobile service number (MSISDN)" in r for r in rows)


def test_the_element_band_recommends_nothing():
    """A "What to do" column stood here until 2026-09-17 — "write a rule", "fix the
    rule's scope", "see COH b42685aa". Recommending the fix for a gap in the register
    is out of scope for this app; the band reports what the register holds."""
    at = _run(SCORECARD)
    body = _body(at)
    for advice in ["What to do", "write a rule", "fix the rule's scope",
                   "add a format rule", "Needs work"]:
        assert advice not in body, advice

    # And the panel behind the strip badge does not smuggle it back.
    panel = _body(_run(SCORECARD, _scope_open=True))
    assert "Needs work" not in panel


def test_an_unvalidated_element_shows_its_coverage_beside_its_score():
    """The quietest failure on the page. `Identity document number` is registered
    critical, has one check, and that check passes on every row — so it scores 100%
    while nothing examines what the column contains. The score alone would read as
    the healthiest element in the register, which is why the coverage column sits
    next to it rather than instead of it."""
    at = _run(SCORECARD)
    rows = [str(m.value) for m in at.markdown
            if 'class="dq-rowgrid' in str(m.value)]
    row = [r for r in rows if "Identity document number" in r]
    assert row, "the identity document element is not on the band"
    assert "Not validated" in row[0], row[0]


def test_failing_checks_filter_by_element_kind():
    """A cut the dimension grouping cannot make: `format` spans an email, a mobile
    number and a date of birth. Narrowing to one kind must drop the checks on every
    other kind and say what it is showing."""
    EMAIL = "Contact email contains an @"
    DOB = "Date of birth parses as a real ISO date"

    unfiltered = _body(_run(SCORECARD))
    assert EMAIL in unfiltered and DOB in unfiltered, \
        "the fixture no longer fails both an email and a DOB check — rewrite this"

    body = _body(_run(SCORECARD, _fail_kind="date_of_birth"))
    assert DOB in body, "the DOB check is not in a DOB filter"
    assert EMAIL not in body, "an email check survived a DOB filter"
    assert "date of birth" in body, "the foot does not say what the filter shows"


def test_checks_on_no_registered_element_are_filterable_rather_than_hidden():
    """14 of the 34 rules in the fixture are attached to no registered element. A
    filter shaped by the register that could only ever narrow to it would hide them
    behind a control that does not admit to hiding anything."""
    body = _body(_run(SCORECARD, _fail_kind="Not on a registered element"))
    assert "not on a registered element" in body.lower()
    # Attached checks are the half this option excludes.
    assert "Contact email contains an @" not in body


def test_the_element_panel_names_the_rules_contradicting_a_scope():
    """COH-B's root cause is an assertion the register makes, not something a human
    noticed, and this panel is the one place it is spelled out now."""
    at = _run(SCORECARD, _cde_pick="CDE_DEVICE_IMEI")
    shown = " ".join(str(c.value) for c in at.caption)
    assert "SUBS_IMEI_NOT_NULL" in shown, shown


def test_grouping_by_dimension_shows_every_dimension_that_has_a_failing_check():
    """The four dimensions stopped being cards and became a grouping. The prose that
    defines them — "Validity" is a term of art — has to survive the move."""
    at = _run(SCORECARD, _fail_group=True)
    body = _body(at)
    for name in ["Completeness", "Validity", "Consistency"]:
        assert name in body, name


def test_a_dimension_with_a_failing_check_never_reads_as_a_clean_100():
    """Consistency scores 99.9% with one check failing. Printed at zero decimals that
    is "100%", sitting beside the words that say it is failing — the header
    contradicting itself, with nothing to tell the reader which half is wrong.
    `theme.pct_text` is what stops it, and this is the case that motivated it."""
    from dq_app.ui import theme

    assert theme.pct_text(99.9) == "99.9"
    assert theme.pct_text(99.96) == "99.96"
    assert theme.pct_text(100.0) == "100"
    assert theme.pct_text(0.0) == "0"
    assert theme.pct_text(None) == "—"

    at = _run(SCORECARD, _fail_group=True)
    # Every group header printed here belongs to a dimension with at least one
    # failing check — the table only lists failing checks — so none of them may read
    # as a clean 100.
    headers = [str(m.value) for m in at.markdown if 'class="dq-dimgrp"' in str(m.value)]
    assert headers
    for header in headers:
        shown = re.search(r">([\d.]+)% scored<", header)
        assert not (shown and shown.group(1) == "100"), header

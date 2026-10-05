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
    "dq_app/ui/pages/thresholds.py",
    "dq_app/ui/pages/onboarding.py",
    "dq_app/ui/pages/onboarding_table.py",
    "dq_app/ui/pages/onboarding_add.py",
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


def _text(at) -> str:
    """Markdown and captions. `st.caption` is its own element type, so a page whose
    explanation lives in one reads as blank to `_body`."""
    return _body(at) + " " + " ".join(str(c.value) for c in at.caption)


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


def _cohorts():
    import pandas as pd

    path = APP_DIR.parent / "fixtures" / "out" / "results.cohort.parquet"
    if not path.exists():
        pytest.skip("fixture not built")
    return pd.read_parquet(path)


def test_the_claim_carries_the_verdict_the_model_actually_returned():
    """Seven fields the model produces used to survive only inside
    `model_input_payload`, where nothing queried them and no page showed them. They
    are columns now, and this asserts they reach the page rather than the JSON.

    Rendered on the largest cohort, which is COH-A: nine members, a rival the model
    declined to offer, and a defect in the data."""
    cohorts = _cohorts()
    target = cohorts.sort_values("member_count").iloc[-1]
    at = _run("dq_app/ui/pages/triage_detail.py", selected_cohort=target["cohort_id"])
    body = _body(at)

    assert "confidence" in body.lower(), "the model's confidence is not on the page"
    assert "The data is wrong" in body, "defect_location did not reach the page"
    # The evidence summary, itemised. One point checked verbatim: if `evidence_points`
    # stops being rendered, the paragraph above it still reads fine and nothing else
    # in this suite would notice.
    assert str(target["evidence_points"][0])[:40] in body
    assert str(target["recommended_steps"][0])[:40] in body
    assert "Who should act" in body
    assert "How we will know it worked" in body
    assert "Grouping: holds" in body


def test_a_rule_defect_says_so_rather_than_implying_it():
    """COH-B's whole point is that the 700 rows are correct and the rules are wrong.
    That verdict was the model's from the first run and had nowhere to go; the page
    has to say it in words, because a reader who infers it from the prose has to
    already know the answer."""
    cohorts = _cohorts()
    rule_defects = cohorts[cohorts["defect_location"] == "rule"]
    assert not rule_defects.empty, "no rule-defect cohort in the fixture — COH-B is it"

    at = _run("dq_app/ui/pages/triage_detail.py",
              selected_cohort=rule_defects.iloc[0]["cohort_id"])
    body = _text(at)
    assert "The rule is wrong" in body
    assert "correcting this data would make correct records wrong" in body.lower()


def test_neither_is_offered_as_an_answer_and_not_as_a_hedge():
    """`defect_location` has three values because two is not enough: the data can be
    correct and the rule reasonable, with the disagreement between them a business
    question. The page must not present that as uncertainty."""
    cohorts = _cohorts()
    neither = cohorts[cohorts["defect_location"] == "neither"]
    assert not neither.empty, "no 'neither' cohort in the fixture"

    at = _run("dq_app/ui/pages/triage_detail.py",
              selected_cohort=neither.iloc[0]["cohort_id"])
    body = _text(at)
    assert "Neither — a business question" in body
    assert "business question rather than a defect on either side" in body


def test_a_rival_reading_is_shown_where_there_is_one_and_absent_where_there_is_not():
    """Absence is a claim: the prompt requires the model to say where the evidence is
    equally consistent with another explanation, so a cohort with no rival is one
    where it asserted there is none. Both halves are pinned, because a component that
    silently renders nothing passes a smoke test either way."""
    cohorts = _cohorts()
    with_rival = cohorts[cohorts["rival_hypothesis"].notna()]
    without = cohorts[cohorts["rival_hypothesis"].isna()]
    assert not with_rival.empty and not without.empty, \
        "the fixture needs both a cohort with a rival reading and one without"

    at = _run("dq_app/ui/pages/triage_detail.py",
              selected_cohort=with_rival.iloc[0]["cohort_id"])
    assert "The evidence also fits" in _body(at)

    at = _run("dq_app/ui/pages/triage_detail.py",
              selected_cohort=without.iloc[0]["cohort_id"])
    assert "The evidence also fits" not in _body(at)


def test_prior_advice_is_shown_on_a_problem_that_has_been_here_before():
    """The spec's worked failure: a run blind to the register re-recommends what has
    already been tried. COH-D is the case — CTCT_PHN_FMT was closed and came back —
    and the page has to say what is different this time."""
    cohorts = _cohorts()
    repeat = cohorts[cohorts["prior_state"] != "none"]
    assert not repeat.empty, "no cohort with prior history in the fixture — COH-D is it"

    at = _run("dq_app/ui/pages/triage_detail.py",
              selected_cohort=repeat.iloc[0]["cohort_id"])
    body = _body(at)
    assert "These rules have been here before" in body
    assert "Different this time" in body


def test_no_recommended_step_can_be_executed():
    """The defining non-goal, checked where a reader meets it. The prompt forbids a
    write statement, the triage job's validator rejects one, a CHECK constraint on
    the table refuses one and `fixtures/verify.py` asserts it — this is the fourth
    place, and the only one that covers what the page actually prints."""
    import re as _re

    write = _re.compile(r"\b(UPDATE|MERGE\s+INTO|DELETE\s+FROM|TRUNCATE|DROP)\b")
    cohorts = _cohorts()
    for _, c in cohorts.iterrows():
        for step in list(c["recommended_steps"]) + [c["recommended_approach"]]:
            assert not write.search(str(step)), f"{c['cohort_id']}: {step[:60]!r}"


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
    reg = pd.read_parquet(path.parent / "config.rule_registry.parquet")
    latest_ver = reg.sort_values("rule_version").groupby("rule_id").tail(1)
    failing = failing[~failing.isin(latest_ver[latest_ver["status"] == "retired"]["rule_id"])]
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


def test_every_failing_check_is_on_a_registered_element():
    """Since 2026-09-28 a rule names its element, so the second denominator the
    scorecard used to carry -- checks on no registered column, not scored -- is
    empty by construction. The fixture must contain no such check, and the panel
    must not tell a scored check it is not."""
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
    # A rule retired after the run still has its verdict on it; it is history, and
    # the scorecard drops it rather than calling it unattached.
    reg = pd.read_parquet(APP_DIR.parent / "fixtures" / "out" / "config.rule_registry.parquet")
    latest_ver = reg.sort_values("rule_version").groupby("rule_id").tail(1)
    failing -= set(latest_ver[latest_ver["status"] == "retired"]["rule_id"])
    assert failing <= attached, sorted(failing - attached)

    at = _run(SCORECARD, _check_pick=sorted(failing)[0])
    shown = " ".join(str(c.value) for c in at.caption)
    assert "does not move the quality figure" not in shown


def test_the_scope_button_is_gone_because_the_element_list_replaced_it():
    """`Scored on 20 checks over 10 critical elements` opened a panel listing every
    element. The element list beside the failing checks is that list, so the button
    went on 2026-09-22 rather than leaving two ways to the same table."""
    at = _run(SCORECARD)
    assert not any(b.key == "_scope_btn" for b in at.button)
    assert "Scored on" not in _body(at)


def _rows(at, of: str) -> list[str]:
    """The markup of every clickable row in one of the scorecard's two lists — `of`
    is "elements" or "checks". Both are drawn by the same helper, so they are told
    apart by what only one of them prints: a check row counts its failing rows."""
    rows = [str(m.value) for m in at.markdown if '<span class="dq-el' in str(m.value)]
    is_check = lambda r: "failing rows" in r  # noqa: E731
    return [r for r in rows if is_check(r) == (of == "checks")]


def test_the_element_list_shows_five_by_default_and_every_element_on_request():
    """The list is an inventory sorted so its top is where to look first. Five rows
    by default; all nineteen one click away — a covered element is as much a fact
    about the register as a gap, so `All` lists every one of them with its score."""
    at = _run(SCORECARD)
    assert len(_rows(at, "elements")) == 5

    at = _run(SCORECARD, _elist_show="all")
    rows = _rows(at, "elements")
    assert len(rows) == 19, len(rows)
    email = [r for r in rows if "Customer email address" in r]
    assert email and "%" in email[0], "the element's score is not on its row"
    assert any("Mobile service number (MSISDN)" in r for r in rows)


def test_the_element_counts_add_up_to_the_register():
    """Below, meeting and unassessed are one partition of the register. If the three
    ever stop summing to the number of elements, a row is being counted twice or
    dropped, and the line is the only place a reader would see it."""
    body = _body(_run(SCORECARD))
    counts = re.search(r"(\d+) below target · (\d+) meeting target · (\d+) unassessed", body)
    assert counts, "the list no longer states how the register splits"
    assert sum(int(n) for n in counts.groups()) == 19


def test_the_largest_shortfall_is_first_and_picked_by_default():
    """Largest target gap first, and the page opens on it. Customer email address
    carries the 240 malformed addresses against a 0.5% tolerance. (Vulnerable customer
    indicator led at 0% until it was retired on 2026-10-01.)"""
    at = _run(SCORECARD)
    first = _rows(at, "elements")[0]
    assert "Customer email address" in first
    assert "below target" in first
    head = [str(m.value) for m in at.markdown if 'class="dq-elhd"' in str(m.value)]
    assert head and "Customer email address" in head[0]
    # A retired element and its retired rule leave the page entirely: not listed,
    # and not swept into "Not on a registered element" by a run that predates it.
    body = " ".join(str(m.value) for m in at.markdown)
    assert "Vulnerable customer indicator" not in body
    assert "Not on a registered element" not in body


def test_the_element_band_recommends_nothing():
    """A "What to do" column stood here until 2026-09-17 — "write a rule", "fix the
    rule's scope", "see COH b42685aa". Recommending the fix for a gap in the register
    is out of scope for this app; the band reports what the register holds."""
    at = _run(SCORECARD, _elist_show="all")
    body = _body(at)
    for advice in ["What to do", "write a rule", "fix the rule's scope",
                   "add a format rule", "Needs work"]:
        assert advice not in body, advice


def test_an_unvalidated_element_is_not_assessed_against_its_target():
    """The quietest failure on the page. `Identity document number` is registered
    critical, has one check, and that check passes on every row — so it scores 100%
    while nothing examines what the column contains. "Meets target" beside that
    would be the page vouching for data nobody has looked at; the row says what the
    register says instead."""
    at = _run(SCORECARD, _elist_show="all")
    row = [r for r in _rows(at, "elements") if "Identity document number" in r]
    assert row, "the identity document element is not on the list"
    assert "Not assessed · Not validated" in row[0], row[0]
    assert "Meets target" not in row[0]


def test_picking_an_element_lists_its_checks_and_no_other_element_s():
    """The element list is the filter. Picking Customer date of birth must show the
    checks on it — passing ones too, since the score is all of them — and none of
    the email checks, and say which element it is showing."""
    EMAIL = "Contact email contains an @"
    DOB = "Date of birth parses as a real ISO date"

    at = _run(SCORECARD, _elem_scope="CDE_CUST_EMAIL")
    assert EMAIL in " ".join(_rows(at, "checks")), \
        "the fixture no longer fails that email check — rewrite this"

    at = _run(SCORECARD, _elem_scope="CDE_CUST_DOB")
    rows = " ".join(_rows(at, "checks"))
    assert DOB in rows, "the DOB check is not listed under the DOB element"
    assert EMAIL not in rows, "an email check survived picking the DOB element"
    head = [str(m.value) for m in at.markdown if 'class="dq-elhd"' in str(m.value)]
    assert head and "Customer date of birth" in head[0], "the pane does not say what it shows"


def test_the_check_breakdown_lists_passing_checks_with_their_own_target():
    """An element's score is every check on it, so a breakdown of only the failures
    cannot be added back up to the figure above it. Customer contact mobile number
    has one check failing and one passing; both are listed, each against the limit
    it was judged on."""
    at = _run(SCORECARD, _elem_scope="CDE_CUST_MOBILE")
    rows = _rows(at, "checks")
    assert len(rows) == 2, rows
    assert any("Below target" in r for r in rows)
    assert any("Meets target" in r for r in rows)
    assert all("\u2265 " in r for r in rows), "a check row is missing its target"


def test_a_passing_check_opens_too():
    """Every row of the breakdown opens the drawer. A passing check has the same
    rule and the same arithmetic and no failed rows, and must say so rather than
    print an empty sample table under "The rows that failed"."""
    at = _run(SCORECARD, _check_pick="CTCT_MOBL_FMT")
    shown = " ".join(str(c.value) for c in at.caption)
    assert "No row failed this check" in shown
    assert "The rows that failed" not in _body(at)


def test_the_scorecard_has_a_way_into_the_triage_queue():
    """The open-problems count is a button, not a figure: it is the page's link to
    the queue, and it went missing once already when the tiles were redrawn."""
    at = _run(SCORECARD)
    assert any(b.key == "_open_dqrow_op_queue" for b in at.button)
    assert "Open problems" in _body(at)


def test_an_element_links_to_the_problem_its_failing_checks_belong_to():
    """Until 2026-10-01 every failing check row named its problem. The breakdown
    rows do not, so the pane carries the problem itself: one row per problem,
    titled as the queue titles it, and it opens that problem."""
    from dq_app.data import adapter
    from dq_app.domain import metrics

    runs = adapter.get_check_runs()
    owner = metrics.live_cohorts(runs, adapter.get_cohorts())
    cohort_id = owner["CTCT_EML_FMT"]
    title = _titles()[cohort_id][0]

    at = _run(SCORECARD, _elem_scope="CDE_CUST_EMAIL")
    assert any(b.key == f"_open_dqrow_pb_{cohort_id}" for b in at.button), \
        "the email element does not link to the problem carrying its checks"
    assert "Triage · 1" in [t.label for t in at.tabs]
    assert title in _body(at)


def test_an_element_with_nothing_failing_links_to_no_problem():
    at = _run(SCORECARD, _elem_scope="CDE_CUST_KEY")
    assert "Triage" in [t.label for t in at.tabs]
    assert not any(str(b.key).startswith("_open_dqrow_pb_") for b in at.button)
    assert "no problem to open" in _text(at)


def test_the_unattached_entry_is_absent_when_every_check_names_an_element():
    """`Not on a registered element` was its own entry while 14 of 34 rules attached
    to nothing. Every rule names its element now, so the entry has nothing to list
    and must not appear -- an empty bucket that still shows reads as a finding."""
    at = _run(SCORECARD, _elist_show="all")
    assert "Not on a registered element" not in _body(at)
    assert "Not counted in the quality score" not in _body(at)


def test_an_element_shows_its_score_against_its_target():
    """The pane's point: the element's score, the same row-weighted arithmetic as the
    headline over that element's own checks, beside the target the register sets on
    it. Customer email address is nine checks, 522 bad rows of 8,993 scanned — 94.2%
    — against a 0.5% tolerance."""
    at = _run(SCORECARD, _elem_scope="CDE_CUST_EMAIL")
    head = [str(m.value) for m in at.markdown if 'class="dq-elhd"' in str(m.value)]
    assert head, "the pane has no element header"
    assert "Customer email address" in head[0]
    assert ">94.2%<" in head[0], head[0]
    assert "Target \u2265 99.5%" in head[0]
    assert "5.3 pts below" in head[0]
    over = [str(m.value) for m in at.markdown if 'class="dq-elover"' in str(m.value)]
    assert over and "since last run" in over[0] and "dq-trend" in over[0], \
        "the Overview tab has no trend"


def test_every_run_on_a_trend_can_be_hovered_for_its_reading():
    """Both trend charts carry one hover column per run drawn, each with the run's
    date, its score and where that stood against the target. Customer email address
    sat at 100% until its checks began failing and ends 5.3 points under a 99.5%
    target, so the one chart exercises both wordings — and the latest run's reading
    has to be the figure in the header above it."""
    import re

    at = _run(SCORECARD, _elem_scope="CDE_CUST_EMAIL")
    over = [str(m.value) for m in at.markdown if 'class="dq-elover"' in str(m.value)][0]
    tips = re.findall(r'<span class="tip"[^>]*><b>([^<]+)</b><span>([^<]+)</span>', over)
    drawn = over.split("<polyline points=\"")[1].split('"')[0].split()
    assert tips and len(tips) == len(drawn), (len(tips), len(drawn))
    assert tips[0][1] == "100% · meets target", tips[0]
    assert tips[-1][1] == "94.2% · 5.3 pts below target", tips[-1]

    hero = [str(m.value) for m in at.markdown if 'class="dq-card dq-hero"' in str(m.value)][0]
    assert hero.count('<span class="pt"') == len(
        hero.split("<polyline points=\"")[1].split('"')[0].split())

    # No target drawn means no verdict in the bubble either — same rule as the line.
    at = _run(SCORECARD, _elem_scope="CDE_BILLING_ACCOUNT", _elist_show="all")
    over = [str(m.value) for m in at.markdown if 'class="dq-elover"' in str(m.value)][0]
    assert 'class="tip"' in over and "target" not in over.split('class="pts"')[1]


def test_the_element_card_is_four_tabs_labelled_with_what_is_behind_them():
    """The card is one height whatever the element holds, because everything that
    varies in length is behind a tab that scrolls inside. Stacked, nine checks ran
    it to three times the height of the list beside it. Each label carries its
    count, so nobody opens a tab to find out whether there is anything in it."""
    at = _run(SCORECARD, _elem_scope="CDE_CUST_EMAIL")
    labels = [t.label for t in at.tabs]
    assert [lb.split(" · ")[0] for lb in labels] == [
        "Overview", "Checks", "Sample rows", "Triage"], labels
    assert labels[1] == "Checks · 9" and labels[3] == "Triage · 1", labels
    assert re.fullmatch(r"Sample rows · [\d,]+", labels[2]), labels

    # An element with nothing failing has nothing to count, and says so in words.
    at = _run(SCORECARD, _elem_scope="CDE_CUST_KEY")
    assert [t.label for t in at.tabs][2:] == ["Sample rows", "Triage"]


def test_the_sample_rows_tab_shows_the_actual_rows_of_the_check_picked():
    """The rows behind the counts, without opening a drawer: one check at a time,
    as the columns they are. Same rows and same cap as the check drawer — the tab
    is a second door onto the one PII surface, not a wider one."""
    at = _run(SCORECARD, _elem_scope="CDE_CUST_MSISDN")
    picker = [sb for sb in at.selectbox if sb.key == "_rows_check_CDE_CUST_MSISDN"]
    assert picker, "no check picker in the Sample rows tab"
    assert len(picker[0].options) == 2, picker[0].options
    frames = [df.value for df in at.dataframe]
    assert any("PRIM_RSRC_VALU_TXT" in f.columns for f in frames), \
        "sampled rows are not rendered as columns in the tab"

    picker[0].select("SUBS_MSISDN_SENTINEL").run()
    assert not at.exception
    values = [f["PRIM_RSRC_VALU_TXT"].tolist() for f in (df.value for df in at.dataframe)
              if "PRIM_RSRC_VALU_TXT" in f.columns]
    assert any("service-number-unknown" in v for v in values)


def test_the_overall_figure_states_its_target():
    """The headline's target is the element tolerances weighted by the rows the
    score is — `targets.blended_target`. The card has to print it, say how far off
    the score is, and draw it."""
    hero = [str(m.value) for m in _run(SCORECARD).markdown
            if 'class="dq-card dq-hero"' in str(m.value)]
    assert hero, "no headline card"
    assert re.search(r"Target \u2265 9\d(\.\d+)?%", hero[0]), hero[0]
    assert "below</span>" in hero[0]
    assert "stroke-dasharray" in hero[0], "the target line is not drawn"
    assert "checked rows passed" in hero[0], "the operands are gone"


def test_the_page_renders_with_no_tolerance_declared(monkeypatch):
    """The workspace until `migrate_cde_scope.sql` runs: `config.cde_registry` has no
    `tolerance_pct` column at all, and the deployed app reads that table. The page
    has to say there is no target, not assume one and not fall over."""
    from dq_app.data import adapter

    current = adapter.get_cde_registry_current()
    monkeypatch.setattr(adapter, "get_cde_registry_current",
                        lambda: current.drop(columns=["tolerance_pct"]))

    at = _run(SCORECARD, _elist_show="all")
    body = _body(at)
    assert "No target" in body
    assert "Target \u2265" not in body
    assert "0 below target · 0 meeting target · 19 unassessed" in body
    rows = _rows(at, "elements")
    assert len(rows) == 19
    assert not any("Meets target" in r or "pts below" in r for r in rows)


def test_a_scope_mismatch_score_is_not_coloured_as_bad_data():
    """Primary billing account scores 50%, and the register says the rule is wrong,
    not the data. Neither the list nor the pane may print that in red or call it
    below target, and the one rule the register disputes is labelled as disputed."""
    from dq_app.ui import theme

    red = theme.TONE["critical"]["fg"]
    at = _run(SCORECARD, _elem_scope="CDE_BILLING_ACCOUNT", _elist_show="all")
    head = [str(m.value) for m in at.markdown if 'class="dq-elhd"' in str(m.value)][0]
    assert "Scope mismatch" in head and "Not assessed" in head
    assert red not in head and "dq-below" not in head
    # No target line either: a dashed line 49 points above the series is the same
    # verdict, drawn instead of written.
    over = [str(m.value) for m in at.markdown if 'class="dq-elover"' in str(m.value)][0]
    assert "dq-trend" in over and "stroke-dasharray" not in over and red not in over

    row = [r for r in _rows(at, "elements") if "Primary billing account" in r][0]
    assert red not in row and "below target" not in row

    check = _rows(at, "checks")[0]
    assert "Rule scope disputed" in check and red not in check


def test_the_element_panel_names_the_rules_contradicting_a_scope():
    """COH-B's root cause is an assertion the register makes, not something a human
    noticed, and this panel is the one place it is spelled out now."""
    at = _run(SCORECARD, _cde_pick="CDE_DEVICE_IMEI")
    shown = " ".join(str(c.value) for c in at.caption)
    assert "SUBS_IMEI_NOT_NULL" in shown, shown


def test_a_check_row_carries_its_dimension():
    """The four dimensions were cards, then a grouping toggle, and are now a line in
    each check's hover text and a badge in its drawer. "Validity" is a term of art,
    so wherever it is printed it is still defined."""
    at = _run(SCORECARD, _elem_scope="CDE_CUST_EMAIL")
    body = _body(at)
    assert "Validity — Does the value look like what it claims to be." in body
    assert "Completeness — Is the value there at all." in body

    at = _run(SCORECARD, _check_pick="CTCT_EML_FMT")
    assert "conforms to the shape it is supposed to have" in _body(at)


def test_a_failing_score_never_reads_as_a_clean_100():
    """99.9% printed at zero decimals is "100%", sitting beside the words that say
    it is failing — the row contradicting itself, with nothing to tell the reader
    which half is wrong. `theme.pct_text` is what stops it."""
    from dq_app.ui import theme

    assert theme.pct_text(99.9) == "99.9"
    assert theme.pct_text(99.96) == "99.96"
    assert theme.pct_text(100.0) == "100"
    assert theme.pct_text(0.0) == "0"
    assert theme.pct_text(None) == "—"

    # `Contact email is present` fails one row in a thousand: 99.9%, below a
    # zero-tolerance limit.
    at = _run(SCORECARD, _elem_scope="CDE_CUST_EMAIL")
    row = [r for r in _rows(at, "checks") if "Contact email is present" in r]
    assert row, "the fixture no longer has the one-in-a-thousand email check"
    assert ">99.9%<" in row[0] and "Below target" in row[0], row[0]


# --- Titles, elements and tabs (2026-09-22) ----------------------------------


def _titles():
    from dq_app.data import adapter
    from dq_app.ui import components

    cov = adapter.get_cde_coverage()
    reg = adapter.get_rule_registry_current()
    out = {}
    for _, c in adapter.get_cohorts().iterrows():
        els, loose = components.cohort_elements(c["member_rule_ids"], cov)
        out[c["cohort_id"]] = (components.problem_title(c, els, reg), els, loose, c)
    return out


def test_every_problem_title_names_what_it_is_about_and_what_kind_of_wrong():
    """A title is `<element or column> — <verdict>`, never the hypothesis's first
    sentence: COH-B's first sentence is "Neither of these is a data defect", which
    names nothing."""
    from dq_app.ui import theme

    verdicts = set(theme.DEFECT_VERDICT.values()) | {"failing checks"}
    for cid, (title, els, _, c) in _titles().items():
        subject, sep, verdict = title.rpartition(" — ")
        assert sep and subject, (cid, title)
        assert verdict in verdicts, (cid, title)
        if els:
            assert els[0]["name"] in subject, (cid, title)


def test_the_rule_defect_title_says_the_rule_is_wrong_and_names_both_elements():
    coh_b = [v for v in _titles().values() if "SUBS_IMEI_NOT_NULL" in
             list(v[3]["member_rule_ids"])][0]
    title, els, _, _ = coh_b
    assert title.endswith("rule flags valid rows")
    assert "Device IMEI" in title and "Primary billing account" in title
    assert {e["coverage_gap"] for e in els} == {"scope_mismatch"}


def test_every_problem_names_an_element_and_the_fallback_still_works():
    """Since 2026-09-28 every rule names its element, so no problem is on no
    registered element and the column fallback in `components.problem_title` has
    no fixture case. It stays, for a registry that predates the rule, and is
    exercised here directly rather than through a problem that cannot exist."""
    import pandas as pd
    from dq_app.ui import components

    bare = [v for v in _titles().values() if not v[1]]
    assert not bare, "a problem on no registered element -- a rule attached to nothing"

    cohorts = _cohorts()
    registry = pd.read_parquet(
        APP_DIR.parent / "fixtures" / "out" / "config.rule_registry.parquet")
    target = cohorts.sort_values("member_count").iloc[-1]
    title = components.problem_title(target, [], registry, 140)
    assert title and "—" in title, title
    assert "EML_ID" in title or "email" in title.lower(), title


def test_an_element_is_one_chip_however_many_columns_bind_it():
    """Customer name is bound to three columns and is one element, the same
    one-row-per-element count the scorecard's element table uses."""
    for title, els, _, _ in _titles().values():
        ids = [e["cde_id"] for e in els]
        assert len(ids) == len(set(ids)), title


def test_the_detail_page_is_six_tabs_with_counts():
    target = _cohorts().sort_values("member_count").iloc[-1]
    at = _run("dq_app/ui/pages/triage_detail.py", selected_cohort=target["cohort_id"])
    labels = [t.label for t in at.tabs]
    assert [lb.split(" · ")[0] for lb in labels] == [
        "Diagnosis", "What to do", "Evidence", "Lineage", "Decisions", "Stored record"]
    assert labels[1] == f"What to do · {len(target['recommended_steps'])} steps"
    body = _body(at)
    # The advice and the blast radius are in their own tabs, not under the claim.
    assert "Tables with bad rows" in body and "Read downstream" in body
    for t in target["blast_radius_tables"]:
        assert str(t) in body


def test_the_detail_header_carries_the_title_the_claim_and_the_elements():
    target = _cohorts().sort_values("member_count").iloc[-1]
    title, els, loose, _ = _titles()[target["cohort_id"]]
    at = _run("dq_app/ui/pages/triage_detail.py", selected_cohort=target["cohort_id"])
    body = _body(at)
    assert title in body
    assert "A change to the CRM contact export" in body   # the claim, under the title
    pills = at.get("button_group")
    assert pills, "no element pills on the detail page"
    if loose:
        assert f"{len(loose)} checks on no registered element" in body
    else:
        assert "on no registered element" not in body


def test_an_element_pill_opens_the_element_drawer():
    target = _cohorts().sort_values("member_count").iloc[-1]
    _, els, _, _ = _titles()[target["cohort_id"]]
    at = _run("dq_app/ui/pages/triage_detail.py", selected_cohort=target["cohort_id"],
              _detail_cde_pick=els[0]["cde_id"])
    assert any(b.key == "_elem_close" for b in at.button), "the drawer did not open"
    at.button(key="_elem_close").click().run()
    assert not at.exception
    assert not any(b.key == "_elem_close" for b in at.button), "Close did not close it"


def test_the_queue_shows_the_new_titles():
    at = _run("dq_app/ui/pages/triage.py")
    body = _body(at)
    assert "rule flags valid rows" in body
    assert "Neither of these is a data defect</span>" not in body

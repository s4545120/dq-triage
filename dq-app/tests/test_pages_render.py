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
    # Outside the problem link: since 2026-09-22 a problem's title names its element,
    # so a failing-check row that links to COH-A mentions the element too.
    band = [r for r in rows if "Customer email address" in r.split('class="link"')[0]]
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


def _fail_rows(at) -> list[str]:
    """The failing-checks table's rows — every clickable row that is not an element
    in the list beside it."""
    return [str(m.value) for m in at.markdown
            if 'class="dq-rowgrid' in str(m.value) and "dq-eldot" not in str(m.value)
            and "Show the checks" not in str(m.value) and "head" not in str(m.value)[:60]]


def test_picking_an_element_narrows_the_failing_checks_to_it():
    """The element list is the filter. Picking Customer date of birth must drop the
    checks on every other element and say what it is showing — the cut the
    dimension grouping cannot make, because `format` spans an email, a mobile number
    and a date of birth."""
    EMAIL = "Contact email contains an @"
    DOB = "Date of birth parses as a real ISO date"

    unfiltered = _body(_run(SCORECARD))
    assert EMAIL in unfiltered and DOB in unfiltered, \
        "the fixture no longer fails both an email and a DOB check — rewrite this"

    at = _run(SCORECARD, _elem_scope="CDE_CUST_DOB")
    rows = " ".join(_fail_rows(at))
    assert DOB in rows, "the DOB check is not listed under the DOB element"
    assert EMAIL not in rows, "an email check survived picking the DOB element"
    assert "of 21 failing checks · Customer date of birth" in _body(at), \
        "the foot does not say what the pane shows"


def test_checks_on_no_registered_element_have_their_own_entry_rather_than_hiding():
    """14 of the 34 rules in the fixture are attached to no registered element. A
    list shaped by the register that could only ever narrow to it would hide them
    behind a control that does not admit to hiding anything."""
    at = _run(SCORECARD)
    assert "Not on a registered element" in _body(at), "no entry for unattached checks"

    at = _run(SCORECARD, _elem_scope="__none__")
    rows = " ".join(_fail_rows(at))
    assert "Special-care status" in rows
    # Attached checks are the half this entry excludes.
    assert "Contact email contains an @" not in rows
    assert "do not move the quality figure" in _body(at)


def test_an_element_shows_its_own_score_in_the_pane():
    """The drill-down's point: the element's DQ score, the same row-weighted
    arithmetic as the headline over that element's own checks. Customer email address
    is 7 checks, 521 bad rows of 6,993 scanned: 92.5%, printed 92.6 at one place."""
    at = _run(SCORECARD, _elem_scope="CDE_CUST_EMAIL")
    head = [str(m.value) for m in at.markdown if 'class="dq-elhd"' in str(m.value)]
    assert head, "the pane has no element header"
    assert "Customer email address" in head[0]
    assert re.search(r">9\d\.\d<span>%</span>", head[0]), head[0]
    assert "since" in head[0] and "dq-spark" in head[0], "no trend beside the score"


def test_a_scope_mismatch_score_is_not_coloured_as_bad_data():
    """Primary billing account scores 50%, and the register says the rule is wrong,
    not the data. The pane prints the figure and the coverage note, never red."""
    from dq_app.ui import theme

    at = _run(SCORECARD, _elem_scope="CDE_BILLING_ACCOUNT")
    head = [str(m.value) for m in at.markdown if 'class="dq-elhd"' in str(m.value)][0]
    assert "Scope mismatch" in head
    assert theme.TONE["critical"]["fg"] not in head.split('class="r"')[1].split("<svg viewBox=\"0 0 120")[0]


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


def test_a_problem_on_no_registered_element_falls_back_to_its_columns():
    """Three problems touch no element. Their titles name the columns their checks
    read rather than going blank or inventing an element."""
    bare = [v for v in _titles().values() if not v[1]]
    assert bare, "every cohort has an element — the fallback is untested"
    for title, _, loose, _ in bare:
        assert loose, title
        subject = title.rpartition(" — ")[0]
        # A column, or a cross-table check's own name. Never one bare table.
        assert subject not in {"subs_c", "ctct_c"}, title


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
    assert f"{len(loose)} checks on no registered element" in body


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

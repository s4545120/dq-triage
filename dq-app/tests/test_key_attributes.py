"""The key attribute register, its migration rules, and the app after the migration.

Three things are pinned here:

* the register and rules in key_attributes/ hold together: every rule names a key
  attribute that binds its column, and none carries the source queries' Spark traps;
* universe rules go to an attribute with no migration rule, and only to one;
* once the mock register is retired (key_attributes/frames.py, the pandas copy of
  sql/migrate_key_attributes.py), every page renders, the mock problems leave Triage,
  and the pages say what is registered instead of "no check runs".
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "key_attributes"))
sys.path.insert(0, str(REPO / "sql"))

import register as ka  # noqa: E402
import rules as ka_rules  # noqa: E402
import universe  # noqa: E402

RULE_TYPES = {"not_null", "format", "uniqueness", "consistency", "referential", "sentinel",
              "variance", "freshness", "volume"}
SEVERITIES = {"P1_block", "P2_alert", "P3_monitor"}


# --- The register and its rules ------------------------------------------------------

def test_the_register_is_the_sheets_in_scope_rows():
    assert len(ka.KEY_ATTRIBUTES) == 22
    assert len({a.cde_id for a in ka.KEY_ATTRIBUTES}) == 22
    assert all(a.cde_id.startswith("KA_") for a in ka.KEY_ATTRIBUTES)
    assert all(a.table.startswith("prod.udp_brnz_nrt_tech_view.") for a in ka.KEY_ATTRIBUTES)
    # The sheet's "Out of scope" rows are not registered.
    for gone in ("E_NUM", "VALIDITY_END", "X_CARD_NUMBER", "is_primary_for_org", "end_ts"):
        assert gone not in {a.column for a in ka.KEY_ATTRIBUTES}


def test_every_rule_names_a_key_attribute_that_binds_its_column():
    for r in universe.all_rules():
        a = ka.BY_ID[r.cde_id]
        assert (a.table, a.column) == (r.table, r.column), r.rule_id
        assert r.column in r.rule_expr, r.rule_id
        assert r.rule_type in RULE_TYPES and r.severity in SEVERITIES, r.rule_id


def test_rule_ids_are_unique_and_new():
    ids = [r.rule_id for r in universe.all_rules()]
    assert len(ids) == len(set(ids))
    assert all(i.startswith("KA_") for i in ids)


@pytest.mark.parametrize("r", universe.all_rules(), ids=lambda r: r.rule_id)
def test_no_rule_carries_the_source_queries_spark_traps(r):
    for sql in filter(None, (r.rule_expr, r.scope_filter)):
        # A POSIX class in Java regex is a set of letters: [[:space:]] matches 's'.
        assert "[[:" not in sql
        # '' INSIDE a Spark literal is two adjacent literals, not an escaped quote. An
        # empty literal ('' after a comma, an operator or a paren) is fine.
        assert not re.search(r"(?<=[^\s,(=])''(?=[^\s,)])", sql)
        # Every literal closes: an odd count of unescaped quotes would swallow the rest.
        assert len(re.findall(r"(?<!\\)'", sql)) % 2 == 0
        # The runner rewrites dq.fn. in rule_expr only, and these call no helper.
        assert "dq.fn." not in sql


def test_every_attribute_has_migration_rules_today():
    assert universe.uncovered() == []
    assert universe.universe_rules() == []


def test_an_attribute_with_no_migration_rule_gets_the_universe_rules():
    extra = ka.KeyAttribute("KA_CONTACT_SALUTATION", "Salutation", ka.CONTACT, "SALUTATION",
                            "other", "Mr, Ms ...", False)
    got = universe.universe_rules([*ka.KEY_ATTRIBUTES, extra])
    assert {r.cde_id for r in got} == {"KA_CONTACT_SALUTATION"}
    assert len(got) == 4 and all(r.universe and "_UNIV_" in r.rule_id for r in got)
    assert all(r.severity == "P3_monitor" for r in got)


def test_every_category_the_analysis_lists_is_registered_or_accounted_for():
    """The PDF's contact-name categories, each a rule or a NOT_REGISTERED entry."""
    first = {r.rule_id.removeprefix("KA_CONTACT_FIRST_NAME_") for r in ka_rules.MIGRATION_RULES
             if r.cde_id == "KA_CONTACT_FIRST_NAME"}
    assert {"NULL_OR_BLANK", "LEADING_OR_TRAILING_WHITESPACE", "PLACEHOLDER_VALUE",
            "COMPANY_NAME_INDICATOR", "STARTS_WITH_TITLE", "STARTS_WITH_NON_LETTER",
            "UNRELATED_IDENTIFIER_NOTE_OR_ADDRESS", "CONSECUTIVE_PUNCTUATION",
            "INVALID_CHARACTERS_OR_STRUCTURE", "CONTROL_CHARACTERS",
            "HYPHEN_OR_APOSTROPHE_EDGE", "EXCEEDS_40_CHARACTERS",
            "DECEASED_WITHOUT_ESTATE_NAME", "ESTATE_NAME_NOT_DECEASED"} == first
    assert "FIRST_NAME LESS_THAN_ONE_CHARACTER" in ka_rules.NOT_REGISTERED


# --- The migration ---------------------------------------------------------------------

def test_the_migration_retires_the_mock_register_and_is_rerunnable():
    import migrate_key_attributes as mig
    _, stmts = mig.build("workspace", "dq_triage", "dq_")
    inserts = [(lab, sql) for lab, kind, sql in stmts if kind == "insert"]
    n_rules = len(universe.all_rules())
    assert len(inserts) == 3 + len(ka.KEY_ATTRIBUTES) + n_rules + len(ka.TABLES)
    retire = [sql for lab, sql in inserts if lab.startswith("retire:")]
    assert len(retire) == 3
    assert all("status <> 'retired'" in s for s in retire)
    assert all("NOT LIKE 'KA\\\\_%'" in s or "NOT IN (" in s for s in retire)
    for lab, sql in inserts:
        if not lab.startswith("retire:"):
            assert "WHERE  NOT EXISTS" in sql, lab
    rule_sql = [sql for lab, sql in inserts if lab.startswith("rule:")]
    assert all("'shadow'" in s and "CAST(NULL AS TIMESTAMP)" in s for s in rule_sql)


# --- The app after the migration -------------------------------------------------------

st_testing = pytest.importorskip("streamlit.testing.v1")
APP = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def migrated(tmp_path_factory):
    import frames
    base = REPO / "fixtures" / "out"
    if not (base / "config.cde_registry.parquet").exists():
        pytest.skip("fixture not built")
    return frames.apply(base, tmp_path_factory.mktemp("key_attributes"))


@pytest.fixture
def page(migrated, monkeypatch):
    import streamlit as st
    monkeypatch.setenv("DQ_FIXTURE_DIR", str(migrated))
    monkeypatch.setenv("DQ_APP_DATA_SOURCE", "local")
    st.cache_data.clear()

    def _open(name: str):
        at = st_testing.AppTest.from_file(str(APP / f"dq_app/ui/pages/{name}.py"),
                                          default_timeout=90)
        at.run()
        assert not at.exception, [e.message for e in at.exception]
        return at

    yield _open
    st.cache_data.clear()


def _text(at) -> str:
    return (" ".join(str(m.value) for m in at.markdown) + " "
            + " ".join(str(c.value) for c in at.caption))


@pytest.mark.parametrize("name", ["scorecard", "tables", "triage", "rule_registry",
                                  "thresholds", "elements", "onboarding"])
def test_every_page_renders_after_the_migration(page, name):
    page(name)


def test_triage_shows_no_mock_problem(page):
    body = _text(page("triage"))
    assert "No problems have been raised on the current checks." in body
    assert "14 raised on checks since retired are kept as history." in body
    assert "Unattributed checks" not in body


def test_the_scorecard_says_what_is_registered_instead_of_no_runs(page):
    body = _text(page("scorecard"))
    n = len(universe.all_rules())
    assert f"22 key attributes are registered, with 0 active and {n} shadow checks" in body
    assert "No check runs available" not in body


def test_the_rules_page_lists_key_attributes_and_no_mock_element(page):
    body = _text(page("rule_registry"))
    assert "Contact first name" not in body or "Key attributes" in body
    assert "Customer email address" not in body and "Device IMEI" not in body
    assert "Expressions verified" not in body
    assert "On universe rules" in body


def test_no_mock_tolerance_advice_is_left_to_decide(page):
    body = _text(page("thresholds"))
    assert "No tolerance advice yet." in body


# --- Pointing the register at a source catalog -----------------------------------------

def test_the_source_migration_moves_only_the_catalog_and_is_guarded():
    import migrate_key_attributes_source as src
    _, stmts = src.build("workspace", "workspace", "dq_triage", "dq_")
    inserts = {lab: sql for lab, kind, sql in stmts if kind == "insert"}
    assert sum(lab.startswith("cde:") for lab in inserts) == len(ka.KEY_ATTRIBUTES)
    # Every rule statement rewrites target_table and nothing about status.
    for lab, sql in inserts.items():
        if lab.startswith("rules:"):
            assert "'workspace.udp_brnz_nrt_tech_view." in sql and "r.status," in sql
            assert "r.target_table IN ('prod.udp_brnz_nrt_tech_view." in sql
    # Mock tables carry their own codes: a code is never reused.
    assert "'KAW_CONTACT'" in inserts["select:workspace.udp_brnz_nrt_tech_view.table_contact_hist"]
    assert all("NOT EXISTS" in s or "<> 'retired'" in s or "= 'retired'" in s
               or "NOT array_contains" in s for s in inserts.values())


def test_pointing_back_at_prod_keeps_the_prod_codes():
    import migrate_key_attributes_source as src
    _, stmts = src.build("prod", "workspace", "dq_triage", "dq_")
    sel = {lab: sql for lab, kind, sql in stmts if lab.startswith("select:")}
    assert "'KA_CONTACT'" in sel["select:prod.udp_brnz_nrt_tech_view.table_contact_hist"]
    assert any(lab.startswith("reselect:prod.") for lab, _, _ in stmts)


def test_the_scorecard_counts_no_retired_problem_as_open(migrated, monkeypatch):
    """Rendered with a key-attribute run, so the page gets past its no-runs note."""
    import pandas as pd
    import streamlit as st
    base = pd.read_parquet(migrated / "results.check_run.parquet")
    row = base.iloc[[0]].copy()
    row["rule_id"], row["target_table"] = "KA_CONTACT_FIRST_NAME_PLACEHOLDER_VALUE", ka.CONTACT
    row["run_id"], row["status"] = "ka-run", "pass"
    row["run_ts"] = pd.Timestamp("2026-10-12 03:00:00")
    out = migrated.parent / "with_run"
    out.mkdir(exist_ok=True)
    for f in migrated.glob("*.parquet"):
        (out / f.name).write_bytes(f.read_bytes())
    pd.concat([base, row]).to_parquet(out / "results.check_run.parquet", index=False)
    reg = pd.read_parquet(out / "config.rule_registry.parquet")
    reg.loc[reg["rule_id"] == "KA_CONTACT_FIRST_NAME_PLACEHOLDER_VALUE", "status"] = "active"
    reg.to_parquet(out / "config.rule_registry.parquet", index=False)
    monkeypatch.setenv("DQ_FIXTURE_DIR", str(out))
    monkeypatch.setenv("DQ_APP_DATA_SOURCE", "local")
    st.cache_data.clear()
    at = st_testing.AppTest.from_file(str(APP / "dq_app/ui/pages/scorecard.py"),
                                      default_timeout=90)
    at.run()
    st.cache_data.clear()
    assert not at.exception, [e.message for e in at.exception]
    body = _text(at)
    assert "Open problems" in body and "0 waiting on a person" in body, re.sub(r"<[^>]+>|\s+", " ", body)[-1500:]

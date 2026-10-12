"""A violation sample stores the row's key and the columns the rule reads, never the rest.

`jobs/run_checks.sample_keep` is the one definition. It is pinned here over every shape
the runner has, and over the real rule register, because a rule whose own column were
dropped would show a steward a sample without the value that failed.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]

CTCT = ["CTCT_KEY", "CTCT_ID", "FRST_NM", "LAST_NM", "BRTH_TS", "EML_ID", "EML_STTS_CD",
        "IDNT_DOC_1_NO", "MOBL_NO"]


@pytest.fixture
def rc():
    sys.path.insert(0, str(ROOT / "jobs"))
    import run_checks
    yield run_checks
    sys.path.remove(str(ROOT / "jobs"))


def _rule(rc, expr, col="EML_ID", scope=None, **kw):
    return rc.Rule("R", 1, "format", expr, "c.s.ctct", col, scope, 0.0, "P2_alert",
                   "active", **kw)


def _kept(rc, rule, columns=CTCT, keys=("CTCT_KEY",)):
    return [columns[i] for i in rc.sample_keep(rule, columns, list(keys) if keys else None)]


def test_a_row_level_rule_keeps_its_column_and_the_key(rc):
    r = _rule(rc, "NOT dq_fn_is_valid_email_v1(EML_ID)")
    assert _kept(rc, r) == ["CTCT_KEY", "EML_ID"]


def test_the_scope_filter_columns_are_kept(rc):
    r = _rule(rc, "EML_ID IS NULL", scope="EML_STTS_CD = 'A'")
    assert _kept(rc, r) == ["CTCT_KEY", "EML_ID", "EML_STTS_CD"]


def test_a_name_inside_a_longer_name_does_not_match(rc):
    r = _rule(rc, "CTCT_ID_X IS NULL", col=None)
    assert _kept(rc, r, CTCT + ["CTCT_ID_X"]) == ["CTCT_KEY", "CTCT_ID_X"]


def test_matching_ignores_case(rc):
    r = _rule(rc, "brth_ts > current_date()", col=None)
    assert _kept(rc, r) == ["CTCT_KEY", "BRTH_TS"]


def test_uniqueness_drops_the_runners_own_marker(rc):
    r = _rule(rc, "count(*) OVER (PARTITION BY CTCT_ID) > 1", col="CTCT_ID")
    assert _kept(rc, r, CTCT + ["__dup"]) == ["CTCT_KEY", "CTCT_ID"]


def test_a_join_keeps_both_sides_columns_by_position(rc):
    r = _rule(rc, "NOT (lower(s.SUBS_FRST_NM) <=> lower(c.FRST_NM))", col=None,
              join_sql="t.subs s JOIN t.ctct c ON s.CTCT_KEY = c.CTCT_KEY")
    cols = ["SUBS_KEY", "CTCT_KEY", "SUBS_FRST_NM", "IMEI_ID",
            "CTCT_KEY", "FRST_NM", "BRTH_TS"]
    assert rc.sample_keep(r, cols, ["SUBS_KEY"]) == [0, 1, 2, 4, 5]


def test_with_no_declared_key_the_sandpit_keys_are_kept(rc):
    r = _rule(rc, "EML_ID IS NULL")
    assert _kept(rc, r, keys=None) == ["CTCT_KEY", "EML_ID"]


def test_every_registered_rule_keeps_its_own_target_column():
    """Over the real register: a rule's target column, where it has one, is always
    stored, so no sample is missing the value that failed."""
    sys.path.insert(0, str(ROOT / "jobs"))
    try:
        import run_checks as rc
        from dq_app.data import adapter
        reg = adapter.get_rule_registry_current()
        fields = rc.Rule.__dataclass_fields__
        for _, row in reg.iterrows():
            rule = rc.Rule(**{k: (None if row[k] != row[k] else row[k]) for k in fields
                              if k in row.index and k != "sample_columns"})
            if not rule.target_column:
                continue
            cols = ["SOME_KEY", rule.target_column, "UNRELATED_PII_COLUMN"]
            kept = [cols[i] for i in rc.sample_keep(rule, cols, ["SOME_KEY"])]
            assert kept == ["SOME_KEY", rule.target_column], rule.rule_id
    finally:
        sys.path.remove(str(ROOT / "jobs"))

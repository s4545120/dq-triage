"""generate's choice of rule_version: which ids it may reuse and at what version."""

from __future__ import annotations

from onboard import next_version

TABLE = "samples.bakehouse.sales_customers"
KEY = ("TPL_NAME_PRESENT", TABLE, "first_name")
RID = "SALES_CUSTOMERS_first_name_NOT_NULL"


def _latest(status, template="TPL_NAME_PRESENT", column="first_name", version=3):
    return {RID: dict(rule_id=RID, rule_version=version, status=status,
                      template_id=template, target_table=TABLE, target_column=column)}


def test_a_new_rule_starts_at_version_one():
    assert next_version(KEY, RID, {}, {}) == 1


def test_a_current_rule_from_the_template_gets_its_next_version():
    assert next_version(KEY, RID, {KEY: {"rule_version": 2}}, _latest("shadow", version=2)) == 3


def test_a_retired_rule_comes_back_when_its_table_is_selected_again():
    # sales_customers, 2026-10-06: decommissioned at v3, selected again, and every id
    # was refused as "already used by a rule not from this template".
    assert next_version(KEY, RID, {}, _latest("retired")) == 4


def test_a_retired_rule_from_another_template_keeps_its_id():
    assert next_version(KEY, RID, {}, _latest("retired", template="TPL_OTHER")) is None


def test_a_retired_rule_on_another_column_keeps_its_id():
    assert next_version(KEY, RID, {}, _latest("retired", column="last_name")) is None


def test_a_hand_written_rule_holding_the_id_is_left_alone():
    assert next_version(KEY, RID, {}, _latest("active", template=None)) is None

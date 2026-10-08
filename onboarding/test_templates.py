"""The template library: every template reproduces its source rule, and the pattern
template takes its shape from the element only where the class has no format check."""

from __future__ import annotations

import templates as tpl

DOB_SIG = r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$"
PATTERN = tpl.BY_ID["TPL_PATTERN"]


def test_every_template_reproduces_its_source_rule():
    assert tpl.equivalence() == []


def test_the_pattern_template_is_lifted_from_the_landline_format_rule():
    # CTCT_PHN_FMT, put back together from the template and its source pattern.
    assert PATTERN.rule_expr == "{col} NOT RLIKE {pattern}"
    assert PATTERN.scope_filter == "{col} IS NOT NULL AND trim({col}) <> ''"


def test_the_pattern_is_written_as_a_literal_spark_will_not_unescape():
    # One backslash in a Spark string literal is dropped: '\d' would arrive as 'd'.
    expr, scope = PATTERN.instantiate("BRTH_TS", DOB_SIG)
    assert expr == r"BRTH_TS NOT RLIKE '^\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}$'"
    assert scope == "BRTH_TS IS NOT NULL AND trim(BRTH_TS) <> ''"


def test_the_pattern_template_needs_a_pattern():
    try:
        PATTERN.instantiate("X")
    except ValueError:
        return
    raise AssertionError("instantiated without a pattern")


def ids(data_class, sig, cde_id="CDE_CUST_DOB"):
    return [tp.template_id for tp in tpl.for_class(data_class, sig, cde_id)]


def test_date_of_birth_has_its_own_format_check_so_no_pattern_beside_it():
    # The DOB class checks are scoped to values that parse, so a '31-02-1988' falls
    # outside all of them. TPL_DOB_PARSEABLE is what sees it -- in the column's own
    # format, which a regex on the element could not be.
    got = ids("date_of_birth", DOB_SIG)
    assert "TPL_DOB_PARSEABLE" in got and "TPL_PATTERN" not in got


def test_a_class_format_check_from_the_migration_queries_wins_over_the_pattern():
    for cls in ("email_address", "phone_number", "person_name", "account_id"):
        assert "TPL_PATTERN" not in ids(cls, r"^\d+$"), cls


def test_a_signature_profiled_from_pilot_data_generates_nothing():
    # The identity document number's ^\d{7}$ came from 1000 mock rows; a real passport
    # would breach it. Not confirmed, so no check -- whatever its class.
    assert ids("national_id", r"^\d{7}$", "CDE_CUST_IDENT_DOC") == []
    assert ids("device_id", r"^\d{7}$", "CDE_DEVICE_IMEI") == []
    assert ids("other", None, "CDE_NETWORK_TECH") == []


def test_the_confirmed_four_are_the_migration_query_elements():
    assert tpl.CONFIRMED_SIGNATURES == {"CDE_CUST_NAME", "CDE_CUST_DOB", "CDE_CUST_EMAIL",
                                        "CDE_CUST_MOBILE", "CDE_CUST_LANDLINE"}


def test_a_rule_is_written_again_only_when_what_it_measures_changed():
    expr, scope = PATTERN.instantiate("PHN_NO", "^0[0-9]{9}$")
    same = {"rule_expr": expr, "scope_filter": scope}
    assert not tpl.restated(same, expr, scope)
    assert tpl.restated({**same, "rule_expr": "PHN_NO NOT RLIKE 'old'"}, expr, scope)
    assert tpl.restated({**same, "scope_filter": None}, expr, scope)
    assert not tpl.restated(None, expr, scope)


# --- The date format is the column's ------------------------------------------------------

FUTURE = tpl.BY_ID["TPL_DOB_FUTURE"]
PARSEABLE = tpl.BY_ID["TPL_DOB_PARSEABLE"]


def test_the_date_templates_carry_a_format_slot_not_the_mock_tables_format():
    for tp in (FUTURE, PARSEABLE, tpl.BY_ID["TPL_DOB_OVER_110"],
               tpl.BY_ID["TPL_DOB_PLACEHOLDER"]):
        assert "{datefmt}" in tp.rule_expr + (tp.scope_filter or ""), tp.template_id
        assert "yyyy-MM-dd" not in tp.rule_expr + (tp.scope_filter or ""), tp.template_id
    assert not tpl.BY_ID["TPL_DOB_PRESENT"].takes_date_format


def test_a_column_in_another_format_is_checked_in_that_format():
    expr, scope = FUTURE.instantiate("DOB", date_format="dd/MM/yyyy")
    assert expr == "to_date(try_to_timestamp(DOB, 'dd/MM/yyyy')) > current_date()"
    assert scope == "try_to_timestamp(DOB, 'dd/MM/yyyy') IS NOT NULL"


def test_a_date_template_needs_a_format():
    try:
        FUTURE.instantiate("DOB")
    except ValueError:
        return
    raise AssertionError("instantiated without a date format")


def test_a_date_column_is_checked_through_its_text_form_and_never_for_parsing():
    col, fmt = tpl.date_column("DOB")
    expr, scope = FUTURE.instantiate(col, date_format=fmt)
    assert expr == ("to_date(try_to_timestamp(date_format(DOB, 'yyyy-MM-dd HH:mm:ss'), "
                    "'yyyy-MM-dd HH:mm:ss')) > current_date()")
    assert FUTURE.accepts("DATE") and FUTURE.accepts("TIMESTAMP") and FUTURE.accepts("STRING")
    assert not PARSEABLE.accepts("DATE"), "a DATE column always parses"
    assert not tpl.BY_ID["TPL_EMAIL_FMT"].accepts("DATE")


def _counts(n, **by_format):
    out = {"n__": n}
    for i, (f, _) in enumerate(tpl.DATE_FORMATS):
        out[f"p__{i}"] = by_format.get(f, 0)
    return out


def test_the_format_most_values_parse_in_is_chosen():
    fmt, why = tpl.choose_date_format(_counts(1000, **{"yyyy-MM-dd HH:mm:ss": 986}))
    assert fmt == "yyyy-MM-dd HH:mm:ss" and "98.6%" in why
    # 'd/M/yyyy' parses everything 'dd/MM/yyyy' does: same field order, not ambiguous.
    fmt, _ = tpl.choose_date_format(_counts(100, **{"dd/MM/yyyy": 99, "d/M/yyyy": 100}))
    assert fmt == "d/M/yyyy"


def test_day_and_month_that_cannot_be_told_apart_generate_nothing():
    fmt, why = tpl.choose_date_format(_counts(100, **{"dd/MM/yyyy": 100, "MM/dd/yyyy": 100}))
    assert fmt is None and "cannot be told apart" in why


def test_a_column_no_format_fits_generates_nothing_and_says_why():
    fmt, why = tpl.choose_date_format(_counts(100, **{"yyyy-MM-dd": 60}))
    assert fmt is None and "60.0%" in why
    assert tpl.choose_date_format(_counts(0))[0] is None


def test_the_probe_measures_every_candidate_format():
    sql = tpl.date_format_probe("DOB")
    assert sql.count("try_to_timestamp(DOB,") == len(tpl.DATE_FORMATS)
    assert "'yyyy-MM-dd\\'T\\'HH:mm:ss'" in sql, "the quoted T survives as a literal"

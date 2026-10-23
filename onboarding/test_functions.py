"""onboarding/functions.py: which function a rule implements."""

import functions as f


def test_a_uc_helper_is_named_whatever_the_prefix():
    assert f.classify("NOT dq.fn.is_valid_email_v1(EML_ID)") == ("uc", "is_valid_email_v1")
    assert f.classify("workspace.dq_triage.dq_fn_is_blank_v1(FRST_NM)") == ("uc", "is_blank_v1")


def test_simple_shapes_map_to_their_dqx_check():
    assert f.classify("IMEI_ID IS NULL") == ("dqx", "is_not_null")
    assert f.classify("FIRST_NAME IS NULL OR trim(cast(FIRST_NAME AS STRING)) = ''") == \
        ("dqx", "is_not_null_and_not_empty")
    assert f.classify("trim(cast(E_MAIL AS STRING)) NOT RLIKE '^[a-z]+@'") == ("dqx", "regex_match")
    assert f.classify("upper(trim(cast(X AS STRING))) RLIKE 'TEST'") == ("dqx", "regex_match")
    assert f.classify("count(*) OVER (PARTITION BY ID) > 1", "uniqueness") == ("dqx", "is_unique")
    assert f.classify("c.CTCT_KEY IS NULL", "referential", "a LEFT JOIN b ON a.k = b.k") == \
        ("dqx", "foreign_key")
    assert f.classify("to_date(timestamp_millis(try_cast(cast(BIRTH_DATE AS STRING) AS BIGINT)))"
                      " > current_date()") == ("dqx", "is_not_in_future")


def test_anything_else_is_inline_sql():
    assert f.classify("cast(X AS STRING) <> trim(cast(X AS STRING))") == ("sql", None)
    assert f.classify("lower(trim(s.A)) <> lower(trim(c.B))", "consistency") == ("sql", None)
    assert f.classify("X RLIKE 'a' AND Y RLIKE 'b'") == ("sql", None)


def test_the_storable_pairs_match_the_table_check():
    assert f.problem("uc", "is_blank_v1") is None
    assert f.problem("sql", None) is None and f.problem(None, None) is None
    assert f.problem("sql", "x") and f.problem("uc", None) and f.problem("dqx", "nope")

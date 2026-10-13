"""Run every key-attribute rule on the warehouse, over values written here, and diff.

    python key_attributes/probe.py            # read-only; needs a Databricks login

The source tables are not reachable from this workspace, so this is how the rules are
proven before they run anywhere: each case is one value for one attribute, and the set
of that attribute's rules expected to flag it. The probe builds an inline VALUES table
per source table, evaluates `scope AND rule_expr` exactly as the check runner does, and
reports every case whose flagged set differs from the expected one. Nothing is read
from any table and nothing is written.

Uniqueness rules are windowed, so they are probed separately, over their own scope.

Epoch-millisecond dates are written at 12:00 UTC so no session time zone can move them
across midnight.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "onboarding"))

import register as ka  # noqa: E402
import universe  # noqa: E402


def ms(y: int, m: int = 6, d: int = 15) -> str:
    return str(int(datetime(y, m, d, 12, tzinfo=timezone.utc).timestamp() * 1000))


NOW = datetime.now(timezone.utc)
TAB = "\t"

# (table, column, value, companions, expected check suffixes)
CASES: list[tuple[str, str, str | None, dict, set[str]]] = []


def case(table, col, value, expect, **companions):
    CASES.append((table, col, value, companions, set(expect)))


C, A, B, R, U = ka.CONTACT, ka.ADDRESS, ka.BUS_ORG, ka.CONTACT_ROLE, ka.CUSTOMER

# --- names -------------------------------------------------------------------------
for v in ("John", "O'Brien", "Mary-Jane", "José", "Mrs"):
    case(C, "FIRST_NAME", v, [])
case(C, "FIRST_NAME", "Ms Jane", ["STARTS_WITH_TITLE"])
case(C, "FIRST_NAME", " John", ["LEADING_OR_TRAILING_WHITESPACE"])
case(C, "FIRST_NAME", "UNKNOWN", ["PLACEHOLDER_VALUE"])
case(C, "FIRST_NAME", "ACME PTY LTD", ["COMPANY_NAME_INDICATOR"])
case(C, "FIRST_NAME", "12 Smith Street", ["UNRELATED_IDENTIFIER_NOTE_OR_ADDRESS",
                                          "STARTS_WITH_NON_LETTER",
                                          "INVALID_CHARACTERS_OR_STRUCTURE"])
case(C, "FIRST_NAME", "-Anne", ["HYPHEN_OR_APOSTROPHE_EDGE", "STARTS_WITH_NON_LETTER",
                                "INVALID_CHARACTERS_OR_STRUCTURE"])
case(C, "FIRST_NAME", "Jo--hn", ["CONSECUTIVE_PUNCTUATION", "INVALID_CHARACTERS_OR_STRUCTURE"])
case(C, "FIRST_NAME", f"Jo{TAB}hn", ["CONTROL_CHARACTERS", "INVALID_CHARACTERS_OR_STRUCTURE"])
case(C, "FIRST_NAME", "a" * 41, ["EXCEEDS_40_CHARACTERS"])
case(C, "FIRST_NAME", None, ["NULL_OR_BLANK"])
case(C, "FIRST_NAME", "ESTATE OF THE LATE JOHN", ["ESTATE_NAME_NOT_DECEASED"], STATUS="1")
case(C, "FIRST_NAME", "John", ["DECEASED_WITHOUT_ESTATE_NAME"], STATUS="5")
case(C, "FIRST_NAME", "ESTATE OF THE LATE JOHN", [], STATUS="5")
case(C, "MIDDLE_NAME", None, [])
case(C, "MIDDLE_NAME", "Ann", [])
case(C, "LAST_NAME", "Mr Smith", ["STARTS_WITH_TITLE"])
case(C, "LAST_NAME", "", ["NULL_OR_BLANK"])
case(C, "LAST_NAME", "O’Neil", [])

# --- phone -------------------------------------------------------------------------
for t in (C, B):
    case(t, "PHONE", "0412345679", [])
    case(t, "PHONE", "0298765432", [])
    case(t, "PHONE", "0412 345 679", ["WASHABLE_FORMATTING"])
    case(t, "PHONE", "+61 412 345 679", ["WASHABLE_FORMATTING"])
    case(t, "PHONE", "0412345678", ["KNOWN_PLACEHOLDER_OR_PROHIBITED"])
    case(t, "PHONE", "0400000000", ["KNOWN_PLACEHOLDER_OR_PROHIBITED", "ALL_ZEROS_PATTERN"])
    case(t, "PHONE", "12345", ["INVALID_FORMAT"])
    case(t, "PHONE", "0412abc", ["UNSUPPORTED_CHARACTER"])
    case(t, "PHONE", " 0412345679", ["LEADING_OR_TRAILING_SPACE"])
    case(t, "PHONE", "1300 123 456", ["WASHABLE_FORMATTING"])
    case(t, "PHONE", None, ["NULL_OR_BLANK"])

# --- email -------------------------------------------------------------------------
for v in ("a.b@example.com", "o'neil@example.com.au", "first_last@sub.example.org"):
    case(C, "E_MAIL", v, [])
case(C, "E_MAIL", "nath.borm@gmail.co", ["INVALID_MALFORMED"])
case(C, "E_MAIL", "NO_EMAIL123@OPTUS.COM.AU", ["INVALID_OPTUS_GENERATED"])
case(C, "E_MAIL", "noreplysales@brownssprings.au", ["INVALID_GENERIC"])
case(C, "E_MAIL", "a..b@example.com", ["INVALID_MALFORMED"])
case(C, "E_MAIL", "abc", ["INVALID_MALFORMED"])
case(C, "E_MAIL", "a b@example.com", ["INVALID_MALFORMED"])
case(C, "E_MAIL", None, ["NULL_OR_BLANK"])

# --- date of birth -----------------------------------------------------------------
case(C, "BIRTH_DATE", ms(1980, 6, 15), [])
case(C, "BIRTH_DATE", "0", ["NULL_OR_ZERO"])
case(C, "BIRTH_DATE", None, ["NULL_OR_ZERO"])
case(C, "BIRTH_DATE", ms(1900, 1, 1), ["PLACEHOLDER", "AGE_OVER_110"])
case(C, "BIRTH_DATE", ms(1850), ["BEFORE_1900", "AGE_OVER_110"])
case(C, "BIRTH_DATE", ms(NOW.year + 4), ["FUTURE"])
case(C, "BIRTH_DATE", ms(NOW.year - 10, 1, 1), ["UNDER_14"])
case(C, "BIRTH_DATE", ms(NOW.year - 16, 1, 1), ["AGE_14_TO_17_REVIEW"])

# --- identifiers -------------------------------------------------------------------
for t, col in ((C, "CONTACT_ID"), (B, "ORG_ID"), (U, "CUSTOMER_ID")):
    case(t, col, "123456", [])
    case(t, col, "12a", ["NUMERIC"])
    case(t, col, None, ["NOT_NULL"])

# --- contact role ------------------------------------------------------------------
case(R, "ROLE_NAME", "Default", [])
case(R, "ROLE_NAME", "default", ["LOWERCASE_DEFAULT"])
case(R, "ROLE_NAME", "Admin", ["NULL_OR_OTHER_VALUE"])
case(R, "ROLE_NAME", None, ["NULL_OR_OTHER_VALUE"])

# --- address -----------------------------------------------------------------------
case(A, "EFF_DT", ms(2020), [])
case(A, "EFF_DT", ms(1753, 1, 1), ["SENTINEL_1753", "BEFORE_1900"])
case(A, "EFF_DT", ms(NOW.year + 4), ["FUTURE"])
case(A, "END_DT", ms(2019), ["BEFORE_EFF_DT"], EFF_DT=ms(2020))
case(A, "END_DT", ms(2021), [], EFF_DT=ms(2020))
case(A, "END_DT", ms(1753, 1, 1), ["SENTINEL_1753", "BEFORE_1900", "BEFORE_EFF_DT"],
     EFF_DT=ms(2020))
case(A, "END_DT", None, [], EFF_DT=ms(2020))
case(A, "X_ADDRESS_ID", "GAACT714845055", [])
case(A, "X_ADDRESS_ID", None, [])
case(A, "X_ADDRESS_ID", "12345", ["NUMERIC_LEGACY"])
case(A, "X_ADDRESS_ID", "GAQLD1|GAQLD2", ["PIPE_DELIMITED"])
case(A, "X_ADDRESS_ID", "GAWA_123", ["FREE_TEXT_OR_INVALID"])
case(A, "X_SUB_ADDRESS_NUMBER", "Unit 4", [], STREET_NUMBER="12")
case(A, "X_SUB_ADDRESS_NUMBER", "Unit  4", ["REPEATED_SPACES"], STREET_NUMBER="12")
case(A, "X_SUB_ADDRESS_NUMBER", " Unit 4", ["LEADING_OR_TRAILING_WHITESPACE"], STREET_NUMBER="12")
case(A, "X_SUB_ADDRESS_NUMBER", "12", ["DUPLICATES_STREET_NUMBER"], STREET_NUMBER="12")
case(A, "X_SUB_ADDRESS_NUMBER", f"Unit{TAB}4", ["CONTROL_CHARACTER"], STREET_NUMBER="12")
case(A, "ADDRESS_3", "Level 2 Tower A", [], X_INTERNATIONAL_ADDRESS="N")
case(A, "ADDRESS_3", "Main St NSW 2000", ["CONTAINS_STATE_OR_POSTCODE"], X_INTERNATIONAL_ADDRESS="N")
case(A, "ADDRESS_3", "Main St NSW 2000", [], X_INTERNATIONAL_ADDRESS="Y")
case(A, "ADDRESS_3", "x" * 81, ["EXCEEDS_80_CHARACTERS"], X_INTERNATIONAL_ADDRESS="N")
case(A, "ADDRESS_4", "Comcentre  Building", ["REPEATED_SPACES"])
case(A, "ADDRESS_4", "Comcentre Building", [])

# --- business organisation ---------------------------------------------------------
case(B, "X_NUMBER_OF_EMPLOYEE", "25", [])
case(B, "X_NUMBER_OF_EMPLOYEE", "0", ["ZERO_OR_ZERO_PADDED"])
case(B, "X_NUMBER_OF_EMPLOYEE", "00", ["ZERO_OR_ZERO_PADDED"])
case(B, "X_NUMBER_OF_EMPLOYEE", "-5", ["NEGATIVE"])
case(B, "X_NUMBER_OF_EMPLOYEE", "2.5", ["DECIMAL_OR_NON_WHOLE"])
case(B, "X_NUMBER_OF_EMPLOYEE", "1e3", ["SCIENTIFIC_NOTATION"])
case(B, "X_NUMBER_OF_EMPLOYEE", "1,000", ["CURRENCY_SEPARATOR_OR_UNIT_TEXT"])
case(B, "X_NUMBER_OF_EMPLOYEE", "20 staff", ["CURRENCY_SEPARATOR_OR_UNIT_TEXT"])
case(B, "X_NUMBER_OF_EMPLOYEE", "about", ["NON_NUMERIC_OR_TEXT"])
case(B, "X_NUMBER_OF_OFFICE", "3", [])
case(B, "X_NUMBER_OF_OFFICE", "0", ["ZERO_PLACEHOLDER"])
case(B, "X_NUMBER_OF_OFFICE", "03", ["LEADING_ZERO_FORMAT"])
case(B, "X_NUMBER_OF_OFFICE", "0298765432", ["POSSIBLE_PHONE_NUMBER", "LEADING_ZERO_FORMAT",
                                             "IMPLAUSIBLE_OUTLIER"])
case(B, "X_NUMBER_OF_OFFICE", "5000", ["IMPLAUSIBLE_OUTLIER"])
case(B, "WEB_SITE", "https://example.com", [])
case(B, "WEB_SITE", None, [])
case(B, "WEB_SITE", "www.example.com", ["MISSING_PROTOCOL"])
case(B, "WEB_SITE", "http://Nil", ["PLACEHOLDER"])
case(B, "WEB_SITE", ".", ["PLACEHOLDER"])
case(B, "ESTABLISH_DATE", ms(2000), [])
case(B, "ESTABLISH_DATE", "-6847840800000", ["PLACEHOLDER_1753", "BEFORE_SUPPORTED_HISTORY"])
case(B, "ESTABLISH_DATE", "abc", ["INVALID_EPOCH_VALUE"])
case(B, "ESTABLISH_DATE", ms(NOW.year + 4), ["FUTURE"])
case(B, "X_ARBN", "123456789", [])
case(B, "X_ARBN", "12345", ["WRONG_LENGTH_NUMERIC"])
case(B, "X_ARBN", "000000000", ["ALL_ZEROS_PLACEHOLDER"])
case(B, "X_ARBN", "N/A", ["PLACEHOLDER_TEXT"])
case(B, "X_ARBN", "see ACN", ["OTHER_NON_NUMERIC"])


def _lit(v: str | None) -> str:
    if v is None:
        return "CAST(NULL AS STRING)"
    return "'" + v.replace("\\", "\\\\").replace("'", "\\'") + "'"


def queries() -> list[tuple[str, str, list, list]]:
    """[(table, sql, row-level rules, cases)] -- one query per source table."""
    rules = universe.all_rules()
    out = []
    for table in ka.TABLES:
        cases = [c for c in CASES if c[0] == table]
        trs = [r for r in rules if r.table == table and r.rule_type != "uniqueness"]
        cols = sorted({r.column for r in rules if r.table == table}
                      | {k for c in cases for k in c[3]})
        rows = []
        for i, (_, col, value, comp, _) in enumerate(cases):
            vals = {c: None for c in cols}
            vals.update(comp)
            vals[col] = value
            rows.append(f"({i}, " + ", ".join(_lit(vals[c]) for c in cols) + ")")
        flags = [f"coalesce(({r.scope_filter or 'TRUE'}) AND ({r.rule_expr}), FALSE) AS f{j}"
                 for j, r in enumerate(trs)]
        sql = (f"SELECT case_id, {', '.join(flags)}\nFROM VALUES\n  " + ",\n  ".join(rows)
               + f"\nAS t(case_id, {', '.join(cols)})\nORDER BY case_id")
        out.append((table, sql, trs, cases))
    return out


def uniqueness_queries() -> list[tuple[str, str, int]]:
    out = []
    for r in universe.all_rules():
        if r.rule_type != "uniqueness":
            continue
        # The rule's own expression, evaluated over its own scope as the runner does.
        sql = (f"SELECT count_if(flag) AS v FROM (SELECT ({r.rule_expr}) AS flag FROM VALUES "
               f"('1'), ('1'), ('2'), (CAST(NULL AS STRING)), (' 2 ') AS t({r.column}) "
               f"WHERE {r.scope_filter})")
        out.append((r.rule_id, sql, 4))       # '1','1' and '2',' 2 ' once trimmed
    return out


def main() -> int:
    import wh
    failures = 0
    with wh.connect() as conn:
        for table, sql, trs, cases in queries():
            got = wh.run(conn, sql)
            for row, (_, col, value, comp, expect) in zip(got, cases):
                prefix = f"{ka.TABLE_CODE[table]}_{col}_"
                flagged = {trs[j].rule_id.removeprefix(prefix)
                           for j in range(len(trs))
                           if trs[j].column == col and row[f"f{j}"]}
                if flagged != expect:
                    failures += 1
                    print(f"FAIL {table.split('.')[-1]}.{col} = {value!r} {comp or ''}\n"
                          f"     expected {sorted(expect)}\n     got      {sorted(flagged)}")
            print(f"{table.split('.')[-1]}: {len(cases)} cases over {len(trs)} rules")
        for rid, sql, want in uniqueness_queries():
            v = wh.run(conn, sql)[0]["v"]
            if v != want:
                failures += 1
                print(f"FAIL {rid}: {v} duplicates flagged, expected {want}")
        print(f"uniqueness: {len(uniqueness_queries())} rules")
    n = len(CASES) + len(uniqueness_queries())
    print(f"\n{n - failures} of {n} agree" + ("" if not failures else f", {failures} do not"))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

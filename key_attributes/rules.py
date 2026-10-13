"""The migration rules, one per validation category of the migration-scope DQ analysis.

SOURCE. dq_analysis_migration_scope_attributes_masked.pdf: each attribute's table of
"Validation rule / Affected / Sample / Recommended solution type". A category the
analysis marks informational (shared phone numbers, landlines, special-service numbers,
a blank middle name) is not a defect and is not registered. Neither is a roll-up row
(PHONE_ANY_RULE_ISSUE, MASTER_DQ_EMAIL_INVALID).

The PDF is masked, so the numbers come from the unmasked queries in DQ_ATTR_PRIORI.xlsx
(the '#1 - DQ Issues' Query column and the DEVIATION sheet) and, for the contact name,
phone and date-of-birth lists, from the workspace's 'DQ Queries' folder, as
fixtures/rules.py first extracted them. Where no source gives the number, the rule is
left out and NOT_REGISTERED says so, rather than guessing.

SOURCE BUGS FIXED ON THE WAY IN, as in fixtures/rules.py: Spark RLIKE is Java regex, so
the queries' POSIX classes ([[:space:]], [[:punct:]]) are character sets of letters.
They are \\s and \\p{P} here. And the queries' '' inside a Spark string literal is not
an escaped quote but two adjacent literals, so the email regex silently lost its
apostrophe. It is \\x27 here.

HOW A RULE IS WRITTEN. `rule_expr` is TRUE for a violating row and `scope_filter`
narrows the rows it applies to, as everywhere in this repo. Every column is read through
cast(... AS STRING), because the source's types are not visible from this workspace and
the analysis queries did the same. Epoch-millisecond dates are read with
to_date(timestamp_millis(...)), the analysis queries' own conversion, so dates fall in
the warehouse session's time zone exactly as they did there.

THE CATEGORIES WERE MUTUALLY EXCLUSIVE; THE RULES ARE NOT. The analysis put each record
in the first category it matched. A rule is a separate check, so a name with a title AND
a trailing space fails two rules where the analysis counted it once.

ALL SHADOW. Measured, never raising a problem, until a person promotes them.

SEVERITY from the recommended solution: a missing or duplicated record key is P1_block;
"Delete" and "Customer amends" are P2_alert; "Optus amends", "check with BCC" and
"confirm" are P3_monitor.
"""

from __future__ import annotations

from dataclasses import dataclass

from register import (ADDRESS, BUS_ORG, CONTACT, CONTACT_ROLE, CUSTOMER,
                      KEY_ATTRIBUTES, LATEST_RECORD_GAP, TABLE_CODE, KeyAttribute)

PDF = "migration-scope DQ analysis"


@dataclass(frozen=True)
class Rule:
    rule_id: str
    rule_name: str
    table: str
    column: str
    rule_type: str
    rule_expr: str
    scope_filter: str | None
    severity: str
    note: str
    universe: bool = False

    @property
    def cde_id(self) -> str:
        return f"{TABLE_CODE[self.table]}_{self.column}"


def S(c: str) -> str:
    return f"cast({c} AS STRING)"


def T(c: str) -> str:
    return f"trim(cast({c} AS STRING))"


def present(c: str) -> str:
    return f"{c} IS NOT NULL AND trim(cast({c} AS STRING)) <> ''"


def blank(c: str) -> str:
    return f"{c} IS NULL OR trim(cast({c} AS STRING)) = ''"


def epoch_date(c: str) -> str:
    return f"to_date(timestamp_millis(try_cast(cast({c} AS STRING) AS BIGINT)))"


def _in(values) -> str:
    return "(" + ", ".join("'" + v.replace("'", "\\'") + "'" for v in values) + ")"


def _rule(table: str, column: str, check: str, name: str, rule_type: str, expr: str,
          scope: str | None, severity: str, category: str, solution: str,
          extra: str = "") -> Rule:
    note = f"{PDF}: {category}. Recommended solution: {solution}."
    if extra:
        note += " " + extra
    return Rule(f"{TABLE_CODE[table]}_{column}_{check}", name, table, column, rule_type,
                expr, scope, severity, note)


# --- names ------------------------------------------------------------------------
# Lists and the length limit from the 'DQ Queries' First / Middle / Last Name queries,
# which the analysis reran (fixtures/rules.py NAME_PLACEHOLDERS, NAME_MAX_LEN).

NAME_PLACEHOLDERS = (
    "N/A", "NONE", "NULL", "UNKNOWN", "NOT APPLICABLE", "NOT PROVIDED", "TBC", "TBD",
    "TEST", "DUMMY", "SAMPLE", "UNDEFINED", "NOT AVAILABLE",
)
NAME_MAX_LEN = 40
_PUNCT_EDGE = r"[-\\x27\\x{2019}]"
_ADDRESS_WORDS = ("C/O|CARE OF|PO BOX|UNIT|SUITE|LEVEL|FLOOR|STREET|ROAD|AVENUE|DRIVE|"
                  "HIGHWAY|POSTCODE|SUBURB|NOTE|NOTES")
# The contact status the 'DQ Queries' exploration used for a deceased contact. The PDF
# redacts it ("CTCT_STTS != [REDACTED]"): confirm before promoting the two estate rules.
DECEASED_STATUS = "5"

# category -> severity by attribute where the analysis recommends differently
_NAME_SEVERITY = {
    "FIRST_NAME": {"title": "P3_monitor"},
    "MIDDLE_NAME": {"edge": "P3_monitor", "title": "P3_monitor"},
    "LAST_NAME": {},
}


def _name_rules(col: str, label: str, *, presence: bool, length: bool,
                estate: bool) -> list[Rule]:
    t, sev = T(col), _NAME_SEVERITY[col]
    scope = present(col)
    out = []
    if presence:
        out.append(_rule(CONTACT, col, "NULL_OR_BLANK", f"{label} is present", "not_null",
                         blank(col), None, "P2_alert", "NULL_OR_BLANK", "customer amends"))
    out += [
        _rule(CONTACT, col, "LEADING_OR_TRAILING_WHITESPACE",
              f"{label} has no leading or trailing whitespace", "format",
              f"{S(col)} <> {t}", scope, "P3_monitor", "LEADING_OR_TRAILING_WHITESPACE",
              "Optus amends"),
        _rule(CONTACT, col, "CONTROL_CHARACTERS", f"{label} has no control characters",
              "format", rf"{S(col)} RLIKE '\\p{{Cc}}'", scope, "P3_monitor",
              "CONTAINS_CONTROL_CHARACTERS", "not stated (NA)"),
        _rule(CONTACT, col, "PLACEHOLDER_VALUE", f"{label} is not a placeholder", "sentinel",
              f"upper({t}) IN {_in(NAME_PLACEHOLDERS)}", scope, "P2_alert",
              "PLACEHOLDER_VALUE", "delete, and ask the customer to update after consent"),
        _rule(CONTACT, col, "HYPHEN_OR_APOSTROPHE_EDGE",
              f"{label} does not start or end with a hyphen or apostrophe", "format",
              f"{t} RLIKE '^{_PUNCT_EDGE}|{_PUNCT_EDGE}$'", scope,
              sev.get("edge", "P2_alert"), "STARTS_OR_ENDS_WITH_HYPHEN_OR_APOSTROPHE",
              "delete or customer amends"),
        _rule(CONTACT, col, "CONSECUTIVE_PUNCTUATION",
              f"{label} has no consecutive punctuation", "format",
              rf"{t} RLIKE '\\p{{P}}{{2,}}'", scope, "P3_monitor", "CONSECUTIVE_PUNCTUATION",
              "Optus amends"),
        _rule(CONTACT, col, "STARTS_WITH_TITLE", f"{label} does not start with a title",
              "format", rf"{t} RLIKE '(?i)^(MR|MISS|MRS|MS)\\.?\\s+'", scope,
              sev.get("title", "P2_alert"), "STARTS_WITH_TITLE", "amend the name"),
        _rule(CONTACT, col, "COMPANY_NAME_INDICATOR",
              f"{label} carries no company-name indicator", "format",
              rf"{t} RLIKE '(?i)(^|[^\\p{{L}}])(P-L|PTY|PTY LTD)([^\\p{{L}}]|$)'", scope,
              "P2_alert", "COMPANY_NAME_INDICATOR", "customer amends",
              "The analysis asks whether a company name can be valid for an SMB customer; "
              "until that is answered this flags both."),
        _rule(CONTACT, col, "UNRELATED_IDENTIFIER_NOTE_OR_ADDRESS",
              f"{label} holds no address, note or link", "format",
              rf"{t} RLIKE '(?i)(^|\\s)({_ADDRESS_WORDS})(\\s|:|$)' "
              rf"OR {t} RLIKE '(@|https?://|www\\.)'", scope, "P2_alert",
              "UNRELATED_IDENTIFIER_NOTE_OR_ADDRESS", "customer amends",
              "STREET can be a real surname; the analysis raises it as a question."),
        _rule(CONTACT, col, "STARTS_WITH_NON_LETTER", f"{label} starts with a letter",
              "format", rf"{t} RLIKE '^[^\\p{{L}}]'", scope, "P2_alert",
              "STARTS_WITH_NON_LETTER", "customer amends"),
        _rule(CONTACT, col, "INVALID_CHARACTERS_OR_STRUCTURE",
              f"{label} is letters separated by single spaces, hyphens or apostrophes",
              "format", rf"{t} NOT RLIKE '^\\p{{L}}+([\\p{{Zs}}\\x27\\x{{2019}}-]\\p{{L}}+)*$'",
              scope, "P2_alert", "INVALID_CHARACTERS_OR_STRUCTURE", "customer amends",
              "The widest of the name rules: most rows another name rule flags fail this "
              "one too."),
    ]
    if length:
        out.append(_rule(CONTACT, col, f"EXCEEDS_{NAME_MAX_LEN}_CHARACTERS",
                         f"{label} is at most {NAME_MAX_LEN} characters", "format",
                         f"length({S(col)}) > {NAME_MAX_LEN}", scope, "P3_monitor",
                         "EXCEEDS_N_CHARACTERS", "not stated (NA)",
                         f"The PDF masks the limit; {NAME_MAX_LEN} is the 'DQ Queries' "
                         "figure."))
    if estate:
        estate_note = (f"Deceased is STATUS = '{DECEASED_STATUS}', the value the 'DQ "
                       "Queries' exploration used; the PDF masks it. Confirm before "
                       "promoting.")
        out += [
            _rule(CONTACT, col, "DECEASED_WITHOUT_ESTATE_NAME",
                  f"A deceased contact's {label.lower()} reads ESTATE OF THE LATE",
                  "consistency",
                  f"{S('STATUS')} = '{DECEASED_STATUS}' "
                  f"AND coalesce(upper({t}), '') NOT LIKE '%ESTATE OF THE LATE%'",
                  None, "P3_monitor", "DECEASED CONTACT NOT HAVING \"ESTATE OF THE LATE\"",
                  "Optus amends", estate_note),
            _rule(CONTACT, col, "ESTATE_NAME_NOT_DECEASED",
                  f"A {label.lower()} reading ESTATE OF THE LATE is on a deceased contact",
                  "consistency",
                  f"upper({t}) LIKE '%ESTATE OF THE LATE%' "
                  f"AND coalesce({S('STATUS')}, '') <> '{DECEASED_STATUS}'",
                  scope, "P3_monitor",
                  "CONTACT HAVING \"ESTATE OF THE LATE\" IN FIRST NAME BUT STATUS NOT DECEASED",
                  "Optus amends", estate_note),
        ]
    return out


# --- phone ------------------------------------------------------------------------
# The 'DQ Queries' Phone query's normalisation and placeholder list (fixtures/rules.py
# PHONE_PLACEHOLDERS, the union of its two drifted versions). The analysis splits
# "invalid" into TOO_SHORT, INVALID_AU_LENGTH and INVALID_FORMAT, and masks the lengths
# that tell the first two apart; here they are one rule, INVALID_FORMAT, which fails
# exactly the union of the three.

PHONE_PLACEHOLDERS = (
    "0400000000", "0400000001", "0400000002", "0404040404", "0400000123", "0400000321",
    "0400009999", "0410000000", "0411000321", "0411111110", "0411111111", "0412000123",
    "0412345678", "0413234234", "0420000000", "0421212111", "0422222222", "0432100000",
    "0433333333", "0444444444", "0452397392", "0455555555", "0477777777", "0488888888",
    "0491570006", "0499999999", "0200000000", "0200000001", "0222222222", "0250000000",
    "0280000000", "0280808080", "0288888888", "0290000000", "0299999999", "0300000000",
    "0390000000", "0700000000", "0800000000", "1300000000", "1300300937", "133937",
    "1300133937", "0400011132", "0411111112", "0411111113", "0411111116", "0422226838",
)
_WASHABLE = r"[\\s()+./-]"
_UNSUPPORTED = r"[^0-9\\s()+./-]"


def _digits(c: str) -> str:
    return f"regexp_replace({S(c)}, '[^0-9]', '')"


def _au(c: str) -> str:
    d = _digits(c)
    return (f"CASE WHEN {d} RLIKE '^61[0-9]{{9}}$' THEN concat('0', substr({d}, 3)) "
            f"WHEN {d} RLIKE '^[23478][0-9]{{8}}$' THEN concat('0', {d}) ELSE {d} END")


def _phone_rules(table: str, col: str, label: str, *, null_solution: str,
                 bad_solution: str) -> list[Rule]:
    t = T(col)
    scope = present(col)
    # Special-service numbers (13, 1300, 1800, 1900) are informational in the analysis.
    fmt_scope = f"{scope} AND {_digits(col)} NOT RLIKE '^(13|18|19)00'"
    return [
        _rule(table, col, "NULL_OR_BLANK", f"{label} is present", "not_null", blank(col),
              None, "P3_monitor", "PHONE_NULL_OR_BLANK", null_solution),
        _rule(table, col, "LEADING_OR_TRAILING_SPACE",
              f"{label} has no leading or trailing space", "format", f"{S(col)} <> {t}",
              scope, "P3_monitor", "PHONE_LEADING_OR_TRAILING_SPACE", "Optus amends"),
        _rule(table, col, "WASHABLE_FORMATTING",
              f"{label} is digits only, with no spaces or punctuation to wash out", "format",
              f"{t} RLIKE '{_WASHABLE}' AND {t} NOT RLIKE '{_UNSUPPORTED}'", scope,
              "P3_monitor", "PHONE_WASHABLE_FORMATTING", "Optus amends"),
        _rule(table, col, "UNSUPPORTED_CHARACTER",
              f"{label} holds only digits and washable punctuation", "format",
              f"{t} RLIKE '{_UNSUPPORTED}'", scope, "P2_alert",
              "PHONE_UNSUPPORTED_CHARACTER", bad_solution),
        _rule(table, col, "INVALID_FORMAT",
              f"{label} is an Australian mobile or landline once washed", "format",
              f"{t} NOT RLIKE '{_UNSUPPORTED}' AND NOT (({_au(col)}) RLIKE '^0[23478][0-9]{{8}}$')",
              fmt_scope, "P2_alert", "PHONE_TOO_SHORT, PHONE_INVALID_AU_LENGTH, "
              "PHONE_INVALID_FORMAT", bad_solution,
              "Three categories in one rule: the PDF masks the lengths that separate them."),
        _rule(table, col, "KNOWN_PLACEHOLDER_OR_PROHIBITED",
              f"{label} is not a known placeholder number", "sentinel",
              f"({_au(col)}) IN {_in(PHONE_PLACEHOLDERS)}", scope, "P2_alert",
              "PHONE_KNOWN_PLACEHOLDER_OR_PROHIBITED", bad_solution),
        _rule(table, col, "ALL_ZEROS_PATTERN", f"{label} is not a run of zeros", "sentinel",
              f"{_digits(col)} RLIKE '0{{7,}}'", scope, "P2_alert",
              "PHONE_ALL_ZEROS_PATTERN", bad_solution,
              "Seven or more zeros in a row, the 'DQ Queries' test."),
    ]


# --- email ------------------------------------------------------------------------

_EMAIL_RE = (r"^[A-Za-z0-9][A-Za-z0-9.!#$%&\\x27*+/=?^_`{|}~-]*@[A-Za-z0-9]"
             r"([A-Za-z0-9-]*[A-Za-z0-9])?(\\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+$")
_EMAIL_TYPO_DOMAINS = "gmail|hotmail|yahoo|outlook|bigpond|optusnet"


def _email_rules() -> list[Rule]:
    c, t = "E_MAIL", T("E_MAIL")
    scope = present(c)
    sol = "delete, and run the SMS campaign to get the correct address from the customer"
    return [
        _rule(CONTACT, c, "NULL_OR_BLANK", "Email is present", "not_null", blank(c), None,
              "P2_alert", "EMAIL ID with NULL VALUES", sol,
              "Every migration-scope contact holds an email in the analysis."),
        _rule(CONTACT, c, "INVALID_MALFORMED", "Email is a well-formed address", "format",
              f"{t} NOT RLIKE '{_EMAIL_RE}' OR {t} RLIKE '^[.]|\\\\.\\\\.|[.]@' "
              f"OR lower({t}) RLIKE '@({_EMAIL_TYPO_DOMAINS})\\\\.co$'",
              scope, "P2_alert", "EMAIL_INVALID_MALFORMED", sol,
              "Includes provider domains cut short to .co (gmail.co, hotmail.co), which "
              "is what the analysis's samples are."),
        _rule(CONTACT, c, "INVALID_OPTUS_GENERATED", "Email is not an Optus-generated stand-in",
              "sentinel", f"lower({t}) RLIKE '^no[_ -]?email[0-9]*@optus\\\\.com\\\\.au$'",
              scope, "P2_alert", "EMAIL_INVALID_OPTUS_GENERATED", sol),
        _rule(CONTACT, c, "INVALID_GENERIC", "Email is not a no-reply address", "sentinel",
              f"lower({t}) RLIKE 'no[_ -]?reply'", scope, "P2_alert",
              "EMAIL_INVALID_GENERIC", sol),
    ]


# --- date of birth ----------------------------------------------------------------

DOB_PLACEHOLDERS = ("1900-01-01", "1901-01-01", "1911-11-11", "1970-01-01", "1980-01-01",
                    "9999-12-31")


def _dob_rules() -> list[Rule]:
    c = "BIRTH_DATE"
    d = epoch_date(c)
    scope = f"{d} IS NOT NULL AND try_cast({S(c)} AS BIGINT) <> 0"

    def r(check, name, expr, sev, category, solution, extra="", rtype="format", sc=scope):
        return _rule(CONTACT, c, check, name, rtype, expr, sc, sev, category, solution, extra)

    age = "Age is measured from current_date(), as the analysis did."
    return [
        r("NULL_OR_ZERO", "Date of birth is present", f"{blank(c)} OR try_cast({S(c)} AS BIGINT) = 0",
          "P2_alert", "BIRTH_DATE_NULL_OR_ZERO", "customer amends", rtype="not_null", sc=None),
        r("PLACEHOLDER", "Date of birth is not a default date",
          f"{d} IN (" + ", ".join(f"DATE'{x}'" for x in DOB_PLACEHOLDERS) + ")",
          "P2_alert", "BIRTH_DATE_PLACEHOLDER", "delete", rtype="sentinel",
          extra="Dates from the DEVIATION query; 1980-01-01 is somebody's real birthday."),
        r("FUTURE", "Date of birth is not in the future", f"{d} > current_date()",
          "P2_alert", "BIRTH_DATE_FUTURE", "customer amends"),
        r("BEFORE_1900", "Date of birth is not before 1900", f"{d} < DATE'1900-01-01'",
          "P3_monitor", "BIRTH_DATE_BEFORE_1900", "Optus amends"),
        r("AGE_OVER_110", "Contact is at most 110 years old",
          f"{d} < add_months(current_date(), -110 * 12)", "P2_alert",
          "BIRTH_DATE_AGE_OVER_110", "customer amends", age),
        r("UNDER_14", "Contact is at least 14 years old",
          f"{d} <= current_date() AND {d} > add_months(current_date(), -14 * 12)",
          "P2_alert", "BIRTH_DATE_UNDER_14", "customer amends", age),
        r("AGE_14_TO_17_REVIEW", "Contact aged 14 to 17 is reviewed",
          f"{d} <= add_months(current_date(), -14 * 12) "
          f"AND {d} > add_months(current_date(), -18 * 12)", "P3_monitor",
          "BIRTH_DATE_AGE_14_TO_17_REVIEW", "customer amends",
          age + " Prepaid customers may be 14 or older; everyone else must be 18: a "
          "segment question, not a data defect, until the segment is joined in."),
    ]


# --- record identifiers -----------------------------------------------------------

def _id_rules(table: str, col: str, label: str, numeric_solution: str) -> list[Rule]:
    t = T(col)
    scope = present(col)
    return [
        _rule(table, col, "NOT_NULL", f"{label} is present", "not_null", blank(col), None,
              "P1_block", "NULL / blank", "source or technical correction"),
        _rule(table, col, "NUMERIC", f"{label} is all digits", "format",
              f"{t} NOT RLIKE '^[0-9]+$'", scope, "P2_alert",
              "INVALID - non-numeric or contains characters", numeric_solution),
        _rule(table, col, "UNIQUE", f"{label} is unique", "uniqueness",
              f"count(*) OVER (PARTITION BY {t}) > 1", scope, "P1_block",
              "VALID - populated, numeric and unique", "source or technical correction",
              "On a history table every record with two versions repeats its id. "
              + LATEST_RECORD_GAP),
    ]


# --- contact role -----------------------------------------------------------------

def _role_rules() -> list[Rule]:
    c, t = "ROLE_NAME", T("ROLE_NAME")
    return [
        _rule(CONTACT_ROLE, c, "LOWERCASE_DEFAULT", "Role name is 'Default', capitalised",
              "format", f"lower({t}) = 'default' AND {t} <> 'Default'", present(c),
              "P3_monitor", "LOWERCASE_DEFAULT", "Optus amends: standardise to Default "
              "after BCC confirmation"),
        _rule(CONTACT_ROLE, c, "NULL_OR_OTHER_VALUE", "Role name is Default", "consistency",
              f"{blank(c)} OR lower({t}) <> 'default'", None, "P3_monitor",
              "NULL_OR_OTHER_VALUE", "not stated (NA)"),
    ]


# --- address ----------------------------------------------------------------------

_BCC = "confirm with the BCC/ODH team whether the sentinel and the cut-off are by design"
_YEAR_ASSUMED = ("The PDF masks the cut-off year; 1900 is assumed, the cut-off the "
                 "birth-date and establishment-date queries use.")


def _address_date_rules() -> list[Rule]:
    out = []
    for c, label in (("EFF_DT", "Address active-from date"),
                     ("END_DT", "Address active-to date")):
        d = epoch_date(c)
        scope = f"{c} IS NOT NULL"
        out += [
            _rule(ADDRESS, c, "SENTINEL_1753", f"{label} is not the 1753-01-01 sentinel",
                  "sentinel", f"{d} = DATE'1753-01-01'", scope, "P3_monitor",
                  "Sentinel value 1753-01-01", _BCC,
                  "The SQL Server minimum date, by far the largest finding on the table."),
            _rule(ADDRESS, c, "BEFORE_1900", f"{label} is not before 1900", "format",
                  f"{d} < DATE'1900-01-01'", scope, "P3_monitor", f"Invalid - {c} before "
                  "the cut-off year", _BCC, _YEAR_ASSUMED + " Includes the sentinel."),
        ]
    out += [
        _rule(ADDRESS, "EFF_DT", "FUTURE", "Address active-from date is not in the future",
              "format", f"{epoch_date('EFF_DT')} > current_date()", "EFF_DT IS NOT NULL",
              "P3_monitor", "Future - EFF_DT after the current date", "Optus amends"),
        _rule(ADDRESS, "END_DT", "BEFORE_EFF_DT",
              "Address active-to date is not before its active-from date", "consistency",
              f"{epoch_date('END_DT')} < {epoch_date('EFF_DT')}",
              "END_DT IS NOT NULL AND EFF_DT IS NOT NULL", "P2_alert", "END_DT < EFF_DT",
              "not stated (no records found)"),
    ]
    return out


def _gnaf_rules() -> list[Rule]:
    c, t = "X_ADDRESS_ID", T("X_ADDRESS_ID")
    scope = present(c)
    ask = "need confirmation from Salesforce before a solution is finalised"
    return [
        _rule(ADDRESS, c, "NUMERIC_LEGACY", "G-NAF ID is not a legacy numeric identifier",
              "format", f"{t} RLIKE '^[0-9]+$'", scope, "P3_monitor",
              "Numeric legacy identifier", "confirm whether it is replaced with G-NAF"),
        _rule(ADDRESS, c, "PIPE_DELIMITED", "G-NAF ID holds one identifier, not several",
              "format", f"{t} LIKE '%|%'", scope, "P3_monitor", "Pipe-delimited value", ask,
              "BCC sends this form today and UDP stores it."),
        _rule(ADDRESS, c, "FREE_TEXT_OR_INVALID", "G-NAF ID is a current G-NAF PID",
              "format",
              f"{t} NOT RLIKE '^GA[A-Z]{{2,3}}[0-9]+$' AND {t} NOT RLIKE '^[0-9]+$' "
              f"AND {t} NOT LIKE '%|%'", scope, "P3_monitor", "Free text or invalid value",
              ask, "An underscore after the state code (GAWA_...) counts as invalid here: "
              "the analysis files those samples under this category."),
    ]


def _line_rules(col: str, label: str, *, max_len: int | None,
                state_postcode: bool = False, street_number: bool = False) -> list[Rule]:
    t = T(col)
    scope = present(col)
    out = [
        _rule(ADDRESS, col, "LEADING_OR_TRAILING_WHITESPACE",
              f"{label} has no leading or trailing whitespace", "format", f"{S(col)} <> {t}",
              scope, "P3_monitor", "Leading/trailing whitespace", "Optus amends"),
        _rule(ADDRESS, col, "CONTROL_CHARACTER", f"{label} has no control characters",
              "format", rf"{S(col)} RLIKE '\\p{{Cc}}'", scope, "P3_monitor",
              "Control character", "Optus amends"),
        _rule(ADDRESS, col, "REPEATED_SPACES", f"{label} has no repeated spaces", "format",
              f"{t} RLIKE ' {{2,}}'", scope, "P3_monitor", "Repeated spaces", "Optus amends"),
    ]
    if max_len:
        out.append(_rule(ADDRESS, col, f"EXCEEDS_{max_len}_CHARACTERS",
                         f"{label} is at most {max_len} characters", "format",
                         f"length({S(col)}) > {max_len}", scope, "P3_monitor",
                         "Over N characters", "confirm the limit with the Salesforce SME",
                         f"The PDF masks the limit; {max_len} is the DEVIATION query's. The "
                         "source column is varchar(255)."))
    if state_postcode:
        out.append(_rule(
            ADDRESS, col, "CONTAINS_STATE_OR_POSTCODE",
            f"{label} holds no state or postcode on an Australian address", "consistency",
            rf"upper(trim(cast(X_INTERNATIONAL_ADDRESS AS STRING))) IN ('N', 'NO', '0', 'FALSE', 'F') "
            rf"AND ({t} RLIKE '(?i)(^|\\s)(NSW|VIC|QLD|WA|SA|TAS|ACT|NT|NEW SOUTH WALES|"
            rf"VICTORIA|QUEENSLAND|WESTERN AUSTRALIA|SOUTH AUSTRALIA|TASMANIA|"
            rf"AUSTRALIAN CAPITAL TERRITORY|NORTHERN TERRITORY)(\\s|$)' "
            rf"OR {t} RLIKE '(^|\\s)[0-9]{{4}}(\\s|$)')",
            scope, "P3_monitor", "Contains suburb, state or postcode already held separately",
            "Optus amends",
            "State and postcode only, on rows flagged Australian, as the DEVIATION query "
            "does. A suburb is not checked: matching it means comparing with CITY, which "
            "nobody has specified."))
    if street_number:
        out.append(_rule(ADDRESS, col, "DUPLICATES_STREET_NUMBER",
                         f"{label} does not repeat the street number", "consistency",
                         f"{t} = {T('STREET_NUMBER')}", f"{scope} AND {present('STREET_NUMBER')}",
                         "P3_monitor", "Duplicates STREET_NUMBER", "Optus amends"))
    return out


# --- business organisation counts -------------------------------------------------

def _count_rules(col: str, label: str, *, office: bool) -> list[Rule]:
    t = T(col)
    scope = present(col)
    sci = "(?i)^-?[0-9]+(\\\\.[0-9]+)?e[+-]?[0-9]+$"
    out = [
        _rule(BUS_ORG, col, "NON_NUMERIC_OR_TEXT", f"{label} is a number", "format",
              f"{t} NOT RLIKE '[0-9]'", scope, "P2_alert", f"{col}_NON_NUMERIC_OR_TEXT",
              "not stated (no records found)"),
        _rule(BUS_ORG, col, "CURRENCY_SEPARATOR_OR_UNIT_TEXT",
              f"{label} carries no currency, separator or unit text", "format",
              rf"{t} RLIKE '[0-9]' AND {t} RLIKE '[$,]|\\p{{L}}' AND {t} NOT RLIKE '{sci}'",
              scope, "P2_alert", f"{col}_CURRENCY_SEPARATOR_OR_UNIT_TEXT",
              "not stated (no records found)"),
        _rule(BUS_ORG, col, "DECIMAL_OR_NON_WHOLE", f"{label} is a whole number", "format",
              f"{t} RLIKE '^-?[0-9]*\\\\.[0-9]+$'", scope, "P2_alert",
              f"{col}_DECIMAL_OR_NON_WHOLE", "not stated (no records found)"),
        _rule(BUS_ORG, col, "SCIENTIFIC_NOTATION", f"{label} is not in scientific notation",
              "format", f"{t} RLIKE '{sci}'", scope, "P2_alert", f"{col}_SCIENTIFIC_NOTATION",
              "not stated (no records found)"),
        _rule(BUS_ORG, col, "NEGATIVE", f"{label} is not negative", "format",
              f"{t} RLIKE '^-\\\\s*[0-9]'", scope, "P2_alert", f"{col}_NEGATIVE",
              "not stated (no records found)"),
    ]
    if office:
        out += [
            _rule(BUS_ORG, col, "ZERO_PLACEHOLDER", f"{label} is not zero", "sentinel",
                  f"{t} RLIKE '^0+$'", scope, "P3_monitor", f"{col}_ZERO_PLACEHOLDER",
                  "confirm with the business before remediation"),
            _rule(BUS_ORG, col, "LEADING_ZERO_FORMAT", f"{label} has no leading zero",
                  "format", f"{t} RLIKE '^0+[1-9][0-9]*$'", scope, "P3_monitor",
                  f"{col}_LEADING_ZERO_FORMAT", "Optus amends, standardise after confirmation"),
            _rule(BUS_ORG, col, "POSSIBLE_PHONE_NUMBER", f"{label} is not a phone number",
                  "format",
                  f"{_digits(col)} RLIKE '^(0[23478][0-9]{{8}}|61[23478][0-9]{{8}}|1[38]00[0-9]{{6}})$'",
                  scope, "P2_alert", f"{col}_POSSIBLE_PHONE_NUMBER",
                  "customer amends or correct the source mapping"),
            _rule(BUS_ORG, col, "IMPLAUSIBLE_OUTLIER", f"{label} is at most 1000", "format",
                  f"{t} RLIKE '^[0-9]+$' AND try_cast({t} AS BIGINT) > 1000", scope,
                  "P3_monitor", f"{col}_IMPLAUSIBLE_OUTLIER",
                  "customer amends after business confirmation",
                  "1000 is the '#1 - DQ Issues' query's cut-off; the PDF masks it."),
        ]
    else:
        out.append(_rule(BUS_ORG, col, "ZERO_OR_ZERO_PADDED", f"{label} is not zero",
                         "sentinel", f"{t} RLIKE '^0+$'", scope, "P3_monitor",
                         f"{col}_ZERO_OR_ZERO_PADDED",
                         "Optus to confirm whether zero is a real count or unknown",
                         "Zero passes every numeric rule; the question is what it means."))
    return out


# --- website, establishment date, ARBN --------------------------------------------

WEBSITE_PLACEHOLDERS = ("http://n/a", "http://no", "http://none", "http://www.nowebsite.com",
                        ".", "http://0", "http://nil", "http://----")
ARBN_PLACEHOLDERS = ("n/a", "na", "nil", "none", "-")
# 1753-01-01 00:00 at UTC+10, the value the '#1 - DQ Issues' query names. Compared raw so
# the session time zone cannot move it.
SQL_SERVER_MIN_DATE_MS = -6847840800000


def _web_rules() -> list[Rule]:
    c, t = "WEB_SITE", T("WEB_SITE")
    scope = present(c)
    return [
        _rule(BUS_ORG, c, "PLACEHOLDER", "Website is not a placeholder", "sentinel",
              f"lower({t}) IN {_in(WEBSITE_PLACEHOLDERS)}", scope, "P2_alert",
              "Website is a placeholder", "delete",
              "The list is the PDF's, compared lower-cased: the PDF's own query compared "
              "'http://Nil' with a lower-cased value, so it never matched."),
        _rule(BUS_ORG, c, "MISSING_PROTOCOL", "Website starts with http:// or https://",
              "format",
              f"lower({t}) NOT RLIKE '^https?://' AND lower({t}) NOT IN {_in(WEBSITE_PLACEHOLDERS)}",
              scope, "P2_alert", "Website is missing protocol", "customer amends"),
    ]


def _establish_rules() -> list[Rule]:
    c = "ESTABLISH_DATE"
    d = epoch_date(c)
    raw = f"try_cast({S(c)} AS BIGINT)"
    scope = f"{c} IS NOT NULL"
    return [
        _rule(BUS_ORG, c, "INVALID_EPOCH_VALUE", "Year started is an epoch-millisecond value",
              "format", f"{raw} IS NULL", scope, "P3_monitor", "Invalid epoch values",
              "not stated (none found)"),
        _rule(BUS_ORG, c, "FUTURE", "Year started is not in the future", "format",
              f"{d} > current_date()", f"{scope} AND {raw} IS NOT NULL", "P3_monitor",
              "Future dates", "Optus amends"),
        _rule(BUS_ORG, c, "PLACEHOLDER_1753", "Year started is not the 1753-01-01 placeholder",
              "sentinel", f"{raw} = {SQL_SERVER_MIN_DATE_MS}", scope, "P3_monitor",
              "Primary system placeholder/default date", "remediate as a placeholder"),
        _rule(BUS_ORG, c, "BEFORE_SUPPORTED_HISTORY", "Year started is not before 1900",
              "format", f"{d} < DATE'1900-01-01'", f"{scope} AND {raw} IS NOT NULL",
              "P3_monitor", "Before supported history", "check with BCC",
              _YEAR_ASSUMED + " Includes the placeholder."),
    ]


def _arbn_rules() -> list[Rule]:
    c, t = "X_ARBN", T("X_ARBN")
    scope = present(c)
    return [
        _rule(BUS_ORG, c, "WRONG_LENGTH_NUMERIC", "ARBN is nine digits", "format",
              f"{t} RLIKE '^[0-9]+$' AND length({t}) <> 9 AND {t} NOT RLIKE '^0+$'", scope,
              "P2_alert", "Wrong-length numeric values", "customer amends"),
        _rule(BUS_ORG, c, "OTHER_NON_NUMERIC", "ARBN is digits only", "format",
              f"{t} RLIKE '[^0-9]' AND lower({t}) NOT IN {_in(ARBN_PLACEHOLDERS)}", scope,
              "P2_alert", "Other non-numeric values", "delete"),
        _rule(BUS_ORG, c, "ALL_ZEROS_PLACEHOLDER", "ARBN is not all zeros", "sentinel",
              f"{t} RLIKE '^0+$'", scope, "P2_alert", "All-zero placeholders", "delete"),
        _rule(BUS_ORG, c, "PLACEHOLDER_TEXT", "ARBN is not placeholder text", "sentinel",
              f"lower({t}) IN {_in(ARBN_PLACEHOLDERS)}", scope, "P2_alert",
              "Placeholder text values", "delete"),
    ]


MIGRATION_RULES: list[Rule] = [
    *_name_rules("FIRST_NAME", "First name", presence=True, length=True, estate=True),
    *_name_rules("MIDDLE_NAME", "Middle name", presence=False, length=True, estate=False),
    *_name_rules("LAST_NAME", "Last name", presence=True, length=False, estate=False),
    *_phone_rules(CONTACT, "PHONE", "Contact phone", null_solution="not stated (NA)",
                  bad_solution="delete or customer amends"),
    *_email_rules(),
    *_dob_rules(),
    *_id_rules(CONTACT, "CONTACT_ID", "Contact ID",
               "outside the current migration scope; source correction if brought in"),
    *_role_rules(),
    *_address_date_rules(),
    *_gnaf_rules(),
    *_line_rules("X_SUB_ADDRESS_NUMBER", "Sub-address number", max_len=None,
                 street_number=True),
    *_line_rules("ADDRESS_3", "Address line 3", max_len=80, state_postcode=True),
    *_line_rules("ADDRESS_4", "Address line 4", max_len=80),
    *_phone_rules(BUS_ORG, "PHONE", "Business phone",
                  null_solution="Optus amends if another source has it",
                  bad_solution="customer amends"),
    *_count_rules("X_NUMBER_OF_EMPLOYEE", "Number of employees", office=False),
    *_count_rules("X_NUMBER_OF_OFFICE", "Number of offices", office=True),
    *_web_rules(),
    *_establish_rules(),
    *_arbn_rules(),
    *_id_rules(BUS_ORG, "ORG_ID", "Organisation ID", "source or technical correction"),
    *_id_rules(CUSTOMER, "CUSTOMER_ID", "Customer ID",
               "source correction; investigate and replace the invalid identifier"),
]

# What the analysis lists and this file does not register, and why. Said here so a
# reader comparing the PDF with the register can account for every category.
NOT_REGISTERED = {
    "E_MAIL DQ_INVALID_EMAIL": "a flag another system computes (dq_email_invalid_*), "
                               "not rule logic",
    "E_MAIL EMAIL_INVALID_HARD_BOUNCE": "needs the bounce list, which no table here holds",
    "E_MAIL EMAIL_INVALID_OTHERS": "reads Jarvis eml_stts_cd values nobody has listed",
    "FIRST_NAME LESS_THAN_ONE_CHARACTER": "returns exactly NULL_OR_BLANK's rows",
    "MIDDLE_NAME NULL_OR_BLANK": "informational: a middle name is optional",
    "PHONE special service / shared / landline": "informational in the analysis",
    "ADDRESS_3, ADDRESS_4 duplicated address component": "the analysis has not defined it "
                                                         "('need to check')",
    "X_NUMBER_OF_EMPLOYEE EXCEEDS_N_DIGITS": "the digit limit is masked in the PDF and in "
                                             "no query",
    "ESTABLISH_DATE implausibly old dates": "the date range is masked",
}

BY_ID = {r.rule_id: r for r in MIGRATION_RULES}
assert len(BY_ID) == len(MIGRATION_RULES), "duplicate rule id"
for _r in MIGRATION_RULES:
    assert _r.cde_id in {a.cde_id for a in KEY_ATTRIBUTES}, _r.rule_id
del _r


def custom_rules_of(attr: KeyAttribute) -> list[Rule]:
    return [r for r in MIGRATION_RULES if r.cde_id == attr.cde_id]

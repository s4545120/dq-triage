"""The rule set, evaluated against the pilot CSVs.

Each rule carries BOTH a SQL `rule_expr` (what would run on Databricks, and what
gets written into config.rule_registry) and a Python `evaluator` (what runs here on
a laptop). They must agree. Where they cannot -- cross-table rules need a join the
single-table rule_expr cannot express -- the SQL is written as a full statement and
flagged with join_sql, so nothing pretends a join is a column predicate.

Rule types mirror the enum in sql/ddl/01_config_rule_registry.sql.

WHY SO MANY RULES PASS. Nine of these report zero violations on the snapshot. That
is deliberate: a fixture where every rule breaches cannot exercise the pass path,
cannot produce a closure rate, and gives the scorecard no denominator. Six of them
are given a history of having been broken and fixed (see build_fixtures.py), which
is what makes MTTR and closure rate real numbers rather than placeholders.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MOBILE_RE = re.compile(r"^04\d{8}$")
LANDLINE_RE = re.compile(r"^0\d{9}$")
MSISDN_RE = re.compile(r"^04\d{8}$")
SENTINELS = {"service-number-unknown", "unknown", "n/a", "na", "none", "null", ""}

SUBS_TABLE = "prod.customer.subs_c"
CTCT_TABLE = "prod.customer.ctct_c"


@dataclass
class Ctx:
    """The three frames a rule can be written against."""

    subs: pd.DataFrame
    ctct: pd.DataFrame
    xref: pd.DataFrame  # subs LEFT JOIN ctct ON CTCT_KEY, suffixes _s / _c


@dataclass
class Rule:
    rule_id: str
    rule_name: str
    target_table: str
    rule_type: str
    rule_expr: str
    evaluator: Callable[[Ctx], tuple[pd.DataFrame, pd.Series]]
    severity: str = "P2_alert"
    target_column: str | None = None
    scope_filter: str | None = None
    fail_threshold_pct: float = 0.0
    business_domain: str = "Customer"
    owner_group: str = "dq-stewards-customer"
    source_layer: str = "L2"
    status: str = "active"
    rule_version: int = 1
    # The FROM-clause BODY for a cross-table rule: the joined table expression with
    # its aliases and ON condition, never a whole SELECT and never the predicate.
    # rule_expr stays the predicate and references these aliases, so it is stored
    # once. Until 2026-09-28 this held a full SELECT including its own WHERE, which
    # meant every cross-table rule carried two copies of its predicate and nothing
    # kept them in step. config.rule_registry.join_sql is now the column that holds
    # this, so sql/checkrun.py and jobs/run_checks.py read it from the registry rather
    # than importing it from here.
    join_sql: str | None = None
    key_column: str = "SUBS_KEY"
    sample_columns: list[str] = field(default_factory=list)
    # Prior versions of this rule, written to the registry as history.
    superseded: list[dict] = field(default_factory=list)
    note: str = ""

    def evaluate(self, ctx: Ctx) -> tuple[int, pd.DataFrame]:
        """Returns (rows_scanned, violating_rows)."""
        scope, mask = self.evaluator(ctx)
        return len(scope), scope[mask]


# ---------------------------------------------------------------------------
# Contact rules
# ---------------------------------------------------------------------------

def _eml_scope(c: Ctx) -> pd.DataFrame:
    return c.ctct[c.ctct.EML_ID.str.strip() != ""]


def _has_no_at(v: str) -> bool:
    return "@" not in v


def _has_whitespace(v: str) -> bool:
    return bool(re.search(r"\s", v))


def _has_no_tld(v: str) -> bool:
    return "@" in v and "." not in v.split("@")[-1]


def _has_double_dot(v: str) -> bool:
    return ".." in v


def _has_trailing_dot(v: str) -> bool:
    return v.endswith(".")


_EML_DEFECTS = (_has_no_at, _has_whitespace, _has_no_tld, _has_double_dot, _has_trailing_dot)


def _any_eml_defect(v: str) -> bool:
    return any(f(v) for f in _EML_DEFECTS)


def _eml_rule(predicate):
    def _inner(c: Ctx):
        scope = _eml_scope(c)
        return scope, scope.EML_ID.str.strip().map(predicate)
    return _inner


# The composite and the five specific rules overlap on purpose. Overlapping rules
# are what real registries look like -- a broad well-formedness rule inherited from
# a platform standard, plus narrow rules a domain team added for the failure modes
# they actually see. The 240 bad addresses therefore trip six rules at once, which
# is precisely the situation cohorting exists to collapse.
_ctct_eml_fmt = _eml_rule(_any_eml_defect)
_ctct_eml_no_at = _eml_rule(_has_no_at)
_ctct_eml_whitespace = _eml_rule(_has_whitespace)
_ctct_eml_domain_tld = _eml_rule(_has_no_tld)
_ctct_eml_double_dot = _eml_rule(_has_double_dot)
_ctct_eml_trailing_dot = _eml_rule(_has_trailing_dot)


def _ctct_eml_null(c: Ctx):
    return c.ctct, c.ctct.EML_ID.str.strip() == ""


def _ctct_eml_stts_null(c: Ctx):
    return c.ctct, c.ctct.EML_STTS_CD.str.strip() == ""


def _ctct_eml_stts_consistent(c: Ctx):
    """Flagged INVALID while the address is actually well formed.

    Zero on this snapshot: all 240 flagged rows are genuinely defective, so the
    upstream validator is accurate. That is worth knowing and worth re-proving every
    run -- a rule that passes is not a rule that is wasted. It is also the rule that
    would fire first if someone "fixed" the email data without clearing the flag.
    """
    scope = _eml_scope(c)
    clean = ~scope.EML_ID.str.strip().map(_any_eml_defect)
    return scope, (scope.EML_STTS_CD == "INVALID") & clean


def _ctct_mobl_null(c: Ctx):
    return c.ctct, c.ctct.MOBL_NO.str.strip() == ""


def _ctct_mobl_fmt(c: Ctx):
    scope = c.ctct[c.ctct.MOBL_NO.str.strip() != ""]
    return scope, ~scope.MOBL_NO.str.strip().map(lambda v: bool(MOBILE_RE.match(v)))


def _ctct_phn_fmt(c: Ctx):
    scope = c.ctct[c.ctct.PHN_NO.str.strip() != ""]
    return scope, ~scope.PHN_NO.str.strip().map(lambda v: bool(LANDLINE_RE.match(v)))


def _ctct_key_unique(c: Ctx):
    return c.ctct, c.ctct.CTCT_KEY.duplicated(keep=False)


def _ctct_brth_parseable(c: Ctx):
    """14 rows carry '31-02-1988': DD-MM-YYYY where every other row is ISO, and a
    date that does not exist in any format. Two defects in one value, which is why
    it gets its own rule rather than being folded into the range check -- a range
    check on an unparseable value can only report NULL, which tells a steward
    nothing about what to fix."""
    scope = c.ctct[c.ctct.BRTH_TS.str.strip() != ""]
    parsed = pd.to_datetime(scope.BRTH_TS, format="%Y-%m-%d %H:%M:%S", errors="coerce")
    return scope, parsed.isna()


def _ctct_brth_plausible(c: Ctx):
    """Scoped to rows that parse, so it measures age and nothing else. 27 contacts
    are 17 years old. A minor as the named contact on a telco account is a consent
    and credit-check question, not a formatting nit -- hence P2, not P3."""
    scope = c.ctct[c.ctct.BRTH_TS.str.strip() != ""].copy()
    yr = pd.to_numeric(scope.BRTH_TS.str.slice(0, 4), errors="coerce")
    scope = scope[yr.notna()]
    yr = yr[yr.notna()]
    return scope, (yr < 1920) | (yr > 2008)


def _ctct_idnt_doc_null(c: Ctx):
    scope = c.ctct[c.ctct.IDNT_TYPE_1_CD.str.strip() != ""]
    return scope, scope.IDNT_DOC_1_NO.str.strip() == ""


def _ctct_spcl_care_variance(c: Ctx):
    """Zero-variance column. Every row is the violation, because the column tells
    us nothing -- either the source never populates it or the load drops it."""
    constant = c.ctct.SPCL_CARE_STTS.nunique(dropna=False) <= 1
    return c.ctct, pd.Series(constant, index=c.ctct.index)


def _ctct_pref_lang_variance(c: Ctx):
    constant = c.ctct.PREF_LANG_NM.nunique(dropna=False) <= 1
    return c.ctct, pd.Series(constant, index=c.ctct.index)


# ---------------------------------------------------------------------------
# Contact rules extracted from the workspace folder "DQ Queries" -- 2026-10-05
# ---------------------------------------------------------------------------
# Seven saved SQL Editor queries (First Name, Middle Name, Last Name, Birth Date,
# Phone, Identifier, Email) written against the real source,
# prod.udp_brnz_nrt_tech_view.table_contact_hist, which this workspace cannot see.
# Each check is re-expressed on the mock ctct_c column that realises the same
# attribute: FIRST_NAME -> FRST_NM, MIDDLE_NAME -> MID_NM, LAST_NAME -> LAST_NM,
# PHONE -> PHN_NO / MOBL_NO, BIRTH_DATE -> BRTH_TS, CONTACT_ID -> CTCT_ID.
#
# Every one lands in SHADOW. The rules they replace stay active until a steward
# promotes the new ones -- shadow first, then retire the old version.
#
# Three things changed on the way in, all on purpose:
#   * POSIX classes. The queries use [[:space:]] and [[:cntrl:]]. Spark RLIKE is
#     Java regex, where those are character sets of the letters ': s p a c e' --
#     verified on the warehouse: 'Ms Jane' fails the title check, 'Mrs' passes it,
#     'John' has a control character and ' 0412' has no leading space. Here they
#     are \s and \p{Cc}.
#   * '\.' in a Spark string literal is '.', so the queries' title check took any
#     character after MR/MS. Here it is written '\\.' as every other rule is.
#   * The queries' rules are consolidated per column (presence, placeholder,
#     formatting, contamination, length, structure) rather than mirrored 1:1, and
#     LESS_THAN_ONE_CHARACTER is dropped: it returns exactly NULL_OR_BLANK's rows.
#     STARTS_WITH_NON_LETTER is subsumed by the structure rule.
#
# Python's re has no \p{L}; [^\W\d_] is the same set of letters.

_LETTER = r"[^\W\d_]"
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")

NAME_PLACEHOLDERS = (
    "N/A", "NONE", "NULL", "UNKNOWN", "NOT APPLICABLE", "NOT PROVIDED", "TBC", "TBD",
    "TEST", "DUMMY", "SAMPLE", "UNDEFINED", "NOT AVAILABLE",
)
_NAME_TITLE_RE = re.compile(r"^(MR|MISS|MRS|MS)\.?\s+", re.IGNORECASE)
_NAME_COMPANY_RE = re.compile(r"(?:^|[\W\d_])(P-L|PTY|PTY LTD)(?:[\W\d_]|$)", re.IGNORECASE)
_NAME_ADDRESS_RE = re.compile(
    r"(?:^|\s)(C/O|CARE OF|PO BOX|UNIT|SUITE|LEVEL|FLOOR|STREET|ROAD|AVENUE|DRIVE|"
    r"HIGHWAY|POSTCODE|SUBURB|NOTE|NOTES)(?:\s|:|$)", re.IGNORECASE)
_NAME_LINK_RE = re.compile(r"(@|https?://|www\.)")
_NAME_STRUCTURE_RE = re.compile(
    rf"{_LETTER}+(?:[   -   　'\-]{_LETTER}+)*")
NAME_MAX_LEN = 40


def _name_scope(c: Ctx, col: str) -> pd.DataFrame:
    return c.ctct[c.ctct[col].str.strip() != ""]


def _name_formatting_defect(v: str) -> bool:
    # Spark's trim() strips spaces only; a tab is caught as a control character.
    t = v.strip(" ")
    return (v != t or bool(_CONTROL_RE.search(v))
            or t[:1] in ("-", "'") or t[-1:] in ("-", "'")
            or bool(re.search(r"[-']{2,}", t)))


def _name_contaminated(v: str) -> bool:
    t = v.strip(" ")
    return bool(_NAME_TITLE_RE.search(t) or _NAME_COMPANY_RE.search(t)
                or _NAME_ADDRESS_RE.search(t) or _NAME_LINK_RE.search(t))


def _name_null(col: str):
    def _inner(c: Ctx):
        return c.ctct, c.ctct[col].str.strip() == ""
    return _inner


def _name_rule(col: str, predicate):
    def _inner(c: Ctx):
        scope = _name_scope(c, col)
        return scope, scope[col].map(predicate)
    return _inner


def _name_placeholder(v: str) -> bool:
    return v.strip(" ").upper() in NAME_PLACEHOLDERS


def _name_too_long(v: str) -> bool:
    return len(v) > NAME_MAX_LEN


def _name_bad_structure(v: str) -> bool:
    return not _NAME_STRUCTURE_RE.fullmatch(v.strip(" "))


# Scope filters are written longhand, never with dq.fn.: sql/seed.py, sql/checkrun.py
# and the runner rewrite the helper prefix in rule_expr only.


def _name_sql(col: str) -> dict[str, str]:
    """The SQL twin of each name predicate, for one column."""
    t = f"trim({col})"
    placeholders = ", ".join(f"'{p}'" for p in NAME_PLACEHOLDERS)
    return dict(
        placeholder=f"dq.fn.is_name_placeholder_v1({col})",
        placeholder_v1=f"upper({t}) IN ({placeholders})",
        formatting=(f"{col} <> {t} OR {col} RLIKE '\\\\p{{Cc}}' "
                    f"OR {t} RLIKE '^[-\\\\x27]|[-\\\\x27]$|[-\\\\x27]{{2,}}'"),
        contaminated=(
            f"{t} RLIKE '(?i)^(MR|MISS|MRS|MS)\\\\.?\\\\s+' "
            f"OR {t} RLIKE '(?i)(^|[^\\\\p{{L}}])(P-L|PTY|PTY LTD)([^\\\\p{{L}}]|$)' "
            f"OR {t} RLIKE '(?i)(^|\\\\s)(C/O|CARE OF|PO BOX|UNIT|SUITE|LEVEL|FLOOR|STREET|"
            f"ROAD|AVENUE|DRIVE|HIGHWAY|POSTCODE|SUBURB|NOTE|NOTES)(\\\\s|:|$)' "
            f"OR {t} RLIKE '(@|https?://|www\\\\.)'"),
        length=f"length({col}) > {NAME_MAX_LEN}",
        structure=f"{t} NOT RLIKE '^\\\\p{{L}}+([\\\\p{{Zs}}\\\\x27-]\\\\p{{L}}+)*$'",
    )


# --- phone ------------------------------------------------------------------
# The query normalises before it judges: strip everything but digits, then turn
# 61xxxxxxxxx and a nine-digit number missing its leading zero into the local
# 0xxxxxxxxx form. A number is well formed if that result is an Australian mobile
# (04) or landline (02/03/07/08) and the raw value held nothing but digits and the
# washable characters -- space ( ) + . / -. 1300/1800/1900 numbers are reported
# separately by the query and are out of scope of the format rules here.

PHONE_PLACEHOLDERS = (
    # The later migration-scope version of the Phone query...
    "0400000000", "0400000001", "0400000002", "0404040404", "0400000123", "0400000321",
    "0400009999", "0410000000", "0411000321", "0411111110", "0411111111", "0412000123",
    "0412345678", "0413234234", "0420000000", "0421212111", "0422222222", "0432100000",
    "0433333333", "0444444444", "0452397392", "0455555555", "0477777777", "0488888888",
    "0491570006", "0499999999", "0200000000", "0200000001", "0222222222", "0250000000",
    "0280000000", "0280808080", "0288888888", "0290000000", "0299999999", "0300000000",
    "0390000000", "0700000000", "0800000000", "1300000000", "1300300937", "133937",
    # ...and the six only the whole-population version carries. The two lists had
    # drifted apart; this is their union.
    "1300133937", "0400011132", "0411111112", "0411111113", "0411111116", "0422226838",
)
_PHONE_WASHABLE = r"[^0-9\s()+./-]"


def _au_digits(v: str) -> str:
    d = re.sub(r"[^0-9]", "", v)
    if re.fullmatch(r"61\d{9}", d):
        return "0" + d[2:]
    if re.fullmatch(r"[23478]\d{8}", d):
        return "0" + d
    return d


def _au_digits_sql(col: str) -> str:
    d = f"regexp_replace({col}, '[^0-9]', '')"
    return (f"CASE WHEN {d} RLIKE '^61[0-9]{{9}}$' THEN concat('0', substr({d}, 3)) "
            f"WHEN {d} RLIKE '^[23478][0-9]{{8}}$' THEN concat('0', {d}) ELSE {d} END")


def _is_special_service(v: str) -> bool:
    return bool(re.match(r"(13|18|19)00", _au_digits(v)))


def _is_au_phone(au: str, mobile_only: bool) -> bool:
    if MOBILE_RE.fullmatch(au):
        return True
    return not mobile_only and bool(re.fullmatch(r"0[2378]\d{8}", au))


def _phone_scope(c: Ctx, col: str) -> pd.DataFrame:
    scope = c.ctct[c.ctct[col].str.strip() != ""]
    return scope[~scope[col].map(_is_special_service)]


def _phone_fmt(col: str, mobile_only: bool):
    def _inner(c: Ctx):
        scope = _phone_scope(c, col)
        bad = scope[col].map(lambda v: bool(re.search(_PHONE_WASHABLE, v))
                             or not _is_au_phone(_au_digits(v), mobile_only))
        return scope, bad
    return _inner


def _phone_washable(col: str, mobile_only: bool):
    def _inner(c: Ctx):
        scope = _phone_scope(c, col)
        hit = scope[col].map(lambda v: bool(re.search(r"[^0-9]", v))
                             and not re.search(_PHONE_WASHABLE, v)
                             and _is_au_phone(_au_digits(v), mobile_only))
        return scope, hit
    return _inner


def _phone_placeholder(col: str):
    def _inner(c: Ctx):
        scope = c.ctct[c.ctct[col].str.strip() != ""]
        hit = scope[col].map(lambda v: _au_digits(v) in PHONE_PLACEHOLDERS
                             or bool(re.search(r"0{7,}", re.sub(r"[^0-9]", "", v))))
        return scope, hit
    return _inner


def _ctct_mobl_shared(c: Ctx):
    scope = c.ctct[c.ctct.MOBL_NO.str.strip() != ""]
    au = scope.MOBL_NO.map(_au_digits)
    return scope, au.map(au.value_counts()) > 10


def _phone_sql(col: str, mobile_only: bool, helpers: bool = True) -> dict[str, str]:
    """v2 (helpers=True) calls dq.fn.au_phone_digits_v1 and is_phone_placeholder_v1;
    v1 (helpers=False) is the longhand the rules were first registered with.

    The scope filter cannot call a helper -- seed.py, checkrun.py and the runner
    rewrite dq.fn. in rule_expr only -- and does not need one: no number that the
    normalisation rewrites starts 13, 18 or 19 either side of it, so testing the
    bare digits for a special-service prefix is the same test."""
    au = f"dq.fn.au_phone_digits_v1({col})" if helpers else _au_digits_sql(col)
    valid = (f"dq.fn.is_au_mobile_v1({au})" if mobile_only
             else f"(dq.fn.is_au_mobile_v1({au}) OR ({au}) RLIKE '^0[2378][0-9]{{8}}$')")
    placeholders = ", ".join(f"'{p}'" for p in PHONE_PLACEHOLDERS)
    present = f"{col} IS NOT NULL AND trim({col}) <> ''"
    return dict(
        scope=(f"{present} AND regexp_replace({col}, '[^0-9]', '') NOT RLIKE '^(13|18|19)00'"
               if helpers else f"{present} AND NOT ({au}) RLIKE '^(13|18|19)00'"),
        fmt=f"{col} RLIKE '[^0-9\\\\s()+./-]' OR NOT {valid}",
        washable=f"{col} RLIKE '[^0-9]' AND NOT {col} RLIKE '[^0-9\\\\s()+./-]' AND {valid}",
        placeholder=(f"dq.fn.is_phone_placeholder_v1({col})" if helpers else
                     f"({au}) IN ({placeholders}) "
                     f"OR regexp_replace({col}, '[^0-9]', '') RLIKE '0{{7,}}'"),
        au=au,
    )


# --- date of birth ----------------------------------------------------------
# The query measures age from CURRENT_DATE(), so the same row can pass this month
# and breach the next with nothing changed. The SQL keeps current_date() -- the
# runner has no run-date placeholder -- and the evaluator is anchored to the
# fixture's final run instead. build_fixtures.py asserts the two dates agree.
# A fixture count and a warehouse count of these three rules are only comparable
# when the warehouse run falls on AS_OF.
AS_OF = pd.Timestamp("2026-09-02")
DOB_PLACEHOLDERS = ("1900-01-01", "1901-01-01", "1970-01-01", "1980-01-01")
_DOB_SQL = "to_date(try_to_timestamp(BRTH_TS, 'yyyy-MM-dd HH:mm:ss'))"
_DOB_SCOPE = "try_to_timestamp(BRTH_TS, 'yyyy-MM-dd HH:mm:ss') IS NOT NULL"


def _dob_scope(c: Ctx) -> tuple[pd.DataFrame, pd.Series]:
    parsed = pd.to_datetime(c.ctct.BRTH_TS, format="%Y-%m-%d %H:%M:%S", errors="coerce")
    scope = c.ctct[parsed.notna()]
    return scope, parsed[parsed.notna()].dt.normalize()


def _dob_rule(predicate):
    def _inner(c: Ctx):
        scope, dob = _dob_scope(c)
        return scope, predicate(dob)
    return _inner


def _years_ago(n: int) -> pd.Timestamp:
    return AS_OF - pd.DateOffset(years=n)


_ctct_brth_future = _dob_rule(lambda d: d > AS_OF)
_ctct_brth_under_14 = _dob_rule(lambda d: (d <= AS_OF) & (d > _years_ago(14)))
_ctct_brth_minor_review = _dob_rule(lambda d: (d <= _years_ago(14)) & (d > _years_ago(18)))
_ctct_brth_over_110 = _dob_rule(lambda d: d < _years_ago(110))
_ctct_brth_placeholder = _dob_rule(
    lambda d: d.dt.strftime("%Y-%m-%d").isin(DOB_PLACEHOLDERS))


def _ctct_brth_null(c: Ctx):
    return c.ctct, c.ctct.BRTH_TS.str.strip() == ""


# --- contact identifier -----------------------------------------------------

def _ctct_id_scope(c: Ctx) -> pd.DataFrame:
    return c.ctct[c.ctct.CTCT_ID.str.strip() != ""]


def _ctct_id_null(c: Ctx):
    return c.ctct, c.ctct.CTCT_ID.str.strip() == ""


def _ctct_id_numeric(c: Ctx):
    scope = _ctct_id_scope(c)
    return scope, ~scope.CTCT_ID.str.strip().str.fullmatch(r"[0-9]+")


def _ctct_id_formatting(c: Ctx):
    scope = _ctct_id_scope(c)
    return scope, scope.CTCT_ID.map(lambda v: v != v.strip(" ") or bool(_CONTROL_RE.search(v)))


def _ctct_id_unique(c: Ctx):
    scope = _ctct_id_scope(c)
    return scope, scope.CTCT_ID.str.strip().duplicated(keep=False)


# ---------------------------------------------------------------------------
# Subscription rules
# ---------------------------------------------------------------------------

def _subs_msisdn_sentinel(c: Ctx):
    scope = c.subs[c.subs.PRIM_RSRC_TYPE_KEY == "1"]
    return scope, scope.PRIM_RSRC_VALU_TXT.str.strip().str.lower().isin(SENTINELS)


def _subs_msisdn_fmt(c: Ctx):
    scope = c.subs[c.subs.PRIM_RSRC_TYPE_KEY == "1"]
    return scope, ~scope.PRIM_RSRC_VALU_TXT.str.strip().map(lambda v: bool(MSISDN_RE.match(v)))


def _subs_msisdn_unique(c: Ctx):
    scope = c.subs[
        (c.subs.PRIM_RSRC_TYPE_KEY == "1")
        & (~c.subs.PRIM_RSRC_VALU_TXT.str.strip().str.lower().isin(SENTINELS))
    ]
    return scope, scope.PRIM_RSRC_VALU_TXT.duplicated(keep=False)


def _subs_imei_null(c: Ctx):
    """NO SCOPE FILTER, ON PURPOSE.

    This rule is wrong and the fixture needs it to be wrong. All 200 violations are
    Fixed Broadband services, which have no handset and therefore no IMEI. It is the
    worked example behind cohort COH-B: a cohort whose root cause is a rule defect,
    not a data defect, and whose correct disposition is 'rejected' with the rule
    routed back to the registry. Do not add the scope_filter here.
    """
    return c.subs, c.subs.IMEI_ID.str.strip() == ""


def _subs_sim_null(c: Ctx):
    scope = c.subs[c.subs.PROD_TYPE_KEY != "0"]
    return scope, scope.SIM_SERL_ID.str.strip() == ""


def _subs_ntwk_null(c: Ctx):
    return c.subs, c.subs.NTWK_TECH_NM.str.strip() == ""


def _subs_prim_acct_zero(c: Ctx):
    """Also deliberately unscoped -- the second member of COH-B. Every violation is
    a prepaid service, which has no billing account by design."""
    return c.subs, c.subs.PRIM_ACCT_KEY == "0"


def _subs_bill_offr_zero(c: Ctx):
    scope = c.subs[c.subs.BILL_SUBS_TYPE_CD == "POSTPAID"]
    return scope, scope.MAIN_BILL_OFFR_KEY == "0"


def _subs_actv_ts_consistent(c: Ctx):
    return c.subs, c.subs.ORIG_ACTV_TS != c.subs.INIT_ACTV_TS


def _subs_stts_rsn_required(c: Ctx):
    scope = c.subs[c.subs.SUBS_STTS_KEY != "1"]
    return scope, scope.SUBS_STTS_RSN_KEY.isin(["0", ""])


def _subs_key_unique(c: Ctx):
    return c.subs, c.subs.SUBS_KEY.duplicated(keep=False)


def _subs_clse_ts_consistent(c: Ctx):
    """A closed record must be a cancelled subscription and vice versa."""
    closed = c.subs.ECF_CLSE_TS.str.strip() != ""
    cancelled = c.subs.SUBS_STTS_KEY == "2"
    return c.subs, closed != cancelled


def _subs_bnft_txt_null(c: Ctx):
    return c.subs, c.subs.BNFT_TXT.str.strip() == ""


# ---------------------------------------------------------------------------
# Cross-table rules
# ---------------------------------------------------------------------------

def _xref_orphan(c: Ctx):
    return c.xref, c.xref.CTCT_ID.isna()


def _xref_name_agreement(c: Ctx):
    scope = c.xref[c.xref.CTCT_ID.notna()]
    return scope, (
        scope.SUBS_FRST_NM.str.strip().str.lower()
        != scope.FRST_NM.str.strip().str.lower()
    )


def _xref_open_ts_agreement(c: Ctx):
    scope = c.xref[c.xref.CTCT_ID.notna()]
    return scope, scope.ECF_OPEN_TS != scope.CTCT_ADD_TS


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------

RULES: list[Rule] = [
    Rule(
        rule_id="CTCT_EML_FMT",
        rule_name="Contact email is well formed (composite)",
        target_table=CTCT_TABLE,
        target_column="EML_ID",
        rule_type="format",
        rule_expr="NOT dq.fn.is_valid_email_v1(EML_ID)",
        rule_version=2,
        superseded=[
            dict(
                rule_version=1,
                rule_expr=r"NOT (EML_ID RLIKE '^[^@\\s.]+(\\.[^@\\s.]+)*@[^@\\s.]+(\\.[^@\\s.]+)+$')",
                note=(
                    "v1 spelled the predicate out longhand. v2 calls dq.fn.is_valid_email_v1, the shared helper declared in sql/ddl/12_functions.sql. Identical counts on the same data -- sql/out/checkrun.sql was re-run against workspace.dq_triage before and after and every figure held. One definition instead of 2."
                ),
            )
        ],
        scope_filter="EML_ID IS NOT NULL AND trim(EML_ID) <> ''",
        evaluator=_ctct_eml_fmt,
        severity="P1_block",
        key_column="CTCT_KEY",
        sample_columns=["CTCT_KEY", "EML_ID", "EML_STTS_CD", "SRCE_NSRT_TS"],
        note="The platform-standard rule. Overlaps the five specific rules below by design.",
    ),
    Rule(
        rule_id="CTCT_EML_NO_AT",
        rule_name="Contact email contains an @",
        target_table=CTCT_TABLE,
        target_column="EML_ID",
        rule_type="format",
        rule_expr="EML_ID NOT LIKE '%@%'",
        scope_filter="EML_ID IS NOT NULL AND trim(EML_ID) <> ''",
        evaluator=_ctct_eml_no_at,
        severity="P1_block",
        key_column="CTCT_KEY",
        sample_columns=["CTCT_KEY", "EML_ID", "EML_STTS_CD"],
        note="Half of these have a space where the @ should be -- the signature of a concatenation bug, not user error.",
    ),
    Rule(
        rule_id="CTCT_EML_WHITESPACE",
        rule_name="Contact email contains no whitespace",
        target_table=CTCT_TABLE,
        target_column="EML_ID",
        rule_type="format",
        rule_expr=r"EML_ID RLIKE '\\s'",
        scope_filter="EML_ID IS NOT NULL AND trim(EML_ID) <> ''",
        evaluator=_ctct_eml_whitespace,
        severity="P2_alert",
        key_column="CTCT_KEY",
        sample_columns=["CTCT_KEY", "EML_ID", "EML_STTS_CD"],
    ),
    Rule(
        rule_id="CTCT_EML_DOMAIN_TLD",
        rule_name="Contact email domain has a top-level domain",
        target_table=CTCT_TABLE,
        target_column="EML_ID",
        rule_type="format",
        rule_expr="EML_ID LIKE '%@%' AND split_part(EML_ID, '@', -1) NOT LIKE '%.%'",
        scope_filter="EML_ID IS NOT NULL AND trim(EML_ID) <> ''",
        evaluator=_ctct_eml_domain_tld,
        severity="P2_alert",
        key_column="CTCT_KEY",
        sample_columns=["CTCT_KEY", "EML_ID"],
    ),
    Rule(
        rule_id="CTCT_EML_DOUBLE_DOT",
        rule_name="Contact email has no consecutive dots",
        target_table=CTCT_TABLE,
        target_column="EML_ID",
        rule_type="format",
        rule_expr="EML_ID LIKE '%..%'",
        scope_filter="EML_ID IS NOT NULL AND trim(EML_ID) <> ''",
        evaluator=_ctct_eml_double_dot,
        severity="P3_monitor",
        key_column="CTCT_KEY",
        sample_columns=["CTCT_KEY", "EML_ID"],
    ),
    Rule(
        rule_id="CTCT_EML_TRAILING_DOT",
        rule_name="Contact email does not end in a dot",
        target_table=CTCT_TABLE,
        target_column="EML_ID",
        rule_type="format",
        rule_expr="EML_ID LIKE '%.'",
        scope_filter="EML_ID IS NOT NULL AND trim(EML_ID) <> ''",
        evaluator=_ctct_eml_trailing_dot,
        severity="P3_monitor",
        key_column="CTCT_KEY",
        sample_columns=["CTCT_KEY", "EML_ID"],
    ),
    Rule(
        rule_id="CTCT_EML_NOT_NULL",
        rule_name="Contact email is present",
        target_table=CTCT_TABLE,
        target_column="EML_ID",
        rule_type="not_null",
        rule_expr="dq.fn.is_blank_v1(EML_ID)",
        rule_version=2,
        superseded=[
            dict(
                rule_version=1,
                rule_expr="EML_ID IS NULL OR trim(EML_ID) = ''",
                note=(
                    "v1 spelled the predicate out longhand. v2 calls dq.fn.is_blank_v1, the shared helper declared in sql/ddl/12_functions.sql. Identical counts on the same data -- sql/out/checkrun.sql was re-run against workspace.dq_triage before and after and every figure held. One definition instead of 8."
                ),
            )
        ],
        evaluator=_ctct_eml_null,
        severity="P2_alert",
        key_column="CTCT_KEY",
        sample_columns=["CTCT_KEY", "EML_ID", "EML_STTS_CD"],
    ),
    Rule(
        rule_id="CTCT_EML_STTS_NOT_NULL",
        rule_name="Contact email status code is present",
        target_table=CTCT_TABLE,
        target_column="EML_STTS_CD",
        rule_type="not_null",
        rule_expr="dq.fn.is_blank_v1(EML_STTS_CD)",
        rule_version=2,
        superseded=[
            dict(
                rule_version=1,
                rule_expr="EML_STTS_CD IS NULL OR trim(EML_STTS_CD) = ''",
                note=(
                    "v1 spelled the predicate out longhand. v2 calls dq.fn.is_blank_v1, the shared helper declared in sql/ddl/12_functions.sql. Identical counts on the same data -- sql/out/checkrun.sql was re-run against workspace.dq_triage before and after and every figure held. One definition instead of 8."
                ),
            )
        ],
        evaluator=_ctct_eml_stts_null,
        severity="P3_monitor",
        key_column="CTCT_KEY",
        sample_columns=["CTCT_KEY", "EML_ID", "EML_STTS_CD"],
    ),
    Rule(
        rule_id="CTCT_EML_STTS_CONSISTENT",
        rule_name="Email marked INVALID is actually malformed",
        target_table=CTCT_TABLE,
        target_column="EML_STTS_CD",
        rule_type="consistency",
        rule_expr="EML_STTS_CD = 'INVALID' AND dq.fn.is_valid_email_v1(EML_ID)",
        rule_version=2,
        superseded=[
            dict(
                rule_version=1,
                rule_expr=r"EML_STTS_CD = 'INVALID' AND EML_ID RLIKE '^[^@\\s.]+(\\.[^@\\s.]+)*@[^@\\s.]+(\\.[^@\\s.]+)+$'",
                note=(
                    "v1 spelled the predicate out longhand. v2 calls dq.fn.is_valid_email_v1, the shared helper declared in sql/ddl/12_functions.sql. Identical counts on the same data -- sql/out/checkrun.sql was re-run against workspace.dq_triage before and after and every figure held. One definition instead of 2."
                ),
            )
        ],
        scope_filter="EML_ID IS NOT NULL AND trim(EML_ID) <> ''",
        evaluator=_ctct_eml_stts_consistent,
        severity="P2_alert",
        key_column="CTCT_KEY",
        sample_columns=["CTCT_KEY", "EML_ID", "EML_STTS_CD"],
        note="Passes on this snapshot: the upstream INVALID flag agrees with all 240 defects exactly.",
    ),
    Rule(
        rule_id="CTCT_MOBL_NOT_NULL",
        rule_name="Contact mobile number is present",
        target_table=CTCT_TABLE,
        target_column="MOBL_NO",
        rule_type="not_null",
        rule_expr="dq.fn.is_blank_v1(MOBL_NO)",
        rule_version=2,
        superseded=[
            dict(
                rule_version=1,
                rule_expr="MOBL_NO IS NULL OR trim(MOBL_NO) = ''",
                note=(
                    "v1 spelled the predicate out longhand. v2 calls dq.fn.is_blank_v1, the shared helper declared in sql/ddl/12_functions.sql. Identical counts on the same data -- sql/out/checkrun.sql was re-run against workspace.dq_triage before and after and every figure held. One definition instead of 8."
                ),
            )
        ],
        evaluator=_ctct_mobl_null,
        severity="P2_alert",
        key_column="CTCT_KEY",
        sample_columns=["CTCT_KEY", "MOBL_NO", "PHN_NO", "PREF_CTCT_MODE_FLG"],
    ),
    Rule(
        rule_id="CTCT_MOBL_FMT",
        rule_name="Contact mobile matches 04########",
        target_table=CTCT_TABLE,
        target_column="MOBL_NO",
        rule_type="format",
        rule_expr="NOT dq.fn.is_au_mobile_v1(MOBL_NO)",
        rule_version=2,
        superseded=[
            dict(
                rule_version=1,
                rule_expr=r"MOBL_NO NOT RLIKE '^04[0-9]{8}$'",
                note=(
                    "v1 spelled the predicate out longhand. v2 calls dq.fn.is_au_mobile_v1, the shared helper declared in sql/ddl/12_functions.sql. Identical counts on the same data -- sql/out/checkrun.sql was re-run against workspace.dq_triage before and after and every figure held. One definition instead of 2."
                ),
            )
        ],
        scope_filter="MOBL_NO IS NOT NULL AND trim(MOBL_NO) <> ''",
        evaluator=_ctct_mobl_fmt,
        severity="P3_monitor",
        key_column="CTCT_KEY",
        sample_columns=["CTCT_KEY", "MOBL_NO"],
    ),
    Rule(
        rule_id="CTCT_PHN_FMT",
        rule_name="Contact landline matches 0#########",
        target_table=CTCT_TABLE,
        target_column="PHN_NO",
        rule_type="format",
        rule_expr=r"PHN_NO NOT RLIKE '^0[0-9]{9}$'",
        scope_filter="PHN_NO IS NOT NULL AND trim(PHN_NO) <> ''",
        evaluator=_ctct_phn_fmt,
        severity="P3_monitor",
        key_column="CTCT_KEY",
        sample_columns=["CTCT_KEY", "PHN_NO", "PHN_NUMB_TYPE_NM"],
    ),
    Rule(
        rule_id="CTCT_KEY_UNIQUE",
        rule_name="Contact key is unique",
        target_table=CTCT_TABLE,
        target_column="CTCT_KEY",
        rule_type="uniqueness",
        rule_expr="count(*) OVER (PARTITION BY CTCT_KEY) > 1",
        evaluator=_ctct_key_unique,
        severity="P1_block",
        key_column="CTCT_KEY",
        sample_columns=["CTCT_KEY", "CTCT_ID", "LEGL_NM"],
    ),
    Rule(
        rule_id="CTCT_BRTH_PARSEABLE",
        rule_name="Date of birth parses as a real ISO date",
        target_table=CTCT_TABLE,
        target_column="BRTH_TS",
        rule_type="format",
        rule_expr="try_to_timestamp(BRTH_TS, 'yyyy-MM-dd HH:mm:ss') IS NULL",
        scope_filter="BRTH_TS IS NOT NULL AND trim(BRTH_TS) <> ''",
        evaluator=_ctct_brth_parseable,
        severity="P1_block",
        key_column="CTCT_KEY",
        sample_columns=["CTCT_KEY", "BRTH_TS", "LEGL_NM", "IDNT_TYPE_1_CD"],
        note="All 14 are the same literal '31-02-1988' -- one bad default, not fourteen bad records.",
    ),
    Rule(
        rule_id="CTCT_BRTH_PLAUSIBLE",
        rule_name="Date of birth is plausible (age 18-105)",
        target_table=CTCT_TABLE,
        target_column="BRTH_TS",
        rule_type="format",
        rule_expr="year(BRTH_TS) < 1920 OR year(BRTH_TS) > 2008",
        scope_filter="try_to_timestamp(BRTH_TS, 'yyyy-MM-dd HH:mm:ss') IS NOT NULL",
        evaluator=_ctct_brth_plausible,
        severity="P2_alert",
        key_column="CTCT_KEY",
        sample_columns=["CTCT_KEY", "BRTH_TS", "LEGL_NM"],
    ),
    Rule(
        rule_id="CTCT_IDNT_DOC_NOT_NULL",
        rule_name="Identity document number present when type is set",
        target_table=CTCT_TABLE,
        target_column="IDNT_DOC_1_NO",
        rule_type="consistency",
        rule_expr="dq.fn.is_blank_v1(IDNT_DOC_1_NO)",
        rule_version=2,
        superseded=[
            dict(
                rule_version=1,
                rule_expr="IDNT_DOC_1_NO IS NULL OR trim(IDNT_DOC_1_NO) = ''",
                note=(
                    "v1 spelled the predicate out longhand. v2 calls dq.fn.is_blank_v1, the shared helper declared in sql/ddl/12_functions.sql. Identical counts on the same data -- sql/out/checkrun.sql was re-run against workspace.dq_triage before and after and every figure held. One definition instead of 8."
                ),
            )
        ],
        scope_filter="IDNT_TYPE_1_CD IS NOT NULL AND trim(IDNT_TYPE_1_CD) <> ''",
        evaluator=_ctct_idnt_doc_null,
        severity="P1_block",
        key_column="CTCT_KEY",
        sample_columns=["CTCT_KEY", "IDNT_TYPE_1_CD", "IDNT_DOC_1_NO"],
    ),
    Rule(
        rule_id="CTCT_SPCL_CARE_VARIANCE",
        rule_name="Special-care status carries more than one value",
        target_table=CTCT_TABLE,
        target_column="SPCL_CARE_STTS",
        rule_type="variance",
        rule_expr="(SELECT count(DISTINCT SPCL_CARE_STTS) FROM {table}) <= 1",
        evaluator=_ctct_spcl_care_variance,
        severity="P2_alert",
        key_column="CTCT_KEY",
        sample_columns=["CTCT_KEY", "SPCL_CARE_STTS"],
        note=(
            "v2: retired 2026-10-01, with CDE_VULNERABLE_CUSTOMER. A count of distinct "
            "values cannot tell a defaulted flag from a population with no vulnerable "
            "customers, and failing it marked all 1000 rows. The runs before this date "
            "stand; nothing runs it after."),
        status="retired",
        rule_version=2,
        superseded=[dict(
            rule_version=1,
            note="A vulnerable-customer flag that is constant is almost certainly not being populated.",
        )],
    ),
    Rule(
        rule_id="CTCT_PREF_LANG_VARIANCE",
        rule_name="Preferred language carries more than one value",
        target_table=CTCT_TABLE,
        target_column="PREF_LANG_NM",
        rule_type="variance",
        rule_expr="(SELECT count(DISTINCT PREF_LANG_NM) FROM {table}) <= 1",
        evaluator=_ctct_pref_lang_variance,
        severity="P3_monitor",
        status="shadow",
        key_column="CTCT_KEY",
        sample_columns=["CTCT_KEY", "PREF_LANG_NM"],
        note="Shadow: measured every run but never raises a cohort. Exercises the shadow->active promotion path.",
    ),
    Rule(
        rule_id="SUBS_MSISDN_SENTINEL",
        rule_name="Mobile service number is not a placeholder",
        target_table=SUBS_TABLE,
        target_column="PRIM_RSRC_VALU_TXT",
        rule_type="sentinel",
        rule_expr="dq.fn.is_sentinel_v1(PRIM_RSRC_VALU_TXT)",
        rule_version=2,
        superseded=[
            dict(
                rule_version=1,
                rule_expr="lower(trim(PRIM_RSRC_VALU_TXT)) IN ('service-number-unknown','unknown','n/a','na','none','null','')",
                note=(
                    "v1 spelled the predicate out longhand. v2 calls dq.fn.is_sentinel_v1, the shared helper declared in sql/ddl/12_functions.sql. Identical counts on the same data -- sql/out/checkrun.sql was re-run against workspace.dq_triage before and after and every figure held. One definition instead of 1."
                ),
            )
        ],
        scope_filter="PRIM_RSRC_TYPE_KEY = 1",
        evaluator=_subs_msisdn_sentinel,
        severity="P1_block",
        sample_columns=["SUBS_KEY", "PRIM_RSRC_VALU_TXT", "PROD_NM", "SUBS_STTS_KEY"],
        note="A live mobile service with no number is a provisioning gap, not a formatting nit.",
    ),
    Rule(
        rule_id="SUBS_MSISDN_FMT",
        rule_name="Mobile service number matches 04########",
        target_table=SUBS_TABLE,
        target_column="PRIM_RSRC_VALU_TXT",
        rule_type="format",
        rule_expr="NOT dq.fn.is_au_mobile_v1(PRIM_RSRC_VALU_TXT)",
        scope_filter="PRIM_RSRC_TYPE_KEY = 1",
        evaluator=_subs_msisdn_fmt,
        severity="P2_alert",
        rule_version=3,
        sample_columns=["SUBS_KEY", "PRIM_RSRC_VALU_TXT", "PRIM_RSRC_TYPE_KEY", "PROD_NM"],
        # The only rule with three versions, and the only one whose history shows the
        # two kinds of change apart: v1 -> v2 fixed what the rule MEASURES, v2 -> v3
        # changed only how the predicate is WRITTEN. Keep them as separate versions;
        # collapsing them would make a behaviour change look like a refactor.
        superseded=[
            dict(
                rule_version=1,
                scope_filter=None,
                rule_expr=r"PRIM_RSRC_VALU_TXT NOT RLIKE '^04[0-9]{8}$'",
                note=(
                    "v1 had no scope_filter and reported 212 violations, 200 of which were "
                    "Fixed Broadband service IDs in a different and correct format. Scoping to "
                    "PRIM_RSRC_TYPE_KEY = 1 took it to 12 real ones. This is the fix COH-B is "
                    "recommending for the two rules that still have the same defect."
                ),
            ),
            dict(
                rule_version=2,
                rule_expr=r"PRIM_RSRC_VALU_TXT NOT RLIKE '^04[0-9]{8}$'",
                note=(
                    "v2 spelled the predicate out longhand. v3 calls dq.fn.is_au_mobile_v1, "
                    "the shared helper declared in sql/ddl/12_functions.sql -- the same "
                    "concept CTCT_MOBL_FMT checks on another table under an unrelated column "
                    "name, which is why naming it once matters. Identical counts: 12 on the "
                    "same data, scope_filter untouched."
                ),
            ),
        ],
    ),
    Rule(
        rule_id="SUBS_MSISDN_UNIQUE",
        rule_name="Mobile service number is not reused across subscriptions",
        target_table=SUBS_TABLE,
        target_column="PRIM_RSRC_VALU_TXT",
        rule_type="uniqueness",
        rule_expr="count(*) OVER (PARTITION BY PRIM_RSRC_VALU_TXT) > 1",
        scope_filter="PRIM_RSRC_TYPE_KEY = 1 AND lower(trim(PRIM_RSRC_VALU_TXT)) <> 'service-number-unknown'",
        evaluator=_subs_msisdn_unique,
        severity="P1_block",
        sample_columns=["SUBS_KEY", "PRIM_RSRC_VALU_TXT", "SUBS_STTS_KEY", "INIT_ACTV_TS"],
    ),
    Rule(
        rule_id="SUBS_IMEI_NOT_NULL",
        rule_name="Handset IMEI is present",
        target_table=SUBS_TABLE,
        target_column="IMEI_ID",
        rule_type="not_null",
        rule_expr="dq.fn.is_blank_v1(IMEI_ID)",
        rule_version=2,
        superseded=[
            dict(
                rule_version=1,
                rule_expr="IMEI_ID IS NULL OR trim(IMEI_ID) = ''",
                note=(
                    "v1 spelled the predicate out longhand. v2 calls dq.fn.is_blank_v1, the shared helper declared in sql/ddl/12_functions.sql. Identical counts on the same data -- sql/out/checkrun.sql was re-run against workspace.dq_triage before and after and every figure held. One definition instead of 8."
                ),
            )
        ],
        scope_filter=None,
        evaluator=_subs_imei_null,
        severity="P3_monitor",
        sample_columns=["SUBS_KEY", "IMEI_ID", "PROD_NM", "PROD_TYPE_KEY"],
        note="MISSING SCOPE FILTER, DELIBERATELY. All 200 violations are Fixed Broadband. See COH-B.",
    ),
    Rule(
        rule_id="SUBS_SIM_NOT_NULL",
        rule_name="SIM serial is present for SIM-bearing products",
        target_table=SUBS_TABLE,
        target_column="SIM_SERL_ID",
        rule_type="not_null",
        rule_expr="dq.fn.is_blank_v1(SIM_SERL_ID)",
        rule_version=2,
        superseded=[
            dict(
                rule_version=1,
                rule_expr="SIM_SERL_ID IS NULL OR trim(SIM_SERL_ID) = ''",
                note=(
                    "v1 spelled the predicate out longhand. v2 calls dq.fn.is_blank_v1, the shared helper declared in sql/ddl/12_functions.sql. Identical counts on the same data -- sql/out/checkrun.sql was re-run against workspace.dq_triage before and after and every figure held. One definition instead of 8."
                ),
            )
        ],
        scope_filter="PROD_TYPE_KEY <> 0",
        evaluator=_subs_sim_null,
        severity="P2_alert",
        sample_columns=["SUBS_KEY", "SIM_SERL_ID", "PROD_NM"],
        note="The correctly-scoped twin of SUBS_IMEI_NOT_NULL. Same data, zero violations.",
    ),
    Rule(
        rule_id="SUBS_NTWK_NOT_NULL",
        rule_name="Network technology is populated",
        target_table=SUBS_TABLE,
        target_column="NTWK_TECH_NM",
        rule_type="not_null",
        rule_expr="dq.fn.is_blank_v1(NTWK_TECH_NM)",
        rule_version=2,
        superseded=[
            dict(
                rule_version=1,
                rule_expr="NTWK_TECH_NM IS NULL OR trim(NTWK_TECH_NM) = ''",
                note=(
                    "v1 spelled the predicate out longhand. v2 calls dq.fn.is_blank_v1, the shared helper declared in sql/ddl/12_functions.sql. Identical counts on the same data -- sql/out/checkrun.sql was re-run against workspace.dq_triage before and after and every figure held. One definition instead of 8."
                ),
            )
        ],
        evaluator=_subs_ntwk_null,
        severity="P2_alert",
        sample_columns=["SUBS_KEY", "NTWK_TECH_NM", "PROD_NM", "PRIM_RSRC_TYPE_KEY"],
        note="Genuinely spread across all three product lines, so scope is not the explanation here.",
    ),
    Rule(
        rule_id="SUBS_PRIM_ACCT_NOT_ZERO",
        rule_name="Primary billing account is set",
        target_table=SUBS_TABLE,
        target_column="PRIM_ACCT_KEY",
        rule_type="sentinel",
        rule_expr="PRIM_ACCT_KEY = 0",
        scope_filter=None,
        evaluator=_subs_prim_acct_zero,
        severity="P2_alert",
        sample_columns=["SUBS_KEY", "PRIM_ACCT_KEY", "BILL_SUBS_TYPE_CD", "PROD_NM"],
        note="MISSING SCOPE FILTER, DELIBERATELY. All 500 violations are prepaid. See COH-B.",
    ),
    Rule(
        rule_id="SUBS_BILL_OFFR_NOT_ZERO",
        rule_name="Main billing offer is set for postpaid",
        target_table=SUBS_TABLE,
        target_column="MAIN_BILL_OFFR_KEY",
        rule_type="sentinel",
        rule_expr="MAIN_BILL_OFFR_KEY = 0",
        scope_filter="BILL_SUBS_TYPE_CD = 'POSTPAID'",
        evaluator=_subs_bill_offr_zero,
        severity="P1_block",
        business_domain="Billing",
        owner_group="dq-stewards-billing",
        sample_columns=["SUBS_KEY", "MAIN_BILL_OFFR_KEY", "BILL_SUBS_TYPE_CD"],
    ),
    Rule(
        rule_id="SUBS_ACTV_TS_CONSISTENT",
        rule_name="Original and initial activation timestamps agree",
        target_table=SUBS_TABLE,
        target_column="ORIG_ACTV_TS",
        rule_type="consistency",
        rule_expr="ORIG_ACTV_TS <> INIT_ACTV_TS",
        evaluator=_subs_actv_ts_consistent,
        severity="P3_monitor",
        sample_columns=["SUBS_KEY", "INIT_ACTV_TS", "ORIG_ACTV_TS", "LAST_ACTV_TS"],
    ),
    Rule(
        rule_id="SUBS_STTS_RSN_REQUIRED",
        rule_name="Non-active subscription carries a status reason",
        target_table=SUBS_TABLE,
        target_column="SUBS_STTS_RSN_KEY",
        rule_type="consistency",
        rule_expr="SUBS_STTS_RSN_KEY = 0 OR SUBS_STTS_RSN_KEY IS NULL",
        scope_filter="SUBS_STTS_KEY <> 1",
        evaluator=_subs_stts_rsn_required,
        severity="P2_alert",
        sample_columns=["SUBS_KEY", "SUBS_STTS_KEY", "SUBS_STTS_RSN_KEY", "SUBS_STTS_TS"],
    ),
    Rule(
        rule_id="SUBS_KEY_UNIQUE",
        rule_name="Subscription key is unique",
        target_table=SUBS_TABLE,
        target_column="SUBS_KEY",
        rule_type="uniqueness",
        rule_expr="count(*) OVER (PARTITION BY SUBS_KEY) > 1",
        evaluator=_subs_key_unique,
        severity="P1_block",
        sample_columns=["SUBS_KEY", "SUBS_ID", "PRIM_RSRC_VALU_TXT"],
    ),
    Rule(
        rule_id="SUBS_CLSE_TS_CONSISTENT",
        rule_name="Record close timestamp agrees with cancelled status",
        target_table=SUBS_TABLE,
        target_column="ECF_CLSE_TS",
        rule_type="consistency",
        rule_expr="(ECF_CLSE_TS IS NOT NULL) <> (SUBS_STTS_KEY = 2)",
        evaluator=_subs_clse_ts_consistent,
        severity="P2_alert",
        sample_columns=["SUBS_KEY", "SUBS_STTS_KEY", "ECF_CLSE_TS", "ECF_XPIR_TS"],
    ),
    Rule(
        rule_id="SUBS_BNFT_TXT_NOT_NULL",
        rule_name="Benefit text is populated",
        target_table=SUBS_TABLE,
        target_column="BNFT_TXT",
        rule_type="not_null",
        rule_expr="dq.fn.is_blank_v1(BNFT_TXT)",
        rule_version=2,
        superseded=[
            dict(
                rule_version=1,
                rule_expr="BNFT_TXT IS NULL OR trim(BNFT_TXT) = ''",
                note=(
                    "v1 spelled the predicate out longhand. v2 calls dq.fn.is_blank_v1, the shared helper declared in sql/ddl/12_functions.sql. Identical counts on the same data -- sql/out/checkrun.sql was re-run against workspace.dq_triage before and after and every figure held. One definition instead of 8."
                ),
            )
        ],
        evaluator=_subs_bnft_txt_null,
        severity="P3_monitor",
        status="shadow",
        fail_threshold_pct=90.0,
        sample_columns=["SUBS_KEY", "BNFT_TXT", "PROD_OFFR_DS"],
        note=(
            "Shadow at a 90% threshold. 75% blank looks alarming but is probably an optional "
            "field. Left in shadow precisely because nobody has confirmed which -- promoting it "
            "on a hunch is how a queue fills with noise."
        ),
    ),
    Rule(
        rule_id="XREF_SUBS_CTCT_ORPHAN",
        rule_name="Every subscription resolves to a contact",
        target_table=SUBS_TABLE,
        rule_type="referential",
        rule_expr="c.CTCT_KEY IS NULL",
        join_sql=(
            "prod.customer.subs_c s "
            "LEFT JOIN prod.customer.ctct_c c ON s.CTCT_KEY = c.CTCT_KEY"
        ),
        evaluator=_xref_orphan,
        severity="P1_block",
        sample_columns=["SUBS_KEY", "CTCT_KEY", "SUBS_STTS_KEY"],
    ),
    Rule(
        rule_id="XREF_NAME_AGREEMENT",
        rule_name="Subscriber first name agrees with contact first name",
        target_table=SUBS_TABLE,
        rule_type="consistency",
        rule_expr="lower(trim(s.SUBS_FRST_NM)) <> lower(trim(c.FRST_NM))",
        join_sql=(
            "prod.customer.subs_c s "
            "JOIN prod.customer.ctct_c c ON s.CTCT_KEY = c.CTCT_KEY"
        ),
        evaluator=_xref_name_agreement,
        severity="P2_alert",
        sample_columns=["SUBS_KEY", "CTCT_KEY", "SUBS_FRST_NM", "FRST_NM"],
    ),
    Rule(
        rule_id="XREF_OPEN_TS_AGREEMENT",
        rule_name="Subscription record open time agrees with contact add time",
        target_table=SUBS_TABLE,
        rule_type="consistency",
        rule_expr="s.ECF_OPEN_TS <> c.CTCT_ADD_TS",
        join_sql=(
            "prod.customer.subs_c s "
            "JOIN prod.customer.ctct_c c ON s.CTCT_KEY = c.CTCT_KEY"
        ),
        evaluator=_xref_open_ts_agreement,
        severity="P2_alert",
        sample_columns=["SUBS_KEY", "CTCT_KEY", "ECF_OPEN_TS", "CTCT_ADD_TS"],
    ),
]


# ---------------------------------------------------------------------------
# The DQ Queries rules -- every one in shadow
# ---------------------------------------------------------------------------

_SRC = "Extracted 2026-10-05 from the workspace query '{q}' ({checks})."

_HELPER_NOTE = (
    "v1 spelled the predicate out longhand, the {what} copied into every rule that needed "
    "it. v2 calls {fns}, declared in sql/ddl/12_functions.sql on 2026-10-05. Identical "
    "counts on the same data and on adversarial values -- see sql/migrate_dq_fn.py.")


def _v1(rule_expr: str, fns: str, what: str, scope_filter: str | None = None) -> dict:
    """The superseded v1 of a rule moved onto a helper. Shadow, like v2: it was never
    promoted, and the registry row must not claim it was."""
    d = dict(rule_version=1, rule_expr=rule_expr, status="shadow",
             note=_HELPER_NOTE.format(fns=fns, what=what))
    if scope_filter is not None:
        d["scope_filter"] = scope_filter
    return d


def _ctct_shadow(**kw) -> Rule:
    kw.setdefault("target_table", CTCT_TABLE)
    kw.setdefault("key_column", "CTCT_KEY")
    kw.setdefault("status", "shadow")
    return Rule(**kw)


def _name_rules(col: str, label: str, query: str, presence: bool) -> list[Rule]:
    sql = _name_sql(col)
    scope = f"{col} IS NOT NULL AND trim({col}) <> ''"
    sample = ["CTCT_KEY", "CTCT_ID", col]
    tag = col.replace("_NM", "")
    out = []
    if presence:
        out.append(_ctct_shadow(
            rule_id=f"CTCT_{tag}_NM_NOT_NULL", rule_name=f"{label} is present",
            target_column=col, rule_type="not_null",
            rule_expr=f"dq.fn.is_blank_v1({col})", evaluator=_name_null(col),
            severity="P2_alert", sample_columns=sample,
            note=_SRC.format(q=query, checks="01_NULL_OR_BLANK; 02_LESS_THAN_ONE_CHARACTER "
                             "dropped, it returns the same rows")))
    out += [
        _ctct_shadow(
            rule_id=f"CTCT_{tag}_NM_PLACEHOLDER", rule_name=f"{label} is not a placeholder",
            target_column=col, rule_type="sentinel", rule_expr=sql["placeholder"],
            rule_version=2,
            superseded=[_v1(sql["placeholder_v1"], "dq.fn.is_name_placeholder_v1",
                            "13-value placeholder list")],
            scope_filter=scope, evaluator=_name_rule(col, _name_placeholder),
            severity="P2_alert", sample_columns=sample,
            note=_SRC.format(q=query, checks="03_PLACEHOLDER_VALUE")),
        _ctct_shadow(
            rule_id=f"CTCT_{tag}_NM_FORMATTING",
            rule_name=f"{label} has no stray whitespace, control characters or edge punctuation",
            target_column=col, rule_type="format", rule_expr=sql["formatting"],
            scope_filter=scope, evaluator=_name_rule(col, _name_formatting_defect),
            severity="P3_monitor", sample_columns=sample,
            note=_SRC.format(q=query, checks="05 control characters, 06 leading/trailing "
                             "whitespace, 07 starts or ends with - or ', 08 consecutive "
                             "punctuation") + " All four are cleansable without asking anyone."),
        _ctct_shadow(
            rule_id=f"CTCT_{tag}_NM_CONTAMINATED",
            rule_name=f"{label} holds a name, not a title, company, address or note",
            target_column=col, rule_type="format", rule_expr=sql["contaminated"],
            scope_filter=scope, evaluator=_name_rule(col, _name_contaminated),
            severity="P2_alert", sample_columns=sample,
            note=_SRC.format(q=query, checks="09 starts with title, 10 company indicator, "
                             "11 identifier, note or address") + " The query's [[:space:]] "
                             "is \\s here; in Spark it matched the letters of 'space'."),
        _ctct_shadow(
            rule_id=f"CTCT_{tag}_NM_LENGTH", rule_name=f"{label} is at most 40 characters",
            target_column=col, rule_type="format", rule_expr=sql["length"],
            scope_filter=scope, evaluator=_name_rule(col, _name_too_long),
            severity="P3_monitor", sample_columns=sample,
            note=_SRC.format(q=query, checks="04_EXCEEDS_40_CHARACTERS") + " The query applies "
                 "40 to every name column. Salesforce allows 80 for a last name; confirm the "
                 "limit the migration target actually enforces before promoting."),
        _ctct_shadow(
            rule_id=f"CTCT_{tag}_NM_STRUCTURE",
            rule_name=f"{label} is letters joined by single spaces, hyphens or apostrophes",
            target_column=col, rule_type="format", rule_expr=sql["structure"],
            scope_filter=scope, evaluator=_name_rule(col, _name_bad_structure),
            severity="P3_monitor", sample_columns=sample,
            note=_SRC.format(q=query, checks="12 starts with non-letter, 13 invalid characters "
                             "or structure") + " Asserts a shape on a name, which CDE_CUST_NAME "
                             "warns against: it rejects digits in a name, and also anyone whose "
                             "name the pattern did not imagine. Overlaps the formatting rule "
                             "by construction. Promote only with the business."),
    ]
    return out


def _phone_rules(col: str, label: str, mobile_only: bool, replaces: str) -> list[Rule]:
    sql = _phone_sql(col, mobile_only)
    old = _phone_sql(col, mobile_only, helpers=False)
    norm = dict(fns="dq.fn.au_phone_digits_v1", what="phone-normalising CASE")
    tag = col.replace("_NO", "")
    sample = ["CTCT_KEY", col, "PHN_NUMB_TYPE_NM"]
    accepted = "an Australian mobile" if mobile_only else "an Australian mobile or landline"
    src = _SRC.format(q="Phone", checks="{c}")
    return [
        _ctct_shadow(
            rule_id=f"CTCT_{tag}_AU_FMT", rule_name=f"{label} is {accepted} once washed",
            target_column=col, rule_type="format", rule_expr=sql["fmt"],
            rule_version=2, superseded=[_v1(old["fmt"], scope_filter=old["scope"], **norm)],
            scope_filter=sql["scope"], evaluator=_phone_fmt(col, mobile_only),
            severity="P3_monitor", sample_columns=sample,
            note=src.format(c="unsupported character, contains letters, too short, invalid AU "
                            "length, invalid format") + f" Candidate replacement for {replaces}: "
                            "normalises 61/+61 and a dropped leading zero before judging, and "
                            "leaves 1300/1800/1900 numbers out of scope as the query does."),
        _ctct_shadow(
            rule_id=f"CTCT_{tag}_WASHABLE",
            rule_name=f"{label} is stored as bare digits",
            target_column=col, rule_type="format", rule_expr=sql["washable"],
            rule_version=2, superseded=[_v1(old["washable"], scope_filter=old["scope"], **norm)],
            scope_filter=sql["scope"], evaluator=_phone_washable(col, mobile_only),
            severity="P3_monitor", sample_columns=sample,
            note=src.format(c="washable formatting, leading or trailing space") + " A valid "
                 "number carrying spaces, brackets, dots, slashes, + or -: a cleansing job "
                 "fixes it, nobody needs to ask the customer."),
        _ctct_shadow(
            rule_id=f"CTCT_{tag}_PLACEHOLDER",
            rule_name=f"{label} is not a known placeholder or prohibited number",
            target_column=col, rule_type="sentinel", rule_expr=sql["placeholder"],
            rule_version=2,
            superseded=[_v1(old["placeholder"], "dq.fn.is_phone_placeholder_v1",
                            "48-number placeholder list and its normalising CASE")],
            scope_filter=f"{col} IS NOT NULL AND trim({col}) <> ''", evaluator=_phone_placeholder(col),
            severity="P2_alert", sample_columns=sample,
            note=src.format(c="known placeholder or prohibited, all-zeros pattern") + " The "
                 "query's two versions carried different lists (42 and 14 numbers); this is "
                 "their union, held once in dq.fn.is_phone_placeholder_v1 since v2. "
                 "Adding a number is a _v2 of the helper and a new version of both rules."),
    ]


DQ_QUERIES_RULES: list[Rule] = [
    *_name_rules("FRST_NM", "First name", "First Name Query", presence=True),
    *_name_rules("LAST_NM", "Last name", "Last Name", presence=True),
    # Middle name is optional: the query tags its NULL_OR_BLANK INFORMATIONAL_ONLY
    # (4,080,822 rows), so there is no presence rule to register.
    *_name_rules("MID_NM", "Middle name", "Middle Name", presence=False),

    *_phone_rules("PHN_NO", "Landline", mobile_only=False, replaces="CTCT_PHN_FMT"),
    *_phone_rules("MOBL_NO", "Mobile", mobile_only=True, replaces="CTCT_MOBL_FMT"),
    _ctct_shadow(
        rule_id="CTCT_MOBL_SHARED", rule_name="Mobile is shared by at most 10 contacts",
        target_column="MOBL_NO", rule_type="uniqueness",
        rule_expr="count(*) OVER (PARTITION BY dq.fn.au_phone_digits_v1(MOBL_NO)) > 10",
        rule_version=2,
        superseded=[_v1(f"count(*) OVER (PARTITION BY {_au_digits_sql('MOBL_NO')}) > 10",
                        "dq.fn.au_phone_digits_v1", "phone-normalising CASE")],
        scope_filter="MOBL_NO IS NOT NULL AND trim(MOBL_NO) <> ''", evaluator=_ctct_mobl_shared,
        severity="P3_monitor", sample_columns=["CTCT_KEY", "MOBL_NO"],
        note=_SRC.format(q="Phone", checks="PHONE_SHARED_BY_10_PLUS_CONTACTS") + " The 2+ "
             "variant is not registered: the query's final version took sharing out of "
             "its any-issue roll-up, and a household sharing a number is not a defect."),

    _ctct_shadow(
        rule_id="CTCT_BRTH_NOT_NULL", rule_name="Date of birth is present",
        target_column="BRTH_TS", rule_type="not_null",
        rule_expr="dq.fn.is_blank_v1(BRTH_TS)", evaluator=_ctct_brth_null,
        severity="P2_alert", sample_columns=["CTCT_KEY", "BRTH_TS", "LEGL_NM"],
        note=_SRC.format(q="Birth Date", checks="BIRTH_DATE_NULL_OR_ZERO") + " The source "
             "stores epoch milliseconds, where 0 also means missing; ctct_c stores a "
             "timestamp string, so only blank applies."),
    _ctct_shadow(
        rule_id="CTCT_BRTH_FUTURE", rule_name="Date of birth is not in the future",
        target_column="BRTH_TS", rule_type="format",
        rule_expr=f"{_DOB_SQL} > current_date()", scope_filter=_DOB_SCOPE,
        evaluator=_ctct_brth_future, severity="P2_alert",
        sample_columns=["CTCT_KEY", "BRTH_TS", "LEGL_NM"],
        note=_SRC.format(q="Birth Date", checks="BIRTH_DATE_FUTURE") + " With the next "
             "three, the candidate replacement for CTCT_BRTH_PLAUSIBLE."),
    _ctct_shadow(
        rule_id="CTCT_BRTH_UNDER_14", rule_name="Contact is at least 14 years old",
        target_column="BRTH_TS", rule_type="format",
        rule_expr=(f"{_DOB_SQL} <= current_date() "
                   f"AND {_DOB_SQL} > add_months(current_date(), -14 * 12)"),
        scope_filter=_DOB_SCOPE, evaluator=_ctct_brth_under_14, severity="P2_alert",
        sample_columns=["CTCT_KEY", "BRTH_TS", "LEGL_NM"],
        note=_SRC.format(q="Birth Date", checks="BIRTH_DATE_UNDER_14") + " Age is measured "
             "from current_date(), so a verdict can change with no change to the data."),
    _ctct_shadow(
        rule_id="CTCT_BRTH_MINOR_REVIEW", rule_name="Contact aged 14 to 17 is reviewed",
        target_column="BRTH_TS", rule_type="format",
        rule_expr=(f"{_DOB_SQL} <= add_months(current_date(), -14 * 12) "
                   f"AND {_DOB_SQL} > add_months(current_date(), -18 * 12)"),
        scope_filter=_DOB_SCOPE, evaluator=_ctct_brth_minor_review, severity="P3_monitor",
        sample_columns=["CTCT_KEY", "BRTH_TS", "LEGL_NM"],
        note=_SRC.format(q="Birth Date", checks="BIRTH_DATE_AGE_14_TO_17_REVIEW") + " The "
             "query says 'segment review required': a business question, which is COH-E's "
             "case. Finds 37 on the fixture's final run where CTCT_BRTH_PLAUSIBLE finds 27 -- "
             "its year > 2008 cut misses the ten born after 2 September 2008."),
    _ctct_shadow(
        rule_id="CTCT_BRTH_OVER_110", rule_name="Contact is at most 110 years old",
        target_column="BRTH_TS", rule_type="format",
        rule_expr=f"{_DOB_SQL} < add_months(current_date(), -110 * 12)",
        scope_filter=_DOB_SCOPE, evaluator=_ctct_brth_over_110, severity="P2_alert",
        sample_columns=["CTCT_KEY", "BRTH_TS", "LEGL_NM"],
        note=_SRC.format(q="Birth Date", checks="BIRTH_DATE_AGE_OVER_110; BEFORE_1900 is "
                         "folded in, every pre-1900 date is over 110")),
    _ctct_shadow(
        rule_id="CTCT_BRTH_PLACEHOLDER", rule_name="Date of birth is not a default date",
        target_column="BRTH_TS", rule_type="sentinel",
        rule_expr=(f"{_DOB_SQL} IN ("
                   + ", ".join(f"DATE'{d}'" for d in DOB_PLACEHOLDERS) + ")"),
        scope_filter=_DOB_SCOPE, evaluator=_ctct_brth_placeholder, severity="P3_monitor",
        sample_columns=["CTCT_KEY", "BRTH_TS", "LEGL_NM"],
        note=_SRC.format(q="Birth Date", checks="BIRTH_DATE_PLACEHOLDER") + " 1970-01-01 is "
             "epoch zero in the source; 1980-01-01 is someone's real birthday. Monitor only."),

    _ctct_shadow(
        rule_id="CTCT_ID_NOT_NULL", rule_name="Contact ID is present",
        target_column="CTCT_ID", rule_type="not_null",
        rule_expr="dq.fn.is_blank_v1(CTCT_ID)", evaluator=_ctct_id_null,
        severity="P1_block", sample_columns=["CTCT_KEY", "CTCT_ID"],
        note=_SRC.format(q="Identifier", checks="CONTACT_ID null_or_blank") + " CUSTOMER_ID "
             "and ORG_ID get the same four checks in the query; their tables have no mock "
             "here, so they are not registered."),
    _ctct_shadow(
        rule_id="CTCT_ID_NUMERIC", rule_name="Contact ID is all digits",
        target_column="CTCT_ID", rule_type="format",
        rule_expr="trim(CTCT_ID) NOT RLIKE '^[0-9]+$'",
        scope_filter="CTCT_ID IS NOT NULL AND trim(CTCT_ID) <> ''", evaluator=_ctct_id_numeric,
        severity="P2_alert", sample_columns=["CTCT_KEY", "CTCT_ID"],
        note=_SRC.format(q="Identifier", checks="non_numeric_or_contains_characters") + " The "
             "Email query found real IDs like 'OOBdbmcrobj)dummy_contact' in the source."),
    _ctct_shadow(
        rule_id="CTCT_ID_FORMATTING",
        rule_name="Contact ID has no stray whitespace or control characters",
        target_column="CTCT_ID", rule_type="format",
        rule_expr="CTCT_ID <> trim(CTCT_ID) OR CTCT_ID RLIKE '\\\\p{Cc}'",
        scope_filter="CTCT_ID IS NOT NULL AND trim(CTCT_ID) <> ''", evaluator=_ctct_id_formatting,
        severity="P3_monitor", sample_columns=["CTCT_KEY", "CTCT_ID"],
        note=_SRC.format(q="Identifier", checks="leading_trailing_whitespace, "
                         "control_character") + " The query's [[:cntrl:]] matched any of the "
                         "letters c, n, t, r, o, l -- 'John' was a control-character finding."),
    _ctct_shadow(
        rule_id="CTCT_ID_UNIQUE", rule_name="Contact ID is unique",
        target_column="CTCT_ID", rule_type="uniqueness",
        rule_expr="count(*) OVER (PARTITION BY trim(CTCT_ID)) > 1",
        scope_filter="CTCT_ID IS NOT NULL AND trim(CTCT_ID) <> ''", evaluator=_ctct_id_unique,
        severity="P1_block", sample_columns=["CTCT_KEY", "CTCT_ID"],
        note=_SRC.format(q="Identifier", checks="duplicate_trimmed_contact_id_value")),
]

RULES += DQ_QUERIES_RULES

BY_ID = {r.rule_id: r for r in RULES}

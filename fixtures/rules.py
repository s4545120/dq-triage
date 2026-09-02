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
        rule_expr=r"NOT (EML_ID RLIKE '^[^@\\s.]+(\\.[^@\\s.]+)*@[^@\\s.]+(\\.[^@\\s.]+)+$')",
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
        rule_expr="EML_ID IS NULL OR trim(EML_ID) = ''",
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
        rule_expr="EML_STTS_CD IS NULL OR trim(EML_STTS_CD) = ''",
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
        rule_expr=r"EML_STTS_CD = 'INVALID' AND EML_ID RLIKE '^[^@\\s.]+(\\.[^@\\s.]+)*@[^@\\s.]+(\\.[^@\\s.]+)+$'",
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
        rule_expr="MOBL_NO IS NULL OR trim(MOBL_NO) = ''",
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
        rule_expr=r"MOBL_NO NOT RLIKE '^04[0-9]{8}$'",
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
        rule_expr="IDNT_DOC_1_NO IS NULL OR trim(IDNT_DOC_1_NO) = ''",
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
        note="A vulnerable-customer flag that is constant is almost certainly not being populated.",
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
        rule_expr="lower(trim(PRIM_RSRC_VALU_TXT)) IN ('service-number-unknown','unknown','n/a','na','none','null','')",
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
        rule_expr=r"PRIM_RSRC_VALU_TXT NOT RLIKE '^04[0-9]{8}$'",
        scope_filter="PRIM_RSRC_TYPE_KEY = 1",
        evaluator=_subs_msisdn_fmt,
        severity="P2_alert",
        rule_version=2,
        sample_columns=["SUBS_KEY", "PRIM_RSRC_VALU_TXT", "PRIM_RSRC_TYPE_KEY", "PROD_NM"],
        superseded=[
            dict(
                rule_version=1,
                scope_filter=None,
                note=(
                    "v1 had no scope_filter and reported 212 violations, 200 of which were "
                    "Fixed Broadband service IDs in a different and correct format. Scoping to "
                    "PRIM_RSRC_TYPE_KEY = 1 took it to 12 real ones. This is the fix COH-B is "
                    "recommending for the two rules that still have the same defect."
                ),
            )
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
        rule_expr="IMEI_ID IS NULL OR trim(IMEI_ID) = ''",
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
        rule_expr="SIM_SERL_ID IS NULL OR trim(SIM_SERL_ID) = ''",
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
        rule_expr="NTWK_TECH_NM IS NULL OR trim(NTWK_TECH_NM) = ''",
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
        rule_expr="BNFT_TXT IS NULL OR trim(BNFT_TXT) = ''",
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
            "SELECT s.* FROM prod.customer.subs_c s "
            "LEFT JOIN prod.customer.ctct_c c ON s.CTCT_KEY = c.CTCT_KEY "
            "WHERE c.CTCT_KEY IS NULL"
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
            "SELECT s.SUBS_KEY, s.SUBS_FRST_NM, c.FRST_NM "
            "FROM prod.customer.subs_c s JOIN prod.customer.ctct_c c ON s.CTCT_KEY = c.CTCT_KEY "
            "WHERE lower(trim(s.SUBS_FRST_NM)) <> lower(trim(c.FRST_NM))"
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
            "SELECT s.SUBS_KEY, s.ECF_OPEN_TS, c.CTCT_ADD_TS "
            "FROM prod.customer.subs_c s JOIN prod.customer.ctct_c c ON s.CTCT_KEY = c.CTCT_KEY "
            "WHERE s.ECF_OPEN_TS <> c.CTCT_ADD_TS"
        ),
        evaluator=_xref_open_ts_agreement,
        severity="P2_alert",
        sample_columns=["SUBS_KEY", "CTCT_KEY", "ECF_OPEN_TS", "CTCT_ADD_TS"],
    ),
]

BY_ID = {r.rule_id: r for r in RULES}

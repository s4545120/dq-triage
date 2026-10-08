"""Check templates, lifted from rules that are already registered.

A template is a registered rule with its column replaced by `{col}`. Lifting them,
rather than writing them again, means a template cannot drift from the rule it came
from: `equivalence()` instantiates every template on its source column and compares
the result with that rule's expression character for character.

Keyed on `data_class`, the field config.cde_registry already carries. A template
applies to a bound column when the column's element has that data_class and the
column's type is the template's input type.

`{col}` is replaced with str.replace, never str.format: the expressions carry regex
quantifiers like `{2,}` that format would try to fill.

THE PATTERN TEMPLATE (2026-10-08). A class template carries one fixed expression, so it
cannot say what a value of THIS element looks like -- a 7-digit identifier and a 9-digit
one are both `account_id`. TPL_PATTERN takes the shape from the element instead: its
expression holds `{pattern}` as well as `{col}`, filled at generation with the element's
`expected_signature` as a SQL literal (`wh.lit`, which doubles the backslashes Spark
would otherwise eat -- the DQ Queries' one-backslash dot bug). It applies to an element
of any class that declares a signature, EXCEPT where the class already has a format check of its own
(`checks_format`). Those were lifted from the migration queries and say more than one
regex can -- the phone check washes formatting before it judges, the email check is the
shared helper -- so the class's check wins and the pattern is not generated beside it.
It is lifted like the rest: CTCT_PHN_FMT is exactly `PHN_NO NOT RLIKE '^0[0-9]{9}$'`
over non-blank rows, and equivalence() puts it back together from that.

ONLY ON A CONFIRMED SIGNATURE. Most signatures in the register were written by profiling
the 1000-row pilot extract (fixtures/cdes.py says so), not stated by the business: the
identity document number's seven-digit pattern would flag every real passport; an IMEI is 15
digits, not 7. A check generated from one of those would raise breaches on correct data.
So the pattern template applies only to elements in CONFIRMED_SIGNATURES -- the four the
migration queries were written for (customer name, date of birth, email, phone), whose
signatures agree with those queries. Adding an element is a reviewed code change until
confirmation is a field on the register.

THE DATE FORMAT IS THE TABLE'S, NOT THE TEMPLATE'S (2026-10-08). The date-of-birth rules
the templates were lifted from parse with 'yyyy-MM-dd HH:mm:ss', because that is how the
mock contact table stores it. Lifted as they were, a table storing 'dd/MM/yyyy' would
scope every DOB check to nothing and pass silently, and a DATE column was skipped
outright. So the format literal is lifted to a `{datefmt}` slot, and the generator fills
it per column: a STRING column with the format its values parse in
(`choose_date_format`, measured on the table at generation, refused when it is ambiguous
or under DATE_FORMAT_MIN); a DATE or TIMESTAMP column through `date_column`, which writes
it as text in the source format so the same expression holds. TPL_DOB_PARSEABLE --
values that do not parse in the column's format -- is the class's own format check, so
the element's regex pattern is no longer generated beside it.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fixtures"))
import rules  # noqa: E402

import wh  # noqa: E402

TEMPLATE_VERSION = 1      # the default; a template whose expression changed says its own

# The format the date rules were written against, and the formats a STRING date column
# is tried in. Each carries the order of its fields: two orders both parsing a column
# (every day <= 12) is ambiguous, and nothing is generated rather than a guess.
SOURCE_DATE_FORMAT = "yyyy-MM-dd HH:mm:ss"
DATE_FORMATS = [
    ("yyyy-MM-dd HH:mm:ss", "ymd"), ("yyyy-MM-dd'T'HH:mm:ss", "ymd"), ("yyyy-MM-dd", "ymd"),
    ("yyyyMMdd", "ymd"), ("yyyy/MM/dd", "ymd"),
    ("dd/MM/yyyy", "dmy"), ("d/M/yyyy", "dmy"), ("dd-MM-yyyy", "dmy"), ("dd.MM.yyyy", "dmy"),
    ("dd-MMM-yyyy", "dmy"), ("dd/MM/yyyy HH:mm:ss", "dmy"),
    ("MM/dd/yyyy", "mdy"), ("M/d/yyyy", "mdy"),
]
DATE_FORMAT_MIN = 95.0    # % of non-blank values that must parse, as discovery's pattern bar
DATE_TYPES = frozenset({"DATE", "TIMESTAMP", "TIMESTAMP_NTZ"})


@dataclass(frozen=True)
class Template:
    template_id: str
    data_class: str
    check: str                # suffix on a generated rule_id, e.g. FMT
    title: str                # "{element} is ..." -- the element name is filled in
    source_rule: str          # the registered rule this was lifted from
    source_column: str
    input_type: str = "STRING"
    checks_format: bool = False   # the class's own check of what a value looks like
    source_pattern: str | None = None   # set on the pattern template only
    dates_too: bool = False       # also applies to a DATE / TIMESTAMP column
    version: int = TEMPLATE_VERSION

    @property
    def takes_date_format(self) -> bool:
        r = rules.BY_ID[self.source_rule]
        return wh.lit(SOURCE_DATE_FORMAT) in (r.rule_expr + " " + (r.scope_filter or ""))

    def accepts(self, data_type: str) -> bool:
        return data_type == self.input_type or (self.dates_too and data_type in DATE_TYPES)

    @property
    def is_pattern(self) -> bool:
        return self.source_pattern is not None

    def _lift(self, sql: str | None) -> str | None:
        if sql is None:
            return None
        lifted = re.sub(rf"\b{re.escape(self.source_column)}\b", "{col}", sql)
        if self.is_pattern:
            lifted = lifted.replace(wh.lit(self.source_pattern), "{pattern}")
        lifted = lifted.replace(wh.lit(SOURCE_DATE_FORMAT), "{datefmt}")
        return lifted.replace("dq.fn.", wh.fn_prefix())

    @property
    def rule_expr(self) -> str:
        return self._lift(rules.BY_ID[self.source_rule].rule_expr)

    @property
    def scope_filter(self) -> str | None:
        return self._lift(rules.BY_ID[self.source_rule].scope_filter)

    @property
    def rule_type(self) -> str:
        return rules.BY_ID[self.source_rule].rule_type

    @property
    def severity(self) -> str:
        return rules.BY_ID[self.source_rule].severity

    def instantiate(self, col: str, pattern: str | None = None,
                    date_format: str | None = None) -> tuple[str, str | None]:
        """The expression and scope on `col` -- a column name, or `date_column`'s text
        form of a typed one. The pattern template also needs the element's signature, a
        date template the column's format; each goes in as a literal."""
        if self.is_pattern and not pattern:
            raise ValueError(f"{self.template_id} needs the element's expected pattern")
        if self.takes_date_format and not date_format:
            raise ValueError(f"{self.template_id} needs the column's date format")
        def fill(sql):
            out = sql.replace("{col}", col)
            if self.is_pattern:
                out = out.replace("{pattern}", wh.lit(pattern))
            if self.takes_date_format:
                out = out.replace("{datefmt}", wh.lit(date_format))
            return out
        return fill(self.rule_expr), fill(self.scope_filter) if self.scope_filter else None


T = Template
ANY_CLASS = "*"
# Elements whose expected_signature the business has confirmed (2026-10-08: the four the
# migration queries cover). CDE_CUST_NAME declares no signature on purpose -- the
# queries' name-structure regex matches 100% of PREF_LANG_NM, CTCT_TYPE_CD, EML_STTS_CD
# and PHN_NUMB_TYPE_NM, so as a signature it would have discovery propose every one of
# them as a name -- and its structure check is TPL_NAME_STRUCTURE. dq_app's copy is
# elements.CONFIRMED_SIGNATURES, pinned to this one.
CONFIRMED_SIGNATURES = frozenset({"CDE_CUST_NAME", "CDE_CUST_DOB", "CDE_CUST_EMAIL",
                                  "CDE_CUST_MOBILE", "CDE_CUST_LANDLINE"})
TEMPLATES: list[Template] = [
    T("TPL_EMAIL_PRESENT", "email_address", "NOT_NULL", "{element} is present",
      "CTCT_EML_NOT_NULL", "EML_ID"),
    T("TPL_EMAIL_FMT", "email_address", "FMT", "{element} is a well-formed address",
      "CTCT_EML_FMT", "EML_ID", checks_format=True),
    T("TPL_PHONE_AU_FMT", "phone_number", "AU_FMT", "{element} is an Australian number",
      "CTCT_PHN_AU_FMT", "PHN_NO", checks_format=True),
    T("TPL_PHONE_PLACEHOLDER", "phone_number", "PLACEHOLDER",
      "{element} is not a placeholder number", "CTCT_PHN_PLACEHOLDER", "PHN_NO"),
    T("TPL_NAME_PRESENT", "person_name", "NOT_NULL", "{element} is present",
      "CTCT_FRST_NM_NOT_NULL", "FRST_NM"),
    T("TPL_NAME_PLACEHOLDER", "person_name", "PLACEHOLDER",
      "{element} is not a placeholder", "CTCT_FRST_NM_PLACEHOLDER", "FRST_NM"),
    T("TPL_NAME_CONTAMINATED", "person_name", "CONTAMINATED",
      "{element} holds no title, company or address", "CTCT_FRST_NM_CONTAMINATED", "FRST_NM"),
    T("TPL_NAME_STRUCTURE", "person_name", "STRUCTURE",
      "{element} is letters, spaces, hyphens and apostrophes", "CTCT_FRST_NM_STRUCTURE",
      "FRST_NM", checks_format=True),
    T("TPL_DOB_PRESENT", "date_of_birth", "NOT_NULL", "{element} is present",
      "CTCT_BRTH_NOT_NULL", "BRTH_TS", dates_too=True),
    # v2: the parse format became a slot filled per column (see the module docstring).
    T("TPL_DOB_PARSEABLE", "date_of_birth", "PARSEABLE",
      "{element} is a date in the column's format", "CTCT_BRTH_PARSEABLE", "BRTH_TS",
      checks_format=True),
    T("TPL_DOB_FUTURE", "date_of_birth", "FUTURE", "{element} is not in the future",
      "CTCT_BRTH_FUTURE", "BRTH_TS", dates_too=True, version=2),
    T("TPL_DOB_OVER_110", "date_of_birth", "OVER_110", "{element} is at most 110 years ago",
      "CTCT_BRTH_OVER_110", "BRTH_TS", dates_too=True, version=2),
    T("TPL_DOB_PLACEHOLDER", "date_of_birth", "PLACEHOLDER",
      "{element} is not a default date", "CTCT_BRTH_PLACEHOLDER", "BRTH_TS", dates_too=True,
      version=2),
    T("TPL_ID_PRESENT", "account_id", "NOT_NULL", "{element} is present",
      "CTCT_ID_NOT_NULL", "CTCT_ID"),
    T("TPL_ID_NUMERIC", "account_id", "NUMERIC", "{element} is all digits",
      "CTCT_ID_NUMERIC", "CTCT_ID", checks_format=True),
    T("TPL_ID_UNIQUE", "account_id", "UNIQUE", "{element} is unique", "CTCT_ID_UNIQUE",
      "CTCT_ID"),
    # Any class. `*` is not a data class: for_class() gives it to an element that
    # declares a signature and whose class has no format check of its own.
    T("TPL_PATTERN", ANY_CLASS, "PATTERN", "{element} matches its expected pattern",
      "CTCT_PHN_FMT", "PHN_NO", source_pattern="^0[0-9]{9}$"),
]
BY_ID = {tp.template_id: tp for tp in TEMPLATES}


def for_class(data_class: str, signature: str | None = None,
              cde_id: str | None = None) -> list[Template]:
    """The templates a column bound to an element of `data_class` gets: the class's
    own, plus TPL_PATTERN when the element is in CONFIRMED_SIGNATURES, declares
    `signature`, and none of the class's own checks what a value looks like."""
    own = [tp for tp in TEMPLATES if tp.data_class == data_class]
    if signature and cde_id in CONFIRMED_SIGNATURES \
            and not any(tp.checks_format for tp in own):
        own += [tp for tp in TEMPLATES if tp.is_pattern]
    return own


def restated(existing: dict | None, expr: str, scope: str | None) -> bool:
    """A rule already generated whose expression or scope would now come out different:
    its element changed its signature, its column's date format changed, or the template
    changed what it measures. The generator writes it again, in shadow, for a person to
    sign off as for any new check. A template version bump that leaves the expression as
    it was (the DOB templates gaining a format slot, on a column already in the source
    format) rewrites nothing."""
    return bool(existing) and (existing.get("rule_expr"), existing.get("scope_filter") or None) \
        != (expr, scope or None)


def date_column(col: str) -> tuple[str, str]:
    """A DATE or TIMESTAMP column as the date templates take it: written as text in the
    source format, which then parses back. NULL stays NULL, so presence still holds."""
    return f"date_format({col}, {wh.lit(SOURCE_DATE_FORMAT)})", SOURCE_DATE_FORMAT


def date_format_probe(col: str) -> str:
    """One SELECT list measuring every candidate format on a STRING column, for
    `choose_date_format`: n__ the non-blank values, p__<i> those parsing in format i."""
    parts = [f"count_if(trim({col}) <> '') AS n__"]
    parts += [f"count_if(trim({col}) <> '' AND try_to_timestamp({col}, {wh.lit(f)}) IS NOT NULL)"
              f" AS p__{i}" for i, (f, _) in enumerate(DATE_FORMATS)]
    return ", ".join(parts)


def choose_date_format(counts: dict) -> tuple[str | None, str]:
    """The format a STRING date column's values are in, from `date_format_probe`'s
    counts: the best-parsing one, if it parses at least DATE_FORMAT_MIN % and no format
    with its fields in another order does too. Returns (format, why) or (None, why)."""
    n = counts.get("n__") or 0
    if not n:
        return None, "the column holds no values to tell its date format from"
    rates = [(100.0 * (counts.get(f"p__{i}") or 0) / n, f, order)
             for i, (f, order) in enumerate(DATE_FORMATS)]
    passing = [r for r in rates if r[0] >= DATE_FORMAT_MIN]
    if not passing:
        best = max(rates)
        return None, (f"no date format parses {DATE_FORMAT_MIN:g}% of its values "
                      f"(best: {best[1]}, {best[0]:.1f}%)")
    orders = {r[2] for r in passing}
    if len(orders) > 1:
        return None, ("its values parse in formats with different field orders ("
                      + ", ".join(sorted({r[1] for r in passing})) + "): day and month "
                      "cannot be told apart, so no date check is generated")
    pct, fmt, _ = max(passing, key=lambda r: (r[0], -[f for f, _ in DATE_FORMATS].index(r[1])))
    return fmt, f"{pct:.1f}% of its values parse as {fmt}"


def helpers(tp: Template) -> list[str]:
    """The shared functions a template calls, by routine name (`dq_fn_is_blank_v1`)."""
    resolved = wh.fn_prefix()
    prefix = resolved.rsplit(".", 1)[-1]                     # dq_fn_
    body = tp.rule_expr + " " + (tp.scope_filter or "")
    names = re.findall(rf"{re.escape(resolved)}(\w+)\(", body)
    return sorted({prefix + n for n in names})


def equivalence() -> list[str]:
    """Every template, put back on its source column, must reproduce its source rule.
    Returns the mismatches; empty means the library is faithful to the registry."""
    bad = []
    for tp in TEMPLATES:
        r = rules.BY_ID[tp.source_rule]
        fn = wh.fn_prefix()
        want = (r.rule_expr.replace("dq.fn.", fn),
                r.scope_filter.replace("dq.fn.", fn) if r.scope_filter else None)
        if tp.instantiate(tp.source_column, tp.source_pattern, SOURCE_DATE_FORMAT) != want:
            bad.append(tp.template_id)
        if "{col}" not in tp.rule_expr:
            bad.append(f"{tp.template_id}: source column never appears in the expression")
        if tp.is_pattern and "{pattern}" not in tp.rule_expr:
            bad.append(f"{tp.template_id}: source pattern never appears in the expression")
    return bad


if __name__ == "__main__":
    miss = equivalence()
    print(f"{len(TEMPLATES)} templates, {len(miss)} mismatches {miss or ''}")
    raise SystemExit(1 if miss else 0)

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
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fixtures"))
import rules  # noqa: E402

from wh import FN_RESOLVED  # noqa: E402

TEMPLATE_VERSION = 1


@dataclass(frozen=True)
class Template:
    template_id: str
    data_class: str
    check: str                # suffix on a generated rule_id, e.g. FMT
    title: str                # "{element} is ..." -- the element name is filled in
    source_rule: str          # the registered rule this was lifted from
    source_column: str
    input_type: str = "STRING"

    def _lift(self, sql: str | None) -> str | None:
        if sql is None:
            return None
        lifted = re.sub(rf"\b{re.escape(self.source_column)}\b", "{col}", sql)
        return lifted.replace("dq.fn.", FN_RESOLVED)

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

    def instantiate(self, col: str) -> tuple[str, str | None]:
        expr = self.rule_expr.replace("{col}", col)
        scope = self.scope_filter.replace("{col}", col) if self.scope_filter else None
        return expr, scope


T = Template
TEMPLATES: list[Template] = [
    T("TPL_EMAIL_PRESENT", "email_address", "NOT_NULL", "{element} is present",
      "CTCT_EML_NOT_NULL", "EML_ID"),
    T("TPL_EMAIL_FMT", "email_address", "FMT", "{element} is a well-formed address",
      "CTCT_EML_FMT", "EML_ID"),
    T("TPL_PHONE_AU_FMT", "phone_number", "AU_FMT", "{element} is an Australian number",
      "CTCT_PHN_AU_FMT", "PHN_NO"),
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
      "FRST_NM"),
    T("TPL_DOB_PRESENT", "date_of_birth", "NOT_NULL", "{element} is present",
      "CTCT_BRTH_NOT_NULL", "BRTH_TS"),
    T("TPL_DOB_FUTURE", "date_of_birth", "FUTURE", "{element} is not in the future",
      "CTCT_BRTH_FUTURE", "BRTH_TS"),
    T("TPL_DOB_OVER_110", "date_of_birth", "OVER_110", "{element} is at most 110 years ago",
      "CTCT_BRTH_OVER_110", "BRTH_TS"),
    T("TPL_DOB_PLACEHOLDER", "date_of_birth", "PLACEHOLDER",
      "{element} is not a default date", "CTCT_BRTH_PLACEHOLDER", "BRTH_TS"),
    T("TPL_ID_PRESENT", "account_id", "NOT_NULL", "{element} is present",
      "CTCT_ID_NOT_NULL", "CTCT_ID"),
    T("TPL_ID_NUMERIC", "account_id", "NUMERIC", "{element} is all digits",
      "CTCT_ID_NUMERIC", "CTCT_ID"),
    T("TPL_ID_UNIQUE", "account_id", "UNIQUE", "{element} is unique", "CTCT_ID_UNIQUE",
      "CTCT_ID"),
]
BY_ID = {tp.template_id: tp for tp in TEMPLATES}


def for_class(data_class: str) -> list[Template]:
    return [tp for tp in TEMPLATES if tp.data_class == data_class]


def helpers(tp: Template) -> list[str]:
    """The shared functions a template calls, by routine name (`dq_fn_is_blank_v1`)."""
    prefix = FN_RESOLVED.rsplit(".", 1)[-1]                  # dq_fn_
    body = tp.rule_expr + " " + (tp.scope_filter or "")
    names = re.findall(rf"{re.escape(FN_RESOLVED)}(\w+)\(", body)
    return sorted({prefix + n for n in names})


def equivalence() -> list[str]:
    """Every template, put back on its source column, must reproduce its source rule.
    Returns the mismatches; empty means the library is faithful to the registry."""
    bad = []
    for tp in TEMPLATES:
        r = rules.BY_ID[tp.source_rule]
        want = (r.rule_expr.replace("dq.fn.", FN_RESOLVED),
                r.scope_filter.replace("dq.fn.", FN_RESOLVED) if r.scope_filter else None)
        if tp.instantiate(tp.source_column) != want:
            bad.append(tp.template_id)
        if "{col}" not in tp.rule_expr:
            bad.append(f"{tp.template_id}: source column never appears in the expression")
    return bad


if __name__ == "__main__":
    miss = equivalence()
    print(f"{len(TEMPLATES)} templates, {len(miss)} mismatches {miss or ''}")
    raise SystemExit(1 if miss else 0)

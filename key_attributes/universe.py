"""Universe rules: the generic checks an attribute gets when it has no migration rule.

An attribute the analysis wrote rules for keeps exactly those. An attribute it did not
cover still gets four checks that hold for any text value, so registering it never
leaves it unmonitored: present, no leading or trailing whitespace, no control
characters, not a placeholder. Every one is P3_monitor: a generic check knows nothing
about whether the attribute is optional or what its values should look like, so it can
report and never block.

The placeholder list is the union the analysis queries share (names, email, address
lines). Rule ids carry UNIV so a reader can tell a generic check from a migration rule
at a glance.

Today every key attribute has migration rules, so `universe_rules()` returns none. The
rule exists for the next attribute registered without them.
"""

from __future__ import annotations

from register import KEY_ATTRIBUTES, TABLE_CODE, KeyAttribute
from rules import MIGRATION_RULES, Rule, S, T, _in, blank, present

UNIVERSE_PLACEHOLDERS = ("N/A", "NA", "NONE", "NULL", "UNKNOWN", "UNDEFINED", "TBC", "TBD",
                         "TEST", "DUMMY", "NOT PROVIDED", "NOT AVAILABLE", "NOT APPLICABLE",
                         "PLEASE SPECIFY")
NOTE = ("Universe rule: a generic check, given because no migration rule covers this "
        "attribute. Replace it with the attribute's own rules when they are written.")


def rules_for(attr: KeyAttribute) -> list[Rule]:
    """The four generic checks, written for one attribute."""
    c, t = attr.column, T(attr.column)
    scope = present(c)
    base = f"{TABLE_CODE[attr.table]}_{c}_UNIV"

    def r(check, name, rtype, expr, sc):
        return Rule(f"{base}_{check}", f"{attr.name}: {name}", attr.table, c, rtype, expr,
                    sc, "P3_monitor", NOTE, universe=True)

    return [
        r("NULL_OR_BLANK", "present", "not_null", blank(c), None),
        r("LEADING_OR_TRAILING_WHITESPACE", "no leading or trailing whitespace", "format",
          f"{S(c)} <> {t}", scope),
        r("CONTROL_CHARACTERS", "no control characters", "format",
          rf"{S(c)} RLIKE '\\p{{Cc}}'", scope),
        r("PLACEHOLDER_VALUE", "not a placeholder", "sentinel",
          f"upper({t}) IN {_in(UNIVERSE_PLACEHOLDERS)}", scope),
    ]


def uncovered(attributes=None, rules=None) -> list[KeyAttribute]:
    """Attributes no migration rule names."""
    attributes = KEY_ATTRIBUTES if attributes is None else attributes
    named = {r.cde_id for r in (MIGRATION_RULES if rules is None else rules)}
    return [a for a in attributes if a.cde_id not in named]


def universe_rules(attributes=None, rules=None) -> list[Rule]:
    return [r for a in uncovered(attributes, rules) for r in rules_for(a)]


def all_rules() -> list[Rule]:
    """Every rule the register carries: the migration rules, then the universe rules for
    attributes they leave uncovered."""
    return MIGRATION_RULES + universe_rules()

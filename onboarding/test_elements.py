"""apply_elements' refusals: what an approved element proposal may not do to the register."""

from __future__ import annotations

import pytest

from elements import changed, marker, refusal

BASE = dict(cde_name="Customer email address", business_term=None,
            data_class="email_address", definition="Where we write to the customer.",
            expected_signature=None, criticality="high", pii=True, regulatory_basis=None,
            tolerance_pct=0.5, business_domain="Customer", owner_group="dq-stewards")


def _v(version, status="registered", bindings=("x",), **attrs):
    return {"cde_id": "CDE_X", "cde_version": version, "status": status,
            "bindings": list(bindings), **{**BASE, **attrs}}


def _p(change, based_on=None, by="a@example.com", reviewer="b@example.com", mark="",
       **attrs):
    body = {} if change == "retire" else {**BASE, **attrs}
    return {"proposal_id": "p1", "cde_id": "CDE_X", "change": change,
            "based_on_version": based_on, "proposed_by": by, "reviewed_by": reviewer,
            "review_reason": mark or None, **body}


def test_a_new_id_registers():
    assert refusal(_p("register"), []) is None


def test_an_id_the_register_has_held_is_never_reused_retired_included():
    assert "already used" in refusal(_p("register"), [_v(1), _v(2, status="retired")])


def test_the_author_cannot_be_the_approver():
    p = _p("register", reviewer="A@example.com")
    assert "second approver" in refusal(p, [])


def test_the_waiver_mark_lets_the_author_approve():
    p = _p("register", reviewer="a@example.com", mark="[second approver waived] ok")
    assert refusal(p, []) is None


def test_an_amendment_applies_over_binding_versions_but_not_over_attribute_changes():
    p = _p("amend", based_on=1, tolerance_pct=1.0)
    # v2 only added a binding: the author's view of the element still holds.
    assert refusal(p, [_v(1), _v(2, bindings=("x", "y"))]) is None
    # v2 changed the criticality: applying p's full attribute set would undo it.
    why = refusal(p, [_v(1), _v(2, criticality="critical")])
    assert "changed since" in why and "criticality" in why


def test_an_amendment_must_change_something():
    assert "changes nothing" in refusal(_p("amend", based_on=1), [_v(1)])


def test_a_bound_elements_data_class_cannot_change():
    assert "data class" in refusal(_p("amend", based_on=1, data_class="other"), [_v(1)])
    assert refusal(_p("amend", based_on=1, data_class="other"), [_v(1, bindings=())]) is None


@pytest.mark.parametrize("change", ["amend", "retire"])
def test_a_retired_or_unknown_element_cannot_be_changed(change):
    assert "retired" in refusal(_p(change, based_on=1, tolerance_pct=2.0),
                                [_v(1), _v(2, status="retired")])
    assert "not on the register" in refusal(_p(change, based_on=1), [])


def test_blank_text_and_nan_compare_as_absent():
    assert changed(BASE, {**BASE, "business_term": "  ", "tolerance_pct": 0.5}) == []
    assert changed({**BASE, "tolerance_pct": float("nan")}, {**BASE, "tolerance_pct": None}) == []


def test_the_marker_is_what_the_view_reads_back():
    # 18_views_cde_onboarding.sql: regexp_extract(note, '^\[cde_proposal ([^\]]+)\]', 1)
    import re
    m = re.match(r"^\[cde_proposal ([^\]]+)\]", marker("abc-123") + " Registered: why")
    assert m and m.group(1) == "abc-123"

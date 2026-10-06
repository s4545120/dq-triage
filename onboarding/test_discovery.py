"""discovery.decide, one rule per test. No warehouse.

    cd onboarding && ../.venv/bin/python -m pytest test_discovery.py -q
"""

from __future__ import annotations

import discovery
from discovery import decide

KNOWN = set(discovery.NAME_HINTS)
NAMES = {c: c for c in KNOWN}
KEYS = ["CDE_CUST_KEY", "CDE_SUBS_KEY", "CDE_BILLING_ACCOUNT", "CDE_BILL_OFFER",
        "CDE_DEVICE_IMEI", "CDE_SIM_SERIAL", "CDE_CUST_IDENT_DOC"]   # all share ^\d{7}$


def _pct(fit: dict[str, float]) -> dict[str, float]:
    return {c: fit.get(c, 0.0) for c in KNOWN}


def test_a_tag_wins_whatever_the_name_or_values_say():
    d = decide("MOBL_NO", "STRING", known=KNOWN, names=NAMES, tag="CDE_CUST_EMAIL",
               nonblank=500, match_pct=_pct({"CDE_CUST_MOBILE": 100}))
    assert (d["cde_id"], d["method"], d["confidence"]) == ("CDE_CUST_EMAIL", "uc_tag", 1.0)


def test_a_pattern_only_one_element_fits_is_proposed_on_the_values():
    d = decide("contact_addr", "STRING", known=KNOWN, names=NAMES,
               nonblank=300, match_pct=_pct({"CDE_CUST_EMAIL": 97.0}))
    assert (d["cde_id"], d["method"], d["confidence"]) == ("CDE_CUST_EMAIL", "value_signature", 0.97)


def test_a_shared_pattern_is_narrowed_by_the_name():
    d = decide("IMEI_ID", "STRING", known=KNOWN, names=NAMES,
               nonblank=800, match_pct=_pct({k: 100.0 for k in KEYS}))
    assert (d["cde_id"], d["method"]) == ("CDE_DEVICE_IMEI", "name_match")
    assert d["confidence"] == discovery.NARROWED_CONFIDENCE
    assert "7 elements share" in d["evidence"]


def test_a_shared_pattern_with_no_naming_column_proposes_nothing():
    d = decide("SUBS_ID", "STRING", known=KNOWN, names=NAMES,
               nonblank=1000, match_pct=_pct({k: 100.0 for k in KEYS}))
    assert d["cde_id"] is None and "7 elements' patterns" in d["why"]


def test_a_name_outside_the_elements_the_values_fit_does_not_narrow():
    """`moblno` names mobile, but these values fit only the seven-digit keys."""
    d = decide("MOBL_NO", "STRING", known=KNOWN, names=NAMES,
               nonblank=500, match_pct=_pct({k: 100.0 for k in KEYS}))
    assert d["cde_id"] is None


def test_a_near_miss_the_name_agrees_with_is_proposed_as_bad_values():
    """EML_ID: 76% look like emails because the rest are bad emails."""
    d = decide("EML_ID", "STRING", known=KNOWN, names=NAMES,
               nonblank=1000, match_pct=_pct({"CDE_CUST_EMAIL": 76.0}))
    assert (d["cde_id"], d["method"]) == ("CDE_CUST_EMAIL", "name_match")
    assert d["confidence"] == discovery.NAME_MATCH_CONFIDENCE
    assert "bad values" in d["evidence"]


def test_a_near_miss_the_name_contradicts_proposes_nothing():
    d = decide("EML_ID", "STRING", known=KNOWN, names=NAMES,
               nonblank=1000, match_pct=_pct({"CDE_CUST_LANDLINE": 80.0}))
    assert d["cde_id"] is None and d["why"].startswith("near miss")


def test_without_values_the_name_alone_decides_at_its_own_confidence():
    d = decide("customerID", "LONG", known=KNOWN, names=NAMES)
    assert (d["cde_id"], d["confidence"]) == ("CDE_CUST_KEY", discovery.NAME_MATCH_CONFIDENCE)


def test_too_few_values_fall_back_to_the_name():
    d = decide("BRTH_TS", "STRING", known=KNOWN, names=NAMES,
               nonblank=discovery.SIGNATURE_MIN_VALUES - 1,
               match_pct=_pct({"CDE_CUST_DOB": 100.0}))
    assert (d["cde_id"], d["method"]) == ("CDE_CUST_DOB", "name_match")


def test_an_element_that_is_not_registered_is_never_proposed():
    d = decide("IMEI_ID", "STRING", known=KNOWN - {"CDE_DEVICE_IMEI"}, names=NAMES)
    assert d["cde_id"] is None


def test_no_name_is_listed_under_two_elements():
    seen: dict[str, str] = {}
    for cde, names in discovery.NAME_HINTS.items():
        for n in names:
            assert n == discovery.name_key(n), f"{n} is not in normalised form"
            assert n not in seen, f"{n} is listed under {seen[n]} and {cde}"
            seen[n] = cde


def test_narrow_off_is_discovery_as_it_was():
    shared = decide("IMEI_ID", "STRING", known=KNOWN, names=NAMES, nonblank=800,
                    match_pct=_pct({k: 100.0 for k in KEYS}), narrow=False)
    near = decide("EML_ID", "STRING", known=KNOWN, names=NAMES, nonblank=1000,
                  match_pct=_pct({"CDE_CUST_EMAIL": 76.0}), narrow=False)
    assert shared["cde_id"] is None and near["cde_id"] is None

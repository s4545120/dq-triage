"""How discovery decides what a column holds -- the rules alone, with no warehouse.

onboard.py `discover` gathers the facts (tags, types, value-pattern match rates) and asks
`decide` about each column; evaluate_discovery.py asks the same function about every
column of a table and compares the answers with what people approved. One function, so
the comparison measures the code that runs, not a copy of it.

The order is the order of certainty:

  1. A Unity Catalog tag `cde = <element id>`: someone said so.          confidence 1.0
  2. A value pattern only one element's values match (>= 95%).           the match rate
  3. A value pattern SEVERAL elements match, narrowed to one by the
     column's name. Neither the shape nor the name settles it alone;
     together they name one element.                                      0.75
     Or a near miss (50-95% match) whose element the name also names:
     usually the right column holding bad values.                         0.6
  4. The column's name alone.                                            0.6

Several candidates at any step mean silence, not a guess. Nothing here approves
anything: every answer is a proposal a person decides.
"""

from __future__ import annotations

SIGNATURE_THRESHOLD_PCT = 95.0   # Ataccama's "detection threshold": share of non-blank values
SIGNATURE_MIN_VALUES = 20        # too few values and a match rate means nothing
NAME_MATCH_CONFIDENCE = 0.6      # a column name is a weaker claim than a tag or the values
NARROWED_CONFIDENCE = 0.75       # a shape several elements share, plus a name naming one

# Column names that say which element a column holds, compared with case and every
# non-alphanumeric character removed (`PRIM_ACCT_KEY` -> `primacctkey`). The fallback
# for a catalog nobody can tag and for columns whose values have no fixed shape, and
# since 2026-10-06 the tie-breaker when a value pattern fits several elements.
#
# The abbreviations are this estate's (the ECF warehouse convention: `_NM` name, `_TS`
# timestamp, `STTS` status, `RSN` reason, `ACTV` activation). An exact name, never a
# substring: `subsid` is a subscription's source id, not its key, and only the
# elements' owners know which is which. A name listed under two elements proposes
# nothing. Adding a name here is a code change; see the open question in the
# discovery doc about who owns this list.
NAME_HINTS = {
    "CDE_CUST_EMAIL": ["email", "emailaddress", "emailaddr", "emlid", "eml"],
    "CDE_CUST_NAME": ["firstname", "givenname", "lastname", "familyname", "surname",
                      "frstnm", "lastnm", "fullname", "legalname",
                      "middlename", "midnm", "leglnm"],
    "CDE_CUST_DOB": ["dob", "birthdate", "dateofbirth", "brthts", "birthts"],
    "CDE_CUST_MOBILE": ["mobile", "mobileno", "mobilenumber", "mobilephone", "moblno"],
    "CDE_CUST_LANDLINE": ["phone", "phoneno", "phonenumber", "homephone", "landline", "phnno"],
    "CDE_CUST_KEY": ["customerid", "custid", "contactid", "customerkey", "ctctid", "ctctkey"],
    "CDE_CUST_IDENT_DOC": ["idntdoc1no", "idntdocno", "identitydocumentnumber",
                           "iddocumentnumber"],
    "CDE_CUST_MSISDN": ["msisdn", "primrsrcvalutxt", "servicenumber"],
    "CDE_PREF_LANGUAGE": ["preflangnm", "preflang", "preferredlanguage"],
    "CDE_SUBS_KEY": ["subskey", "subscriptionkey"],
    "CDE_SUBS_STATUS": ["subssttskey", "subssttsrsnkey", "subscriptionstatus",
                        "subscriptionstatusreason"],
    "CDE_SUBS_ACTIVATION": ["initactvts", "origactvts", "activationdate", "activationts"],
    "CDE_RECORD_LIFECYCLE": ["ecfopents", "ecfclsets"],
    "CDE_BILLING_ACCOUNT": ["primacctkey", "billingaccount", "billingaccountid"],
    "CDE_BILL_OFFER": ["mainbilloffrkey", "billoffer", "billofferkey"],
    "CDE_DEVICE_IMEI": ["imei", "imeiid", "imeino"],
    "CDE_SIM_SERIAL": ["simserlid", "simserial", "simserialnumber", "iccid"],
    "CDE_NETWORK_TECH": ["ntwktechnm", "networktechnology"],
    "CDE_BENEFIT_TEXT": ["bnfttxt", "benefittext"],
}


def name_key(column: str) -> str:
    return "".join(ch for ch in column.lower() if ch.isalnum())


def named_by(column: str, known: set[str]) -> list[str]:
    """Every registered element whose name list holds this column's name."""
    key = name_key(column)
    return [cde for cde, names in NAME_HINTS.items() if key in names and cde in known]


def decide(column: str, data_type: str, *, known: set[str], names: dict[str, str],
           tag: str | None = None, nonblank: int | None = None,
           match_pct: dict[str, float] | None = None, narrow: bool = True) -> dict:
    """What discovery says about one column.

    `known` the registered element ids, `names` id -> display name, `tag` the column's
    `cde` tag if any, `nonblank` and `match_pct` (element id -> % of non-blank values
    matching that element's pattern) for a text column the pattern query covered.

    `narrow=False` skips step 3 (both halves), to measure discovery as it was before
    2026-10-06.

    Returns {"cde_id", "method", "confidence", "evidence"} for a proposal, or
    {"cde_id": None, "why", "detail"} for a column left alone.
    """
    def propose(cde, method, conf, evidence):
        return {"cde_id": cde, "method": method, "confidence": conf, "evidence": evidence}

    def leave(why, detail=""):
        return {"cde_id": None, "why": why, "detail": detail}

    # 1. A tag: someone already said what the column is.
    if tag is not None:
        if tag in known:
            return propose(tag, "uc_tag", 1.0, f"column tag cde = {tag}")
        return leave("tag names an element that is not registered", tag)

    # 2-3. Value patterns, for a text column with enough values to mean something.
    if match_pct is not None and nonblank is not None and nonblank >= SIGNATURE_MIN_VALUES:
        ranked = sorted(match_pct.items(), key=lambda kv: -kv[1])
        hits = [(cde, pct) for cde, pct in ranked if pct >= SIGNATURE_THRESHOLD_PCT]
        if len(hits) == 1:
            cde, pct = hits[0]
            return propose(cde, "value_signature", round(pct / 100, 4),
                           f"{pct:.1f}% of {nonblank} non-blank values match "
                           f"{names.get(cde, cde)}'s pattern; no other element's does")
        if hits:
            fits = [cde for cde, _ in hits]
            by_name = [cde for cde in named_by(column, known) if cde in fits] if narrow else []
            if len(by_name) == 1:
                cde = by_name[0]
                pct = dict(hits)[cde]
                return propose(cde, "name_match", NARROWED_CONFIDENCE,
                               f"{pct:.1f}% of {nonblank} non-blank values match the pattern "
                               f"{len(fits)} elements share; the column name {column!r} names "
                               f"{names.get(cde, cde)}, one of them")
            return leave(f"matches {len(fits)} elements' patterns; tag it to say which",
                         ", ".join(fits))
        if ranked and ranked[0][1] >= 50:
            # A near miss is usually a column of the right kind holding bad values --
            # exactly what the checks exist to find. The name may settle it, but only
            # for an element the values also half-fit: a name the values contradict
            # proposes nothing.
            close = {cde: pct for cde, pct in ranked if pct >= 50}
            by_name = [cde for cde in named_by(column, known) if cde in close] if narrow else []
            if len(by_name) == 1:
                cde = by_name[0]
                return propose(cde, "name_match", NAME_MATCH_CONFIDENCE,
                               f"the column name {column!r} names {names.get(cde, cde)}; "
                               f"{close[cde]:.1f}% of {nonblank} non-blank values match its "
                               f"pattern, below {SIGNATURE_THRESHOLD_PCT:.0f}% -- check for "
                               f"bad values rather than a wrong binding")
            cde, pct = ranked[0]
            return leave(f"near miss: best match {pct:.1f}% ({cde}), below "
                         f"{SIGNATURE_THRESHOLD_PCT:.0f}%")

    # 4. The name alone, for what neither a tag nor the values settled.
    hits = named_by(column, known)
    if len(hits) == 1:
        return propose(hits[0], "name_match", NAME_MATCH_CONFIDENCE,
                       f"column name {column!r} names this element ({data_type})")
    if hits:
        return leave("name matches several elements", ", ".join(hits))
    return leave("nothing identifies it", data_type)

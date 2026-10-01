"""The critical data element register, declared against the pilot CSVs.

Companion to `rules.py`. Where that file says *what we check*, this one says *what
matters* — and the two are deliberately independent, because the whole point of a
CDE register is to be a denominator that does not move when the rule set does. An
element registered here with no rule against it is not an oversight in this file; it
is the finding.

REGISTERED, NOT DISCOVERED. In the full design, bindings are proposed by a
classification sweep — column-name tokens, value signatures, Unity Catalog lineage —
and confirmed by a steward. For the PoC that sweep does not exist and every binding
below is hand-authored, which is why they all carry `discovered_by='manual'` and
`binding_status='bound'`. Those two fields are the seam: when discovery lands it
writes new rows in a 'candidate' state and nothing here has to change shape.

WHY EACH BINDING CARRIES BOTH `populated_when` AND `expected_scope_filter`. The
first is prose for a steward reading the register. The second is the same claim as a
SQL predicate, and it is checkable: `v_cde_coverage` compares it against the
`scope_filter` on every rule attached to the binding and flags a rule that has none.
That is not decoration. Two rules in `rules.py` are deliberately unscoped and report
700 false breaches; the bindings for IMEI and PRIM_ACCT_KEY below declare the scope
those rules should have had, which turns cohort COH-B's root cause from something a
human noticed into something the register asserts. The rules stay broken — see the
note in CLAUDE.md. This file does not fix them. It makes them provably wrong.

Signature regexes are matched against real values by `profile.py`. They were written
after profiling the CSVs, not guessed: a seven-digit identifier is what the pilot
data actually contains, and a signature that does not match the data would make
`signature_match_pct` meaningless rather than informative.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

from rules import CTCT_TABLE, SUBS_TABLE

# Scope predicates, in the two forms this repo always keeps in step: the SQL that
# would run on Databricks, and the pandas that runs here. Compare with rules.py,
# where every rule carries a rule_expr and an evaluator for exactly this reason.
ScopeFn = Callable[[pd.DataFrame], pd.Series]


@dataclass
class Binding:
    """Where one element physically lives."""

    target_table: str
    target_column: str
    populated_when: str | None = None
    expected_scope_filter: str | None = None
    scope_fn: ScopeFn | None = None      # the pandas twin of expected_scope_filter
    binding_status: str = "bound"
    discovered_by: str = "manual"
    confidence: float = 1.0

    def to_struct(self) -> dict:
        """The struct written into config.cde_registry.bindings. `scope_fn` is a
        local execution detail and is deliberately not part of the table."""
        return dict(
            target_table=self.target_table,
            target_column=self.target_column,
            populated_when=self.populated_when,
            expected_scope_filter=self.expected_scope_filter,
            binding_status=self.binding_status,
            discovered_by=self.discovered_by,
            confidence=self.confidence,
        )


# THE ORGANISATION'S TOLERANCE, BY TIER. What share of an element's rows may be
# wrong before the business calls it broken -- the value written to
# config.cde_registry.tolerance_pct, and the CEILING the triage job holds every
# threshold suggestion under. Tiered by criticality because that is how such a
# policy is usually first stated, and set here explicitly rather than derived at
# read time so the register carries the declaration and not a rule for making one.
# Like the criticality tiers themselves these are one person's starting point for a
# conversation with the business, not an agreed policy; an element that needs a
# different figure says so on its own row.
TOLERANCE_BY_CRITICALITY = {"critical": 0.0, "high": 0.5, "medium": 2.0, "low": 5.0}

# When the fixture's retirements took effect: the day they were decided, a month
# after the final check run, so every run and cohort before it is history the
# retirement does not reach.
RETIRED_AT = pd.Timestamp("2026-10-01 09:00:00")


@dataclass
class CDE:
    cde_id: str
    cde_name: str
    data_class: str
    definition: str
    criticality: str
    pii: bool
    bindings: list[Binding]
    business_term: str | None = None
    expected_signature: str | None = None
    regulatory_basis: str | None = None
    # The declared tolerance. None here means "take the tier default" and is
    # resolved in __post_init__, so every registered element carries a figure and
    # the NULL the DDL permits is reserved for an element nobody has decided on.
    tolerance_pct: float | None = None
    business_domain: str = "Customer"
    owner_group: str = "dq-stewards-customer"
    status: str = "registered"
    cde_version: int = 1
    note: str = ""
    # A retired element is written as two versions: v1 registered, carrying `note`,
    # and the retiring version carrying `retired_note`. Retiring is an INSERT, never
    # a delete -- the register is append-only -- so the element's history, and every
    # check run and cohort that predates the retirement, stays readable.
    retired_note: str = ""
    # Rules a column join cannot reach, tagged explicitly. Kept to the genuine
    # cases: tagging a rule whose target_column already matches a binding would
    # make config.rule_registry.cde_id look load-bearing when the column match
    # already did the work, and would leave that join path untested.
    explicit_rule_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.tolerance_pct is None:
            self.tolerance_pct = TOLERANCE_BY_CRITICALITY[self.criticality]


# ---------------------------------------------------------------------------
# Scope predicates — the pandas side
# ---------------------------------------------------------------------------

def _mobile_resource(df: pd.DataFrame) -> pd.Series:
    return df.PRIM_RSRC_TYPE_KEY == "1"


def _has_sim(df: pd.DataFrame) -> pd.Series:
    return df.PROD_TYPE_KEY != "0"


def _postpaid(df: pd.DataFrame) -> pd.Series:
    return df.BILL_SUBS_TYPE_CD == "POSTPAID"


def _identity_type_recorded(df: pd.DataFrame) -> pd.Series:
    return df.IDNT_TYPE_1_CD.str.strip() != ""


# ---------------------------------------------------------------------------
# The register
# ---------------------------------------------------------------------------

CDES: list[CDE] = [
    CDE(
        cde_id="CDE_CUST_EMAIL",
        cde_name="Customer email address",
        business_term="Customer contact email",
        data_class="email_address",
        definition=(
            "The email address the business uses to reach a customer for servicing, "
            "billing and consent-bearing communications. Not a marketing preference "
            "and not an account login."),
        # Deliberately the same expression as CTCT_EML_FMT. A looser one -- merely
        # "has an @ and a dotted domain" -- accepts the doubled-dot and trailing-dot
        # buckets, and signature_match_pct would then sit 80 rows above the rule's
        # violation count with nothing to explain the gap. Where a platform rule
        # already defines well-formedness for an element, the register agrees with
        # it rather than inventing a second definition.
        expected_signature=r"^[^@\s.]+(\.[^@\s.]+)*@[^@\s.]+(\.[^@\s.]+)+$",
        criticality="high",
        pii=True,
        regulatory_basis="Privacy Act 1988 (Cth) APP 10 — quality of personal information",
        bindings=[
            Binding(CTCT_TABLE, "EML_ID"),
            # The source's own verdict on the address is part of the element, not
            # an element of its own: a rule names its element and attaches by the
            # column it reads, so the two rules on EML_STTS_CD need this binding.
            Binding(CTCT_TABLE, "EML_STTS_CD"),
        ],
        note=(
            "The best-covered element in the register: nine active rules over two "
            "columns -- one composite and six specific on the address, two on the "
            "source's own status code. Registered as high rather than critical because an "
            "undeliverable address delays a communication; it does not misidentify a person."),
    ),
    CDE(
        cde_id="CDE_CUST_MSISDN",
        cde_name="Mobile service number (MSISDN)",
        business_term="Service number",
        data_class="msisdn",
        definition=(
            "The mobile number a service is reachable on. Identifies the service to the "
            "network, to the customer and to every downstream system, which is why it is "
            "the one element here tiered critical on availability rather than on privacy."),
        expected_signature=r"^04\d{8}$",
        criticality="critical",
        pii=True,
        regulatory_basis="Telecommunications Consumer Protections Code C628 — service identification",
        bindings=[Binding(
            SUBS_TABLE, "PRIM_RSRC_VALU_TXT",
            populated_when="the primary resource on the service is a mobile number",
            expected_scope_filter="PRIM_RSRC_TYPE_KEY = 1",
            scope_fn=_mobile_resource,
        )],
        note=(
            "The column name says nothing — PRIM_RSRC_VALU_TXT holds whatever resource "
            "type the service uses. Only the data identifies it, which is why a register "
            "built from column names alone would have missed it entirely."),
    ),
    CDE(
        cde_id="CDE_CUST_DOB",
        cde_name="Customer date of birth",
        business_term="Date of birth",
        data_class="date_of_birth",
        definition=(
            "The customer's date of birth as evidenced at onboarding. Used for identity "
            "verification, for age-gating, and for the credit assessment that a contract "
            "service depends on."),
        expected_signature=r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$",
        criticality="high",
        pii=True,
        regulatory_basis="AML/CTF Act 2006 s.32 — KYC identity evidence",
        bindings=[Binding(CTCT_TABLE, "BRTH_TS")],
        note=(
            "The element where profiling earns its place on its own. The fourteen values "
            "written DD-MM-YYYY carry a different masked signature from the other 986, so "
            "they show up in top_signatures as a minority shape before any rule asserts "
            "anything about the column."),
    ),
    CDE(
        cde_id="CDE_CUST_NAME",
        cde_name="Customer name",
        business_term="Customer legal name",
        data_class="person_name",
        definition=(
            "The name of the person the account is held by, as given on identity evidence. "
            "Three columns realise it: the full legal name and its parsed given and family "
            "components."),
        expected_signature=None,   # a name has no shape; asserting one is how you reject people
        criticality="high",
        pii=True,
        regulatory_basis="AML/CTF Act 2006 s.32 — KYC identity evidence",
        bindings=[
            Binding(CTCT_TABLE, "LEGL_NM"),
            Binding(CTCT_TABLE, "FRST_NM"),
            Binding(CTCT_TABLE, "LAST_NM"),
        ],
        explicit_rule_ids=["XREF_NAME_AGREEMENT"],
        note=(
            "High criticality, and the only rule that touches it is a cross-table agreement "
            "check with no target_column — so a coverage view joining on columns alone would "
            "report zero rules on a KYC element and be wrong about why. That is what "
            "rule_registry.cde_id is for. Even counting it, all three bindings are watched by "
            "one consistency rule and nothing else: no format rule, no presence rule, no "
            "uniqueness. This is a real gap, left in place because reporting it is the point."),
    ),
    CDE(
        cde_id="CDE_CUST_IDENT_DOC",
        cde_name="Identity document number",
        business_term="Identity evidence document number",
        data_class="national_id",
        definition=(
            "The number of the document presented as identity evidence at onboarding — "
            "passport, driver licence or equivalent, as typed in IDNT_TYPE_1_CD. The single "
            "most sensitive element in the register."),
        expected_signature=r"^\d{7}$",
        criticality="critical",
        pii=True,
        regulatory_basis="AML/CTF Act 2006 s.32 — KYC identity evidence; Privacy Act 1988 (Cth) APP 11",
        bindings=[Binding(
            CTCT_TABLE, "IDNT_DOC_1_NO",
            populated_when="an identity document type has been recorded for the contact",
            expected_scope_filter="IDNT_TYPE_1_CD IS NOT NULL AND trim(IDNT_TYPE_1_CD) <> ''",
            scope_fn=_identity_type_recorded,
        )],
        note=(
            "Critical, PII, KYC-bearing — and watched by exactly one rule, which only checks "
            "that the field is not empty. Nothing verifies the number is well formed for its "
            "document type, and nothing checks it is not shared between two people. The "
            "coverage panel classifies this 'unvalidated' and it is the strongest argument "
            "in the register for having built the register."),
    ),
    CDE(
        cde_id="CDE_CUST_MOBILE",
        cde_name="Customer contact mobile number",
        business_term="Contact mobile",
        data_class="phone_number",
        definition=(
            "The mobile number used to reach the person, as distinct from the MSISDN a "
            "service runs on. The two are frequently the same number and are not the same "
            "element — one is a contact detail, the other is a network resource."),
        expected_signature=r"^04\d{8}$",
        criticality="high",
        pii=True,
        regulatory_basis="Privacy Act 1988 (Cth) APP 10 — quality of personal information",
        bindings=[Binding(CTCT_TABLE, "MOBL_NO")],
    ),
    CDE(
        cde_id="CDE_CUST_LANDLINE",
        cde_name="Customer contact landline number",
        business_term="Contact landline",
        data_class="phone_number",
        definition="The fixed-line number recorded against the contact, where one is held.",
        expected_signature=r"^0\d{9}$",
        criticality="medium",
        pii=True,
        regulatory_basis="Privacy Act 1988 (Cth) APP 10 — quality of personal information",
        bindings=[Binding(CTCT_TABLE, "PHN_NO")],
        note="Medium: a stale landline degrades reach, it does not misidentify or misbill.",
    ),
    CDE(
        cde_id="CDE_SIM_SERIAL",
        cde_name="SIM serial number",
        business_term="SIM serial",
        data_class="device_id",
        definition=(
            "The serial of the SIM provisioned to a service. Identifies the SIM to the "
            "network and is the key to a replacement or port."),
        expected_signature=r"^\d{7}$",
        criticality="medium",
        pii=False,
        bindings=[Binding(
            SUBS_TABLE, "SIM_SERL_ID",
            populated_when="services that carry a SIM — everything except fixed broadband",
            expected_scope_filter="PROD_TYPE_KEY <> 0",
            scope_fn=_has_sim,
        )],
        business_domain="Subscription",
        owner_group="dq-stewards-subscription",
        note=(
            "The correctly-scoped counterpart to IMEI below. Its rule carries the same "
            "scope_filter the binding declares, so the coverage view finds no mismatch — "
            "which is what makes the mismatch it does find on IMEI meaningful rather than "
            "an artefact of how the check is written."),
    ),
    CDE(
        cde_id="CDE_DEVICE_IMEI",
        cde_name="Device IMEI",
        business_term="Handset IMEI",
        data_class="device_id",
        definition=(
            "The identity of the handset attached to a service. Only exists where the "
            "service involves a handset at all."),
        expected_signature=r"^\d{7}$",
        criticality="medium",
        pii=False,
        bindings=[Binding(
            SUBS_TABLE, "IMEI_ID",
            populated_when="handset services only — fixed broadband has no handset and never will",
            expected_scope_filter="PROD_TYPE_KEY <> 0",
            scope_fn=_has_sim,
        )],
        business_domain="Subscription",
        owner_group="dq-stewards-subscription",
        note=(
            "COH-B, stated as a contradiction rather than as a discovery. The binding says "
            "this column is only populated for handset services. SUBS_IMEI_NOT_NULL carries "
            "no scope_filter and so measures every row, reporting 200 fixed-broadband "
            "services as defects. v_cde_coverage flags the rule by id. The rule is left "
            "unscoped on purpose — see CLAUDE.md; the register's job here is to show that "
            "the data is fine and the rule is not."),
    ),
    CDE(
        cde_id="CDE_BILLING_ACCOUNT",
        cde_name="Primary billing account",
        business_term="Billing account key",
        data_class="account_id",
        definition=(
            "The billing account a service charges to. Postpaid services have one by "
            "definition; prepaid services do not have one at all."),
        expected_signature=r"^\d{7}$",
        criticality="high",
        pii=False,
        bindings=[Binding(
            SUBS_TABLE, "PRIM_ACCT_KEY",
            populated_when="postpaid services only — a prepaid service has no billing account",
            expected_scope_filter="BILL_SUBS_TYPE_CD = 'POSTPAID'",
            scope_fn=_postpaid,
        )],
        business_domain="Subscription",
        owner_group="dq-stewards-subscription",
        note=(
            "The second half of COH-B. SUBS_PRIM_ACCT_NOT_ZERO is unscoped and reports every "
            "prepaid service as a defect; the binding says prepaid never carries one. Its "
            "correctly-scoped twin SUBS_BILL_OFFR_NOT_ZERO checks a different column on the "
            "same rows and returns zero."),
    ),

    # ------------------------------------------------------------------
    # The second ten, registered 2026-09-28 when DQ became CDE-only: every
    # rule must name its element, so every column a rule watches is now an
    # element somebody has declared. These are the one person's starting
    # point that the first ten are, and say so; the business confirms the
    # tier, the tolerance and whether the element belongs on the list at all.
    # Two of them exist to carry a shadow rule and so start with no active
    # rule -- the `no_rule` finding the first ten never exercised.
    # ------------------------------------------------------------------
    CDE(
        cde_id="CDE_CUST_KEY",
        cde_name="Customer record key",
        business_term="Customer key",
        data_class="account_id",
        definition=(
            "The surrogate key of the contact record. Every subscription points at one; "
            "a key that is not unique or that a subscription cannot resolve is a broken "
            "customer, whatever else is right about the row."),
        expected_signature=r"^\d{7}$",
        criticality="critical",
        pii=False,
        bindings=[Binding(CTCT_TABLE, "CTCT_KEY")],
        explicit_rule_ids=["XREF_SUBS_CTCT_ORPHAN"],
        note=(
            "Uniqueness by column match; the orphan check is cross-table, carries no "
            "target_column, and attaches by tag -- it is a rule about whether this key "
            "resolves, so this is its element."),
    ),
    CDE(
        cde_id="CDE_SUBS_KEY",
        cde_name="Subscription record key",
        business_term="Subscription key",
        data_class="account_id",
        definition="The surrogate key of the subscription record.",
        expected_signature=r"^\d{7}$",
        criticality="critical",
        pii=False,
        bindings=[Binding(SUBS_TABLE, "SUBS_KEY")],
        business_domain="Subscription",
        owner_group="dq-stewards-subscription",
    ),
    CDE(
        cde_id="CDE_VULNERABLE_CUSTOMER",
        cde_name="Vulnerable customer indicator",
        business_term="Special-care status",
        data_class="other",
        definition=(
            "Whether the contact is recorded as needing special care -- financial "
            "hardship, accessibility, or another vulnerability the business must act "
            "on. A flag that is never set is a customer never protected."),
        expected_signature=r"^[YN]$",
        criticality="critical",
        pii=True,
        regulatory_basis="Telecommunications Consumer Protections Code C628 — vulnerable customers and financial hardship",
        bindings=[Binding(CTCT_TABLE, "SPCL_CARE_STTS")],
        note=(
            "The pilot data reads 'N' on all 1000 rows, and the variance rule that "
            "watches it says so. Whether that is a defaulted field or a population with "
            "no vulnerable customers is COH-F's open question."),
        status="retired",
        cde_version=2,
        retired_note=(
            "v2: retired 2026-10-01. Its only rule, CTCT_SPCL_CARE_VARIANCE, asked whether "
            "the flag ever varied, and on a 1000-row pilot extract an all-'N' column cannot "
            "tell a defaulted field from a population with no vulnerable customers -- so "
            "every run scored the element 0% for a question the data cannot answer. Retired "
            "with its rule rather than deleted. COH-F, raised on 2026-08-30 with that rule as "
            "a member, is left as raised. Re-register when the business can state how many "
            "customers it expects to carry the flag."),
    ),
    CDE(
        cde_id="CDE_PREF_LANGUAGE",
        cde_name="Preferred language",
        business_term="Contact language",
        data_class="other",
        definition="The language the contact prefers to be served in.",
        expected_signature=None,
        criticality="low",
        pii=False,
        bindings=[Binding(CTCT_TABLE, "PREF_LANG_NM")],
        note=(
            "Its only rule is in shadow, so this element registers with no active rule "
            "against it -- the no_rule finding, present in the register on purpose."),
    ),
    CDE(
        cde_id="CDE_SUBS_STATUS",
        cde_name="Subscription status and reason",
        business_term="Subscription lifecycle status",
        data_class="other",
        definition=(
            "Whether the subscription is active, cancelled or suspended, and why. The "
            "reason is only meaningful once the status is something other than active."),
        expected_signature=None,
        criticality="high",
        pii=False,
        bindings=[
            Binding(SUBS_TABLE, "SUBS_STTS_KEY"),
            Binding(
                SUBS_TABLE, "SUBS_STTS_RSN_KEY",
                populated_when="the subscription is not active",
                expected_scope_filter="SUBS_STTS_KEY <> 1",
                scope_fn=lambda df: df.SUBS_STTS_KEY != "1",
            ),
        ],
        business_domain="Subscription",
        owner_group="dq-stewards-subscription",
        note=(
            "Two bindings, one rule: the reason is checked, the status itself is not. "
            "The status binding is a no_rule finding until somebody writes one."),
    ),
    CDE(
        cde_id="CDE_SUBS_ACTIVATION",
        cde_name="Service activation timestamps",
        business_term="Activation date",
        data_class="other",
        definition=(
            "When the service was first activated and when it was originally provisioned. "
            "The start of billing and of the contract term."),
        expected_signature=r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$",
        criticality="high",
        pii=False,
        regulatory_basis="Telecommunications Consumer Protections Code C628 — billing accuracy",
        bindings=[
            Binding(SUBS_TABLE, "ORIG_ACTV_TS"),
            Binding(SUBS_TABLE, "INIT_ACTV_TS"),
        ],
        business_domain="Subscription",
        owner_group="dq-stewards-subscription",
    ),
    CDE(
        cde_id="CDE_RECORD_LIFECYCLE",
        cde_name="Record lifecycle timestamps",
        business_term="Record open and close",
        data_class="other",
        definition=(
            "When the subscription record was opened in the warehouse and, once "
            "cancelled, when it was closed. Agreement with the contact record's own "
            "timestamps is what says the two tables loaded from the same event."),
        expected_signature=r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$",
        criticality="medium",
        pii=False,
        bindings=[
            Binding(SUBS_TABLE, "ECF_OPEN_TS"),
            Binding(
                SUBS_TABLE, "ECF_CLSE_TS",
                # Prose only, no expected_scope_filter: the agreement rule on this
                # column checks BOTH directions -- closed without a cancel, cancelled
                # without a close -- and must run unscoped to do so. Declaring a scope
                # here would accuse a correct rule of a mismatch.
                populated_when="once the subscription is cancelled",
            ),
        ],
        explicit_rule_ids=["XREF_OPEN_TS_AGREEMENT"],
        business_domain="Subscription",
        owner_group="dq-stewards-subscription",
    ),
    CDE(
        cde_id="CDE_NETWORK_TECH",
        cde_name="Network technology",
        business_term="Access technology",
        data_class="other",
        definition="The network the service runs on -- 4G, 5G, NBN and its variants.",
        expected_signature=None,
        criticality="medium",
        pii=False,
        bindings=[Binding(SUBS_TABLE, "NTWK_TECH_NM")],
        business_domain="Subscription",
        owner_group="dq-stewards-subscription",
    ),
    CDE(
        cde_id="CDE_BILL_OFFER",
        cde_name="Main billing offer",
        business_term="Billing offer key",
        data_class="account_id",
        definition=(
            "The offer a postpaid service is billed under. Prepaid services have none, "
            "for the same reason they have no billing account."),
        expected_signature=r"^\d{7}$",
        criticality="high",
        pii=False,
        regulatory_basis="Telecommunications Consumer Protections Code C628 — billing accuracy",
        bindings=[Binding(
            SUBS_TABLE, "MAIN_BILL_OFFR_KEY",
            populated_when="postpaid services only",
            expected_scope_filter="BILL_SUBS_TYPE_CD = 'POSTPAID'",
            scope_fn=_postpaid,
        )],
        business_domain="Billing",
        owner_group="dq-stewards-billing",
        note=(
            "The correctly-scoped counterpart to Primary billing account: its rule "
            "carries the scope the binding declares, so the coverage view finds no "
            "mismatch here and one there."),
    ),
    CDE(
        cde_id="CDE_BENEFIT_TEXT",
        cde_name="Benefit description",
        business_term="Plan benefit",
        data_class="other",
        definition="Free-text description of the benefit attached to the plan, where one exists.",
        expected_signature=None,
        criticality="low",
        pii=False,
        bindings=[Binding(SUBS_TABLE, "BNFT_TXT")],
        business_domain="Subscription",
        owner_group="dq-stewards-subscription",
        note=(
            "Registered so that its shadow rule names an element, as every rule must. "
            "Low: 75% blank is probably an optional field, which is exactly why the rule "
            "is still in shadow."),
    ),
]


def rule_cde_map() -> dict[str, str]:
    """rule_id -> cde_id for the rules tagged explicitly: the cross-table ones, whose
    target_column is NULL by design, and the two email-status rules, whose column is
    an attribute of the email element rather than an element of its own."""
    return {rid: c.cde_id for c in CDES for rid in c.explicit_rule_ids}


def cde_of(rule_id: str, target_table: str, target_column: str | None) -> str:
    """The element a rule names. Every rule names exactly one, since 2026-09-28:
    `config.rule_registry.cde_id` is NOT NULL and the check runner takes its
    worklist from the register, so a rule on no element is not a monitoring rule.

    The explicit tag wins; otherwise the bound column the rule targets. A rule that
    resolves to neither is refused here, on a laptop, rather than at the INSERT.
    """
    explicit = rule_cde_map()
    if rule_id in explicit:
        return explicit[rule_id]
    for c in CDES:
        for b in bindings_of(c):
            if b.target_table == target_table and b.target_column == target_column:
                return c.cde_id
    raise KeyError(
        f"{rule_id} targets {target_table}.{target_column}, which no registered element "
        "binds. Register the element first -- a rule names its element, never the "
        "other way round.")


def bindings_of(cde: CDE) -> list[Binding]:
    return [b for b in cde.bindings if b.binding_status == "bound"]

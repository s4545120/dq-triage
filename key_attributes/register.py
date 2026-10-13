"""The key attributes: what is registered, and where each one lives.

SOURCE. The in-scope rows of the '#1 - DQ Issues' sheet in DQ_ATTR_PRIORI.xlsx: every
row not marked "Out of scope". That leaves out table_e_addr_hist (secondary addresses,
out of scope per Albert), table_contact_ident_hist, cust_ctct_rel and
table_contact_role.is_primary_for_org. Definitions come from the sheet's CDQ comments
and from the migration-scope DQ analysis PDF.

TABLE NAMES. Everything is bound on prod.udp_brnz_nrt_tech_view.*, the views the
analysis queries read. The sheet names some rows on prod.udp_brnz_nrt.* instead, and
table_bus_org_hist PHONE as table_bus_org; same data, one name used here.

WHAT THE SHEET DOES NOT SAY, AND WHAT IS WRITTEN INSTEAD.
* Criticality. The register needs one, and the sheet gives no tiers. Every attribute
  is 'high', and it is the same value for all of them on purpose: a tier nobody
  decided should not reorder anything. Change it per attribute when the business
  ranks them.
* Tolerance. PLACEHOLDERS since 2026-10-13 (TOLERANCE below), chosen by the
  maintainer by attribute kind, not by the business: keys 0, record-making fields
  0.5, identity and validity dates 1.0, contact channels and external ids 2.0,
  optional or descriptive fields 5.0. They set each attribute's target and which
  breaches Triage holds back. Replace them per attribute when the business says how
  much failure each one can carry; every register version that carries them says so.
* PII. True for anything that identifies or reaches a person: names, phone, email,
  date of birth, address lines. Business identifiers and dates are false.
"""

from __future__ import annotations

from dataclasses import dataclass

SOURCE = "prod.udp_brnz_nrt_tech_view"
CONTACT = f"{SOURCE}.table_contact_hist"
ADDRESS = f"{SOURCE}.table_address_hist"
BUS_ORG = f"{SOURCE}.table_bus_org_hist"
CONTACT_ROLE = f"{SOURCE}.table_contact_role_hist"
CUSTOMER = f"{SOURCE}.table_customer_hist"

# The column that identifies one record of each table, for violation samples. History
# tables carry many versions of a record; see LATEST_RECORD_GAP.
ROW_KEY = {CONTACT: ["CONTACT_ID"], ADDRESS: ["OBJID"], BUS_ORG: ["OBJID"],
           CONTACT_ROLE: ["OBJID"], CUSTOMER: ["OBJID"]}
TABLE_CODE = {CONTACT: "KA_CONTACT", ADDRESS: "KA_ADDRESS", BUS_ORG: "KA_BUS_ORG",
              CONTACT_ROLE: "KA_CONTACT_ROLE", CUSTOMER: "KA_CUSTOMER"}
TABLE_DOMAIN = {CONTACT: "Contact", ADDRESS: "Address", BUS_ORG: "Account",
                CONTACT_ROLE: "Contact", CUSTOMER: "Account"}

# Said once, quoted by the migration and CLAUDE.md. Every analysis query scoped to
# migration_scope_flag = 1 and took the latest non-deleted version of each record.
# The runner can do neither yet, so a rule run on the raw history table counts every
# historical version, and a uniqueness check flags every record with two versions.
LATEST_RECORD_GAP = (
    "The analysis counted the latest non-deleted version of each record in migration "
    "scope (migration_scope_flag = 1). The check runner reads the whole history table, "
    "so its counts will be higher until the table gets a latest-record, migration-scope "
    "population.")

CRITICALITY = "high"
OWNER_GROUP = "dq-stewards-migration"
SHEET = "DQ_ATTR_PRIORI.xlsx '#1 - DQ Issues'"

# Placeholder tolerances, percent of rows checked that may fail (see the docstring).
# Keyed by cde_id; every attribute has one.
TOLERANCE: dict[str, float] = {
    "KA_CONTACT_CONTACT_ID": 0.0, "KA_BUS_ORG_ORG_ID": 0.0, "KA_CUSTOMER_CUSTOMER_ID": 0.0,
    "KA_CONTACT_FIRST_NAME": 0.5, "KA_CONTACT_LAST_NAME": 0.5,
    "KA_CONTACT_ROLE_ROLE_NAME": 0.5,
    "KA_CONTACT_BIRTH_DATE": 1.0, "KA_ADDRESS_EFF_DT": 1.0,
    "KA_CONTACT_E_MAIL": 2.0, "KA_CONTACT_PHONE": 2.0, "KA_BUS_ORG_X_ARBN": 2.0,
    "KA_ADDRESS_X_ADDRESS_ID": 2.0, "KA_ADDRESS_END_DT": 2.0,
    "KA_CONTACT_MIDDLE_NAME": 5.0, "KA_ADDRESS_X_SUB_ADDRESS_NUMBER": 5.0,
    "KA_ADDRESS_ADDRESS_3": 5.0, "KA_ADDRESS_ADDRESS_4": 5.0, "KA_BUS_ORG_PHONE": 5.0,
    "KA_BUS_ORG_X_NUMBER_OF_EMPLOYEE": 5.0, "KA_BUS_ORG_X_NUMBER_OF_OFFICE": 5.0,
    "KA_BUS_ORG_WEB_SITE": 5.0, "KA_BUS_ORG_ESTABLISH_DATE": 5.0,
}
TOLERANCE_NOTE = (
    "Placeholder tolerance, not business-approved: set by attribute kind (keys 0, "
    "record-making fields 0.5, identity and validity dates 1.0, contact channels and "
    "external ids 2.0, optional or descriptive fields 5.0). Replace when the business "
    "decides.")


@dataclass(frozen=True)
class KeyAttribute:
    cde_id: str
    name: str
    table: str
    column: str
    data_class: str
    definition: str
    pii: bool
    # Prose for a reader: when a value is expected at all.
    populated_when: str | None = None

    @property
    def domain(self) -> str:
        return TABLE_DOMAIN[self.table]


def _ka(table: str, column: str, name: str, data_class: str, definition: str,
        pii: bool, populated_when: str | None = None) -> KeyAttribute:
    prefix = TABLE_CODE[table]
    return KeyAttribute(f"{prefix}_{column}", name, table, column, data_class, definition,
                        pii, populated_when)


KEY_ATTRIBUTES: list[KeyAttribute] = [
    # --- Contact (table_contact_hist) -----------------------------------------------
    _ka(CONTACT, "FIRST_NAME", "Contact first name", "person_name",
        "The contact's given name as it will be migrated to Salesforce Contact.", True),
    _ka(CONTACT, "MIDDLE_NAME", "Contact middle name", "person_name",
        "The contact's middle name. Optional: NULL or blank is informational, not a defect.",
        True, "Only when the contact has a middle name."),
    _ka(CONTACT, "LAST_NAME", "Contact last name", "person_name",
        "The contact's family name as it will be migrated to Salesforce Contact.", True),
    _ka(CONTACT, "PHONE", "Contact phone", "phone_number",
        "The customer's phone number. Shared numbers and landlines are informational.",
        True),
    _ka(CONTACT, "E_MAIL", "Contact email", "email_address",
        "The contact's email address. Every migration-scope contact holds one.", True),
    _ka(CONTACT, "BIRTH_DATE", "Contact date of birth", "date_of_birth",
        "Date of birth, stored by BCC as epoch milliseconds; 0 means missing.", True),
    _ka(CONTACT, "CONTACT_ID", "Jarvis contact ID", "account_id",
        "The Jarvis contact identifier: populated, numeric and unique.", False),
    # --- Contact role (table_contact_role_hist) ---------------------------------------
    _ka(CONTACT_ROLE, "ROLE_NAME", "Contact role name", "other",
        "The contact's role in a contact-role relationship, such as an account or "
        "service relationship. Expected value: Default.", False),
    # --- Address (table_address_hist) -------------------------------------------------
    _ka(ADDRESS, "EFF_DT", "Address active from date", "other",
        "Effective-from date of the address record, epoch milliseconds.", False),
    _ka(ADDRESS, "END_DT", "Address active to date", "other",
        "Effective-to date of the address record, epoch milliseconds. NULL when open.",
        False, "When the address record has ended."),
    _ka(ADDRESS, "X_ADDRESS_ID", "G-NAF address ID", "other",
        "G-NAF persistent identifier of the Australian address. Nullable.", False,
        "When the address has been matched to G-NAF."),
    _ka(ADDRESS, "X_SUB_ADDRESS_NUMBER", "Sub-address number", "other",
        "Unit, flat, apartment or suite within a multi-tenanted property. Optional.", True,
        "Only for a multi-tenanted property."),
    _ka(ADDRESS, "ADDRESS_3", "Address line 3", "other",
        "Overflow address detail not held in the structured fields: building, floor, "
        "locality or international detail.", True, "Only when there is overflow detail."),
    _ka(ADDRESS, "ADDRESS_4", "Address line 4", "other",
        "Further overflow beyond line 3. Blank when there is nothing more.", True,
        "Only when line 3 overflows."),
    # --- Business organisation (table_bus_org_hist) -----------------------------------
    _ka(BUS_ORG, "PHONE", "Business phone", "phone_number",
        "The organisation's phone number.", True),
    _ka(BUS_ORG, "X_NUMBER_OF_EMPLOYEE", "Number of employees", "other",
        "Employee count, a whole number. Zero is accepted but may mean unknown.", False),
    _ka(BUS_ORG, "X_NUMBER_OF_OFFICE", "Number of offices", "other",
        "Number of locations, a positive whole number.", False),
    _ka(BUS_ORG, "WEB_SITE", "Website", "other",
        "The organisation's website, with protocol. NULL when it has none.", False,
        "When the organisation has a website."),
    _ka(BUS_ORG, "ESTABLISH_DATE", "Year started", "other",
        "Establishment date, epoch milliseconds.", False),
    _ka(BUS_ORG, "X_ARBN", "ARBN", "other",
        "Australian Registered Body Number: nine digits. Rarely populated.", False,
        "Only for a registered foreign or body-corporate organisation."),
    _ka(BUS_ORG, "ORG_ID", "Jarvis organisation ID", "account_id",
        "The Jarvis organisation identifier: populated, numeric and unique.", False),
    # --- Customer (table_customer_hist) -----------------------------------------------
    _ka(CUSTOMER, "CUSTOMER_ID", "Jarvis customer ID", "account_id",
        "The Jarvis customer identifier: populated, numeric and unique.", False),
]

BY_ID = {a.cde_id: a for a in KEY_ATTRIBUTES}
assert set(TOLERANCE) == set(BY_ID), set(TOLERANCE) ^ set(BY_ID)
TABLES = sorted({a.table for a in KEY_ATTRIBUTES})


def attribute_of(table: str, column: str) -> KeyAttribute:
    for a in KEY_ATTRIBUTES:
        if a.table == table and a.column == column:
            return a
    raise KeyError(f"No key attribute binds {table}.{column}.")

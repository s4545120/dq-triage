"""A mock CRM lead table: a "new source system" the existing registry has never seen.

Every column is chosen to exercise one discovery path, and every defect is planted at
a known count so the first check run can be read against this file:

| Column        | Discovery it tests                                              |
|---------------|-----------------------------------------------------------------|
| LEAD_ID       | UC tag. Seven elements share its `^\\d{7}$` signature           |
| GIVEN_NAME    | UC tag. A person name has no signature to find it by            |
| FAMILY_NAME   | UC tag                                                          |
| EMAIL         | Value signature, unique match (email) above the threshold       |
| HOME_PHONE    | Value signature, unique match (landline: 0 but not 04)          |
| MOBILE        | UC tag. Its values match three elements' signatures             |
| BIRTH_TS      | UC tag. Shares a timestamp signature with two other elements    |
| CREATED_TS    | Nothing. Ambiguous signature and no tag: must stay unbound      |
| ORDER_REF     | Nothing. Seven-digit, no tag: the false positive to avoid       |
| CONTACT_INFO  | Nothing. Half emails, half phones: a near miss below threshold  |
| STATUS, NOTES | Nothing                                                         |

Deterministic: the same seed writes the same 1000 rows.
"""

from __future__ import annotations

import random

ROWS = 1000
SEED = 20261005
COLUMNS = ["LEAD_ID", "GIVEN_NAME", "FAMILY_NAME", "EMAIL", "HOME_PHONE", "MOBILE",
           "BIRTH_TS", "CREATED_TS", "ORDER_REF", "CONTACT_INFO", "STATUS", "NOTES"]

# Which element each tagged column belongs to. Applied as UC column tags, key `cde`.
TAGS = {
    "LEAD_ID": "CDE_CUST_KEY",
    "GIVEN_NAME": "CDE_CUST_NAME",
    "FAMILY_NAME": "CDE_CUST_NAME",
    "MOBILE": "CDE_CUST_MOBILE",
    "BIRTH_TS": "CDE_CUST_DOB",
}

GIVEN = ["Olivia", "Jack", "Mia", "Noah", "Ava", "Leo", "Isla", "Oliver", "Grace", "Lucas",
         "Chloe", "Henry", "Zoe", "Thomas", "Ruby", "Mei", "Arjun", "Siobhan", "Jean-Luc"]
FAMILY = ["Smith", "Nguyen", "Brown", "Wilson", "Taylor", "Patel", "Kelly", "O'Brien",
          "Chen", "Martin", "Singh", "Walker", "Rossi", "Murphy", "Lee", "Van der Berg"]

# Planted defects, by count. The first check run should find each of these.
PLANTED = {
    "GIVEN_NAME blank": 15,
    "GIVEN_NAME placeholder (TEST/UNKNOWN)": 8,
    "GIVEN_NAME with a title (Mr/Mrs)": 12,
    "FAMILY_NAME company (PTY LTD)": 5,
    "EMAIL blank": 20,
    "EMAIL malformed": 25,
    "HOME_PHONE placeholder (0200000000)": 6,
    "HOME_PHONE with letters": 4,
    "MOBILE placeholder (0400000000)": 9,
    "BIRTH_TS in the future": 7,
    "BIRTH_TS default date (1900-01-01)": 10,
    "LEAD_ID duplicated (pairs)": 4,
}


def rows() -> list[dict]:
    rnd = random.Random(SEED)
    out = []
    for i in range(ROWS):
        g, f = rnd.choice(GIVEN), rnd.choice(FAMILY)
        y, m, d = rnd.randint(1945, 2005), rnd.randint(1, 12), rnd.randint(1, 28)
        cy, cm, cd = rnd.randint(2023, 2026), rnd.randint(1, 9), rnd.randint(1, 28)
        out.append(dict(
            LEAD_ID=str(7100000 + i),
            GIVEN_NAME=g, FAMILY_NAME=f,
            EMAIL=f"{g.lower().replace('-', '')}.{f.lower().replace(' ', '').replace(chr(39), '')}{i}@example.com",
            HOME_PHONE=(f"0{rnd.choice('2378')}{rnd.randint(10000000, 99999999)}"
                        if rnd.random() < 0.6 else ""),
            MOBILE=f"04{rnd.randint(10000000, 99999999)}",
            BIRTH_TS=f"{y:04d}-{m:02d}-{d:02d} 00:00:00",
            CREATED_TS=f"{cy:04d}-{cm:02d}-{cd:02d} {rnd.randint(0, 23):02d}:{rnd.randint(0, 59):02d}:00",
            ORDER_REF=str(rnd.randint(1000000, 9999999)),
            CONTACT_INFO=(f"{g.lower()}{i}@example.com" if i % 2 else f"04{rnd.randint(10000000, 99999999)}"),
            STATUS=rnd.choice(["NEW", "CONTACTED", "QUALIFIED", "LOST"]),
            NOTES=rnd.choice(["", "", "call back after 5pm", "prefers email", "met at expo"]),
        ))

    # Defects go into disjoint row ranges so every planted count is exact.
    def span(start: int, n: int):
        return range(start, start + n)

    for i in span(0, 15):
        out[i]["GIVEN_NAME"] = ""
    for k, i in enumerate(span(15, 8)):
        out[i]["GIVEN_NAME"] = "TEST" if k % 2 else "UNKNOWN"
    for k, i in enumerate(span(23, 12)):
        out[i]["GIVEN_NAME"] = ("Mr " if k % 2 else "Mrs ") + out[i]["GIVEN_NAME"]
    for i in span(40, 5):
        out[i]["FAMILY_NAME"] = "Acme Leads PTY LTD"
    for i in span(100, 20):
        out[i]["EMAIL"] = ""
    for k, i in enumerate(span(120, 25)):
        out[i]["EMAIL"] = ["no-at-sign.example.com", "two@@example.com", "trailing.dot@example.",
                           "space in@example.com", "@example.com"][k % 5]
    # HOME_PHONE: only rows that already hold a number, so blanks stay blank.
    filled = [i for i in range(200, ROWS) if out[i]["HOME_PHONE"]]
    for i in filled[:6]:
        out[i]["HOME_PHONE"] = "0200000000"
    for i in filled[6:10]:
        out[i]["HOME_PHONE"] = "02 CALL ME"
    for i in span(300, 9):
        out[i]["MOBILE"] = "0400000000"
    for i in span(400, 7):
        out[i]["BIRTH_TS"] = "2027-03-01 00:00:00"
    for i in span(410, 10):
        out[i]["BIRTH_TS"] = "1900-01-01 00:00:00"
    for k in range(4):
        out[500 + k]["LEAD_ID"] = out[600 + k]["LEAD_ID"]
    return out

# What notebook 03 sends to the triage model — masked

Generated 2026-10-21 by running notebook 03's read cells against `workspace.dq_triage`,
up to the brief and no further: no model call and no write. Run `ceb5dbf3-a6f1-4325-ae67-21cbede9b0d4`
(2026-10-20 16:00:18 UTC, the 03:00 Sydney run of 2026-10-21). **17 briefs, 0 refused by
the leak check.** An independent scan of every sent brief for 692 real names (rule ids
and names, tables, source columns, element ids, names and definitions, owner groups,
domains, steward names and reasons, problem ids, playbook ids and owners) found none.
The one string it matched, `email_address`, is the data class, kept on purpose.

## 1 · Field by field

| Field in the brief | Real value (from this run) | Sent to the model | How |
|---|---|---|---|
| Table | `workspace.udp_brnz_nrt_tech_view.table_contact_hist` | `TABLE_1` | placeholder |
| Column | `FIRST_NAME`, `STATUS` | `COLUMN_1`, `COLUMN_2` | placeholder, same inside expressions |
| Rule id | `KA_CONTACT_FIRST_NAME_PLACEHOLDER_VALUE` | `RULE_1` | placeholder |
| Rule name | `First name is not a placeholder` | `sentinel check on COLUMN_1` | rebuilt from rule type and column |
| Rule expression | `upper(trim(cast(FIRST_NAME AS STRING))) IN ('N/A', 'NONE', …)` | `upper(trim(cast(COLUMN_1 AS STRING))) IN ('VALUE_1', 'VALUE_2', …)` | columns and word-like literals masked, SQL kept |
| Regex literal | `'^[^\\p{L}]'` | `'^[^\\p{L}]'` | kept: a shape, not a business value |
| Scope filter | `FIRST_NAME IS NOT NULL AND trim(…) <> ''` | `COLUMN_1 IS NOT NULL AND trim(…) <> ''` | as an expression |
| Cross-table alias | `pa.CONTACT_ID IS NULL` | `pa.COLUMN_1 IS NULL` | alias of ≤ 3 letters kept, longer ones become `ALIAS_n` |
| Owner group | `dq-stewards-migration` | `TEAM_2` | placeholder |
| Business domain | `Contact` | `DOMAIN_1` | placeholder |
| Element id | `KA_CONTACT_FIRST_NAME` | `ELEMENT_1` | placeholder |
| Element name | `Contact first name` | `person_name element` | rebuilt from data class |
| Element definition | `The contact's given name as it will be migrated to Salesforce Contact.` | `(withheld)` | withheld |
| Regulatory basis | (none on this register) | `(withheld)` when present | withheld |
| Prior problem id | `b7df63fe-02b8-52b9-ab79-16e4b0902489` | `PROBLEM_1` | placeholder |
| Steward name / reason | (none on today's priors) | `PERSON_1` / `(withheld)` | placeholder / withheld |
| Playbook id | `PB_UPSTREAM_SOURCE_RELEASE` | `PLAYBOOK_1` | placeholder |
| Playbook typical owner | `CRM Platform Team` | `TEAM_1` | placeholder |
| Playbook name and guidance | method text | kept, with any known name inside masked | the system's own guidance |
| Grouping basis | `shared rows: KA_CONTACT_FIRST_NAME_CONSECUTIVE_PUNCTUATION and …` | `shared rows: RULE_1 and RULE_4 …` | names inside masked |
| Counts, %, dates, severity, status, criticality, PII flag, tolerance, data class, lifecycle state, approach type, coverage finding | as stored | as stored | system vocabulary, not business |

Placeholders are numbered per brief: `TABLE_1` in one brief and `TABLE_1` in the next
are unrelated, so briefs cannot be lined up against each other. The key stays in the run;
the answer is unmasked with it before `validate`, so `results.cohort` holds real names.

## 2 · Every brief on this run

| First rule | Rules | Tables | Columns | Aliases | Rules masked | Elements | Problems | Playbooks | Teams | Domains | People | Values | Withheld texts | Chars sent |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| `KA_CONTACT_FIRST_NAME_CONSECUTIVE_PUNCTUATION +5` | 6 | 1 | 1 |  | 6 | 1 | 1 | 1 | 2 | 1 |  |  | 8 | 6,580 |
| `CS_07E5AEE5` | 1 | 1 | 1 |  | 1 | 1 | 1 |  | 1 | 1 |  |  | 3 | 2,920 |
| `KA_CONTACT_CONTACT_ID_NOT_NULL` | 1 | 1 | 1 |  | 1 | 1 | 1 | 2 | 3 | 1 |  |  | 3 | 3,919 |
| `KA_CONTACT_CONTACT_ID_NUMERIC` | 1 | 1 | 1 |  | 1 | 1 | 1 | 1 | 2 | 1 |  |  | 3 | 3,526 |
| `KA_CONTACT_CONTACT_ID_UNIQUE` | 1 | 1 | 1 |  | 1 | 1 |  |  | 1 | 1 |  |  | 3 | 2,689 |
| `KA_CONTACT_E_MAIL_INVALID_GENERIC` | 1 | 1 | 1 |  | 1 | 1 |  |  | 1 | 1 |  |  | 3 | 2,654 |
| `KA_CONTACT_E_MAIL_INVALID_MALFORMED` | 1 | 1 | 1 |  | 1 | 1 | 1 | 1 | 2 | 1 |  |  | 3 | 3,817 |
| `KA_CONTACT_E_MAIL_INVALID_OPTUS_GENERATED` | 1 | 1 | 1 |  | 1 | 1 | 1 |  | 1 | 1 |  |  | 3 | 2,978 |
| `KA_CONTACT_E_MAIL_NULL_OR_BLANK` | 1 | 1 | 1 |  | 1 | 1 | 1 | 2 | 3 | 1 |  |  | 3 | 3,923 |
| `KA_CONTACT_FIRST_NAME_COMPANY_NAME_INDICATOR` | 1 | 1 | 1 |  | 1 | 1 | 1 | 1 | 2 | 1 |  |  | 3 | 3,563 |
| `KA_CONTACT_FIRST_NAME_DECEASED_WITHOUT_ESTATE_NAME` | 1 | 1 | 2 |  | 1 | 1 | 1 | 1 | 2 | 1 |  | 2 | 3 | 3,422 |
| `KA_CONTACT_FIRST_NAME_ESTATE_NAME_NOT_DECEASED` | 1 | 1 | 2 |  | 1 | 1 |  | 1 | 2 | 1 |  | 2 | 3 | 3,127 |
| `KA_CONTACT_FIRST_NAME_EXCEEDS_40_CHARACTERS` | 1 | 1 | 1 |  | 1 | 1 |  | 1 | 2 | 1 |  |  | 3 | 3,219 |
| `KA_CONTACT_FIRST_NAME_LEADING_OR_TRAILING_WHITESPACE` | 1 | 1 | 1 |  | 1 | 1 | 1 | 1 | 2 | 1 |  |  | 3 | 3,529 |
| `KA_CONTACT_FIRST_NAME_NULL_OR_BLANK` | 1 | 1 | 1 |  | 1 | 1 | 1 | 2 | 3 | 1 |  |  | 3 | 3,930 |
| `KA_CONTACT_FIRST_NAME_PLACEHOLDER_VALUE` | 1 | 1 | 1 |  | 1 | 1 |  |  | 1 | 1 |  | 13 | 3 | 2,790 |
| `KA_CONTACT_FIRST_NAME_STARTS_WITH_TITLE` | 1 | 1 | 1 |  | 1 | 1 | 1 | 1 | 2 | 1 |  |  | 3 | 3,548 |
| **Total** | 22 | 17 | 19 | 0 | 22 | 17 | 12 | 15 | 32 | 17 | 0 | 17 | 56 | |

"Withheld texts" counts rule names, element names and definitions, and steward reasons
replaced or removed. A brief's "Rules masked" would exceed its "Rules" where a prior
problem or a playbook names a rule outside the group; none does on this run.

## 3 · Expressions with literals: real and sent

**The deceased-contact rule**

```text
REAL
  Rule KA_CONTACT_FIRST_NAME_DECEASED_WITHOUT_ESTATE_NAME - A deceased contact's first name reads ESTATE OF THE LATE
    target     : workspace.udp_brnz_nrt_tech_view.table_contact_hist.FIRST_NAME
    expression : cast(STATUS AS STRING) = '5' AND coalesce(upper(trim(cast(FIRST_NAME AS STRING))), '') NOT LIKE '%ESTATE OF THE LATE%'
    scope      : (none - the rule is applied to every row of the table)
    element    : KA_CONTACT_FIRST_NAME

SENT
  Rule RULE_1 - consistency check on COLUMN_1
    target     : TABLE_1.COLUMN_1
    expression : cast(COLUMN_2 AS STRING) = 'VALUE_1' AND coalesce(upper(trim(cast(COLUMN_1 AS STRING))), '') NOT LIKE 'VALUE_2'
    scope      : (none - the rule is applied to every row of the table)
    element    : ELEMENT_1
```

Key (stays in the run): `VALUE_1` = `'5'`, `VALUE_2` = `'%ESTATE OF THE LATE%'`.

**The placeholder-name rule**

```text
REAL
  Rule KA_CONTACT_FIRST_NAME_PLACEHOLDER_VALUE - First name is not a placeholder
    target     : workspace.udp_brnz_nrt_tech_view.table_contact_hist.FIRST_NAME
    expression : upper(trim(cast(FIRST_NAME AS STRING))) IN ('N/A', 'NONE', 'NULL', 'UNKNOWN', 'NOT APPLICABLE', 'NOT PROVIDED', 'TBC', 'TBD', 'TEST', 'DUMMY', 'SAMPLE', 'UNDEFINED', 'NOT AVAILABLE')
    scope      : FIRST_NAME IS NOT NULL AND trim(cast(FIRST_NAME AS STRING)) <> ''
    element    : KA_CONTACT_FIRST_NAME

SENT
  Rule RULE_1 - sentinel check on COLUMN_1
    target     : TABLE_1.COLUMN_1
    expression : upper(trim(cast(COLUMN_1 AS STRING))) IN ('VALUE_1', 'VALUE_2', 'VALUE_3', 'VALUE_4', 'VALUE_5', 'VALUE_6', 'VALUE_7', 'VALUE_8', 'VALUE_9', 'VALUE_10', 'VALUE_11', 'VALUE_12', 'VALUE_13')
    scope      : COLUMN_1 IS NOT NULL AND trim(cast(COLUMN_1 AS STRING)) <> ''
    element    : ELEMENT_1
```

The model now sees an `IN` list of thirteen values without knowing they are `N/A`,
`UNKNOWN`, `TEST` and so on. That is the cost of masking values: it reads that the column
is compared with a fixed list, not that the list is placeholders.

## 4 · One full brief, exactly as sent

The largest group on this run: six first-name format rules.

```text
Triage the following group of data quality breaches.

GROUP
-----
Raised      : 2026-10-20 16:00:18
Grouped by  : shared rows: RULE_1 and RULE_4 fail on 6 of the same records (100% of the smaller sample); shared rows: RULE_3 and RULE_4 fail on 12 of the same records (100% of the smaller sample)
Severity    : P2_alert   Domain: DOMAIN_1   Owner group: TEAM_2
Members     : 6 rules, 156 violating rows summed
Tables      : TABLE_1
Recurrence  : False (the triage job's assertion, computed from the register)

MEMBER RULES AND THEIR EVIDENCE
-------------------------------
  Rule RULE_1 - format check on COLUMN_1
    type       : format   severity: P3_monitor   status: active
    target     : TABLE_1.COLUMN_1
    expression : trim(cast(COLUMN_1 AS STRING)) RLIKE '\\p{P}{2,}'
    scope      : COLUMN_1 IS NOT NULL AND trim(cast(COLUMN_1 AS STRING)) <> ''
    element    : ELEMENT_1
    latest run : 6 violations of 3579 rows scanned
                 (0.168%, threshold 0.0%)
    history    : has never passed in 12 runs
                 violation count on the last 8 runs: [6, 6, 6, 6, 6, 6, 6, 6]
  Rule RULE_2 - format check on COLUMN_1
    type       : format   severity: P3_monitor   status: active
    target     : TABLE_1.COLUMN_1
    expression : cast(COLUMN_1 AS STRING) RLIKE '\\p{Cc}'
    scope      : COLUMN_1 IS NOT NULL AND trim(cast(COLUMN_1 AS STRING)) <> ''
    element    : ELEMENT_1
    latest run : 33 violations of 3579 rows scanned
                 (0.922%, threshold 0.0%)
    history    : has never passed in 12 runs
                 violation count on the last 8 runs: [33, 33, 33, 33, 33, 33, 33, 33]
  Rule RULE_3 - format check on COLUMN_1
    type       : format   severity: P2_alert   status: active
    target     : TABLE_1.COLUMN_1
    expression : trim(cast(COLUMN_1 AS STRING)) RLIKE '^[-\\x27\\x{2019}]|[-\\x27\\x{2019}]$'
    scope      : COLUMN_1 IS NOT NULL AND trim(cast(COLUMN_1 AS STRING)) <> ''
    element    : ELEMENT_1
    latest run : 12 violations of 3579 rows scanned
                 (0.335%, threshold 0.0%)
    history    : has never passed in 12 runs
                 violation count on the last 8 runs: [12, 12, 12, 12, 12, 12, 12, 12]
  Rule RULE_4 - format check on COLUMN_1
    type       : format   severity: P2_alert   status: active
    target     : TABLE_1.COLUMN_1
    expression : trim(cast(COLUMN_1 AS STRING)) NOT RLIKE '^\\p{L}+([\\p{Zs}\\x27\\x{2019}-]\\p{L}+)*$'
    scope      : COLUMN_1 IS NOT NULL AND trim(cast(COLUMN_1 AS STRING)) <> ''
    element    : ELEMENT_1
    latest run : 65 violations of 3579 rows scanned
                 (1.816%, threshold 0.0%)
    history    : has never passed in 12 runs
                 violation count on the last 8 runs: [65, 65, 65, 65, 65, 65, 65, 65]
  Rule RULE_5 - format check on COLUMN_1
    type       : format   severity: P2_alert   status: active
    target     : TABLE_1.COLUMN_1
    expression : trim(cast(COLUMN_1 AS STRING)) RLIKE '^[^\\p{L}]'
    scope      : COLUMN_1 IS NOT NULL AND trim(cast(COLUMN_1 AS STRING)) <> ''
    element    : ELEMENT_1
    latest run : 26 violations of 3579 rows scanned
                 (0.727%, threshold 0.0%)
    history    : has never passed in 12 runs
                 violation count on the last 8 runs: [26, 26, 26, 26, 26, 26, 26, 26]
  Rule RULE_6 - format check on COLUMN_1
    type       : format   severity: P2_alert   status: active
    target     : TABLE_1.COLUMN_1
    expression : trim(cast(COLUMN_1 AS STRING)) RLIKE '(?i)(^|\\s)(C/O|CARE OF|PO BOX|UNIT|SUITE|LEVEL|FLOOR|STREET|ROAD|AVENUE|DRIVE|HIGHWAY|POSTCODE|SUBURB|NOTE|NOTES)(\\s|:|$)' OR trim(cast(COLUMN_1 AS STRING)) RLIKE '(@|https?://|www\\.)'
    scope      : COLUMN_1 IS NOT NULL AND trim(cast(COLUMN_1 AS STRING)) <> ''
    element    : ELEMENT_1
    latest run : 14 violations of 3579 rows scanned
                 (0.391%, threshold 0.0%)
    history    : has never passed in 12 runs
                 violation count on the last 8 runs: [14, 14, 14, 14, 14, 14, 14, 14]

PRIOR DECISIONS ON THESE RULES
------------------------------

  Cohort PROBLEM_1 - raised 2026-10-13, covers 6 of this group's rules
    current state  : awaiting_triage
    rules covered  : RULE_1, RULE_2, RULE_3, RULE_4, RULE_5, RULE_6
    advised then   : upstream_ticket
    approach taken : (none executed)
    outcome        : not executed
    reopened       : 0 time(s)
    event chain    : 
    steward notes  :
      (no reasons recorded)

REGISTERED CRITICAL DATA ELEMENTS TOUCHED
-----------------------------------------

  ELEMENT_1 - person_name element  (person_name, criticality high, PII True)
    definition            : (withheld)
    regulatory basis      : None
    expected scope filter : (none declared)
    declared tolerance    : 0.5% of rows in scope may violate
    coverage findings     : ['covered', 'no_rule']

PLAYBOOK CANDIDATES
-------------------

  PLAYBOOK_1 - Raise upstream ticket against the source release   [upstream_ticket]
    applies to    : rule type format
    typical owner : TEAM_1
    used before   : 3 times, recurrence rate 0.0
    guidance      : Where a defect starts on a date that matches a source-system release, the correction belongs in that system. Raise a ticket against the release, attach the cohort's before/after counts, and hold the cohort open until the source ships. Do NOT correct the warehouse copy: while the source keeps emitting bad rows the warehouse would disagree with the system of record, which the spec rules out explicitly.

HOW THIS GROUP WAS FORMED
-------------------------
These checks were grouped by a mechanical rule over the run history alone - no judgement
about what the data means was applied, and no cause has been asserted. The grouping is a
proposal for you to test. If the evidence does not support one cause across these
members, say so and name the members it does not cover. Member violation counts are
summed and may double-count where two checks fail on the same rows.

TASK
----
State what these rules have in common and whether one cause explains all of them.

Read the prior decisions before recommending anything. If an approach has already been
taken, say what happened to it and whether the evidence supports repeating it.

Infer the most plausible root cause hypothesis using only the supplied evidence. Decide
whether the defect is in the data or in the rule.

Recommend one approach and the owner best placed to carry it out. Adopt a playbook
candidate if one genuinely fits; otherwise draft one and label it generated.

Return only the requested JSON object.
```

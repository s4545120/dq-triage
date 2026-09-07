# Local fixtures — a complete `dq.*` dataset from the two pilot CSVs

Step 2 of the build plan. Turns `mock_subs_c_1000.csv` and `mock_ctct_c_1000.csv` into
every table the app reads, as Parquet, on a laptop. No Databricks, no network.

```bash
python3 -m venv ../.venv && ../.venv/bin/pip install pandas pyarrow
../.venv/bin/python build_fixtures.py     # writes out/
../.venv/bin/python verify.py             # integrity gate, exits non-zero on a finding
```

Deterministic: same inputs, same uuids, same output, every run. Safe to regenerate.

| File | What it is |
|---|---|
| `rules.py` | 34 rules. SQL `rule_expr` for Databricks + a Python evaluator for here. The two must agree. |
| `build_fixtures.py` | Evaluates the rules, back-projects 40 daily runs, writes cohorts and the register. |
| `verify.py` | Python twin of `v_disposition_integrity`, plus fixture-consistency assertions. |
| `out/*.parquet` | One file per table, named `<schema>.<table>.parquet`. |

## What is real and what is synthesised

This is the part to read before quoting any number from `out/`.

**Real — derived from the CSVs:**
- every `violation_count` and `rows_scanned` on the final run;
- every `violation_sample` row — actual bad rows with actual bad values
  (`alex.adams0001 hotmail.com`, `service-number-unknown`, `31-02-1988`);
- which rules pass and which breach;
- **every number in `results.cde_profile`** — the null and blank rates, cardinality,
  length ranges, masked signature distributions and signature match rates are computed
  over the CSVs by `profile.py`, with the binding's scope filter applied. Nothing in
  the profile is back-projected or hand-written;
- **every row of `results.v_cde_coverage`**, which is derived from the register, the
  rule registry and the final run.

**Synthesised — because one snapshot cannot contain it:**
- the preceding 39 daily runs (see *History*, below);
- every cohort, hypothesis and recommendation. On Databricks these come from the triage
  job's model endpoints. Here they are hand-written from what profiling actually found,
  so the text is defensible — but no model produced it, `recommendation_source` says so,
  and `model_input_payload` is a stub;
- every disposition event and the identities on it;
- **the CDE register itself** (`config.cde_registry`). Which fields are critical, at
  what tier and on what regulatory basis, is a business judgement, and here it is one
  person's — see `cdes.py`. The *bindings* are hand-authored too, which is what
  `discovered_by = 'manual'` on all twelve of them means: the classification sweep that
  would propose them from column names, value signatures and lineage does not exist yet.

**Deliberately *not* synthesised:** violation samples for back-projected breaches.
Fabricating evidence rows for a breach that never happened is the one shortcut worth
refusing, so historical runs carry a count, no samples, and say so in `message`.

## What the rules found

The pilot data holds **240 defective email addresses in six exact buckets of 40** — `@`
replaced by a space, `@` dropped entirely, whitespace in the local part, missing TLD,
doubled dots, trailing dot. That is a formatter emitting six variants, not 240 people
mistyping, and it is the evidence behind the flagship cohort.

Other real defects: 12 mobile services carrying the literal `service-number-unknown`;
14 contacts with the identical impossible date `31-02-1988` in DD-MM-YYYY where every
other row is ISO; 27 contacts aged 17; 18 missing mobiles; 24 malformed landlines; 16
missing network technologies; a vulnerable-customer flag that is `N` on all 1000 rows.

### The trap, and why it earns its own cohort

Four apparent defects are legitimate product variation:

| Looks broken | Rows | Actually |
|---|---|---|
| `IMEI_ID` / `SIM_SERL_ID` blank | 200 | Fixed Broadband — no handset, no SIM |
| `PROD_TYPE_KEY = 0` | 200 | the same Fixed Broadband rows |
| `PRIM_ACCT_KEY = 0` | 500 | prepaid — no billing account |
| `PRIM_RSRC_VALU_TXT` not `04########` | 200 | Fixed Broadband service IDs, correct for their type |

`SUBS_IMEI_NOT_NULL` and `SUBS_PRIM_ACCT_NOT_ZERO` are **left unscoped on purpose** and
report 700 false breaches between them. Their correctly-scoped twins on the same data —
`SUBS_SIM_NOT_NULL`, `SUBS_BILL_OFFR_NOT_ZERO` — return zero. That pair is cohort COH-B,
whose root cause is a rule defect rather than a data defect and whose correct disposition
is `rejected`. Do not "fix" those two rules; the fixture needs them broken.

## History

The CSVs are one point in time, so the 39 earlier runs are back-projected on four
profiles, all in `build_fixtures.py`:

- **incident** — the nine COH-A rules are clean through 2026-08-27 and breach together
  from 2026-08-28, the date of the notional CRM export change;
- **chronic** — holds roughly steady; nobody has touched these;
- **fixed** — seven rules that pass today are given a plausible history of having been
  broken and fixed. This group is the only reason closure rate and MTTR have a
  denominator at all;
- **recurred** — `CTCT_PHN_FMT` was closed, verified, and broke again 13 days later. The
  spec calls recurrence *"the primary signal of root-cause versus symptom"*, so the
  fixture has to contain one or the metric is untestable.

## The fourteen cohorts

Six current, eight historical. Between them they hit **every branch** of
`v_cohort_current`'s state expression, so no UI state is unreachable:

| | Rules | Severity | State | Exercises |
|---|---|---|---|---|
| COH-A | 9 | P1 | `reopened` | two distinct approvers, then a **failed** verification |
| COH-B | 2 | P3 | `closed_rejected` | rejection with a reason; root cause is a rule defect |
| COH-C | 2 | P1 | `closed_verified` | the full happy path |
| COH-D | 3 | P2 | `deferred` | deferral with a review-by date; flagged as a recurrence |
| COH-E | 2 | P3 | `approved_awaiting_execution` | a **generated** recommendation, no playbook match |
| COH-F | 3 | P2 | `awaiting_review` | no disposition yet — the coverage metric's denominator |
| HIST-1…8 | 1 each | mixed | `closed_verified` | MTTR, closure rate, recurrence |

## What the fixture scores against the spec's own targets

```
Cohort compression         3.5:1   [>=5:1]   21 breaches on the final run into 6 cohorts
Disposition coverage      92.9%    [>=90%]
Recommendation accepted   90.0%    [>=50%]   9 of 10 executed cohorts followed the advice
Closure rate              64.3%    [>=75%]
MTTR (verified closed)     5.4d    [<5d P1, <15d P2]
Recurrence                1 cohort [<10% at 30d]
```

**Compression misses the target, and should not be tuned to hit it.** 3.5:1 is a property
of the pilot, not of the grouping: the spec's ≥5:1 assumes something like its worked
example of 30 breaches across 12 tables, and this dataset has two tables. COH-A on its own
compresses 9 breaches into 1. Re-measure once more tables are onboarded; changing the
clustering to make two tables look like twelve would only make the metric lie.

Closure rate misses too, at 64.3%, because six cohorts are still open — which is what an
in-flight queue looks like.

## Testing the control test

```bash
../.venv/bin/python build_fixtures.py --inject-control-failure --out out_bad
../.venv/bin/python verify.py out_bad     # exits 1: insufficient_distinct_approvers
```

The injection rewrites COH-A's second approval so both come from the same identity.
Adding a *third* approval row would not breach anything — the control is on distinct
identities, not row count, and that distinction is exactly what the test exists to catch.

## What profiling found on its own

`results.cde_profile` describes the twelve bound columns without asserting anything
about them, and two defects fall out of the description before any rule is consulted.

**Date of birth carries two shapes.** 986 values are `9{4}-9{2}-9{2}_9{2}:9{2}:9{2}` and
14 are `9{2}-9{2}-9{4}` — DD-MM-YYYY where everything else is ISO. The minority signature
*is* the `CTCT_BRTH_PARSEABLE` breach, visible as a shape rather than as a verdict.

**The landline column contains letters.** 976 values are `9{10}`, and 24 are
`9{2}X{3}9{5}`. That is `CTCT_PHN_FMT`, described rather than judged.

The email column is the useful counter-example. Its 217 distinct shapes are dominated by
name-length variation, so no single signature is informative — but `signature_match_pct`
is 75.98%, which on 999 populated values is exactly the 240 addresses `CTCT_EML_FMT`
reports. The expected signature in `cdes.py` is deliberately the same expression as that
rule, so the profile and the verdict agree to the row instead of differing by 80 with
nothing to explain the gap.

Signatures are masked shapes, never values: digits become `9`, letters `X`, whitespace
`_`, punctuation survives, and runs collapse to a class and a length. For an element
flagged `pii`, shapes seen on fewer than five rows are folded into a `<rare>` bucket that
keeps the count and discards the shape — 30% of the email column ends up there, and both
defects above survive the threshold comfortably.

## Limitations

- **No volume history.** `rows_scanned` is constant across all 40 runs, so
  `volume_anomaly` and freshness rules cannot be demonstrated. Two tables at 1000 rows.
- **`scope_fingerprint` is `NULL` everywhere** — the open engineering question about
  pinning verification scope. Verification here matches on `rule_id` + `target_table`.
- **Blast radius is invented.** Real values come from Unity Catalog lineage, which does
  not exist locally. The named downstream tables are plausible, not observed.
- **Identities are synthetic**, on `example.com`. On Databricks every one arrives from
  `x-forwarded-access-token` and cannot be typed in.
- **CDE criticality tiers are one person's judgement.** They are a starting point for a
  conversation with the business, not an agreed taxonomy. Addendum A lists it as an open
  question.
- **No CDE has zero rules**, so the `no_rule` coverage finding is unexercised in this
  fixture — the twelve bound columns all attract at least one rule. `scope_mismatch`,
  `unvalidated` and `covered` all occur and are asserted by the app's conformance test.
- **The CSVs are read from `~/Downloads`** and are not committed. Change the paths at the
  top of `build_fixtures.py` if they move.

## Wiring this into the app

Done, 2026-09-02. `dq-app/` was rewritten to spec v1.0 and reads these files through
`dq_app/data/local_source.py`, selected by `DQ_APP_DATA_SOURCE=local` (the default). The
adapter seam took the change without modification, as expected.

```bash
cd dq-app && ../.venv/bin/streamlit run app.py
```

The app never writes here. Events recorded in the UI go to session state, because this
directory is generated output gated by `verify.py` and editing it by hand would break
the one thing it is for.

**One mismatch the app had to work around.** `violation_sample` is populated only for
the final run, but every cohort's `member_result_ids` point at the run that raised it —
so no cohort has evidence rows from its own raising run, and the "what did you see when
you decided this" lookup finds nothing for all fourteen. The detail page falls back to
the newest samples for the same rules and says on screen that it has done so. Worth
fixing in the sampling rather than in the UI: a cohort should carry the evidence it was
raised on.

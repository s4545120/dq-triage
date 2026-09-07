# DQ Triage Agent — architecture diagram source

Companion to `dq-triage-agent-spec.md`.
Surfaces: Scorecard, Cohort Queue, Remediation Workbench, Rule Registry Studio.

```mermaid
flowchart TB
  U(["Data steward — decides and acts"])

  subgraph SVC["Databricks Apps Services"]
    SSO["User auth (OBO) — signs every approval"]
    LOG["App service principal — INSERT on dq.results only"]
  end

  subgraph APP["Databricks Apps · Streamlit"]
    direction LR
    P1["Rule Registry — configure"]
    P2["Scorecard — measure"]
    P3["Cohort Queue — triage"]
    P4["Remediation Workbench — approve & record"]
    P5["CDE Register — what matters, read-only"]
    RT{{"Streamlit runtime — one data adapter"}}
    P1 --- RT
    P2 --- RT
    P3 --- RT
    P4 --- RT
    P5 --- RT
  end

  subgraph AI["Databricks Model Serving · AI layer"]
    direction LR
    A1["Cohort triage — group · explain · rank"]
    A2["Remediation advice — recommends an approach"]
  end

  subgraph UC["Unity Catalog · dq catalog"]
    direction LR
    T0[("config.cde_registry — what matters")]
    T1[("config.rule_registry · config.playbook")]
    T2[("results.check_run · results.violation_sample")]
    T3[("results.cohort · results.disposition")]
    T4[("results.cde_profile — what the data looks like")]
  end

  subgraph JOBS["Lakeflow jobs & serverless SQL"]
    direction LR
    J0["Profile job — describes registered CDEs"]
    J1["Check runner — L0-L3 · verdicts"]
    J2["Triage job — L4 · cohorts + advice"]
  end

  PROD[("PRODUCTION TABLES · prod.* — READ ONLY<br/>written by nobody in this architecture")]

  U --> RT
  RT --> SSO
  RT --> LOG
  RT -- "SELECT (read-only)" --> UC
  RT == "appends to disposition — the audit record, never the data" ==> T3
  JOBS <-- "reads · writes" --> UC
  J2 -- "invokes per run" --> AI
  PROD -- "reads only" --> J1
  PROD -- "reads only" --> J0
  T0 == "the worklist — an unregistered column is never profiled" ==> J0
  J0 -. "proposes rules as SHADOW — a human promotes" .-> T1
  RT -. "approved recommendation leaves as a decision — the app never executes it" .-> OWNER
  OWNER["Owner's change process — OUTSIDE THE SYSTEM<br/>pipeline rerun · upstream ticket · CR"]
  OWNER == "the only thing that writes production data" ==> PROD
```

## The one claim this diagram makes

**Nothing in this system writes to business data.** The app's only write is the disposition
record — what was found, what was advised, what the owner decided, and whether it held.
Production tables sit outside the boundary: read by the check runner, written by nobody here.

That single constraint removes the audit problem, the rollback problem, and the "can this touch
billing data" conversation — and it means regulated tables need no special case.

## The approval chain

Five events, each a **new immutable row** in `dq.results.disposition`. Nothing is ever updated in
place, so the sequence itself is the evidence and a correction is a new row, not an edit.

| # | Event | Produced by | Carries |
|---|---|---|---|
| 01 | `recommended` | Triage job | Cohort, root-cause hypothesis, recommended approach |
| 02 | `reviewed` | Steward, in-app | accepted · deferred · rejected · no_action, plus a reason |
| 03 | `approved` | Approver(s), in-app | One row per approver. **P1 needs two distinct named approvers**; P2/P3 one |
| 04 | `executed` | Data owner, **outside the system** | Self-reported: what was done, when, ticket or job-run ref |
| 05 | `verified` | Next scheduled check run | Pass closes the cohort; fail appends a reopen and the chain continues |

Steps 01, 02, 03 and 05 are produced inside the system. **Step 04 is a claim the owner makes — the
register records it, it does not witness it.** No re-check job, nothing for the app to trigger, no
elevated permissions anywhere.

## Identity and permissions — two identities, deliberately

- **On-behalf-of-user authorization** establishes *who is acting*: the signed-in user's token is
  forwarded to the app (`x-forwarded-access-token`), so approver identity comes from the platform and
  cannot be typed into a form field.
- **The app's own service principal** performs the write, granted `INSERT` on `dq.results` and
  nothing else — no grant on any `prod.*` table.

A workspace admin can therefore demonstrate from Unity Catalog grants alone that the app cannot
modify business data. The guarantee is a permission, not a code review. Under OBO the app is also
confined to its declared OAuth scopes, so a steward who can write to production in a notebook still
cannot do it through this app.

**What this control is, and is not.** It records that named people approved and that someone
reported executing. It cannot prevent execution without approval, or prove what ran matched what was
approved. That makes it a **detective** control, not a preventive one. If it ever covers
SOX-relevant data, prevention has to live in change management and production grants — not here.

## Table model

| Table | Written by | Purpose |
|---|---|---|
| `dq.config.cde_registry` | Stewards (seeded; read-only in the app today) | **What matters** — the critical data elements, registered before anything profiles them |
| `dq.config.rule_registry` | Stewards (via app, shadow→active only) | What we check |
| `dq.config.playbook` | Stewards | Remediation **approaches** as reference material — non-executable by design |
| `dq.results.check_run` | Check runner | Every verdict, one row per rule per run |
| `dq.results.violation_sample` | Check runner | ≤100 example bad rows per breach |
| `dq.results.cde_profile` | Profile job | What each registered element actually contains — distributions and masked signatures, never values for a PII element |
| `dq.results.cohort` | Triage job | Grouped breaches + root-cause hypothesis + recommendation |
| `dq.results.disposition` | The app (service principal, `INSERT` only) | **The audit register** — append-only event log: recommended → reviewed → approved → executed → verified, each row carrying the acting identity from OBO |

## Per-surface access

| Surface | Reads | Writes |
|---|---|---|
| Rule Registry Studio | `rule_registry`, `check_run` | `rule_registry` (shadow → active only) |
| Scorecard | `check_run`, `cohort`, `disposition`, `rule_registry` | none |
| Cohort Queue | `cohort`, `violation_sample` | none |
| Remediation Workbench | `cohort`, `playbook`, `violation_sample` | `disposition` |
| CDE Register | `cde_registry`, `cde_profile`, `rule_registry`, `check_run` | none |

## The AI layer

Two Model Serving endpoints, **both invoked by the triage job on a schedule** — never by the app at
request time. The app only reads what they wrote.

| Endpoint | What it does | Priority |
|---|---|---|
| Cohort triage | Collapses many breaches from one root cause into one cohort; root-cause hypothesis, blast radius, ranking | Required — the queue is unusable without it |
| Remediation advice | Recommends an approach; drafts one where the playbook has no entry | Can follow one release later |

Boundary, unchanged from the parent architecture doc: sees aggregated results and ≤100-row samples,
never computes pass/fail, never writes data, never auto-approves. Every output is advice a human
accepts or rejects, stored with its input payload for audit.

## Phase placement

With execution out of scope this is **not a new layer** — it is L4 deepened. It belongs in **Phase 2**
of the parent doc's rollout rather than a Phase 4, does not wait on Phase 3 shift-left, and costs two
new tables, one extended job and one app.

## The CDE register — what matters, named before it is measured

Everything above answers "what broke". None of it answers "is anyone looking at the fields the
business actually cares about", because a coverage number measured against the rule set is 100% by
construction. `config.cde_registry` is the denominator that fixes that: the critical data elements —
date of birth, name, email, identity document number, service number — registered as **definitions**,
with a business meaning, a criticality tier, a PII flag and an expected signature.

**Registration comes before discovery, and the ordering is the control.** An element is registered
first; only then is it bound to physical columns, and only a bound column is profiled. The profile
job takes its worklist from `v_cde_registry_current`, so an unregistered column is never described
and can never produce a proposed rule. That is what stops discovery from quietly deciding what counts
as critical.

**Discovery output lands in the shadow lane, not in production.** Where profiling suggests a rule, it
is INSERTed into `config.rule_registry` with `status = 'shadow'` and the profile evidence in `note`.
A human promotes it through the path that already exists. No new write path, no new approval
machinery, and the spec's existing non-goal — *the agent may propose rules; a human promotes them* —
holds verbatim.

**Criticality is not severity.** Criticality belongs to the element and says how much it matters.
Severity belongs to the rule and says how loudly a check complains. Criticality feeds cohort ranking,
which is advisory, and informs severity when a human authors a rule. It never adjusts a severity
downstream — `check_run.severity` is copied verbatim from the registry and nothing recomputes it.

**A binding is a checkable claim.** Where an element is only populated for some rows — IMEI only for
handset services, billing account only for postpaid — the binding says so in SQL, and `v_cde_coverage`
compares that against the `scope_filter` on every rule attached to it. A rule with no scope where the
register declares one is measuring rows that were never supposed to hold a value. On the pilot data
that is 700 rows across two rules, and it is exactly what cohort COH-B is about: the register turns a
rule defect from something a human noticed into something the model asserts.

**Profiling PII without holding PII.** `results.cde_profile` stores counts, distributions and masked
signatures — digits to `9`, letters to `X`, whitespace to `_`, punctuation kept — so a date of birth
becomes `9{4}-9{2}-9{2}_9{2}:9{2}:9{2}` and cannot be read back. Where the element is flagged PII, a
shape seen on fewer than five rows is folded into a `<rare>` bucket that keeps the count and discards
the shape, and `value_stats_withheld` records that this happened. `violation_sample` is the one
accepted PII surface in this architecture; the profile does not open a second.

**What the app does not do.** Registering an element is an append to `config.cde_registry` and would
be a third write for an app whose whole claim is that it makes two. Today the register is seeded and
the app reads it, so the grants in `sql/ddl/07_grants.sql` are unchanged and the headline claim is
untouched. Making registration an in-app act is a decision about the app's grants, not a UI change.

**Not yet built.** The profile job itself, and the classification sweep that would propose bindings
from column names, value signatures and Unity Catalog lineage. Bindings today are hand-authored,
which is what `discovered_by = 'manual'` on every one of them means. `binding_status` and
`discovered_by` exist now so that discovery later lands as new rows in a `candidate` state rather
than as a schema migration on a table that by then carries history.

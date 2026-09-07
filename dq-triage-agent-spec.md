# PRD — DQ Triage Agent: cohort triage, recommendation & audit register

**Version:** 1.0 (draft) · **Date:** 2026-09-01 · **Owner:** Data Product Management
**Parent doc:** [Proactive Data Quality Agent — Databricks Architecture](../dq-agent-architecture-databricks.md) v0.1
**Supersedes:** `dq-remediation-execution-spec.md` (v0.1, 2026-08-27) — that draft scoped an execution
layer that would modify data. Execution is now explicitly out of scope; see Non-Goals.

---

## Problem Statement

The L0–L4 architecture detects well and stops at a ticket. Everything after that is invisible to the
platform: stewards diagnose ad hoc, fix issues off-platform, and no record survives of what was wrong,
what was done, or whether it worked. Two costs follow. First, the same problem is re-diagnosed from
scratch every time it recurs, because the diagnosis was never written down. Second — and worse for the
programme's credibility — nobody can answer "is data quality actually improving?", because detection
metrics measure how much we found, not how much got resolved.

The gap is not that fixes are hard to execute. Stewards can write SQL. The gap is that **thirty breaches
across twelve tables from one upstream schema change arrive as thirty separate alerts**, and that no
system holds the record of what was decided about any of them.

## Goals

1. **Group, don't list.** Related breaches collapse into a single cohort with one root-cause hypothesis
   and one blast radius, so the queue length reflects the number of problems, not the number of rules.
2. **Recommend a course of action** for each cohort, so stewards start from a proposed approach rather
   than a blank page.
3. **Hold the record.** Every flagged cohort reaches a recorded disposition — accepted and actioned,
   deferred, or rejected with a reason — with the reviewer's identity and timestamp attached.
4. **Prove closure.** The next scheduled check run verifies whether an actioned cohort actually passes,
   so MTTR, closure rate and recurrence become measured numbers.
5. **Stay outside the data.** No component modifies business data, so the system needs no rollback
   machinery, no change-control integration, and no special case for regulated tables.

## Non-Goals

- **Executing fixes against data. This is the defining non-goal.** The app does not run `UPDATE`,
  `MERGE` or `DELETE`, does not trigger jobs that do, and holds no write permission on any `prod.*`
  table. Remediation is carried out by the data owner in their own pipeline through their own change
  process. *(Rationale: the value is in diagnosis, not execution; and an app that can modify billing
  or revenue data is a control question that would gate the whole programme.)*
  **Note the distinction:** approval *for* execution is fully in scope and is recorded as a
  first-class event. What is out of scope is the system performing the execution. The approval is a
  governance record that authorises a person to act, not a button that acts.
- **A general fix-automation platform.** The playbook stores remediation *approaches* as reference
  material, not executable bodies. It is documentation, not a runtime.
- **Replacing the ticketing system.** Dispositions link out to whatever incident tool is chosen
  (parent doc Open Decision #3); this does not become a workflow tool.
- **Automatic rule authoring or promotion.** The agent may propose rules and threshold changes; a
  human promotes them, as today.
- **Upstream root-cause fixing.** Where the fault is in a source system, the output is a routed
  recommendation, not a correction. Correcting warehouse data while the source keeps emitting bad
  rows makes the warehouse disagree with the system of record — explicitly not something we do.

## User Stories

**Data steward / domain owner**
- As a steward, I want related breaches grouped into one cohort so I triage one problem, not thirty alerts.
- As a steward, I want a root-cause hypothesis with the evidence it came from, so I can confirm or discard it quickly.
- As a steward, I want a recommended approach and any past approach used for this rule, so I'm not starting cold.
- As a steward, I want to record what I actually did — and when — so the next person sees it.
- As a steward, I want the system to tell me whether my fix held, without my having to re-query.
- As a steward, I want to reject or defer a cohort with a reason, so the queue reflects real decisions rather than silence.

**Data Product Management / platform**
- As the platform owner, I want every disposition attributable to a named reviewer via SSO, so the register stands up as audit evidence.
- As the platform owner, I want recurrence tracked per rule, so I can see which cohorts are being patched rather than resolved.
- As the platform owner, I want cohort precision measured, so I know whether the grouping is trustworthy.

**Business / domain lead**
- As a business lead, I want to see closure rate and MTTR for my domain, so I have evidence the programme produces outcomes.
- As a business lead, I want to know a critical cohort was verified fixed, not merely acknowledged.

**Edge cases**
- As a steward, if I mark a cohort actioned and the next check run still fails, I want it reopened automatically rather than sitting closed and wrong.
- As an auditor, I want to retrieve every cohort raised in a period with its disposition, including the ones nobody actioned and why.

## Requirements

### Must-Have (P0)

**Cohort model — `dq.results.cohort`**
- Agent output: cohort id, member breaches, root-cause hypothesis, blast radius (from UC lineage), severity, owning domain, recommended approach.
  - *AC:* Given a run where one upstream failure breaches 30 rules across 12 tables, when the triage job runs, then one cohort row is produced referencing all 30 breaches — not 30 cohorts.

**Recommendation**
- Each cohort carries a recommended approach, drawn from the playbook where one matches the rule, otherwise drafted by the advice endpoint.
  - *AC:* Given a rule with a playbook entry, when a cohort is raised, then that entry is presented as the recommendation with its prior-use count. Given no entry, then a drafted recommendation is presented and clearly labelled as generated.

**Disposition register — `dq.results.disposition` (append-only)**

The register is an **event log, not a status column.** Every step appends a new immutable row;
nothing is ever updated or deleted in place, so the sequence itself is the evidence and a
correction is a new row rather than an edit.

| # | Event | Produced by | Carries |
|---|---|---|---|
| 01 | `recommended` | Triage job | Cohort, root-cause hypothesis, recommended approach, playbook ref |
| 02 | `reviewed` | Steward, in-app | `accepted` · `deferred` · `rejected` · `no_action`, plus a reason |
| 03 | `approved` | Approver(s), in-app | One row per approver. **P1 requires two distinct named approvers**; P2/P3 require one |
| 04 | `executed` | Data owner, **outside the system** | Self-reported: what was done, when, external ticket or job-run reference |
| 05 | `verified` | Next scheduled check run | Pass → cohort closes with before/after counts. Fail → appends a reopen and the chain continues |

- *AC:* Every cohort raised in a period is retrievable with its full event chain, including cohorts nobody actioned and the reason why. Nothing disappears silently.
- *AC:* A cohort cannot reach `approved` without the required number of **distinct** approver identities.
- *AC:* Step 04 is recorded as a claim. The register states who reported it and when; it does not assert that the system observed it.
- *AC:* Writes are `INSERT` only. Any attempt to model this as an updatable status column is a design defect.

**Identity and permissions — the two-identity model**
- **On-behalf-of-user authorization** establishes who is acting. The signed-in user's token is forwarded to the app (`x-forwarded-access-token`), so reviewer and approver identity comes from the platform and cannot be typed into a form field.
- **The app's own service principal** performs the write, granted `INSERT` on `dq.results` and **nothing else** — in particular no grant on any `prod.*` table.
  - *AC:* A workspace admin can demonstrate, from Unity Catalog grants alone, that the app cannot modify business data. The guarantee is a permission, not a code review.
  - *AC:* Under OBO the app is confined to its declared OAuth scopes, so a steward who can write to production in a notebook still cannot do so through this app.

**What this control is, and is not**
- The register is a **detective** control: it records that named people approved and that someone reported executing. It cannot prevent execution without approval, nor prove that what ran matched what was approved — execution happens outside the system by design.
- If any cohort in scope touches SOX-relevant or otherwise regulated data, preventive enforcement must live in change management, pipeline CI and production grants. **This spec should not be presented as providing it.** See Open Questions.

**Verification via the next scheduled run**
- When a cohort is marked actioned, the system watches subsequent `check_run` rows for the originating rules and scope.
  - *AC:* Given an actioned cohort, when the next scheduled check run passes for all member rules, then the cohort closes as verified with before/after counts. When it still fails, the cohort reopens with the failed verification recorded.
  - *No re-check job is built.* The check runner already runs on schedule; verification reads its output.

**Playbook — `dq.config.playbook`**
- Rule-to-approach reference: named approach, type (`pipeline_rerun` · `upstream_ticket` · `source_correction` · `manual_sql` · `accept_and_document`), description, prior-use count, recurrence rate. Non-executable by design.

**Scorecard additions**
- MTTR (raised → verified closed), closure rate, recurrence rate and recommendation-acceptance rate, alongside the existing detection metrics, broken out by domain and severity.

### Nice-to-Have (P1)

- **Insight view.** Patterns across cohorts over time — which source systems, domains or table families generate the most cohorts, and which recommendations keep recurring. This is the "where should we invest" output, distinct from per-cohort triage.
- **Cohort merge / split.** Let a steward correct the agent's grouping, and feed those corrections back as evaluation data for cohort precision.
- **Deferral review dates.** A deferred cohort surfaces again on its review-by date rather than disappearing.

### Future Considerations (P2)

- **Assisted execution**, reconsidered only once the register shows which recommendation types are high-volume, low-risk and reliably successful — and only for the `pipeline_rerun` class, which re-derives data rather than amending it. Explicitly not v1. Design the disposition model so an executed-by-system flag could be added without reshaping it.
- **Rule proposals from cohort patterns** — the agent suggesting new rules where recurring cohorts reveal uncovered failure modes.

## Success Metrics

**Leading (days to weeks)**
- Cohort compression: breaches ÷ cohorts. Target ≥5:1 — if it approaches 1:1 the grouping is not working.
- Cohort precision: cohorts a steward confirms as correctly grouped ÷ total reviewed. Target ≥80%.
- Recommendation acceptance: cohorts where the steward's recorded action matches the recommended approach ÷ cohorts with a recommendation. Target ≥50% (a proxy for whether the advice is any good).
- Disposition coverage: cohorts with a recorded disposition ÷ cohorts raised. Target ≥90% within 10 business days.

**Lagging (weeks to months)**
- MTTR: raised → verified closed. Target <5 business days P1, <15 P2.
- Closure rate: verified-closed ÷ cohorts raised. Target ≥75%.
- Recurrence: same rule re-cohorting within 30/90 days of a verified close. Target <10% at 30 days — the primary signal of root-cause versus symptom.
- Proactive catch rate (existing metric, parent doc §8) should improve as recurring cohorts get resolved upstream.

## Open Questions

- **(Data governance / audit) — blocking before any regulated table is onboarded.** Is the programme claiming a detective control or a preventive one? The register is detective by construction. If a preventive control is required for regulated data, it has to be built where execution happens, and that is outside this system's scope entirely. Get this answered before an auditor asks it.
- **(Data governance)** Does the disposition register need formal control status — i.e. is it audit *evidence* subject to retention rules, or an internal working record? Materially changes retention and access design. Sharpens parent doc Open Decision #4.
- **(Data governance)** Who is authorised to be an approver, and is that list managed as a Databricks group? The two-approver rule is only meaningful if the eligible set is governed.
- **(Data governance)** Who signs off a shadow → active rule promotion in the Rule Registry Studio? Currently unspecified, and it is the app's only other write.
- **(Engineering)** How is a cohort's verification scope pinned so the next check run is compared like-for-like when the underlying partition has moved on?
- **(Engineering / cost)** Cohort clustering over what window — per run, rolling 24h, or until disposition? Affects both cost and whether a long-running problem produces one cohort or many.
- **(Stakeholder)** Pilot scope: the top-20 T1 tables from parent doc Phase 1, or narrower?
- **(Stakeholder)** Does "recommendation acceptance" risk anchoring stewards on the agent's suggestion? Worth watching once measured; a high number could mean good advice or passive agreement.

## Timeline Considerations

- **This is no longer a separate layer.** With execution out, cohort triage, recommendation and the
  register are an extension of L4 rather than an L5 on top of it. It becomes part of **Phase 2** in
  the parent doc's rollout, not a Phase 4 — it does not wait on Phase 3 shift-left, and it is
  materially cheaper: two new tables, one extended job, one app.
- **Dependency:** needs the check runner (Phase 1) producing `check_run` at volume, so cohorts form
  from real breach history rather than a cold start.
- **No hard external deadline known** — confirm whether a target quarter is committed anywhere.
- **Suggested first release:** cohort model, queue, disposition register and verification. Recommendation
  can follow one release later if the advice endpoint needs tuning — the register is valuable on its own,
  and it is the piece that makes the scorecard honest.

---

# Addendum A — Critical data elements (v1.1 draft, 2026-09-07)

**Status:** additive to v1.0. Nothing in the body above changes. This addendum introduces one config
table, one results table, two views and a fifth surface. Every requirement, non-goal and open
question in v1.0 stands as written.

## Why

v1.0 measures the rule set: how many checks pass, how many cohorts closed, how fast. All of it is
measured against the rules that happen to exist, so it can say how the checks are doing and cannot
say whether anything is watching the fields the business cares about. Coverage against the rule set
is 100% by construction.

A **critical data element (CDE)** is a field the business has registered as mattering — date of
birth, name, email, identity document number, service number. Registered as a list, before the rules
were written, it becomes a denominator the rule set does not control, and "what proportion of what
matters has anything checking it?" becomes answerable.

## Requirements

### Must-Have (P0)

**CDE register — `dq.config.cde_registry`**
- Append-only and versioned exactly as `rule_registry` is: a re-tier, a new binding or a retirement
  is a new `(cde_id, cde_version)` row, and `effective_to` is derived by `v_cde_registry_current`.
- An element carries a business meaning, a data class, a criticality tier, a PII flag, an optional
  expected signature, and its **bindings** — the physical columns it lands in, as an array.
  - *AC:* Given an element registered with three bindings, when the coverage view is queried, then
    three rows are returned and each is assessed independently.

**Registration precedes discovery**
- The profile job takes its worklist from `v_cde_registry_current`. An unregistered column is never
  profiled and can never produce a proposed rule.
  - *AC:* Given a column not bound to any registered element, when the profile job runs, then no
    `cde_profile` row exists for it.

**Profiling — `dq.results.cde_profile`**
- One row per binding per pass: rows in scope, null and blank rates, cardinality, length range,
  sentinel count, distinct shape count, top masked signatures, and match rate against the element's
  expected signature.
- Not a `check_run` row. A profile describes and reaches no verdict; the verdict layer's status enum
  and thresholds do not apply to it, and admitting one would put non-verdicts into denominators that
  mean "checks that ran".
  - *AC:* Given a column whose values carry two distinct shapes, when it is profiled, then both
    appear in `top_signatures` with their row counts, and the minority shape is visible without any
    rule having been written.

**Privacy — values are never retained for a PII element**
- Where `pii = TRUE`, the profile stores counts, distributions and masked signatures only. Shapes
  occurring on fewer than five rows are folded into a `<rare>` bucket that keeps the count and
  discards the shape, and `value_stats_withheld` records that this happened.
- `violation_sample` remains the one accepted PII surface in the design. The profile does not open a
  second.
  - *AC:* Given a PII element, when its profile is written, then `value_stats_withheld` is TRUE and
    no stored signature has a row count below five.

**Coverage — `dq.results.v_cde_coverage`**
- One row per bound column, classified worst-first: `no_rule`, `scope_mismatch`, `unvalidated`,
  `covered`.
- A rule attaches to a binding by matching its column **or** by naming the element in
  `rule_registry.cde_id`. The second exists for cross-table rules, which carry `target_column = NULL`
  by design and no column join can reach.
  - *AC:* Given a cross-table rule tagged with a `cde_id`, when coverage is computed, then it counts
    toward that element's rule count.

**Scope mismatch is a rule defect, detected structurally**
- Where a binding declares `expected_scope_filter` and an attached rule carries no `scope_filter`,
  that rule measures rows the register says never held a value, and the view names it.
  - *AC:* Given the pilot data, when coverage is computed, then `SUBS_IMEI_NOT_NULL` and
    `SUBS_PRIM_ACCT_NOT_ZERO` are each named against their binding — the two rules behind cohort
    COH-B.

**Surface — CDE Register (read-only)**
- A fifth surface listing registered elements, their bindings, their latest profile and their
  coverage findings, plus a coverage panel on the Scorecard.

### Non-Goals for this addendum

- **In-app registration.** Registering an element would be a third write for an app whose claim is
  that it makes two. The register is seeded and read-only in the app; `sql/ddl/07_grants.sql` is
  unchanged. Making registration an in-app act is a grants decision, not a UI change, and it has not
  been taken.
- **Automated binding discovery.** The classification sweep — column-name tokens, value signatures,
  Unity Catalog lineage — is designed but not built. Every binding is hand-authored, marked
  `discovered_by = 'manual'`. `binding_status` and `discovered_by` exist now so discovery later lands
  as new rows in a `candidate` state rather than as a migration.
- **Automatic rule promotion.** Unchanged from v1.0. Profiling may propose a rule; it lands as
  `shadow` and a human promotes it through the existing path.
- **Criticality driving severity.** Criticality belongs to the element, severity to the rule. It may
  feed `cohort.rank_score`, which is advisory, and inform a human authoring a rule. It never adjusts
  a severity downstream — `check_run.severity` is copied verbatim and nothing recomputes it.

## Metrics this adds

- **CDE coverage:** bound columns with at least one value-examining rule ÷ bound columns. The one
  number on the Scorecard whose denominator the rule set does not control.
- **Critical gaps:** registered `critical` or `high` elements carrying any finding. Target zero.
- **Scope mismatches:** rules contradicting a binding's declared scope. Each is a rule defect and
  each inflates breach counts until it is fixed.
- **Profile freshness:** bound columns not profiled within the agreed window.

## Open Questions this adds

- **(Data governance)** Who may register a CDE, and who may retire one? Retirement is the sharp edge:
  it silently drops coverage and nothing in the current design would notice. Related to, and probably
  answered with, the v1.0 question on who signs off a rule promotion.
- **(Data governance)** Should confirmed bindings also be written to Unity Catalog column tags, so
  the binding is visible to tooling outside this app? The register would remain the versioned audit
  record; the tag would be an operational copy.
- **(Stakeholder)** Who owns the criticality tiers, and against what scale? The seeded tiers are a
  starting point, not an agreed taxonomy.
- **(Engineering)** What is the classification sweep's cost and cadence over a full warehouse, and
  does it need sampling rather than a full pass?

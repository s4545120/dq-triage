"""Turn the two pilot CSVs into a complete local dq.* dataset.

    ../.venv/bin/python build_fixtures.py

Writes Parquet to out/, one file per table, named <schema>.<table>.parquet so the
mapping to Unity Catalog is obvious. Deterministic: same inputs, same output, same
uuids, every time. Nothing here talks to Databricks.

WHAT IS REAL AND WHAT IS SYNTHESISED -- read this before quoting any number.

Real, derived from the CSVs by rules.py:
  * every violation_count and rows_scanned on the FINAL run
  * every violation_sample row -- actual bad rows, actual bad values
  * which rules pass and which breach

Synthesised, because one snapshot cannot contain them:
  * the preceding 39 daily runs. The CSVs are a single point in time, so history is
    back-projected: chronic rules hold roughly steady, the COH-A rules are clean
    until 2026-08-28, and the rules that pass today are given a plausible history of
    having been broken and fixed. That last group is what gives the scorecard a
    closure rate and an MTTR at all.
  * every cohort, hypothesis and recommendation. On Databricks these come from the
    triage job's model endpoints. Here they are written by hand from what the
    profiling actually found, so the text is defensible, but no model produced it
    and model_input_payload is a stub.
  * every disposition event, and the identities attached to them.
  * violation samples for back-projected breaches are NOT synthesised. Fabricating
    evidence rows for a breach that did not happen is the one shortcut worth
    refusing, so those runs carry a count and no samples, and say so in `message`.

The generator is the reference implementation of the rule semantics. When the
triage job is written for real, the numbers it produces on this data should match
what is in out/ -- that is the cheapest correctness test available before a
workspace exists.
"""

from __future__ import annotations

import argparse
import json
import random
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

import rules
from rules import CTCT_TABLE, SUBS_TABLE, Ctx

HERE = Path(__file__).parent
OUT = HERE / "out"
NS = uuid.UUID("6f1b4c2e-0000-4000-8000-000000000001")  # fixed namespace -> stable uuids

SUBS_CSV = Path.home() / "Downloads" / "mock_subs_c_1000 (1).csv"
CTCT_CSV = Path.home() / "Downloads" / "mock_ctct_c_1000 (1).csv"

RUN_DAYS = 40  # long enough that the earliest historical cohort's raise date is in range
SNAPSHOT = datetime(2026, 9, 2, 3, 0, 0)          # the final run: today, 03:00
INCIDENT_DATE = datetime(2026, 8, 28, 0, 0, 0)     # the CRM export change
APP_VERSION = "0.2.0-fixture"
MAX_SAMPLE_ROWS = 100

# --- identities -------------------------------------------------------------
# Synthetic. On Databricks every one of these arrives from x-forwarded-access-token
# and cannot be typed in. Kept on example.com so nothing here resembles a real person.
STEWARD_A = ("m.okonkwo@example.com", "M. Okonkwo")
STEWARD_B = ("j.tanaka@example.com", "J. Tanaka")
STEWARD_C = ("r.delacruz@example.com", "R. Dela Cruz")
APPROVER_A = ("p.nguyen@example.com", "P. Nguyen")
APPROVER_B = ("s.whitfield@example.com", "S. Whitfield")
OWNER_CRM = ("crm-platform@example.com", "CRM Platform Team")
OWNER_PROV = ("provisioning@example.com", "Provisioning Team")

TRIAGE_JOB = ("job:dq-triage", "DQ Triage Job")
CHECK_RUNNER = ("job:dq-check-runner", "DQ Check Runner")


def det_uuid(*parts: str) -> str:
    return str(uuid.uuid5(NS, "|".join(parts)))


# ---------------------------------------------------------------------------
# History profiles
# ---------------------------------------------------------------------------
# day_offset 0 == the final run; -29 == 29 days earlier.

INCIDENT_RULES = [
    "CTCT_EML_FMT", "CTCT_EML_NO_AT", "CTCT_EML_WHITESPACE", "CTCT_EML_DOMAIN_TLD",
    "CTCT_EML_DOUBLE_DOT", "CTCT_EML_TRAILING_DOT", "CTCT_EML_NOT_NULL",
    "CTCT_EML_STTS_NOT_NULL", "XREF_OPEN_TS_AGREEMENT",
]

# rule_id -> (day it was fixed, violations it carried before that)
FIXED_ON = {
    "SUBS_STTS_RSN_REQUIRED": (-25, 22),
    "XREF_SUBS_CTCT_ORPHAN": (-22, 9),
    "SUBS_SIM_NOT_NULL": (-20, 48),
    "SUBS_BILL_OFFR_NOT_ZERO": (-16, 63),
    "CTCT_MOBL_FMT": (-12, 31),
    "CTCT_IDNT_DOC_NOT_NULL": (-9, 17),
    "SUBS_MSISDN_UNIQUE": (-6, 14),
}

# The recurrence case: fixed, verified closed, then broke again inside 30 days.
# This is the metric the spec calls "the primary signal of root-cause versus symptom",
# so the fixture has to contain one or the number is untestable.
RECURRED = {"CTCT_PHN_FMT": (-21, -8, 24)}  # (fixed_day, recurred_day, count now)


def history_count(rule_id: str, snapshot_violations: int, day: int, rng: random.Random) -> int:
    """Violations for `rule_id` on the run `day` days before the snapshot."""
    if rule_id in INCIDENT_RULES:
        run_ts = SNAPSHOT + timedelta(days=day)
        return snapshot_violations if run_ts >= INCIDENT_DATE else 0

    if rule_id in RECURRED:
        fixed_day, recur_day, now = RECURRED[rule_id]
        if day < fixed_day:
            return max(1, int(now * rng.uniform(0.7, 1.2)))
        if day < recur_day:
            return 0
        return now

    if rule_id in FIXED_ON:
        fixed_day, before = FIXED_ON[rule_id]
        if day < fixed_day:
            return max(1, int(before * rng.uniform(0.85, 1.15)))
        return 0

    if snapshot_violations == 0:
        return 0

    # Chronic. Hold roughly steady -- these are the problems nobody has touched.
    if day == 0:
        return snapshot_violations
    return max(1, int(snapshot_violations * rng.uniform(0.92, 1.08)))


# ---------------------------------------------------------------------------
# Load and evaluate
# ---------------------------------------------------------------------------

def load_ctx() -> Ctx:
    for p in (SUBS_CSV, CTCT_CSV):
        if not p.exists():
            raise SystemExit(f"Missing input CSV: {p}")
    subs = pd.read_csv(SUBS_CSV, dtype=str, keep_default_na=False)
    ctct = pd.read_csv(CTCT_CSV, dtype=str, keep_default_na=False)
    xref = subs.merge(ctct, on="CTCT_KEY", how="left")
    return Ctx(subs=subs, ctct=ctct, xref=xref)


@dataclass
class Snapshot:
    rows_scanned: int
    violations: int
    violation_pct: float
    sample: pd.DataFrame


def evaluate_all(ctx: Ctx) -> dict[str, Snapshot]:
    out: dict[str, Snapshot] = {}
    for r in rules.RULES:
        scanned, viol = r.evaluate(ctx)
        pct = (len(viol) / scanned * 100) if scanned else 0.0
        out[r.rule_id] = Snapshot(scanned, len(viol), round(pct, 4), viol.head(MAX_SAMPLE_ROWS))
    return out


# ---------------------------------------------------------------------------
# config.rule_registry
# ---------------------------------------------------------------------------

def build_rule_registry() -> pd.DataFrame:
    rows = []
    base_authored = SNAPSHOT - timedelta(days=180)
    for r in rules.RULES:
        for prior in r.superseded:
            rows.append(dict(
                rule_id=r.rule_id,
                rule_version=prior["rule_version"],
                rule_name=r.rule_name,
                target_table=r.target_table,
                target_column=r.target_column,
                rule_type=r.rule_type,
                rule_expr=r.rule_expr,
                scope_filter=prior.get("scope_filter"),
                fail_threshold_pct=r.fail_threshold_pct,
                severity=r.severity,
                business_domain=r.business_domain,
                owner_group=r.owner_group,
                source_layer=r.source_layer,
                status="active",
                effective_from=base_authored,
                created_by=STEWARD_A[0],
                created_at=base_authored,
                promoted_by=STEWARD_A[0],
                promoted_at=base_authored,
                note=prior.get("note", ""),
            ))
        eff = base_authored if not r.superseded else SNAPSHOT - timedelta(days=45)
        rows.append(dict(
            rule_id=r.rule_id,
            rule_version=r.rule_version,
            rule_name=r.rule_name,
            target_table=r.target_table,
            target_column=r.target_column,
            rule_type=r.rule_type,
            rule_expr=r.rule_expr,
            scope_filter=r.scope_filter,
            fail_threshold_pct=r.fail_threshold_pct,
            severity=r.severity,
            business_domain=r.business_domain,
            owner_group=r.owner_group,
            source_layer=r.source_layer,
            status=r.status,
            effective_from=eff,
            created_by=STEWARD_A[0],
            created_at=eff,
            promoted_by=None if r.status == "shadow" else STEWARD_B[0],
            promoted_at=None if r.status == "shadow" else eff,
            note=r.note,
        ))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# results.check_run + results.violation_sample
# ---------------------------------------------------------------------------

def build_runs(snaps: dict[str, Snapshot]) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    rng = random.Random(20260902)
    runs, samples = [], []
    index: dict[tuple[int, str], str] = {}   # (day, rule_id) -> result_id
    run_ids: dict[int, str] = {}

    for day in range(-(RUN_DAYS - 1), 1):
        run_ts = SNAPSHOT + timedelta(days=day)
        run_id = det_uuid("run", run_ts.date().isoformat())
        run_ids[day] = run_id
        is_final = day == 0

        for r in rules.RULES:
            snap = snaps[r.rule_id]
            viol = history_count(r.rule_id, snap.violations, day, rng)
            scanned = snap.rows_scanned
            pct = round(viol / scanned * 100, 4) if scanned else 0.0
            result_id = det_uuid("result", run_id, r.rule_id)
            index[(day, r.rule_id)] = result_id

            if r.status == "shadow":
                status = "skipped"
                msg = f"shadow rule: measured {viol} violations, not raised"
            elif viol == 0:
                status = "pass"
                msg = f"0 of {scanned} rows in scope violate"
            elif pct > r.fail_threshold_pct:
                status = "breach"
                msg = f"{viol} of {scanned} rows in scope violate ({pct:.2f}%), limit {r.fail_threshold_pct:.2f}%"
            else:
                status = "pass"
                msg = f"{viol} of {scanned} rows violate ({pct:.2f}%), within limit {r.fail_threshold_pct:.2f}%"

            if not is_final and viol:
                msg += " | historical fixture run: violation samples not retained"

            runs.append(dict(
                result_id=result_id, run_id=run_id, run_ts=run_ts,
                rule_id=r.rule_id, rule_version=r.rule_version,
                source_layer=r.source_layer, target_table=r.target_table,
                target_column=r.target_column, rows_scanned=scanned,
                violation_count=viol, violation_pct=pct,
                threshold_pct=r.fail_threshold_pct, status=status,
                severity=r.severity, business_domain=r.business_domain,
                owner_group=r.owner_group,
                scope_fingerprint=None,   # open question, see 03_results_check_run.sql
                message=msg,
                duration_sec=round(rng.uniform(0.4, 9.0), 2),
                dbu_estimate=round(rng.uniform(0.001, 0.03), 5),
            ))

            # Samples only where they are real: the final run, from actual bad rows.
            if is_final and viol and len(snap.sample):
                cols = [c for c in r.sample_columns if c in snap.sample.columns]
                for _, row in snap.sample.iterrows():
                    payload = {c: row[c] for c in cols}
                    key = str(row.get(r.key_column, row.get("CTCT_KEY", "")))
                    samples.append(dict(
                        sample_id=det_uuid("sample", result_id, key),
                        result_id=result_id, run_id=run_id, rule_id=r.rule_id,
                        target_table=r.target_table, row_key=key,
                        sample_row=json.dumps(payload, ensure_ascii=False),
                        captured_ts=run_ts,
                    ))

    return pd.DataFrame(runs), pd.DataFrame(samples), {"index": index, "run_ids": run_ids}


# ---------------------------------------------------------------------------
# config.playbook
# ---------------------------------------------------------------------------

PLAYBOOK = [
    dict(playbook_id="PB_UPSTREAM_SOURCE_RELEASE", rule_id=None, rule_type="format",
         approach_name="Raise upstream ticket against the source release",
         approach_type="upstream_ticket",
         description=(
             "Where a defect starts on a date that matches a source-system release, the "
             "correction belongs in that system. Raise a ticket against the release, attach "
             "the cohort's before/after counts, and hold the cohort open until the source "
             "ships. Do NOT correct the warehouse copy: while the source keeps emitting bad "
             "rows the warehouse would disagree with the system of record, which the spec "
             "rules out explicitly."),
         typical_owner="CRM Platform Team", status="active"),
    dict(playbook_id="PB_RULE_SCOPE_AMENDMENT", rule_id=None, rule_type="not_null",
         approach_name="Amend the rule scope, not the data",
         approach_type="accept_and_document",
         description=(
             "Where every violating row shares a product line or account type that legitimately "
             "does not carry the column, the rule is wrong, not the data. Reject the cohort with "
             "the reason recorded, then author a new rule version carrying the scope_filter and "
             "promote it through the registry. The rejection is the audit record that the rows "
             "were examined and found correct."),
         typical_owner="dq-stewards-customer", status="active"),
    dict(playbook_id="PB_PROVISIONING_BACKFILL", rule_id="SUBS_MSISDN_SENTINEL",
         rule_type=None,
         approach_name="Route to provisioning for reissue",
         approach_type="source_correction",
         description=(
             "A live service carrying a placeholder resource value cannot be corrected in the "
             "warehouse -- the real number does not exist anywhere yet. Route to provisioning to "
             "issue and publish the resource; the warehouse picks it up on the next load."),
         typical_owner="Provisioning Team", status="active"),
    dict(playbook_id="PB_PIPELINE_RERUN", rule_id=None, rule_type="consistency",
         approach_name="Re-run the load for the affected window",
         approach_type="pipeline_rerun",
         description=(
             "Where the source is correct and the warehouse copy is not, re-run the load for the "
             "affected partition window. Re-derives rather than amends, which is why this is the "
             "only class the spec flags as a candidate for assisted execution later."),
         typical_owner="Data Platform", status="active"),
    dict(playbook_id="PB_MANDATORY_FIELD_CAMPAIGN", rule_id=None, rule_type="not_null",
         approach_name="Field-completion campaign with the owning channel",
         approach_type="upstream_ticket",
         description=(
             "For genuinely absent attributes with no upstream defect, the fix is collection, not "
             "correction. Agree a completion target with the owning channel and track it as a "
             "deferred cohort with a review-by date rather than leaving it open."),
         typical_owner="Customer Operations", status="active"),
    dict(playbook_id="PB_ACCEPT_KNOWN_LIMITATION", rule_id=None, rule_type="variance",
         approach_name="Accept and document a known source limitation",
         approach_type="accept_and_document",
         description=(
             "Where a column is constant because the source system never populates it, and there "
             "is no plan to change that, record the acceptance with a reason so the cohort stops "
             "recurring silently. Revisit if the source system changes."),
         typical_owner="dq-stewards-customer", status="active"),
]


# ---------------------------------------------------------------------------
# results.cohort + results.disposition
# ---------------------------------------------------------------------------
# Every hypothesis below is written from what profiling actually found in the CSVs.
# On Databricks the triage job's model endpoints produce these; here they are hand
# written, and recommendation_source / model_endpoint say so.

@dataclass
class CohortSpec:
    key: str
    raised_day: int
    rule_ids: list[str]
    severity: str
    hypothesis: str
    evidence: str
    recommendation: str
    approach_type: str
    playbook_id: str | None
    recommendation_source: str
    chain: list[tuple]
    business_domain: str = "Customer"
    owner_group: str = "dq-stewards-customer"
    blast_radius: list[str] = None
    is_recurrence: bool = False


def _e(event_type: str, day_after: int, **kw):
    return (event_type, day_after, kw)


CURRENT_COHORTS = [
    CohortSpec(
        key="COH-A", raised_day=-5, severity="P1_block",
        rule_ids=INCIDENT_RULES,
        hypothesis=(
            "A change to the CRM contact export on 2026-08-28 broke email serialisation. Nine "
            "rules across two tables were clean on every run up to 2026-08-27 and breached "
            "together on the first run after. The 240 affected addresses fall into six equal "
            "buckets of 40 -- @ replaced by a space, @ dropped entirely, whitespace in the local "
            "part, missing top-level domain, doubled dots, trailing dot -- which is the shape of "
            "a formatter emitting six variants, not of 240 people mistyping."),
        evidence=(
            "Zero violations on runs up to 2026-08-27, 240 from 2026-08-28 onward, on all six "
            "email rules simultaneously. EML_STTS_CD already flags all 240 as INVALID, so the "
            "source's own validator agrees the addresses are bad -- meaning the defect is in "
            "serialisation, not in validation. XREF_OPEN_TS_AGREEMENT moved on the same date, "
            "which places the change in the export rather than in the email field alone."),
        recommendation=(
            "Raise an upstream ticket against the 2026-08-28 CRM export release. Do not correct "
            "the warehouse copy: the source is still emitting the bad format, so a warehouse fix "
            "would be overwritten on the next load and would put the warehouse at odds with the "
            "system of record."),
        approach_type="upstream_ticket", playbook_id="PB_UPSTREAM_SOURCE_RELEASE",
        recommendation_source="playbook",
        blast_radius=["prod.marketing.campaign_audience", "prod.billing.invoice_contact",
                      "prod.customer.customer_360", "prod.servicing.notification_queue"],
        # P1: two distinct approvers, then a verification that FAILS and reopens.
        chain=[
            _e("recommended", 0),
            _e("reviewed", 1, actor=STEWARD_A, decision="accepted",
               reason="Confirmed against the release calendar -- CRM export v4.2 shipped 28 Aug."),
            _e("approved", 1, actor=APPROVER_A, ordinal=1),
            _e("approved", 2, actor=APPROVER_B, ordinal=2),
            _e("executed", 3, actor=OWNER_CRM, external_ref="CRM-4821",
               summary="Hotfix deployed to CRM export serialiser; awaiting next full load.",
               approach="upstream_ticket", playbook="PB_UPSTREAM_SOURCE_RELEASE"),
            _e("verified", 4, passed=False),
            _e("reopened", 4, reason=(
                "Verification failed: all nine member rules still breach at their original "
                "counts. The hotfix is deployed in CRM but the next full contact load has "
                "not run, so no corrected rows have reached the warehouse yet. Nothing to "
                "re-action -- the cohort stays open until a load lands after the hotfix. "
                "This is why 'executed' is recorded as a claim: the owner did deploy, and "
                "the register says so, but the register did not witness the outcome.")),
        ],
    ),
    CohortSpec(
        key="COH-B", raised_day=-26, severity="P3_monitor",
        rule_ids=["SUBS_IMEI_NOT_NULL", "SUBS_PRIM_ACCT_NOT_ZERO"],
        hypothesis=(
            "Neither of these is a data defect. Both rules were authored without a scope_filter "
            "and are firing on rows that legitimately do not carry the column: all 200 IMEI "
            "violations are Fixed Broadband services, which have no handset, and all 500 billing- "
            "account violations are prepaid services, which have no billing account. The cohort's "
            "root cause is in the rule registry, not in prod.customer.subs_c."),
        evidence=(
            "Perfect correlation with product line: 200/200 IMEI violations have PROD_TYPE_KEY = 0 "
            "(Fixed Broadband); 500/500 account violations have BILL_SUBS_TYPE_CD = 'PREPAID'. The "
            "correctly-scoped twin rules on the same data return zero -- SUBS_SIM_NOT_NULL scoped to "
            "PROD_TYPE_KEY <> 0, and SUBS_BILL_OFFR_NOT_ZERO scoped to POSTPAID. SUBS_MSISDN_FMT "
            "already had this defect and was fixed the same way in rule_version 2."),
        recommendation=(
            "Reject the cohort -- the 700 rows are correct. Author rule_version 2 of both rules "
            "carrying the scope_filter (PROD_TYPE_KEY <> 0 and BILL_SUBS_TYPE_CD = 'POSTPAID' "
            "respectively) and promote through the registry. The rejection is the audit record "
            "that the rows were examined and found correct."),
        approach_type="accept_and_document", playbook_id="PB_RULE_SCOPE_AMENDMENT",
        recommendation_source="playbook",
        blast_radius=[],
        chain=[
            _e("recommended", 0),
            _e("reviewed", 2, actor=STEWARD_B, decision="rejected",
               reason=("Not a data defect. All 700 rows are correct for their product line. Rule "
                       "scope defect -- raised RULE-118 and RULE-119 to add scope_filters and "
                       "promote v2. Rejecting so the queue stops carrying 700 false breaches.")),
        ],
    ),
    CohortSpec(
        key="COH-C", raised_day=-19, severity="P1_block",
        rule_ids=["SUBS_MSISDN_SENTINEL", "SUBS_MSISDN_FMT"],
        business_domain="Network", owner_group="dq-stewards-network",
        hypothesis=(
            "Twelve mobile subscriptions -- ten of them active, two since cancelled -- carry the "
            "literal 'service-number-unknown' in place of an MSISDN. One placeholder repeated "
            "twelve times is a provisioning path that completes the subscription record before "
            "the resource is issued, not twelve independent data-entry errors."),
        evidence=(
            "All twelve share the identical literal value and PRIM_RSRC_TYPE_KEY = 1 (mobile); "
            "ten carry SUBS_STTS_KEY = 1 and two are cancelled. "
            "Both breaching rules resolve to the same twelve rows, so this is one problem seen "
            "twice. The uniqueness rule is scoped to exclude the sentinel and therefore passes -- "
            "without that scope it would report the same twelve rows a third time."),
        recommendation=(
            "Route to provisioning to issue and publish the twelve resources. Not correctable in "
            "the warehouse: the real numbers do not exist in any system yet, so there is nothing "
            "to copy."),
        approach_type="source_correction", playbook_id="PB_PROVISIONING_BACKFILL",
        recommendation_source="playbook",
        blast_radius=["prod.network.service_inventory", "prod.billing.usage_rating"],
        # P1 but only one approver so far -> stays in approved_awaiting_execution... no:
        # one of two -> awaiting_approval. Fully closed instead, to exercise the pass path.
        chain=[
            _e("recommended", 0),
            _e("reviewed", 1, actor=STEWARD_C, decision="accepted",
               reason="Confirmed with provisioning: twelve orders stalled at resource assignment."),
            _e("approved", 2, actor=APPROVER_A, ordinal=1),
            _e("approved", 2, actor=APPROVER_B, ordinal=2),
            _e("executed", 4, actor=OWNER_PROV, external_ref="PROV-2290",
               summary=("Ten MSISDNs issued and published to the service inventory; the two "
                        "cancelled subscriptions were closed out rather than provisioned."),
               approach="source_correction", playbook="PB_PROVISIONING_BACKFILL"),
            _e("verified", 6, passed=True),
        ],
    ),
    CohortSpec(
        key="COH-D", raised_day=-8, severity="P2_alert", is_recurrence=True,
        rule_ids=["CTCT_MOBL_NOT_NULL", "CTCT_PHN_FMT", "SUBS_NTWK_NOT_NULL"],
        hypothesis=(
            "Scattered contactability gaps with no shared driver: 18 contacts with no mobile, 24 "
            "with a malformed landline, 16 subscriptions with no network technology. Unlike COH-B "
            "these do not correlate with any product line -- the 16 network gaps span all three -- "
            "so scope is not the explanation. Most likely genuine collection gaps."),
        evidence=(
            "No product-line correlation and no common load date. CTCT_PHN_FMT is a RECURRENCE: it "
            "was verified closed on this rule 13 days ago and breached again 8 days ago at a "
            "similar count, which suggests the previous fix corrected rows rather than the "
            "process that produces them."),
        recommendation=(
            "Defer pending a field-completion campaign with Customer Operations. Before actioning "
            "again, establish why CTCT_PHN_FMT recurred -- re-applying the previous row-level "
            "correction will produce the same recurrence in another fortnight."),
        approach_type="upstream_ticket", playbook_id="PB_MANDATORY_FIELD_CAMPAIGN",
        recommendation_source="playbook",
        blast_radius=["prod.servicing.notification_queue"],
        chain=[
            _e("recommended", 0),
            _e("reviewed", 3, actor=STEWARD_A, decision="deferred", review_by_days=21,
               reason=("Deferred to the Q4 contactability campaign. Recurrence on CTCT_PHN_FMT "
                       "needs a root-cause pass first -- re-correcting rows will not hold.")),
        ],
    ),
    CohortSpec(
        key="COH-E", raised_day=-13, severity="P3_monitor",
        rule_ids=["SUBS_ACTV_TS_CONSISTENT", "XREF_NAME_AGREEMENT"],
        hypothesis=(
            "Low-volume drift between the subscription and contact records: 10 subscriptions where "
            "original and initial activation timestamps disagree, 2 where the subscriber first name "
            "does not match the linked contact. Volumes are consistent with legitimate business "
            "events -- migrations and name changes -- that the load does not propagate to both "
            "tables. No drafted playbook entry matched, so this recommendation is generated."),
        evidence=(
            "Twelve rows across 1000, stable across every run with no step change. The two name "
            "mismatches are both plausible variants rather than corruption."),
        recommendation=(
            "GENERATED, not from the playbook. Re-run the load for the affected subscription keys "
            "so both tables derive from the same source event. Confirm first that the two name "
            "mismatches are not legitimate deed-poll changes, in which case the correct disposition "
            "is no_action."),
        approach_type="pipeline_rerun", playbook_id=None,
        recommendation_source="generated",
        blast_radius=["prod.customer.customer_360"],
        chain=[
            _e("recommended", 0),
            _e("reviewed", 4, actor=STEWARD_B, decision="accepted",
               reason="Agreed. Twelve rows, low risk, worth clearing before it accumulates."),
            _e("approved", 5, actor=APPROVER_A, ordinal=1),
        ],
    ),
    CohortSpec(
        key="COH-F", raised_day=-3, severity="P2_alert",
        rule_ids=["CTCT_SPCL_CARE_VARIANCE", "CTCT_BRTH_PARSEABLE", "CTCT_BRTH_PLAUSIBLE"],
        hypothesis=(
            "Three contact-attribute defects that share a likely cause in how the contact record is "
            "defaulted rather than populated. SPCL_CARE_STTS is 'N' on all 1000 rows -- a "
            "vulnerable-customer flag with no variance is almost certainly defaulted, not "
            "collected. 14 rows carry the identical literal '31-02-1988' as a date of birth, which "
            "is both the wrong format and a date that does not exist. 27 contacts are 17 years old."),
        evidence=(
            "Zero variance on SPCL_CARE_STTS across 1000 rows. All 14 unparseable dates are "
            "byte-identical, so this is one bad default value rather than 14 bad records. The 27 "
            "minors all have a 2009 birth year."),
        recommendation=(
            "GENERATED, not from the playbook. Split this cohort: the defaulted special-care flag "
            "is a source-capability question for Customer Operations, while the '31-02-1988' "
            "default is a straightforward source-correction. The 27 minors need a consent and "
            "credit-check review before any data change -- do not correct them."),
        approach_type="source_correction", playbook_id=None,
        recommendation_source="generated",
        blast_radius=["prod.customer.customer_360", "prod.compliance.vulnerable_customer"],
        # No disposition beyond the opening event: exercises awaiting_review and the
        # disposition-coverage metric.
        chain=[_e("recommended", 0)],
    ),
]


def historical_cohorts() -> list[CohortSpec]:
    """One closed cohort per rule that was broken and fixed inside the window.

    These exist so closure rate, MTTR and recurrence have a denominator. Without
    them the scorecard has nothing but open cohorts and every outcome metric is NULL.
    """
    catalogue = {
        "SUBS_STTS_RSN_REQUIRED": ("P2_alert", "Cancelled subscriptions loaded without a status reason",
                                   "pipeline_rerun", "PB_PIPELINE_RERUN", 1),
        "XREF_SUBS_CTCT_ORPHAN": ("P1_block", "Subscriptions loaded ahead of their contact records",
                                  "pipeline_rerun", "PB_PIPELINE_RERUN", 2),
        "SUBS_SIM_NOT_NULL": ("P2_alert", "SIM serials dropped for a subset of mobile activations",
                              "pipeline_rerun", "PB_PIPELINE_RERUN", 1),
        "SUBS_BILL_OFFR_NOT_ZERO": ("P1_block", "Postpaid services loaded without a main billing offer",
                                    "upstream_ticket", "PB_UPSTREAM_SOURCE_RELEASE", 2),
        "CTCT_MOBL_FMT": ("P3_monitor", "Mobile numbers loaded with a country prefix",
                          "source_correction", "PB_PROVISIONING_BACKFILL", 1),
        "CTCT_IDNT_DOC_NOT_NULL": ("P1_block", "Identity documents missing where a type was recorded",
                                   "upstream_ticket", "PB_UPSTREAM_SOURCE_RELEASE", 2),
        "SUBS_MSISDN_UNIQUE": ("P1_block", "Service numbers reused across concurrent subscriptions",
                               "source_correction", "PB_PROVISIONING_BACKFILL", 2),
    }
    specs = []
    for i, (rule_id, (fixed_day, before)) in enumerate(FIXED_ON.items()):
        sev, title, approach, pb, approvers = catalogue[rule_id]
        raised = fixed_day - 5
        chain = [
            _e("recommended", 0),
            _e("reviewed", 1, actor=[STEWARD_A, STEWARD_B, STEWARD_C][i % 3],
               decision="accepted", reason="Confirmed and actioned."),
        ]
        chain.append(_e("approved", 2, actor=APPROVER_A, ordinal=1))
        if approvers == 2:
            chain.append(_e("approved", 2, actor=APPROVER_B, ordinal=2))
        chain += [
            # HIST-5 deliberately deviates: recommended source_correction, the
            # steward did manual_sql instead. Without at least one deviation the
            # recommendation-acceptance metric reads 100% and measures nothing --
            # which is the anchoring risk the spec flags as an open question.
            _e("executed", 3, actor=[OWNER_CRM, OWNER_PROV][i % 2],
               external_ref=f"DQ-{3100 + i * 7}",
               summary=f"{title}: corrected at source and reloaded.",
               approach=("manual_sql" if i == 4 else approach),
               playbook=(None if i == 4 else pb)),
            _e("verified", 5, passed=True),
        ]
        specs.append(CohortSpec(
            key=f"HIST-{i + 1}", raised_day=raised, rule_ids=[rule_id], severity=sev,
            hypothesis=title,
            evidence=f"{before} violations held steady across prior runs, then fell to zero after remediation.",
            recommendation=f"{title}: correct at source and reload the affected window.",
            approach_type=approach, playbook_id=pb, recommendation_source="playbook",
            blast_radius=[], chain=chain,
        ))
    # The recurrence pair: closed once, then broke again and became part of COH-D.
    fixed_day, recur_day, count = RECURRED["CTCT_PHN_FMT"]
    specs.append(CohortSpec(
        key="HIST-8", raised_day=fixed_day - 5, rule_ids=["CTCT_PHN_FMT"], severity="P3_monitor",
        hypothesis="Landline numbers loaded with inconsistent formatting",
        evidence=f"{count} violations corrected at row level and verified clean.",
        recommendation="Correct the affected rows and reload.",
        approach_type="manual_sql", playbook_id=None, recommendation_source="generated",
        blast_radius=[],
        chain=[
            _e("recommended", 0),
            _e("reviewed", 1, actor=STEWARD_C, decision="accepted",
               reason="Small volume, correcting directly."),
            _e("approved", 2, actor=APPROVER_B, ordinal=1),
            _e("executed", 3, actor=OWNER_CRM, external_ref="DQ-3040",
               summary="24 rows reformatted in the source and reloaded.",
               approach="manual_sql", playbook=None),
            _e("verified", 5, passed=True),
        ],
    ))
    return specs


def build_cohorts_and_dispositions(
    runs: pd.DataFrame, meta: dict, snaps: dict[str, Snapshot], inject_failure: bool
) -> tuple[pd.DataFrame, pd.DataFrame]:
    index, run_ids = meta["index"], meta["run_ids"]
    by_result = runs.set_index("result_id")
    cohort_rows, disp_rows = [], []

    for spec in CURRENT_COHORTS + historical_cohorts():
        raised_ts = SNAPSHOT + timedelta(days=spec.raised_day)
        cohort_id = det_uuid("cohort", spec.key)
        member_ids = [index[(spec.raised_day, rid)] for rid in spec.rule_ids]
        members = by_result.loc[member_ids]

        cohort_rows.append(dict(
            cohort_id=cohort_id,
            raised_run_id=run_ids[spec.raised_day],
            raised_ts=raised_ts,
            member_result_ids=member_ids,
            member_rule_ids=spec.rule_ids,
            member_count=len(member_ids),
            affected_tables=sorted(members.target_table.unique().tolist()),
            total_violation_rows=int(members.violation_count.sum()),
            root_cause_hypothesis=spec.hypothesis,
            evidence_summary=spec.evidence,
            blast_radius_tables=spec.blast_radius or [],
            blast_radius_count=len(spec.blast_radius or []),
            severity=spec.severity,
            business_domain=spec.business_domain,
            owner_group=spec.owner_group,
            rank_score=round(
                {"P1_block": 100, "P2_alert": 50, "P3_monitor": 20}[spec.severity]
                + len(member_ids) * 3
                + len(spec.blast_radius or []) * 5, 2),
            recommended_approach=spec.recommendation,
            recommended_approach_type=spec.approach_type,
            playbook_id=spec.playbook_id,
            recommendation_source=spec.recommendation_source,
            model_endpoint=("dq-cohort-triage" if spec.recommendation_source != "none" else None),
            # Stub. On Databricks this is the exact payload the endpoint was shown,
            # which the parent architecture doc requires be retained for audit.
            model_input_payload=json.dumps({
                "_fixture": "hand-authored, no model invoked",
                "member_rule_ids": spec.rule_ids,
                "member_violation_counts": members.violation_count.tolist(),
            }),
            triage_job_run_id=det_uuid("triagejob", str(spec.raised_day)),
            is_recurrence=spec.is_recurrence,
        ))

        seq = 0
        violations_before = int(members.violation_count.sum())
        for event_type, day_after, kw in spec.chain:
            seq += 1
            ev_ts = raised_ts + timedelta(days=day_after, hours=2 + seq)
            actor = kw.get("actor")
            if event_type == "recommended":
                identity, display, src = TRIAGE_JOB[0], TRIAGE_JOB[1], "triage_job"
            elif event_type in ("verified", "reopened"):
                identity, display, src = CHECK_RUNNER[0], CHECK_RUNNER[1], "check_runner"
            else:
                identity, display, src = actor[0], actor[1], "obo_user"

            row = dict(
                disposition_id=det_uuid("disp", cohort_id, str(seq)),
                cohort_id=cohort_id, event_seq=seq, event_type=event_type,
                event_ts=ev_ts, ingest_ts=ev_ts,
                actor_identity=identity, actor_display_name=display, actor_source=src,
                decision=kw.get("decision"), reason=kw.get("reason"),
                review_by_date=None, approver_ordinal=kw.get("ordinal"),
                executed_summary=kw.get("summary"), external_ref=kw.get("external_ref"),
                executed_ts=None, verifying_run_id=None, verification_passed=None,
                violations_before=None, violations_after=None,
                approach_type_taken=kw.get("approach"), playbook_id=kw.get("playbook"),
                event_payload=None, app_version=APP_VERSION,
            )
            if kw.get("review_by_days"):
                row["review_by_date"] = (ev_ts + timedelta(days=kw["review_by_days"])).date()
            if event_type == "executed":
                row["executed_ts"] = ev_ts
                row["event_payload"] = json.dumps({
                    "self_reported": True,
                    "note": "The register records this claim; it did not observe the execution.",
                })
            if event_type == "verified":
                vday = min(0, spec.raised_day + day_after)
                row["verifying_run_id"] = run_ids[vday]
                row["verification_passed"] = kw["passed"]
                row["violations_before"] = violations_before
                after = sum(
                    int(by_result.loc[index[(vday, rid)], "violation_count"])
                    for rid in spec.rule_ids)
                row["violations_after"] = 0 if kw["passed"] else max(after, 1)
            disp_rows.append(row)

        if inject_failure and spec.key == "COH-A":
            # Deliberate control breach for testing v_disposition_integrity. COH-A is
            # P1 and needs two DISTINCT approvers; rewrite its second approval so both
            # come from the same identity. Adding a third row would not breach anything
            # -- the control is on distinct identities, not on row count, which is
            # exactly the confusion this test exists to catch.
            second = [d for d in disp_rows
                      if d["cohort_id"] == cohort_id
                      and d["event_type"] == "approved"
                      and d["approver_ordinal"] == 2]
            for d in second:
                d["actor_identity"] = APPROVER_A[0]
                d["actor_display_name"] = APPROVER_A[1]
                d["event_payload"] = json.dumps(
                    {"_injected": "same identity approving twice, for integrity testing"})

    return pd.DataFrame(cohort_rows), pd.DataFrame(disp_rows)


def enrich_playbook(disp: pd.DataFrame) -> pd.DataFrame:
    """Derive prior_use_count / recurrence_rate from the register, as the triage job would."""
    pb = pd.DataFrame(PLAYBOOK)
    used = disp[disp.event_type == "executed"].playbook_id.value_counts()
    pb["prior_use_count"] = pb.playbook_id.map(used).fillna(0).astype(int)
    # Only CTCT_PHN_FMT recurred, and it was actioned without a playbook entry, so
    # every playbook approach legitimately shows zero recurrence on this fixture.
    pb["recurrence_count"] = 0
    pb["recurrence_rate"] = 0.0
    last = disp[disp.event_type == "executed"].groupby("playbook_id").event_ts.max()
    pb["last_used_ts"] = pb.playbook_id.map(last)
    pb["created_by"] = STEWARD_A[0]
    pb["created_at"] = SNAPSHOT - timedelta(days=200)
    return pb


# ---------------------------------------------------------------------------
# Derived view, mirroring sql/ddl/08_views.sql
# ---------------------------------------------------------------------------

def cohort_current(cohort: pd.DataFrame, disp: pd.DataFrame) -> pd.DataFrame:
    """Python twin of v_cohort_current.

    It exists so the local app and the deployed app show the same lifecycle_state.
    If these two ever disagree, the SQL view is right and this is wrong -- it is the
    copy, not the original.
    """
    out = []
    for _, c in cohort.iterrows():
        ev = disp[disp.cohort_id == c.cohort_id].sort_values("event_seq")
        approvals = ev[ev.event_type == "approved"]
        distinct_approvers = approvals.actor_identity.nunique()
        required = 2 if c.severity == "P1_block" else 1
        reviews = ev[ev.event_type == "reviewed"]
        latest_decision = reviews.decision.iloc[-1] if len(reviews) else None
        verifies = ev[ev.event_type == "verified"]
        last_passed = bool(verifies.verification_passed.iloc[-1]) if len(verifies) else None
        reopens = int((ev.event_type == "reopened").sum())
        executed = ev[ev.event_type == "executed"]
        last_event = ev.event_type.iloc[-1] if len(ev) else None

        if len(ev) == 0:
            state = "awaiting_triage"
        elif last_passed is True:
            state = "closed_verified"
        elif reopens and last_event in ("reopened", "verified"):
            state = "reopened"
        elif latest_decision == "rejected":
            state = "closed_rejected"
        elif latest_decision == "no_action":
            state = "closed_no_action"
        elif latest_decision == "deferred":
            state = "deferred"
        elif len(executed):
            state = "awaiting_verification"
        elif distinct_approvers >= required:
            state = "approved_awaiting_execution"
        elif latest_decision == "accepted":
            state = "awaiting_approval"
        else:
            state = "awaiting_review"

        verified_ts = verifies.event_ts.iloc[-1] if len(verifies) else None
        mttr = ((verified_ts - c.raised_ts).total_seconds() / 86400.0
                if last_passed is True else None)
        taken = executed.approach_type_taken.iloc[-1] if len(executed) else None
        out.append(dict(
            cohort_id=c.cohort_id, raised_ts=c.raised_ts, severity=c.severity,
            business_domain=c.business_domain, owner_group=c.owner_group,
            member_count=c.member_count, total_violation_rows=c.total_violation_rows,
            recommendation_source=c.recommendation_source, rank_score=c.rank_score,
            lifecycle_state=state, distinct_approvers=distinct_approvers,
            approvals_required=required, reopen_count=reopens,
            latest_decision=latest_decision,
            review_by_date=(reviews.review_by_date.iloc[-1] if len(reviews) else None),
            approach_type_taken=taken,
            recommendation_followed=(None if taken is None
                                     else taken == c.recommended_approach_type),
            violations_before=(verifies.violations_before.iloc[-1] if len(verifies) else None),
            violations_after=(verifies.violations_after.iloc[-1] if len(verifies) else None),
            mttr_days=(round(mttr, 2) if mttr is not None else None),
            is_recurrence=c.is_recurrence,
        ))
    return pd.DataFrame(out)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(OUT), help="output directory (default: ./out)")
    ap.add_argument("--inject-control-failure", action="store_true",
                    help="add a duplicate-approver row so v_disposition_integrity has "
                         "something to catch. Off by default: the clean fixture should "
                         "return zero findings.")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    ctx = load_ctx()
    snaps = evaluate_all(ctx)
    registry = build_rule_registry()
    runs, samples, meta = build_runs(snaps)
    cohort, disp = build_cohorts_and_dispositions(runs, meta, snaps, args.inject_control_failure)
    playbook = enrich_playbook(disp)
    current = cohort_current(cohort, disp)

    tables = {
        "config.rule_registry": registry,
        "config.playbook": playbook,
        "results.check_run": runs,
        "results.violation_sample": samples,
        "results.cohort": cohort,
        "results.disposition": disp,
        "results.v_cohort_current": current,
    }
    for name, df in tables.items():
        df.to_parquet(out / f"{name}.parquet", index=False)

    report(tables, snaps, out)


def report(tables: dict[str, pd.DataFrame], snaps: dict[str, Snapshot], out: Path) -> None:
    runs, cohort, disp = tables["results.check_run"], tables["results.cohort"], tables["results.disposition"]
    current = tables["results.v_cohort_current"]
    final = runs[runs.run_ts == SNAPSHOT]
    breaches = final[final.status == "breach"]

    print(f"\nWrote {len(tables)} tables to {out}\n")
    print(f"{'TABLE':34} {'ROWS':>7}")
    print("-" * 42)
    for name, df in tables.items():
        print(f"{name:34} {len(df):>7,}")

    print(f"\nFINAL RUN  {SNAPSHOT:%Y-%m-%d}  ({len(rules.RULES)} rules)")
    print("-" * 78)
    for _, r in final.sort_values(["status", "violation_count"], ascending=[True, False]).iterrows():
        flag = {"breach": "BREACH", "pass": "pass", "skipped": "shadow"}[r.status]
        print(f"  {r.rule_id:26} {r.severity:11} {flag:7} {r.violation_count:>6,} / {r.rows_scanned:,}")

    print("\nCOHORTS")
    print("-" * 78)
    key_of = {det_uuid("cohort", s.key): s.key for s in CURRENT_COHORTS + historical_cohorts()}
    for _, c in current.sort_values("raised_ts").iterrows():
        print(f"  {key_of[c.cohort_id]:8} {c.raised_ts:%Y-%m-%d}  {c.severity:11} "
              f"{c.lifecycle_state:28} {c.member_count} rules  "
              f"approvers {c.distinct_approvers}/{c.approvals_required}")

    # --- the spec's own metrics, computed from the fixture -------------------
    n_cohorts = len(cohort)
    n_breaches = len(breaches)
    closed = current[current.lifecycle_state == "closed_verified"]
    with_disposition = current[current.lifecycle_state != "awaiting_review"]
    followed = current.recommendation_followed.dropna()

    print("\nSCORECARD  (spec target in brackets)")
    print("-" * 78)
    n_open = len(CURRENT_COHORTS)
    print(f"  Cohort compression      {n_breaches / n_open:>6.1f}:1   "
          f"[>=5:1]   {n_breaches} breaches on the final run grouped into {n_open} cohorts "
          f"({n_cohorts} raised across the whole window)")
    print(f"  Disposition coverage    {len(with_disposition) / n_cohorts * 100:>6.1f}%   [>=90%]")
    print(f"  Recommendation accepted {followed.mean() * 100:>6.1f}%   [>=50%]   "
          f"({int(followed.sum())} of {len(followed)} executed cohorts followed the recommendation)")
    print(f"  Closure rate            {len(closed) / n_cohorts * 100:>6.1f}%   [>=75%]")
    print(f"  MTTR (verified closed)  {closed.mttr_days.mean():>6.1f}d   [<5d P1, <15d P2]")
    print(f"  Recurrence in window    {int(current.is_recurrence.sum())} cohort   [<10% at 30d]   "
          f"CTCT_PHN_FMT closed then re-breached 13 days later")

    print("\nREAD THIS BEFORE QUOTING THE COMPRESSION NUMBER")
    print("-" * 78)
    print(textwrap_fill(
        f"Compression is {n_breaches / n_open:.1f}:1 against the {n_open} current cohorts, short of the "
        f"spec's >=5:1 target. That is a property of the pilot, not of the grouping: the "
        f"target assumes something like the 12-table blast radius in the spec's worked "
        f"example, and this dataset has two tables. COH-A on its own compresses 9 breaches "
        f"into 1. Do not tune the cohorting to hit 5:1 on two tables -- re-measure once more "
        f"tables are onboarded."))
    print()
    print(textwrap_fill(
        "Nine rules pass and two are in shadow. That is deliberate. A fixture where "
        "everything breaches cannot exercise the pass path and gives closure rate no "
        "denominator."))
    print()


def textwrap_fill(s: str, width: int = 78) -> str:
    import textwrap
    return textwrap.fill(" ".join(s.split()), width=width, initial_indent="  ",
                         subsequent_indent="  ")


if __name__ == "__main__":
    main()

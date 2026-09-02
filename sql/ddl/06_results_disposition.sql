-- disposition — THE AUDIT REGISTER
--
-- Substitute {catalog} before execution.
--
-- The second new table, and the only one the app writes. Read the spec's line on
-- this before changing anything here:
--
--     "Writes are INSERT only. Any attempt to model this as an updatable status
--      column is a design defect."
--
-- So: no status column, no closed_ts, no current_state, no last_updated. A
-- correction is a new row with a higher event_seq, never an edit. The sequence
-- itself is the evidence. Where a cohort has got to is a view over this table
-- (08_views.sql), computed at read time.
--
-- APPEND-ONLY IS ENFORCED BY delta.appendOnly, NOT BY THE GRANT. This matters and
-- the spec is imprecise about it. Unity Catalog has no INSERT-only privilege — the
-- finest-grained write privilege on a table is MODIFY, which also permits UPDATE,
-- DELETE and MERGE. The spec's phrase "granted INSERT on dq.results" is therefore
-- not directly expressible. The enforceable equivalent is the pair:
--     (a) MODIFY on this table only, nothing else in dq.results   [07_grants.sql]
--     (b) delta.appendOnly = true on this table                   [below]
-- With (b) set, UPDATE and DELETE fail for every principal including the owner.
-- Clearing the property is itself recorded in Delta history, so the bypass is
-- detectable. See sql/README.md for what to tell an auditor.
--
-- EVENT-SPECIFIC FIELDS ARE NULLABLE, PLUS A PAYLOAD. Five event types with
-- different content, in one table, because the ordering across types is the whole
-- point and separate tables would destroy it. Typed columns exist for the fields
-- that are queried (decision, approver identity, verification counts); everything
-- else goes in event_payload as JSON.

CREATE TABLE IF NOT EXISTS {catalog}.results.disposition (
  disposition_id      STRING    NOT NULL COMMENT 'uuid, unique per event row',
  cohort_id           STRING    NOT NULL COMMENT 'the cohort this event is about',
  event_seq           INT       NOT NULL COMMENT 'monotonic per cohort starting at 1. Gaps are acceptable; reuse is not',
  event_type          STRING    NOT NULL COMMENT 'recommended | reviewed | approved | executed | verified | reopened',
  event_ts            TIMESTAMP NOT NULL COMMENT 'when the event happened',
  ingest_ts           TIMESTAMP NOT NULL COMMENT 'when the row was written. Differs from event_ts for self-reported execution',

  actor_identity      STRING             COMMENT 'the acting principal. For in-app events this is the OBO user, never a typed-in name',
  actor_display_name  STRING             COMMENT 'human-readable name for rendering; identity above is the one that counts',
  actor_source        STRING    NOT NULL COMMENT 'obo_user | service_principal | triage_job | check_runner. How we know who acted',

  decision            STRING             COMMENT 'reviewed only: accepted | deferred | rejected | no_action',
  reason              STRING             COMMENT 'reviewed and reopened: why. Required for deferred and rejected',
  review_by_date      DATE               COMMENT 'reviewed/deferred only: when the cohort resurfaces. Required when decision = deferred',

  approver_ordinal    INT                COMMENT 'approved only: 1 or 2. One ROW per approver — two approvers are two rows, never one row with two names',

  executed_summary    STRING             COMMENT 'executed only: what the owner reports they did',
  external_ref        STRING             COMMENT 'executed only: ticket id or job run reference in the owners own system',
  executed_ts         TIMESTAMP          COMMENT 'executed only: when the owner says it happened. A CLAIM — see the constraint note below',

  verifying_run_id    STRING             COMMENT 'verified only: the check_run that decided it',
  verification_passed BOOLEAN            COMMENT 'verified only: TRUE closes the cohort, FALSE is followed by a reopened row',
  violations_before   BIGINT             COMMENT 'verified only: member violation total at raise time',
  violations_after    BIGINT             COMMENT 'verified only: member violation total at verification',

  approach_type_taken STRING             COMMENT 'the approach actually used, for recommendation-acceptance scoring against cohort.recommended_approach_type',
  playbook_id         STRING             COMMENT 'the playbook entry actually followed, if any',

  event_payload       STRING             COMMENT 'JSON for anything not typed above. Do not put queryable fields here to avoid a schema change',
  app_version         STRING             COMMENT 'which build of the app wrote this, so a behavioural bug can be scoped to a date range'
)
USING DELTA
CLUSTER BY (cohort_id, event_seq)
COMMENT 'Append-only event log: recommended -> reviewed -> approved -> executed -> verified. Never updated, never deleted. The sequence is the audit evidence. delta.appendOnly is the enforcement — see 07_grants.sql for why the grant alone cannot express it.'
TBLPROPERTIES (delta.appendOnly = true);

ALTER TABLE {catalog}.results.disposition
  ADD CONSTRAINT disposition_event_type_enum
  CHECK (event_type IN ('recommended', 'reviewed', 'approved', 'executed', 'verified', 'reopened'));

ALTER TABLE {catalog}.results.disposition
  ADD CONSTRAINT disposition_actor_source_enum
  CHECK (actor_source IN ('obo_user', 'service_principal', 'triage_job', 'check_runner'));

ALTER TABLE {catalog}.results.disposition
  ADD CONSTRAINT disposition_event_seq_positive
  CHECK (event_seq >= 1);

ALTER TABLE {catalog}.results.disposition
  ADD CONSTRAINT disposition_decision_enum
  CHECK (decision IS NULL OR decision IN ('accepted', 'deferred', 'rejected', 'no_action'));

-- A review that rejects or defers without a reason is not a disposition, it is silence.
ALTER TABLE {catalog}.results.disposition
  ADD CONSTRAINT disposition_reason_required
  CHECK (decision IS NULL OR decision NOT IN ('deferred', 'rejected') OR (reason IS NOT NULL AND length(trim(reason)) > 0));

-- A deferral without a resurface date is a disappearance.
ALTER TABLE {catalog}.results.disposition
  ADD CONSTRAINT disposition_deferral_has_date
  CHECK (decision IS NULL OR decision <> 'deferred' OR review_by_date IS NOT NULL);

-- Every in-app event must carry an identity, and it must come from the platform.
ALTER TABLE {catalog}.results.disposition
  ADD CONSTRAINT disposition_human_events_have_identity
  CHECK (event_type NOT IN ('reviewed', 'approved', 'executed') OR (actor_identity IS NOT NULL AND actor_source = 'obo_user'));

-- WHAT CANNOT BE A TABLE CONSTRAINT, AND SO MUST BE TESTED IN CODE
--
-- "A cohort cannot reach approved without the required number of DISTINCT approver
-- identities" is a statement about a SET of rows. A Delta CHECK constraint sees one
-- row at a time and cannot express it. Two approver rows with the same
-- actor_identity will insert happily.
--
-- Enforcement therefore lives in two places, and needs both:
--   1. The approval gate in the app's domain layer, unit-tested, which refuses to
--      write the second row when the identity matches the first.
--   2. The audit query in 08_views.sql (v_disposition_integrity), which finds any
--      cohort that reached approved on fewer than the required distinct identities.
--      Run it on a schedule; a non-empty result is a control failure, not a warning.
--
-- Do not delete (2) on the grounds that (1) exists. (1) is the control; (2) is the
-- evidence that (1) held.

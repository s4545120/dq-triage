-- CDE onboarding views — where each element proposal has got to, derived and never stored
--
-- Substitute {catalog} before execution. Runs after 17, which creates the tables this
-- reads, and after 09.
--
-- Same discipline as 16: the app keeps a labelled pandas copy
-- (dq_app/domain/elements.py `proposal_state`) because a decision recorded in a
-- session has to move the page before any warehouse re-runs this.
--
-- APPLIED IS READ OFF THE REGISTER. The onboarding job starts the note on every version
-- it writes for a proposal with "[cde_proposal <proposal_id>]", so whether a proposal
-- has reached the register is a fact about the register, not a flag anyone sets. The
-- job reads the same marker to stay idempotent.

CREATE OR REPLACE VIEW {catalog}.config.v_cde_proposal_current
COMMENT 'Every CDE proposal with its decision and, once applied, the register version it became. state: open | approved | applied | rejected.'
AS
WITH a AS (
  SELECT regexp_extract(note, '^\\[cde_proposal ([^\\]]+)\\]', 1) AS proposal_id,
         min(cde_version) AS applied_version
  FROM   {catalog}.config.cde_registry
  WHERE  note LIKE '[cde_proposal %'
  GROUP BY 1
)
SELECT p.*,
       r.decision, r.reviewed_by, r.reviewed_at, r.reason AS review_reason,
       a.applied_version,
       CASE
         WHEN r.decision IS NULL            THEN 'open'
         WHEN r.decision = 'rejected'       THEN 'rejected'
         WHEN a.applied_version IS NOT NULL THEN 'applied'
         ELSE 'approved'
       END AS state
FROM   {catalog}.config.cde_proposal p
LEFT JOIN {catalog}.config.cde_review r ON r.proposal_id = p.proposal_id
LEFT JOIN a ON a.proposal_id = p.proposal_id;

-- One-off for workspace.dq_triage, 2026-10-01. NOT generated.
-- migrate_cde_scope.sql part 1 (as applied) copied CDE_CUST_EMAIL's bindings forward from v1,
-- which predates the EML_STTS_CD binding. This appends v3 with the fixture's bindings.
-- The generator is fixed; a fresh workspace does not need this file.
-- Guard: EXPECTED max(cde_version) = 2 before running, 3 after.
SELECT max(cde_version) FROM workspace.dq_triage.dq_config_cde_registry WHERE cde_id = 'CDE_CUST_EMAIL';

INSERT INTO workspace.dq_triage.dq_config_cde_registry (cde_id, cde_version, cde_name, business_term, data_class, definition, expected_signature, criticality, pii, regulatory_basis, tolerance_pct, bindings, business_domain, owner_group, status, effective_from, registered_by, registered_at, note)
SELECT cde_id, cde_version + 1, cde_name, business_term, data_class, definition,
       expected_signature, criticality, pii, regulatory_basis,
       0.5,
       array(named_struct('target_table', 'workspace.dq_triage.dq_mock_ctct_c', 'target_column', 'EML_ID', 'populated_when', NULL, 'expected_scope_filter', NULL, 'binding_status', 'bound', 'discovered_by', 'manual', 'confidence', 1.0), named_struct('target_table', 'workspace.dq_triage.dq_mock_ctct_c', 'target_column', 'EML_STTS_CD', 'populated_when', NULL, 'expected_scope_filter', NULL, 'binding_status', 'bound', 'discovered_by', 'manual', 'confidence', 1.0)),
       business_domain, owner_group, status,
       current_timestamp(), current_user(), current_timestamp(),
       'v3: binds EML_STTS_CD. The fixture registers the email status code as a binding of this element, which is what attaches CTCT_EML_STTS_NOT_NULL and CTCT_EML_STTS_CONSISTENT to it; the binding was added after this workspace was seeded, and v2 (migrate_cde_scope.sql part 1) copied bindings forward from v1 so it never arrived. Same element, same tolerance; one binding more.'
FROM   workspace.dq_triage.dq_config_cde_registry
WHERE  cde_id = 'CDE_CUST_EMAIL'
  AND  cde_version = (SELECT max(cde_version) FROM workspace.dq_triage.dq_config_cde_registry WHERE cde_id = 'CDE_CUST_EMAIL');

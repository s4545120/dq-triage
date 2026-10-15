-- =====================================================================
-- 00_preflight.sql — read-only apart from two probe objects it drops again.
-- target: sdpt_data_trnf.udp_brnz, prefix dq_
--
-- Run in the SQL editor, statement by statement. Every one should succeed. A
-- failure tells you which later step cannot run, before anything is created.
-- =====================================================================

-- 0a — who you are, and that the schema exists.
SELECT current_user() AS me, current_catalog() AS catalog_now;
DESCRIBE SCHEMA sdpt_data_trnf.udp_brnz;

-- 0b — you can create a view and a function here. 01_ddl.sql creates both; without
-- CREATE FUNCTION no rule that calls a helper can run.
CREATE OR REPLACE VIEW sdpt_data_trnf.udp_brnz.dq_probe_v AS SELECT 1 AS x;
CREATE OR REPLACE FUNCTION sdpt_data_trnf.udp_brnz.dq_probe_f(a INT) RETURNS INT RETURN a + 1;
SELECT sdpt_data_trnf.udp_brnz.dq_probe_f(1) AS should_be_2;
DROP VIEW sdpt_data_trnf.udp_brnz.dq_probe_v;
DROP FUNCTION sdpt_data_trnf.udp_brnz.dq_probe_f;

-- 0c — nothing of ours is here yet. EXPECTED: zero rows. If rows come back the DDL
-- has run before: 01_ddl.sql is NOT re-runnable (ADD CONSTRAINT fails a second
-- time), so skip it, or use a fresh schema.
SELECT table_name FROM sdpt_data_trnf.information_schema.tables
WHERE  table_schema = 'udp_brnz' AND table_name LIKE 'dq_%' ORDER BY 1;

-- 0d — the five source tables are readable. EXPECTED: five rows, each with rows > 0.
-- A permission error here means every check on that table will be recorded as an
-- error: ask for USE CATALOG / USE SCHEMA / SELECT on it before going further.
SELECT 'prod.udp_brnz_nrt_tech_view.table_address_hist' AS source_table, COUNT(*) AS `rows` FROM prod.udp_brnz_nrt_tech_view.table_address_hist
UNION ALL
SELECT 'prod.udp_brnz_nrt_tech_view.table_bus_org_hist' AS source_table, COUNT(*) AS `rows` FROM prod.udp_brnz_nrt_tech_view.table_bus_org_hist
UNION ALL
SELECT 'prod.udp_brnz_nrt_tech_view.table_contact_hist' AS source_table, COUNT(*) AS `rows` FROM prod.udp_brnz_nrt_tech_view.table_contact_hist
UNION ALL
SELECT 'prod.udp_brnz_nrt_tech_view.table_contact_role_hist' AS source_table, COUNT(*) AS `rows` FROM prod.udp_brnz_nrt_tech_view.table_contact_role_hist
UNION ALL
SELECT 'prod.udp_brnz_nrt_tech_view.table_customer_hist' AS source_table, COUNT(*) AS `rows` FROM prod.udp_brnz_nrt_tech_view.table_customer_hist;

-- 0e — the columns 05_current_records.sql reads. EXPECTED: zero rows (none missing).
-- A row means that table has no CDC columns of that name: drop its INSERT from 05
-- and its checks will read every version of every record.
WITH need AS (SELECT t, c FROM VALUES ('prod.udp_brnz_nrt_tech_view.table_address_hist', 'ECF_NSRT_TS'), ('prod.udp_brnz_nrt_tech_view.table_address_hist', 'SCN'), ('prod.udp_brnz_nrt_tech_view.table_address_hist', 'offset'), ('prod.udp_brnz_nrt_tech_view.table_address_hist', 'OP_TYPE'), ('prod.udp_brnz_nrt_tech_view.table_address_hist', 'OBJID'), ('prod.udp_brnz_nrt_tech_view.table_bus_org_hist', 'ECF_NSRT_TS'), ('prod.udp_brnz_nrt_tech_view.table_bus_org_hist', 'SCN'), ('prod.udp_brnz_nrt_tech_view.table_bus_org_hist', 'offset'), ('prod.udp_brnz_nrt_tech_view.table_bus_org_hist', 'OP_TYPE'), ('prod.udp_brnz_nrt_tech_view.table_bus_org_hist', 'OBJID'), ('prod.udp_brnz_nrt_tech_view.table_contact_hist', 'ECF_NSRT_TS'), ('prod.udp_brnz_nrt_tech_view.table_contact_hist', 'SCN'), ('prod.udp_brnz_nrt_tech_view.table_contact_hist', 'offset'), ('prod.udp_brnz_nrt_tech_view.table_contact_hist', 'OP_TYPE'), ('prod.udp_brnz_nrt_tech_view.table_contact_hist', 'CONTACT_ID'), ('prod.udp_brnz_nrt_tech_view.table_contact_role_hist', 'ECF_NSRT_TS'), ('prod.udp_brnz_nrt_tech_view.table_contact_role_hist', 'SCN'), ('prod.udp_brnz_nrt_tech_view.table_contact_role_hist', 'offset'), ('prod.udp_brnz_nrt_tech_view.table_contact_role_hist', 'OP_TYPE'), ('prod.udp_brnz_nrt_tech_view.table_contact_role_hist', 'OBJID'), ('prod.udp_brnz_nrt_tech_view.table_customer_hist', 'ECF_NSRT_TS'), ('prod.udp_brnz_nrt_tech_view.table_customer_hist', 'SCN'), ('prod.udp_brnz_nrt_tech_view.table_customer_hist', 'offset'), ('prod.udp_brnz_nrt_tech_view.table_customer_hist', 'OP_TYPE'), ('prod.udp_brnz_nrt_tech_view.table_customer_hist', 'OBJID') AS v(t, c))
SELECT n.t AS source_table, n.c AS missing_column FROM need n
LEFT ANTI JOIN system.information_schema.columns s
  ON concat_ws('.', s.table_catalog, s.table_schema, s.table_name) = n.t
 AND lower(s.column_name) = lower(n.c)
ORDER BY 1, 2;

-- 0f — not a query: check Serving > Endpoints shows system.ai.gpt-oss-120b as Ready. Both
-- notebooks call it. If it is missing, change MODEL_NAME in both notebooks; the
-- triage task would otherwise fail AFTER the checks have written, which is safe.

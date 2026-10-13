"""The key attribute register and its migration rules.

Real, not mocked: every attribute comes from the in-scope rows of the '#1 - DQ Issues'
sheet of DQ_ATTR_PRIORI.xlsx, and every rule from the migration-scope DQ analysis
(dq_analysis_migration_scope_attributes_masked.pdf, 2026-10). They point at the real
source tables (prod.udp_brnz_nrt_tech_view.*), which this workspace cannot read.

"Key attribute" is the app's word since 2026-10-12. The tables still say cde: the
register is config.cde_registry and an attribute's id goes in cde_id.
"""

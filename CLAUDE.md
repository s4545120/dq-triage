# DQ Triage Agent

Cohort triage, recommendation and an audit register on top of an existing DQ detection
stack. Databricks Apps + Streamlit, Unity Catalog, Lakeflow.

- **Spec (authoritative):** `dq-triage-agent-spec.md` v1.0, 2026-09-01, plus
  **Addendum A — Critical data elements** (v1.1 draft, 2026-09-07) at the foot of the
  same file. The addendum is additive: nothing in v1.0 changed.
- **Architecture:** `dq-architecture-diagram.md`

**The one claim the whole design makes:** nothing in this system writes business data.
The app's only writes are its own append-only audit register and shadow→active rule
promotion. Production tables are read by the check runner and written by nobody here.
Most of the rules below exist to keep that claim true.

Still exactly two writes after the CDE work: the register is seeded and read-only in
the app, so `sql/ddl/07_grants.sql` is unchanged. If someone asks for in-app CDE
registration, that is a third `MODIFY` grant and a decision, not a UI change.

## Current state — read before editing anything

| Path | Status |
|---|---|
| `sql/ddl/` | Current. Spec v1.0 + Addendum A. **Never executed** — no workspace access yet. |
| `fixtures/` | Current. Local Parquet dataset generated from the pilot CSVs. Verified. |
| `dq-app/` | Current. Spec v1.0, redesigned 2026-09-16, runs on the fixture. Never run against a workspace. |

### The interface was redesigned on 2026-09-16

Eight nav entries became five, and two of the eight were deleted outright rather than
moved. Nothing about the data model, the grants or the write path changed.

| Was | Now |
|---|---|
| `cohort_queue.py` | `triage.py` — "Cohorts" is our word for it, not the steward's |
| `cohort_detail.py` | `triage_detail.py` — five tabs became three blocks |
| `monitored_tables.py` | `tables.py` |
| `monitor_detail.py` | `table_detail.py` |
| `cde_registry.py` | **deleted** — folded into two panels on the scorecard |

**`app.py` registers seven pages and links five.** `table_detail` and `triage_detail`
are drill-downs: neither means anything without a selection made on the page above it,
so neither is in the sidebar. They stay registered because `st.switch_page` can only
reach a page `st.navigation` knows about — which is why the nav is asked to render
nothing (`position="hidden"`) and `app.py` builds the sidebar itself from
`st.page_link`. Adding a page to `PAGES` therefore does not put it in the sidebar;
`SIDEBAR` does, and `tests/test_pages_render.py` pins both halves of that.

**Deleting the CDE page did not delete the CDE model.** `config.cde_registry`,
`results.cde_profile` and `v_cde_coverage` are untouched, and so is every test pinned
to them — the scorecard's quality figure still has the register for a denominator.
What went is the browsing surface. What replaced it: the `Scope · 10 CDEs` button in
the filter strip opens a panel listing every element, and the issue board's `Review`
opens one element in place instead of switching page. The cross-table attachment
assertion that used to live in the CDE page's tests moved to the check panel.

**The scorecard gained a drill-down.** Selecting a failing check opens a panel with
the rule in plain words, the arithmetic, and the rows that actually failed —
`results.violation_sample`, parsed into real columns by
`components.sample_rows_frame`. Those samples were always captured; until now the only
way to see them was from inside a cohort. `_check_pick` in session state is what the
panel reads, so the selection survives a rerun the table did not cause — and a test
can open a check without simulating a click.

**The four dimension cards are gone.** Completeness / Validity / Consistency /
Uniqueness became a `Group by dimension` toggle on the failing-checks table. The prose
and `_DIMENSION_OF` survived the move; the cards did not. In their place is a row of
six counts of the estate — see the next section for the denominator that comes with
them.

**`metrics.records_affected_floor` is a floor and must stay labelled as one.**
`check_run` stores a violation count and no keys, and the runner caps
`violation_sample` per check, so four of the failing checks are truncated and no exact
distinct count exists. The tile reads `≥ 600`. Making it exact is a change to the
runner, not to the app: a `distinct_entity_count` column would make each check exact
without making the union computable across checks; only a stored key set or a
union-able sketch answers the question the tile asks. Two tests assert the floor is a
floor.

**The palette is "Indigo signal".** `theme.py` moved off petrol teal onto an indigo
accent. One change there is not cosmetic: `TONE["moderate"]` was amber and is now a
cool teal, because amber never had enough contrast on a light ground and "monitor" is
informational rather than a warning. `SEVERITY_TONE` is untouched — `P3_monitor ->
moderate` still holds; only what `moderate` looks like changed.

### `dq-app/` was rewritten to v1.0 on 2026-09-02

The v0.1 execution app is gone: `executor.py`, `states.py`, the `incidents` table with
its mutable `state` column, the `fix_registry` with an executable `fix_body`, and the
free-text approver field were all deleted rather than adapted. What survived is what was
worth keeping — the adapter seam, `theme.py`, and the pure-logic-in-`domain/` discipline.

It reads `fixtures/out/*.parquet` through `dq_app/data/local_source.py`, selected by
`DQ_APP_DATA_SOURCE=local` (the default). `databricks_source.py` is rewritten to the v1.0
tables and, like `sql/ddl/`, has never been executed.

```bash
cd dq-app && ../.venv/bin/streamlit run app.py     # local, no workspace
cd dq-app && ../.venv/bin/python -m pytest tests -q
```

**The app's Python copy of `v_cohort_current` is pinned by a test.** `domain/lifecycle.py`
folds the event log into current state because a session-recorded event has to appear in
the queue before any warehouse could re-run the view. `tests/test_lifecycle_conformance.py`
asserts that fold reproduces the shipped `results.v_cohort_current.parquet` row for row.
Change the view in `sql/ddl/08_views.sql` and that test tells you whether the copy kept up.

**The CDE component was added on 2026-09-07.** `config.cde_registry` (09) and
`results.cde_profile` (10) are new tables; `11_views_cde.sql` adds
`v_cde_registry_current` and `v_cde_coverage`; `config.rule_registry` gained a
nullable `cde_id`. `fixtures/cdes.py` declares ten elements over twelve columns,
`fixtures/profile.py` profiles them from the pilot CSVs, and `fixtures/coverage.py`
is the fixture-side twin of the coverage view. The app reads all of it through the
adapter and writes none of it.

**`v_cde_coverage` has a Python twin too, pinned the same way.** `domain/coverage.py`
recomputes it rather than reading the shipped parquet, because promoting a shadow
rule changes what is covered and the panel has to say so in-session.
`tests/test_coverage_conformance.py` asserts the fold reproduces
`results.v_cde_coverage.parquet` column for column. Change `11_views_cde.sql` and
that test tells you whether the copy kept up.

**Local writes are session-only.** `fixtures/out/` is generated and gated by `verify.py`,
so the app never edits it. Events recorded in the UI live in `st.session_state`.

**The deployed app is the fixture with a URL.** `dq-app/app.yaml` sets
`DQ_APP_DATA_SOURCE=local`, so a Databricks App deploy reads mock data and reaches no
catalog at all. Only `dq-app/` ships, and `fixtures/out/` is gitignored and sits above
it, so there is a committed copy at `dq-app/dq_app/fixture_data/` — the one place
generated fixture output is checked in, and it exists because nothing else can reach
the container. `local_source.fixture_dir()` prefers `fixtures/out/` and falls back to
the bundle. Rebuild the fixture and you must `cp out/*.parquet` over the bundle;
`dq-app/tests/test_bundled_fixture.py` compares them byte for byte and fails if you
forget. Workspace mode is still never-executed: see the commented block in `app.yaml`.

## Invariants — things that look like bugs and are not

**Execution is the defining non-goal.** No `UPDATE`/`MERGE`/`DELETE` on business data, no
job triggering, no execute button. `config.playbook` deliberately has no `fix_body`,
`fix_sql`, `job_id` or `notebook_path` — a body column is the first step to an execute
button. If someone asks for one, that is a scope change to escalate, not a schema change.

**`results.disposition` is an event log, not a status column.** Append-only, enforced by
`delta.appendOnly = true`. A correction is a new row with a higher `event_seq`, never an
edit. `config.rule_registry` is append-only for the same reason, which is why it has no
stored `effective_to`. Current state for both is derived at read time in
`sql/ddl/08_views.sql` — that view is the single definition; the Python twin in
`fixtures/build_fixtures.py` is labelled as the copy.

**Two rules in `fixtures/rules.py` are deliberately unscoped and must stay broken:**
`SUBS_IMEI_NOT_NULL` and `SUBS_PRIM_ACCT_NOT_ZERO`. They report 700 false breaches (all
Fixed Broadband / prepaid rows that legitimately lack the column). They are the worked
example behind cohort COH-B, whose root cause is a rule defect rather than a data defect.
Their correctly-scoped twins — `SUBS_SIM_NOT_NULL`, `SUBS_BILL_OFFR_NOT_ZERO` — return
zero on the same data. Adding a `scope_filter` to the first pair destroys the demo.

**The CDE register does not fix those two rules — it proves they are wrong.** The
bindings for `IMEI_ID` and `PRIM_ACCT_KEY` declare the `expected_scope_filter` the
rules should have had, and `v_cde_coverage` reports a `scope_mismatch` naming each
rule. That is the whole point: COH-B's root cause becomes an assertion the model
makes rather than something a human noticed. Adding `scope_filter` to the rules
themselves still destroys the demo, and now also empties the scope_mismatch bucket
that `tests/test_coverage_conformance.py` asserts is non-empty.

**Quality scores count only CDE-attached checks. Inventory counts do not.** Two
denominators, deliberately, and each is stated where it sits.

*Scoped to the 20 rules `v_cde_coverage` attached to a registered element:* the
scorecard's headline quality figure and its Recent runs rail; every figure on
`ui/pages/tables.py` and `table_detail.py` — the monitor inventory, applied rules, the
per-table score. The scorecard applies the filter itself; the two monitor pages get it
from `ui/monitoring.domain_filter`, which is the only other place the filter is
written. The reason is the denominator: a quality score over "every rule someone
happened to write" moves whenever the rule set does, and cannot be compared across two
months or two domains. `domain/coverage.attached_rule_ids` is the single definition of
that set and is read back off the coverage view — never re-derived by matching table
and column, which would silently drop `XREF_NAME_AGREEMENT` (two tables, no
`target_column`, attaches only through its `cde_id` tag).

*Unscoped, counting the whole run:* the scorecard's six estate tiles and its
failing-checks table. Reporting "2 tables monitored" over only the attached checks
understates the estate, and a diagnostic table that hides 14 of 34 failing checks
would disagree with the Triage queue, which is where those checks get worked. The
tiles carry "What is being watched · every check that ran" above them; the quality
figure carries its scope in the strip beside it.

The scoping is drawn, not implied: the monitor pages carry a `10 CDEs` badge in the
filter strip and the scorecard a `Scope · 10 CDEs` button that opens the element list,
because a diagnostic page that quietly hides 14 of 34 checks is worse than one that
shows fewer and says so.

Consequences a reader will otherwise trip over: the scorecard's quality figure is
built on 20 checks while the tiles beside it say 34 ran; neither shadow rule is
CDE-attached, so the shadow count in any scoped figure is always 0; and three cohorts
have no CDE-attached member, so they appear in Triage and never on a monitor page.

**Criticality is not severity, and must never become it.** Criticality belongs to the
element; severity belongs to the rule. `check_run.severity` is copied verbatim from
the registry and nothing downstream recomputes it. Criticality may feed
`cohort.rank_score` (advisory) and inform a human authoring a rule. Wiring it into
severity would give the same breach two different severities depending on which
element it touched.

**A PII element's profile stores no values, and the floor is enforced twice.**
`cde_profile_pii_withholds_values` in the DDL, and a k-anonymity check in both
`fixtures/verify.py` and `tests/test_coverage_conformance.py`: no stored signature
may have a row count below five. `violation_sample` is the one accepted PII surface
in this design; the profile does not open a second.

**Nine rules pass and two are in shadow, on purpose.** A fixture where everything breaches
cannot exercise the pass path and leaves closure rate with no denominator.

**Unity Catalog has no `INSERT` privilege.** The spec's wording ("granted `INSERT` on
`dq.results`") is not expressible — `MODIFY` is the finest-grained write privilege and it
permits `UPDATE`/`DELETE` too. The enforceable equivalent is table-level `MODIFY` on
exactly two tables plus `delta.appendOnly`. See `sql/README.md`.

## Commands

Use the project venv — system `python3` has no pandas.

```bash
cd fixtures && ../.venv/bin/python build_fixtures.py && ../.venv/bin/python verify.py
```

`verify.py` must exit 0 after any change to `rules.py`, `build_fixtures.py`, or a
`CREATE TABLE` in `sql/ddl/`. It checks register integrity **and** diffs every fixture
table's columns against the DDL — that diff is what catches a column the generator writes
but the DDL does not declare, which fails in a workspace and passes locally.

```bash
../.venv/bin/python build_fixtures.py --inject-control-failure --out out_bad
../.venv/bin/python verify.py out_bad   # must exit 1
```

## Conventions

- Pilot CSVs live in `~/Downloads` and are **not committed**. Paths are at the top of
  `build_fixtures.py`.
- `fixtures/out/` is generated; do not edit by hand or commit.
- DDL uses `{catalog}` / `{app_sp}` / `{steward_group}` / `{approver_group}` placeholders,
  substituted at run time. This repo owns the *shape* of the tables; Databricks owns their
  *contents* — no data rows are checked in.
- Naming follows the triage spec throughout: `config.rule_registry`, `results.check_run`,
  severities `P1_block` / `P2_alert` / `P3_monitor`. There is no other model to reconcile
  against.

## Known gaps, deliberately unresolved

- **Nothing writes `results.check_run`.** `fixtures/` stands in locally. Ownership of that
  job is unconfirmed and cohorts cannot form without it.
- **The `rule_expr` SQL strings have never been parsed by anything.** Every number in
  `fixtures/out/` came from the Python evaluators. First job with a workspace: run each
  `rule_expr` against the pilot data and compare to `results.check_run.parquet`.
- `check_run.scope_fingerprint` is `NULL` everywhere — the spec's open question on pinning
  verification scope.
- Detective vs preventive control, retention, and who may approve are open questions in
  the spec. Do not resolve them in code.

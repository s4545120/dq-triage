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
| `notebooks/` | Current. The triage job's advice endpoint. **Never executed** — same status as `sql/ddl/`, same reason. |

### The interface was redesigned on 2026-09-16

Eight nav entries became five, and two of the eight were deleted outright rather than
moved. Nothing about the data model, the grants or the write path changed.

| Was | Now |
|---|---|
| `cohort_queue.py` | `triage.py` — "Cohorts" is our word for it, not the steward's |
| `cohort_detail.py` | `triage_detail.py` — five tabs, then three blocks, now four tabs |
| `monitored_tables.py` | `tables.py` |
| `monitor_detail.py` | `table_detail.py` |
| `cde_registry.py` | **deleted** — folded into two panels on the scorecard |
| `register.py` | **deleted** 2026-09-17 — the chain is read on the problem it belongs to |

**`app.py` registers six pages and links four.** `table_detail` and `triage_detail`
are drill-downs: neither means anything without a selection made on the page above it,
so neither is in the sidebar. They stay registered because `st.switch_page` can only
reach a page `st.navigation` knows about — which is why the nav is asked to render
nothing (`position="hidden"`) and `app.py` builds the sidebar itself from
`st.page_link`. Adding a page to `PAGES` therefore does not put it in the sidebar;
`SIDEBAR` does, and `tests/test_pages_render.py` pins both halves of that.

**Deleting the CDE page did not delete the CDE model.** `config.cde_registry`,
`results.cde_profile` and `v_cde_coverage` are untouched, and so is every test pinned
to them — the scorecard's quality figure still has the register for a denominator.
What went is the browsing surface. What replaced it: the `Scored on 20 checks over 10
critical elements` button in the filter strip opens a panel listing every element, and
a row of the element table at the foot of the page opens that one element in a drawer
instead of switching page. The cross-table attachment assertion that used to live in
the CDE page's tests moved to the check panel.

**The scorecard gained a drill-down.** Selecting a failing check opens a panel with
the rule in plain words, the arithmetic, and the rows that actually failed —
`results.violation_sample`, parsed into real columns by
`components.sample_rows_frame`. Those samples were always captured; until now the only
way to see them was from inside a cohort. `_check_pick` in session state is what the
panel reads, so the selection survives a rerun the table did not cause — and a test
can open a check without simulating a click.

**The three queue-shaped tables are not `st.dataframe`s.** The scorecard's failing
checks, the element gaps under them, and the Triage queue are drawn as clickable rows
— one `st.container` per row holding its markup and a real button stretched over the
whole row at zero opacity. Three reasons, and the third is the one a reader notices: a
dataframe cell cannot hold a tinted severity badge, it cannot colour a phrase, and its
row selection fires only from the checkbox in its own gutter — so "select a row" meant
hunting for a 14px target. Here the whole row is the target, it tints on hover in the
same accent the selected row uses, and it is still a real button, so the keyboard
reaches it.

`components.clickable_rows` and `components.row_head` are the one implementation, and
every row container is keyed `dqrow_<table>_<id>` so a single `.dq-rowgrid` /
`st-key-dqrow_` block in `theme.py` styles all three. Four rules in that block are
load-bearing rather than cosmetic and each is labelled with what broke without it —
the one worth knowing before you touch it is that Streamlit reports a markdown box as
one line high whatever it contains, so a row's height has to be set on the row
container, never on the grid inside it.

**The problem detail page has tabs again, and that is not a reversal.** It had five
until 2026-09-16 (Evidence, Suggested fix, Decisions, Impact, Stored record), then
three stacked blocks, and since 2026-09-17 four tabs: Why we think this · Evidence ·
Decisions · Stored record. The objection to the first set was never that tabs are bad
— it was that they made a reader choose an order before knowing what was in each, and
that the decision was buried inside one of them. Both are answered rather than
avoided:

* Every tab carries its count, so the label says what is behind it.
* **Nothing you have to act on is inside a tab.** The header and a state strip sit
  above the tab bar, visible on all four. The strip names the state, quotes the last
  reason anyone wrote, says whose turn it is, and carries the one event
  `lifecycle.available_events` permits — which opens the decision form in a drawer.
  `tests/test_write_path.py` clicks that button rather than setting the session flag,
  so the strip is part of the tested write path.
* *Impact* stayed dissolved. Blast radius is one line at the foot of the first tab and
  a phrase in the header. It never earned a tab and did not get one back.

**The model's verdict is eleven columns, and the app renders all of them.**
`notebooks/03_group_and_advise.ipynb` always produced more than a hypothesis and a
paragraph — `grouping_verdict`, `members_not_covered`, `defect_location`,
`recommended_owner`, `confidence`, `prior_state` and `differs_from_prior` came back on
every call and survived only inside the `model_input_payload` JSON, where nothing
queried them and no page could show them. They are columns on `results.cohort` now,
along with four fields the brief did not ask for before: `evidence_points`,
`rival_hypothesis`, `recommended_steps` and `verification_expectation`. A field the UI
cannot reach is a field that does not exist.

What stays in `model_input_payload` is the input and the provenance — the brief, the
system-prompt hash, the model and the temperature — plus `reasoning`. That last one is
deliberate: given a column it would sit on the page beside the evidence and compete
with it, and what a steward confirms is the facts, not the model's narration of its own
answer.

Consequences worth knowing:

* **`defect_location` has three values, not two.** `neither` exists because the data
  can be correct and the rule reasonable, with the disagreement between them a business
  question — COH-E is the fixture's case. Forcing that into data-or-rule makes the model
  assert a defect it does not believe in. `theme.DEFECT_LABEL` and `DEFECT_MEANING` are
  the one place those three are put into the steward's words.
* **The Triage queue's `rule defect, not data` mark still comes from the CDE register,
  not from `defect_location`.** `v_cde_coverage`'s `scope_mismatch` is an assertion the
  model cannot fabricate; the model's verdict is a claim. Both say COH-B, and where they
  ever disagree the register wins. Reading the mark off `defect_location` would quietly
  swap a declared assertion for a generated one.
* **`grouping_verdict` is never `rejected` in the table.** A rejected grouping raises no
  cohort at all, so a stored row is `holds` or `partial`, and a CHECK constraint says so.
  `partial` has no fixture example: making one would drop a member rule from its cohort,
  and `metrics.live_cohorts` maps breaching rules to cohorts, so that rule would vanish
  from the queue rather than appear unattached. The rendering path exists and is
  defensive; it is not exercised locally.
* **`confidence` is advisory and is not an input to `rank_score`.** Ranking on a
  self-reported number lets a confident wrong answer outrank a hedged right one.
* **Nothing re-reads `verification_expectation`.** It states what the next run should
  show, and `verified` is still the check runner's call. Comparing the two is the obvious
  next control test — HIST-8 is the worked example, whose expectation was met by a fix
  that did not hold a fortnight.

**The non-execution invariant is now checked in four places.** `recommended_steps` is
prose, and a step carrying a runnable body is the first move toward an execute button:
the system prompt forbids it, the notebook's `validate` rejects the response,
`cohort_steps_are_not_executable` refuses the row, and `fixtures/verify.py` and
`tests/test_pages_render.py` assert it over what is stored and what is printed. Four,
because a prompt can drift without anyone noticing.

**`fixtures/verify.py` now diffs the notebook too.** It already compared every fixture
table's columns against the `CREATE TABLE`; check 4 does the same for the cell in
`03_group_and_advise.ipynb` that builds the cohort row, anchored on the
`candidate_cohorts` temp view. The notebook is what will really write this table, and
until now nothing could tell you it had fallen behind the DDL. Add a column to
`results.cohort` and you must add it in both places or `verify.py` exits 1.

**The Register page was deleted on 2026-09-17; the register was not.**
`results.disposition` is still the append-only audit artefact and still the app's
primary write. Every event chain is still readable on the problem it belongs to, under
`Decisions` on the detail page — what went is the cross-cohort browsing view, for the
same reason the CDE page went: nobody browses a register.

**One thing went with it and has nowhere to be.** `domain/integrity.check` — the
control test over the whole register, the one that catches an approval with too few
distinct approvers or an execution with none — no longer has a surface anywhere. The
Triage resolution band that carried its badge went on 2026-09-16 and the page holding
its detail went on 2026-09-17. The module still runs and `tests/test_integrity.py`
still pins it, so this is a missing page rather than a missing control, but a control
test nobody can see is not a control anyone is relying on. Putting it back is a panel,
not a rebuild.

**`Rules` moved into the Monitor group.** It shared `Evidence` with the Register, and
a group label reading "Evidence" over a single rule-authoring link described nothing.
What a rule *is* forms part of what is being watched, which is what Monitor already
means here. Two groups now: Monitor (Scorecard, Tables, Rules) and Work (Triage).

**A Streamlit container measures 1rem shorter than what is inside it.** Worth knowing
before debugging any box on these pages that crops its own last line. Streamlit puts a
1rem `gap` between the blocks it stacks, and that gap is counted against the
container's height even when the gap is never drawn — so a `st.container` holding one
tall markdown reports 16px less than its content and clips the bottom. It is not the
markdown wrapper, not the element container and not flex shrinkage: overriding
`display`, `height`, `min-height` or `flex` on any of those changes nothing, because
none of them is where the 16px goes. Two pieces of the detail page's state strip come
from this: the tinted box is markup of our own rather than a bordered container, and
its button is absolutely positioned and anchored to the box's padding rather than
centred against a container height that cannot be trusted.

**Evidence on the detail page is master–detail.** The page used to print a sample
table per failing check — nine stacked expanders for COH-A. The checks are now one
`components.clickable_rows` table and the rows appear for the check selected, held in
`_member_pick`. Same rows, same cap, same grants: what changed is how many are on
screen at once, not what is on screen at all.

**The strip quotes the last reason WRITTEN, not `latest_reason`.** That column travels
with `latest_decision`, so on a reopened problem it returns the review that accepted
it — printed under a headline saying verification failed. The detail page reads the
last non-null `reason` in the event chain instead, which is the check runner's reopen
reason and the one that explains the state being announced.

**The Triage queue lists `metrics.live_cohorts`, not "open cohorts".** For every rule
breaching on the latest run, the cohort that currently owns it — which is the same
function `cohort_compression` divides by, so the row count and the ratio printed under
the table can never disagree. Two consequences that look like bugs: a problem someone
closed whose checks are breaching again is **in** the queue with its closed state
showing, because that is exactly what should be put in front of a steward; and a rule
regrouped into a newer problem is counted once, under the newer one, which is why
`CTCT_PHN_FMT` does not drag its August cohort back into the list. Six rows, 21
breaching checks, 3.5 : 1 — and the `Show` dropdown widens to Open / Waiting on me /
Closed / All for anyone who wants the lifecycle view instead.

**The queue rows carry no selected state, deliberately.** A row there is a link, not
a selection: clicking one calls `st.switch_page`. `selected_cohort` survives the trip
to the detail page and back, so passing it as the table's `picked` tinted a row every
time the queue was opened, for a selection the reader had already finished with.

**The spec's resolution metrics are not on a page.** Closure rate, MTTR, disposition
coverage, recurrence, recommendation acceptance, the triage funnel and the
decision-record control badge were removed from Triage on 2026-09-16 and have not
landed anywhere else. `domain/metrics.py` still computes every one of them and
`tests/test_metrics.py` still pins them, so putting them back is a page, not a
rebuild. The decision-record control badge is in the same position and now has no
Register page to defer to either — see above.

**Whose turn it is, is derived in one place too.** `components.waiting_on` reads it
off the lifecycle state — `owner_group` is the domain that owns the data and is the
same for most of the register, so printing it would say nothing. The Triage queue's
`Waiting on` column and the detail page's state strip both call it.

**A problem's title is derived, in one place.** There is no stored title column and
adding one is a fixture and DDL change, not a UI one, so `components.problem_title`
cuts one out of the root-cause hypothesis: drop a dashed aside, stop at the first `.`
or `:`. It does not rewrite — a badly-written hypothesis yields a badly-written title,
which is the right place for that problem to surface. The Scorecard and the Triage
queue both call it; neither has its own copy.

**The scorecard's bottom band is a list of elements, not an issue queue.** The tabbed
issue board and the two cards in the rail beside it — coverage segments and Recent
runs — were removed on 2026-09-16. What replaced them is one table, and on 2026-09-17
it became `Critical data elements`: every registered element, its kind, its
criticality, how it is covered, how many checks watch it and how it scores. One row
per ELEMENT carrying its worst finding, which is the same count the `CDEs under
watch` tile reports, so the two cannot disagree — three bindings of Customer name
with nothing validating them is one element, not three findings. Every element is
listed now, not only the ones with a gap: a band that only ever lists trouble cannot
be read as an inventory.

**The band reports and does not advise.** A `What to do` column stood there until
2026-09-17 — "write a rule", "fix the rule's scope", or a pointer at the cohort
already carrying the evidence (`see COH b42685aa`). Recommending the fix for a gap in
the register is out of scope for this app; `WHAT_TO_DO` and `_gap_sentence` are
deleted, and `tests/test_pages_render.py` asserts none of that wording comes back.
The scope panel's `Status` column lost its "Needs work" for the same reason and now
prints which of the four coverage findings it is.

**An element's score and its coverage are two different findings and the band shows
both.** The score is `_element_scores` — the same row-weighted arithmetic as the
headline figure, over that element's own checks, deduped across bindings so a
cross-table rule is not counted three times. `Identity document number` scores 100%
on a presence check while nothing looks at what the column holds, so only a *covered*
element's score is coloured; everything else prints the figure in neutral and lets
the Coverage cell beside it carry the verdict. An element with no check scores `—`,
never 0 — a gap in the register is not a data defect.

**Failing checks filter by element kind.** `data_class` is what the element IS —
email address, date of birth, identity document — and `theme.DATA_CLASS_LABEL` is the
one place the register's word is translated into the steward's. It is a cut the
dimension grouping cannot make, because `format` spans an email, a mobile number and
a date of birth. Checks attached to no registered element get their own option rather
than being dropped: 14 of the 34 rules are unattached, and a register-shaped filter
that could only narrow to the register would hide them behind a control that does not
admit to hiding anything. Under any filter the table foot reports the filter
(`7 of 21 failing checks · email address`), not the run.

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

**The palette is "Indigo signal", and it is declared in two files.** `theme.py` moved
off petrol teal onto an indigo accent — and so must `dq-app/.streamlit/config.toml`,
which is where the framework takes the colour for buttons, toggles, focus rings and
links. The two were out of step for a while and the page read as two apps stapled
together: indigo cards, teal controls. Change one, change the other.

One change inside `theme.py` is not cosmetic either: `TONE["moderate"]` was amber and
is now a cool teal, because amber never had enough contrast on a light ground and
"monitor" is informational rather than a warning. `SEVERITY_TONE` is untouched — `P3_monitor ->
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
scorecard's headline quality figure and the trend drawn under it; every figure on
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

The scoping is drawn, not implied, and it is spelled out rather than abbreviated: the
monitor pages carry a `10 CDEs` badge in the filter strip, and the scorecard a
`Scored on 20 checks over 10 critical elements` button that opens the element list —
a reader who does not already know the denominator cannot recover it from a badge
reading `10 CDEs`. A diagnostic page that quietly hides 14 of 34 checks is worse than
one that shows fewer and says so.

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

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

**Still two writes after the notification work too, but the app now has an outward
side effect and that is new.** `DQ_NOTIFY` (off by default) lets an accepted review
trigger an email. It writes nothing — no `notified` event, because that would be the
third write — and the ordering is the part to preserve: the register row is written,
read back by `disposition_id`, and only then is a message composed from the row that
was *observed*. A send is never derived from a row the app believes it wrote. Both
failure directions are in `dq-app/dq_app/data/notify.py`; the short version is that
"written but not sent" is recoverable and "sent but not written" is not.

**Three writes since 2026-09-28, and the third is named as such.** The threshold job
(notebook 06) advises on every rule's `fail_threshold_pct` against the tolerance the
CDE register declares on the element and the run history, and writes
`results.threshold_proposal`. A reviewer decides each proposal on the Thresholds page.
Adopting appends a `rule_version` carrying the new limit — the same append that
promotes a shadow rule — and the decision itself goes to `results.threshold_review`,
which is the third `MODIFY` grant and is listed as one in `07_grants.sql`. It exists
because a rejection recorded nowhere is a proposal that comes back every pass. Nothing
changes a limit without a person's name on the row that did it. See *The threshold
job* below. This is detection, not triage: nothing on the Triage pages reads it.

**Onboarding (2026-10-05) adds three more writes — granted in the `dq_onboard` test
schema, and in `dq_triage` since 2026-10-06.** Selecting a table (`config.monitored_table`), a
person's binding suggestion (`config.binding_proposal`) and a binding decision
(`config.binding_review`), each an append signed with the platform identity. The
element register itself is still written by no app: approved bindings reach it through
the onboarding job. Granting these three in `dq_triage` is the step that makes
onboarding real there, and it is a decision, not a deploy — see *Onboarding* below.
Since 2026-10-06 they are in `07_grants.sql` as six writes, the onboarding three
labelled as that decision: running the file as written takes it.

## Current state — read before editing anything

| Path | Status |
|---|---|
| `sql/ddl/` | Current. Spec v1.0 + Addendum A. **Executed** — as `sql/out/`, rendered for `workspace.dq_triage`. See `RUNBOOK-personal-workspace.md`. |
| `fixtures/` | Current. Local Parquet dataset generated from the pilot CSVs. Verified. |
| `dq-app/` | Current. Spec v1.0, redesigned 2026-09-16; scorecard redrawn around targets 2026-10-01. Runs on the fixture **and** against Unity Catalog; deployed as the Databricks App `dq-triage`. |
| `sql/ddl/15_config_onboarding.sql`, `16_views_onboarding.sql` | Current, 2026-10-06. The onboarding tables and views as DDL. **Applied to `dq_onboard`** (`onboard.py setup`) **and to `dq_triage`** (`onboard.py --schema dq_triage install`, 2026-10-06, with `01`'s two template columns). |
| `onboarding/` + `jobs/run_checks.py` | Current. **Running on a schedule in both schemas.** `dq_onboard`: `dq-checks` (daily 03:00 Sydney) and the table-update-triggered `dq-onboard steps`, app `dq-onboard`. `dq_triage` since 2026-10-06: `dq-triage checks` (568071030107709, daily 03:00) and `dq-triage onboard steps` (906515649279596), same code with `--schema dq_triage`. The `dq-triage` app carries the Onboarding pages since 2026-10-06 (deployment `01f1c110…`). See *Onboarding in dq_triage*. |
| `notebooks/` | `03` current, the triage job's advice endpoint — **executed** on `workspace.dq_triage` against `system.ai.gpt-oss-120b`. `04` is the notification sender, **never executed**: it needs a job, a secret scope and an SMTP host that do not exist yet. |

**There is a real workspace and it is LOADED — which is not the same as having been
produced.** `workspace.dq_triage`, prefix `dq_` — eight tables, five views, the two mock
source tables, 1360 check runs, 1026 violation samples and the 65-event register. The
procedure is `RUNBOOK-personal-workspace.md` and the rendered SQL is `sql/out/`,
regenerated by `sql/render.py` and `sql/seed.py`. Anything in this file that still says
"never executed" is stale; fix it rather than working around it — and read the next
section before quoting any figure above as evidence the system has been operating.

## What is real and what is mocked — verified 2026-09-27

Read this before repeating any number from this file to anyone. `fixtures/README.md` has
the local twin of this list; this one is about the workspace.

**The sentence to never say is "it has been running for 30 days."** Against
`dq_triage` the check runner first ran as a job on 2026-10-06 (run `9fe4d55c…`, 31
active checks, 19 breaching) and is scheduled daily from then; everything before that
date is the one 2026-09-17 run plus 39 seeded ones. Say which schema and since when
before saying "running" — and the source tables are still the 1000-row mocks.

### Real

| What | Evidence |
|---|---|
| **One check run.** Every rule's actual SQL executed inside Databricks | `run_ts = 2026-09-17 12:49:10.553790`. Every figure quoted in this file comes from it |
| **33 of 34 rule_exprs agree with the Python evaluators** | `sql/out/checkrun.sql`. `XREF_NAME_AGREEMENT` is the one that does not — a real bug found this way |
| **The violation counts and samples on that run** | Computed from the CSVs. 240 malformed emails, 200 IMEI, 12 MSISDN, and sample rows carrying actual bad values |
| **Eight cohorts** written by a real model call | `system.ai.gpt-oss-120b`, notebook 03 as a serverless job. Including the unprompted `defect_location = rule` at 0.95 on the IMEI rule |
| **The CDE profile arithmetic** | Real, but computed on a laptop — see *Mocked* |
| **The DDL** | Eight tables, 23 constraints, four functions, five views all created |

### Mocked, seeded, or absent

| What | Reality |
|---|---|
| **39 of the 40 check runs** | Back-projected by `build_fixtures.py` on four invented profiles, all stamped exactly `03:00:00`. The dates exist so closure rate and MTTR have a denominator |
| **Any schedule before 2026-10-06** | None against `dq_triage` until then. `dq-triage checks` runs daily from 2026-10-06; `dq_onboard`'s `dq-checks` from 2026-10-05 |
| **The source data** | Two mock tables, **1000 rows each**, loaded from CSVs in `~/Downloads`. Not production data. The defects in them are real defects, which is why the findings hold |
| **The disposition register** | All 65 events seeded. Latest is `2026-09-01`; **zero events after the Databricks run, and zero written by the deployed app.** No person has ever recorded a decision through it. The write path is exercised by `test_write_path.py`, not by a steward |
| **Every identity** | Synthetic, on `example.com` |
| **14 of the 22 cohorts** | Hand-authored, with `recommendation_source` saying so and a stub `model_input_payload` |
| **`results.cde_profile`** | All 12 rows share one `profile_ts` and a writer string that is a constant in `fixtures/profile.py`. No profiler has ever run in the warehouse |
| **Blast radius** | Invented. Real values come from Unity Catalog lineage, which was never queried |
| **The CDE register's criticality tiers** | One person's judgement, one email address, one date. Addendum A lists this as an open question |
| **The CDE register's tolerances, and its second ten elements** | `tolerance_pct` is set from the criticality tier (`fixtures/cdes.py`: critical 0.0, high 0.5, medium 2.0, low 5.0), and elements 11–20 were registered so that every rule could name one. The same one person's judgement, and every migration row says so |
| **Every threshold proposal and review** | Nine proposals and two decisions, hand-authored in `fixtures/thresholds.py`. **No model has produced one**: notebook 06 has never run, and the workspace does not yet have the table |

### How to state it honestly

Separate *does the thing work* from *is it in operation*. The first is largely yes and
the model reaching COH-B's conclusion unprompted is the evidence. The second is plainly
no, and the single reason is the one at the top of *Known gaps*: nothing writes
`results.check_run` on a schedule and its owner is unconfirmed.

### The interface was redesigned on 2026-09-16

Eight nav entries became five, and two of the eight were deleted outright rather than
moved. Nothing about the data model, the grants or the write path changed.

| Was | Now |
|---|---|
| `cohort_queue.py` | `triage.py` — "Cohorts" is our word for it, not the steward's |
| `cohort_detail.py` | `triage_detail.py` — five tabs, then three blocks, then four tabs, now six |
| `monitored_tables.py` | `tables.py` |
| `monitor_detail.py` | `table_detail.py` |
| `cde_registry.py` | **deleted** — folded into two panels on the scorecard |
| `register.py` | **deleted** 2026-09-17 — the chain is read on the problem it belongs to |

**`app.py` registers ten pages and links six.** `table_detail`, `triage_detail`,
`onboarding_add` and `onboarding_table` are drill-downs: none means anything without a
selection made on the page above it, so none is in the sidebar. They stay registered because `st.switch_page` can only
reach a page `st.navigation` knows about — which is why the nav is asked to render
nothing (`position="hidden"`) and `app.py` builds the sidebar itself from
`st.page_link`. Adding a page to `PAGES` therefore does not put it in the sidebar;
`SIDEBAR` does, and `tests/test_pages_render.py` pins both halves of that.

**Deleting the CDE page did not delete the CDE model.** `config.cde_registry`,
`results.cde_profile` and `v_cde_coverage` are untouched, and so is every test pinned
to them — the scorecard's quality figure still has the register for a denominator.
What went is the browsing surface. What replaced it is the scorecard's element list
(see below), and "Every binding and what checks it" in its right pane opens one
element in a drawer instead of switching page. The `Scored on 20 checks over 10
critical elements` button and the scope panel it opened were deleted on 2026-09-22:
the element list is the same list, and two ways to one table was one too many. The cross-table attachment assertion that used to live in
the CDE page's tests moved to the check panel.

**The scorecard gained a drill-down.** Selecting a check opens a panel with
the rule in plain words, the arithmetic, and the rows that actually failed —
`results.violation_sample`, parsed into real columns by
`components.sample_rows_frame`. Those samples were always captured; until now the only
way to see them was from inside a cohort. `_check_pick` in session state is what the
panel reads, so the selection survives a rerun the table did not cause — and a test
can open a check without simulating a click. Since 2026-10-01 a passing check opens
too — the breakdown lists every check on the element — and says that no row failed
rather than printing an empty sample table.

**The Rules page was redrawn on 2026-10-05 in the scorecard's layout.** It was a
thirteen-column dataframe, a selectbox of every rule id to inspect one, and a second
dataframe plus selectbox to promote — three ways into one list, none by element. Now:
the CDE register on the left (`All rules` first, then each element, its bar the rules
split failing / passing / shadow by count — not a score, the scorecard owns that), the
picked element's rules on the right in `Active` / `Shadow` tabs, and one rule in a
drawer with its expression, history and versions. It reuses the scorecard's keyed
containers (`dq_elsplit`, `dq_elcard`, `dq_elpane`, `dq_check_drawer`), so their CSS
applies unchanged. **Promote now asks first**: the drawer's button opens an
`st.dialog` saying which version is appended, in whose name, and whether the rule
would breach on the latest run; the write happens only on its Promote.
`test_promoting_asks_first_and_writes_only_on_confirm` pins that.

**The three queue-shaped tables are not `st.dataframe`s.** The scorecard's element
list, the check breakdown beside it, and the Triage queue are drawn as clickable rows
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

**The problem detail page has six tabs, and that is not a reversal.** It had five
until 2026-09-16 (Evidence, Suggested fix, Decisions, Impact, Stored record), then
three stacked blocks, then four tabs, and since 2026-09-22 six: Diagnosis · What to
do · Evidence · Lineage · Decisions · Stored record. The first of the four, "Why we
think this", held the claim, the advice and the blast radius in one scroll; they
answer three questions — is it true, what do we do, what else does it touch — so
they are three tabs. The objection to the original set was never that tabs are bad
— it was that they made a reader choose an order before knowing what was in each,
and that the decision was buried inside one of them. Both are still answered:

* Every tab carries its count (`4 facts`, `4 steps`, `6 tables`), so the label says
  what is behind it.
* **Nothing you have to act on is inside a tab.** The header, the element pills and
  a state strip sit above the tab bar, visible on all six. The strip names the state,
  quotes the last reason anyone wrote, says whose turn it is, and carries the one
  event `lifecycle.available_events` permits — which opens the decision form in a
  drawer. `tests/test_write_path.py` clicks that button rather than setting the
  session flag, so the strip is part of the tested write path.
* *Impact* came back as **Lineage**, and earned it by being drawn rather than listed:
  checks → tables with bad rows → what reads them downstream
  (`components.lineage_view`). Two lists of table names never earned a tab; a
  picture of where the damage travels does.
* Prior advice ("These rules have been here before") moved under **What to do**, not
  Diagnosis: what was tried last time is a fact about the advice.

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
means here. Three groups now: Onboard (Onboarding, first — choosing what is checked
comes before monitoring it, since 2026-10-05), Monitor (Scorecard, Tables, Rules,
Thresholds) and Work (Triage). `Thresholds` joined Monitor on 2026-09-28 for the same reason: a limit is a
property of a rule, and the decisions made there are about rules, never problems.

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

**A problem's title is derived, in one place, and it is not the hypothesis.**
`components.problem_title` builds `<what it is about> — <what kind of wrong>`:
the registered elements the checks watch (`components.cohort_elements`, read off
`v_cde_coverage`, most critical first, two by name at most) and `defect_location` in
the steward's words (`theme.DEFECT_VERDICT`: wrong data / rule flags valid rows /
needs a business call). COH-B is "Primary billing account and Device IMEI — rule
flags valid rows". A problem on no registered element falls back to the column its
checks read, or a cross-table check's rule name — never one bare table. Until
2026-09-22 the title was the hypothesis's first sentence, cut; COH-B's was "Neither
of these is a data defect", which names nothing. That cut survives as
`components.claim_sentence`: the line under the title on the detail page and the
tooltip on a queue row. There is still no stored title column — a model-written one
is a DDL, notebook and fixture change, and this stays as its fallback if it lands.
The Scorecard's Triage tab, the Triage queue and the detail page all call it.

**A problem's elements are pills on its detail page.** One per element (Customer
name bound to three columns is one), labelled with criticality and coverage, and a
click opens `components.element_panel` — the same drawer the scorecard's element
table opens, moved out of `scorecard.py` so both pages share it. Each page holds the
pick in its own session key (`_cde_pick`, `_detail_cde_pick`). Checks on no element
are counted in a dashed chip rather than dropped. The Triage queue does not repeat
the chips — its title already names the elements — and carries the most critical
one's criticality on the row's second line instead.

**The scorecard is four cards, and every figure on it stands beside a target.**
Redrawn on 2026-10-01 from a design mock. Until then the page reported scores and
left the reader to decide whether 97.9% was good; the register has declared a
tolerance on every element since 2026-09-28, so the page can now say it.

* **Overall quality** — the row-weighted score, the change since the previous run,
  its target and how far off it is, a 30-day line with the target dashed across it
  (`theme.target_chart`), and one sentence reading the chart aloud. Each run on the
  line can be hovered for its date, score and distance from target — an HTML layer
  of one column per run over the SVG, shown by CSS `:hover` like the row tips; the
  same on the element pane's trend, where a chart drawn without a target gets a
  bubble without a verdict.
* **Monitoring coverage** — elements by their worst finding (6 covered · 7 not
  validated · 6 out of scope on the fixture) as one bar in three shares. Its floor
  is a button: the open-problems count opens the Triage queue (`dq_covcard`,
  `dqrow_op_queue`).
* **Critical data elements** (`dq_elcard`, rows in `dqrows_elist`, selection in
  `_elem_scope`) — one row per element: score, a 0–100 bar with the target ticked on
  it (`theme.target_bar`), the shortfall, the change since the last run. `Priority 5`
  by default, `All 19` on request (`_elist_show`). The page opens on the first row.
* **Selected element** (`dq_elpane`) — a header (name, badges, score against target)
  above four tabs: **Overview** (trend, one sentence, the element drawer's button),
  **Checks · N** (every check on it, passing ones too, each with its own pass rate
  against its own limit; a row opens the check drawer), **Sample rows · N** (the
  failed rows of one check at a time, picked from a dropdown) and **Triage · N** (the
  problems carrying its failing checks, each a link to that problem's page).

**The two lower cards are the same height by construction.** Stacked, an element with
nine checks ran the right card to three times the height of the list. Now everything
that varies in length is behind a tab whose body is `TAB_BODY` px and scrolls inside,
the list is `LIST_BODY` px in both `Priority` and `All`, and theme.py stretches both
cards to the row as a backstop for a header that wraps. Change a row's height or the
header's line count and those two constants need re-measuring. Check rows are the
two-line `compact` variant of `_row_markup` for the same reason.

**The Sample rows tab is a second door onto the one PII surface, not a wider one.**
Same `violation_sample` rows, same columns, same per-check cap as the check drawer —
`_failed_rows` draws both. One check at a time, because each check's sample has its
own columns.

**The scorecard has two ways into Triage and both are pinned.** The first redraw
dropped the failing-checks table and its Problem column and left the page with no
link to the work at all. `test_the_scorecard_has_a_way_into_the_triage_queue` and
`test_an_element_links_to_the_problem_its_failing_checks_belong_to` are there so that
does not happen quietly again. The Triage tab's rows are titled by
`components.problem_title`, so a problem has one name on all three pages.

**Spacing on this page is `clamp()`, never a fixed rem.** The gap between the two
rows of cards has to be asked for: the hero's markdown container carries Streamlit's
`margin-bottom: -1rem`, which cancels the 1rem gap between rows and left them 3px
apart. The coverage card's wrapper carries the same negative margin so its floor
meets the hero's. The list is the narrower card (1 : 1.5) and both wrap to full width
below about 41rem of page.

**Three targets, one module.** `domain/targets.py`, pinned by `tests/test_targets.py`:

* An **element's** is `100 - tolerance_pct` off `config.cde_registry`. No tolerance
  declared means no target, never an assumed hundred.
* A **check's** is `100 - threshold_pct` off the run row — the limit it was actually
  judged on. Almost every limit in the fixture is 0, so almost every check reads
  `≥ 100%`; that is the registry's state, and the Thresholds page is where it moves.
* The **headline's** is the element targets weighted by the rows each check scanned
  (`blended_target`) — the figure the score would read if every element sat exactly
  on its tolerance. 99.3% on the fixture, against a score of 95.3% (92.1% until the
  variance rule was retired — its 1000 failed rows were most of the gap).

**Not every score is assessed against its target, and `targets.assessed` is the one
definition.** It takes a binding something validates, no binding in scope mismatch, a
check that ran and a declared tolerance. An element nothing validates keeps its 100%
and is not told it meets target; a scope mismatch keeps its 50% and is not told it is
below — no red figure, no dashed line on its chart, and the rule the register
disputes is labelled `Rule scope disputed` in its breakdown. On the fixture that is
5 below, 2 meeting, 12 unassessed. **Seven assessed against six "covered" is not a
bug**: coverage counts an element by its WORST binding, and Customer email address
has seven checks examining the address and a status-code column watched only for
presence. Its score is a real claim about the data; its coverage is honestly
"not validated".

The list sorts largest shortfall first among the assessed, then the rest by
criticality — so the two scope mismatches never lead it, which is what sorting on
score alone used to do.

**What the redraw removed.** The six estate tiles, the `All checks` entry, the
failing-checks table with its Trend and Problem columns, and the `Group by dimension`
toggle. Nothing was deleted from `domain/`: `metrics.detection_summary` and
`records_affected_floor` still compute the tiles' figures and `tests/test_metrics.py`
still pins them. All failing checks in one list is the Triage queue's job. A check's
onset survives as `since 28 Aug` on its row — COH-A's evidence is still six email
checks starting on one date.

**A registry without `tolerance_pct` shows no targets.** The workspace has the column
since 2026-10-01; a workspace that predates `migrate_cde_scope.sql` does not.
`targets.element_targets` returns nothing for a registry without the column, every
element reads `No target declared`, and `test_the_page_renders_with_no_tolerance_declared` pins
that the page says so instead of falling over. The scorecard deliberately does not
read `results.threshold_proposal`: the app's service principal has no grant on it yet,
and the adapter's read of it is a bare `SELECT`.

**The band reports and does not advise.** A `What to do` column stood there until
2026-09-17 — "write a rule", "fix the rule's scope", or a pointer at the cohort
already carrying the evidence (`see COH b42685aa`). Recommending the fix for a gap in
the register is out of scope for this app; `WHAT_TO_DO` and `_gap_sentence` are
deleted, and `tests/test_pages_render.py` asserts none of that wording comes back.
The scope panel's `Status` column lost its "Needs work" for the same reason; the
panel itself is gone since 2026-09-22.

**An element's score and its coverage are two different findings and the page shows
both.** The score is `_element_scores` — the same row-weighted arithmetic as the
headline figure, over that element's own checks, deduped across bindings so a
cross-table rule is not counted three times. `Identity document number` scores 100%
on a presence check while nothing looks at what the column holds, so its row reads
`Not assessed · Not validated` in grey rather than `Meets target`. An element with
no check scores `—`, never 0 — a gap in the register is not a data defect.

**The dimensions have no control left, only definitions.** Completeness / Validity /
Consistency / Uniqueness were four cards, then a `Group by dimension` toggle, and
since 2026-10-01 are a line in each check row's hover text and a badge with its
definition in the check drawer. `_DIMENSION_OF` and the prose survived both moves.

**`metrics.records_affected_floor` is a floor and must stay labelled as one.**
`check_run` stores a violation count and no keys, and the runner caps
`violation_sample` per check, so four of the failing checks are truncated and no exact
distinct count exists. Its tile (`≥ 600`) left the scorecard on 2026-10-01 and the
figure is on no page; if it comes back it comes back with the `≥`. Making it exact is
a change to the runner, not to the app: a `distinct_entity_count` column would make
each check exact without making the union computable across checks; only a stored key
set or a union-able sketch answers the question. Two tests assert the floor is a
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

It reads `fixtures/out/*.parquet` through `dq_app/data/local_source.py` when
`DQ_APP_DATA_SOURCE=local`, and Unity Catalog through `databricks_source.py` when it is
`databricks`, which is what `app.yaml` ships. Both paths have run; `tools/parity_check.py`
is what diffs one against the other.

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

**The deployed app reads Unity Catalog.** `dq-app/app.yaml` sets
`DQ_APP_DATA_SOURCE=databricks` with `DQ_CATALOG=workspace`, `DQ_SCHEMA=dq_triage`,
`DQ_PREFIX=dq_`, and takes the warehouse id from the `sql-warehouse` resource
attached to the app rather than discovering it. Set the source back to `local` and
comment out the rest of that block to get the self-contained demo. Only `dq-app/`
ships, and `fixtures/out/` is gitignored and sits above it, so there is a committed
copy at `dq-app/dq_app/fixture_data/` — the one place generated fixture output is
checked in, and it exists because nothing else can reach the container.
`local_source.fixture_dir()` prefers `fixtures/out/` and falls back to the bundle.
Rebuild the fixture and you must `cp out/*.parquet` over the bundle;
`dq-app/tests/test_bundled_fixture.py` compares them byte for byte and fails if you
forget.

**Unity Catalog hands back tz-aware timestamps and the fixture's parquet is naive.**
`databricks_source._naive_timestamps` converts to UTC and drops the offset on every
read, so the two sources stay interchangeable. Without it the detail page's age line
raises `Cannot subtract tz-naive and tz-aware datetime-like objects` — which is
exactly what it did the first time the adapter was ever run. Normalising at the
adapter is the point of having one: the fixture is what 90-odd tests are pinned to.

**A laptop cannot write the register, by design.** `run-workspace.sh` runs the app
against Unity Catalog locally, and reads work. Writes are refused: there is no
`x-forwarded-email` header off a Databricks App, so `identity.py` stamps
`actor_source = 'local_standin'` and two CHECK constraints on `dq_results_disposition`
reject the row. Deploy to write.

## The first real run — 2026-09-21

`notebooks/03_group_and_advise.ipynb` ran as a serverless job against
`workspace.dq_triage` and `system.ai.gpt-oss-120b`. The first run to reach the write
produced 7 cohorts; a later run added an eighth (`CTCT_MOBL_NOT_NULL`) for a group the
first had rejected — `TEMPERATURE = 0.0` does not make this endpoint deterministic.
Every one carries the full verdict, and the current notebook has since completed
cleanly twice on a table already holding its own output. What it established, beyond
that the thing runs:

**The model reached COH-B's conclusion on its own.** Given `SUBS_IMEI_NOT_NULL` it
answered `defect_location = rule` at 0.95 confidence, named the scope filter the rule
is missing, offered the upstream-collection explanation as a rival and said what
evidence would support it, wrote *"Do NOT modify any data rows in the warehouse"* as a
step, and read the steward's August rejection out of the register — then said what it
was doing differently from it. That verdict is the worked example the whole fixture is
built around, and it was not given to the model.

**It split the pair, and that understates it — the mechanical grouping barely groups
at all.** The fixture's COH-B covers `SUBS_IMEI_NOT_NULL` and
`SUBS_PRIM_ACCT_NOT_ZERO` together; the run raised them as separate single-rule
cohorts, because grouping is mechanical over run history and two chronic rules that
never co-moved have nothing to group on. The hand-authored cohort is the better
answer and the mechanical grouping cannot reach it.

Read across all eight, verified against `results.cohort` on 2026-09-27: **seven are
single-rule and one has two members — roughly 1.1 : 1.** The seeded COH-A compresses
nine rules into one problem; nothing the model wrote comes close. Two tables of
chronic defects give co-movement almost nothing to work with, which is the same
caveat `fixtures/README.md` puts on the 3.5 : 1 figure, arriving from the other
direction. This is a finding about the grouping signals, not about the model, and it
is the most important one the run produced: *group, don't list* is the spec's first
principle and on real output it is not yet reproducing. Do not fix it by adding
interpretive grouping keys — see § 2 of the notebook for why `cde_id`,
`target_table` and `rule_type` are deliberately excluded.

**It did not use `neither` where the fixture does.** Given `CTCT_BRTH_PLAUSIBLE` — 27
contacts aged 16–17, valid dates, a business question about minors holding accounts —
it answered `data` at 0.85, with `neither` available and prompt rule 5 describing
exactly this case. And given `CTCT_MOBL_NOT_NULL` it answered `rule` at 0.78 where the
hand-authored COH-D calls it a genuine collection gap. Two disagreements with the
fixture out of eight; neither is wrong by construction, and both are the kind of claim
the detail page exists to let a steward overrule.

**It has never once answered `neither`.** Across all eight the split is five `data`
and three `rule`. The only `neither` row in `results.cohort` is seeded — COH-E, at
0.55. That is the failure `notebooks/README.md` item 4 asks you to check for, and it
is now an observation rather than a worry: check it again before tuning the prompt,
because a third value the model will not reach for is a third value the schema is
carrying for nothing.

**Advice against a loaded register looks nothing like advice against an empty one.**
**All eight** came back with a `prior_state` other than `none` — `awaiting_review` ×2,
`deferred` ×2, `closed_rejected` ×2, `approved_awaiting_execution`, `closed_verified`
— and each said what had already been tried. This is the spec's worked failure,
avoided. (This file said "six of the seven" until 2026-09-27; that was the first run,
and the register now reads 8 of 8.)

**Five bugs surfaced that no test could reach**, all in code that had only ever run
interactively: `currentRunId()` is not whitelisted on serverless, `LATERAL VIEW` was
placed before its JOIN, `createDataFrame` cannot infer a type for a column that is
`None` in every row, the verification cell read verdict columns off
`v_cohort_current`, which does not have them — and the one below.
`RUNBOOK-personal-workspace.md` records all five with fixes.

**The notebook could write exactly once.** `validate`'s `PRIOR_STATES` held six of
the ten states `v_cohort_current` can return, and the four it omitted included
`awaiting_triage` — what the view returns for a cohort with no disposition events at
all, which is every cohort the notebook writes (see the next paragraph). The first run
worked because every prior cohort was a seeded one, in a state the list knew. The
second run's briefs carried the notebook's own cohorts as priors: prompt rule 12 tells
the model to set `prior_state` from the most recent one, the brief said
`awaiting_triage`, the model obeyed, and the validator threw every answer away for
using a word it did not know. Every model call paid for, nothing written, and the job
died further on with `CANNOT_INFER_EMPTY_SCHEMA` from a summary cell that built a
DataFrame out of an empty list — so the misleading error was the only one visible and
the real messages sat unread in the loop output above it.

`recommended` is not a state. It is an event type; the view has no branch that returns
it, and a cohort whose chain has been opened reads `awaiting_review`.

Two rules come out of that. **`PRIOR_STATES` and `08_views.sql` must not drift**: a
state the view can return and the enum omits rejects every brief containing it.
`fixtures/verify.py` check 5 now extracts every `THEN`/`ELSE` literal from the view's
`lifecycle_state` CASE and diffs it against the notebook's list in both directions, so
this is caught on a laptop. **A summary must print its rejections first and
unconditionally**, because the run where nothing validated is the run whose reason you
most need.

**The notebook never opens the chain it creates.** The fixture's triage job writes a
`recommended` disposition event as the first link of every cohort's chain, and
`v_disposition_integrity` reports any cohort without one as
`missing_recommended_event` — its own control test saying the row cannot be trusted.
Notebook 03 writes `results.cohort` and nothing else, so every cohort it has written
is in that report. Closing the gap means the triage principal writing to
`results.disposition` as well: a second `MODIFY` grant, and a decision, not a notebook
change. Until then, expect `awaiting_triage` on every model-written cohort and read it
as this finding, not as the lifecycle's starting state.

**`tools/explain_notebook.py` is the guard that came out of it.** It substitutes the
table constants into every `spark.sql` string in the notebook and asks the warehouse
to plan it — seconds, no compute, nothing written, non-zero exit on the first
statement that will not run. Run it before submitting the job; three of the four bugs
above were reachable this way, before any model call was paid for.

The thing it had to learn is worth keeping in mind anywhere else this trick is used:
**Databricks raises a parse error but returns an analysis error as plan text.** An
unresolved column or a missing table comes back as a result row, so a checker that
only catches exceptions reports success on `SELECT v.no_such_column`. That is how the
verification cell passed this check twice before the tool started reading the plan.

**`v_cohort_current` does not carry the verdict columns and should not.** The view
answers "where has this cohort got to", which is the register's question; the verdict
is the cohort's own. The app already reads them separately — the view for state, the
base table for everything the model said — and the notebook's verification query now
does the same join.

## Migrations applied — 2026-10-01

`migrate_fn_adoption`, `migrate_join_sql` and `migrate_cde_scope` ran against
`workspace.dq_triage` in that order — the first uses positional INSERTs, so it must
precede the `ADD COLUMN`; the last inserts `join_sql`. Every INSERT was `EXPLAIN`ed
first, and part 4's rendered files (`11_views_cde`, `09_results_threshold`,
`12_views_threshold`) ran after. `10_views.sql` had to be re-run too: a Databricks view
freezes its column list at creation, so `v_rule_registry_current` could not see
`join_sql` until it was re-created. Expect the same for any future `ADD COLUMN`.

Verified: 13/13 helper rules OK with identical counts, `SUBS_MSISDN_FMT` at v3; three
cross-table rules carry `join_sql`; 20 elements (19 after the retirement below), all with a tolerance; no current rule
without `cde_id`. Coverage reads 8 covered · 11 unvalidated · 4 no_rule · 2
scope_mismatch against the fixture's 8 · 12 · 4 · 2.

**The one miss is a binding.** The fixture binds `EML_STTS_CD` to `CDE_CUST_EMAIL`, but
that binding arrived after the workspace was seeded and part 1 copied `bindings` forward
from v1, so `CTCT_EML_STTS_NOT_NULL` and `CTCT_EML_STTS_CONSISTENT` attach to nothing
(checks 5b and 5d each return those two). The generator now writes bindings from the
fixture; for this workspace `sql/out/fix_cde_email_binding.sql` appends v3. **Not yet
run.** The threshold tables exist and are empty — the fixture's nine proposals were not
seeded.

The same day `check_run`'s 39 seeded runs were reloaded from the regenerated
`seed_results.sql` (a MERGE on `result_id`): the back-projection had pushed the two
variance rules past rows scanned. COH-F's `total_violation_rows` still reads 1060 in the
workspace against 1039 in the fixture.

## What the workspace actually holds — read 2026-09-27

Queried directly, not inferred from the fixture. Anything below that disagrees with a
figure elsewhere in this file, believe this section and fix the other one.

| | |
|---|---|
| `check_run` | 1360 = 40 runs × 34 rules. 39 runs seeded at `03:00:00`; the final run is `2026-09-17 12:49:10.553790` and was **computed in Databricks** |
| `cohort` | **22** — 14 seeded, 8 written by notebook 03 |
| `disposition` | 65 events: `recommended` 14, `approved` 17 over 11 cohorts, `reviewed` 13, `executed` 10, `verified` 10, `reopened` 1 |
| `cde_registry` / bindings | 10 elements, 12 bound columns |
| `rule_registry` | 35 rows, **32 active**, of which **20 attach** to a binding |
| `cde_profile` | 12 rows, all one `profile_ts` — seeded, see below |
| coverage | 5 `covered`, 2 `scope_mismatch`, 5 `unvalidated`, **0 `no_rule`** |

**These are the workspace as it stands, before `migrate_cde_scope.sql`.** The DDL and
the fixture moved on 2026-09-28 — 20 elements, 26 bound columns, every rule naming its
element, two threshold tables — and the workspace has not. See *DQ runs on CDEs*.

`recommended` = 14 against 22 cohorts is the "notebook never opens the chain" finding
above, confirmed: all eight model-written cohorts are in `v_disposition_integrity` as
`missing_recommended_event`. `approved` 17 over 11 cohorts is the P1 two-approver rule
doing its job. No event carries `actor_source = 'local_standin'` — nothing has forged
a decision from a laptop.

**The scope-mismatch demo holds in the real build**, naming the two rules by id:
`PRIM_ACCT_KEY` over 500 rows against `SUBS_PRIM_ACCT_NOT_ZERO`, `IMEI_ID` over 200
against `SUBS_IMEI_NOT_NULL`. And the table-name rewrite `sql/seed.py` performs landed
consistently in **both** registries — had it touched one and not the other, every
binding would read `no_rule` and the whole component would look broken.

**The `rule_expr` comparison has been made, and it is 33 of 34.** This is the first
item under *Known gaps* below, now answered. Every row-level, uniqueness and variance
rule agrees exactly with the Python evaluator. One rule does not:

`XREF_NAME_AGREEMENT` — the fixture says `breach`, 2 violations; the SQL in the
registry returns `pass`, 0. **The SQL is wrong, not the fixture.** The expression is
`lower(trim(s.SUBS_FRST_NM)) <> lower(trim(c.FRST_NM))`, and exactly two rows in the
1000-row join have a NULL on one side (`SUBS_KEY` 4000996, contact name `Isla`, no
subscription name; and 4000997, `Jack` with no contact name). SQL three-valued logic
makes `NULL <> 'isla'` unknown rather than true, so `count_if` drops both; pandas
compares `NaN != 'Isla'` as true and keeps them. A subscription whose first name is
missing while its contact has one is precisely the disagreement this rule exists to
catch, and the stored SQL cannot see it.

The fix is the null-safe form, `NOT (lower(trim(...)) <=> lower(trim(...)))`, which
finds both rows. **`XREF_OPEN_TS_AGREEMENT` carries the same pattern** and agrees only
because neither of its columns holds a NULL on this data — it is the same defect,
latent. `XREF_SUBS_CTCT_ORPHAN` is fine; it tests `IS NULL` explicitly. Treat
"agreement comparison written with `<>`" as the class, not these two as instances.

**No profiler has ever run in the warehouse.** All 12 `cde_profile` rows share one
`profile_ts` (`2026-09-02 03:00:00`) and the writer string `job:dq-cde-profiler`,
which is the constant `PROFILE_JOB` in `fixtures/profile.py`. They are the laptop's
pandas output, loaded verbatim by `seed_results.sql`. Two consequences:
`v_cde_coverage.never_profiled` is `False` everywhere because rows exist, so it
answers "is there a profile row" and not "has a profiler run against this table" —
today those coincide and at the second table they will not; and the profile is 15 days
behind the final check run, so profile freshness would flag all twelve.

**Two cross-table rules attach to nothing, and nothing says so.**
`XREF_OPEN_TS_AGREEMENT` (breaching, 11 rows) and `XREF_SUBS_CTCT_ORPHAN` (`P1_block`)
carry `target_column = NULL` **and** no `cde_id`, so neither join path in
`v_cde_coverage` reaches them. `XREF_NAME_AGREEMENT` is the only rule in the registry
using the `cde_id` path — the whole reason that column exists is carried by one row.
This is not a defect in the view: nobody registered an element those two cover, which
is what "registration precedes discovery" means. But the unattached set has no surface
anywhere in the app, and a P1 rule outside every coverage figure with nothing
reporting it is the failure the CDE register exists to prevent, one level up. The
query is four lines; the panel does not exist. **Resolved in the DDL and the fixture on
2026-09-28** — both rules now name an element — and still true of the workspace until
`migrate_cde_scope.sql` runs.

## Thirteen rules call a shared UC function — 2026-09-27

`sql/ddl/12_functions.sql` declared four predicate helpers and, until now, no rule
referenced one. Thirteen do:

| Function | Replaces | Rules |
|---|---|---|
| `is_blank_v1` | `X IS NULL OR trim(X) = ''` | 8 |
| `is_valid_email_v1` | the email regex, longhand | 2 |
| `is_au_mobile_v1` | `^04[0-9]{8}$` | 2 |
| `is_sentinel_v1` | the placeholder value list | 1 |
| `au_phone_digits_v1` | the AU phone-normalising CASE | 7 (since 2026-10-05) |
| `is_phone_placeholder_v1` | the 48-number phone placeholder list | 2 (since 2026-10-05) |
| `is_name_placeholder_v1` | the 13-value name placeholder list | 3 (since 2026-10-05) |

The last three serve the ten "DQ Queries" rules that sit at v2 — see that section.

**Proven equivalent, not assumed.** `sql/out/checkrun.sql` was re-run against
`workspace.dq_triage` after the conversion: **33 PASS, 1 FAIL**, the same result as
before it, and the FAIL is the pre-existing `XREF_NAME_AGREEMENT` null-safety bug that
no function touches. Every converted rule returns the identical count — including the
two that must stay broken (`SUBS_IMEI_NOT_NULL` 200, `SUBS_PRIM_ACCT_NOT_ZERO` 500)
and their correctly-scoped twins (0). The conversion changed how the rules are written
and nothing about what they measure.

Three things to know before touching this:

* **`rule_expr` stores `dq.fn.is_blank_v1(...)`, a canonical name, not a placeholder.**
  Same convention as `target_table` holding `prod.customer.ctct_c`: a real name the app
  can print, rewritten per layout at generation time. `sql/seed.py` and
  `sql/checkrun.py` both replace the `dq.fn.` prefix and **must agree** — they take
  `--fn-prefix`, defaulting to `<catalog>.<schema>.<prefix>fn_`, which is what
  `render.py` produces. If they ever disagree, `checkrun.sql` diffs a query the seeded
  registry will never run.
* **The functions are immutable once referenced, and nothing records that.**
  `results.check_run` has no `function_version` column, so `ALTER`ing a referenced
  function retroactively changes the meaning of every historical verdict silently. The
  `_v1` suffix plus `EXECUTE`-only grants is the whole enforcement. A change is a `_v2`
  and a new `rule_version` on every dependent rule. **And note the sandpit weakens
  this**: `render.py` folds `{catalog}.fn` into `dq_triage.dq_fn_*`, so the separate
  schema whose ownership makes `_v1` enforceable does not exist in this workspace.
* **The migration is APPLIED (2026-10-01)** — see *Migrations applied* below.
  `sql/out/migrate_fn_adoption.sql`, generated by `sql/migrate_fn.py`.
  `config.rule_registry` is `delta.appendOnly` — confirmed on the live table — so
  adopting there is an INSERT per rule at `rule_version + 1`, never a re-seed, because
  `DELETE` is blocked. The version is computed from the table rather than assumed:
  twelve rules go to v2 and `SUBS_MSISDN_FMT` to v3, since it already carries the v1→v2
  scope_filter fix.

  Validated without writing: the six read-only steps were executed (the four helpers
  exist, the NULL asymmetry is exact, `already_adopted = 0`, and all 13 counts match
  when the helpers are run against the real rows), and all 13 INSERTs were `EXPLAIN`ed
  to a clean `AppendDataExecV1` — reading the plan text, not just the absence of an
  exception, for the reason `tools/explain_notebook.py` records.

  Each INSERT selects off its own current version, so `status` (shadow stays shadow),
  `promoted_by`/`promoted_at` (NULL on the shadow rule) and `scope_filter` (the two
  deliberately-unscoped rules) all carry forward untouched. `created_by` becomes
  `current_user()` because the DDL defines it as who authored *this* version;
  `promoted_by` is deliberately left alone, since a new version of an already-active
  rule is not a shadow→active promotion and who may sign one off is an open spec
  question this file must not answer by implication.

  **The fixture models the same bump**, so the two do not diverge: longhand at v1, the
  helper at v2, and v3 for `SUBS_MSISDN_FMT` — the only rule with three versions, and
  the only place the two kinds of change are visible apart (v1→v2 changed what it
  MEASURES, v2→v3 only how the predicate is WRITTEN). `sql/out/verify_seed.sql` check 2
  therefore returns zero rows both before and after the migration, which is the property
  worth keeping: it was reporting 14 mismatches when only the workspace had been left
  behind. The fixture version is the TARGET the migration writes, and step 2a checks the
  version landed there rather than trusting the two to have stayed in step.

  There is still no rollback: reverting is another INSERT carrying the longhand back.

**Two bugs in the `superseded` mechanism came out of that**, both `dict.get()` without a
default, and both of which fabricated history rather than failing:

* `rule_expr` was taken from the *current* rule unconditionally, so a prior version
  silently claimed today's predicate. That made an expression change unrepresentable.
* `scope_filter` defaulted to `None`, so any entry that did not mention it claimed the
  rule once ran **unscoped** — which is precisely the COH-B defect, invented out of
  nothing, on rules that were correctly scoped all along. It now inherits from the rule;
  an entry wanting NULL still says `scope_filter=None`, because a key present with value
  None beats the default.

Before today only one `superseded` entry existed and it happened to override the one
field that worked. Add an entry and check what it writes.


What did **not** convert, and why: window uniqueness (3), table-level variance (2) and
the cross-table rules (3). A scalar function takes values and returns a boolean; none
of those three shapes can be expressed that way. They need execution paths in the check
runner, which is also where `join_sql` belongs.

## `join_sql` is a column now — 2026-09-28

`config.rule_registry` gained `join_sql`, and the three cross-table rules stopped being
carried in Python. This was the top item under *Known gaps* and the one blocker on the
check runner being more than a draft.

**It holds the FROM-clause body, not a SELECT and not the predicate.** The joined table
expression with its aliases and ON condition — `prod.customer.subs_c s JOIN
prod.customer.ctct_c c ON s.CTCT_KEY = c.CTCT_KEY` — and `rule_expr` stays the predicate
referencing those aliases. That matters: `fixtures/rules.py` previously held a whole
`SELECT` **including its own WHERE**, so every cross-table rule carried two copies of its
predicate with nothing keeping them in step. The predicate is now stored once.

**`target_table` stays NOT NULL on a cross-table rule and names the DRIVING table.** The
runner reads `join_sql` in place of it when building the query, but `check_run`, the
scorecard and lineage all need one table to attribute a breach to, and "it is a join" is
not something a steward can act on.

What this deleted, all of it hand-maintained:

* `sql/checkrun.py` rebuilt each join by hand — hardcoding both table names and
  `s.CTCT_KEY = c.CTCT_KEY`, and inferring `LEFT JOIN` from whether the rule id contained
  `ORPHAN`. Gone; it reads the column.
* `jobs/run_checks.py` had a `CROSS_TABLE_JOINS` dict. Gone. The runner now hardcodes
  nothing about any rule. A cross-table rule whose `join_sql` is NULL is still written as
  `status = 'error'` rather than skipped, so a registry gap shows up in the data.
* `sql/seed.py` now applies the `prod.customer.*` rewrite to `join_sql` as well as to
  `target_table`. Miss that and a cross-table rule is seeded pointing at a catalog that
  does not exist.

**Proven unchanged:** `jobs/validate_run_checks.py` re-run against `workspace.dq_triage`
gives 33 PASS / 1 FAIL — the same result as before, with the FAIL still the pre-existing
`XREF_NAME_AGREEMENT` null-safety bug. 129 app tests pass, `verify.py` exits 0. And
`verify.py` earned its keep on the way: it failed with
`schema_drift: config.rule_registry.join_sql is declared … but never written by the
generator` before `build_fixtures.py` was updated.

**The workspace migration is APPLIED (2026-10-01).** `sql/out/migrate_join_sql.sql`, from
`sql/migrate_join_sql.py`. `ALTER TABLE ADD COLUMN` is a schema change so `appendOnly`
permits it; filling the three rules is an INSERT per rule at `rule_version + 1`, because
`appendOnly` blocks the UPDATE that a backfill would otherwise be.

Two things to know before running it:

* **Those v2 rows carry no behaviour change**, and each note says so. The rule is the same
  rule and the join was always this join; the only thing that changed is that a column
  exists to record it. A reader finding v2 will otherwise hunt for a difference that is
  not there. The alternative — unset `appendOnly`, UPDATE three rows, set it again — is
  fewer rows and no misleading version, at the cost of the audit table having been
  editable for the duration. That is a governance decision and the file says so rather
  than taking it silently.
* **The INSERTs name their columns explicitly.** `ALTER TABLE ADD COLUMN` appends
  `join_sql` at the END of the table while `sql/ddl/` declares it after `scope_filter`, so
  a positional `INSERT ... SELECT` would line every column up against the wrong one on a
  migrated table and load garbage without erroring. Verified 22 named columns against 22
  SELECT expressions against the DDL's 22, same set and same order.

## DQ runs on CDEs — 2026-09-28

**Every rule names its element.** `config.rule_registry.cde_id` is `NOT NULL`, the
check runner's worklist is the CDE register (`jobs/run_checks.py` joins
`v_rule_registry_current` to `v_cde_registry_current` and runs only what names a
registered element), and a column nobody has declared an element for is a column
nobody is monitoring. That is what "registration precedes discovery" was always meant
to mean, and until now it was half true: 20 of 34 rules attached to an element by
column match and 14 attached to nothing, so the quality score, the coverage view and
the runner each had a different denominator.

**Attachment is one rule, not two.** A rule attaches to the element it names, narrowed
by its column: a rule with a `target_column` attaches to that one binding of the
element, and a cross-table rule with none attaches to every binding of it. Until
2026-09-28 the join was `cde_id OR column match`, which let a tagged rule with a
column attach to every binding of a multi-column element. `sql/ddl/11_views_cde.sql`,
`domain/coverage.py` and `fixtures/coverage.py` all say the same thing and the
conformance test pins them. One consequence the first build hit: the two rules on
`EML_STTS_CD` used to attach to the email element by tag, and now attach because the
status column is a **binding** of that element — which is the honest statement of
what the status code is.

**The register is twenty elements.** Ten more, registered so that every rule could name
one: the two record keys, the vulnerable-customer flag, preferred language,
subscription status and reason, activation timestamps, record lifecycle timestamps,
network technology, the main billing offer and the benefit text. Same one person's
judgement as the first ten, and every note says so; two of them exist to carry a
shadow rule and so start with no active rule — which is the `no_rule` coverage finding
the first ten never exercised. The fixture now reads 26 bound columns, 8 `covered`, 12
`unvalidated`, 4 `no_rule`, 2 `scope_mismatch`, and `fixtures/verify.py` asserts that
every current rule with a column names an element that binds it.

**Nineteen since 2026-10-01: the vulnerable-customer flag is retired.** Its only rule,
`CTCT_SPCL_CARE_VARIANCE`, asked whether `SPCL_CARE_STTS` ever varies; on a 1000-row
extract an all-`N` column cannot tell a defaulted field from a population with no
vulnerable customers, and a failed variance check marks every row, so the element
read 0% and carried most of the headline's gap. Both were retired, not deleted —
`status = 'retired'` at a new version, effective 2026-10-01, in the fixture
(`CDE.retired_note`, `cdes.RETIRED_AT`) and in the workspace
(`sql/out/retire_vulnerable_customer.sql`, applied). Every run before that date and
COH-F, which was raised with the rule as a member, are left as they were; COH-F's
pill row now counts that check as on no element. The scorecard drops a retired
rule's runs at load (`_retired` in `scorecard.py`) so a run that predates the
retirement does not resurface it under `Not on a registered element`. The fixture
reads 25 bound columns, 7 `covered`. Re-registering it waits on the business saying
how many customers it expects to carry the flag.

**One denominator now.** The scorecard's `Not on a registered element` entry and
its `not scored` pane state are conditional on a
check that names no element, which the fixture cannot produce. They stay in the code
for a registry that predates the rule, and `tests/test_pages_render.py` asserts the
entry is absent rather than present.

**The workspace migration is APPLIED (2026-10-01), less one binding** — `sql/out/migrate_cde_scope.sql`
from `sql/migrate_cde_scope.py`. Part 1 adds `tolerance_pct` and a new `cde_version`
per existing element declaring one; part 2 inserts the ten new elements; part 3 gives
every current rule a new `rule_version` carrying its `cde_id`, because this workspace
cannot `ALTER` the column to `NOT NULL` over historical NULLs that `appendOnly` will
not let it fill — so the column stays nullable there and the verification query asserts
what the constraint would; part 4 names the rendered files to re-run for the changed
coverage view and the new threshold tables. See *Migrations applied* for what landed
and the one binding that did not.

## The threshold job — 2026-09-28

The spec's non-goal says it exactly: *"The agent may propose rules and threshold
changes; a human promotes them, as today."* This is the proposing half, and it is
**detection, not triage**: a limit is a property of a rule, a problem is a property of
a run, and nothing on either side reads the other. The first build of this put the
advice in the triage brief and on the cohort row; that was the wrong home and it is
gone.

**One job, one model call per element.** `notebooks/06_suggest_thresholds.ipynb` takes
its worklist from the CDE register, briefs the model on every active or shadow rule
that names an element, and writes one row per rule to `results.threshold_proposal`
(`sql/ddl/13_results_threshold.sql`). Two bases in every brief, labelled: the tolerance
the register declares on the element (`config.cde_registry.tolerance_pct` — what the
business will accept, and a **ceiling**) and where `violation_pct` has sat across every
run (min, median, p90, max, runs breaching — where the data is, not where it may be).
Where no tolerance is declared the expected advice is `unchanged`; history alone may
tighten a limit and never raise one.

**The ceiling is a row-level constraint.** `tolerance_pct` is copied onto the proposal
row, so `threshold_proposal_under_tolerance` is a CHECK on the table, not a join — and
it is also the notebook's validator and `fixtures/verify.py`. A model asked to advise
on a limit can answer "whatever makes the check pass"; this is what stops that.
`current_threshold_pct` and the statistics come from the brief, never from the
response. COH-B's two rules are the case the ceiling exists for: they sit at 20% and
50% on every run and the advice is keep, because the breach is scope.

**The review is the app's third write.** `results.threshold_review` records adopt,
reject or defer, with a reason and, for a deferral, a date. Adopting also appends a
`rule_version` to `config.rule_registry` carrying the proposed limit — the same append
that promotes a shadow rule, same table, same grant — and `adopted_rule_version`
records which. Rejections and deferrals have nowhere else to live; without the table a
rejected proposal is indistinguishable from one nobody looked at. `07_grants.sql` names
it as the third `MODIFY` and the proof query now expects three rows.
`adapter.review_threshold` is adopt-then-record, deliberately: a review row claiming an
adoption that never landed is the worse failure.

**Where a proposal has got to is a view.** `v_threshold_proposal_current`
(`14_views_threshold.sql`): the latest proposal per rule with its latest review folded
in — `no_change`, `open`, `adopted`, `rejected`, `deferred`, `in_force`. No
`current_date()` in it, so a deferral stays `deferred` with its date and the fold can
be pinned: `domain/thresholds.derive_proposal_current` is the labelled copy and
`tests/test_thresholds.py` diffs it against the shipped parquet. The Thresholds page
(Monitor group) is that view as clickable rows with a decision form on the row picked;
`tests/test_thresholds.py` adopts one through it and checks both appends.

**In the fixture, nine proposals, hand-authored** (`fixtures/thresholds.py`): three move
a limit, six say keep, one is rejected, one deferred, one left open for the write-path
test. **No model has produced one**, and notebook 06 has never run: `tools/
explain_notebook.py` plans it cleanly except for the four statements that touch a
column or table `migrate_cde_scope.sql` has not yet created. Item 6 in
`notebooks/README.md` is what to check on the first real run.

## Rules extracted from the "DQ Queries" folder — 2026-10-05

The workspace folder `/Users/lijinrui46@gmail.com/DQ Queries` holds seven saved SQL Editor
queries (First Name, Middle Name, Last Name, Birth Date, Phone, Identifier, Email) written
against the **real** source, `prod.udp_brnz_nrt_tech_view.table_contact_hist`, scoped to
`sf_mig_attribs_analytics.migration_scope_flag = 1`. This workspace has no `prod` catalog, so
none of them can run here. Their bodies are `.dbquery.ipynb` workspace files — the
queries API returns `query_text = ''` for every one, and `workspace list` shows the folder
empty; `databricks workspace export ".../DQ Queries/<name>.dbquery.ipynb"` is what reads them.

**34 rules came out, all in shadow, in `fixtures/rules.py` as `DQ_QUERIES_RULES`.**
Re-expressed on the mock `ctct_c` column for each attribute (`FIRST_NAME`→`FRST_NM`,
`MIDDLE_NAME`→`MID_NM`, `LAST_NAME`→`LAST_NM`, `PHONE`→`PHN_NO`/`MOBL_NO`,
`BIRTH_DATE`→`BRTH_TS`, `CONTACT_ID`→`CTCT_ID`), consolidated per column rather than 1:1:

| Family | Rules | Candidate to replace |
|---|---|---|
| Names | 17 — presence (first, last), placeholder, formatting, contamination, length, structure | nothing; fills `CDE_CUST_NAME`'s gap |
| Phone | 7 — AU format once washed, washable formatting, placeholder, mobile shared by >10 | `CTCT_PHN_FMT`, `CTCT_MOBL_FMT` |
| Birth date | 6 — present, future, under 14, 14–17 review, over 110, placeholder date | `CTCT_BRTH_PLAUSIBLE` |
| Contact ID | 4 — present, numeric, formatting, unique | nothing |

**The old rules are still active.** Shadow first: retiring `CTCT_PHN_FMT`, `CTCT_MOBL_FMT`
and `CTCT_BRTH_PLAUSIBLE` is a new `rule_version` each, done when a steward promotes the
replacements — and `CTCT_BRTH_PLAUSIBLE` is a COH-E member, so retiring it is a fixture
decision, not a registry one. `CTCT_BRTH_MINOR_REVIEW` finds 37 where it finds 27: the
`year > 2008` cut misses ten 17-year-olds born after 2 September 2008.

**Bugs in the source queries, verified on the warehouse, fixed on the way in.** Spark
`RLIKE` is Java regex, so the queries' POSIX classes are character SETS: `[[:space:]]`
matches the letters `: s p a c e` and `[[:cntrl:]]` the letters `c n t r l`. On the
warehouse: `'Ms Jane'` fails the title check while `'Mrs'`, `'Msc'` and `'Mrsa'` pass it,
`'12 Smith Street'` and `'Unit 4'` pass the address check, `'John'` has a control
character and a real one does not, and `' 0412'` has no leading space. And `'\.'` in a
Spark literal is `'.'`, so the title check took any character after `MR`. **Every count in
those queries that rests on one of these patterns is wrong** — first-name
`STARTS_WITH_TITLE` (145) and `UNRELATED_IDENTIFIER_NOTE_OR_ADDRESS` (67) among them. The
two Phone placeholder lists had drifted (42 and 14 numbers); the rules use the union.

**SQL and Python agree 34 of 34 on adversarial values** — names with titles, companies,
addresses, control characters and edge punctuation; phones in every washable shape;
birthdays on each band's boundary — with the age rules' `current_date()` pinned to the
fixture's final run. Unpinned they disagree on the boundaries, by design: the queries
measure age from today, the runner has no run-date placeholder, so the evaluator uses
`rules.AS_OF` (asserted equal to `SNAPSHOT` in `build_fixtures.py`) and **a warehouse
count of the three age rules matches the fixture only on that date.** A `{run_date}` token
in the runner is the fix and is not built.

Two bindings were added so every rule names an element: `MID_NM` on `CDE_CUST_NAME` and
`CTCT_ID` on `CDE_CUST_KEY`. 27 bound columns; coverage reads 8 covered (`CTCT_ID`, by the
orphan check tagged on its element) · 13 unvalidated (`MID_NM`, by name agreement) ·
4 `no_rule` · 2 `scope_mismatch`. Shadow rules do not count, so `CDE_CUST_NAME` is still a
gap until the name rules are promoted. Their history is flat (`build_fixtures.STEADY`)
and their run rows draw duration and DBU from their own rng (`added_rng`): a draw from the
shared one shifted every later rule's figures, cohort totals and threshold statistics
included. Every value the original 35 rules produce is identical to before; add a rule
the same way.

**Not taken:** the Email query is a reconciliation of flags another system computed
(`dq_email_invalid_*_flag` against CDQ), not rule logic; `CUSTOMER_ID` and `ORG_ID` have no
mock table; middle-name presence is informational in the source; the 2+ shared-phone
variant left the query's own roll-up; the two `ESTATE OF THE LATE` / `STATUS = '5'`
queries are exploration with no rule name.

**The workspace migration is APPLIED (2026-10-05)** — `sql/out/migrate_dq_queries.sql`,
from `sql/migrate_dq_queries.py`. Two element versions (the bindings, written from the
fixture) then 34 rule INSERTs at `rule_version` 1, `status = 'shadow'`, then read-only
checks. Every INSERT is guarded (`NOT EXISTS` on the rule_id, `NOT array_contains` on the
binding), so re-running it is a no-op — appendOnly means a duplicate could never be removed.
Validated without writing on 2026-10-05: all 42 statements `EXPLAIN` to a clean plan
(`AppendDataExecV1` for every INSERT), read from the plan text — a deliberately broken
INSERT comes back `SUCCEEDED` with the error in the plan, and the check catches it. And the
SELECT half of each INSERT, run on its own, returns the exact row it would store; those
stored predicates, run against `dq_mock_ctct_c` with `current_date()` pinned to the fixture's
final run, reproduce all 34 fixture counts and rows-scanned exactly.

Applied statement by statement: each of the 36 INSERTs appended one row (registry 86 → 120
rule rows; `CDE_CUST_NAME` v3, `CDE_CUST_KEY` v2). Checks: 34 shadow, zero rules without a
binding, zero canonical names. Coverage reads 8 covered · 12 unvalidated · 4 `no_rule` ·
2 `scope_mismatch` against the fixture's 13 unvalidated — the gap is `EML_STTS_CD`, i.e.
`fix_cde_email_binding.sql`, still unapplied. Re-running every INSERT afterwards inserted
0 rows. Nothing writes `check_run` for these rules: there is no scheduled runner.

**Ten of them moved onto three new helpers the same day — APPLIED.**
`au_phone_digits_v1` (the only helper returning a value, not a boolean),
`is_phone_placeholder_v1` and `is_name_placeholder_v1`, in `sql/ddl/12_functions.sql` and
created in the workspace by `sql/out/migrate_dq_fn.sql` (from `sql/migrate_dq_fn.py`). It
creates with `CREATE FUNCTION IF NOT EXISTS`, never `OR REPLACE`, and never re-issues the
four existing helpers. `is_phone_placeholder_v1` repeats the normalising CASE rather than
calling `au_phone_digits_v1`: a helper calling a helper couples their versions. The ten
rules are at v2 in the fixture and the workspace (130 rule rows), still shadow, v1 kept as
history; `build_fixtures.py` now lets a superseded entry say `status="shadow"`, so v1 is not
recorded as having been active and promoted. Proven before the INSERTs: v1 and v2 counted
side by side on `dq_mock_ctct_c` give identical counts and identical scopes for all ten; the
adversarial set still agrees 34/34 through the helpers; one number written eleven ways is
caught by v1, v2 and Python alike. Re-running the file inserted nothing.

`sql/migrate_dq_queries.py` now reads version 1 from the fixture: regenerated, it differs
from the file that was applied only in the wording of the two phone-placeholder notes.

**Scope filters are longhand on purpose.** `sql/seed.py`, `sql/checkrun.py` and the runner
rewrite `dq.fn.` in `rule_expr` only; a helper in a `scope_filter` would be seeded as an
unresolvable name. The generator asserts none is there.

## Onboarding — 2026-10-05

Choose a table from Unity Catalog, bind its columns to registered elements, generate its
checks from templates, measure them in shadow, promote them — and later pause or
decommission it. Built as a prototype in `onboarding/` against the disposable schema
`workspace.dq_onboard` (cloned from `dq_triage`; `onboard.py setup` creates it,
`DROP SCHEMA … CASCADE` resets it), with the app pages in `dq-app/`. **Nothing of it
touches `dq_triage`.** `onboarding/README.md` has the commands.

**Two deployments of one codebase.** The Databricks App `dq-triage` reads `dq_triage`;
merged, it shows the Onboarding pages with "No tables are selected yet", because
`dq_triage` has none of the onboarding tables and the app has no grant on them. The App
`dq-onboard` is the same `dq-app/` with `DQ_SCHEMA=dq_onboard`, `DQ_NOTIFY=off` and
`DQ_ONBOARD_ALLOW_SELF_APPROVAL=1`; its `app.yaml` is a staged copy, not the committed
one. Its service principal has `SELECT` on `dq_onboard` and `dq_triage`, and `MODIFY`
on `dq_onboard`'s rule register, monitored_table, binding_proposal and binding_review.

**The flow, and who acts at each step.**

| Step | Who | Writes |
|---|---|---|
| Add tables → Continue → suggest (optional) → **Submit** | person | `monitored_table`, `binding_proposal` (suggestions) |
| Discover: UC tag, then a unique value-pattern match (≥95%), then column name | job | `binding_proposal` |
| Review bindings, per column | person | `binding_review` |
| Apply approvals; generate checks from templates in shadow; measure them | job | `cde_registry`, `rule_registry`, `check_run` (shadow only) |
| **Promote** | person | `rule_registry` (one batched append) |
| Pause / resume / **decommission** | person | `monitored_table` (+ retired rule versions); the job then unbinds |

**Two jobs, split by what their results can do.** `dq-onboard steps` (172834918560011)
starts when `monitored_table` or `binding_review` changes — a table-update trigger, so
the app triggers nothing and "no job triggering" holds — and runs discover → apply →
unbind decommissioned → generate → measure new shadow checks with `run_checks.py
--shadow-only`. It can never write an active result. `dq-checks` (851061192655949) runs
the full check on every selected table daily at 03:00 Sydney, and is the only source of
active results. A shadow-only run is never "the latest run": `metrics.latest_run_id`
takes the latest run that measured an active check, or every page would show one table.

**Rules that look like bugs and are not.**

* **Selecting a table writes nothing until Submit.** The first build wrote on "Select"
  and a user found a table onboarding before reaching any Submit.
* **Every write opens a confirmation dialog first** (`onboarding_style.confirm`), and
  every outcome — opened, closed unwritten, written, refused with its reason — is logged.
  A refusal used to show only inside the dialog and could not be diagnosed.
* **Whoever suggests a binding cannot approve it** — page, adapter and apply job each
  refuse. `DQ_ONBOARD_ALLOW_SELF_APPROVAL=1` waives it on a test deployment; every waived
  approval's reason starts `[second approver waived]`, and the apply job accepts a
  self-approval only with that mark.
* **A rejected column is not proposed again** by name or pattern — only by a tag added
  since.
* **Templates are registered rules with the column replaced** (`onboarding/templates.py`,
  15 today); `equivalence()` proves each reproduces its source rule. The generator
  writes concrete rule rows — the runner never fills placeholders — and **leaves a column
  with hand-written rules alone**: generating anyway produced 25 copies on
  `dq_mock_ctct_c`, 8 of them the same check written with the newer helpers, caught only
  by identical measured counts. A template whose helper function is not deployed, or
  whose input type differs from the column's, is skipped and says why.
* **Promotion is offered only once every binding is decided and every shadow check is
  measured.** A promoted check counts from the next daily run.
* **Decommission is permanent; pause is not.** Retiring the table stops the runner
  (it checks only `selected` tables); every check gets a retired version; the job removes
  the bindings. Results and Triage problems stay as history. Table codes are never reused.
* **A laptop cannot write the rule register.** `adapter._require_platform_identity`
  refuses a durable promotion, adoption or onboarding write without a platform identity;
  the rule register had no CHECK constraint doing what the register's do.
* **Add tables reads readability from the privilege views in one query per schema**, not
  a SELECT per table, and sizes on a few reused connections; the catalog is cached an
  hour. It lists what the *app's service principal* can see, not the user.

**The onboarding schema is DDL since 2026-10-06.** `sql/ddl/15_config_onboarding.sql`
declares the four tables with 14 CHECK constraints and `appendOnly`;
`16_views_onboarding.sql` the four views, lifted unchanged from `onboard.py`; `01` gains
`template_id` / `template_version` at the END of its column list (where `ADD COLUMNS`
puts them on every table that predates them) and a constraint that both or neither are
set. What changed around it:

* **`onboard.py setup` declares no table.** It renders 15, 08, 11, 14 and 16 with
  `sql/render.render` and runs them a statement at a time (`render.statements`),
  tolerating "already exists" on `ADD CONSTRAINT`, so it is idempotent. It needs `sql/`
  beside it, so it runs from a laptop; the jobs never call it.
* **Every onboarding INSERT names its columns**, and `fixtures/verify.py` check 6 diffs
  `onboard.py`'s `MONITORED_COLS` / `TEMPLATE_COLS` / `PROPOSAL_COLS` / `RULE_COLS` and
  the app's `MONITORED_COLUMNS` / `PROPOSAL_COLUMNS` / `REVIEW_COLUMNS` against the DDL.
  The fixture writes the two template columns as NULL so check 3 holds `01` to them.
* **What the constraints refuse** that only code refused before: a pause or decommission
  without a note, a job method signed by a person or `suggested` signed by a job, a
  suggestion without a reason, a rejection without a reason, a template whose
  expression has no column placeholder. The second-approver rule spans two tables and
  stays in the app and the apply job.
* **`render.py` appends 15 and 16 to its order** rather than slotting them in, so no
  rendered file was renumbered; `ALL.sql`'s counts (14 tables, 10 views, 7 functions,
  55 constraints) are now computed, not typed.
* **Applied to `dq_onboard` on 2026-10-06**: every existing row checked against every
  constraint first (zero violations over 327 rows), every statement `EXPLAIN`ed and the
  plan text read, then setup run twice. The prototype's `binding_review_decision`
  constraint was dropped as a duplicate of `binding_review_decision_enum`. The existing
  tables keep their old column comments and no `CLUSTER BY`: `CREATE TABLE IF NOT
  EXISTS` does not alter a table that is there.

**Onboarding in dq_triage — 2026-10-06.** Taken as a decision ("full onboarding in
dq_triage"), in this order:

* `onboard.py --schema dq_triage install` — `01`'s template columns, 15, the views
  re-created (08, 11, 14, 16), 15 templates seeded. Every statement `EXPLAIN`ed first;
  coverage read 8 · 12 · 4 · 2 before and after. `setup` refuses `dq_triage`: it clones
  FROM there. `wh.use_schema` / `--schema` is how one codebase serves both schemas.
* `onboard.py --schema dq_triage adopt` — selects every table carrying an active rule:
  `dq_mock_ctct_c` and `dq_mock_subs_c`, codes `DQ_MOCK_CTCT_C` / `DQ_MOCK_SUBS_C`,
  signed, with a note saying why. **It exists because of a trap**: `run_checks.py` runs
  every table while `monitored_table` is empty and only selected ones once anything is,
  so the first table onboarded would have silently stopped the mocks being checked.
* Two jobs, copies of `dq_onboard`'s with `--schema dq_triage`. The first steps run
  proposed nothing, generated 4 shadow checks (bound columns with no rule) and measured
  40 shadow checks; the first check run wrote 31 active verdicts, no errors.
* **Grants, then redeploy.** A person granted the `dq-triage` principal (`fa379f33-…`)
  `SELECT` on schema `dq_triage` and `MODIFY` on monitored_table, binding_proposal,
  binding_review and threshold_review — six MODIFYs in all, as `07_grants.sql` says —
  and the app was redeployed from main after. The order matters: `_q_optional`
  tolerates a missing table, not a missing privilege, deliberately, so the new code
  before the grants breaks the Scorecard and Tables pages. The threshold_review grant
  is the one *Known gaps* listed as written and unapplied; it is applied now.
* There is no self-approval waiver in `dq-triage`: a person's binding suggestion needs a
  second person. Job proposals can be approved by anyone.

**Open, and decisions rather than code:** who may approve a binding (the element's `owner_group` is shown, not enforced —
those groups do not exist in this workspace); browsing as the signed-in user (needs the
app's user-authorization scope); `CTCT_BRTH_PLAUSIBLE`'s `year(BRTH_TS)` fails on
`'31-02-1988'` under ANSI (the runner now records the missing sample instead of failing);
number-typed key columns get no checks until templates accept them; and the precomputed
catalog inventory that would judge readability by the check job's identity.

## Invariants — things that look like bugs and are not

**Execution is the defining non-goal.** No `UPDATE`/`MERGE`/`DELETE` on business data, no
job triggering, no execute button. `config.playbook` deliberately has no `fix_body`,
`fix_sql`, `job_id` or `notebook_path` — a body column is the first step to an execute
button. If someone asks for one, that is a scope change to escalate, not a schema change.

**A notification is triggered by a decision, never by a threshold.** A check falling
past its limit surfaces a candidate in the app and sends nothing; what sends is
`reviewed` + `decision = 'accepted'` by an `obo_user`, which is a named human saying
the problem is real. `domain/notify.should_notify` is the one definition of that and
refuses everything else — a rejection and a deferral are also `reviewed` rows, and
triggering on event type would mail a data owner about a problem just dismissed.
Wiring it to a threshold instead would mean the app asserting a defect nobody
confirmed, which is the same mistake as reading the Triage queue's `rule defect` mark
off `defect_location`.

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

**Quality scores and inventory counts share one denominator since 2026-09-28.** Every
rule names its element, so "the checks attached to a registered element" and "every
check that ran" are the same set, and the scorecard's headline figure and the monitor
pages' per-table scores count the same checks. The machinery
that kept two denominators apart is still there and still the right seam:
`domain/coverage.attached_rule_ids` is the single definition of the scored set, read
back off the coverage view and never re-derived by matching table and column; the
monitor pages take it from `ui/monitoring.domain_filter`; and the scorecard's `Not on
a registered element` entry and its `not scored` pane state
render only when a check that names no element has run — which a registry that
predates the rule can still produce. Keep the page terse; put the long explanation in a
tooltip.

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
cannot exercise the pass path and leaves closure rate with no denominator. (Thirty-six in
shadow since 2026-10-05 — the 34 below are additions, not a change to this design.)

**Unity Catalog has no `INSERT` privilege.** The spec's wording ("granted `INSERT` on
`dq.results`") is not expressible — `MODIFY` is the finest-grained write privilege and it
permits `UPDATE`/`DELETE` too. The enforceable equivalent is table-level `MODIFY` on
exactly six tables plus `delta.appendOnly` — the register, the rule registry, since
2026-09-28 the threshold review, and since 2026-10-05 onboarding's monitored_table,
binding_proposal and binding_review (granted in both `dq_onboard` and `dq_triage`). See
`sql/README.md`.

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

- **`results.check_run` in `dq_triage` is written daily since 2026-10-06** by `dq-triage
  checks`, owned by the account that created it. Nothing schedules notebook 03 after it,
  so no new cohort forms from those runs.
- **The `rule_expr` comparison is done: 33 of 34 agree.** `XREF_NAME_AGREEMENT`'s
  stored SQL misses 2 violations because `<>` is not null-safe, and
  `XREF_OPEN_TS_AGREEMENT` carries the same pattern latently. See *What the workspace
  actually holds* for the diagnosis. Fixing them changes `fixtures/rules.py` and every
  number downstream of it, so it is a decision, not a typo — unlike the two deliberately
  unscoped rules, there is no demo reason for this one to stay broken.
- **No profiler has ever run in the warehouse.** `results.cde_profile` holds the
  fixture's pandas output, seeded. The Spark profile job does not exist; the worklist
  query (`v_cde_registry_current`) and the masking logic are both already written and
  table-agnostic, and `fixtures/profile.py` `_frame()` is the one hardcoded seam.
- **The unattached-rule set is empty by construction since 2026-09-28**, in the DDL and
  the fixture; in the workspace it is 2 rules until `fix_cde_email_binding.sql` runs. What the
  coverage view now reports instead is `no_rule` on four bindings, and that has a
  surface: the scorecard's element list.
- **One workspace step is written and NOT applied** (2026-10-01):
  `sql/out/fix_cde_email_binding.sql` (one binding — see *Migrations applied*). The
  threshold grants that sat beside it were applied on 2026-10-06 (schema-level `SELECT`
  on `dq_triage`, `MODIFY` on `threshold_review`).
- **No model has produced a threshold proposal.** Notebook 06 has never run. The first
  run is the test of the ceiling, of `unchanged` being reached for, and of the figures in
  the rationale — `notebooks/README.md` item 6.
- `check_run.scope_fingerprint` is `NULL` everywhere — the spec's open question on pinning
  verification scope.
- Detective vs preventive control, retention, and who may approve are open questions in
  the spec. Do not resolve them in code.

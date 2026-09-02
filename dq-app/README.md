# DQ Triage App

Streamlit front end for `dq-triage-agent-spec.md` v1.0 — cohort triage, recommendation
and the disposition register.

Runs on a laptop against the generated fixture. No workspace, no auth, no network.

```bash
cd dq-app
../.venv/bin/streamlit run app.py
```

Needs `fixtures/out/` to exist. If it does not:

```bash
cd fixtures && ../.venv/bin/python build_fixtures.py && ../.venv/bin/python verify.py
```

Tests — pure logic, page renders, and the register write path, none of which need a
workspace:

```bash
cd dq-app && ../.venv/bin/python -m pytest tests -q
```

---

## What this app does not do

It does not execute anything. There is no `UPDATE`, `MERGE` or `DELETE` on business
data, no job trigger, no execute button, and no code path that could construct one.
Remediation happens in the data owner's own pipeline through their own change
process; this app records that it was authorised and that someone reported doing it.

That is a claim you can check three ways, in increasing order of how much they are
worth:

1. Read `dq_app/data/databricks_source.py` — the only two statements it writes are
   `INSERT`s, to `results.disposition` and `config.rule_registry`.
2. `config.playbook` has no `fix_body`, `fix_sql`, `job_id` or `notebook_path`. The
   Playbook page prints its own column list so the absence is visible.
3. **The grants.** `sql/ddl/07_grants.sql` gives the app's service principal `MODIFY`
   on exactly those two tables and nothing on any `prod.*` table, and both are
   `delta.appendOnly = true`. A workspace admin can demonstrate the guarantee from
   Unity Catalog alone, without reading any of this code. That is the one that counts.

## Pages

| Page | What it is for |
|---|---|
| **Scorecard** | The health of the data, and nothing else. Headline figures for the latest run, **what changed** (checks that were clean and are not any more, with the date they turned), then per-table insights — and from each table, the problems behind its failing checks with a **Diagnose** button straight into them. |
| **Cohorts** | One row per problem. Leads with the grouping — *21 failing checks → 6 problems* — because that ratio is the queue's whole claim, and closes with **Resolution**: whether problems reach a recorded outcome and whether fixes hold. |
| **Cohort detail** | Evidence → recommendation → register → act, in that order. Member rules carry their own 40-run history; the hypothesis sits next to the profiling that produced it. The playbook entry behind a recommendation appears here, with its prior-use count and recurrence rate. |
| **Register** | The append-only event log as an audit artefact: period filter, CSV export, cohorts with nothing recorded listed explicitly, and the control test. |
| **Rule registry** | Current rules with derived `effective_to`, full version history, and shadow → active promotion — the app's only other write. |

## Architecture

```
app.py                      nav only
dq_app/
  domain/                   pure logic — no Streamlit, no Spark, no I/O
    lifecycle.py            the fold from events to state; what a person may author
    metrics.py              every spec metric, each carrying its own target
    integrity.py            the control test
  data/
    adapter.py              THE SEAM. every page imports from here
    local_source.py         fixtures/out/*.parquet          (default)
    databricks_source.py    Unity Catalog                   (never executed)
    identity.py             who is acting, and how we know
  ui/
    theme.py                palette, status vocabulary, SVG icon set, CSS
    components.py           reusable renderers
    pages/
.streamlit/config.toml      theme — the app's palette, not Streamlit's defaults
```

## Interface conventions

**No emoji.** Icons are inline SVG on a 24-unit grid, stroked in `currentColor`, so
they inherit the size and colour of the text around them and render identically on
every platform. They live in one map in `theme.py`: one icon per concept, reused
wherever that concept appears.

**Colour never carries meaning alone.** Every status is a tinted badge *with its word
in it*. The word is the channel that survives greyscale, colour blindness, and a
screenshot pasted into a ticket. Red, amber and green are reserved for severity and
outcome; charts draw from a separate categorical ramp so nothing decorative can be
mistaken for a status.

**Explanations are tooltips, not paragraphs.** The reasoning behind a metric, the
caveat on a denominator, why a control cannot be a table constraint — all of it goes
in `help=`, reachable by anyone who wants it and invisible to everyone else. Prose
under every widget makes a dense tool read like a tutorial.

**The Scorecard is about the data; the Cohorts page is about the work.** Detection
figures and resolution figures answer different questions for different people, and
mixing them produced a page that was neither. The one thread between them is the
**Diagnose** button: when the Scorecard shows a table failing its checks, it also
shows the problems those failures belong to and links straight into them. Detection
that cannot hand you to the diagnosis is where a data-quality tool usually stops
being useful.

**Plain words on screen, the spec's words in the tooltip.** A steward should not need
to know what `P1_block`, `disposition coverage` or a `rule_expr` is. Severities read
"P1 · Critical"; checks are named, not identified (`Contact email contains an @`, not
`CTCT_EML_NO_AT`); metrics are "Verified fixed" and "Time to fix", each tooltip naming
the spec term it implements so the mapping back to `dq-triage-agent-spec.md` stays
traceable.

**"Findings" is never called "records".** One finding is one row failing one check,
and a single bad row can produce several — the 240 malformed addresses trip six format
checks each. Counting distinct rows would need a key recorded on every finding, which
the runner does only for samples it keeps, so the honest word is used instead.

**"Cohort" is explained wherever it first appears.** It is the system's one invented
word and nothing else makes sense without it, so the same one-line definition — written
once, in `theme.COHORT_ONE_LINER` — sits under the Cohorts title, under the cohort band
on the Scorecard, and under the cohort detail title, with a longer *What is a cohort?*
expander on the first two.

**Short static tables are HTML, not `st.dataframe`.** Streamlit's data grid measures its
own box on first paint, and in some slots that measurement lands at a few pixels and
never recovers, leaving a table with one clipped column. Interactive grids are worth
living with; a six-row summary on a monitoring page is not, so `components.summary_table`
renders those as plain markup.

**There is no Playbook page.** The playbook is P0 in the spec, but as *reference
attached to a recommendation*, not as a library to browse. It appears on the cohort
detail page with its prior-use count and recurrence rate, which is where a steward
deciding whether to follow the advice actually needs it.

**The seam.** Pages import only from `adapter.py`, so the local → workspace switch is
one environment variable:

```bash
DQ_APP_DATA_SOURCE=local        # default — reads fixtures/out/*.parquet
DQ_APP_DATA_SOURCE=databricks   # requires `databricks auth login`
```

Both sources return the same DataFrame shapes. Add a column to one, add it to the other.

**Derived state, computed once.** `results.disposition` is an append-only event log
with no status column, and `config.rule_registry` is append-only with no stored
`effective_to`. Current state for both is derived at read time. `sql/ddl/08_views.sql`
is the single definition; `domain/lifecycle.py` is a labelled Python copy of it, and
`tests/test_lifecycle_conformance.py` asserts the copy reproduces the shipped
`v_cohort_current` output row for row. Change the view without changing the copy and
that test fails.

**Identity is not a form field.** Reviewer and approver identity comes from the
platform's `x-forwarded-access-token`. Locally there is a stand-in persona picker,
and every event it writes is stamped `actor_source = 'local_standin'` — a value the
table's own CHECK constraint rejects, so a demo identity cannot be mistaken for a real
one even if the row were somehow shipped.

## Local writes are session-only

`fixtures/out/` is generated output gated by `fixtures/verify.py`, so the app does not
edit it. A review or approval recorded locally lives in `st.session_state` and is lost
on restart. The register still behaves correctly — append-only, monotonic `event_seq`,
state re-derived — it simply is not durable, and the sidebar says so.

## Deploy

```bash
databricks sync --watch . /Workspace/Users/<you>/dq-app
databricks apps deploy dq-triage
```

`app.yaml` sets `DQ_APP_DATA_SOURCE=databricks` for the deployed environment. Uncomment
`databricks-connect` in `requirements.txt` first.

> **Before investing time in workspace mode:** OAuth login to a corporate Databricks
> workspace often sits behind conditional-access or device-compliance policy, which can
> block a non-enrolled machine. Confirm with the platform team. Local mode is
> unaffected either way.

## Known gaps

- **Nothing here has run against a real workspace.** `databricks_source.py` is written
  and reviewed, never executed — same status as `sql/ddl/`.
- **Violation samples do not line up with cohorts in the fixture.** The check runner
  only sampled the final run, while each cohort's `member_result_ids` point at the run
  that raised it, so no cohort has evidence rows from its own raising run. The detail
  page falls back to the newest samples for the same rules and labels the substitution
  rather than hiding it. The fix belongs in the check runner, not here.
- **Cohort precision is not instrumented**, because capturing a steward's correction
  needs the merge/split affordance (spec P1). It is shown as "not instrumented" rather
  than left off the scorecard.
- **`scope_fingerprint` is `NULL` everywhere**, so verification matches on rule and
  table. This is the spec's open engineering question about pinning verification scope.

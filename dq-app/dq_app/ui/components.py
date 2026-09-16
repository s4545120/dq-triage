"""Reusable renderers, so the same fact looks the same wherever it appears.

Two conventions worth knowing before adding to this file:

**Explanations live in tooltips, not on the page.** The reasoning behind a metric,
a caveat about a denominator, why a control cannot be a table constraint — all of it
belongs in `help=` where a reader can reach it and everyone else can ignore it. Prose
printed under every widget makes a dense tool feel like a tutorial.

**Evidence is shown, not summarised.** A member-rule row carries its own run history;
a hypothesis sits next to the profiling that produced it. A steward confirming or
discarding a hypothesis needs the numbers on the same screen, because a summary they
have to trust is a summary they cannot check.
"""

from __future__ import annotations

import html
import json
import re

import pandas as pd
import streamlit as st

from dq_app.data import adapter, identity
from dq_app.domain import lifecycle
from dq_app.ui import theme


def opt(value):
    """None for anything pandas considers missing.

    Parquet hands back `NaN` for a missing string, and `NaN` is truthy — so
    `value or default` silently renders "nan" and `if value:` takes the wrong branch.
    Everything read out of a row goes through here first.
    """
    if value is None:
        return None
    if isinstance(value, (list, tuple, set)):
        return value or None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):  # arrays and other non-scalars
        pass
    return value


def as_list(value) -> list:
    """A row's array-valued column as a plain list. Empty when it is missing."""
    if value is None:
        return []
    try:
        return list(value)
    except TypeError:
        return []


# --- Page chrome ------------------------------------------------------------


def page_chrome() -> None:
    theme.inject_css()
    _sidebar_source()
    _sidebar_identity()


def _sidebar_source() -> None:
    st.sidebar.divider()
    if adapter.is_local():
        from dq_app.data import local_source

        st.sidebar.markdown(
            theme.badge("Local fixture", "moderate", "table"), unsafe_allow_html=True
        )
        st.sidebar.caption(
            f"`{local_source.fixture_dir().name}/` · counts and samples are real; "
            "cohorts and register events are authored. See fixtures/README.md."
        )
    else:
        st.sidebar.markdown(
            theme.badge("Unity Catalog", "success", "link"), unsafe_allow_html=True
        )

    if not adapter.writes_are_durable():
        pending = len(adapter.get_dispositions()) - len(adapter._base_dispositions())
        st.sidebar.caption(
            f"Writes are session-only — {pending} recorded here, lost on restart."
        )


def _sidebar_identity() -> None:
    who = identity.current()
    st.sidebar.divider()
    if who.is_platform:
        st.sidebar.caption("Signed in")
        st.sidebar.markdown(f"**{who.display_name}**  \n`{who.email}`")
        return

    options = list(identity.LOCAL_PERSONAS)
    st.sidebar.selectbox(
        "Acting as",
        options,
        index=options.index(who.email) if who.email in options else 0,
        key="_local_identity",
        format_func=lambda e: identity.LOCAL_PERSONAS[e],
        help="Local stand-in. In the workspace this control does not exist — identity "
        "arrives in x-forwarded-access-token and cannot be chosen. Events written here "
        "are stamped local_standin, which the table's CHECK constraint rejects.",
    )


# --- Row tables -------------------------------------------------------------
# The scorecard and the triage queue are both drawn with these rather than with
# `st.dataframe`, and for the same three reasons. A data-grid cell cannot hold a
# tinted severity badge or a coloured phrase; the grid measures its own box and
# occasionally lands at nothing; and — the one a reader notices — its row selection
# fires only from the checkbox in its own gutter, so a page that says "select a row"
# is asking for a click on a 14px target the reader has to find first.
#
# Here a row is a container holding its markup and a real button stretched over the
# whole row at zero opacity. The row is clickable everywhere, hovers as one object,
# and is still a button, so the keyboard reaches it. The CSS that makes that work is
# the `st-key-dqrow_` block in theme.py, where each rule is labelled with what broke
# without it.


def row_head(heads: list, grid: str) -> None:
    """The header line for a row table. `heads` are labels, or (label, "n") to align
    a numeric column right."""
    cells = "".join(
        f'<span class="{h[1]}">{html.escape(h[0])}</span>' if isinstance(h, tuple)
        else f"<span>{html.escape(h)}</span>"
        for h in heads
    )
    st.markdown(
        f'<div class="dq-rowgrid head" style="grid-template-columns:{grid}">'
        f"{cells}</div>",
        unsafe_allow_html=True,
    )


def clickable_rows(rows: list[dict], grid: str, cells, key: str, id_key: str,
                   label, picked=None) -> str | None:
    """A block of whole-row click targets. Returns the id clicked, or None.

    `key` is a short name unique to this table on this page — it prefixes the
    container keys, so two row tables on one page cannot collide. `cells` renders one
    row's markup from its dict; `label` gives the hidden button its accessible name.

    Plain dicts rather than `itertuples`, because half these column names carry a
    space and `itertuples` silently renames those to positional `_7`.
    """
    got = None
    for row in rows:
        row_id = row[id_key]
        with st.container(key=f"dqrow_{key}_{row_id}"):
            st.markdown(
                f'<div class="dq-rowgrid{" dq-row-on" if row_id == picked else ""}" '
                f'style="grid-template-columns:{grid}">' + cells(row) + "</div>",
                unsafe_allow_html=True,
            )
            if st.button(label(row), key=f"_open_dqrow_{key}_{row_id}"):
                got = row_id
    return got


_ASIDE = re.compile(r"\s+(--|—)\s.*?\s(--|—)\s+")


# Whose turn it is, said on the page rather than only in a tooltip. Read off the
# lifecycle state, which is the only thing that actually knows: `owner_group` is the
# domain that owns the data and is the same for most of the register, so printing it
# on every row would say nothing.
WAITING_ON = {
    "awaiting_triage": "the triage job",
    "awaiting_review": "you",
    "awaiting_approval": "an approver",
    "awaiting_verification": "the next run",
}


def waiting_on(row) -> str:
    """One phrase naming who the next move belongs to. Shared by the Triage queue and
    the problem detail, so the two cannot answer it differently."""
    state = row["lifecycle_state"]
    if state in WAITING_ON:
        return WAITING_ON[state]
    if state in ("approved_awaiting_execution", "reopened"):
        # With whoever is actioning it. The external reference is the concrete answer
        # where one was recorded; the owning group is the fallback.
        ref = opt(row["external_ref"])
        return str(ref) if ref else str(row["owner_group"])
    return "—"


def problem_title(hypothesis, limit: int = 62) -> str:
    """A cohort's opening claim, as a title.

    There is no stored title column and adding one is a fixture and DDL change rather
    than a UI one, so the title is derived — in one place, because the Scorecard, the
    Triage queue and the detail page all show it, and three copies of a `split(".")`
    are three chances for one problem to carry three different names.

    Two cuts, in this order, because a root-cause hypothesis is written as an argument
    and its first line is not a headline:

      1. A dashed aside is dropped. "Twelve mobile subscriptions -- ten of them
         active, two since cancelled -- carry the literal 'service-number-unknown'"
         is a claim with a parenthetical wedged into it; the parenthetical is detail
         for the detail page.
      2. The sentence ends at the first `.` or `:`. The colon matters as much as the
         stop — "Scattered contactability gaps with no shared driver: 18 contacts
         with no mobile, 24 with a malformed landline" states the finding before the
         colon and enumerates after it.

    What this deliberately does not do is rewrite. The title is the author's own
    words, cut — so a badly-written hypothesis yields a badly-written title, which is
    the correct place for that problem to show up.
    """
    text = _ASIDE.sub(" ", str(hypothesis)).strip()
    first = re.split(r"[.:]", text)[0].strip()
    return first if len(first) <= limit else first[: limit - 1].rstrip(" ,;—-") + "…"


# --- Tiles ------------------------------------------------------------------


def kpi_row(tiles: list[dict]) -> None:
    """`tiles` are dicts of label / value / sub / tone / help."""
    for col, t in zip(st.columns(len(tiles)), tiles):
        with col:
            st.markdown(
                theme.kpi(t["label"], t["value"], t.get("sub", ""), t.get("tone")),
                unsafe_allow_html=True,
                help=t.get("help"),
            )


def metric_tile(metric) -> None:
    """One spec metric: figure, target, and whether it is met.

    The target sits with the number because a scorecard showing 64% without
    "target 75%" invites the reader to supply their own idea of good. The reasoning
    and the caveats go in the tooltip — on the page they would be a wall.
    """
    if metric.met is True:
        mark, tone = "On target", "success"
    elif metric.met is False:
        mark, tone = "Below target", "critical"
    else:
        mark, tone = "Not judged", "neutral"

    sub = " · ".join(x for x in [metric.target, metric.basis] if x)
    st.markdown(
        theme.kpi(metric.label, metric.display, sub) + theme.badge(mark, tone),
        unsafe_allow_html=True,
        help=" ".join(x for x in [metric.help, metric.footnote] if x) or None,
    )


def summary_table(
    df: pd.DataFrame,
    bar: str | None = None,
    bar_max: float = 100.0,
    raw: set[str] | None = None,
) -> None:
    """A small static table, rendered as HTML rather than through `st.dataframe`.

    Streamlit's data grid measures its own box on first paint, and in some slots —
    inside a tab, inside a column, above a chart — that measurement lands at a few
    pixels and never recovers, leaving a table with one clipped column. For an
    interactive grid that is worth living with; for a short read-only summary on a
    monitoring page it is not, and plain markup always draws.

    `bar` names a column to render with a proportional bar behind the figure. `raw`
    names columns whose values are already markup this module produced — sparklines
    and badges — and are therefore inserted unescaped. Never put anything that came
    from data in `raw`.
    """
    raw = raw or set()
    if df.empty:
        st.caption("Nothing to show.")
        return

    numeric = {c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])}
    head = "".join(
        f'<th class="{"n" if c in numeric else ""}">{html.escape(str(c))}</th>'
        for c in df.columns
    )
    body = []
    for _, row in df.iterrows():
        cells = []
        for c in df.columns:
            v = row[c]
            text = "" if opt(v) is None else (f"{v:,}" if isinstance(v, (int,)) else str(v))
            if c in raw:
                cells.append(f'<td class="raw">{v if opt(v) is not None else ""}</td>')
            elif c == bar:
                pct = max(0.0, min(100.0, 100.0 * float(v) / bar_max)) if bar_max else 0.0
                cells.append(
                    f'<td class="n bar"><span class="fill" style="width:{pct:.1f}%"></span>'
                    f'<span class="lbl">{html.escape(text)}%</span></td>'
                )
            else:
                cells.append(
                    f'<td class="{"n" if c in numeric else ""}">{html.escape(text)}</td>'
                )
        body.append("<tr>" + "".join(cells) + "</tr>")

    st.markdown(
        f'<table class="dq-tbl"><thead><tr>{head}</tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table>',
        unsafe_allow_html=True,
    )


def cohort_headline(row) -> None:
    marks = [theme.severity_badge(row["severity"]), theme.state_badge(row["lifecycle_state"])]
    if row["is_recurrence"]:
        marks.append(theme.badge("Recurrence", "critical", "refresh"))
    if row["recommendation_source"] == "generated":
        marks.append(theme.badge("Generated advice", "moderate", "spark"))
    if int(row["reopen_count"]) > 0:
        marks.append(theme.badge(f"Reopened ×{int(row['reopen_count'])}", "critical"))
    st.markdown(
        " ".join(marks)
        + f'<div class="dq-quiet" style="margin-top:.35rem">'
        f'{theme.STATE_MEANING.get(row["lifecycle_state"], "")}</div>',
        unsafe_allow_html=True,
    )


# --- Evidence ---------------------------------------------------------------


def member_rule_table(cohort_row, registry: pd.DataFrame, runs: pd.DataFrame) -> None:
    """Every rule in the cohort with the run history that put it there.

    The history column is the point. A rule breaching at a flat rate for forty runs
    and a rule that went from zero to 240 overnight look identical in a violation
    count and completely different here — and that difference separates a chronic gap
    from an incident with a date on it.
    """
    members = as_list(cohort_row["member_rule_ids"])
    reg = registry.set_index("rule_id")
    latest_run = runs.loc[runs["run_ts"].idxmax(), "run_id"]

    hist = (
        runs[runs["rule_id"].isin(members)]
        .sort_values("run_ts")
        .groupby("rule_id")["violation_count"]
        .apply(list)
    )
    current = runs[(runs["run_id"] == latest_run) & (runs["rule_id"].isin(members))].set_index(
        "rule_id"
    )

    rows = []
    for rid in members:
        r = reg.loc[rid] if rid in reg.index else None
        c = current.loc[rid] if rid in current.index else None
        rows.append(
            {
                # The check's name leads. `CTCT_EML_NO_AT` is an identifier, not a
                # sentence — a reader should not have to decode one to know what
                # failed. The id is still there, one column over.
                "Check": (rid if r is None else r["rule_name"]),
                "Findings": None if c is None else int(c["violation_count"]),
                "History": hist.get(rid, []),
                "Rate": None if c is None else float(c["violation_pct"]),
                "Limit": None if c is None else float(c["threshold_pct"]),
                "Severity": None if r is None else theme.severity_text(r["severity"]),
                "Column": None if r is None else opt(r["target_column"]),
                "Applies to": (
                    "every row" if r is None or opt(r["scope_filter"]) is None
                    else str(r["scope_filter"])
                ),
                "Id": rid,
            }
        )

    st.dataframe(
        pd.DataFrame(rows),
        width="stretch",
        hide_index=True,
        column_config={
            "Check": st.column_config.TextColumn(width="medium"),
            "History": st.column_config.LineChartColumn(
                "History",
                help="Findings per scheduled run, oldest first. A step change dates the "
                "defect; a flat line says it has always been like this.",
                width="medium",
            ),
            "Rate": st.column_config.NumberColumn(format="%.2f%%",
                                                  help="Share of rows failing this check."),
            "Limit": st.column_config.NumberColumn(format="%.2f%%",
                                                  help="How much failure is tolerated."),
            "Findings": st.column_config.NumberColumn(format="%d"),
            "Applies to": st.column_config.TextColumn(
                help="'every row' means the check is unrestricted. Where all failing "
                "rows share a product line that legitimately has no value for that "
                "column, an unrestricted check is itself the defect.",
            ),
            "Id": st.column_config.TextColumn(width="small"),
        },
    )


def violation_samples_view(cohort_row, samples: pd.DataFrame, runs: pd.DataFrame) -> None:
    """The offending rows.

    Two lookups, and the difference between them is stated rather than smoothed over:
    samples captured by the run that *raised* the cohort are the evidence the
    hypothesis was formed from; the newest samples for the same rules show what the
    rule catches now, which may have changed.

    In the local fixture the first finds nothing for any cohort — the runner only
    sampled the final run while `member_result_ids` point at each cohort's raising
    run. That is a gap in the sampling, not a display problem.
    """
    at_raise = samples[samples["result_id"].isin(as_list(cohort_row["member_result_ids"]))]
    if not at_raise.empty:
        st.caption(f"{len(at_raise):,} rows captured by the run that raised this cohort.")
        _sample_tables(at_raise)
        return

    fallback = samples[samples["rule_id"].isin(as_list(cohort_row["member_rule_ids"]))]
    if fallback.empty:
        st.caption("No samples for this cohort's rules — historical breaches carry counts only.")
        return

    run_ts = runs.drop_duplicates("run_id").set_index("run_id")["run_ts"]
    newest_run = fallback["run_id"].map(run_ts).max()
    newest = fallback[fallback["run_id"].map(run_ts) == newest_run]

    st.caption(
        f"No samples from the raising run ({cohort_row['raised_ts']:%d %b}). Showing the "
        f"latest for the same rules, from {newest_run:%d %b} — what they catch now, not "
        "what the hypothesis was formed from."
    )
    _sample_tables(newest)


def _sample_tables(subset: pd.DataFrame) -> None:
    """One expander per rule, each holding that rule's rows as real columns.

    This used to print `sample_row` as a JSON string in a single cell. The pattern in
    these samples is almost always vertical — the same literal twelve times, six
    variants of a broken formatter — and a column of JSON blobs hides exactly that.
    """
    by_rule = subset.groupby("rule_id")
    for rid, g in by_rule:
        with st.expander(f"{rid} — {len(g):,} rows", expanded=by_rule.ngroups == 1):
            sample_rows_view(g)


def sample_rows_frame(subset: pd.DataFrame) -> pd.DataFrame:
    """Sampled rows as the columns they actually are, rather than as JSON text.

    `violation_sample.sample_row` is a JSON object per row, and the runner chose the
    keys in it — the offending column plus whatever makes the failure legible beside
    it. Rendering that object as a string makes the reader parse it; rendering it as
    columns lets them read down the column, which is the whole reason the samples are
    kept. Twelve rows all holding the same literal is a provisioning defect; the same
    twelve as JSON blobs is twelve things to read.

    Column order is first-seen, so it is the runner's order, not alphabetical.
    """
    rows, order = [], []
    for raw in subset["sample_row"]:
        try:
            obj = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
        except (TypeError, ValueError):
            continue
        for k in obj:
            if k not in order:
                order.append(k)
        rows.append(obj)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).reindex(columns=order)


def sample_rows_view(subset: pd.DataFrame, limit: int = 100) -> None:
    """The sampled rows, parsed into columns. Falls back to the raw payload if it
    will not parse — a sample that cannot be shown as columns is still evidence, and
    hiding it would be worse than showing it ugly."""
    frame = sample_rows_frame(subset.head(limit))
    if frame.empty:
        st.dataframe(subset[["row_key", "sample_row"]].head(limit),
                     width="stretch", hide_index=True)
        return
    st.dataframe(frame, width="stretch", hide_index=True)


def blast_radius_view(cohort_row) -> None:
    affected = as_list(cohort_row["affected_tables"])
    downstream = as_list(cohort_row.get("blast_radius_tables"))
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f'<div class="dq-section">Affected · {len(affected)}</div>',
                    unsafe_allow_html=True)
        for t in affected:
            st.markdown(f"`{t}`")
    with c2:
        st.markdown(
            f'<div class="dq-section" title="From Unity Catalog lineage. Locally these '
            f'names are plausible, not observed.">Downstream · {len(downstream)}</div>',
            unsafe_allow_html=True,
        )
        for t in downstream:
            st.markdown(f"`{t}`")


# --- Recommendation ---------------------------------------------------------


def recommendation_view(cohort_row, playbook: pd.DataFrame) -> None:
    """The recommendation, and the playbook entry behind it where there is one.

    The playbook has no page of its own — an approach library nobody browses is
    reference material, and the spec's requirement is that the entry appear *as the
    recommendation, with its prior-use count*, which is here.
    """
    source = cohort_row["recommendation_source"]
    st.markdown(
        theme.badge(theme.approach_label(cohort_row["recommended_approach_type"]), "info")
        + " "
        + (
            theme.badge("From playbook", "neutral")
            if source == "playbook"
            else theme.badge("Generated — no playbook match", "moderate", "spark")
        ),
        unsafe_allow_html=True,
    )
    st.markdown(cohort_row["recommended_approach"])

    pb_id = opt(cohort_row.get("playbook_id"))
    if source == "playbook" and pb_id is not None and (playbook["playbook_id"] == pb_id).any():
        pb = playbook[playbook["playbook_id"] == pb_id].iloc[0]
        with st.container(border=True):
            st.markdown(f"**{pb['approach_name']}**")
            st.markdown(f'<div class="dq-quiet">{html.escape(pb["description"])}</div>',
                        unsafe_allow_html=True)
            last_used = opt(pb["last_used_ts"])
            st.markdown(
                theme.kv("Prior uses", int(pb["prior_use_count"]))
                + theme.kv(
                    "Recurrence rate",
                    f"{100 * float(pb['recurrence_rate']):.0f}% "
                    f"({int(pb['recurrence_count'])} of {int(pb['prior_use_count']) or '—'})",
                )
                + theme.kv("Last used", f"{last_used:%d %b %Y}" if last_used is not None else "never")
                + theme.kv("Typical owner", pb["typical_owner"]),
                unsafe_allow_html=True,
            )
            st.caption(
                "Non-executable by design — the playbook stores an approach and a track "
                "record, never a runnable body."
            )

    with st.expander("Provenance"):
        st.markdown(
            theme.kv("Source", source)
            + theme.kv("Model endpoint", opt(cohort_row.get("model_endpoint")) or "—")
            + theme.kv("Triage job run", opt(cohort_row.get("triage_job_run_id")) or "—")
            + theme.kv("Playbook ref", pb_id or "—"),
            unsafe_allow_html=True,
        )
        payload = opt(cohort_row.get("model_input_payload"))
        if payload:
            st.code(payload, language="json")


# --- The register -----------------------------------------------------------


def event_timeline(events: pd.DataFrame) -> None:
    """The full chain, oldest first. Nothing elided — this is the audit artefact, and
    an auditor asked to trust a rendering that hides rows is being asked to trust the
    renderer."""
    out = ['<div class="dq-rail">']
    for _, e in events.sort_values("event_seq").iterrows():
        etype = e["event_type"]
        tone = theme.EVENT_TONE.get(etype, "neutral")
        if etype == "verified" and e["verification_passed"] is not True:
            tone = "critical"
        t = theme.TONE[tone]

        head = etype.capitalize()
        if opt(e["decision"]):
            head += f" — {e['decision']}"
        if etype == "approved" and opt(e.get("approver_ordinal")):
            head += f" ({int(e['approver_ordinal'])} of the distinct set)"
        if etype == "verified":
            head += " — passed" if e["verification_passed"] is True else " — failed"

        meta = (
            f"{e['event_ts']:%d %b %Y · %H:%M} &nbsp;·&nbsp; {html.escape(str(e['actor_display_name']))}"
            f" &nbsp;·&nbsp; {html.escape(str(opt(e['actor_identity']) or 'no identity'))}"
            f" &nbsp;·&nbsp; {html.escape(str(e['actor_source']))} &nbsp;·&nbsp; seq {int(e['event_seq'])}"
        )

        bits = []
        for field in ("reason", "executed_summary"):
            if opt(e[field]):
                bits.append(html.escape(str(e[field])))
        if opt(e["external_ref"]):
            bits.append(f"Ref <code>{html.escape(str(e['external_ref']))}</code>")
        if opt(e.get("review_by_date")):
            bits.append(f"Review by {e['review_by_date']}")
        if etype == "verified" and opt(e["violations_before"]) is not None:
            bits.append(
                f"{int(e['violations_before']):,} before &rarr; {int(e['violations_after']):,} after"
            )
        if opt(e["approach_type_taken"]):
            bits.append(f"Approach: {theme.approach_label(e['approach_type_taken'])}")

        out.append(
            f'<div class="dq-ev">'
            f'<span class="pin" style="border-color:{t["bd"]};color:{t["fg"]}">'
            f'{theme.icon(theme.EVENT_ICON.get(etype, "spark"), 11)}</span>'
            f'<div class="hd" style="color:{t["fg"]}">{head}</div>'
            f'<div class="meta">{meta}</div>'
            + (f'<div class="body">{"<br>".join(bits)}</div>' if bits else "")
            + "</div>"
        )
    out.append("</div>")
    st.markdown("".join(out), unsafe_allow_html=True)


def approval_gate_view(row, events: pd.DataFrame) -> None:
    satisfied, message = lifecycle.approval_gate(row)
    approvals = events[events["event_type"] == "approved"]
    rows_n, distinct_n = len(approvals), approvals["actor_identity"].nunique()

    with st.container(border=True):
        st.markdown(
            f'<div class="dq-section" style="margin-top:0">Approval gate</div>'
            + theme.badge(message, "success" if satisfied else "moderate",
                          "check" if satisfied else "clock"),
            unsafe_allow_html=True,
        )
        if rows_n:
            st.markdown(
                "".join(
                    theme.kv(f"Approver {i + 1}", f"{a['actor_display_name']} · {a['actor_identity']}")
                    for i, (_, a) in enumerate(approvals.sort_values("event_seq").iterrows())
                ),
                unsafe_allow_html=True,
            )
        if rows_n != distinct_n:
            st.error(
                f"{rows_n} approval rows from {distinct_n} distinct identities — a control "
                "failure. The requirement is on distinct identities, not row count.",
                icon=":material/error:",
            )
        st.caption(
            f"{theme.SEVERITY_SHORT.get(row['severity'], row['severity'])} requires "
            f"{int(row['approvals_required'])} distinct named approver(s).",
            help="P1 requires two, P2/P3 one. 'Distinct' cannot be a table CHECK "
            "constraint because it is a property of a set of rows, so it is enforced "
            "in the app and detected afterwards by v_disposition_integrity.",
        )

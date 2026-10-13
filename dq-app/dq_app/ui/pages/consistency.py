"""Consistency — the checks that read two tables and ask whether they agree.

Built 2026-10-13 from the design mock ("Consistency checks mockup"). Four figures, the
relationships the checks read, the checks by kind, then every check as a clickable row
with the one picked opened underneath it: how the two sides are matched in plain
words, the rows that failed, and the definition.

**Nothing here is new data.** A consistency check is a current rule with a `join_sql`,
measured by the same runner and written to the same `check_run`. It is scored, held
back by tolerance and triaged like any other check, on the pages that already do
that. This page only gathers them and says what each compares. `domain/consistency.py`
holds the folding.

**Relationships are read off the checks** because there is no relationship register
yet. A relationship with no check on it cannot appear, which is the honest state:
nothing is checking it.

**No action lives here.** Promoting a shadow check, and every version of it, is on the
Rules page, which "Open in Rules" lands on with the check picked.
"""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from dq_app.data import adapter
from dq_app.domain import consistency as cs
from dq_app.domain import metrics
from dq_app.ui import components, theme

RULES = "dq_app/ui/pages/rule_registry.py"
NEW = "dq_app/ui/pages/consistency_new.py"
REVIEW = "dq_app/ui/pages/consistency_review.py"
PGRID = "minmax(6rem,.7fr) minmax(12rem,2.6fr) minmax(7rem,.8fr) 1rem"
# Kind · Check · Relationship · Result · Failing · Severity · State · chevron
GRID = ("minmax(6rem,.7fr) minmax(12rem,2fr) minmax(8rem,1.1fr) minmax(7rem,.9fr) "
        "minmax(4rem,.5fr) minmax(3rem,.4fr) minmax(5.5rem,.7fr) 1rem")
REL_GRID = "minmax(0,1fr)"
STATE_TONE = {"Failing": "critical", "Passing": "success", "Shadow": "moderate",
              "Not run": "neutral"}
SEV_SHORT = theme.SEVERITY_SHORT
red = theme.TONE["critical"]["fg"]

components.page_chrome()

current = adapter.get_rule_registry_current()
registry = adapter.get_rule_registry()
retired = metrics.retired_rule_ids(registry)
runs = adapter.get_check_runs()
runs = runs[~runs["rule_id"].isin(retired)]
samples = adapter.get_violation_samples()

# Each rule's own latest measurement, as on the Rules page: a shadow check measured by
# the onboarding job is never in the estate's latest run.
measured = metrics.last_per_day(runs[runs["status"] != "error"])
latest = (measured.sort_values("run_ts").drop_duplicates("rule_id", keep="last")
          .set_index("rule_id"))
checks = cs.checks(current, latest)
by_id = {c["key"]: c for c in checks}

hd, act = st.columns([4, 1], vertical_alignment="center")
hd.markdown(
    '<div class="dq-page-hd"><div class="t">Consistency</div>'
    '<div class="s">Checks that compare two tables.</div></div>',
    unsafe_allow_html=True,
)
if act.button("New check", type="primary", icon=":material/add:", key="_cs_new",
              width="stretch"):
    st.switch_page(NEW)


# --- Proposals: what is waiting, and what was decided --------------------------------------

proposals = adapter.get_consistency_proposal_current()
PSTATE = {"open": ("Needs review", "info"), "approved": ("Approved", "moderate"),
          "applied": ("In shadow", "success"), "rejected": ("Rejected", "neutral")}
if len(proposals):
    order = {"open": 0, "approved": 1, "applied": 2, "rejected": 3}
    prows = (proposals.assign(_o=proposals["state"].map(order))
             .sort_values(["_o", "proposed_at"], ascending=[True, False]).to_dict("records"))
    n_open = sum(r["state"] == "open" for r in prows)
    with st.container(key="dq_csprops"):
        st.markdown(
            '<div class="dq-tmcard-hd"><div class="t">Proposals'
            f'<span class="dq-count">{n_open} waiting</span></div></div>',
            unsafe_allow_html=True,
        )

        def _pcells(r) -> str:
            lab, tone = PSTATE[r["state"]]
            return (f'<span>{theme.badge(cs.KIND_LABEL[r["kind"]], "neutral")}</span>'
                    f'<span class="stack"><span class="t1">{html.escape(r["rule_name"])}</span>'
                    f'<span class="t2 sans">{html.escape(str(r["proposed_by"]))} · '
                    f'{pd.Timestamp(r["proposed_at"]):%-d %b}</span></span>'
                    f'<span>{theme.badge(lab, tone)}</span>'
                    f'<span class="opn">{theme.icon("arrow_right", 15)}</span>')

        with st.container(key="dqrows_csprops"):
            got = components.clickable_rows(
                prows, PGRID, _pcells, "csp", "proposal_id",
                lambda r: f"Open the proposal {r['rule_name']}")
        if got:
            st.session_state["_cs_proposal"] = got
            st.switch_page(REVIEW)

if not checks:
    st.markdown(
        '<div class="dq-card"><div class="ttl">No checks yet</div>'
        '<div class="q">Use New check to compare two tables. A check starts in shadow '
        "once someone else approves it.</div></div>",
        unsafe_allow_html=True,
    )
    st.stop()

s = cs.summary(checks)


# --- Four figures -------------------------------------------------------------

def _fig(label: str, value: str, sub: str, colour: str | None = None) -> str:
    style = f' style="color:{colour}"' if colour else ""
    return (f'<div class="f"><div class="l">{label}</div><div class="v"{style}>{value}'
            f'</div><div class="c">{sub}</div></div>')


st.markdown(
    '<div class="dq-tmkpi">'
    + _fig("Table links", str(s["relationships"]), "with a check on them")
    + _fig("Checks", str(s["checks"]), f'{s["active"]} active · {s["shadow"]} in shadow')
    + _fig("Failing", str(s["failing"]),
           f'{s["failing_p1"]} is P1' if s["failing_p1"] else "none is P1",
           red if s["failing"] else None)
    + _fig("Rows affected", f'{s["rows_floor"]:,}+' if s["failing"] else "0",
           "a row can fail more than one check")
    + "</div>",
    unsafe_allow_html=True,
)

if s["unsafe"]:
    st.markdown(
        f'<div class="dq-cs-warn">{theme.icon("warning", 15)}<span><b>{s["unsafe"]} '
        f'{"check compares" if s["unsafe"] == 1 else "checks compare"} with '
        "<code>&lt;&gt;</code>.</b> A value missing on one side is never counted, so "
        "they can read low.</span></div>",
        unsafe_allow_html=True,
    )


# --- Relationships, and the checks by kind ----------------------------------------

rels = cs.relationships(checks)
left, right = st.columns([1.35, 1], gap="medium")

with left, st.container(key="dq_csrels"):
    st.markdown(
        '<div class="dq-tmcard-hd"><div class="t">Table links'
        f'<span class="dq-count">{len(rels)}</span></div>'
        '<div class="q">Click a link to filter the list.</div></div>',
        unsafe_allow_html=True,
    )
    rel_pick = st.session_state.get("_cs_rel")

    def _rel_cells(r) -> str:
        tone = ("critical" if r["Failing"] else "success" if r["Passing"]
                else "neutral")
        edge = theme.TONE[tone]["fg"] if tone != "neutral" else theme.NEUTRAL["border_strong"]
        parts = []
        for k in ("Failing", "Passing", "Shadow", "Not run"):
            if r[k]:
                parts.append(theme.badge(f"{r[k]} {k.lower()}", STATE_TONE[k]))
        nodes = (f'<span class="dq-cs-node">{html.escape(cs.short(r["Driving"]))}</span>'
                 + "".join(
                     f'<span class="dq-cs-edge" style="--dq-edge:{edge}"></span>'
                     f'<span class="dq-cs-node">{html.escape(cs.short(t))}</span>'
                     for t in (r["Others"] or ["—"])))
        # One cell that wraps: on a narrow card the counts drop under the tables
        # rather than squeezing the table names to three letters.
        return (f'<span class="dq-cs-relrow"><span class="dq-cs-rel">{nodes}</span>'
                f'<span class="dq-cs-relbadges">{"".join(parts)}</span></span>')

    with st.container(key="dqrows_csrels"):
        components.clickable_rows(
            rels, REL_GRID, _rel_cells, "csrel", "key",
            lambda r: f"Show the checks on {r['Label']}", picked=rel_pick,
            on_pick=lambda k: st.session_state.update(
                _cs_rel=None if st.session_state.get("_cs_rel") == k else k),
            tip=lambda r: [r["Label"], (" · ".join([r["Driving"]] + r["Others"]), "mono"),
                           f'{len(r["Checks"])} checks. Click again to show all.'])

with right:
    rows_html = ""
    for k in cs.KINDS:
        mine = [c for c in checks if c["Kind"] == k]
        n = len(mine)
        segs = "".join(
            f'<span style="flex:{sum(c["State"] == st_ for c in mine)} 1 0;'
            f'background:{theme.TONE[STATE_TONE[st_]]["fg"] if st_ != "Not run" else theme.NEUTRAL["border_strong"]}"></span>'
            for st_ in ("Failing", "Passing", "Shadow", "Not run")
            if any(c["State"] == st_ for c in mine))
        rows_html += (
            '<div class="dq-cs-kind"><div><div class="k">' + k + "</div>"
            f'<div class="q">{html.escape(cs.KIND_MEANING[k])}</div></div>'
            f'<div class="n"><b>{n if n else "none"}</b>'
            + (f'<div class="dq-cov3 sm">{segs}</div>' if n else "") + "</div></div>")
    st.markdown(
        '<div class="dq-card dq-cs-kinds"><div class="ttl">Check types</div>' + rows_html
        + f'<div class="dq-legend">'
          f'<span>{theme.dot("critical")}failing</span>'
          f'<span>{theme.dot("success")}passing</span>'
          f'<span>{theme.dot("moderate")}shadow</span></div></div>',
        unsafe_allow_html=True,
    )


# --- The checks, and the one picked ---------------------------------------------

def _result(c) -> str:
    if c["Checked"] is None:
        return '<span class="t2 sans">not measured</span>'
    unit = "groups" if c["Kind"] == "Same total" else "rows"
    return (f'<span class="stack"><span class="t1">{theme.pct_text(c["Rate"], 1)}%</span>'
            f'<span class="t2 sans">of {c["Checked"]:,} {unit}</span></span>')


def _n(v) -> str:
    return "—" if v is None else f"{v:,}"


def _cells(c) -> str:
    tone = STATE_TONE[c["State"]]
    sev_tone = theme.SEVERITY_TONE.get(c["Severity"], "neutral")
    return (
        f'<span>{theme.badge(c["Kind"], "neutral")}</span>'
        f'<span class="stack"><span class="t1">{html.escape(c["Name"])}</span>'
        f'<span class="t2 mono">{html.escape(c["key"])}</span></span>'
        f'<span class="t2 mono">{html.escape(c["Relationship"])}</span>'
        + _result(c)
        + f'<span class="num">{_n(c["Failing rows"])}</span>'
        f'<span>{theme.badge(SEV_SHORT.get(c["Severity"], c["Severity"]), sev_tone)}</span>'
        f'<span>{theme.badge(c["State"], tone)}'
        + (f' {theme.badge("&lt;&gt;", "high")}' if c["Unsafe"] else "") + "</span>"
        f'<span class="opn">{theme.icon("expand_more", 15)}</span>'
    )


def _open_in_rules(rule_id: str) -> None:
    st.session_state["_rule_pick"] = rule_id
    st.session_state.pop("_rule_el", None)
    st.session_state.pop("_rule_cde_search", None)
    st.switch_page(RULES)


@st.fragment
def _checks() -> None:
    rel = st.session_state.get("_cs_rel")
    with st.container(key="dq_cscard"):
        top, ctl = st.columns([1.1, 1.7], vertical_alignment="center")
        scoped = [c for c in checks if not rel or c["rel_key"] == rel]
        top.markdown(
            '<div class="dq-tmcard-hd"><div class="t">Checks'
            f'<span class="dq-count">{len(scoped)}</span></div>'
            '<div class="q">'
            + (f"On {html.escape(next(r['Label'] for r in rels if r['key'] == rel))}."
               if rel else "Failing first.")
            + "</div></div>",
            unsafe_allow_html=True,
        )
        with ctl:
            q, seg = st.columns([1.35, 1], vertical_alignment="center")
            term = q.text_input("Search checks", placeholder="Search",
                                label_visibility="collapsed", icon=":material/search:",
                                key="_cs_search").strip().lower()
            st.session_state.setdefault("_cs_show", "all")
            n_fail = sum(c["State"] == "Failing" for c in scoped)
            n_sh = sum(c["State"] == "Shadow" for c in scoped)
            show = seg.segmented_control(
                "Checks shown", ["all", "failing", "shadow"], key="_cs_show",
                label_visibility="collapsed",
                format_func=lambda v: {"all": f"All {len(scoped)}",
                                       "failing": f"Failing {n_fail}",
                                       "shadow": f"Shadow {n_sh}"}[v]) or "all"
        view = [c for c in scoped
                if show == "all" or c["State"].lower() == show]
        if term:
            view = [c for c in view if term in
                    f"{c['key']} {c['Name']} {c['Relationship']} {c['Kind']}".lower()]
        components.row_head(["Type", "Check", "Tables", "Passed", ("Failed", "n"),
                             "Sev.", "Status", ""], GRID)
        pick = st.session_state.get("_cs_pick")
        if view:
            with st.container(key="dqrows_cschecks"):
                components.clickable_rows(
                    view, GRID, _cells, "cs", "key", lambda c: f"Open {c['Name']}",
                    picked=pick, on_pick=components.pick_into("_cs_pick"),
                    tip=lambda c: [c["Name"], (c["key"], "mono"),
                                   cs.KIND_MEANING[c["Kind"]]])
        else:
            st.markdown('<div class="dq-tmempty">No check matches.</div>',
                        unsafe_allow_html=True)

    c = by_id.get(pick)
    if c is None:
        return
    with st.container(key="dq_cspane"):
        tone = STATE_TONE[c["State"]]
        st.markdown(
            '<div class="dq-cs-panehd">'
            f'<div class="t">{html.escape(c["Name"])}</div>'
            '<div class="b">'
            + theme.badge(c["Kind"], "neutral")
            + theme.badge(SEV_SHORT.get(c["Severity"], c["Severity"]),
                          theme.SEVERITY_TONE.get(c["Severity"], "neutral"))
            + theme.badge(c["State"], tone)
            + f'<span class="t2 mono">{html.escape(c["key"])}</span></div></div>',
            unsafe_allow_html=True,
        )
        unit = "groups" if c["Kind"] == "Same total" else "rows"
        figs = [
            ("Match" if c["Kind"] != "Missing record" else "Found",
             "—" if c["Rate"] is None else f'{theme.pct_text(c["Rate"], 1)}%'),
            (f"{unit.capitalize()} compared",
             "—" if c["Checked"] is None else f'{c["Checked"]:,}'),
            ("Failing", "—" if c["Failing rows"] is None else f'{c["Failing rows"]:,}'),
            ("Last measured",
             "—" if c["Run ts"] is None else f'{pd.Timestamp(c["Run ts"]):%-d %b %H:%M}'),
        ]
        st.markdown(
            '<div class="dq-tmkpi dq-cs-figs">'
            + "".join(f'<div class="f"><div class="l">{a}</div><div class="v">{b}</div></div>'
                      for a, b in figs)
            + "</div>",
            unsafe_allow_html=True,
        )
        how, sides = st.columns([1.4, 1], gap="medium")
        how.markdown(
            '<div class="dq-card"><div class="ttl">How the two sides are matched</div>'
            + "".join(f'<p class="dq-cs-line">{html.escape(x)}</p>'
                      for x in cs.plain_words(c))
            + "</div>",
            unsafe_allow_html=True,
        )
        sides.markdown(
            '<div class="dq-card"><div class="ttl">Tables</div>'
            f'<div class="dq-cs-side"><span class="l">Starts from</span>'
            f'<span class="mono">{html.escape(c["Driving"])}</span></div>'
            + "".join(f'<div class="dq-cs-side"><span class="l">Compared with</span>'
                      f'<span class="mono">{html.escape(t)}</span></div>'
                      for t in c["Others"])
            + '<div class="dq-cs-note">Both sides are read on their current records '
              "where the table declares them; the slice applies to the first only."
              "</div></div>",
            unsafe_allow_html=True,
        )
        rows_tab, defn = st.tabs(
            [f"Sample rows · {0 if c['Failing rows'] is None else c['Failing rows']:,}",
             "Definition"], key="_cs_tab")
        with rows_tab:
            if not c["Failing rows"]:
                st.caption("Nothing failed on its latest measurement."
                           if c["Checked"] is not None else "Not measured yet.")
            else:
                components.failed_rows(c["key"], {"run_id": c["Run id"],
                                                  "violation_count": c["Failing rows"]},
                                       samples, heading=False)
        with defn:
            st.caption("The join, the predicate and the scope as the register stores "
                       "them. The runner counts rows of the join where the predicate "
                       "holds, within the scope.")
            st.code("FROM  " + c["join_sql"]
                    + "\nWHERE " + c["rule_expr"]
                    + ("" if not c["scope_filter"] else "\n  AND " + c["scope_filter"]),
                    language="sql", wrap_lines=True)
        if st.button("Open in Rules", icon=":material/open_in_new:", type="tertiary",
                     key="_cs_to_rules",
                     help="Its every version, its history, and promotion if it is in "
                          "shadow."):
            _open_in_rules(c["key"])


_checks()

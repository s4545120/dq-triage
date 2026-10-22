"""Consistency — the checks that read two tables and ask whether they agree.

Built 2026-10-13 from the design mock ("Consistency checks mockup"); redrawn the same
day from its second version, screens 1 and 2:

* four figures, the Failing one with a red top edge;
* **Proposals**, only while something waits (open, or approved and not yet written by
  the job), each row opening its review;
* **Table links**, one full-width card: the two tables with an arrow coloured by the
  link's worst state, the key it matches on, its check types and state badges. A click
  filters the checks. The "Check types" card is gone: types are filter chips instead;
* **the checks beside the picked check.** The list has status and type chips, a status
  stripe per row and names that wrap. The pane has a 2×2 of figures and three tabs:
  Overview (the match drawn as `table.COL → table.COL`, the rule in plain words, the
  last five runs), Rows (the two compared columns side by side, an empty value tagged
  "— empty", the differing part highlighted) and Definition.

The amber `<>` banner is gone too: a check written with `<>` carries a "May undercount"
badge on its row, explained on hover.

**Nothing here is new data.** A consistency check is a current rule with a `join_sql`,
measured by the same runner and written to the same `check_run`. `domain/consistency.py`
holds every fold this page draws, pure and tested.

**Relationships are read off the checks** because there is no relationship register
yet, so a link nothing checks cannot appear: the mockup's "Add a check" row has no data
to stand on.

**Rows are what the runner stored**: the key and the columns the rule reads
(`run_checks.sample_keep`), keyed by plain column name. When both tables call the
compared column the same, a sample holds one value of the two, so that check's rows are
shown as stored and the page says why. Same rows, same cap as everywhere else.

**No action lives here.** Promotion and every version are on the Rules page, which
"Open in Rules" opens with the check picked.
"""

from __future__ import annotations

import html
import json

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
LGRID = "minmax(0,1.3fr) minmax(0,1fr) auto"
CGRID = "minmax(0,1fr) 5.75rem 4.5rem"
STATE_TONE = {"Failing": "critical", "Passing": "success", "Shadow": "moderate",
              "Not run": "neutral"}
SEV_SHORT = theme.SEVERITY_SHORT
PSTATE = {"open": ("Needs review", "info"), "approved": ("Approved · job pending", "moderate")}


def _colour(state: str) -> str:
    tone = STATE_TONE.get(state, "neutral")
    return theme.NEUTRAL["border_strong"] if tone == "neutral" else theme.TONE[tone]["fg"]


def _link_state(r) -> str:
    return ("Failing" if r["Failing"] else "Passing" if r["Passing"]
            else "Shadow" if r["Shadow"] else "Not run")


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


# --- Four figures -------------------------------------------------------------------------

s = cs.summary(checks) if checks else None


def _fig(label: str, value: str, sub: str, colour: str | None = None,
         cls: str = "") -> str:
    style = f' style="color:{colour}"' if colour else ""
    return (f'<div class="f {cls}"><div class="l">{label}</div><div class="v"{style}>{value}'
            f'</div><div class="c">{sub}</div></div>')


if s:
    red = theme.TONE["critical"]["fg"]
    st.markdown(
        '<div class="dq-tmkpi dq-cs-kpi">'
        + _fig("Table links", str(s["relationships"]), "with a check on them")
        + _fig("Checks", str(s["checks"]), f'{s["active"]} active · {s["shadow"]} in shadow')
        + _fig("Failing", str(s["failing"]),
               f'{s["failing_p1"]} P1' if s["failing_p1"] else "no P1",
               red if s["failing"] else None, "fail" if s["failing"] else "")
        + _fig("Rows affected", f'{s["rows_floor"]:,}+' if s["failing"] else "0",
               "a row can fail more than one check")
        + "</div>",
        unsafe_allow_html=True,
    )


# --- Proposals: only what is waiting --------------------------------------------------------

proposals = adapter.get_consistency_proposal_current()
waiting = (proposals[proposals["state"].isin(list(PSTATE))].sort_values("proposed_at",
                                                                         ascending=False)
           if len(proposals) else proposals)
if len(waiting):
    with st.container(key="dq_csprops"):
        st.markdown(
            '<div class="dq-tmcard-hd"><div class="t">Proposals'
            f'<span class="dq-count">{len(waiting)} waiting</span></div></div>',
            unsafe_allow_html=True,
        )

        def _pcells(r) -> str:
            lab, tone = PSTATE[r["state"]]
            return (f'<span class="dq-tmname" style="--dq-stripe:{theme.ACCENT}">'
                    f'{theme.badge(cs.KIND_LABEL[r["kind"]], "neutral")}</span>'
                    f'<span class="stack"><span class="t1">{html.escape(r["rule_name"])}</span>'
                    f'<span class="t2 sans">{html.escape(str(r["proposed_by"]))} · '
                    f'{pd.Timestamp(r["proposed_at"]):%-d %b}</span></span>'
                    f'<span>{theme.badge(lab, tone)}</span>'
                    f'<span class="opn">{theme.icon("arrow_right", 15)}</span>')

        with st.container(key="dqrows_csprops"):
            got = components.clickable_rows(
                waiting.to_dict("records"), PGRID, _pcells, "csp", "proposal_id",
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


# --- Table links ------------------------------------------------------------------------------

rels = cs.relationships(checks)
with st.container(key="dq_cslinks"):
    st.markdown(
        '<div class="dq-tmcard-hd dq-cs-cardhd"><div class="t">Table links'
        f'<span class="dq-count">{len(rels)}</span></div>'
        '<div class="q">Click a link to filter the checks.</div></div>',
        unsafe_allow_html=True,
    )

    def _link_cells(r) -> str:
        state = _link_state(r)
        edge = _colour(state)
        nodes = (f'<span class="dq-cs-node">{html.escape(cs.short(r["Driving"]))}</span>'
                 + "".join(f'<span class="dq-cs-edge" style="--dq-edge:{edge}"></span>'
                           f'<span class="dq-cs-node">{html.escape(cs.short(t))}</span>'
                           for t in (r["Others"] or ["—"])))
        on = (f'<span class="t2 sans">on {html.escape(" · ".join(r["On"]))}</span>'
              if r["On"] else '<span class="t2 sans">totals</span>')
        badges = "".join(theme.badge(f"{r[k]} {k.lower()}", STATE_TONE[k])
                         for k in ("Failing", "Passing", "Shadow", "Not run") if r[k])
        return (f'<span class="dq-tmname dq-cs-rel" style="--dq-stripe:{edge}">{nodes}{on}</span>'
                f'<span class="t2 sans dq-cs-kinds">{html.escape(" · ".join(r["Kinds"]))}</span>'
                f'<span class="dq-cs-relbadges">{badges}</span>')

    with st.container(key="dqrows_cslinks"):
        components.clickable_rows(
            rels, LGRID, _link_cells, "csrel", "key",
            lambda r: f"Show the checks on {r['Label']}",
            picked=st.session_state.get("_cs_rel"),
            on_pick=lambda k: st.session_state.update(
                _cs_rel=None if st.session_state.get("_cs_rel") == k else k),
            tip=lambda r: [r["Label"], (" · ".join([r["Driving"]] + r["Others"]), "mono"),
                           f'{len(r["Checks"])} checks. Click again to show all.'])


# --- The checks, and the one picked -----------------------------------------------------------

def _check_cells(c) -> str:
    sev_tone = theme.SEVERITY_TONE.get(c["Severity"], "neutral")
    under = (f' <span class="dq-badge dq-cs-under" title="Written with &lt;&gt;: a value '
             f'missing on one side is never counted, so the figure can read low." '
             f'style="color:{theme.TONE["high"]["fg"]};background:{theme.TONE["high"]["bg"]};'
             f'border-color:{theme.TONE["high"]["bd"]}">May undercount</span>'
             if c["Unsafe"] else "")
    failed = "—" if c["Failing rows"] is None else f'{c["Failing rows"]:,}'
    return (
        f'<span class="stack dq-tmname dq-cs-check" style="--dq-stripe:{_colour(c["State"])}">'
        f'<span class="t1 wrap">{html.escape(c["Name"])}</span>'
        f'<span class="t2 sans"><span class="mono">{html.escape(c["Relationship"])}</span>'
        f' · {html.escape(c["Kind"])}{under}</span></span>'
        f'<span class="stack num"><span class="t1 big">{failed}</span>'
        f'<span class="t2 sans">{html.escape(cs.rate_label(c))}</span></span>'
        f'<span class="dq-cs-badges">'
        f'{theme.badge(SEV_SHORT.get(c["Severity"], c["Severity"]), sev_tone)}'
        f'{theme.badge(c["State"], STATE_TONE[c["State"]])}</span>'
    )


def _open_in_rules(rule_id: str) -> None:
    st.session_state["_rule_pick"] = rule_id
    st.session_state.pop("_rule_el", None)
    st.session_state.pop("_rule_cde_search", None)
    st.switch_page(RULES)


def _nodes(a: str, b: str) -> str:
    return (f'<span class="dq-cs-node">{html.escape(a)}</span>'
            f'<span class="dq-cs-edge" style="--dq-edge:{theme.ACCENT}"></span>'
            f'<span class="dq-cs-node">{html.escape(b)}</span>')


def _bars(c) -> str:
    hist = cs.history(runs, c["key"])
    if not hist:
        return ""
    top = max(n for _, n in hist) or 1
    fill = theme.TONE["critical"]["bd"] if c["State"] == "Failing" else theme.NEUTRAL["border_strong"]
    cols = "".join(
        f'<div class="col"><div class="bar" style="height:{max(3, round(44 * n / top))}px;'
        f'background:{fill}" title="{n:,} on {ts:%-d %b}"></div>'
        f'<span>{ts:%-d %b}</span></div>' for ts, n in hist)
    word = "Missing" if c["Kind"] == "Missing record" else "Failed"
    return (f'<div class="dq-cs-hist"><div class="t2 sans">{word}, last {len(hist)} runs'
            f'</div><div class="bars" role="img" aria-label="{word} per run: '
            f'{", ".join(str(n) for _, n in hist)}">{cols}</div></div>')


def _rows_tab(c) -> None:
    if not c["Failing rows"]:
        st.caption("Nothing failed on its latest measurement."
                   if c["Checked"] is not None else "Not measured yet.")
        return
    mine = samples[(samples["rule_id"] == c["key"]) & (samples["run_id"] == c["Run id"])]
    if mine.empty:
        mine = samples[samples["rule_id"] == c["key"]]
    if mine.empty:
        st.caption("No rows were stored for this run. Rows are kept when an active "
                   "check fails.")
        return
    rows = []
    for raw in mine["sample_row"].head(100):
        try:
            rows.append(json.loads(raw))
        except (TypeError, ValueError):
            pass
    view = cs.sample_view(rows, c)
    if view["left"] is None:
        st.caption(f"{len(mine):,} of {c['Failing rows']:,} rows kept"
                   + (". Both tables call the compared column the same, so each row keeps "
                      "one value of the two." if c["Kind"] == "Same value" else "."))
        components.sample_rows_view(mine)
        return
    chips = "".join(theme.badge(f"{k} {n:,}", "critical" if k == "Different" else "high")
                    for k, n in view["counts"].items())
    st.markdown(
        f'<div class="dq-cs-rowshd"><span class="t2 sans">{min(10, len(view["rows"])):,} of '
        f'{c["Failing rows"]:,} shown</span><span class="dq-cs-badges">{chips}</span></div>',
        unsafe_allow_html=True)
    lt, rt = (cs.short(t) for t in [c["Driving"]] + c["Others"][-1:]) \
        if c["Others"] else (cs.short(c["Driving"]), "")
    empty = '<span class="dq-cs-empty">— empty</span>'
    head = ("".join(f"<th>{html.escape(k)}</th>" for k in view["keys"])
            + f'<th class="cmp">{html.escape(lt)} {html.escape(view["left"])}</th>'
            + f'<th class="cmp">{html.escape(rt)} {html.escape(view["right"])}</th><th>Result</th>')
    body = ""
    for r in view["rows"][:10]:
        right = empty if r["right"] is None else (
            html.escape(r["same"]) + (f'<mark class="dq-cs-diff">{html.escape(r["diff"])}</mark>'
                                      if r["diff"] else ""))
        body += ("<tr>" + "".join(f'<td class="mono">{html.escape(str(k) if k is not None else "")}</td>'
                                  for k in r["key"])
                 + f'<td class="cmp mono">{empty if r["left"] is None else html.escape(r["left"])}</td>'
                 + f'<td class="cmp mono">{right}</td>'
                 + f'<td>{theme.badge(r["why"], "critical" if r["why"] == "Different" else "high")}</td></tr>')
    st.markdown(f'<div class="dq-cs-rows"><table><thead><tr>{head}</tr></thead>'
                f"<tbody>{body}</tbody></table></div>", unsafe_allow_html=True)
    st.caption("The differing part is highlighted. Only the key and the compared columns "
               "are kept.")


@st.fragment
def _checks() -> None:
    rel = st.session_state.get("_cs_rel")
    scoped = [c for c in checks if not rel or c["rel_key"] == rel]
    left, right = st.columns([1.25, 1], gap="medium")
    with left, st.container(key="dq_cscard"):
        top, q = st.columns([1, 1.1], vertical_alignment="center")
        top.markdown(
            '<div class="dq-tmcard-hd"><div class="t">Checks'
            f'<span class="dq-count">{len(scoped)}</span></div>'
            + (f'<div class="q">On {html.escape(next(r["Label"] for r in rels if r["key"] == rel))}.</div>'
               if rel else "") + "</div>",
            unsafe_allow_html=True,
        )
        term = q.text_input("Search checks", placeholder="Search",
                            label_visibility="collapsed", icon=":material/search:",
                            key="_cs_search").strip().lower()
        st.session_state.setdefault("_cs_show", "all")
        n = {k: sum(c["State"] == k for c in scoped) for k in ("Failing", "Shadow")}
        show = st.segmented_control(
            "Status", ["all", "failing", "shadow"], key="_cs_show",
            label_visibility="collapsed",
            format_func=lambda v: {"all": f"All {len(scoped)}", "failing": f"Failing {n['Failing']}",
                                   "shadow": f"Shadow {n['Shadow']}"}[v]) or "all"
        kinds = [k for k in cs.KINDS if any(c["Kind"] == k for c in scoped)]
        kind = st.segmented_control(
            "Type", kinds, key="_cs_kind", label_visibility="collapsed",
            format_func=lambda k: f"{k} {sum(c['Kind'] == k for c in scoped)}")
        view = [c for c in scoped if (show == "all" or c["State"].lower() == show)
                and (not kind or c["Kind"] == kind)]
        if term:
            view = [c for c in view if term in
                    f"{c['key']} {c['Name']} {c['Relationship']} {c['Kind']}".lower()]
        pick = st.session_state.get("_cs_pick")
        if pick not in {c["key"] for c in view} and view:
            pick = view[0]["key"]
        if view:
            with st.container(key="dqrows_cschecks"):
                components.clickable_rows(
                    view, CGRID, _check_cells, "cs", "key", lambda c: f"Open {c['Name']}",
                    picked=pick, on_pick=components.pick_into("_cs_pick"),
                    tip=lambda c: [c["Name"], (c["key"], "mono"),
                                   cs.KIND_MEANING[c["Kind"]]])
        else:
            st.markdown('<div class="dq-tmempty">No check matches.</div>',
                        unsafe_allow_html=True)

    c = by_id.get(pick)
    if c is None:
        return
    with right, st.container(key="dq_cspane"):
        edge = _colour(c["State"])
        st.markdown(
            f"<style>.st-key-dq_cspane{{border-top:4px solid {edge}}}</style>"
            '<div class="dq-cs-panehd">'
            f'<div class="t">{html.escape(c["Name"])}</div><div class="b">'
            + theme.badge(c["Kind"], "neutral")
            + theme.badge(SEV_SHORT.get(c["Severity"], c["Severity"]),
                          theme.SEVERITY_TONE.get(c["Severity"], "neutral"))
            + theme.badge(c["State"], STATE_TONE[c["State"]])
            + f'<span class="dq-cs-id">{html.escape(c["key"])}</span></div></div>',
            unsafe_allow_html=True,
        )
        word = {"Missing record": ("Found", "Missing"), "Same total": ("Match", "Off")}.get(
            c["Kind"], ("Match", "Different"))
        unit = "Groups" if c["Kind"] == "Same total" else "Compared"
        red = theme.TONE["critical"]["fg"] if c["Failing rows"] else None
        figs = [(word[0], "—" if c["Rate"] is None else f'{theme.pct_text(c["Rate"], 1)}%', None),
                (unit, "—" if c["Checked"] is None else f'{c["Checked"]:,}', None),
                (word[1], "—" if c["Failing rows"] is None else f'{c["Failing rows"]:,}', red),
                ("Last run", "—" if c["Run ts"] is None
                 else f'{pd.Timestamp(c["Run ts"]):%-d %b, %H:%M}', None)]
        st.markdown(
            '<div class="dq-cs-fig4">' + "".join(
                f'<div><div class="l">{a}</div><div class="v"'
                + (f' style="color:{col}"' if col else "") + f">{b}</div></div>"
                for a, b, col in figs) + "</div>",
            unsafe_allow_html=True,
        )
        n_rows = 0 if c["Failing rows"] is None else c["Failing rows"]
        ov, rows_tab, defn = st.tabs(["Overview", f"Rows · {n_rows:,}", "Definition"],
                                     key="_cs_tab")
        with ov:
            pairs = cs.link_pairs(c["join_sql"])
            st.markdown(
                "".join(f'<div class="dq-cs-rel">{_nodes(a, b)}</div>' for a, b in pairs)
                + '<ul class="dq-cs-words">'
                + "".join(f"<li>{html.escape(x)}</li>" for x in cs.plain_words(c))
                + "</ul>" + _bars(c),
                unsafe_allow_html=True,
            )
        with rows_tab:
            _rows_tab(c)
        with defn:
            st.caption("The join, the predicate and the scope as the register stores them.")
            st.code("FROM  " + c["join_sql"] + "\nWHERE " + c["rule_expr"]
                    + ("" if not c["scope_filter"] else "\n  AND " + c["scope_filter"]),
                    language="sql", wrap_lines=True)
        if st.button("Open in Rules", icon=":material/arrow_forward:", type="tertiary",
                     key="_cs_to_rules",
                     help="Its every version, its history, and promotion if it is in "
                          "shadow."):
            _open_in_rules(c["key"])


_checks()

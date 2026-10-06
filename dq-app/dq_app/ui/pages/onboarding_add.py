"""Add tables — choose a table from Unity Catalog and submit it for onboarding.

A drill-down from Onboarding, registered and not linked in the sidebar. Drawn to the
design mock (artboards 2 and 3 of the "Onboarding Screens" canvas). Three screens:

1. **Browse** -- a catalog tree, the open schema's tables with what each would cost to
   check, and a panel for the table chosen. "Continue" writes nothing.
2. **Draft** -- the table's settings, what happens once it is submitted, and optional
   binding suggestions. Still nothing written.
3. **Submitted** -- after "Submit for onboarding" and its confirmation, which append the
   selection and every suggestion together, signed with the platform identity.

ONE SUBMISSION, NOT A COMMIT HALFWAY THROUGH. Until 2026-10-05 the selection was written
on the first screen's "Select", and the suggestion screen read like the rest of the same
form -- so a user who had not reached any Submit found the table already onboarding.

FAST BY CONSTRUCTION. Which tables are readable comes from one privilege query per
schema (`adapter.get_readable_tables`), sizes from a few reused connections in parallel
(`get_table_sizes`), both held for an hour. The list is drawn before sizes arrive and
filled in by one rerun, so the page is usable while they load. The exact per-table
access check still happens at the moment of submitting (`adapter.select_table`).

Session state: `_add_cat` / `_add_sch` the open schema, `_add_pick` the row chosen,
`_add_draft` the table being drafted, `_add_done` the table just submitted,
`_add_sizes` sizes already fetched this session, by schema.
"""

from __future__ import annotations

import html
import re

import pandas as pd
import streamlit as st

from dq_app.data import adapter
from dq_app.domain import coverage, onboarding
from dq_app.ui import components, theme
from dq_app.ui import onboarding_style as ui

components.page_chrome()
ui.inject()

SIZE_CAP = 60     # sizes are fetched for at most this many rows of one schema


def _key(*parts: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", "__".join(parts))


def _back():
    if st.button("← Onboarding", key="add_back", type="tertiary"):
        for k in ("_add_draft", "_add_done"):
            st.session_state.pop(k, None)
        st.switch_page("dq_app/ui/pages/onboarding.py")


def _size(b) -> str:
    if b is None or pd.isna(b):
        return "—"
    b = float(b)
    for unit, div in (("GB", 1e9), ("MB", 1e6), ("KB", 1e3)):
        if b >= div:
            return f"{b / div:,.1f} {unit}"
    return f"{b:,.0f} B"


monitored = adapter.get_monitored_tables()
current = (onboarding.current_monitored(monitored, ("selected", "paused")) if len(monitored)
           else monitored)
selected_now = set(current["target_table"]) if len(current) else set()
regs = adapter.get_cde_registry_current()
label = {r["cde_id"]: r["cde_name"] for _, r in regs.iterrows()}

# =========================================================================================
# 3. Submitted
# =========================================================================================
done = st.session_state.get("_add_done")
if done:
    _back()
    name = done["fqn"].split(".")[-1]
    st.markdown(
        f'<div class="onb-crumb">Onboarding / Add tables / Submitted</div>'
        f'<div class="onb-title" style="margin-top:.2rem"><h1>{html.escape(name)} is submitted'
        f'</h1>{theme.badge("Recorded with your name", "success")}</div>'
        f'<div class="onb-mono" style="margin:.25rem 0 .6rem">{html.escape(done["fqn"])}</div>',
        unsafe_allow_html=True)
    with st.container(key="onbcard_done"):
        ui.head("What happens next")
        sug = done["suggestions"]
        st.markdown(
            '<div class="onb-tl">'
            '<i class="done">✓</i><div class="onb-ev"><b>Submitted.</b> '
            + (f'{sug} suggestion{"s" if sug != 1 else ""} sent to the element owners. '
               if sug else "")
            + 'Nothing is checked yet.</div>'
            '<i class="next">2</i><div class="onb-ev"><b>Discovery, at the next pipeline run.'
            '</b> A job proposes which columns hold which registered element.</div>'
            '<i class="later">3</i><div class="onb-ev"><b>Each element\'s owner decides.</b> '
            'Your suggestions need a second person.</div>'
            '<i class="later">4</i><div class="onb-ev"><b>Shadow, then promote.</b> Checks are '
            'measured raising nothing, until someone promotes them.</div></div>',
            unsafe_allow_html=True)
    if done.get("refused"):
        st.error("The table was submitted, but these suggestions were not recorded:\n\n"
                 + "\n\n".join(done["refused"]), icon=":material/block:")
    a, b, _ = st.columns([1, 1, 3])
    if a.button("Go to Onboarding", key="add_done_onb", type="primary",
                use_container_width=True):
        st.session_state.pop("_add_done", None)
        st.switch_page("dq_app/ui/pages/onboarding.py")
    if b.button("Add another table", key="add_done_more", use_container_width=True):
        st.session_state.pop("_add_done", None)
        st.rerun()
    st.stop()

# =========================================================================================
# 2. Draft: settings, what happens, optional suggestions -- then one Submit
# =========================================================================================
draft = st.session_state.get("_add_draft")
if draft:
    _back()
    fqn, name = draft["fqn"], draft["fqn"].split(".")[-1]
    st.markdown(
        f'<div class="onb-crumb">Onboarding / Add tables / {html.escape(name)}</div>'
        f'<div class="onb-title" style="margin-top:.2rem"><h1>Onboard {html.escape(name)}</h1>'
        f'{theme.badge("Not submitted yet", "neutral")}</div>'
        f'<div class="onb-mono" style="margin:.25rem 0 .6rem">{html.escape(fqn)} · row key '
        f'{html.escape(", ".join(draft["row_key"]))} · daily at 03:00 · owner '
        f'{html.escape(draft["owner"])} · {html.escape(str(draft.get("domain") or ""))}</div>',
        unsafe_allow_html=True)

    left, right = st.columns([1, 2])
    with left, st.container(key="onbcard_next"):
        ui.head("When you submit")
        st.markdown(
            '<div class="onb-tl">'
            '<i class="next">1</i><div class="onb-ev"><b>The table is selected</b>, recorded '
            'with your name, with any suggestions you add here.</div>'
            '<i class="later">2</i><div class="onb-ev"><b>Discovery, at the next pipeline run.'
            '</b> A job proposes which columns hold which registered element.</div>'
            '<i class="later">3</i><div class="onb-ev"><b>Each element\'s owner decides.</b> '
            'Your suggestions need a second person.</div>'
            '<i class="later">4</i><div class="onb-ev"><b>Shadow.</b> Checks are generated and '
            'measured by the scheduled run, raising nothing.</div>'
            '<i class="later">5</i><div class="onb-ev"><b>Promote.</b> Someone promotes them '
            'after seeing the numbers.</div></div>'
            '<div class="onb-rule" style="margin-top:.3rem"></div>'
            '<div class="onb-cap">Nothing is written until you submit.</div>',
            unsafe_allow_html=True)

    with right, st.container(key="onbcard_rows_suggest"):
        st.markdown(
            '<div class="onb-hd"><span class="t">Suggest bindings <span class="onb-cap" '
            'style="font-weight:400">· optional</span></span>'
            f'{theme.badge("Needs a second approver", "info")}</div>'
            '<div class="onb-cap">If you know what a column holds, say so. Columns you leave '
            'are still looked at: the job proposes from tags, value patterns and names. Your '
            'suggestions go to the element\'s owner, and you can\'t approve them yourself.'
            '</div>', unsafe_allow_html=True)
        bound = {b["target_column"] for b in coverage.bound_columns(adapter.get_cde_registry())
                 if b["target_table"] == fqn}
        cols = adapter.get_catalog_columns(fqn)
        free = [c for c in (cols["column_name"] if len(cols) else []) if c not in bound]
        NONE = "No suggestion — let the job propose"
        W = [.85, 1.3, 1.6]
        hd = st.columns(W)
        for c, t in zip(hd, ["Column", "Registered element", "Why"]):
            c.markdown(f'<div class="onb-headrow">{t}</div>', unsafe_allow_html=True)
        picks = {}
        for c in free:
            st.markdown('<div class="onb-rule"></div>', unsafe_allow_html=True)
            a, b, w = st.columns(W, vertical_alignment="center")
            a.markdown(f'<div class="onb-cell"><b class="onb-mono" style="color:inherit">'
                       f'{html.escape(c)}</b></div>', unsafe_allow_html=True)
            el = b.selectbox(c, [NONE] + sorted(label, key=label.get),
                             format_func=lambda k: label.get(k, k), key=f"_sg_el_{c}",
                             label_visibility="collapsed")
            why = w.text_input("Why", key=f"_sg_why_{c}", label_visibility="collapsed",
                               placeholder="What makes you sure", disabled=el == NONE)
            if el != NONE:
                picks[c] = (el, why)
        st.markdown('<div class="onb-rule"></div>', unsafe_allow_html=True)
        missing = [c for c, (_, why) in picks.items() if not why.strip()]
        f1, f2, f3 = st.columns([2.1, .8, 1.4], vertical_alignment="center")
        f1.markdown(
            f'<div class="onb-cap"><b style="color:#14142b">{len(picks)} '
            f'suggestion{"s" if len(picks) != 1 else ""}</b>'
            + (f' · <span style="color:#b91c1c">{len(missing)} without a reason</span>'
               if missing else " · each goes to the element's owner, not to you")
            + "</div>", unsafe_allow_html=True)
        if f2.button("Back", key="add_draft_back", use_container_width=True):
            st.session_state.pop("_add_draft", None)
            st.rerun()
        if f3.button("Submit for onboarding", key="add_submit", type="primary",
                     disabled=bool(missing), use_container_width=True):
            ui.ask("submit")

    def _submit():
        try:
            adapter.select_table(fqn, draft["row_key"], draft["owner"],
                                 business_domain=draft.get("domain"))
        except adapter.OnboardingRejected as exc:
            return str(exc)
        sent, refused = 0, []
        for c, (cde, why) in picks.items():
            try:
                adapter.suggest_binding(fqn, c, cde, why)
                sent += 1
            except adapter.OnboardingRejected as exc:
                refused.append(f"{c}: {exc}")
        for c in picks:
            st.session_state.pop(f"_sg_el_{c}", None)
            st.session_state.pop(f"_sg_why_{c}", None)
        st.session_state.pop("_add_draft", None)
        st.session_state["_add_done"] = {"fqn": fqn, "suggestions": sent}
        if refused:
            # The selection landed; say plainly which suggestions did not.
            st.session_state["_add_done"]["refused"] = refused
        return None

    lines = [f'<span class="onb-mono">{html.escape(c)}</span> → {html.escape(label.get(cde, cde))}'
             f' — “{html.escape(why)}”' for c, (cde, why) in picks.items()]
    ui.confirm(
        "submit", f"Submit {name} for onboarding?",
        f'<span class="onb-mono">{html.escape(fqn)}</span>'
        + ui.items([f"Row key: <b>{html.escape(', '.join(draft['row_key']))}</b>",
                    f"Owner of record: <b>{html.escape(draft['owner'])}</b>",
                    f"Business domain: <b>{html.escape(str(draft.get('domain') or ''))}</b>",
                    f"Checked daily at 03:00, full table scan ({html.escape(draft['scan'])})"])
        + (f"<b>{len(picks)} suggestion{'s' if len(picks) != 1 else ''}</b>, each to its "
           "element's owner — you can't approve your own:" + ui.items(lines)
           if picks else "No binding suggestions: the discovery job will propose them.<br>")
        + "This records the selection and any suggestions with your name. A selection "
          "cannot be withdrawn from the app yet.",
        "Submit", _submit)
    st.stop()

# =========================================================================================
# 1. Browse
# =========================================================================================
_back()
st.markdown('<div class="onb-crumb">Onboarding / Add tables</div>', unsafe_allow_html=True)
st.title("Add tables")
st.markdown('<div class="onb-cap">You see the tables Unity Catalog lets this app see. Choosing '
            'one writes nothing until you submit it.</div>', unsafe_allow_html=True)

tables = adapter.get_catalog_tables()
if tables.empty:
    st.caption("No tables are visible here.",
               help="The catalog is read from system.information_schema. On the local "
                    "fixture there is no Unity Catalog.")
    st.stop()
tables = tables.assign(fqn=tables["table_catalog"] + "." + tables["table_schema"] + "."
                       + tables["table_name"])

cats = sorted(tables["table_catalog"].unique())
cat = st.session_state.get("_add_cat") if st.session_state.get("_add_cat") in cats else cats[0]
schemas_of = {c: sorted(tables.loc[tables["table_catalog"] == c, "table_schema"].unique())
              for c in cats}
sch = st.session_state.get("_add_sch")
if sch not in schemas_of[cat]:
    sch = schemas_of[cat][0]

tree, mid, side = st.columns([.9, 2.6, 1.15])

with tree, st.container(key="onbcard_tree"):
    ui.head("Catalog")
    find = st.text_input("Search tables", key="_add_find", placeholder="Search tables",
                         label_visibility="collapsed")
    # Only the open catalog is expanded: `samples` alone holds fourteen schemas.
    for c in cats:
        if st.button(f"{'▾' if c == cat else '▸'} {c}", key=f"onbtree_cat_{_key(c)}",
                     use_container_width=True) and c != cat:
            st.session_state["_add_cat"] = c
            st.session_state["_add_sch"] = schemas_of[c][0]
            st.session_state.pop("_add_pick", None)
            st.rerun()
        if c != cat:
            continue
        for sc in schemas_of[c]:
            on = (c, sc) == (cat, sch)
            if st.button(sc, key=f"onbtree_{'on_' if on else ''}{_key(c, sc)}",
                         use_container_width=True):
                st.session_state["_add_cat"], st.session_state["_add_sch"] = c, sc
                st.session_state.pop("_add_pick", None)
                st.rerun()

view = tables[(tables["table_catalog"] == cat) & (tables["table_schema"] == sch)]
if find.strip():
    view = view[view["table_name"].str.contains(find.strip(), case=False, regex=False)]
view = view.sort_values("table_name")
readable = adapter.get_readable_tables(cat, sch)
schema_cols = adapter.get_catalog_columns(f"{cat}.{sch}")
ncols = schema_cols.groupby("table_name").size().to_dict() if len(schema_cols) else {}
ntags = (schema_cols[schema_cols["tag_cde"].notna()].groupby("table_name").size().to_dict()
         if len(schema_cols) else {})
sizes_key = f"{cat}.{sch}"
sizes = st.session_state.get("_add_sizes", {}).get(sizes_key)     # None: not fetched yet
picked = st.session_state.get("_add_pick")


def _access(r) -> tuple[str, str]:
    if r["fqn"] in selected_now:
        return "Already selected", "info"
    if r["table_name"] not in readable:
        return "Not readable — grant SELECT", "critical"
    if sizes is None:
        return "Checking size…", "neutral"
    size = sizes.get(r["fqn"])
    if size is not None and float(size) > onboarding.SCAN_LIMIT_BYTES:
        return "Too large for a daily scan", "high"
    lab = onboarding.scan_label(size)
    return lab[0].upper() + lab[1:], "success"     # green already says "readable"


rows = []
for _, r in view.iterrows():
    size = sizes.get(r["fqn"]) if sizes else None
    rows.append({
        "Id": _key(r["fqn"]), "Fqn": r["fqn"], "Name": r["table_name"],
        "Owner": str(r["table_owner"] or "—"),
        "Size": _size(size) if sizes is not None else "…",
        "SizeBytes": size,
        "Cols": int(ncols.get(r["table_name"], 0)), "Tags": int(ntags.get(r["table_name"], 0)),
        "Access": _access(r),
    })
if picked not in {r["Id"] for r in rows}:
    picked = None

with mid, st.container(key="onbcard_rows_tables"):
    ui.head(f"{html.escape(cat)}.{html.escape(sch)} · {len(rows)} table{'s' if len(rows) != 1 else ''}",
            "Size and tags from Unity Catalog")
    if not rows:
        st.markdown('<div class="onb-ev" style="padding:.3rem 0 .8rem">No tables here match.'
                    '</div>', unsafe_allow_html=True)
    else:
        # Flexible columns shrink and truncate; fixed minimums overflowed into the
        # selection card beside this one.
        GRID = "1.4rem minmax(0,1.7fr) 4.4rem 2.8rem minmax(0,.8fr) minmax(0,1.5fr)"

        def _cells(m) -> str:
            box = f'<span class="onb-box{" on" if m["Id"] == picked else ""}"></span>'
            tags = theme.badge(f'{m["Tags"]} tagged', "info") if m["Tags"] \
                else theme.badge("no tags", "neutral")
            return (f'<span>{box}</span>'
                    f'<span class="stack"><span class="name">{html.escape(m["Name"])}</span>'
                    f'<span class="t2">owner: {html.escape(m["Owner"])}</span></span>'
                    f'<span class="num">{m["Size"]}</span><span class="num">{m["Cols"]}</span>'
                    f'<span>{tags}</span><span>{theme.badge(*m["Access"])}</span>')

        components.row_head(["", "Table", ("Size", "n"), ("Cols", "n"), "Tags", "Daily check"],
                            GRID)
        with st.container(key="dqrows_add"):
            components.clickable_rows(rows, GRID, _cells, "add", "Id",
                                      lambda m: f"Choose {m['Fqn']}", picked=picked,
                                      on_pick=components.pick_into("_add_pick"))
        st.markdown(
            '<div class="onb-cap" style="padding:.6rem 0 .5rem">Check time is estimated from '
            'size: about 15 s per 1.5 GB on the smallest warehouse. Tables above the cost '
            'limit wait on partition scans. A table the checks cannot read would fail on '
            'every run, so it cannot be selected until access is granted.</div>',
            unsafe_allow_html=True)

with side, st.container(key="onbcard_sel"):
    if picked is None:
        ui.head("Selection")
        st.markdown('<div class="onb-cap">Choose a table to see whether it can be checked.'
                    '</div>', unsafe_allow_html=True)
    else:
        r = next(x for x in rows if x["Id"] == picked)
        fqn = r["Fqn"]
        ui.head("Selection · 1 table")
        st.markdown(f'<div class="onb-mono onb-wrap">{html.escape(fqn)}</div>',
                    unsafe_allow_html=True)
        text, tone = r["Access"]
        if tone in ("critical", "high", "info"):
            st.markdown(f'<div class="onb-note">{theme.badge(text, tone)}<br>'
                        + {"critical": "The checks could not read it, so every run would fail. "
                                       "Ask its owner to grant SELECT first.",
                           "high": "A full daily scan would cost too much. Large tables wait "
                                   "on partition scans.",
                           "info": "Its progress is on Onboarding."}[tone]
                        + "</div>", unsafe_allow_html=True)
        else:
            cols = adapter.get_catalog_columns(fqn)
            names = list(cols["column_name"]) if len(cols) else []
            groups = sorted({g for g in regs["owner_group"].dropna()}) if len(regs) else []
            key = st.multiselect("Row key", names, default=onboarding.suggest_row_key(names),
                                 key="add_rowkey",
                                 help="The column(s) that identify a row. Stamped on every "
                                      "failed row the checks sample.")
            owner = st.selectbox("Owner of record", groups or ["dq-stewards"], key="add_owner")
            # Every check on the table carries this, and the Tables page and scorecard
            # filter by it -- a table onboarded without one vanished from both.
            domains = sorted({d for d in regs["business_domain"].dropna()}) if len(regs) else []
            domain = st.selectbox("Business domain", domains or ["Customer"], key="add_domain")
            scan = f'{r["Size"]} · {onboarding.scan_label(r["SizeBytes"])}'
            st.selectbox("Checked", ["Daily at 03:00"], disabled=True, key="add_sched")
            st.selectbox("Scan", [f"Full table · {scan}"], disabled=True, key="add_scan")
            st.markdown('<div class="onb-note">Next you can suggest bindings, then submit. '
                        'Nothing is written until you submit.</div>', unsafe_allow_html=True)
            if st.button("Continue", key="add_continue", type="primary", disabled=not key,
                         use_container_width=True):
                st.session_state["_add_draft"] = {"fqn": fqn, "row_key": list(key),
                                                  "owner": owner, "domain": domain,
                                                  "scan": scan}
                st.session_state.pop("_add_pick", None)
                st.rerun()
        if st.button("Cancel", key="add_cancel", use_container_width=True):
            st.session_state.pop("_add_pick", None)
            st.rerun()

# Sizes last: the page above is already on screen while they load, then one rerun fills
# them in. Cached for an hour, so a schema opened before comes back at once.
if sizes is None and rows:
    fetched = adapter.get_table_sizes(tuple(view["fqn"].head(SIZE_CAP)))
    st.session_state.setdefault("_add_sizes", {})[sizes_key] = fetched
    st.rerun()

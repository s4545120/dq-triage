"""One table's onboarding — its bindings to review, and its checks to promote.

A drill-down from Onboarding, registered and not linked in the sidebar; `_onb_pick`
names the table. Drawn to the design mock (artboards 4 and 5 of the "Onboarding
Screens" canvas): the review card while bindings are open, the shadow evidence and
the Promote card once checks exist.

Two writes start here, both appends signed with the platform identity:

* **A binding decision** -> config.binding_review (`adapter.review_binding`). The apply
  job turns approvals into bindings, so no two reviewers race for a cde_version. A
  person cannot approve a binding they suggested -- the control offers only Reject,
  and the adapter and the apply job each refuse it as well.
* **A promotion** -> one rule version per check (`adapter.promote_rule`), the same
  append the Rules page makes. Offered only once every binding is decided and every
  shadow check has been measured: promoting a check nobody has seen measure anything is
  promoting a guess.
"""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from dq_app.data import adapter, identity
from dq_app.domain import onboarding
from dq_app.ui import components, theme
from dq_app.ui import onboarding_style as ui
from dq_app.ui.components import opt

components.page_chrome()
ui.inject()

if st.session_state.pop("_onb_back", False):    # set by a decommission just written
    try:
        st.switch_page("dq_app/ui/pages/onboarding.py")
    except st.errors.StreamlitAPIException:     # the page run alone, outside the app's nav
        st.success("Decommissioned. Its checks are retired; its columns are unbound at the "
                   "next onboarding run.")
        st.stop()

status = adapter.get_onboarding_status()
picked = st.session_state.get("_onb_pick")
if status.empty or picked not in set(status["table_code"]):
    if st.button("← Onboarding", key="onbt_back0", type="tertiary"):
        st.switch_page("dq_app/ui/pages/onboarding.py")
    st.caption("Choose a table on Onboarding first.")
    st.stop()

s = status[status["table_code"] == picked].iloc[0]
table, stage = s["target_table"], s["stage"]
cat, sch, name = table.split(".")
monitored = onboarding.current_monitored(adapter.get_monitored_tables(), ("selected", "paused"))
m = monitored[monitored["target_table"] == table].iloc[0]

registry = adapter.get_cde_registry()
cdes = adapter.get_cde_registry_current()
cde = {r["cde_id"]: r for _, r in cdes.iterrows()}
me = identity.current().email

# --- Header ------------------------------------------------------------------------------
if st.button("← Onboarding", key="onbt_back", type="tertiary"):
    st.switch_page("dq_app/ui/pages/onboarding.py")
when = opt(m["effective_from"])
st.markdown(
    f'<div class="onb-title"><h1>{html.escape(name)}</h1>{ui.stage_badge(stage)}</div>'
    f'<div class="onb-mono" style="margin-top:.25rem">{html.escape(table)} · selected by '
    f'{html.escape(str(m["selected_by"]))}'
    + (f" on {pd.Timestamp(when):%-d %b}" if when is not None else "")
    + f' · owner {html.escape(str(opt(m["owner_group"]) or "—"))}</div>',
    unsafe_allow_html=True)
st.markdown(ui.steps(stage), unsafe_allow_html=True)

bound = onboarding.bindings_on(registry, table)
proposals, reviews = adapter.get_binding_proposals(), adapter.get_binding_reviews()
open_p = onboarding.open_proposals(proposals, reviews, registry)
open_p = open_p[open_p["target_table"] == table] if len(open_p) else open_p
ev = onboarding.shadow_evidence(adapter.get_rule_registry_current(), adapter.get_check_runs(),
                                table)
shadow, active = ev[ev["status"] == "shadow"], ev[ev["status"] == "active"]
cols = adapter.get_catalog_columns(table)
col_type = dict(zip(cols["column_name"], cols["data_type"])) if len(cols) else {}
templates = adapter.get_check_templates()


def _checks_for(cde_id: str) -> list[str]:
    """What a column bound to this element would be checked for, in words."""
    if templates.empty or cde_id not in cde:
        return []
    t = templates[templates["data_class"] == cde[cde_id]["data_class"]]
    out = []
    for title in t["title"]:
        words = str(title).replace("{element}", "").strip()
        out.append(words.removeprefix("is ").strip())
    return out


def _element_cell(cde_id: str) -> str:
    c = cde.get(cde_id)
    if c is None:
        return html.escape(cde_id)
    tier = str(c["criticality"]).capitalize() + (" · PII" if bool(c["pii"]) else "")
    tone = {"critical": "critical", "high": "high"}.get(str(c["criticality"]), "neutral")
    return f'{html.escape(c["cde_name"])}<br>{theme.badge(tier, tone)}'


# --- Review bindings --------------------------------------------------------------------
if len(open_p):
    HOW = {"uc_tag": "Column tag", "value_signature": "Value pattern",
           "name_match": "Column name", "suggested": "Suggested"}
    W = [1.05, 1.35, 2.1, 1.15, 1.25]
    choice: dict[str, str | None] = {}
    waived = adapter.self_approval_waived()
    with st.container(key="onbcard_rows_review"):
        ui.head(f"Proposed bindings · {len(open_p)}",
                "Proposed by the discovery job, or suggested by a person. Evidence shows the "
                "shape of the values, never the values.")
        if waived:
            st.markdown(f'<div class="onb-note">{theme.badge("Second approver waived on this app", "high")} '
                        'You can approve your own suggestions here. Each one is recorded '
                        f'with “{onboarding.WAIVER_MARK}” in its reason.</div>',
                        unsafe_allow_html=True)
        hd = st.columns(W)
        for c, label in zip(hd, ["Column", "Registered element", "Why it was proposed",
                                 "Checks it gets", "Decision"]):
            c.markdown(f'<div class="onb-headrow">{label}</div>', unsafe_allow_html=True)
        for _, p in open_p.sort_values("target_column").iterrows():
            by = str(p["proposed_by"])
            person = onboarding.is_person(by)
            mine = person and by.lower() == me.lower() and not waived
            who = ("Suggested by you" if mine else f"Suggested by {by}") if person \
                else f'Discovery job · {HOW.get(p["method"], p["method"]).lower()}'
            checks = _checks_for(p["cde_id"])
            chips = "".join(f'<span class="onb-chip">{html.escape(x)}</span>'
                            for x in checks[:2])
            if len(checks) > 2:
                chips += f'<span class="onb-chip">+{len(checks) - 2}</span>'
            st.markdown('<div class="onb-rule"></div>', unsafe_allow_html=True)
            a, b, c, d, e = st.columns(W, vertical_alignment="center")
            a.markdown(f'<div class="onb-cell"><b class="onb-mono" style="color:inherit">'
                       f'{html.escape(p["target_column"])}</b><br><span class="onb-cap">'
                       f'{html.escape(str(col_type.get(p["target_column"], "")))}</span></div>',
                       unsafe_allow_html=True)
            b.markdown(f'<div class="onb-cell">{_element_cell(p["cde_id"])}</div>',
                       unsafe_allow_html=True)
            c.markdown(f'<div class="onb-ev">{theme.badge(html.escape(who), "info" if person else "neutral")}'
                       f'<br>{html.escape(str(p["evidence"] or ""))}</div>',
                       unsafe_allow_html=True)
            d.markdown(f'<div>{chips or "<span class=onb-cap>none apply</span>"}</div>',
                       unsafe_allow_html=True)
            with e:
                choice[p["proposal_id"]] = st.segmented_control(
                    f"Decision on {p['target_column']}",
                    ["Reject"] if mine else ["Approve", "Reject"],
                    key=f"_rv_{p['proposal_id']}", label_visibility="collapsed")
                if mine:
                    st.markdown('<div class="onb-cap">You suggested this. A second person '
                                'must approve it.</div>', unsafe_allow_html=True)
        st.markdown('<div class="onb-rule"></div>', unsafe_allow_html=True)
        picks = [v for v in choice.values() if v]
        rejecting = any(v == "Reject" for v in picks)
        reason = st.text_input("Reason for the rejections", key="_rv_reason",
                               placeholder="Why the column does not hold that element",
                               disabled=not rejecting)
        approved = sum(v == "Approve" for v in picks)
        rejected = sum(v == "Reject" for v in picks)
        left_f, right_f = st.columns([3, 1], vertical_alignment="center")
        left_f.markdown(
            f'<div class="onb-cap"><b style="color:#14142b">{approved} approved · {rejected} '
            f'rejected</b> · {len(open_p) - len(picks)} undecided</div>',
            unsafe_allow_html=True)
        if not adapter.writes_are_durable():
            left_f.markdown('<div class="onb-cap">Writes are session-only here — deploy to '
                            'decide.</div>', unsafe_allow_html=True)
        n = len(picks)
        if right_f.button(f"Record {n} decision{'s' if n != 1 else ''}",
                          key="onbt_record", type="primary", disabled=not picks,
                          use_container_width=True):
            ui.ask("review")

        def _record():
            done, refused = 0, []
            for pid, pick in choice.items():
                if not pick:
                    continue
                try:
                    adapter.review_binding(pid, "approved" if pick == "Approve" else "rejected",
                                           reason)
                    done += 1
                except adapter.OnboardingRejected as exc:
                    refused.append(str(exc))
            if refused:
                return f"Recorded {done}. Not recorded:\n\n" + "\n\n".join(refused)
            for pid in choice:
                st.session_state.pop(f"_rv_{pid}", None)
            return None

        col_of = dict(zip(open_p["proposal_id"], open_p["target_column"]))
        el_of = dict(zip(open_p["proposal_id"], open_p["cde_id"]))
        lines = [f'<b>{v}</b> · <span class="onb-mono">{html.escape(col_of[k])}</span> → '
                 f'{html.escape(cde[el_of[k]]["cde_name"] if el_of[k] in cde else el_of[k])}'
                 for k, v in choice.items() if v]
        ui.confirm(
            "review", f"Record {n} decision{'s' if n != 1 else ''}?",
            f"On <b>{html.escape(name)}</b>:" + ui.items(lines)
            + (f'Reason given for the rejections: “{html.escape(reason)}”<br>' if rejected and reason.strip()
               else ('<b style="color:#b91c1c">A rejection needs a reason — add one first.</b><br>'
                     if rejected else ""))
            + f"Each decision is recorded with your name ({html.escape(me)}) and cannot be "
              "edited afterwards. Approved columns get their checks generated in shadow at "
              "the next pipeline run; nothing raises a problem until they are promoted.",
            f"Record {n} decision{'s' if n != 1 else ''}", _record)

    proposed = set(proposals.loc[proposals["target_table"] == table, "target_column"]) \
        if len(proposals) else set()
    unbound = [c for c in col_type if c not in {b["target_column"] for b in bound}
               and c not in proposed]
    lo, ro = st.columns([2, 1])
    with lo, st.container(key="onbcard_unprop"):
        ui.head(f"Not proposed · {len(unbound)}")
        st.markdown(
            "".join(f'<div class="onb-ev"><b class="onb-mono" style="color:inherit">'
                    f'{html.escape(c)}</b> — nothing identifies it as a registered element.'
                    '</div>' for c in unbound)
            or '<div class="onb-ev">Every column is bound or proposed.</div>',
            unsafe_allow_html=True)
    with ro, st.container(key="onbcard_what"):
        ui.head("What a decision does")
        st.markdown(
            '<div class="onb-ev"><b>Approve</b> records the binding with your name. A job then '
            'adds it to the element register and generates the column\'s checks in shadow.'
            '</div><div class="onb-ev"><b>Reject</b> records why. The column is not proposed '
            'again unless someone tags it or suggests it.</div><div class="onb-ev"><b>A '
            'suggestion needs a second person.</b> Whoever suggests a binding cannot approve '
            'it.</div><div class="onb-ev">Nothing raises a problem until the checks are '
            'measured and someone promotes them.</div>', unsafe_allow_html=True)

# --- Checks and promotion ----------------------------------------------------------------
if len(ev):
    measured = ev[ev["violation_pct"].notna()]
    breach = int(measured["would_breach"].astype(bool).sum())
    last = opt(s["last_run_ts"])
    ncols = len({c for c in ev["target_column"] if opt(c)})
    if len(active) and not len(shadow):
        ui.kpi_row([
            ("Checks active", len(active), f"on {ncols} columns"),
            ("Breaching", breach, "problems in Triage", "critical" if breach else None),
            ("Passing", len(measured) - breach, "at or under their limit",
             "success" if len(measured) - breach else None),
            ("Runs", int(s["runs"]), f"last {last:%-d %b, %H:%M}" if last is not None else "none yet"),
        ])
    else:
        ui.kpi_row([
            ("Checks in shadow", len(shadow), f"on {ncols} columns"),
            ("Would breach", breach, "problems may open in Triage",
             "critical" if breach else None),
            ("Would pass", len(measured) - breach, "at or under their limit",
             "success" if len(measured) - breach else None),
            ("Shadow runs", int(s["runs"]),
             f"last {last:%-d %b, %H:%M}" if last is not None else "none yet"),
        ])

    def _check_label(e) -> str:
        nm = str(opt(e["rule_name"]) or e["rule_id"])
        el = cde[e["cde_id"]]["cde_name"] if e["cde_id"] in cde else ""
        what = nm.removeprefix(el).strip()
        what = what.removesuffix(f'({e["target_column"]})').strip().removeprefix("is ").strip()
        col = opt(e["target_column"])
        return (f'<b class="mono">{html.escape(col)}</b> ' if col else "") + html.escape(what or nm)

    lc, rc = st.columns([1.9, 1])
    with lc, st.container(key="onbcard_rows_checks"):
        live = len(active) and not len(shadow)
        ui.head("Checks, as the latest scheduled run measured them",
                "Active: breaches reach Triage" if live else "In shadow: measured, raising nothing")
        EGRID = "minmax(12rem,2.2fr) 6.5rem 4.6rem 4.2rem minmax(7rem,1fr)"
        components.row_head(["Check", ("Failed", "n"), ("Rate", "n"), ("Limit", "n"),
                             "Now" if live else "If promoted"], EGRID)
        out = []
        for _, e in ev.iterrows():
            if e["violation_pct"] is None or pd.isna(e["violation_pct"]):
                rate, failed, verdict = "—", "—", theme.badge("not yet measured", "neutral")
            else:
                rate = f'{e["violation_pct"]:.2f}%'
                failed = f'{int(e["violation_count"])} / {int(e["rows_scanned"])}'
                if e["status"] == "active":
                    verdict = (theme.badge("breaching", "critical") if e["would_breach"]
                               else theme.badge("passing", "success"))
                else:
                    verdict = (theme.badge("would breach", "critical") if e["would_breach"]
                               else theme.badge("would pass", "success"))
            out.append(
                f'<div class="dq-rowgrid" style="grid-template-columns:{EGRID}">'
                f'<span class="name" title="{html.escape(e["rule_id"])}">{_check_label(e)}</span>'
                f'<span class="num">{failed}</span><span class="num">{rate}</span>'
                f'<span class="num">{e["fail_threshold_pct"]:g}%</span><span>{verdict}</span></div>')
        st.markdown(f'<div class="onb-scroll">{"".join(out)}</div>', unsafe_allow_html=True)

    with rc:
        with st.container(key="onbcard_promote"):
            ui.head("Promote")
            if len(shadow) and stage == "bindings awaiting review":
                st.markdown('<div class="onb-ev">Finish reviewing the bindings first. '
                            'Promotion comes after every column this table will be checked '
                            'on is decided.</div>', unsafe_allow_html=True)
            elif len(shadow) and shadow["violation_pct"].isna().any():
                st.markdown(
                    f'<div class="onb-ev">{int(shadow["violation_pct"].isna().sum())} of '
                    f'{len(shadow)} shadow checks have not been measured yet. They are '
                    'measured at the next scheduled run; promote after that.</div>',
                    unsafe_allow_html=True)
            elif len(shadow):
                # The final decision: every column is promoted unless unticked here. An
                # unticked column is EXCLUDED -- its binding is taken back and its checks
                # retired -- which only a binding that came from a proposal can record.
                excludable = onboarding.excludable_columns(proposals, reviews, table)
                by_col = {c: g for c, g in shadow.groupby(shadow["target_column"].fillna(""))}
                st.markdown('<div class="onb-cap">Untick a column to exclude it: its binding '
                            'is taken back and its checks retired.</div>',
                            unsafe_allow_html=True)
                keep: dict[str, bool] = {}
                for col in sorted(by_col):
                    g = by_col[col]
                    nb = int(g["would_breach"].astype(bool).sum())
                    can = bool(col) and col in excludable
                    keep[col] = st.checkbox(
                        f"{col or 'Cross-table'} · {len(g)} check{'s' if len(g) != 1 else ''}"
                        + (f" · {nb} would breach" if nb else ""),
                        value=True, key=f"_onb_inc_{col or '_xt'}", disabled=not can,
                        help=None if can else "Bound by hand, not through a proposal, so it "
                        "is promoted with the rest.")
                promote = pd.concat([g for c, g in by_col.items() if keep[c]]) \
                    if any(keep.values()) else shadow.iloc[0:0]
                dropped = [c for c in sorted(by_col) if not keep[c]]
                exclude = {excludable[c]: list(by_col[c]["rule_id"]) for c in dropped}
                sb = int(promote["would_breach"].astype(bool).sum())
                n_ex = sum(len(by_col[c]) for c in dropped)
                st.markdown(
                    f'<div class="onb-ev">Makes <b>{len(promote)} checks</b> active. On the '
                    f'latest run <b style="color:{theme.TONE["critical"]["fg"]}">{sb}</b> would '
                    'breach and open problems in Triage on the next run.'
                    + (f' <b>{len(dropped)} column{"s" if len(dropped) != 1 else ""}</b> '
                       f'excluded, {n_ex} check{"s" if n_ex != 1 else ""} retired.'
                       if dropped else "") + '</div>', unsafe_allow_html=True)
                ex_reason = (st.text_input("Why exclude", key="onbt_ex_reason",
                                           placeholder="Why the column does not hold its element")
                             if dropped else "")
                note = st.text_input("Note", key="onbt_note",
                                     value=f"Promoted after shadow review of {name}.")
                if st.button(f"Promote {len(promote)} checks", key="onbt_promote",
                             type="primary", use_container_width=True,
                             disabled=promote.empty):
                    ui.ask("promote")

                def _promote():
                    try:
                        done, retired, refused = adapter.promote_table(
                            list(promote["rule_id"]), exclude, note, ex_reason)
                    except adapter.WriteRejected as exc:
                        return str(exc)
                    if refused:
                        return (f"Promoted {len(done)} of {len(promote)}, retired "
                                f"{len(retired)} of {n_ex}. Not written:\n\n"
                                + "\n\n".join(refused))
                    for c in by_col:
                        st.session_state.pop(f"_onb_inc_{c or '_xt'}", None)
                    return None

                breaching = [_check_label(e) for _, e in promote.iterrows() if e["would_breach"]]
                el_of = {c: (cde[g["cde_id"].iloc[0]]["cde_name"] if g["cde_id"].iloc[0] in cde
                             else g["cde_id"].iloc[0]) for c, g in by_col.items()}
                ui.confirm(
                    "promote", f"Promote {len(promote)} checks on {name}?",
                    f"<b>{len(promote)} checks</b> become active. On the latest run "
                    f'<b style="color:{theme.TONE["critical"]["fg"]}">{sb} would breach</b> and '
                    f"open problems in Triage at the next run, and {len(promote) - sb} would pass."
                    + (ui.items(breaching, 6) if breaching else "<br>")
                    + (f"<b>Excluded</b>, their checks retired and their bindings taken back at "
                       "the next onboarding run:"
                       + ui.items([f'<span class="onb-mono">{html.escape(c)}</span> → '
                                   f'{html.escape(el_of[c])} · {len(by_col[c])} checks'
                                   for c in dropped])
                       + (f'Reason: “{html.escape(ex_reason)}”<br>' if ex_reason.strip()
                          else '<b style="color:#b91c1c">An exclusion needs a reason — add '
                               'one first.</b><br>')
                       if dropped else "")
                    + f"Each check gets a new version signed {html.escape(me)}. Taking one back "
                      "is another new version, not an undo.",
                    f"Promote {len(promote)} checks", _promote)
                st.markdown(f'<div class="onb-cap">Each check gets a new version signed '
                            f'{html.escape(me)}.</div>', unsafe_allow_html=True)
                if not adapter.writes_are_durable():
                    st.markdown('<div class="onb-cap">Writes are session-only here — deploy '
                                'to promote.</div>', unsafe_allow_html=True)
            else:
                who = sorted({str(w) for w in active["promoted_by"] if opt(w)})
                at = pd.to_datetime(active["promoted_at"]).max()
                st.markdown(
                    f'<div class="onb-ev">All {len(active)} checks are active'
                    + (f", promoted by {html.escape(', '.join(who))}" if who else "")
                    + (f" on {at:%-d %b %Y}" if isinstance(at, pd.Timestamp) and not pd.isna(at)
                       else "")
                    + '. Their breaches reach Triage.</div>', unsafe_allow_html=True)

        with st.container(key="onbcard_cols"):
            ui.head("Columns and their elements")
            approved_by = {}
            if len(proposals) and len(reviews):
                j = proposals.merge(reviews[reviews["decision"] == "approved"], on="proposal_id")
                approved_by = {(t, c): w for t, c, w in
                               zip(j["target_table"], j["target_column"], j["reviewed_by"])}
            found = {"uc_tag": "found by tag", "value_signature": "found by value pattern",
                     "name_match": "found by column name", "suggested": "suggested",
                     "manual": "registered by hand"}
            # Excluded at promotion: the binding stays on the register until the
            # onboarding job's unbind step runs, so say so rather than list it as bound.
            gone = onboarding.excluded_bindings(proposals, reviews)
            st.markdown(
                "".join(
                    f'<div class="onb-ev" style="padding:.3rem 0;border-bottom:1px solid #f0f0f5">'
                    f'<b class="onb-mono" style="color:inherit">{html.escape(b["target_column"])}'
                    f'</b> → {html.escape(b["cde_name"])}<br><span class="onb-cap">'
                    f'{found.get(b["discovered_by"], b["discovered_by"])}'
                    + (f' · approved by {html.escape(approved_by[(table, b["target_column"])])}'
                       if (table, b["target_column"]) in approved_by else "")
                    + (" · <b>excluded at promotion</b>, unbound at the next onboarding run"
                       if (table, b["target_column"], b["cde_id"]) in gone else "")
                    + "</span></div>"
                    for b in sorted(bound, key=lambda b: b["target_column"]))
                or '<div class="onb-ev">Nothing bound yet.</div>', unsafe_allow_html=True)

elif not len(open_p) and stage != "paused":
    with st.container(key="onbcard_wait"):
        ui.head("Nothing to decide yet")
        st.markdown(f'<div class="onb-ev">{html.escape(onboarding.STAGES[onboarding.STAGE_INDEX[stage]][2])} '
                    'This page fills in as the pipeline job runs.</div>',
                    unsafe_allow_html=True)

# --- Manage the table ---------------------------------------------------------------------
# Pause and resume are reversible and touch only the table's row. Decommission is not:
# it retires the table and every check on it, and the onboarding job then unbinds its
# columns. Each goes through a confirmation that says exactly that.
paused = m["status"] == "paused"
n_active, n_shadow = len(active), len(shadow)
with st.container(key="onbcard_manage"):
    ui.head("Manage table")
    st.markdown(
        '<div class="onb-ev">'
        + ("<b>Paused.</b> The daily run skips it; its checks and bindings are kept. "
           "Resume to start checking again." if paused else
           "<b>Pause</b> stops the daily checks and keeps everything, to resume later. "
           "<b>Decommission</b> is permanent: the table and its checks are retired.")
        + "</div>", unsafe_allow_html=True)
    reason_txt = st.text_input("Reason", key="onbt_manage_reason",
                               placeholder="Why — kept with the table's history")
    b1, b2, _ = st.columns([1, 1, 2])
    if b1.button("Resume checking" if paused else "Pause checking", key="onbt_pause",
                 use_container_width=True):
        ui.ask("resume" if paused else "pause")
    if b2.button("Decommission", key="onbt_decom", use_container_width=True):
        ui.ask("decommission")


def _status(to: str):
    def _go():
        try:
            adapter.set_table_status(table, to, reason_txt)
        except adapter.OnboardingRejected as exc:
            return str(exc)
        return None
    return _go


def _decommission():
    try:
        n, refused = adapter.decommission_table(table, reason_txt)
    except adapter.OnboardingRejected as exc:
        return str(exc)
    if refused:
        return (f"The table is retired and {n} checks with it. Not retired:\n\n"
                + "\n\n".join(refused))
    st.session_state.pop("_onb_pick", None)
    st.session_state["_onb_back"] = True       # leave the page on the next run
    return None


why = (f'Reason: “{html.escape(reason_txt)}”<br>' if reason_txt.strip()
       else '<b style="color:#b91c1c">Add a reason first — it is required.</b><br>')
ui.confirm("pause", f"Pause checking {name}?",
           why + f"The daily run skips <b>{html.escape(table)}</b> until it is resumed. Its "
           f"{n_active} active and {n_shadow} shadow checks, its bindings and its history are "
           "kept. Problems already in Triage stay where they are.", "Pause", _status("paused"))
ui.confirm("resume", f"Resume checking {name}?",
           why + f"The next daily run checks <b>{html.escape(table)}</b> again, with its "
           f"{n_active} active checks raising problems as before.", "Resume", _status("selected"))
ui.confirm("decommission", f"Decommission {name}?",
           why + f"<b>This is permanent.</b> <b>{html.escape(table)}</b> is retired, and so are its "
           f"<b>{n_active + n_shadow} checks</b> ({n_active} active, {n_shadow} shadow): each gets a "
           "retired version signed with your name. The next onboarding run removes its "
           "columns from the element register. Past results and problems already in Triage "
           "are kept as history. To check it again, onboard it again.",
           "Decommission", _decommission)

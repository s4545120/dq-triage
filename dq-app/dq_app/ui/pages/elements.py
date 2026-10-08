"""Elements — propose, decide and follow changes to the critical data element register.

The step before table onboarding: an element is registered here, then bound to columns
on a table's onboarding page, then checked. Three kinds of change -- register, amend,
retire -- each written as a proposal (`config.cde_proposal`), decided by a SECOND person
(`config.cde_review`), and applied to `config.cde_registry` by the onboarding job's
apply_elements step. Nothing on this page writes the register; the page says which of
those three steps each change is waiting on.

`_el_pick` holds the element picked, `_el_mode` what the right card is doing
(None, "register", "amend", "retire"). Every write goes through
`onboarding_style.confirm`.
"""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from dq_app.data import adapter, identity
from dq_app.domain import elements
from dq_app.domain.onboarding import WAIVER_MARK, OnboardingRejected
from dq_app.ui import components, theme
from dq_app.ui import onboarding_style as ui
from dq_app.ui.components import opt

components.page_chrome()
ui.inject()

PICK, MODE, DRAFT, REV = "_el_pick", "_el_mode", "_el_draft", "_el_rev"
me = identity.current().email
waived = adapter.self_approval_waived()


def _set_mode(mode, pick=None):
    def _go():
        st.session_state[MODE] = mode
        if pick is not None:
            st.session_state[PICK] = pick
    return _go


# --- Data ---------------------------------------------------------------------------------
registry = adapter.get_cde_registry()
current = adapter.get_cde_registry_current()
state = adapter.get_cde_proposal_current()
rule_current = adapter.get_rule_registry_current()
templates = adapter.get_check_templates()
open_p = state[state["state"] == "open"] if len(state) else state
waiting_job = state[state["state"] == "approved"] if len(state) else state

# --- Header and figures -------------------------------------------------------------------
head, act = st.columns([4, 1], vertical_alignment="bottom")
with head:
    st.title("Critical data elements")
    st.markdown('<div class="onb-cap">What is checked starts here: an element is registered, '
                'then bound to columns, then checked. A second person approves every change '
                'to the register.</div>', unsafe_allow_html=True)
with act:
    st.button("Propose an element", key="el_new", type="primary", icon=":material/add:",
              use_container_width=True, on_click=_set_mode("register"))

n_unbound = int((current["status"] == "proposed").sum()) if len(current) else 0
mine_to_review = int((open_p["proposed_by"].str.lower() != me.lower()).sum()) \
    if len(open_p) else 0
ui.kpi_row([
    ("Registered", len(current), f"{n_unbound} not yet bound to a column" if n_unbound
     else "every one bound to a column"),
    ("Awaiting review", len(open_p), "changes nobody has decided"),
    ("Waiting on you", mine_to_review, "proposed by someone else",
     "high" if mine_to_review else None),
    ("Awaiting the job", len(waiting_job), "approved, not yet on the register"),
])

if waived:
    st.markdown(f'<div class="onb-note">{theme.badge("Second approver waived on this app", "high")} '
                'You can approve your own proposals here. Each one is recorded with '
                f'“{WAIVER_MARK}” in its reason.</div>', unsafe_allow_html=True)


# --- Helpers ------------------------------------------------------------------------------
def _crit(c) -> str:
    c = str(opt(c) or "")
    return theme.badge(c.capitalize() or "—", theme.CRITICALITY_TONE.get(c, "neutral"))


def _fmt(attr, v) -> str:
    v = elements._norm(v)
    if v is None:
        return "—"
    if attr == "pii":
        return "Yes" if v else "No"
    if attr == "tolerance_pct":
        return f"{float(v):g}% of rows (target ≥ {100 - float(v):g}%)"
    return str(v)


def _template_line(data_class, signature=None, cde_id=None) -> str:
    """Which checks a column bound to this element gets, by name -- the class's own,
    and the element's pattern where the class has no format check. Nothing where no
    template table is installed (the fixture): the page cannot say."""
    if templates.empty:
        return ""
    words = elements.check_words(elements.templates_for(templates, data_class, signature,
                                                        cde_id))
    unconfirmed = ("" if not elements._norm(signature) or cde_id in elements.CONFIRMED_SIGNATURES
                   else '<div class="onb-cap">Its value pattern is not confirmed by the '
                        'business, so no pattern check is generated from it.</div>')
    if not words:
        return (f'<div class="onb-note">No check template covers <b>{html.escape(str(data_class))}'
                '</b> and the element declares no value pattern: a column bound to it gets no '
                'checks generated. Its rules are written by hand.</div>' + unconfirmed)
    return ('<div class="onb-ev"><b>A bound column is checked that it</b>'
            + ui.items([html.escape(w) for w in words], limit=12) + "</div>" + unconfirmed)


def _status_of(cde_id, status) -> tuple[str, str]:
    if len(elements.open_for(state, cde_id)):
        return "Change waiting", "high"
    return ("Not yet bound", "moderate") if status == "proposed" else ("Bound", "success")


# --- The element list ---------------------------------------------------------------------
split = st.container(key="onb_elsplit")
left, right = split.columns([1.5, 1])
with left, st.container(key="onbcard_rows_el"):
    ui.head(f"Elements · {len(current)}", "Click one to see it, amend it or retire it")
    q = st.text_input("Search elements", key="_el_q", placeholder="Name, id or domain",
                      label_visibility="collapsed")
    view = current.copy()
    if q.strip() and len(view):
        needle = q.strip().lower()
        hay = (view["cde_id"].astype(str) + " " + view["cde_name"].astype(str) + " "
               + view["business_domain"].astype(str)).str.lower()
        view = view[hay.str.contains(needle, regex=False)]
    order = {c: i for i, c in enumerate(elements.CRITICALITIES)}
    view = view.assign(_o=view["criticality"].map(order)).sort_values(["_o", "cde_name"]) \
        if len(view) else view
    # The class rides on the name's second line: as its own column it squeezed the
    # name to nothing below about 1100px of page.
    GRID = "minmax(0,1fr) 5.5rem 2.75rem 7.5rem"
    rows = []
    for _, r in view.iterrows():
        label, tone = _status_of(r["cde_id"], r["status"])
        rows.append({"Id": r["cde_id"], "Name": r["cde_name"], "Crit": r["criticality"],
                     "Class": r["data_class"], "Cols": len(components.as_list(r["bindings"])),
                     "St": label, "Tone": tone})

    def _cells(m) -> str:
        return (f'<span class="stack"><span class="name">{html.escape(str(m["Name"]))}</span>'
                f'<span class="t2 mono">{html.escape(m["Id"])} · '
                f'{html.escape(str(m["Class"]))}</span></span>'
                f'<span>{_crit(m["Crit"])}</span>'
                f'<span class="num">{m["Cols"]}</span>'
                f'<span>{theme.badge(m["St"], m["Tone"])}</span>')

    if not rows:
        st.markdown('<div class="onb-ev" style="padding:.4rem 0 1rem">No element matches.'
                    '</div>', unsafe_allow_html=True)
    else:
        components.row_head(["Element", "Criticality", ("Cols", "n"), "Status"], GRID)
        with st.container(key="dqrows_el"):
            components.clickable_rows(
                rows, GRID, _cells, "el", "Id", lambda m: f"Open {m['Name']}",
                picked=st.session_state.get(PICK),
                on_pick=components.pick_into(PICK, also={MODE: None}))


# --- The form for a proposal --------------------------------------------------------------
def _attr_form(prefix: str, base: dict) -> dict:
    """Every attribute, prefilled from `base`. Keys carry `prefix` so a form for one
    element never shows another's typing."""
    k = lambda f: f"_el_f_{prefix}_{f}"   # noqa: E731
    out = {}
    out["cde_name"] = st.text_input("Name", value=opt(base.get("cde_name")) or "", key=k("name"))
    out["definition"] = st.text_area(
        "Definition", value=opt(base.get("definition")) or "", key=k("def"), height=80,
        help="What the element means in business terms -- what a reviewer agrees to.")
    a, b = st.columns(2)
    dc = opt(base.get("data_class")) or "other"
    out["data_class"] = a.selectbox("Data class", elements.DATA_CLASSES,
                                    index=elements.DATA_CLASSES.index(dc), key=k("class"),
                                    help="Decides which check templates a bound column gets.")
    cr = opt(base.get("criticality")) or "medium"
    out["criticality"] = b.selectbox("Criticality", elements.CRITICALITIES,
                                     index=elements.CRITICALITIES.index(cr), key=k("crit"),
                                     help="Orders problems in Triage. Never a check's severity.")
    a, b = st.columns(2)
    tol = elements._norm(base.get("tolerance_pct"))
    out["tolerance_pct"] = a.number_input(
        "Tolerance, % of rows", min_value=0.0, max_value=100.0, step=0.5,
        value=None if tol is None else float(tol), key=k("tol"),
        help="How many violating rows the business accepts. The element's target is 100 "
             "minus this, and no check on it may have a looser limit. Empty is 'not "
             "declared': the element then has no target.")
    pii = elements._norm(base.get("pii"))
    out["pii"] = b.toggle("Personal data", value=bool(pii), key=k("pii"),
                          help="Its profile then stores no values.")
    a, b = st.columns(2)
    out["business_domain"] = a.text_input("Domain", value=opt(base.get("business_domain")) or "",
                                          key=k("dom"))
    out["owner_group"] = b.text_input("Owner group", value=opt(base.get("owner_group")) or "",
                                      key=k("own"), help="Shown to reviewers; not enforced.")
    with st.expander("More: business term, regulatory basis, value pattern"):
        out["business_term"] = st.text_input("Business term",
                                             value=opt(base.get("business_term")) or "",
                                             key=k("term"))
        out["regulatory_basis"] = st.text_input("Regulatory basis",
                                                value=opt(base.get("regulatory_basis")) or "",
                                                key=k("reg"))
        out["expected_signature"] = st.text_input(
            "Expected value pattern (regex)", value=opt(base.get("expected_signature")) or "",
            key=k("sig"), help="Discovery proposes a column whose values match it. Spark "
                               "(Java) regex: \\s and \\d, never [[:space:]].")
        problem = elements.signature_problem(out["expected_signature"].strip() or None)
        if problem:
            st.markdown(f'<div class="onb-note" style="color:#b91c1c">{html.escape(problem)}</div>',
                        unsafe_allow_html=True)
    return out


def _submit(change: str, cde_id: str, attrs: dict, reason: str, based_on):
    st.session_state[DRAFT] = dict(change=change, cde_id=cde_id, attrs=attrs, reason=reason,
                                   based_on=based_on)
    ui.ask("el_propose")


# --- Right card: propose, or the element picked --------------------------------------------
mode = st.session_state.get(MODE)
pick = st.session_state.get(PICK)
latest = elements.latest_version(registry, pick) if pick else None
if pick and latest is None:
    pick = None

with right:
    if mode == "register":
        with st.container(key="onbcard_el_new"):
            ui.head("Propose an element", "A second person approves it; the onboarding job "
                                          "then registers it")
            attrs = _attr_form("new", {})
            taken = set(registry["cde_id"]) | (set(state["cde_id"]) if len(state) else set())
            cid = st.text_input("Element id", key="_el_new_id",
                                placeholder=elements.suggest_id(attrs["cde_name"], taken),
                                help="Never reused, retired elements included. Left empty, "
                                     "the suggestion is used.").strip().upper() \
                or elements.suggest_id(attrs["cde_name"], taken)
            st.markdown(_template_line(attrs["data_class"],
                                       attrs["expected_signature"].strip() or None, cid),
                        unsafe_allow_html=True)
            reason = st.text_area("Why it is critical", key="_el_new_reason", height=70)
            a, b = st.columns(2)
            a.button("Cancel", key="el_new_cancel", use_container_width=True,
                     on_click=_set_mode(None))
            if b.button("Propose", key="el_new_go", type="primary", use_container_width=True):
                _submit("register", cid, attrs, reason, None)
    elif pick:
        el = latest
        with st.container(key="onbcard_el_pick"):
            label, tone = _status_of(pick, el["status"])
            st.markdown(
                f'<div class="onb-title"><h1 style="font-size:1.15rem">{html.escape(str(el["cde_name"]))}'
                f'</h1>{_crit(el["criticality"])}{theme.badge(label, tone)}</div>'
                f'<div class="onb-mono">{html.escape(pick)} · version {int(el["cde_version"])}</div>',
                unsafe_allow_html=True)
            if mode in (None, "view") or el["status"] == "retired":
                bound = [f"{str(b['target_table']).split('.')[-1]}.{b['target_column']}"
                         for b in components.as_list(el["bindings"])]
                rules = elements.rules_on(rule_current, pick)
                n_act = int((rules["status"] == "active").sum()) if len(rules) else 0
                n_sh = int((rules["status"] == "shadow").sum()) if len(rules) else 0
                facts = "".join(
                    f'<div class="onb-ev"><b>{elements.ATTR_LABEL[a]}</b> · '
                    f'{html.escape(_fmt(a, el.get(a)))}</div>'
                    for a in ("definition", "data_class", "tolerance_pct", "pii",
                              "business_domain", "owner_group", "regulatory_basis",
                              "expected_signature"))
                st.markdown(
                    facts
                    + '<div class="onb-rule"></div>'
                    + f'<div class="onb-ev"><b>Columns</b> · '
                    + ("".join(f'<span class="onb-chip">{html.escape(x)}</span>' for x in bound)
                       or 'none yet -- bind one from a table\'s onboarding page')
                    + f'</div><div class="onb-ev"><b>Checks</b> · {n_act} active, {n_sh} in shadow</div>'
                    + _template_line(el["data_class"], el.get("expected_signature"), pick),
                    unsafe_allow_html=True)
                waiting = elements.open_for(state, pick)
                if len(waiting):
                    st.markdown('<div class="onb-note">A change to this element is waiting '
                                'below. Only one at a time.</div>', unsafe_allow_html=True)
                else:
                    a, b = st.columns(2)
                    a.button("Amend", key="el_amend", icon=":material/edit:",
                             use_container_width=True, on_click=_set_mode("amend"))
                    b.button("Retire", key="el_retire", icon=":material/archive:",
                             use_container_width=True, on_click=_set_mode("retire"))
            elif mode == "amend":
                ui.head("Amend", "Change what it means, how much it matters or how much may "
                                 "be wrong. Its columns stay bound.")
                attrs = _attr_form(f"amend_{pick}_{int(el['cde_version'])}", el)
                diff = elements.changed(el, attrs)
                if "data_class" in diff and elements.is_bound(el):
                    st.markdown('<div class="onb-note" style="color:#b91c1c">The data class of '
                                'an element with bound columns cannot change: their checks '
                                'were generated for the old class.</div>',
                                unsafe_allow_html=True)
                loose = elements.over_tolerance(rule_current, pick, attrs["tolerance_pct"]) \
                    if "tolerance_pct" in diff else []
                if loose:
                    st.markdown(
                        '<div class="onb-note">These checks have a looser limit than the new '
                        'tolerance. Nothing changes them: the threshold job advises on each, '
                        'and a person adopts the advice on the Thresholds page.'
                        + ui.items([f'<span class="onb-mono">{html.escape(x)}</span>' for x in loose])
                        + '</div>', unsafe_allow_html=True)
                st.markdown('<div class="onb-cap">' + (
                    "Changes: " + ", ".join(elements.ATTR_LABEL[d] for d in diff)
                    if diff else "Nothing changed yet.") + "</div>", unsafe_allow_html=True)
                reason = st.text_area("Why it changes", key=f"_el_amend_reason_{pick}", height=70)
                a, b = st.columns(2)
                a.button("Cancel", key="el_amend_cancel", use_container_width=True,
                         on_click=_set_mode(None))
                if b.button("Propose amendment", key="el_amend_go", type="primary",
                            use_container_width=True, disabled=not diff):
                    _submit("amend", pick, attrs, reason, int(el["cde_version"]))
            elif mode == "retire":
                ui.head("Retire", "Permanent. The id is never reused.")
                imp = elements.retire_impact(pick, el, rule_current, adapter.get_cohorts())
                lines = [
                    f"<b>{len(imp['bindings'])}</b> bound column"
                    f"{'s' if len(imp['bindings']) != 1 else ''} leave coverage",
                    f"<b>{len(imp['active'])}</b> active and <b>{len(imp['shadow'])}</b> shadow "
                    "checks get a retired version and stop running",
                    f"<b>{len(imp['problems'])}</b> Triage problem"
                    f"{'s' if len(imp['problems']) != 1 else ''} carrying its checks stay, "
                    "as history",
                ]
                st.markdown('<div class="onb-ev">' + ui.items(lines) + "</div>"
                            + ("".join(f'<span class="onb-chip">{html.escape(x)}</span>'
                                       for x in imp["bindings"])),
                            unsafe_allow_html=True)
                reason = st.text_area("Why it can go", key=f"_el_retire_reason_{pick}", height=70)
                a, b = st.columns(2)
                a.button("Cancel", key="el_retire_cancel", use_container_width=True,
                         on_click=_set_mode(None))
                if b.button("Propose retirement", key="el_retire_go", type="primary",
                            use_container_width=True):
                    _submit("retire", pick, {}, reason, int(el["cde_version"]))
    else:
        with st.container(key="onbcard_el_how"):
            ui.head("How an element is registered")
            st.markdown(
                '<div class="onb-hw">'
                '<i>1</i><span><b>You propose it</b>: what it means, how critical, how much '
                'may be wrong</span>'
                '<i>2</i><span><b>A second person approves</b> it</span>'
                '<i>3</i><span>The onboarding job writes it to the register, not yet bound</span>'
                '<i>4</i><span>Discovery proposes columns for it on every selected table</span>'
                '<i>5</i><span><b>Its owner approves</b> each binding; checks follow</span>'
                '</div><div class="onb-rule" style="margin-top:.4rem"></div>'
                '<div class="onb-cap">Amending and retiring take the same two people. '
                'Retiring takes the element\'s checks with it.</div>',
                unsafe_allow_html=True)


# --- Changes awaiting review --------------------------------------------------------------
def _proposal_body(p: dict) -> str:
    change = p["change"]
    base = elements.latest_version(registry, p["cde_id"]) or {}
    if change == "register":
        lines = [f"<b>{elements.ATTR_LABEL[a]}</b> · {html.escape(_fmt(a, p.get(a)))}"
                 for a in elements.ATTRS if elements._norm(p.get(a)) is not None]
    elif change == "amend":
        lines = [f"<b>{elements.ATTR_LABEL[a]}</b> · {html.escape(_fmt(a, base.get(a)))} → "
                 f"{html.escape(_fmt(a, p.get(a)))}" for a in elements.changed(base, p)]
    else:
        imp = elements.retire_impact(p["cde_id"], base, rule_current, adapter.get_cohorts())
        n_b, n_p = len(imp["bindings"]), len(imp["problems"])
        lines = [f"{n_b} bound column{'s' if n_b != 1 else ''} leave coverage",
                 f"{len(imp['active'])} active and {len(imp['shadow'])} shadow checks retire",
                 f"{n_p} Triage problem{'s' if n_p != 1 else ''} stay as history"]
    return f'<div class="onb-ev">{ui.items(lines, limit=12)}</div>'


def _job_line(p: dict) -> str:
    why = elements.refusal({k: v for k, v in p.items() if k != "reviewed_by"},
                           elements.versions_of(registry, p["cde_id"]))
    if why:
        return (f'<div class="onb-note" style="color:#b91c1c">The onboarding job will not '
                f'apply this: {html.escape(why)}. Reject it and propose again.</div>')
    return ""


if len(open_p) or len(waiting_job):
    with st.container(key="onbcard_el_queue"):
        ui.head(f"Changes awaiting review · {len(open_p)}",
                "Whoever proposed a change cannot approve it")
        for _, row in open_p.iterrows():
            p = row.to_dict()
            pid, mine = p["proposal_id"], str(p["proposed_by"]).lower() == me.lower()
            name = p.get("cde_name") if p["change"] != "retire" else \
                (elements.latest_version(registry, p["cde_id"]) or {}).get("cde_name")
            st.markdown('<div class="onb-rule"></div>', unsafe_allow_html=True)
            st.markdown(
                f'<div class="onb-ev">{theme.badge(elements.CHANGE_LABEL[p["change"]], "info")} '
                f'<b>{html.escape(str(opt(name) or p["cde_id"]))}</b> '
                f'<span class="onb-mono">{html.escape(p["cde_id"])}</span><br>'
                f'<span class="onb-cap">Proposed by {"you" if mine else html.escape(str(p["proposed_by"]))}'
                f' · “{html.escape(str(p["reason"]))}”</span></div>'
                + _proposal_body(p) + _job_line(p), unsafe_allow_html=True)
            a, b, c = st.columns([2.4, 1, 1], vertical_alignment="bottom")
            reason = a.text_input("Reason", key=f"_el_rv_reason_{pid}",
                                  placeholder="Required to reject", label_visibility="collapsed")
            own_block = mine and not waived
            if b.button("Approve", key=f"el_rv_ok_{pid}", use_container_width=True,
                        disabled=own_block,
                        help="You proposed this. A second person must approve it."
                        if own_block else None):
                st.session_state[REV] = (pid, "approved", reason)
                ui.ask("el_review")
            if c.button("Reject", key=f"el_rv_no_{pid}", use_container_width=True):
                st.session_state[REV] = (pid, "rejected", reason)
                ui.ask("el_review")
        for _, row in waiting_job.iterrows():
            p = row.to_dict()
            st.markdown('<div class="onb-rule"></div>', unsafe_allow_html=True)
            st.markdown(
                f'<div class="onb-ev">{theme.badge(elements.STATE_LABEL["approved"], "moderate")} '
                f'{elements.CHANGE_LABEL[p["change"]]} <span class="onb-mono">'
                f'{html.escape(p["cde_id"])}</span> · approved by '
                f'{html.escape(str(p["reviewed_by"]))}</div>'
                + _job_line(p), unsafe_allow_html=True)

# --- Recently decided ------------------------------------------------------------------------
done = state[state["state"].isin(("applied", "rejected"))].head(8) if len(state) else state
if len(done):
    with st.container(key="onbcard_el_done"):
        ui.head("Recently decided")
        st.markdown(ui.items([
            f'{theme.badge(elements.STATE_LABEL[r["state"]], "success" if r["state"] == "applied" else "neutral")} '
            f'{elements.CHANGE_LABEL[r["change"]]} <span class="onb-mono">{html.escape(r["cde_id"])}</span>'
            f' · {html.escape(str(r["reviewed_by"]))}'
            + (f' · v{int(r["applied_version"])}' if opt(r["applied_version"]) is not None else "")
            + (f' · “{html.escape(str(r["review_reason"]))}”'
               if r["state"] == "rejected" and opt(r["review_reason"]) else "")
            for _, r in done.iterrows()], limit=8), unsafe_allow_html=True)


# --- The two confirmations -------------------------------------------------------------------
draft = st.session_state.get(DRAFT)
if draft:
    verb = {"register": "Propose registering", "amend": "Propose amending",
            "retire": "Propose retiring"}[draft["change"]]

    def _propose():
        try:
            adapter.propose_element(draft["change"], draft["cde_id"], draft["attrs"],
                                    draft["reason"], draft["based_on"])
        except OnboardingRejected as exc:
            return str(exc)
        st.session_state.pop(DRAFT, None)
        st.session_state[MODE] = None
        st.session_state[PICK] = draft["cde_id"] if draft["change"] != "register" else \
            st.session_state.get(PICK)
        return None

    ui.confirm(
        "el_propose", f"{verb} {draft['cde_id']}?",
        f'Writes one proposal to <span class="onb-mono">config.cde_proposal</span>, signed '
        f'<b>{html.escape(me)}</b>. Nothing on the register changes until a second person '
        'approves it and the onboarding job applies it.'
        + (f'<br>Reason: “{html.escape(draft["reason"])}”' if draft["reason"].strip() else
           '<br><b style="color:#b91c1c">A proposal needs a reason — add one first.</b>'),
        "Propose", _propose)

rev = st.session_state.get(REV)
if rev:
    pid, decision, reason = rev
    hit = state[state["proposal_id"] == pid] if len(state) else state

    def _review():
        try:
            adapter.review_element(pid, decision, reason)
        except OnboardingRejected as exc:
            return str(exc)
        st.session_state.pop(REV, None)
        return None

    noun = {"register": "registering", "amend": "amending", "retire": "retiring"}
    what = (f'{noun[hit.iloc[0]["change"]]} {hit.iloc[0]["cde_id"]}') if len(hit) \
        else "this change"
    ui.confirm(
        "el_review", f"{'Approve' if decision == 'approved' else 'Reject'} {what}?",
        f'Writes one decision to <span class="onb-mono">config.cde_review</span>, signed '
        f'<b>{html.escape(me)}</b>. A decision is final.'
        + (" Once approved, the onboarding job writes it to the register on its next run."
           if decision == "approved" else "")
        + (f'<br>Reason: “{html.escape(reason)}”' if (reason or "").strip() else
           ('<br><b style="color:#b91c1c">A rejection needs a reason — add one first.</b>'
            if decision == "rejected" else "")),
        "Approve" if decision == "approved" else "Reject", _review)

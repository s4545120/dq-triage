"""Review a consistency check — a second person decides a proposed check.

Built 2026-10-13 from the mockup (screen 4). A drill-down of the Consistency page; the
proposal is `_cs_proposal` in session state.

**The test is run again when the page opens**, on current records, so the decision is
made on today's data rather than the proposer's figures; both are shown. On the local
fixture nothing can be tested and the page says so.

**What the job would refuse is shown before anyone approves it**: the same
`consistency_spec.refusal` the onboarding job runs (a copy of onboarding/consistency.py),
so an approval that the job cannot apply is visible here, not only in a job log.

**One decision per proposal, and not by its author** -- unless the deployment waives the
second approver (DQ_ONBOARD_ALLOW_SELF_APPROVAL=1), which marks the reason. Approving
writes one row to config.consistency_review; the rule is written by the job, in shadow.
"""

from __future__ import annotations

import html
import json

import pandas as pd
import streamlit as st

from dq_app.data import adapter, identity
from dq_app.data.adapter import OnboardingRejected
from dq_app.domain import consistency as cs
from dq_app.domain import consistency_spec as spec_mod
from dq_app.ui import components, theme
from dq_app.ui import onboarding_style as ui

HOME = "dq_app/ui/pages/consistency.py"
RULES = "dq_app/ui/pages/rule_registry.py"
STATE_LABEL = {"open": ("Needs review", "info"), "approved": ("Approved · waiting for the job",
                                                               "moderate"),
               "applied": ("In shadow", "success"), "rejected": ("Rejected", "neutral")}

components.page_chrome()

me = identity.current().email
state = adapter.get_consistency_proposal_current()
pid = st.session_state.get("_cs_proposal")
hit = state[state["proposal_id"] == pid] if len(state) and pid else pd.DataFrame()

if st.button("Back to Consistency", icon=":material/arrow_back:", type="tertiary",
             key="_csr_back"):
    st.switch_page(HOME)

if hit.empty:
    st.info("Pick a proposal on the Consistency page.")
    st.stop()

p = hit.iloc[0].to_dict()
spec = cs.spec_of(p)
label, tone = STATE_LABEL[p["state"]]
names = adapter.get_cde_registry_current().set_index("cde_id")["cde_name"].to_dict()

st.markdown(
    f'<div class="dq-page-hd"><div class="t">{html.escape(p["rule_name"])}</div></div>'
    '<div class="dq-cs-panehd"><div class="b">'
    + theme.badge(label, tone)
    + theme.badge(cs.KIND_LABEL[p["kind"]], "neutral")
    + theme.badge(names.get(p["cde_id"], p["cde_id"]), "neutral")
    + theme.badge(theme.SEVERITY_SHORT.get(p["severity"], p["severity"]),
                  theme.SEVERITY_TONE.get(p["severity"], "neutral"))
    + f'<span class="t2">Proposed by {html.escape(str(p["proposed_by"]))} · '
      f'{pd.Timestamp(p["proposed_at"]):%-d %b} · {html.escape(p["rule_id"])}</span>'
    + "</div></div>",
    unsafe_allow_html=True,
)

main, side = st.columns([1.7, 1], gap="large")

# The test, once per proposal per session.
tkey = f"_csr_test_{p['proposal_id']}"
if tkey not in st.session_state:
    try:
        with st.spinner("Testing on current records…"):
            st.session_state[tkey] = {"result": adapter.test_consistency(spec), "error": None}
    except Exception as exc:  # noqa: BLE001 -- said on the page
        st.session_state[tkey] = {"result": None, "error": str(exc).splitlines()[0][:300]}
now = st.session_state[tkey]["result"]

with main:
    st.markdown(
        '<div class="dq-card"><div class="ttl">What it checks</div>'
        + "".join(f'<p class="dq-cs-line">{html.escape(x)}</p>' for x in cs.proposal_words(p))
        + f'<p class="dq-cs-line"><b>Why:</b> {html.escape(str(p["reason"]))}</p></div>',
        unsafe_allow_html=True,
    )

    def _n(v) -> str:
        return "—" if v is None or (isinstance(v, float) and v != v) else f"{int(v):,}"

    def _pct(v) -> str:
        return "—" if v is None or (isinstance(v, float) and v != v) else f"{float(v):.0f}%"

    rows = [("Compared", _n(p["test_compared"]), _n(now and now["compared"])),
            ("Failing", _n(p["test_failing"]), _n(now and now["failing"]))]
    if p["kind"] != "totals":
        rows.append(("Rows that found a match", _pct(p["test_match_pct"]),
                     _pct(now and now["match_pct"])))
    st.markdown(
        '<div class="dq-card"><div class="ttl">Test results</div>'
        '<table class="dq-cs-cmp"><tr><th></th><th>When proposed</th><th>Now</th></tr>'
        + "".join(f"<tr><td>{a}</td><td>{b}</td><td><b>{c}</b></td></tr>" for a, b, c in rows)
        + "</table></div>",
        unsafe_allow_html=True,
    )
    err = st.session_state[tkey]["error"]
    if err:
        st.error(cs.test_error_words(err, spec_mod.tables_of(spec)), icon=":material/error:")
    elif now is None:
        st.caption("Not tested now: the local fixture has no source rows.")
    elif now["fanout"]:
        st.caption(f"{now['fanout']:,} keys match more than one record; each pair is "
                   "compared.")
    if now and now["sample"] is not None and len(now["sample"]):
        with st.expander(f"Failing rows now · up to {cs.SAMPLE_LIMIT}"):
            st.dataframe(now["sample"], hide_index=True, width="stretch")

    # What the job will do with an approval, said before anyone approves.
    reg = adapter.get_rule_registry()
    registered = set(adapter.get_cde_registry_current().query("status != 'retired'")["cde_id"])
    preview = {**p, "reviewed_by": "someone else", "review_reason": ""}
    why_not = spec_mod.refusal(preview, reg.to_dict("records"), registered) \
        if p["state"] in ("open", "approved") else None
    if why_not:
        st.warning(f"The job would not write this rule: {why_not}.", icon=":material/block:")
    with st.expander("Show SQL"):
        st.code("FROM  " + p["join_sql"] + "\nWHERE " + p["rule_expr"]
                + ("" if not isinstance(p["scope_filter"], str) else
                   "\n  AND " + p["scope_filter"]), language="sql", wrap_lines=True)

with side:
    if p["state"] == "open":
        own = str(p["proposed_by"]).lower() == me.lower()
        waived = adapter.self_approval_waived()
        with st.container(key="dq_csr_decide"):
            st.markdown('<div class="dq-csn-sidehd">Decision</div>', unsafe_allow_html=True)
            if own and not waived:
                st.caption("You can’t review your own proposal.")
            else:
                st.radio("Decision", ["approved", "rejected"], index=None, key="_csr_dec",
                         format_func={"approved": "Approve", "rejected": "Reject"}.get,
                         label_visibility="collapsed")
                st.text_area("Reason (needed to reject)", key="_csr_reason", height=90)
                if own:
                    st.caption("Second approver waived on this deployment; your approval "
                               "is marked as such.")
                if st.button("Submit…", type="primary", key="_csr_submit", width="stretch",
                             disabled=st.session_state.get("_csr_dec") is None):
                    ui.ask("cs_review")
    else:
        st.markdown(
            '<div class="dq-card"><div class="ttl">Decision</div>'
            f'<p class="dq-cs-line">{"Approved" if p["decision"] == "approved" else "Rejected"}'
            f' by {html.escape(str(p["reviewed_by"]))}</p>'
            + (f'<p class="dq-cs-line">{html.escape(str(p["review_reason"]))}</p>'
               if isinstance(p.get("review_reason"), str) else "") + "</div>",
            unsafe_allow_html=True,
        )
    steps = [("Proposed", True), ("Reviewed", p["state"] != "open"),
             ("Runs in shadow", p["state"] == "applied"), ("Promoted", False)]
    if p["state"] == "applied":
        cur = adapter.get_rule_registry_current()
        mine = cur[cur["rule_id"] == p["rule_id"]]
        steps[3] = ("Promoted", len(mine) > 0 and mine.iloc[0]["status"] == "active")
    if p["state"] == "rejected":
        steps = steps[:2]
    st.markdown(
        '<div class="dq-card"><div class="ttl">Progress</div>'
        + "".join(f'<div class="dq-csr-ev{" on" if done else ""}"><span></span>{x}</div>'
                  for x, done in steps) + "</div>",
        unsafe_allow_html=True,
    )
    if p["state"] == "applied" and st.button("Open in Rules", key="_csr_rules",
                                             icon=":material/open_in_new:", type="tertiary"):
        st.session_state["_rule_pick"] = p["rule_id"]
        st.session_state.pop("_rule_el", None)
        st.switch_page(RULES)


def _review():
    dec = st.session_state.get("_csr_dec")
    reason = st.session_state.get("_csr_reason")
    try:
        adapter.review_consistency(p["proposal_id"], dec, reason, now)
    except OnboardingRejected as exc:
        return str(exc)
    for k in ("_csr_dec", "_csr_reason"):
        st.session_state.pop(k, None)
    return None


dec = st.session_state.get("_csr_dec")
reason = st.session_state.get("_csr_reason") or ""
ui.confirm(
    "cs_review", f"{'Approve' if dec == 'approved' else 'Reject'} {p['rule_id']}?",
    f'Writes one decision to <span class="onb-mono">config.consistency_review</span>, signed '
    f'<b>{html.escape(me)}</b>. A decision is final.'
    + (" Once approved, the onboarding job writes the rule in shadow on its next run."
       if dec == "approved" else "")
    + (f'<br>Reason: “{html.escape(reason)}”' if reason.strip() else
       ('<br><b style="color:#b91c1c">A rejection needs a reason — add one first.</b>'
        if dec == "rejected" else "")),
    "Approve" if dec == "approved" else "Reject", _review)

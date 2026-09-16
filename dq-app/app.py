"""DQ Triage Agent — entry point.

Local, against the generated fixture (the default — no workspace needed):

    ../.venv/bin/streamlit run app.py

Deployed as a Databricks App, still on the fixture — `app.yaml` keeps
DQ_APP_DATA_SOURCE=local and the app carries its own copy of the dataset at
dq_app/fixture_data/, because only this directory ships. No catalog, no warehouse:

    databricks sync . /Workspace/Users/<you>/dq-app-src
    databricks apps deploy dq-triage --source-code-path /Workspace/Users/<you>/dq-app-src

Workspace mode exists and is wired, but has never been run. See README.md, Deploy.

Built to `dq-triage-agent-spec.md` v1.0. The retired v0.1 execution spec is gone from
this app along with everything it implied: no executor, no mutable incident state, no
fix body, no execute button.

**Four destinations, six pages.** The nav lists what someone can decide to look at;
`Monitor detail` and `Problem detail` are not on that list because neither means
anything without a selection made on the page above it. They are still registered —
Streamlit can only `switch_page` to a page it knows about — so the sidebar is built by
hand from `st.page_link` and `st.navigation` is asked to render nothing. Adding a page
to `PAGES` therefore does not put it in the sidebar; `SIDEBAR` does.

The `Data elements` page was removed on 2026-09-16. The CDE model behind it was not:
`v_cde_coverage` still owns the scorecard's denominator. What went is the browsing
surface, replaced by the scope panel and the issue board on the scorecard.

The `Register` page was removed on 2026-09-17. The register itself is untouched —
`results.disposition` is still the append-only audit artefact, still the app's primary
write, and every event chain is still readable on the problem it belongs to, under
Decisions on the detail page. What went is the cross-cohort browsing view. One thing
went with it and has not landed anywhere else: `domain/integrity.check`, the control
test over the whole register, no longer has a surface. It still runs and
`tests/test_integrity.py` still pins it.
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(
    page_title="DQ Triage",
    page_icon=":material/rule:",
    layout="wide",
    initial_sidebar_state="expanded",
)

PAGES = {
    "scorecard": st.Page("dq_app/ui/pages/scorecard.py", title="Scorecard",
                         icon=":material/monitoring:", default=True),
    "tables": st.Page("dq_app/ui/pages/tables.py", title="Tables",
                      icon=":material/table_chart:"),
    "triage": st.Page("dq_app/ui/pages/triage.py", title="Triage",
                      icon=":material/inbox:"),
    "rules": st.Page("dq_app/ui/pages/rule_registry.py", title="Rules",
                     icon=":material/rule:"),
    # Drill-downs. Registered so `st.switch_page` can reach them, deliberately absent
    # from SIDEBAR below — each is opened from the page above it, never from a click
    # in the nav, and opening one cold shows an empty selector.
    "table_detail": st.Page("dq_app/ui/pages/table_detail.py", title="Monitor detail",
                            icon=":material/frame_inspect:"),
    "triage_detail": st.Page("dq_app/ui/pages/triage_detail.py", title="Problem detail",
                             icon=":material/frame_inspect:"),
}

# Group → the pages linked under it. The only list that decides what the sidebar shows.
SIDEBAR = {
    # `Rules` sits under Monitor because the group it used to share — Evidence — held
    # the Register, and with that page gone a group label reading "Evidence" over a
    # single rule-authoring link described nothing. What a rule IS is part of what is
    # being watched, which is what Monitor already means here.
    "Monitor": ["scorecard", "tables", "rules"],
    "Work": ["triage"],
}


def _sidebar_nav() -> None:
    """The nav, by hand, because `st.navigation` renders all-or-nothing."""
    st.sidebar.markdown(
        '<div class="dq-brand"><span class="sq">DQ</span>'
        "<span class='nm'>Triage</span></div>",
        unsafe_allow_html=True,
    )
    for group, keys in SIDEBAR.items():
        st.sidebar.markdown(f'<div class="dq-navgrp">{group}</div>',
                            unsafe_allow_html=True)
        for key in keys:
            st.sidebar.page_link(PAGES[key])


nav = st.navigation(list(PAGES.values()), position="hidden")

# The brand and links are written before the page runs, so `components.page_chrome`
# appends the source badge and identity below them rather than above.
_sidebar_nav()

nav.run()

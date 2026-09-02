"""DQ Triage Agent — entry point.

Local, against the generated fixture (the default — no workspace needed):

    ../.venv/bin/streamlit run app.py

Against a real workspace:

    databricks auth login --configure-serverless --host <workspace-url>
    DQ_APP_DATA_SOURCE=databricks ../.venv/bin/streamlit run app.py

Built to `dq-triage-agent-spec.md` v1.0. The retired v0.1 execution spec is gone from
this app along with everything it implied: no executor, no mutable incident state, no
fix body, no execute button.
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
    "queue": st.Page("dq_app/ui/pages/cohort_queue.py", title="Cohorts",
                     icon=":material/inbox:"),
    "detail": st.Page("dq_app/ui/pages/cohort_detail.py", title="Detail",
                      icon=":material/frame_inspect:"),
    "register": st.Page("dq_app/ui/pages/register.py", title="Register",
                        icon=":material/receipt_long:"),
    "registry": st.Page("dq_app/ui/pages/rule_registry.py", title="Rules",
                        icon=":material/rule:"),
}

nav = st.navigation(
    {
        "Monitor": [PAGES["scorecard"]],
        "Triage": [PAGES["queue"], PAGES["detail"]],
        "Evidence": [PAGES["register"], PAGES["registry"]],
    }
)

nav.run()

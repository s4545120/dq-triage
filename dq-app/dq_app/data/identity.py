"""Who is acting, and where that came from.

The spec's two-identity model is the reason the register is evidence at all:

  * **Reviewer / approver identity** arrives from the platform in the
    `x-forwarded-access-token` / `x-forwarded-email` headers of the signed-in
    user's request. It is never typed into a form. A free-text "approved by" field
    would make the two-approver control worthless, since anyone could enter anyone.
  * **The app's service principal** performs the write, and holds `MODIFY` on
    exactly two tables and nothing on `prod.*`.

Locally there are no headers, so there is a stand-in — and every event it authors
is stamped `actor_source = 'local_standin'` rather than `'obo_user'`. That string is
chosen to be un-insertable. Two independent things reject it:

  * `disposition_actor_source_enum` in `sql/ddl/06_results_disposition.sql` permits
    only `obo_user | service_principal | triage_job | check_runner`, so the row
    cannot reach the table at all; and
  * `disposition_human_events_have_identity` requires `actor_source = 'obo_user'`
    on every `reviewed` / `approved` / `executed` row, so even a renamed value
    would fail.

and if one ever did land, `v_disposition_integrity`'s third clause reports it as a
control failure. A demo identity therefore cannot be mistaken for a real one — not
by convention, but because the schema refuses it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import streamlit as st

# Local personas, matching the identities already in the fixture register so a
# demo can continue an existing chain rather than starting a disconnected one.
LOCAL_PERSONAS = {
    "m.okonkwo@example.com": "M. Okonkwo",
    "p.nguyen@example.com": "P. Nguyen",
    "s.whitfield@example.com": "S. Whitfield",
    "r.delacroix@example.com": "R. Delacroix",
}


@dataclass(frozen=True)
class Identity:
    email: str
    display_name: str
    source: str  # 'obo_user' when the platform vouched for it; 'local_standin' otherwise

    @property
    def is_platform(self) -> bool:
        return self.source == "obo_user"


def _from_headers() -> Identity | None:
    """Read the forwarded identity Databricks Apps puts on every request."""
    try:
        headers = st.context.headers or {}
    except Exception:  # pragma: no cover — st.context is not available in every runtime
        return None
    email = headers.get("X-Forwarded-Email") or headers.get("x-forwarded-email")
    if not email:
        return None
    name = (
        headers.get("X-Forwarded-Preferred-Username")
        or headers.get("x-forwarded-preferred-username")
        or email.split("@")[0]
    )
    return Identity(email=email, display_name=name, source="obo_user")


def current() -> Identity:
    """The acting identity for this request."""
    from_platform = _from_headers()
    if from_platform:
        return from_platform

    picked = st.session_state.get("_local_identity") or os.getenv(
        "DQ_LOCAL_IDENTITY", "m.okonkwo@example.com"
    )
    return Identity(
        email=picked,
        display_name=LOCAL_PERSONAS.get(picked, picked.split("@")[0]),
        source="local_standin",
    )

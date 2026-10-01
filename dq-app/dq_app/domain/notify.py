"""What a confirmed-defect notification says, and who it goes to. Pure logic.

No I/O, no Streamlit, no SDK. This module decides *whether* an event warrants a
notification and *what the message reads like*; `dq_app/data/notify.py` is the only
thing that sends anything.

## Why the trigger is an event and not a threshold

A threshold crossing is a claim the check runner makes. It is surfaced in the app so
a person can look at it, and that is all it does — nothing is sent on a number
moving. What is sent is a *decision*: `reviewed` with `decision = 'accepted'`, which
is a named human saying the problem is real. The notification is therefore derived
from a row that already exists in the append-only register, which is what lets it
carry its own provenance: who confirmed it, when, and the reason they typed.

Three conditions, all required, and each one closes a different hole:

  * `event_type == 'reviewed'` and `decision == 'accepted'` — the trigger proper.
    A rejection, a deferral or a `no_action` is also a `reviewed` row, and sending
    on event type alone would mail a data owner about a problem a steward had just
    dismissed.
  * `actor_source == 'obo_user'` — the platform vouched for the identity. A
    `local_standin` event cannot reach the table at all (see `data/identity.py`),
    but a send is an outbound side effect and should not rely on a constraint in a
    table it is not reading to be safe.

The write being durable is the fourth condition and it is not checked here, because
it is not a property of the event — see `data/notify.py`.

## The title is not derived here

`ui/components.problem_title` is the one definition of what a problem is called, and
a second one in this module would let the same cohort carry two names — the page
saying one thing and the email another. So the title arrives as an argument from the
caller that already rendered it. When none is supplied the subject falls back to the
cohort id, which is ugly and unambiguous; an unlovely subject line beats a silent
failure to notify.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

# Duplicated from `ui/theme.SEVERITY_WORD` on purpose, for the reason
# `domain/metrics._SHORT` gives: the domain does not import the UI, and a label that
# travels in a message has to travel with the message. `P1_block` is a database
# value, not a phrase anyone reads in an inbox.
SEVERITY_WORD = {"P1_block": "P1 Critical", "P2_alert": "P2 High", "P3_monitor": "P3 Monitor"}

TRIGGER_EVENT = "reviewed"
TRIGGER_DECISION = "accepted"
PLATFORM_ACTOR = "obo_user"

# Every route spec falls back to this key when the cohort's owner_group has no entry
# of its own. A spec with no catch-all and no matching group sends to nobody, which
# `compose` reports by returning None rather than by raising.
DEFAULT_ROUTE = "*"


@dataclass(frozen=True)
class Message:
    """A composed notification. Inert — holding one has sent nothing."""

    subject: str
    body_text: str
    body_html: str
    recipients: tuple[str, ...]
    cohort_id: str
    disposition_id: str


def should_notify(event: Mapping) -> bool:
    """Does this register event warrant a notification?

    Deliberately total: any mapping can be passed, and anything that is not an
    accepted review by a platform-vouched human is False.
    """
    return (
        event.get("event_type") == TRIGGER_EVENT
        and event.get("decision") == TRIGGER_DECISION
        and event.get("actor_source") == PLATFORM_ACTOR
    )


def parse_routes(spec: str | None) -> dict[str, tuple[str, ...]]:
    """Parse `DQ_NOTIFY_TO` into owner_group -> recipients.

    The format is one route per semicolon, `group: a@x, b@x`, with `*` as the
    catch-all:

        "*: dq-stewards@example.com; Customer Data: crm-owners@example.com"

    A bare list with no group is read as the catch-all, so the common case of
    "send everything to one address" is just `DQ_NOTIFY_TO=dq@example.com`.
    """
    routes: dict[str, tuple[str, ...]] = {}
    for clause in (spec or "").split(";"):
        clause = clause.strip()
        if not clause:
            continue
        group, sep, addresses = clause.partition(":")
        if not sep:
            group, addresses = DEFAULT_ROUTE, clause
        people = tuple(a.strip() for a in addresses.split(",") if a.strip())
        if people:
            routes[group.strip() or DEFAULT_ROUTE] = people
    return routes


def recipients_for(owner_group, routes: Mapping[str, tuple[str, ...]]) -> tuple[str, ...]:
    """The addresses for a cohort's owning domain, or the catch-all, or nothing."""
    if owner_group and owner_group in routes:
        return routes[owner_group]
    return routes.get(DEFAULT_ROUTE, ())


def _tables(cohort: Mapping) -> str:
    raw = cohort.get("affected_tables")
    if raw is None:
        return "—"
    try:
        return ", ".join(str(t) for t in raw) or "—"
    except TypeError:
        return str(raw)


def _int(value, default: str = "—") -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return default


def _when(event: Mapping) -> str:
    ts = event.get("event_ts")
    try:
        return ts.strftime("%Y-%m-%d %H:%M")
    except AttributeError:
        return str(ts or "—")


def compose(
    event: Mapping,
    cohort: Mapping,
    *,
    title: str | None = None,
    routes: Mapping[str, tuple[str, ...]] | None = None,
    app_url: str | None = None,
) -> Message | None:
    """The message for one accepted review, or None if there is nothing to send.

    None rather than an exception in both of the cases that can legitimately occur —
    an event that is not a trigger, and a cohort whose owner group routes nowhere.
    Neither is an error: not every review is an acceptance, and an unrouted domain
    is a configuration the operator chose.
    """
    if not should_notify(event):
        return None

    people = recipients_for(cohort.get("owner_group"), routes or {})
    if not people:
        return None

    cohort_id = str(event.get("cohort_id", ""))
    headline = title or f"Cohort {cohort_id[:8]}"
    severity = SEVERITY_WORD.get(cohort.get("severity"), str(cohort.get("severity") or "—"))
    reason = (event.get("reason") or "").strip()
    actor = event.get("actor_display_name") or event.get("actor_identity") or "—"
    link = f"{app_url.rstrip('/')}/triage_detail?cohort={cohort_id}" if app_url else None

    facts = [
        ("Severity", severity),
        ("Checks failing", _int(cohort.get("member_count"))),
        ("Violation rows", _int(cohort.get("total_violation_rows"))),
        ("Tables", _tables(cohort)),
        ("Owner group", str(cohort.get("owner_group") or "—")),
        ("Validated by", str(actor)),
        ("When", _when(event)),
    ]

    # The provenance line is not decoration. It names the exact row this message was
    # generated from, so a recipient — or an auditor — can go and read it.
    provenance = (
        f"results.disposition · cohort {cohort_id} · "
        f"event_seq {event.get('event_seq', '—')} · reviewed/accepted"
    )
    standing = (
        "Generated from an append-only audit record. The DQ Triage app does not "
        "modify business data and has not acted on this problem."
    )

    width = max(len(k) for k, _ in facts)
    lines = [
        headline,
        "",
        "A steward has confirmed this is a real data defect.",
        "",
        *(f"  {k.ljust(width)}   {v}" for k, v in facts),
    ]
    if reason:
        lines += ["", f'  Reason  "{reason}"']
    if link:
        lines += ["", f"Open in DQ Triage: {link}"]
    lines += ["", provenance, standing]

    rows = "".join(
        f'<tr><td style="padding:2px 14px 2px 0;color:#4a4a63;">{_esc(k)}</td>'
        f'<td style="padding:2px 0;color:#14142b;">{_esc(v)}</td></tr>'
        for k, v in facts
    )
    quoted = (
        f'<p style="margin:12px 0;padding:9px 11px;background:#eef0ff;border-radius:8px;'
        f'color:#14142b;">&ldquo;{_esc(reason)}&rdquo;</p>' if reason else ""
    )
    opener = (
        f'<p style="margin:12px 0;"><a href="{_esc(link)}" style="color:#4f46e5;">'
        f"Open in DQ Triage</a></p>" if link else ""
    )
    body_html = (
        '<div style="font-family:-apple-system,Segoe UI,sans-serif;color:#14142b;">'
        f'<h2 style="font-size:17px;font-weight:600;margin:0 0 4px;">{_esc(headline)}</h2>'
        '<p style="margin:0 0 12px;color:#4a4a63;">A steward has confirmed this is a '
        "real data defect.</p>"
        f'<table style="font-size:14px;border-collapse:collapse;">{rows}</table>'
        f"{quoted}{opener}"
        f'<p style="font-size:12px;color:#9695ad;margin-top:16px;border-top:1px solid '
        f'#e5e5ee;padding-top:8px;">{_esc(provenance)}<br>{_esc(standing)}</p></div>'
    )

    return Message(
        subject=f"[DQ {severity.split()[0]}] {headline}",
        body_text="\n".join(lines),
        body_html=body_html,
        recipients=people,
        cohort_id=cohort_id,
        disposition_id=str(event.get("disposition_id", "")),
    )


def _esc(value) -> str:
    """Minimal HTML escape. The reason field is free text a steward typed."""
    return (
        str(value if value is not None else "")
        .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        .replace('"', "&quot;")
    )

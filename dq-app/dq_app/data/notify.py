"""The only thing in this app that sends anything outward. Off by default.

`domain/notify.py` decides what a message says; this decides whether it leaves the
container, and by what route.

## Nothing is sent that is not already in the register

The register write and the send are two operations and cannot be made one. Both
orderings fail, and they fail differently:

  * write, then send: the insert lands and the send throws — the register records a
    decision nobody was told about. Recoverable, and visible, because the row is
    there to be read.
  * send, then write: the mail goes out and the insert is refused — a data owner has
    been told about a decision that does not exist. Not recoverable: the message is
    gone and nothing anywhere records that it went.

So the order is fixed, and the guard is stronger than "the insert did not raise":
`dispatch` refuses unless the caller passes `confirmed=True`, which `adapter` sets
only after reading the row back out of the table by its `disposition_id`. A send is
therefore always derived from a row that was observed in the register, never from
one the app believes it wrote.

The residual failure — written but not sent — is the one worth having. It is silent
to the recipient, but a scheduled query over `results.disposition` finds it, which
is exactly the SQL-alert design this was the immediate-delivery alternative to. The
two are complements, not rivals: run the alert as the backstop on a wide window and
this for the immediate path.

## Transports

    DQ_NOTIFY=off    (default) compose nothing, send nothing. Local and fixture
                     modes stay here, so no test and no demo can emit a message.
    DQ_NOTIFY=log    compose and write the message to the app log. The way to see
                     what would be sent, against a real workspace, sending nothing.
    DQ_NOTIFY=job    compose and trigger the Lakeflow job named by DQ_NOTIFY_JOB_ID,
                     passing the composed message as job parameters.

`job` rather than SMTP from this container, for one reason: credentials. The app's
service principal needs `CAN_RUN` on that job and nothing else — no SMTP password,
no provider API key, and no secret resource on the app at all. The mail credential
lives with the job, which is the only thing that uses it. `databricks-sdk` is
already a dependency, so this adds none.

Nothing here raises. A transport failure is logged and swallowed, because by the
time it can happen the register write has already succeeded and the steward's
decision is recorded; failing the page at that point would tell them their write
did not land, which is false.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping

from dq_app.domain import notify as compose_mod

log = logging.getLogger("dq_app.notify")
# Nothing configures logging in the app, so the root logger sits at WARNING and
# DQ_NOTIFY=log's `log.info` would be dropped — the one mode meant to show what goes
# out would show nothing. Its own handler, to stderr, which Databricks Apps captures.
if not log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    log.addHandler(_handler)
    log.setLevel(logging.INFO)
    log.propagate = False

OFF, LOG, JOB = "off", "log", "job"


def transport() -> str:
    return os.getenv("DQ_NOTIFY", OFF).strip().lower() or OFF


def enabled() -> bool:
    return transport() in (LOG, JOB)


def routes() -> dict[str, tuple[str, ...]]:
    return compose_mod.parse_routes(os.getenv("DQ_NOTIFY_TO"))


def app_url() -> str | None:
    return (os.getenv("DQ_APP_URL") or "").strip() or None


def recipients_preview(cohort: Mapping | None) -> tuple[str, ...]:
    """Who an acceptance of this cohort would reach, for the page to say so.

    The decision form is the only place a person can cause a message to be sent, so
    it is the only place that has to admit it. Empty when the transport is off — the
    page then says nothing rather than explaining a feature nobody enabled.

    This asks the same two questions `dispatch` does, in the same order, and that
    duplication is the point: a preview derived some other way could disagree with
    what actually goes out, and a page that promises the wrong recipient is worse
    than a page that promises nothing.
    """
    if not enabled() or cohort is None:
        return ()
    return compose_mod.recipients_for(cohort.get("owner_group"), routes())


def dispatch(
    event: Mapping,
    cohort: Mapping | None,
    *,
    title: str | None = None,
    confirmed: bool = False,
) -> str:
    """Compose and send, if every condition holds. Returns why, in one word.

    The return value is for the log and for tests — no caller branches on it, and
    none should: a notification that did not go out must never change what the page
    tells the steward about their write.

    Outcomes: `off`, `unconfirmed`, `no_cohort`, `no_trigger`, `unrouted`, `sent`,
    `failed`.
    """
    mode = transport()
    if mode == OFF:
        return OFF
    if not confirmed:
        # Either the write is session-only (local mode), or the read-back did not
        # find the row. Both mean: there is no register entry to derive a message
        # from, so there is no message.
        return "unconfirmed"
    if cohort is None:
        return "no_cohort"

    message = compose_mod.compose(
        event, cohort, title=title, routes=routes(), app_url=app_url()
    )
    if message is None:
        return "no_trigger" if not compose_mod.should_notify(event) else "unrouted"

    try:
        if mode == LOG:
            log.info(
                "DQ_NOTIFY=log would send to %s: %s\n%s",
                ", ".join(message.recipients), message.subject, message.body_text,
            )
        else:
            _run_job(message)
    except Exception:  # noqa: BLE001 — see the module docstring: never raise here.
        log.exception("notification failed for disposition %s", message.disposition_id)
        return "failed"
    return "sent"


def _run_job(message) -> None:
    """Hand the composed message to the Lakeflow job that owns the mail credential.

    `run_now` returns as soon as the run is queued; this does not wait for it. A job
    that fails to send is visible in its own run history and in whatever failure
    notification the job itself carries — this app is not the place to watch it.
    """
    job_id = (os.getenv("DQ_NOTIFY_JOB_ID") or "").strip()
    if not job_id:
        raise RuntimeError("DQ_NOTIFY=job requires DQ_NOTIFY_JOB_ID")

    from databricks.sdk import WorkspaceClient

    WorkspaceClient().jobs.run_now(
        job_id=int(job_id),
        notebook_params={
            "recipients": ",".join(message.recipients),
            "subject": message.subject,
            "body_text": message.body_text,
            "body_html": message.body_html,
            "cohort_id": message.cohort_id,
            "disposition_id": message.disposition_id,
        },
    )

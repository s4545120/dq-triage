"""Palette, status vocabulary, icon set and the CSS the app injects.

Three rules hold throughout:

  * **No emoji.** Icons are inline SVG on a 24-unit grid, stroked in `currentColor`,
    so they inherit the colour and size of the text they sit in and render the same
    on every platform. Emoji do neither, and they read as decoration in a tool whose
    output is audit evidence.
  * **Colour never carries meaning alone.** Every status renders as a dot or a tinted
    badge *with its word next to it*. The word is the channel that survives greyscale,
    colour blindness and a screenshot pasted into a ticket.
  * **Semantic colour is reserved.** Red, amber and green mean severity and outcome
    and nothing else. Charts draw from a separate categorical ramp, so no decorative
    series can be mistaken for a status.
"""

from __future__ import annotations

import html
import math

import streamlit as st

# --- Colour -----------------------------------------------------------------
# "Indigo signal": an indigo accent on a faintly violet neutral scale. This replaced
# a petrol-teal palette that was chosen to look unlike the well-known DQ suites; the
# brightness was asked for and the resemblance accepted with it.
#
# One change here is not cosmetic. `moderate` used to be amber (#a15c07 on #fefbe8),
# the weakest pairing in the old set and never comfortably readable on a light ground.
# It is now a cool teal, which clears contrast and reads as informational — which is
# what P3_monitor means. SEVERITY_TONE below is untouched, so the mapping
# P3_monitor -> moderate still holds; only what "moderate" looks like has changed.

NEUTRAL = {
    "canvas": "#f7f7fa",
    "surface": "#ffffff",
    "border": "#e5e5ee",
    "border_strong": "#d2d2e0",
    "text": "#14142b",
    "text_2": "#4a4a63",
    "text_3": "#9695ad",
}

ACCENT = "#4f46e5"
ACCENT_TINT = "#eef0ff"

# Reserved. Never reused as a chart series colour.
TONE = {
    "critical": {"fg": "#dc2626", "bg": "#fef2f2", "bd": "#fecaca"},
    "high":     {"fg": "#ea580c", "bg": "#fff7ed", "bd": "#fed7aa"},
    "moderate": {"fg": "#0e7490", "bg": "#ecfeff", "bd": "#a5e8f0"},
    "success":  {"fg": "#16a34a", "bg": "#f0fdf4", "bd": "#bbf7d0"},
    "info":     {"fg": ACCENT,    "bg": ACCENT_TINT, "bd": "#c3c6fb"},
    "neutral":  {"fg": "#4a4a63", "bg": "#f1f1f6", "bd": "#e5e5ee"},
}

# Categorical slots for charts — fixed order, never cycled, never a ninth.
SERIES = [
    "#4f46e5", "#ea580c", "#0e7490", "#ca8a04",
    "#9333ea", "#16a34a", "#dc2626", "#4a4a63",
]

SEVERITY_TONE = {"P1_block": "critical", "P2_alert": "high", "P3_monitor": "moderate"}
SEVERITY_SHORT = {"P1_block": "P1", "P2_alert": "P2", "P3_monitor": "P3"}
# "P1_block" is a database value, not a word anyone says out loud. Every place a
# severity is shown to a person, it is shown with its meaning attached.
SEVERITY_WORD = {"P1_block": "Critical", "P2_alert": "High", "P3_monitor": "Monitor"}
SEVERITY_ORDER = ["P1_block", "P2_alert", "P3_monitor"]

# --- Dimensions -------------------------------------------------------------
# `DIMENSION_OF` is the only place a rule type is assigned to a dimension. The prose
# below describes the dimensions; `dimension_for` is the only reader of the map.

DIMENSION_OF = {
    "not_null": "Completeness",
    "format": "Validity",
    "sentinel": "Validity",
    "variance": "Validity",
    "consistency": "Consistency",
    "referential": "Consistency",
    "uniqueness": "Uniqueness",
}


def dimension_for(rule_type: str) -> str:
    """Map local rule types to the DQ dimensions used in monitoring tools."""
    return DIMENSION_OF.get(rule_type, "Other")


# The prose outlived two homes — four cards, then a grouping toggle. "Validity" is a
# term of art, not a word a steward uses about their own data, so it is still defined
# wherever it is printed: the short line in a check row's tooltip, the long one beside
# the dimension badge in the check drawer.

DIMENSIONS = {
    "Completeness": {
        "short": "Is the value there at all.",
        "long": (
            "Whether a value a record is supposed to carry is actually there. A "
            "completeness check counts the rows where the column is null, blank, or "
            "holds a placeholder standing in for a value nobody ever supplied. It "
            "says nothing about whether the value that is there is any good — that "
            "is Validity's job."
        ),
    },
    "Validity": {
        "short": "Does the value look like what it claims to be.",
        "long": (
            "Whether a value that is present conforms to the shape it is supposed to "
            "have: an email with an @ and a real top-level domain, a mobile number "
            "matching 04########, a date of birth that parses and puts the person "
            "between 18 and 105. Placeholder values that pass a presence check but "
            "mean nothing — 0400000000, a row of nines — are caught here too. A "
            "valid value can still be the wrong value; no automated check can tell."
        ),
    },
    "Consistency": {
        "short": "Does it agree with the other columns and tables.",
        "long": (
            "Whether a value agrees with the rest of the record and the rest of the "
            "estate. Two columns that have to move together — a document number "
            "present whenever a document type is set — and two tables that have to "
            "tell the same story about the same person. Each side can be perfectly "
            "complete and perfectly valid and still disagree, which is why this is a "
            "dimension of its own."
        ),
    },
    "Uniqueness": {
        "short": "Is it there exactly once.",
        "long": (
            "Whether a value that is supposed to identify one thing identifies "
            "exactly one. A mobile service number live on two subscriptions at once "
            "is not a wrong value in either row — both rows are individually fine, "
            "and the defect only exists in the pair."
        ),
    },
}


# --- Critical data elements -------------------------------------------------
# Criticality is a property of the ELEMENT and severity is a property of the RULE.
# They are deliberately different scales with different colours, because they answer
# different questions: how much does this data matter, versus how loudly does this
# check complain. Criticality never adjusts a severity — check_run.severity is
# copied verbatim from the rule registry and nothing downstream touches it.
CRITICALITY_ORDER = ["critical", "high", "medium", "low"]
CRITICALITY_TONE = {"critical": "critical", "high": "high",
                    "medium": "moderate", "low": "neutral"}

COVERAGE_GAP_ORDER = ["no_rule", "scope_mismatch", "unvalidated", "covered"]
COVERAGE_GAP_LABEL = {
    "no_rule": "No rule",
    "scope_mismatch": "Scope mismatch",
    "unvalidated": "Not validated",
    "covered": "Covered",
}
COVERAGE_GAP_TONE = {
    "no_rule": "critical",
    "scope_mismatch": "high",
    "unvalidated": "moderate",
    "covered": "success",
}
COVERAGE_GAP_MEANING = {
    "no_rule": "Registered as critical and nothing checks it. The register knows this "
               "column matters; the rule set does not.",
    "scope_mismatch": "A rule here contradicts the binding. The register says this "
                      "column is only populated for some rows and the rule measures "
                      "all of them, so it reports legitimate gaps as defects. The "
                      "rule is wrong, not the data.",
    "unvalidated": "Something watches it, but nothing checks what it contains — only "
                   "that a value is present, or that it agrees with another column. "
                   "No format, uniqueness or referential rule.",
    "covered": "At least one rule examines the values themselves. Not a claim that "
               "the rules are good, only that something is looking.",
}

# The element's KIND, as `config.cde_registry.data_class` records it. It is what the
# element IS — an email address, a date of birth — and it is the one CDE attribute
# that groups elements across tables and domains: three bindings of a person name on
# two tables are one kind of thing to watch. Criticality says how much it matters and
# is a different axis entirely; neither is a severity.
#
# The labels exist because `national_id` is the register's word and "Identity
# document" is the steward's. Anything the register grows later falls through
# `data_class_label` and is title-cased rather than dropped.
DATA_CLASS_LABEL = {
    "email_address": "Email address",
    "person_name": "Person name",
    "date_of_birth": "Date of birth",
    "phone_number": "Phone number",
    "msisdn": "Mobile service number",
    "national_id": "Identity document",
    "device_id": "Device identifier",
    "account_id": "Account identifier",
    "other": "Other",
}


def data_class_label(data_class) -> str:
    """The element kind as a person would say it."""
    key = str(data_class or "").strip()
    return DATA_CLASS_LABEL.get(key, key.replace("_", " ").capitalize() or "\u2014")


CDE_ONE_LINER = (
    "A critical data element is a field the business has registered as mattering — "
    "date of birth, name, email, identity document — named before any rule was "
    "written against it, so coverage has a denominator that does not move when the "
    "rule set does."
)

STATE_TONE = {
    "awaiting_triage": "neutral",
    "awaiting_review": "high",
    "awaiting_approval": "moderate",
    "approved_awaiting_execution": "info",
    "awaiting_verification": "neutral",
    "deferred": "neutral",
    "reopened": "critical",
    "closed_verified": "success",
    "closed_rejected": "neutral",
    "closed_no_action": "neutral",
}

STATE_LABEL = {
    "awaiting_triage": "Awaiting triage",
    "awaiting_review": "Awaiting review",
    "awaiting_approval": "Awaiting approval",
    "approved_awaiting_execution": "Approved",
    "awaiting_verification": "Awaiting verification",
    "deferred": "Deferred",
    "reopened": "Reopened",
    "closed_verified": "Closed — verified",
    "closed_rejected": "Closed — rejected",
    "closed_no_action": "Closed — no action",
}

# Whose turn it is. Shown as a tooltip, not as a paragraph under every row.
STATE_MEANING = {
    "awaiting_triage": "Raised with no recommendation — the triage job did not finish",
    "awaiting_review": "Waiting on a steward to accept, defer or reject",
    "awaiting_approval": "Accepted; waiting on approval",
    "approved_awaiting_execution": "Approved; waiting on the data owner to act and report back",
    "awaiting_verification": "Action reported; the next scheduled run decides",
    "deferred": "Parked with a reason; returns on its review-by date",
    "reopened": "Verification failed — the fix did not hold",
    "closed_verified": "The next run passed for every member rule",
    "closed_rejected": "Rejected, reason recorded",
    "closed_no_action": "Closed with no action, reason recorded",
}

# --- Explaining the model ---------------------------------------------------
# "Cohort" is this system's one invented word, and nothing else in the UI makes sense
# without it. The same sentence appears wherever cohorts first appear on a page —
# written once here so it cannot drift into three slightly different explanations.

COHORT_ONE_LINER = (
    "A cohort is one problem to solve: related breaches grouped under a single "
    "root-cause hypothesis, with one recommended fix and one recorded decision."
)

COHORT_EXPLAINER = """
**Why they exist.** One upstream change can breach thirty rules across twelve tables.
As alerts that is thirty things to look at; as a cohort it is one thing to fix. The
queue length then reflects the number of *problems*, not the number of rules.

**What a cohort carries.** The breaches that belong to it, a root-cause hypothesis
with the profiling behind it, the blast radius from lineage, a severity, an owning
domain, and a recommended approach — drawn from the playbook where one matches, or
drafted and labelled as generated where none does.

**What you do with one.** Accept, defer or reject it with a reason; approve it
(P1 needs two distinct named approvers); report what was actually done. The next
scheduled check run then verifies whether it worked, and reopens the cohort if not.

**What a cohort is not.** It is not a ticket and it is not a fix. Nothing in this app
modifies data or triggers a job — the remediation happens in the data owner's own
pipeline, and the cohort is the record of what was decided and whether it held.
"""

# Where the fix belongs. The model answers `data`, `rule` or `neither`; these are the
# same three answers in the steward's words, and they are deliberately sentences
# rather than nouns — "rule" alone reads as a category, "the rule is wrong" reads as
# the claim it actually is.
#
# `neither` is not a hedge and must not be labelled as one. The data can be correct
# and the rule reasonable, with the disagreement between them being a business
# question: a plausibility rule firing on customers recorded as under 18 is the
# worked example. Forcing that into data-or-rule makes the model assert a defect it
# does not believe in.
DEFECT_LABEL = {
    "data": "The data is wrong",
    "rule": "The rule is wrong",
    "neither": "Neither — a business question",
}
DEFECT_TONE = {"data": "high", "rule": "info", "neither": "neutral"}
# The same three answers, shortened to the half of a problem's title that says what
# kind of wrong it is — `components.problem_title`. Lower case: it follows a dash.
DEFECT_VERDICT = {
    "data": "wrong data",
    "rule": "rule flags valid rows",
    "neither": "needs a business call",
}

DEFECT_MEANING = {
    "data": "The rule is right and the rows are wrong. The remedy is a correction, "
            "and it belongs as far upstream as the defect reaches.",
    "rule": "The rows are right and the rule that judged them is wrong. The remedy "
            "is a new rule version — correcting this data would make correct "
            "records wrong.",
    "neither": "The data may be correct and the rule reasonable, and the "
               "disagreement between them is a business question rather than a "
               "defect on either side. Answer the question before changing anything.",
}


# What a threshold suggestion rests on, in the steward's words. `unchanged` is the
# common case and is labelled as a verdict rather than as an absence: the model
# was asked and said keep it, with a reason, which is not the same as not asking.
THRESHOLD_BASIS_LABEL = {
    "element_tolerance": "Element tolerance",
    "run_history": "Run history",
    "both": "Tolerance and history",
    "unchanged": "Keep as is",
}
THRESHOLD_BASIS_TONE = {
    "element_tolerance": "info",
    "run_history": "info",
    "both": "info",
    "unchanged": "neutral",
}
# Where a proposal has got to -- v_threshold_proposal_current.review_state, in the
# reviewer's words. `no_change` is advice that asked for nothing; `in_force` means
# the registry already carries the figure, by adoption or by hand.
THRESHOLD_STATE_LABEL = {
    "open": "Awaiting review",
    "deferred": "Deferred",
    "adopted": "Adopted",
    "rejected": "Rejected",
    "in_force": "In force",
    "no_change": "Keep as is",
}
THRESHOLD_STATE_TONE = {
    "open": "high",
    "deferred": "neutral",
    "adopted": "success",
    "rejected": "neutral",
    "in_force": "info",
    "no_change": "neutral",
}
THRESHOLD_BASIS_MEANING = {
    "element_tolerance": "Set from the tolerance the CDE register declares on the "
                         "element this check watches.",
    "run_history": "Set from where the violation rate has sat across the run history.",
    "both": "Set from the element's declared tolerance, with the run history saying "
            "where the data sits against it.",
    "unchanged": "The model was asked and advises keeping the current limit.",
}


def defect_badge(defect_location) -> str:
    """Where the fix belongs, as a claim rather than a category."""
    key = str(defect_location or "").strip()
    if key not in DEFECT_LABEL:
        return ""
    return badge(DEFECT_LABEL[key], DEFECT_TONE[key], "wrench")


# Confidence bands. The number is the model's own and the word beside it is ours;
# both are always printed, because a reader who sees only "0.45" has to invent the
# scale. Tone is the third channel and never the first.
def confidence_badge(value) -> str:
    """The model's own confidence, in figures and in words."""
    if value is None or (isinstance(value, float) and value != value):
        return ""
    v = float(value)
    word, tone = (("high", "neutral") if v >= 0.75
                  else ("moderate", "moderate") if v >= 0.5
                  else ("low", "high"))
    return badge(f"{v:.0%} confidence · {word}", tone)


APPROACH_LABEL = {
    "pipeline_rerun": "Pipeline rerun",
    "upstream_ticket": "Upstream ticket",
    "source_correction": "Source correction",
    "manual_sql": "Manual SQL",
    "accept_and_document": "Accept & document",
}

# --- Icons ------------------------------------------------------------------
# Lucide-style stroke paths on a 24 grid. Kept deliberately few: one icon per
# concept, reused everywhere that concept appears.

_PATHS = {
    "inbox": "M22 12h-6l-2 3h-4l-2-3H2M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z",
    "edit": "M12 20h9M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z",
    "shield": "M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67 0C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1zm-11 -1 2 2 4-4",
    "wrench": "M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z",
    "flask": "M4.5 3h15M6 3v16a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V3M6 14h12",
    "refresh": "M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8M3 3v5h5",
    "check": "M20 6 9 17l-5-5",
    "close": "M18 6 6 18M6 6l12 12",
    "pause": "M10 4H6v16h4zM18 4h-4v16h4z",
    "clock": "M12 6v6l4 2M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0z",
    "archive": "M21 8v13H3V8M1 3h22v5H1zM10 12h4",
    "spark": "m12 3-1.9 5.8-5.8 1.9 5.8 1.9L12 18.4l1.9-5.8 5.8-1.9-5.8-1.9Z",
    "alert": "M12 9v4M12 17h.01M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z",
    "table": "M3 3h18v18H3zM3 9h18M3 15h18M9 3v18",
    "download": "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3",
    "search": "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.35-4.35",
    "link": "M9 17H7A5 5 0 0 1 7 7h2M15 7h2a5 5 0 0 1 0 10h-2M8 12h8",
    "file": "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M9 13h6M9 17h4",
    "nodes": "M18 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM6 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM18 22a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM8.6 13.5l6.8 4M15.4 6.5l-6.8 4",
    "copy": "M20 9h-9a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2v-9a2 2 0 0 0-2-2zM5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1",
    "eye": "M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
    "check_circle": "M22 11.08V12a10 10 0 1 1-5.93-9.14M22 4 12 14.01l-3-3",
    "x_circle": "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM15 9l-6 6M9 9l6 6",
    "arrow_right": "M5 12h14M12 5l7 7-7 7",
    "filter": "M22 3H2l8 9.46V19l4 2v-8.54L22 3z",
    "info": "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 16v-4M12 8h.01",
    "up": "M12 19V5M5 12l7-7 7 7",
    "down": "M12 5v14M19 12l-7 7-7-7",
    "flat": "M5 12h14M13 8l4 4-4 4",
}

# One icon per lifecycle state and per register event, so the same idea keeps the
# same mark on every page.
STATE_ICON = {
    "awaiting_triage": "clock",
    "awaiting_review": "inbox",
    "awaiting_approval": "edit",
    "approved_awaiting_execution": "shield",
    "awaiting_verification": "flask",
    "deferred": "pause",
    "reopened": "refresh",
    "closed_verified": "check",
    "closed_rejected": "close",
    "closed_no_action": "archive",
}

EVENT_ICON = {
    "recommended": "spark",
    "reviewed": "edit",
    "approved": "shield",
    "executed": "wrench",
    "verified": "flask",
    "reopened": "refresh",
}

EVENT_TONE = {
    "recommended": "neutral",
    "reviewed": "moderate",
    "approved": "info",
    "executed": "info",
    "verified": "success",
    "reopened": "critical",
}


def icon(name: str, size: int = 14, colour: str | None = None) -> str:
    """Inline SVG, stroked in currentColor unless told otherwise."""
    path = _PATHS.get(name)
    if not path:
        return ""
    stroke = colour or "currentColor"
    return (
        f'<svg viewBox="0 0 24 24" width="{size}" height="{size}" fill="none" '
        f'stroke="{stroke}" stroke-width="1.75" stroke-linecap="round" '
        f'stroke-linejoin="round" class="dq-i"><path d="{path}"/></svg>'
    )


def sparkline(values, width: int = 88, height: int = 20, tone: str = "info") -> str:
    """A run history as inline SVG.

    Drawn by hand rather than through the data grid's chart column, for the same
    reason `components.summary_table` exists: markup always renders, and a chart that
    silently collapses to nothing is worse than no chart.

    The last point is marked, because "where it ended up" is the question a sparkline
    is usually being asked.
    """
    pts = [float(v) for v in values if v is not None]
    if len(pts) < 2:
        return ""
    lo, hi = min(pts), max(pts)
    span = (hi - lo) or 1.0
    step = width / (len(pts) - 1)
    pad = 2
    coords = [
        (i * step, height - pad - (v - lo) / span * (height - 2 * pad))
        for i, v in enumerate(pts)
    ]
    path = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    colour = TONE.get(tone, TONE["info"])["fg"]
    lx, ly = coords[-1]
    return (
        f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'class="dq-spark" preserveAspectRatio="none">'
        f'<polyline points="{path}" fill="none" stroke="{colour}" stroke-width="1.4" '
        f'stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>'
        f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="1.8" fill="{colour}"/></svg>'
    )


# --- Marks ------------------------------------------------------------------


def hint(text: str, side: str = "left") -> str:
    """An inline explanation mark carrying its own tooltip.

    `st.markdown(..., help=)` renders its icon absolutely positioned at the top-right
    of the *element*, which for a bordered card lands on the border — a row of cards
    ends up with loose dots sitting in the gaps between them. Anything drawn as a card
    carries its explanation through this instead, inside the header where it reads as
    part of the card. Plain Streamlit widgets keep using `help=`, which places it
    correctly for them.

    **The tooltip is drawn, not delegated to `title=`.** It used to be a bare `title`
    attribute on this span, and it did not work: the only thing inside the span is an
    inline `<svg>`, and a pointer over an SVG that has no `<title>` child of its own
    does not reliably fall back to an ancestor's `title` attribute in Chrome or
    Safari. The icon *is* the whole hit area, so the hover landed on the one element
    that swallowed the tooltip and nothing appeared. Two fixes, both needed: the SVG
    is made transparent to the pointer so the hover lands on this span, and the bubble
    is a real element so it is styled, instant, readable at this font size, and
    reachable by keyboard — a `title` is none of those.

    `side` is which way the bubble grows: "left" (default) hangs it from the icon's
    right edge leftwards, which is right for a hint at the end of a card header;
    "right" for a hint near the left edge of the page.
    """
    return (
        f'<span class="dq-hint" tabindex="0" role="note" '
        f'aria-label="{html.escape(text)}">{icon("info", 12)}'
        f'<span class="tip {html.escape(side)}">{html.escape(text)}</span></span>'
    )


def pct_text(value: float | None, places: int = 0, dash: str = "\u2014") -> str:
    """A percentage that never rounds into a claim the number does not support.

    `f"{99.9:.0f}%"` reads "100%", and a dimension card showing 100% above the words
    "1 failing" is not a rounding nit — it is the card contradicting itself, and the
    reader has no way to tell which half is wrong. So: if rounding to `places` would
    print a perfect 100 (or a clean 0) that the value has not actually reached, keep
    adding decimals until the printed figure tells the truth. Everything else rounds
    normally.
    """
    if value is None:
        return dash
    for dp in range(places, places + 4):
        shown = float(f"{value:.{dp}f}")
        if (shown >= 100.0 and value < 100.0) or (shown <= 0.0 and value > 0.0):
            continue
        return f"{value:.{dp}f}"
    return f"{value:.{places + 3}f}"


def badge(text: str, tone: str = "neutral", icon_name: str | None = None) -> str:
    """A tinted badge. Text always present — the tint is the second channel, not the
    first."""
    t = TONE.get(tone, TONE["neutral"])
    glyph = icon(icon_name, 12) if icon_name else ""
    return (
        f'<span class="dq-badge" style="color:{t["fg"]};background:{t["bg"]};'
        f'border-color:{t["bd"]}">{glyph}{text}</span>'
    )


def severity_badge(severity: str, words: bool = True) -> str:
    label = SEVERITY_SHORT.get(severity, severity)
    if words and severity in SEVERITY_WORD:
        label = f"{label} · {SEVERITY_WORD[severity]}"
    return badge(label, SEVERITY_TONE.get(severity, "neutral"))


def severity_text(severity: str) -> str:
    """For table cells, which take text and not markup."""
    return f"{SEVERITY_SHORT.get(severity, severity)} {SEVERITY_WORD.get(severity, '')}".strip()


def criticality_badge(criticality: str) -> str:
    return badge(str(criticality).title(),
                 CRITICALITY_TONE.get(criticality, "neutral"))


def coverage_badge(gap: str) -> str:
    return badge(COVERAGE_GAP_LABEL.get(gap, str(gap)),
                 COVERAGE_GAP_TONE.get(gap, "neutral"))


def state_badge(state: str) -> str:
    return badge(
        STATE_LABEL.get(state, str(state).replace("_", " ")),
        STATE_TONE.get(state, "neutral"),
        STATE_ICON.get(state),
    )


def approach_label(approach: str | None) -> str:
    if not approach:
        return "—"
    return APPROACH_LABEL.get(approach, approach.replace("_", " "))


def meter(pct: float | None, tone: str = "info") -> str:
    """A proportional bar. Always paired with the figure it draws — never alone."""
    if pct is None:
        return '<div class="dq-meter"><span style="width:0"></span></div>'
    width = max(0.0, min(100.0, float(pct)))
    colour = TONE.get(tone, TONE["info"])["fg"]
    return (
        f'<div class="dq-meter"><span style="width:{width:.1f}%;background:{colour}">'
        f"</span></div>"
    )


def delta(points: float | None, unit: str = "%", places: int = 0) -> str:
    """A signed change with its direction drawn as well as written.

    Up is green and down is red because every figure this decorates is a quality
    score, where higher is better. Nothing else may use it — a rising violation
    count rendered by this helper would read as good news.
    """
    if points is None:
        return '<span class="dq-delta n">' + icon("flat", 12) + "new</span>"
    if abs(points) < 0.05:
        return '<span class="dq-delta n">' + icon("flat", 12) + f"0{unit}</span>"
    up = points > 0
    tone = TONE["success" if up else "critical"]["fg"]
    return (
        f'<span class="dq-delta" style="color:{tone}">{icon("up" if up else "down", 12)}'
        f"{abs(points):.{places}f}{unit}</span>"
    )


def segments(parts: list[tuple[float, str]]) -> str:
    """A single bar split into tinted shares. `parts` are (percent, tone)."""
    spans = "".join(
        f'<span style="width:{max(0.0, float(p)):.2f}%;background:{TONE[t]["fg"]}"></span>'
        for p, t in parts
        if float(p) > 0
    )
    return f'<div class="dq-seg">{spans}</div>'


def dot(tone: str) -> str:
    return f'<span class="dq-dot" style="background:{TONE.get(tone, TONE["neutral"])["fg"]}"></span>'

def _axis_ticks(lo: float, hi: float) -> list[float]:
    """Three or four round values spanning `lo`..`hi`, clamped to a percentage."""
    lo, hi = max(0.0, lo), min(100.0, hi)
    span = max(hi - lo, 0.5)
    step = next((s for s in (0.5, 1, 2, 5, 10, 20, 25, 50) if span / s <= 3), 50)
    first = math.floor(lo / step) * step
    last = math.ceil(hi / step) * step
    if first == last:
        # A flat series. Widen downward, or upward when it sits on the floor: a
        # constant 0% (a check failing every row on every run) is otherwise one tick
        # and a zero-height axis.
        if last - step >= 0.0:
            first = last - step
        else:
            last = first + step
    return [first + i * step for i in range(int(round((last - first) / step)) + 1)]


def target_chart(points: list[tuple], target: float | None = None,
                 width: int = 560, height: int = 150) -> str:
    """A score's history against the target it is held to, as inline SVG.

    `points` are (label, value), oldest first. The value axis is fitted to the series
    AND the target, so the dashed line is always on the chart: a trend drawn on an
    axis that crops the target off the top shows a flat line and hides that the whole
    of it is six points short. That costs the series some height when the gap is
    large, and the gap is the thing being reported.

    Three dates along the foot rather than one per point — the shape is the message —
    and the value axis stays labelled: the hover reading below is the second way to
    a figure, not the only one, because a touch screen has no hover.

    **Each run can be hovered for its reading.** The drawing is SVG and the readout
    is not: one transparent column per run is laid over it as HTML, positioned in
    percentages of the same viewBox, and its guide line, dot and bubble are shown by
    the column's own CSS `:hover` — the same drawn-tooltip pattern as `hint()` and
    the row tips, for the same reason (nothing here can run script, and `<title>` is
    slow, unstyled and unreliable inside an inline SVG). A column is as wide as the
    gap between runs, so the pointer only has to be nearest a point, never on it.
    The bubble opens toward the middle of the chart from either half and is clamped
    to the drawing's height, so it cannot leave the card or be cropped by the
    fixed-height tab body the element pane draws this in.

    The end dot is red when the latest value is under the target, and a hovered dot
    is red on the same rule. That is the one place colour carries anything here, and
    the words beside the figure — and in the bubble — say it too.

    `width` is the viewBox width and should be near the width the chart is drawn at:
    the labels are sized in viewBox units, so a 560-wide drawing squeezed into a
    360px pane renders them at two-thirds size.
    """
    vals = [float(v) for _, v in points if v is not None]
    if len(vals) < 2:
        return '<div class="dq-quiet">Not enough history to draw a trend.</div>'
    points = [(lab, float(v)) for lab, v in points if v is not None]

    ticks = _axis_ticks(min(vals + ([target] if target is not None else [])),
                        max(vals + ([target] if target is not None else [])))
    y_lo, y_hi = ticks[0], ticks[-1]
    w, h = float(width), float(height)
    pad_l, pad_r, pad_t, pad_b = 38.0, 8.0, 9.0, 21.0
    plot_w, plot_h = w - pad_l - pad_r, h - pad_t - pad_b
    step = plot_w / (len(points) - 1)

    def y_of(v: float) -> float:
        return pad_t + plot_h - (v - y_lo) / (y_hi - y_lo) * plot_h

    coords = [(pad_l + i * step, y_of(v)) for i, (_, v) in enumerate(points)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    floor = pad_t + plot_h
    area = f"{coords[0][0]:.1f},{floor:.1f} {line} {coords[-1][0]:.1f},{floor:.1f}"

    grid = "".join(
        f'<line x1="{pad_l:.1f}" y1="{y_of(t):.1f}" x2="{w - pad_r:.1f}" '
        f'y2="{y_of(t):.1f}" stroke="{NEUTRAL["border"]}" stroke-width="1"/>'
        f'<text x="{pad_l - 7:.1f}" y="{y_of(t) + 3.5:.1f}" text-anchor="end" '
        f'class="ax">{t:g}%</text>'
        for t in ticks
    )
    goal = ""
    if target is not None:
        goal = (f'<line x1="{pad_l:.1f}" y1="{y_of(target):.1f}" x2="{w - pad_r:.1f}" '
                f'y2="{y_of(target):.1f}" stroke="{NEUTRAL["text_2"]}" stroke-width="1.2" '
                'stroke-dasharray="4 3"/>')
    mid = len(points) // 2
    dates = "".join(
        f'<text x="{coords[i][0]:.1f}" y="{h - 5:.1f}" text-anchor="{anchor}" '
        f'class="ax">{html.escape(str(points[i][0]))}</text>'
        for i, anchor in ((0, "start"), (mid, "middle"), (len(points) - 1, "end"))
        if len(points) > 2 or i != mid
    )
    under = target is not None and vals[-1] < target - 1e-9
    end = TONE["critical"]["fg"] if under else ACCENT
    lx, ly = coords[-1]
    said = (f"{points[0][0]} {pct_text(vals[0], 1)}% to "
            f"{points[-1][0]} {pct_text(vals[-1], 1)}%"
            + (f", target {target:.1f}%" if target is not None else ""))

    def reading(i: int) -> str:
        """The hover column for run `i`: guide line, dot and bubble, all hidden until
        the column is hovered. Everything is placed in percentages of the viewBox, so
        it tracks the drawing at whatever width the card gives it."""
        (x, y), (lab, v) = coords[i], points[i]
        lo, hi = max(0.0, x - step / 2), min(w, x + step / 2)
        at = (x - lo) / (hi - lo) * 100
        top = y / h * 100
        below = target is not None and v < target - 1e-9
        words = ""
        if target is not None:
            gap = pct_text(target - v, 1)
            words = (f"{gap} {'pt' if gap == '1.0' else 'pts'} below target" if below
                     else "meets target")
        # A whole number printed as one, as every score beside the chart is.
        shown = pct_text(v, 1).removesuffix(".0")
        # Toward the middle from either half, so the bubble never leaves the chart.
        side = (f"right:calc({100 - at:.2f}% + 10px)" if x > pad_l + plot_w / 2
                else f"left:calc({at:.2f}% + 10px)")
        return (
            f'<span class="pt" style="left:{lo / w * 100:.3f}%;'
            f'width:{(hi - lo) / w * 100:.3f}%">'
            f'<i class="gl" style="left:{at:.2f}%;top:{pad_t / h * 100:.2f}%;'
            f'height:{plot_h / h * 100:.2f}%"></i>'
            f'<i class="dt" style="left:{at:.2f}%;top:{top:.2f}%;'
            f'background:{TONE["critical"]["fg"] if below else ACCENT}"></i>'
            f'<span class="tip" style="{side};'
            f'top:clamp(1.5rem, {top:.2f}%, calc(100% - 1.5rem))">'
            f"<b>{html.escape(str(lab))}</b>"
            f'<span>{shown}%{" · " + words if words else ""}</span>'
            "</span></span>"
        )

    return (
        '<div class="dq-trendw">'
        f'<svg viewBox="0 0 {w:.0f} {h:.0f}" class="dq-trend" role="img" '
        f'aria-label="{html.escape(said)}">'
        + grid
        + f'<polygon points="{area}" fill="{ACCENT}" fill-opacity=".08"/>'
        + goal
        + f'<polyline points="{line}" fill="none" stroke="{ACCENT}" stroke-width="2" '
        'stroke-linejoin="round" stroke-linecap="round"/>'
        f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="3.4" fill="{end}"/>'
        + dates
        + "</svg>"
        # The label above already reads the series aloud; a bubble per run would
        # only repeat it thirty times to a screen reader.
        + '<div class="pts" aria-hidden="true">'
        + "".join(reading(i) for i in range(len(points)))
        + "</div></div>"
    )


def target_bar(score: float | None, target: float | None, colour: str) -> str:
    """A 0–100 bar filled to `score` with a tick where the target sits.

    Always on the full scale, never zoomed to the interesting end: twenty of these
    stack in a list and are read against each other, and a bar whose axis starts at
    95 makes 97% look like a third.
    """
    fill = 0.0 if score is None else max(0.0, min(100.0, float(score)))
    tick = ""
    if target is not None:
        at = max(0.0, min(100.0, float(target)))
        tick = f'<i style="left:min({at:.2f}%, calc(100% - 2px))"></i>'
    return (f'<span class="dq-tbar"><span style="width:{fill:.2f}%;'
            f'background:{colour}"></span>{tick}</span>')


def area_chart(points: list[tuple], y_lo: float = 0.0, y_hi: float = 100.0) -> str:
    """A filled trend line with its own axes, as inline SVG.

    Hand-drawn for the same reason `sparkline` and `summary_table` are: this sits in
    a fixed-height card next to a headline figure, and `st.line_chart` in that slot
    brings its own padding, its own font and a measurement pass that sometimes lands
    at nothing. `points` are (label, value); the label is drawn for a handful of
    evenly spaced ticks only, because a date under every point is unreadable at this
    width and unnecessary — the shape is the message.
    """
    vals = [v for _, v in points if v is not None]
    if len(vals) < 2:
        return '<div class="dq-quiet">Not enough history to draw a trend.</div>'

    w, h = 300.0, 108.0
    pad_l, pad_r, pad_t, pad_b = 22.0, 4.0, 8.0, 17.0
    span = (y_hi - y_lo) or 1.0
    plot_w, plot_h = w - pad_l - pad_r, h - pad_t - pad_b
    step = plot_w / (len(points) - 1)

    def xy(i, v):
        return pad_l + i * step, pad_t + plot_h - (float(v) - y_lo) / span * plot_h

    coords = [xy(i, v) for i, (_, v) in enumerate(points)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    area = (
        f"{coords[0][0]:.1f},{pad_t + plot_h:.1f} "
        + line
        + f" {coords[-1][0]:.1f},{pad_t + plot_h:.1f}"
    )
    colour = TONE["success"]["fg"]

    grid, ticks = [], []
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        y = pad_t + plot_h - frac * plot_h
        grid.append(
            f'<line x1="{pad_l}" y1="{y:.1f}" x2="{w - pad_r}" y2="{y:.1f}" '
            f'stroke="{NEUTRAL["border"]}" stroke-width="1"/>'
        )
        ticks.append(
            f'<text x="{pad_l - 5}" y="{y + 3.5:.1f}" text-anchor="end" '
            f'class="ax">{y_lo + frac * span:.0f}</text>'
        )

    every = max(1, (len(points) - 1) // 4)
    for i in range(0, len(points), every):
        x = coords[i][0]
        anchor = "start" if i == 0 else "end" if i >= len(points) - every else "middle"
        ticks.append(
            f'<text x="{x:.1f}" y="{h - 5:.1f}" text-anchor="{anchor}" '
            f'class="ax">{points[i][0]}</text>'
        )

    dots = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="1.9" fill="#fff" stroke="{colour}" '
        f'stroke-width="1.2"/>'
        for x, y in coords
    )
    lx, ly = coords[-1]

    return (
        f'<svg viewBox="0 0 {w:.0f} {h:.0f}" class="dq-area">'
        + "".join(grid)
        + f'<polygon points="{area}" fill="{colour}" fill-opacity=".08"/>'
        f'<polyline points="{line}" fill="none" stroke="{colour}" stroke-width="1.8" '
        f'stroke-linejoin="round" stroke-linecap="round"/>'
        + dots
        + f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="2.8" fill="{colour}"/>'
        + "".join(ticks)
        + "</svg>"
    )


# --- CSS --------------------------------------------------------------------

_CSS = f"""
<style>
:root {{
  --dq-border: {NEUTRAL["border"]};
  --dq-text-2: {NEUTRAL["text_2"]};
  --dq-text-3: {NEUTRAL["text_3"]};
  --dq-accent: {ACCENT};

  /* Spacing and type scale with the viewport rather than stepping at a breakpoint.
     The page is a five-column row of cards inside a 1400px container, so every card
     narrows continuously as the window does — a media query would hold one padding
     until it snapped to another, and the snap is what reads as broken. clamp() gives
     a floor, a proportional middle and a ceiling, and every box on the page draws its
     padding from the same three tokens so they stay in step. */
  --dq-pad: clamp(.6rem, 1.05vw, 1rem);
  --dq-pad-y: clamp(.5rem, .8vw, .85rem);
  --dq-fs-hd: clamp(.7rem, .85vw, .8rem);
  --dq-fs-val: clamp(1.32rem, 1.75vw, 1.95rem);
  --dq-fs-sub: clamp(.68rem, .8vw, .78rem);
  --dq-fs-hero: clamp(1.85rem, 2.6vw, 2.75rem);
}}

/* Streamlit's default top padding is built for consumer apps — but it cannot go
   below the height of the floating toolbar (Deploy, the overflow menu) that sits over
   the top-right of the canvas. At 2.2rem the page title ran under it and read as
   cropped. 3.1rem clears the toolbar and still puts the first row of numbers on
   screen without scrolling. */
.stMain .block-container {{ padding-top: 3.1rem; padding-bottom: 4rem; max-width: 1400px; }}

h1, h2, h3 {{ letter-spacing: 0; }}
.stMain h1 {{ font-size: 1.45rem; font-weight: 600; margin-bottom: .15rem; }}
.stMain h2 {{ font-size: 1.02rem; font-weight: 600; margin: .4rem 0 .1rem; }}
.stMain h3 {{ font-size: .92rem; font-weight: 600; }}

.dq-i {{ vertical-align: -2px; flex: none; }}

/* Section label — the small uppercase rule that separates bands of content. */
.dq-section {{
  font-size: .69rem; font-weight: 600; letter-spacing: 0; text-transform: uppercase;
  color: var(--dq-text-3); margin: clamp(1rem, 1.5vw, 1.6rem) 0 var(--dq-pad-y);
  padding-bottom: .3rem;
  border-bottom: 1px solid var(--dq-border);
}}

.dq-badge {{
  display: inline-flex; align-items: center; gap: .28rem;
  padding: .08rem .4rem; border-radius: 4px; border: 1px solid;
  font-size: .715rem; font-weight: 550; line-height: 1.55; white-space: nowrap;
}}

/* KPI tile: label above, figure below, tabular figures so columns line up. */
.dq-kpi {{ padding: .1rem 0; }}
.dq-kpi .lab {{
  font-size: .69rem; font-weight: 600; letter-spacing: 0; text-transform: uppercase;
  color: var(--dq-text-3); display: flex; align-items: flex-start; gap: .3rem;
  /* Reserve two lines. A label that wraps would otherwise push its figure down and
     break the alignment of the whole row. */
  min-height: 2.05em; line-height: 1.35;
}}
.dq-kpi .val {{
  font-size: 1.65rem; font-weight: 600; line-height: 1.25; margin-top: .18rem;
  font-variant-numeric: tabular-nums; letter-spacing: 0;
}}
.dq-kpi .sub {{ font-size: .74rem; color: var(--dq-text-3); margin-top: .05rem; }}

/* Event rail. */
.dq-rail {{ border-left: 1px solid var(--dq-border); margin-left: .5rem; padding-left: 1.15rem; }}
.dq-ev {{ position: relative; padding: .1rem 0 1rem; }}
.dq-ev:last-child {{ padding-bottom: 0; }}
.dq-ev .pin {{
  position: absolute; left: -1.72rem; top: .05rem;
  width: 1.15rem; height: 1.15rem; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  border: 1px solid; background: #fff;
}}
.dq-ev .hd {{ font-size: .855rem; font-weight: 600; }}
.dq-ev .meta {{ font-size: .735rem; color: var(--dq-text-3); margin-top: .08rem; }}
.dq-ev .body {{ font-size: .815rem; color: var(--dq-text-2); margin-top: .32rem; line-height: 1.5; }}
.dq-ev code {{ font-size: .76rem; }}

.dq-kv {{ display: flex; gap: .5rem; font-size: .82rem; padding: .16rem 0; }}
.dq-kv .k {{ color: var(--dq-text-3); min-width: 8.5rem; flex: none; }}
.dq-kv .v {{ color: inherit; }}
.dq-quiet {{ font-size: .78rem; color: var(--dq-text-3); }}

/* Static summary tables — see components.summary_table for why these exist. */
.dq-tbl {{ width: 100%; border-collapse: collapse; font-size: .82rem; margin: .1rem 0 .3rem; }}
.dq-tbl th {{
  text-align: left; font-size: .69rem; font-weight: 600; letter-spacing: 0;
  text-transform: uppercase; color: var(--dq-text-3); padding: .3rem .6rem .3rem 0;
  border-bottom: 1px solid var(--dq-border); white-space: nowrap;
}}
.dq-tbl td {{
  padding: .34rem .6rem .34rem 0; border-bottom: 1px solid var(--dq-border);
  white-space: nowrap;
}}
.dq-tbl th.n, .dq-tbl td.n {{ text-align: right; font-variant-numeric: tabular-nums; }}
.dq-tbl tr:last-child td {{ border-bottom: none; }}
.dq-tbl td.bar {{ position: relative; min-width: 5.5rem; }}
.dq-tbl td.bar .fill {{
  position: absolute; left: 0; top: .42rem; bottom: .42rem;
  background: var(--dq-accent); opacity: .16; border-radius: 2px;
}}
.dq-tbl td.bar .lbl {{ position: relative; }}
/* Inline, so a sparkline sits ON the line of text that introduces it. As a
   block it broke the line and left the clause after it — " · first breached
   25 Jul" — starting with an orphaned separator. */
.dq-spark {{ vertical-align: middle; display: inline-block; }}

.st-key-scorecard_monitor_inventory [data-testid="stDataFrame"] {{
  border: 1px solid var(--dq-border); border-radius: 6px; overflow: hidden;
}}

/* Streamlit ships tabs at body size; at that size they compete with headings. */
.stTabs [data-baseweb="tab"] {{ font-size: .84rem; padding-top: .35rem; padding-bottom: .35rem; }}
.stMain [data-testid="stMetricValue"] {{ font-size: 1.6rem; font-variant-numeric: tabular-nums; }}
.stMain [data-testid="stMetricLabel"] p {{ font-size: .72rem; color: var(--dq-text-3); }}

/* --- Sidebar nav, hand-built. -----------------------------------------------
   `st.navigation(position="hidden")` renders no nav at all, so app.py writes its
   own out of `st.page_link`. These rules give it the brand block and the group
   labels; the links themselves stay Streamlit's, so the active-page highlight and
   the keyboard behaviour are the ones the framework maintains. */
.dq-brand {{ display: flex; align-items: center; gap: .5rem; padding: .1rem .25rem .2rem;
  font-size: .95rem; font-weight: 620; letter-spacing: -.01em; color: {NEUTRAL["text"]}; }}
.dq-brand .sq {{ width: 20px; height: 20px; border-radius: 6px; background: {ACCENT};
  color: #fff; display: grid; place-items: center; font-size: .6rem; font-weight: 600;
  letter-spacing: .02em; flex: none; }}
.dq-navgrp {{ font-size: .63rem; letter-spacing: .1em; text-transform: uppercase;
  color: var(--dq-text-3); font-weight: 600; padding: .75rem .25rem .2rem; }}

/* --- Detail blocks: the three questions, labelled. -------------------------- */
.dq-blockhd {{ display: flex; align-items: center; gap: .5rem; flex-wrap: wrap;
  font-size: .72rem; letter-spacing: .08em; color: var(--dq-text-2);
  margin: -.2rem 0 .55rem; }}
.dq-blockhd b {{ font-weight: 600; color: {NEUTRAL["text"]}; }}
.dq-because {{ font-size: .86rem; color: var(--dq-text-2); line-height: 1.6;
  border-left: 2px solid var(--dq-border); padding-left: .7rem; margin: .5rem 0 .2rem;
  max-width: 78ch; }}
.dq-because b {{ color: {NEUTRAL["text"]}; font-weight: 600; }}

/* --- The itemised verdict: evidence points, steps, and the rival reading. ----
   One fact per line rather than one paragraph, because that is the unit a steward
   works in: a hypothesis is confirmed or discarded a fact at a time, and a
   paragraph has to be taken or left whole.

   Numbered by a counter rather than by an <ol>, so the marker sits inside the
   padding box and lines up with the text of the line above it. A browser <ol>
   marker hangs outside the content box and drifts left of the rule as soon as the
   count reaches double figures. */
.dq-list {{ counter-reset: dqi; margin: .45rem 0 .2rem; padding: 0;
  list-style: none; max-width: 80ch; }}
.dq-list li {{ counter-increment: dqi; position: relative; padding: .18rem 0 .18rem 1.6rem;
  font-size: .855rem; line-height: 1.55; color: var(--dq-text-2); }}
.dq-list li::before {{ content: counter(dqi); position: absolute; left: 0; top: .28rem;
  width: 1.1rem; height: 1.1rem; border-radius: 4px; font-size: .64rem;
  font-weight: 600; display: grid; place-items: center;
  background: {NEUTRAL["canvas"]}; border: 1px solid var(--dq-border);
  color: var(--dq-text-3);
  font-variant-numeric: tabular-nums; }}
/* Evidence is checked off, not ordered — a dot rather than a number, because
   numbering facts implies a sequence they do not have. */
.dq-list.dots li::before {{ content: ""; width: .32rem; height: .32rem; top: .72rem;
  left: .42rem; border-radius: 50%; background: var(--dq-text-3); }}

/* The reading the same evidence also supports. Tinted, because the one thing a
   reader must not do is mistake it for part of the claim. */
.dq-rival {{ font-size: .84rem; line-height: 1.6; max-width: 80ch;
  border: 1px dashed var(--dq-border); border-radius: 8px;
  padding: .55rem .7rem; margin: .6rem 0 .2rem; color: var(--dq-text-2);
  background: {NEUTRAL["canvas"]}; }}
.dq-rival b {{ color: {NEUTRAL["text"]}; font-weight: 600; }}

/* --- Estate tiles: six counts of what is watched. ---------------------------
   Their own card rather than `.dq-kpi`, which is borderless and reads as loose text
   in a six-up row. Bordered, they read as one object per figure — which is what they
   are, since no two of them share a denominator. */
.dq-tile {{
  background: {NEUTRAL["surface"]}; border: 1px solid var(--dq-border);
  border-radius: 10px; padding: .65rem .75rem; height: 100%; min-width: 0;
  display: flex; flex-direction: column; gap: 0; box-sizing: border-box;
}}
.dq-tile .lab {{ font-size: .7rem; font-weight: 600; color: var(--dq-text-2);
  line-height: 1.3; display: flex; align-items: flex-start; gap: .3rem;
  /* Two lines reserved, for the same reason `.dq-kpi` reserves them: a label that
     wraps must not push its figure out of line with the tile beside it. */
  min-height: 2.1em; }}
.dq-tile .val {{ font-size: 1.55rem; font-weight: 620; line-height: 1.2;
  margin-top: .1rem; font-variant-numeric: tabular-nums; letter-spacing: -.01em;
  color: {NEUTRAL["text"]}; }}
.dq-tile .sub {{ font-size: .69rem; color: var(--dq-text-3); line-height: 1.4;
  margin-top: .2rem; }}
/* The figure never wraps — "≥ 600" breaking after the ≥ reads as two numbers — but
   the caption under it may, and the tile grows to fit rather than clipping it. */
.dq-tile .val {{ white-space: nowrap; }}

/* --- The check drill-down, as a drawer. -------------------------------------
   Fixed to the right edge and slid in, rather than pushed into the page below the
   table. The table is the thing being read; a panel that opens underneath it moves
   the rows the reader just clicked, and on a long list pushes them off-screen
   entirely. Everything inside is ordinary Streamlit — the Close button is a real
   button — so only the positioning is borrowed from a modal. */
.st-key-dq_check_drawer, .st-key-dq_element_drawer,
.st-key-dq_decide_drawer {{
  /* Below Streamlit's own toolbar, which is fixed, opaque and painted above this.
     At top:0 the drawer's title row and its Close button rendered underneath it. */
  position: fixed; top: 3.75rem; right: 0; bottom: 0; z-index: 999;
  /* 720, not 660: the element panel puts five columns in here and the fifth —
     the register's own statement of when the column is populated, which is the
     crux of a scope mismatch — was the one pushed off the edge. */
  width: min(720px, 94vw);
  background: {NEUTRAL["surface"]};
  border-left: 1px solid var(--dq-border-strong, {NEUTRAL["border_strong"]});
  /* Two shadows, and the second one IS the veil. A 100vmax spread paints the dim
     over the whole viewport and, because a box-shadow is drawn strictly outside the
     border box, never over the drawer itself — which is the bug it replaces: the veil
     was the drawer's own ::before, and `overflow-y: auto` here clips a pseudo-element
     to the drawer's box, so the dim landed on the panel instead of on the page behind
     it. A shadow is also not hit-testable, so it cannot swallow a click the page below
     still needs. */
  box-shadow: -22px 0 48px -26px rgba(20, 20, 43, .5),
              0 0 0 100vmax rgba(20, 20, 43, .28);
  padding: 0 1.25rem 2.5rem;
  overflow-y: auto; overscroll-behavior: contain;
  animation: dq-drawer-in .22s cubic-bezier(.22, .61, .36, 1);
}}
@keyframes dq-drawer-in {{
  from {{ transform: translateX(100%);
         box-shadow: -22px 0 48px -26px rgba(20, 20, 43, 0),
                     0 0 0 100vmax rgba(20, 20, 43, 0); }}
  to {{ transform: none; }}
}}
/* The title and Close ride along: a drawer this tall scrolls, and a Close button that
   scrolls away leaves the reader with no way out but the browser. */
.st-key-dq_check_drawer [data-testid="stHorizontalBlock"]:has(.dq-dim-panel-hd),
.st-key-dq_element_drawer [data-testid="stHorizontalBlock"]:has(.dq-dim-panel-hd),
.st-key-dq_decide_drawer [data-testid="stHorizontalBlock"]:has(.dq-dim-panel-hd) {{
  position: sticky; top: 0; z-index: 3;
  background: {NEUTRAL["surface"]};
  padding: .85rem 0 .5rem;
  border-bottom: 1px solid var(--dq-border); margin-bottom: .5rem;
}}
@media (prefers-reduced-motion: reduce) {{
  .st-key-dq_check_drawer, .st-key-dq_element_drawer,
  .st-key-dq_decide_drawer {{ animation: none; }}
}}

/* --- Dimension grouping. ---------------------------------------------------- */
.dq-tilehd {{ font-size: .68rem; letter-spacing: .09em; text-transform: uppercase;
  color: var(--dq-text-3); font-weight: 600; padding: .1rem 0 .3rem;
  display: flex; align-items: center; gap: .35rem; }}
.dq-note {{ font-size: .82rem; color: var(--dq-text-2); line-height: 1.55;
  margin: .5rem 0 .2rem; }}
.dq-note .dq-badge {{ margin-right: .3rem; }}

/* --- Page header: title on the left, page-level actions on the right. ----- */
.dq-page-hd {{ margin-bottom: .45rem; }}
/* Beside the run picker, in one row: the row sets the spacing, not the title. */
.st-key-dq_pillbar .dq-page-hd {{ margin-bottom: 0; }}
/* line-height 1.35, not 1.2: most faces are ~1.25em from ascender to descender, so a
   1.2 line box leaves the capitals sitting on its top edge. Nothing is clipped — the
   box just fits the glyphs too closely to look deliberate. */
.dq-page-hd .t {{ font-size: 1.62rem; font-weight: 620; letter-spacing: -.01em;
  color: {NEUTRAL["text"]}; line-height: 1.35; }}
.dq-page-hd .s {{ font-size: .84rem; color: var(--dq-text-2); margin-top: .25rem;
  line-height: 1.5; }}

/* The filter strip. One bordered band so the controls read as a set rather than
   as five unrelated widgets floating above the numbers. */
.st-key-dq_filter_strip,
.st-key-monitor_list_filter_strip {{
  border: 1px solid var(--dq-border); border-radius: 8px;
  background: {NEUTRAL["surface"]}; padding: var(--dq-pad-y) var(--dq-pad) .1rem;
  margin: .35rem 0 var(--dq-pad);
}}
.st-key-dq_filter_strip [data-testid="stVerticalBlock"],
.st-key-monitor_list_filter_strip [data-testid="stVerticalBlock"] {{ gap: .2rem; }}
.dq-strip-lab {{ font-size: var(--dq-fs-sub); font-weight: 550; color: var(--dq-text-2);
  padding-top: .48rem; white-space: nowrap; }}
.dq-strip-note {{ font-size: var(--dq-fs-sub); color: var(--dq-text-3); text-align: right;
  padding-top: .55rem; line-height: 1.5; }}

/* --- The filter bar, as pills. ----------------------------------------------
   Not a bordered band with labels floating outside the controls. That version drew
   three horizontal lines across the top of the page — the band's own top and bottom,
   plus the edge of every control sitting inside it — and none of them lined up with
   each other, because a Streamlit selectbox is 40px tall, a button is 38px, and a
   label rendered in its own column has neither height.

   A pill carries its own label inside its own border, so there is exactly one line
   per control and every one of them is the same height. Streamlit builds a selectbox
   as `label` + `.react-aria-ComboBox`; making the wrapper the flex row, stripping the
   field's own chrome and letting the pill draw the border turns those two into one
   object without touching the widget's behaviour. */
.st-key-dq_pillbar {{ margin: .35rem 0 var(--dq-pad); }}
.st-key-dq_pillbar [data-testid="stHorizontalBlock"] {{ gap: .5rem; }}

.st-key-dq_pillbar [data-testid="stSelectbox"] {{
  display: flex; align-items: center; gap: .1rem; box-sizing: border-box;
  height: 2.35rem; padding-left: .72rem;
  border: 1px solid var(--dq-border); border-radius: 8px;
  background: {NEUTRAL["surface"]};
  transition: border-color .1s ease, box-shadow .1s ease;
}}
.st-key-dq_pillbar [data-testid="stSelectbox"]:hover {{
  border-color: {NEUTRAL["border_strong"]};
}}
/* The focus ring goes on the pill, because the control it belongs to no longer has a
   visible edge of its own. */
.st-key-dq_pillbar [data-testid="stSelectbox"]:focus-within {{
  border-color: {ACCENT}; box-shadow: 0 0 0 1px {ACCENT};
}}
.st-key-dq_pillbar [data-testid="stSelectbox"] > label {{
  margin: 0; padding: 0; flex: none; gap: .25rem;
}}
.st-key-dq_pillbar [data-testid="stSelectbox"] label p {{
  font-size: .78rem; font-weight: 500; color: var(--dq-text-2);
  margin: 0; white-space: nowrap;
}}
/* A help icon inside a pill has to read as part of the label, not as a divider
   between the label and the value it belongs to. */
.st-key-dq_pillbar [data-testid="stSelectbox"] label [data-testid="stTooltipIcon"] svg {{
  width: 13px; height: 13px; opacity: .55;
}}
.st-key-dq_pillbar [data-testid="stSelectbox"] > .react-aria-ComboBox {{
  flex: 1 1 auto; min-width: 0;
}}
/* The field keeps its behaviour and loses its chrome — the pill is drawing it now. */
.st-key-dq_pillbar [data-testid="stSelectbox"] .react-aria-ComboBox > div {{
  border: none; background: transparent; box-shadow: none;
  min-height: 0; height: 2.1rem;
}}
.st-key-dq_pillbar [data-testid="stSelectbox"] input {{
  font-size: .82rem; font-weight: 600; color: {NEUTRAL["text"]};
  padding: 0 0 0 .3rem; text-overflow: ellipsis;
}}

/* A search field in the same row: the same pill, its own border dropped. */
.st-key-dq_pillbar [data-testid="stTextInput"] [data-baseweb="input"] {{
  height: 2.35rem; border: 1px solid var(--dq-border); border-radius: 8px;
  background: {NEUTRAL["surface"]};
}}
.st-key-dq_pillbar [data-testid="stTextInput"] [data-baseweb="input"]:focus-within {{
  border-color: {ACCENT}; box-shadow: 0 0 0 1px {ACCENT};
}}
.st-key-dq_pillbar [data-testid="stTextInput"] input {{ font-size: .82rem; }}

/* A pill that is a button rather than a control: same height, same corner, so the
   row reads as one set. */
.st-key-dq_pillbar .stButton button {{
  height: 2.35rem; min-height: 0; border-radius: 8px;
  border: 1px solid var(--dq-border); background: {NEUTRAL["surface"]};
  color: var(--dq-text-2); font-size: .82rem; font-weight: 500;
}}
.st-key-dq_pillbar .stButton button:hover {{
  border-color: {NEUTRAL["border_strong"]}; color: {NEUTRAL["text"]};
  background: {NEUTRAL["surface"]};
}}
/* The scope statement is tinted, because it is the one thing in the row that is not
   a filter — it says what the figure below it is built on, and a reader who reads it
   as a fourth dropdown will go looking for options that are not there. */
.st-key-dq_pillbar .st-key-_scope_btn button {{
  background: {ACCENT_TINT}; border-color: {TONE["info"]["bd"]}; color: {ACCENT};
  font-weight: 550;
}}
.st-key-dq_pillbar .st-key-_scope_btn button:hover {{
  background: #e6e8ff; border-color: {ACCENT}; color: {ACCENT};
}}

/* --- Cards ---------------------------------------------------------------- */
.dq-card {{
  border: 1px solid var(--dq-border); border-radius: 8px; background: {NEUTRAL["surface"]};
  padding: var(--dq-pad-y) var(--dq-pad); box-sizing: border-box;
  display: flex; flex-direction: column; flex: 1 1 auto; height: 100%;
}}
.dq-card .ttl, .dq-ttl {{
  font-size: clamp(.79rem, .92vw, .87rem); font-weight: 600; color: {NEUTRAL["text"]};
  display: flex; align-items: center; justify-content: space-between; gap: .5rem;
  margin-bottom: var(--dq-pad-y);
}}
.dq-ttl {{ margin-bottom: var(--dq-pad-y); }}
.dq-card .hd {{
  display: flex; align-items: center; gap: .38rem;
  font-size: var(--dq-fs-hd); font-weight: 550; color: var(--dq-text-2);
}}
.dq-card .hd .sp {{ flex: 1 1 auto; }}
/* The hint icon and its drawn tooltip. See theme.hint() for why this is a real
   element and not a `title` attribute.

   Three things make it work where the old one did not:
     1. `.dq-hint > svg` is transparent to the pointer, so hovering the icon hovers
        the SPAN. An inline SVG with no <title> child of its own swallows an
        ancestor's title tooltip in Chrome and Safari, and the icon was the entire
        hit area.
     2. The hit area is padded out to roughly 22px. A 12px icon is a hard target on a
        laptop trackpad, and a tooltip you have to aim at is a tooltip nobody reads.
     3. The bubble is fixed-width and wraps. `title` renders one long line that runs
        off the viewport for anything past a short sentence, and every string this
        app passes to hint() is a paragraph. */
.dq-hint {{
  color: var(--dq-text-3); display: inline-flex; cursor: help; flex: none;
  position: relative; padding: 5px; margin: -5px; border-radius: 4px;
}}
.dq-hint > svg {{ pointer-events: none; }}
.dq-hint:hover, .dq-hint:focus-visible {{ color: {ACCENT}; outline: none; }}
.dq-hint > .tip {{
  position: absolute; bottom: calc(100% + 2px); z-index: 60;
  /* Wide enough to be a paragraph, narrow enough to fit beside a card without being
     clipped by stMain, which is the page's scroll container and therefore the one
     ancestor a bubble cannot escape. `side` picks which way it grows; only the
     leftmost hint on a row needs to grow rightwards. */
  width: max-content; max-width: min(19rem, 30vw);
  background: {NEUTRAL["text"]}; color: #fff;
  font-size: .74rem; font-weight: 450; line-height: 1.45; letter-spacing: 0;
  text-transform: none; white-space: normal; text-align: left;
  padding: .5rem .62rem; border-radius: 6px;
  box-shadow: 0 6px 20px rgba(16, 24, 40, .22);
  /* Hidden by visibility rather than display so the transition has something to
     animate, and pointer-transparent so the bubble can never sit between the cursor
     and the icon and flicker itself off. */
  visibility: hidden; opacity: 0; pointer-events: none;
  transition: opacity .1s ease-out .05s, visibility 0s linear .15s;
}}
/* Which way it grows. A hint at the right edge of a card hangs leftwards or it goes
   off the page; one near the left edge does the opposite. */
.dq-hint > .tip.left {{ right: 0; }}
.dq-hint > .tip.right {{ left: 0; }}
.dq-hint:hover > .tip, .dq-hint:focus-visible > .tip {{
  visibility: visible; opacity: 1; transition-delay: 0s;
}}
.dq-card .val {{
  font-size: var(--dq-fs-val); font-weight: 620; line-height: 1.18;
  margin-top: .3rem; font-variant-numeric: tabular-nums; letter-spacing: -.015em;
  color: {NEUTRAL["text"]};
  /* A card is one column of a five-column row, so it gets narrow before anything else
     does. Without this the browser breaks inside the figure itself — "2,368" wraps to
     "2,3 / 68" and "2 tables" to "2 table / s", which reads as two different numbers.
     The figure never wraps; the label under it may. */
  white-space: nowrap;
}}
.dq-card .val .of {{ font-size: .58em; font-weight: 500; color: var(--dq-text-3);
  margin-left: .22rem; letter-spacing: 0; }}
/* A unit reads as part of the number, not as a word beside it: "93.1%", not
   "93.1 %". The gap above is for "/100", which is a separate phrase. */
.dq-card .val .of.unit {{ margin-left: .04rem; }}
.dq-card .sub {{ font-size: var(--dq-fs-sub); color: var(--dq-text-3); margin-top: .3rem; }}
.dq-card .sub b {{ font-weight: 600; }}

/* Equal heights across a row of cards.

   Streamlit stretches the COLUMNS to the row height, but between a column and the
   card sit five wrappers — stVerticalBlock, stElementContainer, stMarkdown, an
   unnamed emotion div, stMarkdownContainer — and each is auto-height, so the card
   stopped at its own content and the row came out ragged (156 / 125 / 125 / 138 / 138).

   Chaining height:100% down that stack is what fails: it needs every ancestor to have
   a definite height, one wrapper is unnamed and easy to miss, and Streamlit is free to
   add another. flex-grow needs neither a definite height nor a complete list — each
   wrapper simply fills its parent — so the count of wrappers stops mattering.

   Scoped to the two card rows by the classes only they contain. The right-hand rail
   also holds .dq-card elements and must NOT stretch: its two cards are different
   things stacked, not a row to align. */
[data-testid="stHorizontalBlock"]:is(:has(.dq-stat), :has(.dq-dim), :has(.dq-hero))
  > [data-testid="stColumn"] {{
  /* becomes a flex container, but keeps the width basis that sets the column ratios */
  display: flex; flex-direction: column;
}}
[data-testid="stHorizontalBlock"]:is(:has(.dq-stat), :has(.dq-dim), :has(.dq-hero)) :is(
  [data-testid="stVerticalBlock"],
  [data-testid="stElementContainer"],
  .stMarkdown,
  .stMarkdown > div,
  [data-testid="stMarkdownContainer"]) {{
  display: flex; flex-direction: column; flex: 1 1 auto; min-height: 0;
}}

/* Reserve exactly two lines for a stat card's label. At 2.3em this was SHORTER than
   the two lines a wrapped label actually takes, so the one-line "Findings" label kept
   its figure 3.7px above the others. Two lines at line-height 1.3 is 2.6em. */
.dq-stat .hd {{ min-height: 2.6em; align-items: flex-start; line-height: 1.3; }}
.dq-stat .hd .dq-i {{ margin-top: 1px; }}
/* Bars sit on the card floor, so they line up across the row whatever the label and
   caption above them did. */
.dq-stat .dq-meter {{ margin-top: auto; }}

/* --- Meters and segmented bars ------------------------------------------- */
.dq-meter {{
  height: 6px; border-radius: 3px; background: #eef0f3; overflow: hidden;
  margin-top: .55rem; display: block;
}}
.dq-meter > span {{ display: block; height: 100%; border-radius: 3px; }}
.dq-seg {{
  height: 8px; border-radius: 4px; background: #eef0f3; overflow: hidden;
  margin: .5rem 0 .55rem; display: flex; gap: 1px;
}}
.dq-seg > span {{ display: block; height: 100%; }}
.dq-dot {{ width: 7px; height: 7px; border-radius: 50%; display: inline-block;
  margin-right: .3rem; vertical-align: 0; }}
.dq-legend {{ display: flex; flex-wrap: wrap; gap: .1rem clamp(.5rem, 1vw, 1rem);
  font-size: var(--dq-fs-sub);
  color: var(--dq-text-2); }}

.dq-delta {{ display: inline-flex; align-items: center; gap: .12rem;
  font-size: var(--dq-fs-sub); font-weight: 600; font-variant-numeric: tabular-nums;
  /* Never the flex item that gives way: at narrow widths the header was shrinking
     the delta instead of the dimension name, so "0.2%" rendered as "0". */
  flex: none; white-space: nowrap; }}
.dq-delta.n {{ color: var(--dq-text-3); font-weight: 500; }}

/* --- Hero: the headline figure, its target, and its history against it. ----
   Stacked — figure, target line, chart, one sentence — rather than figure beside
   chart: side by side the chart got whatever width the figure did not need, which
   was about 180px for a month of runs. The reading order is the sentence: how good,
   against what, and which way it has been going. */
.dq-hero {{ flex-direction: column; gap: 0; justify-content: flex-start;
  min-height: clamp(9rem, 12vw, 11.5rem); }}
.dq-hero .ttl, .dq-cov .ttl {{ margin-bottom: .1rem; justify-content: flex-start; }}
.dq-hero .ttl .dq-hint, .dq-cov .ttl .dq-hint {{ margin-left: -.15rem; margin-right: auto; }}
.dq-hero .val {{ font-size: var(--dq-fs-hero); margin-top: .2rem;
  display: flex; align-items: baseline; gap: .55rem; }}
.dq-hero .val .dq-delta {{ font-size: .34em; letter-spacing: 0; }}
.dq-hero .sub {{ font-size: clamp(.76rem, .9vw, .84rem); color: var(--dq-text-2);
  margin-top: .25rem; line-height: 1.55; }}
.dq-hero .say {{ font-size: clamp(.76rem, .9vw, .84rem); color: var(--dq-text-2);
  line-height: 1.55; margin-top: .55rem; }}
.dq-hero .say b {{ color: {NEUTRAL["text"]}; font-weight: 620; }}
/* The chart's own legend: a solid stroke and a dashed one, drawn as borders so they
   match the two lines in the SVG without a second drawing. */
.dq-lg {{ display: inline-flex; align-items: center; gap: .35rem; flex: none;
  font-size: clamp(.7rem, .82vw, .78rem); font-weight: 400; color: var(--dq-text-2);
  white-space: nowrap; }}
.dq-lg i {{ display: inline-block; width: 15px; border-top: 2px solid {ACCENT}; }}
.dq-lg i.dash {{ border-top: 2px dashed {NEUTRAL["text_2"]}; margin-left: .55rem; }}
.dq-below {{ color: {TONE["critical"]["fg"]}; }}
/* The chart sits on the card floor whatever the lines above it wrapped to. */
.dq-trendw {{ position: relative; --dq-trend-gap: .6rem; padding-top: var(--dq-trend-gap); }}
.dq-trend {{ width: 100%; height: auto; display: block; overflow: visible; }}
.dq-trend .ax {{ font-size: 11px; fill: {NEUTRAL["text_3"]};
  font-family: inherit; font-variant-numeric: tabular-nums; }}
/* The hover readout — see theme.target_chart(). An HTML layer exactly over the SVG
   (inset by the wrapper's own top gap, which is why that gap is a variable and not
   padding on the SVG: percentages here must mean percentages of the drawing). One
   column per run; hovering a column shows its guide line, dot and bubble. No delay,
   unlike the row tips: running the cursor along a line is scrubbing, and a bubble
   that lags the pointer reads the wrong run. */
.dq-trendw .pts {{ position: absolute; inset: var(--dq-trend-gap) 0 0 0; }}
.dq-trendw .pt {{ position: absolute; top: 0; bottom: 0; }}
.dq-trendw .pt > * {{ position: absolute; visibility: hidden; pointer-events: none; }}
.dq-trendw .pt:hover > * {{ visibility: visible; }}
.dq-trendw .gl {{ width: 0; border-left: 1px solid {NEUTRAL["border_strong"]};
  transform: translateX(-.5px); }}
.dq-trendw .dt {{ width: 9px; height: 9px; border-radius: 50%;
  transform: translate(-50%, -50%); box-shadow: 0 0 0 2px {NEUTRAL["surface"]}; }}
.dq-trendw .tip {{
  z-index: 60; transform: translateY(-50%); width: max-content;
  display: flex; flex-direction: column; gap: .05rem;
  background: {NEUTRAL["text"]}; color: #fff;
  font-size: .74rem; font-weight: 450; line-height: 1.45; letter-spacing: 0;
  white-space: nowrap; font-variant-numeric: tabular-nums;
  padding: .4rem .6rem; border-radius: 6px;
  box-shadow: 0 6px 20px rgba(16, 24, 40, .22);
}}
.dq-trendw .tip b {{ font-weight: 600; }}

/* --- Monitoring coverage: how much of the register something validates. ------
   One bar in three shares, then the same three as a legend with their counts — the
   bar for the proportion, the rows for the numbers. Shades of the accent, not the
   status tones: "not validated" is a statement about the rule set, and painting it
   amber beside a red score would rank a gap in the register with a defect in the
   data. Open problems ride on the card floor under a rule. */
.dq-cov .val .of {{ font-size: .5em; font-weight: 550; color: var(--dq-text-2); }}
.dq-cov3 {{ display: flex; gap: 3px; height: 9px; margin: .75rem 0 .55rem; }}
.dq-cov3 > span {{ display: block; height: 100%; border-radius: 3px; min-width: 4px; }}
.dq-cov .row {{ display: flex; align-items: center; gap: .45rem;
  font-size: clamp(.78rem, .92vw, .86rem); color: {NEUTRAL["text"]}; padding: .2rem 0; }}
.dq-cov .row i {{ width: .5rem; height: .5rem; border-radius: 50%; flex: none; }}
.dq-cov .row b {{ margin-left: auto; font-weight: 550; font-variant-numeric: tabular-nums; }}
.dq-cov .row:last-of-type {{ margin-bottom: .5rem; }}
/* The card is a keyed container, because its floor is a control: the open-problems
   row is a real button and the way into Triage. So the outline moves from the markup
   to the container, exactly as it does for the two lower cards. The container fills
   the column and the row is pushed to its floor, which keeps this card and the hero
   beside it the same height with the rule across both at the same level.

   The selectors are doubled on purpose. The equal-height rule above reaches every
   block inside a card row at specificity (0,3,0) and would stretch the row to share
   the card with the figures above it; these have to out-rank it, not just follow it. */
.st-key-dq_covcard.st-key-dq_covcard.st-key-dq_covcard {{
  border: 1px solid var(--dq-border); border-radius: 8px;
  background: {NEUTRAL["surface"]}; gap: 0; padding: 0; overflow: hidden;
}}
/* Streamlit wraps a keyed container in a layout div the equal-height rule does not
   name, and that div does not grow — so the card stopped at its own content, 40px
   short of the hero. The negative margin is the one Streamlit gives the hero's
   markdown container: the hero overhangs its column by a rem, so this must too or
   the two floors sit a rem apart. */
[data-testid="stLayoutWrapper"]:has(> .st-key-dq_covcard) {{
  flex: 1 1 auto; margin-bottom: -1rem; }}
.st-key-dq_covcard .dq-card {{ border: none; background: transparent; height: auto; }}
.st-key-dq_covcard [data-testid="stMarkdownContainer"] {{ margin-bottom: 0; }}
.st-key-dq_covcard.st-key-dq_covcard.st-key-dq_covcard > :has(.st-key-dqrow_op_queue),
.st-key-dq_covcard.st-key-dq_covcard .st-key-dqrow_op_queue.st-key-dqrow_op_queue {{
  flex: 0 0 auto; margin-top: auto; }}
.st-key-dqrow_op_queue .dq-rowgrid {{ padding: var(--dq-pad-y) var(--dq-pad); }}
.st-key-dqrow_op_queue .stack .t1 {{ font-size: clamp(.82rem, .96vw, .9rem);
  font-weight: 620; }}
.st-key-dqrow_op_queue .stack .t2 {{ font-size: var(--dq-fs-sub); color: var(--dq-text-2); }}
/* A count and an arrow: the arrow is what says the row goes somewhere. */
.dq-rowgrid .opn {{ display: inline-flex; align-items: center; gap: .45rem;
  color: var(--dq-text-3); overflow: visible; }}
.st-key-dqrow_op_queue .opn {{ font-size: clamp(1.15rem, 1.5vw, 1.45rem);
  font-weight: 650; color: {NEUTRAL["text"]}; font-variant-numeric: tabular-nums; }}
.st-key-dqrow_op_queue .opn svg {{ color: var(--dq-text-3); }}
[class*="st-key-dqrow_"]:hover .opn svg {{ color: {ACCENT}; }}
.dq-area {{ width: 100%; height: clamp(76px, 7vw, 108px); display: block; }}
.dq-area .ax {{ font-size: 9px; fill: {NEUTRAL["text_3"]};
  font-family: inherit; font-variant-numeric: tabular-nums; }}

/* A grid of `.dq-tile` figures. One markdown block holding a CSS grid, not a row of
   st.columns: the grid equalises the tile heights for free and has no wrappers to
   shrink. The check drawer's two figures are its one user. */
.dq-tilegrid {{ flex: 1 1 auto; display: grid; gap: clamp(.45rem, .7vw, .7rem);
  grid-template-columns: repeat(3, minmax(0, 1fr)); }}
.dq-tilegrid.compact .dq-tile .lab {{ min-height: 0; }}

/* --- Recent runs --------------------------------------------------------- */
/* Two lines per run, not one. The rail is a third of the page and a single row of
   outcome + timestamp + score only fits by truncating the outcome, which is the part
   worth reading. */
.dq-run {{ display: flex; align-items: center; gap: .5rem;
  padding: .38rem 0; border-bottom: 1px solid var(--dq-border); }}
.dq-run:last-child {{ border-bottom: none; }}
.dq-run .ic {{ display: inline-flex; flex: none; }}
.dq-run .bd {{ flex: 1 1 auto; min-width: 0; }}
.dq-run .t1 {{ font-size: clamp(.72rem, .86vw, .79rem); color: {NEUTRAL["text"]}; white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis; }}
.dq-run .t2 {{ font-size: clamp(.66rem, .78vw, .73rem); color: var(--dq-text-3);
  font-variant-numeric: tabular-nums; white-space: nowrap; }}
.dq-run .n {{ color: var(--dq-text-2); white-space: nowrap; flex: none;
  text-align: right; font-variant-numeric: tabular-nums; font-size: .8rem;
  font-weight: 550; }}

/* --- Dimension cards and the panel behind them ---------------------------- */
/* The card is a st.container, not a block of markup, because its last row is a real
   button — a dimension name is a term of art and the tooltip beside it has room for
   one sentence, so the card has to be able to open. Border and padding therefore move
   off .dq-card and onto the container, exactly as .st-key-dq_issue_board does. */
[class*="st-key-dq_dim_"]:not(.st-key-dq_dimension_panel) {{
  border: 1px solid var(--dq-border); border-radius: 8px;
  background: {NEUTRAL["surface"]};
  padding: var(--dq-pad-y) var(--dq-pad) calc(var(--dq-pad-y) - .3rem);
  display: flex; flex-direction: column; height: 100%;
}}
/* The open card is marked on both channels — a tinted ring AND the button below it
   reading "Hide breakdown" — because the ring alone is colour carrying meaning. */
[class*="st-key-dq_dim_"]:has(.dq-dim-on) {{
  border-color: {ACCENT}; box-shadow: 0 0 0 1px {ACCENT} inset;
}}
[class*="st-key-dq_dim_"]:hover {{ border-color: {NEUTRAL["border_strong"]}; }}
.dq-dim .sub {{ font-size: var(--dq-fs-sub); color: var(--dq-text-3); margin-top: .3rem; }}
.dq-dim .dq-meter {{ margin-top: auto; }}
/* The button sits on the card floor under a hairline, so a row of cards with
   different label heights still lines its buttons up. */
[data-testid="stHorizontalBlock"]:has(.dq-dim) [class*="st-key-dq_dim_"]
  [data-testid="stElementContainer"]:has(.stButton) {{
  flex: 0 0 auto; margin-top: .55rem; border-top: 1px solid var(--dq-border);
  padding-top: .3rem;
}}
[class*="st-key-dq_dim_"] .stButton button {{
  width: 100%; min-height: 0; padding: .16rem .3rem; font-size: .72rem;
  font-weight: 500; border: none; background: transparent; color: var(--dq-text-2);
}}
[class*="st-key-dq_dim_"] .stButton button:hover {{
  color: {ACCENT}; background: {ACCENT_TINT};
}}

.st-key-dq_dimension_panel {{
  border: 1px solid {ACCENT}; border-radius: 8px; background: {NEUTRAL["surface"]};
  padding: var(--dq-pad-y) var(--dq-pad) calc(var(--dq-pad-y) + .1rem);
  margin-top: .55rem;
}}
.dq-dim-panel-hd {{ display: flex; align-items: center; gap: .5rem; flex-wrap: wrap; }}
.dq-dim-panel-hd .ic {{ display: inline-flex; color: {ACCENT}; }}
.dq-dim-panel-hd .t {{ font-size: 1.02rem; font-weight: 620; color: {NEUTRAL["text"]}; }}
.dq-dim-panel-hd .q {{ font-size: var(--dq-fs-sub); color: var(--dq-text-3); }}
.dq-dim-prose {{ font-size: .82rem; line-height: 1.62; color: var(--dq-text-2);
  margin-top: .5rem; }}
.dq-dim-prose.q {{ font-size: .77rem; color: var(--dq-text-3); margin-top: .5rem; }}
.dq-dim-prose code {{ font-size: .93em; }}
/* A rule expression, given its own block. Wraps at any point rather than pushing a
   long SQL string past the panel's padding, and sits on the canvas tint so it reads
   as a quotation of the registry rather than as more prose. */
.dq-expr {{
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: .745rem; line-height: 1.65; color: {NEUTRAL["text"]};
  background: {NEUTRAL["canvas"]}; border: 1px solid var(--dq-border);
  border-radius: 6px; padding: .5rem .65rem; margin-top: .55rem;
  white-space: pre-wrap; overflow-wrap: anywhere;
}}
.dq-expr.scope {{ color: var(--dq-text-2); margin-top: .35rem; }}
/* The arithmetic block. Tabular numerals and a monospaced feel, because it is being
   read as a sum and the operands have to line up under each other. */
.dq-dim-sum {{ background: {NEUTRAL["canvas"]}; border: 1px solid var(--dq-border);
  border-radius: 6px; padding: .55rem .7rem; margin-top: .5rem; }}
.dq-dim-sum .k {{ font-size: .68rem; font-weight: 600; text-transform: uppercase;
  letter-spacing: .02em; color: var(--dq-text-3); }}
.dq-dim-sum .m {{ font-size: .8rem; line-height: 1.55; color: var(--dq-text-2);
  font-variant-numeric: tabular-nums; margin-top: .15rem; }}
.dq-dim-sum .m b {{ color: {NEUTRAL["text"]}; font-weight: 620; }}
.dq-note {{ display: flex; gap: .5rem; align-items: flex-start;
  background: {TONE["info"]["bg"]}; border: 1px solid {TONE["info"]["bd"]};
  border-radius: 6px; padding: .55rem .7rem; margin-top: .7rem;
  font-size: .79rem; line-height: 1.6; color: var(--dq-text-2); }}
.dq-note > svg {{ flex: none; margin-top: .12rem; color: {ACCENT}; }}
.dq-note b {{ color: {NEUTRAL["text"]}; font-weight: 600; }}

/* --- Clickable rows: the failing checks, and the elements nothing watches. ---
   These are not `st.dataframe`. Three things the data grid cannot do and this table
   has to: put a tinted severity badge in a cell, colour a trend phrase, and — the
   one the reader actually notices — open a row when the ROW is clicked. A dataframe
   with `selection_mode="single-row"` only selects from the checkbox in its gutter,
   which means a page that says "select a row" is asking for a click on a 14px target
   the reader has to find first.

   So each row is a container holding its own markup and a real Streamlit button,
   and the button is stretched over the whole row at zero opacity. The row is
   therefore clickable everywhere, keyboard-reachable (it is a button, and it keeps
   its accessible name), and hovers as one object. Nothing is drawn by the button —
   every pixel is the markup underneath it. */
.dq-rowgrid {{
  display: grid; align-items: center; gap: .55rem;
  padding: .5rem .7rem; min-width: 0; box-sizing: border-box;
}}
.dq-rowgrid > * {{ min-width: 0; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; }}
.dq-rowgrid > .dq-rr {{ white-space: normal; }}
.dq-rowgrid .n {{ text-align: right; font-variant-numeric: tabular-nums; }}
.dq-rowgrid .name {{ font-size: clamp(.76rem, .9vw, .84rem); color: {NEUTRAL["text"]};
  font-weight: 500; }}
.dq-rowgrid .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: clamp(.68rem, .8vw, .75rem); color: var(--dq-text-2); }}
.dq-rowgrid .txt {{ font-size: clamp(.71rem, .84vw, .78rem); color: var(--dq-text-2); }}
.dq-rowgrid .num {{ font-size: clamp(.73rem, .86vw, .8rem); color: {NEUTRAL["text"]};
  text-align: right; font-variant-numeric: tabular-nums; }}
.dq-rowgrid .of {{ font-size: clamp(.68rem, .8vw, .75rem); color: var(--dq-text-3);
  text-align: right; font-variant-numeric: tabular-nums; }}
.dq-rowgrid .link {{ font-size: clamp(.71rem, .84vw, .78rem); color: {ACCENT}; }}
/* A row whose first cell is a title over a line of context. The cell opts out of the
   grid's vertical centring so the two lines sit together rather than straddling the
   row, and only the second line is allowed to be quiet. */
.dq-rowgrid .stack {{ display: flex; flex-direction: column; gap: .12rem;
  white-space: normal; overflow: hidden; }}
.dq-rowgrid .stack .t1 {{ font-size: clamp(.78rem, .92vw, .86rem); font-weight: 600;
  color: {NEUTRAL["text"]}; line-height: 1.35;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.dq-rowgrid .stack .t2 {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: clamp(.66rem, .78vw, .72rem); color: var(--dq-text-3); line-height: 1.4;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
/* Opt-in wrapping for a cell whose full text matters more than a fixed row height:
   up to two lines, then an ellipsis. Used on the scorecard's failing checks, where
   "Contact email domain has a top-level domain" cut to "Contact email domain ha…"
   was not a check anyone could identify. The row grows to fit — its height comes
   from `min-height` on the row container, not a fixed height. */
.dq-rowgrid .stack .t1.wrap, .dq-rowgrid .link.wrap {{
  white-space: normal; display: -webkit-box; -webkit-line-clamp: 2;
  -webkit-box-orient: vertical; overflow: hidden; line-height: 1.3; }}
/* The tags on that second line are words, not colours — "recurrence", "checks
   breaching again". The tint is the second channel; the phrase is the first. */
.dq-rowgrid .stack .t2 .mark {{ font-weight: 600; }}
/* A problem's registered elements, as pills — `components.element_chips`. Sans, not
   the mono of the line they may sit on: they are names, not identifiers. The dot is
   criticality's tone and the word beside it says the same thing. `.off` is the count
   of checks on no element, dashed because it is an absence rather than a thing. */
.dq-chip {{ display: inline-flex; align-items: center; gap: .3rem; white-space: nowrap;
  font-family: inherit; font-size: clamp(.64rem, .76vw, .71rem); font-weight: 500;
  color: var(--dq-text-2); border: 1px solid var(--dq-border); border-radius: 999px;
  padding: .02rem .5rem; margin: 0 .3rem .1rem 0; background: {NEUTRAL["surface"]}; }}
.dq-chip i {{ width: .42rem; height: .42rem; border-radius: 50%; display: inline-block; }}
.dq-chip.off {{ border-style: dashed; color: var(--dq-text-3); font-weight: 400; }}
.dq-rowgrid .stack .t2 .dq-chip {{ font-family: -apple-system, BlinkMacSystemFont,
  "Segoe UI", sans-serif; margin-bottom: 0; }}
.dq-chiprow {{ margin: .35rem 0 .1rem; line-height: 1.9; }}
.dq-chiprow .k {{ font-size: .74rem; color: var(--dq-text-3); margin-right: .45rem; }}
.dq-subclaim {{ font-size: .9rem; color: var(--dq-text-2); margin: .1rem 0 .3rem; }}

/* The detail page's Lineage tab — `components.lineage_view`. Three columns and two
   arrows; each column grows to its own height, so nine checks beside two tables do
   not stretch the tables' boxes. */
.dq-lineage {{ display: grid; grid-template-columns: minmax(0,1fr) 1.6rem minmax(0,1fr)
  1.6rem minmax(0,1fr); align-items: start; gap: .4rem; margin: .4rem 0 .6rem; }}
.dq-lineage .col {{ display: flex; flex-direction: column; gap: .35rem; min-width: 0; }}
.dq-lineage .hd {{ font-size: .68rem; font-weight: 600; letter-spacing: .04em;
  text-transform: uppercase; color: var(--dq-text-3); margin-bottom: .1rem; }}
.dq-lineage .node {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: .74rem; color: {NEUTRAL["text"]}; background: {NEUTRAL["surface"]};
  border: 1px solid var(--dq-border); border-radius: 6px; padding: .3rem .55rem;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.dq-lineage .node.hit {{ border-color: {TONE["critical"]["bd"]};
  background: {TONE["critical"]["bg"]}; }}
.dq-lineage .none {{ font-size: .76rem; color: var(--dq-text-3); padding: .3rem 0; }}
.dq-lineage .arrow {{ color: var(--dq-text-3); text-align: center; padding-top: 1.55rem; }}
@media (max-width: 720px) {{
  .dq-lineage {{ grid-template-columns: 1fr; }}
  .dq-lineage .arrow {{ padding: 0; transform: rotate(90deg); }}
}}

/* --- The scorecard's two lower cards: the element list, and one element. ------
   Each card is a keyed container, not a block of markup, because both hold real
   controls — the list's rows and its Priority / All switch, the pane's check rows
   and its drawer button. So the border moves onto the container, the gap Streamlit
   stacks blocks with goes to zero (it is counted against the container's height
   whether or not it is drawn — see `.st-key-dq_strip`), and each block inside
   carries its own padding. */
.st-key-dq_elcard, .st-key-dq_elpane {{
  border: 1px solid var(--dq-border); border-radius: 10px;
  background: {NEUTRAL["surface"]}; gap: 0; padding: 0;
}}
/* With the gap gone, the `margin-bottom: -1rem` Streamlit puts on every markdown
   container to cancel it pulls the next block up over this one's last line. */
.st-key-dq_elcard [data-testid="stMarkdownContainer"],
.st-key-dq_elpane [data-testid="stMarkdownContainer"] {{ margin-bottom: 0; }}
.dq-elcard-hd {{ padding: .9rem 1rem .55rem; }}
.dq-elcard-hd .t {{ font-size: clamp(.86rem, 1vw, .95rem); font-weight: 620;
  color: {NEUTRAL["text"]}; display: flex; align-items: center; gap: .4rem; }}
.dq-elcard-hd .q {{ font-size: clamp(.74rem, .88vw, .82rem); color: var(--dq-text-2);
  margin-top: .2rem; line-height: 1.5; }}
.st-key-dq_elcard [data-testid="stElementContainer"]:has([data-testid="stButtonGroup"]) {{
  padding: 0 1rem .7rem; }}
/* The row boxes run edge to edge inside their card: the card draws the outline, so
   the box keeps only the rules above and below it, and its end rows lose the corner
   radius they take when the box is the outline. */
.st-key-dq_elcard .st-key-dqrows_elist, .st-key-dq_elpane .st-key-dqrows_checks,
.st-key-dq_elpane .st-key-dqrows_problems {{
  border: none; border-top: 1px solid var(--dq-border); border-radius: 0;
  background: transparent; scrollbar-gutter: auto;
}}
.st-key-dq_elpane .st-key-dqrows_checks, .st-key-dq_elpane .st-key-dqrows_problems {{
  border-top: none; }}
.st-key-dq_elpane .st-key-dqrows_problems .dq-rowgrid {{ padding: .6rem 1rem; }}
.st-key-dq_elcard [class*="st-key-dqrow_"], .st-key-dq_elpane [class*="st-key-dqrow_"] {{
  border-radius: 0 !important; }}
.dq-elfoot {{ display: flex; flex-wrap: wrap; justify-content: space-between;
  gap: .2rem 1rem; border-top: 1px solid var(--dq-border);
  padding: .6rem 1rem .7rem; font-size: var(--dq-fs-sub); color: var(--dq-text-2); }}
.dq-elfoot i {{ display: inline-block; width: 2px; height: .8rem; margin: 0 .3rem 0 .8rem;
  background: {NEUTRAL["text"]}; vertical-align: -.12rem; }}

/* One row of either list: a name and its figure, a 0–100 bar with the target ticked
   on it, and a line saying where the figure stands against that target. The dot is
   the element's criticality; the row's tooltip says it in words. */
.dq-el {{ display: flex; flex-direction: column; gap: .32rem; }}
.dq-el .l1, .dq-el .l2 {{ display: flex; align-items: baseline;
  justify-content: space-between; gap: .75rem; min-width: 0; }}
.dq-el .nm {{ font-size: clamp(.8rem, .94vw, .88rem); font-weight: 500;
  color: {NEUTRAL["text"]}; overflow: hidden; text-overflow: ellipsis; min-width: 0; }}
.dq-el .sc {{ font-size: clamp(.8rem, .94vw, .88rem); font-weight: 650; flex: none;
  font-variant-numeric: tabular-nums; }}
.dq-el .sc .of {{ font-weight: 400; color: var(--dq-text-2); font-size: 1em;
  text-align: left; }}
.dq-el .l2 {{ font-size: clamp(.72rem, .85vw, .79rem); color: var(--dq-text-2); }}
.dq-el .l2 > :first-child {{ overflow: hidden; text-overflow: ellipsis; min-width: 0; }}
.dq-el .l2 > :last-child {{ flex: none; font-variant-numeric: tabular-nums; }}
.dq-eldot {{ display: inline-block; width: .5rem; height: .5rem; border-radius: 50%;
  margin-right: .42rem; vertical-align: .06rem; }}
.dq-rowgrid .stack .t2.sans {{ font-family: inherit; }}
.dq-tbar {{ position: relative; display: block; height: 6px; border-radius: 3px;
  background: #eef0f3; margin: .12rem 0; }}
.dq-tbar > span {{ display: block; height: 100%; border-radius: 3px; min-width: 2px; }}
.dq-tbar > i {{ position: absolute; top: -3px; width: 2px; height: 12px;
  border-radius: 1px; background: {NEUTRAL["text"]}; }}
/* Three lines, so the row is taller than the two-line `.stack` rows — and the height
   is asked for on the row container, for the reason given at `st-key-dqrow_` below. */
[class*="st-key-dqrow_"]:has(.dq-el) {{ min-height: 4.7rem; }}
[class*="st-key-dqrow_"] .dq-rowgrid:has(.dq-el) {{ padding: .7rem 1rem; }}
/* The compact row: the bar rides on the second line, between nothing and the words.
   Two lines instead of three, for the check list in its fixed-height tab. The bar is
   let out of the ellipsis rule the line's first child otherwise gets — clipped, it
   loses the target tick, which stands 3px proud of it. */
.dq-el.c2 {{ gap: .34rem; }}
.dq-el.c2 .l2 {{ align-items: center; justify-content: flex-start; }}
.dq-el.c2 .l2 > .dq-tbar {{ flex: 0 1 32%; min-width: 3.5rem; margin: 0; overflow: visible; }}
.dq-el.c2 .l2 > span:nth-of-type(2) {{ flex: 1 1 auto; min-width: 0; overflow: hidden;
  text-overflow: ellipsis; }}
[class*="st-key-dqrow_"]:has(.dq-el.c2) {{ min-height: 3.5rem; }}
[class*="st-key-dqrow_"] .dq-rowgrid:has(.dq-el.c2) {{ padding: .55rem 1rem; }}

/* The pane's own header — which element, and its figure against its target — sits
   above the tabs, so it is on screen whichever of them is open. */
.dq-elhd {{ padding: .9rem 1rem .5rem; }}
.dq-elhd .k {{ font-size: .68rem; letter-spacing: .09em; text-transform: uppercase;
  color: var(--dq-text-3); font-weight: 600; }}
.dq-elhd .n {{ font-size: clamp(.92rem, 1.08vw, 1.02rem); font-weight: 620;
  color: {NEUTRAL["text"]}; margin-top: .3rem; }}
.dq-elhd .b {{ margin: .35rem 0 .2rem; display: flex; flex-wrap: wrap; gap: .3rem; }}
/* One line, always: the header's height is what keeps this card level with the list,
   and an element bound to three columns wrapped it to two. */
.dq-elhd .w {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: .72rem; color: var(--dq-text-3); white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; }}
.dq-elhd .sr {{ display: flex; align-items: baseline; flex-wrap: wrap; gap: .1rem .7rem;
  margin-top: .45rem; font-size: clamp(.78rem, .92vw, .86rem); color: var(--dq-text-2); }}
.dq-elhd .s {{ font-size: clamp(1.35rem, 1.8vw, 1.7rem); font-weight: 650; line-height: 1.15;
  font-variant-numeric: tabular-nums; letter-spacing: -.01em; }}

/* The tabs. The bar is inset to the card's gutter and its rule runs edge to edge;
   the panels lose Streamlit's top padding because each body is a fixed-height box
   that brings its own. Every body is the same height (`TAB_BODY` in scorecard.py)
   and scrolls inside, which is the whole point: nine checks or a hundred sampled
   rows change what is in the card, never how tall it is. */
.st-key-dq_elpane .stTabs [role="tablist"] {{ padding: 0 1rem; }}
.st-key-dq_elpane .stTabs [data-testid="stTabPanel"] {{ padding-top: 0; }}
.st-key-dq_eltab_overview, .st-key-dq_eltab_rows, .st-key-dq_eltab_nochecks,
.st-key-dq_eltab_hist,
.st-key-dq_eltab_notriage {{ padding: .8rem 1rem .6rem; gap: .55rem; }}
.dq-elover .d {{ font-size: clamp(.74rem, .88vw, .82rem); color: var(--dq-text-2);
  margin-bottom: .2rem; }}
.dq-elover .dq-trendw {{ --dq-trend-gap: .35rem; }}
.dq-elnote {{ background: {NEUTRAL["canvas"]}; border-radius: 8px; padding: .65rem .8rem;
  margin-top: .7rem; font-size: clamp(.78rem, .92vw, .86rem); line-height: 1.55;
  color: var(--dq-text-2); }}
.dq-elnote b {{ color: {NEUTRAL["text"]}; font-weight: 620; }}

/* The two cards wrap rather than squeeze. Streamlit only stacks columns below a
   640px VIEWPORT, and the page can be far narrower than the viewport once the
   sidebar is open — so the floor is set on the columns themselves, and whichever
   does not fit goes to the next line at full width. Matched by what each column
   holds, not by `>` from the container: Streamlit puts wrapper blocks between the
   keyed container and its columns. */
/* Clear air between the two rows of cards, scaled with the page. It has to be asked
   for: the hero's markdown container carries Streamlit's `margin-bottom: -1rem`,
   which cancels the 1rem gap between the rows and leaves them 3px apart. */
.st-key-dq_elsplit {{ margin-top: clamp(1.1rem, 2vw, 1.9rem); }}
.st-key-dq_elsplit [data-testid="stHorizontalBlock"]:has(.st-key-dq_elcard) {{
  flex-wrap: wrap; align-items: stretch; }}
/* Both cards fill the row, so their floors meet whatever each one holds. The fixed
   body heights in scorecard.py make them the same height to begin with; this is what
   holds when a header wraps or a font loads late. Each wrapper between the column
   and the card has to pass the height on — Streamlit puts a block and an unnamed
   layout div between them, and neither grows unless told to. */
.st-key-dq_elsplit [data-testid="stColumn"]:is(:has(.st-key-dq_elcard), :has(.st-key-dq_elpane)) {{
  display: flex; flex-direction: column; }}
.st-key-dq_elsplit [data-testid="stColumn"]:is(:has(.st-key-dq_elcard), :has(.st-key-dq_elpane))
  > [data-testid="stVerticalBlock"],
[data-testid="stLayoutWrapper"]:is(:has(> .st-key-dq_elcard), :has(> .st-key-dq_elpane)),
.st-key-dq_elcard, .st-key-dq_elpane {{
  flex: 1 1 auto; display: flex; flex-direction: column; }}
/* The legend is the list's foot, on the card's floor rather than under the last row. */
.st-key-dq_elcard > [data-testid="stElementContainer"]:last-child {{ margin-top: auto; }}
.st-key-dq_elsplit [data-testid="stColumn"]:has(.st-key-dq_elcard) {{
  flex: 1 1 17rem !important; min-width: min(17rem, 100%); }}
.st-key-dq_elsplit [data-testid="stColumn"]:has(.st-key-dq_elpane) {{
  flex: 1.5 1 24rem !important; min-width: min(24rem, 100%); }}

/* The header sits OUTSIDE the scroll box so it does not scroll away, which means
   its cells have to line up with rows drawn inside it: the box's own side padding
   plus the row's. `scrollbar-gutter` below holds that true once the list scrolls. */
.dq-rowgrid.head {{ padding: .1rem calc(.7rem + 1px) .4rem; }}
.dq-rowgrid.head > * {{
  font-size: clamp(.62rem, .74vw, .68rem); font-weight: 600; text-transform: uppercase;
  letter-spacing: .04em; color: var(--dq-text-3);
}}
.dq-rowgrid.head .n {{ text-align: right; }}

/* One row = one container. `position: relative` is what the stretched button
   positions against. */
[class*="st-key-dqrow_"] {{
  position: relative; border-top: 1px solid var(--dq-border);
  /* Square, because a row is a band across the table and not a card in a list. The
     two rows that touch the container's corners get its radius back, below. */
  border-radius: 0; transition: background .09s ease;
  /* Three rules here are load-bearing, and all three are about Streamlit's own
     layout rather than about this table:
       * `flex: 0 0 auto` — the scroll box is a flex column and flex items shrink by
         default, so twenty-one rows in a 252px box were each squeezed to 26px and
         their content spilled into the row below.
       * `min-height` — the row's height has to come from the ROW. Streamlit wraps
         markdown in a centred row-flex box that reports its own height as one line
         whatever it contains, so a taller grid inside it left the container short.
       * `justify-content: center` — with the height set here, the content centres in
         it rather than sitting on the top edge. */
  flex: 0 0 auto; min-height: 2.6rem; justify-content: center;
}}
/* A row whose first cell stacks a title over a line of context needs more than the
   single-line minimum, and asking for it here rather than on `.dq-rowgrid` keeps the
   container and its contents the same height — see the note above about Streamlit
   reporting a markdown box as one line whatever it holds. */
[class*="st-key-dqrow_"]:has(.stack) {{ min-height: 3.35rem; }}
/* Undo that centred row-flex wrapper, so the markdown box is as tall as the row it
   draws. Without it the row is the right height and its contents are not. */
[class*="st-key-dqrow_"] .stMarkdown, [class*="st-key-dqrow_"] .stMarkdown > div {{
  display: block; height: auto;
}}
/* Streamlit gives every markdown container `margin-bottom: -1rem` to cancel the gap it
   puts after blocks — here there is no block after it, so the row came out 1rem short
   of its content and a two-line check name spilled into the next row. Zeroed, the row
   is as tall as its content wherever that beats the `min-height` above. */
[class*="st-key-dqrow_"] [data-testid="stMarkdownContainer"] {{ margin-bottom: 0; }}
/* The hover response the reader is looking for: the whole row tints, in the same
   accent the selected row uses, so hovering previews what clicking does. */
[class*="st-key-dqrow_"]:hover {{
  background: {ACCENT_TINT};
}}
/* Selected. Marked on two channels — the tint AND the accent edge — because the tint
   alone is the same colour hover uses. */
[class*="st-key-dqrow_"]:has(.dq-row-on) {{
  background: {ACCENT_TINT};
  box-shadow: inset 2px 0 0 {ACCENT};
}}
/* The button, stretched over the row and painted with nothing. `opacity: 0` rather
   than `visibility: hidden` or `display: none`: it has to stay hit-testable and
   focusable. The focus ring is drawn back on below, because an invisible control
   that a keyboard can reach and not see is worse than no control. */
/* `inset: 0` alone is not enough: Streamlit gives the element container an explicit
   used width, and an explicit width beats an absolute box's inset stretching. Both
   dimensions are therefore stated. */
[class*="st-key-dqrow_"] [data-testid="stElementContainer"]:has(.stButton) {{
  position: absolute; inset: 0; margin: 0; z-index: 2;
  width: 100%; height: 100%; max-width: none;
}}
[class*="st-key-dqrow_"] [data-testid="stButton"] {{
  height: 100%; width: 100%; max-width: none;
}}
/* A button given `help` is wrapped in three more boxes for its tooltip, each sized to
   its content — which left a 22px strip across the top of the row as the only thing
   that could be clicked or hovered. Stretched, the whole row is the target again and
   the tooltip opens from anywhere on it. */
[class*="st-key-dqrow_"] [data-testid="stButton"] > div,
[class*="st-key-dqrow_"] .stTooltipIcon,
[class*="st-key-dqrow_"] .stTooltipHoverTarget {{
  display: block; height: 100%; width: 100%; max-width: none;
}}
[class*="st-key-dqrow_"] .stButton button {{
  height: 100%; width: 100%; opacity: 0; padding: 0; min-height: 0;
  border: none; background: transparent; cursor: pointer;
}}
[class*="st-key-dqrow_"] .stButton button:focus-visible {{
  opacity: 1; background: transparent; color: transparent;
  outline: 2px solid {ACCENT}; outline-offset: -2px; border-radius: 6px;
}}
/* A row's hover text — `components.clickable_rows(tip=)`. Drawn and shown by
   `:hover` rather than by the button's `help=`, because Streamlit's popover sticks:
   a click reruns the page under it, it never hears the pointer leave, and the
   bubble stayed on screen after the cursor had gone. It hangs below the row, and
   above it for the last two, so the foot of a scrolling list does not clip it. The
   delay is so that running the cursor down the list does not strobe a bubble per
   row. */
.dq-rowtip {{
  position: absolute; top: calc(100% - 4px); left: .7rem; z-index: 60;
  width: max-content; max-width: min(24rem, calc(100% - 1.4rem));
  display: flex; flex-direction: column; gap: .1rem;
  background: {NEUTRAL["text"]}; color: #fff;
  font-size: .74rem; font-weight: 450; line-height: 1.45; white-space: normal;
  overflow-wrap: anywhere; padding: .45rem .62rem; border-radius: 6px;
  box-shadow: 0 6px 20px rgba(16, 24, 40, .22);
  visibility: hidden; opacity: 0; pointer-events: none;
  transition: opacity .1s ease-out 0s, visibility 0s linear .1s;
}}
.dq-rowtip .b {{ font-weight: 600; }}
.dq-rowtip .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .7rem;
  opacity: .85; }}
/* Counted on the row's parent: Streamlit wraps each container in a layout wrapper of
   its own, so the rows themselves are all only children. */
:nth-last-child(-n+2):not(:first-child) > [class*="st-key-dqrow_"] .dq-rowtip {{
  top: auto; bottom: calc(100% - 4px);
}}
[class*="st-key-dqrow_"]:hover .dq-rowtip {{
  visibility: visible; opacity: 1;
  transition: opacity .1s ease-out .45s, visibility 0s linear .45s;
}}
/* The markup underneath must not eat the click meant for the button above it. */
[class*="st-key-dqrow_"] .stMarkdown {{ pointer-events: none; }}

/* The list scrolls rather than paginating. Every failing check stays reachable —
   this page has to agree with the Triage queue, which works all of them — but the
   band below it stays on screen instead of being pushed a thousand pixels down. */
[class*="st-key-dqrows_"] {{
  border: 1px solid var(--dq-border); border-radius: 8px;
  background: {NEUTRAL["surface"]};
  /* No padding. With a gutter here the rows floated inside the box: every separator
     stopped short of both edges, and a hovered or selected row's tint stopped with
     them, leaving a white margin down each side of the highlight. The gutter belongs
     to the row (`.dq-rowgrid` pads its own cells), so the row itself can run edge to
     edge. */
  padding: 0;
  /* Streamlit puts a 1rem gap between every block it stacks. Between table rows that
     is not a gap, it is a hole — and the rows carry their own hairline. */
  gap: 0;
  /* Reserve the scrollbar whether or not it is showing, so the header above the box
     does not shift by 15px the moment the list gets long enough to scroll. */
  scrollbar-gutter: stable;
}}
/* The first row must not draw a line the container has already drawn, and the two
   rows at the ends have to follow its corners — without `overflow: hidden`, which
   cannot be used here: the failing-checks box scrolls, and this same selector would
   win the cascade over Streamlit's own `overflow: auto` and kill the scrolling.

   Both forms of each selector are written out because Streamlit wraps some blocks in
   a layout div and not others; matching only the wrapped shape breaks silently the
   day that changes. */
[class*="st-key-dqrows_"] > :first-child [class*="st-key-dqrow_"],
[class*="st-key-dqrows_"] > [class*="st-key-dqrow_"]:first-child {{
  border-top: none; border-radius: 7px 7px 0 0;
}}
[class*="st-key-dqrows_"] > :last-child [class*="st-key-dqrow_"],
[class*="st-key-dqrows_"] > [class*="st-key-dqrow_"]:last-child {{
  border-radius: 0 0 7px 7px;
}}
.dq-tablefoot {{ font-size: var(--dq-fs-sub); color: var(--dq-text-3);
  padding: .5rem .1rem 0; }}

/* --- The problem detail header and its state strip. -------------------------
   The strip is not a card. It is the page saying whose turn it is, and it carries the
   only control in this app that writes anything — so it sits above the tabs, where it
   is visible on all four of them. The objection to the five tabs this page had until
   2026-09-16 was never that tabs are bad; it was that the decision lived inside one.

   Tinted by outcome, and every variant states that outcome in words as well: colour
   is the second channel here, never the first. */
.dq-factline {{
  display: flex; flex-wrap: wrap; align-items: center; gap: .3rem .5rem;
  font-size: clamp(.74rem, .88vw, .8rem); color: var(--dq-text-2); margin-top: .4rem;
}}
.dq-factline i {{ color: var(--dq-text-3); font-style: normal; }}
.dq-factline b {{ color: {NEUTRAL["text"]}; font-weight: 600;
  font-variant-numeric: tabular-nums; }}
.dq-factline code {{ font-size: .93em; }}

/* The box is one div of our own markup, so its height is set by its own two lines and
   nothing else can shrink it. `padding-right` reserves the button's lane. */
.dq-strip-box {{
  border: 1px solid var(--dq-border); border-radius: 8px;
  padding: var(--dq-pad-y) var(--dq-pad);
}}
.dq-strip-box.has-action {{ padding-right: 13rem; }}
/* The button sits over that lane rather than in the flow beside it — out of flow, so
   it cannot participate in sizing the box.

   Positioned on the ELEMENT CONTAINER, not on `.stButton` inside it: Streamlit gives
   every element container `position: relative`, so an absolute `.stButton` anchors to
   its own wrapper and goes nowhere. Anchored one level up it lands in the lane. */
/* `gap: 0` is the fix to the whole clipping problem, and it is worth knowing why.
   Streamlit puts a 1rem gap between the blocks it stacks, and the gap is counted
   against this container's height even though the only other child — the button — is
   taken out of flow below. The container therefore measured exactly 16px short of the
   box inside it, which cropped the gate line off the bottom edge. Every display,
   flex, height and min-height override tried on the inner wrappers failed for the
   same reason: none of them was where the 16px was going. */
.st-key-dq_strip {{ position: relative; margin: .7rem 0 .2rem; gap: 0; }}
.st-key-dq_strip [data-testid="stElementContainer"]:has(.stButton) {{
  /* Aligned to the top of the box, on the first line of the sentence — not centred.
     Centring would have to measure the container, and the container under-reports its
     own height by a gap it never draws (see `gap: 0` above); anchoring to the top
     depends on nothing but this box's own padding, and reads as deliberate whether
     the sentence runs to one line or four. */
  position: absolute; right: var(--dq-pad); top: var(--dq-pad-y);
  width: auto; margin: 0; z-index: 1;
}}
.st-key-dq_strip .stButton, .st-key-dq_strip [data-testid="stButton"] {{
  width: auto; max-width: none;
}}
.st-key-dq_strip .stButton button {{ white-space: nowrap; }}
/* Below this width the lane costs more than it is worth: the button returns to the
   flow under the sentence and both keep their full width. A truncated "Record a
   review" is worse than a taller box. */
@media (max-width: 900px) {{
  .dq-strip-box.has-action {{ padding-right: var(--dq-pad); }}
  .st-key-dq_strip [data-testid="stElementContainer"]:has(.stButton) {{
    position: static; margin-top: .5rem;
  }}
}}
.dq-strip-said {{ font-size: clamp(.79rem, .94vw, .86rem); line-height: 1.55;
  color: var(--dq-text-2); }}
.dq-strip-said b {{ color: {NEUTRAL["text"]}; font-weight: 600; }}
.dq-strip-gate {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: .71rem; color: var(--dq-text-3); margin-top: .22rem; }}
/* The back link reads as a link, not as a fourth button competing with the strip. */
.st-key-_back button {{
  border: none; background: transparent; color: var(--dq-text-2);
  padding: .1rem .2rem; min-height: 0; font-size: .78rem; justify-content: flex-start;
}}
.st-key-_back button:hover {{ background: transparent; color: {ACCENT}; }}

/* Streamlit's tabs ship at body size and full weight; at that size they compete with
   the title above them. The count rides in the label so a reader knows what is behind
   a tab before opening it. */
.stMain .stTabs [data-baseweb="tab-list"] {{ gap: .15rem; }}
.stMain .stTabs [data-baseweb="tab"] {{
  font-size: .85rem; padding: .45rem .7rem; color: var(--dq-text-2);
}}
.stMain .stTabs [aria-selected="true"] {{ font-weight: 600; }}
.dq-kvline {{ display: flex; flex-wrap: wrap; align-items: center; gap: .35rem .6rem;
  font-size: .82rem; color: var(--dq-text-2); margin-top: .3rem; }}
.dq-kvline .k {{ color: var(--dq-text-3); }}

/* --- Callout: a claim the page is making about itself. ----------------------
   Not a tooltip and not a caption. The compression ratio is the queue's whole
   argument — if it ever approaches 1:1 this page is an alert list with extra steps —
   so it is stated at the foot in prose, at reading size, where it cannot be missed
   by someone who never hovers anything. */
.dq-callout {{
  border-left: 3px solid {ACCENT}; background: {ACCENT_TINT};
  border-radius: 0 8px 8px 0; padding: .7rem .9rem;
  font-size: clamp(.78rem, .92vw, .85rem); line-height: 1.65;
  color: var(--dq-text-2); margin-top: .9rem;
}}
.dq-callout strong, .dq-callout b {{ color: {NEUTRAL["text"]}; font-weight: 600; }}

/* --- The section head: title left, controls right. ------------------------- */
.dq-sectionhd {{ display: flex; align-items: baseline; gap: .6rem; flex-wrap: wrap;
  margin: clamp(1rem, 1.5vw, 1.5rem) 0 .5rem; }}
.dq-sectionhd .t {{ font-size: clamp(.95rem, 1.1vw, 1.08rem); font-weight: 620;
  color: {NEUTRAL["text"]}; letter-spacing: -.01em; }}
.dq-sectionhd .q {{ font-size: var(--dq-fs-sub); color: var(--dq-text-3); }}

/* --- Tables: the inventory and one table opened up. --------------------------
   Redrawn 2026-10-06. The detail page's two lower cards are the scorecard's
   (`dq_elcard`, `dq_elpane`) and take their CSS from there; what is here is what the
   two Tables pages have that the scorecard does not. */
.st-key-monitor_list_filter_strip {{ padding: .55rem var(--dq-pad); }}
.st-key-monitor_list_filter_strip .dq-strip-lab,
.st-key-monitor_list_filter_strip .dq-strip-note {{ padding-top: 0; }}
/* Streamlit's -1rem under a markdown box would leave each label 1rem below the
   control it names, in a row centred on the controls. */
.st-key-monitor_list_filter_strip [data-testid="stMarkdownContainer"] {{ margin-bottom: 0; }}
/* Wraps rather than squeezes: a label keeps its own width, a control keeps 9rem, and
   whatever does not fit goes to the next line. Matched by what each column holds. */
.st-key-monitor_list_filter_strip [data-testid="stHorizontalBlock"] {{
  flex-wrap: wrap; row-gap: .4rem; }}
.st-key-monitor_list_filter_strip [data-testid="stColumn"]:has(.dq-strip-lab) {{
  flex: 0 0 auto !important; width: auto !important; min-width: 0; }}
.st-key-monitor_list_filter_strip [data-testid="stColumn"]:has([data-testid="stSelectbox"]) {{
  flex: 1 1 9rem !important; min-width: 9rem; max-width: 16rem; }}
.st-key-monitor_list_filter_strip [data-testid="stColumn"]:has(.dq-strip-note) {{
  flex: 10 1 12rem !important; min-width: 12rem; }}
.dq-tm-last .dq-dot {{ width: 8px; height: 8px; margin-right: .45rem; }}
/* Four figures in one card, divided by hairlines. One block of markup holding a grid:
   no wrappers to equalise, and it wraps two-by-two on a narrow page. */
.dq-tmkpi {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr));
  border: 1px solid var(--dq-border); border-radius: 10px;
  background: {NEUTRAL["surface"]}; margin-bottom: clamp(.8rem, 1.4vw, 1.2rem); }}
.dq-tmkpi .f {{ padding: clamp(.8rem, 1.3vw, 1.15rem) clamp(.9rem, 1.6vw, 1.6rem); }}
.dq-tmkpi .f + .f {{ border-left: 1px solid var(--dq-border); }}
.dq-tmkpi .l {{ font-size: clamp(.76rem, .9vw, .84rem); color: var(--dq-text-2);
  display: flex; align-items: center; }}
.dq-tmkpi .v {{ font-size: clamp(1.5rem, 2.2vw, 2rem); font-weight: 650;
  color: {NEUTRAL["text"]}; margin-top: .35rem; line-height: 1.1;
  font-variant-numeric: tabular-nums; }}
.dq-tmkpi .v .of {{ font-size: .8em; font-weight: 450; color: var(--dq-text-3); }}
@media (max-width: 760px) {{
  .dq-tmkpi {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
  .dq-tmkpi .f:nth-child(3) {{ border-left: none; }}
  .dq-tmkpi .f:nth-child(n+3) {{ border-top: 1px solid var(--dq-border); }}
}}

/* The table card: a keyed container, because its header holds a search field and a
   switch and its body is clickable rows. Same construction as `dq_elcard`. */
.st-key-dq_tmcard {{ border: 1px solid var(--dq-border); border-radius: 10px;
  background: {NEUTRAL["surface"]}; gap: 0; padding: 0; overflow: hidden; }}
.st-key-dq_tmcard [data-testid="stMarkdownContainer"] {{ margin-bottom: 0; }}
.st-key-dq_tmcard > [data-testid="stLayoutWrapper"]:first-child,
.st-key-dq_tmcard > [data-testid="stHorizontalBlock"]:first-child {{
  padding: clamp(.8rem, 1.2vw, 1.05rem) 1rem .7rem; }}
/* The header row wraps the same way: title, then search and switch, each with a floor. */
.st-key-dq_tmcard [data-testid="stHorizontalBlock"] {{ flex-wrap: wrap; row-gap: .5rem; }}
.st-key-dq_tmcard [data-testid="stColumn"]:has(.dq-tmcard-hd) {{
  flex: 1 1 13rem !important; min-width: 13rem; }}
.st-key-dq_tmcard [data-testid="stColumn"]:has([data-testid="stTextInput"]):has([data-testid="stButtonGroup"]) {{
  flex: 1.6 1 21rem !important; min-width: min(21rem, 100%); }}
.st-key-dq_tmcard [data-testid="stColumn"]:has([data-testid="stTextInput"]):not(:has([data-testid="stButtonGroup"])) {{
  flex: 1 1 10rem !important; min-width: 10rem; }}
.st-key-dq_tmcard [data-testid="stColumn"]:has([data-testid="stButtonGroup"]):not(:has([data-testid="stTextInput"])) {{
  flex: 0 0 auto !important; width: auto !important; min-width: 0; }}
.dq-tmcard-hd .t {{ font-size: clamp(.98rem, 1.15vw, 1.1rem); font-weight: 650;
  color: {NEUTRAL["text"]}; display: flex; align-items: center; gap: .5rem; }}
.dq-tmcard-hd .q {{ font-size: clamp(.76rem, .9vw, .84rem); color: var(--dq-text-2);
  margin-top: .2rem; }}
.dq-count {{ font-size: .74rem; font-weight: 600; color: {ACCENT};
  background: {ACCENT_TINT}; border-radius: 999px; padding: .05rem .5rem; }}
.st-key-dq_tmcard .dq-rowgrid.head {{ background: {NEUTRAL["canvas"]};
  border-top: 1px solid var(--dq-border); padding: .55rem 1rem; }}
.st-key-dq_tmcard .st-key-dqrows_tables {{ border: none; border-radius: 0;
  border-top: 1px solid var(--dq-border); }}
.st-key-dqrows_tables [class*="st-key-dqrow_"] {{ border-radius: 0 !important;
  min-height: 4.6rem; }}
.st-key-dqrows_tables .dq-rowgrid {{ padding: .7rem 1rem; gap: .9rem; }}
/* The status stripe: the row's urgency on its left edge, in the status tone. */
.dq-tmname {{ border-left: 4px solid var(--dq-stripe); border-radius: 2px;
  padding-left: .75rem; }}
.dq-tmname .t1 {{ display: flex; align-items: center; gap: .5rem; }}
.st-key-dqrows_tables .stack .t1.big {{ font-size: clamp(.95rem, 1.15vw, 1.1rem);
  font-weight: 650; font-variant-numeric: tabular-nums; }}
.st-key-dqrows_tables .dq-meter {{ margin-top: .3rem; max-width: 10rem; }}
.st-key-dqrows_tables .dq-spark {{ width: 100%; max-width: 9rem; height: 22px; }}
.st-key-dqrows_tables .num {{ font-size: clamp(.82rem, .98vw, .92rem); }}
.st-key-dqrows_tables .num.lft {{ text-align: left; display: flex; align-items: center;
  gap: .45rem; }}
/* Below this width the trend and the owner go: the rows keep the figures someone
   acts on, and the owner is on the detail page. The grid is set inline per row, so
   the override has to be `!important`. */
@media (max-width: 1180px) {{
  .st-key-dq_tmcard .dq-rowgrid {{
    grid-template-columns: minmax(8rem,1.4fr) minmax(6rem,1fr) minmax(5.5rem,.9fr)
      minmax(3.5rem,.5fr) 1rem !important; }}
  .st-key-dq_tmcard .dq-rowgrid > :nth-child(3),
  .st-key-dq_tmcard .dq-rowgrid > :nth-child(6) {{ display: none; }}
}}
.dq-owner {{ display: flex; align-items: center; gap: .55rem;
  font-size: clamp(.78rem, .92vw, .86rem); color: {NEUTRAL["text"]}; }}
.dq-owner i {{ flex: none; width: 2rem; height: 2rem; border-radius: 50%;
  background: {ACCENT_TINT}; color: {ACCENT}; font-style: normal; font-size: .72rem;
  font-weight: 600; display: inline-flex; align-items: center; justify-content: center; }}
.st-key-dq_tmcard [data-testid="stElementContainer"]:has([data-testid="stButtonGroup"]) {{
  display: flex; justify-content: flex-end; }}
.dq-tmempty {{ padding: 1rem; font-size: .84rem; color: var(--dq-text-3);
  border-top: 1px solid var(--dq-border); }}
.dq-tmfoot {{ display: flex; justify-content: space-between; flex-wrap: wrap;
  gap: .3rem 1rem; padding: .6rem .1rem 0; font-size: var(--dq-fs-sub);
  color: var(--dq-text-2); }}
.dq-tmfoot > span {{ display: inline-flex; align-items: center; gap: .35rem; }}

/* The two cards under the list. */
.dq-tmhealth {{ margin-top: clamp(.9rem, 1.6vw, 1.5rem); }}
.dq-tmhealth .ttl {{ justify-content: flex-start; margin-bottom: .1rem;
  font-size: clamp(.95rem, 1.1vw, 1.05rem); }}
.dq-tmhealth .q, .st-key-dq_tmstart .q {{ font-size: clamp(.78rem, .92vw, .86rem);
  color: var(--dq-text-2); }}
.st-key-dq_tmstart {{ border: 1px solid var(--dq-border); border-radius: 8px;
  background: {NEUTRAL["surface"]}; padding: var(--dq-pad-y) var(--dq-pad);
  margin-top: clamp(.9rem, 1.6vw, 1.5rem); gap: .35rem; }}
.st-key-dq_tmstart [data-testid="stMarkdownContainer"] {{ margin-bottom: 0; }}
.st-key-dq_tmstart .t {{ font-size: clamp(.95rem, 1.1vw, 1.05rem); font-weight: 620;
  color: {NEUTRAL["text"]}; margin-bottom: .45rem; }}
.st-key-dq_tmstart .q b {{ color: {TONE["critical"]["fg"]}; font-weight: 550; }}
.st-key-dq_tmstart .stButton button {{ color: {ACCENT}; padding-left: 0; }}

/* --- The Rules page: three cards, CDEs | Rules | one rule. Redrawn 2026-10-06. ---
   Same construction as the scorecard's lower cards: the border is on the keyed
   container, its stacking gap is zero (Streamlit counts it against the height
   whether or not it is drawn), and each block brings its own padding. The two lists
   and the detail tabs are fixed-height boxes, so the three floors meet; the
   stretch below is the backstop for a header that wraps. */
.st-key-dq_rcde, .st-key-dq_rrules, .st-key-dq_rdetail {{
  border: 1px solid var(--dq-border); border-radius: 10px;
  background: {NEUTRAL["surface"]}; gap: 0; padding: 0; flex: 1 1 auto; }}
.st-key-dq_rcde [data-testid="stMarkdownContainer"],
.st-key-dq_rrules [data-testid="stMarkdownContainer"],
.st-key-dq_rdetail [data-testid="stMarkdownContainer"] {{ margin-bottom: 0; }}
.st-key-dq_rsplit {{ margin-top: clamp(.8rem, 1.6vw, 1.4rem); }}
.st-key-dq_rsplit [data-testid="stHorizontalBlock"] {{ flex-wrap: wrap;
  align-items: stretch; row-gap: .8rem; }}
.st-key-dq_rsplit [data-testid="stColumn"] {{ display: flex; flex-direction: column; }}
.st-key-dq_rsplit [data-testid="stColumn"] > [data-testid="stVerticalBlock"],
[data-testid="stLayoutWrapper"]:is(:has(> .st-key-dq_rcde), :has(> .st-key-dq_rrules),
  :has(> .st-key-dq_rdetail)) {{ flex: 1 1 auto; }}
.st-key-dq_rsplit [data-testid="stColumn"]:has(.st-key-dq_rcde),
.st-key-dq_rsplit [data-testid="stColumn"]:has(.st-key-dq_rrules) {{
  flex: 1 1 14rem !important; min-width: min(15rem, 100%); }}
.st-key-dq_rsplit [data-testid="stColumn"]:has(.st-key-dq_rdetail) {{
  flex: 2.2 1 26rem !important; min-width: min(26rem, 100%); }}
.dq-rcard-hd {{ display: flex; align-items: center; gap: .5rem; padding: 1rem 1rem .7rem; }}
.dq-rcard-hd .t {{ font-size: clamp(1rem, 1.2vw, 1.12rem); font-weight: 650;
  color: {NEUTRAL["text"]}; }}
.dq-count {{ font-size: .74rem; font-weight: 600; color: {ACCENT}; background: {ACCENT_TINT};
  border-radius: 999px; padding: .08rem .5rem; font-variant-numeric: tabular-nums; }}
.st-key-dq_rcde [data-testid="stElementContainer"]:has(:is(input, [data-baseweb="select"])),
.st-key-dq_rrules [data-testid="stElementContainer"]:has(input) {{ padding: 0 1rem .6rem; }}
.st-key-dqrows_rcde, .st-key-dqrows_rrules {{ border-top: 1px solid var(--dq-border);
  scrollbar-gutter: auto; }}
.st-key-dq_rcde [class*="st-key-dqrow_"], .st-key-dq_rrules [class*="st-key-dqrow_"] {{
  border-radius: 0 !important; }}
/* A list row: name over a muted line, the badge on the right. The picked row
   carries the accent down its left edge, as the mock does. */
.dq-rr {{ display: flex; align-items: center; justify-content: space-between; gap: .6rem;
  min-width: 0; }}
.dq-rr .a {{ display: flex; flex-direction: column; gap: .2rem; min-width: 0; }}
/* The name wraps to two lines, as the mock's do, and is cut after that; the row
   container grows with it (measured: the row tracks its grid). The muted line stays
   on one. */
.dq-rr .nm {{ font-size: clamp(.82rem, .96vw, .9rem); font-weight: 500;
  color: {NEUTRAL["text"]}; line-height: 1.35; display: -webkit-box;
  -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }}
.dq-rr .q {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.dq-rr .q {{ font-size: clamp(.72rem, .85vw, .79rem); color: var(--dq-text-2); }}
.dq-rr .dq-badge {{ flex: none; }}
[class*="st-key-dqrow_"]:has(.dq-rr) {{ min-height: 4.1rem; }}
[class*="st-key-dqrow_"] .dq-rowgrid:has(.dq-rr) {{ padding: .7rem 1rem;
  border-left: 3px solid transparent; }}
[class*="st-key-dqrow_"] .dq-rowgrid.dq-row-on:has(.dq-rr) {{ border-left-color: {ACCENT}; }}
.st-key-dq_rpager {{ border-top: 1px solid var(--dq-border); padding: .6rem 1rem;
  justify-content: space-between; gap: .4rem; margin-top: auto; flex-wrap: nowrap; }}
.st-key-dq_rpager > [data-testid="stElementContainer"] {{ width: auto !important;
  flex: none; }}
.st-key-dq_rpager .stButton button {{ min-height: 2rem; padding: 0 .45rem; }}
.st-key-dq_rpager .stButton button p {{ display: none; }}
.dq-rpage {{ font-size: var(--dq-fs-sub); color: var(--dq-text-2); flex: 1 1 auto; }}
.st-key-dq_rpager > [data-testid="stElementContainer"]:has(.dq-rpage) {{
  flex: 1 1 0; min-width: 0; }}

/* The detail card. */
.dq-rdet-hd {{ padding: 1rem 1.1rem .4rem; }}
.dq-rdet-hd .k {{ font-size: .68rem; letter-spacing: .09em; text-transform: uppercase;
  color: var(--dq-text-3); font-weight: 600; }}
.dq-rdet-hd .n {{ font-size: clamp(1.15rem, 1.6vw, 1.45rem); font-weight: 650;
  color: {NEUTRAL["text"]}; margin-top: .25rem; letter-spacing: -.01em; line-height: 1.3; }}
.dq-rdet-hd .b {{ margin-top: .45rem; display: flex; flex-wrap: wrap; align-items: center;
  gap: .35rem; }}
.dq-rdet-hd .id {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: .72rem; color: var(--dq-text-3); margin-left: .2rem; }}
.dq-rstats {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr));
  padding: .6rem 1.1rem .9rem; gap: .6rem 0; }}
.dq-rstats > div {{ display: flex; flex-direction: column; gap: .2rem; min-width: 0;
  padding: 0 .9rem; }}
.dq-rstats > div:first-child {{ padding-left: 0; }}
.dq-rstats > div + div {{ border-left: 1px solid var(--dq-border); }}
.dq-rstats .l {{ font-size: var(--dq-fs-sub); color: var(--dq-text-2); }}
.dq-rstats b {{ font-size: clamp(1.05rem, 1.45vw, 1.5rem); font-weight: 650;
  color: {NEUTRAL["text"]}; font-variant-numeric: tabular-nums; line-height: 1.15;
  white-space: nowrap; }}
.dq-rstats b .of {{ font-weight: 400; color: var(--dq-text-2); }}
.dq-rstats > div:last-child b {{ font-size: clamp(.92rem, 1.15vw, 1.2rem); font-weight: 500;
  line-height: 1.5; }}
.dq-rstats .s {{ font-size: .72rem; color: var(--dq-text-3); }}
@media (max-width: 1100px) {{
  .dq-rstats {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
  .dq-rstats > div:nth-child(3) {{ padding-left: 0; border-left: none; }}
}}
.st-key-dq_rdetail [data-testid="stElementContainer"]:has(.st-key-_promote_open),
.st-key-dq_rdetail .stElementContainer:has(button[kind="primary"]) {{ padding: 0 1.1rem .7rem; }}
.st-key-dq_rdetail .stTabs [role="tablist"] {{ padding: 0 1.1rem; }}
.st-key-dq_rdetail .stTabs [data-testid="stTabPanel"] {{ padding-top: 0; }}
.st-key-dq_rtab_def, .st-key-dq_rtab_rows, .st-key-dq_rtab_hist {{
  padding: .9rem 1.1rem .7rem; gap: .55rem; }}
.dq-rsec {{ font-size: clamp(.92rem, 1.08vw, 1rem); font-weight: 650;
  color: {NEUTRAL["text"]}; margin-top: .35rem; }}
.dq-rsec .sub {{ display: block; font-size: var(--dq-fs-sub); font-weight: 400;
  color: var(--dq-text-2); margin-top: .1rem; }}
.dq-rsec.row {{ display: flex; justify-content: space-between; align-items: center; }}
.dq-rchip {{ font-size: .74rem; font-weight: 500; color: var(--dq-text-2);
  border: 1px solid var(--dq-border); border-radius: 6px; padding: .18rem .55rem; }}
.dq-rscope {{ display: flex; flex-wrap: wrap; justify-content: space-between; gap: .3rem 1rem;
  background: {NEUTRAL["canvas"]}; border-radius: 8px; padding: .6rem .85rem;
  margin-top: .6rem; font-size: clamp(.78rem, .92vw, .86rem); color: {NEUTRAL["text"]}; }}
.dq-rscope > span + span {{ color: var(--dq-text-2); }}
.dq-rscope code, .dq-rwarn code {{ font-size: .92em; overflow-wrap: anywhere; }}
.dq-rwarn {{ margin-top: .5rem; font-size: clamp(.78rem, .92vw, .86rem); line-height: 1.5;
  color: var(--dq-text-2); border-left: 3px solid {TONE["high"]["fg"]}; padding: .1rem .7rem; }}
.st-key-dq_rdetail [data-testid="stCode"] pre {{ font-size: .76rem; }}
.st-key-dq_rctl {{ gap: .4rem; }}
.st-key-dq_rctl [data-testid="stMarkdownContainer"] {{ margin-bottom: 0; }}
.dq-rhead .m .fq {{ font-size: .8rem; }}
/* A long rule name wraps; the badge rides on its last line rather than floating
   off to the right of a two-line flex item. */
.dq-tmhead.dq-rhead .n {{ display: block; }}
.dq-tmhead.dq-rhead .n .dq-badge {{ margin-left: .6rem; vertical-align: .3rem; }}
[data-testid="stColumn"]:has(> [data-testid="stVerticalBlock"] .st-key-dq_rctl) {{
  flex: 1.4 1 14rem !important; min-width: min(14rem, 100%); }}

/* The detail page's header. */
.st-key-dq_tmcrumb {{ gap: .35rem; margin-bottom: -.4rem; }}
.st-key-dq_tmcrumb .stButton button {{ color: var(--dq-text-2); font-size: .84rem;
  padding: 0; min-height: 0; }}
.st-key-dq_tmcrumb .stButton button:hover {{ color: {ACCENT}; }}
.dq-crumb {{ font-size: .84rem; color: var(--dq-text-2); }}
.dq-tmhead .n {{ font-size: clamp(1.4rem, 2vw, 1.75rem); font-weight: 650;
  color: {NEUTRAL["text"]}; display: flex; align-items: center; gap: .6rem;
  line-height: 1.35; letter-spacing: -.01em; }}
.dq-tmhead .fq {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: .78rem; color: var(--dq-text-3); margin-top: .1rem; }}
.dq-tmhead .m {{ font-size: .84rem; color: var(--dq-text-2); margin-top: .3rem; }}
.dq-tmrun {{ font-size: var(--dq-fs-sub); color: var(--dq-text-2); text-align: right;
  margin-top: -.3rem; }}
.st-key-dq_tmctl {{ gap: .5rem; }}
/* The header and the top two cards wrap rather than squeeze, as the lower two do. */
[data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] .dq-tmhead),
[data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] .dq-tmsum) {{
  flex-wrap: wrap; row-gap: .8rem; }}
[data-testid="stColumn"]:has(.dq-tmhead) {{ flex: 3 1 16rem !important; min-width: 16rem; }}
[data-testid="stColumn"]:has(> [data-testid="stVerticalBlock"] .st-key-dq_tmctl) {{
  flex: 1.5 1 16rem !important; min-width: min(16rem, 100%); }}
[data-testid="stColumn"]:has(.dq-hero):not(:has(.dq-tmsum)) {{
  flex: 2.2 1 24rem !important; min-width: min(24rem, 100%); }}
[data-testid="stColumn"]:has(.dq-tmsum) {{ flex: 1 1 15rem !important;
  min-width: min(15rem, 100%); }}
.st-key-dq_tmctl [data-testid="stMarkdownContainer"] {{ margin-bottom: 0; }}

/* The run summary: label left, figure right, one rule per line. */
.dq-tmsum .r {{ display: flex; justify-content: space-between; align-items: baseline;
  padding: .55rem 0; border-bottom: 1px solid var(--dq-border);
  font-size: clamp(.82rem, .98vw, .92rem); color: var(--dq-text-2); }}
.dq-tmsum .r b {{ color: {NEUTRAL["text"]}; font-weight: 620;
  font-variant-numeric: tabular-nums; }}
.dq-tmsum .gap {{ flex: 1 1 auto; min-height: .6rem; }}
.dq-tmsum .gap + .r {{ border-top: 1px solid var(--dq-border); border-bottom: none; }}
.dq-tmsum .ft {{ font-size: var(--dq-fs-sub); color: var(--dq-text-3); margin-top: .4rem; }}

/* The rule pane. */
.dq-tmverdict {{ font-size: clamp(.78rem, .92vw, .86rem); color: var(--dq-text-2);
  margin-top: .2rem; }}
.dq-tmrates {{ display: grid; grid-template-columns: 1fr 1fr; margin-top: .6rem; }}
.dq-tmrates > div {{ display: flex; flex-direction: column; gap: .15rem; }}
.dq-tmrates > div + div {{ border-left: 1px solid var(--dq-border); padding-left: 1rem; }}
.dq-tmrates span {{ font-size: var(--dq-fs-sub); color: var(--dq-text-2); }}
.dq-tmrates b {{ font-size: clamp(1.1rem, 1.4vw, 1.3rem); font-weight: 650;
  color: {NEUTRAL["text"]}; font-variant-numeric: tabular-nums; }}
.st-key-dq_tmalert {{ background: {TONE["critical"]["bg"]};
  border: 1px solid {TONE["critical"]["bd"]}; border-radius: 8px;
  padding: .45rem .5rem .45rem .8rem; flex-wrap: nowrap; }}
.st-key-dq_tmalert:has(.grey) {{ background: {NEUTRAL["canvas"]};
  border-color: var(--dq-border); }}
.st-key-dq_tmalert [data-testid="stElementContainer"]:has(.dq-tmalert) {{ flex: 1 1 auto;
  min-width: 0; }}
.st-key-dq_tmalert [data-testid="stMarkdownContainer"] {{ margin-bottom: 0; }}
.dq-tmalert {{ display: flex; align-items: center; gap: .55rem;
  font-size: clamp(.78rem, .92vw, .86rem); color: {TONE["critical"]["fg"]}; }}
.dq-tmalert.grey {{ color: var(--dq-text-2); }}
.dq-tmalert > svg {{ flex: none; }}
.st-key-dq_tmalert .stButton button {{ background: {NEUTRAL["surface"]};
  border-color: {ACCENT}; color: {ACCENT}; white-space: nowrap; }}

</style>
"""


def inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def section(label: str) -> None:
    st.markdown(f'<div class="dq-section">{label}</div>', unsafe_allow_html=True)


def kpi(label: str, value: str, sub: str = "", tone: str | None = None) -> str:
    colour = f'style="color:{TONE[tone]["fg"]}"' if tone else ""
    return (
        f'<div class="dq-kpi"><div class="lab">{label}</div>'
        f'<div class="val" {colour}>{value}</div>'
        + (f'<div class="sub">{sub}</div>' if sub else "")
        + "</div>"
    )


def kv(key: str, value) -> str:
    return f'<div class="dq-kv"><span class="k">{key}</span><span class="v">{value}</span></div>'

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

def trend_chart(points: list[tuple], y_lo: float = 0.0, y_hi: float = 100.0) -> str:
    """The headline figure's own history, drawn as a filled line under it.

    A different drawing from `area_chart`, and deliberately: that one carries a value
    axis and gridlines because it is read for a level. This one sits directly beneath
    the number it belongs to, where the level is already on the page in 40px type, so
    the only thing left to say is the shape and where the two ends sit. Gridlines and
    a repeated y-axis at that size are noise, and the axis labels were competing with
    the figure for the reader's first look.

    Both ends are labelled with their date AND their value, so the chart still answers
    "from what, to what" without a hover — nothing in a Streamlit markdown block can
    be hovered for a tooltip.

    The end dot is red when the series finished below where it started. That is the
    one place colour carries anything here, and it is doubled by the signed delta
    written beside the figure above.
    """
    vals = [v for _, v in points if v is not None]
    if len(vals) < 2:
        return '<div class="dq-quiet">Not enough history to draw a trend.</div>'

    w, h = 560.0, 126.0
    pad_l, pad_r, pad_t, pad_b = 6.0, 6.0, 10.0, 22.0
    span = (y_hi - y_lo) or 1.0
    plot_w, plot_h = w - pad_l - pad_r, h - pad_t - pad_b
    step = plot_w / (len(points) - 1)

    coords = [
        (pad_l + i * step,
         pad_t + plot_h - (float(v) - y_lo) / span * plot_h)
        for i, (_, v) in enumerate(points)
    ]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    floor = pad_t + plot_h
    area = (f"{coords[0][0]:.1f},{floor:.1f} " + line
            + f" {coords[-1][0]:.1f},{floor:.1f}")

    fell = vals[-1] < vals[0]
    end = TONE["critical"]["fg"] if fell else ACCENT
    first_lab = f"{points[0][0]} {pct_text(vals[0], 1)}%"
    last_lab = f"{points[-1][0]} {pct_text(vals[-1], 1)}%"
    lx, ly = coords[-1]

    return (
        f'<svg viewBox="0 0 {w:.0f} {h:.0f}" class="dq-trend" role="img" '
        f'aria-label="Quality from {html.escape(first_lab)} to {html.escape(last_lab)}">'
        f'<defs><linearGradient id="dqTrendFill" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0%" stop-color="{ACCENT}" stop-opacity=".22"/>'
        f'<stop offset="100%" stop-color="{ACCENT}" stop-opacity=".02"/>'
        "</linearGradient></defs>"
        f'<polygon points="{area}" fill="url(#dqTrendFill)"/>'
        f'<polyline points="{line}" fill="none" stroke="{ACCENT}" stroke-width="2" '
        'stroke-linejoin="round" stroke-linecap="round"/>'
        f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="3.4" fill="{end}"/>'
        f'<text x="{pad_l:.1f}" y="{h - 6:.1f}" text-anchor="start" class="ax">'
        f"{html.escape(first_lab)}</text>"
        f'<text x="{w - pad_r:.1f}" y="{h - 6:.1f}" text-anchor="end" class="ax">'
        f"{html.escape(last_lab)}</text>"
        "</svg>"
    )


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

.dq-monitor-hd {{
  display: flex; align-items: center; justify-content: space-between; gap: .75rem;
  margin: .85rem 0 .1rem; padding-top: .15rem;
}}
.dq-monitor-hd > span:first-child {{
  display: inline-flex; align-items: center; gap: .38rem;
  font-size: .96rem; font-weight: 600; color: {NEUTRAL["text"]};
}}
.st-key-scorecard_monitor_inventory [data-testid="stDataFrame"],
.st-key-monitors_inventory [data-testid="stDataFrame"] {{
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
.dq-dimgrp {{ display: flex; align-items: center; gap: .45rem; flex-wrap: wrap;
  margin: .9rem 0 .35rem; font-size: .92rem; color: {NEUTRAL["text"]}; }}
.dq-dimgrp .q {{ font-size: .78rem; color: var(--dq-text-2); font-weight: 400; }}
.dq-note {{ font-size: .82rem; color: var(--dq-text-2); line-height: 1.55;
  margin: .5rem 0 .2rem; }}
.dq-note .dq-badge {{ margin-right: .3rem; }}

/* --- Page header: title on the left, page-level actions on the right. ----- */
.dq-page-hd {{ margin-bottom: .45rem; }}
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
.st-key-monitor_list_filter_strip,
.st-key-monitor_detail_filter_strip {{
  border: 1px solid var(--dq-border); border-radius: 8px;
  background: {NEUTRAL["surface"]}; padding: var(--dq-pad-y) var(--dq-pad) .1rem;
  margin: .35rem 0 var(--dq-pad);
}}
.st-key-dq_filter_strip [data-testid="stVerticalBlock"],
.st-key-monitor_list_filter_strip [data-testid="stVerticalBlock"],
.st-key-monitor_detail_filter_strip [data-testid="stVerticalBlock"] {{ gap: .2rem; }}
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

/* --- Hero: the headline figure with its own history under it. --------------
   It used to lay out across the card — figure on the left, chart on the right — and
   the chart got whatever width the figure did not need, which at this column width
   was about 180px for a month of runs. Stacked, the chart gets the full card and the
   figure gets the full type size, and the reading order matches the sentence: how
   good, out of what, and which way it has been going. */
.dq-hero {{ flex-direction: column; gap: 0; justify-content: flex-start;
  min-height: clamp(9rem, 12vw, 11.5rem); }}
.dq-hero .lab {{ font-size: .68rem; letter-spacing: .09em; text-transform: uppercase;
  color: var(--dq-text-3); font-weight: 600;
  display: flex; align-items: center; gap: .35rem; }}
.dq-hero .val {{ font-size: var(--dq-fs-hero); margin-top: .35rem; }}
.dq-hero .sub {{ font-size: clamp(.72rem, .86vw, .8rem); color: var(--dq-text-2);
  margin-top: .4rem; line-height: 1.55; }}
/* The chart sits on the card floor whatever the subline above it wrapped to, so the
   hero and the tile grid beside it keep the same outside height. */
.dq-trend {{ width: 100%; height: auto; display: block; margin-top: auto;
  padding-top: .6rem; overflow: visible; }}
.dq-trend .ax {{ font-size: 11px; fill: {NEUTRAL["text_3"]};
  font-family: inherit; font-variant-numeric: tabular-nums; }}
.dq-area {{ width: 100%; height: clamp(76px, 7vw, 108px); display: block; }}
.dq-area .ax {{ font-size: 9px; fill: {NEUTRAL["text_3"]};
  font-family: inherit; font-variant-numeric: tabular-nums; }}

/* --- What is being watched: six counts of the estate. -----------------------
   One markdown block holding a CSS grid, NOT two rows of st.columns. The columns
   version is what put the tiles on top of the search field below them: the
   equal-height rule further down makes every wrapper inside a card row a flex item
   with min-height:0, and the two nested column rows inside the tile column were
   flex items themselves — so they shrank below their content and the content spilled
   out of the bottom of the block. A grid has no wrappers to shrink, and it equalises
   the six heights for free, which is what the flex rule was there to do. */
.dq-watch {{ display: flex; flex-direction: column; height: 100%; min-width: 0; }}
.dq-watch .hd {{ font-size: .68rem; letter-spacing: .09em; text-transform: uppercase;
  color: var(--dq-text-3); font-weight: 600; padding: .1rem 0 .45rem;
  display: flex; align-items: baseline; gap: .5rem; flex-wrap: wrap; }}
/* The denominator note rides in the heading, in sentence case, because the two
   figures beside each other — 20 scored, 34 run — are the single thing a reader is
   most likely to think is a bug on this page. */
.dq-watch .hd .q {{ font-size: .72rem; letter-spacing: 0; text-transform: none;
  font-weight: 400; color: var(--dq-text-3); }}
.dq-tilegrid {{ flex: 1 1 auto; display: grid; gap: clamp(.45rem, .7vw, .7rem);
  grid-template-columns: repeat(3, minmax(0, 1fr)); }}
/* On the scorecard the tile labels reserve two lines so six figures line up across
   a row. In the drawer there are two tiles and every label is one line, so the
   reserved second line is just a gap above the number. */
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
/* The tags on that second line are words, not colours — "recurrence", "checks
   breaching again". The tint is the second channel; the phrase is the first. */
.dq-rowgrid .stack .t2 .mark {{ font-weight: 600; }}
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
[class*="st-key-dqrow_"] .stButton button {{
  height: 100%; width: 100%; opacity: 0; padding: 0; min-height: 0;
  border: none; background: transparent; cursor: pointer;
}}
[class*="st-key-dqrow_"] .stButton button:focus-visible {{
  opacity: 1; background: transparent; color: transparent;
  outline: 2px solid {ACCENT}; outline-offset: -2px; border-radius: 6px;
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

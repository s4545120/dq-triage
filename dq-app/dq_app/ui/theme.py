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
# Cool neutral scale with one petrol accent. Deliberately not the violet-forward
# palette the well-known DQ suites use — same design language, different signature.

NEUTRAL = {
    "canvas": "#f6f7f9",
    "surface": "#ffffff",
    "border": "#e4e7ec",
    "border_strong": "#d0d5dd",
    "text": "#101828",
    "text_2": "#475467",
    "text_3": "#98a2b3",
}

ACCENT = "#0d5c73"
ACCENT_TINT = "#e8f1f4"

# Reserved. Never reused as a chart series colour.
TONE = {
    "critical": {"fg": "#b42318", "bg": "#fef3f2", "bd": "#fecdca"},
    "high":     {"fg": "#c4320a", "bg": "#fff4ed", "bd": "#f9dbaf"},
    "moderate": {"fg": "#a15c07", "bg": "#fefbe8", "bd": "#feee95"},
    "success":  {"fg": "#067647", "bg": "#ecfdf3", "bd": "#abefc6"},
    "info":     {"fg": ACCENT,    "bg": ACCENT_TINT, "bd": "#b9d6de"},
    "neutral":  {"fg": "#475467", "bg": "#f2f4f7", "bd": "#e4e7ec"},
}

# Categorical slots for charts — fixed order, never cycled, never a ninth.
SERIES = [
    "#0d5c73", "#c4320a", "#2e6f9e", "#a15c07",
    "#6941c6", "#067647", "#b42318", "#475467",
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


def hint(text: str) -> str:
    """An inline explanation mark carrying its own tooltip.

    `st.markdown(..., help=)` renders its icon absolutely positioned at the top-right
    of the *element*, which for a bordered card lands on the border — a row of cards
    ends up with loose dots sitting in the gaps between them. Anything drawn as a card
    carries its explanation through this instead, inside the header where it reads as
    part of the card. Plain Streamlit widgets keep using `help=`, which places it
    correctly for them.
    """
    return (
        f'<span class="dq-hint" title="{html.escape(text)}">{icon("info", 12)}</span>'
    )


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
.dq-spark {{ vertical-align: middle; display: block; }}

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
.dq-hint {{ color: var(--dq-text-3); display: inline-flex; cursor: help; flex: none; }}
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
[data-testid="stHorizontalBlock"]:is(:has(.dq-stat), :has(.dq-dim))
  > [data-testid="stColumn"] {{
  /* becomes a flex container, but keeps the width basis that sets the column ratios */
  display: flex; flex-direction: column;
}}
[data-testid="stHorizontalBlock"]:is(:has(.dq-stat), :has(.dq-dim)) :is(
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

/* --- Hero: headline score beside its own trend. --------------------------- */
/* .dq-card lays out down the page; the hero is the one card that lays out
   across it, so it has to say so or it inherits the column direction. */
.dq-hero {{ flex-direction: row; gap: clamp(.7rem, 1.4vw, 1.4rem);
  align-items: stretch; min-height: clamp(7rem, 9.2vw, 8.6rem); }}
.dq-hero .l {{ flex: 0 0 clamp(8.4rem, 11vw, 11.5rem); display: flex;
  flex-direction: column; min-width: 0; }}
.dq-hero .r {{ flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column; }}
.dq-hero .val {{ font-size: var(--dq-fs-hero); margin-top: .15rem; }}
.dq-hero .rl {{ font-size: var(--dq-fs-sub); color: var(--dq-text-3); text-align: right; }}
.dq-area {{ width: 100%; height: clamp(76px, 7vw, 108px); display: block; }}
.dq-area .ax {{ font-size: 9px; fill: {NEUTRAL["text_3"]};
  font-family: inherit; font-variant-numeric: tabular-nums; }}

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

/* Scale is clamp()'s job; REFLOW still needs a breakpoint. Below ~1250px the board
   and the rail beside it cannot both hold their content — the finding badge and the
   Review button get cut off — and no amount of proportional padding fixes that. One
   breakpoint, and the rail drops under the board at full width. */
@media (max-width: 1250px) {{
  [data-testid="stHorizontalBlock"]:has(.st-key-dq_issue_board) {{ flex-wrap: wrap; }}
  [data-testid="stHorizontalBlock"]:has(.st-key-dq_issue_board)
    > [data-testid="stColumn"] {{
    flex: 1 1 100%; width: 100%; max-width: 100%; min-width: 0;
  }}
}}

/* --- The issue list ------------------------------------------------------- */
/* Rows are real Streamlit columns rather than a table, because the last cell is a
   button and a button cannot live inside markup we generate. The borders and the
   tightened gaps are what make a stack of column rows read as a table anyway. */
.st-key-dq_issue_board {{
  border: 1px solid var(--dq-border); border-radius: 8px;
  background: {NEUTRAL["surface"]};
  padding: var(--dq-pad-y) var(--dq-pad) calc(var(--dq-pad-y) + .2rem);
}}
.st-key-dq_issue_board [data-testid="stHorizontalBlock"] {{
  gap: clamp(.35rem, .6vw, .65rem); align-items: center; }}
/* No border-bottom here: a border per column is drawn per column, and the gaps
   between them cut the rule into segments. The header line is one full-width
   .dq-rowline emitted after the header cells. */
.dq-th {{ font-size: clamp(.63rem, .76vw, .69rem); font-weight: 600; text-transform: uppercase;
  color: var(--dq-text-3); padding-bottom: .25rem;
  white-space: nowrap; overflow: hidden; text-overflow: clip; }}
/* A badge sets white-space:nowrap, so in a column narrower than the badge it spills
   over the next cell instead of being cut off. Clip at the cell, not at the column —
   clipping the column also cuts the second line off the element cell. */
.dq-cell {{ overflow: hidden; white-space: nowrap; }}
.dq-td {{ font-size: clamp(.72rem, .88vw, .8rem); color: {NEUTRAL["text"]}; padding: .1rem 0;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.dq-td.q {{ color: var(--dq-text-2); font-size: var(--dq-fs-sub); }}
.dq-td.n {{ font-variant-numeric: tabular-nums; }}
.st-key-dq_issue_board .stButton button {{
  padding: .12rem .5rem; min-height: 0; font-size: .74rem; width: 100%;
}}
.dq-rowline {{ border-bottom: 1px solid var(--dq-border); margin: .1rem 0 .15rem; }}
.dq-rowline.head {{ margin: 0 0 .4rem; }}

/* 2. Rows are top-aligned, not centre-aligned. The element cell is two lines and
   every other cell is one; centring each column in the row's height put the badge
   halfway down the element name instead of level with it. Top alignment gives every
   cell the same first baseline, and the .1rem nudges the shorter boxes onto it. */
.st-key-dq_issue_board [data-testid="stHorizontalBlock"] {{ align-items: flex-start; }}
/* Every cell on a row's first line shares one band and centres inside it. Nudging
   each control by hand does not survive a font change: a badge, a number and a line
   of text all have different intrinsic heights, so the only stable way to put them on
   one line is to give them the same box and centre in it. The second line of the
   element cell opts out. */
.st-key-dq_issue_board .dq-td, .st-key-dq_issue_board .dq-cell {{
  display: flex; align-items: center; min-height: 1.6rem; padding: 0;
}}
.st-key-dq_issue_board .dq-td.q {{ min-height: 0; padding-top: .05rem; }}
.st-key-dq_issue_board .dq-td.n {{ justify-content: flex-start; }}
.st-key-dq_issue_board .stButton {{ display: flex; align-items: center;
  min-height: 1.6rem; }}
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

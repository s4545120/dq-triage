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


# --- CSS --------------------------------------------------------------------

_CSS = f"""
<style>
:root {{
  --dq-border: {NEUTRAL["border"]};
  --dq-text-2: {NEUTRAL["text_2"]};
  --dq-text-3: {NEUTRAL["text_3"]};
  --dq-accent: {ACCENT};
}}

/* Streamlit's default top padding is built for consumer apps. Tighten it so the
   first row of numbers is visible without scrolling. */
.stMain .block-container {{ padding-top: 2.2rem; padding-bottom: 4rem; max-width: 1400px; }}

h1, h2, h3 {{ letter-spacing: 0; }}
.stMain h1 {{ font-size: 1.45rem; font-weight: 600; margin-bottom: .15rem; }}
.stMain h2 {{ font-size: 1.02rem; font-weight: 600; margin: .4rem 0 .1rem; }}
.stMain h3 {{ font-size: .92rem; font-weight: 600; }}

.dq-i {{ vertical-align: -2px; flex: none; }}

/* Section label — the small uppercase rule that separates bands of content. */
.dq-section {{
  font-size: .69rem; font-weight: 600; letter-spacing: 0; text-transform: uppercase;
  color: var(--dq-text-3); margin: 1.5rem 0 .55rem; padding-bottom: .3rem;
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
.st-key-scorecard_monitor_inventory [data-testid="stDataFrame"] {{
  border: 1px solid var(--dq-border); border-radius: 6px; overflow: hidden;
}}

/* Streamlit ships tabs at body size; at that size they compete with headings. */
.stTabs [data-baseweb="tab"] {{ font-size: .84rem; padding-top: .35rem; padding-bottom: .35rem; }}
.stMain [data-testid="stMetricValue"] {{ font-size: 1.6rem; font-variant-numeric: tabular-nums; }}
.stMain [data-testid="stMetricLabel"] p {{ font-size: .72rem; color: var(--dq-text-3); }}
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

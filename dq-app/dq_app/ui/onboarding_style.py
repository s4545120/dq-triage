"""The onboarding pages' cards, tiles and step badges, matching the design mock.

Same technique as the scorecard: a card is a keyed `st.container` styled from here,
because a Streamlit container cannot be given a class. Every onboarding card is keyed
`onbcard_<name>`, every catalog-tree button `onbtree_<id>` (`onbtree_on_<id>` when it is
the one open), so one block of CSS styles them all and nothing here touches the
scorecard's own keys.

Colours come from `theme` -- the palette is declared there and in
`.streamlit/config.toml`, and nowhere else.
"""

from __future__ import annotations

import html
import logging

import streamlit as st

from dq_app.domain import onboarding
from dq_app.ui import theme

N = theme.NEUTRAL
CAP = "#6b6a85"   # caption grey: the mock darkens text_3, which fails contrast at 12px

_CSS = f"""
<style>
[class*="st-key-onbcard_"] {{
  border: 1px solid {N["border"]}; border-radius: 10px; background: {N["surface"]};
  padding: .85rem 1rem .9rem; gap: .55rem; box-sizing: border-box;
}}
[class*="st-key-onbcard_"] [data-testid="stMarkdownContainer"] {{ margin-bottom: 0; }}
.st-key-onbcard_promote {{ border-color: #c3c6fb; }}
/* A card holding a row table: the rows run edge to edge, the header keeps the padding. */
[class*="st-key-onbcard_rows"] {{ padding: .85rem 0 .4rem; gap: .35rem; }}
[class*="st-key-onbcard_rows"] > [data-testid="stElementContainer"],
[class*="st-key-onbcard_rows"] > [data-testid="stHorizontalBlock"],
[class*="st-key-onbcard_rows"] > [data-testid="stLayoutWrapper"] {{
  padding-left: 1rem; padding-right: 1rem; box-sizing: border-box; }}
[class*="st-key-onbcard_rows"] .st-key-dqrows_onb {{ padding: 0; }}

.onb-kpi {{ border: 1px solid {N["border"]}; border-radius: 10px; background: {N["surface"]};
  padding: .85rem 1rem; height: 100%; box-sizing: border-box;
  /* Asked for, not inherited: Streamlit's -1rem on a markdown container cancels the
     gap to the cards below (the scorecard's hero has the same fix). */
  margin: clamp(.4rem, .7vw, .7rem) 0 clamp(.6rem, 1vw, 1rem); }}
[class*="st-key-onbcard_rows"] [data-testid="stHorizontalBlock"] {{ min-width: 0; }}
[class*="st-key-onbcard_rows"] .dq-rowgrid {{ min-width: 0; }}
.onb-kpi .t {{ font-size: .8rem; font-weight: 600; color: {N["text"]}; }}
.onb-kpi .v {{ font-size: 1.85rem; font-weight: 650; letter-spacing: -.01em; line-height: 1.25;
  margin-top: .3rem; font-variant-numeric: tabular-nums; color: {N["text"]}; }}
.onb-kpi .c {{ font-size: .75rem; color: {CAP}; line-height: 1.45; }}

.onb-hd {{ display: flex; flex-wrap: wrap; gap: .3rem .8rem; justify-content: space-between;
  align-items: baseline; }}
.onb-hd .t {{ font-size: .82rem; font-weight: 600; color: {N["text"]}; }}
.onb-cap, .onb-hd .c {{ font-size: .75rem; color: {CAP}; line-height: 1.5; }}
.onb-mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .78rem;
  color: {N["text_2"]}; }}
.onb-crumb {{ font-size: .75rem; color: {CAP}; }}
.onb-wrap {{ overflow-wrap: anywhere; line-height: 1.45; padding-bottom: .2rem; }}
/* Cells in a row table truncate rather than spill into the next column or card. */
[class*="st-key-onbcard_rows"] .dq-rowgrid > span {{ min-width: 0; overflow: hidden;
  text-overflow: ellipsis; }}
[class*="st-key-onbcard_rows"] .dq-rowgrid .dq-badge {{ max-width: 100%; overflow: hidden;
  text-overflow: ellipsis; display: inline-block; vertical-align: middle; }}
.onb-title {{ display: flex; flex-wrap: wrap; gap: .6rem; align-items: center; }}
.onb-title h1 {{ margin: 0; padding: 0; font-size: 1.5rem; font-weight: 650; }}
.onb-steps {{ display: flex; flex-wrap: wrap; gap: .375rem; margin: .5rem 0 .2rem; }}
.onb-scroll {{ max-height: 34rem; overflow-y: auto; }}
.onb-ev {{ font-size: .8rem; color: {N["text_2"]}; line-height: 1.5; }}
.onb-ev b {{ color: {N["text"]}; font-weight: 600; }}
[data-testid="stMarkdownContainer"] .onb-ev + .onb-ev {{ margin-top: .5rem; }}
.onb-note {{ background: {N["canvas"]}; border-radius: 8px; padding: .6rem .75rem;
  font-size: .75rem; color: {CAP}; line-height: 1.5; }}
.onb-chip {{ display: inline-block; font-size: .72rem; color: {N["text_2"]};
  border: 1px solid {N["border"]}; border-radius: 999px; padding: 0 .5rem; margin: 0 .2rem .2rem 0;
  white-space: nowrap; }}
.onb-tl {{ display: grid; grid-template-columns: 1.6rem minmax(0, 1fr); gap: .55rem .7rem; }}
.onb-tl i {{ font-style: normal; width: 1.4rem; height: 1.4rem; border-radius: 50%;
  display: grid; place-items: center; font-size: .7rem; font-weight: 600; border: 1px solid; }}
.onb-tl i.done {{ color: #15803d; background: #f0fdf4; border-color: #bbf7d0; }}
.onb-tl i.next {{ color: {theme.ACCENT}; background: {theme.ACCENT_TINT}; border-color: #c3c6fb; }}
.onb-tl i.later {{ color: {CAP}; background: {N["canvas"]}; border-color: {N["border"]}; }}
.onb-hw {{ display: grid; grid-template-columns: 1.4rem minmax(0, 1fr); gap: .6rem .6rem;
  font-size: .8rem; color: {N["text_2"]}; line-height: 1.45; }}
.onb-hw i {{ font-style: normal; width: 1.25rem; height: 1.25rem; border-radius: 50%;
  background: {theme.ACCENT_TINT}; color: {theme.ACCENT}; font-size: .7rem; font-weight: 600;
  display: grid; place-items: center; }}
.onb-hw b {{ color: {N["text"]}; font-weight: 600; }}
.onb-foot {{ background: {N["canvas"]}; border-top: 1px solid {N["border"]};
  border-radius: 0 0 10px 10px; padding: .7rem 1rem; }}
.onb-cell {{ font-size: .86rem; color: {N["text"]}; line-height: 1.45; }}
.onb-headrow {{ font-size: .66rem; font-weight: 600; letter-spacing: .08em; color: {CAP};
  text-transform: uppercase; }}
.onb-rule {{ border-top: 1px solid #f0f0f5; margin: .1rem 0; }}
.onb-box {{ display: inline-block; width: .9rem; height: .9rem; border-radius: 3px;
  border: 1.5px solid {N["border_strong"]}; vertical-align: -2px; }}
.onb-box.on {{ background: {theme.ACCENT}; border-color: {theme.ACCENT};
  box-shadow: inset 0 0 0 2px {N["surface"]}; }}

/* The catalog tree: plain buttons, left-aligned, the open schema tinted like a picked row. */
[class*="st-key-onbtree_"] button {{
  justify-content: flex-start; border: none; background: transparent; box-shadow: none;
  min-height: 0; height: auto; padding: .3rem .5rem; color: {N["text"]}; width: 100%;
}}
[class*="st-key-onbtree_"] button:hover {{ background: {N["canvas"]}; color: {N["text"]}; }}
[class*="st-key-onbtree_"] button > div, [class*="st-key-onbtree_"] button [data-testid="stMarkdownContainer"] {{
  justify-content: flex-start; text-align: left; width: 100%; }}
[class*="st-key-onbtree_"]:not([class*="st-key-onbtree_cat_"]) button {{ padding-left: 1.4rem; }}
.st-key-onbcard_tree {{ gap: .1rem; }}
[class*="st-key-onbtree_"] button p {{ font-size: .85rem; }}
[class*="st-key-onbtree_on_"] button {{ background: {theme.ACCENT_TINT};
  box-shadow: inset 2px 0 0 {theme.ACCENT}; }}
[class*="st-key-onbtree_on_"] button p {{ color: #3730a3; font-weight: 600; }}
[class*="st-key-onbtree_cat_"] button p {{ font-weight: 550; }}
</style>
"""


def inject() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def kpi(title: str, value, caption: str = "", tone: str | None = None) -> str:
    colour = f' style="color:{theme.TONE[tone]["fg"]}"' if tone else ""
    return (f'<div class="onb-kpi"><div class="t">{html.escape(title)}</div>'
            f'<div class="v"{colour}>{value}</div>'
            f'<div class="c">{html.escape(caption)}</div></div>')


def kpi_row(tiles: list[tuple]) -> None:
    for col, t in zip(st.columns(len(tiles)), tiles):
        with col:
            st.markdown(kpi(*t), unsafe_allow_html=True)


def head(title: str, caption: str = "") -> None:
    st.markdown(f'<div class="onb-hd"><span class="t">{title}</span>'
                f'<span class="c">{caption}</span></div>', unsafe_allow_html=True)


def steps(stage: str) -> str:
    """The six step badges: done in green, the current one in indigo, the rest grey."""
    now = onboarding.STEP_OF[stage]
    out = []
    for i, label in enumerate(onboarding.STEPS, start=1):
        if i < now or now == 6:
            tone, text = "success", f"{i} {label}"
        elif i == now:
            tone = "info"
            text = f"{i} {label}" + (" · you" if i in onboarding.STEP_PERSON else "")
        else:
            tone, text = "neutral", f"{i} {label}"
        out.append(theme.badge(html.escape(text), tone))
    return f'<div class="onb-steps">{"".join(out)}</div>'


def stage_badge(stage: str) -> str:
    return theme.badge(onboarding.STAGE_LABEL.get(stage, stage),
                       onboarding.STAGE_TONE.get(stage, "info"))


# --- Confirming a write ----------------------------------------------------------------------
# Every onboarding write is an append nobody can take back: a selection, a suggestion, a
# binding decision, a promotion. So the button that asks for one only opens this dialog,
# which says what will be written, in whose name, and what follows; the write happens on
# its Confirm.
#
# Driven by a session flag rather than by calling the dialog from the button's branch:
# a dialog drawn only on the click run is gone on the next rerun, and its Confirm click
# with it. Dismissing (the cross, Escape, a click outside) clears the flag, or the
# dialog would reopen on the next unrelated click.

ASK = "_onb_ask"
# Every onboarding write passes through `confirm`, so this is where it is logged. A
# refusal is shown in the dialog and writes nothing -- without this line in the app log,
# "I approved them but nothing happened" could not be told apart from "I closed the
# dialog" or "the reason was missing".
_log = logging.getLogger("dq_app.onboarding")


def _who() -> str:
    from dq_app.data import identity
    return identity.current().email


def ask(name: str) -> None:
    st.session_state[ASK] = name
    _log.warning("onboarding %s: confirmation opened by %s", name, _who())


def _dismiss() -> None:
    if st.session_state.pop(ASK, None):
        _log.warning("onboarding: confirmation closed without writing by %s", _who())


def confirm(name: str, title: str, body: str, label: str, run) -> None:
    """Draw the confirmation for `name` if it is the one pending. `run()` performs the
    write and returns None, or a message saying what was not written."""
    if st.session_state.get(ASK) != name:
        return

    @st.dialog(title, width="medium", on_dismiss=_dismiss)
    def _dialog():
        st.markdown(f'<div class="onb-ev" style="padding-bottom:1.1rem">{body}</div>',
                    unsafe_allow_html=True)
        no, yes = st.columns(2)
        if no.button("Cancel", key=f"{ASK}_no_{name}", use_container_width=True):
            _dismiss()
            st.rerun()
        if yes.button(label, key=f"{ASK}_yes_{name}", type="primary",
                      use_container_width=True):
            err = run()
            if err:
                _log.warning("onboarding %s: REFUSED for %s: %s", name, _who(),
                             err.replace("\n", " "))
                st.error(err, icon=":material/block:")
            else:
                _log.warning("onboarding %s: written by %s", name, _who())
                st.session_state.pop(ASK, None)
                st.rerun()

    _dialog()


def items(lines: list[str], limit: int = 8) -> str:
    """A short list for a dialog body, with the rest counted rather than dropped."""
    shown = "".join(f"<li>{x}</li>" for x in lines[:limit])
    more = f"<li>and {len(lines) - limit} more</li>" if len(lines) > limit else ""
    return f'<ul style="margin:.4rem 0 .6rem 1.1rem;padding:0">{shown}{more}</ul>'

"""Panel 4 — Verifier (PREVIEW placeholder).

Intentionally present in v0 with a static mock preview — NEVER hidden.
Hiding this panel would make reintroducing verification look like a new
feature later. A yellow PREVIEW badge + 3-row static table keeps review
expectations honest.

When the real verifier lands (scheduled v0.2), this module gets swapped
for a live reader over a verifier-produced JSONL at a convention the
verifier session defines. The panel's *slot* in the layout does not
change; only the contents of build_panel() do.
"""
from __future__ import annotations

import gradio as gr


_PREVIEW_BADGE = (
    "### Panel 4 — Verifier  "
    "<span style='background:#FEF3C7;color:#78350F;padding:2px 8px;"
    "border-radius:4px;font-size:0.85em;font-weight:600;letter-spacing:0.02em;"
    "border:1px solid #FCD34D'>PREVIEW — scheduled for v0.2</span>"
)


def build_panel() -> gr.Column:
    with gr.Column() as col:
        gr.Markdown(_PREVIEW_BADGE)
        gr.Markdown(
            "_The 3-row mock verdict table, sourced verbatim from Track O1 "
            "delivery observations §5.1 / §5.4 / §5.3, will render here in "
            "the next commit. The panel slot is reserved now so that the "
            "real verifier (v0.2) drops in without layout rework._"
        )
        gr.Markdown("_(content populated in the next commit)_")
    return col

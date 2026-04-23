"""Panel 3 — LLM narrative (naive orchestrator).

Stub for the layout-review commit. Will render the LLM's response_cleaned
as markdown, with toggles for raw-with-thinking and the prompt that was
sent, plus a metadata footer (word count / elapsed / model / trace_id).
"""
from __future__ import annotations

import gradio as gr


def build_panel() -> gr.Column:
    with gr.Column() as col:
        gr.Markdown("### Panel 3 — LLM narrative (naive orchestrator)")
        gr.Markdown(
            "_Rendered markdown from response_cleaned. Toggle buttons swap "
            "to the raw output (with `<think>` block) or show the system + "
            "user messages sent to MiniMax. Footer: word count / elapsed / "
            "model / trace_id._"
        )
        gr.Markdown("_(content populated in the next commit)_")
    return col

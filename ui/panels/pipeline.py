"""Panel 2 — Pipeline output (deterministic).

Stub for the layout-review commit. Will render a gr.Dataframe of the
top-5 candidates (rank, name, RDKit SMILES→PNG structure, formula,
evidence, cosine, mass_match) plus a row-click accordion with pathways,
HMDB cross-refs, and an optional predicted-spectrum mini-plot.
"""
from __future__ import annotations

import gradio as gr


def build_panel() -> gr.Column:
    with gr.Column() as col:
        gr.Markdown("### Panel 2 — Pipeline output")
        gr.Markdown(
            "_Top-5 candidates from the deterministic pipeline. Click a row "
            "for pathways / HMDB info / predicted-spectrum mini-plot._"
        )
        gr.Markdown("_(content populated in the next commit)_")
    return col

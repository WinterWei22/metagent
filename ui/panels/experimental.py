"""Panel 1 — Experimental input.

Stub for the layout-review commit. Populated in a follow-up commit with
a matplotlib stem plot + precursor/adduct/neutral-mass/peak-count/quality
readout, fed from the cached IdentificationReport.experimental_spectrum.
"""
from __future__ import annotations

import gradio as gr


def build_panel() -> gr.Column:
    with gr.Column() as col:
        gr.Markdown("### Panel 1 — Experimental input")
        gr.Markdown(
            "_Stem plot of the preprocessed spectrum (m/z × relative intensity) "
            "will render here, with precursor and base peak labelled. Precursor, "
            "adduct, neutral mass, peak count, quality flag shown below the plot._"
        )
        gr.Markdown("_(content populated in the next commit)_")
    return col

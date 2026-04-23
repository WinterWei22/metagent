"""MetAgent demo UI entry point (Track UI1).

This is the layout-review stub: the four-panel gr.Blocks shell with header
controls and empty panels. Content fills in next commits, panel by panel.

Launch::

    conda run -n metagent-llm python -m ui.app
    conda run -n metagent-llm python -m ui.app --enable-live --port 7860

Scope: viewer only. Never calls chat() from this layer.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import gradio as gr

from ui.panels import experimental, llm, pipeline, verifier


_REPO_ROOT = Path(__file__).resolve().parent.parent
_CSS_PATH = Path(__file__).resolve().parent / "assets" / "style.css"

_FIXTURES = ("glucose_pos", "caffeine_pos", "lcarnitine_pos")

_LIVE_ENV_VARS = (
    "MINIMAX_API_KEY",
    "METAGENT_HMDB_PATH",
    "METAGENT_RAMP_PATH",
    "METAGENT_CFM_URL",
    "METAGENT_GNPS_PATH",
    "METAGENT_GNPS_SPECTRA_PATH",
    "METAGENT_PUBCHEM_LITE_PATH",
)


def _missing_live_env() -> list[str]:
    return [name for name in _LIVE_ENV_VARS if not os.environ.get(name)]


def _header_markdown(live_available: bool) -> str:
    if live_available:
        tag = (
            "<span style='color:#059669;font-weight:600'>Live mode available</span>"
        )
    else:
        tag = (
            "<span style='color:#6b7280'>Cached mode only — Live mode needs "
            f"{', '.join(_LIVE_ENV_VARS)}</span>"
        )
    return (
        "# MetAgent — Metabolite Identification Demo\n"
        "Naive-orchestrator walkthrough. Panel 4 (Verifier) is a PREVIEW "
        "placeholder until v0.2.\n\n"
        f"{tag}"
    )


def build_blocks(*, enable_live: bool = False) -> gr.Blocks:
    """Construct the gr.Blocks layout. Pure layout — no data load on build.

    Content wiring (dropdown change handlers, fixture loading, etc.) lands
    in the follow-up panel commits. This function is also called from the
    smoke tests, so it must be side-effect-free.
    """
    css = _CSS_PATH.read_text() if _CSS_PATH.exists() else ""
    live_available = enable_live and not _missing_live_env()
    mode_choices = ["Cached"] + (["Live"] if live_available else [])

    with gr.Blocks(title="MetAgent Demo", css=css) as demo:
        gr.Markdown(_header_markdown(live_available))
        with gr.Row():
            _ = gr.Dropdown(
                choices=list(_FIXTURES),
                value=_FIXTURES[0],
                label="Fixture",
                interactive=True,
            )
            _ = gr.Dropdown(
                choices=mode_choices,
                value="Cached",
                label="Run mode",
                interactive=live_available,
                info=(
                    None
                    if live_available
                    else "Live mode disabled: set the env vars listed in the "
                    "header and relaunch with --enable-live."
                ),
            )
            _ = gr.Textbox(
                label="Trace ID",
                interactive=False,
                placeholder="(populated when a run loads)",
            )
        with gr.Row():
            experimental.build_panel()
            pipeline.build_panel()
        with gr.Row():
            llm.build_panel()
            verifier.build_panel()
    return demo


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ui.app",
        description="MetAgent demo UI (Gradio). Viewer only; see ui/README.md.",
    )
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument(
        "--enable-live",
        action="store_true",
        help="Allow Live mode (pipeline + LLM) when backend env vars are set.",
    )
    args = parser.parse_args(argv)

    demo = build_blocks(enable_live=args.enable_live)
    demo.launch(
        server_name="127.0.0.1",
        server_port=args.port,
        share=False,
        show_api=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

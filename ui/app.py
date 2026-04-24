"""MetAgent demo UI entry point (Track UI1).

Two input tabs (Example cached / Custom Live), four content panels,
progressive reveal via Gradio generator handlers.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

# Gradio temp cache — isolate by uid so we don't clash with other users on
# the host who might own /tmp/gradio.
_UID = os.getuid()
os.environ.setdefault("GRADIO_TEMP_DIR", f"/tmp/gradio_{_UID}")
os.makedirs(os.environ["GRADIO_TEMP_DIR"], exist_ok=True)

import gradio as gr

from ui.data import runners
from ui.data.loaders import (
    CANONICAL_FIXTURES,
    CachedRun,
    list_cached_fixtures,
    load_cached_run,
)
from ui.panels import experimental, llm, pipeline, verifier


_REPO_ROOT = Path(__file__).resolve().parent.parent
_CSS_PATH = Path(__file__).resolve().parent / "assets" / "style.css"

_LIVE_ENV_VARS = (
    "MINIMAX_API_KEY",
    "METAGENT_HMDB_PATH",
    "METAGENT_RAMP_PATH",
    "METAGENT_CFM_URL",
    "METAGENT_GNPS_PATH",
    "METAGENT_GNPS_SPECTRA_PATH",
    "METAGENT_PUBCHEM_LITE_PATH",
)

_EXAMPLE_SPECTRUM_JSON = json.dumps(
    {
        "precursor_mz": 181.0707,
        "adduct": "[M+H]+",
        "ionization_mode": "positive",
        "collision_energy": 20.0,
        "peaks": [
            [163.0601, 1000.0],
            [145.0495, 420.0],
            [127.0390, 380.0],
            [109.0284, 300.0],
            [97.0284, 220.0],
            [85.0284, 180.0],
            [73.0284, 150.0],
        ],
    },
    indent=2,
)


def _missing_live_env() -> list[str]:
    return [name for name in _LIVE_ENV_VARS if not os.environ.get(name)]


def _header_markdown(live_available: bool) -> str:
    if live_available:
        tag = "<span style='color:#059669;font-weight:600'>Live mode: available</span>"
    else:
        missing = ", ".join(_missing_live_env())
        tag = (
            "<span style='color:#6b7280'>"
            f"Live mode: disabled (need {missing})</span>"
        )
    return (
        "# MetAgent — Metabolite Identification Demo\n"
        "\n"
        "**Input:** an MS/MS spectrum.  "
        "**Output:** ranked candidates (B library + C de novo), a natural-"
        "language identification narrative, and the verifier's per-claim "
        "verdict (Track V, live in this build)."
        "\n\n"
        f"{tag}"
    )


def _fixture_default(cached: list[str]) -> str:
    return cached[0] if cached else CANONICAL_FIXTURES[0]


# --------------------------------------------------------------------------- #
# Shared renders
# --------------------------------------------------------------------------- #


def _render_for_panels(
    report: dict | None,
    llm_row: dict | None,
    *,
    view: str = llm.VIEW_RENDERED,
    predicted_spectra: dict | None = None,
    verifier_row: dict | None = None,
):
    fig, exp_meta = experimental.render(report)
    (
        gallery,
        denovo_gallery, denovo_caption,
        predict_dd, predict_plot, predict_caption, predict_state,
        table, detail, top1_name, lit_reset, warnings_md,
    ) = pipeline.render(report, predicted_spectra)
    llm_body = llm.render_body(llm_row, view=view)
    llm_footer = llm.render_footer(llm_row)
    ver_summary, ver_rows, ver_rewritten, ver_warnings = verifier.render(verifier_row)
    return (
        fig, exp_meta,
        gallery, denovo_gallery, denovo_caption,
        predict_dd, predict_plot, predict_caption, predict_state,
        table, detail, top1_name, lit_reset, warnings_md,
        llm_body, llm_footer,
        ver_summary, ver_rows, ver_rewritten, ver_warnings,
    )


def _blank_panels_tuple():
    # 16 base + 4 verifier = 20 outputs. Order MUST match panel_outputs in
    # build_blocks(). Verifier slots: summary (md), table rows (list),
    # rewritten body (md), warnings (md).
    return (
        None, "",
        [], [], "",
        gr.update(choices=[], value=None), None, "", None,
        [], "", "", "", "",
        "", "",
        "", [], "", "",
    )


def _run_literature_search(top1_name: str) -> str:
    records, err = runners.try_literature_search(top1_name, max_results=5)
    return pipeline.render_literature(records, err)


_STAGE_DELAY = float(os.environ.get("METAGENT_UI_STAGE_DELAY", "0.45"))


def _load_cached_progressive(fixture: str):
    run: CachedRun | None = load_cached_run(fixture)
    trace_id = run.trace_id if run else f"(no cached run for {fixture})"

    yield (
        *_blank_panels_tuple(),
        trace_id,
        f"<span style='color:#6b7280'>Loading {fixture}…</span>",
    )
    time.sleep(_STAGE_DELAY * 0.4)

    if run is None:
        yield (
            *_blank_panels_tuple(),
            trace_id,
            f"<span style='color:#b91c1c'>No cached run for {fixture}.</span>",
        )
        return

    report = run.report
    llm_row = run.llm_row
    predicted_spectra = run.predicted_spectra
    verifier_row = run.verifier_row

    fig, exp_meta = experimental.render(report)
    (
        gallery,
        denovo_gallery, denovo_caption,
        predict_dd, predict_plot, predict_caption, predict_state,
        table, detail, top1_name, lit_reset, warnings_md,
    ) = pipeline.render(report, predicted_spectra)
    llm_body = llm.render_body(llm_row, view=llm.VIEW_RENDERED)
    llm_footer = llm.render_footer(llm_row)
    ver_summary, ver_rows, ver_rewritten, ver_warnings = verifier.render(verifier_row)

    # Stage 1 — input
    yield (
        fig, exp_meta,
        [], [], "",
        gr.update(choices=[], value=None), None, "", None,
        [], "", "", "", "",
        "", "",
        "", [], "", "",
        trace_id,
        "<span style='color:#0369a1'>Step 1/4 · Input spectrum loaded.</span>",
    )
    time.sleep(_STAGE_DELAY)

    # Stage 2 — deterministic pipeline output
    yield (
        fig, exp_meta,
        gallery, denovo_gallery, denovo_caption,
        predict_dd, predict_plot, predict_caption, predict_state,
        table, detail, top1_name, lit_reset, warnings_md,
        "", "",
        "", [], "", "",
        trace_id,
        "<span style='color:#0369a1'>Step 2/4 · Pipeline output ready.</span>",
    )
    time.sleep(_STAGE_DELAY)

    # Stage 3 — LLM narrative
    yield (
        fig, exp_meta,
        gallery, denovo_gallery, denovo_caption,
        predict_dd, predict_plot, predict_caption, predict_state,
        table, detail, top1_name, lit_reset, warnings_md,
        llm_body, llm_footer,
        "", [], "", "",
        trace_id,
        "<span style='color:#0369a1'>Step 3/4 · LLM narrative loaded.</span>",
    )
    time.sleep(_STAGE_DELAY)

    # Stage 4 — verifier verdict (from sidecar; empty if no sidecar)
    final_status = (
        "<span style='color:#059669'>Step 4/4 · Verifier verdict loaded.</span>"
        if verifier_row else
        "<span style='color:#d97706'>Step 4/4 · No verifier sidecar for this "
        "trace_id (Track V never run, or sidecar missing).</span>"
    )
    yield (
        fig, exp_meta,
        gallery, denovo_gallery, denovo_caption,
        predict_dd, predict_plot, predict_caption, predict_state,
        table, detail, top1_name, lit_reset, warnings_md,
        llm_body, llm_footer,
        ver_summary, ver_rows, ver_rewritten, ver_warnings,
        trace_id,
        final_status,
    )


def _swap_llm_view_cached(fixture: str, view: str) -> str:
    run = load_cached_run(fixture)
    return llm.render_body(run.llm_row if run else None, view=view)


def _load_cached_and_render(fixture: str):
    """Single-shot loader used by demo.load (generators don't fire on load)."""
    run: CachedRun | None = load_cached_run(fixture)
    report = run.report if run else None
    llm_row = run.llm_row if run else None
    predicted_spectra = run.predicted_spectra if run else None
    verifier_row = run.verifier_row if run else None
    trace_id = run.trace_id if run else f"(no cached run for {fixture})"
    return (
        *_render_for_panels(
            report, llm_row,
            predicted_spectra=predicted_spectra,
            verifier_row=verifier_row,
        ),
        trace_id, "",
    )


def _run_live_progressive(spectrum_json_text: str, progress=gr.Progress()):
    yield (
        *_blank_panels_tuple(),
        "",
        "<span style='color:#6b7280'>Parsing custom spectrum…</span>",
    )
    try:
        payload = runners.parse_custom_spectrum_json(spectrum_json_text)
    except runners.LiveRunError as exc:
        yield (
            *_blank_panels_tuple(),
            "",
            f"<span style='color:#b91c1c'>Invalid input: {exc}</span>",
        )
        return

    stub_report = {
        "experimental_spectrum": {
            "mz": [float(p[0]) for p in payload["peaks"]],
            "intensity": [float(p[1]) for p in payload["peaks"]],
            "precursor_mz": float(payload["precursor_mz"]),
            "adduct": payload["adduct"],
            "ionization_mode": payload["ionization_mode"],
            "collision_energy": payload.get("collision_energy"),
        },
        "preprocess_quality_flag": "pending",
        "neutral_mass_computed": 0.0,
        "n_prefilter_candidates": 0,
        "n_library_candidates": 0,
        "n_generated_candidates": 0,
        "candidates": [],
        "pipeline_version": "(live — pending)",
        "tool_versions": {},
        "warnings": [],
    }
    fig, exp_meta = experimental.render(stub_report)
    trace_id = runners.make_live_trace_id(payload)

    # ----- Stage 1 — input acknowledged
    yield (
        fig, exp_meta,
        [], [], "",
        gr.update(choices=[], value=None), None, "", None,
        [], "", "", "", "",
        "", "",
        "", [], "", "",
        trace_id,
        "<span style='color:#0369a1'>Step 1/4 · Input received. "
        "Deterministic pipeline running in diffms (~5 min)…</span>",
    )

    try:
        report_dict = runners.run_live_pipeline(payload, trace_id=trace_id)
    except runners.LiveRunError as exc:
        yield (
            fig, exp_meta,
            [], [], "",
            gr.update(choices=[], value=None), None, "", None,
            [], "", "", "", "",
            "", "",
            "", [], "", "",
            trace_id,
            f"<span style='color:#b91c1c'>Pipeline failed: {exc}</span>",
        )
        return

    try:
        runners.persist_report(report_dict, trace_id)
    except OSError:
        pass

    # Side-car written by the runner; reload it to feed Panel 2's overlay.
    import json as _json
    sidecar_path = Path(
        f"/data/weiwentao/llm_agent_metabolomics/pipeline_runs/"
        f"{trace_id}.predicted_spectra.json"
    )
    predicted_spectra = None
    if sidecar_path.is_file():
        try:
            predicted_spectra = _json.loads(sidecar_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            predicted_spectra = None

    fig2, exp_meta2 = experimental.render(report_dict)
    (
        gallery,
        denovo_gallery, denovo_caption,
        predict_dd, predict_plot, predict_caption, predict_state,
        table, detail, top1_name, lit_reset, warnings_md,
    ) = pipeline.render(report_dict, predicted_spectra)

    # ----- Stage 2 — pipeline rendered
    yield (
        fig2, exp_meta2,
        gallery, denovo_gallery, denovo_caption,
        predict_dd, predict_plot, predict_caption, predict_state,
        table, detail, top1_name, lit_reset, warnings_md,
        "", "",
        "", [], "", "",
        trace_id,
        "<span style='color:#0369a1'>Step 2/4 · Pipeline output ready. "
        "Calling MiniMax (~30 s)…</span>",
    )

    try:
        llm_row = runners.run_live_llm(report_dict, trace_id)
    except Exception as exc:  # noqa: BLE001
        yield (
            fig2, exp_meta2,
            gallery, denovo_gallery, denovo_caption,
            predict_dd, predict_plot, predict_caption, predict_state,
            table, detail, top1_name, lit_reset, warnings_md,
            "", "",
            "", [], "", "",
            trace_id,
            f"<span style='color:#b91c1c'>LLM call failed: "
            f"{type(exc).__name__}: {exc}</span>",
        )
        return

    llm_body = llm.render_body(llm_row or None, view=llm.VIEW_RENDERED)
    llm_footer = llm.render_footer(llm_row or None)

    # ----- Stage 3 — LLM narrative; verifier kicks off next
    yield (
        fig2, exp_meta2,
        gallery, denovo_gallery, denovo_caption,
        predict_dd, predict_plot, predict_caption, predict_state,
        table, detail, top1_name, lit_reset, warnings_md,
        llm_body, llm_footer,
        "", [], "", "",
        trace_id,
        "<span style='color:#0369a1'>Step 3/4 · LLM narrative ready. "
        "Verifier cascade running (~5–9 min, up to 7 LLM calls)…</span>",
    )

    # ----- Stage 4 — verifier cascade
    llm_output = (llm_row or {}).get("response_cleaned") or ""
    verifier_dump, verifier_error = runners.run_live_verifier(
        report_dict, llm_output, trace_id=trace_id,
    )
    ver_summary, ver_rows, ver_rewritten, ver_warnings = verifier.render(verifier_dump)

    if verifier_error:
        final_status = (
            f"<span style='color:#d97706'>Step 4/4 · Verifier degraded: "
            f"{verifier_error}.</span>  trace_id = <code>{trace_id}</code>"
        )
    else:
        final_status = (
            f"<span style='color:#059669'>Step 4/4 · Live run complete "
            "(pipeline + LLM + verifier).</span>  "
            f"trace_id = <code>{trace_id}</code>"
        )

    yield (
        fig2, exp_meta2,
        gallery, denovo_gallery, denovo_caption,
        predict_dd, predict_plot, predict_caption, predict_state,
        table, detail, top1_name, lit_reset, warnings_md,
        llm_body, llm_footer,
        ver_summary, ver_rows, ver_rewritten, ver_warnings,
        trace_id,
        final_status,
    )


# --------------------------------------------------------------------------- #
# Layout
# --------------------------------------------------------------------------- #


def build_blocks(*, enable_live: bool = False) -> gr.Blocks:
    css = _CSS_PATH.read_text() if _CSS_PATH.exists() else ""
    live_available = enable_live and not _missing_live_env()

    cached = list_cached_fixtures()
    default_fixture = _fixture_default(cached)

    with gr.Blocks(title="MetAgent Demo", css=css) as demo:
        gr.Markdown(_header_markdown(live_available))

        with gr.Tabs():
            with gr.Tab("Example spectrum (cached)"):
                fixture_dd = gr.Dropdown(
                    choices=list(CANONICAL_FIXTURES),
                    value=default_fixture,
                    label="Pick a pre-run example",
                    interactive=True,
                )
            with gr.Tab("Custom spectrum (Live)"):
                gr.Markdown(
                    "Paste an MS/MS spectrum as JSON. Required: "
                    "`precursor_mz`, `adduct`, `ionization_mode`, `peaks`. "
                    "Optional: `collision_energy`. "
                    "Pipeline runs in `diffms` env (~5 min) → MiniMax (~30 s)."
                )
                if not live_available:
                    missing = ", ".join(_missing_live_env())
                    gr.Markdown(
                        "<span style='color:#b91c1c'>"
                        f"**Live mode disabled.** Missing env: {missing}."
                        "</span>"
                    )
                spectrum_json_tb = gr.Textbox(
                    label="Spectrum JSON",
                    value=_EXAMPLE_SPECTRUM_JSON,
                    lines=16,
                    max_lines=28,
                    interactive=live_available,
                    elem_classes=["metagent-spectrum-json"],
                )
                run_btn = gr.Button(
                    "Run pipeline + LLM",
                    variant="primary",
                    interactive=live_available,
                )
                status_md = gr.Markdown()

        trace_id_tb = gr.Textbox(
            label="Trace ID (of the run shown below)",
            interactive=False,
            placeholder="(populated when a run loads)",
        )

        with gr.Row():
            _, exp_out = experimental.build_panel()
            _, pipe_out = pipeline.build_panel()
        with gr.Row():
            _, llm_out = llm.build_panel()
            _, ver_out = verifier.build_panel()

        panel_outputs = [
            exp_out.plot,
            exp_out.meta,
            pipe_out.gallery,
            pipe_out.denovo_gallery,
            pipe_out.denovo_caption,
            pipe_out.predict_dropdown,
            pipe_out.predict_plot,
            pipe_out.predict_caption,
            pipe_out.predict_state,
            pipe_out.table,
            pipe_out.detail,
            pipe_out.lit_top1_state,
            pipe_out.lit_body,
            pipe_out.warnings_md,
            llm_out.body,
            llm_out.footer,
            ver_out.summary,
            ver_out.verdict_table,
            ver_out.rewritten_body,
            ver_out.warnings_md,
        ]

        fixture_dd.change(
            fn=_load_cached_progressive,
            inputs=[fixture_dd],
            outputs=[*panel_outputs, trace_id_tb, status_md],
        )
        llm_out.view.change(
            fn=_swap_llm_view_cached,
            inputs=[fixture_dd, llm_out.view],
            outputs=[llm_out.body],
        )
        pipe_out.lit_button.click(
            fn=_run_literature_search,
            inputs=[pipe_out.lit_top1_state],
            outputs=[pipe_out.lit_body],
        )

        pipe_out.predict_dropdown.change(
            fn=pipeline.render_predict_overlay_switch,
            inputs=[pipe_out.predict_dropdown, pipe_out.predict_state],
            outputs=[pipe_out.predict_plot, pipe_out.predict_caption],
        )
        run_btn.click(
            fn=_run_live_progressive,
            inputs=[spectrum_json_tb],
            outputs=[*panel_outputs, trace_id_tb, status_md],
        )
        demo.load(
            fn=_load_cached_and_render,
            inputs=[fixture_dd],
            outputs=[*panel_outputs, trace_id_tb, status_md],
        )
    return demo


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ui.app",
        description="MetAgent demo UI (Gradio). Viewer only; see ui/README.md.",
    )
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument(
        "--host", type=str, default="127.0.0.1",
        help="Bind address. Default 127.0.0.1. Pass 0.0.0.0 for LAN.",
    )
    parser.add_argument(
        "--enable-live", action="store_true",
        help="Allow Live mode when all backend env vars are set.",
    )
    args = parser.parse_args(argv)

    demo = build_blocks(enable_live=args.enable_live)
    demo.launch(
        server_name=args.host,
        server_port=args.port,
        share=False,
        show_api=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

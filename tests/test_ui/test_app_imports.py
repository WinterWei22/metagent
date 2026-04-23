"""Smoke tests for the Track UI1 layout stub.

Validates that the UI module imports cleanly and the gr.Blocks shell can
be constructed without a running server. Content-level tests (loaders,
spectrum plot, molecule image) land alongside their feature commits.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def test_ui_app_module_imports() -> None:
    """`import ui.app` must succeed without launching a server."""
    import ui.app  # noqa: F401 — import-time side effects are the test


def test_build_blocks_returns_gradio_blocks() -> None:
    """build_blocks() constructs the layout; no server started."""
    import gradio as gr

    from ui.app import build_blocks

    demo = build_blocks(enable_live=False)
    assert isinstance(demo, gr.Blocks)


def test_build_blocks_live_disabled_by_default() -> None:
    """When enable_live is False, build_blocks should not raise regardless
    of env-var presence."""
    from ui.app import build_blocks

    demo = build_blocks(enable_live=False)
    assert demo is not None


def test_build_blocks_enable_live_tolerates_missing_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """enable_live=True with missing env vars must degrade gracefully:
    the block still builds, Live mode is just disabled internally.
    """
    from ui.app import build_blocks

    for var in (
        "MINIMAX_API_KEY",
        "METAGENT_HMDB_PATH",
        "METAGENT_RAMP_PATH",
        "METAGENT_CFM_URL",
        "METAGENT_GNPS_PATH",
        "METAGENT_GNPS_SPECTRA_PATH",
        "METAGENT_PUBCHEM_LITE_PATH",
    ):
        monkeypatch.delenv(var, raising=False)

    demo = build_blocks(enable_live=True)
    assert demo is not None


def test_panels_each_build_panel_callable_returns_a_column() -> None:
    """Every panel module exposes build_panel() returning a gr.Column.
    Keeps layout contract stable as content fills in.
    """
    import gradio as gr

    from ui.panels import experimental, llm, pipeline, verifier

    # build_panel() must be invoked inside a gr.Blocks context; construct one.
    with gr.Blocks():
        for module in (experimental, pipeline, llm, verifier):
            col = module.build_panel()
            assert isinstance(col, gr.Column), (
                f"{module.__name__}.build_panel() did not return a gr.Column; "
                f"got {type(col).__name__}"
            )

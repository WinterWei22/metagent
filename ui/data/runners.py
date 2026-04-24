"""Live-mode runners: pipeline subprocess (diffms) → orchestrator LLM (in-proc).

Pipeline leg runs in `diffms` via `conda run -n diffms python -m
ui.data.live_pipeline_runner`. UI-side dependency injection replaces Track C's
default SiriusFingerprinter with CandidateFusionFingerprinter (no SIRIUS
needed).
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DATA_CACHE = Path("/data/weiwentao/llm_agent_metabolomics/pipeline_runs")

_CONDA_BIN = os.environ.get("METAGENT_CONDA_BIN", "/home/weiwentao/miniconda3/bin/conda")
_PIPELINE_ENV = os.environ.get("METAGENT_DIFFMS_ENV", "diffms")

PIPELINE_TIMEOUT_SECONDS = int(os.environ.get("METAGENT_LIVE_PIPELINE_TIMEOUT", "900"))

_DEFAULT_MSBART_CKPT = (
    "/home/weiwentao/workspace/mol_gen/MS-BART/data/MassSpecGym/"
    "MS-BART-MassSpecGym/csyanghan/MS-BART-MassSpecGym"
)


class LiveRunError(RuntimeError):
    """Raised on any live-run failure. message is user-safe."""


# --------------------------------------------------------------------------- #
# Literature search — graceful failure wrapper
# --------------------------------------------------------------------------- #


def try_literature_search(
    query: str, *, max_results: int = 5
) -> tuple[list[dict[str, Any]], str | None]:
    query = (query or "").strip()
    if not query:
        return [], "No query — no top candidate name available."
    try:
        from schemas.pathway import LiteratureSearchRequest
        from tools.literature import literature_search
    except ImportError as exc:
        return [], f"tools.literature not importable: {exc}"
    try:
        req = LiteratureSearchRequest(
            query=query, max_results=max_results, sources=["europepmc"]
        )
        resp = literature_search(req)
    except Exception as exc:  # noqa: BLE001
        return [], f"{type(exc).__name__}: {exc}"
    return [r.model_dump() for r in resp.records], None


# --------------------------------------------------------------------------- #
# JSON payload validation
# --------------------------------------------------------------------------- #


def parse_custom_spectrum_json(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LiveRunError(f"Not valid JSON: {exc}") from None
    if not isinstance(data, dict):
        raise LiveRunError("Top-level JSON must be an object, not a list.")
    for key in ("precursor_mz", "adduct", "ionization_mode", "peaks"):
        if key not in data:
            raise LiveRunError(f"Missing required field: '{key}'")
    if data["ionization_mode"] not in ("positive", "negative"):
        raise LiveRunError(
            "ionization_mode must be 'positive' or 'negative'; "
            f"got {data['ionization_mode']!r}"
        )
    peaks = data["peaks"]
    if not isinstance(peaks, list) or not peaks:
        raise LiveRunError("'peaks' must be a non-empty list of [mz, intensity] pairs.")
    for i, p in enumerate(peaks):
        if not (isinstance(p, (list, tuple)) and len(p) == 2):
            raise LiveRunError(f"Peak {i} is not a two-element list [mz, intensity].")
        try:
            float(p[0]); float(p[1])
        except (TypeError, ValueError):
            raise LiveRunError(f"Peak {i} has non-numeric components: {p!r}") from None
    return data


def make_live_trace_id(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True).encode("utf-8")
    short = hashlib.sha256(blob).hexdigest()[:8]
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"live_{short}_{ts}"


# --------------------------------------------------------------------------- #
# Pipeline subprocess
# --------------------------------------------------------------------------- #


def run_live_pipeline(
    payload: dict[str, Any],
    *,
    trace_id: str | None = None,
    timeout: int = PIPELINE_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Run the pipeline subprocess. If `trace_id` is given, the runner
    persists per-candidate predicted spectra to
    /data/.../pipeline_runs/<trace_id>.predicted_spectra.json.
    """
    cmd = [
        _CONDA_BIN, "run", "-n", _PIPELINE_ENV, "--no-capture-output",
        "python", "-m", "ui.data.live_pipeline_runner",
    ]
    child_env = {
        **os.environ,
        "METAGENT_MSBART_CKPT": os.environ.get(
            "METAGENT_MSBART_CKPT", _DEFAULT_MSBART_CKPT
        ),
    }
    if trace_id:
        child_env["METAGENT_UI_LIVE_TRACE_ID"] = trace_id
    try:
        proc = subprocess.run(
            cmd,
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=_REPO_ROOT,
            env=child_env,
        )
    except subprocess.TimeoutExpired as exc:
        raise LiveRunError(
            f"Pipeline timed out after {timeout}s."
        ) from exc
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-6:]
        raise LiveRunError(
            f"Pipeline subprocess failed (exit {proc.returncode}). "
            "Stderr tail:\n" + "\n".join(tail)
        )
    stdout = proc.stdout or ""
    brace = stdout.find("{")
    if brace < 0:
        raise LiveRunError("Pipeline produced no JSON output.")
    try:
        return json.loads(stdout[brace:])
    except json.JSONDecodeError as exc:
        raise LiveRunError(f"Pipeline output was not valid JSON: {exc}") from None


def run_live_llm(report_dict: dict[str, Any], trace_id: str) -> dict[str, Any]:
    from orchestrator import identify
    from schemas.report import IdentificationReport

    report = IdentificationReport.model_validate(report_dict)
    identify(report, trace_id=trace_id)
    from ui.data.loaders import _read_log_rows
    rows = _read_log_rows()
    row = next((r for r in reversed(rows) if r.get("trace_id") == trace_id), None)
    return row or {}


def persist_report(report_dict: dict[str, Any], trace_id: str) -> Path:
    _DATA_CACHE.mkdir(parents=True, exist_ok=True)
    path = _DATA_CACHE / f"{trace_id}.json"
    path.write_text(json.dumps(report_dict, ensure_ascii=False), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# Verifier — Stage D of Live mode (in-process; metagent-llm env)
# --------------------------------------------------------------------------- #


def run_live_verifier(
    report_dict: dict[str, Any],
    llm_output: str,
    *,
    trace_id: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Run the Track V cascade on ``llm_output`` against ``report_dict``.

    Mirrors ``try_literature_search`` in the same module: returns
    ``(verifier_dump, error_message)`` where exactly one is None.
    Persists the dump to the verifier sidecar location on success.

    Calls happen in-process — verifier already runs in metagent-llm
    (it shares the openai/MiniMax stack with the orchestrator). No
    subprocess. Wall-clock dominated by 7 LLM calls (~9 min worst case
    per Track V delivery; usually closer to 4-6 min).
    """
    if not llm_output or not llm_output.strip():
        return None, "no LLM output to verify"
    try:
        from schemas.report import IdentificationReport
        from verifier.agent import verify
    except ImportError as exc:
        return None, f"verifier not importable: {exc}"
    try:
        source_report = IdentificationReport.model_validate(report_dict)
    except Exception as exc:  # noqa: BLE001 — Pydantic ValidationError + sundry
        return None, f"source_report invalid: {type(exc).__name__}: {exc}"
    try:
        verified = verify(
            llm_output, source_report,
            trace_id=f"{trace_id}_verified",
        )
    except Exception as exc:  # noqa: BLE001 — never propagate; UI surfaces text
        return None, f"verifier crashed: {type(exc).__name__}: {exc}"

    dump = verified.model_dump(mode="json")
    # Persist for UI cached-mode reload + downstream analytics.
    try:
        from ui.data.loaders import verifier_sidecar_path

        sidecar = verifier_sidecar_path(trace_id)
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        sidecar.write_text(
            json.dumps(dump, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
    except OSError:
        # Persistence is best-effort; the verdict is still returned to
        # the caller for in-session display.
        pass
    return dump, None


def run_live(
    payload: dict[str, Any],
    *,
    trace_id: str | None = None,
    progress=None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None, str | None, str]:
    """Live-mode 4-stage pipeline. Returns:

        (report_dict, llm_row, verifier_dump, verifier_error, trace_id)

    ``verifier_dump`` is None when ``verifier_error`` is set, and
    vice versa. Either may legitimately be (None, "skipped — ...")
    when the LLM produced empty output, but in normal operation
    exactly one is populated.
    """
    if trace_id is None:
        trace_id = make_live_trace_id(payload)
    if progress:
        progress(0.05, desc="Step 1/4 · deterministic pipeline (≈5 min)...")
    report_dict = run_live_pipeline(payload, trace_id=trace_id)
    try:
        persist_report(report_dict, trace_id)
    except OSError:
        pass
    if progress:
        progress(0.55, desc="Step 2/4 · MiniMax orchestrator (~30 s)...")
    llm_row = run_live_llm(report_dict, trace_id)
    if progress:
        progress(0.65, desc="Step 3/4 · verifier cascade (~5 min)...")
    llm_output = (llm_row or {}).get("response_cleaned") or ""
    verifier_dump, verifier_error = run_live_verifier(
        report_dict, llm_output, trace_id=trace_id,
    )
    if progress:
        progress(1.0, desc="Step 4/4 · done.")
    return report_dict, llm_row, verifier_dump, verifier_error, trace_id

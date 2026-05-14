"""Deterministic pipeline entry for UI Live mode.

Runs in the `diffms` env via `conda run`. Reads a custom-spectrum JSON
payload on stdin, runs the full A → E pipeline with two UI-side
dependency injections:

  • Track C's default `SiriusFingerprinter` → `CandidateFusionFingerprinter`
    fed by Track B retrieval hits (no SIRIUS needed).
  • A transparent wrapper around `predict_spectrum_fn` that captures every
    CFM-ID predicted Spectrum keyed by candidate SMILES. After the
    pipeline completes, those are written to a side-car JSON at
    `/data/weiwentao/llm_agent_metabolomics/pipeline_runs/
    <trace_id>.predicted_spectra.json` when METAGENT_UI_LIVE_TRACE_ID is
    set in env. stdout still carries just the IdentificationReport JSON,
    so calling UIs need no protocol changes beyond reading the side-car.

Command::

    METAGENT_UI_LIVE_TRACE_ID=<trace_id> conda run -n diffms \\
        python -m ui.data.live_pipeline_runner < payload.json > report.json

Exit codes:
    0 — report written to stdout (and side-car to disk if trace_id set)
    1 — stdin JSON parse error
    2 — pipeline error
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


_PREDICTED_SPECTRA_DIR = Path("/data/weiwentao/llm_agent_metabolomics/pipeline_runs")


def _parse_payload(raw: str) -> dict:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"input JSON parse failed: {exc}", file=sys.stderr)
        sys.exit(1)
    missing = [
        k for k in ("precursor_mz", "adduct", "ionization_mode", "peaks")
        if k not in payload
    ]
    if missing:
        print(f"input JSON missing required keys: {missing}", file=sys.stderr)
        sys.exit(1)
    peaks = payload.get("peaks") or []
    if not isinstance(peaks, list) or not peaks:
        print("input JSON: 'peaks' must be a non-empty list", file=sys.stderr)
        sys.exit(1)
    for p in peaks:
        if not (isinstance(p, (list, tuple)) and len(p) == 2):
            print(
                "input JSON: each peak must be [mz, intensity]", file=sys.stderr
            )
            sys.exit(1)
    return payload


def _build_injected_callables():
    """Return (library_wrap, generate_wrap, predict_wrap, predicted_store).

    predicted_store is a dict mapping candidate SMILES -> Spectrum dict,
    filled transparently every time predict_spectrum_fn is invoked.
    """
    from schemas.common import Candidate
    from tools.library_search import library_search as _real_library
    from tools.molecule_gen import generate as _real_generate
    from tools.molecule_gen.errors import FingerprinterError
    from tools.molecule_gen.fingerprint import CandidateFusionFingerprinter
    from tools.spectrum_predict import predict_spectrum as _real_predict

    library_state: dict = {"library_candidates": []}
    predicted_store: dict[str, dict] = {}

    def library_wrap(req, *args, **kwargs):
        resp = _real_library(req, *args, **kwargs)
        library_state["library_candidates"] = list(resp.candidates)
        return resp

    def generate_wrap(req, *args, **kwargs):
        fusion_pool = library_state["library_candidates"] or []
        if not fusion_pool:
            pool = list(req.candidate_pool or [])
            fusion_pool = [
                Candidate(
                    smiles=p.smiles, name=p.name, source="reference",
                    score=0.5, source_id=p.source_id,
                    explain="Live runner fallback from prefilter pool.",
                )
                for p in pool
            ]
        if not fusion_pool:
            return _real_generate(req, *args, **kwargs)
        try:
            fp = CandidateFusionFingerprinter(
                candidates=fusion_pool, strategy="retrieved_only_60",
            )
        except FingerprinterError as exc:
            print(
                f"[live_pipeline_runner] CandidateFusion construction failed: "
                f"{exc}; falling back to default generate().",
                file=sys.stderr,
            )
            return _real_generate(req, *args, **kwargs)
        return _real_generate(req, fingerprinter=fp)

    def predict_wrap(req, *args, **kwargs):
        resp = _real_predict(req, *args, **kwargs)
        try:
            predicted_store[req.smiles] = resp.predicted.model_dump()
        except Exception as capture_exc:  # noqa: BLE001
            print(
                f"[live_pipeline_runner] failed to capture predicted spectrum "
                f"for {req.smiles!r}: {capture_exc}",
                file=sys.stderr,
            )
        return resp

    return library_wrap, generate_wrap, predict_wrap, predicted_store


def _write_predicted_sidecar(trace_id: str, predicted_store: dict[str, dict]) -> None:
    if not predicted_store:
        return
    try:
        _PREDICTED_SPECTRA_DIR.mkdir(parents=True, exist_ok=True)
        path = _PREDICTED_SPECTRA_DIR / f"{trace_id}.predicted_spectra.json"
        path.write_text(
            json.dumps(predicted_store, ensure_ascii=False),
            encoding="utf-8",
        )
        print(
            f"[live_pipeline_runner] wrote {len(predicted_store)} predicted "
            f"spectra to {path}",
            file=sys.stderr,
        )
    except OSError as exc:
        print(
            f"[live_pipeline_runner] could not persist predicted spectra: {exc}",
            file=sys.stderr,
        )


def main() -> int:
    payload = _parse_payload(sys.stdin.read())
    trace_id = os.environ.get("METAGENT_UI_LIVE_TRACE_ID", "").strip()

    try:
        from schemas import PreprocessRequest
        from scripts.run_full_pipeline import identify as run_pipeline
    except ImportError as exc:
        print(
            f"pipeline deps not importable (expected diffms env): {exc}",
            file=sys.stderr,
        )
        return 2

    peaks = payload["peaks"]
    collision_energy = payload.get("collision_energy")
    req = PreprocessRequest(
        raw_mz=[float(p[0]) for p in peaks],
        raw_intensity=[float(p[1]) for p in peaks],
        precursor_mz=float(payload["precursor_mz"]),
        adduct=str(payload["adduct"]),
        ionization_mode=str(payload["ionization_mode"]),
        collision_energy=(
            float(collision_energy) if collision_energy is not None else None
        ),
    )

    library_wrap, generate_wrap, predict_wrap, predicted_store = (
        _build_injected_callables()
    )

    try:
        report = run_pipeline(
            req,
            library_search_fn=library_wrap,
            generate_fn=generate_wrap,
            predict_spectrum_fn=predict_wrap,
        )
    except Exception as exc:  # noqa: BLE001
        print(
            f"pipeline crashed: {type(exc).__name__}: {exc}", file=sys.stderr
        )
        traceback.print_exc()
        return 2

    if trace_id:
        _write_predicted_sidecar(trace_id, predicted_store)

    sys.stdout.write(report.model_dump_json())
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

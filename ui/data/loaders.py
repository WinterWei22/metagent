"""Cached-run discovery for the UI.

Lookup order (first hit wins):

    1. /data/weiwentao/llm_agent_metabolomics/pipeline_runs/<trace_id>.json
       — durable UI-managed cache; Live-mode runs write here.
    2. /tmp/o1/<fixture>.json — Track O1 Part 4 leftovers.
    3. reports/pipeline_runs/<trace_id>.json — in-repo fallback.

LLM rows always come from logs/llm_calls.jsonl filtered to
caller == "orchestrator.naive.identify".
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DATA_CACHE = Path("/data/weiwentao/llm_agent_metabolomics/pipeline_runs")
_TMP_O1 = Path("/tmp/o1")
_REPO_PIPELINE_RUNS = _REPO_ROOT / "reports" / "pipeline_runs"
_LOG_PATH = _REPO_ROOT / "logs" / "llm_calls.jsonl"

# Verifier sidecar — convention introduced by UI/V1 (see
# reports/ui_v0_delivery_2026-04-24.md §7.2). One JSON file per
# verifier run, keyed by the orchestrator's `trace_id` (NOT the
# verifier's derived `<trace_id>_verified` — UI displays verifier
# verdicts paired with the orchestrator output that was verified, so
# the sidecar lives next to the report whose llm_output it audited).
_VERIFIER_RUNS = Path("/data/weiwentao/llm_agent_metabolomics/verifier_runs")

CANONICAL_FIXTURES: tuple[str, ...] = (
    "glucose_pos",
    "caffeine_pos",
    "lcarnitine_pos",
    # Bonus cached run produced by the UI's Fusion-injected Live pipeline on
    # the glucose spectrum — includes `source=generated` candidates from
    # Track C, unlike the three originals (which were produced with the
    # pipeline's SIRIUS default on a host without SIRIUS installed).
    "glucose_pos_fusion",
)

ORCHESTRATOR_CALLER = "orchestrator.naive.identify"


@dataclass(frozen=True)
class CachedRun:
    fixture: str
    trace_id: str
    report_path: Path
    report: dict[str, Any]
    llm_row: dict[str, Any] | None
    predicted_spectra: dict[str, dict[str, Any]] | None = None
    """Mapping SMILES -> predicted Spectrum dict (CFM-ID output, from the
    Live runner's side-car). None if side-car not present for this run."""
    verifier_row: dict[str, Any] | None = None
    """VerifiedIdentification.model_dump() from the verifier sidecar.
    None if the sidecar is missing — Track V was never run for this
    trace, or the file was deleted. UI degrades gracefully (Panel 4
    shows a "no verifier verdict" message) when this is None."""


def _read_log_rows() -> list[dict[str, Any]]:
    if not _LOG_PATH.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in _LOG_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def list_log_trace_ids(*, caller: str = ORCHESTRATOR_CALLER) -> list[str]:
    return [r.get("trace_id") for r in _read_log_rows() if r.get("caller") == caller]


def _fixture_from_trace_id(trace_id: str) -> str | None:
    if not trace_id:
        return None
    # Longer names first so glucose_pos_fusion wins over glucose_pos.
    for fixture in sorted(CANONICAL_FIXTURES, key=len, reverse=True):
        if trace_id.endswith(fixture):
            return fixture
    if re.fullmatch(r"ident_[0-9a-f]{8}_\d{14}", trace_id):
        return None
    return None


def _candidate_report_paths(fixture: str, trace_id: str | None) -> list[Path]:
    paths: list[Path] = []
    if trace_id:
        paths.append(_DATA_CACHE / f"{trace_id}.json")
    paths.append(_TMP_O1 / f"{fixture}.json")
    if trace_id:
        paths.append(_REPO_PIPELINE_RUNS / f"{trace_id}.json")
    return paths


def find_report_path(fixture: str, trace_id: str | None = None) -> Path | None:
    for path in _candidate_report_paths(fixture, trace_id):
        if path.is_file():
            return path
    return None


def _load_json(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    start = text.find("{")
    if start > 0:
        text = text[start:]
    return json.loads(text)


def load_cached_run(
    fixture: str, *, trace_id: str | None = None
) -> CachedRun | None:
    rows = _read_log_rows()
    llm_row: dict[str, Any] | None = None
    if trace_id is not None:
        llm_row = next(
            (r for r in rows if r.get("trace_id") == trace_id), None
        )
    else:
        matches = [
            r
            for r in rows
            if r.get("caller") == ORCHESTRATOR_CALLER
            and _fixture_from_trace_id(r.get("trace_id", "") or "") == fixture
        ]
        if matches:
            llm_row = matches[-1]
            trace_id = llm_row.get("trace_id")

    report_path = find_report_path(fixture, trace_id)
    if report_path is None:
        return None

    try:
        report = _load_json(report_path)
    except (OSError, json.JSONDecodeError):
        return None

    predicted_spectra: dict[str, dict[str, Any]] | None = None
    if trace_id:
        sidecar = _DATA_CACHE / f"{trace_id}.predicted_spectra.json"
        if sidecar.is_file():
            try:
                predicted_spectra = json.loads(sidecar.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                predicted_spectra = None

    verifier_row = load_verifier_verdict(trace_id) if trace_id else None

    return CachedRun(
        fixture=fixture,
        trace_id=trace_id or f"({fixture}, no log row)",
        report_path=report_path,
        report=report,
        llm_row=llm_row,
        predicted_spectra=predicted_spectra,
        verifier_row=verifier_row,
    )


def load_verifier_verdict(trace_id: str) -> dict[str, Any] | None:
    """Read the verifier sidecar for ``trace_id`` if present.

    Returns the parsed VerifiedIdentification dump, or None when the
    sidecar is absent / unreadable. Never raises — verifier sidecars
    are optional supplements to a cached run, not load-bearing.
    """
    if not trace_id:
        return None
    path = _VERIFIER_RUNS / f"{trace_id}.verifier.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def verifier_sidecar_path(trace_id: str) -> Path:
    """Where the verifier sidecar would live for ``trace_id``.

    Returned regardless of whether the file exists — used by writers
    (the live runner persisting a freshly-computed verdict) as well as
    readers.
    """
    return _VERIFIER_RUNS / f"{trace_id}.verifier.json"


def list_cached_fixtures() -> list[str]:
    available: list[str] = []
    for fixture in CANONICAL_FIXTURES:
        run = load_cached_run(fixture)
        if run is not None:
            available.append(fixture)
    return available

"""End-to-end integration test for the naive orchestrator (Track O1 Part 3).

Makes REAL MiniMax calls. Gated on MINIMAX_API_KEY; skipped otherwise with
a clear reason. Each test redirects the JSONL log to a tmp file so the
repository's logs/llm_calls.jsonl is not mutated.

Scope intentionally narrow:
    - non-empty output returned from MiniMax for a synthetic report
    - logger appends one self-contained JSON line per identification
    - the line's trace_id matches the NaiveIdentification.trace_id

The test deliberately does NOT exercise the full pipeline (A1→E) — that
dependency is out of the metagent-llm env. Part 4 delivery captures the
real-pipeline fixture outputs via a manual two-step run (diffms →
metagent-llm) and pastes them verbatim into the writeup.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from common import llm_client
from orchestrator import identify
from schemas.common import Candidate, Spectrum
from schemas.molecule import MetaboliteInfoResponse
from schemas.report import CandidateReport, IdentificationReport


_NO_KEY_REASON = (
    "MINIMAX_API_KEY is not set; the naive-orchestrator end-to-end test "
    "requires a real MiniMax key to exercise the chat() path. Export it or "
    "run this test in an env where it's set."
)


def _minimax_key_missing() -> bool:
    return not os.environ.get("MINIMAX_API_KEY")


# --------------------------------------------------------------------------- #
# Lightweight synthetic IdentificationReport factory. Matches the shape the
# real pipeline emits for the three v0 fixtures, without depending on the
# pipeline's own deps (rdkit / matchms / torch).
# --------------------------------------------------------------------------- #


_FIXTURE_SPECS = {
    "glucose_pos": {
        "precursor": 181.0707,
        "neutral": 180.0634,
        "adduct": "[M+H]+",
        "mode": "positive",
        "truth_smiles": "OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O",
        "truth_name": "D-Glucose",
        "hmdb_id": "HMDB0000122",
        "formula": "C6H12O6",
        "pathways_hit": True,
        "is_zwitterion": False,
    },
    "caffeine_pos": {
        "precursor": 195.0877,
        "neutral": 194.0804,
        "adduct": "[M+H]+",
        "mode": "positive",
        "truth_smiles": "CN1C=NC2=C1C(=O)N(C(=O)N2C)C",
        "truth_name": "Caffeine",
        "hmdb_id": "HMDB0001847",
        "formula": "C8H10N4O2",
        "pathways_hit": True,
        "is_zwitterion": False,
    },
    "lcarnitine_pos": {
        "precursor": 162.1125,
        "neutral": 161.105,
        "adduct": "[M+H]+",
        "mode": "positive",
        "truth_smiles": "C[N+](C)(C)C[C@H](O)CC(=O)[O-]",
        "truth_name": "L-Carnitine",
        "hmdb_id": "HMDB0000062",
        "formula": "C7H16NO3",  # HMDB cation form — D-1
        "pathways_hit": False,
        "is_zwitterion": True,
    },
}


def _build_report(fixture_name: str) -> IdentificationReport:
    cfg = _FIXTURE_SPECS[fixture_name]
    spec = Spectrum(
        mz=[50.0, 89.0, 120.0, cfg["precursor"] - 18.0],
        intensity=[0.3, 0.6, 0.85, 1.0],
        precursor_mz=cfg["precursor"],
        adduct=cfg["adduct"],
        ionization_mode=cfg["mode"],
        collision_energy=20.0,
    )
    if cfg["is_zwitterion"]:
        info = MetaboliteInfoResponse(
            found=True,
            primary_name=f"{cfg['truth_name']} (HMDB cation form)",
            synonyms=[cfg["truth_name"].lower()],
            molecular_formula=cfg["formula"],
            exact_mass=162.113,  # HMDB cation — D-1 quirk, passed through
            smiles="C[N+](C)(C)C[C@H](O)CC(=O)O",
            inchikey="PHIQHXFUZVPYII-ZCFIWIBFSA-N",
            chemical_class="Quaternary ammonium",
            cross_refs={"hmdb": cfg["hmdb_id"]},
            source="hmdb",
            explain="HMDB returns the cation form — see Track D-1",
        )
        notes = [
            "zwitterion SMILES detected — HMDB may store the protonated "
            "cation form (D-1); mass_match_indicator uses the SMILES-"
            "derived neutral mass, not HMDB's exact_mass."
        ]
    else:
        info = MetaboliteInfoResponse(
            found=True,
            primary_name=cfg["truth_name"],
            synonyms=[cfg["truth_name"].lower()],
            molecular_formula=cfg["formula"],
            exact_mass=cfg["neutral"],
            smiles=cfg["truth_smiles"],
            inchikey=None,
            chemical_class="Sugar" if fixture_name == "glucose_pos" else "Xanthine",
            cross_refs={"hmdb": cfg["hmdb_id"]},
            source="hmdb",
            explain=f"synthetic metabolite info for {fixture_name}",
        )
        notes = []

    top = CandidateReport(
        candidate=Candidate(
            smiles=cfg["truth_smiles"],
            name=cfg["truth_name"],
            source="library",
            score=0.82,
            source_id=cfg["hmdb_id"],
            explain="top library match",
        ),
        prefilter_match=None,
        metabolite_info=info,
        pathway_context=None,
        predicted_spectrum_cosine=0.78,
        predicted_model_version="cfm-id-4.4.7",
        mass_match_indicator=1.0,
        pathway_presence_indicator=0.0,
        evidence_score=0.74,
        notes=notes,
    )
    return IdentificationReport(
        experimental_spectrum=spec,
        preprocess_quality_flag="good",
        neutral_mass_computed=cfg["neutral"],
        n_prefilter_candidates=10,
        n_library_candidates=5,
        n_generated_candidates=3,
        candidates=[top],
        pipeline_version="integration-test:synthetic",
        tool_versions={"cfm-id": "cfm-id-4.4.7"},
        warnings=[],
    )


@pytest.fixture
def tmp_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the JSONL logger to a tmp file so the repo log is untouched."""
    path = tmp_path / "llm_calls.jsonl"
    monkeypatch.setattr(llm_client, "_LOG_PATH", path)
    yield path


def _read_lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


@pytest.mark.requires_minimax_key
@pytest.mark.skipif(_minimax_key_missing(), reason=_NO_KEY_REASON)
def test_end_to_end_glucose(tmp_log: Path) -> None:
    """One real MiniMax call over a glucose-shaped synthetic report."""
    report = _build_report("glucose_pos")
    baseline = len(_read_lines(tmp_log))

    result = identify(report, trace_id="e2e-glucose-001")

    assert isinstance(result.llm_output, str)
    assert result.llm_output.strip(), "MiniMax returned an empty string"
    assert result.trace_id == "e2e-glucose-001"

    lines = _read_lines(tmp_log)
    assert len(lines) == baseline + 1, (
        f"expected one new log line; tmp log grew from {baseline} to {len(lines)}"
    )
    rec = lines[-1]
    assert rec["trace_id"] == "e2e-glucose-001"
    assert rec["caller"] == "orchestrator.naive.identify"
    assert rec["mock"] is False
    assert rec["error"] is None


@pytest.mark.requires_minimax_key
@pytest.mark.skipif(_minimax_key_missing(), reason=_NO_KEY_REASON)
def test_end_to_end_three_fixtures_log_joinable_by_trace_id(
    tmp_log: Path,
) -> None:
    """All three v0 fixtures can be joined between NaiveIdentification and
    logs/llm_calls.jsonl via trace_id — the acceptance signal for downstream
    evaluation."""
    trace_ids: dict[str, str] = {}
    for name in ("glucose_pos", "caffeine_pos", "lcarnitine_pos"):
        trace_id = f"e2e-join-{name}"
        report = _build_report(name)
        out = identify(report, trace_id=trace_id)
        assert out.trace_id == trace_id
        assert out.llm_output.strip(), f"empty LLM output for {name}"
        trace_ids[name] = out.trace_id

    log_rows = _read_lines(tmp_log)
    assert len(log_rows) == len(trace_ids), (
        f"expected {len(trace_ids)} log rows, got {len(log_rows)}"
    )

    by_trace_id = {row["trace_id"]: row for row in log_rows}
    for name, trace_id in trace_ids.items():
        assert trace_id in by_trace_id, (
            f"trace_id {trace_id!r} for {name} not joinable — "
            f"rows carry trace_ids: {list(by_trace_id)}"
        )
        rec = by_trace_id[trace_id]
        assert rec["caller"] == "orchestrator.naive.identify"
        assert rec["response_cleaned"]
        # The user-message must carry a candidates section — prove the
        # formatter actually ran in full, not a stub.
        user = next(
            (m for m in rec["messages"] if m.get("role") == "user"), None
        )
        assert user is not None
        assert "## Candidates" in user["content"]
        # The log's response_cleaned is the exact text the orchestrator
        # returned — sanity-check join direction.
        assert rec["response_cleaned"] in (
            by_trace_id[trace_id]["response_cleaned"],
        )


# --------------------------------------------------------------------------- #
# Marker registration (cosmetic — silences --strict-markers warnings).
# --------------------------------------------------------------------------- #


def pytest_configure(config):  # pragma: no cover — pytest plumbing
    config.addinivalue_line(
        "markers",
        "requires_minimax_key: integration test that performs a real MiniMax "
        "API call; skipped when MINIMAX_API_KEY is unset.",
    )

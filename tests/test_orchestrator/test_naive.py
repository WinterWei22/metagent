"""Unit tests for the naive orchestrator package (Track O1 Part 2).

All tests here use set_mock(); no real MiniMax call. The real-LLM end-to-end
test lives in tests/integration/test_orchestrator_e2e.py and is gated on
MINIMAX_API_KEY.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from common import llm_client
from orchestrator import NaiveIdentification, identify
from orchestrator.formatter import format_report_for_llm
from orchestrator.naive import hash_report
from orchestrator.prompt import SYSTEM_PROMPT
from schemas.common import Candidate, Spectrum
from schemas.molecule import MetaboliteInfoResponse
from schemas.report import CandidateReport, IdentificationReport


# --------------------------------------------------------------------------- #
# Fixture factory — self-contained, no disk, no pipeline dependencies.
# --------------------------------------------------------------------------- #


_NAMES = ["D-Glucose", "D-Fructose", "myo-Inositol", "D-Mannose", "D-Galactose"]
_SMI_GLUCOSE = "OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O"
_SMI_LCARNITINE_ZWITTER = "C[N+](C)(C)C[C@H](O)CC(=O)[O-]"
_SMI_LCARNITINE_CATION = "C[N+](C)(C)C[C@H](O)CC(=O)O"


def _make_report(
    n_candidates: int = 1,
    *,
    lcarnitine: bool = False,
) -> IdentificationReport:
    """Build a minimal, pipeline-free IdentificationReport suitable for tests."""
    spec = Spectrum(
        mz=[60.0, 91.0, 120.0, 163.1],
        intensity=[0.2, 0.5, 0.9, 1.0],
        precursor_mz=162.1125 if lcarnitine else 181.0707,
        adduct="[M+H]+",
        ionization_mode="positive",
        collision_energy=20.0,
    )
    candidates: list[CandidateReport] = []
    for i in range(n_candidates):
        if lcarnitine:
            smi = _SMI_LCARNITINE_ZWITTER
            name = "L-Carnitine"
            info = MetaboliteInfoResponse(
                found=True,
                primary_name="L-Carnitine (HMDB cation form)",
                synonyms=["L-carnitine"],
                molecular_formula="C7H16NO3",
                exact_mass=162.113,  # HMDB cation mass — D-1 quirk
                smiles=_SMI_LCARNITINE_CATION,
                inchikey="PHIQHXFUZVPYII-ZCFIWIBFSA-N",
                chemical_class="Quaternary ammonium",
                cross_refs={"hmdb": "HMDB0000062"},
                source="hmdb",
                explain="HMDB returns the cation form — see Track D-1",
            )
            notes = [
                "zwitterion SMILES detected — HMDB may store the protonated "
                "cation form (D-1); mass_match_indicator uses the SMILES-"
                "derived neutral mass, not HMDB's exact_mass."
            ]
        else:
            smi = _SMI_GLUCOSE
            name = _NAMES[i % len(_NAMES)]
            info = None
            notes = []

        cand = Candidate(
            smiles=smi,
            name=name,
            source="library",
            score=max(0.1, 0.9 - i * 0.15),
            source_id=f"HMDB00001{i:02d}",
            explain=f"rank {i} candidate",
        )
        candidates.append(
            CandidateReport(
                candidate=cand,
                prefilter_match=None,
                metabolite_info=info,
                pathway_context=None,
                predicted_spectrum_cosine=(0.85 if i == 0 else None),
                predicted_model_version=("cfm-id-4.4.7" if i == 0 else None),
                mass_match_indicator=1.0,
                pathway_presence_indicator=0.0,
                evidence_score=max(0.1, 0.82 - i * 0.13),
                notes=notes,
            )
        )

    return IdentificationReport(
        experimental_spectrum=spec,
        preprocess_quality_flag="good",
        neutral_mass_computed=161.105 if lcarnitine else 180.0634,
        n_prefilter_candidates=10,
        n_library_candidates=5,
        n_generated_candidates=3,
        candidates=candidates,
        pipeline_version="test:abcd123",
        tool_versions={"cfm-id": "cfm-id-4.4.7"},
        warnings=[],
    )


@pytest.fixture(autouse=True)
def _isolate_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Every test gets its own JSONL path; mock is cleared on teardown."""
    monkeypatch.setattr(llm_client, "_LOG_PATH", tmp_path / "llm.jsonl")
    yield
    llm_client.clear_mock()


# --------------------------------------------------------------------------- #
# identify()
# --------------------------------------------------------------------------- #


def test_identify_calls_llm_exactly_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    def fake_chat(messages, **kwargs):
        calls.append({"messages": messages, **kwargs})
        return "result"

    monkeypatch.setattr("orchestrator.naive.chat", fake_chat)
    identify(_make_report())
    assert len(calls) == 1, (
        f"naive orchestrator must call chat() exactly once per identification; got {len(calls)}"
    )


def test_identify_passes_trace_id_and_caller(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    def fake_chat(messages, **kwargs):
        seen.update(kwargs)
        return "x"

    monkeypatch.setattr("orchestrator.naive.chat", fake_chat)
    identify(_make_report(), trace_id="trace-explicit-001")
    assert seen.get("trace_id") == "trace-explicit-001"
    assert seen.get("caller") == "orchestrator.naive.identify"


def test_identify_returns_valid_schema() -> None:
    llm_client.set_mock(["result text"])
    out = identify(_make_report(), trace_id="t-1")
    assert isinstance(out, NaiveIdentification)
    assert out.trace_id == "t-1"
    assert len(out.source_report_hash) == 16
    assert out.llm_output == "result text"
    assert out.generated_at is not None


def test_identify_auto_trace_id_has_expected_shape() -> None:
    llm_client.set_mock(["x"])
    out = identify(_make_report())
    assert re.fullmatch(r"ident_[0-9a-f]{8}_\d{14}", out.trace_id), out.trace_id


def test_hash_report_stable_across_equal_reports() -> None:
    r1 = _make_report(n_candidates=3)
    r2 = _make_report(n_candidates=3)
    assert hash_report(r1) == hash_report(r2)
    # Sanity: different content -> different hash.
    r3 = _make_report(n_candidates=2)
    assert hash_report(r1) != hash_report(r3)


def test_identify_strip_thinking_applied_to_output() -> None:
    llm_client.set_mock(["<think>reasoning</think>final"])
    out = identify(_make_report(), trace_id="t-think")
    # chat() strips <think>; identify() surfaces the cleaned text.
    assert out.llm_output == "final"


# --------------------------------------------------------------------------- #
# Formatter
# --------------------------------------------------------------------------- #


def test_formatter_includes_all_top_candidates() -> None:
    report = _make_report(n_candidates=5)
    msg = format_report_for_llm(report, top_n=5)
    for name in _NAMES:
        assert name in msg, f"name {name!r} missing from user message:\n{msg}"
    for i in range(1, 6):
        assert f"### {i}." in msg, f"rank {i} block missing"


def test_formatter_respects_top_n() -> None:
    report = _make_report(n_candidates=5)
    msg = format_report_for_llm(report, top_n=3)
    assert "### 3." in msg
    assert "### 4." not in msg, "top_n=3 must not include rank 4"
    # Counts line still reports merged/enriched total.
    assert "merged/enriched: 5" in msg


def test_formatter_preserves_lcarnitine_zwitterion_mass() -> None:
    report = _make_report(n_candidates=1, lcarnitine=True)
    msg = format_report_for_llm(report)
    # HMDB's cation exact_mass (162.113) flows through verbatim.
    assert "162.113" in msg, (
        "HMDB cation exact_mass must pass through unchanged (D-1); formatter "
        f"must not silently correct it. Output:\n{msg}"
    )
    # Back-calculated neutral mass from precursor also shown as-is.
    assert "161.105" in msg
    # The D-1 note is preserved in the candidate notes block.
    assert "D-1" in msg or "zwitterion" in msg.lower()


def test_formatter_handles_empty_candidate_list() -> None:
    report = _make_report(n_candidates=0)
    msg = format_report_for_llm(report)
    assert "no candidates" in msg.lower()


def test_formatter_output_is_plain_text_non_empty() -> None:
    msg = format_report_for_llm(_make_report(n_candidates=2))
    assert msg.strip()
    assert msg.endswith("\n")
    # Sections are stable.
    for section in (
        "## Experimental spectrum",
        "## Candidates",
        "## Pipeline warnings",
        "## Tool versions",
        "## Pipeline metadata",
    ):
        assert section in msg, f"missing section: {section}"


# --------------------------------------------------------------------------- #
# Prompt guard — the whole point of Track O1 depends on this staying true.
# --------------------------------------------------------------------------- #


_FORBIDDEN_SUBSTRINGS = [
    "hallucinat",        # hallucinate / hallucination / hallucinating
    "do not speculate",
    "do not fabricate",
    "cite your source",
    "cite each claim",
    "refuse if uncertain",
    "only use facts",
    "only state facts",
    "supported by the data",
]


def test_prompt_does_not_contain_antihallucination_phrases() -> None:
    """Track O1 is a measurement apparatus. The system prompt MUST NOT steer
    the model away from hallucinating — that's the Verifier session's job."""
    lower = SYSTEM_PROMPT.lower()
    hits = [p for p in _FORBIDDEN_SUBSTRINGS if p in lower]
    assert not hits, (
        f"SYSTEM_PROMPT contains forbidden anti-hallucination phrasing: {hits}. "
        f"Track O1 measures the bare baseline. If you need these phrases for a "
        f"verifier session, put them in a separate prompt file there — do NOT "
        f"edit this one."
    )


def test_prompt_matches_brief_verbatim() -> None:
    """The brief lists the exact system prompt. Guard against silent edits."""
    # Spot-check: the four numbered directives and the word-cap instruction.
    expected_markers = [
        "1. States the most likely candidate and why.",
        "2. Discusses the top 3 candidates in order of evidence.",
        "3. Mentions relevant pathway context where available.",
        "4. Notes the limitations or caveats visible in the data.",
        "Keep the report under 400 words.",
        "Write for a chemist reading it.",
    ]
    for marker in expected_markers:
        assert marker in SYSTEM_PROMPT, (
            f"SYSTEM_PROMPT missing the brief's verbatim marker: {marker!r}"
        )


# --------------------------------------------------------------------------- #
# CLI (tests/test_orchestrator lives in unit suite; no real LLM here either)
# --------------------------------------------------------------------------- #


def test_cli_report_json_end_to_end_text(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = _make_report(n_candidates=2)
    json_path = tmp_path / "report.json"
    json_path.write_text(report.model_dump_json(), encoding="utf-8")

    llm_client.set_mock(["FROM_LLM_OUTPUT"])
    from orchestrator.__main__ import main as cli_main

    exit_code = cli_main(
        ["identify", "--report-json", str(json_path), "--trace-id", "cli-1"]
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "FROM_LLM_OUTPUT" in out


def test_cli_report_json_output_json_mode(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = _make_report()
    json_path = tmp_path / "r.json"
    json_path.write_text(report.model_dump_json(), encoding="utf-8")

    llm_client.set_mock(["TEXT_FROM_LLM"])
    from orchestrator.__main__ import main as cli_main

    exit_code = cli_main(
        [
            "identify",
            "--report-json",
            str(json_path),
            "--output",
            "json",
            "--trace-id",
            "t-json",
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    parsed = json.loads(out)
    assert parsed["trace_id"] == "t-json"
    assert parsed["llm_output"] == "TEXT_FROM_LLM"
    assert len(parsed["source_report_hash"]) == 16
    assert "generated_at" in parsed


def test_cli_fixture_and_report_json_are_mutually_exclusive(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from orchestrator.__main__ import main as cli_main

    exit_code = cli_main(
        ["identify", "--fixture", "glucose_pos", "--report-json", "/tmp/x.json"]
    )
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "mutually exclusive" in err


def test_cli_requires_one_input(capsys: pytest.CaptureFixture[str]) -> None:
    from orchestrator.__main__ import main as cli_main

    exit_code = cli_main(["identify"])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "required" in err

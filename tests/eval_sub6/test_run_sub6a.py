"""End-to-end mocked tests for evaluation.sub6.run_sub6a."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import pytest

from evaluation.sub6.run_sub6a import run_sub6a, run_sub6a_batch


@dataclass
class _MockCandidate:
    smiles: str
    name: str
    score: float
    source: str = "library"
    source_id: str | None = None


@dataclass
class _MockResponse:
    candidates: list[_MockCandidate]
    libraries_searched: list[str] | None = None
    n_total_compared: int = 0
    explain: str = "mock"


def _make_task(tid: str = "T1") -> dict:
    """Two spectra: one whose GT inchikey will match the (mocked) top-1
    survivor, one whose top-1 self-matches and gets excluded."""
    return {
        "task_id": tid,
        "differential_spectra": [
            {
                "spectrum_id": "sp1",
                "source_id": "GNPS-A",
                "inchikey_first_block": "LFQSCWFLJHTTHZ",  # ethanol
                "ion_mode": "positive",
                "adduct": "[M+H]1+",
                "precursor_mz": 47.05,
                "n_peaks": 3,
                "peaks": [[20.0, 50.0], [30.0, 100.0], [45.0, 25.0]],
            },
            {
                "spectrum_id": "sp2",
                "source_id": "GNPS-B",
                "inchikey_first_block": "OUYCCCASQSFEME",  # tyrosine
                "ion_mode": "positive",
                "adduct": "[M+H]1+",
                "precursor_mz": 182.08,
                "n_peaks": 3,
                "peaks": [[100.0, 50.0], [120.0, 100.0], [150.0, 25.0]],
            },
        ],
        "ground_truth_pathway": {"pathway_name": "X"},
        "ground_truth_signal_compounds": [],
        "ground_truth_noise_compounds": [],
        "ramp_enrichment_result": {"top_pathways": []},
    }


def _mock_lib_factory(by_spectrum_id: dict[str, _MockResponse]):
    """Returns a library_search_fn that picks response by precursor_mz
    matching one of the test spectra (since LibrarySearchRequest doesn't
    carry spectrum_id)."""
    state = {"i": 0}
    responses = list(by_spectrum_id.values())

    def fn(req):
        i = state["i"]
        if i >= len(responses):
            raise IndexError("library_search mock exhausted")
        state["i"] += 1
        return responses[i]

    return fn


def _mock_chat_factory(narrative: str = "Tyrosine metabolism is dominant."):
    def chat(messages, *, temperature, model, trace_id, caller):
        return narrative

    return chat


def test_runs_per_spectrum_identification_then_one_llm_call():
    task = _make_task()
    lib = _mock_lib_factory({
        "sp1": _MockResponse(candidates=[
            _MockCandidate(smiles="CCO", name="ethanol", score=0.9,
                           source_id="GNPS-OTHER1"),
        ]),
        "sp2": _MockResponse(candidates=[
            _MockCandidate(smiles="C1=CC(=CC=C1CC(C(=O)O)N)O",
                           name="tyrosine", score=0.85,
                           source_id="GNPS-OTHER2"),
        ]),
    })
    chat = _mock_chat_factory()
    res = run_sub6a(task, chat_fn=chat, library_search_fn=lib, model="mock")
    assert res.n_spectra == 2
    assert res.n_identified == 2
    # Both inchikeys should match GT → identification_accuracy == 1.0
    assert res.identification_accuracy == pytest.approx(1.0)
    # Single LLM call rendered the dedup'd metabolite list.
    assert res.llm_calls == 1
    assert "Tyrosine metabolism" in res.narrative


def test_self_match_excluded_per_task():
    task = _make_task()
    # sp1 returns ONLY its own self (GNPS-A) → after exclusion, nothing.
    # sp2 also returns only its own self → after exclusion, nothing.
    lib = _mock_lib_factory({
        "sp1": _MockResponse(candidates=[
            _MockCandidate(smiles="CCO", name="ethanol", score=0.99,
                           source_id="GNPS-A"),
        ]),
        "sp2": _MockResponse(candidates=[
            _MockCandidate(smiles="CCO", name="self", score=0.99,
                           source_id="GNPS-B"),
        ]),
    })
    chat = _mock_chat_factory()
    res = run_sub6a(task, chat_fn=chat, library_search_fn=lib, model="mock")
    assert res.n_identified == 0
    assert res.llm_calls == 0
    assert res.error is not None and "no spectra identified" in res.error


def test_dedupes_metabolite_list_across_spectra():
    task = _make_task()
    # Both spectra resolve to the same compound — prompt must list it once.
    lib = _mock_lib_factory({
        "sp1": _MockResponse(candidates=[
            _MockCandidate(smiles="CCO", name="ethanol", score=0.9,
                           source_id="GNPS-X"),
        ]),
        "sp2": _MockResponse(candidates=[
            _MockCandidate(smiles="CCO", name="ethanol", score=0.85,
                           source_id="GNPS-Y"),
        ]),
    })
    chat = _mock_chat_factory()
    res = run_sub6a(task, chat_fn=chat, library_search_fn=lib, model="mock")
    iks = [m["inchikey_first_block"] for m in res.identified_metabolites]
    assert len(iks) == len(set(iks))


def test_no_ground_truth_in_chat_call_arguments():
    """Belt-and-braces: confirm the LLM never sees ground_truth_*."""
    captured: list[list[dict]] = []

    def chat(messages, *, temperature, model, trace_id, caller):
        captured.append(messages)
        return "ok"

    task = _make_task()
    task["ground_truth_pathway"]["pathway_name"] = "SECRET_PATHWAY_XYZ"
    task["ground_truth_signal_compounds"] = ["LEAKED_C001"]

    lib = _mock_lib_factory({
        "sp1": _MockResponse(candidates=[
            _MockCandidate(smiles="CCO", name="ethanol", score=0.9, source_id="X1"),
        ]),
        "sp2": _MockResponse(candidates=[
            _MockCandidate(smiles="CCO", name="ethanol", score=0.85, source_id="X2"),
        ]),
    })
    run_sub6a(task, chat_fn=chat, library_search_fn=lib, model="mock")
    blob = json.dumps(captured)
    assert "SECRET_PATHWAY_XYZ" not in blob
    assert "LEAKED_C001" not in blob
    assert "ground_truth" not in blob.lower()


def test_batch_idempotent_resume(tmp_path):
    tasks_path = tmp_path / "sub6a.jsonl"
    out_path = tmp_path / "sub6a_out.jsonl"
    with tasks_path.open("w") as f:
        f.write(json.dumps(_make_task("T1")) + "\n")
        f.write(json.dumps(_make_task("T2")) + "\n")

    lib = _mock_lib_factory({
        "sp1": _MockResponse(candidates=[
            _MockCandidate(smiles="CCO", name="ethanol", score=0.9, source_id="X")
        ]),
        "sp2": _MockResponse(candidates=[
            _MockCandidate(smiles="CCO", name="ethanol", score=0.9, source_id="Y")
        ]),
        "sp1_2": _MockResponse(candidates=[
            _MockCandidate(smiles="CCO", name="ethanol", score=0.9, source_id="Z")
        ]),
        "sp2_2": _MockResponse(candidates=[
            _MockCandidate(smiles="CCO", name="ethanol", score=0.9, source_id="W")
        ]),
    })
    chat = _mock_chat_factory()
    res1 = run_sub6a_batch(tasks_path, out_path, chat_fn=chat,
                           library_search_fn=lib, model="mock")
    assert {r.task_id for r in res1} == {"T1", "T2"}

    # Re-run: a fresh lib that would raise on any call.
    def boom(req):
        raise RuntimeError("should not be called")

    def boom_chat(*a, **k):
        raise RuntimeError("should not be called")

    res2 = run_sub6a_batch(tasks_path, out_path, chat_fn=boom_chat,
                           library_search_fn=boom, model="mock")
    assert res2 == []


# ---------------------------------------------------------------------------
# Phase 6.1 ablation — libraries pass-through + skip_narrative short-circuit
# ---------------------------------------------------------------------------


def test_libraries_kwarg_threaded_into_library_search_request():
    """run_sub6a's ``libraries=`` kwarg must reach the LibrarySearchRequest
    so the MS-CLIP ablation can flip retrieval libraries from the CLI."""
    captured: list[list[str]] = []

    def lib_fn(req):
        captured.append(list(req.libraries))
        return _MockResponse(
            candidates=[
                _MockCandidate(
                    smiles="CCO", name="ethanol", score=0.9,
                    source_id="OTHER",
                ),
            ],
        )

    task = _make_task()
    chat = _mock_chat_factory()

    # Default — must be ("gnps",) so v2 baseline behaviour is preserved.
    captured.clear()
    run_sub6a(task, chat_fn=chat, library_search_fn=lib_fn, model="mock")
    assert captured, "library_search_fn was never called"
    assert all(libs == ["gnps"] for libs in captured), captured

    # Override — ("gnps", "inhouse") flows through verbatim.
    captured.clear()
    run_sub6a(
        task,
        chat_fn=chat,
        library_search_fn=lib_fn,
        model="mock",
        libraries=("gnps", "inhouse"),
    )
    assert captured, "library_search_fn was never called"
    assert all(libs == ["gnps", "inhouse"] for libs in captured), captured


def test_skip_narrative_short_circuits_llm_call():
    """When skip_narrative=True the LLM chat function must NOT be called.
    Identification still runs and id_acc is populated."""
    chat_calls: list = []

    def chat(*args, **kwargs):
        chat_calls.append((args, kwargs))
        return "should not be called"

    def lib_fn(req):
        return _MockResponse(
            candidates=[
                _MockCandidate(
                    smiles="CCO", name="ethanol", score=0.9,
                    source_id="OTHER",
                ),
            ],
        )

    task = _make_task()

    # Default — chat_fn IS called once.
    chat_calls.clear()
    res = run_sub6a(task, chat_fn=chat, library_search_fn=lib_fn, model="mock")
    assert chat_calls, "default run should have called chat"
    assert res.llm_calls == 1

    # skip_narrative=True — chat_fn must NOT be called.
    chat_calls.clear()
    res = run_sub6a(
        task,
        chat_fn=chat,
        library_search_fn=lib_fn,
        model="mock",
        skip_narrative=True,
    )
    assert chat_calls == [], (
        f"skip_narrative=True must short-circuit the LLM call; got "
        f"{len(chat_calls)} calls"
    )
    assert res.llm_calls == 0
    assert res.narrative == ""
    # Identification still ran — id_acc populated.
    assert res.n_spectra == 2
    assert res.identification_accuracy >= 0.0
    # The error field flags the skip explicitly so log readers know why
    # narrative is empty.
    assert "skip_narrative" in (res.error or ""), res.error

"""End-to-end mocked tests for evaluation.sub6.run_sub6b."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import pytest

from evaluation.sub6.run_sub6b import run_sub6b, run_sub6b_batch


def _mock_chat_factory(responses: list[str]):
    """Build a chat_fn that returns ``responses`` in order on each call."""
    state = {"i": 0}

    def chat(messages, *, temperature, model, trace_id, caller):
        i = state["i"]
        if i >= len(responses):
            raise IndexError("mock exhausted")
        state["i"] += 1
        return responses[i]

    return chat


def _make_task(tid: str, names: list[str]) -> dict:
    return {
        "task_id": tid,
        "differential_metabolites": [{"name": n, "kegg_id": "C0000"} for n in names],
        "ground_truth_pathway": {"pathway_name": "X"},
        "ground_truth_signal_compounds": [],
        "ground_truth_noise_compounds": [],
        "ramp_enrichment_result": {"top_pathways": []},
    }


def test_single_task_ok():
    chat = _mock_chat_factory(["Tyrosine metabolism is the answer."])
    res = run_sub6b(
        _make_task("T1", ["Tyrosine"]),
        chat_fn=chat,
        model="mock",
    )
    assert res.task_id == "T1"
    assert res.narrative == "Tyrosine metabolism is the answer."
    assert res.error is None
    assert res.llm_calls == 1


def test_single_task_chat_error_captured():
    def boom(*a, **kw):
        raise RuntimeError("mock failure")

    res = run_sub6b(
        _make_task("T2", ["X"]),
        chat_fn=boom,
        model="mock",
    )
    assert res.error is not None
    assert "RuntimeError" in res.error
    assert res.narrative == ""
    assert res.llm_calls == 0


def test_batch_idempotent_skips_completed_task_ids(tmp_path):
    tasks_path = tmp_path / "tasks.jsonl"
    out_path = tmp_path / "out.jsonl"
    with tasks_path.open("w") as f:
        f.write(json.dumps(_make_task("T1", ["A"])) + "\n")
        f.write(json.dumps(_make_task("T2", ["B"])) + "\n")

    chat1 = _mock_chat_factory(["narr-1", "narr-2"])
    res1 = run_sub6b_batch(tasks_path, out_path, chat_fn=chat1, model="mock")
    assert {r.task_id for r in res1} == {"T1", "T2"}

    # Re-run: a fresh chat_fn that would raise IndexError if invoked.
    chat2 = _mock_chat_factory([])
    res2 = run_sub6b_batch(tasks_path, out_path, chat_fn=chat2, model="mock")
    assert res2 == []  # nothing processed; both task_ids already in out_path


def test_batch_respects_limit(tmp_path):
    tasks_path = tmp_path / "tasks.jsonl"
    out_path = tmp_path / "out.jsonl"
    with tasks_path.open("w") as f:
        for i in range(5):
            f.write(json.dumps(_make_task(f"T{i}", ["A"])) + "\n")

    chat = _mock_chat_factory(["x"] * 5)
    res = run_sub6b_batch(tasks_path, out_path, chat_fn=chat, model="mock", limit=2)
    assert len(res) == 2
    assert {r.task_id for r in res} == {"T0", "T1"}


def test_batch_appends_full_record(tmp_path):
    tasks_path = tmp_path / "tasks.jsonl"
    out_path = tmp_path / "out.jsonl"
    with tasks_path.open("w") as f:
        f.write(json.dumps(_make_task("T1", ["A", "B", "C"])) + "\n")

    chat = _mock_chat_factory(["the narrative"])
    run_sub6b_batch(tasks_path, out_path, chat_fn=chat, model="mock")

    rec = json.loads(out_path.read_text().strip())
    assert rec["task_id"] == "T1"
    assert rec["narrative"] == "the narrative"
    assert rec["metabolite_count"] == 3
    assert rec["llm_model"] == "mock"
    assert rec["error"] is None


def test_no_ground_truth_in_chat_call_arguments():
    """Belt-and-braces: confirm we don't accidentally hand task['ground_truth_*']
    to the LLM via the messages payload.
    """
    captured: list[list[dict]] = []

    def chat(messages, *, temperature, model, trace_id, caller):
        captured.append(messages)
        return "ok"

    task = _make_task("T1", ["Tyrosine"])
    task["ground_truth_pathway"]["pathway_name"] = "SECRET_PATHWAY_XYZ"
    task["ground_truth_signal_compounds"] = ["LEAKED_C001"]
    run_sub6b(task, chat_fn=chat, model="mock")
    blob = json.dumps(captured)
    assert "SECRET_PATHWAY_XYZ" not in blob
    assert "LEAKED_C001" not in blob
    assert "ground_truth" not in blob.lower()

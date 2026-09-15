"""Mocked tests for Sub-6 narrative LLM routing."""
from __future__ import annotations

import json
import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from evaluation.sub6.run_sub6b import resolve_narrative_llm, run_sub6b_batch
from common import llm_client


def _make_task(tid: str) -> dict:
    return {
        "task_id": tid,
        "differential_metabolites": [{"name": "Estradiol", "kegg_id": "C00951"}],
        "ground_truth_pathway": {"pathway_name": "SECRET"},
        "ground_truth_signal_compounds": [],
        "ground_truth_noise_compounds": [],
        "ramp_enrichment_result": {"top_pathways": []},
    }


def _run_one(tmp_path, narrative_llm: str) -> tuple[dict, dict]:
    provider, model = resolve_narrative_llm(narrative_llm)
    tasks_path = tmp_path / f"{narrative_llm}_tasks.jsonl"
    out_path = tmp_path / f"{narrative_llm}_out.jsonl"
    tasks_path.write_text(json.dumps(_make_task("T1")) + "\n")
    captured: dict = {}

    def chat(messages, **kwargs):
        captured.update(kwargs)
        return f"narrative from {narrative_llm}"

    run_sub6b_batch(
        tasks_path,
        out_path,
        chat_fn=chat,
        model=model,
        provider=provider,
        limit=1,
    )
    record = json.loads(out_path.read_text().strip())
    return captured, record


def test_narrative_llm_minimax_routes_to_minimax_model(tmp_path):
    captured, record = _run_one(tmp_path, "minimax")
    assert captured["model"] == "MiniMax-M2.7-highspeed"
    assert captured["provider"] == "minimax"
    assert record["llm_model"] == "MiniMax-M2.7-highspeed"


def test_narrative_llm_gpt55_routes_to_gpt55_model(tmp_path):
    captured, record = _run_one(tmp_path, "gpt55")
    assert captured["model"] == "gpt-5.5"
    assert captured["provider"] == "openai"
    assert record["llm_model"] == "gpt-5.5"


def test_narrative_llm_opus47_routes_to_opus47_model(tmp_path):
    captured, record = _run_one(tmp_path, "opus47")
    assert captured["model"] == "claude-opus-4-7"
    assert captured["provider"] == "openai"
    assert record["llm_model"] == "claude-opus-4-7"


def test_routing_works_with_llm_client_set_mock(tmp_path):
    provider, model = resolve_narrative_llm("gpt55")
    tasks_path = tmp_path / "tasks.jsonl"
    out_path = tmp_path / "out.jsonl"
    tasks_path.write_text(json.dumps(_make_task("T1")) + "\n")

    llm_client.set_mock(["mocked via llm_client"])
    try:
        run_sub6b_batch(
            tasks_path,
            out_path,
            model=model,
            provider=provider,
            limit=1,
        )
    finally:
        llm_client.clear_mock()

    record = json.loads(out_path.read_text().strip())
    assert record["llm_model"] == "gpt-5.5"
    assert record["narrative"] == "mocked via llm_client"

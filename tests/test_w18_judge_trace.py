from __future__ import annotations

import json
import importlib

from verifier.schemas import ClaimType


def _trace_module():
    return importlib.import_module("verifier.helpers.judge_trace")


def test_write_judge_trace_appends_jsonl(tmp_path):
    mod = _trace_module()
    path = tmp_path / "judge_trace.jsonl"

    mod.write_judge_trace(
        path=path,
        task_id="task-1",
        iteration=1,
        claim_id="claim-1",
        claim_type=ClaimType.GROUNDED,
        verdict="SUPPORTED",
        parser_success=True,
        cost_usd=0.0021,
        confidence=0.91,
    )

    row = json.loads(path.read_text(encoding="utf-8").strip())
    assert row["task_id"] == "task-1"
    assert row["iteration"] == 1
    assert row["claim_id"] == "claim-1"
    assert row["claim_type"] == "grounded_claim"
    assert row["verdict"] == "SUPPORTED"
    assert row["parser_success"] is True
    assert row["cost_usd"] == 0.0021
    assert row["confidence"] == 0.91


def test_default_trace_path_tracks_llm_log_path(monkeypatch, tmp_path):
    mod = _trace_module()
    llm_log = tmp_path / "w18_path_x_post_llm_judge.jsonl"
    monkeypatch.setenv("METAGENT_LLM_LOG_PATH", str(llm_log))

    assert mod.default_judge_trace_path() == tmp_path / "w18_path_x_post_llm_judge_judge_trace.jsonl"

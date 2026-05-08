"""Unit tests for evaluation/sub6/persist.py (phase A2 D2).

Acceptance focus:
  - 1 task 跑到一半 SIGINT 断, find_partial_tasks 能识别 (spec D2)
  - partial detection is FAST (no JSONL parse) and TOLERANT (handles
    partial-line corruption)
  - record_* methods never raise on JSON-serialisable inputs
  - dataclass / Pydantic-model arguments are coerced
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import pytest

from evaluation.sub6.persist import (
    TaskPersister,
    find_complete_tasks,
    find_partial_tasks,
)


# ---------------------------------------------------------------------------
# Basic lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_record_turn_writes_jsonl(self, tmp_path):
        p = TaskPersister(tmp_path, "task_alpha")
        p.record_turn(
            iter_idx=0,
            turn_idx=0,
            assistant_message={"role": "assistant", "content": "hi"},
            tool_calls_log=[{"name": "query_ramp_enrichment", "result": {}}],
        )
        turns = (tmp_path / "task_alpha" / "turns.jsonl").read_text().splitlines()
        assert len(turns) == 1
        rec = json.loads(turns[0])
        assert rec["iter_idx"] == 0
        assert rec["turn_idx"] == 0
        assert rec["assistant_message"]["content"] == "hi"
        assert rec["tool_calls_log"][0]["name"] == "query_ramp_enrichment"

    def test_multiple_turns_appended(self, tmp_path):
        p = TaskPersister(tmp_path, "t")
        for i in range(3):
            p.record_turn(
                iter_idx=0, turn_idx=i,
                assistant_message={"role": "assistant", "content": f"turn {i}"},
            )
        lines = (tmp_path / "t" / "turns.jsonl").read_text().splitlines()
        assert len(lines) == 3
        assert [json.loads(l)["turn_idx"] for l in lines] == [0, 1, 2]

    def test_record_iteration(self, tmp_path):
        p = TaskPersister(tmp_path, "t")
        p.record_iteration(
            iter_idx=0,
            narrative="initial",
            verdict_summary={"contradicted": 1, "supported": 5},
            n_tool_calls=4,
            n_turns=3,
            force_finalised=False,
            feedback_prompt_used=False,
        )
        rec = json.loads((tmp_path / "t" / "iterations.jsonl").read_text())
        assert rec["narrative"] == "initial"
        assert rec["verdict_summary"]["contradicted"] == 1

    def test_mark_complete_writes_final_state(self, tmp_path):
        p = TaskPersister(tmp_path, "t")
        p.record_turn(iter_idx=0, turn_idx=0, assistant_message={"role": "assistant"})
        p.mark_complete(
            final_narrative="done",
            n_iterations=1,
            n_total_tool_calls=4,
            elapsed_seconds=42.0,
        )
        assert (tmp_path / "t" / "final_state.json").is_file()
        rec = json.loads((tmp_path / "t" / "final_state.json").read_text())
        assert rec["final_narrative"] == "done"
        assert rec["n_iterations"] == 1
        assert rec["error"] is None

    def test_is_complete_flag(self, tmp_path):
        p = TaskPersister(tmp_path, "t")
        assert not p.is_complete()
        p.mark_complete(
            final_narrative="x", n_iterations=0, n_total_tool_calls=0,
            elapsed_seconds=1.0,
        )
        assert p.is_complete()


# ---------------------------------------------------------------------------
# Partial detection (D2 acceptance scenario)
# ---------------------------------------------------------------------------


class TestPartialDetection:
    def test_complete_task_not_partial(self, tmp_path):
        p = TaskPersister(tmp_path, "complete_task")
        p.record_turn(iter_idx=0, turn_idx=0, assistant_message={"role": "a"})
        p.mark_complete(final_narrative="x", n_iterations=1,
                        n_total_tool_calls=1, elapsed_seconds=1.0)
        assert find_partial_tasks(tmp_path) == []
        assert find_complete_tasks(tmp_path) == ["complete_task"]

    def test_interrupted_task_is_partial(self, tmp_path):
        # Simulates SIGINT: turns.jsonl exists, no final_state.json
        p = TaskPersister(tmp_path, "interrupted_task")
        p.record_turn(iter_idx=0, turn_idx=0, assistant_message={"role": "a"})
        p.record_turn(iter_idx=0, turn_idx=1, assistant_message={"role": "a"})
        # NOT calling mark_complete — simulates mid-run interrupt.
        assert find_partial_tasks(tmp_path) == ["interrupted_task"]
        assert find_complete_tasks(tmp_path) == []

    def test_empty_persist_dir_returns_empty(self, tmp_path):
        assert find_partial_tasks(tmp_path) == []
        assert find_complete_tasks(tmp_path) == []

    def test_nonexistent_persist_dir_returns_empty(self, tmp_path):
        nonexist = tmp_path / "does_not_exist"
        assert find_partial_tasks(nonexist) == []
        assert find_complete_tasks(nonexist) == []

    def test_dir_with_no_jsonl_not_listed(self, tmp_path):
        # An empty task dir (created by the persister but never written to)
        # should not be flagged as partial.
        TaskPersister(tmp_path, "started_but_silent")
        assert find_partial_tasks(tmp_path) == []
        assert find_complete_tasks(tmp_path) == []

    def test_mixed_persist_dir(self, tmp_path):
        # 3 tasks: complete, interrupted, never-started
        c = TaskPersister(tmp_path, "complete_one")
        c.record_turn(iter_idx=0, turn_idx=0, assistant_message={"role": "a"})
        c.mark_complete(final_narrative="x", n_iterations=1,
                        n_total_tool_calls=1, elapsed_seconds=1.0)

        i = TaskPersister(tmp_path, "interrupted_one")
        i.record_turn(iter_idx=0, turn_idx=0, assistant_message={"role": "a"})
        # no mark_complete

        TaskPersister(tmp_path, "never_started_one")
        # no record_turn either

        assert find_partial_tasks(tmp_path) == ["interrupted_one"]
        assert find_complete_tasks(tmp_path) == ["complete_one"]

    def test_partial_with_corrupt_last_line_still_detected(self, tmp_path):
        # Simulate a power-loss mid-write: turns.jsonl ends with a
        # truncated line. find_partial_tasks must NOT crash because it
        # only stat()s the file, never parses contents.
        p = TaskPersister(tmp_path, "corrupt_task")
        p.record_turn(iter_idx=0, turn_idx=0, assistant_message={"role": "a"})
        # Append a half-line manually:
        with (tmp_path / "corrupt_task" / "turns.jsonl").open("a", encoding="utf-8") as f:
            f.write('{"ts": "2026')  # intentionally truncated; no newline
        # Not calling mark_complete:
        assert find_partial_tasks(tmp_path) == ["corrupt_task"]


# ---------------------------------------------------------------------------
# Coercion of dataclasses / pydantic
# ---------------------------------------------------------------------------


@dataclass
class _StubToolCall:
    name: str
    cached: bool


class TestCoercion:
    def test_dataclass_assistant_message_serialised(self, tmp_path):
        p = TaskPersister(tmp_path, "t")
        p.record_turn(
            iter_idx=0, turn_idx=0,
            assistant_message={"role": "assistant", "content": "x"},
            tool_calls_log=[_StubToolCall(name="q", cached=False)],
        )
        rec = json.loads((tmp_path / "t" / "turns.jsonl").read_text())
        assert rec["tool_calls_log"][0] == {"name": "q", "cached": False}

    def test_pydantic_model_coerced_via_model_dump(self, tmp_path):
        from pydantic import BaseModel

        class _Item(BaseModel):
            x: int
            y: str

        p = TaskPersister(tmp_path, "t")
        p.record_turn(
            iter_idx=0, turn_idx=0,
            assistant_message=None,
            tool_calls_log=[_Item(x=42, y="hello")],
        )
        rec = json.loads((tmp_path / "t" / "turns.jsonl").read_text())
        assert rec["tool_calls_log"][0] == {"x": 42, "y": "hello"}


# ---------------------------------------------------------------------------
# Error robustness
# ---------------------------------------------------------------------------


class TestErrorRobustness:
    def test_record_turn_with_none_message(self, tmp_path):
        # Some assistant messages have content=None when only tool_calls
        # are present. record_turn must accept that.
        p = TaskPersister(tmp_path, "t")
        p.record_turn(iter_idx=0, turn_idx=0, assistant_message=None)
        rec = json.loads((tmp_path / "t" / "turns.jsonl").read_text())
        assert rec["assistant_message"] is None

    def test_mark_complete_with_error(self, tmp_path):
        p = TaskPersister(tmp_path, "t")
        p.mark_complete(
            final_narrative="",
            n_iterations=0,
            n_total_tool_calls=0,
            elapsed_seconds=10.0,
            error="timeout_fallback_used",
        )
        rec = json.loads((tmp_path / "t" / "final_state.json").read_text())
        assert rec["error"] == "timeout_fallback_used"
        # Even on error, the task counts as COMPLETE (the runner finished
        # producing some terminal state — partial means the process died
        # before any terminal state was written).
        assert find_complete_tasks(tmp_path) == ["t"]
        assert find_partial_tasks(tmp_path) == []

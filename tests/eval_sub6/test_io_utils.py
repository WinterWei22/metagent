"""Unit tests for evaluation.sub6.io_utils."""
from __future__ import annotations

import json
import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from evaluation.sub6.io_utils import (
    append_jsonl,
    iter_jsonl,
    load_completed_task_ids,
)


def test_load_completed_handles_missing_file(tmp_path):
    assert load_completed_task_ids(tmp_path / "no_file.jsonl") == set()


def test_append_then_load(tmp_path):
    path = tmp_path / "out.jsonl"
    append_jsonl(path, {"task_id": "T1", "narrative": "abc"})
    append_jsonl(path, {"task_id": "T2", "narrative": "def"})
    assert load_completed_task_ids(path) == {"T1", "T2"}


def test_partial_trailing_line_is_tolerated(tmp_path):
    path = tmp_path / "out.jsonl"
    append_jsonl(path, {"task_id": "T1"})
    with path.open("a") as f:
        f.write('{"task_id": "T2", "narrative": "incomplete')  # truncated, no newline
    assert load_completed_task_ids(path) == {"T1"}


def test_iter_jsonl_returns_records_in_order(tmp_path):
    path = tmp_path / "out.jsonl"
    append_jsonl(path, {"task_id": "T1", "x": 1})
    append_jsonl(path, {"task_id": "T2", "x": 2})
    out = list(iter_jsonl(path))
    assert [r["task_id"] for r in out] == ["T1", "T2"]


def test_append_creates_parent_directory(tmp_path):
    nested = tmp_path / "deep" / "deeper" / "out.jsonl"
    append_jsonl(nested, {"task_id": "T1"})
    assert nested.exists()
    assert json.loads(nested.read_text().strip())["task_id"] == "T1"

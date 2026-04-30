"""Idempotent JSONL helpers for Sub-6 runners.

Both ``run_sub6b`` and ``run_sub6a`` write per-task records to a JSONL
file. A 3-hour Sub-6A crash at task 12 should not re-run tasks 1-11, so
we read the existing file at startup and skip already-completed task IDs.

The append is line-buffered (one ``f.write`` + ``f.flush()`` per task)
so a SIGKILL still leaves the file in a parseable state — at worst the
last record is partial; the resume logic tolerates a trailing partial
line.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable


def load_completed_task_ids(jsonl_path: Path | str) -> set[str]:
    """Return the set of ``task_id``s already present in the JSONL file."""
    p = Path(jsonl_path)
    if not p.exists():
        return set()
    out: set[str] = set()
    with p.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                # Tolerate trailing partial line from a SIGKILL.
                continue
            tid = rec.get("task_id")
            if isinstance(tid, str):
                out.add(tid)
    return out


def append_jsonl(jsonl_path: Path | str, record: dict) -> None:
    """Append one JSON record to the file, flushing immediately."""
    p = Path(jsonl_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        f.flush()


def iter_jsonl(jsonl_path: Path | str) -> Iterable[dict]:
    """Yield records from a JSONL file, skipping blanks / partial lines."""
    p = Path(jsonl_path)
    if not p.exists():
        return
    with p.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue

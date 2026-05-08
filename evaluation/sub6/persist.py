"""Per-task message / iteration persistence for the A2 feedback loop.

A2's ReAct + feedback runner can lose 30+ tool-call seconds of work to
a single viviai disconnect (A1 audit debt #3). This module dumps every
turn's assistant message + tool results to disk as it happens, so a
mid-run failure leaves a partial trace on disk instead of nothing.

We do NOT support automatic resume from partial state. Per session
decision: phase A2 detects partial → reports it as a failure mode,
audit excludes the task from aggregates. Resume is deferred (resume
adds judgement complexity to the verifier-feedback loop that we don't
need yet).

Layout::

    {persist_dir}/{task_id}/
        turns.jsonl              ← append-only; one record per ReAct turn
                                   per feedback iteration
        iterations.jsonl         ← one record per feedback iteration with
                                   narrative + verdict summary
        final_state.json         ← written only on clean completion

Detection rules (find_partial_tasks):
  - ``turns.jsonl`` exists AND ``final_state.json`` missing → partial
  - both present → complete
  - directory empty → never started

The detection function never reads the JSONL contents — it only looks
at directory entries, so it is fast and tolerates partial-write
corruption inside turns.jsonl.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)


_TURNS_FILE = "turns.jsonl"
_ITERS_FILE = "iterations.jsonl"
_FINAL_FILE = "final_state.json"


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _to_jsonable(obj: Any) -> Any:
    """Best-effort coercion of dataclasses / pydantic models to plain dicts."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump(mode="json")
        except Exception:
            pass
    return obj


# ---------------------------------------------------------------------------
# TaskPersister — used by the runner inline
# ---------------------------------------------------------------------------


class TaskPersister:
    """Per-task disk writer.

    Lifecycle::

        p = TaskPersister(persist_dir, task_id)
        for turn_idx in range(max_turns):
            ...
            p.record_turn(
                iter_idx=0,
                turn_idx=turn_idx,
                assistant_message=msg,
                tool_calls_log=[...],
            )
        p.record_iteration(
            iter_idx=0,
            narrative=...,
            verdict_summary={...},
        )
        # ... feedback iter loop ...
        p.mark_complete(final_narrative=..., n_iterations=N)

    The persister never raises on disk failures — IO problems are
    logged but don't propagate, so a flaky disk doesn't kill an
    otherwise-good run. The trade-off is that an unobserved disk
    failure produces an incomplete record (which find_partial_tasks
    will then surface).
    """

    def __init__(self, persist_dir: Path | str, task_id: str) -> None:
        self.task_id = task_id
        self.task_dir = Path(persist_dir) / task_id
        self.task_dir.mkdir(parents=True, exist_ok=True)
        self.turns_path = self.task_dir / _TURNS_FILE
        self.iters_path = self.task_dir / _ITERS_FILE
        self.final_path = self.task_dir / _FINAL_FILE

    # ------------------------------------------------------------------ writes

    def record_turn(
        self,
        *,
        iter_idx: int,
        turn_idx: int,
        assistant_message: dict[str, Any] | None,
        tool_calls_log: Iterable[dict[str, Any]] = (),
    ) -> None:
        """Append one turn record to ``turns.jsonl``.

        ``iter_idx`` is the feedback-loop iteration (0 for initial
        ReAct, 1+ for feedback rounds). ``turn_idx`` is the ReAct turn
        within that iteration.
        """
        record = {
            "ts": _utc_now(),
            "iter_idx": iter_idx,
            "turn_idx": turn_idx,
            "assistant_message": _to_jsonable(assistant_message),
            "tool_calls_log": [_to_jsonable(t) for t in tool_calls_log],
        }
        self._append(self.turns_path, record)

    def record_iteration(
        self,
        *,
        iter_idx: int,
        narrative: str,
        verdict_summary: dict[str, Any] | None,
        n_tool_calls: int,
        n_turns: int,
        force_finalised: bool,
        feedback_prompt_used: bool,
    ) -> None:
        """Append one iteration summary to ``iterations.jsonl``.

        Recorded once per feedback round. ``iter_idx=0`` is the initial
        narrative + verdict; ``iter_idx>=1`` are post-feedback revisions.
        """
        record = {
            "ts": _utc_now(),
            "iter_idx": iter_idx,
            "narrative": narrative,
            "verdict_summary": _to_jsonable(verdict_summary),
            "n_tool_calls": n_tool_calls,
            "n_turns": n_turns,
            "force_finalised": force_finalised,
            "feedback_prompt_used": feedback_prompt_used,
        }
        self._append(self.iters_path, record)

    def mark_complete(
        self,
        *,
        final_narrative: str,
        n_iterations: int,
        n_total_tool_calls: int,
        elapsed_seconds: float,
        error: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Write the completion marker. ``final_state.json`` is the
        signal find_partial_tasks uses to distinguish complete from
        interrupted runs.
        """
        record: dict[str, Any] = {
            "ts": _utc_now(),
            "task_id": self.task_id,
            "final_narrative": final_narrative,
            "n_iterations": n_iterations,
            "n_total_tool_calls": n_total_tool_calls,
            "elapsed_seconds": elapsed_seconds,
            "error": error,
        }
        if extra:
            record["extra"] = _to_jsonable(extra)
        try:
            self.final_path.write_text(
                json.dumps(record, ensure_ascii=False, default=str, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:  # pragma: no cover — disk full / readonly
            logger.warning(
                "TaskPersister(%s): failed to write final_state.json: %s",
                self.task_id, exc,
            )

    # ------------------------------------------------------------------ status

    def is_complete(self) -> bool:
        return self.final_path.is_file()

    # ------------------------------------------------------------------ private

    @staticmethod
    def _append(path: Path, record: dict[str, Any]) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(
                    json.dumps(record, ensure_ascii=False, default=str) + "\n"
                )
        except OSError as exc:  # pragma: no cover — disk full / readonly
            logger.warning("TaskPersister: failed to append %s: %s", path, exc)


# ---------------------------------------------------------------------------
# Partial-task detection (audit hook)
# ---------------------------------------------------------------------------


def find_partial_tasks(persist_dir: Path | str) -> list[str]:
    """Scan ``persist_dir`` and return task_ids whose runs were interrupted.

    A task is *partial* iff its directory has a non-empty ``turns.jsonl``
    AND no ``final_state.json``. Dirs with neither file are treated as
    "never started" and excluded.

    Detection only inspects directory entries — it does not read JSONL
    contents, so it is fast even on large persist directories and
    tolerant of partial-line corruption inside ``turns.jsonl``.
    """
    base = Path(persist_dir)
    if not base.is_dir():
        return []
    out: list[str] = []
    for child in sorted(base.iterdir()):
        if not child.is_dir():
            continue
        turns = child / _TURNS_FILE
        final = child / _FINAL_FILE
        if not turns.is_file():
            continue
        if final.is_file():
            continue  # complete
        try:
            if turns.stat().st_size == 0:
                continue  # never wrote anything
        except OSError:
            continue
        out.append(child.name)
    return out


def find_complete_tasks(persist_dir: Path | str) -> list[str]:
    """Symmetric helper. Returns task_ids with a final_state.json marker."""
    base = Path(persist_dir)
    if not base.is_dir():
        return []
    out: list[str] = []
    for child in sorted(base.iterdir()):
        if child.is_dir() and (child / _FINAL_FILE).is_file():
            out.append(child.name)
    return out

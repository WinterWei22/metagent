"""Sub-6B (compound-only enrichment) runner.

For each task, render the differential metabolite list into the prompt
template, call the LLM, and emit a ``Sub6BResult`` dict to
``data/eval/sub6/sub6b_narratives.jsonl``. Idempotent — already-completed
``task_id``s are skipped.

The runner is intentionally framework-light: it does **not** load
ground-truth fields, and the LLM client is passed in by the caller so
tests can inject ``set_mock``.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from common import llm_client
from evaluation.sub6.io_utils import (
    append_jsonl,
    iter_jsonl,
    load_completed_task_ids,
)
from evaluation.sub6.prompts import build_messages

logger = logging.getLogger(__name__)


# A "chat function" is anything matching common.llm_client.chat's signature.
ChatFn = Callable[..., str]


@dataclass
class Sub6BResult:
    task_id: str
    narrative: str
    elapsed_seconds: float
    llm_model: str
    llm_calls: int
    metabolite_count: int
    error: str | None = None


def _strip_ground_truth(task: dict) -> dict:
    """Defensive copy used for prompt rendering — nothing leaks into the LLM."""
    return {
        "task_id": task["task_id"],
        "differential_metabolites": list(task.get("differential_metabolites") or []),
    }


def run_sub6b(
    task: dict,
    *,
    chat_fn: ChatFn | None = None,
    model: str = llm_client.DEFAULT_MODEL,
    temperature: float = 0.0,
    caller: str = "sub6b_baseline",
) -> Sub6BResult:
    """Process one Sub-6B task. Errors are captured into ``Result.error``."""
    safe = _strip_ground_truth(task)
    metabolites = safe["differential_metabolites"]
    messages = build_messages(metabolites)
    chat = chat_fn or llm_client.chat
    t0 = time.perf_counter()
    try:
        narrative = chat(
            messages,
            temperature=temperature,
            model=model,
            trace_id=task["task_id"],
            caller=caller,
        )
        err: str | None = None
    except Exception as exc:  # log the failure into the JSONL
        narrative = ""
        err = f"{type(exc).__name__}: {exc}"
        logger.warning("Sub-6B task %s failed: %s", task["task_id"], err)
    elapsed = time.perf_counter() - t0
    return Sub6BResult(
        task_id=task["task_id"],
        narrative=narrative,
        elapsed_seconds=elapsed,
        llm_model=model,
        llm_calls=1 if err is None else 0,
        metabolite_count=len(metabolites),
        error=err,
    )


def run_sub6b_batch(
    tasks_path: Path | str,
    output_path: Path | str,
    *,
    chat_fn: ChatFn | None = None,
    model: str = llm_client.DEFAULT_MODEL,
    temperature: float = 0.0,
    caller: str = "sub6b_baseline",
    limit: int | None = None,
) -> list[Sub6BResult]:
    """Iterate ``tasks_path`` (JSONL), append ``Sub6BResult`` rows to
    ``output_path``, skipping already-completed ``task_id``s.

    Returns the full set of results processed in *this* invocation (does
    not include resumed-from-disk records).
    """
    tasks_path = Path(tasks_path)
    output_path = Path(output_path)
    completed = load_completed_task_ids(output_path)
    logger.info(
        "Sub-6B runner: %d task_ids already in %s", len(completed), output_path
    )

    results: list[Sub6BResult] = []
    processed = 0
    with tasks_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            task = json.loads(line)
            tid = task["task_id"]
            if tid in completed:
                continue
            r = run_sub6b(
                task,
                chat_fn=chat_fn,
                model=model,
                temperature=temperature,
                caller=caller,
            )
            append_jsonl(output_path, asdict(r))
            results.append(r)
            processed += 1
            if limit is not None and processed >= limit:
                break
    logger.info("Sub-6B runner: processed %d tasks this run", processed)
    return results


def load_sub6b_results(output_path: Path | str) -> list[dict]:
    """Read all narratives from a previous run."""
    return list(iter_jsonl(output_path))

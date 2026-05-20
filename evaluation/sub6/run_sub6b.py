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

import argparse
import json
import logging
import os
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


NARRATIVE_LLM_ROUTES: dict[str, dict[str, str | None]] = {
    "minimax": {"provider": "minimax", "model": "MiniMax-M2.7"},
    "gpt55": {"provider": "openai", "model": "gpt-5.5"},
    "opus47": {"provider": "openai", "model": "claude-opus-4-7"},
}


def resolve_narrative_llm(name: str) -> tuple[str, str]:
    route = NARRATIVE_LLM_ROUTES[name]
    return str(route["provider"]), str(route["model"])


def _chat_kwargs(provider: str | None) -> dict[str, str]:
    return {"provider": provider} if provider else {}


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
    provider: str | None = None,
    temperature: float = 0.0,
    caller: str = "sub6b_baseline",
    llm_retries: int = 0,
) -> Sub6BResult:
    """Process one Sub-6B task. Errors are captured into ``Result.error``."""
    safe = _strip_ground_truth(task)
    metabolites = safe["differential_metabolites"]
    messages = build_messages(metabolites)
    chat = chat_fn or llm_client.chat
    t0 = time.perf_counter()
    err: str | None = None
    narrative = ""
    for attempt in range(llm_retries + 1):
        try:
            narrative = chat(
                messages,
                temperature=temperature,
                model=model,
                trace_id=task["task_id"],
                caller=caller,
                response_format={"type": "json_object"},
                **_chat_kwargs(provider),
            )
            err = None
            break
        except Exception as exc:  # log the failure into the JSONL
            err = f"{type(exc).__name__}: {exc}"
            logger.warning("Sub-6B task %s failed: %s", task["task_id"], err)
            if attempt < llm_retries:
                time.sleep(1.0)
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
    provider: str | None = None,
    temperature: float = 0.0,
    caller: str = "sub6b_baseline",
    limit: int | None = None,
    llm_retries: int = 0,
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
                provider=provider,
                temperature=temperature,
                caller=caller,
                llm_retries=llm_retries,
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


def _resolve_api_key(provider: str, model: str) -> None:
    if provider == "openai":
        os.environ.setdefault("METAGENT_OPENAI_BASE_URL", "https://api.viviai.cc/v1")
        if os.environ.get("METAGENT_OPENAI_API_KEY"):
            return
        key_files = (
            ("api_key_claude.txt", "api_key_gpt.txt")
            if model.startswith("claude-")
            else ("api_key_gpt.txt", "api_key_claude.txt")
        )
        for name in key_files:
            candidate = Path.cwd() / name
            if candidate.is_file():
                os.environ["METAGENT_OPENAI_API_KEY"] = candidate.read_text().strip()
                return
        return
    if os.environ.get("MINIMAX_API_KEY"):
        return
    for name in ("api_key_minimax.txt", "api_key.txt"):
        candidate = Path.cwd() / name
        if candidate.is_file():
            os.environ["MINIMAX_API_KEY"] = candidate.read_text().strip()
            return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tasks", help="Sub-6B JSONL tasks file")
    parser.add_argument("output", help="Output JSONL file")
    parser.add_argument(
        "--narrative-llm",
        choices=tuple(NARRATIVE_LLM_ROUTES),
        default="minimax",
        help="LLM used to generate narratives",
    )
    parser.add_argument("--llm-model", default=None, help="Legacy explicit model override")
    parser.add_argument("--limit", "--max-tasks", type=int, default=None)
    parser.add_argument("--no-llm-key-check", action="store_true")
    args = parser.parse_args(argv)

    provider, model = resolve_narrative_llm(args.narrative_llm)
    if args.llm_model:
        model = args.llm_model
    if not args.no_llm_key_check:
        _resolve_api_key(provider, model)
    results = run_sub6b_batch(
        args.tasks,
        args.output,
        model=model,
        provider=provider,
        limit=args.limit,
        llm_retries=1,
    )
    ok = sum(1 for r in results if r.error is None)
    print(f"Sub-6B: processed {len(results)} tasks, ok={ok}, fail={len(results)-ok}")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

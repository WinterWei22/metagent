"""Sub-6B ReAct-agent runner (phase A1, track AGENT).

Runs the same Sub-6B tasks as :mod:`evaluation.sub6.run_sub6b` but with
function-calling: at each turn the LLM may either (a) emit ``tool_calls``
which we route through :func:`tools.agent_tools.dispatch` and append back
into the conversation as ``role=tool`` messages, or (b) produce the final
narrative text. The loop runs up to ``max_turns`` (default 5) and is
hard-bounded by ``total_timeout`` seconds — beyond that we force a final
no-tools call so the task always produces *some* narrative for downstream
verifier evaluation.

The single-call path (:mod:`evaluation.sub6.run_sub6b`) is unchanged. This
module imports the metabolite-block renderer + ``_strip_ground_truth`` /
``_resolve_api_key`` from there.
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from common import llm_client
from evaluation.sub6.io_utils import append_jsonl, load_completed_task_ids
from evaluation.sub6.prompts_agent import build_react_messages
from evaluation.sub6.run_sub6b import (
    NARRATIVE_LLM_ROUTES,
    _resolve_api_key,
    _strip_ground_truth,
    resolve_narrative_llm,
)
from tools.agent_tools import (
    TOOL_DEFINITIONS_OPENAI,
    dispatch,
    reset_call_cache,
)

logger = logging.getLogger(__name__)


ChatWithToolsFn = Callable[..., dict]
ChatFn = Callable[..., str]


# ---------------------------------------------------------------------------
# Result dataclass — extends Sub6BResult fields with ReAct-specific telemetry
# ---------------------------------------------------------------------------


@dataclass
class Sub6BAgentResult:
    """One Sub-6B task run via the ReAct agent.

    Field overlap with ``Sub6BResult`` is intentional — both serialise via
    ``asdict`` into the per-run JSONL and a downstream verifier can consume
    either shape by reading ``narrative`` + ``task_id``.
    """

    task_id: str
    narrative: str
    elapsed_seconds: float
    llm_model: str
    metabolite_count: int
    n_turns: int  # ReAct turns actually executed (≤ max_turns)
    n_tool_calls: int  # total tool invocations across the run
    force_finalised: bool = False  # True if narrative came from finalise pass, not natural termination
    tool_calls_log: list[dict] = field(default_factory=list)
    error: str | None = None


# ---------------------------------------------------------------------------
# Defaults — see spec § Pitfalls 4 & 6
# ---------------------------------------------------------------------------

DEFAULT_MAX_TURNS = 5
DEFAULT_TOTAL_TIMEOUT = 120.0  # seconds


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _argument_str(tool_call: dict) -> str:
    """Best-effort extraction of the raw ``arguments`` field for logging.

    OpenAI returns it as a JSON string; our dispatcher accepts that or a
    parsed object. We normalise to a string for the audit log.
    """
    fn = tool_call.get("function")
    if isinstance(fn, dict) and "arguments" in fn:
        args = fn["arguments"]
    else:
        args = tool_call.get("arguments")
    if isinstance(args, str):
        return args
    try:
        return json.dumps(args, ensure_ascii=False, default=str)
    except Exception:
        return str(args)


def _echo_assistant(msg: dict) -> dict:
    """Build the assistant-role message to append to history.

    OpenAI semantics: when ``tool_calls`` is present, ``content`` may be
    ``null`` or a string; when no tool_calls, ``content`` is the narrative.
    """
    out: dict[str, Any] = {"role": "assistant"}
    if msg.get("tool_calls"):
        out["content"] = msg.get("content")  # may be None
        out["tool_calls"] = msg["tool_calls"]
    else:
        out["content"] = msg.get("content") or ""
    return out


def _tool_result_message(envelope: dict, fallback_call_id: str) -> dict:
    """Convert a dispatcher envelope into a ``role=tool`` message."""
    return {
        "role": "tool",
        "tool_call_id": envelope.get("tool_call_id") or fallback_call_id,
        "name": envelope["name"],
        "content": json.dumps(
            envelope["result"], ensure_ascii=False, default=str
        ),
    }


# ---------------------------------------------------------------------------
# Core ReAct runner
# ---------------------------------------------------------------------------


def run_sub6b_react(
    task: dict,
    *,
    chat_with_tools_fn: ChatWithToolsFn | None = None,
    finalise_chat_fn: ChatWithToolsFn | None = None,
    model: str = "claude-opus-4-7",
    provider: str = "openai",
    temperature: float = 0.0,
    max_turns: int = DEFAULT_MAX_TURNS,
    total_timeout: float = DEFAULT_TOTAL_TIMEOUT,
    caller: str = "sub6b_agent_a1",
) -> Sub6BAgentResult:
    """Run one Sub-6B task with a ReAct loop.

    The loop terminates on the first of:
      - LLM produces an assistant message with no tool_calls → that
        message's ``content`` is the narrative.
      - ``max_turns`` reached → forced final no-tools call.
      - ``total_timeout`` exceeded between turns → forced final no-tools call.
      - A network/LLM exception → recorded into ``error``, narrative may
        be empty.

    Tool calls are routed through ``tools.agent_tools.dispatch``, which
    handles validation errors and per-call deduplication internally; this
    runner only assembles the message history and aggregates telemetry.

    The dispatcher cache is reset at the start of each task — within one
    task we want dedup, but across tasks the same query is legitimate.
    """
    safe = _strip_ground_truth(task)
    metabolites = safe["differential_metabolites"]
    task_id = safe["task_id"]

    chat_with_tools_fn = chat_with_tools_fn or llm_client.chat_with_tools
    finalise_chat_fn = finalise_chat_fn or llm_client.chat_with_tools

    messages = build_react_messages(metabolites)
    tool_calls_log: list[dict] = []
    n_turns = 0
    n_tool_calls = 0
    narrative = ""
    err: str | None = None
    timed_out = False

    reset_call_cache()
    t0 = time.perf_counter()

    # ---- Main ReAct loop ----
    # Guarantee at least one turn so a degenerate ``total_timeout=0`` still
    # exercises the LLM once (and so the finalise pass has *some* history).
    for turn_idx in range(max_turns):
        if turn_idx > 0 and (time.perf_counter() - t0) > total_timeout:
            timed_out = True
            break
        n_turns = turn_idx + 1

        try:
            msg = chat_with_tools_fn(
                messages,
                tools=TOOL_DEFINITIONS_OPENAI,
                tool_choice="auto",
                temperature=temperature,
                model=model,
                provider=provider,
                trace_id=task_id,
                caller=f"{caller}_turn{n_turns}",
            )
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            logger.warning("ReAct turn %d failed for %s: %s", n_turns, task_id, err)
            break

        messages.append(_echo_assistant(msg))

        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            narrative = (msg.get("content") or "").strip()
            break

        for tc in tool_calls:
            n_tool_calls += 1
            envelope = dispatch(tc)
            tool_calls_log.append(
                {
                    "turn": n_turns,
                    "name": envelope["name"],
                    "tool_call_id": envelope.get("tool_call_id"),
                    "arguments": _argument_str(tc),
                    "result": envelope["result"],
                    "cached": envelope["cached"],
                }
            )
            messages.append(
                _tool_result_message(
                    envelope, fallback_call_id=f"call_local_{n_tool_calls}"
                )
            )

    # ---- Fallback / finalise pass ----
    # We force a final narrative whenever the loop ended without one and the
    # error (if any) was not a hard LLM/network failure. This guarantees
    # downstream verifier sees *some* narrative per task.
    needs_finalise = (
        err is None
        and not narrative
        and (n_turns > 0 or timed_out)
    )
    force_finalised = False
    if needs_finalise:
        force_finalised = True
        nudge = (
            "Time to summarise. Based on the tool outputs above, write the "
            "final 200-400 word narrative now. Do NOT call any more tools — "
            "tool_choice is set to 'none' for this turn."
        )
        messages.append({"role": "user", "content": nudge})
        try:
            final_msg = finalise_chat_fn(
                messages,
                tools=TOOL_DEFINITIONS_OPENAI,
                tool_choice="none",
                temperature=temperature,
                model=model,
                provider=provider,
                trace_id=task_id,
                caller=f"{caller}_finalise",
                response_format={"type": "json_object"},
            )
            narrative = (final_msg.get("content") or "").strip()
            if timed_out:
                err = "timeout_fallback_used"
            elif not narrative:
                err = "empty_narrative_after_finalise"
        except Exception as exc:
            err = f"finalise_failed: {type(exc).__name__}: {exc}"
            logger.warning("ReAct finalise failed for %s: %s", task_id, err)

    elapsed = time.perf_counter() - t0
    return Sub6BAgentResult(
        task_id=task_id,
        narrative=narrative,
        elapsed_seconds=elapsed,
        llm_model=model,
        metabolite_count=len(metabolites),
        n_turns=n_turns,
        n_tool_calls=n_tool_calls,
        force_finalised=force_finalised,
        tool_calls_log=tool_calls_log,
        error=err,
    )


# ---------------------------------------------------------------------------
# Batch driver
# ---------------------------------------------------------------------------


def run_sub6b_react_batch(
    tasks_path: Path | str,
    output_path: Path | str,
    *,
    chat_with_tools_fn: ChatWithToolsFn | None = None,
    finalise_chat_fn: ChatWithToolsFn | None = None,
    model: str = "claude-opus-4-7",
    provider: str = "openai",
    temperature: float = 0.0,
    max_turns: int = DEFAULT_MAX_TURNS,
    total_timeout: float = DEFAULT_TOTAL_TIMEOUT,
    caller: str = "sub6b_agent_a1",
    limit: int | None = None,
) -> list[Sub6BAgentResult]:
    """Iterate ``tasks_path`` (JSONL), append result rows to ``output_path``,
    skipping ``task_id``s already present.
    """
    tasks_path = Path(tasks_path)
    output_path = Path(output_path)
    completed = load_completed_task_ids(output_path)
    logger.info(
        "Sub-6B ReAct runner: %d task_ids already in %s",
        len(completed),
        output_path,
    )

    results: list[Sub6BAgentResult] = []
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
            r = run_sub6b_react(
                task,
                chat_with_tools_fn=chat_with_tools_fn,
                finalise_chat_fn=finalise_chat_fn,
                model=model,
                provider=provider,
                temperature=temperature,
                max_turns=max_turns,
                total_timeout=total_timeout,
                caller=caller,
            )
            append_jsonl(output_path, asdict(r))
            results.append(r)
            processed += 1
            if limit is not None and processed >= limit:
                break
    logger.info("Sub-6B ReAct runner: processed %d tasks this run", processed)
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sub-6B ReAct agent runner")
    parser.add_argument("tasks", help="Sub-6B JSONL tasks file")
    parser.add_argument("output", help="Output JSONL file")
    parser.add_argument(
        "--narrative-llm",
        choices=tuple(NARRATIVE_LLM_ROUTES),
        default="opus47",
        help="LLM route (phase A1 only validated for opus47)",
    )
    parser.add_argument("--llm-model", default=None)
    parser.add_argument("--limit", "--max-tasks", type=int, default=None)
    parser.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS)
    parser.add_argument("--total-timeout", type=float, default=DEFAULT_TOTAL_TIMEOUT)
    parser.add_argument("--no-llm-key-check", action="store_true")
    args = parser.parse_args(argv)

    provider, model = resolve_narrative_llm(args.narrative_llm)
    if args.llm_model:
        model = args.llm_model
    if not args.no_llm_key_check:
        _resolve_api_key(provider, model)

    if provider != "openai":
        # Phase A1 limitation: tool calling only validated against the
        # OpenAI-compat (viviai) path. MiniMax tool protocol differs.
        raise SystemExit(
            f"--narrative-llm={args.narrative_llm} routes to provider "
            f"{provider!r}; phase A1 ReAct runner only supports the "
            f"openai-compat provider. Use --narrative-llm=opus47."
        )

    results = run_sub6b_react_batch(
        args.tasks,
        args.output,
        model=model,
        provider=provider,
        max_turns=args.max_turns,
        total_timeout=args.total_timeout,
        limit=args.limit,
    )
    ok = sum(1 for r in results if r.error is None)
    print(
        f"Sub-6B ReAct: processed {len(results)} tasks, "
        f"ok={ok}, fail={len(results) - ok}, "
        f"avg_tool_calls={sum(r.n_tool_calls for r in results) / max(len(results), 1):.2f}"
    )
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

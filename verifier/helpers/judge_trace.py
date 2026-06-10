from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def default_judge_trace_path() -> Path:
    explicit = os.environ.get("METAGENT_JUDGE_TRACE_PATH")
    if explicit:
        return Path(explicit)
    llm_log = Path(os.environ.get("METAGENT_LLM_LOG_PATH") or "logs/concord/w18_path_x_post_llm_judge.jsonl")
    return llm_log.with_name(f"{llm_log.stem}_judge_trace.jsonl")


def write_judge_trace(
    *,
    task_id: str | None,
    iteration: int | None,
    claim_id: str | None,
    claim_type: Any,
    verdict: str,
    parser_success: bool,
    cost_usd: float,
    confidence: float | None,
    path: str | Path | None = None,
) -> None:
    out_path = Path(path) if path is not None else default_judge_trace_path()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "task_id": task_id,
        "iteration": iteration,
        "claim_id": claim_id,
        "claim_type": _value_of(claim_type),
        "verdict": verdict,
        "parser_success": bool(parser_success),
        "cost_usd": float(cost_usd),
        "confidence": confidence,
    }
    with out_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _value_of(value: Any) -> str:
    return str(getattr(value, "value", value))

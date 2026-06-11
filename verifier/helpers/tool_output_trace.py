from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def write_tool_output_trace(
    *,
    path: str | Path,
    task_id: str | None,
    iteration: int | None,
    claim_id: str | None,
    claim_type: str,
    method: str | None,
    status: str,
    verdict: str,
    source_field: str | None,
) -> None:
    row = {
        "task_id": task_id,
        "iteration": iteration,
        "claim_id": claim_id,
        "claim_type": claim_type,
        "method": method,
        "status": status,
        "verdict": verdict,
        "source_field": source_field,
        "cost_usd": 0.0,
    }
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


@dataclass
class ToolOutputRequestTracker:
    max_requests_per_run: int = 1000
    requests: int = 0
    run_id: str | None = None

    def can_call(self) -> bool:
        return self.requests < self.max_requests_per_run

    def record(self) -> None:
        self.requests += 1

    def reset_for_run(self, run_id: str | None = None) -> None:
        self.requests = 0
        self.run_id = run_id

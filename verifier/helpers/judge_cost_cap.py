from __future__ import annotations

from dataclasses import dataclass


@dataclass
class JudgeCostTracker:
    cap_usd: float = 2.0
    spent_usd: float = 0.0
    run_id: str | None = None

    def can_call(self, estimated_increment_usd: float = 0.0) -> bool:
        return self.spent_usd < self.cap_usd and self.spent_usd + estimated_increment_usd <= self.cap_usd

    def record(self, cost_usd: float) -> None:
        self.spent_usd += cost_usd

    def reset_for_run(self, run_id: str | None = None) -> None:
        self.spent_usd = 0.0
        self.run_id = run_id


_RUN_LEVEL_TRACKER = JudgeCostTracker()


def get_run_level_tracker() -> JudgeCostTracker:
    return _RUN_LEVEL_TRACKER


def reset_run_level_tracker(
    *,
    run_id: str | None = None,
    cap_usd: float | None = None,
) -> JudgeCostTracker:
    if cap_usd is not None:
        _RUN_LEVEL_TRACKER.cap_usd = cap_usd
    _RUN_LEVEL_TRACKER.reset_for_run(run_id=run_id)
    return _RUN_LEVEL_TRACKER

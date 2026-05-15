"""LC-MS peak record schema (W4 D1).

PeakRecord is the input unit for mummichog: a single (m/z, p-value, t-score)
triple from differential LC-MS analysis. retention_time and feature_id are
optional metadata for traceability.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PeakRecord:
    mz: float                          # mass / charge ratio
    p_value: float                     # differential p-value (0..1)
    t_score: float | None = None       # t-statistic (optional)
    retention_time: float | None = None
    feature_id: str | None = None

    def __post_init__(self) -> None:
        if not (self.mz > 0):
            raise ValueError(f"PeakRecord.mz must be positive, got {self.mz!r}")
        if not (0.0 <= self.p_value <= 1.0):
            raise ValueError(
                f"PeakRecord.p_value must be in [0,1], got {self.p_value!r}"
            )

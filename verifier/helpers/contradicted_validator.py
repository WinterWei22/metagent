from __future__ import annotations

import re
from typing import Any


_TOKEN_RE = re.compile(r"([^.[\]]+)|\[(\d+)\]")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?(?:e[-+]?\d+)?", re.IGNORECASE)


def validate_contradicted_pointer(source_report: Any, evidence_pointer: str, rationale: str) -> bool:
    if not evidence_pointer or _resolve_pointer(source_report, evidence_pointer) is None:
        return False
    numbers = _NUMBER_RE.findall(rationale or "")
    return "claim" in rationale.lower() and "carrier" in rationale.lower() and len(numbers) >= 2


def _resolve_pointer(source_report: Any, pointer: str) -> Any:
    value = source_report
    for key, index in _TOKEN_RE.findall(pointer):
        if key:
            if isinstance(value, dict):
                value = value.get(key)
            else:
                value = getattr(value, key, None)
        else:
            if not isinstance(value, list):
                return None
            idx = int(index)
            if idx >= len(value):
                return None
            value = value[idx]
        if value is None:
            return None
    return value

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from verifier.schemas import ClaimVerdict


@dataclass(frozen=True)
class ParsedJudgeResponse:
    verdict: ClaimVerdict
    confidence: float
    evidence_pointer: str
    rationale: str


_VERDICT_MAP = {
    "SUPPORTED": ClaimVerdict.SUPPORTED,
    "CONTRADICTED": ClaimVerdict.CONTRADICTED,
    "UNVERIFIABLE_V0": ClaimVerdict.UNVERIFIABLE_V0,
    "UV": ClaimVerdict.UNVERIFIABLE_V0,
    "HEDGED": ClaimVerdict.NEEDS_HUMAN_REVIEW,
}


def parse_judge_response(response: str | dict[str, Any]) -> ParsedJudgeResponse:
    try:
        data = json.loads(response) if isinstance(response, str) else response
    except (TypeError, json.JSONDecodeError):
        return _uv("parse failure")
    if not isinstance(data, dict):
        return _uv("non-object response")
    raw_verdict = str(data.get("verdict") or "").upper()
    confidence = data.get("confidence")
    evidence_pointer = data.get("evidence_pointer")
    rationale = str(data.get("rationale") or "")
    if raw_verdict not in _VERDICT_MAP or confidence is None or evidence_pointer is None:
        return _uv("missing required fields")
    try:
        confidence_float = float(confidence)
    except (TypeError, ValueError):
        return _uv("invalid confidence")
    return ParsedJudgeResponse(
        verdict=_VERDICT_MAP[raw_verdict],
        confidence=max(0.0, min(1.0, confidence_float)),
        evidence_pointer=str(evidence_pointer),
        rationale=rationale,
    )


def confidence_bucket(confidence: float) -> str:
    if confidence >= 0.90:
        return "contradicted_strong"
    if confidence >= 0.85:
        return "strong"
    if confidence >= 0.50:
        return "hedged"
    return "uv"


def _uv(rationale: str) -> ParsedJudgeResponse:
    return ParsedJudgeResponse(
        verdict=ClaimVerdict.UNVERIFIABLE_V0,
        confidence=0.0,
        evidence_pointer="",
        rationale=rationale,
    )

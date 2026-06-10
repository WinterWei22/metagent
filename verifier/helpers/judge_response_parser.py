from __future__ import annotations

import json
import re
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
    data = _coerce_response_object(response)
    if data is None:
        return _uv("parse failure")
    return _parse_response_object(data)


def _coerce_response_object(response: str | dict[str, Any]) -> dict[str, Any] | None:
    if isinstance(response, dict):
        return response
    if not isinstance(response, str):
        return None
    cleaned = _strip_think_blocks(response)
    for candidate in _json_candidates(cleaned):
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None


def _strip_think_blocks(text: str) -> str:
    without_closed = re.sub(
        r"<think\b[^>]*>.*?</think>",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    return without_closed.strip()


def _json_candidates(text: str) -> list[str]:
    candidates = [text.strip()]
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        candidates.append(fenced.group(1).strip())
    first_object = _extract_first_json_object(text)
    if first_object is not None:
        candidates.append(first_object)
    return [candidate for candidate in candidates if candidate]


def _extract_first_json_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(text)):
        char = text[idx]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:idx + 1]
    return None


def _parse_response_object(data: dict[str, Any]) -> ParsedJudgeResponse:
    try:
        raw_verdict = str(data.get("verdict") or "").upper()
        confidence = data.get("confidence")
        evidence_pointer = data.get("evidence_pointer")
        rationale = str(data.get("rationale") or "")
        if raw_verdict not in _VERDICT_MAP or confidence is None or evidence_pointer is None:
            return _uv("missing required fields")
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

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from verifier.helpers.tool_output_claim_parser import ParsedToolOutputClaim, parse_tool_output_claim


@dataclass(frozen=True)
class ToolOutputEvidence:
    status: str
    method: str | None = None
    metric: str | None = None
    claimed: Any = None
    observed: Any = None
    source_field: str | None = None


def lookup_tool_output_evidence(claim_text: str, source_report: Any) -> ToolOutputEvidence:
    parsed = parse_tool_output_claim(claim_text)
    if parsed is None:
        return ToolOutputEvidence(status="unparsed")
    rows, base = _carrier_rows(parsed.method, source_report)
    if not rows:
        return ToolOutputEvidence(status="absent", method=parsed.method, metric=parsed.metric, claimed=parsed.value)
    row_idx, row = _find_row(parsed, rows)
    if row is None:
        return ToolOutputEvidence(status="absent", method=parsed.method, metric=parsed.metric, claimed=parsed.value)
    observed, suffix = _observed_value(parsed, row)
    if observed is None:
        return ToolOutputEvidence(status="absent", method=parsed.method, metric=parsed.metric, claimed=parsed.value)
    status = "match" if _values_match(parsed.value, observed) else "mismatch"
    return ToolOutputEvidence(
        status=status,
        method=parsed.method,
        metric=parsed.metric,
        claimed=parsed.value,
        observed=observed,
        source_field=f"{base}[{row_idx}].{suffix}",
    )


def _carrier_rows(method: str, source_report: Any) -> tuple[list[dict[str, Any]], str]:
    if method == "ramp":
        carrier = _get(source_report, "ramp_enrichment_result") or {}
        return list(carrier.get("top_pathways") or carrier.get("pathways") or []), "ramp_enrichment_result.top_pathways"
    if method == "mummichog":
        carrier = _get(source_report, "mummichog_enrichment_result") or {}
        return list(carrier.get("pathways") or carrier.get("top_pathways") or []), "mummichog_enrichment_result.pathways"
    if method == "metaboanalystr":
        carrier = (_get(source_report, "metaboanalystr_enrichment_result") or {}).get("psea") or {}
        return list(carrier.get("pathways") or carrier.get("top_pathways") or []), "metaboanalystr_enrichment_result.psea.pathways"
    return [], method


def _find_row(parsed: ParsedToolOutputClaim, rows: list[dict[str, Any]]) -> tuple[int, dict[str, Any] | None]:
    if parsed.pathway_hint:
        hint = _norm(parsed.pathway_hint.replace("MUMM:", ""))
        for idx, row in enumerate(rows):
            values = [row.get("pathway_id"), row.get("pathway_name"), row.get("pathway_id_native")]
            if any(hint and hint in _norm(str(value or "")) for value in values):
                return idx, row
        return -1, None
    return 0, rows[0] if rows else None


def _observed_value(parsed: ParsedToolOutputClaim, row: dict[str, Any]) -> tuple[Any, str | None]:
    if parsed.metric == "rank":
        return row.get("rank"), "rank"
    if parsed.metric == "fdr":
        return row.get("fdr"), "fdr"
    if parsed.metric == "fold_enrichment":
        return row.get("fold_enrichment"), "fold_enrichment"
    if parsed.metric == "p_value":
        if row.get("p_value") is not None:
            return row.get("p_value"), "p_value"
        if row.get("score_type") == "p_value":
            return row.get("score"), "score"
    if parsed.metric == "overlap":
        aux = row.get("auxiliary_scores") or {}
        observed = (int(aux.get("overlap_size", -1)), int(aux.get("pathway_size", -1)))
        return observed, "auxiliary_scores.overlap_size"
    return None, None


def _values_match(claimed: Any, observed: Any) -> bool:
    if isinstance(claimed, tuple):
        return tuple(claimed) == tuple(observed)
    try:
        c = float(claimed)
        o = float(observed)
    except (TypeError, ValueError):
        return claimed == observed
    return abs(c - o) <= max(1e-12, abs(o) * 1e-6)


def _get(obj: Any, name: str) -> Any:
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def _norm(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())

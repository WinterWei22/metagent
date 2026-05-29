"""Lookup extracted signal mentions against Sub-6 enrichment output."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from schemas.sub6_report import SubsixSourceReport
from verifier.helpers.signal_extractor import SignalMention


@dataclass(frozen=True)
class LookupResult:
    matched: bool
    metric: str
    actual_value: float
    pathway_name: str
    pathway_id: str | None = None
    actual_total: float | None = None
    match_type: str = "exact_match"
    pathway_rank: int | None = None


def lookup_signal_evidence(
    mention: SignalMention,
    source_report: SubsixSourceReport,
) -> LookupResult | None:
    """Match one signal mention to ``ramp_enrichment_result.top_pathways``."""
    pathways = (source_report.ramp_enrichment_result or {}).get("top_pathways") or []
    row_rank = _find_row(mention, pathways)
    if row_rank is None:
        return None

    row, rank = row_rank
    actual = _metric_value(mention.metric, row, rank)
    if actual is None:
        return None
    actual_total = _metric_total(mention.metric, row)
    matched = _values_match(mention, actual, actual_total)
    match_type = "exact_match" if matched else "miss"
    if matched and not _is_exact(mention.value, actual):
        match_type = "tolerance_match"
    return LookupResult(
        matched=matched,
        metric=mention.metric,
        actual_value=float(actual),
        actual_total=float(actual_total) if actual_total is not None else None,
        pathway_name=str(row.get("pathway_name") or ""),
        pathway_id=row.get("pathway_id"),
        pathway_rank=rank,
        match_type=match_type,
    )


def _find_row(mention: SignalMention, pathways: list[dict[str, Any]]) -> tuple[dict[str, Any], int] | None:
    if not pathways:
        return None
    hint = _norm(mention.pathway_hint or "")
    if hint:
        for idx, row in enumerate(pathways, start=1):
            if _row_matches_hint(row, hint):
                return row, idx
        return None
    if len(pathways) == 1:
        return pathways[0], 1
    return None


def _row_matches_hint(row: dict[str, Any], hint: str) -> bool:
    values = [
        row.get("pathway_name"),
        row.get("pathway_id"),
        row.get("pathway_external_id"),
    ]
    for value in values:
        norm = _norm(str(value or ""))
        if norm and (hint == norm or hint in norm or norm in hint):
            return True
    return False


def _metric_value(metric: str, row: dict[str, Any], rank: int) -> float | None:
    if metric == "rank":
        return float(rank)
    if metric == "rank_cutoff":
        return float(rank)
    if metric == "overlap_count":
        return float(len(row.get("matched_compounds") or []))
    if metric == "total_compounds":
        value = row.get("total_pathway_compounds")
        return float(value) if value is not None else None
    key = {
        "p_value": "p_value",
        "fdr": "fdr",
        "fold_enrichment": "fold_enrichment",
        "score": "score",
        "nes": "nes",
        "impact": "impact",
    }.get(metric)
    if key is None:
        return None
    value = row.get(key)
    return float(value) if value is not None else None


def _metric_total(metric: str, row: dict[str, Any]) -> float | None:
    if metric != "overlap_count":
        return None
    value = row.get("total_pathway_compounds")
    return float(value) if value is not None else None


def _values_match(mention: SignalMention, actual: float, actual_total: float | None) -> bool:
    if mention.operator == "lt":
        return actual < mention.value or _is_exact(actual, mention.value)
    if mention.operator == "gt":
        return actual > mention.value or _is_exact(actual, mention.value)
    if not (_is_exact(mention.value, actual) or _within_tolerance(mention.value, actual)):
        return False
    if mention.total is not None:
        return actual_total is not None and (_is_exact(mention.total, actual_total) or _within_tolerance(mention.total, actual_total))
    return True


def _is_exact(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-12 * max(1.0, abs(a), abs(b))


def _within_tolerance(a: float, b: float) -> bool:
    denom = max(abs(a), abs(b), 1e-12)
    return abs(a - b) / denom <= 0.10


def _norm(value: str) -> str:
    return " ".join(value.lower().replace("_", " ").replace("-", " ").split())

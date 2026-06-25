"""Multisource enrichment pool helper — Task 3 (D1.1).

Merges rows from all 5 enrichment carriers on a SubsixSourceReport into one flat
pool, and matches a claimed pathway against that pool using ID equivalence and
semantic name matching.

Reuse:
- ID equivalence: ``verifier.helpers.pathway_namespace.pathway_ids_equivalent``
  (same logic as ``method_aware_enrichment._find_row``)
- Name matching: ``concord.lookup.pathway_name_matcher.PathwayNameMatcher``
  (SapBERT + token-overlap fallback; singleton to avoid repeated model loads)
"""
from __future__ import annotations

import re
from typing import Any

from schemas.sub6_report import SubsixSourceReport
from verifier.helpers.pathway_namespace import pathway_ids_equivalent

# Module-level singleton — instantiated once; safe because PathwayNameMatcher
# handles missing SapBERT gracefully via fallback_to_token_overlap=True.
_name_matcher: "PathwayNameMatcher | None" = None  # noqa: F821


def _get_name_matcher():
    global _name_matcher
    if _name_matcher is None:
        from concord.lookup.pathway_name_matcher import PathwayNameMatcher
        _name_matcher = PathwayNameMatcher()
    return _name_matcher


# ---------------------------------------------------------------------------
# Carrier extraction — mirrors method_aware_enrichment._carrier_rows structure
# ---------------------------------------------------------------------------

_CARRIER_SPECS: list[tuple[str, Any]] = [
    # (paradigm_label, extractor_fn)
]


def _extract_ramp(source_report: SubsixSourceReport) -> list[dict[str, Any]]:
    carrier = source_report.ramp_enrichment_result or {}
    return list(carrier.get("top_pathways") or [])


def _extract_mummichog(source_report: SubsixSourceReport) -> list[dict[str, Any]]:
    carrier = source_report.mummichog_enrichment_result or {}
    return list(carrier.get("pathways") or carrier.get("top_pathways") or [])


def _extract_metaboanalystr(source_report: SubsixSourceReport) -> list[dict[str, Any]]:
    carrier = (source_report.metaboanalystr_enrichment_result or {}).get("psea") or {}
    return list(carrier.get("pathways") or carrier.get("top_pathways") or [])


def _extract_sspa(source_report: SubsixSourceReport) -> list[dict[str, Any]]:
    carrier = source_report.sspa_enrichment_result or {}
    return list(carrier.get("pathways") or carrier.get("top_pathways") or [])


def _extract_fella(source_report: SubsixSourceReport) -> list[dict[str, Any]]:
    carrier = source_report.fella_enrichment_result or {}
    rwr = carrier.get("rwr") or {}
    return list(rwr.get("pathways") or rwr.get("top_pathways") or [])


_PARADIGM_EXTRACTORS = [
    ("ramp", _extract_ramp),
    ("mummichog", _extract_mummichog),
    ("metaboanalystr", _extract_metaboanalystr),
    ("sspa", _extract_sspa),
    ("fella", _extract_fella),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_pathway_pool(source_report: SubsixSourceReport) -> list[dict[str, Any]]:
    """Merge all 5 enrichment carriers into one flat pool.

    Each row is a copy of the original row dict, annotated with ``_paradigm``
    (one of "ramp", "mummichog", "metaboanalystr", "sspa", "fella").
    """
    pool: list[dict[str, Any]] = []
    for paradigm, extractor in _PARADIGM_EXTRACTORS:
        for row in extractor(source_report):
            annotated = dict(row)
            annotated["_paradigm"] = paradigm
            pool.append(annotated)
    return pool


def match_in_pool(
    pool: list[dict[str, Any]],
    pathway_id: str | None,
    pathway_name: str | None,
) -> dict[str, Any] | None:
    """Return the first row matching the claimed pathway, or None.

    Match priority:
    1. ID equivalence via ``pathway_ids_equivalent`` (checks pathway_id,
       pathway_id_native, pathway_external_id fields).
    2. Exact normalised name match.
    3. Semantic name match via ``PathwayNameMatcher`` (SapBERT + token overlap).
    """
    matcher = _get_name_matcher()

    for row in pool:
        # --- ID match ---
        if pathway_id:
            ids = [
                row.get("pathway_id"),
                row.get("pathway_id_native"),
                row.get("pathway_external_id"),
            ]
            if any(pathway_ids_equivalent(pathway_id, str(v or "")) for v in ids):
                return row

        # --- Name match ---
        if pathway_name:
            row_name = row.get("pathway_name") or row.get("pathway_id_native") or ""
            if row_name:
                # Exact normalised match (same as method_aware_enrichment._norm_name)
                if _norm_name(str(row_name)) == _norm_name(pathway_name):
                    return row
                # Semantic match
                if matcher.match(pathway_name, str(row_name)).hit:
                    return row

    return None


def _norm_name(value: str) -> str:
    """Normalise pathway name to lowercase alphanum tokens (same as method_aware_enrichment)."""
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))

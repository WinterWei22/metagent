from __future__ import annotations

import json
from typing import Any

from verifier.schemas import ClaimType


JUDGE_ELIGIBLE_TYPES = {
    ClaimType.GROUNDED,
    ClaimType.BIOLOGICAL,
    ClaimType.FACTUAL,
}


def build_source_report_excerpt(source_report: Any, max_chars: int = 12_000) -> str:
    if hasattr(source_report, "model_dump"):
        payload = source_report.model_dump(mode="json")
    else:
        payload = source_report
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return text[:max_chars]


def build_llm_judge_prompt(
    *,
    claim_text: str,
    claim_type: ClaimType,
    source_report_excerpt: Any,
) -> str:
    excerpt = (
        source_report_excerpt
        if isinstance(source_report_excerpt, str)
        else build_source_report_excerpt(source_report_excerpt)
    )
    eligible = ", ".join(sorted(claim_type.name for claim_type in JUDGE_ELIGIBLE_TYPES))
    return (
        "Classify a MetAgent Sub-6 claim as judge_strict evidence.\n"
        f"Eligible claim types: {eligible}.\n"
        "Return JSON with verdict, confidence, evidence_pointer, rationale.\n"
        "Use judge_strict rules only when source_report evidence is sufficient.\n"
        "EDGE-1: External knowledge base or Reactome-only pathway claims are judge_uncoverable unless source_report directly contains that evidence.\n"
        "EDGE-2: Identifier-as-content mentions, such as bare KEGG/HMDB/Reactome IDs without source values, are judge_uncoverable.\n"
        "EDGE-3: Interpretive contribution language without direct numeric or ranked source support is judge_uncoverable.\n"
        "EDGE-4: Undefined placement/status terms such as central, upstream, downstream, or key are judge_uncoverable without direct source fields.\n"
        "EDGE-5: Direct Mummichog rank, score, p-value, or pathway ID claims with populated mummichog_enrichment_result carrier can be judge_strict.\n"
        f"claim_type: {claim_type.name}\n"
        f"claim_text: {claim_text}\n"
        f"source_report_excerpt: {excerpt}"
    )

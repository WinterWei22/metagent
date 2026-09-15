"""Task 6 (D2.2): missing-evidence checklist for SET_ENRICHMENT INSUFFICIENT_EVIDENCE.

Returns a Chinese-language checklist describing what evidence is missing to
adjudicate a claim whose pathway is named but absent from all enrichment pools.

NOTE: The design doc mentions an optional ``query_pathway_members`` re-query
before giving up. That step would require the verifier to call a concord tool,
which would violate the architecture boundary (``verifier/`` must NOT import
``concord/``). The re-query is therefore DEFERRED. The checklist records what
a human or future layer would need to supply.
"""
from __future__ import annotations

from verifier.schemas import ClassifiedClaim


def build_missing_evidence_checklist(
    claim: ClassifiedClaim,
    pool: list[dict],  # non-empty pool that did NOT match
) -> str:
    """Return a Chinese checklist of what is needed to judge *claim*.

    Parameters
    ----------
    claim:
        The SET_ENRICHMENT claim that could not be matched.
    pool:
        The flattened multisource pool rows that were searched (may be empty
        if only RaMP top-10 was available). Used to enumerate which paradigms
        ARE present so the checklist can name which one(s) are missing.

    Returns
    -------
    str
        Human-readable Chinese checklist suitable for ``VerifiedClaim.feedback_hint``.
    """
    pathway_ref = (
        (claim.extracted_fields.pathway_name if claim.extracted_fields else None)
        or (claim.extracted_fields.pathway_id if claim.extracted_fields else None)
        or _lifted_name_from_text(claim.claim_text)
        or "（未知通路）"
    )

    # Enumerate paradigms seen in the pool so reviewer knows what's available.
    paradigms_seen: list[str] = sorted(
        {row.get("_paradigm", "unknown") for row in pool if row.get("_paradigm")}
    )
    paradigm_str = "、".join(paradigms_seen) if paradigms_seen else "任一 paradigm"

    lines = [
        f"该通路 {pathway_ref!r} 未出现在 {paradigm_str} 的 top_pathways；",
        "判定缺少以下证据（至少满足其一）：",
        "  1. query_pathway_members(pathway_id) 的通路成员表（验证 claim 中代谢物是否真属该通路）",
        "  2. 该通路在某 paradigm 富集结果中的 FDR/p-value（确认真实入选 top_pathways）",
        "  3. 外部 KB（KEGG / RaMP / WikiPathways）对 pathway_id 的别名解析，",
        "     以确认 claim 命名与 top_pathways 中条目是否同义",
        "NOTE: query_pathway_members 补查已延迟实现（verifier/ 不可 import concord/）",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


def _lifted_name_from_text(text: str) -> str | None:
    """Very lightweight fallback: try to extract a pathway phrase from text."""
    import re
    _PHRASE_RE = re.compile(
        r"\b([A-Za-z][A-Za-z0-9-]*(?:\s+[A-Za-z][A-Za-z0-9-]*){0,5}\s+"
        r"(?:metabolism|biosynthesis|degradation|catabolism|anabolism|"
        r"synthesis|cycle|signaling|pathway))\b",
        re.IGNORECASE,
    )
    m = _PHRASE_RE.search(text)
    return m.group(0).strip() if m else None

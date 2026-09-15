from __future__ import annotations

import re
from typing import Any

from schemas.sub6_report import SubsixSourceReport
from verifier.helpers.pathway_namespace import pathway_ids_equivalent
from verifier.schemas import (
    ClaimSubtype,
    ClaimType,
    ClaimVerdict,
    ClassifiedClaim,
    VerifiedClaim,
)


def verify_method_aware_enrichment(
    claim: ClassifiedClaim,
    source_report: SubsixSourceReport,
) -> VerifiedClaim | None:
    """Verify structured enrichment claims against their cited method carrier.

    Returns None when no explicit method is present so the legacy RaMP layer
    can preserve default behavior exactly.
    """
    method = _evidence_method(claim)
    if method is None:
        return None

    rows, carrier_name, base_path = _carrier_rows(source_report, method)
    if not rows:
        return _verified(
            claim,
            verdict=ClaimVerdict.UNVERIFIABLE_V0,
            evidence=f"{carrier_name} carrier not populated; no fallback to RaMP.",
            source_field=base_path,
            tool_called=carrier_name,
        )

    pathway_id = claim.extracted_fields.pathway_id or _pathway_id_from_text(claim.claim_text)
    pathway_name = claim.extracted_fields.pathway_name
    matched_index, matched = _find_row(rows, pathway_id, pathway_name)
    if matched is None:
        return _verified(
            claim,
            verdict=ClaimVerdict.CONTRADICTED,
            evidence=f"Claimed pathway {(pathway_id or pathway_name)!r} not found in {base_path}.",
            source_field=base_path,
            tool_called=carrier_name,
        )

    claimed_rank = claim.extracted_fields.rank or _rank_from_text(claim.claim_text)
    claimed_score = claim.extracted_fields.score_value or _score_from_text(claim.claim_text)
    observed_rank = _row_rank(matched, matched_index)
    observed_score = _row_score(matched)
    rank_ok = claimed_rank is None or _rank_matches(claimed_rank, observed_rank)
    score_ok = claimed_score is None or _score_matches(claimed_score, observed_score)
    source_field = f"{base_path}[{matched_index}]"
    if rank_ok and score_ok:
        return _verified(
            claim,
            verdict=ClaimVerdict.SUPPORTED,
            evidence=(
                f"{carrier_name} matched pathway {matched.get('pathway_id')!r} "
                f"rank={observed_rank} score={observed_score}."
            ),
            source_field=source_field,
            tool_called=carrier_name,
        )

    return _verified(
        claim,
        verdict=ClaimVerdict.CONTRADICTED,
        evidence=(
            f"{carrier_name} matched pathway {matched.get('pathway_id')!r}, "
            f"but claimed_rank={claimed_rank}, observed_rank={observed_rank}, "
            f"claimed_score={claimed_score}, observed_score={observed_score}."
        ),
        source_field=source_field,
        tool_called=carrier_name,
    )


def _evidence_method(claim: ClassifiedClaim) -> str | None:
    raw = getattr(claim.extracted_fields, "evidence_method", None)
    text = str(raw or claim.claim_text).lower()
    if "mummichog" in text or "mumm:" in text:
        return "mummichog"
    if "metaboanalystr" in text or "metaboanalyst" in text or "psea" in text:
        return "metaboanalystr"
    if "sspa" in text:
        return "sspa"
    if "fella" in text:
        return "fella"
    if raw and "ramp" in text:
        return "ramp"
    return None


def _carrier_rows(
    source_report: SubsixSourceReport,
    method: str,
) -> tuple[list[dict[str, Any]], str, str]:
    if method == "mummichog":
        carrier = source_report.mummichog_enrichment_result or {}
        return list(carrier.get("pathways") or carrier.get("top_pathways") or []), "mummichog_enrichment_result", "mummichog_enrichment_result.pathways"
    if method == "metaboanalystr":
        carrier = (source_report.metaboanalystr_enrichment_result or {}).get("psea") or {}
        return list(carrier.get("pathways") or carrier.get("top_pathways") or []), "metaboanalystr_enrichment_result", "metaboanalystr_enrichment_result.psea.pathways"
    if method == "sspa":
        carrier = source_report.sspa_enrichment_result or {}
        return list(carrier.get("pathways") or carrier.get("top_pathways") or []), "sspa_enrichment_result", "sspa_enrichment_result.pathways"
    if method == "fella":
        carrier = source_report.fella_enrichment_result or {}
        return list(carrier.get("pathways") or carrier.get("top_pathways") or []), "fella_enrichment_result", "fella_enrichment_result.pathways"
    carrier = source_report.ramp_enrichment_result or {}
    return list(carrier.get("top_pathways") or []), "ramp_enrichment_result", "ramp_enrichment_result.top_pathways"


def _find_row(
    rows: list[dict[str, Any]],
    pathway_id: str | None,
    pathway_name: str | None,
) -> tuple[int, dict[str, Any] | None]:
    for idx, row in enumerate(rows):
        ids = [
            row.get("pathway_id"),
            row.get("pathway_id_native"),
            row.get("pathway_external_id"),
        ]
        if pathway_id and any(pathway_ids_equivalent(pathway_id, str(value or "")) for value in ids):
            return idx, row
        if pathway_name:
            row_name = _norm_name(str(row.get("pathway_name") or row.get("pathway_id_native") or ""))
            if row_name and row_name == _norm_name(pathway_name):
                return idx, row
    return -1, None


def _rank_matches(claimed: int, observed: int | None) -> bool:
    if observed is None:
        return False
    return claimed == observed or (claimed > 0 and claimed - 1 == observed)


def _score_matches(claimed: float, observed: float | None) -> bool:
    if observed is None:
        return False
    return abs(claimed - observed) <= max(1e-12, abs(observed) * 0.03)


def _row_rank(row: dict[str, Any], index: int) -> int | None:
    if row.get("rank") is not None:
        try:
            return int(row["rank"])
        except (TypeError, ValueError):
            return None
    return index


def _row_score(row: dict[str, Any]) -> float | None:
    for key in ("score", "fdr", "p_value"):
        if row.get(key) is not None:
            try:
                return float(row[key])
            except (TypeError, ValueError):
                return None
    return None


def _pathway_id_from_text(text: str) -> str | None:
    match = re.search(
        r"\b(MUMM:[A-Za-z0-9_:-]+|KEGG:(?:map|hsa)\d{5}|(?:map|hsa)\d{5}|WP:WP\d{3,5}|SMPDB:SMP\d{5,7}|REACT:R-HSA-\d+)\b",
        text,
        flags=re.I,
    )
    return match.group(1) if match else None


def _rank_from_text(text: str) -> int | None:
    match = re.search(r"rank(?:s|ed)?(?:\s+#?\s*|\s*=\s*)(\d+)", text, flags=re.I)
    if match:
        return int(match.group(1))
    if re.search(r"\btop[- ]ranked\b|\btop hit\b|\bfirst\b", text, flags=re.I):
        return 0
    if re.search(r"\bsecond\b|\b2nd\b", text, flags=re.I):
        return 1
    return None


def _score_from_text(text: str) -> float | None:
    match = re.search(
        r"\b(?:fdr|p[_ -]?value|p)\b\s*(?:=|of|is|at|with)?\s*([0-9]+(?:\.[0-9]+)?(?:e[-+]?\d+)?)",
        text,
        flags=re.I,
    )
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _norm_name(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def _verified(
    claim: ClassifiedClaim,
    *,
    verdict: ClaimVerdict,
    evidence: str,
    source_field: str,
    tool_called: str,
) -> VerifiedClaim:
    return VerifiedClaim(
        claim_id=claim.claim_id,
        claim_text=claim.claim_text,
        claim_type=ClaimType.SET_ENRICHMENT,
        claim_subtype=ClaimSubtype.ENRICHMENT_PATHWAY,
        subject=claim.subject,
        subject_kind=claim.subject_kind,
        candidate_ref=claim.candidate_ref,
        verdict=verdict,
        evidence=evidence,
        source_field=source_field,
        extracted_fields=claim.extracted_fields,
        verifier_layer="method_aware_enrichment",
        tool_called=tool_called,
        trace_summary=f"method-aware enrichment {verdict.value}",
    )


"""Claim-level metrics for verifier outputs."""
from __future__ import annotations

from collections import Counter, defaultdict

from verifier.schemas import ClaimMetrics, ClaimVerdict, VerifiedClaim


def compute_claim_metrics(
    claims_v1: list[VerifiedClaim],
    claims_v2: list[VerifiedClaim],
) -> ClaimMetrics:
    """Compute first-pass claim metrics.

    Metrics default to ``claims_v2`` because that is the user-visible,
    post-rewrite claim set. When v2 is empty, v1 is used as a fallback.
    """
    claims = claims_v2 or claims_v1
    total = len(claims)
    verdict_counts = Counter(c.verdict for c in claims)

    supported = verdict_counts[ClaimVerdict.SUPPORTED]
    contradicted = verdict_counts[ClaimVerdict.CONTRADICTED]
    unsupported = verdict_counts[ClaimVerdict.UNSUPPORTED]
    unverifiable = verdict_counts[ClaimVerdict.UNVERIFIABLE_V0]
    errors = verdict_counts[ClaimVerdict.ERROR]

    judged_denominator = supported + contradicted + unsupported

    confidence_components = _confidence_components(
        claim_precision=_claim_precision(supported, judged_denominator, total),
        supported_ratio=_ratio(supported, total),
        contradiction_rate=_ratio(contradicted, total),
        unverifiable_rate=_ratio(unverifiable, total),
    )
    metrics = ClaimMetrics(
        total_claims=total,
        supported_claims=supported,
        contradicted_claims=contradicted,
        unsupported_claims=unsupported,
        unverifiable_claims=unverifiable,
        error_claims=errors,
        supported_ratio=confidence_components.get("supported_ratio"),
        contradiction_rate=confidence_components.get("contradiction_rate"),
        unverifiable_rate=confidence_components.get("unverifiable_rate"),
        claim_precision=confidence_components.get("claim_precision"),
        rewrite_improvement=_rewrite_improvement(claims_v1, claims_v2),
        per_type_verdict_counts=_per_type_verdict_counts(claims),
        per_subtype_verdict_counts=_per_subtype_verdict_counts(claims),
        per_candidate_support_counts=_per_candidate_counts(claims),
        peak_claim_coverage=_peak_claim_coverage(claims),
        tool_call_counts=_tool_call_counts(claims),
        confidence_components=confidence_components,
    )
    return metrics.model_copy(
        update={"verification_confidence": compute_verification_confidence(metrics)}
    )


def compute_verification_confidence(metrics: ClaimMetrics) -> float | None:
    """Auditable aggregate confidence from claim-level verifier metrics."""
    required = (
        metrics.claim_precision,
        metrics.supported_ratio,
        metrics.contradiction_rate,
        metrics.unverifiable_rate,
    )
    if any(v is None for v in required):
        return None
    confidence = (
        0.45 * metrics.claim_precision
        + 0.25 * metrics.supported_ratio
        + 0.20 * (1.0 - metrics.contradiction_rate)
        + 0.10 * (1.0 - metrics.unverifiable_rate)
    )
    return round(max(0.0, min(1.0, confidence)), 12)


def _ratio(num: int, den: int) -> float | None:
    if den == 0:
        return None
    return num / den


def _claim_precision(supported: int, judged_denominator: int, total: int) -> float | None:
    if total == 0:
        return None
    if judged_denominator == 0:
        return 0.0
    return supported / judged_denominator


def _confidence_components(
    *,
    claim_precision: float | None,
    supported_ratio: float | None,
    contradiction_rate: float | None,
    unverifiable_rate: float | None,
) -> dict[str, float]:
    out: dict[str, float] = {}
    for key, value in (
        ("claim_precision", claim_precision),
        ("supported_ratio", supported_ratio),
        ("contradiction_rate", contradiction_rate),
        ("unverifiable_rate", unverifiable_rate),
    ):
        if value is not None:
            out[key] = value
    return out


def _per_type_verdict_counts(
    claims: list[VerifiedClaim],
) -> dict[str, dict[str, int]]:
    out: dict[str, Counter[str]] = defaultdict(Counter)
    for claim in claims:
        out[claim.claim_type.value][claim.verdict.value] += 1
    return {k: dict(v) for k, v in out.items()}


def _per_subtype_verdict_counts(
    claims: list[VerifiedClaim],
) -> dict[str, dict[str, int]]:
    out: dict[str, Counter[str]] = defaultdict(Counter)
    for claim in claims:
        out[claim.claim_subtype.value][claim.verdict.value] += 1
    return {k: dict(v) for k, v in out.items()}


def _per_candidate_counts(
    claims: list[VerifiedClaim],
) -> dict[str, dict[str, int]]:
    out: dict[str, Counter[str]] = defaultdict(Counter)
    for claim in claims:
        if claim.candidate_ref is None:
            continue
        key = claim.candidate_ref.path or claim.candidate_ref.name
        if not key:
            continue
        out[key][claim.verdict.value] += 1
    return {k: dict(v) for k, v in out.items()}


def _tool_call_counts(claims: list[VerifiedClaim]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for claim in claims:
        if claim.tool_called:
            counts[claim.tool_called] += 1
    return dict(counts)


def _peak_claim_coverage(claims: list[VerifiedClaim]) -> float | None:
    peak_claims = [
        c for c in claims
        if c.extracted_fields.mz is not None or c.claim_type.value == "peak_mechanistic_claim"
    ]
    if not peak_claims:
        return None
    supported = sum(1 for c in peak_claims if c.verdict == ClaimVerdict.SUPPORTED)
    return supported / len(peak_claims)


def _rewrite_improvement(
    claims_v1: list[VerifiedClaim],
    claims_v2: list[VerifiedClaim],
) -> float | None:
    if not claims_v1 or not claims_v2:
        return None
    bad = {
        ClaimVerdict.CONTRADICTED,
        ClaimVerdict.UNSUPPORTED,
        ClaimVerdict.ERROR,
    }
    bad_v1 = sum(1 for c in claims_v1 if c.verdict in bad)
    bad_v2 = sum(1 for c in claims_v2 if c.verdict in bad)
    if bad_v1 == 0:
        return None
    return (bad_v1 - bad_v2) / bad_v1

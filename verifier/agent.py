"""Public verifier entry point — ``verify(...)``.

Strings the four cascade stages together:

* Stage 1 — extract claims (LLM call #1)
* Stage 2 — classify claims (rule-based; LLM call #2 only if any claim was
  ambiguous)
* Stage 3 — verify each claim via Layer A (grounded), B (factual), or C
  (biological); plus Layer D consistency sweep (LLM call #3 if ≥2 claims)
* Stage 4 — if any v1 verdict was actionable, rewrite (LLM call #4),
  re-extract from rewritten output (LLM call #5), reclassify (LLM call
  #6 if v2 has ambiguity), re-run Layer D consistency on v2 (LLM call
  #7)

Worst-case budget: 7 LLM calls (Stage 2 can fire in both v1 and v2 when
both passes have rule-ambiguous claims). Best case (all v1 supported, no
Stage 4): 1 call. Per-call ``caller`` strings on the JSONL log:
``verifier.stage1.extract_claims``, ``verifier.stage2.classify_ambiguous``,
``verifier.stage3.check_consistency``, ``verifier.stage4.rewrite``.

Architectural rule: this module does NOT import from ``orchestrator.*``.
Caller-side, the typical pattern is::

    naive = orchestrator.naive.identify(report)
    verified = verify(
        llm_output=naive.llm_output,
        source_report=report,
        trace_id=naive.trace_id + "_verified",
    )
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Literal

from schemas import LiteratureSearchResponse
from schemas.molecule import MetaboliteInfoResponse
from schemas.report import IdentificationReport
from verifier.claim_classifier import classify_claims
from verifier.claim_extractor import (
    ClaimExtractionError,
    extract_claims,
)
from verifier.layers import biological as layer_c
from verifier.layers import consistency as layer_d
from verifier.layers import factual as layer_b
from verifier.layers import grounded as layer_a
from verifier.layers import literature as layer_e
from verifier.layers import peak_mechanistic as layer_f
from verifier.rewriter import is_rewrite_needed, rewrite
from verifier.schemas import (
    ClaimType,
    ClaimVerdict,
    ClassifiedClaim,
    VerifiedClaim,
    VerifiedIdentification,
)


Fetcher = Callable[[str], MetaboliteInfoResponse]
LiteratureFetcher = Callable[[str], LiteratureSearchResponse]


def verify(
    llm_output: str,
    source_report: IdentificationReport,
    *,
    trace_id: str,
    fetcher: Fetcher | None = None,
    literature_fetcher: LiteratureFetcher | None = None,
) -> VerifiedIdentification:
    """Run the full 4-stage cascade. Always returns; never re-raises.

    ``fetcher`` is dependency-injected for Layer B (metabolite_info round-
    trip); ``literature_fetcher`` for Layer E (Europe PMC). Both default to
    the real tools, lazy-imported when first needed; tests pass mocks.
    """
    warnings: list[str] = []
    llm_calls = 0

    # ---------- v1 pass ----------
    classified_v1, calls, w = _extract_classify(
        llm_output, trace_id=f"{trace_id}.s1s2_v1"
    )
    llm_calls += calls
    warnings += w
    if classified_v1 is None:
        # Stage 1 failed; cannot proceed.
        return _failed(
            llm_output=llm_output,
            trace_id=trace_id,
            warnings=warnings,
            llm_calls=llm_calls,
        )

    verified_v1 = _verify_per_claim(
        classified_v1, source_report,
        fetcher=fetcher, literature_fetcher=literature_fetcher,
    )
    consistency_v1, calls, w = layer_d.detect_consistency_contradictions(
        classified_v1, trace_id=f"{trace_id}.s3_v1"
    )
    llm_calls += calls
    warnings += w
    verified_v1 = list(verified_v1) + list(consistency_v1)

    # ---------- Stage 4: rewrite + re-extract + re-verify ----------
    if not is_rewrite_needed(verified_v1):
        return _final(
            llm_output=llm_output,
            rewritten_output=llm_output,
            claims_v1=verified_v1,
            claims_v2=verified_v1,
            warnings=warnings,
            llm_calls=llm_calls,
            trace_id=trace_id,
        )

    rewritten = rewrite(
        source_llm_output=llm_output,
        verified_claims=verified_v1,
        trace_id=f"{trace_id}.s4_rewrite",
    )
    llm_calls += 1

    classified_v2, calls, w = _extract_classify(
        rewritten, trace_id=f"{trace_id}.s1s2_v2"
    )
    llm_calls += calls
    warnings += w
    if classified_v2 is None:
        # Re-extract failed — preserve v1 record but flag the failure.
        warnings.append(
            "Stage 4 re-extract failed; claims_v2 left equal to claims_v1."
        )
        return _final(
            llm_output=llm_output,
            rewritten_output=rewritten,
            claims_v1=verified_v1,
            claims_v2=verified_v1,
            warnings=warnings,
            llm_calls=llm_calls,
            trace_id=trace_id,
        )

    verified_v2 = _verify_per_claim(
        classified_v2, source_report,
        fetcher=fetcher, literature_fetcher=literature_fetcher,
    )
    consistency_v2, calls, w = layer_d.detect_consistency_contradictions(
        classified_v2, trace_id=f"{trace_id}.s3_v2"
    )
    llm_calls += calls
    warnings += w
    verified_v2 = list(verified_v2) + list(consistency_v2)

    return _final(
        llm_output=llm_output,
        rewritten_output=rewritten,
        claims_v1=verified_v1,
        claims_v2=verified_v2,
        warnings=warnings,
        llm_calls=llm_calls,
        trace_id=trace_id,
    )


# ---------------------------------------------------------------------------
# Stage helpers
# ---------------------------------------------------------------------------


def _extract_classify(
    text: str, *, trace_id: str
) -> tuple[list[ClassifiedClaim] | None, int, list[str]]:
    """Run Stage 1 + Stage 2. Returns (classified, llm_calls, warnings).

    ``classified`` is None when Stage 1 raised — caller treats that as a
    fatal cascade failure for the relevant pass.

    Empty / whitespace-only input short-circuits: ``extract_claims`` skips
    the LLM call, we return an empty classified list, and llm_calls stays
    at 0. This keeps :class:`VerifiedIdentification.llm_call_count`
    honest rather than over-counting a call that never happened.
    """
    warnings: list[str] = []
    if not text.strip():
        return [], 0, warnings

    try:
        extracted = extract_claims(text, trace_id=f"{trace_id}.extract")
    except ClaimExtractionError as exc:
        warnings.append(f"VERIFICATION_PARSE_FAILED at stage1: {exc}")
        return None, 1, warnings

    classified, classify_calls = classify_claims(
        extracted, trace_id=f"{trace_id}.classify"
    )
    return classified, 1 + classify_calls, warnings


def _verify_per_claim(
    classified: list[ClassifiedClaim],
    source_report: IdentificationReport,
    *,
    fetcher: Fetcher | None,
    literature_fetcher: LiteratureFetcher | None = None,
) -> list[VerifiedClaim]:
    """Dispatch each claim to its layer (A/B/C/E). Layer D runs separately."""
    out: list[VerifiedClaim] = []
    for c in classified:
        if c.claim_type == ClaimType.GROUNDED:
            out.append(layer_a.verify_grounded(c, source_report))
        elif c.claim_type == ClaimType.FACTUAL:
            out.append(layer_b.verify_factual(c, source_report, fetcher=fetcher))
        elif c.claim_type == ClaimType.BIOLOGICAL:
            out.append(layer_c.verify_biological(c, source_report))
        elif c.claim_type == ClaimType.LITERATURE:
            out.append(
                layer_e.verify_literature(
                    c, source_report, fetcher=literature_fetcher,
                )
            )
        elif c.claim_type == ClaimType.PEAK_MECHANISTIC:
            out.append(layer_f.verify_peak_mechanistic(c, source_report))
        elif c.claim_type == ClaimType.CONSISTENCY:
            # Stage 2 should not assign CONSISTENCY directly — Layer D
            # creates those entries. If it ever happens (LLM fallback
            # returned consistency_claim), default-route to Layer A.
            out.append(layer_a.verify_grounded(c, source_report))
        else:  # pragma: no cover — exhaustive
            raise AssertionError(f"unhandled claim_type {c.claim_type}")
    return out


# ---------------------------------------------------------------------------
# Verdict aggregation
# ---------------------------------------------------------------------------


def _aggregate_verdict(
    claims: list[VerifiedClaim],
) -> Literal["verified", "partially_verified", "contradicted", "failed"]:
    if not claims:
        # No claims at all is a failure mode (extractor returned empty).
        return "failed"
    has_contradicted = any(c.verdict == ClaimVerdict.CONTRADICTED for c in claims)
    has_error = any(c.verdict == ClaimVerdict.ERROR for c in claims)
    has_unsupported = any(c.verdict == ClaimVerdict.UNSUPPORTED for c in claims)
    has_unverifiable = any(
        c.verdict == ClaimVerdict.UNVERIFIABLE_V0 for c in claims
    )
    if has_contradicted:
        return "contradicted"
    if has_error:
        # An ERROR (tool raised, parse failed mid-cascade) means we cannot
        # confidently say "verified". Treat as partially_verified rather
        # than failed — the caller still gets the surviving evidence.
        return "partially_verified"
    if has_unsupported or has_unverifiable:
        return "partially_verified"
    return "verified"


# ---------------------------------------------------------------------------
# Result constructors
# ---------------------------------------------------------------------------


def _final(
    *,
    llm_output: str,
    rewritten_output: str,
    claims_v1: list[VerifiedClaim],
    claims_v2: list[VerifiedClaim],
    warnings: list[str],
    llm_calls: int,
    trace_id: str,
) -> VerifiedIdentification:
    return VerifiedIdentification(
        trace_id=trace_id,
        source_llm_output=llm_output,
        rewritten_output=rewritten_output,
        claims_v1=claims_v1,
        claims_v2=claims_v2,
        overall_verdict=_aggregate_verdict(claims_v2),
        verification_warnings=warnings,
        llm_call_count=llm_calls,
        generated_at=datetime.now(timezone.utc),
    )


def _failed(
    *,
    llm_output: str,
    trace_id: str,
    warnings: list[str],
    llm_calls: int,
) -> VerifiedIdentification:
    return VerifiedIdentification(
        trace_id=trace_id,
        source_llm_output=llm_output,
        rewritten_output=llm_output,
        claims_v1=[],
        claims_v2=[],
        overall_verdict="failed",
        verification_warnings=warnings,
        llm_call_count=llm_calls,
        generated_at=datetime.now(timezone.utc),
    )

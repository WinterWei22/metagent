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

import os
from datetime import datetime, timezone
from typing import Any, Callable, Literal

from schemas import LiteratureSearchResponse
from schemas.molecule import MetaboliteInfoResponse
from schemas.report import IdentificationReport
from schemas.sub6_report import SubsixSourceReport
from verifier.candidate_resolution import resolve_candidate_ref
from verifier.claim_classifier import classify_claims
from verifier.claim_extractor import (
    ClaimExtractionError,
    extract_claims,
    extract_claims_rulebased,
)
from verifier.claim_table import build_claim_table
from verifier.layers import biological as layer_c
from verifier.layers import consistency as layer_d
from verifier.layers import factual as layer_b
from verifier.layers import grounded as layer_a
from verifier.layers import literature as layer_e
from verifier.layers import peak_mechanistic as layer_f
from verifier.metrics import compute_claim_metrics
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
CfmidPredictor = Callable[[Any], Any]


def verify(
    llm_output: str,
    source_report: IdentificationReport,
    *,
    trace_id: str,
    fetcher: Fetcher | None = None,
    literature_fetcher: LiteratureFetcher | None = None,
    cfmid_fn: CfmidPredictor | None = None,
) -> VerifiedIdentification:
    """Run the full 4-stage cascade. Always returns; never re-raises.

    ``fetcher`` is dependency-injected for Layer B (metabolite_info round-
    trip); ``literature_fetcher`` for Layer E (Europe PMC); ``cfmid_fn``
    for Layer F's CFM-ID cross-check. All default to the real tools,
    lazy-imported when first needed; tests pass mocks.
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
        cfmid_fn=cfmid_fn,
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
        cfmid_fn=cfmid_fn,
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

    Phase 6.4: when ``METAGENT_VERIFIER_EXTRACTOR=rule-based`` is set in
    the environment, Stage 1 uses :func:`extract_claims_rulebased` (no LLM
    call, sentence-level split that preserves compound mechanistic
    phrases). The rule-based path is paper-finding-tied to Layer F
    activation; see ``reports/eval/layerf_loop_closed.md`` for context.
    """
    warnings: list[str] = []
    if not text.strip():
        return [], 0, warnings

    extractor_mode = os.environ.get("METAGENT_VERIFIER_EXTRACTOR", "llm").lower()
    try:
        if extractor_mode == "rule-based":
            extracted = extract_claims_rulebased(text, trace_id=f"{trace_id}.extract")
            extract_calls = 0
        else:
            extracted = extract_claims(text, trace_id=f"{trace_id}.extract")
            extract_calls = 1
    except ClaimExtractionError as exc:
        warnings.append(f"VERIFICATION_PARSE_FAILED at stage1: {exc}")
        return None, 1, warnings

    classified, classify_calls = classify_claims(
        extracted, trace_id=f"{trace_id}.classify"
    )
    return classified, extract_calls + classify_calls, warnings


def _verify_per_claim(
    classified: list[ClassifiedClaim],
    source_report: IdentificationReport,
    *,
    fetcher: Fetcher | None,
    literature_fetcher: LiteratureFetcher | None = None,
    cfmid_fn: CfmidPredictor | None = None,
) -> list[VerifiedClaim]:
    """Dispatch each claim to its layer (A/B/C/E/F). Layer D runs separately."""
    out: list[VerifiedClaim] = []
    for c in classified:
        candidate_ref = resolve_candidate_ref(c, source_report)
        if candidate_ref is not None:
            c = c.model_copy(update={"candidate_ref": candidate_ref})
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
            out.append(
                layer_f.verify_peak_mechanistic(
                    c, source_report, cfmid_fn=cfmid_fn,
                )
            )
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
    has_needs_review = any(
        c.verdict == ClaimVerdict.NEEDS_HUMAN_REVIEW for c in claims
    )
    if has_contradicted:
        return "contradicted"
    if has_error:
        # An ERROR (tool raised, parse failed mid-cascade) means we cannot
        # confidently say "verified". Treat as partially_verified rather
        # than failed — the caller still gets the surviving evidence.
        return "partially_verified"
    if has_unsupported or has_unverifiable or has_needs_review:
        # NEEDS_HUMAN_REVIEW from Layer F's cross-validation: the
        # consensus could not arbitrate between SIRIUS and CFM-ID, so
        # the claim's status is suspended pending review. Maps to
        # partially_verified rather than contradicted because the
        # tools have not jointly contradicted the claim.
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
    # Phase A2 D1: synthesise stable claim_ids and populate feedback_hint
    # before serialising. The build_claim_table helper still applies its
    # fallback id-synthesis but it now no-ops since claim_id is set.
    from verifier.feedback_hints import annotate_claims
    claims_v1 = annotate_claims(claims_v1, pass_id="v1")
    claims_v2 = annotate_claims(claims_v2, pass_id="v2")
    table_v1 = build_claim_table(claims_v1, pass_id="v1")
    table_v2 = build_claim_table(claims_v2, pass_id="v2")
    metrics = compute_claim_metrics(claims_v1=claims_v1, claims_v2=claims_v2)
    return VerifiedIdentification(
        trace_id=trace_id,
        source_llm_output=llm_output,
        rewritten_output=rewritten_output,
        claims_v1=claims_v1,
        claims_v2=claims_v2,
        claim_tables=[table_v1, table_v2],
        claim_metrics=metrics,
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
    table_v1 = build_claim_table([], pass_id="v1")
    table_v2 = build_claim_table([], pass_id="v2")
    metrics = compute_claim_metrics(claims_v1=[], claims_v2=[])
    return VerifiedIdentification(
        trace_id=trace_id,
        source_llm_output=llm_output,
        rewritten_output=llm_output,
        claims_v1=[],
        claims_v2=[],
        claim_tables=[table_v1, table_v2],
        claim_metrics=metrics,
        overall_verdict="failed",
        verification_warnings=warnings,
        llm_call_count=llm_calls,
        generated_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Sub-6 entry point
# ---------------------------------------------------------------------------


def verify_sub6(
    llm_output: str,
    source_report: SubsixSourceReport,
    *,
    trace_id: str,
    ramp_db_path: str | None = None,
    ramp_conn=None,
    driver_lookup: dict[str, str] | None = None,
) -> VerifiedIdentification:
    """Stage-cascaded verification for Sub-6 enrichment narratives.

    Mirrors the structure of ``verify()`` but consumes a
    ``SubsixSourceReport`` and dispatches the four enrichment claim
    types (SET_ENRICHMENT, DRIVER_METABOLITE, PATHWAY_RELATIONSHIP,
    BIOLOGICAL) to their dedicated layers.

    Stage 4 (rewriter) is intentionally NOT run for Sub-6 in v0 — the
    rewriter is tuned for spectrum-centric corrections and lacks templates
    for enrichment narratives. ``rewritten_output`` is set to
    ``llm_output`` and ``claims_v2 == claims_v1``.

    Other claim types (GROUNDED / FACTUAL / LITERATURE / PEAK_MECHANISTIC /
    CONSISTENCY) that the extractor + classifier might still surface from
    a Sub-6 narrative are routed to a Sub-6 friendly default verdict —
    ``UNVERIFIABLE_V0`` — because the existing layers consume the
    spectrum-centric ``IdentificationReport`` and would crash on
    SubsixSourceReport. Layer D (consistency) is the one exception: it
    operates on the claim list itself without reading source_report.candidates,
    so it runs on Sub-6 narratives unmodified.
    """
    warnings: list[str] = []
    llm_calls = 0

    classified, calls, w = _extract_classify(
        llm_output, trace_id=f"{trace_id}.s1s2"
    )
    llm_calls += calls
    warnings += w
    if classified is None:
        return _failed(
            llm_output=llm_output,
            trace_id=trace_id,
            warnings=warnings,
            llm_calls=llm_calls,
        )

    verified = _verify_per_claim_sub6(
        classified,
        source_report,
        ramp_db_path=ramp_db_path,
        ramp_conn=ramp_conn,
        driver_lookup=driver_lookup,
    )
    consistency, calls, w = layer_d.detect_consistency_contradictions(
        classified, trace_id=f"{trace_id}.s3"
    )
    llm_calls += calls
    warnings += w
    verified = list(verified) + list(consistency)

    return _final(
        llm_output=llm_output,
        rewritten_output=llm_output,
        claims_v1=verified,
        claims_v2=verified,
        warnings=warnings,
        llm_calls=llm_calls,
        trace_id=trace_id,
    )


def _verify_per_claim_sub6(
    classified: list[ClassifiedClaim],
    source_report: SubsixSourceReport,
    *,
    ramp_db_path: str | None,
    ramp_conn,
    driver_lookup: dict[str, str] | None,
) -> list[VerifiedClaim]:
    """Dispatch each Sub-6 claim to its layer.

    Lazy-imports the four enrichment layers so import-time cost stays low
    when the verify() spectrum entry point is the only one being used.
    """
    from verifier.layers.biological_sub6 import verify_biological_sub6
    from verifier.layers.driver_metabolite import verify_driver_metabolite
    from verifier.layers.pathway_relationship import verify_pathway_relationship
    from verifier.layers.set_enrichment import verify_set_enrichment

    out: list[VerifiedClaim] = []
    for c in classified:
        if c.claim_type == ClaimType.SET_ENRICHMENT:
            out.append(verify_set_enrichment(c, source_report))
        elif c.claim_type == ClaimType.DRIVER_METABOLITE:
            out.append(
                verify_driver_metabolite(
                    c, source_report, lookup=driver_lookup,
                )
            )
        elif c.claim_type == ClaimType.PATHWAY_RELATIONSHIP:
            out.append(
                verify_pathway_relationship(
                    c, source_report,
                    db_path=ramp_db_path, conn=ramp_conn,
                )
            )
        elif c.claim_type == ClaimType.BIOLOGICAL:
            out.append(
                verify_biological_sub6(
                    c, source_report,
                    db_path=ramp_db_path, conn=ramp_conn,
                )
            )
        elif c.claim_type == ClaimType.PEAK_MECHANISTIC:
            # Phase 6.3: Layer F dispatch for Sub-6A real-id narratives.
            # SubsixSourceReport now exposes experimental_spectrum/candidates
            # adapters (schemas/sub6_report.py) so Layer F can run without
            # changes. The first differential_spectra row is used as the
            # spectrum proxy — see Phase 6.3 report §10 for the
            # per-claim-spectrum-routing future-work caveat.
            out.append(layer_f.verify_peak_mechanistic(c, source_report))
        else:
            # Spectrum-centric layers cannot consume SubsixSourceReport;
            # surface as UNVERIFIABLE_V0 with explicit reasoning.
            out.append(
                VerifiedClaim(
                    claim_id=c.claim_id,
                    claim_text=c.claim_text,
                    claim_type=c.claim_type,
                    claim_subtype=c.claim_subtype,
                    subject=c.subject,
                    subject_kind=c.subject_kind,
                    candidate_ref=c.candidate_ref,
                    verdict=ClaimVerdict.UNVERIFIABLE_V0,
                    evidence=(
                        f"Sub-6 verifier does not support claim_type "
                        f"{c.claim_type.value!r}: existing layer requires "
                        "IdentificationReport (spectrum-centric), but "
                        "Sub-6 supplies SubsixSourceReport. Treated as "
                        "declared limitation."
                    ),
                    extracted_fields=c.extracted_fields,
                    verifier_layer="verify_sub6",
                    trace_summary=f"sub6 cannot verify {c.claim_type.value}",
                )
            )
    return out

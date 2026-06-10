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

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Callable, Literal

logger = logging.getLogger(__name__)

from schemas import LiteratureSearchResponse
from schemas.molecule import MetaboliteInfoResponse
from schemas.report import IdentificationReport
from schemas.sub6_report import SubsixSourceReport
from verifier.candidate_resolution import resolve_candidate_ref
from verifier.claim_classifier import classify_claims
from verifier.claim_extractor import (
    ClaimExtractionError,
    extract_claims,
    extract_claims_from_json,
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
    DroppedClaim,
    TaskOutcome,
    VerifiedClaim,
    VerifiedIdentification,
)
from verifier.task_outcome import detect_task_outcome


# Phase B1 D4 — v2 grammar should only ever route to one of these
# ClaimType values via verifier.claim_classifier.route_v2_claim. Any
# other ClaimType arriving with ``grammar is not None`` means the
# extractor / classifier silently produced a v1 type for a v2-grammar
# claim — log it loudly so the smoke can flag the regression.
_V2_EXPECTED_TYPES = frozenset({
    ClaimType.BIOLOGICAL,
    ClaimType.SET_ENRICHMENT,
    ClaimType.DRIVER_METABOLITE,
})


def _maybe_warn_v1_legacy_in_v2_path(c: ClassifiedClaim, *, where: str) -> None:
    """Emit one ``logger.warning`` when a claim that was extracted via
    the v2 grammar path lands on a ClaimType the dispatcher expects to
    see only from the v1 legacy path.

    ``where`` is a short tag (e.g. ``'sub6'`` / ``'spectrum'``) for the
    log line so D5 audit can filter on it. The warning carries
    ``claim_id`` so the trace_id grep is fast.
    """
    if c.grammar is not None and c.claim_type not in _V2_EXPECTED_TYPES:
        logger.warning(
            "v1 legacy claim_type %s in v2 grammar path (%s); "
            "claim_id=%s grammar=%s",
            c.claim_type.value, where, c.claim_id, c.grammar.value,
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

    dropped_all: list[DroppedClaim] = []

    # ---------- v1 pass ----------
    classified_v1, calls, w, dropped = _extract_classify(
        llm_output, trace_id=f"{trace_id}.s1s2_v1"
    )
    llm_calls += calls
    warnings += w
    dropped_all += dropped
    if classified_v1 is None:
        # Stage 1 failed; cannot proceed.
        return _failed(
            llm_output=llm_output,
            trace_id=trace_id,
            warnings=warnings,
            llm_calls=llm_calls,
            dropped_claims=dropped_all,
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
            dropped_claims=dropped_all,
        )

    rewritten = rewrite(
        source_llm_output=llm_output,
        verified_claims=verified_v1,
        trace_id=f"{trace_id}.s4_rewrite",
    )
    llm_calls += 1

    classified_v2, calls, w, dropped = _extract_classify(
        rewritten, trace_id=f"{trace_id}.s1s2_v2"
    )
    llm_calls += calls
    warnings += w
    dropped_all += dropped
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
            dropped_claims=dropped_all,
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
        dropped_claims=dropped_all,
    )


# ---------------------------------------------------------------------------
# Stage helpers
# ---------------------------------------------------------------------------


def _extract_classify(
    text: str, *, trace_id: str
) -> tuple[
    list[ClassifiedClaim] | None,
    int,
    list[str],
    list[DroppedClaim],
]:
    """Run Stage 1 + Stage 2.

    Returns ``(classified, llm_calls, warnings, dropped)``.

    ``classified`` is None when Stage 1 raised — caller treats that as a
    fatal cascade failure for the relevant pass.

    ``dropped`` is the list of claims rejected by the grammar v2 path
    (empty list when the legacy extractor path is used). Surfacing it
    here is the Phase B1 D2 hook that lets ``_final`` aggregate the
    ``dropped_by_grammar`` metric across passes.

    Empty / whitespace-only input short-circuits: ``extract_claims`` skips
    the LLM call, we return an empty classified list, and llm_calls stays
    at 0. This keeps :class:`VerifiedIdentification.llm_call_count`
    honest rather than over-counting a call that never happened.

    Phase 6.4: when ``METAGENT_VERIFIER_EXTRACTOR=rule-based`` is set in
    the environment, Stage 1 uses :func:`extract_claims_rulebased` (no LLM
    call, sentence-level split that preserves compound mechanistic
    phrases). The rule-based path is paper-finding-tied to Layer F
    activation; see ``reports/eval/layerf_loop_closed.md`` for context.

    Phase B1 D2: a third mode, triggered when ``text`` parses as a v2
    grammar JSON payload (``{"narrative_text": str, "claims": list}``),
    routes through :func:`extract_claims_from_json` — zero LLM call,
    schema validation only. The dropped claim list returned by that
    function is surfaced as the 4th tuple element.
    """
    warnings: list[str] = []
    dropped: list[DroppedClaim] = []
    if not text.strip():
        return [], 0, warnings, dropped

    extractor_mode = os.environ.get("METAGENT_VERIFIER_EXTRACTOR", "llm").lower()
    try:
        # Phase B1 D2: auto-detect v2 grammar JSON payload regardless of mode.
        # extract_claims_from_json raises ClaimExtractionError when the
        # payload is not a v2 object — we then fall back to the configured
        # extractor (LLM or rule-based) for v1 narrative shapes.
        try:
            extracted, dropped = extract_claims_from_json(
                text, trace_id=f"{trace_id}.extract"
            )
            extract_calls = 0
        except ClaimExtractionError:
            if extractor_mode == "rule-based":
                extracted = extract_claims_rulebased(text, trace_id=f"{trace_id}.extract")
                extract_calls = 0
            else:
                extracted = extract_claims(text, trace_id=f"{trace_id}.extract")
                extract_calls = 1
    except ClaimExtractionError as exc:
        warnings.append(f"VERIFICATION_PARSE_FAILED at stage1: {exc}")
        return None, 1, warnings, dropped

    classified, classify_calls = classify_claims(
        extracted, trace_id=f"{trace_id}.classify"
    )
    return classified, extract_calls + classify_calls, warnings, dropped


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
        # Phase B1 D4 — log when a v2-grammar claim arrives with an
        # unexpected v1 type (smoke stop condition).
        _maybe_warn_v1_legacy_in_v2_path(c, where="spectrum")
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
        elif c.claim_type == ClaimType.OTHER:
            # Phase B1 D3 — abstract single-compound regulatory
            # statements (Polyamines regulate protein synthesis, etc.)
            # are routed here instead of being silently absorbed by
            # BIOLOGICAL. Honest verdict is UNVERIFIABLE_V0; Stage 4
            # rewriter will not try to "fix" them.
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
                        "Claim classified as OTHER (abstract single-"
                        "compound regulation / mechanism with no specific "
                        "pathway or enzyme endpoint). v1 used to absorb "
                        "these into BIOLOGICAL; B1 D3 keeps them "
                        "explicitly unverifiable to avoid misleading "
                        "UNSUPPORTED verdicts."
                    ),
                    extracted_fields=c.extracted_fields,
                    verifier_layer="other_fallback",
                    trace_summary="OTHER claim — no verifier route",
                )
            )
        else:  # pragma: no cover — exhaustive
            raise AssertionError(f"unhandled claim_type {c.claim_type}")
    return _stamp_grammar_from_classified(out, classified)


def _iteration_from_trace_id(trace_id: str) -> int | None:
    match = re.search(r"\.iter(\d+)(?:\.|$)", trace_id)
    if match is None:
        return None
    return int(match.group(1))


def _classified_with_trace_id(claim: ClassifiedClaim, claim_index: int) -> ClassifiedClaim:
    if claim.claim_id:
        return claim
    return claim.model_copy(update={"claim_id": f"claim-{claim_index}"})


def _stamp_grammar_from_classified(
    verified_claims: list[VerifiedClaim],
    classified_claims: list[ClassifiedClaim],
) -> list[VerifiedClaim]:
    """Phase B1 P0 Stage D — copy ``ClassifiedClaim.grammar`` onto each
    ``VerifiedClaim`` so per-grammar metric aggregation (e.g. distinguishing
    ``pathway_membership`` from ``metabolite_pathway_link`` — both collapse
    to ``ClaimType.BIOLOGICAL``) can read ``VerifiedClaim.grammar`` directly
    instead of round-tripping through ``ExtractedClaim``.

    Previously the per-layer verifier constructors set
    ``VerifiedClaim.grammar`` to its default ``None`` because layers don't
    receive the grammar information explicitly. This dispatcher-level stamp
    centralises the passthrough — no layer touched.

    1:1 with the classified list (each dispatch appends exactly one verified
    claim per classified claim). Was followup_debt P0 #1.
    """
    return [
        v if (c.grammar is None or v.grammar == c.grammar)
        else v.model_copy(update={"grammar": c.grammar})
        for v, c in zip(verified_claims, classified_claims, strict=True)
    ]


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
    dropped_claims: list[DroppedClaim] | None = None,
) -> VerifiedIdentification:
    # Phase A2 D1: synthesise stable claim_ids and populate feedback_hint
    # before serialising. The build_claim_table helper still applies its
    # fallback id-synthesis but it now no-ops since claim_id is set.
    from verifier.feedback_hints import annotate_claims
    claims_v1 = annotate_claims(claims_v1, pass_id="v1")
    claims_v2 = annotate_claims(claims_v2, pass_id="v2")
    table_v1 = build_claim_table(claims_v1, pass_id="v1")
    table_v2 = build_claim_table(claims_v2, pass_id="v2")
    dropped = list(dropped_claims or [])
    metrics = compute_claim_metrics(
        claims_v1=claims_v1,
        claims_v2=claims_v2,
        dropped_by_grammar=len(dropped),
    )
    # Phase B1 D4: bucket the run for D5 aggregation.
    outcome = detect_task_outcome(
        llm_output=llm_output,
        verified_claims=claims_v2 or claims_v1,
        dropped_claims=dropped,
    )
    return VerifiedIdentification(
        trace_id=trace_id,
        source_llm_output=llm_output,
        rewritten_output=rewritten_output,
        claims_v1=claims_v1,
        claims_v2=claims_v2,
        claim_tables=[table_v1, table_v2],
        claim_metrics=metrics,
        dropped_claims=dropped,
        task_outcome=outcome,
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
    dropped_claims: list[DroppedClaim] | None = None,
) -> VerifiedIdentification:
    table_v1 = build_claim_table([], pass_id="v1")
    table_v2 = build_claim_table([], pass_id="v2")
    dropped = list(dropped_claims or [])
    metrics = compute_claim_metrics(
        claims_v1=[], claims_v2=[],
        dropped_by_grammar=len(dropped),
    )
    # Phase B1 D4: even on the failed path the outcome detector runs;
    # it disambiguates "extractor parse failed" (system) vs "extractor
    # got [] honest-refusal narrative".
    outcome = detect_task_outcome(
        llm_output=llm_output,
        verified_claims=[],
        dropped_claims=dropped,
    )
    return VerifiedIdentification(
        trace_id=trace_id,
        source_llm_output=llm_output,
        rewritten_output=llm_output,
        claims_v1=[],
        claims_v2=[],
        claim_tables=[table_v1, table_v2],
        claim_metrics=metrics,
        dropped_claims=dropped,
        task_outcome=outcome,
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
    is_final_iteration: bool = True,
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

    classified, calls, w, dropped = _extract_classify(
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
            dropped_claims=dropped,
        )

    verified = _verify_per_claim_sub6(
        classified,
        source_report,
        ramp_db_path=ramp_db_path,
        ramp_conn=ramp_conn,
        driver_lookup=driver_lookup,
        is_final_iteration=is_final_iteration,
        iteration=_iteration_from_trace_id(trace_id),
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
        dropped_claims=dropped,
    )


def _verify_per_claim_sub6(
    classified: list[ClassifiedClaim],
    source_report: SubsixSourceReport,
    *,
    ramp_db_path: str | None,
    ramp_conn,
    driver_lookup: dict[str, str] | None,
    is_final_iteration: bool = True,
    iteration: int | None = None,
) -> list[VerifiedClaim]:
    """Dispatch each Sub-6 claim to its layer.

    Lazy-imports the four enrichment layers so import-time cost stays low
    when the verify() spectrum entry point is the only one being used.
    """
    from verifier.layers.biological_sub6 import verify_biological_sub6
    from verifier.layers.driver_metabolite import verify_driver_metabolite
    from verifier.layers.factual_sub6 import verify_factual_sub6
    from verifier.helpers.judge_cost_cap import get_run_level_tracker
    from verifier.layers.llm_judge_sub6 import verify_llm_judge_sub6 as _verify_llm_judge_sub6_default
    from verifier.layers.pathway_relationship import verify_pathway_relationship
    from verifier.layers.set_enrichment import verify_set_enrichment

    out: list[VerifiedClaim] = []
    judge_cost_tracker = get_run_level_tracker()
    for claim_index, c in enumerate(classified):
        c_for_trace = _classified_with_trace_id(c, claim_index)
        # Phase B1 D4 — log when a v2-grammar claim arrives with an
        # unexpected v1 type (smoke stop condition).
        _maybe_warn_v1_legacy_in_v2_path(c_for_trace, where="sub6")
        verified_claim: VerifiedClaim
        if c_for_trace.claim_type == ClaimType.SET_ENRICHMENT:
            verified_claim = verify_set_enrichment(c_for_trace, source_report)
        elif c_for_trace.claim_type in (ClaimType.FACTUAL, ClaimType.GROUNDED):
            # W12 C7 — route metabolite-ID claims to the Sub-6 friendly
            # factual_sub6 layer. The original fall-through path below
            # produces an informationally empty UV because B1 D2's
            # Layer A / Layer B require IdentificationReport-shaped
            # candidate pools, which SubsixSourceReport does not provide.
            verified_claim = verify_factual_sub6(c_for_trace, source_report)
        elif c_for_trace.claim_type == ClaimType.DRIVER_METABOLITE:
            verified_claim = (
                verify_driver_metabolite(
                    c_for_trace, source_report, lookup=driver_lookup,
                )
            )
        elif c_for_trace.claim_type == ClaimType.PATHWAY_RELATIONSHIP:
            verified_claim = (
                verify_pathway_relationship(
                    c_for_trace, source_report,
                    db_path=ramp_db_path, conn=ramp_conn,
                )
            )
        elif c_for_trace.claim_type == ClaimType.BIOLOGICAL:
            verified_claim = (
                verify_biological_sub6(
                    c_for_trace, source_report,
                    db_path=ramp_db_path, conn=ramp_conn,
                )
            )
        elif c_for_trace.claim_type == ClaimType.PEAK_MECHANISTIC:
            # Phase 6.3: Layer F dispatch for Sub-6A real-id narratives.
            # SubsixSourceReport now exposes experimental_spectrum/candidates
            # adapters (schemas/sub6_report.py) so Layer F can run without
            # changes. The first differential_spectra row is used as the
            # spectrum proxy — see Phase 6.3 report §10 for the
            # per-claim-spectrum-routing future-work caveat.
            verified_claim = layer_f.verify_peak_mechanistic(c_for_trace, source_report)
        else:
            # Spectrum-centric layers cannot consume SubsixSourceReport;
            # surface as UNVERIFIABLE_V0 with explicit reasoning. Phase
            # B1 D4 keeps this v1-legacy fallback alive but
            # ``_maybe_warn_v1_legacy_in_v2_path`` above logs whenever a
            # v2 claim lands here so the ablation can audit drift.
            verified_claim = VerifiedClaim(
                claim_id=c_for_trace.claim_id,
                claim_text=c_for_trace.claim_text,
                claim_type=c_for_trace.claim_type,
                claim_subtype=c_for_trace.claim_subtype,
                subject=c_for_trace.subject,
                subject_kind=c_for_trace.subject_kind,
                candidate_ref=c_for_trace.candidate_ref,
                verdict=ClaimVerdict.UNVERIFIABLE_V0,
                evidence=(
                    f"Sub-6 verifier does not support claim_type "
                    f"{c_for_trace.claim_type.value!r}: existing layer requires "
                    "IdentificationReport (spectrum-centric), but "
                    "Sub-6 supplies SubsixSourceReport. Treated as "
                    "declared limitation."
                ),
                extracted_fields=c_for_trace.extracted_fields,
                verifier_layer="verify_sub6",
                trace_summary=f"sub6 cannot verify {c_for_trace.claim_type.value}",
            )
        # [W16-ROLLBACK 2026-06-08] signal_sub6 catch-all disabled pending W18 beta
        # rebuild with source-aware conservative behavior. See:
        #   reports/agent/w16_signal_sub6_d4_diagnostic.md
        #   feedback_multi_paradigm_data_carrier_audit
        # Re-enable only after signal_sub6 honors method/source compatibility.
        # if (
        #     c.claim_type in (ClaimType.FACTUAL, ClaimType.GROUNDED, ClaimType.OTHER)
        #     and verified_claim.verdict == ClaimVerdict.UNVERIFIABLE_V0
        # ):
        #     signal_claim = verify_signal_sub6(c, source_report)
        #     if signal_claim.verdict != ClaimVerdict.UNVERIFIABLE_V0:
        #         verified_claim = signal_claim
        # [verifier-modify-warning] W18 D3: post-UV LLM-judge route.
        if is_final_iteration and verified_claim.verdict == ClaimVerdict.UNVERIFIABLE_V0:
            judge_func = globals().get("verify_llm_judge_sub6")
            if judge_func is None and os.environ.get("METAGENT_ENABLE_LLM_JUDGE_SUB6") == "1":
                judge_func = _verify_llm_judge_sub6_default
            if judge_func is not None:
                judge_claim = judge_func(
                    c_for_trace,
                    source_report,
                    cost_tracker=judge_cost_tracker,
                    iteration=iteration,
                )
                if judge_claim.verdict != ClaimVerdict.UNVERIFIABLE_V0:
                    verified_claim = judge_claim
        out.append(verified_claim)
    return _stamp_grammar_from_classified(out, classified)

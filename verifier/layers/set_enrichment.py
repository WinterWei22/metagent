"""Layer 6a — verify Type ``SET_ENRICHMENT`` claims.

A SET_ENRICHMENT claim asserts that a group of metabolites is enriched in
some pathway (e.g. "These metabolites are enriched in Tyrosine metabolism").

## Verification architecture (multisource refactor — 2026-06-25)

See design doc: ``docs/decisions/2026-06-25_verifier_multisource_refactor.md``

``verify_set_enrichment`` uses a **two-pass** design:

**Pass 1 — Multisource pool (UNCONDITIONAL):**
  The multisource pool pass runs *unconditionally*, regardless of the
  ``METAGENT_ENABLE_METHOD_AWARE_ENRICHMENT`` flag. It builds a merged pool
  from all 5 enrichment carriers (RaMP, Mummichog, MetaboAnalystR, SSPA, FELLA)
  but queries only the **non-RaMP** paradigms. A claim hitting ANY non-RaMP
  paradigm's pathways is returned as SUPPORTED immediately (non-RaMP paradigms
  do not expose a comparable top-K rank contract, so any pool hit is SUPPORTED).
  This intentionally supersedes W22's "flag-off → single-source RaMP only"
  semantics — the multisource pool is now the unconditional evidence base for
  non-RaMP paradigms.

**Pass 2 — RaMP ranked path (rank-aware):**
  If the multisource pool returns no hit, the function falls through to the
  existing RaMP-based ranked logic:
  - Match in ``top_pathways[:3]``  → ``SUPPORTED``
  - Match in ``top_pathways[3:10]`` → ``UNSUPPORTED`` (weak evidence)
  - No match in ``top_pathways[:10]`` → ``CONTRADICTED``
  - Pathway phrase / ID could not be lifted from claim → ``UNVERIFIABLE_V0``
  - ``ramp_enrichment_result`` missing or empty → ``UNVERIFIABLE_V0``

**Flag-controlled method-aware pre-pass (optional):**
  When ``METAGENT_ENABLE_METHOD_AWARE_ENRICHMENT=1``, a method-aware pre-pass
  runs *before* the pool pass. It detects a method from claim TEXT (e.g. the
  word "mummichog" in claim_text) and routes the claim to a method-specific
  verifier if a method is detected.
  Priority order: method_aware (text-mention) → multisource pool → RaMP ranked.
  NOTE: The two paths are NOT orthogonal — if the flag is ON and the claim
  text mentions a specific method (e.g. "mummichog"), method_aware_enrichment
  handles it first and the pool pass is bypassed for that claim. If the flag is
  OFF or no method is detected in the text, the pool pass runs unconditionally.

Pathway matching (within each pass):

1. Pathway IDs (e.g. ``map00350``, ``RAMP_P_000000106``, ``WP430``) are
   matched first via ``pathway_ids_equivalent``.
2. Pathway names fall back to semantic/fuzzy match (exact → substring →
   token-Jaccard). This is the same convention as Layer C and the eval
   guide §3 pitfall 3.
"""
from __future__ import annotations

import re
import os
from typing import Any

from schemas.sub6_report import SubsixSourceReport
from verifier.schemas import (
    ClaimSubtype,
    ClaimType,
    ClaimVerdict,
    ClassifiedClaim,
    EnrichmentContext,
    PathwayMatch,
    VerifiedClaim,
)


_TOP_K_SUPPORTED = 3
_TOP_K_TOLERATED = 10

# RaMP pathway IDs look like RAMP_P_000000106; KEGG mapXXXXX; WikiPathways
# WPNNNN; Reactome R-HSA-NNNN; SMPDB SMPNNNN. Be generous — we just need
# to spot one to short-circuit the fuzzy phrase path.
_PATHWAY_ID_RE = re.compile(
    r"\b("
    r"RAMP_P_\d+"
    r"|map\d{5}"
    r"|hsa\d{5}"
    r"|R-HSA-\d+"
    r"|SMP\d+"
    r"|WP\d+"
    r")\b",
    re.IGNORECASE,
)

# Re-uses the phrase regex from Layer C with the addition of a few extra
# enrichment idioms we expect from Sub-6 narratives.
_PATHWAY_PHRASE_RE = re.compile(
    r"\b("
    r"[A-Za-z][A-Za-z0-9-]*(?:\s+[A-Za-z][A-Za-z0-9-]*){0,5}\s+"
    r"(?:metabolism|biosynthesis|degradation|catabolism|anabolism|"
    r"synthesis|disease|syndrome|cycle|oxidations?|signal[l]?ing|"
    r"transduction|disorder|inhibition|production|pathways?)"
    r")\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def verify_set_enrichment(
    claim: ClassifiedClaim,
    source_report: SubsixSourceReport,
) -> VerifiedClaim:
    """Verify one SET_ENRICHMENT claim against the task's enrichment result."""
    if os.environ.get("METAGENT_ENABLE_METHOD_AWARE_ENRICHMENT") == "1":
        from verifier.helpers.method_aware_enrichment import verify_method_aware_enrichment

        method_aware = verify_method_aware_enrichment(claim, source_report)
        if method_aware is not None:
            return method_aware

    # --- Multisource pool: try non-RaMP paradigms first ---
    # Extract pathway identifiers from claim so they're available for both
    # the pool pass and the downstream RaMP-based ranked pass.
    pathway_id, pathway_name = _extract_pathway_from_claim(claim)
    pool_hit = _try_multisource_pool(claim, source_report, pathway_id, pathway_name)
    if pool_hit is not None:
        return pool_hit

    top_pathways = _extract_top_pathways(source_report)
    if not top_pathways:
        return _unverifiable(
            claim,
            evidence=(
                "ramp_enrichment_result.top_pathways is empty or missing; "
                "no enrichment ground truth to compare against."
            ),
            ctx=EnrichmentContext(),
        )

    # Echo top-3 into context regardless of match outcome — auditors want
    # to see what was being compared against.
    matched_top = [
        _pathway_match_from_dict(p, rank=i + 1)
        for i, p in enumerate(top_pathways[:_TOP_K_SUPPORTED])
    ]

    # ID match wins.
    if pathway_id:
        for i, p in enumerate(top_pathways[:_TOP_K_TOLERATED]):
            if _id_match(pathway_id, p):
                return _verdict_for_rank(
                    claim,
                    matched=p,
                    rank=i + 1,
                    method="id",
                    matched_top=matched_top,
                    pathway_id=pathway_id,
                    pathway_name=pathway_name,
                )

    # Forward fuzzy match: the regex-lifted phrase against canonical names.
    if pathway_name:
        norm_claim = _normalise(pathway_name)
        for i, p in enumerate(top_pathways[:_TOP_K_TOLERATED]):
            canon = _normalise(p.get("pathway_name") or "")
            if not canon:
                continue
            if canon == norm_claim:
                return _verdict_for_rank(
                    claim,
                    matched=p,
                    rank=i + 1,
                    method="exact",
                    matched_top=matched_top,
                    pathway_id=pathway_id,
                    pathway_name=pathway_name,
                )
            if norm_claim in canon or canon in norm_claim:
                return _verdict_for_rank(
                    claim,
                    matched=p,
                    rank=i + 1,
                    method="substring_either",
                    matched_top=matched_top,
                    pathway_id=pathway_id,
                    pathway_name=pathway_name,
                )

    # Reverse fuzzy match: canonical name appears verbatim in claim text.
    # Catches naked pathway names that the phrase regex misses
    # (e.g. "Alkaptonuria", "Phenylketonuria") by trusting that the
    # ground-truth top_pathways entries are themselves a closed
    # vocabulary for this task.
    norm_text = _normalise(claim.claim_text)
    for i, p in enumerate(top_pathways[:_TOP_K_TOLERATED]):
        canon = _normalise(p.get("pathway_name") or "")
        if not canon or len(canon) < 5:
            # Skip very short canonical names — too risky for substring fuzz
            # (e.g. a 3-letter pathway name would match almost any claim).
            continue
        if canon in norm_text:
            return _verdict_for_rank(
                claim,
                matched=p,
                rank=i + 1,
                method="substring_either",
                matched_top=matched_top,
                pathway_id=pathway_id,
                pathway_name=pathway_name or p.get("pathway_name"),
            )

    # W12 C7 Stage 2.5: token-Jaccard fuzzy on content tokens (post
    # stop-word strip). Catches "Arachidonic acid eicosanoid biosynthesis"
    # ↔ "Arachidonic acid metabolism" (Jaccard 2/3 ≈ 0.67) which the
    # substring sweep misses because neither is a substring of the other.
    # Threshold 0.5 matches the Concord W6 default. Operates on the
    # claim's lifted pathway_name only (not the raw claim_text) to keep
    # false-positive risk low.
    if pathway_name:
        from verifier.helpers.fuzzy_match import token_jaccard
        for i, p in enumerate(top_pathways[:_TOP_K_TOLERATED]):
            canon_name = p.get("pathway_name") or ""
            if not canon_name:
                continue
            score = token_jaccard(pathway_name, canon_name)
            if score >= 0.5:
                # Reuse 'substring_either' method label (existing Literal
                # value on EnrichmentContext.pathway_match_method) — the
                # token-Jaccard pass is conceptually a generalised fuzzy
                # match. Trace summary distinguishes the two via the
                # explicit score it carries.
                return _verdict_for_rank(
                    claim,
                    matched=p,
                    rank=i + 1,
                    method="substring_either",
                    matched_top=matched_top,
                    pathway_id=pathway_id,
                    pathway_name=pathway_name,
                )

    if not pathway_id and not pathway_name:
        return _unverifiable(
            claim,
            evidence=(
                "Layer 6a found no pathway ID or name in the claim, and no "
                "top_pathways canonical name appears verbatim in the claim "
                "text. Cannot map to a verdict."
            ),
            ctx=EnrichmentContext(matched_top_pathways=matched_top),
        )

    # No match in top-10 → CONTRADICTED.
    canonical_top1 = top_pathways[0].get("pathway_name")
    return VerifiedClaim(
        claim_id=claim.claim_id,
        claim_text=claim.claim_text,
        claim_type=ClaimType.SET_ENRICHMENT,
        claim_subtype=claim.claim_subtype if claim.claim_subtype != ClaimSubtype.UNKNOWN else ClaimSubtype.ENRICHMENT_PATHWAY,
        subject=claim.subject,
        subject_kind=claim.subject_kind,
        candidate_ref=claim.candidate_ref,
        verdict=ClaimVerdict.CONTRADICTED,
        evidence=(
            f"Claimed pathway {(pathway_name or pathway_id)!r} is not in "
            f"top_pathways[:{_TOP_K_TOLERATED}]; ground-truth top-1 is "
            f"{canonical_top1!r}."
        ),
        correction=canonical_top1,
        extracted_fields=claim.extracted_fields,
        verifier_layer="set_enrichment",
        tool_called="ramp_enrichment_result",
        trace_summary=(
            f"claim pathway {(pathway_name or pathway_id)!r} absent from top-{_TOP_K_TOLERATED}"
        ),
        enrichment_context=EnrichmentContext(
            claimed_pathway=pathway_name,
            claimed_pathway_id=pathway_id,
            matched_top_pathways=matched_top,
            best_match=None,
            pathway_match_method="none",
        ),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _try_multisource_pool(
    claim: ClassifiedClaim,
    source_report: SubsixSourceReport,
    pathway_id: str | None,
    pathway_name: str | None,
) -> VerifiedClaim | None:
    """Try matching the claimed pathway against the non-RaMP multisource pool.

    Returns a SUPPORTED VerifiedClaim if the pathway is found in any non-RaMP
    paradigm (mummichog, metaboanalystr, sspa, fella). Returns None if no
    non-RaMP match is found, allowing the caller to fall through to the
    existing RaMP-based ranked logic.

    RaMP rows are excluded here: they are handled by the rank-aware path below,
    which distinguishes SUPPORTED (top-3) from UNSUPPORTED (rank 4-10) and
    CONTRADICTED (outside top-10). Non-RaMP paradigms do not expose a
    comparable rank contract, so any hit is SUPPORTED.

    Even on a pool hit, the RaMP top-3 pathways are echoed into
    ``matched_top_pathways`` so auditors have comparison context.
    """
    if not pathway_id and not pathway_name:
        return None

    from verifier.helpers.multisource_enrichment import build_pathway_pool, match_in_pool

    pool = build_pathway_pool(source_report)
    # Exclude RaMP rows — those are verified by the rank-aware path.
    non_ramp_pool = [row for row in pool if row.get("_paradigm") != "ramp"]
    if not non_ramp_pool:
        return None

    matched_row = match_in_pool(non_ramp_pool, pathway_id, pathway_name)
    if matched_row is None:
        return None

    paradigm = matched_row.get("_paradigm", "unknown")
    matched_name = matched_row.get("pathway_name") or matched_row.get("pathway_id_native") or ""
    matched_pid = matched_row.get("pathway_id") or matched_row.get("pathway_id_native") or ""

    # Finding 3: Determine actual match basis from the matched row's IDs
    # rather than just checking if claim had a pathway_id and matched row has
    # a pathway_id. The match could have been via name even when both IDs exist.
    matched_row_ids = {
        (matched_row.get("pathway_id") or "").strip().lower(),
        (matched_row.get("pathway_id_native") or "").strip().lower(),
        (matched_row.get("pathway_external_id") or "").strip().lower(),
    }
    matched_row_ids.discard("")
    claimed_id_norm = (pathway_id or "").strip().lower()
    # Label "id" only when the claim's pathway_id actually appears in the
    # matched row's ID fields; otherwise the match was name/semantic-based.
    if claimed_id_norm and claimed_id_norm in matched_row_ids:
        match_method: str = "id"
    else:
        match_method = "substring_either"

    # Finding 4: Echo RaMP top-3 into matched_top_pathways for auditor context,
    # even when the hit came from a non-RaMP pool entry.
    top_pathways = _extract_top_pathways(source_report)
    ramp_top3: list[PathwayMatch] = [
        _pathway_match_from_dict(p, rank=i + 1)
        for i, p in enumerate(top_pathways[:_TOP_K_SUPPORTED])
    ]

    return VerifiedClaim(
        claim_id=claim.claim_id,
        claim_text=claim.claim_text,
        claim_type=ClaimType.SET_ENRICHMENT,
        claim_subtype=ClaimSubtype.ENRICHMENT_PATHWAY,
        subject=claim.subject,
        subject_kind=claim.subject_kind,
        candidate_ref=claim.candidate_ref,
        verdict=ClaimVerdict.SUPPORTED,
        evidence=(
            f"Claimed pathway {(pathway_name or pathway_id)!r} matched in "
            f"{paradigm} enrichment pool "
            f"(pathway={matched_name!r}, id={matched_pid!r})."
        ),
        extracted_fields=claim.extracted_fields,
        verifier_layer="set_enrichment",
        tool_called=f"{paradigm}_enrichment_result",
        trace_summary=f"multisource pool hit via {paradigm}",
        enrichment_context=EnrichmentContext(
            claimed_pathway=pathway_name,
            claimed_pathway_id=pathway_id,
            matched_top_pathways=ramp_top3,
            best_match=PathwayMatch(
                pathway_id=matched_pid or None,
                pathway_name=matched_name or None,
                pathway_source=matched_row.get("pathway_source"),
                pathway_external_id=matched_row.get("pathway_external_id"),
                rank=None,
            ),
            pathway_match_method=match_method,  # type: ignore[arg-type]
        ),
    )


def _extract_top_pathways(report: SubsixSourceReport) -> list[dict[str, Any]]:
    result = report.ramp_enrichment_result or {}
    top = result.get("top_pathways") or []
    return [p for p in top if isinstance(p, dict)]


def _extract_pathway_from_claim(
    claim: ClassifiedClaim,
) -> tuple[str | None, str | None]:
    """Return (pathway_id, pathway_name) lifted from typed fields or text.

    Typed fields win when populated by the extractor. Otherwise we regex
    over the claim text.
    """
    typed_id = claim.extracted_fields.pathway_id
    typed_name = claim.extracted_fields.pathway_name

    pathway_id = typed_id or None
    pathway_name = typed_name or None

    if not pathway_id:
        m = _PATHWAY_ID_RE.search(claim.claim_text)
        if m:
            pathway_id = m.group(1)

    if not pathway_name:
        m = _PATHWAY_PHRASE_RE.search(claim.claim_text)
        if m:
            pathway_name = m.group(0).strip()

    return pathway_id, pathway_name


def _normalise(s: str) -> str:
    return " ".join((s or "").lower().split())


def _id_match(claimed: str, p: dict[str, Any]) -> bool:
    cl = (claimed or "").strip().lower()
    if not cl:
        return False
    for key in ("pathway_id", "pathway_external_id"):
        v = (p.get(key) or "").strip().lower()
        if v and v == cl:
            return True
    return False


def _pathway_match_from_dict(p: dict[str, Any], rank: int) -> PathwayMatch:
    return PathwayMatch(
        pathway_id=p.get("pathway_id"),
        pathway_name=p.get("pathway_name"),
        pathway_source=p.get("pathway_source"),
        pathway_external_id=p.get("pathway_external_id"),
        rank=rank,
        fdr=p.get("fdr"),
        p_value=p.get("p_value"),
        fold_enrichment=p.get("fold_enrichment"),
        matched_compounds=list(p.get("matched_compounds") or []),
        total_pathway_compounds=p.get("total_pathway_compounds"),
    )


def _verdict_for_rank(
    claim: ClassifiedClaim,
    *,
    matched: dict[str, Any],
    rank: int,
    method: str,
    matched_top: list[PathwayMatch],
    pathway_id: str | None,
    pathway_name: str | None,
) -> VerifiedClaim:
    best = _pathway_match_from_dict(matched, rank=rank)
    ctx = EnrichmentContext(
        claimed_pathway=pathway_name,
        claimed_pathway_id=pathway_id,
        matched_top_pathways=matched_top,
        best_match=best,
        pathway_match_method=method,  # type: ignore[arg-type]
    )

    # SUPPORTED vs UNSUPPORTED based on rank.
    if rank <= _TOP_K_SUPPORTED:
        return VerifiedClaim(
            claim_id=claim.claim_id,
            claim_text=claim.claim_text,
            claim_type=ClaimType.SET_ENRICHMENT,
            claim_subtype=ClaimSubtype.ENRICHMENT_PATHWAY,
            subject=claim.subject,
            subject_kind=claim.subject_kind,
            candidate_ref=claim.candidate_ref,
            verdict=ClaimVerdict.SUPPORTED,
            evidence=(
                f"Claimed pathway matches top_pathways[{rank - 1}] "
                f"({matched.get('pathway_name')!r}) by {method}; "
                f"FDR={matched.get('fdr')}."
            ),
            extracted_fields=claim.extracted_fields,
            verifier_layer="set_enrichment",
            tool_called="ramp_enrichment_result",
            trace_summary=f"top-{rank} match via {method}",
            enrichment_context=ctx,
        )

    # rank in 4..10 → UNSUPPORTED (weak evidence)
    return VerifiedClaim(
        claim_id=claim.claim_id,
        claim_text=claim.claim_text,
        claim_type=ClaimType.SET_ENRICHMENT,
        claim_subtype=ClaimSubtype.ENRICHMENT_PATHWAY,
        subject=claim.subject,
        subject_kind=claim.subject_kind,
        candidate_ref=claim.candidate_ref,
        verdict=ClaimVerdict.UNSUPPORTED,
        evidence=(
            f"Claimed pathway matches top_pathways[{rank - 1}] but rank "
            f"{rank} is outside the top-{_TOP_K_SUPPORTED} acceptance set "
            f"used by Sub-6 grading. Match method: {method}."
        ),
        extracted_fields=claim.extracted_fields,
        verifier_layer="set_enrichment",
        tool_called="ramp_enrichment_result",
        trace_summary=f"top-{rank} match (outside top-{_TOP_K_SUPPORTED})",
        enrichment_context=ctx,
    )


def _unverifiable(
    claim: ClassifiedClaim,
    *,
    evidence: str,
    ctx: EnrichmentContext,
) -> VerifiedClaim:
    return VerifiedClaim(
        claim_id=claim.claim_id,
        claim_text=claim.claim_text,
        claim_type=ClaimType.SET_ENRICHMENT,
        claim_subtype=claim.claim_subtype,
        subject=claim.subject,
        subject_kind=claim.subject_kind,
        candidate_ref=claim.candidate_ref,
        verdict=ClaimVerdict.UNVERIFIABLE_V0,
        evidence=evidence,
        extracted_fields=claim.extracted_fields,
        verifier_layer="set_enrichment",
        trace_summary="set_enrichment unverifiable",
        enrichment_context=ctx,
    )

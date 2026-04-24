"""Schemas for the Track V verifier.

Every type here is consumed by the verifier cascade
(``claim_extractor`` → ``claim_classifier`` → ``layers/*`` → ``rewriter``)
and by the public ``verify()`` entry point in ``agent.py``.

Design notes
------------

* **Independence from ``orchestrator/``.** No type here imports from the
  orchestrator package. ``VerifiedIdentification`` carries the original LLM
  output verbatim (``source_llm_output``), so a caller does not need to keep
  the ``NaiveIdentification`` around to reconstruct provenance.

* **Verbatim source preservation.** ``source_llm_output`` is never mutated.
  All Stage-4 corrections land in ``rewritten_output``. The audit trail
  depends on this distinction — ``source_llm_output`` is what the model
  actually said; ``rewritten_output`` is what survived verification (which
  may include corrections the model never wrote).

* **Two-pass claim record.** ``claims_v1`` are the claims extracted from
  ``source_llm_output``; ``claims_v2`` are the claims extracted from
  ``rewritten_output`` after Stage 4. When Stage 4 did not run (no v1
  claim was contradicted/unsupported), ``claims_v2 == claims_v1`` and
  ``rewritten_output == source_llm_output``.

* **Verdicts are routable, not free-text.** ``ClaimVerdict.UNVERIFIABLE_V0``
  marks claims the verifier cannot judge with current backends (e.g.
  pathway-neighbour claims blocked by the D/E P-2/3/4/6 bugs). It is a
  declared limitation, not a judgement.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ClaimType(str, Enum):
    """How a claim is verified.

    Each type maps 1:1 to a layer under ``verifier/layers/``. The classifier
    (Stage 2) is responsible for assigning exactly one type per claim;
    multi-type claims are split during extraction.
    """

    GROUNDED = "grounded_claim"
    """Type 1 — verified by lookup in ``source_report``. No tool call."""

    FACTUAL = "factual_roundtrip_claim"
    """Type 2 — verified by re-querying ``fetch_metabolite_info`` and
    comparing fields. Tolerates name/synonym drift via canonical
    SMILES / InChIKey."""

    BIOLOGICAL = "biological_claim"
    """Type 3 — verified by re-querying ``pathway_context`` for membership.
    Claims depending on neighbours / cooccurrence are marked
    ``UNVERIFIABLE_V0`` pending P-2/3/4/6."""

    CONSISTENCY = "consistency_claim"
    """Type 4 — verified by LLM reasoning across the full claim set.
    Catches intra-document contradictions (e.g. H1: header formula vs.
    body formula for the same molecule)."""

    LITERATURE = "literature_claim"
    """Type 5 — verified by PMID / DOI round-trip against Europe PMC, or
    source-first lookup in ``candidate.literature_records``. Catches
    hallucinated citations (an LLM-named PMID that does not resolve, or
    one that does not match the title / journal asserted alongside it)."""


class ClaimVerdict(str, Enum):
    """The outcome of running a claim through its layer.

    ``UNVERIFIABLE_V0`` and ``ERROR`` are deliberately distinct:
    ``UNVERIFIABLE_V0`` is a declared limitation of the v0 backends;
    ``ERROR`` is an unexpected failure (e.g. tool raised, JSON parse failed).
    """

    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    UNSUPPORTED = "unsupported"
    UNVERIFIABLE_V0 = "unverifiable_v0"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Per-claim record
# ---------------------------------------------------------------------------


class ExtractedClaim(BaseModel):
    """A claim emitted by Stage 1 (extractor) before classification.

    The extractor's only job is to surface atomic, decontextualised
    factual statements. It does not assign ``claim_type`` — that is
    Stage 2's responsibility.
    """

    model_config = ConfigDict(frozen=True)

    claim_text: str = Field(
        ...,
        description=(
            "The atomic, decontextualised factual statement, as a complete "
            "sentence that stands alone without surrounding paragraph context. "
            "Example: 'D-Gulose has molecular formula C7H14O7' — not just "
            "'C7H14O7'."
        ),
    )
    subject: str | None = Field(
        None,
        description=(
            "The named entity the claim is about, when one can be identified "
            "(e.g. 'D-Gulose', 'caffeine', 'map00232'). Used by the Stage 3 "
            "consistency layer to group claims about the same subject."
        ),
    )


class ClassifiedClaim(BaseModel):
    """A claim with a routable type assigned by Stage 2."""

    model_config = ConfigDict(frozen=True)

    claim_text: str = Field(..., description="See ``ExtractedClaim.claim_text``.")
    subject: str | None = Field(
        None, description="See ``ExtractedClaim.subject``."
    )
    claim_type: ClaimType = Field(
        ...,
        description=(
            "Determines which ``verifier/layers/`` module verifies this claim. "
            "Assigned by ``claim_classifier``: rule-based when the claim "
            "matches a known pattern, LLM-fallback otherwise."
        ),
    )
    classifier_source: Literal["rule", "llm", "fallback"] = Field(
        ...,
        description=(
            "Where the type came from. ``rule`` = deterministic pattern hit; "
            "``llm`` = Stage 2 fallback call; ``fallback`` = neither matched, "
            "default-routed to a layer (logged for analysis)."
        ),
    )


class VerifiedClaim(BaseModel):
    """A claim after its layer has run.

    ``evidence`` is human-readable and short — a one-liner explaining what
    was checked and how. ``correction`` is populated only when the verdict
    is ``CONTRADICTED`` and the layer can name the right value per the
    source of truth (e.g. for H1, ``correction='C6H12O6'``).
    """

    model_config = ConfigDict(frozen=True)

    claim_text: str = Field(..., description="The atomic statement, verbatim from extraction.")
    claim_type: ClaimType = Field(..., description="Which layer judged this claim.")
    verdict: ClaimVerdict = Field(..., description="The layer's verdict.")
    evidence: str = Field(
        ...,
        description=(
            "One-line description of what was checked and how. Examples: "
            "'source_report.candidates[0].metabolite_info.molecular_formula = "
            "C6H12O6, claim says C7H14O7'; 'fetch_metabolite_info(C07481) "
            "returned primary_name=Caffeine, claim names same compound'. "
            "Read by the rewriter to decide whether to drop or correct."
        ),
    )
    source_field: str | None = Field(
        None,
        description=(
            "When the verdict came from a ``source_report`` lookup (Layer A), "
            "the dotted/bracketed path to the field that was consulted. "
            "Example: 'candidates[0].metabolite_info.molecular_formula'. "
            "None for layers B/C/D, whose evidence is external or cross-claim."
        ),
    )
    correction: str | None = Field(
        None,
        description=(
            "For CONTRADICTED claims, the correct value per the ground "
            "truth the layer consulted. The rewriter substitutes this when "
            "regenerating the output. None for non-CONTRADICTED verdicts and "
            "for contradictions where no single 'correct' value can be named "
            "(e.g. an internally inconsistent narrative with no canonical fix)."
        ),
    )


# ---------------------------------------------------------------------------
# Top-level result
# ---------------------------------------------------------------------------


class VerifiedIdentification(BaseModel):
    """The verifier's full output. Joinable to the orchestrator's JSONL row
    by ``trace_id`` (convention: ``<orchestrator_trace_id>_verified``)."""

    model_config = ConfigDict(protected_namespaces=())

    trace_id: str = Field(
        ...,
        description=(
            "Identifier shared with the verifier's JSONL log lines. "
            "Convention: ``<orchestrator_trace_id>_verified`` — lets a "
            "downstream evaluator grep ``logs/llm_calls.jsonl`` for both "
            "halves of an identification."
        ),
    )
    source_llm_output: str = Field(
        ...,
        description=(
            "The ORIGINAL naive-orchestrator output, untouched. The audit "
            "trail depends on this being verbatim — even if Stage 4 corrected "
            "every claim, this field still contains the wrong-as-said text."
        ),
    )
    rewritten_output: str = Field(
        ...,
        description=(
            "Stage 4 output. Equals ``source_llm_output`` when no v1 claim "
            "was CONTRADICTED or UNSUPPORTED (no rewrite needed). May contain "
            "strings the model never wrote (e.g. corrected formulas) — that "
            "is intentional and is why ``source_llm_output`` is preserved "
            "separately."
        ),
    )
    claims_v1: list[VerifiedClaim] = Field(
        ...,
        description=(
            "Claims extracted from ``source_llm_output`` after Stage 3 "
            "verification. Empty list iff Stage 1 produced no claims (which "
            "itself should produce ``overall_verdict='failed'`` via the "
            "warnings)."
        ),
    )
    claims_v2: list[VerifiedClaim] = Field(
        ...,
        description=(
            "Claims extracted from ``rewritten_output`` after Stage 4 "
            "re-verification. Equals ``claims_v1`` when Stage 4 did not "
            "run. Layer D consistency IS re-fired on these — per maintainer "
            "decision, we do not assume the rewriter cannot introduce new "
            "contradictions."
        ),
    )
    overall_verdict: Literal[
        "verified",
        "partially_verified",
        "contradicted",
        "failed",
    ] = Field(
        ...,
        description=(
            "Aggregate over ``claims_v2``: "
            "``verified`` — every claim SUPPORTED; "
            "``partially_verified`` — some UNSUPPORTED or UNVERIFIABLE_V0, "
            "no CONTRADICTED; "
            "``contradicted`` — at least one CONTRADICTED claim survived "
            "into v2 (rewriter could not eliminate it); "
            "``failed`` — extraction or verification could not complete "
            "(see ``verification_warnings``)."
        ),
    )
    verification_warnings: list[str] = Field(
        default_factory=list,
        description=(
            "Per-stage failure notes. Examples: "
            "'VERIFICATION_PARSE_FAILED at stage1 — extractor returned "
            "non-JSON'; 'fetch_metabolite_info raised HmdbUnavailable at "
            "layer B for claim 3'. Empty list means the cascade ran clean."
        ),
    )
    llm_call_count: int = Field(
        ...,
        ge=0,
        description=(
            "Actual count of LLM calls this verification cost. Budget "
            "ceiling is 7 (extract-v1 / classify-v1 / consistency-v1 / "
            "rewrite / extract-v2 / classify-v2 / consistency-v2). Best "
            "case is 1 (all v1 claims SUPPORTED with no ambiguity, no "
            "Stage 4). The ceiling was bumped from 6 to 7 after the first "
            "live integration run hit Stage 2 LLM-fallback in BOTH v1 and "
            "v2 — the original budget table mistakenly counted Stage 2 "
            "only once."
        ),
    )
    generated_at: datetime = Field(
        ...,
        description="UTC timestamp at which ``verify()`` returned.",
    )

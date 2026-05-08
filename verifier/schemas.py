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
from typing import Any, Literal

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
    """Layer E — verified by PMID / DOI round-trip against Europe PMC, or
    source-first lookup in ``candidate.literature_records``. Catches
    hallucinated citations (an LLM-named PMID that does not resolve, or
    one that does not match the title / journal asserted alongside it)."""

    PEAK_MECHANISTIC = "peak_mechanistic_claim"
    """Type 5 — verified by peak existence plus SIRIUS fragmentation-tree
    annotation. Used for fragment / neutral-loss claims at a specific m/z."""

    SET_ENRICHMENT = "set_enrichment"
    """Type 6a (Sub-6) — claims of the form "these metabolites are enriched
    in pathway X". Verified by ``verifier/layers/set_enrichment.py`` against
    ``SubsixSourceReport.ramp_enrichment_result.top_pathways``."""

    DRIVER_METABOLITE = "driver_metabolite"
    """Type 6b (Sub-6) — claims of the form "compound X drives pathway Y".
    Verified by ``verifier/layers/driver_metabolite.py`` against
    ``SubsixSourceReport.ground_truth_signal_compounds`` /
    ``ground_truth_noise_compounds`` after KEGG↔InChIKey resolution."""

    PATHWAY_RELATIONSHIP = "pathway_relationship"
    """Type 6d (Sub-6) — claims of the form "pathway A is upstream of B" or
    "pathways A and B share intermediates". Verified by
    ``verifier/layers/pathway_relationship.py`` against RaMP's
    ``analytehaspathway`` table for shared compounds; upstream/downstream
    claims fall back to ``UNVERIFIABLE_V0`` because RaMP-DB has no
    pathway-hierarchy table.

    Note: Type 6c "biological significance" claims are routed to the
    existing ``BIOLOGICAL`` value at classification time (or, for
    Sub-6 source reports, to the dedicated Sub-6 biological subroute).
    No separate ClaimType is added for 6c — see Sub-6 verifier session
    decision Q1(b)."""


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
    NEEDS_HUMAN_REVIEW = "needs_human_review"
    """Tools-disagree escape hatch. Layer F cross-validation produces this
    verdict when SIRIUS and CFM-ID assign incompatible interpretations to a
    peak claim. Downstream code must treat it as a first-class verdict, not
    as an error or a filtered-out null."""


class ClaimSubtype(str, Enum):
    """More specific semantic shape within a broad ``ClaimType`` route."""

    UNKNOWN = "unknown"
    FORMULA = "formula"
    PRECURSOR_MZ = "precursor_mz"
    NEUTRAL_MASS = "neutral_mass"
    ADDUCT = "adduct"
    PEAK_COUNT = "peak_count"
    EVIDENCE_SCORE = "evidence_score"
    CANDIDATE_SCORE = "candidate_score"
    PREDICTED_COSINE = "predicted_cosine"
    MASS_MATCH = "mass_match"
    RANKING = "ranking"
    DATABASE_ID = "database_id"
    CHEMICAL_TAXONOMY = "chemical_taxonomy"
    NAME_IDENTITY = "name_identity"
    PATHWAY_MEMBERSHIP = "pathway_membership"
    PATHWAY_NEIGHBOUR = "pathway_neighbour"
    COOCCURRENCE = "cooccurrence"
    BIOLOGICAL_CONTEXT = "biological_context"
    LITERATURE_PMID = "literature_pmid"
    LITERATURE_DOI = "literature_doi"
    LITERATURE_FREE_TEXT = "literature_free_text"
    PEAK_EXISTENCE = "peak_existence"
    FRAGMENT_ASSIGNMENT = "fragment_assignment"
    NEUTRAL_LOSS = "neutral_loss"
    RING_CLEAVAGE = "ring_cleavage"
    # Sub-6 enrichment subtypes
    ENRICHMENT_PATHWAY = "enrichment_pathway"
    DRIVER_LIST = "driver_list"
    PATHWAY_UPSTREAM = "pathway_upstream"
    PATHWAY_DOWNSTREAM = "pathway_downstream"
    PATHWAY_CROSS_TALK = "pathway_cross_talk"
    PATHWAY_SHARED_INTERMEDIATES = "pathway_shared_intermediates"


class SubjectKind(str, Enum):
    """Coarse type for the entity named by ``subject``."""

    UNKNOWN = "unknown"
    CANDIDATE = "candidate"
    COMPOUND = "compound"
    PATHWAY = "pathway"
    DATABASE_ID = "database_id"
    SPECTRUM = "spectrum"
    PEAK = "peak"
    LITERATURE = "literature"
    CLASS = "class"


# ---------------------------------------------------------------------------
# Typed-claim support records
# ---------------------------------------------------------------------------


class ClaimExtractedFields(BaseModel):
    """Machine-readable fields parsed from a natural-language claim.

    ``extra='allow'`` lets future parsers add narrow fields without another
    migration while keeping the first-order fields typed for metrics/UI.
    """

    model_config = ConfigDict(extra="allow")

    mz: float | None = None
    mz_tolerance_ppm: float | None = None
    formula: str | None = None
    neutral_mass: float | None = None
    precursor_mz: float | None = None
    adduct: str | None = None
    neutral_loss: str | None = None
    fragment_formula: str | None = None
    smiles: str | None = None
    inchikey: str | None = None
    database_name: str | None = None
    database_id: str | None = None
    pathway_name: str | None = None
    pathway_id: str | None = None
    pmid: str | None = None
    doi: str | None = None
    score_name: str | None = None
    score_value: float | None = None
    rank: int | None = None
    candidate_name: str | None = None


class CandidateRef(BaseModel):
    """Stable-ish reference to a candidate in ``IdentificationReport``."""

    index: int | None = None
    path: str | None = None
    name: str | None = None
    smiles: str | None = None
    inchikey: str | None = None
    source_id: str | None = None
    match_method: str | None = None


class EvidenceRef(BaseModel):
    """Structured pointer to a field/tool result used as verification evidence."""

    source: str
    path: str | None = None
    value: str | float | int | bool | None = None
    summary: str | None = None


class PathwayMatch(BaseModel):
    """Structured echo of one ``ramp_enrichment_result.top_pathways[i]``.

    Populated by Layer 6a (``set_enrichment``) when a claimed pathway is
    matched against the enrichment result. Mirrors the keys returned by
    RaMP-DB's enrichment API so downstream consumers don't need to
    re-parse the dict.
    """

    pathway_id: str | None = None
    pathway_name: str | None = None
    pathway_source: str | None = None
    pathway_external_id: str | None = None
    rank: int | None = Field(
        None,
        ge=1,
        description="1-based position in ramp_enrichment_result.top_pathways.",
    )
    fdr: float | None = Field(None, ge=0.0)
    p_value: float | None = Field(None, ge=0.0)
    fold_enrichment: float | None = None
    matched_compounds: list[str] = Field(default_factory=list)
    total_pathway_compounds: int | None = Field(None, ge=0)


class EnrichmentContext(BaseModel):
    """Structured evidence carrier for Sub-6 enrichment-narrative verifier
    layers (``SET_ENRICHMENT``, ``DRIVER_METABOLITE``,
    ``PATHWAY_RELATIONSHIP``).

    All fields are optional; each Sub-6 layer populates the slice that
    matches its responsibility:

    * Layer 6a (set_enrichment) — ``claimed_pathway`` + ``matched_top_pathways``
      + ``best_match`` + ``pathway_match_method``.
    * Layer 6b (driver_metabolite) — ``claimed_drivers`` +
      ``matched_signal_drivers`` / ``matched_noise_drivers`` /
      ``unresolved_drivers`` + ``driver_precision`` / ``driver_recall``.
    * Layer 6d (pathway_relationship) — ``pathway_a`` / ``pathway_b`` +
      ``relationship_type`` + ``shared_compound_count`` / ``shared_compounds``.

    ``tool_evidence`` mirrors ``VerifiedClaim.tool_evidence``'s role: a
    free-form sink for layer-specific evidence (e.g. a SQL fingerprint
    of the RaMP query, a list of unmatched names).
    """

    model_config = ConfigDict(extra="forbid")

    # ---- Layer 6a: SET_ENRICHMENT ----
    claimed_pathway: str | None = Field(
        None,
        description="Pathway name lifted from the claim text.",
    )
    claimed_pathway_id: str | None = Field(
        None,
        description="RaMP / KEGG / WikiPathways ID lifted from the claim, when present.",
    )
    matched_top_pathways: list[PathwayMatch] = Field(
        default_factory=list,
        description="Top-3 (or top-N) entries from ramp_enrichment_result echoed for audit.",
    )
    best_match: PathwayMatch | None = Field(
        None,
        description="The single top_pathways entry the claim resolves to, when one matches.",
    )
    pathway_match_method: Literal["exact", "substring_either", "id", "none"] | None = Field(
        None,
        description=(
            "How the claimed pathway was matched: exact name, substring "
            "(claim ⊂ canonical or canonical ⊂ claim), pathway ID, or none."
        ),
    )

    # ---- Layer 6b: DRIVER_METABOLITE ----
    claimed_drivers: list[str] = Field(
        default_factory=list,
        description="Driver compound names / IDs as they appeared in the claim.",
    )
    claimed_drivers_resolved: list[str] = Field(
        default_factory=list,
        description=(
            "Claimed drivers after resolution to InChIKey first-blocks via "
            "the curated compound pool. Same ordering as ``claimed_drivers`` "
            "where resolution succeeded; entries that failed to resolve are "
            "listed in ``unresolved_drivers`` instead."
        ),
    )
    matched_signal_drivers: list[str] = Field(
        default_factory=list,
        description="InChIKey first-blocks present in ground_truth_signal_compounds.",
    )
    matched_noise_drivers: list[str] = Field(
        default_factory=list,
        description=(
            "InChIKey first-blocks present in ground_truth_noise_compounds. "
            "Non-empty list ⇒ CONTRADICTED verdict (LLM cited a noise compound)."
        ),
    )
    unresolved_drivers: list[str] = Field(
        default_factory=list,
        description="Claimed driver names that did not resolve to any InChIKey.",
    )
    off_pool_drivers: list[str] = Field(
        default_factory=list,
        description=(
            "Resolved InChIKey first-blocks that are neither in signal nor "
            "noise set — i.e. compounds outside this task's pool entirely. "
            "Non-empty ⇒ UNSUPPORTED (claim referenced something irrelevant)."
        ),
    )
    driver_precision: float | None = Field(
        None,
        ge=0.0,
        le=1.0,
        description="|matched_signal| / |claimed_drivers_resolved|, when denominator > 0.",
    )
    driver_recall: float | None = Field(
        None,
        ge=0.0,
        le=1.0,
        description="|matched_signal| / |ground_truth_signal_compounds|.",
    )

    # ---- Layer 6d: PATHWAY_RELATIONSHIP ----
    pathway_a: str | None = Field(None, description="First pathway in the relationship claim.")
    pathway_b: str | None = Field(None, description="Second pathway in the relationship claim.")
    pathway_a_id: str | None = None
    pathway_b_id: str | None = None
    relationship_type: Literal[
        "upstream",
        "downstream",
        "cross_talk",
        "shared_intermediates",
        "unknown",
    ] | None = Field(
        None,
        description="Parsed relationship asserted by the claim.",
    )
    shared_compound_count: int | None = Field(
        None,
        ge=0,
        description="Number of compounds appearing in both pathways per RaMP analytehaspathway.",
    )
    shared_compounds: list[str] = Field(
        default_factory=list,
        description=(
            "Up to 20 InChIKey first-blocks (or KEGG IDs when InChIKey is "
            "unavailable) shared between the two pathways. Truncated for "
            "log readability — ``shared_compound_count`` carries the full count."
        ),
    )
    hierarchy_data_available: bool | None = Field(
        None,
        description=(
            "True iff RaMP-DB exposes a pathway-hierarchy table that can "
            "support upstream/downstream verification. Currently always "
            "False (RaMP v2025-03-06 has no pathwayhaspathway). Surfacing "
            "this explicitly so consumers can distinguish 'we don't know' "
            "from 'we checked and there's no relationship'."
        ),
    )

    # ---- Generic ----
    tool_evidence: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Layer-specific evidence sink. Examples: "
            "{'ramp_query': '<sql>', 'ramp_rows': 12} for Layer 6d; "
            "{'lookup_cache_size': 150, 'unresolved_names': [...]} for Layer 6b."
        ),
    )


class ClaimProvenance(BaseModel):
    """Where a typed claim and its fields came from."""

    pass_id: Literal["v1", "v2"] | None = None
    extractor: str | None = None
    extractor_source: Literal["llm", "rule", "manual"] | None = None
    classifier_source: Literal["rule", "llm", "fallback"] | None = None
    parser_version: str | None = None
    source_span_start: int | None = None
    source_span_end: int | None = None


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

    claim_id: str | None = Field(
        None,
        description="Stable claim identifier within a verifier pass, when assigned.",
    )
    source_text: str | None = Field(
        None,
        description="Original extracted text before any normalization.",
    )
    claim_text: str = Field(
        ...,
        description=(
            "The atomic, decontextualised factual statement, as a complete "
            "sentence that stands alone without surrounding paragraph context. "
            "Example: 'D-Gulose has molecular formula C7H14O7' — not just "
            "'C7H14O7'."
        ),
    )
    normalized_text: str | None = Field(
        None,
        description="Normalized claim text used by local parsers.",
    )
    subject: str | None = Field(
        None,
        description=(
            "The named entity the claim is about, when one can be identified "
            "(e.g. 'D-Gulose', 'caffeine', 'map00232'). Used by the Stage 3 "
            "consistency layer to group claims about the same subject."
        ),
    )
    peak_mz: float | None = Field(
        None,
        description=(
            "For peak-level mechanistic claims, the asserted fragment m/z. "
            "None for non-peak claims."
        ),
    )
    neutral_loss: str | None = Field(
        None,
        description=(
            "For peak-level mechanistic claims, the asserted neutral loss "
            "when stated, e.g. 'H2O' or 'water'. None otherwise."
        ),
    )
    claim_subtype: ClaimSubtype = Field(
        ClaimSubtype.UNKNOWN,
        description="Optional semantic subtype inferred by local parsers.",
    )
    subject_kind: SubjectKind = Field(
        SubjectKind.UNKNOWN,
        description="Coarse kind of the claim subject.",
    )
    extracted_fields: ClaimExtractedFields = Field(
        default_factory=ClaimExtractedFields,
        description="Typed fields parsed from claim_text.",
    )
    provenance: ClaimProvenance = Field(
        default_factory=ClaimProvenance,
        description="Extraction/parser provenance for audit and metrics.",
    )


class ClassifiedClaim(BaseModel):
    """A claim with a routable type assigned by Stage 2."""

    model_config = ConfigDict(frozen=True)

    claim_id: str | None = Field(None, description="See ``ExtractedClaim.claim_id``.")
    claim_text: str = Field(..., description="See ``ExtractedClaim.claim_text``.")
    normalized_text: str | None = Field(
        None, description="See ``ExtractedClaim.normalized_text``."
    )
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
    peak_mz: float | None = Field(
        None,
        description="See ``ExtractedClaim.peak_mz``.",
    )
    neutral_loss: str | None = Field(
        None,
        description="See ``ExtractedClaim.neutral_loss``.",
    )
    claim_subtype: ClaimSubtype = Field(
        ClaimSubtype.UNKNOWN,
        description="Semantic subtype used by tables/metrics.",
    )
    subject_kind: SubjectKind = Field(
        SubjectKind.UNKNOWN,
        description="See ``ExtractedClaim.subject_kind``.",
    )
    candidate_ref: CandidateRef | None = Field(
        None,
        description="Candidate matched during typed normalization, if available.",
    )
    extracted_fields: ClaimExtractedFields = Field(
        default_factory=ClaimExtractedFields,
        description="See ``ExtractedClaim.extracted_fields``.",
    )
    confidence_hint: float | None = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Optional parser/classifier confidence hint; not a verdict.",
    )
    provenance: ClaimProvenance = Field(
        default_factory=ClaimProvenance,
        description="Extraction/classification provenance for audit and metrics.",
    )


class VerifiedClaim(BaseModel):
    """A claim after its layer has run.

    ``evidence`` is human-readable and short — a one-liner explaining what
    was checked and how. ``correction`` is populated only when the verdict
    is ``CONTRADICTED`` and the layer can name the right value per the
    source of truth (e.g. for H1, ``correction='C6H12O6'``).
    """

    model_config = ConfigDict(frozen=True)

    claim_id: str | None = Field(None, description="Stable claim identifier, if available.")
    claim_text: str = Field(..., description="The atomic statement, verbatim from extraction.")
    claim_type: ClaimType = Field(..., description="Which layer judged this claim.")
    claim_subtype: ClaimSubtype = Field(
        ClaimSubtype.UNKNOWN,
        description="Semantic subtype used by claim tables and metrics.",
    )
    subject: str | None = Field(None, description="Claim subject, if propagated.")
    subject_kind: SubjectKind = Field(
        SubjectKind.UNKNOWN,
        description="Coarse kind of the claim subject.",
    )
    candidate_ref: CandidateRef | None = Field(
        None,
        description="Candidate reference associated with this claim, if known.",
    )
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
    extracted_fields: ClaimExtractedFields = Field(
        default_factory=ClaimExtractedFields,
        description="Typed fields carried through verification.",
    )
    evidence_refs: list[EvidenceRef] = Field(
        default_factory=list,
        description="Structured evidence references used by the verifier.",
    )
    verifier_layer: str | None = Field(
        None,
        description="Layer implementation that judged the claim.",
    )
    tool_called: str | None = Field(
        None,
        description="External tool used for this claim, if any.",
    )
    trace_summary: str | None = Field(
        None,
        description="Short machine-friendly verification trace summary.",
    )
    severity: Literal["info", "minor", "major", "critical"] | None = Field(
        None,
        description="UI/metrics severity derived from verdict.",
    )
    claim_group_id: str | None = Field(
        None,
        description="Group id for linked claims such as consistency contradictions.",
    )
    parent_claim_id: str | None = Field(
        None,
        description="Previous-pass parent claim id when a rewritten claim is aligned.",
    )
    tool_evidence: dict[str, Any] | None = Field(
        None,
        description=(
            "Per-tool evidence for cross-validated claims. Layer F populates "
            "this with {'sirius': {...}, 'cfmid': {...}, 'consensus': '<label>'} "
            "when peak-mechanistic claims are checked by both SIRIUS and "
            "CFM-ID. None for layers that do not cross-validate."
        ),
    )
    enrichment_context: EnrichmentContext | None = Field(
        None,
        description=(
            "Structured Sub-6 enrichment-narrative evidence. Populated by "
            "Layer 6a (set_enrichment) / 6b (driver_metabolite) / 6d "
            "(pathway_relationship). None for non-Sub-6 claims."
        ),
    )
    feedback_hint: str | None = Field(
        None,
        description=(
            "LLM-facing actionable revision hint, populated post-verification "
            "by ``verifier.feedback_hints.annotate_claims``. Populated only "
            "for verdicts the agent can act on (CONTRADICTED / UNSUPPORTED). "
            "Phase A2 introduction; older verdict files written before "
            "v9-PhaseC+A2 leave this null."
        ),
    )


class VerifiedClaimRow(BaseModel):
    """Flattened row for UI tables and claim-level metrics."""

    claim_id: str
    claim_text: str
    claim_type: ClaimType
    claim_subtype: ClaimSubtype = ClaimSubtype.UNKNOWN
    subject: str | None = None
    candidate_ref: CandidateRef | None = None
    verdict: ClaimVerdict
    evidence_summary: str
    source_field: str | None = None
    correction: str | None = None
    verifier_layer: str | None = None
    tool_called: str | None = None
    trace_summary: str | None = None
    severity: Literal["info", "minor", "major", "critical"] = "info"
    claim_group_id: str | None = None
    parent_claim_id: str | None = None
    extracted_fields: ClaimExtractedFields = Field(default_factory=ClaimExtractedFields)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class VerifiedClaimTable(BaseModel):
    """Claim table for one verifier pass."""

    pass_id: Literal["v1", "v2"]
    rows: list[VerifiedClaimRow] = Field(default_factory=list)


class ClaimMetrics(BaseModel):
    """Aggregate metrics computed from verified claims."""

    total_claims: int = 0
    supported_claims: int = 0
    contradicted_claims: int = 0
    unsupported_claims: int = 0
    unverifiable_claims: int = 0
    error_claims: int = 0
    supported_ratio: float | None = None
    contradiction_rate: float | None = None
    unverifiable_rate: float | None = None
    claim_precision: float | None = None
    rewrite_improvement: float | None = None
    per_type_verdict_counts: dict[str, dict[str, int]] = Field(default_factory=dict)
    per_subtype_verdict_counts: dict[str, dict[str, int]] = Field(default_factory=dict)
    per_candidate_support_counts: dict[str, dict[str, int]] = Field(default_factory=dict)
    peak_claim_coverage: float | None = None
    tool_call_counts: dict[str, int] = Field(default_factory=dict)
    verification_confidence: float | None = None
    confidence_components: dict[str, float] = Field(default_factory=dict)


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
    claim_tables: list[VerifiedClaimTable] = Field(
        default_factory=list,
        description="Flattened claim tables for UI and claim-level metrics.",
    )
    claim_metrics: ClaimMetrics | None = Field(
        None,
        description="Aggregate claim-level metrics computed from the verifier output.",
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

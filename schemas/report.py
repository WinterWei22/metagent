"""Top-level audit-ready report produced by the deterministic identification pipeline.

The orchestrator (when it lands) will consume `IdentificationReport` as the
output of stitching A1 → A2 → (B, C) → D1, D2, E. This module defines only the
shape — composition logic lives in `scripts/run_full_pipeline.py`.

Design notes
------------

* **Auditable by construction.** Every score component (candidate.score,
  predicted_spectrum_cosine, mass_match_indicator, pathway_presence_indicator)
  is a published field on `CandidateReport`. A reader can recompute
  `evidence_score` from the report's own fields without rerunning the
  pipeline.

* **Honest about degradation.** Each enrichment source (D1, D2, E) can legally
  return `None` when its backend is unavailable or the candidate is out of
  scope (e.g. de novo SMILES absent from HMDB). The scoring formula down-
  weights a None branch to 0 rather than crashing or fabricating.

* **No re-use of the untrustworthy pathway fields for ranking.** `hit_count`
  was fixed per-pathway by commit 7d8b097, but `upstream_neighbours` /
  `downstream_neighbours` still carry the P-2 / P-3 / P-4 caveats (direction
  collapse, prefix leakage, cofactor noise). For v0 scoring we only use
  "any pathway returned → 1, else 0". Everything else is display-only.

Scoring formula (v0)
--------------------

::

    evidence_score = 0.4 * candidate.score                           # B/C
                   + 0.3 * (predicted_spectrum_cosine or 0.0)        # E, if available
                   + 0.2 * mass_match_indicator                      # SMILES-derived
                   + 0.1 * pathway_presence_indicator                # from D2.pathways

Weights sum to 1.0 and the formula is capped at 1.0 when every component is
maximal. `mass_match_indicator` is always computed from SMILES via RDKit's
`ExactMolWt`, never from `MetaboliteInfoResponse.exact_mass`, so that HMDB's
zwitterion curation choices (D-1) do not cause a 1 Da miss.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from schemas.common import Candidate, LiteratureRecord, PrefilteredCandidate, Spectrum
from schemas.molecule import MetaboliteInfoResponse
from schemas.pathway import PathwayContextResponse


# ---------------------------------------------------------------------------
# Scoring weights — declared as module constants so tests and the runner can
# assert against the same source of truth.
# ---------------------------------------------------------------------------


W_CANDIDATE: float = 0.4
W_PREDICTED_COSINE: float = 0.3
W_MASS_MATCH: float = 0.2
W_PATHWAY_PRESENCE: float = 0.1

assert abs(W_CANDIDATE + W_PREDICTED_COSINE + W_MASS_MATCH + W_PATHWAY_PRESENCE - 1.0) < 1e-9, (
    "Evidence-score weights must sum to 1.0"
)


# ---------------------------------------------------------------------------
# Per-candidate report
# ---------------------------------------------------------------------------


class CandidateReport(BaseModel):
    """One ranked candidate plus every downstream enrichment we ran on it."""

    # Silence pydantic's protected-namespace warning for `predicted_model_version`
    # — it starts with `model_` but is not related to Pydantic's own `model_*` API.
    model_config = ConfigDict(protected_namespaces=())

    candidate: Candidate = Field(
        ...,
        description="The post-merge Candidate from B (library) or C (generated), survivor of canonical-SMILES dedupe.",
    )
    prefilter_match: PrefilteredCandidate | None = Field(
        None,
        description=(
            "The matching PrefilteredCandidate from A2, if this candidate's "
            "canonical SMILES appeared in the A2 pool. None when the candidate "
            "came purely from C (de novo) without a pool entry."
        ),
    )
    metabolite_info: MetaboliteInfoResponse | None = Field(
        None,
        description=(
            "Raw D1 output, verbatim. exact_mass may carry HMDB's zwitterion "
            "offset (see D-1); do NOT use it for precursor matching — the "
            "pipeline uses mass_match_indicator (SMILES-derived) instead."
        ),
    )
    pathway_context: PathwayContextResponse | None = Field(
        None,
        description=(
            "Raw D2 output, verbatim. Per-pathway hit_count is trustworthy "
            "(fixed by 7d8b097). upstream_neighbours / downstream_neighbours "
            "still carry P-2 / P-3 / P-4 caveats and are display-only in v0."
        ),
    )
    predicted_spectrum_cosine: float | None = Field(
        None,
        ge=0.0,
        le=1.0,
        description=(
            "Modified-cosine similarity between E's predicted spectrum and the "
            "experimental spectrum, in [0, 1]. None when E was not run or failed."
        ),
    )
    predicted_model_version: str | None = Field(
        None,
        description="model_version from the E response, e.g. 'cfm-id-4.4.7'. None on skip.",
    )
    mass_match_indicator: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description=(
            "1.0 iff the SMILES-derived exact mass agrees with "
            "IdentificationReport.neutral_mass_computed within 5 ppm, else 0.0. "
            "Always computed from SMILES via RDKit ExactMolWt — bypasses the "
            "D-1 HMDB zwitterion offset."
        ),
    )
    pathway_presence_indicator: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description=(
            "1.0 iff pathway_context is not None and has at least one pathway entry, "
            "else 0.0. Does NOT use hit_count, neighbours, or cooccurrence_score."
        ),
    )
    evidence_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Weighted composite defined by compute_evidence_score. Audit-replayable from the fields above.",
    )
    notes: list[str] = Field(
        default_factory=list,
        description=(
            "Per-candidate caveats and provenance notes. Examples: "
            "'merged from library+generated', 'HMDB stores this as a cation "
            "(D-1)', 'E skipped: CfmUnavailableError'."
        ),
    )
    literature_records: list[LiteratureRecord] = Field(
        default_factory=list,
        description=(
            "Top-k literature hits from Track F (`literature_search`), "
            "verbatim from Europe PMC / PubMed. Empty when Stage 6 was "
            "skipped (literature_top_n=0), the candidate ranked outside "
            "the literature-enrichment window, or the search returned no "
            "results. Each record carries a verifiable PMID — the verifier "
            "round-trips PMIDs against Europe PMC to detect hallucinated "
            "citations."
        ),
    )

    # ------------------------------------------------------------------ #
    # Scoring formula — shared by the runner and the unit test.
    # ------------------------------------------------------------------ #

    @staticmethod
    def compute_evidence_score(
        *,
        candidate_score: float,
        predicted_spectrum_cosine: float | None,
        mass_match_indicator: float,
        pathway_presence_indicator: float,
    ) -> float:
        """Return the v0 evidence_score for a candidate's components.

        A None predicted_spectrum_cosine is treated as 0.0. The output is
        clamped to [0, 1] defensively, though with the documented weights and
        per-field ranges it can never exceed 1.0.
        """
        cosine = 0.0 if predicted_spectrum_cosine is None else predicted_spectrum_cosine
        score = (
            W_CANDIDATE * candidate_score
            + W_PREDICTED_COSINE * cosine
            + W_MASS_MATCH * mass_match_indicator
            + W_PATHWAY_PRESENCE * pathway_presence_indicator
        )
        # Defensive clamp; inputs are already schema-bounded to [0, 1] but a
        # future refactor might relax that and we don't want NaN/out-of-range
        # propagating into the final report.
        return max(0.0, min(1.0, score))


# ---------------------------------------------------------------------------
# Top-level report
# ---------------------------------------------------------------------------


class IdentificationReport(BaseModel):
    """Full audit-ready output of the deterministic identification pipeline.

    Composed from A1 → A2 → (B, C) → per-candidate D1, D2, E enrichment. The
    orchestrator (LLM-driven) will eventually consume this in bulk or
    per-candidate to assemble the final user-facing report.
    """

    model_config = ConfigDict(protected_namespaces=())

    experimental_spectrum: Spectrum = Field(
        ...,
        description="The A1-preprocessed input spectrum, verbatim.",
    )
    preprocess_quality_flag: Literal["good", "sparse", "noisy", "invalid"] = Field(
        ...,
        description="A1's quality assessment. Note: 'invalid' would already have raised from A1, so it is listed for forward compatibility only.",
    )
    neutral_mass_computed: float = Field(
        ...,
        gt=0.0,
        description="A2's neutral exact mass backed out from precursor_mz + adduct.",
    )
    n_prefilter_candidates: int = Field(..., ge=0, description="Size of A2's output pool.")
    n_library_candidates: int = Field(..., ge=0, description="B's candidates, before merge.")
    n_generated_candidates: int = Field(..., ge=0, description="C's candidates, before merge.")
    candidates: list[CandidateReport] = Field(
        ...,
        description="Merged + enriched, sorted descending by evidence_score. May be empty if upstream returned nothing.",
    )
    pipeline_version: str = Field(
        ...,
        min_length=1,
        description="Git description of the pipeline revision that produced this report, e.g. 'integration-day1:c745894'.",
    )
    tool_versions: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Keyed by tool / backend name (e.g. 'cfm-id', 'ms-bart', 'ms-clip', "
            "'gnps', 'hmdb', 'ramp'). Values are version strings when a tool "
            "reports one (cfm-id does), or a data-path signature "
            "('<abspath>@<mtime>') when it does not. Present to make reports "
            "trace-reproducible across backend changes."
        ),
    )
    warnings: list[str] = Field(
        default_factory=list,
        description=(
            "Aggregate degradation messages from across the pipeline. Examples: "
            "'predict_spectrum skipped for 3 candidates: CfmUnavailableError', "
            "'fetch_metabolite_info returned found=False for 2 candidates'. "
            "Empty list means the whole pipeline ran clean."
        ),
    )

"""Phase B1 claim grammar — 4 allowed claim shapes for Sub-6 narratives.

Phase B1 D0 draft. NOT YET WIRED into the extractor / classifier /
dispatcher. See ``docs/claim_grammar_v2.md`` for the rationale, layer
routing, DROP rules, and per-class positive / negative examples drawn
from real ``v4_a3_d3_no_lit`` verdicts.

Why 4 classes and not 5
-----------------------
The v1 verifier accepts 9 ``ClaimType`` values, yet 63–67% of Sub-6
claims come back ``UNVERIFIABLE_V0`` because the dispatcher (see
``verifier/agent.py:494``) routes GROUNDED / FACTUAL / LITERATURE /
PEAK_MECHANISTIC claims through spectrum-centric layers that
``SubsixSourceReport`` cannot satisfy. Opening a 5th GROUNDED class for
Sub-6A would re-invite that dead path: the audit
(``reports/agent/prompt_audit_for_rewrite.md`` §4) shows Sub-6A does NOT
inject IdReport into the narrative prompt today, so a 5th class has no
verifier-side route. If Sub-6A grounded ever lands, it is a dispatcher
change first; that work is outside Phase B1.

Why ``PATHWAY_MEMBERSHIP`` and ``METABOLITE_PATHWAY_LINK`` are split
--------------------------------------------------------------------
Both route to ``verifier/layers/biological_sub6.py`` (layer 6c), but
``METABOLITE_PATHWAY_LINK`` demands a concrete ``enzyme_or_reaction``
endpoint as a required field — that lets the narrative prompt request
mechanistic detail when it is truly grounded, and lets the extractor
drop bare "X is involved in Y" hand-waving that the v1 BIOLOGICAL bucket
silently absorbed.

Why ``PATHWAY_ENRICHMENT`` carries ``term_type``
------------------------------------------------
RaMP-DB enrichment results are not pathway-only: disease terms, Reactome
pathways, and GO terms all surface as enrichment hits. v1 routed any
non-KEGG-named result to ``grounded_claim`` and dropped it (see
``docs/claim_grammar_v2.md`` §5). v2 lifts that limitation up-front so
the D3 layer 6a fix can dispatch by ``term_type`` without a schema
migration.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enum
# ---------------------------------------------------------------------------


class ClaimGrammar(str, Enum):
    """Allowed claim shapes for Sub-6 narratives in Phase B1+."""

    PATHWAY_MEMBERSHIP = "pathway_membership"
    METABOLITE_PATHWAY_LINK = "metabolite_pathway_link"
    PATHWAY_ENRICHMENT = "pathway_enrichment"
    DRIVER_METABOLITE = "driver_metabolite"


# ---------------------------------------------------------------------------
# Per-class pydantic schemas
# ---------------------------------------------------------------------------
# These are the contract the narrative prompt (D1) and extractor (D2) must
# emit. Each carries the discriminator ``grammar`` so a JSON list of
# heterogeneous claim objects can be parsed by a single
# ``ClaimV2.model_validate`` call.


TermType = Literal["pathway", "disease", "reactome", "go"]
"""Term taxonomies surfaced by RaMP enrichment. ``pathway`` covers KEGG /
WikiPathways / SMPDB pathway entries; ``disease`` covers SMPDB / OMIM /
disease-set hits (e.g. "17-Beta Hydroxysteroid Dehydrogenase III
Deficiency"); ``reactome`` and ``go`` are reserved for future RaMP table
expansion. Layer 6a (Phase B1 D3 fix) dispatches by this field."""


class _BaseClaim(BaseModel):
    """Fields common to every grammar class."""

    claim_text: str = Field(
        ...,
        description=(
            "The verbatim sentence as it should appear in the human-facing "
            "narrative. Must NOT contain phrases from BANNED_HEDGES / "
            "BANNED_DIRECTIONAL / BANNED_ABSTRACT / BANNED_META."
        ),
    )


class PathwayMembershipClaim(_BaseClaim):
    """``<metabolite> is a member of <pathway>``.

    Verifier layer: ``verifier/layers/biological_sub6.py`` (6c).
    """

    grammar: Literal[ClaimGrammar.PATHWAY_MEMBERSHIP] = (
        ClaimGrammar.PATHWAY_MEMBERSHIP
    )
    subject: str = Field(..., description="Metabolite name as it appears in the input list.")
    pathway_name: str = Field(..., description="Pathway / term name as returned by query_ramp_enrichment or query_pathway_membership.")


class MetabolitePathwayLinkClaim(_BaseClaim):
    """``<metabolite> participates in <pathway> via <enzyme/reaction>``.

    Verifier layer: ``verifier/layers/biological_sub6.py`` (6c) — strict
    mode that rejects rows where ``enzyme_or_reaction`` is missing,
    generic, or absent from the narrative's tool-call transcript.
    """

    grammar: Literal[ClaimGrammar.METABOLITE_PATHWAY_LINK] = (
        ClaimGrammar.METABOLITE_PATHWAY_LINK
    )
    subject: str = Field(..., description="Metabolite name.")
    pathway_name: str = Field(..., description="Pathway / term name.")
    enzyme_or_reaction: str = Field(
        ...,
        description=(
            "Concrete enzyme name (e.g. 'cyclooxygenase 2 / COX-2') or KEGG "
            "reaction ID (e.g. 'R03050'). Free-text 'metabolism' or "
            "'biosynthesis' is NOT acceptable and must be dropped."
        ),
    )

    @field_validator("enzyme_or_reaction")
    @classmethod
    def _reject_generic_enzyme(cls, v: str) -> str:
        """Reject hand-waving endpoints that v1 BIOLOGICAL silently absorbed."""
        generic = {
            "metabolism", "biosynthesis", "biology", "pathway",
            "the pathway", "this pathway", "enzyme", "reaction",
            "enzymes", "reactions",
        }
        stripped = (v or "").strip().lower()
        if not stripped:
            raise ValueError("enzyme_or_reaction must be non-empty")
        if stripped in generic:
            raise ValueError(
                f"enzyme_or_reaction={v!r} is too generic; supply a concrete "
                "enzyme name or KEGG reaction ID"
            )
        return v


class PathwayEnrichmentClaim(_BaseClaim):
    """``<term> is enriched given metabolite set {...}``.

    Verifier layer: ``verifier/layers/set_enrichment.py`` (6a). The
    ``term_type`` field lets the v2 layer dispatch by taxonomy without a
    schema migration when D3 lifts the v1 KEGG-only assumption.
    """

    grammar: Literal[ClaimGrammar.PATHWAY_ENRICHMENT] = (
        ClaimGrammar.PATHWAY_ENRICHMENT
    )
    term_id: str = Field(
        ...,
        description=(
            "Stable identifier for the enriched term — KEGG pathway ID, "
            "Reactome ID, GO ID, or SMPDB disease ID. Mandatory: the v2 "
            "extractor refuses to route enrichment claims without an ID, "
            "even when ``term_name`` looks unambiguous."
        ),
    )
    term_name: str = Field(..., description="Human-readable term name.")
    term_type: TermType = Field(
        ...,
        description=(
            "Taxonomy of ``term_id``. v2 layer 6a dispatches by this field. "
            "v1 narratives implicitly assumed ``pathway`` — v2 makes the "
            "choice explicit so disease / Reactome / GO hits survive."
        ),
    )
    p_value: float | None = Field(default=None, description="Hypergeometric p-value as returned by RaMP. Optional.")
    fdr: float | None = Field(default=None, description="FDR-adjusted q-value. Optional.")
    metabolite_set: list[str] = Field(
        default_factory=list,
        description=(
            "The subset of input metabolites that hit this term. Empty "
            "list is allowed for terse narratives, but every name must "
            "appear in the original differential list."
        ),
    )


class DriverMetaboliteClaim(_BaseClaim):
    """``<metabolite> drives <pathway> based on <signal evidence>``.

    Verifier layer: ``verifier/layers/driver_metabolite.py`` (6b).
    ``signal_evidence`` must reference
    ``SubsixSourceReport.ground_truth_signal_compounds`` so the layer can
    cross-check the driver assertion against the planted ground truth.
    """

    grammar: Literal[ClaimGrammar.DRIVER_METABOLITE] = (
        ClaimGrammar.DRIVER_METABOLITE
    )
    subject: str = Field(..., description="Driver metabolite name.")
    pathway_name: str = Field(..., description="Pathway driven by the subject.")
    signal_compound_ids: list[str] = Field(
        ...,
        min_length=1,
        description=(
            "Concrete compound names or KEGG IDs from "
            "``ground_truth_signal_compounds`` that support the driver "
            "assertion. Must be a strict subset of the differential set; "
            "abstract collectives ('driver cluster', 'sulphur amino "
            "acids') are NOT acceptable. Empty list is rejected — a "
            "driver claim without evidence is structurally void."
        ),
    )


ClaimV2 = Annotated[
    Union[
        PathwayMembershipClaim,
        MetabolitePathwayLinkClaim,
        PathwayEnrichmentClaim,
        DriverMetaboliteClaim,
    ],
    Field(discriminator="grammar"),
]
"""Union of every legal v2 claim shape, discriminated by ``grammar``.

Usage::

    from pydantic import TypeAdapter
    adapter = TypeAdapter(list[ClaimV2])
    claims = adapter.validate_python(json.loads(narrative_json_text))
"""


# ---------------------------------------------------------------------------
# Required-field summary (for prompt generation and metric reporting)
# ---------------------------------------------------------------------------

REQUIRED_FIELDS: dict[ClaimGrammar, tuple[str, ...]] = {
    ClaimGrammar.PATHWAY_MEMBERSHIP: ("subject", "pathway_name"),
    ClaimGrammar.METABOLITE_PATHWAY_LINK: (
        "subject", "pathway_name", "enzyme_or_reaction",
    ),
    ClaimGrammar.PATHWAY_ENRICHMENT: ("term_id", "term_name", "term_type"),
    ClaimGrammar.DRIVER_METABOLITE: (
        "subject", "pathway_name", "signal_compound_ids",
    ),
}


# ---------------------------------------------------------------------------
# Negative-word lexicons (consumed by D1 narrative prompt and D2 extractor)
# ---------------------------------------------------------------------------
# Phrases that signal a sentence is outside the 4 grammar classes.
# Centralised so prompt, extractor, and feedback-hint code share one
# source of truth. These are checked against ``claim_text`` (case-
# insensitive); a hit forces ``dropped_by_grammar``.

BANNED_HEDGES: tuple[str, ...] = (
    "may", "might", "maybe",
    "suggest", "suggesting", "suggests",
    "potentially", "possibly",
    "likely", "unlikely",
    "consistent with",
    "appears to", "seems to",
    "could be",
    "is thought to",
)

BANNED_DIRECTIONAL: tuple[str, ...] = (
    "upstream", "downstream",
    "two-hop", "three-hop", "four-hop", "n-hop",
    "spans four steps", "spans three steps", "spans two steps",
    "precursor of",
    "leads to",
    "routes lead",
    "positioned at the branch point",
)
"""Directional language without a ground-truth path. NOTE: 'drives' /
'driving' are deliberately NOT banned — they are the canonical verb for
the :class:`DriverMetaboliteClaim` shape (e.g. 'L-Methionine drives
Cysteine and methionine metabolism'). The problematic surface form is
direction-without-evidence ('upstream of X', 'downstream of Y'), which
is what RaMP-DB cannot ground."""

BANNED_ABSTRACT: tuple[str, ...] = (
    "canonical",
    "cascade",
    "arms radiating",
    "axis",
    "interplay",
    "hallmark of",
    "crosstalk",
    "signaling cascade",
    "metabolic-immune",
    "branch producing",
    "driver cluster",
    "eicosanoid cluster",
    "metabolite cluster",
)

BANNED_TOOL_ROUNDTRIP_PATTERNS: tuple[str, ...] = (
    r"\bC\d{5}\b",                       # KEGG compound ID
    r"\bD\d{5}\b",                       # KEGG drug ID
    r"\bR\d{5}\b",                       # KEGG reaction ID
    r"\bmap\d{5}\b",                     # KEGG pathway map ID
    r"\bhsa\d{5}\b",                     # KEGG human pathway ID
    r"\bHMDB\d{7}\b",                    # HMDB ID
    r"\bRAMP_C_\d+\b",                   # RaMP analyte ID
    r"\bSMP\d{5,7}\b",                   # SMPDB ID
    r"\bWP\d{3,5}\b",                    # WikiPathways ID
    r"\b[A-Z]{14}-[A-Z]{10}-[A-Z]\b",    # InChIKey
    r"\bC\d+H\d+(?:N\d*)?(?:O\d*)?(?:S\d*)?(?:P\d*)?\b",  # Hill-notation formula
    r"\bhas (?:KEGG|HMDB|RAMP|InChIKey|SMPDB|WP|map|hsa)\b",  # roundtrip phrasing
)
"""Tool-roundtrip surface patterns. v1 BIOLOGICAL/FACTUAL claims of the
form 'X has KEGG ID C00073' / 'X has molecular formula C5H11NO2S' are
mid-reasoning tool-call breadcrumbs, not pathway-level conclusions, and
account for 318 (~18%) of v1 UNV claims in the 63-task scan.

Tool-roundtrip checks use ``re.search`` (case-sensitive — KEGG IDs are
literal) against ``claim_text``. Any hit forces ``dropped_by_grammar``."""


BANNED_META: tuple[str, ...] = (
    "limited to",
    "should be validated",
    "lack of evidence",
    "lack of positive evidence",
    "omitted",
    "strength of claims",
    "future work",
    "caveat",
    "is limited",
    "claims regarding",
    "does not preclude",
)
"""Self-limitation / methods-meta language. Bans both at the narrative
prompt (don't write it) and at the extractor (drop if it leaks through).
Reason: meta sentences pollute the human-facing narrative text — a
paper reviewer reading 'the strength of claims is limited' will lose
trust in the result before reading the verdict table."""


# ---------------------------------------------------------------------------
# Validation (stub — real implementation lands in Phase B1 D2)
# ---------------------------------------------------------------------------


class ValidationResult(BaseModel):
    """Outcome of running a candidate claim through the grammar check.

    A claim with ``is_valid=False`` and ``drop_reason`` populated is
    counted under ``dropped_by_grammar`` and excluded from the
    ``supported / unsupported / contradicted / unverifiable_v0``
    denominator.
    """

    is_valid: bool
    grammar: ClaimGrammar | None = None
    drop_reason: str | None = None


def validate(claim_obj: dict) -> ValidationResult:
    """Validate a candidate claim dict against the grammar.

    Phase B1 D0 — stub. The full implementation in D2 will:

    1. Reject if the ``grammar`` field is missing or not a
       :class:`ClaimGrammar` value.
    2. Reject if any field in ``REQUIRED_FIELDS[grammar]`` is missing or
       empty.
    3. Reject if ``claim_text`` contains a banned phrase from
       :data:`BANNED_HEDGES`, :data:`BANNED_DIRECTIONAL`,
       :data:`BANNED_ABSTRACT`, or :data:`BANNED_META`.
    4. Parse via the appropriate per-class pydantic schema; surface
       schema errors as ``drop_reason``.
    5. Return ``ValidationResult(is_valid=True, grammar=<class>,
       drop_reason=None)`` on success.
    """
    return ValidationResult(
        is_valid=False,
        grammar=None,
        drop_reason="stub-not-implemented-phase-b1-d0",
    )

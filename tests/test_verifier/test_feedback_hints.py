"""Unit tests for verifier/feedback_hints.py (phase A2 D1).

The annotation helper is verifier output post-processing: it should
populate ``claim_id`` and ``feedback_hint`` for the LLM-facing feedback
loop, and never alter any verdict, evidence, or other field.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import pytest

from verifier.feedback_hints import (
    _NEUTRAL_VERDICTS,
    annotate_claims,
    generate_feedback_hint,
)
from verifier.schemas import (
    ClaimExtractedFields,
    ClaimSubtype,
    ClaimType,
    ClaimVerdict,
    VerifiedClaim,
)


def _make_claim(
    *,
    claim_text: str = "claim",
    claim_type: ClaimType = ClaimType.BIOLOGICAL,
    claim_subtype: ClaimSubtype = ClaimSubtype.UNKNOWN,
    verdict: ClaimVerdict,
    evidence: str = "stub evidence",
    pathway_name: str | None = None,
    correction: str | None = None,
    claim_id: str | None = None,
) -> VerifiedClaim:
    return VerifiedClaim(
        claim_id=claim_id,
        claim_text=claim_text,
        claim_type=claim_type,
        claim_subtype=claim_subtype,
        verdict=verdict,
        evidence=evidence,
        correction=correction,
        extracted_fields=ClaimExtractedFields(pathway_name=pathway_name),
    )


# ---------------------------------------------------------------------------
# Verdict-conditional hint emission
# ---------------------------------------------------------------------------


class TestNeutralVerdicts:
    @pytest.mark.parametrize(
        "verdict",
        list(_NEUTRAL_VERDICTS),
    )
    def test_no_hint_for_neutral_verdict(self, verdict):
        c = _make_claim(verdict=verdict)
        assert generate_feedback_hint(c) is None

    def test_supported_no_hint(self):
        c = _make_claim(
            verdict=ClaimVerdict.SUPPORTED,
            pathway_name="Glycolysis",
        )
        assert generate_feedback_hint(c) is None


class TestContradictedHints:
    def test_pathway_relationship_hint_mentions_kegg(self):
        c = _make_claim(
            claim_type=ClaimType.PATHWAY_RELATIONSHIP,
            verdict=ClaimVerdict.CONTRADICTED,
        )
        h = generate_feedback_hint(c)
        assert h is not None
        assert "KEGG" in h
        assert "retract" in h.lower() or "reverse" in h.lower()

    def test_contradicted_with_correction_uses_correction(self):
        c = _make_claim(
            claim_type=ClaimType.SET_ENRICHMENT,
            verdict=ClaimVerdict.CONTRADICTED,
            pathway_name="folate cycle",
            correction="Folate metabolism (KEGG hsa00670)",
        )
        h = generate_feedback_hint(c)
        assert h is not None
        assert "Folate metabolism" in h

    def test_driver_metabolite_hint_mentions_input_list(self):
        c = _make_claim(
            claim_type=ClaimType.DRIVER_METABOLITE,
            claim_subtype=ClaimSubtype.DRIVER_LIST,
            verdict=ClaimVerdict.CONTRADICTED,
        )
        h = generate_feedback_hint(c)
        assert h is not None
        assert "input" in h.lower() and "list" in h.lower()

    def test_set_enrichment_hint_includes_pathway_name(self):
        c = _make_claim(
            claim_type=ClaimType.SET_ENRICHMENT,
            verdict=ClaimVerdict.CONTRADICTED,
            pathway_name="one-carbon homeostasis",
        )
        h = generate_feedback_hint(c)
        assert h is not None
        assert "one-carbon homeostasis" in h


class TestUnsupportedHints:
    def test_unsupported_pathway_includes_name_and_tool(self):
        c = _make_claim(
            claim_type=ClaimType.SET_ENRICHMENT,
            verdict=ClaimVerdict.UNSUPPORTED,
            pathway_name="metabolic homeostasis",
        )
        h = generate_feedback_hint(c)
        assert h is not None
        assert "metabolic homeostasis" in h
        assert "query_ramp_enrichment" in h

    def test_unsupported_relationship_advises_path_or_drop(self):
        c = _make_claim(
            claim_type=ClaimType.PATHWAY_RELATIONSHIP,
            verdict=ClaimVerdict.UNSUPPORTED,
        )
        h = generate_feedback_hint(c)
        assert h is not None
        assert "query_kegg_path" in h or "drop" in h.lower()


# ---------------------------------------------------------------------------
# annotate_claims — produces a NEW list, originals untouched
# ---------------------------------------------------------------------------


class TestAnnotatePass:
    def test_assigns_synthesised_ids_in_order(self):
        a = _make_claim(verdict=ClaimVerdict.SUPPORTED)
        b = _make_claim(verdict=ClaimVerdict.CONTRADICTED)
        out = annotate_claims([a, b], pass_id="v1")
        assert [c.claim_id for c in out] == ["v1:c000", "v1:c001"]

    def test_preserves_existing_claim_ids(self):
        a = _make_claim(
            verdict=ClaimVerdict.SUPPORTED, claim_id="prebaked_99"
        )
        out = annotate_claims([a], pass_id="v1")
        assert out[0].claim_id == "prebaked_99"

    def test_pass_id_appears_in_synthetic_id(self):
        a = _make_claim(verdict=ClaimVerdict.SUPPORTED)
        out = annotate_claims([a], pass_id="v2")
        assert out[0].claim_id == "v2:c000"

    def test_supported_claim_has_no_feedback_hint(self):
        a = _make_claim(verdict=ClaimVerdict.SUPPORTED)
        out = annotate_claims([a], pass_id="v1")
        assert out[0].feedback_hint is None

    def test_contradicted_claim_has_feedback_hint(self):
        a = _make_claim(
            claim_type=ClaimType.PATHWAY_RELATIONSHIP,
            verdict=ClaimVerdict.CONTRADICTED,
        )
        out = annotate_claims([a], pass_id="v1")
        assert out[0].feedback_hint
        assert "KEGG" in out[0].feedback_hint

    def test_originals_unchanged(self):
        # frozen=True model_copy must produce a new instance, not mutate
        a = _make_claim(verdict=ClaimVerdict.CONTRADICTED, claim_id=None)
        original_hint = a.feedback_hint  # None
        out = annotate_claims([a], pass_id="v1")
        # New instance
        assert out[0] is not a
        assert out[0].claim_id == "v1:c000"
        assert out[0].feedback_hint
        # Original untouched
        assert a.claim_id is None
        assert a.feedback_hint == original_hint

    def test_preserves_all_other_fields(self):
        a = _make_claim(
            claim_text="The dominant signal is steroid hormone biosynthesis",
            claim_type=ClaimType.BIOLOGICAL,
            verdict=ClaimVerdict.UNSUPPORTED,
            evidence="evidence string",
            pathway_name="steroid hormone biosynthesis",
        )
        out = annotate_claims([a], pass_id="v1")
        c = out[0]
        # Untouched fields:
        assert c.claim_text == a.claim_text
        assert c.verdict == a.verdict
        assert c.evidence == a.evidence
        assert c.claim_type == a.claim_type
        assert c.extracted_fields.pathway_name == a.extracted_fields.pathway_name
        # New fields populated:
        assert c.claim_id == "v1:c000"
        assert c.feedback_hint is not None


# ---------------------------------------------------------------------------
# Backward-compat sanity — old verdict JSONL records have null
# claim_id / feedback_hint and should still parse with the new schema.
# ---------------------------------------------------------------------------


class TestLiteratureHintsA3:
    """Phase A3 D1b: unsupported biological_claim hints should steer the
    agent toward search_literature, not blanket retract.
    """

    def test_unsupported_biological_with_subject_suggests_literature(self):
        c = VerifiedClaim(
            claim_id="v1:c000",
            claim_text="Methionine restriction extends mouse lifespan",
            claim_type=ClaimType.BIOLOGICAL,
            verdict=ClaimVerdict.UNSUPPORTED,
            evidence="not in RaMP",
            subject="methionine restriction lifespan",
            extracted_fields=ClaimExtractedFields(),
        )
        hint = generate_feedback_hint(c)
        assert hint
        assert "search_literature" in hint
        # The hint embeds the focus phrase (subject) inside the suggested call.
        assert "methionine restriction lifespan" in hint
        # Drop fallback still available
        assert "drop" in hint.lower()

    def test_unsupported_biological_with_pathway_fallback(self):
        c = VerifiedClaim(
            claim_id="v1:c001",
            claim_text="Aromatase activity links androgens and estrogens",
            claim_type=ClaimType.BIOLOGICAL,
            verdict=ClaimVerdict.UNSUPPORTED,
            evidence="not in RaMP",
            extracted_fields=ClaimExtractedFields(pathway_name="aromatase pathway"),
        )
        hint = generate_feedback_hint(c)
        assert hint
        assert "search_literature" in hint
        assert "aromatase pathway" in hint

    def test_unsupported_biological_with_no_fields_uses_text(self):
        # Neither subject nor pathway_name; falls back to first 6 words.
        c = VerifiedClaim(
            claim_id="v1:c002",
            claim_text="Mitochondrial superoxide drives cellular senescence in adipocytes",
            claim_type=ClaimType.BIOLOGICAL,
            verdict=ClaimVerdict.UNSUPPORTED,
            evidence="not in RaMP",
            extracted_fields=ClaimExtractedFields(),
        )
        hint = generate_feedback_hint(c)
        assert hint
        assert "search_literature" in hint
        # First 6 words of the claim text become the focus.
        assert "Mitochondrial superoxide drives cellular senescence in" in hint

    def test_unsupported_non_biological_does_not_suggest_literature(self):
        # Only BIOLOGICAL gets the literature steer; pathway_relationship
        # stays with the KEGG-graph guidance.
        c = VerifiedClaim(
            claim_id="v1:c003",
            claim_text="Pyruvate is upstream of acetyl-CoA",
            claim_type=ClaimType.PATHWAY_RELATIONSHIP,
            verdict=ClaimVerdict.UNSUPPORTED,
            evidence="no KEGG path",
            extracted_fields=ClaimExtractedFields(),
        )
        hint = generate_feedback_hint(c)
        assert hint
        assert "search_literature" not in hint
        # Stays with the KEGG-specific advice.
        assert "kegg" in hint.lower() or "co-membership" in hint.lower()

    def test_supported_biological_no_hint(self):
        # Sanity: SUPPORTED still emits no hint regardless of type.
        c = VerifiedClaim(
            claim_id="v1:c004",
            claim_text="Glucose is in glycolysis",
            claim_type=ClaimType.BIOLOGICAL,
            verdict=ClaimVerdict.SUPPORTED,
            evidence="RaMP confirms",
            extracted_fields=ClaimExtractedFields(),
        )
        assert generate_feedback_hint(c) is None


class TestBackwardCompat:
    def test_v3_verdict_record_still_parses(self):
        # A trimmed v3-PhaseC claim record with the fields that existed
        # before A2 D1 (and feedback_hint absent).
        legacy = {
            "claim_id": None,
            "claim_text": "The dominant signal is steroid hormone biosynthesis",
            "claim_type": "biological_claim",
            "claim_subtype": "pathway_membership",
            "subject": "steroid hormone biosynthesis",
            "subject_kind": "unknown",
            "verdict": "unsupported",
            "evidence": "Pathway not in top hits.",
            "extracted_fields": {
                "pathway_name": "steroid hormone biosynthesis",
            },
        }
        c = VerifiedClaim.model_validate(legacy)
        assert c.feedback_hint is None  # default
        assert c.claim_id is None
        # And it can be annotated to populate both:
        annotated = annotate_claims([c], pass_id="v1")[0]
        assert annotated.claim_id == "v1:c000"
        assert annotated.feedback_hint is not None

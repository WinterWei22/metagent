"""Unit tests for Stage 2 classifier (``verifier.claim_classifier``)."""
from __future__ import annotations

import pytest

from common import llm_client
from verifier.claim_classifier import _rule_classify, classify_claims
from verifier.schemas import ClaimType, ExtractedClaim


# ---------------------------------------------------------------------------
# Rule-based classification — should cover the 80%+ pattern library
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("D-Gulose has molecular formula C7H14O7", ClaimType.GROUNDED),
        ("D-Gulose evidence_score is 0.771", ClaimType.GROUNDED),
        ("Predicted-spectrum cosine is 0.423", ClaimType.GROUNDED),
        ("B/C is 0.860", ClaimType.GROUNDED),
        ("The mass accuracy is below 1 ppm vs HMDB reference", ClaimType.GROUNDED),
        ("Linked to galactose metabolism", ClaimType.BIOLOGICAL),
        ("Linked to galactosemia", ClaimType.BIOLOGICAL),
        ("Linked to Fabry disease pathways", ClaimType.BIOLOGICAL),
        ("Caffeine maps to KEGG pathway map00232", ClaimType.BIOLOGICAL),
        ("Caffeine has KEGG ID C07481", ClaimType.FACTUAL),
        ("Top candidate has CID:218057", ClaimType.FACTUAL),
        ("Caffeine InChIKey is RYYVLZVUVIJVGH-UHFFFAOYSA-N", ClaimType.FACTUAL),
        ("Caffeine is in HMDB0001847", ClaimType.FACTUAL),
        ("Bare formula C6H19NSi2", ClaimType.GROUNDED),
        # Literature claims — anchored PMID / DOI
        ("Caffeine has been characterised in PMID 12345678",
         ClaimType.LITERATURE),
        ("doi:10.1000/jbc.123 reports this", ClaimType.LITERATURE),
        ("see 10.1038/nature.2023.001 for details", ClaimType.LITERATURE),
        # Literature precedence over compound name: a citation makes the
        # claim a literature claim, not a factual-roundtrip claim
        ("Caffeine has KEGG ID C07481 according to PMID 12345",
         ClaimType.LITERATURE),
    ],
)
def test_rule_classify(text, expected):
    assert _rule_classify(text) == expected


def test_rule_classify_returns_none_on_ambiguous():
    assert _rule_classify("D-Gulose is a C-3 epimer of glucose") is None
    assert _rule_classify("The structure is synthetically plausible") is None


# ---------------------------------------------------------------------------
# P1 regression — Sub-6 SET_ENRICHMENT routing fix (Day 3 §4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        # Real misclassified Sub-6B claims (verbatim from sub6b_verdicts.jsonl)
        "The dominant pathway affected is glycerolipid metabolism/TAG biosynthesis",
        "Pyrimidine metabolism is the dominant pathway affected",
        "Methionine/Sulfur Amino Acid Metabolism is the most affected pathway",
        "The metabolites strongly suggest perturbation of pyrimidine metabolism as the primary pathway",
        "Differential metabolites point to disruption of several interconnected pathways",
        "Coordinated changes in pyrimidine metabolites suggest altered nucleotide demand",
        "The data indicate dysregulation of arachidonic acid metabolism",
        "The dominant theme is glycerolipid metabolism",
        # Pre-existing canonical phrasings — must still classify correctly
        "These metabolites are enriched in Tyrosine metabolism",
        "Pathway analysis identified Statin inhibition as the top hit",
    ],
)
def test_set_enrichment_p1_rule_classify(text):
    """P1 fix: collective-subject + pathway-as-predicate phrasings now
    route to SET_ENRICHMENT (previously fell through to BIOLOGICAL via
    the pathway/metabolism keyword catch-all)."""
    assert _rule_classify(text) == ClaimType.SET_ENRICHMENT


@pytest.mark.parametrize(
    "text",
    [
        # Counter-examples that match the existing pathway/metabolism keyword
        # and resolve deterministically to BIOLOGICAL — must STILL be
        # BIOLOGICAL after the P1 widening.
        "dCMP is in pyrimidine metabolism",
        "Ureidosuccinic acid represents an early node in the pyrimidine pathway",
        "Tyrosine metabolism is dysregulated in Parkinson's disease",
        "Caffeine maps to KEGG pathway map00232",
    ],
)
def test_biological_stays_biological_after_p1(text):
    """P1 must NOT over-classify: pathway_membership / single-compound
    pathway claims still rule-classify as BIOLOGICAL."""
    assert _rule_classify(text) == ClaimType.BIOLOGICAL


@pytest.mark.parametrize(
    "text",
    [
        # Single-compound role/process claims — no pathway/metabolism
        # keyword, so the rule classifier returns None and the LLM
        # fallback labels them. They MUST NOT route to SET_ENRICHMENT
        # via rule (the LLM will class them as biological_claim per the
        # updated few-shots).
        "Glutathione is involved in oxidative stress response",
        "Polyamines regulate protein synthesis",
        "Acrolein presence indicates oxidative damage to polyunsaturated fatty acids",
    ],
)
def test_single_compound_claims_dont_route_to_set_enrichment_via_rule(text):
    """Defensive: P1 widening must not capture single-compound role
    claims by mistake. They fall through to LLM fallback (None)."""
    out = _rule_classify(text)
    assert out != ClaimType.SET_ENRICHMENT
    # Single-compound role claims have no pathway-keyword anchor →
    # rule classifier returns None, LLM fallback decides.
    assert out is None or out == ClaimType.BIOLOGICAL


def test_pathway_relationship_still_wins_over_set_enrichment():
    """Precedence: relationship-shaped phrasings outrank set_enrichment
    even when they include 'dominant' / 'primary' qualifiers."""
    # 'shares intermediates' — pathway_relationship
    assert (
        _rule_classify(
            "Tyrosine metabolism shares intermediates with Phenylalanine metabolism"
        )
        == ClaimType.PATHWAY_RELATIONSHIP
    )
    # 'upstream of' — pathway_relationship
    assert (
        _rule_classify("Methionine metabolism is upstream of polyamine biosynthesis")
        == ClaimType.PATHWAY_RELATIONSHIP
    )


def test_driver_metabolite_still_wins_over_set_enrichment():
    """Precedence: driver-shaped phrasings outrank set_enrichment."""
    assert (
        _rule_classify("Tyrosine and DOPA are the key drivers of this enrichment")
        == ClaimType.DRIVER_METABOLITE
    )


# ---------------------------------------------------------------------------
# classify_claims — rule + LLM fallback
# ---------------------------------------------------------------------------


def _ec(text, subj=None):
    return ExtractedClaim(claim_text=text, subject=subj)


def test_all_rule_decided_costs_no_llm_call():
    llm_client.set_mock([])  # would IndexError if called
    claims = [
        _ec("formula C7H14O7", "D-Gulose"),
        _ec("Linked to galactose metabolism", "D-Gulose"),
        _ec("HMDB0250761", None),
    ]
    classified, n_calls = classify_claims(claims, trace_id="t1")
    assert n_calls == 0
    assert all(c.classifier_source == "rule" for c in classified)
    assert [c.claim_type for c in classified] == [
        ClaimType.GROUNDED, ClaimType.BIOLOGICAL, ClaimType.FACTUAL,
    ]


def test_ambiguous_claims_batched_into_single_llm_call():
    llm_client.set_mock(["0: factual_roundtrip_claim\n1: biological_claim"])
    claims = [
        _ec("D-Gulose is a C-3 epimer of glucose", "D-Gulose"),
        _ec("This appears in biological contexts", None),
    ]
    classified, n_calls = classify_claims(claims, trace_id="t2")
    assert n_calls == 1
    assert all(c.classifier_source == "llm" for c in classified)
    assert classified[0].claim_type == ClaimType.FACTUAL
    assert classified[1].claim_type == ClaimType.BIOLOGICAL


def test_llm_malformed_line_defaults_to_fallback():
    llm_client.set_mock(["0: biological_claim\n1: malformed-no-valid-type"])
    claims = [_ec("X?", None), _ec("Y?", None)]
    classified, n_calls = classify_claims(claims, trace_id="t3")
    assert n_calls == 1
    assert classified[0].classifier_source == "llm"
    assert classified[1].classifier_source == "fallback"
    # fallback default is GROUNDED so the downstream layer has *some*
    # plausible route; evaluation can filter on source == "fallback".
    assert classified[1].claim_type == ClaimType.GROUNDED


def test_mixed_rule_and_llm_only_ambiguous_costs_one_call():
    # Only the second claim is ambiguous
    llm_client.set_mock(["0: factual_roundtrip_claim"])
    claims = [
        _ec("formula C7H14O7", "D-Gulose"),            # rule -> GROUNDED
        _ec("D-Gulose is a fancy molecule", "D-Gulose"),  # ambiguous -> LLM
        _ec("Linked to galactose metabolism", None),   # rule -> BIOLOGICAL
    ]
    classified, n_calls = classify_claims(claims, trace_id="t4")
    assert n_calls == 1
    assert [c.classifier_source for c in classified] == ["rule", "llm", "rule"]


def test_empty_input_no_llm_call():
    llm_client.set_mock([])
    classified, n_calls = classify_claims([], trace_id="t5")
    assert classified == [] and n_calls == 0

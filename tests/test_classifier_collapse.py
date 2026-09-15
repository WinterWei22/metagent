"""Phase B1 D3 — classifier collapse (9-class v1 → 4-class grammar v2)
unit tests.

Covers:
  - ``route_v2_claim`` direct asserts for each ClaimGrammar value.
  - The v2 grammar path through ``classify_claims``: each grammar
    shape routes to the correct ClaimType, ``llm_calls=0``, and
    ``classifier_source="rule"``.
  - The v1 legacy free-text path is preserved (rule pass still
    decides).
  - The Phase B1 D3 anti-pattern fix: the
    ``classify_ambiguous`` LLM prompt no longer absorbs
    "Polyamines regulate protein synthesis"-type abstracts into
    BIOLOGICAL — they parse as ``other_claim``.
  - Mixed batch (v2 + legacy) — one batch, only legacy claims hit
    the LLM fallback.
"""
from __future__ import annotations

import pytest

from common import llm_client
from verifier.claim_classifier import (
    _V2_GRAMMAR_TO_LEGACY_ROUTE,
    _parse_type,
    classify_claims,
    route_v2_claim,
)
from verifier.grammar import ClaimGrammar
from verifier.schemas import ClaimType, ExtractedClaim


# ---------------------------------------------------------------------------
# Direct asserts on the routing table
# ---------------------------------------------------------------------------


def test_route_v2_pathway_membership_to_biological() -> None:
    assert route_v2_claim(ClaimGrammar.PATHWAY_MEMBERSHIP) is ClaimType.BIOLOGICAL


def test_route_v2_metabolite_pathway_link_to_biological() -> None:
    assert route_v2_claim(ClaimGrammar.METABOLITE_PATHWAY_LINK) is ClaimType.BIOLOGICAL


def test_route_v2_pathway_enrichment_to_set_enrichment() -> None:
    assert route_v2_claim(ClaimGrammar.PATHWAY_ENRICHMENT) is ClaimType.SET_ENRICHMENT


def test_route_v2_driver_metabolite_to_driver_metabolite() -> None:
    assert route_v2_claim(ClaimGrammar.DRIVER_METABOLITE) is ClaimType.DRIVER_METABOLITE


def test_route_v2_table_covers_every_grammar() -> None:
    """Regression guard: a new ClaimGrammar value added without
    updating the routing table should fail this test (and any future
    ``route_v2_claim`` lookup)."""
    assert set(ClaimGrammar) == set(_V2_GRAMMAR_TO_LEGACY_ROUTE)


# ---------------------------------------------------------------------------
# v2 grammar path through classify_claims — no LLM call
# ---------------------------------------------------------------------------


def _ec(text: str, *, grammar: ClaimGrammar | None) -> ExtractedClaim:
    return ExtractedClaim(claim_text=text, source_text=text, grammar=grammar)


def test_classify_claims_v2_path_routes_each_shape_without_llm() -> None:
    claims = [
        _ec("L-Methionine is a member of cysteine metabolism",
            grammar=ClaimGrammar.PATHWAY_MEMBERSHIP),
        _ec("Arachidonic acid participates in eicosanoid metabolism via COX-2",
            grammar=ClaimGrammar.METABOLITE_PATHWAY_LINK),
        _ec("Galactose metabolism is enriched", grammar=ClaimGrammar.PATHWAY_ENRICHMENT),
        _ec("Methionine drives methionine cycle", grammar=ClaimGrammar.DRIVER_METABOLITE),
    ]
    classified, llm_calls = classify_claims(claims, trace_id="t_d3_v2_path")
    assert llm_calls == 0, "v2 grammar path must not invoke the classifier LLM"
    assert [c.claim_type for c in classified] == [
        ClaimType.BIOLOGICAL,
        ClaimType.BIOLOGICAL,
        ClaimType.SET_ENRICHMENT,
        ClaimType.DRIVER_METABOLITE,
    ]
    for c in classified:
        assert c.classifier_source == "rule", (
            f"v2-path claim should be source='rule'; got {c.classifier_source}"
        )
        assert c.grammar is not None, "grammar passthrough must survive into ClassifiedClaim"


# ---------------------------------------------------------------------------
# v1 legacy path preserved
# ---------------------------------------------------------------------------


def test_classify_claims_v1_legacy_no_grammar_uses_rule() -> None:
    """A legacy free-text claim (grammar=None) with a rule-recognised
    pattern goes through ``_rule_classify`` — no LLM call needed."""
    claims = [_ec("dCMP is in pyrimidine metabolism", grammar=None)]
    classified, llm_calls = classify_claims(claims, trace_id="t_d3_v1_path")
    assert llm_calls == 0
    assert classified[0].classifier_source == "rule"
    assert classified[0].claim_type == ClaimType.BIOLOGICAL
    assert classified[0].grammar is None


def test_classify_claims_mixed_v2_and_v1_only_v1_consults_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In a mixed batch, v2 claims short-circuit; only v1 ambiguous
    claims hit the LLM fallback."""
    captured: dict = {"called": False, "n_ambiguous": 0}

    def _fake_llm(texts, *, trace_id):
        captured["called"] = True
        captured["n_ambiguous"] = len(texts)
        return [ClaimType.BIOLOGICAL] * len(texts)

    monkeypatch.setattr(
        "verifier.claim_classifier._llm_classify", _fake_llm
    )

    claims = [
        _ec("Galactose metabolism is enriched", grammar=ClaimGrammar.PATHWAY_ENRICHMENT),
        # No grammar, no rule match → ambiguous → goes to LLM
        _ec("This sentence has no recognisable rule pattern", grammar=None),
    ]
    classified, llm_calls = classify_claims(claims, trace_id="t_mixed")
    assert llm_calls == 1
    assert captured["n_ambiguous"] == 1, (
        "v2 claim must NOT contribute to the LLM batch"
    )
    assert classified[0].claim_type == ClaimType.SET_ENRICHMENT  # v2
    assert classified[0].classifier_source == "rule"


# ---------------------------------------------------------------------------
# OTHER routing replaces silent BIOLOGICAL absorption
# ---------------------------------------------------------------------------


def test_parse_type_recognises_other_claim_token() -> None:
    """The Phase B1 D3 prompt change asks the LLM to emit
    ``other_claim`` for abstract single-compound regulatory sentences;
    the parser must accept that token."""
    assert _parse_type("other_claim") is ClaimType.OTHER
    assert _parse_type("other") is ClaimType.OTHER
    assert _parse_type("OTHER") is ClaimType.OTHER  # case-insensitive
    assert _parse_type("Other_Claim") is ClaimType.OTHER


def test_classify_legacy_polyamines_no_longer_routes_to_biological(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The v1 anti-pattern: 'Polyamines regulate protein synthesis'
    used to be auto-routed to BIOLOGICAL via a few-shot. Phase B1 D3
    rewrote that prompt to route to OTHER. We mock the LLM to return
    what the new prompt directs and assert the wiring."""
    def _fake_llm(texts, *, trace_id):
        return [ClaimType.OTHER for _ in texts]

    monkeypatch.setattr(
        "verifier.claim_classifier._llm_classify", _fake_llm
    )
    claims = [_ec("Polyamines regulate protein synthesis", grammar=None)]
    classified, _ = classify_claims(claims, trace_id="t_polyamines")
    assert classified[0].claim_type == ClaimType.OTHER, (
        "abstract single-compound sentence must route to OTHER, "
        "NOT to BIOLOGICAL (v1 anti-pattern)."
    )


# ---------------------------------------------------------------------------
# Sanity: ClaimType.OTHER exists
# ---------------------------------------------------------------------------


def test_claimtype_other_value() -> None:
    assert ClaimType.OTHER.value == "other_claim"

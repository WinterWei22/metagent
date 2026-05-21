"""W10 D3 P0-C — REGRESSION-LOCK tests for B1 D2 zero-LLM extract invariant.

P0-C in the W10 plan v1 was specified as "wire extract_claims_from_json
into ConcordMet verifier path". Pre-implementation recon during W10 D3
revealed that the wiring is **already implemented** in
``verifier/agent.py:_extract_classify`` by B1 D2 commit ``2354011`` —
predating the metagent-v2 merge.

The W10 P0-C scope therefore converts to **regression-lock**: pin the
existing zero-LLM-extract behaviour with explicit tests, so any future
commit that reorders the try/except in ``_extract_classify`` or
short-circuits the JSON path fails CI loudly.

3 invariants pinned:
  1. grammar-v2 JSON narrative → ``extract_calls == 0`` (JSON path used)
  2. dropped claims surface to the 4th tuple element (not silently lost)
  3. legacy prose narrative falls through to ``extract_claims`` (1 LLM call)

All 3 tests are **expected to PASS on the current tree** — they assert
existing behaviour. This is a strict-TDD-compliant variant: when the
production code already meets spec, the RED commit's role is to lock
the contract rather than to fail-then-pass.
"""
from __future__ import annotations

import json
from unittest.mock import patch

from verifier.agent import _extract_classify


def _make_valid_pathway_membership_claim(subject: str, pathway_name: str, claim_text: str) -> dict:
    """Build a grammar-v2 PATHWAY_MEMBERSHIP claim that passes validate().

    Required fields per ``verifier.grammar.REQUIRED_FIELDS``: subject,
    pathway_name (plus the always-required grammar + claim_text).
    """
    return {
        "grammar": "pathway_membership",
        "claim_text": claim_text,
        "subject": subject,
        "pathway_name": pathway_name,
    }


def test_grammar_v2_json_narrative_triggers_zero_llm_extract():
    """REGRESSION LOCK: verify_sub6 must route grammar-v2 JSON narratives
    through ``extract_claims_from_json`` (zero LLM call).

    Inherited from B1 D2 commit 2354011 in
    ``verifier/agent.py:_extract_classify`` (lines 272-287). If a future
    commit reorders the try/except or short-circuits the JSON path,
    this test fails loudly.
    """
    json_narrative = json.dumps({
        "narrative_text": "Tyrosine participates in tyrosine metabolism.",
        "claims": [
            _make_valid_pathway_membership_claim(
                subject="Tyrosine",
                pathway_name="Tyrosine metabolism",
                claim_text="Tyrosine belongs to the tyrosine metabolism pathway.",
            ),
        ],
    })

    classified, llm_calls, warnings, dropped = _extract_classify(
        json_narrative, trace_id="w10_d3.zero_llm.t1"
    )

    assert llm_calls == 0, (
        f"JSON narrative must trigger zero LLM call for extract; got llm_calls={llm_calls}. "
        "Regression: _extract_classify's try-block for extract_claims_from_json "
        "may have been reordered or removed."
    )
    assert classified is not None, "JSON path must produce a classified list, not None"
    assert len(classified) >= 1, (
        "JSON path produced 0 classified claims from a 1-claim payload — extract path likely silently failed"
    )


def test_grammar_v2_json_dropped_claims_surface_to_verdict():
    """REGRESSION LOCK: dropped claims (grammar-violating entries in JSON)
    must surface to the 4th tuple element of ``_extract_classify``, not
    vanish silently.

    Without surfacing, ``VerifiedIdentification.dropped_claims`` ends up
    empty, breaking the W10 D2 P0-B feedback-builder's ``dropped=`` kwarg
    (which reads from there).
    """
    json_narrative = json.dumps({
        "narrative_text": "Tyrosine participates in tyrosine metabolism.",
        "claims": [
            _make_valid_pathway_membership_claim(
                subject="Tyrosine",
                pathway_name="Tyrosine metabolism",
                claim_text="Tyrosine belongs to the tyrosine metabolism pathway.",
            ),
            # Grammar-violating: claims pathway_membership shape but
            # missing the required pathway_name field.
            {
                "grammar": "pathway_membership",
                "claim_text": "Some incomplete claim with no pathway.",
                "subject": "Glucose",
            },
        ],
    })

    classified, llm_calls, warnings, dropped = _extract_classify(
        json_narrative, trace_id="w10_d3.zero_llm.t2"
    )

    assert llm_calls == 0, f"JSON path should be zero LLM call; got {llm_calls}"
    assert len(dropped) == 1, (
        f"Expected 1 dropped claim from grammar-violating entry; got {len(dropped)}. "
        "Regression: dropped list may not be surfacing from extract_claims_from_json."
    )
    drop = dropped[0]
    assert drop.drop_reason, "DroppedClaim.drop_reason must be populated"
    assert drop.claim_text == "Some incomplete claim with no pathway."


def test_non_json_narrative_falls_through_to_llm_extract():
    """REGRESSION LOCK: legacy A3-style prose narrative (no JSON object)
    must fall through to ``extract_claims`` (1 LLM call). Backward-compat
    guarantee for non-grammar-v2 evaluation paths.

    Without the fallthrough, prose narratives would crash on
    ClaimExtractionError instead of being processed.
    """
    prose_narrative = (
        "Tyrosine is significantly enriched in the tyrosine metabolism "
        "pathway, where it serves as a precursor to several neurotransmitters."
    )

    # The LLM extract path returns a JSON list of {claim_text, subject}
    # dicts that the legacy extractor's _parse_claim_list consumes.
    mock_extractor_response = json.dumps([
        {
            "claim_text": "Tyrosine is significantly enriched in the tyrosine metabolism pathway.",
            "subject": "Tyrosine",
        },
    ])

    with patch("verifier.claim_extractor.chat", return_value=mock_extractor_response) as mock_chat:
        classified, llm_calls, warnings, dropped = _extract_classify(
            prose_narrative, trace_id="w10_d3.zero_llm.t3"
        )

    assert mock_chat.called, (
        "Prose narrative must invoke the LLM-based extract_claims path. "
        "Regression: _extract_classify's except-branch for ClaimExtractionError "
        "may have been swallowed or removed."
    )
    assert llm_calls == 1, (
        f"Prose fallthrough must report exactly 1 LLM call; got {llm_calls}. "
        "Regression: extract_calls bookkeeping may be off."
    )
    assert classified is not None
    assert len(dropped) == 0, (
        "Prose path should produce no dropped claims (legacy extractor has no grammar gate)"
    )

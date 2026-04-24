"""Unit tests for Stage 4 rewriter."""
from __future__ import annotations

from common import llm_client
from verifier.rewriter import is_rewrite_needed, rewrite
from verifier.schemas import ClaimType, ClaimVerdict, VerifiedClaim


def _vc(text, verdict, *, correction=None):
    return VerifiedClaim(
        claim_text=text, claim_type=ClaimType.GROUNDED,
        verdict=verdict, evidence="X",
        source_field="X", correction=correction,
    )


# ---------------------------------------------------------------------------
# is_rewrite_needed
# ---------------------------------------------------------------------------


def test_no_rewrite_when_all_supported():
    assert is_rewrite_needed([_vc("A", ClaimVerdict.SUPPORTED)]) is False


def test_rewrite_needed_for_contradicted():
    assert is_rewrite_needed([_vc("A", ClaimVerdict.CONTRADICTED, correction="B")]) is True


def test_rewrite_needed_for_unsupported():
    assert is_rewrite_needed([_vc("A", ClaimVerdict.UNSUPPORTED)]) is True


def test_rewrite_needed_for_unverifiable_v0():
    assert is_rewrite_needed([_vc("A", ClaimVerdict.UNVERIFIABLE_V0)]) is True


def test_rewrite_not_needed_for_error():
    # ERROR surfaces to warnings; rewriter shouldn't pretend to fix it.
    assert is_rewrite_needed([_vc("A", ClaimVerdict.ERROR)]) is False


def test_rewrite_preserves_supported_claims():
    # When both supported and actionable claims exist, only actionable
    # ones pass to the prompt; supported claims are expected to survive
    # by the LLM's instruction to preserve "every other claim verbatim".
    llm_client.set_mock([
        "## REPORT\n**1. D-Gulose (C6H12O6)**\nGlucose has C6H12O6."
    ])
    out = rewrite(
        source_llm_output="## REPORT\n**1. D-Gulose (C7H14O7)**\n"
                          "Glucose has C6H12O6.",
        verified_claims=[
            _vc("D-Gulose has C7H14O7", ClaimVerdict.CONTRADICTED,
                correction="C6H12O6"),
            _vc("Glucose has C6H12O6", ClaimVerdict.SUPPORTED),
        ],
        trace_id="t6",
    )
    assert "C6H12O6" in out
    assert "C7H14O7" not in out


def test_rewrite_empty_edits_returns_original_without_llm_call():
    llm_client.set_mock([])  # would IndexError if called
    out = rewrite(
        source_llm_output="UNCHANGED",
        verified_claims=[_vc("A", ClaimVerdict.SUPPORTED)],
        trace_id="t7",
    )
    assert out == "UNCHANGED"

"""W14.A D2 RED — grammar NOISE_PATTERN subtype + noise-claim detection (5 cases).

Pins the contract a new `DroppedReason` enum + noise-pattern detector
in `verifier/grammar.py` must satisfy. Noise patterns target W11 C8 +
C9 strict_noise: meta-filler, template boilerplate, self-reference,
pasted prompt fragments — all carry zero biological information and
should be DROPPED at validation, not routed through layer dispatch.

W14 §0 re-classification (commit 2026-05-25): 14 / 148 C8+C9 claims
are strict_noise (= 1.27 pp ceiling on W11 baseline). The GREEN
commit will add infrastructure to drop these explicitly.

Expected at RED:
  - case 1 (enum exists)         FAIL (ERROR: DroppedReason not defined)
  - cases 2-4 (validator marks)  FAIL (no noise check in validator)
  - case 5 (regression)          PASS (current validator does not
                                  misclassify real claims as noise)
"""
from __future__ import annotations

import pytest


def _claim_dict(claim_text: str) -> dict:
    """Minimal pathway_membership grammar dict for validation tests."""
    return {
        "grammar": "pathway_membership",
        "claim_text": claim_text,
        "subject": "L-tyrosine",
        "pathway_name": "Tyrosine metabolism",
    }


def test_dropped_reason_noise_pattern_enum_exists():
    """Case 1 — `verifier.grammar.DroppedReason` enum exists with value
    `NOISE_PATTERN` for W14.A grammar-level noise detection.

    Expected at RED: FAIL (ERROR — DroppedReason does not exist in
    current grammar.py; `drop_reason` is a plain `str | None`).
    """
    from verifier.grammar import DroppedReason

    assert hasattr(DroppedReason, "NOISE_PATTERN"), (
        "DroppedReason enum must define NOISE_PATTERN per W14.A spec"
    )
    assert DroppedReason.NOISE_PATTERN.value == "noise_pattern"


def test_validator_marks_meta_filler_as_noise():
    """Case 2 — meta-filler text ("以上是分析结果") in claim_text →
    validator drops the claim with a noise-pattern signal.

    Expected at RED: FAIL (current validator has no noise check).
    """
    from verifier.grammar import validate

    result = validate(_claim_dict("以上是分析结果,tyrosine 出现在通路中"))

    assert not result.is_valid, (
        f"meta-filler claim should be dropped; got is_valid=True"
    )
    assert "noise" in (result.drop_reason or "").lower(), (
        f"drop_reason should mention 'noise'; got {result.drop_reason!r}"
    )


def test_validator_marks_template_boilerplate_as_noise():
    """Case 3 — template boilerplate ("future work suggests further...")
    → validator drops with noise signal.

    Expected at RED: FAIL.
    """
    from verifier.grammar import validate

    result = validate(_claim_dict(
        "Future work suggests further investigation into tyrosine metabolism."
    ))

    assert not result.is_valid, (
        f"template-boilerplate claim should be dropped; got is_valid=True"
    )
    assert "noise" in (result.drop_reason or "").lower(), (
        f"drop_reason should mention 'noise'; got {result.drop_reason!r}"
    )


def test_validator_marks_self_reference_as_noise():
    """Case 4 — self-reference ("as mentioned above" / "如上所述") →
    validator drops with noise signal.

    Expected at RED: FAIL.
    """
    from verifier.grammar import validate

    result = validate(_claim_dict(
        "As mentioned above, tyrosine is implicated in this pathway."
    ))

    assert not result.is_valid, (
        f"self-reference claim should be dropped; got is_valid=True"
    )
    assert "noise" in (result.drop_reason or "").lower(), (
        f"drop_reason should mention 'noise'; got {result.drop_reason!r}"
    )


def test_validator_does_not_mark_real_claim_as_noise():
    """Case 5 (regression) — real biology claim must NOT be marked as
    noise. Validator currently passes such claims; W14.A noise check
    must preserve this.

    Expected at RED: PASS (regression baseline).
    """
    from verifier.grammar import validate

    result = validate(_claim_dict(
        "L-tyrosine is a member of the Tyrosine metabolism pathway."
    ))

    assert result.is_valid, (
        f"real biology claim must not be flagged as noise; got "
        f"is_valid=False, drop_reason={result.drop_reason!r}"
    )

"""Test for the new ClaimVerdict.INSUFFICIENT_EVIDENCE enum member.

Task 5: Add INSUFFICIENT_EVIDENCE verdict (pool-absent but checkable,
distinct from UNVERIFIABLE_V0 which is out-of-paradigm).
"""

from verifier.schemas import ClaimVerdict


def test_insufficient_evidence_exists():
    """INSUFFICIENT_EVIDENCE enum value must exist with correct string value."""
    assert hasattr(ClaimVerdict, "INSUFFICIENT_EVIDENCE"), \
        "ClaimVerdict.INSUFFICIENT_EVIDENCE does not exist"
    assert ClaimVerdict.INSUFFICIENT_EVIDENCE.value == "insufficient_evidence"


def test_insufficient_evidence_is_enum_member():
    """INSUFFICIENT_EVIDENCE must be a valid ClaimVerdict enum member."""
    verdict = ClaimVerdict.INSUFFICIENT_EVIDENCE
    assert isinstance(verdict, ClaimVerdict)
    assert verdict.name == "INSUFFICIENT_EVIDENCE"

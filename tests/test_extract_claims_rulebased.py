"""Unit tests for the Phase 6.4 rule-based claim extractor."""
from __future__ import annotations

from verifier.claim_extractor import extract_claims_rulebased


def test_empty_input_returns_empty():
    assert extract_claims_rulebased("") == []
    assert extract_claims_rulebased("   \n  ") == []


def test_single_line_one_claim():
    out = extract_claims_rulebased("The metabolite cluster suggests xenobiotic detoxification.")
    assert len(out) == 1
    assert "xenobiotic" in out[0].claim_text


def test_bullet_list_yields_per_bullet_claim():
    text = """Justification: candidate 0 (testosterone) is supported.
Peak-level claims:
  - m/z 109.0648 corresponds to fragment of A-ring enone
  - m/z 81.0699 arises from loss of H2O from m/z 99.08
  - m/z 271.2056 corresponds to loss of H2O from [M+H]+
"""
    out = extract_claims_rulebased(text)
    # 1 justification line + 3 bullet claims = 4
    assert len(out) >= 4
    bullet_texts = [c.claim_text for c in out]
    assert any("m/z 109.0648" in t and "fragment" in t for t in bullet_texts)
    assert any("loss of H2O" in t for t in bullet_texts)


def test_compound_mechanistic_phrase_preserved():
    """The KEY behavioural test — line stays intact, both m/z and
    mechanism keyword survive into a single claim."""
    text = "  - m/z 138.0660 corresponds to loss of methyl group (-CH3) from caffeine"
    out = extract_claims_rulebased(text)
    assert len(out) == 1
    assert "m/z 138.0660" in out[0].claim_text
    assert "loss of methyl" in out[0].claim_text
    assert out[0].peak_mz is not None
    # Layer F regex contract: claim_text must contain BOTH a m/z number
    # and a mechanism keyword.
    import re
    text = out[0].claim_text
    assert re.search(r"\bm/z\s*=?\s*\d", text, re.IGNORECASE)
    assert re.search(r"loss\s+of|fragment|arises\s+from", text, re.IGNORECASE)


def test_sentence_split_only_on_uppercase_start():
    """Sentence regex `(?<=[.!?])\\s+(?=[A-Z])` splits only when next
    sentence starts with capital letter — protects against false splits
    on abbreviations like 'm/z' or 'C8H10N4O2'."""
    # Two sentences with second starting uppercase: split → 2 claims.
    text2 = "Candidate 0 is testosterone. The mass match is exact at 5 ppm."
    out2 = extract_claims_rulebased(text2)
    assert len(out2) == 2
    # Sentence followed by lowercase 'm/z': stays as 1 claim (preserves
    # mechanistic compound phrases like "X. m/z 138 ...").
    text1 = "Candidate 0 is testosterone. m/z 109.0648 corresponds to fragment."
    out1 = extract_claims_rulebased(text1)
    assert len(out1) == 1


def test_does_not_break_on_brackets():
    """[M+H]+ embedded in claim should not corrupt sentence boundaries."""
    text = "  - m/z 271.2056 corresponds to loss of H2O from [M+H]+ precursor"
    out = extract_claims_rulebased(text)
    assert len(out) == 1
    assert "[M+H]+" in out[0].claim_text


def test_short_fragments_dropped():
    text = "OK.\n  - hi\n  - m/z 138.07 corresponds to loss of methyl"
    out = extract_claims_rulebased(text)
    # "OK" and "hi" filtered (< 8 chars after strip)
    assert all(len(c.claim_text) >= 8 for c in out)
    assert any("m/z 138.07" in c.claim_text for c in out)


def test_layer_f_eligible_count_on_realistic_narrative():
    """Sanity: Phase 6.3 LLM-as-reranker output → many Layer-F-eligible
    sentences (m/z + mechanism in same line)."""
    text = """Spectrum sub6a-gnps-CCMSLIB00006403004 (precursor m/z 289.22).
Selected top-1: testosterone (confidence: high).
Justification: Candidate 0 has near-perfect modified cosine 0.999 and CFM-ID cosine 0.336.
Peak-level claims:
  - m/z 109.0648 corresponds to fragment of A-ring enone [C7H9O]+ from testosterone
  - m/z 97.0640 corresponds to fragment of [C6H9O]+ from A-ring retro-cleavage
  - m/z 81.0690 corresponds to loss of H2O from the 109.064 A-ring cation
  - m/z 271.2056 corresponds to loss of H2O from the [M+H]+ precursor at 289.22
"""
    import re
    out = extract_claims_rulebased(text)
    eligible = sum(
        1 for c in out
        if re.search(r"\bm/z\s*=?\s*\d", c.claim_text, re.IGNORECASE)
        and re.search(r"loss\s+of|fragment|arises\s+from", c.claim_text, re.IGNORECASE)
    )
    assert eligible >= 4, f"expected ≥4 Layer-F-eligible, got {eligible} (claims: {[c.claim_text for c in out]})"

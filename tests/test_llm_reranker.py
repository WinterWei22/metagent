"""Unit tests for evaluation/sub6/llm_reranker.py."""
from __future__ import annotations

import json

import pytest

from evaluation.sub6.llm_reranker import (
    LlmRerankResult,
    build_reranker_messages,
    llm_rerank,
    parse_reranker_response,
    render_narrative,
)


@pytest.fixture
def spectrum_meta():
    return {
        "spectrum_id": "spec-1",
        "precursor_mz": 195.0877,
        "ion_mode": "positive",
        "adduct": "[M+H]+",
        "experimental_peaks": [[42.034, 0.4], [110.071, 1.0], [138.066, 0.68], [195.088, 0.5]],
    }


@pytest.fixture
def candidates():
    return [
        {
            "rank_after_primary": 1,
            "smiles": "Cn1cnc2c1c(=O)n(C)c(=O)n2C",
            "name": "caffeine",
            "formula": "C8H10N4O2",
            "primary_retriever": "msclip",
            "primary_retriever_score": 0.71,
            "modcos": 0.82, "msclip": 0.71,
            "mass_match": 1.0,
            "sirius_top1_formula": "C8H10N4O2", "sirius_formula_match": True,
            "cfmid_top_peaks": [[42.034, 0.4], [110.071, 0.6], [138.066, 1.0]],
            "cfmid_cosine_vs_experimental": 0.85,
        },
        {
            "rank_after_primary": 2,
            "smiles": "OCc1ccc(O)cc1", "name": "p-hydroxybenzyl alcohol",
            "formula": "C7H8O2",
            "primary_retriever": "msclip",
            "primary_retriever_score": 0.45,
            "modcos": 0.50, "msclip": 0.45,
            "mass_match": 0.0,
            "sirius_top1_formula": "C8H10N4O2", "sirius_formula_match": False,
            "cfmid_top_peaks": [[80.0, 1.0]],
            "cfmid_cosine_vs_experimental": 0.20,
        },
    ]


# ---- prompt assembly ----

def test_build_messages_under_token_budget(spectrum_meta, candidates):
    msgs = build_reranker_messages(spectrum_meta, candidates)
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    # Crude token sanity: total chars / 4 ~= tokens.
    total_chars = sum(len(m["content"]) for m in msgs)
    assert total_chars < 16_000, f"prompt too big: {total_chars} chars"


def test_user_payload_includes_required_fields(spectrum_meta, candidates):
    msgs = build_reranker_messages(spectrum_meta, candidates)
    user = msgs[1]["content"]
    assert "spec-1" in user
    assert "caffeine" in user
    # JSON schema words appear in system prompt.
    sys = msgs[0]["content"]
    assert "selected_top1_index" in sys
    assert "peak_claims" in sys


def test_cfmid_peaks_capped(spectrum_meta):
    cands = [{
        "smiles": "X", "name": "x", "formula": "X", "primary_retriever": "msclip",
        "primary_retriever_score": 0.5, "modcos": 0.5, "msclip": 0.5,
        "mass_match": 0.0,
        "cfmid_top_peaks": [[float(i), 1.0/(i+1)] for i in range(50)],  # 50 peaks
        "cfmid_cosine_vs_experimental": 0.5,
        "rank_after_primary": 1,
    }]
    msgs = build_reranker_messages(spectrum_meta, cands)
    user_text = msgs[1]["content"]
    payload = json.loads(user_text.split("```json")[1].split("```")[0].strip())
    assert len(payload["candidates"][0]["cfmid_top_peaks"]) <= 10


# ---- parser ----

def test_parse_clean_json():
    raw = '{"selected_top1_index": 0, "selected_top1_smiles": "X", "confidence": "high", "justification": "ok", "peak_claims": ["m/z 138 corresponds to loss of CH3"]}'
    parsed, err = parse_reranker_response(raw)
    assert err is None and parsed["selected_top1_index"] == 0


def test_parse_with_code_fences():
    raw = '```json\n{"selected_top1_index": 1, "selected_top1_smiles": "Y", "confidence": "low", "justification": "x", "peak_claims": []}\n```'
    parsed, err = parse_reranker_response(raw)
    assert err is None and parsed["selected_top1_index"] == 1


def test_parse_with_leading_prose():
    raw = "Sure, here is my answer:\n\n{\"selected_top1_index\": 0, \"selected_top1_smiles\": \"Z\", \"confidence\": \"medium\", \"justification\": \"ok\", \"peak_claims\": [\"m/z 50 fragments from M+H\"]}"
    parsed, err = parse_reranker_response(raw)
    assert err is None and parsed["selected_top1_smiles"] == "Z"


def test_parse_garbage_returns_error():
    parsed, err = parse_reranker_response("this is not json at all")
    assert parsed is None and err is not None


# ---- Phase 6.7 parser defense ----

def test_parse_fenced_json_with_surrounding_prose():
    """Opus often emits 'Here is the result: ```json {...} ```'."""
    raw = (
        "Here is my analysis:\n\n"
        "```json\n"
        '{"selected_top1_index": 1, "selected_top1_smiles": "CCO"}\n'
        "```\n"
        "Hope that helps!"
    )
    parsed, err = parse_reranker_response(raw)
    assert err is None
    assert parsed == {"selected_top1_index": 1, "selected_top1_smiles": "CCO"}


def test_parse_thinking_block_with_stray_brace():
    """<thinking> blocks often contain literal '{' that confuse the greedy
    brace-finder. We strip them BEFORE searching for JSON."""
    raw = (
        "<thinking>\n"
        "Let me consider: the formula {C8H10O} matches several candidates.\n"
        "I should pick rank 0.\n"
        "</thinking>\n"
        '{"selected_top1_index": 0, "selected_top1_smiles": "c1ccccc1"}'
    )
    parsed, err = parse_reranker_response(raw)
    assert err is None
    assert parsed["selected_top1_index"] == 0


def test_parse_already_valid_json_regression():
    """Defensive additions must not break the simple-input case."""
    raw = '{"selected_top1_index": 2, "selected_top1_smiles": "C", "confidence": "high"}'
    parsed, err = parse_reranker_response(raw)
    assert err is None
    assert parsed["confidence"] == "high"


# ---- Phase 6.7-A ranked_indices ----

def _make_cands(n: int) -> list[dict]:
    """Synthesise n minimal candidate dicts with valid required fields."""
    return [{
        "rank_after_primary": i + 1,
        "smiles": f"C{'C'*i}",
        "name": f"cand{i}",
        "formula": "C2H6O",
        "primary_retriever": "msclip",
        "primary_retriever_score": 0.5 - i * 0.05,
        "modcos": 0.4, "msclip": 0.5 - i * 0.05,
        "mass_match": 1.0,
        "sirius_top1_formula": "C2H6O", "sirius_formula_match": True,
        "cfmid_top_peaks": [[46.0, 1.0]],
        "cfmid_cosine_vs_experimental": 0.5,
    } for i in range(n)]


def test_ranked_indices_clean_permutation(spectrum_meta):
    """LLM emits a valid full permutation — must round-trip exactly."""
    cands = _make_cands(3)
    def _chat(messages, **kw):
        return (
            '{"selected_top1_index": 2, "selected_top1_smiles": "CCC", '
            '"ranked_indices": [2, 0, 1], '
            '"confidence": "high", '
            '"justification": "sirius confirms, cfm cosine 0.91 vs experimental",'
            '"peak_claims": ["m/z 60.0813 corresponds to fragment of CH4N2"]}'
        )
    res = llm_rerank(spectrum_meta, cands, chat_fn=_chat)
    assert res.selected_top1_index == 2
    assert res.ranked_indices == [2, 0, 1]
    assert res.fallback_used is False


def test_ranked_indices_recovers_from_missing_field(spectrum_meta):
    """When LLM omits ranked_indices, _coerce_ranked_indices must synthesise
    a valid permutation with selected_top1_index in position 0."""
    cands = _make_cands(4)
    def _chat(messages, **kw):
        return (
            '{"selected_top1_index": 1, "selected_top1_smiles": "CC", '
            '"confidence": "medium", '
            '"justification": "modcos 0.7 highest",'
            '"peak_claims": ["m/z 45.0335 corresponds to fragment of CHO2"]}'
        )
    res = llm_rerank(spectrum_meta, cands, chat_fn=_chat)
    # Coercion should put 1 first, then primary order (0,2,3).
    assert res.ranked_indices == [1, 0, 2, 3]
    assert res.fallback_used is False


def test_ranked_indices_recovers_from_partial_list(spectrum_meta):
    """Partial / out-of-range / duplicate indices should be repaired."""
    cands = _make_cands(4)
    def _chat(messages, **kw):
        return (
            '{"selected_top1_index": 0, "selected_top1_smiles": "C", '
            '"ranked_indices": [0, 5, 0, 2, -1], '   # contains OOR + duplicate
            '"confidence": "low", '
            '"justification": "marginal cfm cosine 0.12",'
            '"peak_claims": ["m/z 31.0184 corresponds to fragment of CH3O"]}'
        )
    res = llm_rerank(spectrum_meta, cands, chat_fn=_chat)
    # Dedupe + clamp + fill missing in primary order → [0, 2, 1, 3].
    assert res.ranked_indices[0] == 0
    assert sorted(res.ranked_indices) == [0, 1, 2, 3]
    assert len(set(res.ranked_indices)) == 4


# ---- happy path ----

def test_llm_rerank_picks_high_consensus_candidate(spectrum_meta, candidates):
    def _mock_chat(messages, **kw):
        return json.dumps({
            "selected_top1_index": 0,
            "selected_top1_smiles": "Cn1cnc2c1c(=O)n(C)c(=O)n2C",
            "confidence": "high",
            "justification": "Candidate 0 (caffeine) has SIRIUS top-1 formula C8H10N4O2 matching, CFM-ID cosine 0.85.",
            "peak_claims": [
                "m/z 138.0660 corresponds to loss of methyl (-CH3) from caffeine",
                "m/z 110.0710 arises from subsequent loss of -CO from m/z 138.07",
            ],
        })
    res = llm_rerank(spectrum_meta, candidates, chat_fn=_mock_chat)
    assert res.selected_top1_index == 0
    assert res.fallback_used is False
    assert "C8H10N4O2" in res.justification
    assert len(res.peak_claims) == 2


# ---- failure paths ----

def test_llm_rerank_fallback_on_parse_failure(spectrum_meta, candidates):
    def _bad(messages, **kw):
        return "I cannot help with that."
    res = llm_rerank(spectrum_meta, candidates, chat_fn=_bad, max_retries=0)
    assert res.fallback_used is True
    assert res.selected_top1_index == 0  # primary top-1
    assert res.confidence == "low"


def test_llm_rerank_fallback_on_invalid_index(spectrum_meta, candidates):
    def _out_of_range(messages, **kw):
        return json.dumps({
            "selected_top1_index": 99, "selected_top1_smiles": "x",
            "confidence": "high", "justification": "x", "peak_claims": [],
        })
    res = llm_rerank(spectrum_meta, candidates, chat_fn=_out_of_range, max_retries=0)
    assert res.fallback_used is True


def test_llm_rerank_retry_on_first_failure(spectrum_meta, candidates):
    calls = []
    def _first_bad_then_good(messages, **kw):
        calls.append(1)
        if len(calls) == 1:
            return "garbage not json"
        return json.dumps({
            "selected_top1_index": 0, "selected_top1_smiles": "Cn1cnc2c1c(=O)n(C)c(=O)n2C",
            "confidence": "medium", "justification": "x", "peak_claims": ["m/z 138 loss of CH3"],
        })
    res = llm_rerank(spectrum_meta, candidates, chat_fn=_first_bad_then_good, max_retries=1)
    assert res.fallback_used is False and len(calls) == 2


def test_llm_rerank_chat_exception_falls_back(spectrum_meta, candidates):
    def _crash(messages, **kw):
        raise RuntimeError("network down")
    res = llm_rerank(spectrum_meta, candidates, chat_fn=_crash, max_retries=0)
    assert res.fallback_used is True
    assert "network down" in (res.parse_error or "")


# ---- narrative rendering ----

def test_render_narrative_contains_peak_mz_pattern(spectrum_meta):
    result = LlmRerankResult(
        selected_top1_index=0, selected_top1_smiles="X",
        confidence="high",
        justification="strong consensus",
        peak_claims=["m/z 138.0660 corresponds to loss of -CH3"],
        raw_llm_output="",
    )
    narrative = render_narrative(spectrum_meta, result)
    assert "m/z 138.0660" in narrative
    # Layer F regex pattern compatibility
    import re
    assert re.search(r"\bm/z\s*=?\s*\d", narrative)
    assert re.search(r"loss\s+of", narrative)

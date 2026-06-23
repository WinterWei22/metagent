"""Tests for PathwayNameMatcher — 全部走 fallback 路径，无需下载 SapBERT 模型。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from concord.lookup.pathway_name_matcher import (
    PathwayMatchResult,
    PathwayNameMatcher,
)


# ---------------------------------------------------------------------------
# Fixture：始终无模型的 matcher（encoder=None，fallback=True）
# ---------------------------------------------------------------------------

@pytest.fixture()
def matcher_fallback() -> PathwayNameMatcher:
    """PathwayNameMatcher，强制 encoder=None 以测试 fallback 路径。"""
    with patch(
        "concord.lookup.pathway_name_matcher.SapBertEncoder",
        side_effect=RuntimeError("no model"),
    ):
        m = PathwayNameMatcher(fallback_to_token_overlap=True)
    return m


@pytest.fixture()
def matcher_no_fallback() -> PathwayNameMatcher:
    """PathwayNameMatcher，无模型且 fallback=False。"""
    with patch(
        "concord.lookup.pathway_name_matcher.SapBertEncoder",
        side_effect=RuntimeError("no model"),
    ):
        m = PathwayNameMatcher(fallback_to_token_overlap=False)
    return m


# ---------------------------------------------------------------------------
# 辅助：构造假 embedding matcher
# ---------------------------------------------------------------------------

def _make_embedding_matcher(
    threshold: float = 0.80,
    embed_map: dict[str, list[float]] | None = None,
) -> PathwayNameMatcher:
    """返回一个 encoder.available=True 的 matcher，embed_map 控制返回向量。"""
    embed_map = embed_map or {}

    mock_encoder = MagicMock()
    mock_encoder.available = True

    def fake_encode(texts: list[str]) -> list[list[float]]:
        return [embed_map.get(t, [1.0, 0.0]) for t in texts]

    mock_encoder.encode.side_effect = fake_encode

    with patch(
        "concord.lookup.pathway_name_matcher.SapBertEncoder",
        return_value=mock_encoder,
    ):
        m = PathwayNameMatcher(threshold=threshold)
    return m


# ---------------------------------------------------------------------------
# 1. Substring / token-overlap 必过
# ---------------------------------------------------------------------------

class TestFallbackBasicHits:
    def test_exact_match(self, matcher_fallback: PathwayNameMatcher) -> None:
        assert matcher_fallback.is_hit("Tyrosine metabolism", ["Tyrosine metabolism"])

    def test_token_content_subset(self, matcher_fallback: PathwayNameMatcher) -> None:
        # "catabolism" 是 suffix token，stripped 后内容 token 相同 → hit
        assert matcher_fallback.is_hit("Tyrosine metabolism", ["Tyrosine catabolism"])

    def test_substring_tca(self, matcher_fallback: PathwayNameMatcher) -> None:
        assert matcher_fallback.is_hit("TCA cycle", ["Citrate cycle (TCA cycle)"])

    def test_case_insensitive(self, matcher_fallback: PathwayNameMatcher) -> None:
        assert matcher_fallback.is_hit(
            "arachidonic acid metabolism", ["Arachidonic acid metabolism"]
        )

    def test_no_hit_unrelated(self, matcher_fallback: PathwayNameMatcher) -> None:
        assert not matcher_fallback.is_hit(
            "Completely unrelated pathway", ["Tyrosine metabolism"]
        )

    def test_multiple_candidates_one_hit(self, matcher_fallback: PathwayNameMatcher) -> None:
        assert matcher_fallback.is_hit(
            "Tyrosine metabolism",
            ["Glycolysis", "Tyrosine catabolism", "Fatty acid biosynthesis"],
        )

    def test_multiple_candidates_no_hit(self, matcher_fallback: PathwayNameMatcher) -> None:
        assert not matcher_fallback.is_hit(
            "Tyrosine metabolism",
            ["Glycolysis", "Fatty acid biosynthesis"],
        )

    def test_no_false_broad_match(self, matcher_fallback: PathwayNameMatcher) -> None:
        # "Cysteine" ≠ "Methionine"
        assert not matcher_fallback.is_hit("Cysteine metabolism", ["Methionine metabolism"])


# ---------------------------------------------------------------------------
# 2. 空输入处理
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_candidates(self, matcher_fallback: PathwayNameMatcher) -> None:
        assert not matcher_fallback.is_hit("Tyrosine metabolism", [])

    def test_empty_query(self, matcher_fallback: PathwayNameMatcher) -> None:
        assert not matcher_fallback.is_hit("", ["Tyrosine metabolism"])

    def test_empty_both(self, matcher_fallback: PathwayNameMatcher) -> None:
        assert not matcher_fallback.is_hit("", [])

    def test_match_empty_query(self, matcher_fallback: PathwayNameMatcher) -> None:
        r = matcher_fallback.match("", "Tyrosine metabolism")
        assert not r.hit

    def test_match_empty_candidate(self, matcher_fallback: PathwayNameMatcher) -> None:
        r = matcher_fallback.match("Tyrosine metabolism", "")
        assert not r.hit

    def test_match_any_empty_candidates(self, matcher_fallback: PathwayNameMatcher) -> None:
        r = matcher_fallback.match_any("Tyrosine metabolism", [])
        assert not r.hit
        assert r.candidate == ""


# ---------------------------------------------------------------------------
# 3. PathwayMatchResult 字段完整性
# ---------------------------------------------------------------------------

class TestResultFields:
    def test_fields_present_hit(self, matcher_fallback: PathwayNameMatcher) -> None:
        r = matcher_fallback.match("Tyrosine metabolism", "Tyrosine catabolism")
        assert isinstance(r, PathwayMatchResult)
        assert r.query == "Tyrosine metabolism"
        assert r.candidate == "Tyrosine catabolism"
        assert isinstance(r.score, float)
        assert isinstance(r.hit, bool)
        assert isinstance(r.method, str)
        assert isinstance(r.threshold, float)
        assert r.hit is True

    def test_fields_present_miss(self, matcher_fallback: PathwayNameMatcher) -> None:
        r = matcher_fallback.match("Glycolysis", "Tyrosine metabolism")
        assert r.hit is False
        assert r.score == -1.0   # fallback 无 embedding 时固定 -1

    def test_method_fallback_label(self, matcher_fallback: PathwayNameMatcher) -> None:
        r = matcher_fallback.match("TCA cycle", "Citrate cycle (TCA cycle)")
        assert r.method in ("substring", "token_overlap")

    def test_threshold_propagated(self, matcher_fallback: PathwayNameMatcher) -> None:
        with patch(
            "concord.lookup.pathway_name_matcher.SapBertEncoder",
            side_effect=RuntimeError("no model"),
        ):
            m = PathwayNameMatcher(threshold=0.75, fallback_to_token_overlap=True)
        r = m.match("Glycolysis", "Glycolysis")
        assert r.threshold == 0.75


# ---------------------------------------------------------------------------
# 4. match_any 返回最高分
# ---------------------------------------------------------------------------

class TestMatchAny:
    def test_returns_best_match(self, matcher_fallback: PathwayNameMatcher) -> None:
        r = matcher_fallback.match_any(
            "Tyrosine metabolism",
            ["Glycolysis", "Tyrosine catabolism", "Fatty acid biosynthesis"],
        )
        assert r.hit is True
        assert r.candidate == "Tyrosine catabolism"

    def test_returns_any_when_no_hit(self, matcher_fallback: PathwayNameMatcher) -> None:
        r = matcher_fallback.match_any("Completely unrelated", ["Glycolysis", "Fatty acid"])
        assert r.hit is False


# ---------------------------------------------------------------------------
# 5. no_fallback 模式
# ---------------------------------------------------------------------------

class TestNoFallback:
    def test_no_hit_when_no_model_no_fallback(
        self, matcher_no_fallback: PathwayNameMatcher
    ) -> None:
        assert not matcher_no_fallback.is_hit("Tyrosine metabolism", ["Tyrosine metabolism"])

    def test_match_returns_false_when_no_model_no_fallback(
        self, matcher_no_fallback: PathwayNameMatcher
    ) -> None:
        r = matcher_no_fallback.match("Tyrosine metabolism", "Tyrosine catabolism")
        assert r.hit is False
        assert r.score == -1.0


# ---------------------------------------------------------------------------
# 6. Embedding 路径（mock encoder）
# ---------------------------------------------------------------------------

class TestEmbeddingPath:
    def test_embedding_hit_above_threshold(self) -> None:
        # query 和 candidate 向量相同 → cosine = 1.0 > 0.80
        embed_map = {
            "Tyrosine metabolism": [1.0, 0.0],
            "Tyrosine catabolism": [1.0, 0.0],
        }
        m = _make_embedding_matcher(threshold=0.80, embed_map=embed_map)
        assert m.is_hit("Tyrosine metabolism", ["Tyrosine catabolism"])

    def test_embedding_miss_below_threshold(self) -> None:
        # 正交向量 → cosine = 0.0 < 0.80
        embed_map = {
            "Glycolysis": [1.0, 0.0],
            "Tyrosine metabolism": [0.0, 1.0],
        }
        m = _make_embedding_matcher(threshold=0.80, embed_map=embed_map)
        assert not m.is_hit("Glycolysis", ["Tyrosine metabolism"])

    def test_embedding_method_label(self) -> None:
        embed_map = {
            "Tyrosine metabolism": [1.0, 0.0],
            "Tyrosine catabolism": [1.0, 0.0],
        }
        m = _make_embedding_matcher(embed_map=embed_map)
        r = m.match("Tyrosine metabolism", "Tyrosine catabolism")
        assert r.method == "embedding"
        assert r.score > 0.0

    def test_embedding_match_any_picks_highest(self) -> None:
        # catabolism 与 query 对齐，glycolysis 偏 90 度
        embed_map = {
            "Tyrosine metabolism": [1.0, 0.0],
            "Tyrosine catabolism": [0.95, 0.31],   # cos ≈ 0.95
            "Glycolysis": [0.0, 1.0],              # cos = 0.0
        }
        m = _make_embedding_matcher(threshold=0.80, embed_map=embed_map)
        r = m.match_any("Tyrosine metabolism", ["Glycolysis", "Tyrosine catabolism"])
        assert r.candidate == "Tyrosine catabolism"
        assert r.hit is True


# ---------------------------------------------------------------------------
# 7. 模块可 import，无需 torch
# ---------------------------------------------------------------------------

def test_import_without_torch() -> None:
    """确认在没有 torch 的环境中 import 不抛 ImportError。"""
    # 已经走到这里说明 import 成功
    from concord.lookup.pathway_name_matcher import PathwayNameMatcher  # noqa: F401
    from concord.lookup.pathway_name_encoder import SapBertEncoder, cosine_similarity  # noqa: F401
    assert callable(cosine_similarity)

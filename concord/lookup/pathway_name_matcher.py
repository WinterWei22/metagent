"""通路名语义匹配模块 — SapBERT embedding + cosine，回退 token overlap。

用法::

    from concord.lookup.pathway_name_matcher import PathwayNameMatcher

    matcher = PathwayNameMatcher()
    result = matcher.match("Tyrosine metabolism", "Tyrosine catabolism")
    # result.hit == True, result.method == "embedding" 或 "token_overlap"

    hit = matcher.is_hit("TCA cycle", ["Citrate cycle (TCA cycle)", "Glycolysis"])
    # True
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass

from concord.lookup.pathway_name_encoder import SapBertEncoder, cosine_similarity
from evaluation.sub6.metrics import _content_tokens, is_pathway_hit


@dataclass(frozen=True)
class PathwayMatchResult:
    query: str
    candidate: str
    score: float          # cosine similarity [0,1]；无 embedding 时为 -1.0
    hit: bool
    method: str           # "embedding" | "token_overlap" | "substring"
    threshold: float


def _stem(tok: str) -> str:
    """Minimal English stemming: strip common plural/inflection suffixes."""
    if len(tok) > 4 and tok.endswith("ing"):
        return tok[:-3]
    if len(tok) > 3 and tok.endswith("es"):
        return tok[:-2]
    if len(tok) > 3 and tok.endswith("s"):
        return tok[:-1]
    return tok


def _stem_tokens(toks: set[str]) -> set[str]:
    return {_stem(t) for t in toks}


def _token_overlap_method(query: str, candidate: str) -> tuple[bool, str]:
    """Substring check then stemmed token-subset check.

    Returns True when the shorter token set (after stemming) is a subset
    of the longer — i.e. the prediction is a more specific sub-pathway of
    the ground truth or vice versa.
    """
    if not query or not candidate:
        return False, "token_overlap"
    q_norm = query.lower().strip()
    c_norm = candidate.lower().strip()
    if q_norm in c_norm or c_norm in q_norm:
        return True, "substring"
    q_toks = _stem_tokens(_content_tokens(query))
    c_toks = _stem_tokens(_content_tokens(candidate))
    if not q_toks or not c_toks:
        return False, "token_overlap"
    smaller, larger = (
        (q_toks, c_toks) if len(q_toks) <= len(c_toks) else (c_toks, q_toks)
    )
    return smaller.issubset(larger), "token_overlap"


class _LRUCache:
    """简单线程安全 LRU cache，key=str，value=list[float]。"""

    def __init__(self, maxsize: int) -> None:
        self._maxsize = maxsize
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> list[float] | None:
        with self._lock:
            if key not in self._cache:
                return None
            self._cache.move_to_end(key)
            return self._cache[key]

    def put(self, key: str, value: list[float]) -> None:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = value
            if len(self._cache) > self._maxsize:
                self._cache.popitem(last=False)


class PathwayNameMatcher:
    """通路名语义匹配器。

    优先用 SapBERT embedding + cosine；若模型不可用且 fallback_to_token_overlap=True，
    则回退到原有 token overlap 逻辑。
    """

    def __init__(
        self,
        model_name: str = "cambridgeltl/SapBERT-from-PubMedBERT-fulltext",
        threshold: float = 0.80,
        fallback_to_token_overlap: bool = True,
        cache_size: int = 2048,
    ) -> None:
        self._threshold = threshold
        self._fallback = fallback_to_token_overlap
        self._cache = _LRUCache(cache_size)
        # encoder 初始化失败时 self._encoder = None（避免 RuntimeError 传出）
        self._encoder: SapBertEncoder | None = None
        try:
            enc = SapBertEncoder(model_name=model_name)
            if enc.available:
                self._encoder = enc
        except RuntimeError:
            # 模型不在 cache —— 用 fallback
            pass

    def _get_embedding(self, text: str) -> list[float] | None:
        if self._encoder is None or not text:
            return None
        cached = self._cache.get(text)
        if cached is not None:
            return cached
        result = self._encoder.encode([text])
        if not result or not result[0]:
            return None
        emb = result[0]
        self._cache.put(text, emb)
        return emb

    def match(self, query: str, candidate: str) -> PathwayMatchResult:
        """对单个 query/candidate 对做匹配，返回 PathwayMatchResult。"""
        if not query or not candidate:
            return PathwayMatchResult(
                query=query,
                candidate=candidate,
                score=-1.0,
                hit=False,
                method="token_overlap",
                threshold=self._threshold,
            )

        # Token overlap always runs (never purely a fallback).
        tok_hit, tok_method = _token_overlap_method(query, candidate)

        # Embedding path — runs when encoder available.
        if self._encoder is not None:
            q_emb = self._get_embedding(query)
            c_emb = self._get_embedding(candidate)
            if q_emb and c_emb:
                score = cosine_similarity(q_emb, c_emb)
                emb_hit = score >= self._threshold
                return PathwayMatchResult(
                    query=query,
                    candidate=candidate,
                    score=score,
                    hit=emb_hit or tok_hit,
                    method="embedding" if emb_hit else tok_method,
                    threshold=self._threshold,
                )

        # Encoder unavailable — token overlap only.
        return PathwayMatchResult(
            query=query,
            candidate=candidate,
            score=-1.0,
            hit=tok_hit,
            method=tok_method,
            threshold=self._threshold,
        )

    def match_any(self, query: str, candidates: list[str]) -> PathwayMatchResult:
        """对 candidates 逐一 match，返回得分最高的结果。"""
        if not candidates:
            return PathwayMatchResult(
                query=query,
                candidate="",
                score=-1.0,
                hit=False,
                method="token_overlap",
                threshold=self._threshold,
            )
        best: PathwayMatchResult | None = None
        for c in candidates:
            r = self.match(query, c)
            if best is None or r.score > best.score or (r.score == best.score and r.hit and not best.hit):
                best = r
        assert best is not None
        return best

    def is_hit(self, query: str, candidates: list[str]) -> bool:
        """drop-in 替换 evaluation.sub6.metrics.is_pathway_hit。"""
        if not query or not candidates:
            return False
        return any(self.match(query, c).hit for c in candidates)

"""底层 SapBERT 编码器 — 软依赖 torch/transformers，不可用时 available=False。"""
from __future__ import annotations

from typing import Iterable

_TORCH_AVAILABLE = False
_TRANSFORMERS_AVAILABLE = False

try:
    import torch  # noqa: F401
    _TORCH_AVAILABLE = True
except ImportError:
    pass

try:
    from transformers import AutoModel, AutoTokenizer  # noqa: F401
    _TRANSFORMERS_AVAILABLE = True
except ImportError:
    pass


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """两向量 cosine 相似度（纯 Python，无外部依赖）。"""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class SapBertEncoder:
    """SapBERT CLS-pooled encoder，batch encode + 去重缓存。

    若 torch/transformers 不可用，self.available=False；调用 encode 抛 RuntimeError。
    """

    def __init__(
        self,
        model_name: str = "cambridgeltl/SapBERT-from-PubMedBERT-fulltext",
        batch_size: int = 32,
        device: str | None = None,
    ) -> None:
        self.model_name = model_name
        self.batch_size = batch_size
        self.available = False

        if not (_TORCH_AVAILABLE and _TRANSFORMERS_AVAILABLE):
            return

        try:
            import torch
            import torch.nn.functional as F
            from transformers import AutoModel, AutoTokenizer

            self._torch = torch
            self._F = F
            resolved_device = device or ("cuda" if torch.cuda.is_available() else "cpu")
            self._device = resolved_device
            self._tokenizer = AutoTokenizer.from_pretrained(model_name)
            self._model = AutoModel.from_pretrained(model_name).to(resolved_device)
            self._model.eval()
            self.available = True
        except Exception as exc:
            # 模型不在 HuggingFace cache 时会到这里
            raise RuntimeError(
                f"SapBERT model '{model_name}' not found in local cache. "
                "Pre-download it with: "
                f"python -c \"from transformers import AutoModel; "
                f"AutoModel.from_pretrained('{model_name}')\""
            ) from exc

    def encode(self, texts: list[str]) -> list[list[float]]:
        """对一批文本编码，返回 L2-normalized CLS embedding 列表。"""
        if not self.available:
            raise RuntimeError(
                "SapBertEncoder not available: torch/transformers import failed."
            )
        result = self.encode_unique(texts)
        return [result.get(t, []) for t in texts]

    def encode_unique(self, texts: Iterable[str]) -> dict[str, list[float]]:
        """去重批量编码，返回 text → embedding 映射。"""
        if not self.available:
            raise RuntimeError(
                "SapBertEncoder not available: torch/transformers import failed."
            )
        unique = sorted({t for t in texts if t})
        out: dict[str, list[float]] = {}
        with self._torch.inference_mode():
            for start in range(0, len(unique), self.batch_size):
                batch = unique[start : start + self.batch_size]
                toks = self._tokenizer(
                    batch,
                    padding=True,
                    truncation=True,
                    max_length=64,
                    return_tensors="pt",
                )
                toks = {k: v.to(self._device) for k, v in toks.items()}
                hidden = self._model(**toks).last_hidden_state
                emb = hidden[:, 0, :]
                emb = self._F.normalize(emb, p=2, dim=1).detach().cpu().tolist()
                out.update(zip(batch, emb))
        return out

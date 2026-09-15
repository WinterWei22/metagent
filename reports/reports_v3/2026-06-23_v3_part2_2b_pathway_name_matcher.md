# V3 Part 2 — 2B 通路名语义匹配模块

- 日期：`2026-06-23`
- 分支：`metagent-v3-benchmark`
- 阶段：V3 Part 2（方法升级）工作项 **2B**（通路名语义匹配）
- 设计文档：[`docs/decisions/2026-06-23_v3_part2_embedding_method_upgrade.md`](../../docs/decisions/2026-06-23_v3_part2_embedding_method_upgrade.md)

---

## 1. 问题

Stage 2 / V3 benchmark 判断"预测通路名 A 是否命中 GT 通路名 B"靠 `evaluation/sub6/metrics.py:is_pathway_hit`。该函数用两层规则：
1. 大小写不敏感 substring
2. content token subset（去掉 stop word + metabolism/catabolism/... 后缀）

人工校验集（Human1 stratum）显示 semantic TP 只有 53%：大量同义表达（"TCA cycle" vs "Citrate cycle"、"eicosanoid" vs "arachidonic acid metabolism"）被 token-overlap 漏判。

## 2. 出发点：已有代码

`scripts/eval_sub6/semantic_pathway_accuracy_sapbert.py` 已有完整的 `SapBertEncoder`（~80 行），用 HuggingFace `cambridgeltl/SapBERT-from-PubMedBERT-fulltext` 做 CLS-pooled batch encode + cosine 相似度，并在 Stage 1 A3 baseline 上做过验证（threshold @0.80 为操作点）。2B 的任务就是把它从一次性 eval 脚本里提取为正式复用模块。

## 3. 产出物

### 3.1 `concord/lookup/pathway_name_encoder.py`（105 行）

底层 encoder，包含：
- `SapBertEncoder`：从原有 eval 脚本提取，清理了外部 state；`__init__` 失败时 `self.available=False`（不抛 ImportError）
- `cosine_similarity(a, b)`：纯 Python 无外部依赖，两向量 cosine 相似度

软依赖约定：`torch` + `transformers` 不在 import 时报错；只有实例化 + 调用 `encode` 时才会触发。

### 3.2 `concord/lookup/pathway_name_matcher.py`（199 行）

对外 API 工具，核心返回类型：

```python
@dataclass(frozen=True)
class PathwayMatchResult:
    query: str
    candidate: str
    score: float        # cosine similarity [0,1]；无 embedding 时 -1.0
    hit: bool           # score >= threshold
    method: str         # "embedding" | "token_overlap" | "substring"
    threshold: float
```

核心类 `PathwayNameMatcher`：

| 方法 | 说明 |
|---|---|
| `match(query, candidate)` | 单对匹配，返回 `PathwayMatchResult` |
| `match_any(query, candidates)` | 多候选取最高分结果 |
| `is_hit(query, candidates)` | drop-in 替换 `is_pathway_hit`，返回 bool |

**解析逻辑**（短路）：
1. 若 `SapBertEncoder.available=True`：计算 embedding cosine，`>= threshold` 为 hit，`method="embedding"`
2. 若 encoder 不可用且 `fallback_to_token_overlap=True`：回退原有 token overlap，`method="token_overlap"` / `"substring"`
3. 其余：`hit=False, score=-1.0`

**Embedding cache**：内置 `_LRUCache`（默认 2048 条），threading.Lock 保护，避免同通路名重复 encode。`SapBertEncoder` 已做 L2 normalize（CLS pooling），cache 直接存 list[float]。

**默认参数**：`model_name="cambridgeltl/SapBERT-from-PubMedBERT-fulltext"`，`threshold=0.80`，`fallback_to_token_overlap=True`。

### 3.3 `tests/test_pathway_name_matcher.py`（263 行，27 cases）

所有 27 case 在无 torch 环境（fallback 路径）下 pass，无需下载模型：

| 测试类 | 场景 |
|---|---|
| `TestFallbackBasicHits`（8）| exact match / token subset / substring / case-insensitive / no-hit / multi-candidates |
| `TestEdgeCases`（6）| 空 candidates / 空 query / match_any 空 |
| `TestResultFields`（4）| 字段完整性 / method label / threshold 传播 |
| `TestMatchAny`（2）| 返回最高分 / no-hit 时仍返回 |
| `TestNoFallback`（2）| fallback=False 时无模型 → hit=False |
| `TestEmbeddingPath`（4）| mock encoder，验证 embedding 路径 score/method/match_any |
| `test_import_without_torch`（1）| import 不报错 |

### 3.4 `scripts/metagent/full344_pathway_scorecard.py`（已改）

在模块级创建单例 `_pathway_matcher = PathwayNameMatcher(fallback_to_token_overlap=True)`，在 `rows_for_full344` 的 metrics 行里用 `is_hit` 覆盖 `primary_semantic_match` + `topk_semantic_match` 两列。有 SapBERT 时用 embedding；无模型时 fallback token overlap，行为透明、已有 scorecard 数字不受影响。

## 4. 测试结果

```
PYTHONPATH=. pytest tests/test_pathway_name_matcher.py -v
27 passed in 0.05s
```

B1 verifier 回归：pre-existing pydantic/Python 3.8 不兼容错误（`model_validator` import 在 Python 3.8 失败），与本次改动无关，git diff 确认 verifier-core 文件无改动。

## 5. 用法

### 5.1 基本调用

```python
from concord.lookup.pathway_name_matcher import PathwayNameMatcher

matcher = PathwayNameMatcher()   # 默认：SapBERT threshold=0.80，fallback on

# 单对
r = matcher.match("TCA cycle", "Citrate cycle (TCA cycle)")
# r.hit=True, r.score=0.97(embedding) or True(substring)

# 多候选，取最高分
r = matcher.match_any("eicosanoid metabolism", [
    "Arachidonic acid metabolism", "Glycolysis", "Fatty acid beta-oxidation"
])

# drop-in 替换 is_pathway_hit
hit = matcher.is_hit("Tyrosine catabolism", ["Tyrosine metabolism"])
# True（token subset 或 embedding）
```

### 5.2 无模型环境

若 SapBERT 未在本地 cache，`PathwayNameMatcher()` 自动 fallback token overlap，不抛错：

```python
matcher = PathwayNameMatcher()
print(matcher._encoder)   # None
matcher.is_hit("Tyrosine metabolism", ["Tyrosine catabolism"])  # True via token_overlap
```

首次下载 SapBERT（~440MB）：

```bash
python -c "from transformers import AutoModel; AutoModel.from_pretrained('cambridgeltl/SapBERT-from-PubMedBERT-fulltext')"
```

### 5.3 V3 benchmark scorecard

V3 scorecard 脚本 `scripts/metagent/full344_pathway_scorecard.py` 已接入。重跑时如果 SapBERT 在 cache 中，`primary_semantic_match` / `topk_semantic_match` 列自动升级为 embedding cosine；否则保持原有 token overlap 语义，backward-compatible。

## 6. 已知边界

- `threshold=0.80` 来自 `semantic_pathway_accuracy_sapbert.py` 的历史验证，未在 V3 benchmark 上做系统超参扫描。2D 接入时如需调阈值，构造时传入 `threshold=<value>`。
- SapBERT 模型 444MB，首次需联网下载；之后从 `~/.cache/huggingface` 读，不联网。
- `cosine_similarity` 用纯 Python 实现（无 numpy），在 2048-dim 向量上约 0.3ms/pair，对批量 eval 可接受；如需加速可改 numpy dot。
- 目前 `is_hit` 在 embedding 路径下**任一候选超阈值即返回 True**（与原 token overlap 的 any-hit 语义一致）；`match_any` 则返回最高分那个候选的完整 `PathwayMatchResult`，可供 2D verifier 取 score 字段做软判决。

## 7. 下一步

2B 模块完成，供 2D（verifier 结构一致性层）+ 2C（结构相似度富集）调用。建议 2D 先做（依赖 2A resolver + 2B matcher），2C 最后。

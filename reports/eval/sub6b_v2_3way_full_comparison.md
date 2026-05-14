# Sub-6B v2 — 3-way LLM Comparison (MiniMax / GPT-5.5 / Opus-4-7)

**Date:** 2026-05-07
**Branch:** `feature/sub6-v2-integrated`
**Verifier:** v9-PhaseC (extractor = Opus-4-7, working tree code, mtime 2026-05-06 00:27)
**Tasks:** 63 Sub-6B v2 mammalian (`data/benchmark/sub6/sub6b_mammalian_tasks_v2.jsonl`)
**Code changes:** 0 行
**v1/v2 已有文件改动:** 0 个

---

## 1. Three-way main table

| | MiniMax-M2.7 | GPT-5.5 | Opus-4-7 |
|---|---:|---:|---:|
| narrative wall | **44.3 min** | 24.8 min | 19.7 min |
| s/task | 42.2 | 23.6 | 18.8 |
| narrative 平均长度 | **2389 chars** | 2601 | 2766 |
| total claims | 2733 | 2956 | 3281 |
| supported pct | 18.92% | **28.89%** | 18.10% |
| unsupported pct | 18.73% | 17.42% | 12.56% |
| **contradicted pct** | **5.01%** | 3.89% | 4.18% |
| unverifiable_v0 pct | 57.34% | 49.80% | 65.16% |
| SE 任务级 supported | 2/63 | **5/63** | 2/63 |
| Driver-contra 任务 | **8/63** | 16/63 | 17/63 |

---

## 2. Set-enrichment verdict 分布（F4 audit 验证 + 推翻最初假设）

| | MiniMax | GPT-5.5 | Opus-4-7 |
|---|---:|---:|---:|
| SE total | 124 | 143 | 156 |
| SE supported | 2 | **5** | 2 |
| SE unsupported | 4 | 6 | 2 |
| SE **contradicted** | **33** | 31 | 32 |
| SE unverifiable_v0 | 85 | 101 | 120 |
| SE supported pct | 1.61% | **3.50%** | 1.28% |
| SE contradicted pct | **26.61%** | 21.68% | 20.51% |
| SE unverifiable pct | 68.55% | 70.63% | 76.92% |

**关键反转**: prompt 里预期 "MiniMax SE supported pct 显著高于 Opus" — **数据没支持这个假设**。在 Sub-6B v2 上 MiniMax SE supported pct (1.61%) 实际**略低于** Opus (1.28% — 几乎相同) 和 GPT-5.5 (3.50%)。

但 audit (Sub-6A perfect) 发现 MiniMax SE supported = 11% (3/28) 是真的 — 那是因为 v1 14-task 的 ground-truth pathway 有 3/14 是 RAMP_P_000053306 (Pyrimidine metabolism)，MiniMax 在该 pathway 上 3 个 seed 都把 canonical 名"pyrimidine metabolism"写出来了 → 全 supported。**那是任务分布偏置 + small-sample 现象，不是 LLM 本身的"literal-style → 高 supported"通则**。

更精细的 finding 在 **SE contradicted pct**: MiniMax (26.6%) > GPT-5.5 (21.7%) ≈ Opus (20.5%)。MiniMax 的确**更倾向于写出具体 pathway 名**，但这些名经常**不在 RaMP top-10** → contradicted。Opus 倾向写功能性术语 → unverifiable。两种风格的"可验证份额"都低，但失败模式不同：MiniMax 的失败更可能被检出为 contradicted（具体且错），Opus 的失败更多落在 unverifiable_v0（笼统而无法判定）。

---

## 3. Contradicted 跨 LLM 一致性 — 强 finding

| LLM | total claims | contradicted | contradicted pct |
|---|---:|---:|---:|
| MiniMax | 2733 | 137 | **5.01%** |
| GPT-5.5 | 2956 | 115 | **3.89%** |
| Opus-4-7 | 3281 | 137 | **4.18%** |

**3 个 LLM 的整体 contradicted 比例都在 4–5% 区间**，差距不到 1.2 pt。这说明:

1. **底层"客观乱说"水平在 3 个 LLM 中相当**(差异 <1.2 pt)。
2. 主要差异在**写作风格**（具体 vs 模糊）→ 决定可验证份额（GPT 50% < MiniMax 57% < Opus 65% unverifiable_v0）。
3. **强证据支撑 paper 的 verifier-literal-style-bias finding** — 我们看到的 supported pct 跨 LLM 差异 (MM 19% / GPT 29% / Opus 18%) 不是 hallucination 水平差异，而是**verifier 看见多少**的差异。

可以以此重写 paper limitation：**verifier 当前 grading 严重偏好 literal pathway-name 写法；mechanistic narrative LLM (Opus) 被低估，list-heavy LLM (GPT-5.5) 被高估**。

---

## 4. Sample claim 对比（同 task 跨 3 LLM，3 task）

### 4.1 RAMP_P_000000398 (Galactose Metabolism, central) — task seed0

| LLM | SE claim 文本 | verdict |
|---|---|---|
| MiniMax | "perturbations in **galactose/sugar alcohol metabolism**" | **CONTRADICTED** (galactose/sugar alcohol 不是 RaMP 顶部 canonical 名) |
| GPT-5.5 | "treatment-induced reprogramming of **carbon storage/osmoprotection**" | UNVERIFIABLE_v0 |
| Opus-4-7 | "...signature of **osmotic, cold, or oxidative stress adaptation**" | UNVERIFIABLE_v0 |

**注解**: gt 是 "Galactose Metabolism" — 三家都没写出 canonical 名。MiniMax 最接近（写"galactose/sugar alcohol"）但被 verifier 判 contra（slash-合写不被反向模糊匹配命中）。这是 paper 一个可贴的"literal-style 也救不了"案例。

### 4.2 RAMP_P_000050021 (Biological oxidations, other) — task seed0

| LLM | SE claim 文本 | verdict |
|---|---|---|
| MiniMax | "disruption of **xenobiotic metabolism/detoxification**" | **SUPPORTED** |
| GPT-5.5 | "altered **xenobiotic biotransformation**" | UNVERIFIABLE_v0 |
| Opus-4-7 | "The most likely affected pathway is **Xenobiotic metabolism**" | **SUPPORTED** |

**注解**: gt = "Biological oxidations" 的 RaMP top-3 含 "Xenobiotic metabolism" 同义路径。MiniMax 和 Opus 都写出 "xenobiotic" canonical 名 → 反向模糊命中。GPT-5.5 写"biotransformation"（同义但不字面）→ unverifiable。这个 task 是 **literal-style 帮助**的正例。

### 4.3 RAMP_P_000053306 (Pyrimidine metabolism, nucleotide) — task seed7

| LLM | SE claim 文本 | verdict |
|---|---|---|
| MiniMax | "the entire **pyrimidine lifecycle**" | UNVERIFIABLE_v0 |
| GPT-5.5 | "...span **nucleotide pools, deoxynucleoside turnover, and uracil catabolism**" | **CONTRADICTED** |
| Opus-4-7 (3 SE) | "altered flux through **pyrimidine catabolism**" / "interconversion between cytidine nucleotide pool and deoxyribonucleotide synthesis" | UNSUPPORTED + 2 CONTRADICTED |

**注解**: 同样的 ground-truth (Pyrimidine metabolism)，**三家全部失败**。MiniMax 写"pyrimidine lifecycle"（'lifecycle' 不是 RaMP canonical 名 — 没有反向模糊命中），GPT 写多个具体子通路名但都不在 top-10，Opus 写细节流向。**audit 报告里 v1-MiniMax 同 pathway 上写"pyrimidine metabolism" canonical 名 → SUPPORTED 的现象，没在 v2 重现** — 主要是 v2 的 RaMP enrichment top-3 排序变了（Pyrimidine metabolism 在 v2 的 seed7 task 下可能是 rank 2/3 但更细致的子通路是 rank 1/2，LLM 跟着顶部走），把 LLM 从 canonical 名拉到了子通路名。

---

## 5. Paper finding 更新建议

1. **核心 finding 强化**：3 个 LLM contradicted pct 几乎相同（4–5%）说明 hallucination 水平相当；supported pct 大差异（MM 19 / GPT 29 / Opus 18）是 verifier-literal-style-bias 的产物。这是更"诚实"的 framing。

2. **F4 (LLM swap) audit 推翻 prompt 假设但 audit 结论仍稳**：MiniMax 在 Sub-6B v2 上 SE supported pct 没有显著高于 Opus，**但** SE contradicted 高于 Opus；Opus 不是"严格变差"，而是把同样的失败从 contradicted 转移到 unverifiable_v0。Audit 报告的核心 — "v1→v2 SE 退化是 LLM-driven artifact"——仍成立，只是机制更精确：v1 的 3/3 supported 是 task 偏置 + canonical 名命中的小样本巧合，不是 MiniMax 通则强项。

3. **Driver-contra 仍是 v2 的 v1 强升级**：MM 8/63 (13%) 比 GPT 16/63 (25%) / Opus 17/63 (27%) 略低，但仍远高于 v1 sub6b MiniMax 的 1/20 (5%)。**v2 数据扩展实质性提升了 Layer 6b 检出能力，独立于 LLM 选择**。这比 prompt 之前 framing 更稳健。

4. **Build 时 GPT-5.5 narrative 速度比 MiniMax 快 ~2×**（24 min vs 44 min）— 实际 paper 可作 secondary metric：cross-LLM 不仅是科学控制，也是工程现实考虑（MiniMax 推理 token 更长）。

---

## 6. Provenance

| field | value |
|---|---|
| git commit | `17a90dc` (`feature/sub6-v2-integrated`) |
| narrative wall | 2026-05-07 09:39 → 10:24 (44 min 19 s) |
| verifier wall | 2026-05-07 10:42 → 11:23 (41 min) |
| narrative LLM | `MiniMax-M2.7` via `https://api.minimaxi.com/v1` |
| verifier extractor | `claude-opus-4-7` via viviai relay |
| narrative file MD5 | `08b7dc6305dfe71503ea60db8e1db23a` |
| verdict file MD5 | `d91905fc4586aa83909829b8f114e5ce` |
| Layer code mtime | `2026-05-06 00:27:27` (unchanged across all 3 LLM runs) |
| ramp-db | `/data/weiwentao/llm_agent_metabolomics/ramp.sqlite` |

```
✓ data/eval/sub6/v2/sub6b_minimax/sub6b_narratives.jsonl     63 行
✓ data/eval/sub6/v2/sub6b_minimax/verdicts_v9_phaseC.jsonl   63 行
✓ results/v2/sub6b_minimax/sub6b_v2_minimax_verdicts_summary.json
✓ §1 主表 3 LLM 列填全
✓ §3 contradicted 比例对比
✓ 0 行代码改动
✓ 现有 Opus / GPT-5.5 文件未动
```

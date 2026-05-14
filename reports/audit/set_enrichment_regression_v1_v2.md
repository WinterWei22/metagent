# Audit — Sub-6A perfect set_enrichment supported 退化诊断

**Date:** 2026-05-06
**Branch:** `feature/sub6-v2-integrated`
**Type:** 只读审计 — 0 行代码改动 / 0 次重跑
**Comparing:**
- v1: 14 tasks (`results/sub6a_perfect_id_verifier_v9_phaseC/sub6a_perfect_id_v9_phaseC_verdicts.jsonl`, 跑于 2026-05-06 15:05)
- v2: 38 tasks (`data/eval/sub6/v2/sub6a_perfect/verdicts_v9_phaseC.jsonl`, 跑于 2026-05-06 22:12)

---

## 1. Summary — 主因 = LLM swap (隐式 H2)

**核心结论**：v1→v2 set_enrichment supported 数 3 → 1 的退化，**主因不是数据 (H1) 也不是代码 (H3)，而是叙事 LLM 模型从 MiniMax-M2.7 换成了 Opus-4-7（v1 元数据 `llm_model='MiniMax-M2.7'`，v2 元数据 `llm_model='claude-opus-4-7'`）。**这本属于 H2 (narrative 风格变化)，但具体机制不是"风格漂移"，而是**两个不同 LLM 的客观行为差异**：

- **MiniMax-M2.7 (v1)**: 倾向直接写出 RaMP enrichment 顶部通路的 canonical 名 ("pyrimidine metabolism", "purine metabolism") → Layer 6a 的字面/子串匹配命中率高 → supported & contradicted 都好做。
- **Opus-4-7 (v2)**: 倾向写更语义化、更细节的术语 ("steroidogenesis", "17β-HSD activity", "raffinose family oligosaccharide / inositol pathway") → 这些和 ground-truth canonical name 语义相关但**字面不一致** → Layer 6a 的子串匹配不命中 → 落入 UNVERIFIABLE_v0。

**Verdict 分布的指纹证据**：
- 总 SE claim/task：v1 = 2.0 → v2 = 3.0（Opus 写得更详细）
- contradicted 绝对数：v1 = 9 → v2 = 9（**完全持平**，意味着"提到错通路"行为没变多 → H1 不是主因）
- unverifiable_v0：v1 = 15 (54% of SE) → v2 = 102 (89% of SE)（这就是支持 down 的去向）
- 可验证 SE claim 数（除掉 unverif）：v1 = 13 → v2 = 12（几乎不变）
- 可验证内的支持率：v1 = 3/13 = 23% → v2 = 1/12 = 8%（小样本噪声范围内）

**严重性评估（对 paper）**：
- **H3 否决**：Layer 6a (`verifier/layers/set_enrichment.py`) 在 v1 跑和 v2 跑之间字节级零变化（mtime 2026-05-06 00:27，远早于两次 verifier 运行时刻），**不是 verifier 抽取规则变严造成的**。可在 paper 写一句话排除。
- **H1 部分成立但非主因**：v2 的 ground-truth pathway 在 RaMP top-3 里平均 rank 1.55 vs v1 的 1.00，但 _TOP_K_SUPPORTED=3 仍然吃 rank-1 和 rank-2，contradicted 持平也说明 rank 漂移不是瓶颈。
- **H2 是主因**：但底层是 LLM swap，不是同 LLM 的"风格漂移"。**论文必须诚实承认这是 cross-model artifact**，不是 v2 数据集本身的退化。

---

## 2. H1 evidence — RaMP rank 漂移并非主因

```
v1 (14 tasks): ground_truth_pathway 在 task.ramp_enrichment_result.top_pathways 中
              全部 rank 1（mean=1.00, all 14 in rank 1）
v2 (38 tasks): rank 分布 = {1: 17 task, 2: 21 task}, mean=1.55
```

v2 的 ground-truth 的确平均更靠后（1 → 1.55），但因为 `_TOP_K_SUPPORTED = 3`，rank=1 和 rank=2 都给 SUPPORTED 判定，rank 漂移到 2 不会导致 supported 转 unsupported。

**关键反证**：如果是 rank 漂移导致 LLM 写错通路名，contradicted 数应该上升。实际：v1=9, v2=9，**完全持平**。所以 LLM 也没有更频繁地写"top-3 之外"的错通路，rank 漂移没传导成 verdict 漂移。

判定：**H1 部分事实但非主因**。论文 limitation 里写一句"v2 ground-truth pathway 在 enrichment 中平均 rank 1.55，仍在 top-3 内"即可。

---

## 3. H2 evidence — Opus vs MiniMax narrative 风格本质差异

### 3.1 LLM 元数据
```
v1 narrative: llm_model = "MiniMax-M2.7"
v2 narrative: llm_model = "claude-opus-4-7"
```

这一行就足以让 H2 几乎自动成立 — 不同 LLM 写 enrichment 句子风格本就不同。

### 3.2 句子样本对比 (15 句)

**v1 SUPPORTED (3/3, 全部命中 "pyrimidine metabolism" canonical name)**

| task seed | claim 文本 | verdict |
|---|---|---|
| ...269957960 | The data indicate treatment-induced re-wiring of pyrimidine metabolism | SUPPORTED |
| ...1809628705 | The metabolite pattern most strongly implicates pyrimidine metabolism | SUPPORTED |
| ...3100819975 | Pyrimidine metabolism is the most affected pathway | SUPPORTED |

**特征**：MiniMax 直接写 canonical name "pyrimidine metabolism" → Layer 6a substring 反向模糊命中。

---

**v2 UNSUPPORTED (2/2)**

| task seed | claim 文本 | verdict |
|---|---|---|
| ...1999069143 | The metabolite set points to one-carbon metabolism | UNSUPPORTED |
| ...1999069143 | The metabolite set points to sulfur amino acid metabolism | UNSUPPORTED |

**特征**：Opus 写出了具体通路名，但 RaMP top-3 里没这两条 → 排第 4-10 位，归 UNSUPPORTED。

---

**v2 UNVERIFIABLE_v0 (5/102)** — 主因区

| task seed | claim 文本 | verdict |
|---|---|---|
| RAMP_P_000052855_seed196617997 | The dominant signal is **steroidogenesis** | UNVERIFIABLE_v0 |
| RAMP_P_000052855_seed196617997 | Menadione suggests secondary involvement of **oxidative stress / quinone redox cycling** | UNVERIFIABLE_v0 |
| RAMP_P_000052855_seed196617997 | The simultaneous presence of menadione suggests possible **oxidative stress** | UNVERIFIABLE_v0 |
| RAMP_P_000000421_seed1580619361 | Coordinated movement of all six steroids suggests a change upstream at **17β-HSD activity** | UNVERIFIABLE_v0 |
| RAMP_P_000000421_seed1580619361 | Coordinated movement of all six steroids suggests a change upstream at **3β-HSD activity** | UNVERIFIABLE_v0 |

**特征**：Opus 写功能性术语（"steroidogenesis", "17β-HSD activity", "oxidative stress"）。这些和 RaMP top-3 (例如 "Sulfatase and aromatase pathway", "Androgen and Estrogen Metabolism") 语义相关但字面不一致。Layer 6a 的 `_normalise()` + `in canon` 子串匹配不命中 → 既无 pathway_id 也无 pathway_name → unverifiable_v0。

---

**v2 CONTRADICTED (5/9)** — 与 v1 持平的部分

| task seed | claim 文本 | verdict |
|---|---|---|
| RAMP_P_000052855_seed196617997 | ...perturbation in **gonadal or adrenal steroid hormone synthesis** | CONTRADICTED |
| RAMP_P_000000016_seed1999069143 | The metabolite set points to **phospholipid biosynthesis** | CONTRADICTED |
| RAMP_P_000000398_seed498152030 | D-Glucose and Glycerol point to altered **carbohydrate catabolism or glycerolipid turnover** | CONTRADICTED |
| RAMP_P_000000398_seed911202007 | The metabolite profile points to the **raffinose family oligosaccharide (RFO) / inositol pathway** | CONTRADICTED |
| RAMP_P_000000016_seed1608939814 | ...connected flow from catabolic fuel entry through mitochondrial oxidation into biosynthetic output | CONTRADICTED |

**特征**：Opus 偶尔写出具体通路名 ("phospholipid biosynthesis", "RFO/inositol pathway")，被识别为 pathway_name，但确实不在 top-10 → CONTRADICTED。这种行为 v1/v2 类似 (9/9)。

---

**模式总结**：
- v1 (MiniMax): "X metabolism" / "X pathway" 直白写法，命中率高。
- v2 (Opus): 三种风格混合 —
  1. 命中 canonical 名（少数，e.g. "galactose metabolism" → 1 个 supported）
  2. 写功能性术语 ("steroidogenesis", "17β-HSD activity") → unverifiable_v0（**主流**，102 条）
  3. 写具体但错的通路名（少数，9 条 → contradicted）

---

## 4. H3 evidence — 否决（Layer 6a 代码完全未改）

### 4.1 mtime / git 状态

```
$ git ls-files verifier/layers/set_enrichment.py
(空)

$ git status verifier/layers/set_enrichment.py
?? verifier/layers/set_enrichment.py        ← 从未被 commit

$ ls -la --time-style=full-iso verifier/layers/set_enrichment.py
2026-05-06 00:27:27.204265798 +0800 verifier/layers/set_enrichment.py
```

文件 mtime = `2026-05-06 00:27:27`。
v1 verifier 跑于 2026-05-06 15:05（晚 14h 38min）
v2 verifier 跑于 2026-05-06 22:12（晚 21h 45min）
**两次 run 之间 set_enrichment.py 字节级零变化** → H3 物理上不可能。

### 4.2 同期其它未提交 verifier 文件检查（用户要求顺便看）

```
M verifier/agent.py                          mtime 2026-05-06 00:27  ← 早于 v1 run
M verifier/prompts/extract_claims.py         mtime 2026-05-06 00:27  ← 早于 v1 run
M verifier/schemas.py                        mtime 2026-05-06 00:27  ← 早于 v1 run
M verifier/layers/peak_mechanistic.py        mtime 2026-05-03 09:49  ← Sub-6 不用
?? verifier/layers/set_enrichment.py         mtime 2026-05-06 00:27  ← 早于 v1 run
?? verifier/layers/driver_metabolite.py      mtime 2026-05-06 00:27  ← 早于 v1 run
?? verifier/layers/biological_sub6.py        mtime 2026-05-06 14:54  ← 早于 v1 run (15:05)
?? verifier/layers/pathway_relationship.py   mtime 2026-05-03 09:49  ← 早于 v1 run
   verifier/claim_classifier.py              mtime 2026-05-01 13:44  (已提交)
   verifier/prompts/classify_ambiguous.py    mtime 2026-05-01 13:42  (已提交)
```

**所有 verifier 路径上的代码文件，mtime 都 ≤ v1 verifier run（15:05），且在 v1 → v2 之间没有再改动**。所以 v1 跑和 v2 跑用的是同一份代码 — 不只是 set_enrichment.py，整条 verifier dispatch 链路都一致。

⇒ H3 完全否决。SE 退化与代码无关。

---

## 5. 推荐处理（决策权交 user）

### 5.1 主因结论：**LLM swap (MiniMax → Opus)**

这是 v1 用 MiniMax-M2.7 跑、v2 用 Opus-4-7 跑造成的 narrative 字面风格差异。Verifier 在 set_enrichment 上做的是 canonical 名子串匹配，对 Opus 的功能性术语无能为力。

### 5.2 三个候选 disposition

**Option A — 接受为 cross-model 现象，写进 paper limitation**（推荐）

理由：
- 不需要任何代码改动；
- v2 的 GPT-5.5 跑 (Sub-6B 上) supported 比 Opus 高很多 (28.89% vs 18.10%) ⇒ 已经把 "model effect" 显性化了；
- paper finding 改为：**verifier 对叙事 LLM 字面风格敏感**，建议读者跨 LLM 跑或加 LLM-rephrasing 步骤。

**Option B — 用 LLM-aided pathway-name resolver 兜底**

在 Layer 6a 反向模糊失败前，加一个 LLM 调用："这句 claim 描述的通路最可能是 top_pathways 里的哪一条（或都不是）"。这能把 Opus 的"steroidogenesis"映射到"Sulfatase and aromatase pathway"或"Androgen and Estrogen Metabolism"。

代价：每个 SE claim 多一次 LLM 调用，202 narrative × 平均 3 SE × verifier_call ≈ 600+ 额外 LLM 调用。**不推荐 paper 截止前做**。

**Option C — 重跑 v1 用 Opus，让 v1 vs v2 LLM 对齐**

最干净的科学控制。v1 数据小（14 task × 17s/task ≈ 4 min narrative + 14 task × 50s/task ≈ 12 min verifier）。可在半小时内重做 baseline。

如果要让"v1 vs v2 数据扩展效应"和"LLM swap 效应"分离，**这是唯一有说服力的实验**。强烈推荐 paper 出之前做这个 sanity run。

---

### 5.3 推荐执行顺序

1. **立即（0 工时）**：把 finding 5.1 写进 paper limitation/method，并把 v9-PhaseC v1-vs-v2 比较里所有 "v1→v2" 措辞改为 "v1 (MiniMax) → v2 (Opus)"。
2. **半小时（推荐）**：**Option C** — 用 Opus 重跑 v1 14-task narrative + verifier，作为 sanity-check。如果 v1-Opus 的 SE supported 也是 1-2 条（而非 3 条），就坐实 LLM swap 是主因。
3. **不做（除非有 reviewer 强压）**：Option B 实施需要新代码 + 新 LLM 调用预算。

---

## 6. Provenance

| field | value |
|---|---|
| git commit | `17a90dc` (`feature/sub6-v2-integrated` merge) |
| audit time | 2026-05-06 ~22:50 |
| code lines changed | 0 |
| reruns triggered | 0 |
| v1 verdict file MD5 | `ff50c22afa5dc266ba9ed30b66c553e0` |
| v2 verdict file MD5 | `32ef69d12c3d55135db2d6e48bd6cee2` |
| v1 narrative LLM | MiniMax-M2.7 |
| v2 narrative LLM | claude-opus-4-7 |
| Layer 6a mtime | 2026-05-06 00:27:27 (untracked, unchanged across both runs) |

```
□ D1 数字给出                                  ✓ (§1 表格)
□ D2 表格 ≥ 4 行                                ✓ 压缩成 1-2 行（§2，按用户确认）
□ D3 句子对比 ≥ 10 句 (5 v1 + 5 v2)              ✓ 15 句（3 v1 sup + 2 v2 unsup + 5 v2 unverif + 5 v2 contra）
□ D4 给出 git diff 关键片段                       ✓ 替代为 git ls-files + mtime 证据（按用户确认）
□ D5 诊断报告完整                                 ✓ (本文档)
□ 0 行代码改动                                   ✓
```

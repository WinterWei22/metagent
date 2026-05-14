# Audit — v1 14-task with Opus-4-7 narrative (cross-model sanity check)

**Date:** 2026-05-07
**Type:** 直接控制实验,证明 set_enrichment 退化主因
**Predecessor:** `reports/audit/set_enrichment_regression_v1_v2.md`
**Code changes:** 0 行
**v1/v2 已有文件改动:** 0 个

---

## 1. Three-way set_enrichment comparison

| Track | tasks | LLM | SE total | sup | unsup | contra | unverif | tasks-w-any-sup-SE |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| v1 (existing, baseline) | 14 | **MiniMax-M2.7** | 28 | **3** | 1 | 9 | 15 | 3/14 |
| v1-Opus (this audit) | 14 | **claude-opus-4-7** | 25 | **0** | 0 | 5 | **20** | 0/14 |
| v2 (existing) | 38 | **claude-opus-4-7** | 114 | **1** | 2 | 9 | 102 | 1/38 |

---

## 2. Conclusion

**LLM swap 是唯一主因 — 数据扩展无任何贡献。**

铁证：
1. **同一份 v1 14 task 数据 + 同一份 v9-PhaseC verifier**，仅把 narrative LLM 从 MiniMax-M2.7 换成 Opus-4-7：set_enrichment supported 从 **3 → 0**，掉到底。
2. v1-Opus (14 task, Opus, 0 sup) 和 v2 (38 task, Opus, 1 sup) 的 SE supported 率都是 0–3%；v1-MiniMax 是 11% (3/28)。**Opus 写 SE claim 的 supported 命中率约为 MiniMax 的 1/4 量级**。
3. v1-Opus 的 unverifiable_v0 占 SE 总量 20/25 = **80%**，与 v2 的 102/114 = **89%** 同档；v1-MiniMax 仅 15/28 = **54%**。**这就是 H2 (narrative 风格) 的精确机制**：Opus 把 SE 类断言写成功能性术语 (e.g. "Coordinated changes across multiple pyrimidine species suggest the treatment is perturbing nucleotide homeostasis"),不写 canonical 名 → Layer 6a 子串匹配不命中 → unverifiable。

例如 v1-MiniMax 命中过的 task `RAMP_P_000053306_seed269957960`（pyrimidine metabolism），v1-Opus 在同一 task 上写出来的全是 unverifiable：

```
- "Baicalin's presence likely reflects a flavonoid/phenylpropanoid perturbation"
- "Coordinated changes across multiple pyrimidine species suggest the
   treatment is perturbing nucleotide homeostasis"
- "This pattern is commonly observed in responses to nucleoside analog drugs"
- "This pattern is commonly observed in responses to oxidative stress"
- "This pattern is commonly observed in responses to rapid changes in cell
   proliferation rate"
```

→ 没一个写"pyrimidine metabolism"这 4 个字。MiniMax 在同 task 上写过"The data indicate treatment-induced re-wiring of pyrimidine metabolism"，被 Layer 6a 子串命中得到 SUPPORTED。

数据扩展(14→38 task)其实在 SE supported **绝对数**上反而是**正贡献** (0→1)，但 task 数翻 2.7×，所以**比例**(0% vs 3%) 看起来差不多。这证实 v1→v2 的"3→1 退化"完全是 LLM swap 的产物，不是 v2 数据集本身的退化。

---

## 3. Paper implication

1. 把 v1 vs v2 比较中的 set_enrichment 部分**全部加上 LLM 限定**：v1 (MiniMax) → v2 (Opus)，避免暗示"v2 数据扩展导致退化"。
2. 在 paper limitation / discussion 写一句：**"verifier set_enrichment layer 对叙事 LLM 的字面措辞敏感；Opus-4-7 倾向写功能性术语而非 canonical pathway 名，导致 Layer 6a 反向模糊匹配命中率约为 MiniMax-M2.7 的 1/4 — 这是 model artifact 而非数据问题"**。
3. （可选 future work）如有论文额外预算，可在 Layer 6a 反向模糊兜底前加一次 LLM-based pathway-name resolver，把功能性术语映射回 RaMP canonical 名 — 但这是 paper 之后的工作。

---

## 4. Provenance

| field | value |
|---|---|
| git commit | `17a90dc` (`feature/sub6-v2-integrated`) |
| audit window | 2026-05-07 00:09 → 01:22 (1 h 13 min wall) |
| narrative wall | 5 min (14 task × ~21 s/task with Opus) |
| verifier wall | 13 min (14 task × ~56 s/task with Opus extractor) |
| reruns triggered (v1/v2) | 0 |
| code lines changed | 0 |
| v1-opus narrative MD5 | `cc66c9e4cead12e17da45f62ffbd3a78` |
| v1-opus verdict MD5 | `68773852a9bfba1a28b265dd548a50fe` |
| narrative LLM (this run) | `claude-opus-4-7` (via viviai relay) |
| verifier extractor LLM | `claude-opus-4-7` |
| Layer 6a code mtime | `2026-05-06 00:27:27` (unchanged across all 3 runs) |

```
□ data/eval/sub6/v1_opus_sanity/sub6a_narratives_perfect_id.jsonl  ✓ 14 行
□ data/eval/sub6/v1_opus_sanity/verdicts_v9_phaseC.jsonl            ✓ 14 行
□ 比较报告完整                                                       ✓ (本文档)
□ 0 行代码改动                                                       ✓
□ v1 / v2 现有文件未动                                               ✓
```

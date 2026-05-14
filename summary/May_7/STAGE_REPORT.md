# MetAgent 阶段性汇报 (v2 完整数据)

**Date:** 2026-05-07
**Branch:** `feature/sub6-v2-integrated`(commit `17a90dc`)
**作者:** Wentao Wei
**报告范围:** Sub-6 v2 benchmark 全量数据 + audit + cross-LLM 对比

---

## TL;DR

- 数据规模 v1→v2: 唯一 task 34→101 (+197%), narrative 调用 14→202 (+1343%), verdict 1.8K→10K
- Stage 1 (Spec→Mol): per-spectrum top-1 鉴定准确率 **67.32%** (459 谱图,38 task)
- Stage 2 (Mol→Pathway): cross-LLM verdict 已铺开 (Opus + GPT-5.5),contradicted 率底层 ~4% 跨 LLM 稳定
- Audit + sanity 闭环: F4 finding (verifier literal-style bias) 用控制实验坐实
- 6 张 Nature 风格 figure + end-to-end 案例已落盘到 `summary/May_7/figures/`

---

## 1. 模型框架图

**文件:** `figures/fig6_architecture.png`

3 阶段 pipeline:

```
Stage 1: Spectrum → Compound identification (Sub-6A only)
           candidate_prefilter → library_search → molecule_generate →
           merge_dedupe → per-candidate_enrichment → evidence_score → IdentificationReport

Stage 2: Narrative generation (cross-LLM, single-call, no tool use)
           format_report_for_llm() → {Opus-4-7 | GPT-5.5 | MiniMax-M2.7} → narrative

Stage 3: Verifier cascade (4 stages, 10 layers)
           extract → classify → per-claim verify (10 layers) → rewrite (if contradictions)
```

**关键设计点(paper-relevant):**

- Stage 1 是确定性 pipeline,**LLM 不参与编排**(不是 ReAct agent,是 Python 硬编码 dispatcher)
- Stage 2 LLM 单次调用,**不调工具**(所有外部数据预先算好塞进 prompt)
- Stage 3 verifier 是 hybrid:LLM 抽 claim + 规则路由 + 工具确定性验证

---

## 2. Spec → 分子 (Stage 1: Identification)

### 2.1 数据细节

| 维度 | v2 数值 |
|---|---:|
| Sub-6A task 数 | **38** |
| 总谱图数 | **459** |
| 平均每 task 谱图数 | ~12 |
| 谱图来源 | RIKEN MassBank + GNPS + MoNA-non-RIKEN |
| 总待筛 GNPS 库规模 | 985,492 records |
| Phase A 后 GNPS 平均池子(per query) | 89 records (5536× 缩减) |
| NM-002 自匹配排除 IDs | 76,783 GNPS records |

### 2.2 Identification 工具栈 (实测)

```
candidate_prefilter:    GNPS + PubChem-Lite, ±10 ppm window (Phase A 修复)
library_search:         Modified Cosine (matchms ModifiedCosineGreedy)  ← 唯一在用
                        MS-CLIP                                          ← 实现了但默认 off
molecule_generate:      SIRIUS+MS-BART                                  ← 不参与最终排序
spectrum_predict:       CFM-ID 4.0                                      ← 不进 evidence_score
```

**当前 Sub-6A v2 全部 38 task 走 `library_search` 单一策略。** MS-CLIP 双源融合 / molecule_generate / CFM-ID 都已实现但未启用——这是 paper future work 的明确空间。

### 2.3 检索性能结果

**文件:** `figures/fig_id_per_task_distribution.png`

| 指标 | v2 结果 |
|---|---:|
| Per-spectrum top-1 命中率 | **67.32%** (309/459) |
| Per-spectrum identified rate | 97.60% (448/459) |
| Per-task 平均准确率 | 67.37% |
| Per-task 中位数 | 67.95% |
| Per-task 区间 | 28.57% - 100% |
| Q1-Q3 IQR | 52.50% - 83.33% |

**任务级分布:**

```
100% accuracy:    3 / 38  (7.9%)   完美鉴定
≥75% accuracy:   16 / 38  (42.1%)
≥50% accuracy:   32 / 38  (84.2%)  主流
0% accuracy:      0 / 38  (0.0%)   没有完全失败的 task
```

### 2.4 v1 vs v2 对比

| | v1 (14 task / 128 spec) | v2 (38 task / 459 spec) |
|---|---:|---:|
| Phase A library_search top-1 | 71.09% | 67.32% |
| 无 Phase A baseline (v3 verifier) | 6.25% | (未重测) |
| Phase A 提升倍数 | **11.4×** | ~10.7× (估算) |

v2 略低 4pt——因为 nucleotide / amino acid 化合物在 GNPS 同质量异构体更多,识别更难。

### 2.5 Wall time

| 阶段 | 平均/task | 备注 |
|---|---:|---|
| Identification (Stage 1) | 3.6s | Phase A mass filter 之后非常快 |
| LLM narrative (Stage 2) | 17.9s | Opus-4-7 |
| Verifier cascade (Stage 3) | ~50s | 跨 10 layers + 抽 claim |

### 2.6 已知 limitations(paper 写明)

1. **单一 library 策略**:仅 `library_search`,molecule_generate / CFM-ID / MS-CLIP 都未启用
2. **缺 top-5 / top-10 metric**:领域标准,需要 aggregator 改半天能补
3. **缺 baseline 对比**:跟 SIRIUS / MIST / CASMI 等 prior work 没对比(数据已有,需独立 session)
4. **缺 precision-recall / ROC**:简单 aggregation,可补

---

## 3. 分子 → Pathway 鉴定 (Stage 2+3: Narrative + Verifier)

### 3.1 数据细节

| 维度 | v2 数值 |
|---|---:|
| Sub-6B task 数 (compound list 输入) | **63** |
| Sub-6A task 数 (spectrum → compound → pathway) | 38 |
| 通路覆盖 (unique pathways in Sub-6B) | 13 |
| HMDB curated 化合物 | 250 |
| 化合物总池(扩展后) | 600 |
| 已跑的 narrative LLM | Opus-4-7, GPT-5.5 |
| 待跑 | MiniMax-M2.7 |
| 总 narrative runs | 202 (含 v1-Opus sanity) |
| 总 verdict 数 | **10,042** claims |

### 3.2 Verdict 指标定义(reviewer 必问)

**文件:** `figures/fig_metric_explainer.png`

| Verdict | 定义 | 解读 |
|---|---|---|
| **SUPPORTED** | LLM claim 跟 RaMP/KEGG/HMDB/SIRIUS 证据一致 | 越高 = LLM 跟工具数据越对齐 |
| **UNSUPPORTED** | 数据库无对应记录(可能数据缺/可能 LLM 错) | 保守判定:未证实非证伪 |
| **CONTRADICTED** | 数据库返回反向结果(如化合物在不同 pathway) | 越高 = verifier 抓到更多 LLM hallucination |
| **UNVERIFIABLE_v0** | claim 在 v0 verifier scope 外(自由文本生物学/机制) | 越高 = LLM 写更多 functional 表述,verifier 限制 |

### 3.3 Verdict 分布跨 4 track (核心结果)

**文件:** `figures/fig1_cross_llm_distribution.png`, `figures/fig2_cascade_decomposition.png`

| Track | tasks | claims | sup% | unsup% | **contra%** | unverif% |
|---|---:|---:|---:|---:|---:|---:|
| sub6b_opus | 63 | 3,281 | 18.10 | 12.56 | **4.18** | 65.16 |
| sub6b_gpt55 | 63 | 2,956 | 28.89 | 17.42 | **3.89** | 49.80 |
| sub6a_perfect | 38 | 1,924 | 19.13 | 14.60 | **4.21** | 62.06 |
| sub6a_real | 38 | 1,881 | 14.19 | 14.83 | **4.47** | 66.51 |

**观察:**
- contradicted 率跨 4 track **稳定在 3.89-4.47%**(LLM 底层 hallucination 率稳定)
- supported / unverifiable 跨 LLM 差距大(15pt 量级),但**不反映正确性**,反映**verifier 字面匹配能力**

### 3.4 Per-layer verifier 行为

**文件:** `figures/fig4_per_layer_breakdown.png`

10 个 layer 中,Sub-6 任务主要触发 4 个:

| Layer | Sub-6B Opus 数据 | 关键观察 |
|---|---|---|
| **6a Set enrichment** | 156 claims, 1.3% sup, 77% unverif | substring matching,Opus 写 mechanistic 句子 → unverif 高 |
| **6b Driver metabolite** | 83 claims, 51% sup, 34% contra | precision = sup/(sup+contra) = 60% (Opus) vs 72% (GPT-5.5) |
| **6c Biological** | 2,288 claims (主流), 22% sup, 58% unverif | LLM 自由文本 biology 占大头 |
| **6d Pathway relationship** | 168 claims, 23% sup, 3% contra | KEGG reaction graph BFS,Opus 比 GPT-5.5 更 aggressive |

### 3.5 关键 finding F4: Verifier literal-style bias (smoking gun)

**文件:** `figures/fig3_se_supported_3way.png`

**3-way 控制实验**(同 14 task,同 verifier code,只换 narrative LLM):

| Track | LLM | SE supported | 备注 |
|---|---|---:|---|
| v1 | MiniMax-M2.7 | 3/28 (10.7%) | baseline |
| v1-Opus (sanity) | Opus-4-7 | 0/25 (0%) | LLM 切换,数据不变 |
| v2 | Opus-4-7 | 1/114 (0.9%) | 数据扩展 + Opus |

**铁证:** 数据扩展贡献 = 0,LLM swap 是 SE supported 退化的唯一主因。

**含义:** 不是 Opus "差",是 **Opus 倾向写 mechanistic 术语**("17β-HSD activity", "perturbing nucleotide homeostasis"),verifier substring matching 抓不到。

**Smoking gun example**(同 task `RAMP_P_000053306` pyrimidine):
- MiniMax narrative: "treatment-induced re-wiring of **pyrimidine metabolism**" → SUPPORTED
- Opus narrative: "perturbing **nucleotide homeostasis**" → UNVERIFIABLE

### 3.6 Cross-LLM precision (per layer)

```
Layer 6b driver_metabolite precision = SUPPORTED / (SUPPORTED + CONTRADICTED):
  GPT-5.5:    84/(84+33) = 72%
  Opus-4-7:   42/(42+28) = 60%

Layer 6d pathway_relationship:
  GPT-5.5: 39 sup, 0 contra (保守,从不写错 KEGG hierarchy claim)
  Opus-4-7: 39 sup, 5 contra (aggressive,有 5 个错)
```

---

## 4. End-to-End 报告案例

本节给出两个互补的端到端样例:

| 样例 | 起点 | 关注点 | 文件 |
|---|---|---|---|
| 4A 完整 spec→pathway | raw MS/MS spectrum | 5 阶段流水线一图概览,适合 PPT | `end_to_end_case_sub6a.json` · `figures/fig_e2e_case_from_spec.png` |
| 4B 下游 narrative/verifier | 已识别 differential metabolites | LLM narrative 与 verifier verdict 的细节 | `end_to_end_case.json` · `figures/fig_e2e_case.png` |

### 4A. 从 spec 出发的完整三阶段案例

**Task:** `e2e_enrich_mammalian_RAMP_P_000050099_seed1975252413`
**GT pathway:** Pyrimidine catabolism (Reactome R-HSA-73621)
**输入:** 10 个 raw MS/MS spectra
**Stage 1:** library_search,10/10 top-1(100%),1.2s
**Stage 2:** claude-opus-4-7 narrative,2,738 chars,17.3s,40 个 claim
**Stage 3 verifier verdict:** 10 supported / 4 unsupported / 2 contradicted / 24 unverifiable
**Bottom line:** 化合物全识别对、生物学方向对(pyrimidine 代谢),但 LLM 用了非 canonical 的命名
("pyrimidine degradation" vs Reactome 标准 "Pyrimidine catabolism"),被 Layer 6a 判 CONTRADICTED。

可视化(单张 PPT 横排,5 panel 流水线):`figures/fig_e2e_case_from_spec.png`

### 4B. 下游 narrative/verifier 案例

**完整 JSON:** `end_to_end_case.json`
**可视化:** `figures/fig_e2e_case.png`

### 4.1 Task 输入

```
Task ID: compound_only_enrich_mammalian_RAMP_P_000052855_seed0
Ground truth pathway: Sulfatase and aromatase pathway (wikipathways: WP_000052855)
Ground truth signal compounds (5):
  C00951 (estradiol)        C00280 (androstenedione)
  C00468 (estrone)          C00535 (testosterone)
  C01227 (DHEA-sulfate)
8 differential metabolites (5 signal + 3 noise)
```

### 4.2 LLM Narrative (Opus-4-7, 39.4s, 2828 chars)

部分摘录:

> "The dominant signal is **steroid hormone biosynthesis**. Steroid hormone biosynthesis maps to KEGG map00140. Six of the eight metabolites sit in the steroid hormone biosynthesis pathway: Dehydroepiandrosterone (DHEA), Androstenedione, ..."

LLM 提了正确的 high-level pathway 概念(steroid hormone biosynthesis),但**没有命中 ground truth 的 canonical name**("Sulfatase and aromatase pathway")。

### 4.3 Verifier 判定 (49 个 claim)

| Verdict | 数量 | % |
|---|---:|---:|
| SUPPORTED | 10 | 20% |
| UNSUPPORTED | 10 | 20% |
| CONTRADICTED | 0 | 0% |
| UNVERIFIABLE_v0 | 29 | 59% |

**有趣的是 0 contradicted**——LLM 没有明显说错的话,但 supported 也只有 20%——大部分 claim 都是 unverifiable(自由文本 biology)或 unsupported(LLM 提的 specific pathway name 不在 RaMP enrichment top-3)。

### 4.4 6 个代表性 claim

| # | Verdict | Claim |
|---:|---|---|
| 1 | UNSUPPORTED | The dominant signal is steroid hormone biosynthesis |
| 2 | SUPPORTED | Steroid hormone biosynthesis maps to KEGG map00140 |
| 3 | UNSUPPORTED | Six of the eight metabolites sit in the steroid hormone biosynthesis pathway |
| 4 | SUPPORTED | DHEA is one of the metabolites in the steroid hormone biosynthesis pathway |
| 5 | SUPPORTED | Androstenedione is one of the metabolites in the steroid hormone biosynthesis pathway |
| ... | UNVERIFIABLE | ... (free-text biology continues) |

### 4.5 这个案例的解读

**LLM 表现:**
- ✅ 识别出正确的代谢领域(steroid hormone)
- ✅ 准确指出多个 driver compounds (DHEA, androstenedione)
- ❌ 错过 ground truth 的 specific pathway name
- ⚠️ 大量 free-text biology (29/49 claims 都 unverifiable)

**Verifier 表现:**
- 抓住了 LLM 提的 KEGG ID 和 driver 化合物(20% supported)
- 没抓到任何明显错(0 contradicted),说明 LLM 整体没乱说
- 大量 unverifiable 反映 verifier 当前 scope 局限(不验自由文本)

---

## 5. 数据规模 v1 → v2 (paper Supplementary)

**文件:** `figures/fig5_data_scale_v1_vs_v2.png`

| | v1 | v2 | Δ |
|---|---:|---:|---|
| Sub-6B mammalian tasks | 20 | 63 | +215% |
| Sub-6A end-to-end tasks | 14 | 38 | +171% |
| 通路覆盖 (Sub-6B) | 7 | 13 | +86% |
| HMDB curated 化合物 | 150 | 250 | +67% |
| Sub-6A 谱图总数 | 128 | 459 | +259% |
| 桶覆盖 | 4 | 5 | +1 (central recovered) |
| 总 verdict 数 | ~1,800 | 10,042 | +458% |
| Narrative LLMs | 1 | 2 (Opus + GPT-5.5) | +1 |

---

## 6. Bucket 分布(已知 limitation)

| Bucket | Sub-6B v2 tasks | Sub-6A v2 tasks |
|---|---:|---:|
| amino_acid_metabolism | 21 | ~13 |
| central_metabolism | 10 | ~6 |
| nucleotide_metabolism | 4 | ~3 |
| **lipid_metabolism** | **1** | **1** |
| other_metabolism | 27 | ~15 |

**Paper limitation:** lipid (1) + nucleotide (4) 太少,不能做 bucket-level statistics。

---

## 7. 7 张 figure 索引

| 文件 | 用途 |
|---|---|
| `fig6_architecture.png` | 系统总览 (Main Figure 1) |
| `fig1_cross_llm_distribution.png` | Sub-6B Opus vs GPT-5.5 verdict 分布 |
| `fig2_cascade_decomposition.png` | Sub-6B → 6A perfect → 6A real |
| `fig3_se_supported_3way.png` | Smoking gun: LLM swap 控制实验 |
| `fig4_per_layer_breakdown.png` | 4 layer × 2 LLM verdict 对比 |
| `fig5_data_scale_v1_vs_v2.png` | v1→v2 规模扩展 |
| `fig_id_per_task_distribution.png` | Sub-6A 鉴定准确率 per-task 分布 + cumulative |
| `fig_metric_explainer.png` | 4 种 verdict 的定义和解读 |
| `fig_e2e_case.png` | End-to-end 案例(已识别 metabolites → narrative → verdict → 6 claims) |
| `fig_e2e_case_from_spec.png` | End-to-end 完整 spec→pathway 案例(PPT 横排,5 panel:spec / Stage 1 ID / narrative / verifier / pathway) |

---

## 8. 待完成的实验(paper 投稿前)

| 实验 | 工作量 | 优先级 |
|---|---|---|
| Sub-6B v2 × MiniMax (3-way 完整矩阵) | 3-4h wall, ~$5 | 高 |
| Sub-6A 加 MS-CLIP + Modified Cosine 双源融合 | 1-2h | 高 (paper "ablation") |
| Sub-6A 跑 SIRIUS/CASMI baseline 对比 | 1-2 周 | 中 (paper benchmark prior work) |
| top-5 / top-10 metric aggregation | 半天 | 高 (领域标准) |
| 人工标注 5-7 task 算 Cohen's κ | 你 ~3h + 第二标注者 | 高 (NM 标准) |

---

## 9. Provenance

```
git commit:        17a90dc (feature/sub6-v2-integrated)
v2 task data:      data/benchmark/sub6/sub6{a,b}*v2.jsonl
v2 narrative:      data/eval/sub6/v2/sub6{a,b}_*/sub6{a,b}_narratives.jsonl
v2 verdict:        data/eval/sub6/v2/sub6{a,b}_*/verdicts_v9_phaseC.jsonl
v2 summary:        results/v2/sub6{a,b}_*/sub6{a,b}_v2_*_verdicts_summary.json
audit reports:     reports/audit/{set_enrichment_regression_v1_v2,v1_opus_sanity_check}.md
end-to-end case:   summary/May_7/end_to_end_case.json
figures source:    scripts/paper_figures/render_{nature,architecture,summary}_figures.py
```

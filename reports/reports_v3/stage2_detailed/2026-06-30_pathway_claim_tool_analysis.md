# Stage 2 详细分析 —— pathway 准确率 · claim 分布 · 工具调用 · case study

> 日期：2026-06-30 · 分支 `metagent-v3-benchmark`
> 主分析 run：`data/metagent/v4_bench_eval_cascade_fix_20260629`（**生产默认 cascade**，v4 benchmark 112 task：sub6 63 + hmdb_ramp 49；57 task 触发 cascade，0 rollback）
> 对照 run：`v4_bench_eval_repro_20260629`（legacy feedback）
> 打分：`PathwayNameMatcher.is_hit`（SapBERT + token-overlap fallback）；claim verdict 来自 `verify_sub6` 4 层。
> 复现：`scripts/metagent/stage2_detailed_analysis.py`（+ scorecard CSV）。

---

## 核心结论（先看这个）

1. **raw LLM 的 pathway 已经很强（语义 79.46%），cascade feedback 反而显著拉低到 71.43%**（配对 0 gained / **9 lost**，McNemar **p=0.0039**）。
2. **cascade 把 claim 质量做到极致（86% SUPPORTED、噪声归零），却以 pathway 准确率为代价**——两者方向相反。
3. **claim-supported 与 pathway 正确性解耦**：pathway 命中的 task 平均 supported 比例（0.876）反而**低于**未命中 task（0.970，Mann-Whitney 命中>未命中 p=1.0 完全不成立）。
4. **6 个核心工具几乎每个 task 必调**（5 富集 PA + query_pathway_members ≥92%），ID 解析/文献很少用（lookup_chebi 13%、search_literature 1.8%），平均 6.07 工具/task。

---

## 1. Pathway 准确率

### 1a / 1b / 1c —— FINAL（cascade 后，n=112）
| 范围 | n | 1a name精确 | 1b 语义 | 1c topk语义（含 alternatives/更高层概念） | abstain |
|---|---:|---:|---:|---:|---:|
| **overall** | 112 | 69.64% | **71.43%** | **81.25%** | 4.46% |
| sub6 | 63 | 65.08% | 66.67% | 80.95% | 3.17% |
| hmdb_ramp | 49 | 75.51% | 77.55% | 81.63% | 6.12% |

> 1c 用 top-k 语义（primary + alternatives 任一语义命中）作为"语义对 或 命中更高层/相邻概念"的宽口径；比 primary 语义高 ~10pp，说明正确通路常在 alternatives 里（second-pass 选 primary 时退化）。

### 1d —— RAW LLM（iter-0，cascade 前）
| 范围 | n | name精确 | 语义 |
|---|---:|---:|---:|
| **overall** | 112 | 77.68% | **79.46%** |
| sub6 | 63 | 79.37% | 80.95% |
| hmdb_ramp | 49 | 75.51% | 77.55% |

> **raw LLM 一次 ReAct 的 pathway 语义就有 79.46%**——是整个 Stage 2 的真实上限；后续 cascade 只会降低它。

### 1e —— feedback 前后（iter-0 raw → final，配对）
| 范围 | n | raw 语义 | final 语义 | gained | lost | McNemar p |
|---|---:|---:|---:|---:|---:|---:|
| cascade 触发的 task | 57 | 64.91% | **49.12%** | 0 | 9 | **0.0039** ✓ |
| 全部 | 112 | 79.46% | **71.43%** | 0 | 9 | **0.0039** ✓ |

> **cascade 在 pathway 上是纯负向**：触发的 57 个 task 里 9 个从命中变未命中、0 个反向修正。机制：cascade 删掉 UNSUPPORTED/UV claim 并把 CONTRADICTED 改 top-1，second-pass 在被"净化"过的 claim 集上反而选错 primary。

---

## 2. 报告 / claim 分布

### 2a —— FINAL 各类 claim 分布（n=112 聚合，共 798 claim）
| verdict | n | % |
|---|---:|---:|
| **SUPPORTED** | 689 | **86.34%** |
| INSUFFICIENT_EVIDENCE | 87 | 10.90% |
| UNVERIFIABLE_V0 | 22 | 2.76% |
| UNSUPPORTED | 0 | 0.00% |
| CONTRADICTED | 0 | 0.00% |

> 噪声（UNSUPPORTED+CONTRADICTED）已被 cascade 清零；残留 UV/INSUFFICIENT 来自 55 个未触发 cascade 的 task。

### 2b —— feedback 前后 claim 分布（57 触发 task，iter-0 → final）
| verdict | iter-0 | iter-0 % | final | final % |
|---|---:|---:|---:|---:|
| SUPPORTED | 305 | 52.05% | 247 | **100%** |
| UNSUPPORTED | 133 | 22.70% | 0 | 0% |
| INSUFFICIENT_EVIDENCE | 95 | 16.21% | 0 | 0% |
| UNVERIFIABLE_V0 | 39 | 6.66% | 0 | 0% |
| CONTRADICTED | 14 | 2.39% | 0 | 0% |
| **TOTAL** | **586** | | **247** | |

> cascade 删掉 ~58% claim（586→247），把 SUPPORTED 占比从 52% 推到 100%——claim 质量完美，但同一批 task 的 pathway 语义却从 64.9% 掉到 49.1%（§1e）。

### 2c —— claim supported 比例 vs pathway 语义命中（相关性）
| | n | 平均 SUPPORTED 比例 |
|---|---:|---:|
| pathway **命中** task | 80 | 0.876 |
| pathway **未命中** task | 30 | **0.970** |

Mann-Whitney U（命中 > 未命中）**p=1.0000**（完全不成立）。

> **强解耦/轻微反相关**：claim 都 supported 不代表 pathway 选对——未命中 task 的 supported 比例反而更高。说明 verifier 的 claim-level supported 信号**不能**当 pathway 正确性的 proxy；这也解释了为何 cascade（最大化 supported）会伤 pathway。

---

## 3. 工具调用分布（iter-0 ReAct，n=112）
| 工具 | 调用 task 数 | 占比 |
|---|---:|---:|
| query_pathway_members | 112 | 100% |
| run_mummichog | 112 | 100% |
| run_ramp_enrichment | 112 | 100% |
| run_fella_rwr | 109 | 97.3% |
| run_metaboanalystr_psea | 107 | 95.5% |
| run_sspa_ora | 103 | 92.0% |
| lookup_chebi | 15 | 13.4% |
| reconcile_inchikey | 8 | 7.1% |
| search_literature | 2 | 1.8% |

平均不同工具数/task = **6.07**。

> agent 稳定地把 **5 个富集 PA + query_pathway_members** 当标准动作全调一遍（多 paradigm 收敛策略）；ID 解析（lookup_chebi/reconcile_inchikey）按需触发；文献几乎不用（pathway 任务用不上 PMID）。

---

## 4. 优质报告 case

### 4.1 详例 —— Androgen and Estrogen Metabolism（全 9 supported / 语义命中）
- **task**：`sub6_easy_compound_only_enrich_mammalian_RAMP_P_000000421_seed1`（sub6）
- **输入 8 代谢物**：Warfarin, Estradiol, 3,4-Dihydroxyphenylacetaldehyde, Androstenedione, Estrone, Dehydroepiandrosterone, Dihydrotestosterone, Testosterone
- **预测 primary**：`Androgen and Estrogen Metabolism`（KEGG:hsa00150）✓ 命中 gold
- **claims（11，全 SUPPORTED）样例**：
  - `pathway_enrichment`：run_ramp_enrichment ranks KEGG:hsa00150 at rank 2 with **fdr 4.97e-18**
  - `pathway_enrichment`：run_mummichog ranks androgen_and_estrogen_biosynthesis_and_metabolism
  - `pathway_membership`：testosterone / 17β-estradiol / dehydroepiandrosterone is a member of Androgen and Estrogen Metabolism
- **亮点**：多 paradigm（RaMP ORA + mummichog）独立收敛到同一通路 + 多个底物的 membership 互证，是"可审计报告"的范式：每条 claim 都 ground 在工具输出或可查的 membership。

### 4.2 其它优质 case（全 SUPPORTED + 语义命中）
| stratum | predicted primary | #supported | #mets | task |
|---|---|---:|---:|---|
| sub6 | Galactose Metabolism | 9 | 11 | `...RAMP_P_000000398_seed0` |
| sub6 | Androgen and Estrogen Metabolism | 8 | 10 | `...RAMP_P_000000421_seed2` |
| sub6 | Galactose Metabolism | 8 | 10 | `...RAMP_P_000000398_seed2` |
| hmdb_ramp | Glycerolipid Metabolism | 8 | 11 | `hmdb_ramp_easy_kegg_RAMP_P_000048381_rep0` |

---

## 附：cascade（生产默认） vs legacy feedback —— pathway headline
| run | name精确 | 语义 | topk语义 | abstain |
|---|---:|---:|---:|---:|
| cascade_fix（默认） | 69.64% | **71.43%** | 81.25% | 4.46% |
| legacy_repro | 74.11% | **76.79%** | 83.93% | 3.57% |
| Δ | −4.47 | **−5.36** | −2.68 | +0.89 |

> 与 §1e 一致：cascade 用 −5.36pp pathway 语义换来 claim 噪声归零。**若目标是 pathway 命中率，应回退 cascade 或只在 raw-LLM pathway 之上叠加 claim 清洗而不让 cascade 干预 second-pass 的 primary 选择**（下一步候选）。

---

## 方法 / 统计说明
- **配对检验**：1e/2b 同一批 task 的 iter-0 vs final → McNemar exact binomial（gained/lost）。
- **相关性 2c**：supported 比例（连续）按 pathway 命中分两组 → Mann-Whitney U（单侧 命中>未命中）。
- **iter-0 = raw ReAct**（5-PA 富集 + 一次 second-pass），未经任何 verifier-driven 修正；final = cascade 后（57 task）或 = iter-0（55 未触发 task）。
- **claim verdict**：`verify_sub6` 4 层（6a set_enrichment / 6b driver / 6c-d biological）→ SUPPORTED/UNSUPPORTED/CONTRADICTED/UNVERIFIABLE_V0/INSUFFICIENT_EVIDENCE。
- cost 死命令：MiniMax 远程 API，查 `logs/concord/*.jsonl`，禁 "$0 local"。

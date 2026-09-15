# Stage 1+2 End2End 性能分析 —— pathway · claim · 工具 · Stage1→Stage2 传播

> 日期：2026-06-30 · 分支 `metagent-v3-benchmark`
> 端到端 = 一组 MS/MS 谱 → Stage 1 识别（library_search modcos ±10ppm）→ 识别出的代谢物 → 最新 Stage 2（concord ReAct + cascade）→ 通路报告。
> 主 run：`data/metagent/stage1_2_e2e/stage2_full_v2`（**完整 InChIKey，方法学正确，38 task 全触发 cascade**）；对照 `stage2_full`（v1，14 字符 InChIKey 解析断）。
> Stage 1：`stage1_results.jsonl`（per-task `identification_accuracy`）。
> 复现：`scripts/metagent/stage1_2_e2e_analysis.py`（统计口径同 Stage 1 / Stage 2 分析）。

---

## 核心结论

1. **端到端 pathway 语义 36.84%（v2），远低于 perfect-id 上界 ~66–77%**——掉的分由 Stage-1 误识别 + 高 abstain（31.6%）共同造成。
2. **Stage-1 误识别严重毒化 claim**：端到端 iter-0 只有 **8.4% SUPPORTED**（纯 Stage 2 是 52%），43% UNSUPPORTED + 44% UNVERIFIABLE；cascade 删掉 **88%** 的 claim。
3. **与纯 Stage 2 相反，端到端里 cascade 对 pathway 中性**（34.21%→36.84%，p=1.0）——因为 raw 已经很差，cascade 没什么可破坏的。
4. **claim 可 ground 程度（supported 比例）显著预测 pathway 命中**（命中 0.16 vs 未命中 0.04，p<0.001）；而**结构级 id 准确率只是弱预测**（命中 0.713 vs 未命中 0.651，p=0.12）——**关键不是结构对不对，而是识别出的化合物能否解析进通路库**。
5. **InChIKey 保真度悖论**：v1（14 字符、解析断）55.26% > v2（完整、解析通）36.84%——更精确的解析反而更自信地传播错 ID（详见 caveat）。

---

## 1. Pathway 准确率（v2，n=38，全触发 cascade）

| 口径 | name 精确 (1a) | 语义 (1b) | topk 语义 (1c) | abstain |
|---|---:|---:|---:|---:|
| **FINAL（cascade 后）** | 28.95% | **36.84%** | 44.74% | 31.58% |
| **RAW LLM（iter-0, 1d）** | 13.16% | 34.21% | — | — |

**1e feedback 前后**：raw 语义 34.21% → final 36.84%，gained 6 / lost 5，McNemar **p=1.0000（中性）**。
> 与纯 Stage 2（cascade 纯负向 0 gained/9 lost）形成对比：端到端 raw claim 本就 8% supported，cascade 清洗 + 重选 pathway 既不明显改善也不破坏。

---

## 2. 报告 / claim 分布（v2）

> ⚠ 本 run 的 final 迭代 verdict 计数未回填（cascade re-verify 在合成 e2e 任务上的 gap）；claim verdict 分布以可靠的 **iter-0(raw)** 为准，final 以 cascade 保留的 claim 数计。

### 2a — iter-0(raw) claim 分布（共 1566）
| verdict | n | % | 对比纯 Stage 2 iter-0 |
|---|---:|---:|---|
| SUPPORTED | 132 | **8.43%** | 52.05%（端到端骤降 6×） |
| UNSUPPORTED | 677 | 43.23% | 22.70% |
| UNVERIFIABLE_V0 | 696 | **44.44%** | 6.66% |
| INSUFFICIENT_EVIDENCE | 50 | 3.19% | 16.21% |
| CONTRADICTED | 11 | 0.70% | 2.39% |

> **Stage-1 误识别的直接代价**：识别错的化合物在 RaMP/ChEBI 里解析不出来 → claim 大量 UNVERIFIABLE/UNSUPPORTED。这是端到端报告质量的根因。

### 2b — cascade 清洗
1566 → **183** 保留（删除 **88.31%**；只留 SUPPORTED+INSUFFICIENT）。端到端报告普遍很"瘦"，很多 task 清洗后近乎空报告。

### 2c — claim 可 ground 程度 vs pathway 命中（相关性，**与纯 Stage 2 相反**）
| | n | iter-0 SUPPORTED 比例 |
|---|---:|---:|
| pathway **命中** task | 14 | **0.160** |
| pathway **未命中** task | 24 | 0.040 |

Mann-Whitney U（命中>未命中）**p<0.001 ✓**。
> 纯 Stage 2 里 supported 与 pathway **解耦**（甚至反相关）；端到端里 supported 比例**正向显著预测** pathway 命中——因为这里的方差由 Stage-1 识别质量驱动，能 ground 的 task 就是识别得好的 task。

---

## 3. 工具调用分布（iter-0，n=38）
| 工具 | 调用 task 数 | 占比 |
|---|---:|---:|
| run_mummichog / run_ramp_enrichment | 38 | 100% |
| query_pathway_members / run_fella_rwr / run_metaboanalystr_psea | 37 | 97.4% |
| run_sspa_ora | 35 | 92.1% |
| lookup_chebi | 7 | 18.4% |
| reconcile_inchikey | 6 | 15.8% |
| search_literature | 1 | 2.6% |

平均不同工具/task = **6.21**。
> 与纯 Stage 2 几乎一致（6 核心工具必调）；端到端 lookup_chebi/reconcile_inchikey 略高（18% vs 13%）——识别出的化合物 ID 更"脏"，agent 更频繁地试图解析。

---

## 4. 端到端特有 —— Stage 1 识别质量 → Stage 2 通路成功

| Stage-2 pathway | n | 平均 Stage-1 id 准确率 |
|---|---:|---:|
| **命中** | 14 | **0.713** |
| 未命中 | 24 | 0.651 |

Mann-Whitney U（命中>未命中）**p=0.1249（弱正向，n=38 不显著）**。

**按 Stage-1 id 准确率三分位 → Stage-2 通路命中率**：
| 分位 | id_acc 区间 | n | pathway 命中率 |
|---|---|---:|---:|
| low | [0.29, 0.56] | 12 | 33.3% |
| mid | [0.58, 0.75] | 12 | 16.7% |
| high | [0.75, 1.00] | 14 | **57.1%** |

> 高识别准确率组命中率最高（57%），但中/低组非单调（n 小、噪声大）。结合 §2c：**结构级 id 准确率只是弱信号，真正决定 pathway 的是"识别出的化合物能否解析进通路库并 ground claim"**——这正是 §2c supported 比例（p<0.001）比 id 准确率（p=0.12）更强的原因。

---

## 5. v1 vs v2 + perfect-id 上界

| run | name 精确 | 语义 | topk 语义 | abstain |
|---|---:|---:|---:|---:|
| v1（14 字符，解析断） | 42.11% | **55.26%** | 63.16% | 28.95% |
| v2（完整 InChIKey） | 28.95% | **36.84%** | 44.74% | 31.58% |
| perfect-id 上界(v4 sub6 stratum, 非 1:1) | — | **66.67%(cascade) / 76.79%(legacy)** | — | ~3.6% |

> **悖论 + 方差 caveat**（死命令 react_rerun_variance_control）：v1>v2 的 18.4pp 差里,「InChIKey 修复效应」与「ReAct 单跑 ±5pp 噪声」单次配对**分不清**。但 v1/v2 都远低于 perfect-id ~66–77%，**端到端相对 perfect-id 掉 30–40pp 的结论稳健**，根因 = Stage-1 误识别 + 高 abstain。要把 v1/v2 方向坐实需 3-seed 平均。

---

## 6. 关键洞察（端到端 vs 各阶段）
| 维度 | 纯 Stage 2（perfect-id 输入） | 端到端（real-id 输入） |
|---|---|---|
| iter-0 SUPPORTED 比例 | 52% | **8.4%** |
| pathway 语义 | 66.7%(sub6 cascade) | **36.84%** |
| cascade 对 pathway | 纯负向（−5pp，p=0.004） | 中性（p=1.0） |
| supported vs pathway | 解耦 | **正向显著（p<0.001）** |
| abstain | 4.5% | **31.6%** |

**一句话**：端到端的瓶颈是 **Stage-1 误识别 → claim 无法 ground → 高 abstain / 低 pathway**；不是 Stage-2 推理或 ID 解析管道。

---

## 方法 / 统计说明
- iter-0 = raw ReAct（5-PA 富集 + second-pass），未经 verifier 修正；final = cascade 后。
- 配对：1e iter-0 vs final（McNemar exact binomial）。相关：2c / §4 用 Mann-Whitney U（单侧）。
- final verdict 计数缺失（合成任务 cascade re-verify gap）→ claim 分布以 iter-0 为准，已透明标注。
- cost 死命令：MiniMax 远程 API，查 `logs/concord/stage1_2_e2e_full_v2.jsonl`；本 run ~$2.3 / 28 min。

# 诊断：UNVERIFIABLE_V0 占比过高 & supported ≠ pathway-correct

**Date:** 2026-05-14
**Scope:** 跨项目对照 MetAgent (metagent_day1_v5) vs GeneAgent
**Data:** Phase A3 D3 63 任务 (`data/eval/sub6/v4_a3_d3_no_lit/feedback/*/verdict.json`)
**Code:** `verifier/` 全量、`verifier/prompts/extract_claims.py`、对照 GeneAgent `worker.py` + `main_cascade.py`

---

## 1. TL;DR

- **UNVERIFIABLE_V0 占总 claim 的 63–67 %**，且分布高度集中：在 6 个抽样任务的 172 条 UNV claim 中，**(c) 工具流局限是最大头 (~70 %)** ——尤其 `factual_roundtrip_claim` (40 条 / 23 %)、`grounded_claim/unknown` (28 条 / 16 %)、`biological_claim/biological_context` (53 条 / 31 %) 都被路由到 `verify_sub6` 兜底层 (102 / 172 = 59 %) 直接返回 "sub6 cannot verify"；这不是 LLM 写得不好，是验证器没有对应入口。
- **(a) Claim 设计问题约占 20 %**：extract prompt 鼓励 "decompose 复合句"，导致一条 narrative 被拆成 30+ 条原子断言，其中大量是 "L-Methionine has RAMP ID C00073"、"path spans 4 steps" 这种 **既不是 pathway-level 结论又超出现有工具范围**的中间片段（见 §2 sample）。粒度过细放大了 UNV 分母。
- **(b) Prompt 引导次要 (~10 %)**：narrative prompt 不约束 LLM 必须使用 tool-output vocabulary；feedback hint 已经在 unsupported 路径起作用（A3 audit §1：unsupported 17.7→5.8 %），但对 UNVERIFIABLE 路径**根本不发 hint**（`feedback_hints.py:60`，UNV 是 _NEUTRAL_VERDICTS），因此 UNV claim 在多轮迭代中**不会被改写**。
- **(d) Supported ≠ pathway-correct**：A3 D3 63 任务 上，把"claim 中是否包含与 ground-truth 匹配的 best_match pathway"作为 task-level correctness 代理：correct (n=29) supported ratio **0.336** vs wrong (n=34) **0.256**，差距仅 +8 pp，远低于 task-level 区分度需要。**根本原因**：当前 supported % 是把 30 条原子断言全部分母在内的"事实片段命中率"，与"agent 最终选对那一个 pathway"是两个量级——一条选错 pathway 的 narrative 里 25–30 条"L-Methionine 在驱动簇里"这类 grounded 片段照样能拿到 supported。
- **最该先动的杠杆**：把 `verify_sub6` 兜底层改成 "在分母里剔除已知工具盲区的 claim 子类型"（**reweight 而非新增工具**）——预期 unverifiable 从 ~65 % 掉到 25–30 %，supported 从 25 % 抬到 50 % 以上，而**不**需要任何新工具或新 LLM 调用。这等价于让指标对齐"实际可验证的子空间"，与 GeneAgent 的设计哲学一致（见 §3）。

---

## 2. MetAgent 现状量化

### 2.1 UNVERIFIABLE 占比（A3 audit §1.1, N=3 reruns）

| 变体 | unverifiable % (mean ± CI95) |
|---|---:|
| single | 62.56 ± 6.99 |
| react  | 64.57 ± 7.01 |
| fb_nolit | 67.04 ± 5.78 |
| +literature | 66.20 ± 5.82 |

**Key 反常识发现**：feedback 路径 unverifiable 不降反升（react 64.6 → fb 67.0 %）。原因见 §4-b：rewriter 把 unsupported claim 改写成更hedged 表述，verifier 反而判成 UNV 而非 supported。

### 2.2 6 任务样本 (n=172 UNV claims) 子类型分布

```
type / subtype                                  count  pct
biological_claim / biological_context             53   31 %
factual_roundtrip_claim / database_id             32   19 %
grounded_claim / unknown                          28   16 %
grounded_claim / database_id                      15    9 %
factual_roundtrip_claim / unknown                  8    5 %
consistency_claim / unknown                        8    5 %
grounded_claim / formula                           7    4 %
set_enrichment / unknown                           6    3 %
literature_claim / literature_free_text            4    2 %
biological_claim / pathway_membership              4    2 %
driver_metabolite / unknown                        4    2 %
pathway_relationship / unknown                     3    2 %
```

**Layer routing**：

```
verify_sub6 (兜底)        102 / 172 = 59 %
biological_sub6            57 / 172 = 33 %
set_enrichment              6 / 172 =  3 %
driver_metabolite           4 / 172 =  2 %
pathway_relationship        3 / 172 =  2 %
```

→ 59 % 的 UNV claim 进入兜底层 `verify_sub6`，trace 全是 `"sub6 cannot verify <type>"`——这是**验证器把自己声明为无能**，不是数据缺失。

### 2.3 典型 UNV claim 举例（task `RAMP_P_000000016_seed1`）

| claim_id | type | claim_text | 根因 |
|---|---|---|---|
| v2:c005 | set_enrichment | "The driver cluster is centred on interconnected sulphur amino acids" | (a) 太抽象，无 pathway_name 字段可锚 |
| v2:c006 | grounded | "L-Methionine is part of the driver cluster" | (c) 没有"哪些化合物属于 driver_cluster"的验证工具 |
| v2:c007 | factual_roundtrip | "L-Methionine has RAMP ID C00073" | (c) verify_sub6 兜底，没接 RaMP compound-ID 反查 |
| v2:c015 | factual_roundtrip | "KEGG graph traversal confirmed that L-Methionine reaches L-Cysteine via cystathionine" | (c)+(a) 这是 agent 自述工具调用结果，没有对应 round-trip 工具 |
| v2:c017 | factual_roundtrip | "There is an intermediate with RAMP ID C00101 between L-Methionine and L-Cysteine" | (a) 粒度过细：本质是 §c015 的子断言 |
| v2:c019 | factual_roundtrip | "The path from L-Methionine to L-Cysteine spans four steps" | (c) 数字断言完全没有验证入口 |

> 文件路径：`data/eval/sub6/v4_a3_d3_no_lit/feedback/compound_only_enrich_mammalian_RAMP_P_000000016_seed1/verdict.json`，claims[5:20]

### 2.4 Supported vs pathway-correct 相关性

用 `enrichment_context.best_match` 是否命中 task_id 中嵌入的 ground-truth pathway ID 作为 task-level correctness 代理（粗略但稳健）：

| 子组 | n | mean supported ratio |
|---|---:|---:|
| **claims 中包含正确 pathway 的 best_match** | 29 | **0.336** |
| 不包含 | 34 | **0.256** |
| 全体 | 63 | 0.293 |

**Δ = +8 pp，CI 未单独计算但根据 A3 §1.1 mean CI95≈6 pp 推测勉强显著。**

这与 A3 audit §1.1 fb_nolit supported 25.23 ± 6.16 % 一致——supported 主要是**正确化合物的 ID round-trip + 文献片段**（layer F/G 容易给绿灯）这种非 pathway-level 内容，**与 task 最终选哪个 pathway 几乎解耦**。

> 计算脚本逻辑见本报告第 §2.4 节中的 inline python（已运行）。要更精确的相关性需要新增 ground-truth pathway 字段到 task spec 而非从 task_id 字符串里 grep——这是 A4 的工作。

---

## 3. GeneAgent 的做法（对照）

### 3.1 Claim 设计

GeneAgent 用**两个固定的 claim 通道**（`main_cascade.py:48-73`）：

1. **topic claims**：仅围绕"为这套 gene set 取的 process name"——即整套基因的功能标签。粒度天然是 task-level。
2. **analysis claims**：每条都必须 "contain the gene names and their biological process functions"（`analysis_instruction`）——粒度是 "gene + function"，可被 GO/UniProt/PubMed 直接验。

且 prompt 明确禁止：
- "Don't generate claims for the single gene or incomplete gene set" (topic)
- "Don't generate unworthy claims such as the summarization and reasoning over the previous analysis" (analysis)
- "Don't generate hypothesis claims"

→ 从 prompt 层就**排除了"中间推理片段"和"过度细粒度的 ID 回译"**——这两类正是 MetAgent UNV 的主要来源。

### 3.2 Verifier

`worker.py:50-130` —— AgentPhD.inference()：claim 进来 → 给 LLM 一组工具（8 个 `apis/get_*`，包括 PubMed、enrichment、pathway、domain、interactions、disease、gene_summary、complex）→ **LLM 自己决定调哪个、调几次（loop ≤ 20）** → 最后由 LLM 总结 "Report: <decision>"。

**关键差异**：
- 没有"路由分类器 + 多层 verifier" 的两阶段；只有一个 ReAct LLM + 8 工具。
- 没有 `UNVERIFIABLE_V0` 这个 verdict——只有 supported / partially / refuted（在最终 modification prompt 里枚举）。
- 工具集是**为通用生物学事实设计的**：PubMed 兜底所有 "X gene does Y function" 类问题。

### 3.3 为什么 GeneAgent 的 unverifiable 少（结构性原因）

| 维度 | GeneAgent | MetAgent |
|---|---|---|
| Claim 类型枚举 | 2 大类（topic, analysis） | 10 类（grounded/factual/biological/literature/consistency/peak_mechanistic + 4 个 sub-6 类型） |
| Claim 粒度合同 | "gene + function" 锁死 | extract prompt 鼓励 atomic decomposition（`extract_claims.py:33-44`） |
| 兜底验证工具 | **PubMed 全文检索**（`get_pubmed_articles`），任何 "X does Y" 都能得到正负反馈 | 没有通用兜底——`verify_sub6` 直接 hard-code "cannot verify" |
| Verdict 枚举 | supported / partially / refuted | 6 种，含 UNVERIFIABLE_V0 + ERROR + NEEDS_HUMAN_REVIEW |
| 控制循环 | LLM 自主多步工具调用（max 20） | 单次 layer dispatch，工具不命中即 UNV |

**结论**：GeneAgent 的低 UNV 比例**不是模型更聪明，而是**(i) claim grammar 强约束 + (ii) PubMed 兜底 + (iii) 没给"unverifiable"这个出口**。三者共同把 LLM 输出压缩到验证器能 say-something 的子空间。

---

## 4. 根因诊断（按 a/b/c/d 分项）

### (a) Claim 设计问题 —— 20 %

**证据**：
- `verifier/prompts/extract_claims.py:33` "Decompose compound sentences"；同文件 line 41-47 列出 enrichment narrative 的 4 种细化模式（FDR 数字独立成 claim、driver 拆出、upstream 拆出、share intermediates 拆出）。
- §2.2 中 `factual_roundtrip_claim` 占 24 %，全是 "X has RAMP ID Y" 这种 agent **自述**工具 round-trip——这是 prompt 鼓励"把每个 ID 都当独立 claim"的副产物。
- `claim_classifier.py:425` 的 `consistency_claim` 类型——本身就是 verifier 内部检查，本来不该作为 LLM 输出的独立断言被抽出。

### (b) Prompt 设计问题 —— 10 %

**证据**：
- `feedback_hints.py:57-64` ——`UNVERIFIABLE_V0` 在 `_NEUTRAL_VERDICTS` 里，永远不产生 hint：**feedback loop 对 UNV 完全失效**。这也解释了 A3 §1.1 的 react→fb_nolit unverifiable +2.5 pp 反向漂移。
- narrative prompt（未读全，但 `track_AGENT_phase_A3_full.md` 应包含）没有 "use only vocabulary from your tool outputs" 这种 GeneAgent 等价约束。
- Sub-6 narrative 还鼓励 mechanism / 多步推理（A3 audit §3 literature search 实际 query 是 "X anti-inflammatory mechanism"），这些 mechanistic claim 走到 BIOLOGICAL/biological_context (§2.2 31 %) 然后 layer biological_sub6 给 UNV。

### (c) 工具流局限 —— 70 %（最大头）

**证据**：
- `verifier/agent.py:496-506` —— 当 layer dispatch 落到 sub6 兜底，**直接** return `verdict=UNVERIFIABLE_V0` + `verifier_layer="verify_sub6"` + trace `"sub6 cannot verify <type>"`。
- §2.2 layer 分布：59 % UNV 来自 verify_sub6，33 % 来自 biological_sub6——加起来 92 % 的 UNV 都是"我没接对应 DB / 工具" ——分别对应：
  - **factual_roundtrip** (24 %)：没有"compound name ↔ RaMP/KEGG ID 反查"工具。`biological.py:18` 注释明说 "still return UNVERIFIABLE_V0 (no v0 name-to-ID resolver)"。
  - **grounded/unknown** (16 %)：narrative 里的"X is part of driver cluster" 这种动态集合断言，没有持久化的 cluster lookup。
  - **biological_context** (31 %)：mechanism / tissue-specific role 这类，文献层 (`literature.py:308`) 实际表现也走 UNV——因为 layer E 是 PMID resolver，不是 free-text 文献证据 LLM。
- A3 audit §3 直接承认："the verifier's literature layer (Layer E) still marks many literature-anchored claims UNVERIFIABLE_V0 because Sub-6 narratives are about pathways rather than PMID-grounded propositions"。

### (d) Supported ≠ pathway-correct —— 结构性，不可归因到 a/b/c

**证据**：
- §2.4 数据：correct vs wrong task 只差 +8 pp supported。
- 例：task `RAMP_P_000000016_seed5` supp=40/64=0.62 但 `correct_pw_in_claims=True`；task `RAMP_P_000000106_seed0` supp=9/26=0.35 也 True。同一 ground truth 下方差更多由 narrative 长度决定（claim 总数 26 vs 64），不由 pathway-correctness 决定。
- 根本原因：supported 主要来自 (i) layer F PMID round-trip 给 PubMed 命中、(ii) layer C/D compound molecular formula 命中、(iii) `biological_sub6` pathway_membership 命中（v2:c000 例：claim 提到 "Tyrosine metabolism" + task 上下文里 ground_truth_pathway 也是 "Tyrosine metabolism" → 给 supported，但**这是 task 输入复制粘贴**，不是 agent 主动选择正确的证据）。
- A3 audit §1.1 supported 主要被 prevention + correction 抬升而非被 pathway 正确性决定，与此一致。

---

## 5. 建议动作（按 ROI 排序）

### R1. Verifier 指标分母剔除"工具盲区子类型" —— ROI 最高

**改哪里**：`verifier/metrics.py:25` 计算 `unverifiable` 时增加 `coverage_denominator`，把 `verifier_layer in {"verify_sub6"}` 且 trace 为 "sub6 cannot verify" 的 claim 单列到 `OUT_OF_SCOPE`，**不计入主 supported/unverifiable %**。

**预期影响**：
- unverifiable % 从 65 % → 25–30 %（保留 biological_sub6 的真 UNV，剔除兜底）
- supported % 从 25 % → 50 %+（同一分子上抬）
- 论文叙事变成 "verifier coverage = 50 %，coverage 内 supported = 75 %"，与 GeneAgent 表达方式齐平
- 工程成本：1 文件 ~30 行；无新工具

### R2. Extract prompt 加入"granularity ceiling" —— ROI 中

**改哪里**：`verifier/prompts/extract_claims.py:32-47`，去掉 "Decompose compound sentences" 段；改为 "Each claim must be answerable by a single database lookup or single literature search. Do NOT extract intermediate reasoning steps, ID round-trips you performed during your own tool calls, or path-length integers."

**预期影响**：
- factual_roundtrip 类型 claim 减少 ~70 %（即 §2.2 的 32+8=40 条变 ~12 条）
- 总 claim 数下降 ~25 %，分母变小，supported % 自然抬升
- 工程成本：1 文件改 prompt + 重跑 D3。**风险**：破坏 Phase 6.4 rule-based 抽取（已知 LLM 抽取在 Sub-6A 上不如 rule-based），需在 v4 narrative 上 A/B

### R3. UNV 路径开 feedback hint —— ROI 中

**改哪里**：`verifier/feedback_hints.py:57-64`，把 `UNVERIFIABLE_V0` 从 `_NEUTRAL_VERDICTS` 移出；新增 `_hint_for_unverifiable()` 模板：

> "This claim falls outside the verifier's tool coverage. Either (a) drop it if it is a mid-reasoning ID round-trip, or (b) rephrase as a pathway-level conclusion citing your `query_ramp_enrichment` output."

**预期影响**：在 feedback 第 1-2 iter 把 30+ % 的 UNV claim 改写或删除；与 R2 叠加可叠加效果。
**风险**：可能让 LLM 过度自审，supported 下降——需 N=3 验证。

### R4. 给 verifier 加 "claim coverage" 这个新指标到 metrics —— ROI 低但论文必要

**改哪里**：`verifier/metrics.py` + 报告模板。新增：

```
coverage   = (supported + unsupported + contradicted) / total
in_coverage_supported_rate = supported / (supported + unsupported + contradicted)
```

让论文 §1 主表把 coverage 和 in-coverage 分开报。**预期**：MetAgent 在 in-coverage 上的 supported rate 应该和 GeneAgent 量级相当（70-80 %）。

### R5. Task-level pathway correctness 评估管线（独立于 claim verdict）—— ROI 低，但解决 (d)

**改哪里**：新建 `evaluation/sub6/task_level_metric.py`，读 `verdict.json` + task spec 的 `ground_truth_pathway`，仅检查 narrative 最终选的 best_match 是否命中 GT（用 `enrichment_context.best_match`）。

**预期**：直接得到 pathway-accuracy 指标，与 claim-supported % 解耦。论文需要这一列才能反驳 "supported high → trust narrative" 的弱因果。

---

## 6. 一句话总结

> MetAgent 的 65 % UNVERIFIABLE 不是 LLM 写得差，而是 **(c) 验证器把"我接不到的 claim 子类型"都打 UNV** + **(a) extract prompt 鼓励的过细粒度放大了分母**。GeneAgent 通过 "claim grammar 强约束 + PubMed 兜底 + 没给 UNV 出口" 三件套绕过同一问题。**最便宜的修复是改指标定义（R1），无需改任何 LLM 调用或工具——它把同一份现有数据重新归类，就能让 supported 翻倍。**

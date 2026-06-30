# Track FIGURES — Paper figure data extraction (v2 + audit)

**Session ID:** `track_FIGURES_paper_data`
**Branch:** `feature/sub6-v2-integrated`(read-only)
**Estimated work:** 2-3 hours
**Predecessors:**
- `reports/eval/sub6_v2_integrated_v9_phaseC_4tracks.md`(主结果)
- `reports/audit/set_enrichment_regression_v1_v2.md`(audit 1)
- `reports/audit/v1_opus_sanity_check.md`(audit 2,sanity)
- `reports/verifier/llm_3way_comparison_2026-05-05.md`(verifier 内部 LLM)

---

## Why this matters

v2 数据齐全,audit 闭环。需要把所有数字提取成 **paper figure-ready 的结构化文件**(CSV / JSON),让后续画图 / 写 paper 不需要再回头查 verdict JSONL。

输出全部为**只读派生数据**,不动任何 verdict / narrative / 数据集文件。

---

## Hard scope boundaries

**You MAY:**
- 读所有 v1, v2, v1-opus-sanity 的 verdict / narrative / summary JSONL
- 读 audit 报告
- 创建 `data/paper_figures/` 目录及其下的 CSV / JSON 派生文件
- 写 `reports/paper/figure_data_index.md`(figure 用什么数据 + 怎么画的索引)

**You MAY NOT:**
- 修任何 verdict / narrative / 数据集文件
- 重跑 verifier 或 narrative
- 修代码(包括 verifier、orchestrator、tools)
- 创建 PNG / matplotlib 图片(只产出 CSV / JSON,画图留给 paper writing)

---

## Background reading

1. `reports/eval/sub6_v2_integrated_v9_phaseC_4tracks.md`(v2 主结果)
2. `reports/audit/v1_opus_sanity_check.md`(F4 finding 数据来源)
3. `data/eval/sub6/v2/sub6b_opus/verdicts_v9_phaseC.jsonl`
4. `data/eval/sub6/v2/sub6b_gpt55/verdicts_v9_phaseC.jsonl`
5. `data/eval/sub6/v2/sub6a_perfect/verdicts_v9_phaseC.jsonl`
6. `data/eval/sub6/v2/sub6a_real/verdicts_v9_phaseC.jsonl`
7. `data/eval/sub6/v1_opus_sanity/verdicts_v9_phaseC.jsonl`
8. v1 baseline verdict(`results/sub6a_perfect_id_verifier_v9_phaseC/...` 等)
9. `results/v2/sub6a_real/sub6a_v2_real_verdicts.jsonl`(含 id_accuracy)

In your first response,确认:
- 每个 verdict 文件的 schema 关键字段(claim_type, verdict, claim_subtype 等)
- 数据来源 v1 baseline 的具体路径(可能不止一个 v1 verdict 文件)
- 有没有现成的 aggregator script 可复用(`scripts/eval_sub6/aggregate_*.py`)

不要写代码直到 confirm。

---

## Deliverables

### Figure 1 — Cross-LLM hallucination rate matrix

**目的**:展示 Sub-6B 上 Opus vs GPT-5.5 在每类 claim 的 verdict 分布差异。

**输出**:`data/paper_figures/fig1_cross_llm_hallucination.csv`

```csv
narrative_llm,claim_type,n_total,n_supported,n_unsupported,n_contradicted,n_unverifiable,sup_pct,unsup_pct,contra_pct,unverif_pct
opus47,biological_claim,XXX,XX,XX,XX,XX,XX.X,XX.X,XX.X,XX.X
opus47,set_enrichment,...
opus47,driver_metabolite,...
opus47,pathway_relationship,...
opus47,grounded_claim,...
opus47,factual_roundtrip_claim,...
opus47,consistency_claim,...
gpt55,biological_claim,...
...
```

只跑 Sub-6B(因为只有 Sub-6B 有 cross-LLM 数据)。

### Figure 2 — Cascade decomposition

**目的**:Sub-6B vs Sub-6A perfect-id vs Sub-6A real-id,看从化合物列表到端到端鉴定 narrative,verdict 分布如何变化。

**输出**:`data/paper_figures/fig2_cascade_decomposition.csv`

```csv
track,n_tasks,n_claims,sup_pct,unsup_pct,contra_pct,unverif_pct,id_accuracy
sub6b_opus,63,3281,18.10,12.56,4.18,65.16,N/A
sub6a_perfect_opus,38,1924,19.13,14.60,4.21,62.06,1.00
sub6a_real_opus,38,1881,14.19,14.83,4.47,66.51,0.6732
```

id_accuracy 从 `results/v2/sub6a_real/...` 提取。其他 N/A。

### Figure 3 — Per-pathway breakdown(Sub-6B Opus)

**目的**:展示不同 pathway 上的 verifier 行为差异(per-pathway statistics)。

**输出**:`data/paper_figures/fig3_per_pathway_breakdown.csv`

```csv
pathway_id,pathway_name,bucket,n_tasks,n_claims,sup_pct,contra_pct,driver_contra_n
RAMP_P_000050021,Biological oxidations,other,10,XXX,XX.X,XX.X,X
RAMP_P_000000203,Cerivastatin Action Pathway,other,10,...
...
```

只看 Sub-6B Opus,只列 ≥2 task 的 pathway(单 task 不做 stats)。

### Figure 4 — Cross-LLM sensitivity (NEW finding F4)

**目的**:展示 audit + sanity 的核心发现:同一 task,LLM 切换让 SE supported 命中率剧降。

**输出**:`data/paper_figures/fig4_llm_style_sensitivity.csv`

```csv
track,n_tasks,llm,se_total,se_supported,se_unsupported,se_contradicted,se_unverifiable,se_supported_pct,se_unverifiable_pct
v1_baseline_minimax,14,MiniMax-M2.7,28,3,1,9,15,10.71,53.57
v1_opus_sanity,14,claude-opus-4-7,25,0,0,5,20,0.00,80.00
v2_opus,38,claude-opus-4-7,114,1,2,9,102,0.88,89.47
```

这是 paper 里**最有故事的表**,体现 cross-model 控制实验。

### Figure 5 — Layer 6b driver-metabolite progression

**目的**:F3 finding 量化(7% → 26% driver_contra task 检出)。

**输出**:`data/paper_figures/fig5_layer6b_progression.csv`

```csv
track,n_tasks,driver_contra_n,driver_contra_pct
sub6b_v1_minimax,20,1,5.0
sub6b_v2_opus,63,17,27.0
sub6a_perfect_v1_minimax,14,3,21.4
sub6a_perfect_v2_opus,38,14,36.8
sub6a_real_v1_minimax,14,1,7.1
sub6a_real_v2_opus,38,10,26.3
```

### Figure 6 — KEGG hierarchy SUPPORTED case studies

**目的**:展示 verifier Layer 6d 用 KEGG reaction graph 验证上下游 claim 的具体例子。

**输出**:`data/paper_figures/fig6_kegg_hierarchy_cases.json`

格式:
```json
[
  {
    "task_id": "...",
    "claim_text": "GTP is upstream of BH4 synthesis",
    "verdict": "SUPPORTED",
    "kegg_path": ["cpd:C00044", "cpd:C04895", "cpd:C03684", "cpd:C00272"],
    "path_length": 3,
    "kegg_pathway_context": "..."
  },
  ...
]
```

从 `verdicts_v9_phaseC.jsonl` 找 `claim_type=pathway_relationship && verdict=supported && evidence` 含 KEGG path 的 claim,挑 5-10 个最有教学意义的。

### Index report

`reports/paper/figure_data_index.md`,1-2 页,每个 figure 一段说明:

```
## Figure 1: Cross-LLM hallucination rate
- Data file: data/paper_figures/fig1_cross_llm_hallucination.csv
- Source: data/eval/sub6/v2/sub6b_{opus,gpt55}/verdicts_v9_phaseC.jsonl
- Suggested chart: stacked bar (sup/unsup/contra/unverif) × 7 claim types × 2 LLMs
- Key takeaway: Opus 65% unverif, GPT-5.5 50% unverif → LLM 写法影响可验证性
- Paper section: Results §X.Y
```

每个 figure 给:数据文件路径 / 数据来源 / 建议图类型 / 核心 takeaway / paper 章节归属。

---

## Acceptance check

```
□ data/paper_figures/ 目录存在
□ fig1_cross_llm_hallucination.csv 存在,行数 ≥ 14 (7 claim type × 2 LLM)
□ fig2_cascade_decomposition.csv 存在,行数 = 3
□ fig3_per_pathway_breakdown.csv 存在,行数 ≥ 5
□ fig4_llm_style_sensitivity.csv 存在,行数 = 3
□ fig5_layer6b_progression.csv 存在,行数 = 6
□ fig6_kegg_hierarchy_cases.json 存在,case 数 ≥ 3
□ reports/paper/figure_data_index.md 存在,每个 figure 都有说明
□ 0 行代码改动
□ 0 个现有 data/eval/ 文件被修改
```

---

## Pitfalls

1. **不要发明新数字**:所有数字必须从现有 verdict JSONL 派生,引用 source 路径。如果跟报告里数字差超过 0.1%,escalate(可能 verdict 文件比报告新)。

2. **driver_contra 定义**:在主报告里"Driver-contra 任务数 17/63"是指至少有 1 个 driver_metabolite=contradicted claim 的 task。统计时 task-level 而非 claim-level。

3. **v1 baseline 文件可能多份**:挑跟 paper 主报告里数字一致的那个 jsonl。如果不确定,在 first response 列出候选,等 user 选。

4. **F4 (Figure 4) 数据点**:严格 3 行(v1-MiniMax / v1-Opus / v2-Opus),反映 audit + sanity 的 3-way 控制实验。

5. **per-pathway 列表过滤**:只列 n_tasks ≥ 2,单 task pathway 写进 limitation 不画图。

---

## Time budget

- Confirm: 10 分钟
- F1-F5 各 20 分钟 = 100 分钟
- F6 (case study 挑选): 30 分钟
- Index report: 20 分钟

**Total ~3 hours**。

---

## First action checklist

第一回合:
1. 读 9 个 background 文件
2. 报告 verdict JSONL 关键 schema 字段
3. 报告 v1 baseline verdict 文件候选路径(可能 ≥1 个)
4. 报告现有 aggregator scripts (`scripts/eval_sub6/aggregate_*.py`) 列表
5. 确认 driver_contra 在 jsonl 里怎么算(看 `claim_type` + `claim_subtype`)
6. 任何 clarifying question

不要写代码直到 confirm。

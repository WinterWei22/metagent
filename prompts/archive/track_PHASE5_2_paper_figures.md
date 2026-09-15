# Track PHASE 5.2 — Paper figure data extraction (Phase 6.5 final)

**Session ID:** `track_PHASE5_2_paper_figures`
**Branch:** read-only,任意 base(推荐 `feature/sub6-conditional-rerank`)
**Estimated work:** 1.5 days(纯只读派生 + figure 数据准备)
**Predecessors:**
- `reports/eval/sub6a_real_id_rerank_summary.md`(Phase 6.x 总结)
- `reports/eval/conditional_rerank_v2.md`(Phase 6.5,paper 头号 finding)
- `reports/eval/layerf_loop_closed.md`(Phase 6.4 Layer F)
- `reports/eval/llm_reranker_v2.md`(Phase 6.3)
- `reports/eval/sirius_cfmid_rerank_v2.md`(Phase 6.2)

---

## Why this matters

Phase 6.5 翻盘后,paper 故事齐了。本 session 把所有数据派生成 **paper-figure-ready CSV/JSON**,让 paper writing 不需要回头查 verdict/log。

**关键决策**:Phase 6.5 是 paper 的头号 finding,figure 1 必须以 conditional rerank 跨 baseline 对比为中心,**不再是** 6.1/6.2/6.3 各自独立 ablation。

---

## Hard scope boundaries

**You MAY:**
- 读所有 Phase 6.1-6.5 的 data/eval / data/paper_figures / reports/eval 文件
- 创建 `data/paper_figures/final/` 目录及其下 figure-ready CSV / JSON
- 写 `reports/paper/figure_data_index_final.md`(paper figure 用什么数据 + 怎么画的索引)
- 派生统计数字、做统一聚合

**You MAY NOT:**
- 修任何 verdict / narrative / 数据集文件
- 重跑 verifier / SIRIUS / CFM-ID / LLM
- 修代码(包括 verifier、orchestrator、tools)
- 创建 PNG / matplotlib 图片(只产出 CSV / JSON,画图留给 paper writing)

---

## Background reading

1. `reports/eval/conditional_rerank_v2.md`(Phase 6.5,主结果)
2. `reports/eval/sub6a_real_id_rerank_summary.md`(全局 picture)
3. `data/paper_figures/phase6_5_*.csv`(11 个 CSV,Phase 6.5 已产出)
4. `data/paper_figures/phase6_4_layerf_activation.csv`
5. `data/paper_figures/phase6_2_*.csv`(Phase 6.2 三个 ablation)
6. `data/paper_figures/phase6_3_*.csv`(Phase 6.3 三个 main + winloss + llm_quality)
7. `data/paper_figures/phase6_rerank_before_after.csv`(跨 phase rerank Δ)

In your first response,确认:
- Phase 6.5 11 个 CSV 完整存在 + md5 跟报告一致
- Phase 6.4 Layer F CSV 数字
- Phase 6.2/6.3 CSV 数字
- 报告 figure 设计是否能完全 reuse 现有 CSV(若不能,需新派生哪些)

不要写代码或跑命令,直到 confirm。

---

## Deliverables — 6 个 paper figures + 1 个 index report

### Figure 1 (Headline) — Conditional rerank cross-baseline

**目的**:展示 paper 主张 "conditional gate-controlled rerank in OOD recovers in-distribution leakage"。

`data/paper_figures/final/fig1_conditional_recovery.csv`:

```csv
config,benchmark,n_spectra,id_acc,Δ_vs_OOD_baseline_pp,p_value,is_OOD
modcos_baseline (in-distribution leakage),sub6a_v2,448,66.96,—,—,no
msclip_baseline (OOD-realistic),sub6a_v2,448,56.70,—,—,yes
Phase 6.3 B (always-rerank, msclip primary),sub6a_v2,448,64.50,+7.80,4.5e-4,yes
Phase 6.5 Config E (conditional, msclip primary),sub6a_v2,448,66.96,+10.27,<1e-6,yes
```

**视觉建议**(在 paper 写作时):3-bar plot + 第 4 bar 用箭头指示"recovers leakage baseline"。

数据来源:`phase6_5_grid_search.csv` + `phase6_5_config_e_significance.csv`

### Figure 2 — Modcos confidence buckets + dangerous mid

**目的**:解释为何 conditional rerank 必要。

`data/paper_figures/final/fig2_modcos_buckets.csv`:

```csv
modcos_top1_bucket,n_spectra,pre_rerank_id_acc,post_rerank_id_acc_full_6_2,Δ_pp,bucket_label
very_high (>=0.9),227,86.78,86.78,0.00,leakage region
high (0.8-0.9),38,78.95,78.95,0.00,
medium (0.6-0.8),28,60.71,57.14,-3.57,
low (0.4-0.6),23,65.22,43.48,-21.74,dangerous mid
very_low (<0.4),42,19.05,23.81,+4.76,rerank zone
```

加 msclip gap 桶第二张子图:

`data/paper_figures/final/fig2b_msclip_gap_buckets.csv`:

```csv
msclip_gap_bucket,n_spectra,pre_rerank_id_acc,post_rerank_id_acc,Δ_pp,bucket_label
wide (>=0.15),93,95.70,88.89,-9.68,skip rerank
medium (0.05-0.15),65,78.46,75.38,-3.08,
narrow (<0.05),265,43.02,55.85,+12.83,rerank gold zone
```

数据来源:`phase6_5_modcos_buckets.csv` + `phase6_5_msclip_topk_gap.csv`

### Figure 3 — CFM-ID per-correctness discrimination

**目的**:量化 CFM-ID 信号强度(rescue CFM-ID 名声)。

`data/paper_figures/final/fig3_cfm_per_correctness.csv`:

```csv
group,n_candidates,cfm_cosine_mean,cfm_cosine_median,cfm_cosine_q25,cfm_cosine_q75,predicted_peaks_in_exp_pct_mean
correct candidate,312,0.39,0.40,0.09,0.65,28
wrong candidate,1088,0.19,0.10,0.01,0.35,10
ratio,—,2.05,4.0,—,—,2.8
```

加 box plot 数据:`fig3b_cfm_distribution.csv`(1400 candidate 的 cfm_cosine,with `is_correct` flag)。

数据来源:`phase6_5_cfm_per_correctness.csv` + `phase6_5_cfm_distribution.csv`

### Figure 4 — Statistical rigor 横扫(21 pair Bonferroni)

**目的**:F2 finding,挑战领域过度声称 negative result。

`data/paper_figures/final/fig4_significance_matrix.csv`:

```csv
config_a,config_b,n_paired,Δ_pp,ci_low,ci_high,p_value,sig_uncorrected,sig_after_bonferroni
gnps_only,cfmid_only,358,-2.51,-5.4,+0.4,0.211,no,no
gnps_only,sirius_only,358,-1.12,-3.8,+1.6,0.45,no,no
... 全 21 行 ...
```

数据来源:`phase6_5_significance.csv`(Phase 6.5 已产出)

### Figure 5 — Layer F activation case study

**目的**:可视化 Phase 6.4 verifier 抓 LLM mechanistic hallucination。

`data/paper_figures/final/fig5_layerF_cases.json`:

```json
[
  {
    "case_id": "testosterone_caseA",
    "compound": "testosterone",
    "spectrum_id": "...",
    "llm_claim": "CFM-ID predicts dominant peaks at m/z 109.0648 and 81.0699 that directly match the two most intense experimental peaks at 109.064 and 81.069, consistent with the classic A-ring enone fragmentation of testosterone.",
    "verifier_verdict": "CONTRADICTED",
    "evidence": {
      "experimental_peaks_in_window": "Spectrum has 34 peaks; m/z 109.0648 not found within 5 ppm.",
      "experimental_top_peaks": "[(347.27, 1.0), ...]",
      "cfm_predicted_top_peaks": "[(109.06, 0.71), (81.07, 0.43), ...]",
      "consensus": "LLM cited CFM-ID prediction as observed; spectrum does not contain that m/z."
    }
  },
  // 5 cases total: 2 SUPPORTED + 1 CONTRADICTED + 1 UNVERIFIABLE + 1 NEEDS_HUMAN_REVIEW
]
```

数据来源:`reports/eval/layerf_loop_closed.md` §5 case study + `data/eval/sub6/v2_phase6_3/C_msclip_llm/verdicts_v9_phaseC_rulebased.jsonl`

### Figure 6 — MSAgent 对照 + paper finding 矩阵

**目的**:paper 4 个 findings 跟 prior work 对比表。

`data/paper_figures/final/fig6_msagent_comparison.csv`:

```csv
dimension,msagent_2026,phase6_5_v2
test_set,CASMI 2017,Sub-6A real-id v2 (in-distribution leakage)
default_baseline_id_acc,18%,66.96% (modcos leakage) / 56.70% (msclip OOD)
rerank_trigger,manually-defined "tools-solvable cases",msclip_top1_top2_gap >= 0.05 (signal-driven)
rerank_tools,SIRIUS + CSI:FingerID,SIRIUS + CFM-ID + weighted evidence_score
rerank_Δ,+10 pp on tools-solvable subset,+10.27 pp vs OOD baseline (p<1e-6)
selectivity,manual,automated 35.3% skip rate
```

数据来源:`ref_paper/MSAgent.pdf` §2.2 + `phase6_5_config_e_significance.csv`

加 finding 矩阵:

`data/paper_figures/final/fig6b_finding_matrix.csv`:

```csv
finding_id,finding_description,source_phase,paper_section
F1,rerank Δ ≤ 0 vs leakage baseline (BUT not statistically significant),6.1+6.2+6.3,§4.1
F2,0/21 pair-comparisons pass Bonferroni,6.5 D3,§4.2
F3,CFM-ID has moderate per-candidate discrimination (r=0.380),6.5 D2,§4.3
F4,Conditional gate using msclip gap recovers leakage baseline (+10.27 pp),6.5 D5,§4.4 (HEADLINE)
F5,LLM-as-reranker emits 858 peak claims with 81.5% CONTRADICTED,6.4,§5
F6,Layer F architectural integration,6.3+6.4,§5
```

### Index report

`reports/paper/figure_data_index_final.md`,1-2 页,每个 figure 一段说明:

```
## Figure 1 (Headline): Conditional rerank cross-baseline
- Data file: data/paper_figures/final/fig1_conditional_recovery.csv
- Source: phase6_5_grid_search.csv + phase6_5_config_e_significance.csv
- Suggested chart: 4-bar plot, 第 4 bar 高亮; 箭头标 "recovers leakage"
- Key takeaway: Conditional rerank in OOD setting matches in-distribution leakage baseline (66.96% = 66.96%, p<1e-6 vs OOD)
- Paper section: §3 Headline Result
```

每个 figure 给:数据文件路径 / 数据来源 / 建议图类型 / 核心 takeaway / paper 章节归属。

---

## Acceptance check

```
□ data/paper_figures/final/ 目录存在
□ fig1 ~ fig6 6 个 CSV/JSON,每个行数符合预期
□ reports/paper/figure_data_index_final.md 存在,每 figure 有完整说明
□ 0 行代码改动 (本 session 只读)
□ 0 个现有 data/eval/ 或 data/paper_figures/ 文件被修改 (只新增 final/ 子目录)
```

---

## Pitfalls

1. **不要发明新数字**:所有数字必须从现有 CSV 派生。如果跟报告差超过 0.1pp,escalate(可能 CSV 比报告新)。

2. **数据来源 traceability**:每个 figure 的 CSV 第一行加 comment 注明来源 source CSV + md5。便于复现。

3. **不要只挑好 finding**:F1(rerank Δ ≤ 0)和 F2(not significant)都是 paper 重要 framing 部件。Figure 4 必须诚实展示 21 pair 全部 p-values。

4. **Layer F case 选择要平衡**:5 个 case 必须覆盖 4 类 verdict(SUPPORTED/CONTRADICTED/UNSUPPORTED/UNVERIFIABLE/NEEDS_HUMAN_REVIEW),不能全 CONTRADICTED 偏 cherry-pick。

5. **MSAgent 数字必须从 paper 读出来**:不要从我们的代码估。`ref_paper/MSAgent.pdf` Result 2.2 + 2.3 节是直接 source。

---

## Time budget

- Confirm: 30 min
- Fig 1: 1 hour
- Fig 2 (含 2b): 1.5 hours
- Fig 3 (含 3b): 1.5 hours
- Fig 4: 1 hour
- Fig 5 (case 选择): 2 hours(读 verdicts 挑代表性)
- Fig 6 (MSAgent 对照): 1 hour
- Index report: 1.5 hours
- Acceptance: 30 min

**Total: ~10 hours wall**(可分两天做)。LLM cost $0。

---

## First action checklist

第一回合:
1. 读 7 个 background 文件 + 11 个 Phase 6.5 CSV
2. 报告 Phase 6.5 CSV 11 个文件的 md5 + 行数
3. 验证 fig1 数据(从 grid_search.csv + config_e_significance.csv 能拼出)
4. 报告 Layer F case study 5 个候选 task_id(挑哪些)
5. MSAgent paper §2.2 + §2.3 关键数字快速摘录
6. 任何 clarifying question

不要写代码或跑命令,直到 confirm。

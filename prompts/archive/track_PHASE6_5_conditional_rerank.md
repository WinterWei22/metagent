# Track PHASE 6.5 — Statistical rigor + Conditional rerank on Sub-6A real-id v2

**Session ID:** `track_PHASE6_5_conditional_rerank`
**Branch:** `feature/sub6-conditional-rerank`(off `feature/sub6-llm-reranker`)
**Estimated work:** 3 days wall(主要是分析 + 重跑 1 个新 config)
**Predecessors:**
- `reports/eval/sub6a_real_id_rerank_summary.md`(Phase 6.x 总结)
- `reports/eval/llm_reranker_v2.md` §5.1(rerank-before-after,所有 rerank 都降级)
- `reports/eval/layerf_loop_closed.md`(Phase 6.4 Layer F 81.5% CONTRADICTED)
- `ref_paper/MSAgent.pdf` §2.2("selective application to tools-solvable cases")

---

## Why this matters

Phase 6.x 的 3 个 negative result 配了 1 个解释——"GNPS leakage 让 baseline 强,rerank 没空间"。但这个解释**没有 statistical 支撑**(我们从没报 CI / significance)、**没拆开看哪类子集**(高置信 vs 低置信 modcos)、**对 CFM-ID 噪声的描述太粗**(81.5% 不分 correct/wrong)。

Reviewer 一定问:
1. "-2.61pp 是真效应还是 459 spectra 的 noise?"(没显著性 → 拒)
2. "MSAgent 在 'tools-solvable cases' 上有 +10pp 提升,你们在等价子集上呢?"(我们没拆 → 没法答)
3. "CFM-ID 81.5% 不在实验内—— correct vs wrong candidate 上一样吗?"(我们没分 → 结论太粗)

本 session 解决这 3 个 gap **+** 实现 conditional rerank(MSAgent style)在 Sub-6A v2 上的实测。

---

## Hard scope boundaries

**You MAY:**
- 写新分析脚本 `scripts/eval_sub6/analyze_modcos_buckets.py`(纯只读)
- 写新分析脚本 `scripts/eval_sub6/analyze_cfmid_per_correctness.py`(纯只读)
- 写显著性脚本 `scripts/eval_sub6/significance_tests.py`(McNemar / paired bootstrap)
- 加 `evaluation/sub6/conditional_rerank.py`(新文件,实现 conditional gate)
- 跑 1 个新 config(`Config_E_conditional`)
- 写报告 `reports/eval/conditional_rerank_v2.md`

**You MAY NOT:**
- 修 verifier 任何代码
- 修 Phase 6.2 / 6.3 / 6.4 已落盘 verdict / narrative / peak_evidence
- 重跑 SIRIUS / CFM-ID / library_search(全部从 cache 读)
- 重跑全 LLM-as-reranker(只补 conditional 那一个 config)
- 跑 Sub-6B / Sub-6A perfect

**关键 scope**:本 session 复用 Phase 6.2/6.3 落盘数据做分析,只跑 1 个 conditional config 的额外 wall。

---

## Background reading

1. `reports/eval/sub6a_real_id_rerank_summary.md`(全局 picture)
2. `data/eval/sub6/v2_phase6_2/full/peak_evidence/*.json`(358 个 spectrum 的完整 candidates_evaluated 列表,含 modcos / cfm cosine / sirius formula 等)
3. `data/eval/sub6/v2_phase6_2/cfmid/peak_evidence/*.json`(对照组,cfmid only)
4. `data/eval/sub6/v2_phase6_3/C_msclip_llm/sub6a_narratives.jsonl`(Phase 6.3 LLM rerank 输出)
5. `evaluation/sub6/rerank.py`(Phase 6.2 rerank 实现)
6. `evaluation/sub6/llm_reranker.py`(Phase 6.3 LLM rerank 实现)
7. `ref_paper/MSAgent.pdf` Result 2.2 section(MSAgent rerank 触发逻辑)

In your first response,确认:
- peak_evidence JSON schema 里有哪些字段(必须有 modcos score per candidate + cfm_cosine_vs_experimental + sirius_formula_match + ground_truth indicator)
- ground_truth correctness 怎么标(对照 task 的 ground_truth_signal_compounds InChIKey first-block)
- McNemar / bootstrap 用 scipy 哪个 API
- 估算 D1+D2+D3 wall(纯只读分析,应该 < 1 day)

不要写代码或跑命令,直到 confirm。

---

## Deliverables

### D1 — Modcos 置信度分桶分析(0.5 day,纯只读)

`scripts/eval_sub6/analyze_modcos_buckets.py`,从 358 个 peak_evidence JSON 里提取每 spectrum 的 modcos top-1 score,分 5 桶:

| Bucket | modcos top-1 范围 | n_spectra | n_correct | id_acc | rerank Δ (Phase 6.2 D - pre-rerank) |
|---|---|---:|---:|---:|---:|
| Very high | ≥0.9 | ? | ? | ?% | ?pp |
| High | 0.8-0.9 | ? | ? | ?% | ?pp |
| Medium | 0.6-0.8 | ? | ? | ?% | ?pp |
| Low | 0.4-0.6 | ? | ? | ?% | ?pp |
| Very low | <0.4 | ? | ? | ?% | ?pp |

**关键判断**:
- 如果 Very high + High 桶占 >70% 且 id_acc 已 >90% → 这部分**不该 rerank**
- 如果 Low + Very low 桶有 ≥20%,且 rerank Δ 在这部分是正的 → 这是 conditional rerank 的目标子集

**第二个角度**:top-1 vs top-2 score gap 分桶(MSAgent ambiguous case 定义):

| Gap (top1-top2) | n_spectra | id_acc baseline | rerank Δ |
|---|---:|---:|---:|
| Wide (≥0.15) | ? | ?% | ?pp |
| Medium (0.05-0.15) | ? | ?% | ?pp |
| Narrow (<0.05) | ? | ?% | ?pp |

**预期发现**:Narrow gap 子集是 ambiguous,rerank 对它们应该有 +5-10pp。

输出:
- `data/paper_figures/phase6_5_modcos_buckets.csv`
- `data/paper_figures/phase6_5_topk_gap_buckets.csv`

### D2 — CFM-ID per-correctness 拆分(0.5 day,纯只读)

`scripts/eval_sub6/analyze_cfmid_per_correctness.py`,每 candidate 标记 `is_correct`(InChIKey first-block 跟 ground truth 比),分 4 类聚合:

| Group | n_candidates | mean cfm_cosine | mean predicted_peaks_in_exp_pct | median |
|---|---:|---:|---:|---:|
| Correct candidate, in pool | ? | ? | ? | ? |
| Wrong candidate, in pool (top-5) | ? | ? | ? | ? |
| Correct candidate not in top-5 (rare) | ? | ? | ? | ? |
| All candidates pooled | ? | ? | ? | ? |

**关键判断**:
- 如果 correct cfm cosine ≈ wrong cfm cosine (~0.2) → CFM-ID 在 Sub-6A v2 上**完全无判别力**,paper 写成 "CFM-ID predictions failed to discriminate correct from wrong on this benchmark"
- 如果 correct = 0.4, wrong = 0.15 → CFM-ID **有判别力,只是噪声大**;paper 应说 "CFM signal exists but is dominated by absolute-noise floor"

输出 `data/paper_figures/phase6_5_cfm_per_correctness.csv`,做箱线图数据(per-class distribution,不只 mean)。

### D3 — 统计显著性(0.5 day)

`scripts/eval_sub6/significance_tests.py`:

对每对 config (A vs B, A vs C, B vs C, etc.),跑:
- **McNemar's test**(paired binary 数据)→ p-value
- **Paired bootstrap CI**(10K samples,95% CI on Δ id_acc)
- **多比较校正**:Bonferroni(9 configs → 36 pairs → α/36)

输出主表 `data/paper_figures/phase6_5_significance.csv`:

| Comparison | n_paired | Δ id_acc | 95% CI | p-value (McNemar) | sig after Bonferroni |
|---|---:|---:|---|---:|---|
| A vs B (modcos+w vs msclip+w) | 358 | -3.99pp | [-5.7, -2.3] | 0.001 | yes |
| A vs C (modcos+w vs msclip+LLM) | 358 | -2.61pp | [-4.5, -0.7] | 0.012 | yes |
| 6.2 cfmid vs gnps_only | 358 | -2.51pp | [...] | ... | ... |
| ...总共所有 pair |

**核心数字**:**前 3 个 negative result 哪些过了 significance,哪些是 noise**?如果 -0.44pp (Phase 6.1 fused) 不过 significance,paper 写法变温和:"MS-CLIP fusion 跟 modcos baseline **统计不显著差异**" 而非 "差 0.44pp"。

### D4 — 实现 Conditional Rerank(0.5 day)

`evaluation/sub6/conditional_rerank.py`:

```python
def should_rerank(
    candidates: list[Candidate],
    *,
    modcos_top1_threshold: float = 0.85,    # D1 数字校准后填
    topk_gap_threshold: float = 0.10,        # D1 数字校准后填
    isomer_tanimoto_threshold: float = 0.7,  # 待 D5 实测
) -> tuple[bool, str]:
    """
    Returns (should_rerank, reason).
    
    Triggers rerank only if any of:
      - top-1 modcos score < threshold (low confidence)
      - top1-top2 gap < threshold (ambiguous)
      - top-5 mean Tanimoto > threshold (isomer cluster)
    """
```

阈值用 D1 实测数字校准——比如 D1 显示 modcos>0.85 桶 id_acc 已 95%,就用 0.85 作为 trigger。

加单元测试:
- 高置信 case → no rerank
- 低置信 case → rerank
- 边界 case 

### D5 — Conditional rerank 重跑 + 评估(1 day wall)

跑一个新 Config E:

```bash
PYTHONPATH=. python scripts/eval_sub6/run_baseline.py \
    --sub6a data/benchmark/sub6/sub6a_e2e_tasks_v2.jsonl \
    --out-dir data/eval/sub6/v2_phase6_5/E_conditional/ \
    --libraries gnps,inhouse \
    --primary-retriever modcos \
    --reranker conditional \
    --conditional-fallback weighted \
    --rerank-with sirius,cfmid \
    --skip-narrative \
    --mass-tolerance-ppm 10.0
```

`--reranker conditional` 是 D4 加的新模式。`--conditional-fallback weighted` 决定触发时用哪个 reranker(weighted 或 llm,本 session 用 weighted 复用 6.2 cache)。

复用 Phase 6.2 cache:
- SIRIUS 输出已落盘
- CFM-ID 输出已落盘
- 不重跑

预期 wall: 1-2 hours(只触发 ~30% spectra 的 rerank 计算,大部分直接 take modcos top-1)。

**Acceptance**:
- Config E id_acc ≥ Config A (67.10%, baseline reused),目标 +0.5 to +2pp
- 触发率 20-40% 之间(全触发跟 6.2 D 等价,0% 触发跟 baseline 等价)
- 触发的 spectra 子集上 rerank 净 Δ > 0(否则 conditional gate 阈值定错了)

如果 Config E ≤ Config A,**这是 paper 重要 negative**:即使 selective rerank 都救不了 Sub-6A v2,这进一步坐实"benchmark 是 in-distribution + leakage,rerank 没空间"。

### D6 — 综合报告(0.5 day)

`reports/eval/conditional_rerank_v2.md`,8-10 节:

#### 1. Summary
- D1+D2+D3+D5 的 4 个 finding 各 1 句话
- paper 影响:从"naive rerank fails"升级为"我们 quantified 失败的 3 个独立维度,且 conditional rerank 在 v2 上仍 marginal"

#### 2. Modcos confidence 分桶(D1)
- 5-bucket 表 + per-bucket rerank Δ
- top1-top2 gap 表
- 关键 finding 文字 1-2 段

#### 3. CFM-ID per-correctness(D2)
- correct vs wrong 的 cfm cosine 分布
- 判别力结论(yes/no)
- 跟 paper Phase 6.4 的 81.5% CONTRADICTED 数字关联

#### 4. Statistical significance(D3)
- 9 configs 全 pair 的 p-value 表
- 哪些 negative result 是真显著,哪些是 noise
- Bonferroni 校正后哪些保留

#### 5. Conditional Rerank Config E(D5)
- 触发率 + 触发子集上 vs 全集上的 id_acc 对比
- 跟 Config A baseline 直接对比(McNemar)

#### 6. MSAgent 对照
- 报告 §6 直接表格:MSAgent CASMI 设置 vs 我们 Sub-6A v2 设置
- 4 个差异维度(baseline 强度 / 触发条件 / 解决问题 / 测试集)

#### 7. Paper finding 升级
旧 finding (3 negative results) → 新 finding 矩阵:

| Finding | 数据出处 | paper 影响 |
|---|---|---|
| F1: rerank Δ negative on Sub-6A v2 | 现有 |已知|
| F2: significance: X/9 不过 Bonferroni | D3 | 升级为"严谨 negative" |
| F3: CFM-ID 在 v2 上无判别力(或有) | D2 | 解释 F1 机制 |
| F4: rerank value bound by modcos confidence bucket | D1 | conditional rerank 理论支撑 |
| F5: Conditional rerank 在 v2 上 +Δpp | D5 | MSAgent style 实测 |

#### 8. Limitations + Future Work
- 仍未跑 OOD benchmark (CASMI / CANOPUS) — 留 Phase 6.6
- 仍未接 de novo molecule_gen — 留 Phase 6.7
- per-claim spectrum routing 未修 — 留 Phase 6.8
- top-K = 5 vs MSAgent top-50 — 留 Phase 6.6

#### 9. Provenance
- git commit / 输入 MD5 / 输出 MD5 / wall

### D7 — Acceptance

```
□ data/paper_figures/phase6_5_{modcos_buckets,topk_gap_buckets,cfm_per_correctness,significance}.csv 4 个 CSV
□ data/eval/sub6/v2_phase6_5/E_conditional/ 完整(narrative_id 输出 + identifications.csv)
□ Config E id_acc 报数(任意值,正负都接受)
□ McNemar p-value 9 个 config pair 全部计算
□ Bonferroni 校正后报告哪些过 significance
□ Conditional gate 触发率 20-40% 之间
□ 报告 8 节完整
□ 现有 v2 / v2_phase6_2 / v2_phase6_3 / v2_phase6_4 文件未动
□ 0 verifier 改动,0 SIRIUS/CFM-ID 重跑(只 cache lookup)
```

---

## Pitfalls

1. **D1 阈值校准是 D4 的前提**。如果 D1 数字诡异(比如 modcos>0.9 桶 id_acc 也只 70%),conditional gate 设计要重新想。第一回合先做 D1,**等 user review D1 数字再决定 D4 阈值**。

2. **Ground truth correctness 的标准**:用 InChIKey first-block 跟 task 的 ground_truth_signal_compounds InChIKey 比。如果 ground_truth_signal_compounds 是 KEGG ID,要先 lookup 到 InChIKey first-block。看 Phase 6.2 / 6.3 现有代码怎么算 `correct_top1`,**复用同一逻辑**(不要发明新对比规则)。

3. **McNemar paired test 要求 sample 配对**:每 config 必须有同一 spectrum 的 prediction。一些 config 缺 spectrum (e.g. Phase 6.3 B 是 354 vs 358),配对要 intersect spectrum_id,不是简单合并。

4. **Bootstrap CI 不要用 percentile method**:对 paired binary data 用 BCa method。或简单点用 normal-approx CI(95% CI = Δ ± 1.96·SE)。

5. **CFM cosine 数据来源**:是 peak_evidence JSON 里 `candidates_evaluated[i].predicted_cosine` 字段,不是别的。第一回合先 verify schema 再写聚合脚本。

6. **不要重跑 cache miss CFM-ID**:Conditional config 触发的 candidate 必须在 Phase 6.2 cache 里。如果发现 cache miss > 5%,说明 Conditional 触发了不一样的 candidate(因为 conditional rerank 上游 Phase A pool 应该一致)。debug 在 Phase A 一致性。

7. **不要跑 LLM**:本 session 全程 `--skip-narrative`。conditional rerank 用 weighted fallback,不调 LLM。

---

## Time budget

- Confirm: 30 min
- D1 modcos 分桶: 4 hours
- D2 CFM 拆分: 3 hours
- D3 显著性: 4 hours
- **Stop here, present D1+D2+D3 to user**(half-day checkpoint)
- D4 conditional rerank 实现: 4 hours
- D5 Config E 跑: 1-2 hours wall
- D6 综合报告: 4 hours
- D7: 15 min

**Total: ~2.5 days wall**(D1-D3 第一天,D4-D5 第二天,D6 第三天)。

LLM 成本: $0(本 session 全程无 LLM 调用)。

---

## First action checklist

第一回合:
1. 读 7 个 background 文件
2. 贴 1 个 peak_evidence JSON sample (从 Phase 6.2 full/),标 candidates_evaluated 里 modcos 和 predicted_cosine 字段位置
3. 报告 ground truth correctness 的现有标记逻辑(从 Phase 6.2 / 6.3 代码引用)
4. 估算 D1 + D2 + D3 总 wall(应该 < 1 day,纯只读分析)
5. 任何 clarifying question

不要写代码或跑命令,直到 confirm。

**重要:D1+D2+D3 跑完先停一下,把数字给 user review 后再进 D4(conditional gate 阈值要根据 D1 实测定)。**

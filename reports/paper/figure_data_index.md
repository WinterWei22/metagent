# Paper figure data index

**Date:** 2026-05-07
**Source branch:** `feature/sub6-v2-integrated`
**Status:** read-only — 0 行代码改动 / 0 个现有 verdict 文件被修改
**Builder:** `/tmp/build_paper_figures.py` (transient, 不入库)

所有 figure 数据派生自 verdict JSONL，不重跑 verifier、不发明新数字。每个 csv/json 都可由 `data/eval/sub6/...v9_phaseC.jsonl` 重产。

---

## Figure 1 — Cross-LLM hallucination rate matrix

- **Data file:** `data/paper_figures/fig1_cross_llm_hallucination.csv`
- **Rows:** 14 (7 claim_type × 2 narrative LLM)
- **Source:**
  - `data/eval/sub6/v2/sub6b_opus/verdicts_v9_phaseC.jsonl` (Opus-4-7)
  - `data/eval/sub6/v2/sub6b_gpt55/verdicts_v9_phaseC.jsonl` (GPT-5.5)
- **Suggested chart:** stacked bar (sup / unsup / contra / unverif) × 7 claim types × 2 LLMs (side-by-side)
- **Key takeaways:**
  - **Opus 65% unverif vs GPT-5.5 50% unverif** at task-level → GPT-5.5 写出更多可验证 claim。
  - 在 set_enrichment 上两者都 ≥ 70% unverif；在 driver_metabolite 上 GPT-5.5 几乎 0% unverif (1/128) 而 Opus 13% — GPT-5.5 把 driver 分得更细。
  - `factual_roundtrip_claim` 与 `consistency_claim` 在 Sub-6B narrative 上几乎 100% unverifiable_v0 — finding 本身：Sub-6 narrative 不触发这两类的可验证子集，paper 画图时可筛掉或单列说明。
- **Paper section:** Results §X.Y (Cross-LLM comparison)
- **Cross-references:** `reports/eval/sub6_v2_comparison_2026-05-06.md` §2; `reports/verifier/llm_3way_comparison_2026-05-05.md`（注意区分：3way 报告对比的是 *verifier* 内部 LLM；本图对比的是 *narrative* LLM）

---

## Figure 2 — Cascade decomposition (compound → identification → narrative)

- **Data file:** `data/paper_figures/fig2_cascade_decomposition.csv`
- **Rows:** 3 (sub6b_opus / sub6a_perfect_opus / sub6a_real_opus)
- **Source:**
  - 4 个 v2 verdict JSONL（同 fig1）
  - `data/eval/sub6/v2/sub6a_real/sub6a_narratives.jsonl` 提取 `identification_accuracy` 平均值
- **Suggested chart:** 3-bar stacked (verdict 分布) + side metric `id_accuracy` 文字标注。
- **Key takeaways:**
  - sub6b → sub6a_perfect → sub6a_real：unverif% 从 65 → 62 → 67，supported% 从 18 → 19 → 14（real-id 引入识别误差但只损失 ~5 pt 可信度）。
  - `id_accuracy = 0.6737`（v2 Phase A library_search ±10 ppm），是 cascade 损失的"上游瓶颈"。
- **Paper section:** Results §X.Y (End-to-end pipeline degradation)
- **Cross-references:** `reports/eval/sub6_v2_comparison_2026-05-06.md` §3.1, §4

---

## Figure 3 — Per-pathway breakdown (Sub-6B Opus)

- **Data file:** `data/paper_figures/fig3_per_pathway_breakdown.csv`
- **Rows:** 8 (Sub-6B v2 中 n_tasks ≥ 2 的 pathway；剩余 5 个单 task pathway 写 limitation 不画图)
- **Source:** `data/eval/sub6/v2/sub6b_opus/verdicts_v9_phaseC.jsonl` × `data/benchmark/sub6/sub6b_mammalian_tasks_v2.jsonl`
- **bucket 标注**：取自 `reports/benchmark/sub6_construction_report_v2.md §3`，硬编码 13 个通路 → 5 桶映射。
- **Suggested chart:** pathway × verdict 分布堆叠 bar，按 n_tasks 降序。
- **Key takeaways:**
  - **Galactose Metabolism (central) 表现最好**：sup 20%, contra 4%。
  - **Biological oxidations 最差**：sup 10%, unverif 81% — Opus 在该通路上写很多模糊抗氧化/redox claim，难落到具体通路名上。
  - driver_contra 数集中在 8 个 ≥2 task 的 pathway（sum=17，与全集 17/63 一致 — 单 task pathway 没有任一 driver_contra）。
- **Paper section:** Results §X.Y (Pathway-level reliability)

---

## Figure 4 — Cross-LLM sensitivity (set_enrichment only, 3-way control)

- **Data file:** `data/paper_figures/fig4_llm_style_sensitivity.csv`
- **Rows:** 3 (v1_baseline_minimax / v1_opus_sanity / v2_opus)
- **Source:**
  - `data/eval/sub6/sub6a_perfect_id_verdicts_v9_phaseC.jsonl` (v1, MiniMax-M2.7 narrative)
  - `data/eval/sub6/v1_opus_sanity/verdicts_v9_phaseC.jsonl` (v1 重跑, Opus 同一份 14 task)
  - `data/eval/sub6/v2/sub6a_perfect/verdicts_v9_phaseC.jsonl` (v2, Opus, 38 task)
- **Suggested chart:** 3-row table 或简单条形图，对比 `se_supported_pct` 和 `se_unverifiable_pct`。
- **Key takeaways:**
  - v1-MiniMax: 11% sup, 54% unverif
  - v1-Opus: **0% sup, 80% unverif** — 同一份数据，仅换 LLM
  - v2-Opus: 1% sup, 89% unverif
  - **Conclusion: v1→v2 set_enrichment 退化是 LLM artifact，不是数据问题**。这是 paper 最有力的反事实证据 (counterfactual control)。
- **Paper section:** Limitations / Discussion (cross-model artifact)
- **Cross-references:** `reports/audit/set_enrichment_regression_v1_v2.md`, `reports/audit/v1_opus_sanity_check.md`

---

## Figure 5 — Layer 6b driver-metabolite progression (v1 → v2)

- **Data file:** `data/paper_figures/fig5_layer6b_progression.csv`
- **Rows:** 6 (3 tracks × 2 versions)
- **Source:**
  - v1: 3 个 `data/eval/sub6/sub6{b,a_perfect_id,a_real_id}_verdicts_v9_phaseC.jsonl`
  - v2: 4 个 v2 verdict（取 sub6b_opus / sub6a_perfect / sub6a_real）
- **Suggested chart:** grouped bar (v1 vs v2) × 3 tracks，y 轴是 `driver_contra_pct`。
- **Key takeaways:**
  - Sub-6B: 5% → 27% (+22 pt)
  - Sub-6A perfect: 21% → 37% (+16 pt)
  - Sub-6A real: 7% → 26% (+19 pt)
  - **F3 finding：v2 数据扩展（不是 LLM swap）让 Layer 6b driver-metabolite 检出率全面跃升**。注意 v1 是 MiniMax narrative、v2 是 Opus narrative，所以本图存在 confound — paper 写法应说"扩集 + LLM 切换共同导致"，并参照 fig4（cross-LLM control on SE）作 contrast。
- **Paper section:** Results §X.Y (Layer 6b ablation across versions)
- **Cross-references:** `reports/eval/sub6_v2_comparison_2026-05-06.md` §3.1; `reports/eval/sub6_metagent_final_summary_2026-05-06.md` (F3)

---

## Figure 6 — KEGG hierarchy SUPPORTED case studies

- **Data file:** `data/paper_figures/fig6_kegg_hierarchy_cases.json`
- **Pool:** 39 supported `pathway_relationship` claims in `data/eval/sub6/v2/sub6b_opus/verdicts_v9_phaseC.jsonl`
- **Chosen:** 5 cases differentiated by (path_length × direction)
  1. **L-DOPA → dopamine**, 1 hop, forward (短路径直接邻居)
  2. **Pregnenolone → DHEA**, 2 hop, forward (经典 steroid 链)
  3. **Cholesterol → pregnenolone**, 3 hop, forward (经典代谢链, 含 hydroxylation 中间体)
  4. **Cystathionine → glutathione synthesis**, 4 hop, bidirectional (跨步 + 双向)
  5. **DHEA → androstenedione**, 1 hop, bidirectional (近邻 + 双向)
- **Suggested figure layout:** 5 子图，每子图：claim 文本 + KEGG path 图谱 (节点 = compound, 边 = reaction)。
- **Key takeaways:**
  - Verifier Layer 6d 在 1–4 hop 范围都能命中，**反向（bidirectional）也能正确判定**。
  - "Cystathionine → glutathione synthesis"（case 4）的 bidirectional 标记说明 KEGG reaction graph 允许双向 traversal — paper 可借此说明 verifier 不是"硬性方向"，而是"reachability"。
  - 5 case 跨 3 个不同 ground-truth pathway (Galactose, Androgen/Estrogen, Glycine/Serine/Threonine) — 多样性足够。
- **Paper section:** Methods / Results §X.Y (KEGG-grounded reasoning case studies)

---

## Figure 7 — Pathway-identification dual definition (strict vs broad)

- **Data file:** `data/paper_figures/fig7_pathway_identification_dual_definition.csv`
- **Rows:** 5 (one per v2 track)
- **Source:** 5 个 v2 verdict JSONL（含 `sub6b_minimax` 由 Phase 5.3 补出的 3-way 第三 LLM）
- **Suggested chart:** 同图双 y 轴或并排两个柱：左轴 strict_task_coverage_pct (0–10%)，右轴 broad_task_coverage_pct (90–100%)。
- **Two definitions:**
  - **Strict (GSEA 式)**: 仅 `set_enrichment` claim_type + verdict=supported。意为 "metabolite 集合作为整体被 RaMP enrichment top-3 命中"。Verifier 看 `ramp_enrichment_result.top_pathways[:10]` 字面/子串匹配。
  - **Broad (membership 式)**: 任何 supported claim 命名了具体 pathway — 包括 `set_enrichment` + `driver_metabolite` + `biological_claim/pathway_membership` + `pathway_relationship/pathway_membership`。Verifier 用 RaMP `analytehaspathway` 表逐 compound 核对。**Verifier evidence 显式标注 "SUPPORTED on membership, not on relevance"**。
- **Key takeaways:**
  - **Strict task coverage 仅 2.6–7.9%** (12 supported claims 全 5 track 加起来) — 受 Layer 6a 字面匹配限制。
  - **Broad task coverage 94–100%** (2,090 supported claims) — narrative 几乎在每个 task 上都点名了真实 pathway 并被 verifier 静态生物事实背书。
  - 主导贡献来自 `biological_claim/pathway_membership` (1,835/2,090 ≈ 88%)。
  - **Membership ≠ Relevance**：membership supported 表示 "命名的 pathway 真实存在 + 化合物属于它"；relevance 才表示 "对此 task 富集"。Paper 必须分开报告两个数字，避免混淆。
- **Paper section:** Results §X.Y (Pathway identification — dual reporting)
- **Cross-references:** `reports/eval/sub6b_v2_3way_full_comparison.md` §2; 全 12 条 strict supported 已列在 audit-style 答疑中（任一 track verdict JSONL 可重提）

---

## Figure 8 — Pathway identification correctness PER TASK (4-strength sweep)

- **Data file:** `data/paper_figures/fig8_pathway_id_correctness_per_task.csv`
- **Rows:** 5 (one per v2 track, same 5 as fig7)
- **Source:** 5 个 v2 verdict JSONL × task JSONL（ground_truth_pathway 字段）
- **Suggested chart:** 4 条带 (strict GSEA → STRICT-gt → gt-or-syn → broad-any) 对每 track 画 stacked / aligned bar，展示从严到宽的覆盖率单调上升。
- **Four strengths（task-level，是否 ≥1 supported claim 满足条件）:**
  - **strict_GSEA** (2.6–7.9%)：claim_type=set_enrichment AND verdict=supported（最严，verifier Layer 6a 直接命中 RaMP enrichment top-3）
  - **STRICT_gt** (26–33%)：任意 broad-pathway-id supported claim 文本中 verbatim 出现 ground-truth pathway 名（"tryptophan metabolism" 字符串）
  - **gt_or_syn** (34–51%)：STRICT_gt 或 GT pathway 第一词 stem 命中（"tryptophan" 不带 "metabolism"）
  - **broad_any** (94–100%)：任意 supported claim 命名了**任意**真实 pathway（不要求与 GT 相关）
- **Key takeaways:**
  - **Headline number (paper-defensible)：framework 在 34–51% 的 task 上**正确**鉴定出 task 的 ground-truth pathway**（gt_or_syn 列）；最严 GSEA 仅 2.6–7.9%（受 Layer 6a 字面匹配限制）。
  - **broad_any 94–100% 是 secondary finding**：narrative 在几乎所有 task 上都点名了某条真实 pathway 并被 verifier 静态生物学事实背书 — 但**这条 pathway 不一定是 task 的答案**。verifier 的 evidence 在这种情况会显式标注 "SUPPORTED on membership, not on relevance"。
  - 不能把 broad_any 当作"鉴定正确率"（这是常见误读）。**task-level 真鉴定率应取 STRICT_gt 或 gt_or_syn**。
- **Paper section:** Results §X.Y (Pipeline correctness)；与 fig7 (claim-level dual definition) 配套使用：fig7 解释 claim-level 双语义，fig8 解释 task-level 正确率。

---

## Acceptance check

```
✓ data/paper_figures/                              存在
✓ fig1_cross_llm_hallucination.csv     14 rows  (≥ 14 required)
✓ fig2_cascade_decomposition.csv        3 rows
✓ fig3_per_pathway_breakdown.csv        8 rows  (≥ 5 required)
✓ fig4_llm_style_sensitivity.csv        3 rows
✓ fig5_layer6b_progression.csv          6 rows
✓ fig6_kegg_hierarchy_cases.json        5 cases (≥ 3 required)
✓ fig7_pathway_identification_dual_definition.csv  5 rows (claim-level dual)
✓ fig8_pathway_id_correctness_per_task.csv         5 rows (task-level 4-strength)
✓ reports/paper/figure_data_index.md   存在
✓ 0 行代码改动                          (verifier / orchestrator / tools 全未动)
✓ 0 个现有 data/eval/ 文件被修改        (仅新建 data/paper_figures/ 派生文件)
```

---

## Provenance

| field | value |
|---|---|
| git commit | `17a90dc` (`feature/sub6-v2-integrated`) |
| build script | `/tmp/build_paper_figures.py` (transient — 同样 verdict 输入下可复现) |
| build date | 2026-05-07 |
| input verdict files | v1 ×3 + v2 ×4 + v1_opus_sanity ×1 = 8 个 JSONL |
| input task files | `data/benchmark/sub6/sub6b_mammalian_tasks_v2.jsonl` (用于 fig3 / fig6 pathway 元数据) |
| pathway → bucket source | `reports/benchmark/sub6_construction_report_v2.md §3` (硬编码 13-pathway 映射) |
| cross-checks | task-level `driver_contra` 在 v2 sub6b_opus = 17 (主报告 17/63 一致) |

# MetAgent 项目地图（PROJECT MAP）

> 整理日期：2026-06-30
> 用途：**看这一份就懂全项目**——三个流程各自的「① 流程 ② 复现脚本 ③ 当前结果 ④ 数据」，外加报告导航。
> 与 `CLAUDE.md`（接手交接）互补：CLAUDE.md 讲「为什么这么设计 + 历史 ledger」，本文讲「现在有什么 + 怎么跑 + 结果在哪」。

---

## 0. 三流程总览

| 流程 | 是什么 | verifier 入口 | 评测集 | 当前权威 |
|---|---|---|---|---|
| **Stage 1** | 单谱代谢物**结构**识别（一张 MS/MS 谱 → ranked 候选结构 + 峰归属 + PMID） | `verifier/agent.py::verify()`（spectrum） | sub6a (real-id) · CASMI | `docs/decisions/2026-06-30_stage1_b1_method_data_results_repro.md` |
| **Stage 2** | 富集后**通路**鉴定 narrative（一组差异代谢物 → pathway-grounded narrative + 结构化 claim） | `verifier/agent.py::verify_sub6()` | v4 benchmark (sub6 63 + hmdb_ramp 49 = 112) | `reports/reports_v3/summary/` |
| **Stage 1+2** | 贯穿两者的基础设施：架构 / 工具契约 / claim grammar / benchmark 构建 / 数据护栏 | — | — | `docs/ARCHITECTURE.md` 等 4 核心文档 |

---

## 1. Stage 1 — 单谱结构识别

### ① 流程
```
MS/MS 谱 →[Phase A ±10ppm 质量窗预筛: 622k→~89 候选]→[library_search modcos(+MS-CLIP) top-20]
        →[可选 rerank: SIRIUS 分子式 / CFM-ID 预测谱 / LLM reranker]→ ranked 候选结构 + 峰证据
        →[verify() + Layer F peak_mechanistic: 逐条核 peak claim vs 实测谱 ±5ppm]
```

### ② 复现脚本
```bash
# sub6a real-id 端到端
PYTHONPATH=. python scripts/eval_sub6/run_baseline.py --sub6a --id-strategy library_search --mass-tolerance-ppm 10 --output-suffix _phase_a --out-dir data/eval/sub6
PYTHONPATH=. python scripts/eval_sub6/grade_with_verifier.py --narratives data/eval/sub6/sub6a_narratives_phase_a.jsonl --tasks data/benchmark/sub6/sub6a_e2e_tasks_v2.jsonl --out <verdicts.jsonl> --track sub6a_real_id
# CASMI（OOD 结构识别 + rerank 对比）
PYTHONPATH=. python scripts/eval_sub6/run_casmi.py --casmi 2016_cat2 --reranker llm --primary-retriever msclip --rerank-with cfmid --rerank-top-k 5 --narrative-llm opus47 --dump-ranks --out-dir <dir>
PYTHONPATH=. python scripts/eval_sub6/casmi_combined_topk_mrr.py
```

### ③ 当前结果
- **Phase A 质量过滤**（headline）：id_acc **6.25% → 72.07%**（11.5×）、识别提速 **170×**、候选池 5536× 缩减。
- **sub6a rerank（in-distribution）**：modcos 默认 top-1 **74.58%** 最强，**所有正交 rerank 降 1–5pp**（根因 GNPS leakage，74.58% 虚高）。
- **CASMI（OOD）**：LLM reranker **+5.82pp top-1 / +14% MRR / p=1.4×10⁻⁵**（唯一正向 rerank，复现并超越 MSAgent +10% MRR）。
- **Layer F verifier**：858 peak claim 中 **81.5% CONTRADICTED**（客观量化 LLM 把工具预测峰当实测峰的机制幻觉）。

### ④ 数据
- `data/benchmark/sub6/sub6a_e2e_tasks_v2.jsonl`（38 task / 459 谱 / Phase A 后 358）
- CASMI 2022 (170) + 2016 cat2 (208) = 378 谱
- GNPS 库 ~620k 候选（Phase A 后 ~89/谱）

---

## 2. Stage 2 — 富集通路 narrative

### ① 流程
```
差异代谢物组 →[concord ReAct: 5-PA 富集工具(SSPA/Mummichog/RaMP/MetaboAnalystR/FELLA) LLM 编排]
            →[pathway_prediction second-pass]→ narrative + 结构化 claim
            →[verify_sub6(): 4-shape grammar 4 层审计]→[cascade feedback: 确定性保 SUPPORTED/删噪音, LLM 只织叙述]
```

### ② 复现脚本
```bash
# v4 benchmark 全量（112 task）
PYTHONPATH=. python scripts/metagent/v4_bench_eval.py \
    --benchmark data/benchmark/metagent_bench_v2/metagent_bench_easy_v4_metabolic.jsonl \
    --strata sub6 hmdb_ramp --out <dir> --max-react-turns 8 --max-feedback-iters 1 --k 8
# 打分
PYTHONPATH=. python scripts/metagent/full344_pathway_scorecard.py --out-dir <dir> \
    --benchmark data/benchmark/metagent_bench_v2/metagent_bench_easy_v4.jsonl \
    --relevant-sidecar data/benchmark/metagent_bench_v2/relevant_sets_easy_v3.json \
    --gold-sidecar data/benchmark/metagent_bench_v2/gold_drivers_easy_v3.json \
    --ramp /data/weiwentao/llm_agent_metabolomics/ramp.sqlite --report-dir <dir>/scorecard --stem <stem> --llm-log <log>
# feedback A/B（复用 iter-0 trace，只重跑 feedback 轮）
PYTHONPATH=. python scripts/metagent/feedback_ab_eval.py
```

### ③ 当前结果（v4 benchmark，2026-06-29，`reports/reports_v3/summary/`）
- **legacy rewrite 路径**：pathway primary semantic **76.79%**、top-k 83.93%、112/112 ok、$5.98 / 61.5 min。
- **cascade 路径（现为生产默认，commit `00d47f0`/`b75601f`）**：噪音(UNS+UV) **15.4%→2.8%**、Supported **+18.4pp**、cost −29%、wall −28%；**但 pathway primary −5.36pp**（sub6 −11.11pp 主导，top-k 仅 −2.68pp）→ 正确通路多半还在 claim 里，是 second-pass 选 primary 退化，**待诊断**（下一步候选）。

### ④ 数据
- `data/benchmark/metagent_bench_v2/metagent_bench_easy_v4_metabolic.jsonl`（292，本轮跑 sub6 63 + hmdb_ramp filtered 49 = 112）
- sidecar：`relevant_sets_easy_v3.json` / `gold_drivers_easy_v3.json`；`ramp.sqlite`

---

## 3. Stage 1+2 — 基础设施 / 架构

### 核心设计文档（CURRENT，必读）
| 文档 | 内容 |
|---|---|
| `docs/ARCHITECTURE.md` | 系统设计哲学（Schemas are law / Tools are narrow / Every claim verifiable） |
| `docs/TOOL_CONTRACTS.md` | Stage 1 7-tool I/O 契约 |
| `docs/claim_grammar_v2.md` | Stage 2 claim grammar v2（4-shape） |
| `docs/LLM_INTEGRATION.md` | LLM client / provider switch（MiniMax 远程 API）/ cache |

### verifier 4-shape grammar（Stage 2 入口共用）
`pathway_membership` / `metabolite_pathway_link` / `pathway_enrichment` / `driver_metabolite`——超出即 `UNVERIFIABLE_V0`。
（Stage 1 走 `verify()` + Layer F peak_mechanistic，验证结构/峰级，不走这 4-shape。）

### benchmark 构建 + 数据护栏
- 数据集构建审计：`reports/benchmark/`（sub6 construction / npclassifier / lipidmaps / metagent_bench_v2 卡）
- 数据完整性/独立性审计：`reports/audit/`（v1 opus sanity / v2-v3 data integrity / spectra sparsity / set_enrichment regression）
- 护栏：`metagent-v2-base-b1` tag @ `ed6243b` immutable；`data/eval/sub6/b1_d5_*` + `a3_rerun_*` immutable；B1 test floor 14 fail。

---

## 4. 报告导航（清理后所在）

| 你想看 | 去哪 |
|---|---|
| **Stage 1 方法/数据/结果/复现** | `docs/decisions/2026-06-30_stage1_b1_method_data_results_repro.md`（收口）；详报 `reports/eval/*` |
| **Stage 2 当前权威总结** | `reports/reports_v3/summary/`（2 份：feedback 重构 + v4 复现/cascade）；详报 `reports/reports_v3/*` |
| **Stage 2 设计决策** | `docs/decisions/2026-06-*`（w17-w22 / stage2 contract / verifier 多源 / cascade） |
| **阶段收口报告** | `reports/agent/`（concord w13/w14 + w17-w21 close_out + merge_status） |
| **verifier 工程改进** | `reports/verifier/`（layer6c / kegg / enrichment delivery / llm 对比） |
| **架构总参考** | `reports/project_architecture_tools_verifier_summary_2026-04-27.md` |
| **数据集构建 / 审计** | `reports/benchmark/` · `reports/audit/` |
| **数据泄露审计** | `reports/nm002_leakage_audit_2026-04-29.md` |
| **运行时 prompt** | `prompts/agent/` · `prompts/concord/` · `prompts/track_01_naive_orchestrator.md`（代码加载，勿动） |

### 归档区（历史过程，`reports/archive/` + `prompts/archive/`）
| 归档目录 | 内容 |
|---|---|
| `reports/archive/stage1_tool_delivery/` | 2026-04 早期 7-tool 交付 / integration / acceptance / massbank 数据源（27） |
| `reports/archive/stage1_eval_superseded/` | eval 被取代的版本对比 / baseline（10） |
| `reports/archive/benchmark_v1_construction/` | metagent_bench v1 数据集构建（15，被 v2 取代） |
| `reports/archive/stage2_concord_sprints/` | W3-W14 concord sprint status + 诊断 + 计划（24） |
| `reports/archive/phase_b1_process/` | phase_a / phase_b1 narrative 过程（18，被 reports_v3 取代） |
| `reports/archive/stage2_v2_intermediate/` | reports_v2 被取代的 scorecard 迭代 + 小试跑（33） |
| `reports/archive/_data/` | reports_v2/v3 的 csv/json 中间数据（56） |
| `reports/archive/spike/` · `misc/` | spike / 重复 acceptance / v1 baseline / verifier 噪音 |
| `prompts/archive/` | 58 历史 sprint-spec（track_*.md）+ verifier spec |

> 归档全部用 `git mv`（history 保留），**未删除任何文件**；运行时 prompt 与 `reports/benchmark/` 一律未动。

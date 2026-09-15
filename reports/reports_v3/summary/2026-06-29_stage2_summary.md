# MetAgent 阶段总结 — v4 benchmark 复现 + cascade 接入状态核查（2026-06-29）

- 日期：`2026-06-29`
- 分支：`metagent-v3-benchmark`，HEAD `b75601f`（本 session 由 fast-forward 合并 feedback 分支 + 提交 cascade 接线 + 修复 cascade pathway_prediction bug 推进而来）
- 前置阶段：见 `reports/reports_v3/summary/2026-06-26_feedback_redesign_phase_summary.md`（feedback A_cascade 重构）
- 本 session 六件事：①合并 feedback/verifier 重构分支；②用最新代码复现 v4 benchmark；③核查 cascade 生产接入的真实状态；④将 cascade 生产接线正式提交（`00d47f0`）；⑤cascade 全量重跑暴露 pathway_prediction bug；⑥**修复 bug（`b75601f`）+ cascade 全量重跑得到有效对比**

> **关键结论（先看这条）**：cascade 接入 + 修复后，在生产 v4 112-task 上与 legacy rewrite paired 对比：**噪音目标超额达成**（noise 15.4%→2.8%、Supported +18.4pp、cost −29%、wall −28%），但 **pathway primary 未持平**（overall 76.79%→71.43%，−5.36pp；sub6 −11.11pp，hmdb_ramp +2.04pp；top-k 仅 −2.68pp）。详见 §4.4。

---

## 1. 版本 / 分支状态（What's the code state）

### 1.1 合并动作

本 session 起点：`metagent-v3-benchmark` @ `008e91b`，feedback 重构工作在独立 worktree 分支 `claude/stupefied-shtern-43fb20` @ `cffc4d3`（领先 12 commit，干净 fast-forward 关系）。

执行 `git merge --ff-only claude/stupefied-shtern-43fb20`：
- 结果：**fast-forward 成功**，当前分支 HEAD → `cffc4d3`，引入 44 文件 / +8215 行。
- 本地未提交改动（两个 scorecard + 未追踪决策文档副本）原样保留，无冲突。
- 带进来的核心产物：
  - `concord/agent/feedback_strategies.py`（cascade 策略实现，`apply_feedback_strategy`）
  - `scripts/metagent/feedback_ab_eval.py`（A/B 实验脚本）
  - verifier 多源重构（`verifier/layers/set_enrichment.py` 多源 + `INSUFFICIENT_EVIDENCE` verdict + `verifier/helpers/multisource_enrichment.py` + structural_consistency layer）
  - `concord/agent/verifier_adapter.py` 的 `v4_task_to_subsix_source_report`（v4 adapter，修好 v4 无 verifier 指标的老问题）
  - feedback 策略全套单元测试

### 1.2 cascade 生产接入的真实状态（重要核查结论）

| 层面 | 状态 | 位置 |
|---|---|---|
| cascade **策略代码** | ✅ 已提交、已合并 | `concord/agent/feedback_strategies.py`（当前分支已有） |
| cascade **接入生产 `react_runner`** | ✅ **已提交（`00d47f0`）** | 当前分支 `metagent-v3-benchmark`（本 session 末从 worktree 取入并 commit） |

**核查经过（含一次自我更正）**：
- 第一轮只查 git 提交历史 + 各分支，搜不到 `_run_cascade_iteration` / `feedback_strategy` 字段 → 一度误判"接入从未做"。
- 第二轮查 worktree **工作区**（未提交改动）→ 找到完整接线，决策文档描述属实。
- 第三轮（本 session 末）：将这套接线正式提交到当前分支。

接线来源：`stupefied-shtern-43fb20` worktree 的未提交改动，含：
```
 M concord/agent/react_runner.py        (+253 行：feedback_strategy 字段 + cascade 分支 + _run_cascade_iteration + _weave_llm_call)
?? tests/concord/test_react_runner_cascade_default.py  (4 测试：default_is_cascade / does_not_rerun_react / rewrite_still_reachable / corrected_claims_match_experiment)
 M scripts/metagent/feedback_ab_eval.py  (实验脚本侧 adapter 2-参签名调整，与生产接线正交；本次未随接线提交，仍留 worktree)
```

**结论**：决策文档（`docs/decisions/2026-06-26_feedback_workflow_a_cascade.md`）对"cascade 已接入生产"的描述**准确**——工作确实做完了，此前唯一问题是停在 worktree 工作区未 commit。本 session 已将生产接线（react_runner + 测试）**正式提交到当前分支 `00d47f0`**：

- 提交：`00d47f0 feat(concord): wire cascade as default feedback strategy in react_runner [concord-modify-warning]`（2 文件 +544/-33）
- B1 无回归实测：**B1 Gate A 409 passed / 0 failed**；cascade 单元+一致性 **4/4**；legacy feedback loop **40 passed**（rewrite 路径仍可达）。
- 当前 `react_runner.run_task_with_feedback` 默认 `feedback_strategy="cascade"`，legacy rewrite 保留在 `="rewrite"`。

> 注：实验脚本 `feedback_ab_eval.py` 的 worktree 改动（adapter 2-参签名）与生产接线正交，本次未提交，仍留在 worktree。

---

## 2. 流程（Process this session）

1. 读 `2026-06-26_feedback_redesign_phase_summary.md` + 决策文档，接手项目。
2. `git merge --ff-only` 合并 feedback/verifier 重构分支到 `metagent-v3-benchmark`。
3. 环境验证（conda python 3.13 / MiniMax key / ramp.sqlite / chebi+metanetx symlink / scorecard 脚本 / sidecars）。
4. 1-task 冒烟测试（确认合并后代码端到端跑通 + v4 adapter 产出 verifier 指标）。
5. 全量 112-task v4 benchmark live run（后台，k=8）。
6. `full344_pathway_scorecard.py` 打分。
7. claim-level verdict 聚合 + 成本/token 实测。
8. cascade 接入状态核查（见 §1.2）。

---

## 3. 运行记录（Run record）

| 项 | 值 |
|---|---|
| Benchmark | `data/benchmark/metagent_bench_v2/metagent_bench_easy_v4_metabolic.jsonl`（292，本次 sub6=63 + hmdb_ramp filtered=49 = **112**） |
| Driver | `scripts/metagent/v4_bench_eval.py --strata sub6 hmdb_ramp --max-react-turns 8 --max-feedback-iters 1 --k 8` |
| 模型 | MiniMax-M2.7-highspeed |
| feedback 路径 | **legacy rewrite**（cascade 未在当前分支接入，见 §1.2） |
| 结果目录 | `data/metagent/v4_bench_eval_repro_20260629/`（status/ + path_x_full/ + scorecard/） |
| LLM log | `logs/concord/v4_repro_full.jsonl` |
| Scorecard | `data/metagent/v4_bench_eval_repro_20260629/scorecard/2026-06-29_v4_repro_scorecard.{md,json,csv}` |
| 复现报告 | `reports/reports_v3/2026-06-29_v4bench_reproduction.md` |
| 完成度 | **112/112 ok，0 crash** |
| 墙钟 | **61.5 min**（3690s，k=8） |
| LLM | **1137 calls / 15.38M token**（prompt 13.87M + completion 1.51M，cached 9.60M） |
| **成本** | **$5.98**（MiniMax $0.30/M prompt + $1.20/M completion） |

---

## 4. 结果（Results）

### 4.1 主指标 pathway accuracy（vs 2026-06-25 基线）

| stratum | 指标 | baseline 2026-06-25 | repro 2026-06-29 | Δ |
|---|---|---:|---:|---:|
| **overall** | primary semantic | 75.89% | **76.79%** | **+0.90pp** |
| overall | top-k semantic | 83.04% | **83.93%** | +0.89pp |
| overall | name-exact | 72.32% | 74.11% | +1.79pp |
| overall | abstain | 5.36% | **3.57%** | −1.79pp |
| overall | prediction ok | 100% | 100% | 0 |
| sub6 | primary semantic | 76.19% | **77.78%** | +1.59pp |
| sub6 | top-k semantic | 87.30% | 87.30% | 0 |
| hmdb_ramp | primary semantic | 75.51% | 75.51% | 0 |
| hmdb_ramp | top-k semantic | 77.55% | **79.59%** | +2.04pp |

ID-exact 全程 0%（v4 去掉 DB ID 预填充，强制 InChIKey，属预期）。差异全在 ReAct 跑次方差（±5pp）内、方向一致偏正 → **复现成功，无回归**。

### 4.2 Recall@k + Driver P/R（repro）

| stratum | recall@3 | hit@3 | MRR | driver P | driver R |
|---|---:|---:|---:|---:|---:|
| overall | 0.374 | 0.821 | 0.789 | 0.835 | 0.200 |
| sub6 | 0.506 | 0.873 | 0.839 | 0.906 | 0.211 |
| hmdb_ramp | 0.203 | 0.755 | 0.725 | 0.759 | 0.188 |

### 4.3 Claim-level verdict 分布（112 task 汇总，最终轮 / 含 feedback 后）

| verdict | overall | sub6 | hmdb_ramp |
|---|---:|---:|---:|
| **SUPPORTED** | 662 (**67.9%**) | 387 (69.4%) | 275 (65.9%) |
| INSUFFICIENT_EVIDENCE | 158 (16.2%) | 78 (14.0%) | 80 (19.2%) |
| UNSUPPORTED | 95 (9.7%) | 52 (9.3%) | 43 (10.3%) |
| CONTRADICTED | 5 (0.5%) | 3 (0.5%) | 2 (0.5%) |
| **UNVERIFIABLE_V0 (UV)** | 55 (**5.6%**) | 38 (6.8%) | 17 (4.1%) |
| —— graded 合计 | 975 | 558 | 417 |
| dropped_by_grammar | 55 | 41 | 14 |
| **noise (UNS+UV)** | 150 (**15.4%**) | 90 (16.1%) | 60 (14.4%) |

- **UV% = 5.64% / Supported% = 67.90%（overall）**。
- feedback 触发：57/112 task 跑了 feedback 轮，43 个最终采用 iter-1，69 个停在 iter-0。
- **重要 caveat**：此处 UV 5.6% **不可直接对比 W14 sub6b-v3 的 UV 44.25%**——基准不同（v4 vs sub6b-v3）+ verifier 代码不同（本次含多源重构 + 新增 `INSUFFICIENT_EVIDENCE` 档，把原本会落进 UV 的"证据不足"claim 接走）。
- 这些 verifier 指标本次能正常产出（`v4_task_to_subsix_source_report` 生效，0 adapter 失败），不再是 2026-06-25 报告"v4 无 UV/Supported 指标"的状态。

### 4.4 Legacy vs Cascade（生产 feedback 策略 paired 对比，同 112 task）

发现一个 cascade 接线 bug 并修复（见 §5.1）。下面是**修复后**的有效对比。

数据目录：legacy = `data/metagent/v4_bench_eval_repro_20260629/`；cascade(fixed) = `data/metagent/v4_bench_eval_cascade_fix_20260629/`。

| 维度 | Legacy rewrite | Cascade (fixed) | Δ |
|---|---:|---:|---:|
| pathway primary (overall) | 76.79% | **71.43%** | **−5.36pp** |
| pathway top-k (overall) | 83.93% | 81.25% | −2.68pp |
| ‑ sub6 primary | 77.78% | 66.67% | **−11.11pp** |
| ‑ hmdb_ramp primary | 75.51% | 77.55% | +2.04pp |
| prediction_ok | 100% | 100% | 0 |
| SUPPORTED claims | 67.9% | **86.3%** | **+18.4pp** |
| noise (UNS+UV) | 15.4% (150) | **2.8% (22)** | **−12.6pp** |
| ‑ UNSUPPORTED | 95 | **0** | −95 |
| ‑ CONTRADICTED | 5 | **0** | −5 |
| cost | $5.98 | **$4.25** | **−29%** |
| wall | 61.5 min | **44.1 min** | −28% |
| feedback 触发 task | 57/112 | 57/112 | — |

**诚实解读**（cascade 设计承诺 = "不破坏 pathway + 噪音归零"）：

- ✅ **噪音归零：强确认。** UNSUPPORTED 95→0、CONTRADICTED 5→0、noise 15.4%→2.8%、Supported +18.4pp，同时 −29% cost / −28% wall。
- ⚠ **不破坏 pathway：生产 primary 未兑现。** overall primary −5.36pp（sub6 −11.11pp 主导，hmdb_ramp +2.04pp 部分抵消）；但 top-k 仅 −2.68pp → **正确通路大多仍在 cascade 的 claims 里，是 second-pass 从精简后的 claim 池里选 primary 时选差了**。
- **与 feedback 实验"pathway +1 task"为何矛盾**：实验从 **claims**（topk 口径）量 pathway；生产 scorecard 量 **pathway_prediction primary**（second-pass LLM 从 claims 挑一个）。cascade 确定性删 UNSUPPORTED/UV 后，若 verifier 误判了含正确通路的 claim，second-pass 可选池变小 → primary 命中掉。实验口径掩盖了这个生产差距。
- **W21 死命令对齐**：核心指标看 SUPPORTED/质量↑（已达成），但 pathway primary 是本 benchmark 的主指标，−5.36pp 不可忽略。

> 注：第一次 cascade 全量（`v4_bench_eval_cascade_20260629/`，bug 未修）primary 41.07% / prediction_ok 44.64% 为**无效数据**（接线漏 pathway_prediction），仅留作 bug 复盘，不计入对比。

---

## 5. 代码情况小结（Code状态）

| 组件 | 状态 |
|---|---|
| feedback cascade 策略（`feedback_strategies.py`） | ✅ 当前分支已有，已验证 |
| verifier 多源重构 + INSUFFICIENT_EVIDENCE + v4 adapter | ✅ 当前分支已有，本次复现验证产出正常 |
| cascade 接入生产 `react_runner` | ✅ **已提交（`00d47f0`）**，B1 Gate A 409/0 无回归 |
| cascade pathway_prediction bug 修复 | ✅ **已提交（`b75601f`）**，见 §5.1 |
| 生产 feedback 实际路径 | **现为 cascade**（`feedback_strategy="cascade"` 默认；legacy rewrite 保留在 `="rewrite"`） |
| 实验脚本 `feedback_ab_eval.py` worktree 改动 | ⚠ 与生产接线正交，未随本次提交，仍留 worktree |

工作区当前未提交/未追踪：`reports/reports_v2/2026-06-19_full344_pathway_scorecard.{json,md}`（M）、`docs/decisions/2026-06-26_feedback_workflow_a_cascade.md`（未追踪副本）、本总结 + 复现/对比 scorecard。

### 5.1 cascade pathway_prediction bug（本 session 发现并修复）

- **症状**：cascade 全量首跑 pathway primary 41.07% / prediction_ok 44.64%（暴跌）。
- **根因**：`_run_cascade_iteration` 构造的合成 `ConcordReactResult` 没设 `pathway_prediction`（默认 None）；生产 scorecard 读 `final_react_result.pathway_prediction` 算通路准确率 → 凡跑了 cascade 反馈的 task（62/112）prediction 全判失败。相关性 62/62 完美。
- **为何实验没抓到**：feedback A/B 实验从 claims 量 pathway，没走生产 scorecard 这条路。
- **修复（`b75601f`，TDD，`[concord-modify-warning]`）**：cascade 迭代用与 iter-0 同一个 `generate_pathway_prediction_second_pass`，对修正后 claims + 织好的叙述重新生成 `pathway_prediction` 并存入结果。生成器永不抛（失败/空 claims 返回 abstain sentinel）。
- **验证**：RED→GREEN 新测试 `test_cascade_iteration_populates_pathway_prediction`；cascade 5/5 + legacy 40 + B1 Gate A 409/0；1-task live smoke pathway_prediction 正常填充。修复后 prediction_ok 回到 100%。

---

## 6. 下一步候选

| # | 候选 | 说明 |
|---|---|---|
| 1 | ~~提交 cascade 生产接线~~ | ✅ **已完成**（`00d47f0`）。 |
| 2 | ~~cascade 全量 v4 重跑 + 对比~~ | ✅ **已完成**（见 §4.4；发现并修复 bug `b75601f` 后得有效对比）。 |
| 3 | **诊断 cascade sub6 −11pp** | per-task paired 翻转分析：定位 sub6 哪些 task primary 由对变错，判断是 verifier 误删含正确通路的 claim（改 verifier/cascade 规则）还是 second-pass 选 primary 退化（改 second-pass prompt）。**推荐下一步。** |
| 4 | cascade primary 选择策略 | top-k 仅 −2.68pp 说明正确通路多半还在；可让 cascade 的 pathway_prediction 优先 SUPPORTED claim 的通路，或保留 iter-0 primary 做对照。 |
| 5 | 提交本次复现/对比产物 | 复现报告 + 3 套 scorecard + 决策文档副本 + 本总结入库（目前未提交）。 |
| 6 | feedback_ab_eval.py 收尾 | 评估 worktree 实验脚本 adapter 2-参改动是否入库。 |

---

## 7. 复现命令

```bash
PY=/home/weiwentao/miniconda3/bin/python3
KEY=$(cat /home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5/api_key_minimax.txt | tr -d '[:space:]')
export MINIMAX_API_KEY="$KEY" METAGENT_API_KEY="$KEY" METAGENT_LLM_PROVIDER=minimax
export METAGENT_VERIFY_STRUCTURED_CLAIMS=1 METAGENT_ENABLE_METHOD_AWARE_ENRICHMENT=1
export METAGENT_LLM_LOG_PATH=logs/concord/v4_repro_full.jsonl

# run
PYTHONPATH=. $PY scripts/metagent/v4_bench_eval.py \
    --benchmark data/benchmark/metagent_bench_v2/metagent_bench_easy_v4_metabolic.jsonl \
    --strata sub6 hmdb_ramp --out data/metagent/v4_bench_eval_repro_20260629 \
    --max-react-turns 8 --max-feedback-iters 1 --k 8

# score
PYTHONPATH=. $PY scripts/metagent/full344_pathway_scorecard.py \
    --out-dir data/metagent/v4_bench_eval_repro_20260629 \
    --benchmark data/benchmark/metagent_bench_v2/metagent_bench_easy_v4.jsonl \
    --relevant-sidecar data/benchmark/metagent_bench_v2/relevant_sets_easy_v3.json \
    --gold-sidecar data/benchmark/metagent_bench_v2/gold_drivers_easy_v3.json \
    --ramp /data/weiwentao/llm_agent_metabolomics/ramp.sqlite \
    --report-dir data/metagent/v4_bench_eval_repro_20260629/scorecard \
    --stem 2026-06-29_v4_repro_scorecard --llm-log logs/concord/v4_repro_full.jsonl
```

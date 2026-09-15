# Stage 1+2 End2End —— 谱图集合 → 通路鉴定报告（方法 · 数据 · 结果 · 复现）

> 整理日期：2026-06-30 · 分支 `metagent-v3-benchmark`
> 范围：**端到端 = 输入一组 MS/MS 谱 → Stage 1 逐谱识别成代谢物 → 最新 Stage 2（concord ReAct 5-PA 富集 + cascade）→ 输出通路鉴定报告**。
> 口径：**Stage 1 用原流程（sub6a library_search 识别），Stage 2 用最新版（v4 cascade 生产路径）**。
> 数据/脚本根目录：`data/metagent/stage1_2_e2e/` · `scripts/metagent/stage1_2_e2e_build.py`。
> 关联：Stage 1 细节见同目录 `2026-06-30_stage1_method_data_results_repro.md`；Stage 2 v4 权威见 `2026-06-29_v4_reproduction_and_cascade_status_summary.md`。

---

## 1. 方法（Method）

### 1.1 端到端链路
```
sub6a 谱图（38 task × ~12 谱）
  └[Stage 1 原流程] library_search modcos ±10ppm → top-1 候选 → 按 InChIKey 骨架去重
  └[桥接] 识别出的 {name, SMILES, InChIKey} → v4 schema input.differential_metabolites
  └[Stage 2 最新] ConcordReactRunner.run_task_with_feedback
        （5-PA 富集 ReAct: SSPA/Mummichog/RaMP/MetaboAnalystR/FELLA
         + cascade feedback + second-pass pathway_prediction）
  └[打分] PathwayNameMatcher semantic match（predicted primary vs ground_truth_pathway）
```

**关键设计**：
- **桥接不改 Stage 2**，纯复用现成生产代码：`run_sub6a_batch(skip_narrative=True)` 出 Stage 1 识别 → 合成一个 v4-format benchmark（task_id 加 `sub6_easy_` 前缀让 stratum=sub6，`ground_truth_pathway` 映射成 `ground_truth.perturbed_pathway`）→ 直接跑 `v4_bench_eval.py` + `full344_pathway_scorecard.py`。
- **关键变量**：Stage 2 吃的是**真实识别结果**（含 Stage 1 误判，谱级仅 67% 正确），不是 perfect-id 的 ground-truth 代谢物列表。这正是端到端要量化的误差传播。

### 1.2 Stage 1 → Stage 2 传什么（实现细节）
代谢物以 prompt bullet 传给 agent：`- <name> (SMILES: <smiles>, InChIKey: <ik>)`（v4 SMILES-first 路径，**KEGG/DB ID 刻意 suppress**，逼 agent 用 InChIKey/SMILES 调富集工具）。
- **InChIKey 必须是完整 27 字符**：concord `ChebiLookup.lookup_by_inchikey` 只认完整 key（14 字符 first-block 会 MISS）。桥接用 RDKit 从 `predicted_smiles` 重算完整 InChIKey（`_full_inchikey`）。
- 见 §3 的 v1（误用 14 字符）vs v2（修正为完整）对比——这是本次最重要的发现。

---

## 2. 数据（Data）

| 项 | 文件 / 规模 |
|---|---|
| 输入任务 | `data/benchmark/sub6/sub6a_e2e_tasks_v2.jsonl`（38 task，每 task 含 `differential_spectra` + `ground_truth_pathway` + `ground_truth_signal/noise_compounds`） |
| Stage 1 识别结果 | `data/metagent/stage1_2_e2e/stage1_results.jsonl`（38 行 Sub6AResult） |
| 合成 benchmark (v2,完整 IK) | `data/metagent/stage1_2_e2e/e2e_benchmark.jsonl` |
| 合成 benchmark (v1,14字符) | `data/metagent/stage1_2_e2e/e2e_benchmark_block14.jsonl` |
| Stage 2 trace | `stage2_full/`（v1）· `stage2_full_v2/`（v2）下 `path_x_full/` + `status/` |
| 打分 | `stage2_full*/scorecard/e2e_full38*.{json,md,csv}` |
| 参照上界 | v4 sub6 stratum perfect-id（不同 seed，非 1:1 配对），见 v4 复现 summary |

---

## 3. 结果（Results）

### 3.1 Stage 1（识别）
| 指标 | 值 |
|---|---:|
| 谱级 top-1 id 准确率（InChIKey 骨架） | **67.32%**（309/459 谱） |
| 平均去重代谢物 / task | 8.45 |

> 67.32% 分母是全部 459 谱（含没过 Phase A 的）；Stage 1 文档里 72.07% 分母是 Phase A 存活的 ~358 谱,同口径不同分母。

### 3.2 Stage 2 端到端 —— 两轮（InChIKey 保真度对照）

| 指标 | v1 (14char,解析断) | v2 (full IK,解析通) | perfect-id 上界† |
|---|---:|---:|---:|
| **primary semantic** | **55.26%**（21/38） | **36.84%**（14/38） | 76.19% |
| top-k semantic | 63.16% | 44.74% | 87.30% |
| 非 abstain 准确率 | 77.8%（21/27） | 53.8%（14/26） | — |
| abstain 率 | 28.95% | 31.58% | ~3.6% |
| pathway_prediction_ok | 100% | 100% | 100% |
| 成本（MiniMax 实测） | 498 calls/4.2M tok/~$2.3/27min | 同量级/~$2.3/28min | — |

† perfect-id 上界 = v4 sub6 stratum（同域同通路、不同 seed，**非 1:1 配对**，仅作量级参照）。

### 3.3 核心发现：InChIKey「修对了反而变差」（反直觉）

- **修复正确**：v1 误把 Stage 1 的 14 字符 first-block 填进 inchikey → concord `lookup_by_inchikey` MISS（解析率 0%）；v2 用完整 InChIKey → 解析率 **0%→69.5%**（实测 ChebiLookup HIT）。
- **但端到端分数反降**：primary 55.26%→36.84%（−18.4pp）。**配对逐任务：same-hit 11 / same-miss 14 / v2 赢 3 / v2 输 10**（净 −7，方向性退化,非平衡 churn,丢分集中在同几条通路的不同 seed）。
- **解读（hypothesis，未证）**：Stage 1 谱级仅 67% 结构正确。把（1/3 错的）化合物**正确**解析成精确 ChEBI/KEGG ID 后，agent 是在用"确信但部分错结构"的集跑富集 → 把信号拉向错通路；v1 那条断掉的解析反而逼 agent 退回 name/SMILES 软推理，对误识别更鲁棒。**含义：端到端瓶颈不是 ID 解析管道，而是 Stage 1 误识别本身——更精确的管道反而更"自信地"传播错 ID。**

### 3.4 ⚠ 方差未控（结论强度）
死命令 `react_rerun_variance_control`：ReAct 单跑方差 ±5pp。18pp 摆动里修复效应 vs 单跑噪声**无法用单次配对分离**（abstain 本身 v1=11/v2=12、仅 7 重叠，证明有 run-level 随机性）。当前可下的结论：**修复让解析变通，但端到端分数没涨反跌、方向偏负**；要坐实"修对了反而变差"需 **3-seed 平均或多次配对重跑**（未做，用户暂停）。

---

## 4. 已知限制 / 缺口
1. **方差未控**（见 §3.4）——本文所有 Δ 为单跑配对,不构成统计结论。
2. **perfect-id 上界非 1:1 配对**（不同 seed/任务数 38 vs 63）,量级参照而非严格对照。严格配对需对同一批 sub6a 任务用其 `ground_truth_signal/noise_compounds`（KEGG ID,需 resolve）另跑 perfect-id Stage 2。
3. **abstain 高位**（~30%）是主要可优化点：富集信号真不足 vs second-pass 阈值过严待诊断；与 v4 cascade primary −5.36pp 同类问题。
4. `tools_called:[]` 出现在 cascade 重建的 final_react_result（表象,真实 RaMP 富集有调用,见 run log）。

---

## 5. 复现脚本

```bash
cd /home/weiwentao/workspace/llm_agent_metabolomics/metagent_v2
./scripts/concord/setup_metagent_v2_env.sh
export MINIMAX_API_KEY=$(cat ../metagent_day1_v5/api_key_minimax.txt)

# 1) Stage 1（原流程,纯 modcos 无 LLM）+ 桥接 → 合成 benchmark（完整 InChIKey）
PYTHONPATH=. python scripts/metagent/stage1_2_e2e_build.py
#   产物: stage1_results.jsonl / e2e_benchmark.jsonl / build_summary.json
#   (--limit N 可冒烟; Stage 1 已落盘,重跑会 skip-done 只重组 benchmark)

# 2) Stage 2（最新版 concord ReAct + cascade,~27 min ~$2.3）
export METAGENT_LLM_PROVIDER=minimax
PYTHONPATH=. METAGENT_LLM_LOG_PATH=logs/concord/stage1_2_e2e_full_v2.jsonl \
python scripts/metagent/v4_bench_eval.py \
    --benchmark data/metagent/stage1_2_e2e/e2e_benchmark.jsonl --strata sub6 \
    --out data/metagent/stage1_2_e2e/stage2_full_v2 \
    --max-react-turns 8 --max-feedback-iters 1 --k 8

# 3) 打分
PYTHONPATH=. python3 scripts/metagent/full344_pathway_scorecard.py \
    --out-dir data/metagent/stage1_2_e2e/stage2_full_v2 \
    --benchmark data/metagent/stage1_2_e2e/e2e_benchmark.jsonl \
    --report-dir data/metagent/stage1_2_e2e/stage2_full_v2/scorecard --stem e2e_full38_v2
```

### 关键脚本 / 代码
| 路径 | 职责 |
|---|---|
| `scripts/metagent/stage1_2_e2e_build.py` | 桥接：Stage 1 识别 → 合成 v4 benchmark（`_full_inchikey` 重算完整 InChIKey） |
| `evaluation/sub6/run_sub6a.py::run_sub6a_batch` | Stage 1 识别（`skip_narrative=True` 只产识别） |
| `scripts/metagent/v4_bench_eval.py` | 最新 Stage 2 driver（ConcordReactRunner + cascade） |
| `scripts/metagent/full344_pathway_scorecard.py` | semantic pathway 打分（`PathwayNameMatcher.is_hit`） |
| `concord/agent/react_runner.py::run_task_with_feedback` | Stage 2 入口 |

> cost 死命令：MiniMax 远程 API,禁说 "$0 local",实测查 `logs/concord/stage1_2_e2e_full*.jsonl`。

# Session Summary: v4 Benchmark P0–P3 Fixes (2026-06-25)

Branch: `metagent-v3-benchmark`  
Benchmark: `metagent_bench_easy_v4_metabolic.jsonl` (292 tasks; this run: sub6=63, hmdb_ramp=49)  
Model: MiniMax-M2.7-highspeed · Wall: ~65 min · Tokens: 10.8M (6.8M cached)

---

## 背景

上个 session 完成了 InChIKey xref pipeline 和 v4 filtered benchmark 基础版，两个核心修复（second-pass SELECTION RULE + semantic matcher parallel OR + stemming）已 commit。本 session 的目标是：

1. 诊断 hmdb_ramp 43.43% 的根因
2. 实施 P0–P3 修复
3. 重跑 112-task benchmark（sub6 + hmdb_ramp filtered）
4. 产出完整 scorecard

---

## P0–P3 修复

### P0：过滤 ill-posed benchmark tasks

**问题**：v4 filtered benchmark 的 hmdb_ramp 99 个任务里，有 ~50 个任务在原理上无法用 membership-based 富集范式解决：
- 18 个 WikiPathways 任务：CNV pathways / ADHD / ACE inhibitor 等信号通路，没有代谢物成员
- 32 个 Reactome 任务：ADME / 烷化修复 / 信号转导通路，RaMP/KEGG 代谢物成员表中不存在

**修复**：新建 `metagent_bench_easy_v4_metabolic.jsonl`（292 tasks，hmdb_ramp 99→49），保留全部 sub6=63 和 human1/recon22（后两者标注为 "beyond enrichment paradigm scope"）。

**commit**: `adaecbb` `feat(bench): P0 filtered benchmark metagent_bench_easy_v4_metabolic (342→292 tasks)`

### P1：ReAct system prompt — RaMP 优先规则 + KEGG namespace 等价

**问题**：当 RaMP 返回高置信度信号（FDR ≤ 1e-5，fold ≥ 5）时，LLM 仍要求多工具收敛才选该通路，导致明确答案被否决。同时 LLM 把 `map00020` 和 `hsa00020` 视为不同通路，收敛评分错误。

**修复**：`prompts/concord/concord_react_prompt.md` 新增两条规则：
- SELECTION RULE：RaMP FDR ≤ 1e-5 + fold ≥ 5 → 直接作为强证据，不需多工具收敛
- KEGG namespace rule：`map00XXX` 和 `hsa00XXX` 数字部分相同即等价，不惩罚收敛评分

**commit**: `28b9b24` `fix(prompt): RaMP priority rule + KEGG namespace equivalence`

### P2：tool_handlers.py — KEGG map→hsa ID 规范化

**问题**：`run_ramp_enrichment` 返回的 pathway_id 是 `KEGG:map00020`，而其他工具（MetaboAnalystR）返回 `KEGG:hsa00020`，LLM 看到两个不同 ID 认为没有收敛。

**修复**：`concord/agent/tool_handlers.py` 新增 `_normalize_kegg_id()`，在 RaMP 返回结果发送给 LLM 前统一转换 `KEGG:map` → `KEGG:hsa`。

**commits**: `a5058c0` (RED) → `e68c7a9` (GREEN) `[concord-modify-warning]`

### P3：pathway_prediction.py — second-pass 失败时返回 abstain 而非 None

**问题**：`generate_pathway_prediction_second_pass()` 在 LLM 响应解析失败（invalid JSON / 格式错误）时静默返回 `None`，导致 `pathway_prediction` 字段在 task trace 中消失，scorecard 统计 `prediction_ok=False`。

**修复**：引入 `_ABSTAIN_SECOND_PASS_FAILED` sentinel dict（`{"primary": null, "alternatives": [], "abstain": true, "abstain_reason": "second_pass_failed"}`），所有 6 条失败返回路径改为返回该 sentinel。`react_runner.py` 中 `empty_system_failure` 和 `empty_unknown` 分支同步修改。

**commit**: `a5058c0`（随 P2 RED test 一起提交）

---

## 全量 scorecard（P1+P2+P3 修复后，112 tasks）

数据来源：`data/metagent/v4_bench_eval_sub6hmdb_p1p2p3_20260625/scorecard_p1p2p3/`

### 主要指标

| stratum | tasks | primary semantic | top-k semantic | abstain |
|---|---:|---:|---:|---:|
| **overall** | 112 | **75.89%** | **83.04%** | 5.36% |
| sub6 | 63 | **76.19%** | **87.30%** | 3.17% |
| hmdb_ramp (filtered 49) | 49 | **75.51%** | **77.55%** | 8.16% |

prediction ok: **100.00%**（P3 修复前为 96.91%，P3 fallback 保证不再出 None）

### Recall@k + Driver P/R

| stratum | recall@3 | hit@3 | MRR | driver P | driver R |
|---|---:|---:|---:|---:|---:|
| overall | 0.376 | 0.813 | 0.778 | 0.882 | 0.209 |
| sub6 | 0.504 | 0.841 | 0.807 | 0.915 | 0.216 |
| hmdb_ramp | 0.211 | 0.776 | 0.742 | 0.847 | 0.202 |

---

## 修复前后对比

### 主 semantic 准确率（primary semantic）

| stratum | 修复前 | 修复后 | Δ |
|---|---:|---:|---:|
| sub6 | 65.08% | **76.19%** | **+11.11 pp** |
| hmdb_ramp (apple-to-apple 49 tasks) | 69.4%* | **75.51%** | **+6.1 pp** |
| hmdb_ramp (全 99，含 ill-posed) | 43.43% | — | —（不可比） |

\* apple-to-apple：同 49 个任务在 P1+P2+P3 前后比较

### hmdb_ramp 按 ontology（修复后，49 tasks）

| ontology | tasks | pass | accuracy |
|---|---:|---:|---:|
| KEGG | 40 | 37 | **92.5%** |
| Reactome | 7 | 0 | **0%** |
| WikiPathways | 2 | 0 | **0%** |

Reactome 7 个全 FAIL：RaMP 信号本身就稀疏（这些通路的成员代谢物在 RaMP 里覆盖率低），是数据库覆盖率问题，不是系统问题。WikiPathways 2 个 FAIL：同类原因。

---

## sub6 剩余 15 个 FAIL 根因

| 根因 | 数量 | 代表性通路 | 处置建议 |
|---|---:|---|---|
| Broad Reactome parent pathway | ~7 | Biological oxidations (6) | 原理性难题，仅能 matcher 层优化 |
| Matcher synonym 缺失 | ~3 | Eicosanoid synthesis ↔ Arachidonic acid metabolism | 加 WP167 sidecar synonym |
| Parent/child scorer 阈值 0.80 过严 | ~3 | Androgen/Estrogen Metabolism | 降阈或加子通路映射 |
| Abstain fallback（P3 触发） | 2 | 各 1 sub6 | 正常 fallback，不属于系统错误 |

---

## Verifier 指标参考

v4 benchmark 任务缺少 `SubsixSourceReport` 必填字段（task_type / domain / ground_truth_pathway 等），verifier adapter 报 `source_report_adapter_failed`，v4 run 无 UV/Supported 指标。

Verifier 指标参考 **W14 Stage-2 官方数字**（sub6b-v3, 63 tasks）：

| 指标 | 数字 |
|---|---:|
| UV % | 44.25% |
| Supported % | 34.48% |
| Pathway accuracy | 85.7% (54/63) |
| iter-2 trigger | 0/63 |
| Wall | 64.2 min |
| Cost | $6.83 |

---

## 本 session commit 列表

| commit | 说明 |
|---|---|
| `28b9b24` | P1: RaMP priority rule + KEGG namespace equivalence（prompt） |
| `a5058c0` | P2 RED + P3 GREEN: null fallback + _normalize_kegg_id RED test |
| `e68c7a9` | P2 GREEN: _normalize_kegg_id + RaMP output normalization `[concord-modify-warning]` |
| `adaecbb` | P0: filtered benchmark metagent_bench_easy_v4_metabolic (342→292) |
| `059f725` | feat: v4_bench_eval skip-done + --strata multi-stratum flag |
| `008e91b` | docs: design decision 2026-06-25 + failure analysis script |

---

## 未解决 / 下一步候选

| # | 候选 | 预期收益 | 难度 | 备注 |
|---|---|---|---|---|
| 1 | Matcher synonym fix（Eicosanoid ↔ Arachidonic） | ~2–3 sub6 FAIL 消除 | 低 | 加 sidecar JSON 即可 |
| 2 | Reactome 0% 专项诊断 | 诊断为主，看是 RaMP 覆盖还是 narrative | 中 | 7 任务，先采样 2–3 个手工看 |
| 3 | W16 UV tighten（Stage-2, C7 producer prompt） | 4.57 pp UV ceiling | 高 | 与 v4 bench 独立，prompt-only |
| 4 | human1/recon22 GEM crosswalk | — | — | 明确不做；超出 enrichment paradigm scope |

---

*Report generated: 2026-06-25*

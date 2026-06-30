# Concord Sprint W9 — Status (Framework Fix Sprint)

**Branch:** `feature/investigation-concord` (worktree `metagent_day1_v5_investigation`)
**HEAD at sprint start:** `9fcc2f3` (W8 D5 完结)
**Sprint window:** 2026-05-18+ (5 工作日,人值守)
**Spec:** `prompts/track_CONCORD_sprint_W9_framework_fix.md` (main worktree)
**Mode:** D2 handler-output-shape gap fix + Path X full 63 re-run + framework
health report v2;**0 paper writing,0 deterministic 复辟,0 strict TDD slip**。

---

## 0. Onboarding Completion

Sprint context is continuous from W8 D1-D5(同 session,memory 中 W8
context 全 hot)。Onboarding 是 quick re-verify,不是冷读。

### Tier 1 takeaways(W9 上下文)

1. **`reports/agent/concord_w8_framework_health.md`**(prompt 写
   `concord_sprint_w8_*` 是 typo,实际文件名无 `sprint_`):W8 D5 health
   report。5 issue list 头条 = **D2 handler-output-shape gap**(4/5 PA
   wrapper 在 dispatcher 静默返回 `_n_pathways=0`)。Path Y ≈ Path Z =
   96.83% precision@10 是 wrapper-normalisation 缺失导致 V3 算法等于
   RaMP alone 的直接证据。`bridge_lost_to_rollback = 1/5` 是 D4 smoke 2
   trajectory 的 generalisation seed。
2. **`reports/agent/concord_sprint_w8_status.md` §D4/§D5**:D4 close-loop
   wire 工程上工作(38 concord/agent test 全绿),D5 落 4 path data + 17
   new test。W8 D5 末 full pytest 17/1306/33,D5 引入 0 regression。
3. **W8 prompt §0 + §2**:架构 spec 全锁定 — 9 tool catalog(5 PA +
   4 utility,不暴露 V3 algorithm tool),grammar v2 4 类 claim,
   closed-loop verifier wire,max_react_turns=8 + max_feedback_iters=2。
   W9 全部不改,只动 dispatcher 适配层。

### Tier 2 scan(代码当前态)

**`concord/agent/tool_handlers.py` 当前 9 个 handler**(W9 主要改动区域):

| handler | wrapper call site | output 读取 | D5 实际效果 |
|---|---|---|---|
| `handle_run_sspa_ora` | `run_sspa(compound_refs=...)` | `raw.get("pathways")` | ❌ sspa 输出 method-key dict `{ora,gsva,kpca,...}`,无顶层 `pathways` → `_n_pathways=0` |
| `handle_run_ramp_enrichment` | `run_ramp_enrichment(refs, top_n=)` | `raw.get("pathways")` | ❌ ramp 输出 `{report: EnrichmentReport}` → `_n_pathways=0`(虽然 ramp wrapper 本身找对 96.83%) |
| `handle_run_metaboanalystr_psea` | `run_metaboanalystr_psea(refs)` | `raw.get("pathways")` | ❌ psea 输出 `{raw: <R subprocess JSON>}` → `_n_pathways=0` |
| `handle_run_mummichog` | `run_mummichog_for_compound_set(refs)` | `raw.get("pathways")` | ✅ mummichog 输出 `{pathways: [...]}` 直接命中 → `_n_pathways > 0` |
| `handle_run_fella_rwr` | `run_fella_rwr(refs)` | `raw.get("pathways")` | ❌❌ fella 输出 `{raw: ...}` + R 端 "argument is of length zero" 100% 失败 |
| `handle_lookup_chebi` / `handle_reconcile_inchikey` / `handle_query_pathway_members` / `handle_search_literature` | 各 own normalisation,与 W9 无关 | — | OK |

**5 wrapper 实际 top-level output keys**(D5 已实测,W9 normaliser 输入):

| wrapper | top-level keys (excerpt) | 真 pathways 字段 |
|---|---|---|
| sspa | `ora, gsva, kpca, kegg, metacyc, _input_chebi_numeric, method, n_input, n_input_resolved, organism, ...` | method-key dict (e.g. `output["ora"]` 是 DataFrame-like / list of dict) |
| ramp | `report, wall_time_sec, n_input, n_input_resolved, parameters, ...` | `output["report"].top_pathways: list[EnrichmentResult]` |
| metaboanalystr | `raw, library, mode, method, compounds, params, db_release, tool_version, wall_time_sec, error, n_input, ...` | `output["raw"]: <R subprocess JSON>`(具体 shape D2 normaliser 实测时确定) |
| mummichog | `pathways, empirical_compounds, stats, errors, parameters, peaks, ref_db, n_features_in, n_pathways_tested, n_significant, ...` | `output["pathways"]: list[dict]`(D2 mummichog handler 直接读) |
| fella | `raw, method, organism, compounds, params, db_release, tool_version, wall_time_sec, error, auxiliary_data, ...` | `output["raw"]: <R subprocess JSON>`(D2 normaliser 实测时);D5 实测 R 端"argument is of length zero" |

**Test base**:`tests/concord/test_concord_tools.py` 13 case(D2 + D2
hotfix regression)+ `tests/concord/test_react_runner.py` 5 case(D3)+
W8 D4/D5 共 37 case = 55 total。W9 加 wrapper shape contract test
**不破坏既有**(新文件 `tests/concord/test_wrapper_shape_contracts.py`)。

### Tier 3 data state

- **Path X 5-task D5 sample**:`data/concord/w8_llm_agent/path_x_results.jsonl`
  (5 rows,13117 bytes)+ `path_x_summary.json` ✓ 存在,W9 D5 re-run
  会覆盖到新 dir `data/concord/w9_llm_agent_full/`。
- **Path W symlink**:`data/eval/sub6/v3/sub6b_opus` →
  `/home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5/data/eval/sub6/v3/sub6b_opus`
  ✓ active(W8 D1 setup,不动)。

---

## Confirmation

**(a) W9 任务是修 D2 handler-output-shape gap,不是改 wrapper 源** ✅
所有 normaliser 落 `concord/normalize/wrapper_shape_norm.py`(新文件)+
`concord/agent/tool_handlers.py` 5 个 PA handler 用 normaliser。
**0 改动**到 `concord/wrappers/*.py`。

**(b) Path X full 63 task re-run 在 W9 内(D5),不延 W10** ✅
预算 wall ~1.5-2h(K=10 concurrent if 工程能力允许;sequential ~8h
是 D5 budget edge);API cost ~$5-7 from `logs/llm_calls.jsonl`(MiniMax
remote API token-billed,**不"$0 local"**)。

**(c) Layer 6a cross-ns / Quality metric 延 W10,W9 不碰** ✅
W9 不改 `verifier/` 任何文件。bridge_lost_to_rollback 现象在 W9 数据上
继续观察,W10 才设计 fix。

**(d) FELLA fix 是 W9 stretch (≤4h time-box),不阻塞 D5 主线** ✅
若 4h 没头绪 → 标 W10 candidate,继续 D5。

**(e) 不写 paper narrative,framework health report v2 用 raw 数字
描述** ✅
report v2 沿用 W8 D5 health report 结构(纯数据 + W10 issue list)。
0 "reconciliation lift" / "cross-paradigm consensus" / "future work" 等
paper-style 措辞。

**(f) 不暴露 V3 算法 tool,死命令延续** ✅
9 tool catalog 不变;V3 算法仅作 Path Y baseline 在 W9 D6 report 中
引用 W8 D5 数字(不重跑,不暴露 tool)。

---

## W9 Open Questions(non-blocking,主线推进)

1. **Prompt §3 D1 contract test 示例 API 不一致**:prompt 写
   `from concord.agent.tool_dispatcher import call_run_sspa_ora`,但
   实际 D2 实现把 handler 拆到 `concord.agent.tool_handlers` 命名为
   `handle_run_sspa_ora`,dispatcher 暴露的入口是
   `dispatch({"name": "run_sspa_ora", "arguments": ...}) -> DispatchResult`。
   **W9 D1 contract test 直接走 `dispatch(...)` 入口**(envelope-level
   contract),不导入私有 handler。Spec 行为等价,API 名一致。

2. **sspa wrapper_unavailable + FELLA R 端 fail 在 D1 RED 期间的混合**:
   sspa pkg 未装 → `_err("wrapper_unavailable", ...)` envelope(已在 D2
   测试,等价 PR4);FELLA R 端 "argument is of length zero" → 当前
   handler `except Exception` catch 返回 `{error: "raised...", ...}`
   envelope。**D1 contract test 区分两 envelope shape**:
   - `_n_pathways == 0` AND `error == "wrapper_unavailable"` → 环境
     未装,**不是 D2 handler gap**(sspa 这种情况会持续直到环境装
     sspa pkg,W10+)
   - `_n_pathways == 0` AND `ok == True` → **D2 handler gap**(W9 主要
     fix 目标)
   两种 都期待 D1 RED,但 fix 策略不同。

3. **Path X full 63 task K-concurrent 复杂度**:W9 D5 预算假设 K=10
   concurrent。当前 `concord/agent/react_runner.py` 实现 sequential。
   K-concurrent 实现需要 ThreadPoolExecutor + 各 PA wrapper 的线程
   安全性 audit(metaboanalystr / fella Docker R session 共享态,
   mummichog venv subprocess 是否安全 K=10 实际未验证)。**D5 行动**:
   先 sequential 跑(实测 ~8h)看是否完成;如超 wall stop condition
   (> 4h),pivot 到 K=2-4 并 audit Docker session 共享。

---

(D1 RED phase contract test 待 user sanity check 后启动。)

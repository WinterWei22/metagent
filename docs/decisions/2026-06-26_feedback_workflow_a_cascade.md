# 决策：A_cascade 定为 MetAgent 的 feedback 工作流

- 日期：`2026-06-26`
- 状态：**Accepted**
- 范围：Stage 2（富集后 narrative + claim 验证）的 self-correction / feedback 轮
- 相关：`reports/reports_v3/summary/2026-06-26_feedback_redesign_phase_summary.md`、`reports/reports_v3/2026-06-26_feedback_ab_v4_full112.md`、`docs/superpowers/specs/2026-06-26-feedback-redesign-design.md`

---

## 决策

MetAgent 的 feedback 轮采用 **A_cascade（确定性 cascade）** 策略：系统按 iter-0 verdict 确定性处理 claim（SUPPORTED 保留 / CONTRADICTED 替换为多源池 top-1 / UNSUPPORTED 删 / INSUFFICIENT 保留 / UV 删），LLM 仅做 1 次受限 narrative 织合、不得增删或修改 claim。

正式入口：`concord.agent.feedback_strategies.apply_feedback_strategy("cascade", verified_claims, source_report)`（已实现、已验证）。

**否决**：B_anchored（LLM 锚定重写）与原 legacy rewrite feedback，均因"让 LLM 自由重写 claims"而净破坏质量。

## 依据（全量 v4 112-task 实验，paired，3 个 live 臂可比）

| 臂 | pathway top1 | 噪音 (UNS+UV) |
|---|---:|---:|
| iter0_reverify（无反馈基线） | 75.00% (84/112) | 139 |
| **A_cascade** | **75.89% (85/112，+1 task)** | **0** |
| B_anchored | 54.05% (60/111，−24 task) | 651 |

A 在主指标上不退反略升、噪音确定性归零；B 在两个轴上都崩。23-task sub6b-v3 先导方向一致。成本 $1.47 / 112 task。

## 设计原理

> self-verification 的安全收益来自把"改什么"从 LLM 手里拿走、只留"怎么说"给 LLM。

与 OriGene Critic Agent / GeneAgent 的 deterministic-cascade 一致。LLM 无权增删 claim ⇒ 机制上根除"破坏 supported / 引入新通路 / 留噪音"。

## 当前生效范围（已落地，2026-06-26）

- ✅ **策略选型 + 实现 + 全量验证**：cascade 是选定的 feedback 工作流，入口 `feedback_strategies.py`，由 112-task v4 实验背书。
- ✅ **生产 `react_runner.run_task_with_feedback` 默认已切换为 cascade**（`feedback_strategy: str = "cascade"`），legacy rewrite 保留在 `feedback_strategy="rewrite"`。最新 v4 全流程 driver `scripts/metagent/v4_bench_eval.py` 不传该参数 → 自动走 cascade。属 ⚠ `[concord-modify-warning]` 改动。

### 实施记录（react_runner 生产接线，已完成 + 已验证）

1. `ConcordReactRunner` 加 `feedback_strategy: str = "cascade"` 字段 + `__post_init__` 校验 ∈ {"cascade","rewrite"}。
2. `verify_with_b1` 尾部抽成可复用 `_verify_payload(narrative, source_report, …)`；adapter dispatch 抽成 `_build_source_report(react_result, task)`（纯 refactor，rewrite 路径测试保持 green）。
3. `run_task_with_feedback` iter-k 分支：`cascade` → `_run_cascade_iteration`（取 `prev_outcome.verdict.claims_v2` → `apply_feedback_strategy("cascade", …)` → `_verify_payload` → 合成 `ConcordReactResult`）；`rewrite` → 原行为。
4. 新增 `_weave_llm_call`：cascade 织叙述走 runner 自身 provider/model，且**永不抛**（LLM 失败降级为空叙述——叙述是 cosmetic，指标由确定性 claims 决定）。这是补全原实现的关键缺口（RED 测试 `test_cascade_iteration_does_not_rerun_react` 暴露）。
5. 早退 / rollback / `_assemble_feedback_result` 逻辑不变。

### 验证结果（全绿）

| 检查 | 结果 |
|---|---|
| cascade 单元 + 一致性测试 `tests/concord/test_react_runner_cascade_default.py` | **4/4 passed** |
| legacy feedback loop（`test_run_task_with_feedback` + `iter_cap` + `d4_dispatcher`） | **42/42 passed**（rewrite 路径仍可达） |
| **B1 Gate A**（verifier-core 等 6 套） | **409 passed / 0 failed**（无回归；+2 vs 407 基线 = 本 session INSUFFICIENT_EVIDENCE 新增） |
| 全 concord 套件 | 346 passed / 10 failed — 10 个全预存在环境（sspa 包/R/FELLA），**0 回归** |
| **一致性**（生产 cascade vs 实验脚本 corrected claims） | 测试断言**逐字节相同**（确定性 `apply_cascade` 纯函数） |
| **端到端 live**（`v4_bench_eval.py` 5 sub6 任务） | **5/5 跑通 / 0 错误**；1 任务触发 cascade：iter-0 unsupported=6 → iter-1 **unsupported=0 / uv=0**、supported 保留、final 选 iter-1，与 112-task 实验行为一致 |

## caveat

- B 的 1 个 task 被 MiniMax 内容审核拒答（422），故 B pathway 分母 111。
- A 的 weave narrative 可能漂移 pathway 措辞（top1 含该噪声仍 +1 task；topk 不受影响）。

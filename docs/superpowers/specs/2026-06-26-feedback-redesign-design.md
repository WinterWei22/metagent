# Feedback 机制重构 — 设计 spec

- 日期：`2026-06-26`
- 分支：`claude/stupefied-shtern-43fb20`
- 前置：verifier 多源重构（已完成，`docs/decisions/2026-06-25_verifier_multisource_refactor.md`）
- 背景调研：OriGene Critic Agent + GeneAgent self-verification cascade

---

## 0. Context（为什么）

verifier 多源重构跑通后，对 112-task live run 做了 feedback 收益分析，结论是**当前 feedback 净破坏质量**：

- claim-level：feedback 删了 192 条 claim，其中 SUPPORTED 删最多（−101），UV% 反升（5.5→6.0）
- 机制根因（代码 + 数据三重证据）：
  1. **重写式**：feedback 让 LLM 重出整个 `claims[]`（41/61 触发 task 引入 iter-0 没有的新通路）
  2. **不保护 supported**：`_resolve_default_feedback_builder` 只 forward contradicted/unsupported/UV/dropped，**完全不展示已 SUPPORTED 的 claim**，LLM 失去正确答案锚点
  3. 标志案例：Tyrosine task iter-0 = 8/8 全对，被 1 个 INSUFFICIENT 触发 feedback 后变 0 supported + 4 UV，还编出 Flavonoid/alpha-Linolenic 等无关通路
- 收益边界：初稿差（sup~3、坏占比 35%）→ feedback 正收益；初稿好（sup~6、坏占比 22%）→ 破坏。oracle 完美 gating 天花板也只 +30 supported（+4.3%）

**结论**：当前 feedback 太简陋。本 spec 不优化当前实现，而是**重构 feedback 机制并评估能否带来真实收益**。

---

## 1. 目标 + 成功标准（已与用户确认）

**主指标：pathway 预测准确率**（task 真实目标）—— top-1 semantic match / hit@k / MRR。
**辅指标：claim 质量** —— 尤其 contradicted 减少（"过程更干净"）+ supported 不被破坏。

**成功定义**：重构后的 feedback（主力 A）在 paired 对比中，pathway accuracy **不退且最好能升**，同时 claim 层面不再出现"破坏 supported"（A 机制上根除）。

**评估规模**：先小规模验证方向 —— 复用已跑的 112 iter-0，在 20-30 个**触发过 feedback 的** task 上 paired 对比 4 臂，只重跑 feedback 轮（~$1-2）。方向为正再扩全量。

---

## 2. 三个 feedback 策略设计

所有策略的 feedback 轮**不重新调用富集工具**（复用 iter-0 的 `enrichment_carriers`），只做"基于已有证据修正"——这与当前 prompt rule 6（"DO NOT research further"）一致，且保证 paired 可比 + 低成本。

### A. 确定性 cascade（主力，GeneAgent 式）

feedback 轮不让 LLM 自由重写 claims。系统按 verdict 确定性处理 iter-0 的 verified claims：

| iter-0 verdict | 系统动作 |
|---|---|
| SUPPORTED | **保留**（原样，不进 LLM） |
| CONTRADICTED | **替换**为该 claim 的 `correction`（多源池 top-1 pathway，Task 8/D3 已填充） |
| UNSUPPORTED | **删除** |
| INSUFFICIENT_EVIDENCE | **保留**（OriGene unsure→keep，不动） |
| UNVERIFIABLE_V0 | **删除**（范式外，无法修） |

产出 `corrected_claims`（系统确定）。然后 **1 次受限 LLM call**：给 LLM `corrected_claims`，要求"只写一段连贯的 `narrative_text` 描述这些 claim，**不得增删或修改任何 claim**"，输出 `{narrative_text, claims: corrected_claims}`。

- claims 完全由系统控制 → 机制上根除"破坏 supported"+"引入新通路"
- LLM 只负责 narrative 织合（1 次 call，不调工具）
- 需要新 prompt：`feedback_narrative_weave_prompt`（"基于给定 claims 写 narrative，不增删"）

### B. 锚定重写（对照臂）

改进现有 `build_feedback_message`，仍让 LLM 重写（narrative + claims），但：
- feedback prompt **新增正面锚点**：明确列出"以下 N 个 claim 已 SUPPORTED，原样保留"
- contradicted/unsupported 附 `correction`（top-1 alternative）建议
- **触发 gating**：只对 CONTRADICTED 反馈，INSUFFICIENT 不反馈（unsure→keep）
- 保留 LLM 灵活性（可能真在 pathway 上提升），但依赖 LLM 守规则

### C. gating-only（ablation，后置）

不改机制，只加触发门槛：初稿质量差（supported 占比 < 阈值 或 有 contradicted）才触发当前 feedback。作为 ablation 证明"光 gating 不够、需要机制改造"。本 spec 实现接口但默认不跑全量。

---

## 3. 实验设计（核心）

### 4 臂 paired 对比（同 task，复用 iter-0）

| 臂 | feedback 轮做法 | 数据来源 |
|---|---|---|
| no-feedback | 直接用 iter-0 | trace 已有 |
| 现状（baseline） | iter-0 + 当前 feedback | live run 的 final（已有） |
| **A** | iter-0 + 确定性 cascade | 新跑（1 LLM call/task） |
| **B** | iter-0 + 锚定重写 | 新跑（1 LLM 重写 call/task，不调工具） |

### task 选取（20-30）

从 **61 个触发过 feedback 的 task** 中选 20-30，覆盖：
- 初稿好（live run supported 降组，~39 个里选）
- 初稿差（升组 + 持平组，~22 个里选）
- 两个 stratum（sub6 + hmdb_ramp）
- 目的：看 A/B 能否在"初稿好"上不退（根因对症）、在"初稿差"上提升

### 复用 iter-0 的技术路径

从每个 trace 的 `iterations[0]` 取 react_result（含 `final_claims` + `enrichment_carriers` + `final_narrative_text`）+ iter-0 verification verdict。重建 `SubsixSourceReport`（v4 adapter）。对 A/B 策略各跑一次 feedback 轮，产出新 narrative + claims，再过 verifier 出 verdict。

---

## 4. 评估指标 + 方法

**主：pathway accuracy** —— 对每臂的最终 narrative 跑 `full344_pathway_scorecard` 的 semantic match（top-1 / hit@3 / MRR），对比 ground-truth `perturbed_pathway`。

**辅：claim 质量** —— 每臂 verdict 分布（supported / contradicted / unsupported / UV / insufficient）；重点看 contradicted 是否减少、supported 是否被破坏。

**paired 统计** —— 同 task 跨臂对比，报告每臂相对 no-feedback 的 Δ（pathway accuracy + supported + contradicted）。feedback 实验方差大，小规模先看方向（符号 + 量级），不追求显著性。

---

## 5. 模块 / 文件结构

| 文件 | 责任 |
|---|---|
| `concord/agent/feedback_strategies.py`（新） | 3 策略统一接口 `build_feedback(strategy, iter0_verdict, source_report) -> FeedbackAction`（A: direct_claims + weave；B: prompt；C: gated prompt） |
| `prompts/agent/feedback_narrative_weave_prompt.md`（新） | A 策略的"基于给定 claims 写 narrative，不增删"prompt |
| `prompts/agent/sub6b_react_feedback_prompt_anchored.md`（新） | B 策略的锚定重写 prompt（加 supported 锚点 + top-1 建议） |
| `scripts/metagent/feedback_ab_eval.py`（新） | 复用 iter-0 + 跑 4 臂 + 出 pathway accuracy + claim 对比 |
| `reports/reports_v3/2026-06-26_feedback_ab.md`（输出） | paired 对比结果 |

**不改 production verifier/concord 核心逻辑**（feedback_strategies 是新模块；实验脚本独立）。若需在 react_runner 接 A/B builder，走 ⚠ `[concord-modify-warning]`，但优先在实验脚本里注入，不动 production。

---

## 6. 风险 / 限制

| 风险 | 缓解 |
|---|---|
| A 的 narrative 织合生硬 → pathway 提取受影响 | weave prompt 要求 narrative 覆盖所有 claim 的 pathway name；scorecard 同时看 claims 和 narrative |
| 复用 iter-0 不等于真实多轮（真实 feedback 轮 LLM 可调工具） | 明确范围：本实验测"基于固定证据的修正策略"，与 rule 6 一致；工具重调留全量阶段 |
| 20-30 task 方差大 → 方向不清 | 选取覆盖升/降/持平；paired 看符号；方向正再全量多 seed |
| top-1 correction 本身可能错（多源池 top-1 ≠ ground truth） | A 的 contradicted 替换有上限风险；评估时单独看"替换后是否命中 GT" |

---

## 7. 验收标准

- A/B/现状/no-feedback 4 臂在 20-30 task 上跑通，产出 paired 对比表
- 主指标 pathway accuracy 每臂有数；辅指标 claim 分布每臂有数
- 明确结论：A 是否在 pathway accuracy 上不退/提升 + claim 层面不破坏 supported
- 方向为正 → 触发全量 + 多 seed 的后续 spec；为负 → 记录"机制改造仍不够"的诚实结论

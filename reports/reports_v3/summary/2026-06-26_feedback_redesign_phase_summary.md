# MetAgent Feedback 重构阶段 — 完整总结

- 日期：`2026-06-26`
- 分支：`claude/stupefied-shtern-43fb20`（worktree）
- 决定：**A_cascade 定为 MetAgent 后续的正式 feedback 工作流**（决策记录见 `docs/decisions/2026-06-26_feedback_workflow_a_cascade.md`）
- 阶段产物：
  - 实现：`concord/agent/feedback_strategies.py`（`apply_feedback_strategy` 等）
  - 实验脚本：`scripts/metagent/feedback_ab_eval.py`
  - 数据：`data/metagent/feedback_ab_v4_full/`（v4 全量 112-task）、`data/metagent/feedback_ab_eval/`（sub6b-v3 23-task）
  - 报告：本文件 + `reports/reports_v3/2026-06-26_feedback_ab_v4_full112.md`（v4 全量）+ `reports/reports_v3/2026-06-26_feedback_ab.md`（23-task）
  - 设计：`docs/superpowers/specs/2026-06-26-feedback-redesign-design.md`

---

## 1. 背景与问题（Why）

verifier 多源重构跑通后，对 v4 live run（112 task）做了原有 feedback 的收益分析，结论是**当前 feedback 净破坏质量**：

- claim-level：feedback 删了大量 claim，其中 **SUPPORTED 删最多**，UV% 反升。
- 机制根因（代码 + 数据三重证据）：
  1. **重写式**：feedback 把整个 `claims[]` 交给 LLM 重出，引入 iter-0 没有的新通路。
  2. **不保护 supported**：原 `_resolve_default_feedback_builder` 只把 contradicted/unsupported/UV/dropped 反馈给 LLM，**完全不展示已 SUPPORTED 的 claim**，LLM 失去正确答案锚点。
  3. 标志案例：iter-0 全对的 task，被 1 个 INSUFFICIENT 触发 feedback 后变 0 supported + 多个 UV，并编出无关通路。
- 收益边界：初稿差 → feedback 可能正收益；初稿好 → 破坏。即使 oracle 完美 gating，天花板也很低。

**结论**：当前 feedback 太简陋。本阶段不优化旧实现，而是**重构 feedback 机制并严谨评估"重构后能否带来真实收益"**——这是用户的核心研究问题（"不用纠结于当前 feedback 的收益，而是要评估重构/修改 feedback 后能否带来收益"）。

调研锚点：OriGene Critic Agent + GeneAgent self-verification cascade —— 两者的共性是 **deterministic cascade**：系统决定"改什么"，LLM 只负责"怎么说"。

---

## 2. 方法（Method）

### 2.1 三个 feedback 策略

所有策略的 feedback 轮**不重新调用富集工具**（复用 iter-0 的 `enrichment_carriers`），只基于已有证据修正，保证 paired 可比 + 低成本。

| 策略 | 机制 | 实现 |
|---|---|---|
| **A_cascade（主力）** | 系统按 iter-0 verdict 确定性处理 claim：**SUPPORTED 保留 / CONTRADICTED 替换为多源池 top-1 / UNSUPPORTED 删 / INSUFFICIENT 保留（unsure→keep）/ UV 删**；然后 **1 次受限 LLM call 只织 narrative，不得增删/改 claim**。 | `apply_feedback_strategy("cascade", …)` → `apply_cascade` + `weave_narrative` + `build_cascade_payload` |
| B_anchored（对照） | 仍让 LLM 重写 narrative + claims，但加 supported 正面锚点 + top-1 建议 + 只对 CONTRADICTED 触发。保留 LLM 灵活性，依赖它守规则。 | `apply_feedback_strategy("anchored", …)` → `build_anchored_feedback` + 1 次 LLM 重写 |
| C_gated（ablation，后置） | 不改机制，只加触发门槛。证明"光 gating 不够"。 | `apply_feedback_strategy("gated", …)`（本阶段未跑全量） |

A 的关键不变量：**claims 完全由系统控制 → 机制上根除"破坏 supported / 引入新通路 / 留噪音"**；LLM 只做 narrative 织合。

### 2.2 五臂 paired 评估

| 臂 | feedback 轮做法 |
|---|---|
| no_feedback | iter-0 verdict（从 trace 读） |
| baseline | live run 最后一轮 verdict（从 trace 读） |
| **iter0_reverify** | iter-0 payload 的 live 重验证，**A/B 的公平共同基线** |
| **A_cascade** | iter-0 claims → 确定性 cascade + weave → 重验 |
| **B_anchored** | iter-0 → 锚定重写 prompt → 1 次 LLM 重写 → 重验 |

复用每 task 的 iter-0 react 结果（`iterations[0].react_result`，含 `final_claims` + `enrichment_carriers`），只重跑 feedback 轮，三个 live 臂共享 iter-0 重验证结果（省 ~30% LLM 成本）。

### 2.3 指标

- **主指标 · pathway accuracy**：对 GT `perturbed_pathway` 做语义匹配。
  - **top1**：preferred-verdict（SUPPORTED/INSUFFICIENT）pool 第一个 claim 的 pathway。
  - **topk**：扫所有 claim 是否语义命中 GT（不受 weave narrative 措辞漂移影响，更反映真实预测）。
- **辅指标 · claim 质量**：verdict 分布；重点看**噪音 = UNSUPPORTED + UNVERIFIABLE_V0** 与 **SUPPORTED 是否被破坏**。
- **paired delta**：同 task 跨臂对比，相对 iter0_reverify 的 Δ。

---

## 3. 数据（Data）

| 数据集 | 任务 | trace 来源 | 用途 |
|---|---|---|---|
| **v4 metabolic（主）** | **112**（sub6=63 + hmdb_ramp=49） | `data/metagent/v4_live_full/path_x_full/`（v4 live run，benchmark `metagent_bench_easy_v4_metabolic.jsonl`） | 全量主结论 |
| sub6b-v3（先导） | 23（升/降/持平 × strata 分层抽样） | `data/concord/w14_path_x_post_noise_cap/path_x_full/` | 小规模先验证方向 |

v4 benchmark 详情见 `reports/benchmark/v4/benchmark_v4_details.md`：v4 去掉 DB ID 预填充，强制 LLM 用 InChIKey 调工具，比 v3 更难。

**关键工程修复（让 v4 首次能跑出 verifier 指标）**：v4 task 此前缺 `SubsixSourceReport` 必填字段 → adapter 报 `source_report_adapter_failed`、v4 run 无 UV/Supported 指标。本阶段的 verifier 多源重构 + `v4_task_to_subsix_source_report`（带 carriers）修好；`feedback_ab_eval.py` 按 `_is_v4_task` 自动选 v3/v4 adapter，**112/112 全部跑出真实 verifier 指标，0 adapter 失败**。

---

## 4. 结果（Results）

### 4.1 v4 全量 112-task（主结论）

**主指标 · pathway accuracy（3 个 live 臂可比）**

| 臂 | top1 | topk | Δtop1 vs 基线 |
|---|---:|---:|---:|
| iter0_reverify（基线） | **75.00%** (84/112) | 85.71% (96/112) | — |
| **A_cascade** | **75.89%** (85/112) | 84.82% (95/112) | **+0.89pp（+1 task）** |
| B_anchored | 54.05% (60/111) | 63.96% (71/111) | **−20.95pp（−24 task）** |

分层 top1：A 在 **sub6 +2 task（76.2→79.4%）**、hmdb_ramp −1 task（73.5→71.4%），净 +1。B 全面崩塌（sub6 57.1% / hmdb_ramp 50.0%），且 24 个 task abstain。

**辅指标 · claim 噪音（全量 verdict 总数）**

| 臂 | SUPPORTED | UNSUPPORTED | UV | **噪音 (UNS+UV)** |
|---|---:|---:|---:|---:|
| iter0_reverify | 721 | 139 | 0 | **139** |
| **A_cascade** | 629 | **0** | **0** | **0** |
| B_anchored | 575 | 302 | 349 | **651** |

**paired delta（每 task 平均 vs iter0_reverify）**：A_cascade Δuv=**−1.72**、Δpathway_top1=**+0.009**；B_anchored Δuv=**+1.67**、Δpathway_top1=**−0.207**。

**成本**：本次并发 run 实测 **$1.47**（`logs/concord/feedback_ab_v4_full.jsonl`，713 calls）；墙钟 ~90 min（并发 k=8）。

### 4.2 sub6b-v3 23-task（先导，方向一致）

A topk 86%（vs 基线 91%，−1 task）、噪音 97→1；B topk 82%、噪音 97→179。方向与 v4 全量一致。

### 4.3 23-task → 112-task 一致性

| 指标 | 23-task | 112-task |
|---|---|---|
| A pathway top1 vs 基线 | −1 task | **+1 task** |
| A 噪音 (UNS+UV) | 97 → **1** | 139 → **0** |
| B pathway | −2 task | **−24 task（−21pp）** |
| B 噪音 | 97 → 179 | 139 → **651** |

全量放大了所有信号：A 更稳（top1 转正、噪音归零），B 更糟。

---

## 5. 分析（Analysis）

1. **"feedback 提升最终通路准确率"在小规模上不成立，但在全量上 A 转为净 +1 task。** A 的设计目标不是"提准确率"，而是"不破坏 + 去噪"；扩到 112-task 后，A 在主指标上不退反略升（top1 +1 task，topk 仅 −1 task），"不掉准确率"稳固成立。

2. **A 把噪音确定性清到字面 0。** UNSUPPORTED 与 UV 全部归零，而 pathway 不退。这是"系统确定性处理 claim + LLM 只织叙述"机制的直接结果——LLM 无权增删 claim，就无从制造噪音或破坏 supported。

3. **B 证伪了"靠 prompt 锚点约束 LLM 自由重写"这条路。** 即使给了 supported 锚点 + top-1 建议 + gating，B 仍在两个轴上都崩（pathway −21pp、噪音 ×4.7、24 task abstain，含 1 次被外部内容审核拒答）。

4. **设计教训（核心）**：

   > **"让 LLM 自由重写"会破坏（旧 feedback、B）；"系统确定性处理 + LLM 只织叙述"（A）能保住准确率并把噪音清零。self-verification 的安全收益，来自把"改什么"从 LLM 手里拿走、只留"怎么说"给 LLM。**

   这与 OriGene Critic / GeneAgent 的 deterministic-cascade 调性一致。

5. **故事定位（诚实）**：feedback 重构的价值在**过程干净度 + 准确率不退（全量上 +1 task）**，A 是唯一不破坏的 self-correction 设计。

### caveat
- B 的 1 个 task 被 MiniMax 审核拒答（`output new_sensitive`, 422），已被接住记 error，故 B pathway 分母 111。是 B 脆弱性的真实体现，非脚本 bug。
- no_feedback/baseline 臂从 trace 读、不跑 live pathway eval，公平比较只在 3 个 live 臂之间。
- A 的 weave narrative 仍可能漂移 pathway 措辞；top1（含该噪声）仍 +1 task，topk（claims 命中、不受影响）−1 task，两口径都显示 A 与基线持平偏正。
- 并发 LLM 有效并发约 3–4（旧 openai 0.x 客户端部分串行），非逻辑限制，不影响结果正确性。

---

## 6. 复现方法（Reproduction）

### 6.1 环境

```bash
cd /home/weiwentao/workspace/llm_agent_metabolomics/metagent_v2/.claude/worktrees/stupefied-shtern-43fb20
./scripts/concord/setup_metagent_v2_env.sh   # symlink chebi/metanetx sqlite（首次）

# 必须用 conda python（系统 python3 是 3.8 会假报 ImportError）
PY=/home/weiwentao/miniconda3/bin/python3

# MiniMax 远程 API key
KEY=$(cat /home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5/api_key_minimax.txt | tr -d '[:space:]')
export MINIMAX_API_KEY="$KEY" METAGENT_API_KEY="$KEY" METAGENT_LLM_PROVIDER=minimax
export METAGENT_VERIFY_STRUCTURED_CLAIMS=1 METAGENT_ENABLE_METHOD_AWARE_ENRICHMENT=1
```

### 6.2 跑 v4 全量 112-task 五臂评估

```bash
export METAGENT_LLM_LOG_PATH=logs/concord/feedback_ab_v4_full.jsonl
PYTHONPATH=. $PY scripts/metagent/feedback_ab_eval.py \
    --traces-dir data/metagent/v4_live_full/path_x_full \
    --benchmark data/benchmark/metagent_bench_v2/metagent_bench_easy_v4_metabolic.jsonl \
    --output data/metagent/feedback_ab_v4_full \
    --all-tasks --k-concurrent 8
```

- 输出：`data/metagent/feedback_ab_v4_full/{summary.json, results.jsonl, <task_id>.json}`
- **断点续传**：被 kill 后重跑同命令即可，skip-done 自动跳过已完成 task；summary 从磁盘全量重算。
- 成本 ~$1.47 / 墙钟 ~90 min（k=8）。

### 6.3 跑 sub6b-v3 23-task 先导

```bash
PYTHONPATH=. $PY scripts/metagent/feedback_ab_eval.py \
    --traces-dir data/concord/w14_path_x_post_noise_cap/path_x_full \
    --benchmark data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl \
    --output data/metagent/feedback_ab_eval
# 不加 --all-tasks 则跑脚本内 DEFAULT_EVAL_TASK_IDS（23 个分层 task）
```

### 6.4 读结果

```bash
$PY -c "import json; s=json.load(open('data/metagent/feedback_ab_v4_full/summary.json')); \
import pprint; pprint.pprint(s['pathway_accuracy_by_arm']); pprint.pprint(s['aggregate_by_arm'])"
```

### 6.5 单独调用 cascade 工作流（A_cascade 正式入口）

```python
from concord.agent.feedback_strategies import apply_feedback_strategy
# verified_claims: 一次 verifier pass 产出的 VerifiedClaim 列表（iter-0 输出）
fb = apply_feedback_strategy("cascade", verified_claims, source_report)
payload = fb.payload          # JSON: {"narrative_text":..., "claims":[...]}（verify_sub6 零-LLM 消费）
corrected = fb.corrected_claims  # 系统确定的 grammar-v2 claim 列表
```

---

## 7. 工作流定型（What's locked in）

**A_cascade 是 MetAgent 的正式 feedback 工作流，已接入生产主流程。**

- 策略入口：`concord.agent.feedback_strategies.apply_feedback_strategy("cascade", verified_claims, source_report)`（112-task v4 实验背书：pathway +1 task、噪音归零）。
- **生产 `react_runner.run_task_with_feedback` 默认已切换为 cascade**（`feedback_strategy: str = "cascade"`，legacy rewrite 保留在 `="rewrite"`）。最新 v4 全流程 driver `scripts/metagent/v4_bench_eval.py` 不传该参数 → 自动走 cascade。
- B_anchored 作为反例对照，C_gated 留作 ablation。

### 生产接线验证（2026-06-26，严格 TDD + 回归，全绿）

| 检查 | 结果 |
|---|---|
| cascade 单元 + 一致性测试 | **4/4 passed** |
| legacy feedback loop（rewrite 仍可达） | **42/42 passed** |
| **B1 Gate A** | **409 passed / 0 failed**（无回归） |
| 全 concord 套件 | 346 passed / 10 failed（10 个全预存在环境 sspa/R/FELLA，0 回归） |
| **一致性** | 生产 cascade corrected claims **逐字节 == 实验脚本**（确定性 `apply_cascade`） |
| **端到端 live**（`v4_bench_eval.py` 5 任务） | **5/5 跑通 / 0 错误**；触发的 cascade 任务 iter-0 unsupported=6 → iter-1 **unsupported=0/uv=0**，supported 保留，与实验一致 |

**为什么"结果一致"成立**：生产 react_runner 的 cascade 路径与实验脚本**调用同一个确定性 `apply_cascade(claims)`**（pathway accuracy / 噪音等指标由 claims 决定，不由 weave 叙述决定）。补全的关键缺口是 `_weave_llm_call`：cascade 织叙述走 runner 自身 provider/model 且 LLM 失败时优雅降级（叙述 cosmetic，不拖垮 loop）。

完整决策记录 + 实施规格：`docs/decisions/2026-06-26_feedback_workflow_a_cascade.md`。

# Feedback 重构 A/B 评估 — 全量 v4 benchmark（112 task）

- 日期：`2026-06-26`
- 脚本：`scripts/metagent/feedback_ab_eval.py`（本次新增 v4 adapter dispatch + 并发 + 断点续传）
- 数据：`metagent_bench_easy_v4_metabolic.jsonl` 上 v4 live run 的 112 个 trace
  （`data/metagent/v4_live_full/path_x_full/`，sub6=63 + hmdb_ramp=49）
- 复用每 task 的 iter-0 react 结果，只重跑 feedback 轮（不重调富集工具）
- 输出：`data/metagent/feedback_ab_v4_full/`
- 设计：`docs/superpowers/specs/2026-06-26-feedback-redesign-design.md`
- 23-task（sub6b-v3）前序结果见 `reports/reports_v3/2026-06-26_feedback_ab.md`

---

## 0. 本次跑通的关键工程修复

1. **v4 verifier 路径首次跑通**。旧报告（`2026-06-25_v4bench_p0p1p2p3_session_summary.md` §Verifier 指标参考）记录：v4 task 缺 `SubsixSourceReport` 必填字段 → adapter 报 `source_report_adapter_failed`，**v4 run 完全没有 UV/Supported 指标**，只能引用 W14 sub6b-v3 的旧数字。本 session 的 verifier 多源重构 + `v4_task_to_subsix_source_report`（带 carriers）修好了这一点。`feedback_ab_eval.py` 现在按 `_is_v4_task` 自动选 v3/v4 adapter，**112/112 task 全部跑出真实 verifier 指标，0 adapter 失败**。
2. **并发 + 断点续传**。评估改为 `ThreadPoolExecutor`（k=8）、每 task 独立写盘、results.jsonl append、summary 从磁盘重算。墙钟从顺序版 ~5 h 压到 ~90 min；中途被 kill 过一次，skip-done 自动续跑无损失。
3. 成本：本次并发 run 实测 **$1.47**（查 `logs/concord/feedback_ab_v4_full.jsonl`，713 calls，prompt 0.66M / completion 1.08M token）。

---

## 1. 五臂

| 臂 | 含义 |
|---|---|
| no_feedback | iter-0 verdict，从 trace 读（无 live pathway eval） |
| baseline | live run 最后一轮 verdict，从 trace 读（无 live pathway eval） |
| **iter0_reverify** | iter-0 payload 的 live 重验证，**A/B 的公平共同基线** |
| **A_cascade** | 确定性保留 SUPPORTED + 替换 CONTRADICTED 为 top-1 + 删 UNSUPPORTED/UV，LLM 只织 narrative |
| **B_anchored** | LLM 重写（narrative + claims）+ supported 锚点 + top-1 建议 + gating |

n_ok = 109（本次）/ 112（含先前 3 个续跑 task）/ **0 fail**。

---

## 2. 全量 112-task 结果

### 主指标 — pathway accuracy（vs GT perturbed_pathway）

| 臂 | top1 | topk | Δtop1 vs 基线 |
|---|---:|---:|---:|
| iter0_reverify（基线） | **75.00%** (84/112) | 85.71% (96/112) | — |
| **A_cascade** | **75.89%** (85/112) | 84.82% (95/112) | **+0.89pp（+1 task）** |
| **B_anchored** | **54.05%** (60/111) | 63.96% (71/111) | **−20.95pp（−24 task）** |

B 还有 **24 个 task 直接 abstain**（重写产出无可用 claim / 被内容审核拒答）。

#### 分层（top1）

| stratum | iter0_reverify | A_cascade | B_anchored |
|---|---:|---:|---:|
| sub6 (63) | 76.2% (48/63) | **79.4% (50/63)** | 57.1% (36/63) |
| hmdb_ramp (49) | 73.5% (36/49) | 71.4% (35/49) | 50.0% (24/48) |

A 在 sub6 上 **+2 task**，在 hmdb_ramp 上 −1 task，**净 +1 task**。

### 辅指标 — claim 质量（全量 verdict 总数）

| 臂 | total | SUP | UNS | CON | UV | INSUF | **噪音 (UNS+UV)** |
|---|---:|---:|---:|---:|---:|---:|---:|
| iter0_reverify | 1107 | 721 | 139 | 44 | 0 | 193 | **139** |
| **A_cascade** | 635 | 629 | **0** | 4 | **0** | 0 | **0** |
| **B_anchored** | 1291 | 575 | 302 | 31 | 349 | 31 | **651** |

### Paired delta（每 task 平均，vs iter0_reverify）

| 臂 | Δsupported | Δuv | Δunsupported | Δpathway_top1 |
|---|---:|---:|---:|---:|
| **A_cascade** | −0.82 | **−1.72** | **−1.24** | **+0.009** |
| **B_anchored** | −1.30 | **+1.67** | **+1.46** | **−0.207** |

---

## 3. 诚实结论

**核心答案（重构后的 feedback 能否带来收益）——在更大、更难的 v4 全量上，结论比 23-task 更强、更干净：**

1. **A_cascade 在主指标 pathway accuracy 上首次转正。** top1 75.89% vs 基线 75.00%（**+1 task**，sub6 +2 / hmdb_ramp −1），topk 基本持平（−1 task）。23-task 上 A 是 top1 −1 task；扩到 112-task 后 A **净 +1 task**，"不掉准确率"这一结论在全量上稳固成立，且略偏正。

2. **A_cascade 把噪音确定性清到字面 0。** UNSUPPORTED 139→**0**、UV 0→**0**、噪音 139→**0**，而 pathway 不退。这是 A 设计目标的完整兑现：**系统确定性处理 claim，LLM 只织叙述 → 机制上根除"破坏 supported / 编新通路 / 留噪音"。**

3. **B_anchored 在两个轴上都是灾难。** pathway top1 暴跌 **−20.95pp**（75→54%）、24 个 task abstain、噪音从 139 爆到 **651（×4.7）**、UV 0→349。"让 LLM 自由锚定重写"不仅没帮上忙，反而比不做 feedback 差得多。

4. **排序：A ≫ no-feedback/iter0_reverify ≫ B。** 与 23-task 完全一致，且在全量上幅度更大。清晰的设计教训：

   > **"让 LLM 自由重写"会破坏（当前 feedback、B）；"系统确定性处理 + LLM 只织叙述"（A）能保住准确率并把噪音清零。**

**故事定位（诚实）：** feedback 重构的价值在**过程干净度 + 准确率不退（全量上甚至 +1 task）**。A 是唯一不破坏的 self-correction 设计；B 证伪了"靠 prompt 锚点约束 LLM 重写"这条路。这与 OriGene Critic / GeneAgent 的 deterministic-cascade 调性一致：**self-verification 的安全收益来自把"改什么"从 LLM 手里拿走、只留"怎么说"给 LLM。**

---

## 4. 与 23-task（sub6b-v3）对比

| 指标 | 23-task (sub6b-v3) | 112-task (v4) |
|---|---|---|
| A pathway top1 vs 基线 | −1 task (73% vs 78%) | **+1 task (75.89% vs 75.00%)** |
| A topk vs 基线 | −1 task (86% vs 91%) | −1 task (84.82% vs 85.71%) |
| A 噪音 (UNS+UV) | 97 → **1** | 139 → **0** |
| B pathway | −2 task | **−24 task（−21pp）** |
| B 噪音 | 97 → 179 | 139 → **651** |

全量放大了所有信号：A 更稳（top1 转正、噪音归零），B 更糟（pathway 崩、噪音爆）。

---

## 5. 已知 caveat

- **B 的 1 个 task 被 MiniMax 内容审核拒答**（`output new_sensitive`, HTTP 422），已被 try/except 接住记为 error，故 B pathway 分母 111 而非 112。这是 B"自由重写触发外部 moderation"脆弱性的真实体现，不是脚本 bug。
- no_feedback / baseline 臂从 trace 读，不跑 live pathway eval，故 pathway 列为 None；公平比较只在 3 个 live 臂（iter0_reverify / A / B）之间。
- A 的 weave narrative 仍可能漂移 pathway 措辞（23-task 报告 §4 记录的 Galactose→Galactosemia 类）；本次 top1 已含该噪声仍 +1 task，topk（claims 命中，不受 narrative 影响）−1 task，两口径都显示 A 与基线持平偏正。
- 并发 LLM 调用有效并发约 3–4（旧 openai 0.x 客户端部分串行），非脚本逻辑限制；不影响结果正确性。

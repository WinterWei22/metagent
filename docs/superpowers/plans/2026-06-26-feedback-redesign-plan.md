# Feedback 机制重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 实现 3 个 feedback 策略(A 确定性 cascade / B 锚定重写 / C gating)并在 20-30 个触发过 feedback 的 task 上 paired 对比 4 臂,评估"重构后 feedback 能否带来收益"(主指标 pathway 准确率,辅 claim 质量)。

**Architecture:** 新模块 `concord/agent/feedback_strategies.py` 实现 3 策略统一接口;A 把 iter-0 verified claims 按 verdict 确定性处理成 corrected grammar-v2 claims,LLM 只织 narrative;实验脚本复用已跑的 112 iter-0,只重跑 feedback 轮。不改 production verifier/concord 核心逻辑。

**Tech Stack:** Python 3.13, pydantic v2, pytest, MiniMax 远程 API。

## Global Constraints

- 中文对话,英文代码/标识符。模型名 **MetAgent**。
- **不改 production verifier/concord 核心逻辑**:feedback_strategies 是新模块,策略在实验脚本里注入。若必须改 `react_runner` 接策略 → ⚠ `[concord-modify-warning]`;优先避免。
- 不碰 B1-core ❌ helper(`claim_extractor.extract_claims_from_json` / `feedback_hints.build_feedback_message` / `verifier/agent.py:_extract_classify`)。
- Gate A 不退:`PYTHONPATH=. python3 -m pytest tests/test_verifier/ tests/test_d4_feedback_dispatcher.py tests/test_grammar_validate.py tests/test_classifier_collapse.py tests/test_runner_response_format.py tests/test_prompt_banned_sync.py -q` → 408+ pass / 0 fail。
- 严格 TDD:先 RED 再 GREEN,独立 commit。
- `python3` = conda 3.13;pytest 用 `PYTHONPATH=. python3 -m pytest`。
- MiniMax key: `tr -d ' \n\r' < /home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5/api_key_minimax.txt`;实验设 `METAGENT_VERIFY_STRUCTURED_CLAIMS=1` + `METAGENT_ENABLE_METHOD_AWARE_ENRICHMENT=1`;cost 查 `logs/llm_calls.jsonl`,**禁说 $0**。
- 已跑 iter-0 数据:`data/metagent/v4_live_full/path_x_full/*.json`(112 trace,顶层 `iterations[0]` = iter-0)。
- subagent 按难易用 **sonnet 4.6**(逻辑/集成)或 **haiku 4.5**(纯函数/prompt)。
- 设计依据:`docs/superpowers/specs/2026-06-26-feedback-redesign-design.md`。

## 关键数据结构(已确认)

- `VerifiedClaim`(verifier/schemas.py): `claim_text` / `claim_type:ClaimType` / `claim_subtype` / `verdict:ClaimVerdict` / `correction:str|None`(CONTRADICTED 时 = 多源池 top-1) / `extracted_fields:ClaimExtractedFields`(含 `pathway_name`/`pathway_id`) / `subject`。
- grammar-v2 claim dict 形状(verify_sub6 zero-LLM 提取所需): `{"grammar": "<shape>", "claim_text": str, "pathway_name": str, "pathway_id": str, ...}`。verify_sub6 入口 `llm_output: str` = JSON `{"narrative_text": str, "claims": [...]}`。
- `ClaimVerdict`: SUPPORTED / CONTRADICTED / UNSUPPORTED / UNVERIFIABLE_V0 / INSUFFICIENT_EVIDENCE / NEEDS_HUMAN_REVIEW。

---

## File Structure

| 文件 | 责任 | task |
|---|---|---|
| `concord/agent/feedback_strategies.py`(新) | 3 策略 + 统一接口 | T1,T4,T5 |
| `tests/concord/test_feedback_strategies.py`(新) | 策略单测 | T1,T4,T5 |
| `prompts/agent/feedback_narrative_weave_prompt.md`(新) | A 织 narrative prompt | T3 |
| `prompts/agent/sub6b_react_feedback_prompt_anchored.md`(新) | B 锚定重写 prompt | T4 |
| `scripts/metagent/feedback_ab_eval.py`(新) | 复用 iter-0 + 4 臂 + 评估 | T6,T7 |
| `reports/reports_v3/2026-06-26_feedback_ab.md`(输出) | paired 对比结果 | T7 |

---

### Task 1: A cascade 确定性 claim 处理

**Files:** Create `concord/agent/feedback_strategies.py`; Test `tests/concord/test_feedback_strategies.py`

**Interfaces:**
- Produces: `apply_cascade(verified_claims: list[VerifiedClaim]) -> list[dict]` — 按 verdict 把 iter-0 claims 处理成 corrected grammar-v2 claim dicts:
  - SUPPORTED → 保留(从 claim 重建 grammar-v2 dict)
  - CONTRADICTED → 保留但 pathway_name 替换为 `claim.correction`(top-1);correction 为空则降级删除
  - UNSUPPORTED → 删
  - UNVERIFIABLE_V0 → 删
  - INSUFFICIENT_EVIDENCE → 保留
- 每个保留 claim 重建为 `{"grammar": <claim_subtype或claim_type映射>, "claim_text": ..., "pathway_name": ..., "pathway_id": ...}`(grammar-v2 形状,能被 verify_sub6 zero-LLM 提取)。

**建议模型:** sonnet 4.6(verdict 映射 + grammar-v2 重建需读 schema)

- [ ] **Step 1: RED** — 写测试: 构造含 5 种 verdict 的 VerifiedClaim 列表,断言 apply_cascade 后:supported/insufficient 保留、unsupported/uv 删、contradicted 的 pathway_name == correction。先确认 verify_sub6 提取 grammar-v2 dict 需要哪些字段(读 `verifier/claim_extractor.py:extract_claims_from_json`),测试断言重建 dict 含这些字段。
- [ ] **Step 2: 确认 FAIL**(函数不存在)
- [ ] **Step 3: GREEN** — 实现 apply_cascade + grammar-v2 重建 helper
- [ ] **Step 4: PASS** + Gate A
- [ ] **Step 5: Commit**(加新代码 ✅)

---

### Task 2: corrected claims → verify roundtrip 验证

**Files:** Modify `feedback_strategies.py`(加 payload builder); Test 同上

**Interfaces:**
- Produces: `build_cascade_payload(corrected_claims: list[dict], narrative_text: str) -> str` — 组成 verify_sub6 消费的 grammar-v2 JSON 字符串 `{"narrative_text":..., "claims":corrected_claims}`。
- Consumes: T1 `apply_cascade`

**建议模型:** sonnet 4.6(需验证 verify_sub6 roundtrip)

- [ ] **Step 1: RED** — 测试: apply_cascade → build_cascade_payload → `verify_sub6(payload, source_report, trace_id=..., is_final_iteration=True)`,断言提取出的 claims 数 == corrected_claims 数(claims 被 zero-LLM 提取,不丢)。用一个真实 trace 的 iter-0 source_report(从 `data/metagent/v4_live_full/path_x_full/` 取一个 + v4 adapter 构造)。
- [ ] **Step 2: FAIL** → **Step 3: GREEN** → **Step 4: PASS** + Gate A → **Step 5: Commit**

---

### Task 3: A narrative weave(prompt + LLM 接口)

**Files:** Create `prompts/agent/feedback_narrative_weave_prompt.md`; Modify `feedback_strategies.py`

**Interfaces:**
- Produces: `weave_narrative(corrected_claims: list[dict], llm_call: Callable) -> str` — 1 次 LLM call,prompt 给 corrected_claims(name + grammar),要求"只写一段 150-300 词连贯 narrative 描述这些 claim,**不得增删或修改任何 claim**,narrative 必须提及每个 claim 的 pathway name",返回 narrative_text。
- prompt 文件硬约束:禁止引入新通路、禁止 meta-language(与现有 feedback prompt rule 一致)。

**建议模型:** haiku 4.5(prompt + 单 LLM 接口)

- [ ] **Step 1: RED** — 测试(注入 mock llm_call): weave_narrative 用 mock 返回固定 narrative,断言接口正确传 corrected_claims 的 pathway names 进 prompt + 返回 narrative_text。
- [ ] **Step 2: FAIL** → **Step 3: GREEN**(实现 + 写 prompt md)→ **Step 4: PASS** + Gate A → **Step 5: Commit**

---

### Task 4: B 锚定重写(prompt + builder)+ C gating

**Files:** Create `prompts/agent/sub6b_react_feedback_prompt_anchored.md`; Modify `feedback_strategies.py`

**Interfaces:**
- Produces: `build_anchored_feedback(verified_claims: list[VerifiedClaim]) -> str` — B 策略 feedback prompt:
  - **正面锚点 block**: 列出所有 SUPPORTED claim "原样保留"
  - contradicted/unsupported block 附 `correction`(top-1 alternative)建议
  - **gating**: 只对 CONTRADICTED 生成"必须改"指令,INSUFFICIENT 不出现(unsure→keep)
- Produces: `should_trigger_feedback(verified_claims: list[VerifiedClaim], min_bad_frac: float = 0.0) -> bool` — C gating: 有 CONTRADICTED/UNSUPPORTED 才触发(默认),可选按 bad fraction 阈值。

**建议模型:** sonnet 4.6(prompt 设计 + builder + gating 逻辑)

- [ ] **Step 1: RED** — 测试: build_anchored_feedback 输出含 supported 锚点 block(断言 supported claim 的 text 出现)+ contradicted 的 correction 出现 + INSUFFICIENT 不出现;should_trigger 在有/无 contradicted 时返回 True/False。
- [ ] **Step 2: FAIL** → **Step 3: GREEN**(实现 + 写 anchored prompt md)→ **Step 4: PASS** + Gate A → **Step 5: Commit**

---

### Task 5: feedback_strategies 统一 dispatch 接口

**Files:** Modify `feedback_strategies.py`; Test 同上

**Interfaces:**
- Produces: `FeedbackResult`(dataclass): `{strategy: str, payload: str | None, corrected_claims: list[dict] | None, kind: "cascade"|"rewrite"}` —— A 返回 corrected_claims(+ weave 后的 payload);B/C 返回 rewrite prompt。
- Produces: `apply_feedback_strategy(strategy: str, verified_claims, source_report, llm_call) -> FeedbackResult` — dispatch: "cascade"→A(apply_cascade + weave + build_payload);"anchored"→B(build_anchored_feedback);"gated"→C(should_trigger ? 现状 feedback : None)。

**建议模型:** sonnet 4.6(集成前 4 task)

- [ ] **Step 1: RED** — 测试 3 个 strategy 各返回正确 kind + 非空内容(注入 mock llm_call)。
- [ ] **Step 2: FAIL** → **Step 3: GREEN** → **Step 4: PASS** + Gate A → **Step 5: Commit**

---

### Task 6: 实验脚本 — 复用 iter-0 + 跑 4 臂

**Files:** Create `scripts/metagent/feedback_ab_eval.py`

**Interfaces:**
- 输入: trace 目录 `data/metagent/v4_live_full/path_x_full/` + 选定 task_ids(20-30,从 61 触发 task 选,覆盖 live-run supported 升/降/持平 + 两 stratum)。
- 每 task: 从 `iterations[0]` 取 react_result(final_claims + enrichment_carriers + final_narrative_text) → v4 adapter 构造 source_report → iter-0 verify 得 verified_claims。然后 4 臂:
  - **no-feedback**: iter-0 verdict(直接用 iterations[0].verification)
  - **现状**: iterations[-1].verification(live run 的 final,已有)
  - **A cascade**: apply_feedback_strategy("cascade") → verify_sub6(payload) → verdict + narrative
  - **B anchored**: build_anchored_feedback → 1 次 LLM 重写(chat,复用 iter-0 证据,不调工具)→ verify_sub6 → verdict + narrative
- 输出每 task 每臂: verdict 分布 + final narrative + claims(存 JSON,供 T7 评估)。

**建议模型:** sonnet 4.6(集成 + LLM 调用 + 复用 iter-0 路径)。**有真实 LLM cost** —— 先 `--limit 2` smoke,再 20-30。

- [ ] **Step 1:** 读 `feedback_ab_eval` 需要的入口(v4 adapter、verify_sub6、chat);写脚本骨架 + task 选取逻辑
- [ ] **Step 2:** 实现 4 臂 runner;`--limit 2` smoke(设 key)确认 A/B 跑通、verifier 出 verdict、无崩
- [ ] **Step 3:** 确认 smoke 输出结构正确(每臂 verdict + narrative)
- [ ] **Step 4:** Commit 脚本(加新代码)

---

### Task 7: 评估 + 跑小规模 + 报告

**Files:** Modify `feedback_ab_eval.py`(加评估); Output `reports/reports_v3/2026-06-26_feedback_ab.md`

**Interfaces:**
- Consumes: T6 每臂的 narrative + claims
- 评估:
  - **主: pathway accuracy** — 每臂最终 narrative/claims 跑 pathway 预测(复用 `concord/agent/pathway_prediction.py:generate_pathway_prediction_second_pass` 或 scorecard 的 semantic match),对比 task 的 ground-truth `perturbed_pathway.name`(top-1 命中 / hit@3)。
  - **辅: claim 质量** — 每臂 verdict 分布(supported/contradicted/unsupported/UV/insufficient)。
- paired 对比: 同 task 跨臂,报告每臂相对 no-feedback 的 Δ(pathway 命中、supported、contradicted)。

**建议模型:** sonnet 4.6(评估 + 分析 + 报告)。**有真实 LLM cost**(pathway 预测可能调 LLM)。

- [ ] **Step 1:** 实现评估(pathway accuracy + claim 分布);先在 T6 的 2-task smoke 输出上验证评估逻辑
- [ ] **Step 2:** 跑选定 20-30 task 全 4 臂(设 key,cost 查 llm_calls.jsonl)
- [ ] **Step 3:** 出 paired 对比表 + 报告 `2026-06-26_feedback_ab.md`:4 臂 pathway accuracy + claim 分布 + 每臂 vs no-feedback 的 Δ + 诚实结论(A 是否不退/提升)
- [ ] **Step 4:** Gate A 不退;Commit 报告
- [ ] **Step 5:** 若方向为正 → 提议全量 + 多 seed 后续 spec;为负 → 记录诚实结论

---

## Self-Review

- **Spec 覆盖:** A cascade(T1-T3,T5)/ B anchored(T4)/ C gating(T4)/ 实验 4 臂(T6)/ 评估 pathway+claim(T7)。✅
- **Placeholder:** task 选取的具体 20-30 task_ids 在 T6 Step 1 由 subagent 按"61 触发 task 覆盖升/降/持平 + 两 stratum"选定,不预列(避免硬编码)。grammar-v2 dict 的精确字段在 T1 Step 1 由 subagent 读 extract_claims_from_json 确认。其余无 placeholder。
- **类型一致:** `apply_cascade`(T1)→`build_cascade_payload`(T2)→`weave_narrative`(T3)→`apply_feedback_strategy`(T5)→`feedback_ab_eval`(T6)接口链一致;`VerifiedClaim.correction` 贯穿 A/B。✅

## Execution Order

T1 → T2 → T3 → T4 → T5(策略实现,串行依赖)→ T6(实验脚本)→ T7(评估+跑+报告)。T4 可与 T1-T3 并行(B/C 独立于 A),但建议串行以复用 T1 的 schema 理解。

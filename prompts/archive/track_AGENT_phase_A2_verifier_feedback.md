# Track AGENT Phase A2 — Verifier feedback loop + MiniMax tool calling

**Session ID:** `track_AGENT_phase_A2_verifier_feedback`
**Branch:** `feature/agent-phase-a2` (新建,base on `feature/agent-phase-a1`)
**Estimated work:** 1.5-2 weeks
**Predecessors:**
- `reports/agent/phase_a1_smoke_audit.md`(A1 完整 audit + 8 个 engineering debt)
- `summary/May_7/STAGE_REPORT.md`(v3 架构现状)
- `reports/eval/sub6b_v3_opus_vs_v2_comparison.md`(v3 baseline)

---

## Why this matters

Phase A1 验证了 prevention 那一面有效(supported +6.58 pt, unverifiable_v0 −7.57 pt)。但 A1 是 prevention only,**verifier 不知道 LLM 调了什么 tool,LLM 也不知道 verifier 怎么判它**。

**Phase A2 闭环**:LLM 写完 narrative → verifier 判 → contradicted/unsupported claim 喂回 LLM → LLM 修订 → 再 verify(2 轮上限)。这是 paper "closed-loop agent" 卖点的核心。

**关键 v2 转向**:用户决定 default LLM **从 Opus → MiniMax-M2.7**。这意味着:
- 必须先扩 `chat_raw` 支持 MiniMax tool calling(A1 audit debt #8)
- 需要新 MiniMax single-call baseline(对照组)
- A1 的 v3 vs v4 数字仅 Opus 域有效,A2 全部用 MiniMax 跑

**本 phase 不做**:
- 文献 search_literature 集成(A3)
- Cross-LLM 三面对比(A3)
- v4 全量 63 task 评估(等 A3 后)

---

## Hard scope boundaries

**You MAY:**
- 扩展 `common/llm_client.py`:加 MiniMax tool calling 支持
- 扩展 `verifier/agent.py` 输出:加 per-claim attribution(claim_id + verdict + evidence + layer)
- 创建 `evaluation/sub6/run_sub6b_react_feedback.py`(A1 runner 的扩展版)
- 创建 `prompts/agent/sub6b_react_feedback_prompt.md`(扩 A1 prompt 加 feedback turn 模板)
- 加 message persistence:每轮 dump 到 `data/eval/sub6/v4_a2/{task_id}.partial.jsonl`
- 跑 5-task smoke + 20-task pilot(MiniMax)
- 跑 Sub-6B v3 × MiniMax single-call 作为新 baseline
- 写 audit `reports/agent/phase_a2_feedback_audit.md`

**You MAY NOT:**
- 修 A1 已有代码(`tools/agent_tools/`、`run_sub6b_react.py` 不动,新建 `_feedback` 版本)
- 修 LIPID MAPS / NM-002 / Sub-6 数据
- 跑 Opus(本 phase 全 MiniMax,A3 再扩)
- 改 v3 数据 jsonl
- 改 verifier 内部 layer 逻辑(只扩输出 schema,不改判定 logic)

---

## Background reading (mandatory)

1. `reports/agent/phase_a1_smoke_audit.md`(尤其 §6 engineering debt)
2. `evaluation/sub6/run_sub6b_react.py`(A1 runner)
3. `tools/agent_tools/dispatcher.py`(dedup cache 机制)
4. `common/llm_client.py`(`chat_raw` / `chat_with_tools` — A1 加的 tool 支持)
5. `verifier/agent.py`(verify_sub6 主入口,看输出 schema)
6. `verifier/layers/set_enrichment.py` + `pathway_relationship.py`(看 verdict + evidence 字段)
7. MiniMax tool calling 文档:https://platform.minimaxi.com/document/(确认协议)
8. `prompts/agent/sub6b_react_prompt.md`(A1 prompt,扩展时复用)

In your first response,确认:
- MiniMax 的 OpenAI-compat 端点是否支持 `tools` / `tool_choice` 参数(看 platform docs)
- 现有 verifier verdict 输出里 per-claim 字段是否已存在(若已有 claim_id,只是没暴露,工作量小;若没有,需要扩 schema)
- Verifier feedback prompt 模板的格式建议(把 contradicted claim + evidence 怎么塞回 message history)
- A2 max_feedback_iterations 推荐值(我推荐 2,跟 GeneAgent 一致)
- 是否新建 `run_sub6b_react_feedback.py` 还是改 `run_sub6b_react.py` 加 flag

不要写代码直到 confirm。

---

## Deliverables

### D0 — MiniMax tool calling prerequisite(1-2 天,**MUST 先过**)

**这是 hard gate** —— 不通则 phase A2 abort,因为 A1/A2/A3 切 MiniMax 都依赖。

修改 `common/llm_client.py`:
- `chat_raw(provider="minimax", tools=[...])` 当前抛异常,改为透传 `tools` / `tool_choice` 到 MiniMax API
- 确认 MiniMax 返回的 `tool_calls` 字段格式跟 OpenAI 一致(probably 是)
- 加 1 个 unit test:mock MiniMax response with tool_calls,验证 dispatcher 能解析

**Smoke test**:用 MiniMax 跑 1 个真实 v3 task(用 A1 的 `run_sub6b_react.py`,只改 `--narrative-llm minimax`),验证:
- LLM 至少调 1 个 tool
- narrative 产出非空
- tool_calls_log 完整

**Acceptance D0**:
- ✅ MiniMax 能调 tool 并产 narrative → 进 D1
- ⚠️ MiniMax 协议跟 OpenAI 不同,需要 adapter → 实现 adapter,延期 1 天
- ❌ MiniMax 完全不支持 tool calling → escalate(A2 退化为只做 verifier feedback,不切 LLM)

### D1 — Verifier per-claim attribution 扩展(2-3 天)

**当前问题**:`verifier/agent.py` 输出的 verdict 是 task-level 聚合,看不到 "哪条具体 claim 被判 contradicted + verifier 给出什么 evidence"。Feedback loop 没法定位错误。

**扩展输出 schema**(只加字段,不改 logic):

```python
# verifier/agent.py 当前输出
{
    "task_id": ...,
    "verdicts_total": {"supported": N, "contradicted": M, ...},
    "claims": [...]  # 已有,但需要补字段
}

# A2 扩展后(不破坏现有)
{
    "task_id": ...,
    "verdicts_total": {...},
    "claims": [
        {
            "claim_id": "claim_42",          # 新增 ← 用于 feedback 定位
            "claim_text": "...",
            "claim_type": "biological_claim",
            "verdict": "contradicted",
            "evidence": {                     # 已有,确认完整
                "tool": "ramp_enrichment",
                "matched_pathways": [...],
                "expected": "...",
                "got": "...",
            },
            "layer_invoked": "6c",            # 新增 ← LLM 看了知道哪类问题
            "feedback_hint": "..."             # 新增 ← 自然语言提示,LLM 直接用
        },
        ...
    ]
}
```

**关键**:`feedback_hint` 是 verifier 给 LLM 的人话提示,例如:
- contradicted: "You wrote 'X is in pathway Y', but RaMP-DB shows X is only in pathway Z. Either retract or qualify."
- unsupported: "Pathway 'one-carbon homeostasis' not found in RaMP top-10. Consider rephrasing as one of: [Folate metabolism / Methionine metabolism]."

**Acceptance D1**:
- 现有 verdict jsonl schema 向后兼容(老 reader 能读)
- 新字段在 v3 v9-PhaseC verdict 上回填一次,验证 reader 能解析
- 1 个 unit test 验证 feedback_hint 模板生成

### D2 — Message persistence(1 天,A1 debt #3)

每轮 LLM call + tool result 落盘:

```
data/eval/sub6/v4_a2/persist/{task_id}/
├── turn_001.json   # full message at turn 1
├── turn_002.json   # ...
├── turn_001.tools.json   # tool calls + results at turn 1
└── final_state.json
```

失败时:
- 检测到 `final_state.json` 不存在但 `turn_*.json` 存在 → 视为 partial
- audit 时 partial task 单独标记,不混入 aggregate

**Acceptance D2**:
- 1 个 task 跑到一半 SIGINT 断,再启动能识别 partial 状态(不需要 resume,只识别 + 丢弃干净)
- partial 数据**不**自动 fallback 到 single-call(A1 那条 timeout fallback 保留,但 partial 不算)

### D3 — Feedback loop runner(3-5 天,核心)

**新建** `evaluation/sub6/run_sub6b_react_feedback.py`(独立文件,不动 A1):

```python
def run_sub6b_react_feedback(
    task: dict,
    *,
    chat_fn: ChatFn,
    model: str = "MiniMax-M2.7",
    max_react_turns: int = 5,
    max_feedback_iterations: int = 2,
    verifier_fn: Callable[[Narrative], VerdictReport],
    tools: list,
    persist_dir: Path,
    caller: str = "sub6b_agent_a2",
) -> Sub6BAgentFeedbackResult:
    """ReAct + verifier feedback loop.
    
    Per task flow:
      1. Run A1 ReAct loop → initial narrative N1
      2. Run verifier on N1 → verdict V1
      3. If V1 has contradicted/unsupported claims:
           - Build feedback prompt: claims + evidence + feedback_hint
           - LLM produces N2 (refined narrative)
           - Run verifier on N2 → V2
           - If V2 has more issues AND feedback_iter < max: repeat
      4. Return (final_narrative, feedback_history)
    """
```

**Feedback prompt 模板**(`prompts/agent/sub6b_react_feedback_prompt.md`):

```
The verifier reviewed your narrative. Here are claims that did not pass:

CONTRADICTED claims:
[claim_id]: "[claim_text]"
  Verifier evidence: [evidence]
  Hint: [feedback_hint]

UNSUPPORTED claims:
[claim_id]: "[claim_text]"
  Verifier evidence: [evidence]
  Hint: [feedback_hint]

Please revise your narrative to either:
  (a) retract claims that the verifier contradicted, or
  (b) rephrase unsupported claims using verified pathway names from earlier 
      tool calls, or
  (c) explicitly surface conflicts when evidence is genuinely contradictory.

You may call tools again if needed for new evidence. Do NOT add new pathway 
claims that were not in your original narrative — focus on fixing existing 
claims.

Original narrative:
[N1]
```

**关键设计**:
- Feedback 不让 LLM 自由扩写,只让它**改/删/加 caveat**(防止 N2 引入新 claim 又触发 verifier)
- 每次 feedback iteration 后跑完整 verifier,记 `(iter, supported, contradicted, unsupported, unverifiable)`
- 终止:`max_feedback_iterations` 或者 `verdict 没改善` 或者 `LLM 选择不修订`

**`Sub6BAgentFeedbackResult` schema**:

```python
@dataclass
class Sub6BAgentFeedbackResult:
    task_id: str
    iterations: list[IterationRecord]    # 每轮 (narrative, verdict, n_tool_calls)
    final_narrative: str
    final_verdict: dict
    n_feedback_iterations: int           # 0 = 没触发 feedback
    elapsed_seconds: float
    error: str | None = None

@dataclass
class IterationRecord:
    iter_index: int                       # 0 = initial, 1+ = feedback rounds
    narrative: str
    verdict_total: dict
    n_tool_calls_this_iter: int
    n_contradicted: int
    n_unsupported: int
    feedback_prompt_used: bool
```

**Acceptance D3**:
- 1 个真实 task 触发 feedback 至少 1 轮,V2 contradicted < V1 contradicted
- max_feedback_iterations 上限工作(不死循环)
- LLM 不修订时干净退出(记 `early_exit_no_revisions`)

### D4 — MiniMax 3-way baseline on 5 task(1 天)

**关键对照实验**:在 5 个 v3 task(amino_acid / lipid / nucleotide / central / other 各 1)上跑:

| variant | 描述 | 用 |
|---|---|---|
| **MiniMax single-call** | A1 之前的 v3 现状 | baseline,paper 必须有 |
| **MiniMax react-agent** | A1 架构,切 MiniMax | 隔离 "tool use" 贡献 |
| **MiniMax react+feedback** | A2 完整(本 phase) | 隔离 "feedback loop" 贡献 |

跑完出对比表:

| task | metric | single | react | react+feedback | Δ feedback |
|---|---|---:|---:|---:|---:|
| amino_acid | sup % | ? | ? | ? | ? |
| lipid | contra % | ? | ? | ? | ? |
| ... | ... |

**Acceptance D4**:
- 5 task × 3 variants 全跑完
- 每 variant 的 supported / contradicted / unverifiable 三个数字都有

### D5 — 20-task pilot + audit(2-3 天)

跟 A1 同 pilot 选样:**10 LM lipid + 10 random non-LM**(seed=42,跟 A1 一致,可对比)。

跑 react+feedback,verdict 落盘。

**Audit `reports/agent/phase_a2_feedback_audit.md`**:

#### 1. 4-way verdict comparison(20 task aggregate)

| metric | v3 single (Opus) | A1 react (Opus) | A2 single (MiniMax) | A2 react+feedback (MiniMax) |
|---|---:|---:|---:|---:|
| supported % | 14.10 | 20.69 | ? | ? |
| contradicted % | 2.93 | 2.94 | ? | ? |
| unverifiable_v0 % | 71.89 | 64.31 | ? | ? |

注意:Opus 列是 A1 已有数字(直接引用),MiniMax 两列是本 phase 新跑。

#### 2. Feedback loop 改善幅度

```
N0 → N1 (feedback 1 后):
  contradicted Δ = ? (期望降)
  unsupported Δ = ? (期望降)
  unverifiable Δ = ? (可能涨,因为 LLM 加 caveat 变成 unverifiable)

N1 → N2 (feedback 2 后):
  改善幅度递减?
  几个 task 真的进 N2(很多 N1 后没有 contradicted 就提前退出)?
```

#### 3. Feedback iterations 分布
- 多少 task 0 iter(initial 就过)
- 多少 task 1 iter
- 多少 task 2 iter(用满)
- 用满 task 的 contradicted 是不是真的降到 0?

#### 4. LM lipid sub-group(A1 的 +2.65 pt regression case)
A1 audit 指出 LM lipid 在 react-only 下 contradicted 上升 2.65 pt。**A2 feedback loop 在 LM lipid 上有没有把这个 regression 修掉?**

#### 5. Engineering debt

#### 6. Decision

```
✅ 显著改善 → 进 A3 (文献 + cross-LLM)
⚠️ 改善小 → 调 feedback prompt 后重测
❌ regression / loop oscillation → debug
```

#### 7. Provenance

### D6 — Acceptance

```
□ D0 MiniMax tool calling 通(1 task smoke)
□ D1 verifier 输出 per-claim 字段(向后兼容)
□ D2 message persistence 验证 1 个中断 task 能干净识别 partial
□ D3 feedback runner 1 task 触发 ≥1 iter 且 V2 比 V1 好
□ D4 MiniMax 5-task 3-way baseline 数据齐
□ D5 20-task pilot 数据齐 + audit 完整
□ A1 代码 0 行改(diff verify)
□ verifier 内部 logic 0 行改(只扩输出 schema)
□ v3 数据 jsonl 0 改
□ branch 干净 + mergeable
```

---

## Pitfalls

1. **MiniMax tool calling 不一定原生支持**:虽然 MiniMax 有 OpenAI-compat 端点,但 tool calling 部分可能 request shape 不同。第一回合**先小流量测**(1 个 tool,1 个 task),不通就 escalate。

2. **Feedback prompt 不能让 LLM 自由扩写**:LLM 收到 feedback 容易"再多写两段补充"——结果 N2 比 N1 还多 unverifiable claim。**prompt 必须严格限制为 retract / rephrase / qualify**,不允许新增 pathway claim。

3. **Feedback iteration 死循环**:LLM 改完一次 verifier 又找新错,反复改。**max=2 是硬限**,且要监控 verdict 是不是真的改善——如果 N1→N2 contradicted 反而升,**回滚到 N1**(不接受 N2)。

4. **Per-claim attribution 改 verifier 时要小心**:`verifier/agent.py` 是 11 layer + cascade,改输出 schema 不要破坏现有数字。**先在 v3 v9-PhaseC verdict 上回填一次新字段并 verify totals 不变**,再用新代码跑新数据。

5. **Verifier feedback 引入新错风险**:verifier 自己 4% contradicted rate 不是 100% 准确。LLM 信了错的 feedback 反而把对的改错。**Audit §2 必须比较 N0 vs N2**(不只 N0 vs N1),如果 N2 比 N0 还差,这条路本身有问题,paper 退化为只做 prevention。

6. **MiniMax 速度**:MiniMax 比 Opus 慢(A1 audit 提到)。20-task pilot wall time 可能 2-3 小时,不要在 1 个 task 卡死后才发现。

7. **跨 LLM 数字不可比警示**:A2 用 MiniMax,A1 用 Opus。**aggregate 数字不能直接 v3-Opus vs v4-MiniMax 比**。Audit §1 必须按 LLM 分列。

---

## Time budget

- D0 MiniMax tool: 1-2 天
- D1 verifier per-claim: 2-3 天
- D2 persistence: 1 天
- D3 feedback runner: 3-5 天
- D4 3-way baseline: 1 天
- D5 pilot + audit: 2-3 天

**Total: 1.5-2 周**(MiniMax 慢导致 D5 wall time 偏长)

---

## First action checklist

第一回合:
1. 读 8 个 background 文件(尤其 A1 audit §6 debt 列表)
2. 报告 MiniMax OpenAI-compat 端点是否支持 tools= 参数(看 platform docs 或 quick curl test)
3. 报告现有 verifier verdict jsonl 中是否已有 claim_id 字段(若有,工作量降)
4. 提议 feedback prompt 模板的具体 wording(不要让 LLM 自由扩写)
5. 提议 max_feedback_iterations 值(推荐 2)
6. 确认是否新建 `run_sub6b_react_feedback.py`(推荐)
7. 任何 clarifying question

不要写代码 / 改 chat_raw / 改 verifier,直到我 confirm 这 7 项。

# Track AGENT Phase A1 — Function calling infrastructure (LLM tool use)

**Session ID:** `track_AGENT_phase_A1_tool_use`
**Branch:** `feature/agent-phase-a1` (新建,base on `feature/lipidmaps`)
**Estimated work:** 1.5-2 weeks
**Predecessors:**
- `summary/May_7/STAGE_REPORT.md`(v2/v3 现有架构 + verifier 状态)
- `reports/audit/v1_opus_sanity_check.md`(F4 finding)
- `reports/eval/sub6b_v3_opus_vs_v2_comparison.md`(LIPID MAPS 集成结果)

---

## Why this matters

当前 Stage 2 LLM **不调任何工具**——prompt 塞预算好 context,LLM 单次输出 narrative。这导致:

1. paper 不能诚实 claim "agent"
2. LLM 凭训练记忆推 pathway,hallucination 率高
3. F4 finding 暴露的 literal-style bias 无解(LLM 写"nucleotide homeostasis"而不查 RaMP)

**本 phase 解决 prevention 那一面**:LLM 收到化合物列表后,**主动调用 5 个 function tool 查真实数据**,基于工具输出生成 narrative。后续 phase A2 加 verifier feedback,A3 加文献检索集成。

**本 phase 不做**:
- verifier feedback loop(A2)
- 文献集成(A3,只做 search_literature 接口,不做 retrieval-augmented narrative)
- 大规模评估(A1 只做 single-LLM smoke + 部分 v4 pilot)

---

## Hard scope boundaries

**You MAY:**
- 创建 `tools/agent_tools/` 包(5 个 function tool 的 LLM-facing wrapper)
- 修改 `evaluation/sub6/run_sub6b.py` 加 ReAct loop 选项(不改原 single-call path)
- 修改 `evaluation/sub6/run_sub6a.py` 同样
- 创建 `prompts/agent/sub6b_react_prompt.md`(新 prompt 模板,不动旧的)
- 跑 5-task smoke + 20-task pilot(不跑全 63)
- 写 audit `reports/agent/phase_a1_smoke_audit.md`

**You MAY NOT:**
- 改 verifier 任何代码(verifier feedback 是 A2 的事)
- 修 LIPID MAPS / NM-002 / Sub-6 数据构建逻辑
- 重写 `common/llm_client.py`(用现有 chat() 接口扩展,不改主体)
- 跑 GPT-5.5 / MiniMax(本 phase 只用 Opus-4-7,稳定后再扩 cross-LLM,放 A2/A3)
- 跑 v4 全量(63 task × 3 LLM,留给 phase A3 后)
- 改 v3 数据 jsonl

---

## Background reading (mandatory)

1. `evaluation/sub6/run_sub6b.py`(现有 single-call narrative runner)
2. `common/llm_client.py`(chat() 实现 + provider routing)
3. `tools/pathway_context/`(看现有 RaMP enrichment 实现,Tool 1 复用)
4. `tools/metabolite_info/`(看现有 HMDB lookup 实现,Tool 4 复用)
5. `tools/benchmark/sub6/ramp_enrichment.py`(Tool 1 主体逻辑)
6. `verifier/layers/pathway_relationship.py`(看 KEGG graph BFS,Tool 3 复用)
7. `tools/literature/`(若存在;Layer E 文献接口,Tool 5 复用)
8. Anthropic tool use docs:https://docs.anthropic.com/en/docs/build-with-claude/tool-use
9. OpenAI function calling docs(viviai 走 OpenAI-compat 接口)

In your first response,确认:
- 现有 `chat()` 函数是否支持传 `tools=[...]` 参数(Anthropic 和 OpenAI 都支持,viviai relay 应该转发)
- 5 个 tool 中哪几个能直接复用现有 verifier 模块,哪几个需要薄包装
- ReAct loop 的最大轮数定多少(推荐 5,防发散)
- 是否在 `evaluation/sub6/` 下加 `run_sub6b_react.py`(独立文件)还是 `run_sub6b.py` 加 flag

不要写代码直到 confirm。

---

## Deliverables

### D1 — 5 个 function tool 的 wrapper(3-4 天)

**新建** `tools/agent_tools/`,每个 tool 一个文件:

```
tools/agent_tools/
├── __init__.py
├── schemas.py              # Pydantic input/output schemas (LLM tool calling 要)
├── tool_definitions.py     # OpenAI/Anthropic-style tool definition JSON
├── query_ramp_enrichment.py
├── query_pathway_membership.py
├── query_kegg_path.py
├── lookup_compound_info.py
├── search_literature.py
├── dispatcher.py           # 接收 LLM tool_call,路由到对应 tool,返回 tool_result
└── tests/
    └── test_tools.py
```

**关键设计** — 每个 tool 必须满足:

1. **Input schema 严格**:Pydantic 模型,LLM 必须传合法 KEGG ID / HMDB ID。LLM 传错(e.g. SMILES)→ 返回 ValidationError dict,LLM 看到错误重试。

2. **Output 给 LLM 看的字段简洁**:不返回内部 ramp_id 之类技术细节,只返回 LLM 能用来推理的字段。

3. **复用现有模块**:
   - Tool 1 query_ramp_enrichment ← 复用 `tools/benchmark/sub6/ramp_enrichment.py`
   - Tool 2 query_pathway_membership ← 复用 `tools/pathway_context/`
   - Tool 3 query_kegg_path ← 复用 `verifier/layers/pathway_relationship.py` 内的 KEGG BFS
   - Tool 4 lookup_compound_info ← 复用 `tools/metabolite_info/`
   - Tool 5 search_literature ← 复用 `tools/literature/`(若存在)或 Europe PMC 直接 wrapper

4. **统一错误处理**:tool failure 不抛异常,返回 `{"error": "...", "fallback_suggested": "..."}`,让 LLM 决定换 tool 还是放弃。

**Tool definitions JSON**(`tool_definitions.py`)— Anthropic + OpenAI 双版本:

```python
RAMP_ENRICHMENT_TOOL_OAI = {
    "type": "function",
    "function": {
        "name": "query_ramp_enrichment",
        "description": "Run hypergeometric pathway enrichment on RaMP-DB...",
        "parameters": {
            "type": "object",
            "properties": {
                "compound_kegg_ids": {"type": "array", "items": {"type": "string"}},
                "top_k": {"type": "integer", "default": 5},
            },
            "required": ["compound_kegg_ids"],
        },
    },
}

RAMP_ENRICHMENT_TOOL_ANTH = {
    "name": "query_ramp_enrichment",
    "description": "Run hypergeometric pathway enrichment on RaMP-DB...",
    "input_schema": {...}
}
```

**Acceptance D1:**
- 5 个 tool 各自单测全过
- dispatcher 端到端 mock test:模拟 LLM tool_call → 路由 → 真实 tool → 返回 tool_result(JSON)
- Tool definition 通过 Anthropic + OpenAI 两边 schema validation

### D2 — ReAct runner(3-4 天)

**新建** `evaluation/sub6/run_sub6b_react.py`(独立文件,不动 `run_sub6b.py`):

```python
def run_sub6b_react(
    task: dict,
    *,
    chat_fn: ChatFn = ...,
    model: str = "claude-opus-4-7",
    max_turns: int = 5,
    tools: list = None,
    caller: str = "sub6b_agent_a1",
) -> Sub6BAgentResult:
    """ReAct-style agent run on a Sub-6B task.
    
    Flow per task:
      1. Initial prompt: differential metabolites + tool descriptions
      2. LLM responds with EITHER text OR tool_calls
      3. If tool_calls: execute via dispatcher, append tool_results to messages
      4. Loop until LLM produces final narrative OR max_turns reached
      5. Return narrative + tool_call_log
    """
```

**关键设计**:

1. **Prompt 模板** `prompts/agent/sub6b_react_prompt.md`:
```
You are a metabolomics expert analyzing a differential metabolite list.

Available tools:
- query_ramp_enrichment(compound_kegg_ids): pathway enrichment
- query_pathway_membership(...): verify membership claim  
- query_kegg_path(...): find reaction path between compounds
- lookup_compound_info(...): get compound metadata
- search_literature(...): search papers

Process:
1. Start by calling query_ramp_enrichment to identify candidate pathways
2. Verify driver compounds with query_pathway_membership
3. For upstream/downstream claims, use query_kegg_path
4. For biological context, use lookup_compound_info or search_literature
5. After gathering evidence, write a final narrative

Differential metabolites:
[METABOLITES]
```

2. **`Sub6BAgentResult` 比 `Sub6BResult` 多记录**:
```python
@dataclass
class Sub6BAgentResult:
    task_id: str
    narrative: str
    elapsed_seconds: float
    llm_model: str
    n_turns: int                       # 实际 ReAct 轮数
    n_tool_calls: int
    tool_calls_log: list[dict]         # 每次 tool call + result(audit 用)
    error: str | None = None
```

3. **保留 single-call path 兼容**:`run_sub6b.py` 不动,新增独立 runner 方便对比。

**Acceptance D2:**
- 1 个真实 Sub-6B v3 task 跑通 ReAct loop,LLM 至少调 2 个 tool,产出 narrative
- tool_calls_log 完整记录每个 tool input/output
- 总 wall time < 60s/task(超时降级 fallback 到 single-call,不要硬撑)
- 无未捕获异常

### D3 — 5-task smoke test(1 天)

挑 v3 中 5 个代表性 task(amino_acid / lipid / nucleotide / central / other 各 1 个):

```bash
PYTHONPATH=. python scripts/eval_sub6/run_baseline.py \
    --sub6b data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl \
    --narrative-llm opus47 \
    --mode react-agent \
    --max-tasks 5 \
    --output data/eval/sub6/v4_smoke/sub6b_opus_react/ 
```

(具体 CLI 看 D2 实际实现)

**记录**:
- 每个 task 实际调了哪些 tool / 几轮
- narrative 长度对比 single-call(应该差不多 2000-3000 chars)
- 失败模式(LLM 不调 tool / 调错 tool / 死循环)

### D4 — 20-task pilot evaluation(2-3 天)

跑 20 个 v3 task(包括所有 11 个 lipid + 随机 9 个),用现有 verifier v9-PhaseC 跑出 verdict。

**注意**:**verifier 不动**(本 phase 是 prevention,不是 correction)。Verifier 当作 v3 同口径 evaluator。

**关键对比表**(audit §3 必有):

| metric | v3 single-call (现有) | v4 react-agent (新) | Δ |
|---|---:|---:|---:|
| supported % | 17.40 | ? | ? |
| **contradicted %** | 4.11 | ? | ? (期望降) |
| unverifiable_v0 % | 66.97 | ? | ? (期望降) |
| 平均 tool calls/task | 0 | ? | 新指标 |
| 平均 wall time/task | 22s | ? | 新指标(预期 60-120s) |

**Hard expectation**:
- contradicted < v3 (LLM 调 tool 后应该错得更少)
- 如果 contradicted 反而高 → 问题大,escalate

### D5 — Phase A1 audit report

`reports/agent/phase_a1_smoke_audit.md`:

#### 1. Tool call statistics
- 每个 tool 被调用的次数 / 频率
- 哪个 tool 最常用?哪个从不被用?
- 调用错误率(LLM 传错参数)

#### 2. Narrative quality 对比(5 task 详细)
- 同 task 下 single-call vs react-agent 的 narrative 对比
- LLM 是否真的引用了 tool 输出?
- 还是 tool 调了但输出被忽略?

#### 3. 20-task pilot verdict 对比
- 跟 v3 的 4 维度 verdict 数字对比表
- supported/contradicted/unverifiable 变化

#### 4. 失败模式分类
- LLM 不调 tool(直接写 narrative)
- LLM 调错 tool(用 KEGG 查 HMDB ID)
- 死循环(同一 tool 调多次)
- 超时

#### 5. 决策给 user

基于 D4 对比数字推荐:
- ✅ 显著改善 → 进 A2 (verifier feedback loop)
- ⚠️ 无改善但无 regression → 调 prompt 后重测,不进 A2
- ❌ regression → debug,phase A1 不算完成

#### 6. Provenance + 工程债务清单

### D6 — Acceptance check

```
□ 5 个 tool wrapper 单测全过
□ dispatcher mock test 通过
□ ReAct runner 5 task smoke 跑通
□ 20-task pilot 完整数据落盘
□ audit report 完整覆盖 §1-5
□ verifier 代码 0 行改动(diff verify)
□ v3 数据 jsonl 0 改动
□ 不影响现有 run_sub6b.py 的 single-call path
□ branch feature/agent-phase-a1 干净 + 可 merge
```

---

## Pre-flight: v3 baseline 已 snapshot

**派本 session 之前**,user 已运行 `scripts/snapshot_v3_baseline.sh` 创建 baseline:
- Git tag: `v3-baseline-2026-05-XX` (注意:实际日期看 `git tag -l 'v3-baseline-*'`)
- Branch snapshot: `v3-state-snapshot-2026-05-XX`(若 dirty WT 不空)
- Data tarball: `~/backups/metagent_v3-baseline-2026-05-XX.tar.gz`

如果本 phase 跑出来需要回退:
```bash
# 回退代码:
git checkout v3-baseline-2026-05-XX
# 如果 phase A1 跑过程中污染了 v3 数据(不应该,但保险):
tar xzf ~/backups/metagent_v3-baseline-2026-05-XX.tar.gz -C /tmp/restore/
diff -r /tmp/restore/data/eval/sub6/v3/ data/eval/sub6/v3/   # 查看差异
```

**本 session 严禁动 v3 baseline 数据**(`data/eval/sub6/v3/sub6b_opus/*` 是对照基准)。所有 phase A1 输出必须落到新目录 `data/eval/sub6/v4_smoke/` / `data/eval/sub6/v4_pilot/`。

---

## Pitfalls

1. **viviai relay 的 tool calling 行为不确定**:Anthropic / OpenAI tool calling protocol 不同。viviai 是 OpenAI-compat,所以走 OpenAI-style tool_calls 字段。**第一回合务必确认 chat() 是否能透传 tools**,不行就需要薄改 llm_client(这是允许的)。

2. **LLM 不调 tool 是常见失败**:Opus 偶尔会"觉得自己知道"直接写 narrative。prompt 里**强制要求至少调用 query_ramp_enrichment**,不调拒绝接受 narrative。

3. **Tool 输出过大会撑爆 context**:RaMP enrichment top-5 可能几 KB。每个 tool result **限 2 KB**,truncate + 提示 LLM 可以再调 tool 看更多。

4. **死循环**:LLM 同一 tool 重复调。dispatcher 加去重 — 同一 (tool_name, input_hash) 调过就直接返回 cache,告诉 LLM "you already called this"。

5. **KEGG ID 错误**:LLM 给 SMILES 而不是 KEGG。tool 拒绝 + 返回 "expected KEGG cpd:Cxxxxx, got SMILES",LLM 重试。

6. **wall time 失控**:5 turn × 5s/tool + 4 LLM call × 10s = ~50s/task。设硬超时 120s,超时 fallback 到 single-call。

7. **Anthropic vs OpenAI 协议差异**:第一回合如果发现 tool calling 在 Opus 走得通但 GPT 走不通,本 phase 只支持 Opus,跨 LLM 适配留 A3。

---

## Time budget

- D1 tool wrappers: 3-4 天
- D2 ReAct runner: 3-4 天
- D3 smoke: 1 天
- D4 pilot: 2-3 天
- D5 audit: 1-2 天
- D6: 5 min

**Total: 1.5-2 周**(单 LLM Opus only)。

---

## First action checklist

第一回合,做这些:

1. 读 9 个 background 文件
2. 报告 chat() 是否原生支持 tools 参数(看 common/llm_client.py 实现)
3. 报告 5 个 tool 各自能复用哪个现有模块(file:line 引用)
4. 确认 viviai relay 是 OpenAI-compat,tool_calls 协议走 OpenAI style
5. 提议 ReAct max_turns(推荐 5)
6. 提议是否新建 `run_sub6b_react.py`(推荐)还是改 `run_sub6b.py` 加 flag
7. 任何 clarifying question

不要写代码 / 改 llm_client,直到 confirm 这 7 项。

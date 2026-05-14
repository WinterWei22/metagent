# Track EVAL Sub-6 v2 Phase 3.1 — Cross-LLM narrative routing

**Session ID:** `track_EVAL_sub6_v2_cross_llm_routing`
**Branch:** `feature/sub6-v2-cross-llm` (新建,base on `feature/sub6-v2-expand-pool`)
**Estimated work:** 0.5 day
**Predecessor reports:**
- `reports/verifier/llm_3way_comparison_2026-05-05.md`(verifier 3-way 已通,viviai relay 已用)
- `reports/eval/sub6_baseline_day3_2026-05-01.md`(原 baseline runner)

---

## Who you are

Verifier 内部 LLM 已做 3-way 对比(MiniMax/GPT-5.5/Opus-4-7),viviai relay 通了。
但 narrative 生成侧 (`evaluation/sub6/run_sub6{a,b}.py`) 还只支持单一 LLM
(通过 `model` 参数,但 CLI 没暴露)。

本 session 加 `--narrative-llm` CLI 参数,让 baseline runner 能跑跨 LLM。
**不实际跑 baseline**(那是 Phase 3.2 的事),只改 CLI + 测试通过。

---

## Hard scope boundaries

**You MAY:**
- 修 `evaluation/sub6/run_sub6b.py`(加 CLI parsing)
- 修 `evaluation/sub6/run_sub6a.py`(加 CLI parsing)
- 修 `scripts/eval_sub6/run_baseline.py`(传 `--narrative-llm` 给 runner)
- 加 unit test
- 写小 audit `reports/eval/cross_llm_routing_implementation.md`

**You MAY NOT:**
- 修 `common/llm_client.py`(viviai relay 已工作,不动)EXCEPT for adding 1-2 lines
  to support per-call provider override (see Pitfall 1)
- 修 prompt 模板(跨 LLM 公平对比需要)
- 实际跑 baseline narratives(Phase 3.2 的事)
- 修 verifier
- 修 metric 计算

---

## Background reading (mandatory)

1. `evaluation/sub6/run_sub6b.py` 完整(已有 `model: str = llm_client.DEFAULT_MODEL`)
2. `evaluation/sub6/run_sub6a.py` 完整
3. `scripts/eval_sub6/run_baseline.py`(CLI 入口)
4. `common/llm_client.py` line 30-60(provider switch logic)
5. `reports/verifier/llm_3way_comparison_2026-05-05.md` §2(viviai env vars)

In your first response,确认:
- 现有 `run_sub6b.py` `model` 参数怎么传的(从 CLI? 硬编码?)
- viviai relay 切 LLM 是 env var 还是函数参数(从 verifier v4/v5 的实现看)
- `chat()` 函数签名是否支持 per-call model override(跨 LLM 同进程切换)

不要写代码直到 confirm。

---

## Deliverables

### D1 — CLI 参数设计

加到 `scripts/eval_sub6/run_baseline.py` 和直接调 runner 的入口:

```
--narrative-llm {minimax|gpt55|opus47}    (default: minimax)
```

路由逻辑(在 runner 入口处,跑 chat() 之前):
- `minimax`:用现有 default,不动 env
- `gpt55`:在跑之前 set `METAGENT_LLM_PROVIDER=openai`,
  `METAGENT_OPENAI_MODEL=gpt-5.5`
- `opus47`:同上但 `METAGENT_OPENAI_MODEL=claude-opus-4-7`

**关键:** env var 切换要在 `common.llm_client` 的 module-level state
被读取**之前**生效。如果 llm_client 在 import 时就读 env(看代码确认),
你需要在 chat() per-call 传 model + provider,而不是改 env。

如果 chat() 不支持 per-call provider override,**需要小改 llm_client.py**
增加这能力(单一参数加 default 值,backward compat),这是 EXCEPTION 给本 session
的允许范围 — 但只能加 1-2 行,不重构。

### D2 — 单元测试

`tests/eval_sub6/test_cross_llm_routing.py`:
- mock chat_fn,断言 narrative-llm=minimax 时调用使用 minimax model 名
- 同 gpt55 → claude-opus-4-7 / gpt-5.5
- 不实际调 LLM(用 set_mock)

### D3 — Smoke test(实际调 viviai)

跑 1 个 task × 3 LLM(用现有 Sub-6B v2 第一条):

```bash
# 测 minimax
python scripts/eval_sub6/run_baseline.py \
    --sub6b data/benchmark/sub6/sub6b_mammalian_tasks_v2.jsonl \
    --narrative-llm minimax \
    --output /tmp/cross_llm_smoke/minimax/ \
    --max-tasks 1

# 测 opus47
python scripts/eval_sub6/run_baseline.py \
    --sub6b data/benchmark/sub6/sub6b_mammalian_tasks_v2.jsonl \
    --narrative-llm opus47 \
    --output /tmp/cross_llm_smoke/opus47/ \
    --max-tasks 1

# 测 gpt55
python scripts/eval_sub6/run_baseline.py \
    --sub6b data/benchmark/sub6/sub6b_mammalian_tasks_v2.jsonl \
    --narrative-llm gpt55 \
    --output /tmp/cross_llm_smoke/gpt55/ \
    --max-tasks 1
```

如果 `--max-tasks` 还没实现,加上(很简单的 limit)。

确认:
- 3 个输出文件都生成
- llm_model 字段分别是 `MiniMax-M2.7` / `claude-opus-4-7` / `gpt-5.5`
- 3 个 narrative 内容**不一致**(说明真的调了不同 LLM)
- 没有 fallback 到 minimax 的 silent failure

### D4 — Implementation report

`reports/eval/cross_llm_routing_implementation.md`:

#### 1. CLI 设计
- 加的 flag、default、位置(run_baseline.py + run_sub6{a,b}.py)
#### 2. 路由实现
- env var vs per-call model override 选择 + 理由
- llm_client 是否被改(若改,diff 行数)
#### 3. Smoke test 结果
- 3 个 LLM 的 1-task narrative 长度 + 时间 + 成本估算
#### 4. Phase 3.2 handoff
- 跑全量 63 task × 3 LLM 的命令
- 预期 wall time 和成本
#### 5. Provenance + git diff stat

### D5 — Acceptance

```
□ --narrative-llm 参数在 3 个入口(run_baseline.py + run_sub6{a,b}.py)都接受
□ 3 个 LLM 各跑 1 task 成功
□ llm_model 字段正确
□ 3 个 narrative 内容不同
□ unit tests pass
□ git diff:run_sub6{a,b}.py + run_baseline.py + 1 个新 test,加上可能 1-2 行 llm_client
□ 不动 prompt
```

---

## Pitfalls to avoid

1. **env var 切换的 module state**:llm_client 可能在 import 时读 env。如果是这样,在 import 后改 env 不生效。需要 per-call 传 provider/model。这是允许小改 llm_client 的唯一情况(加 1-2 行 per-call override)。

2. **viviai relay 502/超时**:smoke test 偶尔失败,加 1 次 retry。GPT-5.5 在 viviai 上 SSL 错误率 ~23%(verifier v4 实测),正常。

3. **`--max-tasks` 如果没有就加**,不要改 batch loop 主体。

4. **不要硬编码 model 名称**。把 'minimax' / 'gpt55' / 'opus47' → model name 的映射放配置 dict,paper 里改 model 容易。

5. **Sub-6A 同样需要 --narrative-llm**(LLM call 在 stage 2 enrichment narrative 处,跟 Sub-6B 同 prompt template)。

---

## Time budget

- D1 + D2: 1.5 小时
- D3 smoke: 30 分钟(viviai 慢)
- D4: 30 分钟
- D5: 5 分钟

总:2.5-3 小时。

---

## First action checklist

第一回合:
1. 读 5 个 background 文件
2. 报告 chat() 是否支持 per-call provider override(代码引用)
3. 报告 viviai env vars 是 import-time 还是 runtime 读
4. 报告 run_baseline.py 现有 CLI args 列表
5. 报告 `--max-tasks` 是否已存在
6. 决策:env var 切 vs per-call 切(给推荐)
7. 任何 clarifying question

不要写代码直到 confirm。

# Track AGENT Phase A3 — Parallelization + Literature tool + v4 全量

**Session ID:** `track_AGENT_phase_A3_full`
**Branch:** `feature/agent-phase-a3` (新建,base on `feature/agent-phase-a2`)
**Estimated work:** 2.5-3 weeks
**Predecessors:**
- `reports/agent/phase_a2_feedback_audit.md`(A2 完整 audit)
- `reports/agent/phase_a1_smoke_audit.md`(A1 audit + 8 个 engineering debt)
- `summary/May_7/STAGE_REPORT.md`

---

## Why this matters

A2 verified closed-loop feedback works on MiniMax (supported 10.32% → 31.30%, contradicted 3.87% → 2.97%). 但有 **7 个红牌**阻碍 v4 全量评估:

1. **wall time 909s/task** — 跑 v4 全量 63 task = 16h 单 LLM,不可接受
2. **文献 tool 在 mammalian 上 0 调用** — A1 已暴露,A3 必须用 verifier feedback 联动救活
3. **Layer 6d KEGG SQL warning** — verifier audit 必修,**且修复后所有 v4 数字会漂移,必须量化**
4. **同 task subset 跨 phase 不一致** — D5 (n=16) vs A1 (n=18) 不可直接 head-to-head
5. **🆕 MiniMax 非确定性严重**(A2 §8):D4↔D5 同 task 80% delta>5 claim。单次跑的 v4 数字带 ±10pt 噪声,paper 不能用单 sample
6. **🆕 MiniMax cluster overload**:A2 §5 debt #5,3/60 verifier calls 超时或 HTTP 529。v4 全量 567 calls 预期 ~28 失败
7. **🆕 max_feedback_iterations=2 可能不够**:A2 §3 显示 85% (17/20) task 用满 budget,LLM 还想继续改

**A3 解决前 3 + 5/6/7**(第 4 个属 cross-LLM,留 A4)。完成后:
- v4 全量 63 task × MiniMax × 3 variants 跑通
- closed-loop 三阶段完整(prevention → feedback → literature)
- N≥3 reruns 保证 paper 数字带 95% CI
- paper main figure 数据落盘 + Layer 6d 修复前后量化

**本 phase 不做**:
- Cross-LLM (Opus / GPT-5.5 tool calling 适配)
- MiniMax N=3 seeds 鲁棒性
- 任何 paper 写作

---

## Hard scope boundaries

**You MAY:**
- 创建 `evaluation/sub6/parallel_runner.py`(asyncio 任务池)
- 修改 `evaluation/sub6/run_sub6b_react_feedback.py`(支持 async + literature 联动)
- 修改 `tools/agent_tools/search_literature.py`(Europe PMC 真实接入 + truncation)
- 修改 `verifier/feedback_hints.py`(扩 biological_claim unsupported 分支建议查文献)
- 修 Layer 6d SQL warning(只改这一个 layer,其他 verifier 代码不动)
- 跑 5 task smoke + 20 task pilot + **v4 全量 63 task**
- 写 audit `reports/agent/phase_a3_audit.md`

**You MAY NOT:**
- 改 verifier 其他 layer 的 logic(只修 Layer 6d SQL bug)
- 改 LIPID MAPS / NM-002 / Sub-6 数据
- 跑 Opus / GPT-5.5(本 phase 全 MiniMax)
- 改 v3 数据 jsonl
- 改 A2 D3 feedback runner 主体逻辑(只加 async + literature 联动)

---

## Background reading (mandatory)

1. `reports/agent/phase_a2_feedback_audit.md`(尤其 §5 engineering debt + §8 MiniMax 非确定性)
2. `evaluation/sub6/run_sub6b_react_feedback.py`(A2 D3 runner)
3. `tools/agent_tools/search_literature.py`(A1 已 wire 但 0 调用)
4. `verifier/feedback_hints.py`(A2 D1 已实现,需扩展)
5. `verifier/layers/pathway_relationship.py` 或 Layer 6d 实现(SQL warning 来源)
6. `tools/literature/`(若有 Europe PMC client)或 `verifier/layers/literature.py`(A1 Layer E)
7. Europe PMC REST API:https://europepmc.org/RestfulWebService

In your first response,确认:
- 当前 single task wall time 分布(LLM call vs verifier vs tool dispatch 各占多少)
- Layer 6d SQL warning 具体出现位置(file:line)+ 修复方向
- search_literature 当前实现是否真有 Europe PMC 接入,还是 stub
- 推荐并行度(同时跑几 task)— 受 MiniMax rate limit 约束,我猜 3-5 并行
- v4 全量 63 task × 3 variants × verifier 总 wall time 估算(基于并行后)

不要写代码直到 confirm。

---

## Deliverables

### D0 — 并行化 + retry-with-backoff(5-7 天)— HARD GATE

**两块工作合并**:

#### D0a — 并行化(主体)

**目标**:把 909s/task 降到 ≤120s/task 等效串行时间(实际 wall time 受并行度限制)。

**实现路径**:

```
当前 (D5 串行):
  task 1: react 50s + feedback 859s = 909s
  task 2: 等 task 1 完才开始
  ...
  20 task 总 wall = 20 × 909s ≈ 5h

A3 (asyncio 并行):
  task 1, 2, 3, 4, 5 同时跑(并行度 K=5)
  瓶颈是单 task 内 verifier × 多 iter × 30-claim narrative
  
  优化点:
    a) verifier 内部 layer 并行(每 claim 独立 layer 调用,asyncio.gather)
    b) feedback iter 间不能并行(依赖关系)
    c) tool dispatch 已有 cache,不需改
  
  预期: 20 task wall = ~2h (并行度 5)
        v4 全量 63 task = ~6h (并行度 5)
```

#### D0b — Chat 层 retry-with-backoff(A2 §5 debt #5)

A2 v4 全量预期 567 verifier calls × 5% 失败 ≈ 28 失败 → paper 数字污染。**chat 层加 retry**:

```python
# common/llm_client.py
RETRY_STATUS = {500, 502, 503, 504, 529}  # 5xx + overloaded
RETRY_EXCEPTIONS = (httpx.ReadTimeout, httpx.ConnectError, httpx.RemoteProtocolError)

def chat_with_retry(messages, *, max_retries=3, backoff_seconds=(10, 30, 60), **kwargs):
    """Wrap chat() with retry on 5xx / Timeout / 529."""
    for attempt in range(max_retries + 1):
        try:
            return chat(messages, **kwargs)
        except RETRY_EXCEPTIONS as e:
            if attempt == max_retries:
                raise
            sleep(backoff_seconds[attempt])
        except httpx.HTTPStatusError as e:
            if e.response.status_code not in RETRY_STATUS or attempt == max_retries:
                raise
            sleep(backoff_seconds[attempt])
```

**集成点**:verifier internal LLM call、narrative LLM call、feedback LLM call **全部走 retry 包装**。tool dispatch 不需要(无 LLM)。

**Acceptance D0**:
- 5 task pilot 在 ≤30 min wall 跑完(单 LLM,并行度 5)
- 单 task wall time 降到 ≤300s(verifier 内部并行后)
- 数据正确性:并行 vs 串行同 5 task verdict diff = 0(LLM 非确定性除外,但 verifier 必须 deterministic)
- 失败一个 task 不挂掉整 pipeline(asyncio task 异常隔离)
- **🆕 retry**:故意注入 1 个 503 response,验证 retry 机制工作 + 最终成功
- **🆕 5xx/529 失败率 < 1%**(对比 A2 的 5%)

### D1 — Literature tool 真实接入 + verifier 联动(5-7 天)

**两块工作**:

#### D1a — search_literature 真实实现

当前 wrapper 应是 stub,改为真实 Europe PMC REST API:

```python
def search_literature(query: str, top_k: int = 5) -> dict:
    """Search Europe PMC. Returns top_k results with truncated abstracts."""
    # GET https://www.ebi.ac.uk/europepmc/webservices/rest/search
    # parse XML/JSON
    # truncate each abstract to ~500 chars
    # output budget ≤2 KB total (跟 dispatcher 一致)
    return {
        "results": [
            {"pmid": ..., "title": ..., "abstract_excerpt": ..., "year": ...},
            ...
        ],
        "total_hits": N,
    }
```

**关键**:abstract 必须 truncate,否则 5 篇 × 2000 chars = 10KB 撑爆 LLM context。每篇限 500 chars,前 2 句 + ellipsis。

#### D1b — verifier feedback_hint 联动文献 tool

扩 `verifier/feedback_hints.py`:

```python
def get_feedback_hint(claim, evidence, verdict, claim_subtype) -> str:
    # A2 已有:
    if claim_subtype == "pathway_membership" and verdict == "contradicted":
        return retract_or_qualify_hint(claim, evidence)
    
    # A3 新增:
    if claim_subtype == "biological_significance" and verdict == "unsupported":
        return (
            f"Your claim '{claim.text[:80]}' is not in our pathway databases. "
            f"This is often a literature-supported claim. Consider calling "
            f"search_literature('{extract_query_from_claim(claim)}') to find "
            f"supporting papers and cite them, OR retract if speculative."
        )
    
    if claim_subtype == "compound_function" and verdict == "unsupported":
        return f"... similar literature suggestion for compound function claims ..."
    
    if claim_subtype == "disease_association" and verdict == "unsupported":
        return f"... similar for disease/clinical claims ..."
```

**Acceptance D1**:
- search_literature 在 5 测试 query 上返回真 Europe PMC 数据
- abstract_excerpt 平均 ≤500 chars,total response ≤2 KB
- feedback_hint 模板 unit test 覆盖 3 个新分支
- **5 task smoke**: 至少 3 个 task 中 LLM 在 feedback turn 主动调 search_literature(对比 A1 的 0/20 调用率)
- **关键验收**:文献调用必须**对 verifier verdict 有改善**——LLM 调文献后写出来的 N2 narrative,unsupported 数比 N1 低

如果 LLM 调了文献但 N2 没改善,说明 LLM 看了文献摘要也没用——这本身是 finding,但 acceptance 不过,需要调 prompt。

### D2 — 20 task pilot × 4 variants(2-3 天)

复用 D5 的 20 task selection(10 LM lipid + 10 random non-LM,seed=42),跑 4 variants:

```
Step 1: single (MiniMax)                    # baseline
Step 2: react (MiniMax)                     # A1 架构
Step 3: react+feedback (MiniMax)            # A2 架构,复用 D5 数字也可
Step 4: react+feedback+literature (MiniMax) # A3 完整,新跑

Step 4 跟 Step 3 比,隔离文献 tool 的 marginal 贡献。
```

**Acceptance D2**:
- 4 variants × 20 task = 80 narrative + 80 verdict 全落盘
- D5 数字应在 D2 重现(±5pt 噪声,MiniMax 非确定性)— 注:A2 §8 实测 ±10pt,所以 ≤10pt 都接受
- 4-way 主表 + LM lipid sub-group 分析
- **🆕 Non-LM contra% 监控**(A2 §4 暴露 +0.88pt 微涨):
  ```
  □ non-LM (n=10) contra% in +literature variant ≤ feedback variant + 1pt
  □ 否则 flag "literature introduces non-LM contra regression"
  □ 这个 finding 进 audit §4,不阻塞 D3 全量
  ```

### D3 — v4 全量 63 task × 3 variants(3-5 天)

跑 paper main figure 数据:

```
v4 全量:
  Step 1: single (MiniMax) × 63 task
  Step 2: react+feedback (MiniMax) × 63 task        # closed-loop 主架构
  Step 3: react+feedback+literature (MiniMax) × 63 task  # 完整 closed-loop
  
不跑: react-only (D2 已有 pilot 数据,不需全量)
不跑: cross-LLM (留 A4)
```

预期 wall time(基于 D0 并行度 5):
- 63 task × 3 variants × ~300s/task = 16h
- 实际并行后 ~3-4h wall

**Acceptance D3**:
- 3 variants × 63 task = 189 narrative + 189 verdict 全落盘
- 失败率 <5%(>3 task 失败需 escalate)
- v3 baseline(63 task × MiniMax single)从 v3 现有数据复用,不重跑

### D3.5 — N=3 reruns on 10 task subset(1-2 天)— **PAPER GATE**

**Why**:A2 §8 暴露 MiniMax 同 LLM 同 task 80% delta>5 claim。单次 v4 数字带 ±10pt 噪声,**paper 不能用单 sample**。

**做法**:

```
从 D3 全量 63 task 选 10 task subset (5 LM + 5 non-LM, 跨 5 bucket)
对每 task 跑 N=3 reruns × 3 variants = 90 verdict
计算每 cell mean ± std,paper 主表数字 = mean ± 95% CI

注意:N=3 reruns 用相同 task,只是 LLM call 重抽样
       不是重选 task,不是重 build benchmark
```

**Subset 选样**:
```
LM (5): WP167_seed{0,2,4,6,8}
non-LM (5): RAMP_P_000000016_seed{0,1}, RAMP_P_000053306_seed{0,1}, RAMP_P_000000398_seed0
```

**Acceptance D3.5**:
- 90 narrative + 90 verdict 落盘 (10 task × 3 variants × 3 reruns)
- 每 cell 计算 mean / std / 95% CI
- audit §1 主表数字附 ±CI
- 如果某 cell std 大于 mean 的 30%,flag "metric not reliable",paper 写明

**预算**:10 task × 3 variants × 3 reruns × ~120s/task (并行后) = ~3h wall + ~$5

### D3.6 — max_iter=3 ablation(1 天)— optional

**Why**:A2 §3 显示 17/20 task 用满 max_iter=2。LLM 还想继续改但被 budget 截断。

**做法**:

```
on D3.5 的 10 task subset, react+feedback variant only
跑 max_iter=3,记录 N3 verdict
对比:
  N2 (max=2 cap, 当前 default)
  N3 (max=3, 实验)
  
计算:
  - N3 vs N2 supported / contradicted delta
  - 如果 |Δ supported| < 0.5pt → 确认 max=2 够,paper 写明
  - 如果 N3 显著好(≥1pt 改善)→ 升级 default max=3
  - 监控 max_iter=3 时 rollback 触发率(可能涨)
```

**Acceptance D3.6**:
- 10 task × 3 reruns × max_iter=3 跑完
- decision: 接受 max=2 default 或升级 max=3
- audit §3 列表 N0/N1/N2/N3 quality 分布

**这是 optional**:如果 D3 + D3.5 + D4 已经超 18 天,可以砍掉 D3.6,留作 future ablation。

### D4 — Layer 6d KEGG SQL warning 修复 + 影响量化(1-2 天)

A2 audit §5 debt #6。**关键修正**:不只是修 warning 消失,**还要量化修复对 verdict 数字的影响**。

#### D4a — 修复 SQL warning(0.5 天)

```
定位 file:line(应在 verifier/layers/pathway_relationship.py 或类似)
修 SQL: pathwaySourceId → 正确 column name(可能是 sourceId 或 source_id)
单测覆盖
```

#### D4b — 修复前后量化对比(0.5-1 天)— **关键新增**

**Why**:A2 audit §5 debt #6 暗示 SQL warning 导致 Layer 6d **静默降级 supported claim 到 UNVERIFIABLE_V0**。修复后 verdict 数字会漂移。

**做法**:

```
在 5 task pilot 上跑 verdict 修复前 vs 修复后
记录 verdict 分布变化:
  
  | metric              | pre-fix | post-fix | Δ |
  | supported %         | ?       | ?        | ? |
  | contradicted %      | ?       | ?        | ? |
  | unverifiable_v0 %   | ?       | ?        | ? |
  | Layer 6d verdicts   | breakdown by claim type | 同左 | |

如果 |Δ| > 2pt(任一 metric):
  - **flag**: "A2 D5 数字基于 buggy verifier,不能跟 A3 数字直接比"
  - audit 必须分两块:A2-comparable (pre-fix) vs A3-only (post-fix)
  - paper 主表必须用 post-fix verifier 重跑 D5 (额外预算 ~5h)
  
如果 |Δ| ≤ 2pt:
  - 可接受为 noise,继续用 A2 D5 数字作 paper baseline
  - audit 写明 "Layer 6d SQL fix had negligible impact on aggregate"
```

**Acceptance D4**:
- SQL warning 消失
- 5 task pre/post fix verdict 对比表
- 决策落地:Δ>2pt 触发 D5 重跑,否则继续
- 单测覆盖修复点

### D5 — Audit + paper figure 数据(3-4 天)

`reports/agent/phase_a3_audit.md`:

#### 1. 5-way 主表(paper headline,带 95% CI)

数字格式:`mean ± CI95`(来自 D3.5 N=3 reruns)。Opus 列单次跑(无 reruns),CI 标 N/A。

| metric | A1 v3 single (Opus, n=18, no CI) | A1 react (Opus, n=18, no CI) | A3 single (MiniMax, n=63) | A3 feedback (MiniMax, n=63) | A3 +literature (MiniMax, n=63) |
|---|---:|---:|---:|---:|---:|
| supported %       | 14.10 | 20.69 | ? ± ? | ? ± ? | ? ± ? |
| contradicted %    | 2.93  | 2.94  | ? ± ? | ? ± ? | ? ± ? |
| unverifiable_v0 % | 71.89 | 64.31 | ? ± ? | ? ± ? | ? ± ? |

**注意**:
- A2 D5 数字(已知 single 10.32 / feedback 31.30 / contra 2.97)如果 D4 SQL fix 影响 >2pt,需要标注 "based on pre-fix verifier" 或重跑
- MiniMax 列必须有 ±CI(D3.5 N=3 reruns 输出),否则 reviewer 一定问

#### 2. v4 全量 vs 20 task pilot 一致性

```
20 task pilot D2 → v4 D3 数字(同 variant)
expected: ±3pt 噪声内
if 显著漂移 → flag,可能 v4 全量含 pilot 没的难 task
```

#### 3. 文献 tool 调用统计

- 每 variant 中 search_literature 调用率
- 哪类 claim 触发文献调用最多
- 文献调用前后 unsupported claim 改善率

#### 4. LM lipid sub-group(A1 +2.65pt regression / A2 -2.90pt 修复 → A3 是否进一步降?)

#### 5. Wall time 改善

- D0 并行化前后对比表
- v4 全量 63 task 实际 wall time

#### 6. Engineering debt(留 A4)
- Cross-LLM 适配未做
- MiniMax N=3 seeds 未做
- 文献 tool 调用率(若仍 <30%)说明什么

#### 7. 决策

```
✅ closed-loop + literature 显著改善 → 进 A4 (cross-LLM + paper)
⚠️ literature 加了但没改善 → 接受 A3 v0,paper 写 finding
❌ regression → debug
```

#### 8. Provenance

### D6 — Acceptance check

```
□ D0 并行化:5 task pilot ≤30 min wall
□ D0b retry-with-backoff:故意注入 503 验证 retry 工作 + 5xx/529 失败率 <1%
□ D1 literature 调用率 ≥60% on 5 task smoke(对比 A1 的 0%)
□ D2 20 task × 4 variants 数据齐
□ D2 non-LM contra% 监控:+literature 不引入 >1pt regression
□ D3 v4 63 task × 3 variants 数据齐
□ D3.5 N=3 reruns × 10 task subset:每 cell 有 mean ± CI95
□ D3.6 max_iter=3 ablation 决策落地(接受 max=2 或升级 max=3)
□ D4 Layer 6d SQL warning 消失
□ D4 SQL fix 修复前后 verdict 漂移量化(Δ>2pt 触发 D5 重跑)
□ D5 audit 完整(主表带 ±CI)
□ verifier 内部 logic 0 行改(只修 Layer 6d SQL bug)
□ A2 代码 0 行改(只扩 feedback_hints.py + 加 async runner)
□ branch clean + mergeable
```

---

## Pitfalls

1. **MiniMax rate limit**:并行度过高会 429。第一回合先测 rate limit(curl 多线程跑 10 个 chat,看几个失败)。可能并行度 3-5 就触顶。

2. **Verifier 内部并行 race condition**:Layer 6c (biological_claim) 用 RaMP sqlite,多线程读可能有锁。**不要用 multiprocessing,用 asyncio + connection pool**。

3. **search_literature abstract truncation 不能太狠**:截 200 chars LLM 看不出有用信息。500 chars + 前 2 句优先。

4. **Europe PMC 偶尔 timeout**:加 retry + 5s 超时。Tool 失败应 graceful 返回 `{"error": "europe_pmc_timeout"}`,不挂 ReAct loop。

5. **文献调用率刷分风险**:不要为了让 D1 acceptance 过线,在 prompt 里硬塞"必须调 search_literature"——这会让 LLM 在不需要时也调,污染 paper finding。**自然触发**才有意义。

6. **v4 全量跑出来如果跟 D2 pilot 数字差太多**(>5pt),可能是 pilot 选样有 bias。回头检查 task 难度分布。

7. **D3 v4 全量 wall time 不可控**:跑前先在 5 task 上验证并行度真的工作(单 task wall 真的降到 300s 内),再扩 63 task。否则容易跑一半发现要 20h,token 钱浪费。

8. **不要并行跑 D2 和 D3**:D3 v4 全量是 D2 pilot 通过后的扩展,不通过不要扩。

---

## Time budget

- D0 并行化 + retry: 5-7 天(最大不确定性,可能 D2 时还在调)
- D1 literature + feedback 联动: 5-7 天
- D2 20 task pilot: 2-3 天(D0 通过后)
- D3 v4 全量 63 task: 3-5 天
- **D3.5 N=3 reruns × 10 task: 1-2 天**(paper gate)
- **D3.6 max_iter=3 ablation: 1 天**(optional,可砍)
- D4 SQL fix + 影响量化: 1-2 天
- D5 audit: 3-4 天

**Total: 3-4 周**(D0 + D3.5 + D4b 是新增关键路径)

如果时间紧:
- D3.6 可砍(信息价值有限,paper 接受 max=2 default)
- 减负后 ~3 周

---

## First action checklist

第一回合:
1. 读 7 个 background 文件(尤其 A2 audit §5 debt + §8 finding + §9 selection bug)
2. 报告当前单 task wall time 分解(LLM call / verifier / tool 各占多少)
3. 报告 Layer 6d KEGG SQL warning 出现位置(file:line)+ 修复方向 + **预估对 verdict 数字影响**
4. 报告 search_literature 当前实现状态(stub or real)
5. 报告 MiniMax rate limit 测试结果(并行度上限)
6. 估算 v4 全量 63 task × 3 variants 在并行度 K 下的 wall time
7. **🆕 估算 D3.5 (10 task × 3 variants × 3 reruns = 90 verdicts) wall time + cost**
8. **🆕 提议 chat retry 的具体 backoff 策略**(spec 给的 10/30/60s 是否合理,看 MiniMax 实际恢复时间)
9. **🆕 D3.6 max_iter=3 是必做还是 optional**(看 D0+D1+D3.5 总预算后)
10. 任何 clarifying question

不要写代码 / 改 runner / 改 verifier,直到 confirm 这 10 项。

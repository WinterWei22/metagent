# MetAgent W19 — γ KB Tools(KEGG REST first,Reactome/PubMed deferred)

**Sprint type**: ✅ Add 新 verifier helper(KEGG REST client)+ 新 verifier layer(`kegg_kb_sub6`)+ ⚠ verifier-modify-warning(dispatcher add)+ 新引入外部 HTTP KB 工具到 verifier
**Duration**: 4-6 day(D0 + D1 dual audit + D2 RED + D3 GREEN + D4 Path X + D5 close-out)
**Date launched**: 2026-06-11
**Working tree**: `/home/weiwentao/workspace/llm_agent_metabolomics/metagent_v2/`
**Branch**: `metagent-v2`
**Predecessor**: W18 β sprint close-out commit `e0855d03`
**Model name**: **MetAgent**

---

## §0 Onboarding(在任何代码动作前必读)

### A. 战略上下文 — 为什么 γ 是 KEGG REST 而不是其他 KB

W18 β LLM-judge 实测 validate 了"verifier 端 LLM-as-tool"模式(59/63 task,UV -8.47pp),但 W18 D1.2 v4 audit 显示**剩 624 个 judge_uncoverable claim**——LLM-judge 帮不上,需要外部 KB 查询。

**用户 2026-06-08 战略 pivot**(`feedback_metagent_must_be_llm_driven` 2026-06-08 边界澄清):
- V3 deterministic 算法 ❌ 不暴露
- **KEGG REST / PubMed / Reactome / MetaboAnalyst REST 等 KB 查询工具 ✅ 可暴露**
- 系统级共享(ReAct + Verifier 都可调,role 不同)

### B. 为什么先 KEGG REST 不先 PubMed / Reactome

| KB 工具 | 覆盖 uncoverable 类型 | W18 D1.2 v4 量级估计 | 工程复杂度 | 优先级 |
|---|---|---|---|---|
| **KEGG REST** | 中间产物 / pathway-compound 关系 / 分子结构 | ~200-300 of 624 uncoverable | 中(REST + cache + parse)| **P1 W19** |
| Reactome API | pathway hierarchy / network | ~50-80 | 中-高(GraphQL)| P2 W20 |
| PubMed Search | literature citation 验真 | ~80-120 | 高(rate limit + ranking)| P3 W21 |
| MetaboAnalyst REST | canonical enrichment 重算 | ~30-50 | 低-中 | P4 maybe skip |

KEGG REST 单项预期 cover ~30-50% of uncoverable → UV 再降 5-10pp 进 26-31% 区间。一次只做一个 KB 工具,避免 scope 失控(W18 一次做 LLM-judge 已经 6 轮 patch)。

### C. W19 不做什么(铭刻于心)

| Non-goal | 理由 |
|---|---|
| ❌ 不接 Reactome / PubMed / MetaboAnalyst REST | W20+ 范畴 |
| ❌ 不动 LLM-judge layer(`llm_judge_sub6`)| W18 已 validate,保持稳定 |
| ❌ 不重启用 signal_sub6 dispatcher | W16 rollback 不变 |
| ❌ 不动 ReAct prompt | producer 端 W14 稳定 |
| ❌ 不改 SubsixSourceReport schema | W17 已锁,不重开 ⚠ schema-extend |
| ❌ 不改 `DEFAULT_MAX_FEEDBACK_ITERS=1` | W14 锁 |
| ❌ 不动 B1-core helper | ❌ 默认禁 |
| ❌ 不在 ReAct 端启用 KEGG REST(只 verifier 用)| W19 范畴限制,ReAct 端推 W20+ |
| ❌ 不写 paper narrative | 死命令 |

### D. 死命令(全部 active,2026-06-11 最新版)

1. **中文交流**,代码英文 — `feedback_language_chinese`
2. **MetAgent LLM-driven** — `feedback_metagent_must_be_llm_driven`(2026-06-11 W18 partial validation section)
3. **MiniMax remote API** — `reference_minimax_is_remote_api`,成本必从 `logs/concord/*.jsonl` 读实际
4. **每条回复结尾 2 段大白话总结** — `feedback_plain_summary_at_end`
5. **Verifier 修改三档准则**(2026-06-11 含新 ClaimVerdict aggregate semantics 死命令) — `feedback_verifier_modification_policy`
   - ✅ Add 新 layer / 新 helper / **新 KB tool 调用**(本 sprint 主菜)
   - ⚠ Modify dispatcher 路由(D3 触发)
   - **新增**:**新 ClaimVerdict 必须 D2 RED 前定 aggregate 语义**(W18 D3.5f 教训)
   - ❌ B1-core helpers 默认禁
6. **3 护栏**:tag `metagent-v2-base-b1@ed6243b` immutable / B1 paper 数据 immutable / pytest 14-fail floor 不退步
7. **UV sprint 必做 strict-vs-fuzzy 重分类** — `feedback_uv_sprint_must_reclassify_first`,target ≤ ceiling × 0.6
8. **Multi-paradigm 必做 data carrier audit** — `feedback_multi_paradigm_data_carrier_audit`,本 sprint D1 用 W18 attribution 数据
9. **Crash-time 必须 persist per-claim 中间状态** — `feedback_crash_time_data_preservation`(W18 D3.5f 新立)
10. **Verifier LLM-judge / KB 工具实施模式** — `reference_verifier_llm_judge_pattern`(W18 总结 8 项复用模板)
11. **不写 paper narrative** — `feedback_no_paper_writing_yet`
12. **设计决策存档** — `feedback_design_decisions_archive`,W19 D5 必写 `docs/decisions/2026-06-11_w19_kegg_rest_kb_tool.md`
13. **跨 session 通信通道** — `reference_conversation_channel`
14. **Strict TDD per-piece**

### E. 必读 memory 文件(D0 第一步)

```
feedback_language_chinese.md
feedback_proceed_with_defaults.md
feedback_metagent_must_be_llm_driven.md           # 2026-06-11 含 W18 partial validation
reference_minimax_is_remote_api.md
feedback_plain_summary_at_end.md
feedback_verifier_modification_policy.md          # 2026-06-11 含新 ClaimVerdict aggregate 条
feedback_no_paper_writing_yet.md
feedback_uv_sprint_must_reclassify_first.md
feedback_multi_paradigm_data_carrier_audit.md
feedback_crash_time_data_preservation.md          # W18 D3.5f 新立 必读
reference_verifier_llm_judge_pattern.md           # W18 总结 8 模板 必读
feedback_design_decisions_archive.md
project_metagent_v2_merge.md
reference_conversation_channel.md
```

### F. 必读项目工件(D0 第一步)

```
# W18 close-out
reports/agent/w18_llm_judge_close_out.md
docs/decisions/2026-06-09_w18_llm_judge_layer.md  # 含 W19 准备 checklist

# W18 attribution + uncoverable data
data/metagent/w18_dual_audit/claim_judge_fitness_inventory_v4.csv  # 624 uncoverable claim
data/metagent/w18_dual_audit/claim_judge_fitness_summary_v4.md
data/metagent/w18_path_x_post_llm_judge_full63_d5_clean/path_x_full63_results.jsonl  # 59 task baseline

# W17 / W16 reference
docs/decisions/2026-06-08_w17_subsix_source_report_schema_extension.md
reports/agent/w16_signal_sub6_d4_diagnostic.md

# W18 LLM-judge implementation(W19 复用基础)
verifier/layers/llm_judge_sub6.py
verifier/helpers/llm_judge_prompt.py
verifier/helpers/judge_response_parser.py
verifier/helpers/judge_cost_cap.py
verifier/helpers/build_judge_excerpt.py
verifier/helpers/contradicted_validator.py

# Dispatcher
verifier/agent.py
verifier/claim_table.py                           # W18 D3.5f patched

# Schema
schemas/sub6_report.py

# ReAct
concord/agent/react_runner.py
concord/agent/verifier_adapter.py
```

---

## §1 Goals & Non-Goals

### Goals

| ID | Goal |
|---|---|
| G1 | D1.1 carrier smoke check 沿用 W18 D1.1 模式 |
| G2 | D1.2 strict-vs-fuzzy 重分类 624 uncoverable claim 分 `kegg_strict`(KEGG REST 能 cover)vs `kegg_uncoverable`(Reactome / PubMed / 其他)。**Target ≤ ceiling × 0.6**(死命令) |
| G3 | D2 RED ≥25 cases 覆盖 KEGG REST client + 新 layer + dispatcher + cost cap + contract test。**HEDGED-like 新 ClaimVerdict 若引入,必须含 aggregate 语义 RED test**(W18 D3.5f 教训) |
| G4 | D3 GREEN 实现 `verifier/helpers/kegg_rest_client.py`(含 cache + rate limit)+ `verifier/layers/kegg_kb_sub6.py` + dispatcher add(⚠ verifier-modify-warning)+ per-Path-X cost cap 复用 W18 `judge_cost_cap.py` |
| G5 | D4 Path X full-63 verify:UV 再降 ≥ 4pp(W18 36.45% → ≤ 32.5%),pathway ≥ 84%,iter-2 = 0,KEGG REST 调用计费(免费但要 rate limit),total cost ≤ $25 |
| G6 | D5 写 `docs/decisions/2026-06-11_w19_kegg_rest_kb_tool.md` + close-out report |

### Non-Goals

- ❌ 不接 Reactome / PubMed / MetaboAnalyst REST(W20+)
- ❌ 不在 ReAct 端启用 KEGG REST(W20+)
- ❌ 不动 LLM-judge layer 内部逻辑(W18 已 validate)
- ❌ 不动 schema / signal_sub6 / iter cap / B1-core
- ❌ 不写 paper narrative
- ❌ 不在本 sprint 顺手做 Crash-time data preservation refactor(单独 sprint 范畴)

---

## §2 Architecture(D1 audit 后细化)

### Layer 设计草稿

```python
# verifier/layers/kegg_kb_sub6.py
"""
W19 γ: KEGG REST KB verifier layer.

Fires after LLM-judge returns UV for claim types where KEGG can help:
  - Biology background ("X is intermediate of Y") → KEGG REACTION lookup
  - Pathway-compound relationship → KEGG PATHWAY query
  - Molecular formula / structure → KEGG COMPOUND query

Conservative:
  - KEGG REST hit + exact match → SUPPORTED, confidence 0.95
  - KEGG REST hit + partial match → HEDGED, confidence 0.7
  - KEGG REST hit + clear mismatch → CONTRADICTED, confidence 0.95(double-confirm gate 同 W18)
  - KEGG REST miss / API error → UV
"""

KB_ELIGIBLE_TYPES = {
    "BIOLOGY_INTERMEDIATE",     # "X is intermediate of Y"
    "PATHWAY_MEMBERSHIP_KB",    # "X is in pathway Y" 引用 KEGG 数据库
    "COMPOUND_FORMULA",         # "X has molecular formula Y"
    # 不含 GROUNDED / BIOLOGICAL / FACTUAL(W18 LLM-judge 处理)
    # 不含 SIGNAL_*(deterministic layer 处理)
}

KB_COST_CAP_USD = 0.0  # KEGG REST 免费,但 rate limit / latency 是 cost
KB_RATE_LIMIT_PER_SEC = 3  # KEGG official 推荐
KB_TIMEOUT_SEC = 5
```

### Dispatcher 接入(⚠ verifier-modify-warning)

```python
# verifier/agent.py:_verify_per_claim_sub6
def _verify_per_claim_sub6(claim, source_report, ...):
    # ... existing layers ...
    
    # W18 β: LLM-judge catch-all
    if prior_verdict == UV and claim_type in JUDGE_ELIGIBLE_TYPES:
        judge_verdict = verify_llm_judge_sub6(...)
        if judge_verdict.confidence >= 0.85:
            return judge_verdict
    
    # NEW W19 γ: KEGG KB catch-all(after LLM-judge,post-UV only)
    if prior_verdict == UV and claim_type in KB_ELIGIBLE_TYPES:
        kb_verdict = verify_kegg_kb_sub6(claim, source_report, ...)
        if kb_verdict.confidence >= 0.85:
            return kb_verdict
    
    return UV
```

### Helper modules

- `verifier/helpers/kegg_rest_client.py` — HTTP client + rate limit + cache + retry
- `verifier/helpers/kegg_query_builder.py` — claim text → KEGG REST query
- `verifier/helpers/kegg_response_parser.py` — REST response → structured evidence
- `verifier/helpers/kegg_cache.py` — local LRU cache(KEGG 数据稳定,适合 cache)

### Crash-time preservation 设计(死命令)

`feedback_crash_time_data_preservation` 死命令要求:
- KEGG KB layer 每个 per-claim verdict **写入 task json 后才进下一条**
- aggregate 函数读取 list,不阻塞 partial write
- 写 `verifier/helpers/retroactive_aggregate.py` 与正常 aggregate 共享同一 read interface
- D2 RED 含"模拟 KB layer 中途 crash → assert per-claim list 完整"测试

---

## §3 Daily Breakdown

### D0(~0.3d)— Onboarding

1. 读 §0.D 14 个 memory 文件
2. 读 §0.F 项目工件全集
3. 报 git status + branch + HEAD(应 `metagent-v2 @ e0855d03` 或更新)
4. pytest baseline(预期 14 fail / 1503 pass / 14 skip)
5. 实测确认 W18 D3.5f patch 状态(`verifier/claim_table.py:48` 含 NEEDS_HUMAN_REVIEW)
6. 实测确认 W18 close-out artifacts 存在
7. 不进 D1 直到 user OK

### D1(~0.7-1d)— Dual Audit + Strict-vs-Fuzzy + Carrier Audit

#### D1.1 W18 carrier smoke check(~0.2d)

用 W18 D5 clean aggregate(59 task)quick check:
- 哪些 task 含 biology background / intermediate claim
- KEGG ID(`hsa00450` 等)出现频率
- Compound ID(`C01234` 等)出现频率
- Pathway name + KEGG: prefix 出现频率

输出 `data/metagent/w19_dual_audit/w18_kegg_context_smoke.md`。

#### D1.2 Strict-vs-Fuzzy KB fitness(~0.4-0.6d)

从 W18 D1.2 v4 `claim_judge_fitness_inventory_v4.csv` 的 624 `judge_uncoverable` 子集做 strict-vs-fuzzy:

**rubric**:
- **kegg_strict**:KEGG REST 能 cover
  - "X is intermediate of Y in KEGG pathway Z"
  - "X has molecular formula C..."
  - "X is in pathway KEGG:hsa00450"
  - "Reaction R01234 converts A to B"
- **kb_uncoverable**:其他 KB 才能 cover
  - Reactome network claim(W20)
  - PubMed literature(W21)
  - SMPDB / WikiPathways
  - 纯生物学背景无 KB 引用

**Spot-check 20 sample,seed `random.seed(20260611)`,≥80% 一致率守 HG-2**(W17/W18 教训)。

**Target**:`strict_count / total_uncoverable × 0.6` UV 降幅。预估 ceiling 5-8pp,target 3-5pp。

**Stop**:< 1pp ROI 不值,可能跳到 W20 Reactome 或缩 scope。

输出:`data/metagent/w19_dual_audit/claim_kegg_fitness_inventory.csv` + `summary.md` + `spot_check.csv`。

#### D1.3 KEGG REST cost / rate-limit projection(~0.1d)

- 每 Path X 估 KEGG REST 调用次数(per-task × KB_ELIGIBLE_TYPES claim 数)
- 估单次 HTTP latency × concurrency → wall time impact
- KEGG REST 免费但 3 req/sec rate limit → 750 req per Path X = 250 sec = 4 min 额外 wall
- 输出 `cost_projection.md`

#### D1.4 Carrier audit per 死命令

按 `feedback_multi_paradigm_data_carrier_audit`:
- 列 claim 端引用的 KB(KEGG / Reactome / PubMed / etc.)
- 列 verifier 端实际可访问 carrier(W18 SubsixSourceReport + 新 KEGG REST client)
- MISSING_CARRIER:Reactome / PubMed / SMPDB 等仍缺,这些 claim 必 UV fallback,不 CONTRADICTED

#### D1.5 Decision doc draft(~0.1d)

写 `docs/decisions/2026-06-11_w19_kegg_rest_kb_tool.md` draft。

### D2(~0.5-0.8d)— RED

#### D2.0 — 前置 grep(5 min)

确认 ClaimType 是否需要新增 `BIOLOGY_INTERMEDIATE` / `PATHWAY_MEMBERSHIP_KB` / `COMPOUND_FORMULA` 等:
- grep verifier/grammar.py 现有 ClaimType enum
- 若需新增 → ⚠ schema-extend-warning + ping user
- 若现有 `BIOLOGICAL` 等已够 → 直接 reuse

**新 ClaimVerdict 处理(死命令)**:KEGG KB 是否引入 HEDGED / 新 verdict?若引入,**D2 RED 必须先含 aggregate 语义测试**(`feedback_verifier_modification_policy` 新条)。预计 W19 复用 W18 verdict 集合(SUPPORTED/CONTRADICTED/UV/HEDGED),不引入新。

#### D2.1 — `tests/test_w19_kegg_rest_client.py`(≥8 case)

- HTTP GET 成功 → 解析返回
- HTTP 404 → 返 None
- HTTP 500 → retry 3 次后返 None
- Rate limit > 3 req/sec → 自动 sleep
- Cache hit → 不调 HTTP
- Cache miss → 调 HTTP + 缓存
- Timeout 5 sec → 返 None
- API endpoint malformed → 异常

#### D2.2 — `tests/test_w19_kegg_kb_sub6.py`(≥8 case)

- claim_type 在 KB_ELIGIBLE_TYPES + KEGG hit + exact → SUPPORTED + confidence 0.95
- partial match → HEDGED + 0.7
- clear mismatch + double-confirm pass → CONTRADICTED + 0.95
- mismatch + double-confirm fail → HEDGED degrade
- KEGG miss → UV
- KEGG API error → UV(不 CONTRADICTED)
- claim_type 不 eligible → 不调 KEGG REST + UV
- prior_verdict ≠ UV → 不调

#### D2.3 — `tests/test_w19_kegg_kb_dispatcher_integration.py`(≥4 case)

- LLM-judge 已 SUPPORTED → kegg_kb_sub6 不 fire
- LLM-judge UV + claim_type in KB_ELIGIBLE → kegg_kb_sub6 fire
- LLM-judge UV + claim_type 不 eligible → 留 UV
- W12 / W18 既有 preservation tests 不退步

#### D2.4 — `tests/test_w19_kegg_rest_contract.py`(实调 KEGG REST 一次,≥3 case)

- 真调 `https://rest.kegg.jp/get/cpd:C01697` → assert 解析成功
- 真调 `https://rest.kegg.jp/list/pathway/hsa` → assert 含 hsa00450
- 真调 unknown ID → 404 handled

**标 `@pytest.mark.requires_network`** 让 CI 可选跑。

#### D2.5 — `tests/test_w19_kegg_cost_cap.py`(≥3 case)

W18 `judge_cost_cap` 复用。KEGG REST 免费但加 `kb_request_count` tracker 防 fan-out 失控:
- per-Path-X request count > 1000 → 拒绝
- per-task request count > 50 → 拒绝
- Reset per Path X

#### D2.6 — Crash-time preservation test(死命令)

`tests/test_w19_kegg_crash_preservation.py`(≥2 case):
- 模拟 KB layer 中途 KEGG API error → assert per-claim list 持久化已完成的 claim
- 模拟 aggregate KeyError → assert retroactive recompute 可用现有数据

Commit: `test(verifier): W19 D2 RED — KEGG REST KB layer + helpers + dispatcher + cost cap + contract + crash preservation`

跑 RED → 全 fail。≥28 cases。

### D3(~1.5-2d)— GREEN

按 D2 piece 顺序逐绿:

1. `verifier/helpers/kegg_rest_client.py` → RED → GREEN → commit `feat(verifier): W19 D3 — KEGG REST client + cache + rate limit`
2. `verifier/helpers/kegg_query_builder.py` → commit
3. `verifier/helpers/kegg_response_parser.py` → commit
4. `verifier/helpers/kegg_cache.py` → commit
5. `verifier/layers/kegg_kb_sub6.py` → commit
6. Dispatcher 接入 `verifier/agent.py`(⚠ verifier-modify-warning commit body)
7. Crash-time persist helper(若现有 verifier_run 不自动 persist,需 helper)

每 commit 后跑:
- `pytest tests/test_w19_*.py -q` → 相关 GREEN
- `pytest tests/` 全 repo → ≤ 14 fail
- W12-W18 preservation:`pytest tests/test_w18_*.py tests/test_w17_*.py tests/test_signal_*.py tests/test_factual_sub6*.py tests/test_w16_rollback_*.py -q` → 0 退步

Dispatcher commit body:
```
[verifier-modify-warning]

This commit adds kegg_kb_sub6 catch-all to _verify_per_claim_sub6 dispatcher
AFTER llm_judge_sub6, per feedback_verifier_modification_policy ⚠ tier.

Changes:
- Add kegg_kb_sub6 case AFTER llm_judge_sub6 (which is after deterministic layers)
- Fires only when llm_judge returned UV AND claim_type in KB_ELIGIBLE_TYPES
- LLM-judge logic unchanged (W18 β preserved)
- signal_sub6 catch-all remains DISABLED (W16 rollback preserved)
- iter cap unchanged
- B1-core unchanged

KEGG REST invokes external HTTP API (rate-limited at 3 req/sec).
HG-11 false CONTRADICTED rate verified via D4 manual review.

B1 paper data unaffected (verifier-only behavior change).
B1 test floor preserved (verify in D4).

Decision doc: docs/decisions/2026-06-11_w19_kegg_rest_kb_tool.md
```

### D4(~0.5-1d)— Path X full-63 Verify

1. 跑 Path X full-63,输出 `data/metagent/w19_path_x_post_kegg_kb/`:
   - `path_x_full63_results.jsonl`
   - `summary.md`
   - LLM log + KB request log
2. 算 metrics:

| 指标 | 目标 | W18 D5 baseline |
|---|---|---|
| UV rate | ≤ 32.5%(降 ≥4pp from W18 36.45%) | 36.45% |
| Pathway accuracy | ≥ 84% | 88.1% |
| iter-2 deg | = 0 | 0 |
| Total cost | ≤ $25 | $24.06 累计 W18 |
| KEGG REST request count | report | n/a |
| KEGG REST hit rate | report | n/a |
| New layer fire rate | report | n/a |
| New layer conversion rate(% non-UV) | ≥ 20% | n/a |

3. Hard Gate verify(§4)
4. 20-sample CONTRADICTED 手工 TP/FP

### D5(~0.3d)— Close-out

按 W18 D5 模板。

---

## §4 Hard Gates(全部 PASS 才能 close-out)

| Gate | Target | Verify |
|---|---|---|
| HG-1 | D1.1 W18 carrier smoke check 完成 | summary.md |
| HG-2 | D1.2 LLM-vs-human 20-sample agreement ≥80% | spot-check |
| HG-3 | D1.2 strict ceiling × 0.6 target ≥ 1pp | summary |
| HG-4 | D1.3 KEGG REST projection 不超 KEGG rate limit | projection.md |
| HG-5 | D2 RED ≥28 case 全 fail | pytest output |
| HG-6 | D2 含 crash preservation test(死命令) | code review |
| HG-7 | D4 UV drop ≥ target(从 D1.2 算)| Path X jsonl |
| HG-8 | D4 pathway ≥ 84% | 同上 |
| HG-9 | D4 iter-2 = 0 | 同上 |
| HG-10 | D4 total cost ≤ $25 | jsonl |
| HG-11 | D4 false CONTRADICTED ≤ 30%(20-sample 手工 TP ≥ 70%)| review |
| HG-12 | pytest 14-fail floor 不退步 | full repo |
| HG-13 | W12-W18 既有测试 0 退步 | focused |
| HG-14 | B1-core helper 未碰 | git diff audit |
| HG-15 | signal_sub6 dispatcher catch-all 仍 DISABLED | grep |
| HG-16 | iter cap 未改 | grep |
| HG-17 | SubsixSourceReport schema 未改 | git diff |
| HG-18 | LLM-judge layer 内部逻辑未碰 | grep |
| HG-19 | 新 ClaimVerdict 若引入,aggregate 语义已定 | claim_table.py check |
| HG-20 | KEGG REST 错误恢复:API error 不 CONTRADICTED | unit + manual review |

---

## §5 Risks & Stop Conditions

| Risk | Stop trigger | User decision |
|---|---|---|
| D1.2 strict ceiling × 0.6 < 1pp | KEGG REST ROI 不值 sprint | YES option {A: 缩 scope / B: pivot W20 Reactome / C: 跳 γ 整体} |
| D1.2 spot-check < 80% | rubric 模糊 | YES W17/W18 retry 流程 |
| KEGG REST rate limit / quota / outage | 整体 unavailable | YES — local cache + UV fallback,W19 部分价值仍在 |
| D3 dispatcher reorder | scope creep | YES option {A: 接受 + warning / B: 缩 scope} |
| D4 pathway < 84% | spurious CONTRADICTED 影响 | YES STOP |
| D4 iter-2 > 0 | W14 锁破 | YES STOP immediately |
| D4 UV drop < target | HG-7 fail | YES option {A: partial close / B: 调阈值 retry / C: 重审 D1 ceiling} |
| D4 total cost > $25 | budget cap | YES STOP |
| D4 CONTRADICTED TP < 70% | judge hallucinates | YES STOP retry |
| 任何 commit 触动 B1-core | HG-14 | YES STOP immediately |
| 任何 schema 改 | HG-17 | YES STOP immediately |
| 任何 LLM-judge layer 内逻辑改 | HG-18 | YES STOP(W18 已 validate 不动) |
| 新 ClaimVerdict 无 aggregate 语义(W18 D3.5f 教训) | HG-19 | YES STOP — 必先补 |

---

## §6 Banned Phrases

- 不写 paper narrative
- 不说 "$0 local"
- 大白话总结不用 strict-TDD / commit / sprint / RED / GREEN / Hard Gate
- 不 push remote / 不 force tag / 不删 tag

---

## §7 输出工件清单(D5 末必须存在)

```
# D1
data/metagent/w19_dual_audit/
  ├─ w18_kegg_context_smoke.md
  ├─ claim_kegg_fitness_inventory.csv
  ├─ claim_kegg_fitness_summary.md
  ├─ claim_kegg_fitness_spot_check.csv
  ├─ cost_projection.md
  └─ carrier_audit.md

# D2 RED
tests/test_w19_kegg_rest_client.py
tests/test_w19_kegg_kb_sub6.py
tests/test_w19_kegg_kb_dispatcher_integration.py
tests/test_w19_kegg_rest_contract.py
tests/test_w19_kegg_cost_cap.py
tests/test_w19_kegg_crash_preservation.py

# D3 GREEN
verifier/helpers/kegg_rest_client.py
verifier/helpers/kegg_query_builder.py
verifier/helpers/kegg_response_parser.py
verifier/helpers/kegg_cache.py
verifier/layers/kegg_kb_sub6.py
verifier/agent.py  (⚠ verifier-modify-warning)

# D4
data/metagent/w19_path_x_post_kegg_kb/
  ├─ path_x_full63_results.jsonl
  ├─ summary.md
  └─ contradicted_manual_review.md
logs/concord/w19_path_x_post_kegg_kb.jsonl
logs/concord/w19_kegg_request_log.jsonl

# D5
docs/decisions/2026-06-11_w19_kegg_rest_kb_tool.md
reports/agent/w19_kegg_kb_close_out.md
conversation/master/{...}_w19-sprint-close-out.md
```

---

## §8 Memory updates expected at D5

- 可能 append `reference_verifier_llm_judge_pattern` — KB tool 模式补充(HTTP cache / rate limit / retry)
- 可能新 `reference_kegg_rest_query_patterns.md` — KEGG REST endpoint cheat sheet

---

## §9 First Action upon receiving this prompt

1. 中文 ack + 2 段大白话总结
2. 执行 §3 D0 全 7 步
3. Ping user with D0 报告
4. **不进 D1 直到 user OK**
5. D1.2 strict-vs-fuzzy 算出 target 后必 ping user 等 OK 才进 D1.3
6. 任何模糊点 → 在 ping 里 flag,不默默假设

---

## §10 决断红线(立即停 ping)

- Memory 文件读不到
- W18 数据(`full63_d5_clean/path_x_full63_results.jsonl`,`w18_dual_audit/claim_judge_fitness_inventory_v4.csv`)缺失
- branch ≠ `metagent-v2` 或 worktree ≠ `metagent_v2`
- HEAD < `e0855d03`(W18 close-out)
- pytest baseline > 14 fail
- W17/W18 数据契约破(schema / LLM-judge layer 状态)
- signal_sub6 dispatcher 居然 enabled
- iter cap 改变
- 死命令冲突
- 新 ClaimVerdict 引入但 aggregate 语义未定(W18 D3.5f 教训死命令)
- Crash-time persistence 不可实现(W18 D3.5f 教训死命令)

**Ready. Go.**

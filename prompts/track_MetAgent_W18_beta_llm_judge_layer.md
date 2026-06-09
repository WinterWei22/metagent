# MetAgent W18 — β LLM-judge verifier layer (llm_judge_sub6)

**Sprint type**: ✅ Add 新 layer + ⚠ verifier-modify-warning(dispatcher add)+ 新引入 LLM-as-tool 模式到 verifier
**Duration**: 4-6 day(D0 + D1 dual audit + D2 RED + D3 GREEN + D4 Path X + D5 close-out)
**Date launched**: 2026-06-09
**Working tree**: `/home/weiwentao/workspace/llm_agent_metabolomics/metagent_v2/`
**Branch**: `metagent-v2`
**Predecessor**: W17 sprint close-out commit `95779f06`
**Model name**: **MetAgent**

---

## §0 Onboarding(在任何代码动作前必读)

### A. 战略上下文 — 为什么 β 是 LLM-judge 而不是 signal_sub6 重建

W16 D4 失败之后,用户 2026-06-08 拍板 α → β → γ 路线。**用户在 W17 close-out 后明确选择跳过 signal_sub6 重建,直接做 LLM-judge layer**——理由:

1. **deterministic layer 路线已撞墙**:W16 D4 signal_sub6 是 deterministic source-aware lookup,即使 W17 α 给了 method-keyed carrier,deterministic 路线对 W15 attribution 里的 67.8% NONE bucket(biology background / 通用表述)依然无能为力
2. **LLM-judge 一步触达更大 ceiling**:NONE bucket 是 verifier 想 cover 但 deterministic 写不出 rule 的部分,只有 LLM 能做语义判断
3. **架构哲学一致**:`feedback_metagent_must_be_llm_driven` 死命令(2026-06-08 更新版)明确"LLM-judge 是 verifier 工具不是反过来",β 正是这个原则的实施
4. **W17 α 已经把数据通道铺好**:LLM-judge 可以 leverage method-keyed carrier,signal_sub6 改 deterministic 重建反而浪费 α 投资

### B. W18 不做什么(铭刻于心)

| Non-goal | 理由 |
|---|---|
| ❌ 不重建 signal_sub6 deterministic 层 | W16 D4 已证明 deterministic 撞墙,LLM-judge 是替代方案 |
| ❌ 不重启用 signal_sub6 dispatcher catch-all | 留 disabled,layer 代码作为历史保留 |
| ❌ 不接 KEGG REST / PubMed / Reactome 外部 KB(W19 γ 范畴) | scope discipline |
| ❌ 不动 ReAct prompt(producer 端 W14 已稳) | scope |
| ❌ 不改 `DEFAULT_MAX_FEEDBACK_ITERS=1`(W14 锁) | iter-2 deg 锁不许动 |
| ❌ 不改 SubsixSourceReport schema(W17 已扩,本 sprint 不再动) | scope |
| ❌ 不改 B1-core helper(`claim_extractor` / `feedback_hints` / `_extract_classify`) | ❌ 默认禁 |
| ❌ 不写 paper narrative | 死命令 |

### C. 死命令(全部 active,2026-06-09 更新版)

1. **中文交流**,代码英文 — `feedback_language_chinese`
2. **MetAgent LLM-driven** — `feedback_metagent_must_be_llm_driven`(2026-06-08 版本)
   - V3 deterministic 富集算法 ❌ 不暴露 LLM
   - **KB 工具 ✅ 可暴露**(本 sprint 暂不接,W19 γ 范畴)
   - **LLM-as-judge ✅ 是 verifier 工具**,本 sprint 正是这个模式的实施
3. **MiniMax remote API** — `reference_minimax_is_remote_api`
   - 成本必从 `logs/concord/*.jsonl` 读实际值,禁说 "$0 local"
   - 本 sprint Path X cost 会因为 LLM-judge 调用上涨,预算 ≤ $15
4. **每条回复结尾 2 段大白话总结** — `feedback_plain_summary_at_end`
5. **Verifier 修改三档准则**(2026-06-09 含 concord-modify 子条) — `feedback_verifier_modification_policy`
   - ✅ Add 新 layer 文件 / 新 helper / 新 dispatcher route / **新 verifier 层的 LLM tool 调用**(本 sprint 主菜)
   - ⚠ `[verifier-modify-warning]`:改 verifier 内部判定 / dispatcher 路由(本 sprint dispatcher add 算 ⚠)
   - ⚠ `[concord-modify-warning]`:改 `concord/agent/*.py`(本 sprint 不预期碰)
   - ⚠ `[schema-extend-warning]`:改 schema 字段(本 sprint 不预期碰)
   - ❌ B1-core helpers / 改字段类型 / 删字段:默认禁
6. **3 护栏**:tag `metagent-v2-base-b1@ed6243b` immutable / B1 paper 数据 immutable / pytest 14-fail floor 不退步
7. **UV sprint 必做 strict-vs-fuzzy 重分类** — `feedback_uv_sprint_must_reclassify_first`
   - 本 sprint D1 用 W17 D1.5 v3 数据为基础,再做 W18 特定 strict-vs-fuzzy(LLM-judge 能 cover vs 不能 cover)
   - **target ≤ ceiling × 0.6**(死命令)
8. **Multi-paradigm verification 必做 data carrier audit** — `feedback_multi_paradigm_data_carrier_audit`
   - W17 已做过,W18 D1 做"smoke check + claim_type fit"延续
9. **不写 paper narrative** — `feedback_no_paper_writing_yet`
10. **设计决策存档** — `feedback_design_decisions_archive`
    - W18 D5 必写 `docs/decisions/2026-06-09_w18_llm_judge_layer.md`
11. **跨 session 通信通道** — `reference_conversation_channel`
12. **Strict TDD per-piece**,每个 piece RED → GREEN 独立 commit

### D. 必读 memory 文件(D0 第一步)

```
feedback_language_chinese.md
feedback_proceed_with_defaults.md
feedback_metagent_must_be_llm_driven.md          # 2026-06-08 更新,V3 vs KB vs LLM-judge 边界
reference_minimax_is_remote_api.md
feedback_plain_summary_at_end.md
feedback_verifier_modification_policy.md         # 2026-06-09 含 concord-modify 子条
feedback_no_paper_writing_yet.md
feedback_uv_sprint_must_reclassify_first.md
feedback_multi_paradigm_data_carrier_audit.md    # 2026-06-09 含 W17 D1.5 v3 教训
feedback_design_decisions_archive.md
project_metagent_v2_merge.md
reference_conversation_channel.md
```

### E. 必读项目工件(D0 第一步)

```
# W17 close-out
reports/agent/w17_evidence_parity_close_out.md
docs/decisions/2026-06-08_w17_subsix_source_report_schema_extension.md

# W17 D1.5 v3 paradigm audit data(W18 D1 基础)
data/metagent/w17_carrier_audit/claim_paradigm_inventory_v3.csv
data/metagent/w17_carrier_audit/claim_paradigm_summary.md
data/metagent/w17_carrier_audit/carrier_audit_crosstab.md
data/metagent/w17_carrier_audit/proposed_schema_fields.csv

# W16 D4 失败诊断(W18 风险参考)
reports/agent/w16_signal_sub6_d4_diagnostic.md

# W15 attribution(全局 UV 桶分布)
docs/decisions/2026-05-26_uv_root_cause_attribution_framework.md
data/metagent/w15_uv_attribution/attribution_v2.csv

# Verifier 当前状态
verifier/agent.py                              # dispatcher,看 _verify_per_claim_sub6
verifier/layers/factual_sub6.py                # W12 layer 参考(本 sprint 不动)
verifier/layers/signal_sub6.py                 # 暂禁层(W18 不重建,留为历史)
verifier/helpers/enrichment_lookup.py          # signal lookup helper(参考,不动)

# ReAct + adapter(W17 D3 改过的,本 sprint 不动)
concord/agent/react_runner.py                  # iter cap = 1 锁
concord/agent/verifier_adapter.py              # method-keyed carrier passthrough(W17)

# Schema(W17 D3 扩字段,本 sprint 不动)
schemas/sub6_report.py
```

---

## §1 Goals & Non-Goals

### Goals

| ID | Goal |
|---|---|
| G1 | D1 dual audit:**(a) W17 carrier smoke check**(确认 carrier 通到 verifier 仍工作)+ **(b) claim_type × LLM-judge fitness 分类**(哪些 claim_type 适合 LLM-judge,哪些 LLM-judge 帮不上) |
| G2 | D1 strict-vs-fuzzy 重分类:UV claim 全集分 LLM-judge_strict / fuzzy_uncoverable 二分,算 strict ceiling,target ≤ ceiling × 0.6 |
| G3 | D2 RED 写 unit + dispatcher integration + cost cap 测试,≥15 cases |
| G4 | D3 GREEN 实现 `verifier/layers/llm_judge_sub6.py` + helper(prompt template / evidence pointer parser / cost cap)+ dispatcher add 新 case(post-UV catch-all,⚠ verifier-modify-warning) |
| G5 | D4 Path X full-63 verify:UV 下降 ≥ target,pathway ≥ 84%,iter-2 = 0,LLM-judge incremental cost ≤ $2,Path X 总 ≤ $15,B1 floor 14 |
| G6 | D5 写 `docs/decisions/2026-06-09_w18_llm_judge_layer.md` 决策文档 + W18 close-out report |

### Non-Goals

- ❌ 不重建 signal_sub6 deterministic 层
- ❌ 不接外部 KB API(KEGG REST / PubMed 等,W19 γ 范畴)
- ❌ 不动 ReAct prompt
- ❌ 不改 `DEFAULT_MAX_FEEDBACK_ITERS=1`
- ❌ 不改 SubsixSourceReport schema(W17 已扩)
- ❌ 不动 factual_sub6 / set_enrichment / signal_sub6 等已有 layer
- ❌ 不动 B1-core helper
- ❌ 不写 paper narrative
- ❌ 不在本 sprint 顺手做 W19 γ / 优化 prompt 等

---

## §2 Architecture(D1 audit 后细化)

### 当前 verifier dispatcher 状态(W17 close-out 后)

```
_verify_per_claim_sub6(claim, source_report):
    layer A: kegg_pathway_lookup
    layer B: ... (existing layers)
    factual_sub6                   # W12
    ... (other layers)
    # signal_sub6 catch-all DISABLED (W16 rollback @ 5933cdd4)
    return UV  # 现状:所有未命中的 claim 直接 UV
```

### W18 β 目标

```
_verify_per_claim_sub6(claim, source_report):
    layer A: kegg_pathway_lookup
    layer B: ...
    factual_sub6                   # W12
    ... (other layers)
    # signal_sub6 catch-all 仍 DISABLED
    
    # NEW W18: llm_judge_sub6 post-UV catch-all
    if prior_verdict == UV and claim_type in JUDGE_ELIGIBLE_TYPES:
        judge_verdict = verify_llm_judge_sub6(claim, source_report, claim_type, narrative_excerpt)
        if judge_verdict.confidence >= JUDGE_CONFIDENCE_THRESHOLD:
            return judge_verdict
        # confidence 不够 → 留 UV(judge 不强行升级)
    
    return UV
```

### `verifier/layers/llm_judge_sub6.py` 设计草稿(D2 RED 时细化)

```python
"""
W18 β: LLM-judge verifier layer.

Uses MiniMax to grade claims that deterministic layers leave UV.
Default conservative:
- confidence >= 0.85 → SUPPORTED / CONTRADICTED
- confidence < 0.85 → HEDGED with feedback hint
- confidence < 0.5 → UV (give up)

CONTRADICTED requires double confirmation:
- confidence >= 0.90 AND
- evidence_pointer matches actual carrier field AND
- rationale cites specific value mismatch
Otherwise degrade to HEDGED.

This implements 'verifier 工具化' per feedback_metagent_must_be_llm_driven.
LLM-judge is verifier's tool, not the reverse.
"""

JUDGE_ELIGIBLE_TYPES = {
    ClaimType.BIOLOGY_BACKGROUND,    # NONE bucket — biology free-form
    ClaimType.SIGNAL_AMBIGUOUS,      # 数值带方法但 deterministic 查不到精确匹配
    ClaimType.CROSS_METHOD,          # multi-paradigm consensus claim
    ClaimType.PATHWAY_MEMBERSHIP_FUZZY,   # 不能 exact match 但语义可能对
    # 不含 FACTUAL_ID(factual_sub6 处理)
    # 不含 ENRICHMENT_NUMERIC_EXACT(B 层处理)
    # 不含 LITERATURE_REFERENCE(留 W19 γ PubMed)
}

JUDGE_CONFIDENCE_THRESHOLD = 0.85
CONTRADICTED_CONFIDENCE_THRESHOLD = 0.90
PER_PATH_X_COST_CAP_USD = 2.00

def verify_llm_judge_sub6(claim, source_report, claim_type, narrative_excerpt) -> Verdict:
    if claim_type not in JUDGE_ELIGIBLE_TYPES:
        return UV  # 类型不 eligible,不调 LLM
    
    # Cost cap check(累积 per Path X)
    if _current_path_x_cost() > PER_PATH_X_COST_CAP_USD:
        return UV  # 超预算,直接 UV
    
    prompt = _build_judge_prompt(claim, source_report, claim_type, narrative_excerpt)
    response = minimax_call(prompt, temperature=0.0, json_mode=True)
    parsed = _parse_judge_response(response)
    
    if parsed.confidence < 0.5:
        return UV
    
    if parsed.verdict == "CONTRADICTED":
        if not _validate_contradicted(parsed, source_report):
            # degrade to HEDGED
            return Verdict(HEDGED, layer="llm_judge_sub6",
                          quality_score=0.6,
                          feedback_hint=parsed.rationale,
                          rationale=parsed.rationale)
        return Verdict(CONTRADICTED, layer="llm_judge_sub6",
                      quality_score=0.0, rationale=parsed.rationale,
                      evidence_pointer=parsed.evidence_pointer)
    
    if parsed.confidence >= JUDGE_CONFIDENCE_THRESHOLD:
        return Verdict(parsed.verdict, layer="llm_judge_sub6",
                      quality_score=1.0 if parsed.verdict == "SUPPORTED" else 0.0,
                      rationale=parsed.rationale,
                      evidence_pointer=parsed.evidence_pointer)
    
    # confidence in [0.5, 0.85) → HEDGED
    return Verdict(HEDGED, layer="llm_judge_sub6",
                  quality_score=0.6,
                  feedback_hint=parsed.rationale,
                  rationale=parsed.rationale)
```

### Helpers(D2 设计,D3 实现)

- `verifier/helpers/llm_judge_prompt.py` — prompt template 构造
- `verifier/helpers/judge_response_parser.py` — JSON parse + schema validation
- `verifier/helpers/judge_cost_cap.py` — per-Path-X cost tracking + cap enforcement
- `verifier/helpers/contradicted_validator.py` — double-confirmation gate

### Cost 设计

预算计算(per Path X full-63):
- ~900 UV claims 在到达 LLM-judge 前
- JUDGE_ELIGIBLE_TYPES 过滤:估 40-60% 通过 → 360-540 claim
- Per call:~3-8K input + 500 output tokens
- MiniMax rate: $0.30/M input + $1.20/M output
- 估算:540 × 5K × $0.30/M + 540 × 500 × $1.20/M = $0.81 + $0.32 = **$1.13**
- Cap 设 $2 留 buffer

### 死命令冲突检查

| 死命令 | 影响 | 解决 |
|---|---|---|
| MetAgent LLM-driven | ✅ 强化(LLM-judge 是 verifier 工具) | — |
| MiniMax 远程 API | ✅ 适用,cost 必从 jsonl 读 | helper cost log |
| Verifier 三档 | ✅ Add 新 layer / ⚠ dispatcher add 必 verifier-modify-warning | 严格 commit body |
| Strict TDD per-piece | ✅ 每个 piece RED → GREEN | 严格 |
| iter-2 deg 锁 | ✅ HEDGED feedback hint 可能影响 ReAct iter-1,需 D4 验证 0 退步 | HG-7 |
| B1-core 不动 | ✅ 不预期碰 | D3 verify |
| 不写 paper narrative | ✅ 不碰 | — |
| strict-vs-fuzzy 重分类 | ✅ D1 必做 | target ≤ ceiling × 0.6 |
| data carrier audit | ✅ D1 smoke check + claim_type fit | — |

---

## §3 Daily Breakdown

### D0(~0.3d)— Onboarding

1. 读 §0.D 12 个 memory 文件
2. 读 §0.E 项目工件全集
3. 回报当前 git status + branch + HEAD(应 `metagent-v2 @ 95779f06` 或更新)
4. 跑 `pytest tests/` 记录 baseline fail count(必须 ≤ 14)
5. 确认 W17 D3 实测:
   - `schemas/sub6_report.py` 含 4 个新 carrier 字段 ✅
   - `concord/agent/verifier_adapter.py` 含 passthrough ✅
   - `verifier/agent.py` dispatcher signal_sub6 catch-all 仍 disabled ✅
6. **不进 D1 直到 user OK D0 报告**

### D1(~0.7-1d)— Dual Audit + Strict-vs-Fuzzy 重分类

#### D1.1 W17 carrier smoke check(~0.2d)

1. 读 W17 D4 Path X 一个 task 的 trace dump
2. 检查 SubsixSourceReport 实际承载的 carrier 字段(应有 mummichog / metaboanalystr["psea"] / sspa / fella["rwr"] 中至少一些非空)
3. 输出 `data/metagent/w18_dual_audit/w17_carrier_smoke.md`(carrier populated rate per Path X task)

#### D1.2 claim_type × LLM-judge fitness 分类(~0.3-0.5d)

1. 从 W15 v2 attribution + W17 v3 paradigm audit pull verifier_gap+both claim
2. MiniMax 二分类:
   - **judge_strict**:LLM-judge 能 cover(biology background 有 tool evidence / signal claim 缺精确 carrier 但有近似 / 等)
   - **judge_uncoverable**:LLM-judge 帮不上(需要外部 KB / 缺数据 / 完全凭空 / 等)
3. 算 strict ceiling:`judge_strict / total_UV` = LLM-judge 真实工程 ceiling
4. **Sprint target ≤ ceiling × 0.6**(W12 教训)
5. 20-sample spot-check(seed 固定 20260609),≥80% 一致率守 HG-2
6. 输出 `data/metagent/w18_dual_audit/claim_judge_fitness_inventory.csv` + `summary.md`
7. **Ping user 报 target 数字,等 OK 才进 D1.3**

#### D1.3 cost projection(~0.1d)

1. 从 D1.2 strict 集合估算每个 Path X 调用次数
2. 根据 W15 / W17 实测 token avg + MiniMax rate 算成本
3. 输出 `data/metagent/w18_dual_audit/cost_projection.md`
4. 若估算 > $2 per Path X → 收紧 JUDGE_ELIGIBLE_TYPES 直到 ≤ $2

#### D1.4 design decision doc draft(~0.1d)

写 `docs/decisions/2026-06-09_w18_llm_judge_layer.md` 草稿:
- Context(W16 D4 + 2026-06-09 用户决策)
- Architecture(layer 设计 + dispatcher integration 点)
- JUDGE_ELIGIBLE_TYPES 决策依据(D1.2 数字)
- Cost 预算 + cap 机制
- Confidence threshold 决策(0.85 / 0.90)
- CONTRADICTED double confirmation 设计
- Backward compat:HEDGED feedback hint 不破 iter-2 锁

### D2(~0.5-0.8d)— RED

#### D2.1 Unit test(`tests/test_w18_llm_judge_sub6.py`,≥10 case)

- mock MiniMax response 测各 verdict 分支
- confidence ≥ 0.85 SUPPORTED 路径
- confidence ≥ 0.90 + valid evidence pointer → CONTRADICTED
- confidence ≥ 0.90 但 evidence pointer 无效 → HEDGED(double confirmation gate)
- confidence in [0.5, 0.85) → HEDGED
- confidence < 0.5 → UV
- claim_type 不在 JUDGE_ELIGIBLE_TYPES → 直接 UV(不调 LLM)
- cost cap 触发 → UV

#### D2.2 Dispatcher integration test(`tests/test_w18_llm_judge_dispatcher_integration.py`,≥5 case)

- prior layers 已命中 → 不调 llm_judge_sub6(确保 post-UV only)
- prior layers 全 UV + claim_type eligible → 调 llm_judge_sub6
- prior layers 全 UV + claim_type 不 eligible → 留 UV
- signal_sub6 catch-all 保持 disabled(W16 rollback 不变)
- W12 factual_sub6 路由不变(preservation test)

#### D2.3 Cost cap test(`tests/test_w18_judge_cost_cap.py`,≥3 case)

- 累积成本 < cap → 允许调用
- 累积成本 ≥ cap → 拒绝调用 + 留 UV
- cost log 写 jsonl(从 logs/concord/w18_path_x_*.jsonl 读)

#### D2.4 Helper unit tests

- `tests/test_w18_judge_prompt.py`(prompt template,≥3 case)
- `tests/test_w18_judge_response_parser.py`(JSON parse + schema,≥4 case)
- `tests/test_w18_contradicted_validator.py`(double confirmation,≥3 case)

D2 总 case 数:≥ 28(unit 10 + integration 5 + cost 3 + helpers 10)

跑 RED 确认全 fail(实现未存在)。Commit `test(verifier): W18 D2 RED — llm_judge_sub6 layer + helpers + dispatcher integration + cost cap`。

### D3(~1.5-2d)— GREEN

按 D2 写的 RED 测试逐个绿,**每个 piece 独立 commit**:

1. `verifier/helpers/llm_judge_prompt.py` → RED → GREEN → commit `feat(verifier): W18 D3 — judge_prompt helper`
2. `verifier/helpers/judge_response_parser.py` → RED → GREEN → commit
3. `verifier/helpers/judge_cost_cap.py` → RED → GREEN → commit
4. `verifier/helpers/contradicted_validator.py` → RED → GREEN → commit
5. `verifier/layers/llm_judge_sub6.py` → RED → GREEN → commit
6. Dispatcher 接入 `verifier/agent.py`:加新 case after 所有 deterministic layers,**before final UV return** → **⚠ verifier-modify-warning commit body** → ping user 后 commit

每个 commit 后:
- 跑 `pytest tests/test_w18_*.py -q` → 相关 piece GREEN
- 跑 `pytest tests/` 全 repo → 14-fail floor 守住
- 跑 `pytest tests/test_factual_sub6* tests/test_set_enrichment* tests/test_signal_sub6.py tests/test_w16_rollback_dispatcher_returns_to_w14.py tests/test_w17_*.py -q` → W12-W17 0 退步

Dispatcher commit body 必须含:
```
[verifier-modify-warning]
This commit adds llm_judge_sub6 catch-all to _verify_per_claim_sub6 dispatcher
per feedback_verifier_modification_policy ⚠ tier.

Changes:
- Add llm_judge_sub6 case AFTER all existing deterministic layers
- Fires only when prior_verdict == UV and claim_type in JUDGE_ELIGIBLE_TYPES
- signal_sub6 catch-all remains DISABLED (W16 rollback preserved)
- factual_sub6 / set_enrichment / verify_sub6 routing unchanged
- iter-2 cap (DEFAULT_MAX_FEEDBACK_ITERS=1) preserved

LLM-judge invokes MiniMax with bounded cost per Path X (≤ $2).
HEDGED outputs may produce feedback hints; impact on ReAct iter-1 verified by D4 Path X (HG-7 iter-2 deg = 0).

B1 paper data unaffected (verifier-only behavior change).
B1 test floor preserved (verify in D4).

Decision doc: docs/decisions/2026-06-09_w18_llm_judge_layer.md
```

### D4(~0.5d)— Path X full-63 Verify

1. 跑 Path X full-63,输出 `data/metagent/w18_path_x_post_llm_judge/`:
   - `path_x_full63_results.jsonl`
   - `summary.md`
   - LLM 调用 log `logs/concord/w18_path_x_post_llm_judge.jsonl`
2. 算 metrics:

| 指标 | 目标 | W17 D4 baseline | W14 baseline |
|---|---|---|---|
| UV rate | ≤ W17 44.92% − target | 44.92% | 44.25% |
| Pathway accuracy | ≥ 84% | 90.5% | 85.7% |
| iter-2 deg | = 0 | 0 | 0 |
| Cost total | ≤ $15 | $6.45 | $6.83 |
| LLM-judge incremental cost | ≤ $2 | n/a | n/a |
| LLM-judge fire rate | report | n/a | n/a |
| SUPPORTED conversions | report | n/a | n/a |
| CONTRADICTED count | report | n/a | n/a |
| HEDGED count | report | n/a | n/a |

3. Hard Gate verify(§4)
4. 20-sample 手工 review CONTRADICTED 输出 → ≥80% 真 positive 才算 HG-12 PASS
5. 任何 HG fail → stop ping

### D5(~0.3d)— Close-out

1. Finalize `docs/decisions/2026-06-09_w18_llm_judge_layer.md`(加 D4 数字 + CONTRADICTED 抽检结果)
2. 写 `reports/agent/w18_llm_judge_close_out.md`(sprint summary + HG verdict table + cost breakdown + next sprint recommend)
3. Memory 更新建议(suggestions only,Claude 应用):
   - 可能 append `feedback_metagent_must_be_llm_driven` — LLM-judge layer 实施案例 + 经验教训
   - 可能 append `feedback_verifier_modification_policy` — verifier 层 LLM 调用 cost cap 模式
4. Sprint close-out master log(`conversation/master/{date}_{time}_w18-sprint-close-out.md`)

---

## §4 Hard Gates(全部 PASS 才能 close-out)

| Gate | Target | Verify |
|---|---|---|
| HG-1 | D1.1 W17 carrier smoke check pass(W17 carrier 实际通到 verifier)| `data/metagent/w18_dual_audit/w17_carrier_smoke.md` |
| HG-2 | D1.2 LLM-vs-human 20-sample agreement ≥80% | spot-check report |
| HG-3 | D1.2 strict ceiling 算出,target ≤ ceiling × 0.6 | `summary.md` |
| HG-4 | D1.3 cost projection per Path X ≤ $2 | `cost_projection.md` |
| HG-5 | D2 RED test case ≥ 28 全 fail | pytest output |
| HG-6 | D4 UV drop ≥ target(D1.2 算出的)| Path X jsonl |
| HG-7 | D4 pathway accuracy ≥ 84% | 同上 |
| HG-8 | D4 iter-2 deg = 0(W14 锁不可破) | 同上 |
| HG-9 | D4 Path X 总成本 ≤ $15 | logs/concord jsonl |
| HG-10 | D4 LLM-judge incremental cost ≤ $2 | 同上 |
| HG-11 | D4 false CONTRADICTED rate ≤ 20%(20-sample 手工 review,真 positive ≥ 16/20)| review report |
| HG-12 | pytest 14-fail floor 不退步 | full repo pytest |
| HG-13 | W12-W17 既有 layer / dispatcher 测试 0 退步 | focused pytest |
| HG-14 | B1-core helper(claim_extractor / feedback_hints / _extract_classify)未碰 | git diff audit |
| HG-15 | signal_sub6 dispatcher catch-all 仍 DISABLED | grep audit |
| HG-16 | iter cap(DEFAULT_MAX_FEEDBACK_ITERS=1)未改 | grep audit |
| HG-17 | SubsixSourceReport schema 未改(W17 已锁) | git diff audit |

---

## §5 Risks & Stop Conditions

| Risk | Stop trigger | User decision |
|---|---|---|
| D1.2 strict ceiling × 0.6 < 1pp | Target 太小,LLM-judge ROI 不值 | YES — option {A: 收紧 eligible types 加深 strict / B: pivot 到 W19 γ KB tools / C: 接受小 target close 早} |
| D1.2 LLM 一致率 < 80% | rubric 模糊或类型边界不清 | YES — W15/W17 教训 retry 流程 |
| D1.3 cost projection > $5 per Path X(超 cap 2.5x) | scope 太大 | YES — 收紧 eligible types |
| D3 dispatcher 接入需要 reorder 老 case | scope creep ⚠ → 更严 ⚠ | YES — option {A: 接受 + warning / B: 改架构 add 新 sub-dispatcher / C: 缩 scope} |
| D4 pathway accuracy < 84% | HG-7 fail | YES — STOP,LLM-judge 错判 SUPPORTED 影响 ReAct rollback |
| D4 iter-2 deg > 0 | HG-8 fail | YES — STOP,HEDGED feedback hint 破了 iter cap 锁 |
| D4 UV drop < target | HG-6 fail | YES — option {A: 接受 partial close / B: 调 confidence threshold retry / C: 重审 D1 ceiling} |
| D4 LLM-judge cost > $5 | HG-10 fail | YES — STOP,cap 机制失效 |
| D4 CONTRADICTED 抽检真 positive < 80% | HG-11 fail | YES — STOP,judge hallucinates,disable CONTRADICTED 输出 retry |
| 任何 commit 触动 B1-core helper | HG-14 fail | YES — STOP immediately |
| 任何 commit 改 schema 字段 | HG-17 fail | YES — STOP immediately(W17 already extended,W18 应该不动) |

---

## §6 Banned Phrases

- 不写 paper narrative:"Our results show...", "We demonstrate...", "In conclusion,...", footnote prose
- 不说 "$0 local" / "free local run"(MiniMax 是远程 API)
- 大白话总结不用 strict-TDD / commit / sprint / RED / GREEN / Hard Gate 术语
- 不 push 任何 commit 到 remote
- 不 force tag / 不删 tag

---

## §7 输出工件清单(D5 末必须存在)

```
# D1 dual audit
data/metagent/w18_dual_audit/
  ├─ w17_carrier_smoke.md
  ├─ claim_judge_fitness_inventory.csv
  ├─ claim_judge_fitness_summary.md
  ├─ claim_judge_fitness_spot_check.csv
  └─ cost_projection.md

# D2 RED
tests/test_w18_llm_judge_sub6.py
tests/test_w18_llm_judge_dispatcher_integration.py
tests/test_w18_judge_cost_cap.py
tests/test_w18_judge_prompt.py
tests/test_w18_judge_response_parser.py
tests/test_w18_contradicted_validator.py

# D3 GREEN
verifier/helpers/llm_judge_prompt.py
verifier/helpers/judge_response_parser.py
verifier/helpers/judge_cost_cap.py
verifier/helpers/contradicted_validator.py
verifier/layers/llm_judge_sub6.py
verifier/agent.py  (⚠ verifier-modify-warning commit body)

# D4 verify
data/metagent/w18_path_x_post_llm_judge/
  ├─ path_x_full63_results.jsonl
  ├─ summary.md
  └─ contradicted_manual_review.md  (HG-11)
logs/concord/w18_path_x_post_llm_judge.jsonl

# D5 close-out
docs/decisions/2026-06-09_w18_llm_judge_layer.md
reports/agent/w18_llm_judge_close_out.md
conversation/master/{...}_w18-sprint-close-out.md
```

---

## §8 Memory updates expected at D5

- 可能 append `feedback_metagent_must_be_llm_driven`:LLM-judge layer 实施案例,验证"LLM-judge 是 verifier 工具不是反过来"
- 可能新增 memory:`reference_verifier_llm_judge_pattern.md`(per-Path-X cost cap 模式 / confidence threshold 决策依据)
- 若 D4 CONTRADICTED hallucination 严重 → 可能立新死命令"verifier 层 CONTRADICTED 输出必须有 deterministic 校验"

---

## §9 First Action upon receiving this prompt

1. 中文 ack,结尾必含 2 段大白话总结
2. 执行 §3 D0 全 6 步
3. Ping user with D0 6 项报告
4. **不进 D1 直到 user OK D0 报告**
5. D1.2 strict-vs-fuzzy 算出 target 后必 ping user 等 OK 才进 D1.3
6. 任何模糊点 / blocker / spec 与现状不符 → 在 ping 里 flag,不默默假设

---

## §10 决断红线(立即停 ping)

- Memory 文件读不到 / 不存在 → STOP
- W17 数据(`carrier_audit/claim_paradigm_inventory_v3.csv` 等)不存在 → STOP
- 当前 branch ≠ `metagent-v2` 或 worktree ≠ `metagent_v2` → STOP
- HEAD < `95779f06`(W17 close-out)→ STOP
- pytest baseline > 14 fail → STOP
- W17 D3 数据契约破(schema 没 4 字段 / adapter 没 passthrough)→ STOP
- signal_sub6 dispatcher 居然 enabled(W16 rollback 被破)→ STOP
- 死命令冲突 → STOP

**Ready. Go.**

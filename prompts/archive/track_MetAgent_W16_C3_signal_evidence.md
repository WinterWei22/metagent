# MetAgent W16 — C3 signal_evidence verifier layer (signal_sub6)

**Sprint type**: pure-add new verifier layer (W12 `factual_sub6` 同款 pattern)
**Duration**: 3-4 day(D1 §0 + onboarding / D2 RED / D3 GREEN / D4 verify + Path X / D5 close-out)
**Date launched**: 2026-05-26
**Working tree**: `/home/weiwentao/workspace/llm_agent_metabolomics/metagent_v2/`
**Branch**: `metagent-v2`
**Model name**: **MetAgent**(不是 ConcordMet——ConcordMet 是 sibling investigation worktree,本 sprint 不碰)

---

## §0 Onboarding — 在任何代码动作前必读

### A. 项目当前状态(2026-05-26 W15 close-out 后)

- 当前 UV claim rate:**44.25%**(Path X full-63 task)
- Pathway accuracy:86%(W8 → W14 全程持平)
- iter-2 quality degradation:0%(W14 锁死,`DEFAULT_MAX_FEEDBACK_ITERS = 1`)
- 累计纪律:W8 → W14 共 52 commit / 0 strict-TDD slip / 3 护栏未破

### B. W15 attribution audit 给的硬数字(W16 出发点)

**全 901 条 UV claim 三分类**(MiniMax-M2.7,v2 rubric tightened,详见 `docs/decisions/2026-05-26_uv_root_cause_attribution_framework.md`):

| 类型 | 占比 |
|---|---|
| verifier_gap(verifier 没工具) | **62%** |
| both(两边都有) | 19% |
| producer_fault(ReAct 乱讲) | 18% |

**C3 signal_evidence 桶**:**168 条**(占 UV 18.6%),其中 **76% = verifier_gap**(~127 条),producer_fault 仅 ~10%。
→ 这一桶的瓶颈非常清楚:**LLM 引用数值是从 5 PA 工具的 `EnrichmentResult` 出来的,内容多数 legit,但 verifier 没层 catch**。

### C. 死命令(全部 active,违反 ping user)

1. **中文交流**,代码/标识符英文 — `feedback_language_chinese`
2. **MetAgent 必须 LLM-driven** — `feedback_concordmet_must_be_llm_driven`(本 sprint 沿用 ReAct + verifier 闭环)
3. **V3 deterministic 算法不暴露给 LLM** — 同上
4. **MiniMax 是远程 API,按 token 收费** — `reference_minimax_is_remote_api`,成本必须从 `logs/llm_calls.jsonl` 读实际值,禁说 "$0 local"
5. **每条回复结尾必加 2 段大白话总结** — `feedback_plain_summary_at_end`,各 1-3 句,禁用 strict-TDD/commit/sprint 等术语,保留数字
6. **Verifier 修改三档准则** — `feedback_verifier_modification_policy`
   - ✅ Add 新层 / 新 helper / 新 enum / 新 dispatcher route → 自由
   - ⚠ Modify 现有 verifier 逻辑 → commit body 必含 `[verifier-modify-warning]` + ping user
   - ❌ 改 B1 D5/D6 核心 helper(claim_extractor / feedback_hints / `_extract_classify`)默认禁
   - **本 sprint 全程纯 ✅ Add 设计,不应触发 ⚠ 或 ❌**
7. **3 护栏(绝不可破)**:
   - Tag `metagent-v2-base-b1 @ ed6243b` 不可 force / 不可删
   - `data/eval/sub6/b1_*/` + `a3_rerun_*/` paper 数据 immutable
   - `tests/` 全 repo pytest **14-fail floor 不退步**(每改完一处 verifier 跑 `pytest tests/` 验证)
8. **不写 paper narrative** — `feedback_no_paper_writing_yet`,Discussion / Methods / Results / Abstract / footnote / "We demonstrate..." 一律不写;输出文件 = 可直接 copy-paste 进 paper = 越界
9. **UV sprint 启动前必做 strict vs fuzzy 重分类** — `feedback_uv_sprint_must_reclassify_first`,本 sprint §0 必须包含 0.3-0.5d LLM 重分类 + target ≤ ceiling × 0.6
10. **重要设计决策存档** — `feedback_design_decisions_archive`,W16 layer 架构选型必须写一份 `docs/decisions/2026-05-26_w16_signal_sub6_architecture.md`(本 branch,本 worktree)
11. **Strict TDD per-piece**:每个 piece 先 RED(失败测试 commit) → GREEN(实现 commit),0 slip

### D. 必读 memory 文件(D0 第一步)

```
feedback_language_chinese.md
feedback_proceed_with_defaults.md
feedback_concordmet_must_be_llm_driven.md
reference_minimax_is_remote_api.md
feedback_plain_summary_at_end.md
feedback_verifier_modification_policy.md
feedback_no_paper_writing_yet.md
feedback_uv_sprint_must_reclassify_first.md
feedback_design_decisions_archive.md
project_metagent_v2_merge.md
```

### E. 必读项目工件(D0 第一步)

```
docs/decisions/2026-05-26_uv_root_cause_attribution_framework.md   # W15 框架
data/metagent/w15_uv_attribution/summary.md                        # W15 v2 数据(D2 已产出)
data/metagent/w15_uv_attribution/attribution_v2.csv                # 重分类 raw
prompts/track_CONCORD_W14_noise_prompt_iter2_cap.md                # 最近 sprint 结构参考(命名 CONCORD_ 是历史前缀,内容已是 MetAgent)
prompts/track_CONCORD_W12_C7_namespace_fix.md                      # factual_sub6 同款 pattern 参考(命名 CONCORD_ 同上)
prompts/track_MetAgent_W15_uv_attribution_audit.md                 # W15 attribution sprint 参考
verifier/layers/factual_sub6.py                                    # W12 写的新层(本 sprint 抄架构)
verifier/agent.py                                                  # dispatcher,看 _verify_per_claim_sub6
verifier/grammar.py                                                # ClaimType 枚举位置
concord/agent/react_runner.py                                      # iter cap 现状
```

---

## §1 Goals & Non-Goals

### Goals

1. **G1**: 启动前必做 strict vs fuzzy 重分类——把 168 个 C3 claim 用 MiniMax 二分类成
   - **strict_signal_lookup**:claim 引用的数值/分数/p-value 可在某个 `EnrichmentResult` 字段精确定位(直接键查或 ±tolerance 查)
   - **fuzzy_signal_inference**:claim 表述 "method X 的 score 高/低/显著",但具体数值无法对到 EnrichmentResult 任一字段(需要语义匹配 + 阈值推理)
   - 算 strict_ceiling = `strict_signal_lookup / total_C3`,sprint target ≤ ceiling × 0.6
2. **G2**: 新 verifier 层 `signal_sub6`(类比 W12 `factual_sub6`),pure-add 到 `verifier/layers/`
3. **G3**: Dispatcher 接入(`verifier/agent.py:_verify_per_claim_sub6` 加一个新 case),只 add 不 modify 老路由
4. **G4**: 用 W15 重分类数据 + W16 §0 重分类数据校准 target,Path X full-63 跑通后 Hard Gate verify
5. **G5**: D5 写 architecture decision doc 到 `docs/decisions/2026-05-26_w16_signal_sub6_architecture.md`

### Non-Goals

- ❌ 不动 ReAct prompt(prompts/concord/concord_react_prompt.md 本 sprint frozen)
- ❌ 不动 `DEFAULT_MAX_FEEDBACK_ITERS`(W14 锁的 1,不改)
- ❌ 不动 5 个 PA tool 的 EnrichmentResult contract(只读不写)
- ❌ 不动 grammar.py 已有 ClaimType / DroppedReason 枚举(可 add 新枚举值,不改老的)
- ❌ 不动 `claim_extractor.extract_claims_from_json` / `feedback_hints.build_feedback_message` / `_extract_classify`(B1 核心 ❌ 档)
- ❌ 不写 paper narrative
- ❌ 不在本 sprint 顺手碰 C5 intermediate_biology 或 C1 cross-method(留给 W17 / W18)

---

## §2 Architecture(layer 设计概略,D1 细化)

### 当前 verifier 处理 signal-like claim 的状况

- 现状:`verifier/agent.py:_verify_per_claim_sub6` 把 ClaimType == `ENRICHMENT_NUMERIC` 的 claim 路由给 **B 层 `enrichment_evidence`**
- 问题:**ClaimType classifier(`_extract_classify`)对 signal-like 表述识别率低**(W15 attribution 显示 168 个 C3 claim 多数没被 tag 成 ENRICHMENT_NUMERIC,所以根本没进 B 层)
- **不能** 改 `_extract_classify`(B1 ❌ 档)

### W16 新增 `signal_sub6` 层(pure-add 路线)

**Idea**: 不 fix classifier,改在 dispatcher 末端加一个 **catch-all signal lookup 层**,所有 ClaimType ∈ {FACTUAL, GROUNDED, UNCLASSIFIED, ENRICHMENT_NUMERIC(已被 B 处理过的 fallthrough 不再处理)} 的 claim,若文本含数值/分数/p-value 模式 → 进 signal_sub6 尝试对 EnrichmentResult lookup。

**Layer 内部步骤(草稿,D1 review)**:
1. **正则提取**:从 claim text 抽出 `(method_name, metric_name, value)` 三元组
   - method:ora / gsea / msea / qea / topology / "pathway analysis" / "the analysis" 等
   - metric:p-value / FDR / NES / impact / score / rank
   - value:浮点 / 整数 / 区间("highly" "significant" → 跳过本层 fuzzy)
2. **EnrichmentResult lookup**:用 `(method, pathway_name)` 从对应 method 的 EnrichmentResult dict 查值
3. **Match 判定**:
   - 精确等值 → GROUNDED + verifier_layer="signal_sub6"
   - ±10% tolerance → HEDGED + 写 feedback hint
   - lookup miss / 元组提取失败 → 不接管(由原 dispatcher 兜底 UV)
4. **Quality score**:命中 GROUNDED = 1.0;HEDGED = 0.6
5. **Feedback hint(给 ReAct iter-1,W14 后 iter cap = 1)**:仅当 ±10% tolerance 命中时,提示"score is approximately X (got Y), tighten phrasing or cite exact value"

### 关键 helper(可能新加)

- `verifier/helpers/signal_extractor.py` — 正则三元组提取
- `verifier/helpers/enrichment_lookup.py` — 跨 5 PA tool EnrichmentResult 统一查询接口

### Dispatcher 改动(⚠ modify 风险点)

`_verify_per_claim_sub6` 末端加 `signal_sub6` case **位置敏感**:
- 必须在 B 层后(避免 ENRICHMENT_NUMERIC 双重处理)
- 必须在 unknown_fallback 前(否则永远到不了)

→ **这是本 sprint 唯一 ⚠ 风险点**,D2 RED 时 ping user 确认接入方式;若 D3 实现走 `add new case` 而非 `modify existing routing` 仍算 ✅ Add。

---

## §3 Daily breakdown

### D0(0.2d)— Onboarding
1. 读 §0 D 全部 memory 文件
2. 读 §0 E 全部项目工件
3. 回报当前 git status + branch + HEAD,确认在 `metagent_v2` worktree / `metagent-v2` branch
4. 跑 `pytest tests/` 记录基线 fail count(应为 ≤ 14)
5. ping user:确认 §0 全部读完 + baseline 数字

### D1(0.3-0.5d)— §0 重分类(死命令必做)
1. Pull C3 桶 168 个 claim 从 `data/metagent/w15_uv_attribution/attribution_v2.csv`
2. 写 `scripts/metagent/w16_c3_strict_vs_fuzzy.py`(template 复用 W12 同款脚本)
3. MiniMax 二分类 strict_signal_lookup vs fuzzy_signal_inference
4. 输出 `data/metagent/w16_c3_strict_vs_fuzzy/c3_subclassification.csv` + summary
5. 算 strict_ceiling × 0.6 = target UV 降幅
6. ping user 报数字,**确认 target 后才进 D2**

### D2(0.5d)— RED
1. 写 `tests/test_signal_sub6.py`(覆盖 §2 layer 4 步内部步骤,≥10 cases)
2. 写 `tests/test_signal_extractor.py`(正则三元组提取 unit test,≥8 cases)
3. 写 `tests/test_enrichment_lookup.py`(跨 5 method 查询 unit test,≥5 cases)
4. 写 `tests/test_signal_sub6_dispatcher_integration.py`(走 verifier/agent.py 路由,≥3 cases)
5. 跑全部新测试,确认全 RED(实现未存在)
6. Commit `test(signal): W16 D2 RED — signal_sub6 layer + extractor + lookup + dispatcher`

### D3(0.8-1d)— GREEN
1. 实现 `verifier/helpers/signal_extractor.py` → RED → GREEN → commit
2. 实现 `verifier/helpers/enrichment_lookup.py` → RED → GREEN → commit
3. 实现 `verifier/layers/signal_sub6.py` → RED → GREEN → commit
4. Dispatcher 接入(verifier/agent.py 加新 case,**不 modify 老 case**)
   - 若不得不 modify(case 顺序敏感),commit body 加 `[verifier-modify-warning]` + ping user
   - 否则单纯 add → 普通 commit
5. 每个 commit 后 `pytest tests/` 验证 14-fail floor 不退步
6. 全部 GREEN 后跑 verifier 全 test 套件 `pytest tests/test_verifier/`,确认无 NEW fail

### D4(0.5d)— Verify on Path X full-63
1. 跑 Path X full-63 task(MiniMax-M2.7,K=10 docker concurrent)
2. 输出到 `data/metagent/w16_path_x_post_signal_sub6/path_x_full63_results.jsonl`
3. 计算指标:
   - **UV claim rate**(目标 D1 算出的 target)
   - Pathway accuracy(目标 ≥ 84%,保留 2pp 余量)
   - iter-2 deg(目标 0%,W14 锁的不应回滚)
   - 成本(查 `logs/llm_calls.jsonl` 实际)
   - 墙钟
4. Hard Gate verify(§4)
5. 若 fail → ping user 决断 option

### D5(0.3d)— Close-out
1. 写 `docs/decisions/2026-05-26_w16_signal_sub6_architecture.md`(Context / Options / Decision / Consequences / Related,参考 W15 decision doc 格式)
2. Memory 更新(若有新教训):append 到现有 memory 文件,不新建
3. 把 W17 候选(C5 intermediate_biology)的 strict vs fuzzy 重分类列为 W17 D1 必做
4. Sprint close-out ping(2 段大白话总结 + 实际数字)

---

## §4 Hard Gates(全部 PASS 才能 close-out)

| Gate | Target | Verify method |
|---|---|---|
| **HG-1** | UV drop ≥ D1 算出的 target(strict_ceiling × 0.6) | `data/metagent/w16_path_x_post_signal_sub6/` UV count / total |
| **HG-2** | Pathway accuracy ≥ 84%(W14 baseline 86%,留 2pp 余量) | Path X full-63 pathway match rate |
| **HG-3** | iter-2 quality degradation ≤ 0%(W14 锁) | `react_runner.py` iter-2 path 命中数 |
| **HG-4** | 成本 ≤ $15(Path X full-63 估值,实际查 jsonl) | `logs/llm_calls.jsonl` aggregate |
| **HG-5** | B1 test floor 不退步:`pytest tests/` fail ≤ 14 | `pytest tests/` 输出 |
| **HG-6** | Verifier B 层(enrichment_evidence)行为不变 | `pytest tests/test_verifier/test_enrichment_evidence*` 全过 |
| **HG-7** | No B1-core helper(claim_extractor / feedback_hints / `_extract_classify`)modified | `git diff --name-only HEAD~10 HEAD` audit |

---

## §5 Risks & Stop Conditions

| Risk | Stop trigger | User decision needed? |
|---|---|---|
| D1 strict_ceiling × 0.6 < 1pp | Target 太小,ROI 不值 sprint | YES — stop ping option {A: 加 fuzzy_signal 一起做 / B: 跳到 W17 C5 / C: 收 sprint scope} |
| D3 dispatcher 接入不得不 modify 老 case 顺序 | ⚠ 触发 | YES — stop ping option {A: 接受 modify + warning / B: 改架构 add 新 sub-dispatcher / C: 缩 scope} |
| D4 pathway accuracy 跌破 84% | HG-2 fail | YES — stop ping(可能 layer 触发了 spurious DROP) |
| D4 iter-2 deg > 0 | HG-3 fail | YES — stop ping(应该不会,iter cap = 1 锁死;若真发生说明有人改了 iter cap) |
| D4 UV drop < target | HG-1 fail | YES — stop ping option {A: 接受 partial + close / B: D5 调 layer 参数 retry / C: 重审 D1 ceiling} |
| HG-2 spot-check 20-sample LLM 一致率 < 80% | D1 §0 重分类 trust issue | YES — stop ping(W15 教训) |

---

## §6 Banned phrases & 行为

- 不写 paper narrative:"Our results show...", "We demonstrate...", "In conclusion,...", "This study...", footnote 风格 prose
- 不说 "$0 local"(MiniMax 是远程 API)
- 不在大白话总结里用 strict-TDD / commit / sprint / RED / GREEN / Hard Gate 等术语
- 不动 `tests/test_concord/` 已有的 ReAct 测试
- 不 push 任何 commit 到 remote(除非用户明确说)
- 不 `git tag -f` 或 `git tag -d` 任何 immutable tag

---

## §7 输出工件清单(D5 末必须存在)

```
verifier/layers/signal_sub6.py                                                  # NEW
verifier/helpers/signal_extractor.py                                            # NEW
verifier/helpers/enrichment_lookup.py                                           # NEW
verifier/agent.py                                                               # add case(可能 ⚠ modify)
tests/test_signal_sub6.py                                                       # NEW
tests/test_signal_extractor.py                                                  # NEW
tests/test_enrichment_lookup.py                                                 # NEW
tests/test_signal_sub6_dispatcher_integration.py                                # NEW

scripts/metagent/w16_c3_strict_vs_fuzzy.py                                      # NEW
data/metagent/w16_c3_strict_vs_fuzzy/c3_subclassification.csv                   # NEW
data/metagent/w16_c3_strict_vs_fuzzy/summary.md                                 # NEW

scripts/metagent/w16_path_x_post_signal_sub6.py                                 # NEW(可复用 W14 同款)
data/metagent/w16_path_x_post_signal_sub6/path_x_full63_results.jsonl           # NEW
data/metagent/w16_path_x_post_signal_sub6/summary.md                            # NEW

docs/decisions/2026-05-26_w16_signal_sub6_architecture.md                       # NEW
```

---

## §8 Memory updates expected at D5

- `feedback_uv_sprint_must_reclassify_first.md` — 若 W16 也踩了 ceiling 估高 → append 教训;若没踩 → append "W16 confirmed pattern works"
- 若发现新 verifier pipeline 模式 → 考虑新写 memory file(命名 `reference_*` 或 `feedback_*`)

---

## §9 First action upon receiving this prompt

1. 中文 ack,**结尾必须 2 段大白话总结**(进展 + 下一步,各 1-3 句)
2. 执行 §3 D0 onboarding(读 memory + 工件 + git 状态 + pytest baseline)
3. 全部读完后,把 D0 5 项报给 user,**等 user OK 才进 D1**
4. 任何模糊 / blocker / 与现状不符的 spec 点 → 在 ping 里 flag,不要默默假设

---

## §10 决断红线(出现以下情况立即停 ping)

- Memory 文件读不到 / 不存在 → stop ping
- `data/metagent/w15_uv_attribution/attribution_v2.csv` 不存在(我以为 session 已经 D2 commit 进 metagent-v2,若没有需 fallback v1)→ stop ping
- 当前 branch ≠ `metagent-v2` 或 worktree ≠ `metagent_v2` → stop ping
- pytest baseline > 14 fail → stop ping(护栏已破)
- `_extract_classify` 或 `claim_extractor` 或 `feedback_hints` 有未 commit 修改 → stop ping
- 任何与 §0 死命令冲突的事件 → stop ping

**Ready. Go.**

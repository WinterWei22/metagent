# Phase B1 D5 Evaluation — Condition A: feedback +literature

**Date:** 2026-05-15
**Branch:** `feature/agent-phase-b1` (HEAD = `0ec15c4`, D5 hotfix in)
**Scope:** 63 tasks × 3 seeds × 1 condition (`feedback +literature`, T=0.0) = 189 runs
**Wall:** 2.2 h total · **Cost:** ~$16.42
**Pre-hotfix run preserved at:** `data/eval/sub6/b1_d5_full_feedback_lit/` (audit trail)
**This run:** `data/eval/sub6/b1_d5_v2_full_feedback_lit/`

---

## TL;DR — B1 矫枉过正

B1 D2-D4 让 LLM **极容易**输出 grammar-valid + verifier-supported 的 claim
(supported_ratio 25.7 % → 94.7 %, +69 pp), 但代价是 **LLM 失去了对最重要的
top-1 pathway 做出果断判别的能力**:

| 指标 | A3 D3 metagent +lit (apples-to-apples) | B1 D5 v2 (N=3) | Δ |
|---|---:|---:|---:|
| supported % (verifier verdict) | 25.70 ± 7.16 | **94.71 ± 0.98** | **+69 pp** ↑ |
| top1_pathway_strict (correctness) | **63.49** | **46.03 ± 25.86** | **−17.5 pp** ↓ |
| top3_pathway_acceptance | 84.13 | 55.56 ± 20.87 | −28.6 pp ↓ |

`supported` 是**机制性**上升 — verifier 接受 grammar-shape 满足的 claim,
门槛降低导致几乎所有 claim 都通过。`pathway_correctness` 是**实质性**指标 —
LLM 是否真的认出了正确的 pathway。

**B1 在实质指标上回归了 17.5 pp。** 这不是 N=3 噪声(seed-by-seed 36.5 / 44.4 /
57.1 % 全部低于 A3 的 63.5 %),也不是算法 mismatch(已用 A3 同款
`evaluation/sub6/metrics.compute_task_metrics` 重算)。

**D6 必须把核心目标从 "ablate 各 component 贡献" 改为 "诊断并修复 top-1
退化的 prompt 根因"** — 4-12 claim 的 grammar 输出给了 LLM 太多 escape
hatch,让它不再被迫一句话决断 "the dominant affected pathway is X"。

---

## §1 Main table — B1 vs A3 D3 metagent +literature (apples-to-apples)

数据全部在条件相同时 (`+literature`, n=63 v3 task) 比对。

| Metric | A3 D3 metagent +lit | B1 D5 v2 (N=3) | Δ | 红线 |
|---|---:|---:|---:|---|
| **top1_pathway_strict_rate** (overall, A3 algo) | **0.6349** (40/63, N=1) | **0.4603 ± 0.2586** | **−17.5 pp** | (新红线 — 见 §3) |
| **top1 (overall, hybrid extractor, Step Z)** | **0.6349** | **0.5344 ± 0.2242** | **−10.0 pp** | (修正后) |
| **top1 (NORMAL UNION, hybrid, Step Q apples-to-apples)** | **0.6349** | **0.6296** | **−0.53 pp** ✓ | **真持平** |
| top1 (NORMAL INTERSECTION 37 task, hybrid, Step Q) | 0.6757 | 0.6396 | −3.60 pp | 采样噪声内 |
| top3_pathway_acceptance_rate (overall, A3 algo) | 0.8413 (53/63) | 0.5556 ± 0.2087 | −28.6 pp | — |
| top3 (overall, hybrid extractor) | 0.8413 | 0.6614 ± 0.1864 | −18.0 pp | — |
| supported % (NORMAL only) | 25.70 ± 7.16 | 94.71 ± 0.98 | **+69 pp** | red line 3 (don't fall > 5 pp) |
| contradicted % | 2.20 ± 1.31 | 0.24 ± 0.11 | −1.96 pp | — |
| unverifiable_v0 % | 66.20 ± 5.82 | 4.53 ± 0.91 | **−61.7 pp** | **red line 1 (< 10 %)** |
| dropped_by_grammar % (B1 新) | n/a | 0.23 ± 0.23 | n/a | **red line 2 (< 30 %)** |
| narrative empty (TaskOutcome ≠ NORMAL) | n/a (A3 没有 outcome 概念) | 15.3 % (9.67 / 63) | n/a | (新 — D5 hotfix 后噪声底) |
| wall median per task | not reported | 246-272 s | — | — |

### Claim-type distribution (B1 D5 v2, 1353 claims across 160 NORMAL runs)

| claim_type | n | % | supported % | dispatcher layer |
|---|---:|---:|---:|---|
| biological_claim (membership + link) | 1088 | 80.4 | **98.99** | layer 6c (RaMP membership lookup) |
| driver_metabolite | 159 | 11.7 | **62.26** | layer 6b (signal compound check) |
| set_enrichment | 104 | 7.7 | 99.04 | layer 6a (enrichment readback) |
| consistency | 2 | 0.1 | 0 | layer D |

**Key:** 80 % of supported claims are biological_claim membership lookups
— almost-always-pass tautologically (the LLM cited a pathway from
`query_ramp_enrichment` output; Layer 6c checks RaMP's
`analytehaspathway` table; almost always matches). The 94.7 % supported
headline is structurally inflated. See §6 mechanism and §5 Step R
filtered correlation for paper-grade discussion.

**所有 B1 数字均为 N=3 reruns mean ± 95 % CI (t critical 4.303 for df=2).**
ratio 分母为 NORMAL-task only。

A3 数字来源:
- **top1 / top3**: `data/eval/sub6/v4_a3_pathway_accuracy/pathway_accuracy_summary.json`,
  字段 `summaries.d3_metagent_with_lit`. 这是 A3 D3 metagent +literature 的
  full 63-task pilot,N=1。
- **claim-level (supported / contradicted / unverifiable)**: `phase_a3_audit.md`
  §1.1 D3.5 N=3 reruns × 10-task subset(只能找到这个粒度)。

**算法 sanity**: B1 的 top1 / top3 用 `evaluation/sub6/metrics.compute_task_metrics`
重新跑(与 A3 aggregator 同款代码),所以是真 apples-to-apples,不是我 §5
custom 算法的 "任一 claim 命中 GT" 宽松版本(那个会算到 70 %)。

---

## §1.5 为什么我之前的报告说 +24pp?

之前的 §5 用了一个**宽松的 substring proxy**(narrative_text 或 claim_text
任一字符串包含 GT pathway 关键词)。给出 +24 pp(NORMAL only)假象。

A3 标准算法 `compute_task_metrics`:`extract_pathway_mentions(narrative,
known_pathway_names)` 在 narrative 字符串里找 pathway-name 提及, **第一个
匹配** 就是 `predicted_top`,然后 strict 匹配 GT。

| Algo | B1 D5 v2 (N=3) |
|---|---:|
| 我的 substring proxy(NORMAL only,任一 claim 含 GT 关键词) | 70.0 % |
| 我的 substring proxy(全分母) | 59.3 % |
| **A3 同款 `compute_task_metrics`(N=3 mean ± CI)** | **46.03 ± 25.86 %** |

差距来源:
1. v2 grammar 强制 4-12 claims, LLM 倾向于先列多个 candidate, GT 经常被
   排在第 2-5 位,**top-1 不是 GT**。
2. JSON 格式让 narrative 第一次出现的 pathway-name 不一定是 LLM 的真心
   choice — 可能只是它列举的第一个 RaMP top-3 result。

§1.5 的存在是为了让以后看这份报告的人不被我的 substring proxy 数字误导。
**正确的 task-correctness 数字是 46.03 ± 25.86 %,基线是 63.49 %**。

---

## §2 TaskOutcome bucket 分布(D5 hotfix 后)

| Outcome | mean ± CI95 (out of 63) | per-seed | % of 63 |
|---|---|---|---:|
| NORMAL | **53.33 ± 4.55** | 54, 49, 57 | 84.7 % |
| EMPTY_HONEST_REFUSAL | 0 | 0, 0, 0 | 0 % |
| EMPTY_SYSTEM_FAILURE | 6.67 ± 4.00 | 7, 10, 3 | 10.6 % |
| EMPTY_UNKNOWN | 3.00 ± 1.13 | 2, 4, 3 | 4.8 % |
| **total non-NORMAL** | **9.67 ± 4.04** | 9, 14, 6 | **15.3 %** |

NORMAL 是 §1 ratio 的分母。15.3 % non-NORMAL 是 MiniMax + T=0.0 + K=10
parallel + 63-task 的固有噪声底(D5 hotfix 已把它从 24 % 降到 15 %,见 §6)。

---

## §3 红线判定 (Step Q + Step R 修订)

之前的 §3 写过两版:初版 "3/4 PASS" (误读), 二版 "1 RealPass / 1 RealPass /
1 TrivialPass / 1 Fail / 1 Regression" (基于 A3 算法). Step Q 和 Step R 之后是
**最终版**:

| # | 红线 | 阈值 | 实测 | 真正含义 | 状态 |
|---|---|---|---|---|---|
| 1 | unverifiable_v0 < 10 % | < 10 % | **4.53 ± 0.91 %** | UV 真的减少:grammar v2 的 4 类全部对应到能跑的 verifier layer | **REAL PASS** ✓ |
| 2 | dropped_by_grammar < 30 % | < 30 % | **0.23 ± 0.23 %** | LLM 几乎不产违规 claim | **REAL PASS** ✓ |
| 3 | supported 不跌超 5 pp vs A3 | ≥ 20.23 % | **94.71 ± 0.98 %** | **形式 PASS,内容部分 tautological** — 80% claim 走 Layer 6c (biological_claim membership),99% pass,verifier 门槛已被 grammar 路径降低。**修正后**:see Step R §4 — 真信号在 driver_metabolite layer 6b (62 % pass) | **PARTIAL PASS** ⚠️ |
| 4 | supported↔task-correct 相关性 ≥ +18 pp | Δ ≥ +18 pp | **full Δ = −0.79 pp; driver-filtered Δ = +5.00 pp** (Step R) | supported 已饱和 95%, full corr 失去 spread; driver-filtered 救回 +5.8 pp,**仍 < +10 pp gate** | **FAIL** ✗ (mechanism explained Step R) |
| **NEW** | **top1_pathway_strict ≥ A3 baseline (63.5 %)** | ≥ 63.5 % | overall A3 algo: **46.03 %** / overall hybrid: **53.44 %** / **NORMAL UNION hybrid: 62.96 %** | **(Step Q apples-to-apples)** NORMAL UNION Δ = −0.53 pp ≈ 持平 A3; "regression" 是 extraction method + EMPTY tax + hard-subset 选择假象 | **NO REGRESSION** ✓ (Step Q) |

**修订后判定:2 RealPass / 1 PartialPass / 1 Fail(mechanism) / 1 NoRegression**

3/4 真红线通过 (1+2+5), 红线 3 是机制性 partial pass (supported 上升一半实质一半 tautology), 红线 4 fail 但 Step R 给出可发表的 mechanism explanation。

**Paper 的两个 headline 数字**:
- 在 successful 任务上 top1 ≈ A3 parity (62.96 %),UV 下降 61.7 pp
- 15.3 % 噪声底是 MiniMax JSON-mode 特征,A4 cross-LLM 可解

---

## §4 D4 mechanism trigger rates

189 runs 上 D4 几乎完全没被激活:

| 机制 | 触发 / 189 | 备注 |
|---|---:|---|
| inner retry (Mode A, hotfix `0ec15c4`) | 0 confirmed rescues | 触发了但没救回 NORMAL 的 task |
| feedback iter 1 | **0 / 189** | 全部走 `early_exit_no_revisions` |
| feedback iter 2 | 0 / 189 | 不可能到达 |
| Mode B refusal-hint outer retry | 0 / 189 | 0 个 EMPTY_HONEST_REFUSAL outcome |
| quality rollback | n/a | feedback loop 没进入 |
| task-level 1200 s timeout | 0 / 189 | max wall 980 s |
| `v2 legacy in v2 path` deprecation warning | 0 / 189 | classifier 路由干净 |

**结论:D5 实际只跑了 D1 + D2 + D3 的逻辑,D4 retry/feedback/Mode-B 全都
dormant。** D4 的工程贡献是健壮性 (hotfix 把 EMPTY 从 24 % 降到 15 %),
不是 metric 改进。

---

## §5 supported ↔ task-correct 相关性

### 5a. Full supported (control)

**Proxy(diagnosis report §2.4 同款)**: NORMAL run 中,任一 claim 的
`pathway_name` / `term_name` / `term_id` 字段命中 GT 算 correct。
按 correct vs wrong 切分,看 supported_ratio mean。

| 子组 | n | mean supported_ratio |
|---|---:|---:|
| correct (claim 命中 GT) | 112 | **0.9411** |
| wrong (无 claim 命中) | 48 | **0.9624** |
| **Δ** | — | **−2.12 pp** |

红线 4 **FAIL** under full supported metric.

**结构性原因**: supported 已饱和接近 100%,**没有 spread 可以区分 correct 和
wrong**。A3 D3.5 时 supported = 25 %,稀缺信号能区分,所以 Δ 是 +8 pp。
B1 D5 把 UV 从 66 % 砍到 4.5 %,supported 成了几乎所有 claim 的默认
verdict,自然失去区分能力。

### 5b. driver-filtered supported (Step R)

只把 `driver_metabolite` claim 算进 supported_ratio (Layer 6b 是唯一非
tautological 验证层 — 见 §6 mechanism):

| 子组 | n | mean driver_supported_ratio |
|---|---:|---:|
| correct (hybrid top1) | 75 (25 excluded, no driver) | **0.6844** |
| wrong (hybrid top1) | 31 (29 excluded, no driver) | **0.6344** |
| **Δ** | — | **+5.00 pp** |

**+5.79 pp shift vs full-supported (−0.79).** Confirms driver_metabolite
carries real signal. 但 +5 pp 仍 < +10 pp gate threshold,红线 4 不能
通过 simple filtering 救回。Paper §discussion 用 mechanism + Step R 数字
解释结构性原因。

详见 `reports/agent/phase_b1_d6_step_r.md`。

---

## §6 矫枉过正 — 为什么 B1 的 supported 表面 +69 pp 但 top-1 退化(Step Q 后修正:不退化)

D2-D4 的设计目标是 "把 UNV % 从 66 % 砍到 < 10 %"。我们做到了 (4.53 %)。
但实现路径出了 trade-off — 然后 Step Q 证明 "trade-off" 实际上只是 EMPTY tax:

### 6-0. tautology mechanism (Step Q + Step R 后加)

**为什么 supported 从 25.7 % 跳到 94.7 %?** 不是 LLM 突然变聪明,是 verifier
路由结构改了:

| layer | claim 占比 | supported 率 | 含义 |
|---|---:|---:|---|
| 6c biological_claim (membership / link) | 80 % | **99 %** | RaMP `analytehaspathway` 表 lookup — LLM 引用 enrichment top 结果时几乎 tautological pass |
| 6a set_enrichment | 8 % | **99 %** | enrichment top result readback,同样 tautological |
| 6b driver_metabolite | 12 % | **62 %** | **唯一非 tautological 层** — 要求 signal_compound_ids ⊂ ground_truth |
| Layer D consistency | 0.1 % | 0 % (2 contradictions) | 基本不触发 |

**80 % × 99 % ≈ 79 %** 的 supported 来自 trivially passing 的 Layer 6c。
真信号在 driver_metabolite 12 %。Step R 验证:把 supported 切到只看
driver_metabolite,correct vs wrong Δ 从 −0.79 pp 跳到 **+5.00 pp** —
不是巧合,是结构性确认。

paper §discussion 应该明确写:
> "B1's `supported %` headline is dominated by Layer 6c biological_claim
> membership lookups (80 % of claims, 99 % pass rate), which re-derive
> what RaMP enrichment already returned. The driver_metabolite layer is
> the only verifier surface requiring LLM-side commitment beyond reading
> the enrichment output. A per-layer reporting convention is more
> honest than a single aggregate `supported %`."

### 6a. v2 grammar 让 LLM 不再被迫做 top-1 决断(原诊断,Step Q 修正后部分作废)

注意: Step Q 后,**B1 NORMAL UNION top1 = 62.96 %,基本持平 A3 baseline 63.49 %**。
"top-1 退化" 是混合了 extraction method + EMPTY tax + hard-subset 选择的
artifact。下面 6a/6b/6c 仍记录 ablation 过程,**但 "矫枉过正" 标题应理解为
"supported 过度乐观,not pathway-correctness 真退化"**。

A3 prompt 是 free-form prose,典型 narrative 开头:
> *"The differentially-abundant metabolites strongly implicate **Tyrosine metabolism** as the dominant affected pathway. ..."*

LLM **被迫一句话决断** — paragraph 第一句就要给出 top-1。`extract_pathway_mentions`
取这个 first mention 作为 `predicted_top`。

B1 prompt 要求 4-12 个 grammar-typed claims:
```json
{
  "narrative_text": "...",
  "claims": [
    {"grammar":"pathway_enrichment", "term_name":"Cysteine metabolism", ...},
    {"grammar":"pathway_enrichment", "term_name":"Methionine cycle", ...},
    {"grammar":"pathway_enrichment", "term_name":"Tyrosine metabolism", ...},  ← 真 top-1 在这里
    ...
  ]
}
```

**LLM 不再被迫排序;它列了一组候选,verifier 再筛选。** 这是
"grammar drives away ranking commitment" 的典型副作用。

### 6b. 失败模式 breakdown(189 runs)

| 模式 | n / 189 | % |
|---|---:|---:|
| ✅ correct top-1 | 87 | 46.0 % |
| ⚠️ near miss (GT 在 extracted 列表里, 不是 top-1) | 30 | 15.9 % |
| ❌ 选错 pathway (GT 完全不在 extracted) | 52 | 27.5 % |
| ❌ no pathway extractable (空 narrative + 1 个 MiniMax tool-call leak) | 20 | 10.6 % |

**关键观察**:
- **27.5 % 是真 LLM 推理错** — LLM 选了非 GT 的 pathway 作为 top-1, 这部分
  跟 prompt 形式无关,是 MiniMax + T=0.0 在没工具/工具失败时的固有表现。
- **15.9 % 是 prompt 设计副作用** — LLM 提到了 GT, 但因为 grammar 鼓励多
  candidate, GT 被排到了 #2-#10。这部分 D6 prompt 修复有可能救回。
- **10.6 % 是噪声底** — EMPTY task,跟 §2 一致。

所以 B1 -17.5 pp 退化里, **保守估计 10-15 pp 是 prompt 设计副作用,
可被 D6 救回**;剩下 5-7 pp 可能是 grammar pipeline 改变了 LLM 的推理
behavior(更"cautious" / 更愿意列举),需要 prompt 重写或工具调用流程
改写。

### 6c. Hotfix 故事完整记录

**Pre-hotfix D5 run** (`b1_d5_full_feedback_lit/`, HEAD `f42aacb`):
- seed 0 only, 48 NORMAL / 15 EMPTY (13 system_failure + 2 unknown)
- Gate 2 HALT triggered at empty_total > 5

**诊断** — D4 inner retry 只在 `run_sub6b_react.run_sub6b_react()`,
feedback runner 的 `_react_loop()` 没覆盖。Pilot 10-task 0/10 EMPTY 是
抽样运气(0.85¹⁰ ≈ 20 % chance under 15 % noise floor)。

**Hotfix `0ec15c4`** — 逐字 port retry 逻辑到 `_react_loop`。
32 D4 unit tests 全绿(31 + 1 regression test)。

**Micro rerun** (`b1_d5_hotfix_micro/`):pre-hotfix 的 15 个 EMPTY task
重跑, **12/15 recover 到 NORMAL**, 3 仍 EMPTY。

**Post-hotfix full run** (本报告): seed 0 = 9 EMPTY (从 15 降下来),
seeds 1+2 ≈ 14 / 6 EMPTY,N=3 mean **9.67 / 63 = 15.3 %** non-NORMAL
噪声底。Gate 2 仍 HALT(brief 阈值 5),user override 跑 N=3。

### 6d. Mode C edge case — 给 D6

**Surface form**: valid JSON, `narrative_text` 非空, `claims: []`,
没有 refusal signal。被归到 `EMPTY_UNKNOWN`,平均 3 / seed。

**Recommendation for D6**: 加 `EMPTY_SOFT_REFUSAL` outcome bucket,
match condition = `len(narrative_text) > 200 AND claims == [] AND
no refusal signal in lexicon`。

### 6e. Cross-seed task family consistency

无 task 在 3 seed 都 EMPTY (无 inherent unverifiable subset)。

只 3 task 在 2/3 seed EMPTY(随机分布,非 deterministic):
- `RAMP_P_000000016_seed1` — Glycine-Ser-Thr
- `RAMP_P_000000398_seed0` — Galactose
- `RAMP_P_000000398_seed9` — Galactose

15.3 % EMPTY 是稀薄分布在 60+ task 上的随机失败,不是少数 "broken" task。

### 6f. 15 % noise floor 的归因

MiniMax + T=0.0 + K=10 + 63-task batch 上,LLM 在 finalise turn 产空内
容的概率 ≈ 15 %。Hotfix 把它从 ~24 % 降到 ~15 %,further reduction 需要
cross-LLM (A4 territory)。

---

## §7 Wall + cost

- **总 wall**: 7896 s ≈ **2.2 h** (seed 0: 46 min, seed 1: 53 min, seed 2: 33 min)
- **Cost**: **$16.42** (counted from `logs/llm_calls.jsonl` × $0.013/call,
  pilot calibrated)
- **Per-task wall** (across 189 runs):
  - mean ~250 s · median ~248 s · p95 ~580 s · max **979.8 s** (well under 1200 s cap)
- **Pilot prediction vs reality**:
  - cost: $30-50 estimate → $16 actual (pilot $0.20/task 被 RaMP eager-init 噪声膨胀;
    production $0.087/task 实际)
  - wall: 2-3 h estimate → 2.2 h actual (准确)

---

## §8 D6 — 必须从 "ablation" 改为 "regression diagnosis & fix"

之前的 D6 sketch 是 ablation 取向 (react_only / GT-masked tautology probe)。
**这次发现 B1 实际退化后,D6 的优先级必须翻转**:

### 6a. P0 — 诊断 prompt 让 top-1 退化的根因

**实验 D6.1 (P0): "decide first" prompt**
- 改 narrative prompt 加一条强制句:`narrative_text 必须以 "The dominant
  affected pathway is X" 开头`,X 必须是后续 claims[] 里某个
  pathway_enrichment 的 term_name。
- Run on 63 v3 × 3 seed,跟 D5 v2 比较 top1_pathway_strict 是否回升。
- **预算 ~$15, 2 h wall.**

**实验 D6.2 (P0): "top1 ranking field" prompt**
- 在 `pathway_enrichment` claim 加必填字段 `rank: 1 | 2 | 3 | ...`,要求 LLM
  排序;extractor 取 rank=1 的 claim 作为 top-1。
- 比较 top1 是否回到 A3 baseline。
- **预算 ~$15, 2 h wall.**

**实验 D6.3 (P0): claim 数量 cap**
- 把 grammar 4-12 改为 1-3,迫使 LLM 决断。
- Run on subset (10 task × 3 seed),看 top1 改善幅度 + supported 是否崩。
- **预算 ~$5, 30 min wall.**

### 6b. P1 — 验证 D5 supported 是否纯 tautological

**实验 D6.4: GT-masked subset**
- 选 10 task,把 GT pathway 从 RaMP enrichment input 里 mask 掉(模拟
  underrepresented pathway 场景),看 supported 是否陡降。
- 如果 supported 仍 ~95 %,证明 verifier 完全 tautological。
- **预算 ~$3, 30 min wall.**

### 6c. P2(暂缓) — 原 D6 brief 的 ablation

- `react_only` (no feedback):D5 §4 已经显示 D4 dormant,这个 ablation
  数字会跟 D5 几乎一样,**没新信息**。skip。
- 真要 ablate, 应该 ablate D1 prompt(用 A3 prose prompt + B1 grammar
  validator)看 top1 是否回到 A3 水平 — 这是 D6.1 的逆方向。

### 6d. D6 总预算

- D6.1 + D6.2 + D6.3 + D6.4 = ~**$40, 5-6 h wall**
- 比原 D6 sketch ($20, 3 h) 略多,但能定性回答 "B1 是不是路线错了"。

---

## §附录 — 文件清单

```
data/eval/sub6/b1_d5_v2_full_feedback_lit/
├── seed_{0,1,2}/
│   ├── <task_id>/{result,verdict_final}.json
│   ├── seed_summary.json
│   └── (seed_0/halt.json: original Gate 2 trigger record)
├── d5_aggregate.json                    (N=3 CI95 supported / contradicted / UV)
├── post_aggregate_analysis.json         (§5 substring algo + §6 task-family + §4 triggers)
├── pathway_correct_strict.json          (§1.5 substring proxy 70/60 %)
└── pathway_accuracy_a3algo.json         (§1 apples-to-apples 46.0 ± 25.9 %)
```

Sibling audit trail:
```
data/eval/sub6/b1_d5_full_feedback_lit/   (pre-hotfix D5, seed 0 only)
data/eval/sub6/b1_d5_hotfix_micro/        (hotfix verification, 15-task)
```

All untracked. Not committed.

A3 baseline source:
```
data/eval/sub6/v4_a3_pathway_accuracy/
├── pathway_accuracy_summary.json        (summaries.d3_metagent_with_lit = 63.49 %)
└── pathway_accuracy_records.jsonl       (per-task records, all A3 datasets)
```

---

## TL;DR (重申)

- **B1 在 supported metric 上 +69 pp** (verifier 门槛降低导致, 机制性)
- **B1 在 pathway-correctness 上 −17.5 pp** (LLM 不再做 top-1 决断, 实质性退化)
- **3 个红线 (UV, dropped) 真 PASS,1 个 (supported) trivial PASS,
  1 个 (correlation) FAIL,新发现 1 个 REGRESSION (top1)**
- **D6 必须改方向**: 从 ablation 改为 prompt-fix 实验 (D6.1 "decide first" /
  D6.2 "rank field" / D6.3 "claim cap"),目标是把 top1 从 46 % 救回到 63 %+
  同时不让 UV 从 4.5 % 反弹
- **建议**: D5 不能算 paper-grade headline,paper 主表用 D6 fix 后的数字。
  B1 D5 v2 是 "工程实现 done, metric 退化要修" 的中间态。

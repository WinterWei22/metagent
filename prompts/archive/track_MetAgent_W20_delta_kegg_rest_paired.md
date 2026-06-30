# MetAgent W20 δ — KEGG REST KB tool + paired-comparison(variance-controlled)

Sprint 起算: 2026-06-12
Branch: `metagent-v2`
前置: W19 INCONCLUSIVE close-out(`docs/decisions/2026-06-12_w19_tool_output_verifier.md`)

## 0. Onboarding(D0)

读取 memory:
- 与 W19 D0 同名 14 条 + **新**`feedback_react_rerun_variance_control`(W19 新增,死命令)
- 读 `feedback_context_engineering_discipline`(死命令,不复述已落盘内容)

读取 W19 残留:
- `reports/agent/w19_tool_output_close_out.md`
- `docs/decisions/2026-06-12_w19_tool_output_verifier.md`
- `data/metagent/w19_dual_audit/claim_react_tool_output_fitness_inventory.csv`(569 tool_uncoverable 详单)

读取 W18 保存的 ReAct output:
- `data/metagent/w18_path_x_post_llm_judge_full63_d5_clean/path_x_full/`(59 task 完整 dump)
- 确认 raw claim text + carrier 可独立 replay verifier

baseline pytest 跑一次,确认 14-fail floor。

## 1. 核心架构差异:Paired Comparison(死命令)

**不重跑 ReAct**。W20 是 verifier-layer-only sprint。

```
saved W18 59-task ReAct output
  ├─→ V_a = W17 + W18 LLM-judge → baseline UV rate(应 ≈ 36.86% 或更接近,不重跑 ReAct 本身)
  └─→ V_b = W17 + W18 LLM-judge + W20 KEGG REST → treatment UV rate
       Δ = V_a UV − V_b UV(纯 W20 层净增益,ReAct 方差 = 0)
```

实现路径:
- 写 `scripts/metagent/w20_paired_verifier_replay.py`
- 输入: W18 saved ReAct output(claim + carrier)
- 输出: 两份独立 verifier 结果 JSONL,只差 W20 层
- 对比 per-claim verdict diff

**护栏**:V_a UV rate 必须 ±2pp 内复现 W18 close-out UV rate(36.45-36.86%),否则 replay infra 有 bug → STOP。

## 2. D1 — KEGG-coverable subset audit + ceiling gate

### D1.1 数据 audit($0)

对 W19 D1.1 输出的 569 tool_uncoverable claim,分类:
- **KEGG_strict**: claim 引用具体 KEGG pathway / KEGG compound ID / KEGG reaction,且可通过 KEGG REST 查到 ground truth
- **KEGG_fuzzy**: 提及 pathway 名 / metabolite 名但无 ID,需 name→KEGG ID 映射
- **KEGG_uncoverable**: 与 KEGG 无关(literature claim / PubMed-style / cross-tool comparison)

### D1.2 spot-check(20 row,$0)

手工核 20 条 KEGG_strict 是否真 KEGG REST 能查。≥80% 一致进 D1.3,否则 rubric 收紧重审。

### D1.3 ceiling gate(死命令)

按 `feedback_react_rerun_variance_control`:

| KEGG_strict ceiling | 决策 |
|---|---|
| ≥ 5pp(strict / total claim) | green-light W20 KEGG REST |
| 3-5pp | 必须 paired comparison(本 sprint 已是)+ multi-run avg 备份 |
| < 3pp | **STOP ping**,推荐换 KB(PubMed / Reactome / MetaboAnalyst REST) |

target = ceiling × 0.6,但**绝对最小 target = 2pp**(paired comparison 把噪音吃没,小信号也能看见)。

## 3. D2-D3 KEGG REST 实施

复用 `reference_verifier_llm_judge_pattern` 8 项模板:
- KEGG REST client(`bioservices.KEGG` 或 raw HTTP,缓存到 `data/metagent/w20_kegg_cache/`)
- KEGG result parser(deterministic 优先,如必须 LLM-judge 则跟 W18 同 pattern)
- Final-iteration dispatch guard
- Per-Path-X cost cap singleton(若用 LLM 解析 KEGG output)
- Trace JSONL: `logs/concord/w20_*_kegg_trace.jsonl`
- Carrier-priority excerpt(若用 LLM)
- Crash-time per-claim persist
- HEDGED 路径(若引入新 verdict)

### Deterministic vs LLM-judge KEGG 选择

D2 决断点:
- **Deterministic 优先**: KEGG REST 返回 ground truth → 跟 carrier 数据直接 string/numeric 对比 → $0 LLM cost
- **LLM-judge fallback**: 若 KEGG output 结构复杂(KGML / pathway map)需语义判断 → 复用 W18 LLM-judge pattern

session 写 D2 spec 时声明走哪条。

### KEGG REST 速率限制

KEGG bioservices 默认无 rate limit hard cap,但实际 ≤ 3 QPS 礼貌。加 retry + 缓存。

## 4. D4 — Paired-comparison full-59 run

**不重跑 ReAct**。只跑两套 verifier:

- V_a (baseline):W18 LLM-judge only on saved ReAct output
- V_b (treatment):V_a + W20 KEGG REST

输出:
- `data/metagent/w20_paired_full59/v_a_results.jsonl`
- `data/metagent/w20_paired_full59/v_b_results.jsonl`
- `data/metagent/w20_paired_full59/paired_delta.csv`(per-claim diff)
- `data/metagent/w20_paired_full59/w20_metrics.json`

Cost cap: $15 hard(若 LLM-judge KEGG output)。Deterministic 则 $0。

## 5. Hard Gates(20 项,简化版)

HG-1 14-fail floor 不退步
HG-2 W17 schema 类型不改
HG-3 B1-core helper 不改
HG-4 Tag immutable 不动
HG-5 signal_sub6 catch-all 不取消注释
HG-6 W19 代码不删
HG-7 V_a UV rate ±2pp 复现 W18 baseline(replay 健康)
HG-8 D1.3 KEGG_strict ceiling ≥ 3pp 才开实施
HG-9 D2 RED gate: KEGG REST client + parser unit test 通过
HG-10 D2 prompt 契约测试(若用 LLM-judge)
HG-11 D4 V_b vs V_a 净 UV drop ≥ 2pp(paired,无 ReAct 噪音)
HG-12 D4 W20 final CONTRADICTED TP 抽样 ≥ 70%(W18 是 85%)
HG-13 KEGG cache hit rate ≥ 50%(运行效率)
HG-14 Trace JSONL 完整(per-claim 必写)
HG-15 Crash-time per-claim persist 实现
HG-16 D4 cost actual ≤ $15
HG-17 Pathway bridge 不退步超 3pp(W18 88.1%)
HG-18 Iter-2 trigger 0(`DEFAULT_MAX_FEEDBACK_ITERS=1` 锁不变)
HG-19 Memory 文件无直改(草稿写 master log)
HG-20 close-out report 分开报 layer-attributable trace 与 aggregate(`feedback_react_rerun_variance_control` 要求)

## 6. 节奏(autonomous,8h+)

- D0 onboarding → master log,等批
- D1.1 audit + D1.2 spot-check → master log,等批
- D1.3 ceiling gate → 自动决策(≥5pp 自动进 D2,3-5pp ping,<3pp STOP)
- D2 RED → master log
- D3 GREEN per-piece → master log
- D4 paired full-59 → master log
- D5 close-out + decision doc + memory 草稿 → master log

每个 master log 死命令:中文 + 大白话 2 段。

## 7. 死命令汇总

- `feedback_react_rerun_variance_control`: paired comparison 是本 sprint 核心,**不准重跑 ReAct**
- `feedback_metagent_must_be_llm_driven`: KEGG REST 是 LLM 可暴露工具,但 V3 富集算法不暴露
- `feedback_verifier_modification_policy`: Add ✅ / B1-core ❌ / Schema 扩字段 ⚠
- `feedback_no_paper_writing_yet`: 不写 narrative
- `feedback_context_engineering_discipline`: 新阶段自动 compact / 不复述已落盘内容
- `feedback_plain_summary_at_end`: 每 master log 结尾 2 段大白话

## 8. Cost projection

| Phase | 预估 |
|---|---|
| D0-D1 audit | $0 |
| D2-D3 实施 | $0 |
| D4 paired(deterministic 路径)| $0 |
| D4 paired(LLM-judge fallback)| ~$8-12 |
| D5 close-out | $0 |
| **W20 max** | **$15 hard cap** |

## 9. Open question(blocker 写这,不阻塞主流程)

- 若 D1.3 KEGG_strict ceiling 3-5pp,paired comparison 是否够? → 默认够(信号> 2pp 即可识别),实测决断
- KEGG bioservices vs raw HTTP? → 默认 bioservices,问题再切

## End

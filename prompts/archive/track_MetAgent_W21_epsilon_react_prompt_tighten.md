# MetAgent W21 ε — ReAct prompt 收紧(source-side UV 压缩)

Sprint 起算: 2026-06-13
Branch: `metagent-v2`
前置: W20 INCONCLUSIVE close-out + 新策略转向(`feedback_verifier_side_marginal_returns`)

## 0. 战略背景

W17-W20 verifier 端边际递减:
- W17 (carrier): -14pp
- W18 (LLM-judge): -8pp
- W19 (tool-output): 0(噪音吞)
- W20 (KEGG): strict 2.03pp,< 3pp gate STOP

转 **ReAct 源头干预**。UV 来源 ~85% 在 ReAct 端(纯解读 50% + 模糊 25% + cross-tool 10%)可压。

## 1. 范围

**Strategy A only**: ReAct system prompt 收紧。不动 grammar(schema 扩字段 ⚠ 留 W22),不动 filter(post-ReAct drop 误删风险)。

**核心哲学(2026-06-12 决策修正)**:不是"禁止推断"——那损扩展性,违背 `feedback_metagent_must_be_llm_driven`。
真问题是 ReAct 把**事实陈述**和**推断假设**混在一起,verifier 分不清只能全打 UV。

W21 解法:**让 ReAct 自己把两类分开标**(只测标注版,user 2026-06-12 决策)。

1. **事实类 claim**: 声称是 tool output 事实的,必须挂证据(具体 tool / carrier / metabolite ID)
2. **推断类 claim**: biological insight / cross-tool synthesis / 机制假设 → **显式标 hypothesis**,不假装是 grounded fact
3. **不混淆**: 同一句话不要把事实和推断糅一起;先报事实,再分开给推断

关键: 推断类 claim 显式标了 hypothesis,**不进 UV 分母**(它本就没声称是 grounded fact,W18 HEDGED 思路挪到源头)。扩展性零损失,UV 仍能降。

## 2. Paired comparison 架构(死命令,`feedback_react_rerun_variance_control`)

ReAct 改 prompt = 端到端变量,必须 paired。

| 维度 | 控制 |
|---|---|
| Task seed | 同 task ID,同 input |
| Model | MiniMax-M2.7 同 model |
| ReAct framework | 同 verifier(W17+W18 LLM-judge,不加 W19/W20)|
| Variable | 仅 ReAct system prompt(baseline vs tightened)|
| 跑次 | 每 task 2 次:V_a baseline / V_b tightened |

Target: V_b UV − V_a UV ≤ -5pp(净降,paired 直接抵消方差)。

## 3. D0 onboarding

读 memory 15 条 + **新加**`feedback_verifier_side_marginal_returns`。

读 W19 + W20 close-out:
- `reports/agent/w19_tool_output_close_out.md`
- `reports/agent/w20_kegg_audit_close_out.md`
- `docs/decisions/2026-06-12_w19_tool_output_verifier.md`
- `docs/decisions/2026-06-12_w20_kegg_kb_audit.md`

定位 ReAct system prompt 文件:
- 主路径: `agent/prompts/react_system_prompt.py` 或 `concord/prompts/react_system.txt`(session 自查)
- 死命令: B1-core helper 不动(`claim_extractor.extract_claims_from_json` / `feedback_hints.build_feedback_message` / `verifier/agent.py:_extract_classify`)
- ReAct prompt 改属 ✅ Add 区(不属 B1-core)

baseline pytest → 14-fail floor。

## 4. D1 — Prompt draft + 死命令检查($0)

### D1.1 draft tightened prompt

在现有 ReAct rules 段后追加 `## Claim Discipline` 节。核心是**分类**而非禁止。

样本 wording(session 可调):
```
## Claim Discipline

Separate your claims into two kinds. Do NOT blur them into one sentence.

1. **Factual claims** — anything you state AS a tool result MUST cite a specific
   evidence source by name and identifier:
   - GOOD: "mummichog top_pathways[3] = 'glycolysis' (p=0.012)"
   - BAD: "glycolysis appears relevant" (no source → either cite it or mark it as hypothesis)

2. **Hypothesis claims** — biological interpretation, mechanism, or cross-tool
   synthesis that goes beyond a single tool's direct output MUST be explicitly
   labelled as a hypothesis, not asserted as fact:
   - GOOD: "Hypothesis: citrate cycle dysfunction may drive the phenotype
            (interpretation, not directly measured)"
   - GOOD: "Hypothesis: since Mummichog and RaMP both rank TCA highly, TCA is
            likely central (cross-tool inference)"
   - BAD: "citrate cycle dysfunction drives the phenotype" (stated as fact, no evidence)

You are ENCOURAGED to make biological hypotheses — that is your value. Just label
them honestly so they are not mistaken for measured facts. A clearly-labelled
hypothesis is good; a disguised one is not.
```

注意: 这版**保留 ReAct 的推断/扩展能力**,只要求诚实标注。verifier 端对显式 hypothesis claim 的处理(不进 UV 分母)是否需要配套调整,D2 pilot 数据出来后看——若 ReAct 标了 hypothesis 但 verifier 仍打 UV,则需 verifier 侧识别 hypothesis 标记(留 D2 决断,可能溢出到小改 verifier)。

输出: `docs/decisions/2026-06-13_w21_react_prompt_diff.md`(草稿,标 ⚠ proposed)

### D1.2 死命令冲突检查

- B1-core 不动 ✅
- W17 schema 不动 ✅
- claim grammar 字段不动 ✅
- DEFAULT_MAX_FEEDBACK_ITERS=1 不动 ✅
- LLM-driven 原则 ✅(prompt 是 LLM 的指令,不是 deterministic algorithm 暴露)

### D1.3 spot-check: 1-task dry-run($0)

不调真 LLM。Mock 一个 task,看 tightened prompt 是否能被 ReAct framework 正确加载。仅 shape 测试。

## 5. D2 — Pilot 5-task paired($5)

### D2.0 ⚠ verifier 配套(必 ping,先于 pilot)

**关键**(W19 反面教训:不能只测半条 pipeline):
ReAct 标了 `Hypothesis:` 但 verifier 若不认这个标记,照样查证据 → 照样打 UV → prompt 改了也白改,pilot 会假阴性。

所以 pilot 前必须决定 verifier 怎么处理 hypothesis-标记的 claim。两个选项:

- **选项 1(最小改动)**: verifier 识别 claim 文本里的 `Hypothesis:` / `(interpretation, not directly measured)` 标记 → 归一个新 bucket(类似 W18 HEDGED),不进 UV 分母也不进 SUPPORTED。改动落在 `verifier/claim_table.py` + classify 入口,属 ⚠ Modify。
- **选项 2(零 verifier 改动)**: 不改 verifier,pilot 直接测——但需先确认 verifier 现状对 `Hypothesis:` 前缀 claim 实际怎么分类的(可能已归 BIOLOGICAL → UV)。若现状就是全 UV,则选项 2 注定假阴性,必须走选项 1。

**session 在 D2.0 必须 STOP ping me**,报告:
- verifier 现状对 hypothesis-标记 claim 的实际处理(抽 2-3 个样本跑一次看)
- 推荐选项 1 还是 2
- 若选项 1,列出具体改哪几行 + 是否破 14-fail floor

我决断后才进 D2.1。**不准自动改 verifier**(`feedback_verifier_modification_policy` ⚠ 档需 ping)。

### D2.1 task 采样

从 W18 59 task 选 5 个,分层(Mummichog/RaMP/MetaboAnalystR 各至少 1)。

### D2.2 paired 跑

每 task:
- V_a: baseline prompt + W17+W18 verifier(现状)
- V_b: 标注版 prompt + W17+W18 verifier(+ D2.0 决断的 hypothesis 处理)

输出:
- `data/metagent/w21_pilot_5task_paired/v_a_results.jsonl`
- `data/metagent/w21_pilot_5task_paired/v_b_results.jsonl`
- `data/metagent/w21_pilot_5task_paired/pilot_metrics.json`

Cost cap: $6。

### D2.3 Pilot gate

| V_b − V_a UV delta | 自动决策 |
|---|---|
| ≤ -5pp(净降 ≥ 5pp)| **自动进 D3 full-59 paired** |
| -5pp 到 -2pp | **ping me**(信号有但需决断是否值得 full)|
| > -2pp 或回归 | **STOP**,W21 inconclusive close-out |

抽 3 个 task 看 claim 数 / claim 质量 diff,确认 tightened prompt 没把好 claim 也删了。

## 6. D3 — Full-59 paired($30)

只在 pilot gate 自动过通过时跑。

- 59 task × 2 prompt = 118 ReAct runs
- W17+W18 verifier(不加 W19/W20)
- Cost cap: $32 hard
- Trace JSONL 必写

输出:
- `data/metagent/w21_full59_paired/v_a_results.jsonl`
- `data/metagent/w21_full59_paired/v_b_results.jsonl`
- `data/metagent/w21_full59_paired/w21_full59_metrics.json`
- `data/metagent/w21_full59_paired/claim_diff_crosswalk.csv`(per-claim V_a vs V_b verdict + claim text diff)

## 7. D4 — close-out + decision doc + memory 草稿($0)

按结果定性:
- V_b − V_a ≤ -5pp: **SUCCESS**
- -5 到 -2pp: **PARTIAL**
- > -2pp: **INCONCLUSIVE / FAILED**

产出:
- `reports/agent/w21_react_prompt_tighten_close_out.md`
- `docs/decisions/2026-06-13_w21_react_prompt_tighten.md`
- `conversation/master/{date}_{time}_w21-memory-suggestions.md`

## 8. Hard Gates(15 项)

HG-1 14-fail floor 不退步
HG-2 B1-core 不改
HG-3 W17 schema 不改
HG-4 claim grammar 字段不改
HG-5 DEFAULT_MAX_FEEDBACK_ITERS=1 不动
HG-6 LLM-driven 原则不破(prompt 改 ✅)
HG-7 paired 架构严守,同 task ID / 同 verifier
HG-8 D1.3 dry-run 通过(prompt 能被加载)
HG-9 D2 pilot V_a UV rate ±3pp 复现 W18 baseline 36.45-36.86%(健康)
HG-10 D2 pilot gate 严守(≤-5pp 才自动 full)
HG-11 D3 V_b 不能比 V_a claim 数减少 > 30%(没把好 claim 也删了)
HG-12 D3 trace JSONL 完整
HG-13 D3 cost ≤ $32
HG-14 pathway bridge V_b 不低于 V_a 超 3pp
HG-15 memory 文件不直改,草稿写 master log

## 9. Cost projection

| Phase | 预估 | Cap |
|---|---|---|
| D0-D1 | $0 | $1 |
| D2 pilot 5-task | $5 | $6 |
| D3 full-59 paired | $30 | $32 |
| D4 close-out | $0 | $0 |
| **W21 total** | **~$35** | **$39 hard** |

仍比 W18 $24 + W19 $6.96 + W20 $0 = $31 累计高,但是**首次 source-side 干预**,值得验。

## 10. 死命令汇总

- `feedback_verifier_side_marginal_returns`: 转 ReAct 端干预的指导思想
- `feedback_react_rerun_variance_control`: paired 架构强制
- `feedback_metagent_must_be_llm_driven`: ReAct prompt 改 = ✅,不暴露 deterministic algorithm
- `feedback_verifier_modification_policy`: prompt 改 ✅ Add 区,B1-core ❌
- `feedback_no_paper_writing_yet`: 不写 narrative
- `feedback_context_engineering_discipline`: 新阶段自动 compact
- `feedback_plain_summary_at_end`: 每 master log 2 段大白话

## End

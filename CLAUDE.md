# MetAgent — Project Brief

**Worktree:** `/home/weiwentao/workspace/llm_agent_metabolomics/metagent_v2`
**Branch:** `metagent-v2`
**Last sprint:** W15 UV attribution audit (HEAD `de6cf5a`,2026-05-26)
**Sibling worktrees:**
- `metagent_day1_v5` (main, B1 paper data,frozen tag `metagent-v2-base-b1` @ `ed6243b`)
- `metagent_day1_v5_investigation` (ConcordMet 5-PA wrapper调研,frozen tag `metagent-v2-base-investigation` @ `3ffe621`)

---

## 项目目标

MetAgent 是一个**LLM 多代理代谢物鉴定系统**,核心目标是把传统"输出 top-1 候选 +
打分"的范式重构为"输出可审计的鉴定报告":

- **输入**:一张 MS/MS 谱(m/z + 强度数组)、precursor m/z、电离模式、加合物猜测,
  以及可选的自由文本上下文("人类肝脏样本,关注胆汁酸相关代谢物")
- **输出**:结构化 `IdentificationReport`,包含按证据排名的候选结构、每张峰的结构
  归属解释、生物学通路上下文、PubMed PMID 文献证据、以及**自验证 (Verifier) 阶段**
  的完整审计轨迹

设计哲学(`docs/ARCHITECTURE.md` 落地):
- **Schemas are law** — 所有 tool 边界由 Pydantic 契约固化,放在 `schemas/`,tool 单向依赖
- **Tools are narrow** — 一个 tool = 一个 LLM 视角的意图,而非一次 DB query
- **Tools are independent** — tool 间不互相 import,组合只在 orchestrator 发生
- **Every claim is verifiable** — PMID 必须能在 Europe PMC 解析,KEGG/HMDB ID 必须能
  在对应库解析,峰归属必须 cite 预测 fragment;**Verifier 阶段强制这一点**

整个系统分两个 Stage:
- **Stage 1 — 单谱代谢物识别**(Per-spectrum identification):输入一张 MS/MS 谱
  → 输出一个 ranked candidate report。涉及谱预处理、library search、生成式 SMILES
  候选、metabolite info 拉取、通路上下文注入、forward spectrum prediction、文献
  搜索 + Verifier 自验证。这是 B1 Phase 的核心工作,数据集为 sub6a (real-id) /
  sub6b (perfect-id)。
- **Stage 2 — 富集分析后的代谢物鉴定 / 路径解释**(Post-enrichment pathway-level
  identification & narrative):输入一组 differentially-abundant 代谢物 → 输出
  pathway-grounded narrative + 结构化 claims,通过多 paradigm 富集工具(RaMP-DB
  ORA、Mummichog、MetaboAnalystR PSEA、FELLA、SSPA)的 LLM-driven ReAct
  orchestration 实现。这是 W8 → W15 的核心工作,benchmark 为
  `sub6b_mammalian_tasks_v3.jsonl` (63 task)。**当前会话只涉及 Stage 2**。

---

## 核心架构决策

### 1. Stage 1 工具栈(B1 Phase)
- **为什么 7-tool 窄腰结构(`docs/TOOL_CONTRACTS.md`)**:每个 tool 单一意图、独立
  容器化、可独立替换。LLM 看到的契约稳定,可以换 backbone 而不改 tool。
- **为什么 Verifier 是独立 agent 而非 orchestrator 内置 check**:hallucination 检
  测需要"事后审计"视角,与"生成 candidates"的认知任务正交;独立 agent 才能用不同
  prompt + LLM 调用 budget 做严格 cite check。
- **关键约束**:Verifier 4-shape grammar(`pathway_membership` /
  `metabolite_pathway_link` / `pathway_enrichment` / `driver_metabolite`)— 任何
  超出这 4 个 shape 的 claim 都会被判为 UNVERIFIABLE_V0,产生 W8+ 一系列扩展工作。

### 2. Stage 2 多 paradigm ReAct orchestration(W8 → W14)
- **为什么 LLM-driven function-tool 而非 deterministic pipeline**:5 个富集 paradigm
  (ORA、Mummichog、PSEA、FELLA、SSPA)结果异构;不同 task pattern 需要不同 paradigm
  组合;hard-coded combinator 写不动也不能 generalise。**死命令 2026-05-17:必须
  LLM-driven。**
- **为什么 ConcordMet 5-PA wrapper 收编进 verifier 路径**:`concord/` 的 5 个
  wrapper 提供 deterministic 工具结果;LLM 通过 ReAct 调用它们;Verifier 再用 B1
  4-shape grammar 审计 narrative。三层分工:Tools 提供事实 / LLM 解释 / Verifier
  审计。
- **为什么 Verifier 不分 ReAct path / single-shot path 两套代码**:`verify_sub6()`
  在两个路径上语义一致,仅 dispatcher case 差别。W12 D3 + W12 D4 +
  W13.A GREEN 都遵循这个不变量。
- **为什么 W13.C 后选 `max_feedback_iters=1`(W14.B)**:N=14 iter-2-degraded task
  上 14/14 unsupported gains 主导 iter-2 quality 上升(H3_CONFIRMED),iter-2 净破坏。
  W14.B 单行 config 改动验证 iter-2 触发率 0/63、cost −31%、UV 进一步降 3.54 pp。

### 3. Verifier modification policy(2026-05-22 三档)
- ✅ **加新代码**:新 enum / 新 layer / 新 helper(自由)
- ⚠ **改现有 verifier 逻辑**:commit body 必须含 `[verifier-modify-warning]` +
  justification + B1 test no-regression 实测数字
- ❌ **改 B1 D5/D6 核心 helper**(`claim_extractor.extract_claims_from_json` /
  `feedback_hints.build_feedback_message` / `verifier/agent.py:_extract_classify`)
  默认禁

3 条护栏:
- `metagent-v2-base-b1` tag @ `ed6243b` immutable
- `data/eval/sub6/b1_d5_*/` + `data/eval/sub6/a3_rerun_*/` immutable
- B1 test floor 14 fail 不退步

### 4. UV 优化 sprint 必走 strict-vs-fuzzy reclassification(W12 教训)
- **为什么**:W11 9-cat 分类只看 surface form,目标 W14 sprint 假设 C8+C9 ≈ 15%
  UV,实际重分类后只 9.5% strict_noise(ceiling 1.27pp);W12 spec 假设 80%
  recoverable 实际只 54%。**任何 UV 优化 sprint §0 第一件事就做 reclassify**
  (memory `feedback_uv_sprint_must_reclassify_first`)。
- W15 进一步要求 **3-way attribution audit**(producer_fault / verifier_gap / both),
  区分"LLM 写错"(prompt 修)vs"verifier 没法判"(layer 修)。

### 5. 严格 TDD + ⚠ commit body audit
- 每个 piece 先 RED 再 GREEN,独立 commit
- ⚠ modify verifier/ 必须 `[verifier-modify-warning]` body
- ⚠ modify concord/ 必须 `[concord-modify-warning]` body
- W8 → W15 累计 **~60 commit / 0 strict-TDD slip**

---

## 当前进度(Stage 2 W8 → W15 完整 ledger)

### 已完成

**Stage 1(预 W8)**:7-tool 栈完整 land(spectrum_ops / library_search /
molecule_gen / metabolite_info / pathway_context / spectrum_predict /
literature_search);B1 sub6a + sub6b 数据集冻结;`tag metagent-v2-base-b1`。

**W8-W9** ConcordMet 5-PA wrapper(SSPA / Mummichog / RaMP / MetaboAnalystR /
FELLA)+ ReAct dispatcher + 9-function-tool 集成(`concord/agent/`)

**W10 D4** Path X 首次全 63-task 跑(W10 D4 baseline:UV 52.95%、pathway 准
54/63 = 85.7%)

**W11** UV 9-cat 诊断(`reports/agent/concord_w11_uv_diagnosis.md`,1102 UV claim
LLM-classify into C1-C9)

**W12** C7 namespace_form fix → `factual_sub6` layer + set_enrichment fuzzy
match(UV 52.95 → 51.45,pathway 持平,cost $11.17)

**W13** A 扩 `_ID_PATTERNS` + subject normaliser + C iter-2 root-cause
(H3_CONFIRMED)→ UV 51.45 → 47.79(−3.66 pp),iter-2 deg 22.22% →
15.87%(副作用),pathway 持平,cost $9.90

**W14** A noise prompt + grammar `NOISE_PATTERN` subtype + B
`DEFAULT_MAX_FEEDBACK_ITERS=1` → UV 47.79 → **44.25%**(−3.54 pp,4.66× target),
iter-2 trigger 61/63 → 0/63,cost $9.90 → $6.83(−31%),pathway 持平
86%

**W15** UV attribution audit(no production change):
- 901 UV 三分类:**verifier_gap 52.5% / producer_fault 27.9% / both 19.6%**
- W11 9-cat × attribution cross-tab,出 W16 候选 ranked
- HG-2(20-sample agreement)60% strict / 100% axis-level(`both` boundary 模糊,但 producer↔verifier 主轴 0 硬冲突)
- Cost $0.93(v1 + v2 + retry,纯 audit)

### Cumulative UV reduction(W10 D4 → W14)

| sprint | UV % | Δ |
|---|---:|---:|
| W10 D4 baseline | 52.95 | — |
| W12 D5 (post C7 dispatch) | 51.45 | −1.50 |
| W13.A (post extended ID + normaliser) | 47.79 | −3.66 |
| **W14 (post noise + cap)** | **44.25** | **−3.54** |
| **cumulative drop** | | **−8.70 pp** |

Pathway accuracy 全程持平 **54/63 = 85.7%**,iter-2 trigger 0/63,total cost W10
→ W14 ~$40。

### 进行中 / 等开干

**W16-A(推荐)C7 producer prompt tighten**:基于 W15 v2 数据,C7 producer rate
50.8%(v1 43.8% → v2 50.8% 验证 prompt-side lever 正确)。预计 4.57 pp UV
ceiling,~3 day,prompt-only 不动 verifier。

### 下一步候选

| # | candidate | strict ceiling | ease | tentative sprint |
|---|---|---:|---|---|
| 1 | C7 producer prompt tighten | 4.57 pp | high | W16 |
| 2 | C9 sub-classification audit | 11.39 pp gross | low | W17 prereq |
| 3 | C9 producer prompt subset | 3.19 pp | high | W17 alternative |
| 4 | C3 signal_evidence verifier layer | 5.06 pp | low | W18 |
| 5 | C5 KEGG REACTION verifier layer | 4.17 pp | very low | W19+ |

完整 ranked 表 + 数据 backing 见 `data/metagent/w15_uv_attribution/summary.md`。

### Stage 1 / Stage 2 之间的连接

Stage 2 的 Verifier 路径 import Stage 1 build 的 schemas(`verifier/schemas.py`
的 `ClaimVerdict` / `VerifiedIdentification` / `DroppedClaim`)和 B1 D2 的
`extract_claims_from_json`(grammar v2 JSON parse,zero-LLM extract)。Stage 2 不
反向 import Stage 1 工具,但通过 `verifier.agent.verify_sub6()` 的 4-shape
grammar 强制对齐。

---

## 已知问题 / 绕坑记录

### 解决了的

| 问题 | 解法 / 涉及 commit |
|---|---|
| `extract_claims` 在 grammar-v2 JSON path 下重复 LLM call | B1 D2 commit `2354011` —— 自动 detect grammar-v2 JSON → `extract_claims_from_json` zero-LLM(W10 P0-C regression lock) |
| W10 D4.5 iter-2 quality degradation 11.3% | W13.C verified H3_CONFIRMED(richer feedback overshoot);W14.B `max_feedback_iters=1` 锁死(iter-2 trigger 0/63) |
| `str(Enum)` 在 Py3.11+ 返回 `"ClassName.MEMBER"` 而非 value | W10 D2.5 fix(`52613ac`)concord react_runner verdict filter 改 enum equality |
| W12 spec target -12 pp 超 ceiling(实际 1.27 pp) | W12 D ceiling re-classify(commit `edb8fe4`)校准,W13 起强制 §0 reclassify |
| W14 §0 期望 C8+C9 ≈ 15% UV 实际 9.5% | W14 §0 reclassification 落地(memory `feedback_uv_sprint_must_reclassify_first`),W14 主要价值转 B(iter-2 cap)|
| W11 9-cat 分类粒度过粗(W12 教训) | W15 加 3-way attribution audit(producer/verifier/both),修正 W16 候选排名(C7 producer rate v1→v2 +7pp) |

### 未解决 / 待 W16+

| 问题 | 原因 | W16+ 处置 |
|---|---|---|
| W15 HG-2 strict 20-sample agreement 60% < 80% | rubric 自身边缘歧义("both" 标准 LLM 与人类不一致) | 接受 v2 + axis-level 100% 透明 caveat;summary.md §3 记录;不阻塞 W16 ranking |
| W14 §0 134 valid_content 仍归 C9 | W14 §0 schema 是 binary(strict_noise vs valid_content),没细分 | W15 v2 已经做完(C9 大头 232 claim 中:verifier 119、producer 65、both 48) |
| C9 还有 11.39 pp gross ceiling 未拆 | W15 v2 cross-tab 揭示 C9 是 mixed bucket | W17 候选 — sub-classification audit 0.5 d |
| `data/concord/metanetx.sqlite` 只有 compound xref,无 pathway xref | external data limitation | W12 D4 commit `2239fcf` skip pathway cross-walk + 透明记录(future PathBank dep) |
| `verifier/grammar.py` `DroppedReason` enum 仅 1 个 value(`NOISE_PATTERN`) | W14.A 新加,W15 没用上 | 未来 sprint(C8 follow-up / 其他 dropped reason)再扩 |
| Stage 1 (sub6a real-id) 离 paper-grade 还差 driver-filtered correlation Δ ≥ 18pp red line(B1 #4) | 实测 +3.50 pp,durable FAIL | 已 documented 为 Discussion limitation;不阻塞 ConcordMet 工作 |

### 死命令(全工作流必守)

- 中文对话,英文代码 / 标识符
- 模型名 **MetAgent**(不是 ConcordMet — 后者是 sibling investigation worktree
  的 spike artifact)
- 不写 paper narrative / Discussion / Methods / Results / footnote
- MiniMax 是远程 API:cost 必须查 `logs/llm_calls.jsonl` 实测,**禁说 "$0 local"**
- 每条 ping 结尾 2 段大白话总结(进展 + 下一步,1-3 句各)
- ConcordMet 必须 LLM-driven,不暴露 V3 deterministic 算法 tool
- 三档 verifier 修改 policy(见上)
- 3 条护栏(tag / B1 数据 / B1 test floor)
- UV 优化 sprint §0 强制 reclassify

---

## 目录结构说明

### 顶层组织

```
metagent_v2/
├── CLAUDE.md                  # 本文件 — 项目交接
├── README.md                  # 公开向 README(v0 高层介绍)
├── docs/
│   ├── ARCHITECTURE.md        # 系统设计哲学(必读)
│   ├── TOOL_CONTRACTS.md      # Stage 1 7-tool I/O 契约
│   ├── claim_grammar_v2.md    # Stage 2 grammar v2 spec(B1 D1 引入)
│   ├── LLM_INTEGRATION.md     # LLM client / provider switch / cache
│   └── concord/               # Stage 2 ConcordMet 设计文档(W3-W7 早期)
├── schemas/                   # Pydantic 契约(law)
│   ├── report.py              # IdentificationReport (Stage 1 主输出)
│   ├── sub6_report.py         # SubsixSourceReport (Stage 2 富集 task 输入)
│   └── peak.py / spectrum.py  # Stage 1 谱 / 峰
│
├── tools/                     # Stage 1 — 一子目录一 tool
│   ├── spectrum_ops/          # 谱 preprocess (track A1)
│   ├── candidate_prefilter/   # 候选预筛 (track A2)
│   ├── library_search/        # MS/MS library 搜 (track B)
│   ├── molecule_gen/          # 生成式 SMILES 候选 (track C)
│   ├── metabolite_info/       # HMDB/KEGG/ChEBI fetch (track D1)
│   ├── pathway_context/       # 通路上下文 (track D2)
│   ├── spectrum_predict/      # CFM-ID / SIRIUS forward (track E)
│   ├── literature/            # PubMed / Europe PMC (track F)
│   ├── agent_tools/           # 通用 LLM tool 适配层
│   ├── lipidmaps/             # LIPID MAPS 子工具
│   ├── classyfire/ kegg/ sirius/  # 第三方 wrapper
│   ├── benchmark/             # benchmark 数据加载
│
├── orchestrator/              # Stage 1 LLM 编排
│   ├── naive.py               # baseline naive orchestrator
│   ├── prompt.py / formatter.py
│   └── __main__.py            # CLI entry
│
├── verifier/                  # B1 Phase Verifier(Stage 1 + Stage 2 共享)
│   ├── agent.py               # verify() spectrum entry + verify_sub6() Stage 2 entry
│   ├── grammar.py             # claim grammar v2 (4 shape) + DroppedReason enum
│   ├── claim_extractor.py     # B1 D2: extract_claims / extract_claims_from_json
│   ├── claim_classifier.py    # 9-cat → 4-shape collapse (B1 D3)
│   ├── feedback_hints.py      # B1 D4 反馈 hint (annotate_claims)
│   ├── task_outcome.py        # NORMAL / EMPTY_* 4 enum (B1 D4)
│   ├── layers/                # 各层判定
│   │   ├── factual_sub6.py    # W12 D3 — Sub-6 friendly factual layer (new)
│   │   ├── biological_sub6.py # Sub-6 biology layer
│   │   ├── set_enrichment.py  # Layer 6a (W12 D4 token-Jaccard fuzzy)
│   │   ├── driver_metabolite.py / pathway_relationship.py / ...
│   ├── helpers/               # W13/W14 引入
│   │   ├── fuzzy_match.py     # W13.A token-Jaccard helper
│   │   ├── subject_normalizer.py  # W13.A NFKD + Greek-to-Roman + whitespace
│   │   └── noise_pattern.py   # W14.A noise regex (meta-filler / boilerplate)
│   └── schemas.py             # ClaimVerdict / VerifiedIdentification / DroppedClaim
│
├── concord/                   # Stage 2 5-PA dispatcher + ReAct runner
│   ├── agent/
│   │   ├── react_runner.py    # ConcordReactRunner (W8) + verify_with_b1 (W8 D4)
│   │   ├── system_prompts.py
│   │   ├── tool_dispatcher.py # 9 function tool 路由
│   │   ├── tool_handlers.py
│   │   └── verifier_adapter.py # ConcordReactResult → SubsixSourceReport
│   ├── wrappers/              # 5 PA wrapper (W3-W7)
│   ├── normalize/             # wrapper output → v0.3.1 schema 适配
│   ├── reconcile/             # cross-source ID + charge state
│   ├── analyze/               # paradigm_consensus / pathway_match / gate2_variants
│   ├── etl/                   # ChEBI / MetaNetX / Cooke / PathwayMembers ETL
│   ├── lookup/                # ChEBI thread-safe lookup
│   ├── schema/                # EnrichmentResult / PathwayHit / CompoundRef
│   └── figures/               # Fig 3 数据
│
├── evaluation/
│   ├── sub6/                  # Stage 1 sub6a/sub6b 单谱 eval runner
│   │   ├── run_sub6a.py       # real-id 鉴定 eval
│   │   ├── run_sub6b.py       # perfect-id narrative eval
│   │   ├── run_sub6b_react.py # ReAct + tools eval
│   │   ├── run_sub6b_react_feedback.py  # ReAct + verifier feedback closed loop (B1 D4)
│   │   └── prompts.py         # narrative prompt templates
│   └── concord/               # Stage 2 Path W/X/Y/Z runner
│       ├── path_x.py          # Stage 2 主 eval (full 63 task)
│       └── ...
│
├── prompts/
│   ├── concord/concord_react_prompt.md    # Stage 2 system prompt (W8 锁定 + W14 BANNED PHRASES)
│   ├── agent/sub6b_react*.md  # Stage 1 narrative prompt
│   ├── track_AGENT_phase_B1_*.md  # B1 sprint spec
│   ├── track_CONCORD_*.md     # Stage 2 W8-W14 sprint spec
│   └── track_MetAgent_W15_*.md  # W15 sprint spec
│
├── tests/                     # B1 verifier-core + W12-W15 unit + concord/ integration
│   ├── test_verifier/         # B1 D2-D4 unit (~320 cases)
│   ├── test_factual_sub6.py   # W12 RED→GREEN
│   ├── test_factual_sub6_id_patterns_extended.py  # W13.A RED→GREEN
│   ├── test_grammar_noise_pattern.py + test_concord_react_prompt_banned.py  # W14.A RED→GREEN
│   ├── test_react_runner_iter_cap.py  # W14.B RED→GREEN
│   ├── test_w15_uv_attribution_extractor.py  # W15 D1 pure-audit
│   ├── concord/               # W3-W9 ConcordMet 单元 + integration (148+ cases)
│   └── ...
│
├── scripts/
│   ├── concord/               # W3-W14 ConcordMet driver
│   │   ├── w10_d4_path_x_full.py        # Stage 2 主 eval driver(W10 起复用)
│   │   ├── w11_extract_uv_claims.py / w11_classify_uv_claims.py
│   │   ├── w12_d_reclassify_c7_strict_vs_fuzzy.py
│   │   ├── w13_c_iter2_diagnostic.py
│   │   ├── w14_c8c9_strict_vs_valid.py
│   │   └── setup_metagent_v2_env.sh     # 必跑 — symlink chebi/metanetx sqlite
│   ├── eval_sub6/             # Stage 1 sub6 aggregator
│   └── metagent/              # W15 起 audit script
│       ├── w15_uv_attribution.py
│       └── w15_v2_retry.py
│
├── data/
│   ├── benchmark/sub6/        # sub6b_mammalian_tasks_v3.jsonl (63 task)
│   │   └── curated_hmdb_mammalian.jsonl  # W12 factual_sub6 fallback pool
│   ├── concord/               # Stage 2 ETL / eval artifact
│   │   ├── chebi.sqlite       # gitignored,setup script symlink
│   │   ├── metanetx.sqlite    # gitignored,setup script symlink
│   │   ├── pathway_members.sqlite
│   │   ├── w10_d4_path_x_full/                  # W10 D4 baseline data
│   │   ├── w12_path_x_post_c7/                  # W12 D5 data
│   │   ├── w13_a_path_x_post_extended_id/       # W13.A data
│   │   ├── w14_path_x_post_noise_cap/           # W14 D5 data(最新)
│   │   ├── w11_uv_diagnosis/                    # W11 9-cat 数据
│   │   ├── w12_uv_ceiling/                      # W12 §0 reclassify
│   │   ├── w13_c_iter2_diagnostic/              # W13.C H3 verdict
│   │   ├── w14_uv_reclassify/                   # W14 §0 reclassify
│   │   └── w10_d4_5_degradation_diagnostic/     # W10 D4.5 H1 verdict
│   ├── metagent/              # W15 起 audit data 新 root
│   │   └── w15_uv_attribution/                  # W15 v1 + v2 + summary
│   └── eval/sub6/             # B1 Stage 1 data — IMMUTABLE per 护栏
│       └── b1_d5_*/, a3_rerun_*/
│
├── reports/
│   └── agent/                 # 每个 sprint 的 close-out + status doc
│       ├── concord_sprint_w*_status.md
│       ├── concord_w*_close_out.md
│       ├── concord_w11_uv_diagnosis.md
│       ├── phase_b1_*.md
│       └── ...
│
└── logs/
    ├── llm_calls.jsonl        # 全局 LLM call log(cost 来源)
    └── concord/               # 各 sprint 独立 log file
```

### `concord/agent/react_runner.py` 关键点

- `DEFAULT_MAX_FEEDBACK_ITERS = 1`(W14.B,was 2)
- `ConcordReactRunner.verify_with_b1()` 在 line 679,把 ReAct narrative 喂给
  `verifier.agent.verify_sub6()`
- `_resolve_default_feedback_builder()` 在 line 822,把 verifier verdict 转
  feedback prompt(W10 D2 P0-B wire UV/dropped kwargs + W10 D2.5 enum-equality fix)

---

## 运行方式 / 测试命令

### 环境冷启动(新 worktree clone 必跑)

```bash
cd /home/weiwentao/workspace/llm_agent_metabolomics/metagent_v2
./scripts/concord/setup_metagent_v2_env.sh
# Symlinks chebi.sqlite + metanetx.sqlite from sibling investigation worktree
# (gitignored, ~620 MB total, ETL重跑要数十分钟,所以共用)
```

环境变量(MiniMax 远程 API):
```bash
export MINIMAX_API_KEY=<your key>
# 或 METAGENT_OPENAI_API_KEY=<key> 走 OpenAI provider
```

### Stage 1 — 单谱代谢物识别

```bash
# 跑单谱(deterministic pipeline,no LLM)
python scripts/run_full_pipeline.py --fixture glucose_pos --output md

# 跑 sub6a (real-id 鉴定)
python evaluation/sub6/run_sub6a.py --benchmark data/benchmark/sub6/sub6a_*.jsonl

# 跑 sub6b (perfect-id narrative)
python evaluation/sub6/run_sub6b.py --benchmark data/benchmark/sub6/sub6b_*.jsonl

# 跑 sub6b react + feedback(B1 D4 闭环)
python evaluation/sub6/run_sub6b_react_feedback.py --benchmark <path>
```

Stage 1 主输出:`IdentificationReport` JSON / Markdown。

### Stage 2 — 富集分析后的路径鉴定(主战场)

```bash
# 主 driver — Path X 全 63 task LLM-agent rerun(W10 起复用)
PYTHONPATH=. METAGENT_LLM_LOG_PATH=logs/concord/<sprint>_path_x.jsonl \
python scripts/concord/w10_d4_path_x_full.py \
    --benchmark data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl \
    --output data/concord/<sprint>_path_x/path_x_full63_results.jsonl \
    --summary data/concord/<sprint>_path_x/path_x_full63_summary.json \
    --full-dir data/concord/<sprint>_path_x/path_x_full \
    --llm-log logs/concord/<sprint>_path_x.jsonl \
    --max-react-turns 8 \
    --max-feedback-iters 1 \
    --k-concurrent 10

# 注意 --max-feedback-iters 1 是 W14.B 锁的默认;backward compat 留了 = 2 路径
# Wall ~ 1-2 h,API cost ~ $7-12(W14 实测 $6.83 / 64 min)
```

跑完后:
- `path_x_full63_results.jsonl` — 每行一 task 的 signal aggregate
- `path_x_full63_summary.json` — 总 aggregate 数字
- `path_x_full/<task_id>.json` — 每 task 完整 ConcordFeedbackResult trace

### W15 UV attribution audit(pure-audit,no LLM rerun)

```bash
# D1 extract pool
PYTHONPATH=. python scripts/metagent/w15_uv_attribution.py

# D2 classifier(v2 — with DISAMBIGUATION RULE)
PYTHONPATH=. METAGENT_LLM_LOG_PATH=logs/concord/w15_uv_attribution.jsonl \
python scripts/metagent/w15_v2_retry.py
```

### 测试

```bash
# B1 verifier-core(每 sprint Gate A,必过)
PYTHONPATH=. pytest tests/test_verifier/ tests/test_d4_feedback_dispatcher.py \
    tests/test_grammar_validate.py tests/test_classifier_collapse.py \
    tests/test_runner_response_format.py tests/test_prompt_banned_sync.py -q
# 期望 407 pass / 0 fail

# 全 repo(每 sprint Gate B)
PYTHONPATH=. pytest -q --tb=line --ignore=tests/test_ui --ignore=tests/integration
# 期望 1368 pass / 14 fail(W14 baseline + W15 +3 W15 audit cases ~ 1371 / 14)
# 14 fail 全是 pre-existing env(sspa pkg / R docker / GNPS env)

# 单 sprint 单元(例:W14 noise + iter cap)
pytest tests/test_grammar_noise_pattern.py tests/test_concord_react_prompt_banned.py tests/test_react_runner_iter_cap.py -v
```

---

## 大致的结果介绍

### Stage 1 (B1 Phase) 主要数字

数据集 sub6b-v3 mammalian tasks(63 task,3 seed,N=189 task-seed pairs)。
**top-1 method C(hybrid extractor):83.60 ± 7.48 %**(N=3 seed mean ± SE)。
对比 A3 baseline(same-LLM rerun):**66.67 ± 4.75 %**(N=3),净 **+16.93 pp**
hybrid extractor lift。P0 fix marginal on top-1 = **0.00 pp**(W10 P0 isolation
finding,attribution shifts from "P0 fix" to "LLM version drift between
2026-05-15 and 2026-05-18")。

**Per-layer breakdown**(Stage C `step_r_per_layer`):
- 6c(consistency)99.9% supported / Δ -0.07
- 6a(set_enrichment)96.6% supported / Δ +17.97
- 6b(driver_metabolite)72.3% supported / Δ +3.50

**Red line #4**(driver-filtered correlation Δ ≥ +18 pp):durable FAIL at
+3.50 pp on v3 N=3;informative for paper Discussion(tautology between
ground-truth metabolite list 与 driver detection),not a B1-claims blocker。

完整结果在 `reports/agent/phase_b1_d5_v3_p0fix.md` + `reports/agent/phase_b1_step_r_v3.md`。

### Stage 2 主要数字(W8 → W14)

数据集同 sub6b-v3(63 task),但目标从 per-spectrum identification 转 narrative
+ structured claim verification on multi-paradigm enrichment output。

**Cumulative metrics (Path X full 63 task)**:

| sprint | UV % | supported % | pathway acc | iter-2 deg | wall | cost |
|---|---:|---:|---:|---:|---:|---:|
| W10 D4 baseline | 52.95 | 28.62 | 54/63 = 85.7% | 17.46% | 139.7 min | $11.17 |
| W12 D5 (post C7) | 51.45 | 26.61 | 54/63 | 22.22% | 109.8 min | $11.17 |
| W13.A (post extended ID) | 47.79 | 31.91 | 54/63 | 15.87% | 103.7 min | $9.90 |
| **W14 (post noise + iter cap)** | **44.25** | **34.48** | **54/63 = 85.7%** | **0.00%** | **64.2 min** | **$6.83** |
| **cumulative (W10→W14)** | **−8.70 pp** | **+5.86 pp** | **持平** | **−17.46 pp** | **−54 %** | **−39 %** |

亮点:
- **UV 累计降 8.70 pp**(52.95 → 44.25)
- **Supported 累计升 5.86 pp**(28.62 → 34.48)
- **Pathway 命中率全程持平 85.7%**(没有 regression)
- **iter-2 trigger count W13 61/63 → W14 0/63**(W14.B `max_feedback_iters=1` 完全锁定)
- **Path X wall 减半**(139 → 64 min),**cost 降 39%**

### W15 attribution finding(audit-only,no rerun)

W14 残留 44.25% UV(901 claim)的根因拆分(v2 authoritative):

| label | n | % | implication |
|---|---:|---:|---|
| verifier_gap(verifier 缺工具)| 473 | **52.5 %** | 需新 layer / external data;cap 23.2 pp UV |
| producer_fault(LLM 写错)| 251 | **27.9 %** | prompt 修就能消;cap 12.4 pp UV |
| both(两者皆有)| 177 | 19.6 % | mixed lever |

**C7 namespace 验证 hypothesis**:v2 producer rate 50.8%(v1 43.8%);W12 factual_sub6
没 cover 的 C7 残量主要是 ReAct-side 优化空间(wrong-prefix IDs / name-only
references),W16 推荐 C7 producer prompt tighten(4.57 pp cap,3 day,prompt-only)。

### 关于 paper(死命令禁触,但 finding 已经成熟)

死命令禁 paper narrative,但 W8 → W15 产生的数据已经够成熟可写:
- Stage 1:B1 hybrid extractor +16.93 pp lift over A3(83.60 ± 7.48% top-1)
- Stage 2:cumulative −8.70 pp UV / +5.86 pp supported / 持平 pathway 准确率 / cost −39%
- Methodology:7-tool 窄腰 + Verifier 4-shape grammar + LLM-driven ReAct + 强制
  reclassify + 3-way attribution audit(W12-W15 教训累计)

完整 close-out 报告链:
- `reports/agent/concord_w13_close_out.md`
- `reports/agent/concord_w14_close_out.md`
- `data/metagent/w15_uv_attribution/summary.md`

---

## 关键 git refs

| ref | meaning |
|---|---|
| `metagent-v2-base-b1` @ `ed6243b` | B1 Stage 1 frozen tip(immutable per 护栏)|
| `metagent-v2-base-investigation` @ `3ffe621` | ConcordMet investigation frozen tip(immutable)|
| `metagent-v2` HEAD `de6cf5a` | W15 D2 完成 |
| W8 merge commit `8ce5ad9` | Concord + B1 合并 |
| W10 P0-C lock `48a71dd` | zero-LLM extract regression-lock |
| W14 close-out `5116dd9` | latest paper-grade Path X data |
| W15 audit `de6cf5a` | latest attribution data |

---

## 接手提示

1. **先读 `docs/ARCHITECTURE.md`**(Stage 1 设计哲学)+ **`docs/claim_grammar_v2.md`**(Stage 2 4-shape grammar)
2. **跑 setup script**(symlink sqlite,否则 concord 测试 ~12 fail)
3. **看最新 close-out**:`reports/agent/concord_w14_close_out.md` + `data/metagent/w15_uv_attribution/summary.md`
4. **W16 推荐起点**:C7 producer prompt tighten。spec 还没写,需要起草。

如果只看一份文件了解全貌,看这份 CLAUDE.md。如果只跑一次验证回归没坏,跑 Gate A
(`pytest tests/test_verifier/ ...` 407 pass / 0 fail)+ Gate B(全 repo,1368-1371 pass / 14 fail)。

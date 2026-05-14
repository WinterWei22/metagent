# Track PHASE 6.7 — LLM-as-reranker on CASMI 2022 (paper-decisive confirmatory)

**Session ID:** `track_PHASE6_7_casmi_llm_reranker`
**Branch:** `feature/casmi-llm-reranker`(off `feature/sub6-baseline-eval` 即 Phase 6.6 分支)
**Estimated work:** 1 day wall(主要是 LLM 调用 + 报告)
**Predecessors:**
- `reports/eval/casmi_ood_v1.md`(Phase 6.6,weighted reranker 在 CASMI 上 +0 pp,诊断 evidence_score 塌陷)
- `reports/eval/llm_reranker_v2.md` §6.1(Phase 6.3 LLM-as-reranker 实现)
- `ref_paper/MSAgent.pdf` Result §2.2(MSAgent CASMI +10% MRR 来自 LLM chemical reasoner)

---

## Why this matters (paper-decisive)

Phase 6.6 在 CASMI 2022 上跑了 **weighted reranker** 拿 +0pp,但报告 §3.3.1 明确诊断 evidence_score 在 PubChem-formula-restricted pool 上塌陷为 `0.3·CFM_cosine` 单一信号。**这是 weighted reranker 在该候选池上的固有缺陷,不是 conditional gate 的失败。**

MSAgent 在 CASMI 上 +10% MRR 提升来自 **LLM chemical reasoner**(paper §2.2),不是 weighted。LLM 可以引入化学领域知识(SMILES topology / fragmentation mechanisms / functional group reasoning)作为额外辨别力,**绕过 evidence_score 公式塌陷**。

我们 Phase 6.3 在 Sub-6A v2 上跑过 LLM-as-reranker (Config C),但 weighted 已足够 → LLM 仅 +1.38pp。**CASMI 上 weighted 失效,LLM 的边际收益应放大**。这是公平对照 MSAgent 的必做实验。

**Phase 6.7 完成后,paper CASMI 章节有 3 种可能:**

```
乐观 (+10pp):  paper claim "LLM-as-reranker is the right tool when 
              weighted evidence collapses, recovers MSAgent-magnitude gain"
现实 (+3-7pp): paper write "LLM provides modest chemistry-guided rerank 
              signal beyond weighted ensemble"
悲观 (+0pp):   极强 negative — "CASMI 2022 candidate space too narrow 
              (1385 formula-isomers) for any rerank approach"
```

**3 种结果都有 paper finding**。Session 不要预设。

---

## Hard scope boundaries

**You MAY:**
- 修 `evaluation/sub6/run_sub6a.py` / `scripts/eval_sub6/run_casmi.py` 加 `--reranker llm` 路由(Phase 6.3 已实现 llm_reranker.py,本 session 只接 CASMI runner)
- 复用 `evaluation/sub6/llm_reranker.py` (Phase 6.3 实现,13 单测通过)
- 跑 Sub-6A real-id v2 候选池上 CASMI loader 产出的 task JSONL
- 写报告 `reports/eval/casmi_llm_reranker_v1.md`

**You MAY NOT:**
- 修 `evaluation/sub6/llm_reranker.py`(Phase 6.3 实现,锁定)
- 重跑 Phase 6.6 已落盘的 SIRIUS / CFM-ID(全部 cache 读)
- 修 verifier 任何代码
- 跑 Sub-6A v2 / Sub-6B(本 session 只 CASMI 2022)
- 改 conditional gate 阈值(Phase 6.5 锁定 gap≥0.05)

**关键 scope**:本 session **只换 reranker mode**,不动其他 pipeline 配置。所有差异都归因到 LLM vs weighted 一个变量上。

---

## Phase 6.6 已落盘资产(本 session 直接复用)

```
/home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5/
├── data/eval/casmi/
│   ├── 2022_msclip_only/          baseline,170 spec,id_acc=13.53%
│   │   ├── casmi_identifications.jsonl  ← 每条含 gate diagnostic + GT
│   │   └── summary.json
│   ├── 2022_conditional/          weighted reranker,170 spec,id_acc=13.53%
│   │   ├── casmi_identifications.jsonl  ← b/c=8/8 paired diff source
│   │   └── summary.json
│   └── 2022_gate_only/            gate diagnostic(rerank disabled,看 gap 分布)
├── data/benchmark/casmi/2022/     CASMI loader 已产出(Phase 6.6 D1)
│   └── casmi_tasks.jsonl          170 task,跟 Sub-6A v2 schema 兼容
├── data/cache/cfmid/              CFM-ID 缓存(Phase 6.6 跑完已有 CASMI 候选预测)
└── data/cache/sirius/             SIRIUS 缓存(若 Phase 6.6 有落盘)
```

**最关键**:`casmi_identifications.jsonl` 每条含 `predicted_inchikey_first_block` + `gt_inchikey_first_block` + `gate.gate_msclip_top1` + `gate.gate_msclip_gap` + `n_candidates_returned: 20`。

但**缺**:每候选的 SIRIUS top-1 formula、CFM-ID predicted spectrum、modcos score。这些是 LLM-as-reranker 的输入。本 session **D2 需要补跑 peak_evidence**(类似 Phase 6.2 输出),或直接从 CFM/SIRIUS cache 现 lookup。

---

## Background reading

1. `reports/eval/casmi_ood_v1.md` §3.3.1(weighted 塌陷诊断,LLM 路径正是绕开这点)
2. `evaluation/sub6/llm_reranker.py`(Phase 6.3 实现,本 session 直接复用)
3. `evaluation/sub6/prompts.py::build_reranker_messages()`(LLM input JSON schema)
4. `scripts/eval_sub6/run_casmi.py`(Phase 6.6 CASMI runner,加 `--reranker llm` 路由)
5. `data/eval/casmi/2022_conditional/casmi_identifications.jsonl`(看 Phase 6.6 输出格式 + gate 字段)
6. `ref_paper/MSAgent.pdf` Result §2.2(MSAgent rerank 怎么用 SIRIUS knowledge)

In your first response,确认:
- llm_reranker.py 当前签名(从 Phase 6.3 不动)
- run_casmi.py 是否已支持 `--reranker` 参数(从 Phase 6.6 D3 conditional 推断应该有)
- CASMI 候选池每 spec 平均多少 candidate(从 `n_candidates_returned` 字段)
- peak_evidence 是否需要现跑(看 Phase 6.6 是否落盘了 candidate-level SIRIUS / CFM-ID)
- 估算 LLM call wall(170 task × Opus-4-7 ~15s/call ≈ 45 min)

不要写代码或跑命令,直到 confirm。

---

## Deliverables

### D1 — `--reranker llm` 路由到 CASMI runner(1 hour)

`scripts/eval_sub6/run_casmi.py`:
- 加 `--reranker {weighted,llm,none}` CLI(从 Phase 6.6 conditional 模式扩展)
- LLM 模式下,调 `evaluation.sub6.llm_reranker.llm_rerank()`
- LLM 输入 schema 跟 Phase 6.3 一致(候选 + SIRIUS + CFM + experimental peaks)
- LLM 输出 schema 一致(selected_top1_smiles + justification + peak_claims)

不破坏现有 weighted 路径。新增 path 完全 additive。

加 1 个 unit test:mock llm_rerank,断言 `--reranker llm` 调到正确函数。

### D2 — Peak evidence 准备(2 hours)

LLM-as-reranker 需要每候选的:
- modcos score:CASMI 上为 0(no reference spectra),传 `null` 给 LLM
- msclip score:已有(用于 primary retriever)
- SIRIUS top-1 formula:从 Phase 6.6 cache 读
- CFM-ID predicted top peaks:从 Phase 6.6 cache 读
- candidate 是否 GT formula-match(CASMI 全 True,因 formula-restricted)

写脚本 `scripts/eval_sub6/build_casmi_peak_evidence.py`:
- 输入:CASMI candidate list (`n=20` per spec)
- 输出:每 spec 一个 `peak_evidence/<spec_id>.json`,Phase 6.3 schema

如果 Phase 6.6 已落盘 peak_evidence,跳过 D2。

### D3 — 跑 Config CASMI-LLM(1 hour wall + 45min LLM)

```bash
PYTHONPATH=. python scripts/eval_sub6/run_casmi.py \
    --casmi-tasks data/benchmark/casmi/2022/casmi_tasks.jsonl \
    --candidate-pool-mode pubchem_formula_restricted \
    --libraries inhouse \
    --primary-retriever msclip \
    --reranker llm \
    --narrative-llm opus47 \
    --rerank-top-k 5 \
    --rerank-with sirius,cfmid \
    --skip-narrative \
    --output data/eval/casmi/2022_llm_reranker/
```

注意:`--skip-narrative` 仍要打开(我们看 id_acc + peak_claims emission,LLM-as-reranker 的 justification 本身就是 narrative)。但 Phase 6.3 实现里 LLM-as-reranker 不受 `--skip-narrative` 影响,会照常吐 justification。验证一下。

预期产出:
- `2022_llm_reranker/casmi_identifications.jsonl`(170 行)
- `2022_llm_reranker/peak_evidence/*.json`(170 个,含 LLM justification + peak_claims)
- `2022_llm_reranker/summary.json`

### D4 — 三方 paired McNemar 显著性(30 min)

```python
configs = ["msclip_only", "conditional_weighted", "llm_reranker"]
pairs = [(A, B) for A in configs for B in configs if A < B]

for A, B in pairs:
    # 复用 scripts/eval_sub6/casmi_significance.py
    # paired McNemar on correct_top1 字段
    print(f"{A} vs {B}: Δ={...}, b={...}, c={...}, p={...}")
```

主 CSV:`data/paper_figures/phase6_7_casmi_three_way.csv`:

```csv
config,n_spec,n_correct,id_acc,Δ_vs_msclip_baseline,p_vs_msclip,Δ_vs_weighted,p_vs_weighted
msclip_only (D2 Phase 6.6),170,23,13.53%,—,—,—,—
weighted (D3 Phase 6.6),170,23,13.53%,+0.00,1.00,—,—
llm_reranker (Phase 6.7),170,?,?%,?,?,?,?
```

cross-benchmark coherence 更新表 `phase6_7_cross_benchmark.csv`:

```csv
benchmark,reranker,n,id_acc,Δ_vs_baseline,p
sub6a_v2,weighted_conditional,448,66.96%,+10.27,<1e-6
sub6a_v2,llm (Phase 6.3 C),448,64.49%,+7.79,<1e-4
casmi_2022,weighted_conditional,170,13.53%,+0.00,1.00
casmi_2022,llm (Phase 6.7),170,?%,?,?
```

**关键比较**:CASMI 上 LLM 相对 weighted 的 Δ 是否显著正向?这是核心 finding。

### D5 — LLM justification 抽样(30 min,paper case study 用)

挑 5 个 spectrum 的 LLM justification + peak_claims:
- 2 个 LLM 选对(weighted 选错)→ 展示 LLM chemistry reasoning 价值
- 1 个 LLM 选错(weighted 选对)→ 展示 LLM failure mode
- 1 个两个都对(展示 reasoning consistency)
- 1 个两个都错(展示 hard case)

落 `data/paper_figures/phase6_7_llm_case_studies.json`,跟 Phase 6.4 Layer F case 同 schema。

### D6 — 报告 `reports/eval/casmi_llm_reranker_v1.md`(2 hours)

8-10 节,跟 Phase 6.6 报告同模板。重点章节:

#### 1. Summary
LLM 在 CASMI 上 +Xpp,vs weighted +Y pp(同 baseline)。决定性结论。

#### 2. Setup(跟 6.6 一致,只点出 LLM 是唯一变量)

#### 3. Main result
3-way 主表(msclip_only / weighted / llm)。

#### 4. Why LLM works/fails on CASMI(关键诊断)
对照 Phase 6.6 §3.3.1 weighted 塌陷诊断,分析 LLM 在 CASMI 上为何成功/失败。

LLM 用到的 evidence:
- experimental peaks(weighted reranker 没传给 evidence_score,LLM 看了)
- SIRIUS fragmentation tree(weighted 只看 top-1 formula,LLM 看完整 tree)
- CFM predicted peaks(weighted 算 cosine,LLM 看 peak-by-peak match)
- candidate SMILES topology(weighted 完全没用,LLM 推理 functional groups)

#### 5. Statistical significance(D4)
3-way McNemar + Bonferroni(3 pair α=0.0167)。

#### 6. LLM case studies(D5)
5 个 case + 完整 justification + peak_claims。

#### 7. MSAgent 对照
| 维度 | MSAgent CASMI | Phase 6.7 CASMI |
|---|---|---|
| Reranker | LLM chemical reasoner | LLM-as-reranker (Opus-4-7) |
| 输入 | SIRIUS + Tanimoto + chemistry | SIRIUS + CFM + msclip + candidate SMILES |
| Δ | +10% MRR | +X% top-1 |

#### 8. Cross-benchmark coherence(D4 phase6_7_cross_benchmark.csv)
Sub-6A v2 (weighted +10pp / LLM +8pp,weighted 主导) vs CASMI 2022(LLM ?pp / weighted +0pp)。

#### 9. Paper finding 更新
基于 Phase 6.7 数字,把 Phase 6.6 的 "weighted reranker on CASMI fails" 升级为 "weighted vs LLM 在不同 candidate-space-topology 上行为相反"。

#### 10. Provenance + 命令 + MD5

### D7 — Acceptance

```
□ data/eval/casmi/2022_llm_reranker/ 完整 (170 task)
□ casmi_identifications.jsonl 170 行,每条含 LLM justification + peak_claims
□ phase6_7_casmi_three_way.csv 含 msclip_only/weighted/llm 3 行
□ phase6_7_cross_benchmark.csv 4 行(Sub-6A v2 × {weighted,llm} + CASMI × {weighted,llm})
□ phase6_7_llm_case_studies.json 5 case
□ 报告 10 节完整
□ McNemar 3 pair p-value 全报
□ 现有 Phase 6.6 落盘文件未动
□ 0 verifier 改动
□ 0 SIRIUS/CFM-ID 重跑(只 cache lookup,新跑 candidate 须 escalate)
```

---

## Pitfalls

1. **LLM context overflow**:CASMI 候选池 1,385 个 formula-isomer,但 LLM 只看 top-5(从 msclip 排出来)。candidate evidence bundle 单 candidate ~400 tokens × 5 = 2000 tokens。加 SIRIUS / CFM 总 prompt 应 < 4K tokens。**Phase 6.3 实现里 top-K 默认是 5,本 session 保持**。

2. **LLM 输出 JSON parsing 失败**:Phase 6.3 在 Sub-6A v2 上有 66.3% fallback 率(markdown fence 问题)。CASMI 上预期类似。fallback 时 LLM 选 primary top-1 = msclip top-1,等价于 msclip_only baseline。如果 fallback 率 > 50%,**LLM 实际未参与决策**,需 escalate(可能要硬化 parser)。

3. **Candidate pool 跟 Phase 6.6 必须一致**:不能为 LLM 重新选不同 top-5。**top-5 由 msclip primary 排出来**,LLM 只重排这 top-5,不改 candidate pool。

4. **不要跑 verifier**:本 session `--skip-verifier`(如果有这个 flag)或显式跳过 verifier 阶段。我们只看 id_acc + LLM justification 内容,verifier 验证 LLM justification 是 Phase 6.8 的事。

5. **LLM justification 不一定包含 m/z**:Phase 6.3 在 Sub-6A v2 上 LLM 平均写 1.97 peak_claims/spec。CASMI 候选池更难区分,LLM 可能更倾向写 SMILES topology reasoning(无 m/z)而非 peak claims。**两种 reasoning 都接受**,但报告里要区分类型。

6. **不要调阈值**:conditional gate 在 CASMI 上 trigger rate=100%(见 6.6 §3.2),LLM rerank 同 weighted 一样无 gate 可用。直接 always-llm-rerank。

---

## Time budget

- Confirm: 30 min
- D1 CLI 路由: 1 hour
- D2 peak_evidence(若需重做): 2 hours
- D3 跑 170 LLM call: 1 hour wall (~45 min Opus + retry buffer)
- D4 显著性: 30 min
- D5 case study: 30 min
- D6 报告: 2 hours
- D7: 15 min

**Total: ~7-8 hours wall**(1 个工作日内)。

LLM 成本:170 task × Opus-4-7 average 1200 input + 400 output tokens ≈ $3-5(viviai relay)。

---

## First action checklist

第一回合:
1. 读 6 个 background 文件
2. 报告 `evaluation/sub6/llm_reranker.py` 当前签名 + Phase 6.3 实现 13 单测状态
3. 报告 `scripts/eval_sub6/run_casmi.py` 现有 CLI args(确认有 `--reranker` 参数,或需新加)
4. 检查 `data/eval/casmi/2022_conditional/casmi_identifications.jsonl` 每条 record 是否含 candidate-level 字段(若不含,D2 必须重新跑 candidate-level SIRIUS/CFM lookup)
5. 报告 CASMI 候选池每 spec 平均 candidate 数(从 n_candidates_returned 字段)
6. 估算总 wall + LLM 成本
7. 任何 clarifying question

不要写代码或跑命令,直到 confirm。

**重要**:本 session 全程**不重跑 Phase 6.6 已跑过的 retrieval / SIRIUS / CFM-ID**,只换 reranker mode。如果 D2 发现需要重跑 candidate-level peak_evidence(因为 Phase 6.6 没落盘),那是合理新增工作量,但**任何重跑必须 escalate 给 user 确认**(可能 +2-3 hours wall)。

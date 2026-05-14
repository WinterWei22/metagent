# Track PHASE 6.7-A — MRR / top-K reanalysis on Phase 6.7 CASMI data

**Session ID:** `track_PHASE6_7A_mrr_topk`
**Branch:** `feature/casmi-llm-reranker`(同 Phase 6.7,read-only 派生)
**Estimated work:** 30-60 min(纯派生 + 报告,无 LLM,无重跑)
**Predecessors:**
- `reports/eval/casmi_llm_reranker_v1.md`(Phase 6.7 主报告)
- `data/eval/casmi/2022_{msclip_only,conditional,llm_reranker}/casmi_identifications.jsonl`
- `ref_paper/MSAgent.pdf` §2.2(MSAgent 报 MRR 非 top-1)

---

## Why this matters

Phase 6.7 报 **+1.76 pp top-1** vs MSAgent 报 **+10% MRR**——metric 不同,不可直接比。

MSAgent 的 +10% 包含 LLM "把正确答案从 rank 5 推到 rank 2 但仍未 top-1" 这种部分胜利。我们 top-1 只算 rank 1。**如果 LLM 把正确答案从 rank 8 推到 rank 3,top-1 仍错但 MRR 实际从 0.125 → 0.333**。

本 session **不重跑任何 retrieval / rerank**,只从现有 JSONL + 候选 score 派生 top-K accuracy 和 MRR。30 分钟搞定。

**3 种结果**:
- **MRR Δ ≥ +5%**:paper 直接对标 MSAgent +10%,LLM-as-reranker 章节升级
- **MRR Δ = +2-5%**:paper 写 "directionally MSAgent-aligned, smaller magnitude"
- **MRR Δ ≤ +2%**:确认 candidate pool 难度才是主因,跟 MSAgent 数字不可比

---

## Hard scope boundaries

**You MAY:**
- 读 Phase 6.7 / 6.6 落盘的 identifications.jsonl + peak_evidence JSON
- 写脚本 `scripts/eval_sub6/casmi_topk_mrr.py` 派生 top-K accuracy + MRR
- 写报告补丁 `reports/eval/casmi_llm_reranker_v1_appendixA_mrr.md`(单独 appendix,不修主报告)
- 更新主报告 §7 MSAgent 对比表(append MRR 行)

**You MAY NOT:**
- 重跑 retrieval / rerank / LLM(任何 wall > 5 min 的 compute = scope 违规)
- 修主报告 §1-§6 任何数字
- 修 verifier / orchestrator / tools

---

## Background reading

1. `data/eval/casmi/2022_llm_reranker/casmi_identifications.jsonl`(170 行)
2. `data/eval/casmi/2022_conditional/casmi_identifications.jsonl`(170 行 weighted)
3. `data/eval/casmi/2022_msclip_only/casmi_identifications.jsonl`(170 行 baseline)
4. `data/eval/casmi/2022_llm_reranker/peak_evidence/*.json`(LLM 看到的 top-5 + scores)
5. `data/eval/casmi/2022_conditional/peak_evidence/*.json`(weighted 跑完的 top-K + scores)
6. `reports/eval/casmi_llm_reranker_v1.md` §7(MSAgent 对比表,本 session 要加 MRR 行)

In your first response,确认:
- identifications.jsonl 每条 record 有没有 **full ranked candidate list with GT position**(看 schema)
- 如果**只有 top-1**:peak_evidence JSON 是否含全部 top-K 候选 + scores → 从那里反推 rank
- 如果**peak_evidence 也只有 top-5**:msclip_only 的 top-20 候选哪里来(从 retrieval cache?)
- 决定 MRR 计算的 denominator (top-1 only / top-5 / top-10 / top-20)
- 估算派生 wall(应该 < 15 min)

不要写代码,直到 confirm。

---

## Deliverables

### D1 — 派生 top-K accuracy + MRR(15-20 min)

`scripts/eval_sub6/casmi_topk_mrr.py`:

对每个 config(msclip_only / weighted / llm_reranker):
- 对每 spec,找 GT IK14 在 ranked candidate list 里的 position(rank)
- top-K accuracy:rank ≤ K 的比例
- MRR:mean(1/rank if rank exists else 0)

输出 `data/paper_figures/phase6_7_topk_mrr.csv`:

```csv
config,n,top1_acc,top3_acc,top5_acc,top10_acc,top20_acc,mrr,mrr_reachable_142
msclip_only,170,13.53,?,?,?,?,?,?
weighted,170,13.53,?,?,?,?,?,?
llm_reranker,170,15.29,?,?,?,?,?,?
```

**Note**:LLM-as-reranker 只对 top-5 重排,所以 top-5+ accuracy = msclip_only。MRR 应该看 top-5 内 rank 移动。

### D2 — Pairwise paired delta(10 min)

每对 config (msclip vs weighted, msclip vs llm, weighted vs llm) 算:
- top-3 / top-5 Δ
- MRR Δ
- paired sign test 或 Wilcoxon

输出 `data/paper_figures/phase6_7_topk_mrr_significance.csv`。

### D3 — Cross-benchmark MRR(5 min,如果 Sub-6A v2 数据有)

如果 Sub-6A v2 的 Phase 6.5 / 6.3 也有 ranked candidates,加 Sub-6A v2 MRR 行做 4-corner update。

如果没有,跳过(单 benchmark MRR 数据足够回答 MSAgent 对比)。

### D4 — Appendix 报告 `casmi_llm_reranker_v1_appendixA_mrr.md`(15 min)

5 节:
1. **Headline**:LLM MRR Δ vs MS-CLIP-only / vs weighted,Bonferroni
2. **Table**:D1 CSV 内容 + per-config MRR
3. **MSAgent 对比 update**:append MRR 行到主报告 §7 风格表
4. **Decision tree**:Δ 数字对应 paper 写法
   - MRR Δ ≥ +5%:直接对标 MSAgent
   - MRR Δ = +2-5%:directionally aligned
   - MRR Δ ≤ +2%:metric-agnostic null
5. **Provenance + 命令**

### D5 — 更新主报告 §7 MSAgent comparison 表(5 min)

把主报告 `reports/eval/casmi_llm_reranker_v1.md` §7 表加一行 "Top-1 vs MRR rationale already pre-flagged in §9.4":

| dimension | MSAgent | Phase 6.7 top-1 | Phase 6.7 MRR |
|---|---|---|---|
| metric | MRR | top-1 id_acc | MRR |
| Δ | +10% | +1.76 pp | **+X.X%** |

只 append 一列,不动其他行。

### D6 — Acceptance

```
□ phase6_7_topk_mrr.csv 含 top-1/3/5/10/20 + MRR + reachable subset
□ phase6_7_topk_mrr_significance.csv 含 3 pair 配对显著性
□ appendix 报告 5 节
□ 主报告 §7 加 MRR 列(只 append,不动)
□ 0 重跑 / 0 LLM 调用 / 0 verifier 改动
□ git diff 限制在 scripts/eval_sub6/casmi_topk_mrr.py + 2 个新 csv + 1 个 appendix .md + 主报告 §7 的小改
```

---

## Pitfalls

1. **LLM-as-reranker 只对 top-5 重排**:msclip top-6 至 top-20 顺序不变。所以 LLM rerank 的 top-10 accuracy ≥ msclip top-10 accuracy(LLM 不会把 top-5 候选挪到 top-10 之外)。这是预期。

2. **MRR 的 rank 起算**:rank 从 1 开始(top-1 = rank 1)。GT 不在 candidate list 里 → reciprocal = 0(不是 NaN)。

3. **Reachable subset (142/170)**:28 个 GT IK14 不在 PubChem 候选池,这 28 个无论 K 多大,top-K accuracy 都 = 0。报告里同时给 full (170) 和 reachable (142) 两套数字,paper 用 reachable 跟 MSAgent 对齐。

4. **MSAgent 的 MRR 定义**:paper §2.2 没明确写公式。我们用标准定义 `MRR = mean(1/rank)`。如果 MSAgent 用不同(e.g. 1/(rank+1)),差异在 metric 不在 our number,报告 §3 注明。

5. **不要等价化 weighted = conditional**:Phase 6.6 conditional gate 在 CASMI 上 trigger rate=100%,所以 conditional ≡ weighted always-rerank。直接读 `2022_conditional/` 即可。

---

## Time budget

- Confirm: 10 min
- D1 派生: 15 min
- D2 显著性: 10 min
- D3 cross-benchmark: 5 min(若有数据)
- D4 appendix: 15 min
- D5 主报告补丁: 5 min
- D6: 5 min

**Total: ~60 min wall**(纯只读派生)。

---

## First action checklist

第一回合:
1. 读 6 个 background 文件
2. 报告 `2022_llm_reranker/casmi_identifications.jsonl` 第 1 条 record 的字段(确认有没有 ranked candidate list)
3. 如果只有 top-1,报告 `peak_evidence/casmi2022_XX.json` 的 candidates 字段结构
4. 报告 msclip_only 是否能拿到 top-20 ranked candidates(可能要从 retrieval cache 读)
5. 估算 D1 wall(< 20 min)
6. 任何 clarifying question

不要写代码,直到 confirm。

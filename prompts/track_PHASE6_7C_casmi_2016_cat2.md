# Track PHASE 6.7-C — CASMI 2016 cat2 OOD validation (n=378 expansion)

**Session ID:** `track_PHASE6_7C_casmi_2016_cat2`
**Branch:** `feature/casmi-2016-cat2`(off `feature/casmi-llm-reranker`)
**Estimated work:** 1-1.5 days wall(主要是 LLM call + report)
**Predecessors:**
- `reports/eval/casmi_llm_reranker_v1.md`(Phase 6.7,CASMI 2022 +1.76 pp top-1)
- `reports/eval/casmi_llm_reranker_v1_appendixA_mrr.md`(Phase 6.7-A,+11% MRR matching MSAgent)

---

## Why this matters

Phase 6.7-A 已经在 CASMI 2022 上验证 +11% MRR 跟 MSAgent +10% MRR 同档,但 **n=170 + Wilcoxon p=0.087 卡在 Bonferroni 边缘**。

Phase 6.7-C 用 **CASMI 2016 cat2 (208 spec)** 把样本扩到 **n=378**,Wilcoxon 应过 Bonferroni α=0.0167。

成本极低:
- Loader 复用 Phase 6.6 loader 结构(只换 parsing)
- LLM-as-reranker 完全复用(schema、parser、CLI 全在)
- SIRIUS / CFM-ID cache 跟 CASMI 2022 接近不重叠,需新跑(后台跑)

---

## Hard scope boundaries

**You MAY:**
- 扩展 `evaluation/sub6/casmi_loader.py` 加 CASMI 2016 cat2 parser
- 跑 `run_casmi.py --casmi 2016_cat2 --reranker {none,weighted,llm}`
- 复用 Phase 6.7 / 6.7-A 所有 LLM rerank 基础设施(LlmRerankResult schema + ranked_indices + dump-ranks)
- 跑 SIRIUS / CFM-ID 在 CASMI 2016 候选上(预期新跑)
- 跑 paired Wilcoxon on n=378 combined sample (CASMI 2016 + 2022)
- 写报告 `reports/eval/casmi_2016_cat2_v1.md` + appendix update

**You MAY NOT:**
- 修 LLM-as-reranker 算法或 prompt(锁定)
- 修 verifier 任何代码
- 重跑 Phase 6.6 / 6.7 / 6.7-A CASMI 2022 数据
- 跑 CASMI 2016 cat1(NPID,只 19 task,不值得)

---

## 现有数据状态

```
/data/weiwentao/llm_agent_metabolomics/CASMI/casmi_2016/
├── category2/
│   ├── challenges/                    MS2 peak lists (mgf + txt, pos+neg)
│   │   ├── Challenge*.mgf             ← 主输入(208 challenge)
│   │   └── Challenge.csv              ← challenge metadata
│   ├── candidates/                    Per-challenge candidate lists (.zip)
│   │   └── Challenge_Candidates.zip   ← 候选池(每 challenge 1 个 zip)
│   └── training/                      Training set,不用
├── category3/                         symlink to cat2,数据共享(不重复跑)
└── solutions/
    └── solutions_casmi2016_cat2and3.csv   ← 208 行 GT (cat2+3 共享)
```

GT CSV schema(预期):

```
challenge_id, formula, smiles, inchikey, ionization, ...
```

候选 zip 解压后:每 challenge 一份 candidate list,通常含 SMILES + 一些元数据。

---

## Background reading

1. `reports/eval/casmi_llm_reranker_v1.md`(整体框架)
2. `reports/eval/casmi_llm_reranker_v1_appendixA_mrr.md`(MRR 评估方法)
3. `evaluation/sub6/casmi_loader.py`(CASMI 2022 loader,本 session 扩展它)
4. `scripts/eval_sub6/run_casmi.py`(runner,加 `--casmi 2016_cat2` 路由)
5. `scripts/eval_sub6/casmi_topk_mrr.py`(MRR 计算,完全复用)
6. `data/eval/casmi/2022_llm_reranker_v2/casmi_identifications.jsonl`(参考 schema)
7. `/data/weiwentao/llm_agent_metabolomics/CASMI/casmi_2016/README.md`(数据结构)

In your first response,确认:
- CASMI 2016 cat2 challenge 数量(预期 208)
- MGF 格式 + GT CSV 的 column 名 + ion mode 分布(pos vs neg)
- 候选 zip 解压后 schema(SMILES list?with InChIKey?)
- 估算 LLM call wall(预期 208 × ~15s ≈ 50 min)
- 估算 SIRIUS / CFM-ID 总 wall(预期 ~2-3 hours,跟 CASMI 2022 类似)
- 任何 clarifying question

不要写代码或跑命令,直到 confirm。

---

## Deliverables

### D1 — CASMI 2016 cat2 loader(0.5 day)

`evaluation/sub6/casmi_loader.py` 扩展 `load_casmi_2016_cat2()`:

- Parse `solutions_casmi2016_cat2and3.csv` for GT
- Parse `category2/challenges/*.mgf` 用 `matchms.importing.load_from_mgf`
- 解压 `category2/candidates/Challenge_Candidates.zip` 拿候选 SMILES
- 产出 `data/benchmark/casmi/2016_cat2/casmi_tasks.jsonl` (~208 task)
- schema 跟 CASMI 2022 一致(`run_sub6a` 直接消费)

加 unit test:loader 产出至少 200 task,每 task 有 GT InChIKey + 候选池。

### D2 — 3-config run on CASMI 2016 cat2(后台跑,~3-4 hours wall)

```bash
# Config A: msclip only baseline
PYTHONPATH=. python scripts/eval_sub6/run_casmi.py \
    --casmi 2016_cat2 \
    --reranker none \
    --primary-retriever msclip \
    --libraries gnps,inhouse \
    --rerank-top-k 5 \
    --dump-ranks \
    --out-dir data/eval/casmi/2016_cat2_msclip_only/

# Config B: weighted (full Phase 6.6 evidence_score)
... --reranker conditional --rerank-with sirius,cfmid ...
out-dir: data/eval/casmi/2016_cat2_conditional/

# Config C: LLM-as-reranker (paper main)
... --reranker llm --rerank-with cfmid --narrative-llm opus47 ...
out-dir: data/eval/casmi/2016_cat2_llm_reranker/
```

**重要**:Config B 需要 `SIRIUS auto-relogin`(`METAGENT_SIRIUS_USER` / `METAGENT_SIRIUS_PASS` 必须 export)。

LLM 成本:208 × Opus-4-7 ≈ **$4-6**。

### D3 — Combined n=378 MRR analysis(15 min)

```python
# 合并 CASMI 2022 (n=170) + CASMI 2016 cat2 (n=208) = n=378 paired
# 跑 Wilcoxon on combined reciprocal rank
```

复用 `scripts/eval_sub6/casmi_topk_mrr.py`,加 `--combined-2022-2016` flag。

输出 `data/paper_figures/phase6_7c_combined_n378.csv`:

```csv
config,benchmark,n,top1_acc,top5_acc,mrr,mrr_relative_delta_vs_msclip
msclip_only,casmi_2022,170,13.53%,28.24%,0.2045,—
msclip_only,casmi_2016_cat2,208,?,?,?,—
msclip_only,combined,378,?,?,?,—
weighted,combined,378,?,?,?,?
llm_reranker,combined,378,?,?,?,?
```

加 Wilcoxon 显著性 csv:

```csv
test,n_paired,n_better_B,n_better_A,n_tied,mean_delta_rr,p_value,sig_after_bonferroni
msclip→llm combined,378,?,?,?,?,?,?  ← 关键 row,期望 p<0.0167
```

### D4 — 报告 `reports/eval/casmi_2016_cat2_v1.md`(0.5 day)

8 节,跟 Phase 6.7 报告同模板:

1. **Headline**:CASMI 2016 cat2 上 LLM Δ vs MS-CLIP-only(top-1 + MRR)
2. **Setup**(指出跟 Phase 6.7 唯一变量是 benchmark)
3. **Per-benchmark main result**(CASMI 2016 vs 2022 数字对比)
4. **Combined n=378 显著性**(核心 paper finding)
5. **Cross-benchmark coherence**(2016 vs 2022 数字应一致 ±2pp)
6. **Discordance pattern**(LLM b/c 分布是否跨 benchmark 一致)
7. **Limitations**(单 LLM、单 reranker 形式等)
8. **Provenance + reproducer**

#### Appendix B(并行)更新 `casmi_llm_reranker_v1_appendixA_mrr.md` § A.6:

加一段 "Phase 6.7-C extension":n=378 上 Wilcoxon p 数字 + Bonferroni 结论。

### D5 — Acceptance

```
□ data/benchmark/casmi/2016_cat2/casmi_tasks.jsonl ~208 task
□ data/eval/casmi/2016_cat2_{msclip_only,conditional,llm_reranker}/ 三套完整
□ phase6_7c_combined_n378.csv 含 3 config × 3 benchmark (2022/2016/combined)
□ Combined n=378 上 Wilcoxon p < 0.05(目标过 Bonferroni 0.0167)
□ 报告 8 节
□ 现有 CASMI 2022 数据未动
□ LlmRerankResult schema 不修(Phase 6.7-A 锁定)
```

---

## Pitfalls

1. **CASMI 2016 cat2 候选池可能不一样**:cat 2 用 "best automatic in silico identification" 协议,候选池来自比赛规则。如果跟 CASMI 2022 PubChem-formula-restricted 不同,paper §3 必须分 benchmark 报数字。

2. **MGF 解析 edge cases**:CASMI 2016 MGF 可能有 multi-spectrum-per-challenge。Loader 取每 challenge 第 1 个 spectrum(或最高质量那个)。在 audit report 写明。

3. **SIRIUS 4.9 hours 风险**:Phase 6.6 CASMI 2022 D3 weighted run 4.9 hours,有 SIRIUS auto-relogin 问题。本 session **强制 export env vars 后跑**,不然 weighted 数字废一半。

4. **Combined 显著性不一定过 Bonferroni**:n=378 上若 discordance scale-linear,p 应该 < 0.05。但 CASMI 2016 vs 2022 数据特性可能不同(e.g. cat2 有更多 challenging stereoisomer)。报告里写两个数:per-benchmark + combined,**两个都低于 0.05 才是强 finding**。

5. **不要跑 cat1 / cat3**:cat1 太小(19 spec),cat3 跟 cat2 数据共享(冗余)。只跑 cat2。

---

## Time budget

- Confirm: 30 min
- D1 loader: 0.5 day
- D2 跑 3 config: 4-6 hours wall(后台,SIRIUS + CFM 主导)
- D3 combined analysis: 15 min
- D4 报告: 0.5 day
- D5: 10 min

**Total: ~1.5 days wall**(可后台跑 D2)。LLM cost ~$5。

---

## First action checklist

第一回合:
1. 读 7 个 background 文件
2. 确认 CASMI 2016 cat2 challenge 数量 + GT CSV 列名
3. 报告候选 zip 解压后 1 个 sample challenge 的结构
4. ion mode 分布(pos vs neg)
5. 估算 wall(D1 / D2 / D4 分开)
6. 检查 SIRIUS env vars 是否 export(`echo $METAGENT_SIRIUS_USER`)
7. 任何 clarifying question

不要写代码或跑命令,直到 confirm。

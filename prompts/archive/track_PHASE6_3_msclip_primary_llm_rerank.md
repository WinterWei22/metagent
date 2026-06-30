# Track PHASE 6.3 — MS-CLIP primary retrieval + LLM-as-reranker on Sub-6A real-id v2

**Session ID:** `track_PHASE6_3_msclip_primary_llm_rerank`
**Branch:** `feature/sub6-llm-reranker`(新建 from `feature/sub6-v2-integrated`)
**Estimated work:** 1-2 days wall
**Predecessors:**
- `reports/eval/msclip_ablation_v2.md`(Phase 6.1,MS-CLIP fusion 失败,但作为 primary 未测)
- `reports/eval/sirius_cfmid_rerank_v2.md`(Phase 6.2,产出 358 peak_evidence,加权 rerank 不动 id_acc)
- `reports/eval/sub6_v2_comparison_2026-05-06.md`(Layer F 当前 = 0)

---

## Why this matters (paper 战略)

当前 Sub-6A real-id v2 的 GNPS modcos baseline 67.32% 存疑:**测试谱图来自 RIKEN 而 RIKEN 谱图很多被 GNPS 重新收录**(InChIKey 一致但 source_id 不同,NM-002 leakage filter 抓不到全部)。这是 in-distribution 检索,数字虚高。

真实部署场景:
- 用户拿到一张**没在任何库见过**的实验谱图
- 期望:基于 SMILES/化学结构的检索(MS-CLIP)给出候选,SIRIUS+CFM-ID 提供独立证据,系统整合判断

**Phase 6.3 提两个独立设计变量**:

1. **MS-CLIP as primary retriever**(不是 re-ranker):候选池从 GNPS modcos 切换到 MS-CLIP,降低 GNPS leakage 影响
2. **LLM-as-reranker**(不是 weighted score):把所有 evidence 喂 LLM,让 LLM 自己 reason + 选 top-1 + 写 justification

LLM-as-reranker 的副产品:**LLM justification 里天然含 peak-level claim**,直接激活 verifier Layer F(目前 = 0)。一举两得。

---

## Hard scope boundaries

**You MAY:**
- 修 `evaluation/sub6/identification.py` 加 `--primary-retriever {modcos|msclip}` 参数
- 修 `evaluation/sub6/rerank.py` 加 `llm` 模式(complement 现有 `weighted` 模式)
- 写新 prompt template `evaluation/sub6/prompts.py::build_reranker_messages()`
- 复用 Phase 6.2 已实现的 SIRIUS / CFM-ID wrapper + cache
- 跑 Sub-6A real-id v2 with 3 个 ablation config(详见 D4)
- 跑 verifier on 新 narratives(包括 Layer F)
- 写报告 `reports/eval/llm_reranker_v2.md`

**You MAY NOT:**
- 修 `tools/sirius/`、`tools/spectrum_predict/`、`tools/library_search/scoring.py` 算法
- 修 verifier 任何 layer 代码
- 重跑 SIRIUS 或 CFM-ID(完全复用 Phase 6.2 落盘的 peak_evidence)
- 跑 Sub-6B 或 Sub-6A perfect(本 session 只 Sub-6A real)
- 改其他 prompt 或 retrieval 配置

**关键 scope**:本 session 不重跑昂贵的 SIRIUS/CFM-ID。只切换 retriever 主排序逻辑 + 加 LLM-as-reranker。

---

## Background reading

1. `evaluation/sub6/identification.py`(看 identify_spectrum 怎么调 library_search)
2. `evaluation/sub6/rerank.py`(Phase 6.2 加的,看现有 weighted reranker)
3. `tools/library_search/tool.py`(看 modcos vs msclip 调度逻辑)
4. `tools/library_search/scoring.py`(看 fuse_scores 当前实现)
5. `data/eval/sub6/v2_phase6_2/full/peak_evidence/<sample>.json`(贴 1 个 sample 看 schema)
6. `verifier/layers/peak_mechanistic.py`(看 Layer F 期望的 claim 格式)
7. `evaluation/sub6/prompts.py`(看现有 prompt template 结构)

In your first response,确认:
- 现有 library_search 怎么切 primary retriever(改 fuse_scores? 改 candidate selection?)
- LLM 一次 call 能 fit 多少 candidate(top-5 × evidence bundle 估算 token)
- peak_evidence JSON 实际 schema(贴 sample)
- Layer F claim 触发关键词(看 claim_classifier)
- 估算 3 个 config 的总 wall

不要写代码或跑命令,直到 confirm。

---

## Key design decisions

### D1: MS-CLIP primary retriever 实现

最小改动:`tools/library_search/scoring.py` 已有 modcos + msclip 两个 score。primary retriever 切换的本质是**改变 ranking 用哪个 score**:

```python
# Config A (current baseline): rank by modcos, msclip optional
# Config B (NEW MS-CLIP primary): rank by msclip_rescaled, modcos optional
# 输出 top-K 用于下游 reranker
```

不动 candidate pool(仍是 Phase A mass window 选出来的 GNPS+PubChem-Lite 候选),只切排序 metric。

如果实现不允许这种切换,加一个 `primary_score` 字段,reranker 先按它排再 take top-K。

### D2: LLM-as-reranker 输入 schema(关键)

每个 spectrum 的 LLM input(top-5 候选,JSON 化):

```json
{
  "experimental_spectrum": {
    "spectrum_id": "...",
    "precursor_mz": 195.0877,
    "ion_mode": "positive",
    "adduct": "[M+H]+",
    "top_peaks": [[m/z, intensity], ...]
  },
  "candidates": [
    {
      "rank_after_primary": 1,
      "smiles": "...",
      "name": "caffeine",
      "molecular_formula": "C8H10N4O2",
      "primary_retriever_score": 0.71,
      "primary_retriever": "msclip",
      "modcos_score": 0.82,
      "modcos_top_in_pool": false,
      "sirius_top1_formula": "C8H10N4O2",
      "sirius_formula_match": true,
      "cfmid_predicted_peaks": [[138.07, 0.71, "C7H8N4O2", "[-CH3]"]],
      "cfmid_cosine_vs_experimental": 0.82,
      "experimental_peaks_explained_count": 8,
      "experimental_peaks_total": 12
    }
  ]
}
```

LLM expected output(JSON):

```json
{
  "selected_top1_index": 0,
  "selected_top1_smiles": "...",
  "confidence": "high",
  "justification": "Candidate 0 (caffeine) has the strongest multi-tool consensus. SIRIUS top-1 formula C8H10N4O2 matches the candidate exactly. CFM-ID predicts 8/12 experimental peaks within 5ppm, including m/z 138.07 corresponding to [-CH3] loss with predicted intensity 0.71 vs experimental 0.68.",
  "peak_claims": [
    "m/z 138.07 corresponds to loss of methyl group (-CH3) from caffeine",
    "m/z 110.08 corresponds to subsequent loss of -CO from m/z 138.07"
  ]
}
```

`justification` 字段 + `peak_claims` 字段都进 narrative,verifier 从中抽 claim。

### D3: 3 个 ablation configs(精简,可控)

| Config | Primary retriever | Reranker | 已有数据? |
|---|---|---|---|
| **A baseline** | GNPS modcos | weighted (Phase 6.2 Config D) | ✅ 已有(67.10%) |
| **B msclip + weighted** | MS-CLIP | weighted (复用 6.2 evidence_score) | ❌ 新跑 |
| **C msclip + LLM** | MS-CLIP | **LLM-as-reranker** | ❌ 新跑 |

**Config A 不重跑**,直接引用 Phase 6.2 数据。本 session 只跑 B 和 C。

为啥不加 D (modcos+LLM)?paper 关键 finding 是 "MS-CLIP primary + LLM rerank vs modcos baseline"。多一个 config 增加 4-6 hours wall 没必要,留 follow-up。

### D4: peak_evidence 复用 Phase 6.2

不重跑 SIRIUS/CFM-ID。Config B/C 都从 `data/eval/sub6/v2_phase6_2/full/peak_evidence/` 读。

如果 candidate pool 跟 Phase 6.2 不同(MS-CLIP 选出来的 top-5 跟 modcos 选出来的 top-5 可能不重叠),需补跑 SIRIUS/CFM-ID 的 candidate **必须先 cache check**:
- (smiles, adduct, ion_mode) 在 cache 里 → 直接读
- 不在 → 单独跑 CFM-ID(SIRIUS 是 per-spectrum,跟 candidate 无关,Phase 6.2 已 cover 全 459 spectra)

CFM-ID 缓存 hit rate 预期 >70%(同分子在不同 spectrum 出现概率高)。

### D5: LLM 配置

- `--narrative-llm opus47`(默认,用 viviai relay)
- temperature = 0
- max output ≤ 2000 tokens
- 每 spectrum 一次 LLM call(459 calls × ~10s ≈ 80 min wall)

---

## Deliverables

### D1 — Primary retriever 切换(2 hours)

`evaluation/sub6/identification.py` 加 `--primary-retriever {modcos|msclip}` CLI:
- default `modcos`(现有行为不变)
- `msclip` → 候选池仍是 Phase A,但按 msclip_rescaled 降序取 top-K

加 unit test:mock library_search,断言 candidate 顺序按选定 metric 排。

### D2 — LLM-as-reranker(4 hours)

新文件 `evaluation/sub6/llm_reranker.py`:

```python
def llm_rerank(
    spectrum: dict,
    candidates_with_evidence: list[dict],
    *,
    llm_chat_fn,
    model: str,
    max_candidates: int = 5,
) -> dict:
    ...
```

新 prompt template `build_reranker_messages()` 在 `evaluation/sub6/prompts.py`。

加 unit test:mock LLM 返回 JSON,断言 parsing OK。

### D3 — 集成到 run_sub6a(1 hour)

加 `--reranker {weighted|llm|none}` CLI:
- `weighted` = 现有(Phase 6.2)
- `llm` = NEW
- `none` = baseline

不破坏现有 `--rerank-with sirius,cfmid` 等路径。

### D4 — Smoke test(30 分钟)

跑 1 task with `--primary-retriever msclip --reranker llm`,确认:
- LLM 收到 candidate JSON 没爆 context
- LLM 输出合法 JSON,peak_claims 字段非空
- narrative 里包含 LLM 的 justification + peak_claims

不通过 escalate。

### D5 — 跑 Config B (msclip primary + weighted)(2 hours wall)

```bash
PYTHONPATH=. python scripts/eval_sub6/run_baseline.py \
    --sub6a data/benchmark/sub6/sub6a_e2e_tasks_v2.jsonl \
    --out-dir data/eval/sub6/v2_phase6_3/B_msclip_weighted/ \
    --libraries gnps,inhouse \
    --primary-retriever msclip \
    --reranker weighted \
    --skip-narrative \
    --mass-tolerance-ppm 10.0
```

复用 Phase 6.2 peak_evidence cache。预期 wall 1-2 hours。

### D6 — 跑 Config C (msclip primary + LLM rerank)(3 hours wall)

```bash
PYTHONPATH=. python scripts/eval_sub6/run_baseline.py \
    --sub6a data/benchmark/sub6/sub6a_e2e_tasks_v2.jsonl \
    --out-dir data/eval/sub6/v2_phase6_3/C_msclip_llm/ \
    --libraries gnps,inhouse \
    --primary-retriever msclip \
    --reranker llm \
    --narrative-llm opus47 \
    --mass-tolerance-ppm 10.0
```

**注意没有 `--skip-narrative`**!Config C 的 LLM-as-reranker 本身就是 narrative 生成步骤。

预期 wall:1-2h MS-CLIP + 80 min LLM ≈ 2-3 hours。

### D7 — 跑 verifier on Config C narratives(40 min wall)

```bash
PYTHONPATH=. python scripts/eval_sub6/grade_with_verifier.py \
    --narratives data/eval/sub6/v2_phase6_3/C_msclip_llm/sub6a_narratives.jsonl \
    --output data/eval/sub6/v2_phase6_3/C_msclip_llm/verdicts_v9_phaseC.jsonl
```

verifier 用 Opus-4-7 内部 LLM。

**关键 acceptance**:`peak_mechanistic` claim 数 > 0(Layer F 终于激活)。

### D8 — Aggregator + 报告(1 hour)

新写 `scripts/eval_sub6/aggregate_phase6_3.py`,产出主表:

```csv
config,primary_retriever,reranker,n_tasks,id_acc,task_mean,wall_min,peak_mech_total,peak_mech_sup,peak_mech_contra
A_modcos_weighted,modcos,weighted,38,67.10,67.84,132.7,0,0,0
B_msclip_weighted,msclip,weighted,38,?,?,?,0,0,0
C_msclip_llm,msclip,llm,38,?,?,?,?,?,?
```

报告 `reports/eval/llm_reranker_v2.md`,9-10 节,跟 Phase 6.2 同模板,加:
- LLM justification quality 抽样(5 个 case + verifier verdict)
- LLM-vs-weighted disagreement 分析(LLM 选了不同 candidate 时,谁更准)
- "MS-CLIP primary 是否减轻 GNPS leakage" 的 evidence(per-bucket id_acc 比对)
- Layer F **激活前后**对比(0 → ?)

### D9 — Acceptance

```
□ Config B 跑完,id_acc 报数(任意值,负结果也接受)
□ Config C 跑完,id_acc 报数 + LLM justification 落盘
□ Config C verifier 跑完,peak_mechanistic verdict > 0(关键!)
□ 报告 §LLM justification quality 含 5 个 case
□ Aggregator CSV
□ 现有 v2 / v2_phase6_2 文件未动
□ git diff 限制在 evaluation/sub6/{identification,rerank,llm_reranker,prompts,run_sub6a}.py
  + scripts/eval_sub6/{run_baseline,aggregate_phase6_3}.py + 1-2 unit test
□ 0 verifier 代码改动
□ 0 SIRIUS / CFM-ID 重跑(只 cache lookup + 少量 miss 补跑)
```

---

## Pitfalls

1. **LLM context overflow**:5 个 candidate × evidence bundle 可能 5K+ tokens。如果 smoke test 看到 truncation,降到 top-3 或裁剪 cfmid_predicted_peaks 到 top-10。

2. **MS-CLIP primary 可能比 modcos 差**:这是 paper 真正想测的。如果 Config B 比 Config A 低,**接受 + 写报告**。这本身证明 GNPS leakage 假设。

3. **LLM 输出 JSON parsing 失败**:Opus-4-7 输出 JSON 偶尔有问题。加 retry + fallback(parsing 失败时 LLM 选 top-1 = primary top-1)。

4. **Layer F 触发依赖 claim 抽取**:LLM 输出 `peak_claims` 字段后,verifier extractor 需要从这个字段抽 claim。如果 verdict 仍 0,debug claim_extractor。

5. **CFM-ID cache miss**:MS-CLIP 选出来的 top-5 跟 modcos 选的不同,cache miss 部分要补跑。如果 cache miss > 30%,wall time 显著增加。

6. **LLM justification 质量风险**:LLM 可能产生 hallucinated reasoning。这正是 verifier Layer F 的检测目标——paper 里展示 verifier 抓 LLM 的 reasoning 错误,是核心卖点。

---

## Time budget

- Confirm: 30 min
- D1 primary retriever: 2 hours
- D2 LLM reranker: 4 hours
- D3 集成: 1 hour
- D4 smoke: 30 min
- D5 Config B: 1-2 hours wall
- D6 Config C: 2-3 hours wall
- D7 verifier: 40 min
- D8 aggregator + 报告: 1 hour
- D9: 10 min

**Total: ~1.5 day**

---

## First action checklist

第一回合:
1. 读 7 个 background 文件
2. 贴 1 个 peak_evidence JSON sample(从 Phase 6.2 落盘的)
3. 报告 library_search 当前 fuse_scores 是 max 还是 weighted
4. 估算 LLM input token(5 candidates × evidence bundle)
5. 确认 Phase 6.2 peak_evidence 覆盖了 459 spectra 的全 candidate(还是只 modcos top-5?)→ 决定 cache miss 率
6. 报告 Layer F claim 触发的关键词模式(看 claim_classifier.py)
7. 任何 clarifying question

不要写代码或跑命令,直到 confirm。

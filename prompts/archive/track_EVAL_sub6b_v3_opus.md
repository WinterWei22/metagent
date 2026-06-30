# Track EVAL — Sub-6B v3 × Opus narrative + verifier rerun

**Session ID:** `track_EVAL_sub6b_v3_opus`
**Branch:** `feature/lipidmaps`(继续 LIPID MAPS session 的分支,不新建)
**Estimated work:** 2-3 hours wall(主要 LLM + verifier 计算时间)
**Predecessors:**
- `reports/benchmark/sub6_construction_report_v3_raw.md`(v3 数据 build)
- `reports/benchmark/lipidmaps_integration_audit.md`(LIPID MAPS 集成 audit)
- `data/eval/sub6/v2/sub6b_opus/`(v2 baseline,直接对比目标)

---

## Why this matters

LIPID MAPS 集成把 lipid bucket 从 1 task → 11 task(其中 10 个是 eicosanoid pathway)。但**数据扩展只是手段**——关键问题是:

1. **LLM narrative 是否真在 eicosanoid task 上写出 LIPID MAPS pathway 名?** 还是仍写"steroid hormone biosynthesis"这种通用 lipid 概念?
2. **Verifier substring matching 能否识别 LIPID MAPS pathway?** 还是仍 unverifiable_v0?
3. **Layer 6c (biological_claim) unverifiable 率是否变化?**

只有跑通 v3 narrative + verifier,这 3 个问题才有答案。这是判断 LIPID MAPS 集成"实际有用"还是"仅数据 cosmetic"的关键。

**严格对照实验**:用跟 v2 sub6b_opus 完全相同的 narrative LLM (Opus-4-7) 和 verifier (v9-PhaseC),仅换数据 (v2→v3),对比 verdict 分布。

---

## Hard scope boundaries

**You MAY:**
- 跑 `evaluation/sub6/run_sub6b.py` 在 v3 数据上(用现有 `--narrative-llm opus47`)
- 跑现有 verifier `grade_with_verifier.py` 在 v3 narrative 上
- 写 audit `reports/eval/sub6b_v3_opus_vs_v2_comparison.md`
- 创建 `data/eval/sub6/v3/sub6b_opus/` 目录及输出

**You MAY NOT:**
- 修任何代码(narrative runner / verifier / aggregator)
- 重跑 Sub-6A v2 / Sub-6B v2 现有结果(它们是对照,不能动)
- 跑 GPT-5.5 或 MiniMax(本 session 仅 Opus,跟 v2 sub6b_opus 一对一对比)
- 修改 v3 数据 jsonl
- 跑 Sub-6A v3(还没构建,本 session 不涉及)

---

## Background reading (mandatory)

1. `data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl`(63 task,确认存在 + 行数)
2. `data/eval/sub6/v2/sub6b_opus/sub6b_narratives.jsonl`(v2 baseline 63 narrative)
3. `data/eval/sub6/v2/sub6b_opus/verdicts_v9_phaseC.jsonl`(v2 baseline verdict)
4. `results/v2/sub6b_opus/sub6b_v2_opus_verdicts_summary.json`(v2 aggregate metrics)
5. `reports/benchmark/lipidmaps_integration_audit.md`(知道 v3 跟 v2 差在哪)
6. `evaluation/sub6/run_sub6b.py`(确认 `--narrative-llm` CLI 已支持 opus47)
7. `scripts/eval_sub6/run_baseline.py`(确认现有 batch runner 接口)
8. `scripts/eval_sub6/grade_with_verifier.py`(verifier batch driver)

In your first response,确认:
- v3 jsonl 行数确实是 63
- v2 sub6b_opus narrative 文件 MD5(用作对比 provenance)
- v9-PhaseC verifier 是 working tree 当前版本(无未 commit 改动)
- 11 个 lipid task 的 task_id list(从 v3 jsonl 抽,后续要 spot check)
- 提议的输出路径 `data/eval/sub6/v3/sub6b_opus/`

不要跑命令直到 confirm。

---

## Deliverables

### D1 — Narrative generation(~30-40 min wall)

```bash
PYTHONPATH=. python scripts/eval_sub6/run_baseline.py \
    --sub6b data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl \
    --narrative-llm opus47 \
    --output data/eval/sub6/v3/sub6b_opus/ \
    > logs/v3/sub6b_opus_narrative.log 2>&1
```

**Acceptance:**
- 63/63 narrative 跑完,失败率 < 5%
- llm_model 字段 = `claude-opus-4-7`(确认路由对)
- 总 wall time 跟 v2 sub6b_opus(19.7 min)在同量级

### D2 — Verifier(~50-70 min wall)

```bash
PYTHONPATH=. python scripts/eval_sub6/grade_with_verifier.py \
    --narratives data/eval/sub6/v3/sub6b_opus/sub6b_narratives.jsonl \
    --output data/eval/sub6/v3/sub6b_opus/verdicts_v9_phaseC.jsonl \
    > logs/v3/sub6b_opus_verifier.log 2>&1
```

**注意**:verifier 内部 LLM 用 working tree default(应该是 Opus-4-7,跟 v2 一致)。如果不是,**stop 并 escalate**——不能用别的 LLM,会让对比不公平。

**Acceptance:**
- 63 verdict 全跑完(允许 ≤2 个 error verdict)
- 总 LLM 调用数跟 v2 同量级(±20%)

### D3 — Aggregator + summary(~5 min)

```bash
# 用现有 aggregator 出 summary.json
mkdir -p results/v3/sub6b_opus/
PYTHONPATH=. python scripts/eval_sub6/aggregate_verifier.py \
    --verdicts data/eval/sub6/v3/sub6b_opus/verdicts_v9_phaseC.jsonl \
    --output-dir results/v3/sub6b_opus/ \
    --track sub6b_v3_opus
```

输出:
- `results/v3/sub6b_opus/sub6b_v3_opus_verdicts.csv`
- `results/v3/sub6b_opus/sub6b_v3_opus_verdicts_summary.json`
- `results/v3/sub6b_opus/sub6b_v3_opus_verdicts.md`

### D4 — v3 vs v2 对比报告

`reports/eval/sub6b_v3_opus_vs_v2_comparison.md`,简洁(~2 页):

#### 1. Aggregate verdict comparison(主表)

| metric | v2 sub6b_opus | v3 sub6b_opus | Δ |
|---|---:|---:|---|
| n_tasks | 63 | 63 | 0 |
| total claims | 3,281 | ? | ? |
| supported % | 18.10 | ? | ? |
| unsupported % | 12.56 | ? | ? |
| **contradicted %** | 4.18 | ? | ? |
| **unverifiable_v0 %** | 65.16 | ? | ? |
| narrative 平均长度 (chars) | 2766 | ? | ? |

**关键期望**:contradicted 率跟 v2 接近(±1pt),unverifiable 率应该**降低**(因为 LIPID MAPS pathway 名给了 verifier 更多匹配空间)。

#### 2. Per-claim-type 对比(关注 layer 6a/6c)

| claim_type | metric | v2 | v3 | Δ |
|---|---|---:|---:|---|
| set_enrichment | total | 156 | ? | ? |
| set_enrichment | supported | 2 | ? | ? |
| biological_claim | total | 2,288 | ? | ? |
| biological_claim | supported | 511 | ? | ? |
| biological_claim | unverifiable | 1,322 | ? | ? |

#### 3. Lipid bucket 专项分析(11 task)

抽 v3 中 11 个 lipid task,看:

| task_id | LLM 写了 LIPID MAPS pathway 名? | 写了什么 lipid 相关概念? | verifier 匹配上 LIPID MAPS pathway 吗? |
|---|---|---|---|
| eicosanoid task #1 | ? (Y/N) | "eicosanoid synthesis" / "arachidonic acid" / ... | ? |
| eicosanoid task #2 | ... | ... | ... |
| ...11 个全列 | | | |

**关键观察点**:
- 如果 LLM **没** 写 LIPID MAPS pathway 名(只写"lipid metabolism"或"eicosanoid"),**LIPID MAPS 集成对 verifier 价值有限**——LLM 不知道这些 pathway 名存在
- 如果 LLM 写出来但 verifier 仍 unverifiable,**verifier substring matching 没接 LIPID MAPS pathway list**(可能要扩 verifier 数据源)

#### 4. Smoking gun example(挑 1 个 lipid task)

跟 v2 audit 类似格式——挑一个 v3 lipid task 的 narrative + verdict,展示集成的实际行为。

#### 5. 决策建议(给 user)

基于数据给 3 种处理:
- **Case A**:v3 unverifiable 显著降低(>5pt) → ✅ LIPID MAPS 集成有效,投 paper
- **Case B**:基本不变(±2pt) → ⚠️ LIPID MAPS 改了数据,verifier 没接住,需扩 verifier pathway list
- **Case C**:反而变差 → ❌ 集成有 bug,回滚

#### 6. Provenance + MD5 + wall time

### D5 — Acceptance check

```
□ data/eval/sub6/v3/sub6b_opus/sub6b_narratives.jsonl 63 行
□ data/eval/sub6/v3/sub6b_opus/verdicts_v9_phaseC.jsonl ≥ 61 行(允许 2 个失败)
□ results/v3/sub6b_opus/*_summary.json 存在
□ 报告 §1 主表 v2/v3 列填全
□ 报告 §3 11 个 lipid task 全列
□ 0 行代码改动
□ v2 文件 MD5 跟跑前一致(未污染)
```

---

## Pitfalls

1. **viviai relay 偶发 502**:Opus narrative 跑时偶尔失败,加 retry。如果 ≥5 task 失败,记录后跑另一轮 fill-in。

2. **verifier 内部 LLM 必须跟 v2 一致**:第一回合确认 working tree 的 verifier extractor LLM 配置——如果不是 Opus-4-7,stop。

3. **Aggregator 别忘加 `--track sub6b_v3_opus`**:命名标记,跟 v2 区分。

4. **不要触动 v2 文件**:对比基础。任何意外覆盖立刻 escalate。

5. **wall time 不要并发**:Opus 跟 v2 同口径(~20s/task × 63 = 21 min),verifier ~1 hour。串行跑稳。

---

## Time budget

- Confirm: 5 min
- D1 narrative: ~30 min wall(后台跑可写 D4 草稿)
- D2 verifier: ~60 min wall
- D3 aggregator: 5 min
- D4 report: 30-40 min
- D5: 5 min

**Total: 2-3 小时 wall(其中 ~90 min 是计算等待)**。

---

## First action checklist

第一回合:
1. 读 8 个 background 文件
2. 确认 v3 jsonl 行数 = 63
3. 确认 v2 sub6b_opus 文件 MD5(用 `md5sum`)
4. 报告 v9-PhaseC working tree status(`git status verifier/`)
5. 列出 v3 中 11 个 lipid_metabolism task 的 task_id(后续 §3 用)
6. 确认 viviai env vars 已设(`echo $METAGENT_OPENAI_*`)
7. 任何 clarifying question

不要跑命令直到 confirm。

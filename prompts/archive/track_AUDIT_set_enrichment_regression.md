# Track AUDIT — Sub-6A perfect set_enrichment supported 退化诊断

**Session ID:** `track_AUDIT_set_enrichment_regression`
**Branch:** read-only,任意 base(推荐 `feature/sub6-v2-integrated`)
**Estimated work:** 1-2 hours
**Type:** 纯诊断,**不修任何代码 / 不重跑任何 narrative / 不重跑 verifier**

---

## Why this matters

v1 → v2 唯一退化的指标:Sub-6A perfect-id set_enrichment 任务级 supported 数从 **3/14 (21%)** 跌到 **1/38 (3%)**。

绝对数字几乎不变(3→1),但 v2 多了 24 个新 task,几乎都没拿到 set_enrichment supported。Paper reviewer 一定会追问"为什么扩集后这个指标降了"。

本 session 的任务是**找到原因**,不是修复。修不修留给后续决策。

---

## 三种可能假设(逐一验证)

### H1:v2 任务的 ground_truth pathway 在 RaMP enrichment 中排名更难

逻辑:v3 协议加了 quality gate "ground_truth_pathway 必须在 RaMP top-3",但
v1 时这个 gate 较松。v2 里"刚好满足 top-3 但排名靠后"的 task 比例可能更高
→ LLM narrative 提到的 pathway 名跟 ground truth 错开 1-2 位 → set_enrichment
match 不上。

### H2:v2 narrative 风格变化(更模糊)

逻辑:v2 用 Opus-4-7 generate narrative(v1 可能用 MiniMax)。Opus 倾向写
"these compounds may suggest disruption in X-related processes" 这种模糊表述,
被 verifier 分类为 biological_claim 而非 set_enrichment。

### H3:Layer 6a 抽取规则在 v9-PhaseC 上变严

逻辑:Phase C borderline filtering 可能把"温和的 set enrichment claim"降级
为 unverifiable_v0 → supported 数下降。

---

## Hard scope boundaries

**You MAY:**
- 读 v1 + v2 verdict JSONL 文件
- 读 v1 + v2 narrative JSONL 文件
- 读 task JSONL(看 ground_truth_pathway 字段)
- 写诊断报告 `reports/audit/set_enrichment_regression_v1_v2.md`
- 跑只读 SQL 查 RaMP / KEGG sqlite

**You MAY NOT:**
- 修任何代码
- 重跑 narrative / verifier
- 修 task JSONL
- 触动 prompt 模板

---

## Background reading

1. v1 verdict:`results/sub6a_perfect_id_verifier*` 下最新的 `*verdicts.jsonl`
   (找 `claim_type == "set_enrichment"` 且 `verdict == "supported"` 的 3 条)
2. v2 verdict:`data/eval/sub6/v2/sub6a_perfect/verdicts_v9_phaseC.jsonl`
   (找 `claim_type == "set_enrichment"` 且 `verdict == "supported"` 的 1 条)
3. v1 narrative:`results/sub6a_perfect_id_*/sub6a_narratives*.jsonl` 或类似
4. v2 narrative:`data/eval/sub6/v2/sub6a_perfect/sub6a_narratives_perfect_id.jsonl`
5. v1 task:`data/benchmark/sub6/sub6a_e2e_tasks.jsonl`(14 task)
6. v2 task:`data/benchmark/sub6/sub6a_e2e_tasks_v2.jsonl`(38 task)
7. Verifier Layer 6a code:`verifier/layers/pathway_enrichment.py`(看
   v9-PhaseC 的 set_enrichment 判定逻辑)

In your first response,确认:
- 找到 v1 的 3 个 supported set_enrichment claim 的 task_id
- 找到 v2 的 1 个 supported set_enrichment claim 的 task_id
- 报告 v9-PhaseC 在 set_enrichment 上的判定规则简述

不要写代码直到我 confirm。

---

## Deliverables

### D1 — 提取所有 set_enrichment claim(v1 + v2)

```
v1 (14 task):
  total set_enrichment claims: ?
  supported: 3 (确认)
  unsupported: ?
  contradicted: ?
  unverifiable_v0: ?

v2 (38 task):
  total set_enrichment claims: ?
  supported: 1 (确认)
  unsupported: ?
  contradicted: ?
  unverifiable_v0: ?
```

如果 v2 total set_enrichment claim 数量比 v1 少很多(比如 v1=15 v2=10),
那 supported 跌就是 H3(抽取规则严了导致 claim 没被认成 set_enrichment)。

如果 v2 total 数量正常(比如 v2 ≈ 38 × v1平均),那要看 verdict 分布。

### D2 — 验证 H1(ground truth 难度)

对每个 v2 set_enrichment supported / unsupported claim 的 task,看:
- ground_truth_pathway 在该 task 的 RaMP enrichment top-3 排第几位
- v1 同上

输出表格:
```
task_id | track | claim verdict | gt_pathway_rank_in_RaMP | top-3 pathway names
```

如果 v2 的 gt_pathway 排名系统性地比 v1 更靠后(e.g. v1 平均 rank 1.5,
v2 平均 rank 2.5),H1 成立。

### D3 — 验证 H2(narrative 风格)

抽 5 个 v1 supported task + 5 个 v2 unsupported task 的 narrative,
对比里面的 set_enrichment claim 句子风格:

| task_id | track | narrative 中 set_enrichment 句子 | verdict |
|---|---|---|---|
| ... | v1 | "These compounds are enriched in glycolysis" | supported |
| ... | v2 | "The pattern suggests potential disruption..." | unsupported |

如果 v2 句子明显更模糊(条件词、推测词更多),H2 成立。

### D4 — 验证 H3(抽取规则)

读 `verifier/layers/pathway_enrichment.py` 的 v9-PhaseC 代码,看
set_enrichment 判定的核心逻辑。比较 v1 时期(更早 commit)的版本,
看 Phase C borderline filter 是否新增了让 set_enrichment 降级的规则。

Git command:
```bash
git log --oneline --all -- verifier/layers/pathway_enrichment.py | head -20
```

找出 v9-PhaseC 跟 v1 时期版本的 diff,看 set_enrichment 路径上的关键逻辑变化。

如果 Phase C 引入了"模糊 enrichment claim → unverifiable"的规则,H3 成立。

### D5 — 写诊断报告

`reports/audit/set_enrichment_regression_v1_v2.md`,包含:

#### 1. Summary
- v1 vs v2 set_enrichment verdict 全分布
- 主因(H1/H2/H3,可能多个组合)
- 严重性评估(对 paper 影响)

#### 2. H1 evidence
- gt_pathway rank 分布对比

#### 3. H2 evidence
- 5+5 narrative 句子对比

#### 4. H3 evidence
- Layer 6a 代码 diff 关键片段 + 解读

#### 5. 推荐处理(给 user 决策,不实施)
基于主因:
- H1 → 接受为 v2 数据特性,paper limitation 写明
- H2 → 也接受,paper 写"v2 narrative 风格变化"作为 finding
- H3 → 考虑回退 Phase C borderline filter 在 set_enrichment 上的应用

#### 6. Provenance
- git commit + 数据文件 MD5 + 诊断时间

### D6 — Acceptance

```
□ D1 数字给出
□ D2 表格 ≥ 4 行
□ D3 句子对比 ≥ 10 句(5 v1 + 5 v2)
□ D4 给出 git diff 关键片段
□ D5 诊断报告完整
□ 0 行代码改动(纯只读 audit)
```

---

## Time budget

- D1: 30 分钟(脚本提取 + 统计)
- D2: 30 分钟(SQL + 比对)
- D3: 30 分钟(读 narrative)
- D4: 30 分钟(git log + diff)
- D5: 30 分钟
- D6: 5 分钟

总:~2 小时。

---

## First action checklist

第一回合:
1. 读 7 个 background 文件
2. 报告 v1 / v2 的 supported set_enrichment task_id list
3. 报告 v9-PhaseC 的 set_enrichment 判定核心规则简述(贴几行代码)
4. 推荐先验证哪个假设(H1/H2/H3)优先级
5. 任何 clarifying question

不要写代码直到 confirm。

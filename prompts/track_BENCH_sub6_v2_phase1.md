# Track BENCH Sub-6 v2 Phase 1 — Expand to 100 Sub-6B tasks

**Session ID:** `track_BENCH_sub6_v2_phase1`
**Branch:** `feature/sub6-v2-expand` (新建,base on `feature/layer6c-phrase-resolver`)
**Estimated work:** 1-2 days
**Predecessor reports:**
- `reports/benchmark/sub6_construction_report.md` (current 20+14 task baseline)
- `reports/eval/sub6_baseline_day3_2026-05-01.md`
- `reports/verifier/llm_3way_comparison_2026-05-05.md`

---

## Who you are

你在扩展 Sub-6 enrichment benchmark,从 20 (Sub-6B) + 14 (Sub-6A) 扩到 100 (Sub-6B)。Sub-6A 的 spectrum 扩展是 **Phase 2 另一个 session 做的事**,**本 session 不碰 Sub-6A**。

整个 build infrastructure 已经在 `tools/benchmark/sub6/` 和 `scripts/build_sub6/build_all.py` 里。本 session 只需要修 1 个 bug + re-run + write audit。

---

## Hard scope boundaries

**You MAY:**
- 修 `scripts/build_sub6/build_all.py`(只改 line ~158 的硬编码 `pathway_min_compounds=5`)
- Re-run `build_all.py` with new CLI flags
- 写新的 audit 文件 `reports/benchmark/sub6_construction_report_v2.md`
- 创建 `data/benchmark/sub6/sub6b_mammalian_tasks_v2.jsonl` 和 `data/benchmark/sub6/curated_hmdb_mammalian_v2.jsonl`
- 跑测试

**You MAY NOT:**
- 动 `tools/benchmark/sub6/compound_curator.py`(改 default 会破坏 backward compat)
- 动 `tools/benchmark/sub6/task_constructor.py`(已经支持 `pathway_min_compounds=3`)
- 动 Sub-6A 相关任何东西(Phase 2 处理)
- 覆盖 v1 文件(必须 `_v2` 后缀,保留 v1 做 before/after 对比)
- 修 verifier、orchestrator、prompt 模板

---

## Background reading (mandatory first action)

Read these files,在 first response 报告关键发现:

1. `scripts/build_sub6/build_all.py` 完整(626 行)
   - **关键确认:** line ~158 是不是确实硬编码 `pathway_min_compounds=5`?
2. `tools/benchmark/sub6/compound_curator.py` 函数 `curate_hmdb_mammalian_subset` 签名
   - 确认:`pathway_min_compounds` 参数存在且接受 int
3. `tools/benchmark/sub6/task_constructor.py` 函数 `construct_compound_only_tasks` 签名
   - 确认:`pathway_min_compounds=3` 已是 task 阶段默认值
4. `data/benchmark/sub6/curated_hmdb_mammalian.jsonl` (150 行,verify)
5. `data/processed/hmdb_candidates_npc_classified.jsonl` (300 行,verify)
6. `reports/benchmark/sub6_construction_report.md` 当前 v1 audit

In your first response,确认:
- The single-line bug location
- Upstream HMDB candidate pool size (确认 300)
- Upstream pool 里有多少 compound 当前因 `pathway_min_compounds=5` 在 curator 阶段被砍
- 预测如果把 curator 阶段也改成 ≥3,curated pool 能从 150 涨到多少(150-300 之间)

**不要写代码直到我 confirm。**

---

## Deliverables

### D1 — Fix `build_all.py` hardcoded threshold(15 分钟)

把 `scripts/build_sub6/build_all.py` 里硬编码的 `pathway_min_compounds=5`(在调用 `curate_hmdb_mammalian_subset` 那段)改为使用 CLI 参数 `args.pathway_min_compounds`。

注意:这个改动让 default 行为发生变化(curator 阶段从 5 → 3)。可能影响其他依赖 default 行为的地方。**只改 build_all.py,不改 compound_curator.py 的 default**。

如果你担心影响 backward compat,**新增** 一个 CLI 参数 `--curator-pathway-min-compounds`(default 3),保留 `--pathway-min-compounds` 给 task 阶段。这样默认行为变了,但用户可以通过 CLI 显式回退。

### D2 — Sanity test(10 分钟)

跑一个最小的 build:
```bash
python scripts/build_sub6/build_all.py \
    --target-6b-mammalian 30 \
    --target-curated-hmdb 200 \
    --pathway-min-compounds 3 \
    --output-dir /tmp/sub6_v2_smoke \
    --report-path /tmp/sub6_v2_smoke/report.md \
    --skip-spectrum-index
```

确认:
- 不报错
- curated_hmdb_mammalian.jsonl 行数 > 150(说明 D1 改对了)
- sub6b_mammalian_tasks.jsonl 行数 > 20

如果 curated 还是 150,D1 没改对,debug。
如果 task 数 < 30,可能还有别的瓶颈,在第一回合 escalate。

### D3 — Full v2 build(30-60 分钟 wall)

一旦 D2 通过,跑正式 v2 build:
```bash
python scripts/build_sub6/build_all.py \
    --target-6b-mammalian 100 \
    --target-curated-hmdb 250 \
    --pathway-min-compounds 3 \
    --tasks-per-pathway-max 6 \
    --tasks-per-bucket-max 15 \
    --output-dir data/benchmark/sub6/ \
    --report-path reports/benchmark/sub6_construction_report_v2_raw.md \
    --skip-spectrum-index \
    --seed 42
```

注意 `--tasks-per-bucket-max` 从 default 8 提到 15(否则 single bucket 把 100 task 卡死)。

**关键:** `--skip-spectrum-index` 必须有,因为 Sub-6A 是 Phase 2 的事,不在本 session scope。

文件输出:
- `data/benchmark/sub6/curated_hmdb_mammalian.jsonl` ← 会被覆盖 ⚠️

**为了保留 v1**,在跑之前做 backup:
```bash
cp data/benchmark/sub6/curated_hmdb_mammalian.jsonl data/benchmark/sub6/curated_hmdb_mammalian_v1.jsonl
cp data/benchmark/sub6/sub6b_mammalian_tasks.jsonl data/benchmark/sub6/sub6b_mammalian_tasks_v1.jsonl
cp data/benchmark/sub6/sub6a_e2e_tasks.jsonl data/benchmark/sub6/sub6a_e2e_tasks_v1.jsonl
```

跑完后,把新输出 rename 为 v2:
```bash
mv data/benchmark/sub6/curated_hmdb_mammalian.jsonl data/benchmark/sub6/curated_hmdb_mammalian_v2.jsonl
mv data/benchmark/sub6/sub6b_mammalian_tasks.jsonl data/benchmark/sub6/sub6b_mammalian_tasks_v2.jsonl
# sub6a_e2e_tasks.jsonl 不应该被生成(--skip-spectrum-index),如果生成了也 mv 走或删除
```

把 v1 备份恢复回原名(下游消费者还在用):
```bash
cp data/benchmark/sub6/curated_hmdb_mammalian_v1.jsonl data/benchmark/sub6/curated_hmdb_mammalian.jsonl
cp data/benchmark/sub6/sub6b_mammalian_tasks_v1.jsonl data/benchmark/sub6/sub6b_mammalian_tasks.jsonl
cp data/benchmark/sub6/sub6a_e2e_tasks_v1.jsonl data/benchmark/sub6/sub6a_e2e_tasks.jsonl
```

### D4 — Audit report(30 分钟)

写 `reports/benchmark/sub6_construction_report_v2.md`,包含:

#### 1. Summary
- v1 vs v2 对比表:
  | metric | v1 | v2 |
  |---|---|---|
  | curated HMDB compounds | 150 | ? |
  | Sub-6B mammalian tasks | 20 | ? |
  | unique pathways covered | 7 | ? |
  | unique pathway buckets covered | 4 | ? |

#### 2. Bucket distribution
- 每个 bucket 多少 task(amino_acid / nucleotide / lipid / central / other)
- 跟 v1 比较,哪些 bucket 涨了哪些没涨

#### 3. Pathway distribution
- 每个 ground_truth pathway 多少 task
- top-5 pathway + tail

#### 4. Quality gates(必须 100% 通过)
- ground_truth_pathway 在 RaMP enrichment top-3 的占比 (acceptance: 100%)
- 没有 pfocr pathway (acceptance: 100%)
- signal compound 数 ≥ 3 per task (acceptance: 100%)
- noise compound 数 ≥ 0 per task (放宽,允许 0 noise)

#### 5. Curation stats
- 输入 300 → 多少 valid SMILES → 多少有 RaMP → 多少 pass pathway gate → 多少 final
- 列出每步丢弃的原因 + 数量

#### 6. Provenance
- git commit SHA
- File MD5(curated_hmdb_mammalian_v2.jsonl, sub6b_mammalian_tasks_v2.jsonl)
- 跑这个 build 的命令(完整)
- Wall time

#### 7. Known limitations
- 哪些 bucket 仍然 < 5 task
- 哪些 pathway 只有 1 个 task(不能做 per-pathway statistics)
- 用户决定不做 plant subset(填 paper limitation 用)

### D5 — Acceptance check

完成 D4 后,自检:

```
□ build_all.py 改动只 1-2 行,其他文件未动
□ data/benchmark/sub6/curated_hmdb_mammalian_v2.jsonl 存在,行数 ≥ 200
□ data/benchmark/sub6/sub6b_mammalian_tasks_v2.jsonl 存在,行数 ≥ 80(目标 100,允许 buffer)
□ data/benchmark/sub6/curated_hmdb_mammalian.jsonl 仍是 v1(150 行)
□ data/benchmark/sub6/sub6b_mammalian_tasks.jsonl 仍是 v1(20 行)
□ reports/benchmark/sub6_construction_report_v2.md 完整,涵盖 §1-7
□ ground_truth pathway 全在 RaMP top-3(quality gate 100%)
□ bucket 至少 4 个非空,每桶 ≥ 5 task(否则 escalate)
□ git diff 只有 build_all.py + 新文件,无其他改动
```

如果 acceptance check 任何一条失败,在 final response 显式 flag,不要假装通过。

---

## Pitfalls to avoid

1. **不要覆盖 v1 文件**。下游 verifier evaluation / cross-LLM 报告还在用 v1。任何 v1 文件被覆盖都视为破坏性操作,**先 backup 再跑 build**。

2. **不要改 `tools/benchmark/sub6/compound_curator.py` 的 default 值**。CLI 流转 OK,但函数 default 一改,所有调用方都受影响。

3. **不要 commit 大数据文件**。新增的 `_v2.jsonl` 文件应该跟 v1 一样处理(在 .gitignore 里或 git-lfs),不要直接 commit 几 MB 的 JSONL 进 git。检查 `.gitignore` 现有规则。

4. **不要跑 spectrum index**。这是 Phase 2 的事,本 session `--skip-spectrum-index` 必须开着。Spectrum index 跑全 GNPS 要几小时,误开会浪费时间。

5. **CLI 参数兼容性**。如果你新增了 `--curator-pathway-min-compounds`,确认旧的 `--pathway-min-compounds` 仍然 work(只影响 task 阶段)。

6. **如果 bucket 100% 不平衡**(所有 100 task 都在一个 bucket),说明 `--tasks-per-bucket-max 15` 不够,可能要再调整。但**不要**为了平衡而砍 task 数,要**记录**实际分布让上层决定。

---

## Time budget

- D1 + D2: 30 分钟
- D3: 1 小时(主要是 build 跑的 wall time)
- D4: 30-45 分钟
- D5: 10 分钟

**总:** 2-3 小时。如果 D2 smoke test 失败 + 需要 debug curator 内部逻辑,escalate(可能需要扩 upstream pool)。

---

## First action checklist

第一回合,做这些:

1. 读 6 个 background 文件
2. 在 build_all.py 里精确定位 pathway_min_compounds=5 的硬编码位置(file:line)
3. 报告 upstream pool 的真实化合物分布:
   ```
   wc -l data/processed/hmdb_candidates_npc_classified.jsonl
   # 期望 300
   ```
4. 估计如果 curator 阶段也用 `pathway_min_compounds=3`,curated pool 能涨到多少(140?200?280?)
5. 报告 `--tasks-per-bucket-max` default 8 vs 推荐 15 的差异:当前 v1 各 bucket 多少 task?
6. 确认 `tasks-per-pathway-max=6 + tasks-per-bucket-max=15` 数学上能撑 100 task(假设 ≥30 个 qualifying pathway,每个 ≤6,合计 ≥180,bucket 5 个 × 15 = 75,实际取 min)
7. 任何 clarifying question

不要开始写代码直到我 confirm 这 7 条。

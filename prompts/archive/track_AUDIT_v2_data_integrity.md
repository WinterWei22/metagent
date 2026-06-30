# Track AUDIT — Sub-6 v2 数据全面完整性检查

**Session ID:** `track_AUDIT_v2_data_integrity`
**Branch:** read-only,任意 base(推荐 `feature/sub6-v2-integrated`)
**Estimated work:** 2-3 hours
**Type:** **纯只读** — 0 行代码改动 / 0 次重跑 / 0 个文件修改

---

## Why this matters

v2 数据扩展完成后,有 8 个具体可疑点(5 P0 + 3 P1)需要在投稿前查清。本 session 跑数据完整性 audit,不动任何东西,产出 PASS/FAIL/WARN 报告。

每个检查项必须给:
- **检查方法**:精确说明读了哪个文件 / 用什么字段
- **数字证据**:具体 count / 比例 / list
- **判定**:PASS / WARN / FAIL
- **影响**:对 paper 的具体影响(若 FAIL)

---

## Hard scope boundaries

**You MAY:**
- 读所有 v2 数据文件 (`data/benchmark/sub6/*v2*`)
- 读所有 verdict / narrative JSONL
- 读 `data/processed/nm002_excluded_gnps_ids.json`
- 读 RaMP / HMDB sqlite(只读 SQL 查询)
- 写 audit 报告 `reports/audit/v2_data_integrity_audit.md`
- 在 `/tmp/` 下生成中间分析 CSV

**You MAY NOT:**
- 修任何代码
- 重跑任何 benchmark / verifier / narrative
- 修改 `data/benchmark/`、`data/eval/`、`data/processed/` 任何文件
- 创建任何 _v3 文件(只 audit 不修复)
- 删除现有文件

---

## Background reading

1. `data/benchmark/sub6/sub6b_mammalian_tasks_v2.jsonl`(63 task)
2. `data/benchmark/sub6/sub6a_e2e_tasks_v2.jsonl`(38 task)
3. `data/benchmark/sub6/curated_hmdb_mammalian_v2.jsonl`(250 化合物)
4. `data/processed/hmdb_candidates_npc_classified_v2.jsonl`(600 化合物 upstream pool)
5. `data/processed/nm002_excluded_gnps_ids.json`(317K GNPS exclusion list)
6. `reports/benchmark/sub6_construction_report_v2.md`(主构建报告)
7. `reports/benchmark/sub6a_v2_construction_audit.md`(Sub-6A 构建)
8. `reports/benchmark/curation/hmdb_pool_expansion_audit.md`(600 pool 扩展)
9. `reports/eval/sub6_v2_comparison_2026-05-06.md`(主结果)

In your first response,确认:
- 每个 task json 的 schema 关键字段(noise_count, signal_count, ground_truth_pathway 等)
- noise_compounds 是 task 顶层字段还是嵌套字段
- Sub-6A `differential_spectra` 里 `source_id` 字段的 prefix 格式(GNPS / MassBank / RIKEN)
- v2 task 是否带 seed 字段(用于 cross-task 一致性检查)

不要写代码或跑分析,直到 confirm。

---

## Checks

### P0-1: noise = 0 是 bug 还是设计变更?

**v3.1 协议要求**:每 task 有 ≥2 noise compounds(干扰项),让 LLM 必须区分 signal vs noise。

**检查**:
```python
for task in sub6b_v2 + sub6a_v2:
    noise_n = len(task.get("ground_truth_noise_compounds", []))
    signal_n = len(task.get("ground_truth_signal_compounds", []))
```

输出表格:
| metric | sub6b_v2 (63) | sub6a_v2 (38) |
|---|---:|---:|
| min noise_count | ? | ? |
| max noise_count | ? | ? |
| mean noise_count | ? | ? |
| tasks with noise=0 | ? | ? |
| tasks with noise≥2 | ? | ? |

**判定**:
- PASS: 所有 task noise ≥ 2
- WARN: 部分 task noise = 0-1,但有意为之(check task_constructor 是否有 noise_required=True 默认)
- FAIL: 大量 task noise = 0,且违反协议

**注意**:在主构建报告 §4 quality gate 写的是 "noise compound count >= 0 per task (放宽,允许 0 noise)"。这是设计放宽还是 protocol drift?查 git log on `tools/benchmark/sub6/task_constructor.py` 看 noise default 是什么,何时改的。

### P0-2: 6 个 pathway 单 task 问题

**主报告说**:13 unique pathways,top 5 占 46/63 task,6 pathway 仅 1 task。

**检查**:
```python
from collections import Counter
pw = Counter(task["ground_truth_pathway"]["external_id"] for task in sub6b_v2)
```

输出:
| pathway_id | name | n_tasks |
|---|---|---:|
| (top 13 列出来) | | |

**判定**:
- 单 task pathway 数量(=6 ?)
- 单 task pathway 是否本身有意义(疾病通路 vs 真实代谢通路)
- 是否能合并相似单 task pathway 提高 per-pathway power
- **paper limitation**:per-pathway statistics 不可做的具体 pathway list

### P0-3: Sub-6A 的 GNPS exclusion 是否仍生效?

**风险**:Sub-6A real-id 跑 library_search,如果 spectrum 来自 GNPS 且没过 NM-002 filter,会自匹配虚高 id_acc。

**检查**:
```python
# 1. 看每条 differential_spectra 的 source_id
for task in sub6a_v2:
    for spec in task["differential_spectra"]:
        sid = spec.get("source_id", "")
        # 分类: GNPS (CCMSLIB...), MassBank (MSBNK-...), RIKEN, etc.

# 2. 看 source_id 是否在 nm002_excluded list 里
excluded = set(json.load(open("data/processed/nm002_excluded_gnps_ids.json"))["excluded_ids"])
overlap = [sid for sid in all_sub6a_source_ids if sid in excluded]

# 3. 看 logs/v2/sub6a_real.log 里有没有 exclusion_source_ids 实际传入
```

输出:
| metric | value |
|---|---:|
| total Sub-6A spectra | 459 |
| GNPS source spectra (CCMSLIB-prefix) | ? |
| MassBank source spectra (MSBNK-prefix) | ? |
| RIKEN-derived spectra (应为 0) | ? |
| GNPS spectra in nm002_excluded list | ? |
| spectra excluded at runtime in real-id run | ? |

**判定**:
- PASS: 实际 library_search 跑时,task-level exclusion list 生效(log 里能看到)
- WARN: exclusion list 加载了但未传入 library_search
- FAIL: GNPS 谱图 source_id 没过 leakage filter,可能虚高 id_acc

特别检查:Sub-6A real-id v2 跑出来 67.32% top-1。**如果 GNPS exclusion 没生效,这数字部分是自匹配**。这是 NM-002 整套机制的核心场景,必须确认。

### P0-4: HMDB upstream pool 600 化合物是否真被 task 用上?

**风险**:扩 pool 300→600 是为了 task 多样性,但 build_all 实际可能只挑前 250 个 → 600 白建。

**检查**:
```python
# 1. v2 600 pool 的 KEGG ID set
upstream_keggs = {row["kegg_id"] for row in hmdb_candidates_v2 if row.get("kegg_id")}
print("upstream:", len(upstream_keggs))

# 2. v2 250 curated 的 KEGG ID set
curated_keggs = {row["kegg_id"] for row in curated_hmdb_mammalian_v2 if row.get("kegg_id")}
print("curated:", len(curated_keggs))

# 3. v2 task 实际用了多少 unique KEGG
task_keggs = set()
for task in sub6b_v2:
    for c in task.get("ground_truth_signal_compounds", []) + task.get("ground_truth_noise_compounds", []):
        if c.startswith("C"):
            task_keggs.add(c)
    for m in task.get("differential_metabolites", []):
        if m.get("kegg_id"):
            task_keggs.add(m["kegg_id"])
print("used in tasks:", len(task_keggs))

# 4. 比例
print("upstream → curated 使用率:", len(curated_keggs) / len(upstream_keggs))
print("curated → task 使用率:", len(task_keggs & curated_keggs) / len(curated_keggs))
print("upstream → task 使用率:", len(task_keggs & upstream_keggs) / len(upstream_keggs))
```

输出:
| metric | value | % of 600 |
|---|---:|---:|
| upstream pool unique KEGG | 526 | 100% |
| curated 250 unique KEGG | ? | ? |
| task 实际用上 unique KEGG | ? | ? |
| **utilization (task / upstream)** | ? | ? |

**判定**:
- PASS: ≥40% upstream 化合物被 task 用上
- WARN: 20-40%
- FAIL: <20% (说明 600 大部分白建,curator/constructor 有 bottleneck)

### P0-5: 新数据是否过 NM-002 leakage filter

**重点**:扩 pool 时容易漏过 leakage filter。

**检查**:
```python
# 1. 600 upstream pool 是否过 NM-002
# (NM-002 主要是 GNPS 排除,跟 HMDB 化合物层无关,但要确认)
# 看 hmdb_candidates_v2 的构建脚本里有没有调 leakage_filter

# 2. Sub-6A v2 spectra 的 source_id 是否在 nm002_excluded
# 跟 P0-3 部分重叠,这里看的是"是否进入 task 之前过滤了"
```

特别看:
- `tools/benchmark/sub6/spectrum_lookup.py` 是否调用 `tools.benchmark.leakage_filter`?
- 还是 leakage 只在 runtime library_search 调用层做?

**判定**:
- PASS: build 时已过滤 + runtime 也过滤(双重保险)
- WARN: 仅 runtime 过滤
- FAIL: 哪一层都没过滤

### P1-1: 每 task signal compound 跨 task 重复?

**风险**:同 5 个 steroid 化合物用 10 个不同 seed 抽,生成 10 个 task,这些 task 之间相关性极高 → 统计 power 虚高。

**检查**:
```python
# task signal compound 集
task_to_signal = {task["task_id"]: tuple(sorted(task["ground_truth_signal_compounds"])) for task in sub6b_v2}

# 1. 完全相同 signal set 的 task 数
from collections import Counter
sig_count = Counter(task_to_signal.values())
duplicate_sets = {s: c for s, c in sig_count.items() if c > 1}

# 2. 部分重叠(jaccard ≥ 0.7)的 task pair
import itertools
high_overlap_pairs = []
for t1, t2 in itertools.combinations(task_to_signal, 2):
    s1, s2 = set(task_to_signal[t1]), set(task_to_signal[t2])
    jac = len(s1 & s2) / len(s1 | s2) if s1 | s2 else 0
    if jac >= 0.7:
        high_overlap_pairs.append((t1, t2, jac))
```

输出:
| metric | value |
|---|---:|
| tasks with identical signal set | ? |
| task pairs with jaccard ≥ 0.9 | ? |
| task pairs with jaccard ≥ 0.7 | ? |
| task pairs with jaccard ≥ 0.5 | ? |
| max jaccard (excluding self) | ? |
| signal compound 在 ≥3 task 出现的化合物数 | ? |

**判定**:
- PASS: <10% task 跟另一个 task jaccard ≥ 0.7
- WARN: 10-30%
- FAIL: >30% (paper 不能 claim 63 个 independent samples)

### P1-2: Sub-6A spectrum 每化合物 ≥3 条覆盖率

**v3.1 协议提到**:目标 ≥3 spec/compound,实际 ≥1 也接受。

**检查**:
```python
# Sub-6A 38 task 里每个 signal compound 实际 spectrum 数
from collections import defaultdict
compound_spec_count = defaultdict(int)
for task in sub6a_v2:
    for spec in task["differential_spectra"]:
        cmpd = spec.get("compound_kegg_id") or spec.get("compound_inchikey")
        compound_spec_count[(task["task_id"], cmpd)] += 1
```

输出:
| metric | value |
|---|---:|
| 每 task 平均 spectrum 数 | 9.143 |
| 每 task signal compound 平均 spectrum 数 | ? |
| n compounds with ≥3 spectra | ? |
| n compounds with =1 spectrum | ? |
| n compounds with 0 spectrum (drop) | ? |

**判定**:
- PASS: ≥80% compound 有 ≥3 spectra
- WARN: 50-80%
- FAIL: <50% (大部分单谱图,鲁棒性弱)

### P1-3: 同 pathway 不同 seed 的 ground_truth 一致性

**风险**:Methionine Metabolism 9 个 task,如果它们的 ground_truth_pathway 字段填的不一样(例如 RAMP_id 飘),verifier 评测会乱。

**检查**:
```python
# 按 pathway_id 分组
from collections import defaultdict
pathway_to_tasks = defaultdict(list)
for task in sub6b_v2:
    pw = task["ground_truth_pathway"]["pathway_id"]
    pathway_to_tasks[pw].append(task)

# 检查每个 pathway 内,所有 task 的 ground_truth 字段一致
for pw_id, tasks in pathway_to_tasks.items():
    if len(tasks) < 2:
        continue
    # 所有 task ground_truth_pathway 应字段对字段一致
    first = tasks[0]["ground_truth_pathway"]
    for t in tasks[1:]:
        if t["ground_truth_pathway"] != first:
            print(f"INCONSISTENT pathway {pw_id}: task {t['task_id']} differs")
```

**判定**:
- PASS: 所有 same-pathway task 的 ground_truth 字段完全一致
- WARN: 只有 metadata (timestamp 等) 差异
- FAIL: pathway_name / external_id / source 漂移

---

## Deliverable

### `reports/audit/v2_data_integrity_audit.md`

#### 1. Executive summary

```
Total checks: 8 (5 P0 + 3 P1)
PASS:  ?
WARN:  ?
FAIL:  ?

Critical issues for paper investment: [list FAIL items]
```

#### 2. Per-check detail (8 sections, 1 per check above)

每节包含:
- 检查方法
- 数字证据(表格)
- 判定 (PASS/WARN/FAIL)
- 影响 (paper / 数据可信度)
- 推荐处理(若需修)

#### 3. Cross-cutting findings

任何在多个 check 之间观察到的模式(e.g. 6 个单 task pathway 都来自 wikipathways → 数据源 quality 问题)。

#### 4. Recommended actions(决策权交 user)

按优先级排,每条给:
- 修复成本(代码改动量 / 重跑时间)
- 修不修对 paper 的影响
- 推荐(yes/no/wait_for_paper_v1)

#### 5. Provenance

- git commit
- 8 个 audit 数据文件 MD5
- audit wall time
- 0 行代码改动 / 0 次重跑(必须确认)

---

## Acceptance check

```
□ 8 个 check 全部跑了
□ 每个 check 给出数字证据(不是 hand-wave)
□ PASS/WARN/FAIL 判定标准明确
□ 0 行代码改动
□ 0 个 data/ 文件被修改
□ 0 次 verifier / narrative 重跑
□ 报告完整 5 节
```

---

## Pitfalls

1. **不要修复任何 issue**:本 session 只 audit。即使发现 noise=0 是 bug,也只记录,不动 task json。修复留给后续 session。

2. **判定阈值要严格写出**:"PASS = ≥80%" 比 "PASS = mostly good" 有用 100 倍。

3. **P0-3 是 audit 最关键的检查**:GNPS exclusion 失效会让 67.32% id_acc 数字部分作废。**必须 100% 确定 exclusion 在 runtime 真生效**。

4. **不要假定 schema**:每个字段都先 grep 确认存在,再统计。task json schema 在 v1 / v2 之间可能变化。

5. **报告必须可执行**:每条 finding 给具体的 task_id / KEGG ID / source_id 例子,不只是聚合数字。

---

## Time budget

- Confirm + setup: 15 分钟
- P0-1 (noise): 15 分钟
- P0-2 (single-task pathway): 15 分钟
- P0-3 (GNPS exclusion): 30 分钟(最复杂)
- P0-4 (600 pool utilization): 20 分钟
- P0-5 (NM-002 filter): 20 分钟
- P1-1 (signal overlap): 30 分钟
- P1-2 (spectrum coverage): 15 分钟
- P1-3 (cross-task consistency): 15 分钟
- 报告整合: 30 分钟

**Total: 3-4 hours**(纯只读,无 LLM 调用,无 GPU)。

---

## First action checklist

第一回合:
1. 读 9 个 background 文件
2. 报告 sub6b_v2 / sub6a_v2 task json schema(关键字段列表 + 类型)
3. 报告 noise_compounds 字段位置(顶层? 嵌套?)
4. 报告 differential_spectra 字段是否含 source_id
5. 报告 600 pool 文件第一条记录的字段
6. 报告 nm002_excluded_gnps_ids.json 的 keys 列表
7. 任何 clarifying question

不要写代码或跑命令,直到 confirm。

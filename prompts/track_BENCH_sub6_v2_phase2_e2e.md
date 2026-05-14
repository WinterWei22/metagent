# Track BENCH Sub-6 v2 Phase 2 — Build Sub-6A v2 with expanded spectrum coverage

**Session ID:** `track_BENCH_sub6_v2_phase2_e2e`
**Branch:** `feature/sub6-v2-e2e` (新建,base on `feature/sub6-v2-expand-pool`)
**Estimated work:** 0.5-1 day
**Predecessor reports:**
- `reports/benchmark/sub6_construction_report_v2.md`(N=63 Sub-6B v2 已交付)
- `reports/benchmark/curation/hmdb_pool_expansion_audit.md`(600 pool)

---

## Who you are

Sub-6B v2 (63 task) 已建。本 session 把 Sub-6A 从 14 task 扩到尽可能多
(目标 30-40),给 cascade decomposition figure 提供数据。

**关键发现:** `tools/benchmark/sub6/spectrum_lookup.py` 已经实现了 GNPS +
MassBank-non-RIKEN spectrum index;`scripts/build_sub6/build_all.py` 的
Step 3+4 已经集成。所以本 session 大部分是**复用现有 pipeline**,不是写新代码。

---

## Hard scope boundaries

**You MAY:**
- 跑 `build_all.py`(不加 `--skip-spectrum-index`)
- 写新的 audit `reports/benchmark/sub6a_v2_construction_audit.md`
- 调整 `--spectra-per-compound-min/max` 等 CLI 参数
- 修 `tools/benchmark/sub6/spectrum_lookup.py` 中的 minor bug(若发现)

**You MAY NOT:**
- 覆盖 v1 文件(`sub6a_e2e_tasks.jsonl` 已有 14 task,backup 后再跑)
- 覆盖 Sub-6B v2 文件(`sub6b_mammalian_tasks_v2.jsonl`,本 session 不动 Sub-6B)
- 覆盖 curated_hmdb_mammalian_v2.jsonl(本 session 复用,不重建)
- 修 Sub-6B 任何东西
- 重写 spectrum_lookup.py 主 logic

---

## Background reading (mandatory)

1. `tools/benchmark/sub6/spectrum_lookup.py`(完整,13700 bytes)
   - 报告:`build_spectrum_index()` 签名 + 输入输出
   - 报告:source 包含 GNPS + 哪些 MassBank contributors,RIKEN 是否排除
   - 报告:NM-002 leakage 怎么处理(docstring 说 downstream orchestrator's job)
2. `scripts/build_sub6/build_all.py` Step 3 + Step 4(line 180-220)
3. `data/benchmark/sub6/sub6a_e2e_tasks.jsonl`(v1, 14 task)— 看 schema
4. `data/benchmark/sub6/sub6b_mammalian_tasks_v2.jsonl`(v2, 63 task)— 这是 Sub-6A v2 的化合物来源
5. `data/processed/nm002_excluded_gnps_ids.json`(317K excluded IDs)— 看格式

In your first response,确认:
- `build_spectrum_index` 默认 contributors 列表(不含 RIKEN?)
- HMDB-Mammalian 250 化合物里,GNPS+MassBank 能 cover 多少(spectrum_lookup 的 coverage 报告)
- 当前 Sub-6A v1 的每 task spectra 数分布(平均、max、min)
- 期望:用 v2 pool (250 vs 150),Sub-6A 应该能从 14 涨到多少

不要写代码直到我 confirm。

---

## Deliverables

### D1 — Smoke test(15 分钟)

跑一个 Sub-6A only smoke build:

```bash
PYTHONPATH=. python scripts/build_sub6/build_all.py \
    --hmdb-candidates data/processed/hmdb_candidates_npc_classified_v2.jsonl \
    --target-6b-mammalian 100 \
    --target-curated-hmdb 250 \
    --pathway-min-compounds 3 \
    --tasks-per-pathway-max 10 \
    --tasks-per-bucket-max 20 \
    --target-6a 40 \
    --spectra-per-compound-min 1 \
    --spectra-per-compound-max 3 \
    --min-compounds-with-spectra 3 \
    --output-dir /tmp/sub6_v2_e2e_smoke \
    --report-path /tmp/sub6_v2_e2e_smoke/report.md \
    --seed 42
```

**注意没有** `--skip-spectrum-index`(本 session 核心)。

如果跑挂了 / spectrum_lookup OOM / GNPS MGF 找不到,escalate。
预期 wall time 5-15 分钟(spectrum index 构建 + Sub-6A 任务生成)。

报告:
- Sub-6A task 数 N
- 每 task 平均 spectra 数
- coverage(多少 compound 没找到 spectrum)

### D2 — Full v2 build(30-60 分钟)

D1 通过后,跑正式输出。**严格按 Phase 1 的 backup-then-rename 流程**:

```bash
# 1. backup v1 (Sub-6B v2 已经做过 backup,但 Sub-6A v1 还在原位)
cp data/benchmark/sub6/sub6a_e2e_tasks.jsonl \
   data/benchmark/sub6/sub6a_e2e_tasks_v1.jsonl  # 已存在则跳过

# 2. 同时,Sub-6B v2 已存在 _v2 后缀,但 build_all 会再生成一份
#    sub6b_mammalian_tasks.jsonl(覆盖 v1!)。所以要先 backup v1
cp data/benchmark/sub6/sub6b_mammalian_tasks.jsonl \
   data/benchmark/sub6/sub6b_mammalian_tasks_v1_backup_p2.jsonl

cp data/benchmark/sub6/curated_hmdb_mammalian.jsonl \
   data/benchmark/sub6/curated_hmdb_mammalian_v1_backup_p2.jsonl

# 3. 跑(同 D1 命令但 output 改 data/benchmark/sub6/)
PYTHONPATH=. python scripts/build_sub6/build_all.py \
    --hmdb-candidates data/processed/hmdb_candidates_npc_classified_v2.jsonl \
    --target-6b-mammalian 100 \
    --target-curated-hmdb 250 \
    --pathway-min-compounds 3 \
    --tasks-per-pathway-max 10 \
    --tasks-per-bucket-max 20 \
    --target-6a 40 \
    --spectra-per-compound-min 1 \
    --spectra-per-compound-max 3 \
    --min-compounds-with-spectra 3 \
    --output-dir data/benchmark/sub6/ \
    --report-path reports/benchmark/sub6a_v2_construction_audit_raw.md \
    --seed 42

# 4. rename 输出为 _v2 后缀
mv data/benchmark/sub6/sub6a_e2e_tasks.jsonl \
   data/benchmark/sub6/sub6a_e2e_tasks_v2.jsonl

# 5. Sub-6B v2 已经存在,新生成的覆盖了 v1。检查是否一致
diff <(sort data/benchmark/sub6/sub6b_mammalian_tasks.jsonl) \
     <(sort data/benchmark/sub6/sub6b_mammalian_tasks_v2.jsonl) | head
# 应该完全相同(同种子同参数)。如果不同,escalate

# 6. 恢复 v1 原名
cp data/benchmark/sub6/sub6b_mammalian_tasks_v1_backup_p2.jsonl \
   data/benchmark/sub6/sub6b_mammalian_tasks.jsonl
cp data/benchmark/sub6/curated_hmdb_mammalian_v1_backup_p2.jsonl \
   data/benchmark/sub6/curated_hmdb_mammalian.jsonl
cp data/benchmark/sub6/sub6a_e2e_tasks_v1.jsonl \
   data/benchmark/sub6/sub6a_e2e_tasks.jsonl

# 7. 删除临时 backup
rm data/benchmark/sub6/sub6b_mammalian_tasks_v1_backup_p2.jsonl
rm data/benchmark/sub6/curated_hmdb_mammalian_v1_backup_p2.jsonl
```

### D3 — Audit report `reports/benchmark/sub6a_v2_construction_audit.md`

#### 1. Summary
| metric | v1 | v2 |
|---|---:|---:|
| Sub-6A tasks | 14 | ? |
| total spectra | ? | ? |
| spectra/task mean | ? | ? |
| spectra/task min | ? | ? |
| HMDB compounds covered | ? | ? |

#### 2. Spectrum source breakdown
| source | n_spectra | n_compounds_covered |
|---|---:|---:|
| GNPS | ? | ? |
| MassBank-non-RIKEN | ? | ? |

#### 3. Per-task spectrum count distribution
直方图:1 spec / 2 spec / 3 spec / ... 各多少 task

#### 4. Coverage gaps
- 250 curated 化合物里,多少没找到 spectrum
- 按 bucket 分:central_metabolism 化合物 spectra 覆盖率(关键!Sub-6B v2 central 涨到 10 task,Sub-6A 能不能跟上)

#### 5. NM-002 leakage handling
- spectrum_lookup 是否排除了 RIKEN(看 default contributors)
- source_id 是否带 GNPS 'CCMSLIB' / MassBank 'MSBNK' 前缀
- 下游 Sub-6A orchestrator 用 NM-002 exclusion 时是否需要额外集成(只报告,不实施)

#### 6. Provenance
- git commit + MD5 + wall time + 完整命令

#### 7. Known limitations
- 哪些 bucket Sub-6A 太少(预期 lipid+nucleotide 仍弱)
- spectrum_lookup 跨 ion mode 怎么处理(positive/negative 分开?)

### D4 — Acceptance check

```
□ data/benchmark/sub6/sub6a_e2e_tasks_v2.jsonl 存在,行数 ≥ 25
□ data/benchmark/sub6/sub6a_e2e_tasks.jsonl 仍是 v1(14 行,内容未动)
□ data/benchmark/sub6/sub6b_mammalian_tasks.jsonl 仍是 v1(20 行)
□ data/benchmark/sub6/sub6b_mammalian_tasks_v2.jsonl 存在,63 行(未变)
□ data/benchmark/sub6/curated_hmdb_mammalian_v2.jsonl 存在,250 行(未变)
□ audit report 完整
□ 每 task 至少 3 compounds with spectra (--min-compounds-with-spectra=3)
```

如果 N < 25,接受为 v2 ceiling 但在 audit limitation 写明(不 escalate,Sub-6A 数据稀缺是已知 limitation)。

---

## Pitfalls to avoid

1. **GNPS MGF 加载慢且占内存**(2.5GB 文件,内存峰值可能 4-6GB)。第一次加载 ~5-10 分钟。OOM 就 escalate。

2. **Sub-6B 重生成必须跟 v2 一致**(同种子同参数应该 deterministic)。不一致说明 build_all 不是 deterministic,是 bug。

3. **不要修 spectrum_lookup 的 default contributors 列表**(RIKEN 排除是设计意图,改了破坏 NM-002)。

4. **不要 commit 大数据文件**(_v2.jsonl 可能几 MB)。

5. **`--target-6a 40` 是上限**,实际可能 < 40(取决于 spectrum coverage)。N=15-25 都接受。

---

## Time budget

- D1 smoke: 15-20 分钟
- D2 full: 30-60 分钟
- D3 audit: 30 分钟
- D4: 5 分钟

总:1.5-2 小时。GNPS 加载慢可拖到半天。

---

## First action checklist

第一回合:
1. 读 5 个 background 文件
2. 报告 spectrum_lookup default contributors
3. 报告 Sub-6A v1 的 spectra/task 分布(平均、max、min)
4. 报告 sub6b_mammalian_tasks_v2.jsonl 第一条 task 的 ground_truth_signal_compounds 是哪些 KEGG ID
5. 估算 Sub-6A v2 N 的范围(基于 14×250/150 ≈ 23,但 GNPS 覆盖未知,可能更多)
6. 任何 clarifying question

不要写代码直到 confirm。

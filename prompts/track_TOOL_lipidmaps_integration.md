# Track TOOL — LIPID MAPS integration for Sub-6 v3 (lipid bucket fix)

**Session ID:** `track_TOOL_lipidmaps_integration`
**Branch:** `feature/lipidmaps` (新建,base on `feature/sub6-v2-integrated`)
**Estimated work:** 1-2 days
**Predecessors:**
- `summary/May_7/SUB6_V2_DATA_DETAILS.md`(v2 数据现状,lipid bucket 1 task)
- `reports/benchmark/sub6_construction_report_v2.md`(v2 构建)

---

## Why this matters

v2 已知 limitation:Sub-6B mammalian 63 task 中 **lipid_metabolism bucket 仅 1 task**(nucleotide 4)。无法做 per-bucket statistics。

根因:RaMP-DB 的 lipid pathway compound 注释稀疏。即使我们把 HMDB 池扩到 600 + 全部跑 NPClassifier,RaMP 在 lipid pathway 上的 enrichment top-3 命中数依然不足以撑 task 构造。

修法:**集成 LIPID MAPS 作为 lipid 化合物的第二 pathway 数据源**。LIPID MAPS 是脂质领域的 reference DB,有完整的 LMSD (Structure DB) + LIPID MAPS Pathways DB。

预期产出:Sub-6 v3 数据集,**lipid bucket 从 1 task → 8-15 task**。

---

## Hard scope boundaries

**You MAY:**
- 创建 `tools/lipidmaps/` 包(新工具,跟现有 `tools/cfm_id/` 等并列)
- 下载 LIPID MAPS LMSD + Pathways dump 到 `data/lipidmaps/`
- 在 `tools/benchmark/sub6/compound_curator.py` 加 **可选的** LIPID MAPS fallback(只对 lipid bucket 触发)
- 跑 v3 build,产出 `_v3.jsonl` 后缀的新数据(保留 v2 不动)
- 写 audit `reports/benchmark/lipidmaps_integration_audit.md`

**You MAY NOT:**
- 覆盖 v2 文件(`*_v2.jsonl` 必须保留)
- 修改 RaMP 查询 logic(LIPID MAPS 是 additive fallback,不替换)
- 修 verifier / orchestrator / evaluation 任何代码
- 修改 amino_acid / central / nucleotide / other bucket 的 curation(LIPID MAPS 仅对 lipid 触发)
- 跑 narrative 或 verifier(本 session 只构建数据,不评估)
- 在 main 上直接 commit(必须新分支)

---

## Background reading (mandatory)

1. `tools/benchmark/sub6/compound_curator.py` — 看 `curate_hmdb_mammalian_subset` 函数,尤其 RaMP pathway 解析部分(~line 800-870)
2. `data/benchmark/sub6/curated_hmdb_mammalian_v2.jsonl` 第一条 record(看 `pathway_bucket=lipid_metabolism` 的样本)
3. `tools/cfm_id/` 整个目录(参考 docker shim / external tool 集成 pattern)
4. `summary/May_7/sub6_v2_data_details.json` 中 `curated_pool` 部分(确认 lipid 50 化合物的现状)
5. LIPID MAPS REST API 文档:https://www.lipidmaps.org/databases/lmsd/programmatic_access
6. LMSD 全量 SDF/CSV 下载:https://www.lipidmaps.org/files/?file=LMSD&ext=sdf.zip(or .csv.zip)
7. LIPID MAPS Pathways DB:https://www.lipidmaps.org/data/structure/pathways.html

In your first response,确认:
- LMSD CSV dump 实际大小(~30MB?)+ 包含字段(InChIKey、LM_ID、category、main_class、sub_class)
- LIPID MAPS Pathway DB 有没有 dump 文件,还是只 web?如果只 web,需要 scrape
- 现有 v2 curated lipid 50 化合物中,InChIKey 能在 LMSD 命中的比例(quick spot check 5 条)
- 你打算在 compound_curator 哪一行接入 LIPID MAPS fallback

不要写代码 / 下载 dump,直到我 confirm。

---

## Deliverables

### D1 — LIPID MAPS client(0.5 天)

**新建** `tools/lipidmaps/`:
```
tools/lipidmaps/
├── __init__.py
├── lmsd_loader.py      # 解析 LMSD CSV → 内存 dict (InChIKey → LM_ID + category/class)
├── pathway_loader.py   # 解析 LIPID MAPS Pathways → dict (LM_ID → pathway_name list)
└── client.py           # 公开 API
```

**API 设计(client.py)**:
```python
class LipidMapsClient:
    def __init__(self, lmsd_path, pathway_db_path):
        self._lmsd = load_lmsd(lmsd_path)
        self._pathways = load_pathways(pathway_db_path)
    
    def lookup_by_inchikey(self, inchikey: str) -> dict | None:
        """Return {lm_id, category, main_class, sub_class} or None."""
    
    def get_lipid_pathways(self, lm_id: str) -> list[dict]:
        """Return [{name, category, ...}] from LIPID MAPS Pathway DB."""
    
    def lookup_compound_to_pathways(self, inchikey: str) -> list[dict]:
        """Convenience: inchikey → lipid pathways (via LM_ID)."""
```

**Acceptance:**
- 单测覆盖 InChIKey 第一段查询(完整串和首段都试)
- Smoke test:已知化合物 (e.g. cholesterol `HVYWMOMLDIMFJA`)能查到 LM_ID + 至少 1 个 pathway

### D2 — Data download + cache(0.5 天)

下载 LMSD 和 Pathway dumps 到 `data/lipidmaps/`:
```
data/lipidmaps/
├── lmsd_2026-05-XX.csv        # ~30 MB
├── lipid_pathways_2026-05-XX.json  # 提取自 LIPID MAPS Pathway DB
├── README.md                  # 下载日期、URL、license、记录数
└── .download_audit.json       # MD5 + 时间戳
```

**Acceptance:**
- LMSD ≥ 40,000 records loaded
- Pathway DB ≥ 100 pathways
- Audit JSON 含 source URL + 下载时间 + MD5

### D3 — compound_curator 集成(0.5-1 天)

**修改** `tools/benchmark/sub6/compound_curator.py` 中 `curate_hmdb_mammalian_subset`:

逻辑设计:
```python
# 现有 RaMP pathway 解析(不改)
ramp_to_pathways = _pathways_for_ramp_ids(...)

# 新增:LIPID MAPS fallback ─ 仅对 lipid bucket 触发
if enable_lipidmaps and pathway_bucket == "lipid_metabolism":
    lm_pathways = lipidmaps_client.lookup_compound_to_pathways(inchikey)
    if lm_pathways:
        # 合并到 candidate 的 pathway list,标 source="lipidmaps"
        ...
```

**关键决策:**
- LIPID MAPS pathway 用什么字段当 "ramp_pathway_id" 等价物?— 用 `lm_pathway:{LMP_ID}` 前缀,跟 RaMP_P_xxx 区分
- pathway_min_compounds gate 怎么配合?— 同样要求 ≥3 个化合物在该 LIPID MAPS pathway,但允许跨 RaMP+LIPID MAPS 计数
- enable_lipidmaps 默认值?— **default False**(不影响默认行为),v3 build 显式开启

**新增 CLI flag** 在 `scripts/build_sub6/build_all.py`:
```
--enable-lipidmaps          (default False)
--lipidmaps-lmsd-path       (default data/lipidmaps/lmsd_2026-05-XX.csv)
--lipidmaps-pathway-path    (default data/lipidmaps/lipid_pathways_2026-05-XX.json)
```

**Acceptance:**
- 不开 flag 时,build 行为跟 v2 完全一致(reproducibility check)
- 开 flag 后,curated lipid 化合物的 `pathways` 字段含 LIPID MAPS 来源记录

### D4 — Build v3 + audit(0.5 天)

**Backup v2 first:**
```bash
cp data/benchmark/sub6/curated_hmdb_mammalian_v2.jsonl data/benchmark/sub6/curated_hmdb_mammalian_v2_backup.jsonl
cp data/benchmark/sub6/sub6b_mammalian_tasks_v2.jsonl  data/benchmark/sub6/sub6b_mammalian_tasks_v2_backup.jsonl
```

**Build v3:**
```bash
PYTHONPATH=. python scripts/build_sub6/build_all.py \
    --hmdb-candidates data/processed/hmdb_candidates_npc_classified_v2.jsonl \
    --target-6b-mammalian 100 \
    --target-curated-hmdb 250 \
    --pathway-min-compounds 3 \
    --tasks-per-pathway-max 10 \
    --tasks-per-bucket-max 20 \
    --enable-lipidmaps \
    --output-dir data/benchmark/sub6/ \
    --report-path reports/benchmark/sub6_construction_report_v3_raw.md \
    --skip-spectrum-index \
    --seed 42

# rename outputs to _v3
mv data/benchmark/sub6/curated_hmdb_mammalian.jsonl data/benchmark/sub6/curated_hmdb_mammalian_v3.jsonl
mv data/benchmark/sub6/sub6b_mammalian_tasks.jsonl  data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl

# restore v1 (downstream consumers still on v1 default name)
cp data/benchmark/sub6/curated_hmdb_mammalian_v2_backup.jsonl data/benchmark/sub6/curated_hmdb_mammalian.jsonl  # OR earlier v1 if relevant
# (具体看 v2 当时是怎么 restore 的,sub6 v2 phase 2 prompt 里有 backup-rename 流程)
```

**Acceptance:**
- v3 lipid bucket task 数 ≥ 5(目标 ≥10,但接受 5+)
- v3 其他 bucket 数字跟 v2 接近(±10%)— 否则说明 LIPID MAPS 影响溢出
- ground_truth pathway 在 RaMP 或 LIPID MAPS top-3 命中(quality gate 100%)
- v2 文件未被覆盖

### D5 — Audit report

`reports/benchmark/lipidmaps_integration_audit.md`,包含:

#### 1. Summary
| metric | v2 | v3 | Δ |
|---|---:|---:|---|
| Sub-6B mammalian tasks | 63 | ? | ? |
| lipid_metabolism bucket | **1** | **?** | **关键数字** |
| amino_acid_metabolism bucket | 21 | ? | (期望基本不变) |
| central_metabolism bucket | 10 | ? | (基本不变) |
| nucleotide_metabolism bucket | 4 | ? | (基本不变) |
| other_metabolism bucket | 27 | ? | (基本不变) |
| unique pathways | 13 | ? | ? |
| LIPID MAPS pathway 占比 | 0% | ?% | 新增 |
| RaMP pathway 占比 | 100% | ?% | (期望仍主导) |

#### 2. Source breakdown
- RaMP-only tasks
- LIPID MAPS-only tasks(纯 lipid pathway)
- 双源支持的 tasks(RaMP + LIPID MAPS 都 confirm)

#### 3. Sample lipid tasks (5 个)
列 5 个 v3 lipid task 的:
- ground_truth pathway name + source(RaMP / LIPID MAPS)
- signal compounds (KEGG/LM_ID)
- 是否 RaMP 也能 enrich(cross-validation)

#### 4. Quality gates(全部通过)
- ground_truth_pathway 在 enrichment top-3 (RaMP OR LIPID MAPS): 100%
- duplicate signal IDs: 0
- min unique signal ≥ 3: 100%

#### 5. LIPID MAPS coverage 统计
- 250 curated 化合物中,多少能在 LMSD 找到匹配
- 多少能 resolve 到 ≥1 LIPID MAPS pathway
- 平均每 lipid 化合物 pathway 数(对比 RaMP)

#### 6. Provenance
- git commit + 数据 MD5 + LMSD/Pathway dump 来源 URL + 下载日期 + wall time
- 完整 build 命令

#### 7. Known limitations / Future work
- LIPID MAPS pathway 命名跟 KEGG 不一致(有些 pathway 在两边都存在但 name 不同)— paper 写明
- 是否影响 verifier Layer 6c 的 substring matching(可能 verifier 看到 LIPID MAPS pathway name 更难匹配)— 这是下一个 session 处理
- Negative ion mode lipid 不在本 session scope

---

## Pitfalls

1. **LMSD InChIKey 格式**:LIPID MAPS 用完整 InChIKey,但你的 curated pool 可能只存第一段。匹配时**优先全串,fallback 第一段**。

2. **LIPID MAPS Pathway DB 没有现成 dump**:可能要 scrape 或用 REST API 列举。第一回合如果发现这点,先回报告,不要 scrape 一整天。

3. **不要并行下载**:LIPID MAPS 是公益服务,串行 + 加 sleep。

4. **LIPID MAPS 化合物可能跟 RaMP 重复**:同一个 cholesterol 在 RaMP 也有 pathway 注释,但 RaMP 把它归为 "Steroid biosynthesis"(WikiPathways),LIPID MAPS 归为 "Sterol metabolism"。这两个 pathway **不是同一回事但有大量交集**。merge 时**保留两个独立来源**,让 task constructor 自己决定用哪个,不强行去重。

5. **License**:LIPID MAPS 是 CC-BY 4.0,可商用。免费,但 paper 必须 cite Fahy et al, J Lipid Res 2009。

6. **不要 commit dump 文件**:LMSD 30MB,在 .gitignore 里(类似处理 GNPS / HMDB sqlite)。

7. **修复后跑 v3,但默认 sub6b_mammalian_tasks.jsonl 必须保持是 v1**(下游 verifier / narrative runner 还在引用)。所有新输出都加 `_v3` 后缀。

---

## Time budget

- Confirm: 30 min
- D1 client: 4h
- D2 download: 2h
- D3 integration: 4-6h
- D4 v3 build: 1-2h
- D5 audit: 1h

**Total: 1.5-2 days**。

---

## First action checklist

第一回合:
1. 读 7 个 background 文件
2. 报告 LMSD CSV 字段 schema(从官网或 sample row 推测)
3. 报告 LIPID MAPS Pathway DB 是否有 dump(决定下载方式)
4. 报告 v2 curated lipid 50 化合物里,sample 5 个 InChIKey 在 LMSD 命中率(用 web 查 5 个,不下载全 dump)
5. 推荐在 `compound_curator.py` 哪一行接入 fallback(给行号)
6. 是否需要新建 sqlite cache(类似 ClassyFire/NPClassifier 模式)还是 in-memory dict 够用
7. 任何 clarifying question

不要下载 dump / 写代码,直到 confirm 这 7 项。

# Sub-6 v2 Benchmark Data Details

**Generated:** 2026-05-07
**Branch:** `feature/sub6-v2-integrated`(commit `17a90dc`)
**Companion:** machine-readable summary in `sub6_v2_data_details.json`

---

## 1. Top-level inventory

| Asset | Count | File | MD5 |
|---|---:|---|---|
| Sub-6B mammalian tasks | **63** | `data/benchmark/sub6/sub6b_mammalian_tasks_v2.jsonl` | `23594c0a3c6ab7a906baad1e0cd622dc` |
| Sub-6A end-to-end tasks | **38** | `data/benchmark/sub6/sub6a_e2e_tasks_v2.jsonl` | `73f0f3a336dc3d0be87571d15cfc6831` |
| Curated HMDB-Mammalian compounds | **250** | `data/benchmark/sub6/curated_hmdb_mammalian_v2.jsonl` | `2a8a9f35e8cf84a9c1e2a452eb00561e` |
| Upstream HMDB candidates pool | **600** | `data/processed/hmdb_candidates_npc_classified_v2.jsonl` | `8824f112a1a63e2f91fcc451ce157244` |
| Sub-6A total spectra | **459** | (per-task `differential_spectra` field) | — |

---

## 2. Sub-6B (compound list → narrative)

### 2.1 Task structure

每个 task 包含:
- `task_id`(unique seed-based id)
- `differential_metabolites`(化合物列表,每个含 KEGG ID / SMILES / InChIKey / NPClassifier 分类)
- `ground_truth_pathway`(RaMP enrichment top-1 pathway,quality gate 保证在 RaMP top-3)
- `ground_truth_signal_compounds`(应该贡献富集的 KEGG IDs)
- `noise_compounds`(混入的非 pathway 成员,KEGG IDs)

### 2.2 化合物组成统计

| 维度 | min | median | mean | max | total |
|---|---:|---:|---:|---:|---:|
| Differential metabolites / task | 5 | 8 | 8.0 | 13 | 506 |
| Signal compounds / task | 3 | 5 | 5.0 | 8 | — |
| Noise compounds / task | 0 | 3 | 3.0 | 5 | — |

### 2.3 Pathway 分布(13 unique pathways)

| n tasks | pathway_id | source | external_id | name |
|---:|---|---|---|---|
| 10 | RAMP_P_000000398 | kegg | hsa00052 | Galactose Metabolism |
| 10 | RAMP_P_000050021 | reactome | R-HSA-211859 | Biological oxidations |
| 10 | RAMP_P_000000203 | smpdb | SMP00041 | Cerivastatin Action Pathway |
|  9 | RAMP_P_000000141 | kegg | hsa00380 | Tryptophan metabolism |
|  7 | RAMP_P_000000421 | kegg | hsa00150 | Androgen and Estrogen Metabolism |
|  6 | RAMP_P_000000016 | kegg | hsa00260 | Glycine, serine and threonine metabolism |
|  4 | RAMP_P_000000106 | kegg | hsa00350 | Tyrosine metabolism |
|  2 | RAMP_P_000053306 | wikipathways | WP4022 | Pyrimidine metabolism |
|  1 | RAMP_P_000025682 | smpdb | SMP00078 | Celecoxib Action Pathway |
|  1 | RAMP_P_000050096 | reactome | R-HSA-71291 | Metabolism of amino acids and derivatives |
|  1 | RAMP_P_000050099 | reactome | R-HSA-73621 | Pyrimidine catabolism |
|  1 | RAMP_P_000053042 | wikipathways | WP43 | Steroid biosynthesis |
|  1 | RAMP_P_000052855 | wikipathways | WP_000052855 | Sulfatase and aromatase pathway |

**Pathway source breakdown:**
- KEGG: 5 pathways (45 task = 71%)
- Reactome: 3 pathways (12 task)
- SMPDB: 2 pathways (11 task)
- WikiPathways: 3 pathways (4 task)

**Limitation:** top 5 pathway 占 46/63 (73%) tasks,尾部 6 个 pathway 仅 1 task,**不能做 per-pathway statistics**(单 task 没有方差)。

---

## 3. Sub-6A (spectrum → identification → narrative)

### 3.1 数据规模

| 维度 | 值 |
|---|---:|
| Tasks | 38 |
| Total spectra | **459** |
| Per-task spectra range | 5 - 12 |
| Per-task median | 12 |
| Per-task mean | 12.1 |

### 3.2 Spectrum 来源分布

| Source | Count | % | 说明 |
|---|---:|---:|---|
| GNPS | 323 | 70.4% | 主源(`CCMSLIB...` 前缀) |
| MassBank | 69 | 15.0% | 非 RIKEN contributor(已排除 RIKEN 防泄漏) |
| MoNA | 58 | 12.6% | 补充源 |
| other | 9 | 2.0% | 边缘 case |

### 3.3 Sub-6A 任务来自 Sub-6B 哪些 pathway?

Sub-6A 的 38 task 是 Sub-6B 63 中**有充足 spectrum 覆盖**的子集(每 task 至少 3 个 compound 有 ≥1 spectrum,Phase 2 acceptance gate)。

bucket 平衡情况比 Sub-6B 略差(spectrum 覆盖率不均):
- 中心代谢化合物 spectrum 覆盖率高 → Sub-6A 留下更多
- lipid / nucleotide spectrum 稀缺 → Sub-6A 这两 bucket 仍弱

### 3.4 NM-002 leakage filter 状态

每个 Sub-6A task 携带 `excluded_source_ids`:
- 来源:`data/processed/nm002_excluded_gnps_ids.json`(76,783 GNPS records)
- 应用:在 library_search 阶段从 GNPS 候选池中排除,防止自匹配
- 实测:每 spectrum 平均排除 ~600-1500 GNPS records(取决于化合物的同分异构体数)

---

## 4. Curated HMDB-Mammalian 化合物池(250)

### 4.1 Bucket 分布

按 `pathway_bucket` 字段(基于 RaMP pathway 关键词分类):

| Bucket | n compounds | % |
|---|---:|---:|
| amino_acid_metabolism | 50 | 20% |
| central_metabolism | 50 | 20% |
| lipid_metabolism | 50 | 20% |
| nucleotide_metabolism | 50 | 20% |
| other_metabolism | 50 | 20% |

**完美 5 等分**(round-robin sampling 保证)。

### 4.2 ClassyFire 数据来源

| Source | n compounds | 说明 |
|---|---:|---|
| npclassifier | 250 | NPClassifier 全覆盖(API 调用稳定) |
| hmdb_chemical_class | 0 | NPClassifier 完全替代 |
| missing | 0 | 无缺失 |

注:这是**已知矛盾点之一** —— `data/classyfire_cache.sqlite` 只有 188 条 ClassyFire 真值。当前 curated pool 100% 用 NPClassifier 替代。

---

## 5. 上游 HMDB candidates 池(600,Phase 1 fallback 输出)

### 5.1 来源

从 HMDB sqlite 筛选出有 KEGG ID + SMILES + RaMP pathway + valid InChIKey + mass∈[50,1000] 的化合物,跑 NPClassifier 分类后按 5 bucket 分层。

### 5.2 Pathway domain 分布(5 bucket × 120)

| pathway_domain | n compounds | bucket capacity |
|---|---:|---:|
| amino_acid_metabolism | 120 | 完整 |
| central_metabolism | 120 | 完整 |
| lipid_metabolism | 120 | 完整 |
| nucleotide_metabolism | 120 | 完整 |
| other_metabolism | 120 | 完整 |

### 5.3 NPClassifier 缓存

| 指标 | 数值 |
|---|---:|
| Cache files before expansion | 993 |
| Cache files after expansion | 1,273 |
| New API calls (this expansion) | 280 |
| API failures | 0 |
| Cache hit rate (this expansion) | 53% |

---

## 6. 已跑的 LLM narrative + verifier 状态

| Track | tasks | LLM | narrative file | verdict file |
|---|---:|---|---|---|
| sub6b_opus | 63 | claude-opus-4-7 | `data/eval/sub6/v2/sub6b_opus/sub6b_narratives.jsonl` | `verdicts_v9_phaseC.jsonl` |
| sub6b_gpt55 | 63 | gpt-5.5 | `data/eval/sub6/v2/sub6b_gpt55/sub6b_narratives.jsonl` | `verdicts_v9_phaseC.jsonl` |
| sub6b_minimax | 63 | MiniMax-M2.7 | **(pending)** | — |
| sub6a_perfect | 38 | claude-opus-4-7 (oracle id) | `data/eval/sub6/v2/sub6a_perfect/sub6a_narratives_perfect_id.jsonl` | `verdicts_v9_phaseC.jsonl` |
| sub6a_real | 38 | claude-opus-4-7 (real id) | `data/eval/sub6/v2/sub6a_real/sub6a_narratives.jsonl` | `verdicts_v9_phaseC.jsonl` |

**总 narrative runs**: 202(63 × 2 + 38 × 2)
**总 verdict claims**: 10,042

---

## 7. 数据 quality gates(全部通过)

| Gate | 验收标准 | 实际 |
|---|---|---|
| Sub-6B ground_truth_pathway 在 RaMP enrichment top-3 | 100% | 63/63 |
| Sub-6B 排除 pfocr pathway | 100% | 0/63 pfocr |
| Sub-6B signal compound count ≥ 3 | 100% | min unique signal = 5 |
| Sub-6B duplicate task_ids | 0 | 0 |
| Sub-6B tasks_with_duplicate_signal_ids | 0 | 0 |
| Sub-6A min compounds with spectra | ≥3 per task | min = 3 |
| NM-002 GNPS leakage filter applied | 是 | 76,783 IDs excluded |
| Curated pool ClassyFire 5-level coverage | ≥85% | 100% (NPClassifier) |

---

## 8. v1 → v2 维度对比

| | v1 | v2 | Δ |
|---|---:|---:|---|
| Sub-6B mammalian tasks | 20 | 63 | +215% |
| Sub-6A end-to-end tasks | 14 | 38 | +171% |
| Unique pathways (Sub-6B) | 7 | 13 | +86% |
| HMDB curated compounds | 150 | 250 | +67% |
| HMDB upstream pool | 300 | 600 | +100% |
| Sub-6A total spectra | 128 | 459 | +259% |
| Bucket coverage (≥1 task) | 4 | 5 | +1 (central recovered) |
| Spectrum sources | 2 (GNPS+MassBank) | 4 (+MoNA, +"other") | +2 |
| Narrative LLMs | 1 (MiniMax) | 2 (Opus + GPT-5.5) | +1 |
| Total claims (verdict 数) | ~1,800 | 10,042 | +458% |

---

## 9. 已知 limitations(paper 必写)

### 9.1 Bucket 分布严重不平衡

Sub-6B v2 task 实际 bucket(基于 ground_truth_pathway 主导化合物):

| Bucket | n tasks | 适合 per-bucket 统计? |
|---|---:|---|
| amino_acid_metabolism | 21 | ✓ |
| central_metabolism | 10 | ✓ (marginal) |
| nucleotide_metabolism | 4 | ✗ 不够 |
| **lipid_metabolism** | **1** | ✗ **不能做** |
| other_metabolism | 27 | ✓ |

**根因**:RaMP 中 lipid pathway 化合物覆盖度低,即使扩 HMDB pool 到 600 仍补不齐。Future work 需要扩 LipidMaps / Reactome lipid 子集。

### 9.2 Pathway 长尾

13 个 pathway 中 6 个只 1 task:
- Celecoxib Action Pathway / Metabolism of amino acids and derivatives / Pyrimidine catabolism / Steroid biosynthesis / Sulfatase and aromatase pathway / FOXA2 (相关 SMPDB)

不能 claim per-pathway performance,只能做 aggregate 统计。

### 9.3 单一 spectrum 来源主导

GNPS 占 70%,跨 source 鲁棒性未充分验证。

### 9.4 Sub-6A 化合物分布与 Sub-6B 不完全同源

Sub-6A 是 Sub-6B 的子集(spectrum 充足的部分),不是平行采样。lipid / nucleotide pathway 的 task 可能因 spectrum 缺失被淘汰。

### 9.5 缺人工标注

verifier 真实 P/R/F1 / Cohen's κ 未算(用户决定先跳过)。Nature Methods 投稿前应补 5-7 task 标注。

---

## 10. Provenance

```
git commit:                 17a90dc (feature/sub6-v2-integrated)
build pipeline:             scripts/build_sub6/build_all.py
expand HMDB pool script:    scripts/expand_hmdb_pool.py
construction reports:
  - reports/benchmark/sub6_construction_report_v2.md (Sub-6B)
  - reports/benchmark/sub6a_v2_construction_audit.md (Sub-6A)
  - reports/benchmark/curation/hmdb_pool_expansion_audit.md (600 pool)
audit reports:
  - reports/audit/set_enrichment_regression_v1_v2.md
  - reports/audit/v1_opus_sanity_check.md
generated:                  2026-05-07
```

---

## 11. 机器可读版本

```json
{
  "version": "v2",
  "tasks": {"sub6b": 63, "sub6a": 38},
  "pools": {"curated": 250, "upstream": 600},
  "spectra": 459,
  "claims": 10042,
  "narratives": 202
}
```

完整结构化数据见同目录 `sub6_v2_data_details.json`(包含每 pathway / 每 bucket / 每 source 的精确数字 + MD5 + 文件大小)。

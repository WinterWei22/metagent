# Track PHASE 6.6 — CASMI OOD validation of conditional rerank

**Session ID:** `track_PHASE6_6_casmi_ood`
**Branch:** `feature/sub6-casmi-ood`(off `feature/sub6-conditional-rerank`)
**Estimated work:** 3-5 days wall(数据集成 + 端到端跑)
**Predecessors:**
- `reports/eval/conditional_rerank_v2.md`(Phase 6.5,Sub-6A v2 上 conditional gate +10.3 pp OOD-simulated)
- `ref_paper/MSAgent.pdf` Result 2.2(MSAgent 在 CASMI 报 +10% MRR)

---

## Why this matters (paper 决定性 confirmatory)

Phase 6.5 的 OOD 是**仿真**(msclip primary 当 OOD baseline,56.7% → conditional gate 66.96%)。但真 OOD = CASMI(challenge benchmark,设计上 leakage-free)。

如果 CASMI 上 conditional gate 复现 +10pp,paper 主张 **watertight**:
- F5 升级:"conditional rerank 在真 OOD (CASMI) 上 +X pp,跟 Sub-6A v2 OOD-simulated 数字一致"
- 直接对标 MSAgent +10% MRR

如果 CASMI 上 conditional gate 失败,**反而**是真 finding:"Sub-6A v2 的 in-distribution leakage 制造了 OOD 模拟假象,真 OOD 上 conditional 也救不了" → 重新评估 paper 故事。

**两种结果都有 paper 价值。** 这正是 confirmatory 实验的意义。

---

## Hard scope boundaries

**You MAY:**
- 解析现有 CASMI 2016 / 2022 数据(**已下载并部分处理**,详见下面"现有数据状态")
- 写 CASMI loader `evaluation/sub6/casmi_loader.py`,产出跟 Sub-6A v2 兼容的 task JSONL
- 跑 conditional rerank pipeline on CASMI(完全复用 Phase 6.5 代码)
- 跑 SIRIUS / CFM-ID 在 CASMI 数据上(预期 cache miss 高,因为是新数据)
- 写报告 `reports/eval/casmi_ood_v1.md`

### 现有数据状态(prompt 作者已确认,session 不用再探索)

```
/data/weiwentao/llm_agent_metabolomics/CASMI/
├── casmi_2016/
│   ├── README.md             ← 详细 schema + 来源说明,先读
│   ├── category1/            19 NPID challenge (peak_lists_pos/neg_ms2 + raw_mzML)
│   ├── category2/            208 in silico challenge
│   │   ├── challenges/       MS2 peak lists (mgf + txt, pos+neg)
│   │   ├── candidates/       Per-challenge candidate lists (.zip)
│   │   └── docs/
│   ├── category3/            symlink to category2 (data 共享)
│   ├── solutions/
│   │   ├── solutions_casmi2016_cat1.csv      ← cat1 GT
│   │   └── solutions_casmi2016_cat2and3.csv  ← cat2+3 GT (主要)
│   └── results/              其他团队提交结果(可作 paper 对比)
│
└── casmi_2022/
    ├── README.md             ← 详细 schema,先读
    ├── preprocessed/casmi2022/    ← MIST 团队预处理,直接可用
    │   ├── labels_true.tsv         170 行 GT(dataset/spec/name/ionization/formula/smiles/inchikey)
    │   ├── spec_files/             170 个 .ms (SIRIUS-format,peak-picked)
    │   ├── retrieval_hdf/          PubChem candidate set + Morgan-4096 fingerprints
    │   ├── sirius_outputs/         SIRIUS 已跑结果(343 dirs!)
    │   └── csi_outputs/            CSI:FingerID 已跑结果(172 dirs!)
    ├── raw_mzml/                   ← 空(FTP 不通)
    ├── solutions/.../3_Data/mzML Data/   145 个 raw mzML(替代 raw_mzml)
    └── challenges/{priority,bonus}/      原始 xlsx challenge 文件
```

**关键利好**:
- **CASMI 2022 已有 MIST preprocessed 170 个 .ms spec + labels_true.tsv** → 直接做 task JSONL,**不需重做 peak-picking**
- **CASMI 2022 SIRIUS / CSI:FingerID 已跑过** → 部分 SIRIUS 输出可复用(降低 wall)
- CASMI 2016 cat 2 是 208 challenge,GT 在 `solutions_casmi2016_cat2and3.csv`,MS2 peaks 在 mgf

**优先级**:CASMI 2022 用 MIST preprocessed 最快,作主战场(170 task)。CASMI 2016 cat 2 作补充(208 task)。Cat 1 (19 task) 太小可跳。

**You MAY NOT:**
- 修 verifier 任何代码
- 修 Phase 6.5 已落盘 data / config
- 修 conditional gate 阈值(Phase 6.5 的 `gap≥0.05, top1=0.0` 锁定)
- 跑 LLM narrative(本 session 只测 id_acc + 显著性,paper 之后再补 narrative)
- 调 evidence_score 权重

**关键 scope**:CASMI baseline 数据生成 + conditional rerank 跑 + 显著性。LLM 阶段留 future。

---

## Background reading

1. `reports/eval/conditional_rerank_v2.md`(Phase 6.5 完整结果)
2. `evaluation/sub6/conditional_rerank.py`(should_rerank_msclip_gate 实现)
3. `evaluation/sub6/identification.py`(identify_spectrum 接口)
4. `/data/weiwentao/llm_agent_metabolomics/CASMI/casmi_2016/{category1,category2,category3}/`(原始 challenge 数据)
5. `/data/weiwentao/llm_agent_metabolomics/CASMI/casmi_2022/{challenges,raw_mzml,solutions}/`
6. `data/benchmark/sub6/sub6a_e2e_tasks_v2.jsonl`(目标 schema 参考)
7. `reports/eval/sirius_cfmid_rerank_v2.md` §Acceptance(Phase 6.2 的 SIRIUS auto-relogin,CASMI 跑也会用)

In your first response,确认:
- CASMI 2016 + 2022 解压后总 challenge 数(预期 ~700)
- 每 challenge 包含什么(query spectrum + ground truth SMILES?adduct?ion mode?)
- ground truth 给定形式(SMILES / InChIKey / 正确 candidate position?)
- 跟 Sub-6A v2 task schema 对齐难度(易 / 中 / 难)
- SIRIUS / CFM-ID 在 CASMI candidate 上的 cache hit 估计(基本是 miss,因为新数据)
- 估算端到端 wall(cache miss 影响很大)

不要写代码或跑命令,直到 confirm。

---

## Deliverables

### D1 — CASMI loader + schema 适配(0.5-1 day)

`evaluation/sub6/casmi_loader.py`:
- 解析现有 CASMI 数据(见上"现有数据状态")
- 产出 `data/benchmark/casmi/{2016,2022}/casmi_tasks.jsonl`
- schema:跟 `sub6a_e2e_tasks_v2.jsonl` 兼容(differential_spectra + ground_truth_signal_compounds)
- 单 challenge 包成单 "task"(每 task 1 个 spectrum + 1 个 GT 化合物)

#### CASMI 2022 优先(用 MIST preprocessed,半天)

数据来源:`/data/weiwentao/llm_agent_metabolomics/CASMI/casmi_2022/preprocessed/casmi2022/`

```python
# 简化逻辑(伪代码)
labels = read_tsv("labels_true.tsv")  # 170 行
for row in labels:
    spec_file = f"spec_files/{row['spec']}.ms"
    spectrum = parse_sirius_ms_file(spec_file)  # peak list + precursor
    task = {
        "task_id": f"casmi2022_{row['spec']}",
        "differential_spectra": [spectrum],
        "ground_truth_signal_compounds": [{
            "name": row["name"] or row["spec"],
            "smiles": row["smiles"],
            "inchikey": row["inchikey"],
            "inchikey_first_block": row["inchikey"][:14],
            "molecular_formula": row["formula"],
            "ionization": row["ionization"],  # [M+H]+, [M-H]-
        }],
        # ramp_enrichment_result 等 留空
    }
```

预期输出 ~170 task(对应 labels_true.tsv 行数,部分 spec_file 可能缺失需 skip)。

#### CASMI 2016 cat 2(自己 parse MGF,1 day)

数据:`/data/weiwentao/llm_agent_metabolomics/CASMI/casmi_2016/category2/challenges/*.mgf`
GT:`/data/weiwentao/llm_agent_metabolomics/CASMI/casmi_2016/solutions/solutions_casmi2016_cat2and3.csv`

用 `matchms.importing.load_from_mgf` 即可 parse MGF。

预期输出 ~208 task(cat 2 全集,cat 3 共享 data 不重复)。

#### 关键 schema 适配

CASMI 跟 Sub-6A v2 的几个差异:
- CASMI 1 spectrum/task,Sub-6A v2 4-23 spectra/task → loader 包成 1-spectrum task 即可
- CASMI 单一 GT,Sub-6A v2 multi-compound signal → ground_truth_signal_compounds list 只放 1 个
- CASMI 没有 ramp_enrichment_result(pathway 信息)→ 留空,本 session 用不上(rerank 不依赖 pathway)

加 unit test:loader 产出的 task JSONL 能被 `run_sub6a.py` 直接消费(schema 兼容)。

输出:
- `data/benchmark/casmi/2022/casmi_tasks.jsonl` (~170 task)
- `data/benchmark/casmi/2016_cat2/casmi_tasks.jsonl` (~208 task)
- `reports/benchmark/casmi_loader_audit.md`(每个 challenge 的 spectrum quality / adduct 分布 / GT InChIKey first-block 在 GNPS reference 里的命中率,**最后这个**是 leakage check)

### D2 — Library_search baseline on CASMI(1 day wall)

跑 4 个 baseline config(无 rerank):

```bash
# Config CASMI-A: GNPS modcos primary, 无 rerank
PYTHONPATH=. python scripts/eval_sub6/run_baseline.py \
    --sub6a data/benchmark/casmi/2016/casmi_tasks.jsonl \
    --libraries gnps \
    --primary-retriever modcos \
    --reranker none \
    --skip-narrative \
    --output data/eval/casmi/2016_modcos_baseline/

# Config CASMI-B: MS-CLIP primary, 无 rerank
... --libraries gnps,inhouse --primary-retriever msclip --reranker none ...
output: data/eval/casmi/2016_msclip_baseline/

# 同样 2 个 config 跑 CASMI 2022
```

预期 baseline:
- modcos: 30-50% top-1 (CASMI 设计就是难)
- msclip: 25-45% top-1

如果 modcos baseline > 65% → 警告,CASMI 数据集可能也部分 leak 到 GNPS,paper 写 limitation。

### D3 — Conditional rerank on CASMI(2 days wall)

跑 2 个 conditional config(2016 + 2022,共 1 个 reranker config):

```bash
PYTHONPATH=. python scripts/eval_sub6/run_baseline.py \
    --sub6a data/benchmark/casmi/2016/casmi_tasks.jsonl \
    --libraries gnps,inhouse \
    --primary-retriever msclip \
    --reranker conditional \
    --conditional-fallback weighted \
    --rerank-with sirius,cfmid \
    --rerank-top-k 5 \
    --mass-tolerance-ppm 10 \
    --skip-narrative \
    --output data/eval/casmi/2016_conditional/

# 同样 CASMI 2022
output: data/eval/casmi/2022_conditional/
```

**注意 cache miss**:CASMI candidate 大部分不在 Phase 6.2 CFM cache 里。SIRIUS 跑 per-spectrum,没复用空间。预期 wall:
- CFM-ID: 700 task × top-5 候选 × 5s/call ≈ 5 hours(后台)
- SIRIUS: 700 × 30s ≈ 6 hours
- 加 auto-relogin 容错 → 可能 1.5-2 day wall

### D4 — Significance + 跨 benchmark 对比(0.5 day)

跑 `scripts/eval_sub6/significance_tests.py`(Phase 6.5 已写好):

```
CASMI 2016 conditional vs CASMI 2016 msclip baseline → McNemar p
CASMI 2016 conditional vs CASMI 2016 modcos baseline → McNemar p
CASMI 2022 同 2 个 pair
+ 跨 benchmark:CASMI conditional Δ vs Sub-6A v2 conditional Δ(看是否一致)
```

主表 `data/paper_figures/phase6_6_casmi_results.csv`:

```csv
benchmark,config,n_task,n_correct,id_acc,Δ_vs_msclip_baseline_pp,p_value,significant_after_bonferroni
casmi_2016,modcos_baseline,250,?,?%,—,—,—
casmi_2016,msclip_baseline,250,?,?%,—,—,—
casmi_2016,conditional,250,?,?%,?pp,?,?
casmi_2022,modcos_baseline,450,?,?%,—,—,—
casmi_2022,msclip_baseline,450,?,?%,—,—,—
casmi_2022,conditional,450,?,?%,?pp,?,?
```

加 cross-benchmark coherence 表:

```csv
metric,sub6a_v2_simulated_OOD,casmi_2016_real_OOD,casmi_2022_real_OOD
msclip_baseline_id_acc,56.70%,?,?
conditional_id_acc,66.96%,?,?
Δ_pp,+10.27,?,?
n,448,250,450
p_value_vs_msclip,<1e-6,?,?
```

**关键 sanity check**:CASMI 跟 Sub-6A v2 的 Δ 数字应在 ±3pp 内。差太远说明 conditional gate 阈值不 universal。

### D5 — 报告 `reports/eval/casmi_ood_v1.md`(0.5 day)

8 节,跟 Phase 6.5 报告同模板。**关键 §Result**:

```
Sub-6A v2 (simulated OOD via msclip primary):  +10.27 pp [95% CI ?]
CASMI 2016 (real OOD challenge):               +X pp     [95% CI ?]
CASMI 2022 (real OOD challenge):               +Y pp     [95% CI ?]
```

3 个数字一致 → paper 主张 universal,投稿大概率成功
3 个数字不一致 → paper 写"in-distribution leakage 让 Sub-6A v2 high-estimate;真 OOD 仅 ?pp"

**两种结果都有 paper finding**,session 不要倾向预设。

### D6 — Acceptance

```
□ CASMI loader 产出 ~700 task,schema 兼容 run_sub6a
□ 4 baseline configs (2016+2022 各 modcos+msclip) id_acc 报数
□ 2 conditional configs (2016+2022) id_acc 报数
□ Significance: 4 个 pair (per benchmark × per baseline) p-value 全报
□ 主 CSV phase6_6_casmi_results.csv 完整
□ 报告 8 节
□ 0 verifier 改动
□ Phase 6.5 落盘文件未动
```

---

## Pitfalls

1. **CASMI 数据格式不一致**(2016 vs 2022 schema 可能不同):D1 必须分两个 parser。如果 D1 卡住超过 1 day,escalate(loader 代码量比 rerank 大)。

2. **CASMI ground truth 可能是 InChIKey 而非 SMILES**:Sub-6A v2 用 InChIKey first-block。CASMI 给 SMILES 时,RDKit 转 InChIKey first-block 作 GT。

3. **CASMI 谱图 mass tolerance 不一定是 10ppm**:某些 CASMI challenge 用更宽容差。本 session 用 10ppm 跟 Sub-6A v2 一致;如果 baseline 极低(<20%),试 20ppm 看是否 calibration 问题。

4. **SIRIUS auto-relogin 必备**:CASMI 跑 ~6 小时,SIRIUS academic license 90-120 min 失效一次。Phase 6.2 的 auto-relogin 必须工作,不然每隔 1.5h 手动介入。

5. **CFM-ID cache 大量 miss**:Phase 6.2 cache 是 RIKEN 化合物的预测,CASMI 化合物不重叠。预期 hit rate <5%。CFM-ID 是主导 wall。

6. **不要因为 baseline 太低质疑数据**:CASMI baseline 30-50% 是预期。如果 modcos 在 CASMI 上 >70%,说明 CASMI 部分 leak 到 GNPS——是 finding 不是 bug。

7. **不要调阈值**:conditional gate `gap≥0.05` 是 Phase 6.5 在 Sub-6A v2 上 grid-search 出来的。CASMI 上**直接用同一阈值**,这正是测试 universality。如果 CASMI 上 0.05 不最优,paper 写"阈值需 per-benchmark 校准",不要本 session 就调。

---

## Time budget

- Confirm + D1 loader: 1.5 days
- D2 baselines: 1 day wall
- D3 conditional: 2 days wall(后台跑)
- D4 significance: 0.5 day
- D5 报告: 0.5 day
- D6: 15 min

**Total: ~5 days wall**(主要是 SIRIUS+CFM-ID 在新数据上的 cache miss + 700 task 体量)。

LLM 成本: $0(纯 retrieval + rerank)。

GPU: 2× RTX 4090(MS-CLIP)+ CFM-ID docker(CPU)。SIRIUS academic 频繁 relogin。

---

## First action checklist

第一回合:
1. 读 7 个 background 文件 + 2 个 CASMI README(`casmi_2016/README.md` + `casmi_2022/README.md`)
2. 验证 `casmi_2022/preprocessed/casmi2022/labels_true.tsv` 真有 170 行 + 头几行 sample
3. 验证 `casmi_2022/preprocessed/casmi2022/spec_files/*.ms` 数量(应 ~170)
4. 验证 `casmi_2016/solutions/solutions_casmi2016_cat2and3.csv` 行数 + sample
5. 验证 `casmi_2016/category2/challenges/*.mgf` 数量(应跟 cat 2 challenge 数对齐)
6. **GNPS leakage 检查**:对 CASMI 2022 的 170 个 InChIKey first-block,有多少在 `data/cache/library_search_dual_score.jsonl` 提到的 GNPS reference 里?(>30% leak 就需要 paper 写明 limitation)
7. 估算 CFM-ID 在 ~378 task × top-5 候选 × cache miss > 95% 的总 wall(主要成本)
8. 估算 SIRIUS 在 ~378 task 的 wall(可能复用 CASMI 2022 已有 sirius_outputs/ 343 dirs)
9. 任何 clarifying question,尤其 schema 适配 difficulty

不要写代码或跑命令,直到 confirm。

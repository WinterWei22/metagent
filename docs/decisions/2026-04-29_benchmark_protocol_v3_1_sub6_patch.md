# MetAgent-Bench: Benchmark Protocol (v3.1) — Sub-6 Section Patch

**文档位置:** `docs/decisions/2026-04-29_benchmark_protocol_v3_1_sub6_patch.md`

**作者:** Wentao Wei

**日期:** 2026-04-29

**状态:** Draft v3.1, supersedes §3.6 of v3 protocol

**用法:** 本文件**仅替换 v3 协议的 §3.6 整节**(以及相关交叉引用),其他章节不变。完整使用时把本文件 §3.6 内容替换 v3 协议同章节即可。

---

## v3.1 主要变更(相对 v3)

**Sub-6 拆分为两个子集:**

- **Sub-6A: End-to-end Enrichment** — 测全流程(spectrum → compound → enrichment narrative)
- **Sub-6B: Compound-only Enrichment** — 测半流程(compound → enrichment narrative)

理由:两者结合可以分离"Stage 1 鉴定误差"和"Stage 2 narrative 幻觉",这是 prior work 完全没做过的对比分析。

**Sub-6A 数据来源:** RIKEN spectrum(必须有谱图)
**Sub-6B 数据来源:** RIKEN 化合物 + HMDB 化合物混合(scope 广,无谱图依赖)

---

## §3.6 (新): MetAgent-Bench-Enrichment

**全新设计,测试 Stage 2(化合物组 → 富集路径 narrative),拆为 6A + 6B 两个子集**

**这是 MSAgent / SIRIUS / MIST / GeneAgent 都没做过的评估范式。**

---

### §3.6.1 整体定位

```
Sub-6A (端到端):
   spectrum_set → 鉴定 → compound_set → enrichment narrative
   ────────────────────────────────────────────────────────
   测什么:全流程在真实工作流下的可信度
   误差源:Stage 1 鉴定错误 + Stage 2 narrative 幻觉(级联)
   
Sub-6B (半流程):
   compound_set(已知)→ enrichment narrative
   ────────────────────────────────────────────────────────
   测什么:Stage 2 narrative 隔离评估
   误差源:仅 Stage 2 narrative 幻觉
```

**Paper 关键 punchline:**

> "By comparing Sub-6A and Sub-6B, we can decompose total Stage 2 error into:
> (1) Stage 1 identification cascade — present in 6A, absent in 6B
> (2) Stage 2 narrative hallucination — present in both
> The difference 6A_error − 6B_error quantifies the cascade contribution.
> This decomposition has not been performed in prior LLM-based metabolomics frameworks."

---

### §3.6.2 Sub-6A: End-to-end Enrichment

#### 测试什么

给定一组 MS/MS 谱图(模拟代谢组学实验里"差异显著"的代谢物的 raw spectra),测试系统能否端到端走完:鉴定 → 形成化合物组 → 推理 pathway enrichment narrative。

#### 数据规模

**30 个 enrichment task**(每个 task 含 8-13 条 spectrum)。

每 task 的 spectrum 总数:
- 5-8 条 signal spectrum(对应同一 pathway 的 RIKEN 化合物)
- 2-5 条 noise spectrum(对应不同 pathway 的 RIKEN 化合物)
- 每化合物可能贡献 1-2 条 spectrum(不同 collision energy 或 adduct)

**总 spectrum 用量:** 约 240-390 条

#### 数据来源

**仅使用 RIKEN spectrum**(必须有谱图)。

**Scope 限定:植物次级代谢方向**(Sub-6A 必然继承 Sub-1/Sub-2 的 scope 局限)。

#### 关键化合物筛选条件

```
化合物必须满足:
1. 在 RIKEN compound pool 中(有 spectrum)
2. 通过 NM-002 leakage filter(GNPS 无 RIKEN cross-reference)
3. 谱图 peaks ≥ 30 且 CE ≥ 10V(避免 SIRIUS 在稀疏低 CE 下错误)
4. 在 RaMP-DB 有 ≥1 pathway 注释
5. 该 pathway 内有 ≥5 个 RIKEN 化合物(用于构造 task)
```

**预期可用化合物:** 估计 100-150 个(从 171 个有 RaMP 注释中筛 peaks≥30 + CE≥10V 后)

#### Task 构造

跟 v3 §3.6.4 类似,但 signal/noise 来自 spectrum:

```python
def construct_e2e_enrichment_task(pathway, riken_pool, seed):
    pathway_compounds = get_riken_compounds_in_pathway(pathway)
    n_signal_compounds = random.randint(5, 8)
    signal_compounds = random.sample(pathway_compounds, n_signal_compounds)
    
    n_noise_compounds = random.randint(2, 5)
    non_members = [c for c in riken_pool 
                   if c not in pathway_compounds]
    noise_compounds = random.sample(non_members, n_noise_compounds)
    
    # 为每个化合物挑 1-2 条 spectrum
    differential_spectra = []
    for compound in signal_compounds + noise_compounds:
        spectra = get_spectra_for_compound(
            compound, peaks_min=30, ce_min=10)
        n = random.randint(1, min(2, len(spectra)))
        differential_spectra.extend(random.sample(spectra, n))
    
    random.shuffle(differential_spectra)
    
    return {
        "task_id": f"e2e_enrich_{pathway.id}_seed{seed}",
        "differential_spectra": differential_spectra,  # 谱图列表
        "ground_truth_pathway": pathway,
        "ground_truth_signal_compounds": signal_compounds,
        "ground_truth_noise_compounds": noise_compounds,
    }
```

#### 全流程执行

```
Step 1: 输入 differential_spectra (8-13 条 raw MS/MS 谱图)
Step 2: 系统对每条 spectrum 跑 identification (Sub-1 同款 pipeline)
        → 产出 candidate set(每条 spectrum 多个候选)
Step 3: 系统从 candidate set 形成 compound list
        (取每条 spectrum 的 top-1?或 verified 候选?这是策略选择)
Step 4: 系统基于 compound list 生成 enrichment narrative
Step 5: Verifier 同时验证:
        - Identification 准确率(per spectrum,跟 ground_truth_signal_compounds 比对)
        - Enrichment narrative 准确率(同 Sub-6B 的 4 类 claim)
```

**关键策略选择:Step 3 用什么候选?**

三种策略,paper 都要做对比实验:

```
Strategy A: 每 spectrum top-1 candidate (naive,容易级联误差)
Strategy B: Verifier-supported candidate(只用 verifier verdict=SUPPORTED 的)
Strategy C: Top-N union (取 top-3 候选并集,化合物数膨胀但 recall 高)
```

#### 评估指标

**Per-task identification 层:**

| 指标 | 含义 |
|---|---|
| Per-spectrum top-1 accuracy | 跟 v3 Sub-1 一致 |
| Compound-set precision | 系统形成的 compound list 中真 signal 化合物占比 |
| Compound-set recall | 真 signal 化合物中被正确识别的比例 |

**Per-task enrichment 层:**

| 指标 | 含义 |
|---|---|
| Top-1 pathway accuracy | LLM 提的 top pathway 是否在 RaMP top-3 |
| Driver precision/recall | 同 Sub-6B |

**关键级联指标:**

| 指标 | 含义 |
|---|---|
| Cascade impact | 6A_error − 6B_error,量化鉴定错误的级联 |
| Strategy comparison | Strategy A/B/C 的端到端 accuracy 对比 |

#### Paper 价值

**Sub-6A 的核心贡献是回答:**

> "如果 LLM 的输入是真实的 raw MS/MS 而不是已知化合物列表,enrichment narrative 的准确率会下降多少?"

这是**研究者真实场景**——在实验室里没人会拿"已经鉴定好的化合物列表"做 enrichment,都是从 raw data 出发。

**Punchline:**

> "Sub-6A reveals that under realistic end-to-end conditions, identification errors cascade into enrichment narratives: each 1% identification error contributes ~X% additional pathway error. Strategy B (verifier-gated identification) reduces cascade by Y% compared to naive top-1 selection."

---

### §3.6.3 Sub-6B: Compound-only Enrichment

#### 测试什么

给定一组化合物身份(SMILES + InChIKey),测试系统的 Stage 2 narrative 推理能力。**完全跳过 Stage 1**,纯净评估 LLM 在生物学解释上的可信度。

#### 数据规模

**50 个 enrichment task**(每个 task 含 7-13 个化合物)。

#### 数据来源(混合策略)

**RIKEN 化合物 + HMDB 化合物混合**:

```
Sub-6B-Plant (基于 RIKEN, 30 task):
  - 植物次级代谢 pathway
  - anthocyanin / flavonoid / phenylpropanoid / terpenoid / alkaloid
  - 化合物来自 RIKEN 171 个有 RaMP 注释的子集

Sub-6B-Mammalian (基于 HMDB, 20 task):
  - 人/哺乳动物代谢 pathway
  - TCA cycle / glycolysis / fatty acid β-oxidation / 
    purine metabolism / 其他 KEGG pathway
  - 化合物来自 HMDB(从 90,000+ 中抽 100-150 个高质量子集)
```

#### Sub-6B-Mammalian 化合物筛选条件(HMDB 来源)

```
1. HMDB 收录(必须)
2. KEGG ID 存在(必须,用于 RaMP 查询)
3. ClassyFire 完整 5 级分类
4. 在 RaMP-DB 有 ≥1 pathway 注释
5. 该 pathway 内有 ≥5 个 HMDB 化合物
6. SMILES 通过 RDKit 校验
```

不需要 spectrum。

#### Task 构造

跟 v3 §3.6.4 一致,基于化合物列表:

```python
def construct_compound_only_enrichment_task(
    pathway, compound_pool, seed
):
    pathway_compounds = get_compounds_in_pathway(pathway)
    signal = random.sample(pathway_compounds, k=random.randint(5, 8))
    
    non_members = [c for c in compound_pool 
                   if c not in pathway_compounds]
    noise = random.sample(non_members, k=random.randint(2, 5))
    
    differential_set = signal + noise
    random.shuffle(differential_set)
    
    return {
        "task_id": f"compound_only_enrich_{pathway.id}_seed{seed}",
        "differential_metabolites": differential_set,
        "ground_truth_pathway": pathway,
        "true_drivers": signal,
        "true_non_drivers": noise,
        "domain": "plant" or "mammalian",  # 区分两个子集来源
    }
```

#### LLM Prompt

```
## Task: Pathway Enrichment Reasoning

A metabolomics study identified the following metabolites as
significantly differentially abundant between control and
treatment groups:

[METABOLITE LIST: name + SMILES + KEGG ID + HMDB ID]

Please analyze:
1. Which metabolic pathway(s) are most likely affected?
2. Which of the listed metabolites are key drivers in those pathways?
3. What is the biological significance of these pathway changes?
4. Are there upstream/downstream pathway relationships worth noting?

Provide reasoning in 200-400 words.
```

(同 v3 §3.6.5,**不给 LLM 预先算好的 enrichment p-value**)

#### Verifier 解析:4 类 claim

跟 v3 §3.6.6 完全一致:

- **Claim 6a SET_ENRICHMENT** — 验证工具:RaMP-DB enrichment
- **Claim 6b DRIVER_METABOLITE** — 验证工具:RaMP-DB set membership
- **Claim 6c BIOLOGICAL_SIGNIFICANCE** — 验证工具:KEGG description / 文献
- **Claim 6d PATHWAY_RELATIONSHIP** — 验证工具:KEGG reaction graph / RaMP hierarchy

#### 评估指标

**Set-level (per-task):**

| 指标 | 含义 |
|---|---|
| Top-1 pathway accuracy | LLM 提的 top pathway 在 RaMP top-3 |
| Top-3 pathway recall | RaMP top-3 中 LLM 提到几个 |
| False enrichment rate | LLM 提的 pathway 完全不在 RaMP top-10 |

**Claim-level:**

(同 v3 §3.6.8)

**Domain-stratified (Sub-6B 关键新指标):**

| 指标 | Plant | Mammalian | 整体 |
|---|---|---|---|
| Top-1 pathway accuracy | ? | ? | ? |
| Driver precision | ? | ? | ? |
| Hallucination rate (4 类合并) | ? | ? | ? |

**Punchline 预期:**

> "LLMs perform comparably on plant secondary metabolism (Sub-6B-Plant) and mammalian central metabolism (Sub-6B-Mammalian) pathway attribution, but hallucinate cross-pathway relationships (Type 6d) significantly more on plant-specific pathways (X% vs Y%), likely due to sparser training data on plant pathway hierarchies."

---

### §3.6.4 Sub-6A vs Sub-6B 对比分析(paper 核心 figure)

**Paper 里 Figure 6:Cascade Decomposition**

```
                  Sub-6B    Sub-6A    Cascade contribution
                  (compound-only)  (end-to-end)  (6A − 6B)
─────────────────────────────────────────────────────────────
Top-1 pathway     X1%        X2%         X2 − X1
Driver precision  Y1         Y2          Y1 − Y2
Driver recall     Z1         Z2          Z1 − Z2
Type 6c halluc    H1         H2          H2 − H1
Overall claim acc A1         A2          A1 − A2
```

(占位数字,实际跑出后填)

**Paper 里 Section X(单独章节):**

```
Section X: Decomposing Identification Cascade in 
            End-to-End Enrichment Narratives

Existing LLM-based metabolomics frameworks evaluate either
identification (MSAgent, SIRIUS) or downstream interpretation
(GeneAgent, in genomics) but not both jointly. We introduce
a paired evaluation: Sub-6A (end-to-end from raw MS/MS) and
Sub-6B (compound-only). Their difference quantifies cascade
errors that real-world deployments face.

Findings:
- Sub-6B alone: LLM hallucinates X% of biological claims
- Sub-6A: cumulative error reaches Y% (Z% additional from
  identification cascade)
- Verifier-gated identification (Strategy B) reduces cascade
  contribution from W% to V%
```

**这一章可以撑 4-5 页**,是 paper 的方法学创新点。

---

### §3.6.5 数据格式

**Sub-6A task:**

```json
{
  "task_id": "e2e_enrich_smp_00029_seed_42",
  "task_type": "end_to_end_enrichment",
  "differential_spectra": [
    {
      "spectrum_id": "MetAgent-6A-001-spec-001",
      "source_id": "MSBNK-RIKEN-PR309128",
      "spectrum": {
        "precursor_mz": 449.1083,
        "adduct": "[M-H]-",
        "ion_mode": "negative",
        "collision_energy": 20.0,
        "peaks": []
      }
    }
  ],
  "ground_truth": {
    "primary_pathway": {
      "name": "Anthocyanin biosynthesis",
      "ramp_id": "smp_00029"
    },
    "ground_truth_signal_compounds": [
      {"name": "Cyanidin-3-glucoside", "inchikey": "..."}
    ],
    "ground_truth_noise_compounds": [
      {"name": "...", "inchikey": "..."}
    ],
    "ramp_enrichment_result": {
      "top_pathways": [],
      "drivers_per_pathway": {}
    }
  },
  "system_outputs": {
    "identification": [],
    "compound_list_strategy_a": [],
    "compound_list_strategy_b": [],
    "compound_list_strategy_c": [],
    "enrichment_narrative": "...",
    "extracted_claims": []
  }
}
```

**Sub-6B task:**

```json
{
  "task_id": "compound_only_enrich_smp_00029_seed_42",
  "task_type": "compound_only_enrichment",
  "domain": "plant",
  "differential_metabolites": [
    {
      "name": "Cyanidin-3-glucoside",
      "smiles": "...",
      "inchikey": "TUJKJAMUKRIRHC-UHFFFAOYSA-N",
      "kegg_id": "C08604",
      "hmdb_id": "HMDB0030700",
      "source": "riken"
    }
  ],
  "ground_truth": {
    "primary_pathway": {},
    "true_drivers": [],
    "true_non_drivers": [],
    "ramp_enrichment_result": {}
  },
  "llm_generated_narrative": "...",
  "extracted_claims": []
}
```

---

### §3.6.6 Verifier 实现工作量

**新增/扩展:**

```
verifier/layers/pathway_enrichment.py (NEW, ~300-400 行)
  ├─ verify_set_enrichment_claim()
  ├─ verify_driver_metabolite_claim()
  ├─ verify_pathway_relationship_claim()
  └─ verify_biological_significance_claim() (复用 Type 3 layer)

verifier/schemas.py (additive, 4 个新 ClaimType)
  ├─ ClaimType.SET_ENRICHMENT
  ├─ ClaimType.DRIVER_METABOLITE
  ├─ ClaimType.PATHWAY_RELATIONSHIP
  └─ ClaimType.BIOLOGICAL_SIGNIFICANCE (可能已存在)

verifier/claim_classifier.py (扩展)
  └─ enrichment claim 分类逻辑

verifier/agent.py (扩展 dispatcher)
  └─ enrichment claims 路由

orchestrator/end_to_end.py (NEW, ~200 行)
  └─ Sub-6A 全流程 orchestrator(spectrum_set → compound → narrative)
  └─ 实现 Strategy A/B/C 的候选选择
```

**实现工作量预估:** **3-4 天**(verifier 扩展 2 天 + orchestrator 1-2 天)

---

### §3.6.7 数据规模总结

```
Sub-6A (end-to-end):
  - 30 enrichment tasks
  - 240-390 RIKEN spectrum
  - 化合物 100-150 个(去重)
  - Scope: 植物次级代谢

Sub-6B (compound-only):
  - 50 enrichment tasks
    - 30 plant (RIKEN 化合物来源)
    - 20 mammalian (HMDB 化合物来源)
  - 化合物 200-300 个(去重)
  - Scope: 植物次级代谢 + 人/哺乳动物代谢
```

**总 task 数:80**(v3 是 50-80,v3.1 取上限)

---

### §3.6.8 关键预期结果

**Sub-6A vs Sub-6B 对比假设(待跑数据填):**

```
Metric                | Sub-6B    | Sub-6A    | Cascade
                      | (compound)| (e2e)     | contribution
─────────────────────────────────────────────────────────────
Top-1 pathway acc     | 65%       | 45%       | 20pp
Driver precision      | 0.70      | 0.55      | 0.15
Driver recall         | 0.65      | 0.50      | 0.15
Type 6a halluc rate   | 15%       | 25%       | 10pp
Type 6b halluc rate   | 25%       | 40%       | 15pp
Overall claim acc     | 0.75      | 0.60      | 0.15
```

**Strategy A/B/C 在 Sub-6A 上的对比假设:**

```
Strategy   | Top-1 pathway | Driver precision | Cascade
A (top-1)  | 40%           | 0.50             | high
B (verifier-gated) | 50%   | 0.60             | medium
C (top-3 union) | 45%      | 0.45             | medium-low
```

---

### §3.6.9 Sub-6 完整时间线

```
Day 1-2:   Verifier 扩展(4 类新 claim layer)— session
Day 3:     Sub-6B 化合物筛选(RIKEN 子集 + HMDB 子集)— session
Day 4:     Sub-6B task 构造脚本 — session
Day 5:     Sub-6A task 构造脚本(spectrum 抽取)— session
Day 6:     End-to-end orchestrator(Strategy A/B/C)— session
Day 7:     Sub-6B LLM narrative 生成 + verifier 评估
Day 8:     Sub-6A 全流程跑 + verifier 评估
Day 9-10:  分析结果 + cascade decomposition figure
```

**总耗时:~10 天(2 周)**

---

### §3.6.10 与 v3 协议其他章节的交叉引用更新

**§4 对比矩阵更新:**

```
                | Sub-6A        | Sub-6B
                | (e2e)         | (compound-only)
────────────────────────────────────────────────
SIRIUS          |   -           |   -
MIST            |   -           |   -
GPT-4 + prompt  |   ✓           |   ✓
Naive (yours)   |   ✓           |   ✓
Verified        |   ✓           |   ✓
MSAgent         |   -           |   -
GeneAgent       |   -           |   ◇* (方法学)
Cross-LLM       |   -           |   ✓
```

**§5 计算资源更新:**

| Method | Sub-6A (30 task) | Sub-6B (50 task) |
|---|---|---|
| Naive | 5h | 7h |
| Verified | 8h | 11h |
| Cross-LLM | 16h | 32h |

**总计算时间:~+10 小时**(相对 v3)

**§8 checklist 更新:**

**Sub-6A:**
- [ ] 30 task 全部基于 RIKEN spectrum
- [ ] 谱图 peaks≥30 + CE≥10V 筛选应用
- [ ] NM-002 leakage filter 应用
- [ ] Strategy A/B/C 都跑通

**Sub-6B:**
- [ ] Plant subset 30 task / Mammalian subset 20 task
- [ ] HMDB 化合物来源审计完整
- [ ] Domain-stratified 指标分别报告

**§9 PI 讨论要点新增:**

7. **Sub-6 拆分为 6A + 6B 是方法学创新**——cascade decomposition 是 paper 的强 punchline,prior work 完全没做

---

### §3.6.11 Limitations(纳入 v3 §11)

**新增 §11.6: Sub-6A scope 局限**

Sub-6A 必然继承 RIKEN scope(植物次级代谢)。Sub-6B-Mammalian 部分扩展到中心代谢/脂代谢,但只在化合物层面,不在 spectrum 层面。**Future work:** 扩展到 HMDB / MoNA spectrum 数据,实现 mammalian metabolism 的端到端 evaluation。

---

## Change log

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-04-29 | v3 | Sub-6 设计为 single subset(Pathway Enrichment Reasoning) |
| 2026-04-29 | v3.1 | Sub-6 拆分为 Sub-6A(端到端,RIKEN spectrum)+ Sub-6B(半流程,RIKEN+HMDB 化合物混合);新增 cascade decomposition 评估;Strategy A/B/C 候选选择对比 |
# MetAgent-Bench: Benchmark Protocol (v3)

**文档位置:** `docs/decisions/2026-04-29_benchmark_protocol_v3.md`

**作者:** Wentao Wei

**日期:** 2026-04-28 (v1) / 2026-04-29 (v2 + v3)

**状态:** Draft v3, pending PI review

---

## v3 主要变更(相对 v2)

1. **Sub-6 完全重新设计:** 从 "BiologicalContext"(单化合物 → 生物学注释)转向 "Pathway Enrichment Reasoning"(化合物组 → 富集路径 narrative),并明确限定 scope 为**植物次级代谢方向**
2. **Layer F 实现升级落入协议:** SIRIUS + CFM-ID cross-validation,不仲裁,新增 `NEEDS_HUMAN_REVIEW` verdict
3. **NM-002 数据泄漏处理纳入:** GNPS-RIKEN cross-reference filter,benchmark 构建必须先过 leakage filter
4. **Mode 比例调整:** 70:30 → 60:40(基于 RIKEN 真实分布 59.8%:40.2%)
5. **数据筛选条件加严:** Negative mode 子集筛选条件加 peaks ≥ 30 且 CE ≥ 10V(NM-001 mitigation)
6. **evidence_score 在 negative mode 下重新加权:** `predicted_spectrum_cosine` 权重 0.30 → 0.15(NM-007 mitigation)
7. **新 verdict 类别独立统计:** `NEEDS_HUMAN_REVIEW` 在所有 metrics 里作为 first-class 类别
8. **新增 limitation section:** RIKEN 单仪器、SIRIUS sanity threshold 待 sensitivity analysis、Sub-6 限定植物次级代谢
9. **计算资源估算更新:** Layer F CFM-ID overhead 因缓存可忽略;Sub-6 v2 比 v1 多 2-3 周

---

## 1. 设计目标与原则

### 1.1 总体目标

构建一个 benchmark,使 MetAgent 框架的评估满足三个条件:

1. **可对比性:** 至少部分子集与 MSAgent (Wang et al., 2026) 同口径,便于 head-to-head 比较
2. **针对性:** 至少部分子集专门为 verifier 价值评估设计,这是 MSAgent benchmark 没有的维度
3. **公开性:** 数据来源公开 (MassBank RIKEN + RaMP-DB + HMDB),benchmark 本身可作为社区资源 release

### 1.2 设计原则

| 原则 | 实现 |
|---|---|
| 数据来源公开 | 全部从 MassBank RIKEN / RaMP-DB / HMDB / KEGG 筛选 |
| 数据规模与 MSAgent 相当 | 总量 600-850 条 |
| 至少 2 个子集与 MSAgent 兼容 | Sub-1 (Open), Sub-2 (Pool) |
| 至少 2 个子集为 verifier 设计 | Sub-3 (Verification), Sub-4 (Mechanism) |
| 至少 1 个子集测试 Stage 2 | Sub-6 (Pathway Enrichment Reasoning) |
| Ground truth 多层(自动 + 人工) | 跟随 GeneAgent (Wang et al., 2024) 协议 |
| Cohen's κ 报告 | 在人工标注子集上 |
| Mode 比例反映现实分布 | 60:40 positive:negative |
| Benchmark 防数据泄漏 | 强制过 NM-002 leakage filter |

### 1.3 设计哲学:Two-Stage Identification + Biology

MetAgent 是**两阶段任务**,但 prior work 都只关注第一阶段。Benchmark 设计反映这个现实。

```
Stage 1: Spectrum → Compound identification
   - 输入:MS/MS 谱图
   - 输出:候选分子 + 排序
   - 评估:top-k accuracy
   - Prior work:MSAgent, SIRIUS, MIST 都在做这个

Stage 2: Compound (set) → Pathway enrichment narrative
   - 输入:差异代谢物组
   - 输出:富集路径 + driver + 生物学 narrative
   - 评估:set-level + per-claim accuracy
   - Prior work:无人系统做过 narrative-level 评测

Cross-cutting: Claim-level Hallucination Detection
   - 输入:LLM narrative(可能涵盖 Stage 1 + Stage 2)
   - 输出:per-claim verdicts
   - 评估:verifier precision/recall
```

**MetAgent 的核心差异化在 Stage 2 + Cross-cutting。**

- Sub-1, Sub-2, Sub-5: 测 Stage 1(跟 prior work 兼容)
- **Sub-6: 测 Stage 2(prior work 没做)**
- Sub-3, Sub-4: 测 Cross-cutting(prior work 没做)

### 1.4 与 prior work 的定位

```
MSAgent-Bench (4 子集)              MetAgent-Bench (6 子集)
─────────────────────────────────────────────────────────────
Sub-Open       (无候选)        ←→  Sub-1: Open        (兼容)
Sub-Pool       (4 难度池)      ←→  Sub-2: Pool        (兼容)
Sub-MultiTool  (ICEBERG+SIRIUS)←→  Sub-5: MultiTool   (扩展,可选)
Sub-Knowledge  (粗粒度知识消融)     [删除,粒度不够]

[新增,Cross-cutting]            →  Sub-3: Verification
[新增,Cross-cutting]            →  Sub-4: Mechanism
[新增,Stage 2,v3 重设计]       →  Sub-6: Pathway Enrichment Reasoning
```

**核心策略:** "Compatible (Stage 1) + Extended (Stage 2 + Cross-cutting)"

---

## 2. 数据源与筛选

### 2.1 数据源

**Stage 1 子集(Sub-1, Sub-2, Sub-5)主要来源: MassBank Europe (MassBank.eu) 的 RIKEN 子集**

理由:
- 完全公开,license 友好(CC-BY-NC)
- 全部 Level 1 鉴定(标准品验证),ground truth 可靠
- LC-ESI-MS/MS 为主,仪器多样(实际 RIKEN 单仪器 LC-ESI-QTOF — 见 limitation §11.1)
- 已有结构化 metadata(SMILES, InChIKey, precursor m/z, adduct, instrument)
- MSAgent 也用了 RIKEN,数据源一致便于对比

**Stage 2 子集(Sub-6)主要来源: RaMP-DB + HMDB + KEGG**

理由:
- RaMP-DB 整合 KEGG / Reactome / WikiPathways / HMDB,提供化合物 → pathway 的统一接口
- HMDB 提供 tissue / disease metadata
- KEGG 提供 reaction graph 用于 network reasoning ground truth
- 不需要 spectrum,只需要化合物身份

**Cross-cutting 子集(Sub-3, Sub-4)主要来源: 上述子集的 spectrum + LLM 生成 + 文献**

### 2.2 筛选条件(Stage 1 子集 — Positive mode)

| 维度 | 条件 |
|---|---|
| Ionization mode | Positive ESI |
| Instrument type | Q-TOF, Orbitrap, FT-ICR (排除 GC-EI, Triple Quad MS1) |
| MS level | MS2 |
| Precursor m/z | 100-800 Da |
| Peak count | ≥ 15 |
| 标注完整性 | SMILES + InChIKey + 分子式必备,adduct + collision energy 优选 |
| Identification level | Level 1(标准品验证)或 high-confidence Level 2 |

### 2.3 筛选条件(Stage 1 子集 — Negative mode,v3 加严)

**NM-001 mitigation:** Negative mode 在 SIRIUS 上对稀疏低 CE 谱图有错误公式倾向。Benchmark 数据筛选必须加严以避免该失败模式主导评测。

| 维度 | 条件 | v2 → v3 变化 |
|---|---|---|
| Ionization mode | Negative ESI | unchanged |
| Instrument type | Q-TOF, Orbitrap, FT-ICR | unchanged |
| MS level | MS2 | unchanged |
| Precursor m/z | 100-800 Da | unchanged |
| **Peak count** | **≥ 30** | v2 是 ≥ 15 |
| **Collision energy** | **≥ 10 eV** | v2 无要求 |
| 标注完整性 | SMILES + InChIKey + 分子式必备 | unchanged |
| Identification level | Level 1 或 high-confidence Level 2 | unchanged |

**预期影响:** RIKEN negative mode 2,381 条 → 估计降至 ~1,500 条(应用 peaks≥30 + CE≥10V 后)。仍足以支撑 60:40 比例下的 negative mode 子集需求。

### 2.4 筛选条件(Stage 2 子集 — Sub-6 v2)

Sub-6 不需要 spectrum,但需要化合物在多个数据库都有完整信息:

| 维度 | 条件 |
|---|---|
| 在 RaMP-DB 有 ≥1 pathway 注释 | 必须 |
| 该 pathway 内有 ≥5 个 RIKEN 化合物 | 必须(用于构造 enrichment task) |
| HMDB 收录 | 必须 |
| ClassyFire 完整 5 级分类 | 必须 |
| **Scope:植物次级代谢** | **必须**(NM 投稿时声明的 scope) |

**v3 关键决策:** Sub-6 v2 限定 scope 为植物次级代谢。理由:
- RIKEN 712 个独立化合物只有 171 (24%) 有 RaMP pathway 注释
- 这 171 个绝大多数集中在 anthocyanin / flavonoid / phenylpropanoid / polyphenol / terpenoid / alkaloid pathway
- 8 个经典中心代谢化合物只命中 1 个(citric acid),TCA / 糖酵解 / 脂代谢 / 核苷酸代谢 ground truth 不足
- Paper 里清晰声明 scope 比泛泛的覆盖更可信

### 2.5 NM-002 数据泄漏过滤(强制)

**所有 Stage 1 子集构建必须先过 leakage filter。**

GNPS reference library 包含来自 MassBank-RIKEN 的 cross-imported records。从 RIKEN 抽 query 在 GNPS 里查询会导致自我匹配,score 通常 >0.8,top-1 accuracy 虚高 20-40 个百分点。

**强制流程:**
```
Step 1: 从 RIKEN 抽出候选 spectrum 列表
Step 2: 调用 tools/benchmark/leakage_filter.py 的 build_leakage_filter()
        生成 GNPS exclusion list
Step 3: library_search 时传入 exclusion list,跳过这些 GNPS records
Step 4: benchmark 构建 audit report 必须记录:
        - 排除的 GNPS records 数量
        - 触发的 filter type 分布(InChIKey first-block / 
          MSBNK-RIKEN cross-reference / exact source ID)
        - 化合物类层面的覆盖
```

**审计文件:** `data/processed/nm002_excluded_gnps_ids.json`

### 2.6 化合物类别多样性

为避免某一类化合物主导评估,按化合物类分层抽样。每子集尽量覆盖以下 6 类:

| 化合物类 | 代表化合物 | 选择理由 |
|---|---|---|
| 氨基酸及衍生物 | L-phenylalanine, tryptophan | 基础代谢,HMDB 覆盖好 |
| 核苷/核苷酸 | adenosine, guanosine | 碎片有规律(碱基丢失) |
| 有机酸 | citric acid, succinic acid | 中性丢失明显 |
| 黄酮类 | quercetin, naringenin | retro-DA 机理,Sub-4 主战场 |
| 脂质(LPC/LPE) | LysoPC(16:0), LysoPE(18:1) | 高通量代谢组常见 |
| 生物碱 | caffeine, berberine | SIRIUS 表现好,Sub-2 isomer 区分 |

**抽样策略:** 每子集每类 5-15 条,确保至少 4 类有充分覆盖。

**实际分布(基于 RIKEN compound pool 5,930 spectra / 712 unique compounds):**

| 化合物类 | spectrum 数 | 独立化合物数 | 占比 |
|---|---:|---:|---:|
| other | 3,907 | 422 | 59.3% |
| flavonoid | 1,402 | 133 | 18.7% |
| organic_acid | 353 | 85 | 11.9% |
| lipid | 195 | 43 | 6.0% |
| amino_acid | 70 | 27 | 3.8% |
| nucleoside | 3 | 2 | 0.3% |
| **Total** | **5,930** | **712** | **100%** |

**注:** `other` 比例高是 SMARTS-only 分类的副作用。建议跑一晚 ClassyFire API 全量分类,会让 alkaloid / terpenoid / glycoside 显式出现,other 预计降至 25% 以下。

### 2.7 Mode 比例(v3 调整为 60:40)

**v2 → v3 调整:** 70:30 → **60:40 positive:negative**

理由:
1. RIKEN 真实分布是 59.8%:40.2%,60:40 是 natural ratio
2. RIKEN negative mode 在 flavonoid 类有更强覆盖(677/2381 = 28% 是 flavonoid),60:40 让黄酮在 benchmark 里有充分代表性
3. NM-001 SIRIUS 失败模式在 negative 上更突出,benchmark 应该包含足够 negative 样本来诚实展示这个问题

**各子集 mode 比例:**

```
Sub-1 Open (250):       150 positive + 100 negative
Sub-2 Pool (250):       同 Sub-1 化合物层面  
Sub-3 Verification (40): 24 positive + 16 negative
Sub-4 Mechanism (60):   36 positive + 24 negative
Sub-5 MultiTool (50):   30 positive + 20 negative
Sub-6 (Pathway):        N/A (不涉及 spectrum)
```

---

## 3. 六个子集详细设计

### 3.1 Sub-1: MetAgent-Bench-Open

**对应 MSAgent-Bench-Open / 测试 Stage 1**

#### 3.1.1 测试什么

End-to-end 鉴定准确率。给定一条 spectrum,系统从零开始检索 + 排序候选,无候选池。

#### 3.1.2 数据规模

250 条(150 positive + 100 negative)。每化合物类约 30-50 条。

#### 3.1.3 数据格式

```json
{
  "spectrum_id": "MetAgent-Bench-Open-001",
  "source_id": "MSBNK-RIKEN-PR309128",
  "spectrum": {
    "precursor_mz": 191.0197,
    "adduct": "[M-H]-",
    "ion_mode": "negative",
    "collision_energy": 20.0,
    "instrument": "LC-ESI-QTOF",
    "peaks": [[m/z, intensity], ...]
  },
  "ground_truth": {
    "compound_name": "Citric acid",
    "smiles": "OC(=O)CC(O)(C(=O)O)CC(=O)O",
    "inchikey": "KRKNYBCHXYNGOX-UHFFFAOYSA-N",
    "molecular_formula": "C6H8O7",
    "exact_mass": 192.0270,
    "compound_class": "organic_acid"
  },
  "metadata": {
    "msbankID_level": "1",
    "leakage_filter_applied": true,
    "leakage_excluded_gnps_count": 3
  }
}
```

#### 3.1.4 评估指标

| 指标 | 计算方法 |
|---|---|
| Top-1 accuracy | 排第一的候选 InChIKey 第一段是否匹配 ground truth |
| Top-5 accuracy | 正确候选在 top-5 内 |
| Top-10 accuracy | 正确候选在 top-10 内 |
| MRR | mean(1 / 正确答案排名) |
| Per-class accuracy | 按化合物类分别报告 top-1 |
| **Per-mode accuracy** | **positive 和 negative 分别报告(v3 新增)** |

**InChIKey 匹配口径:** 用第一段(2D 结构),宽容立体异构体差异。

#### 3.1.5 与 MSAgent 的对应关系

设计跟 MSAgent-Bench-Open 一致,数据源都是 MassBank RIKEN。Paper:

> "Following the design of MSAgent-Bench-Open (Wang et al., 2026), we constructed Sub-1 with 250 spectra in unconstrained identification setting. Our subset uses MassBank RIKEN as the source, identical to MSAgent-Bench. We additionally apply a leakage filter (Section 2.5) that excludes GNPS reference records cross-imported from RIKEN, preventing self-match inflation that affects naive RIKEN-based evaluation."

#### 3.1.6 这个子集主要评估的方法

| Method | 预期表现 |
|---|---|
| SIRIUS | 强 baseline,top-5 ~70-85% (positive),~60-75% (negative) |
| MIST | 类似 SIRIUS |
| Naive orchestrator | top-5 ~70-80% |
| Verified | 与 naive 接近(rank 没变,verifier 不改 candidate) |
| MSAgent (引用) | 引用其报告值 |

**重要洞察:** 这个子集**不是 verifier 主战场**。Top-1 accuracy 上 naive vs verified 差距小。这个子集的价值是**证明 base pipeline 跟 prior work 同水平**,不丢失 identification accuracy。

---

### 3.2 Sub-2: MetAgent-Bench-Pool

**对应 MSAgent-Bench-Pool / 测试 Stage 1 — Verifier 主战场**

#### 3.2.1 测试什么

候选区分能力,尤其是 isomer。给定 spectrum + 预构建的候选池,系统从池中选择最佳候选。

#### 3.2.2 数据规模

250 条(可与 Sub-1 重叠 50-80%)。每条 spectrum 配 4 个难度等级的候选池。

#### 3.2.3 候选池构建

每条 spectrum 的 ground truth compound 是 C_true。构建 4 个 level 的候选池,每池 10 个候选:

**Level 1 (Easy): Mass decoys** — 1 个 C_true + 9 个 mass 差异 >50 Da 的随机分子
**Level 2 (Medium): Same mass, different formula** — 9 个 ±0.05 Da 内但分子式不同
**Level 3 (Hard): Same formula, different connectivity** — 9 个分子式相同但 SMILES 不同
**Level 4 (Very Hard): Stereoisomers / positional isomers** — 9 个高度相似的同分异构体

#### 3.2.4 候选池生成方法

```python
def build_candidate_pool(c_true, level):
    if level == 1:
        return [c_true] + sample_random_pubchem(9, mass_diff_min=50)
    elif level == 2:
        return [c_true] + sample_pubchem_by_mass(
            9, target_mass=c_true.mass, tol=0.05, formula_must_differ=True)
    elif level == 3:
        return [c_true] + sample_pubchem_by_formula(
            9, formula=c_true.formula, exclude_inchikey=c_true.inchikey_first_block)
    elif level == 4:
        return [c_true] + sample_isomers(
            9, scaffold=c_true.scaffold, max_tanimoto=0.9, min_tanimoto=0.7)
```

#### 3.2.5 评估指标

| 指标 | 计算方法 |
|---|---|
| Top-1 by Level | 每个难度级别的 top-1 accuracy |
| Cross-level degradation | Level 1 vs Level 4 的 accuracy 降幅 |
| Per-class × Per-level | 双向分层 |
| **Per-mode × Per-level** | **mode 分层(v3 新增)** |

#### 3.2.6 这个子集是 verifier 的主战场

**关键预期结果(占位假设,实际跑出来再填):**

```
Method               | Level 1 | Level 2 | Level 3 | Level 4
─────────────────────────────────────────────────────────────
Naive orchestrator   | 95%     | 80%     | 50%     | 30%
Verified (full)      | 96%     | 85%     | 65%     | 50%
  - 去掉 Type 5      | 95%     | 81%     | 52%     | 32%
  - 去掉 SIRIUS only | 96%     | 84%     | 60%     | 40%
  - 去掉 CFM-ID only | 96%     | 84%     | 62%     | 45%
```

**Paper 里的 punchline:**

> "On Sub-2 Level 4 (stereoisomer/positional isomer discrimination), our verified framework improves top-1 accuracy from X% (naive) to Y%, an absolute gain of Z percentage points. Ablation analysis attributes 70% of this improvement to Type 5 (peak-mechanistic) claim verification with SIRIUS+CFM-ID cross-validation."

#### 3.2.7 evidence_score 在 negative mode 下重新加权(v3 新增)

NM-007 发现 CFM-ID 4.4.7 在 negative mode 下预测准确率较低(20% / 6% peak overlap)。`predicted_spectrum_cosine` 在 negative mode 系统性偏低。

**Mode-specific 权重:**

```
evidence_score components:
                              Positive | Negative
─────────────────────────────────────────────────
library_search_score          0.30     | 0.30
predicted_spectrum_cosine     0.30     | 0.15  ← v3 调整
formula_match_score           0.20     | 0.30  ← 补回
classyfire_consistency        0.10     | 0.15  ← 补回
peak_count_match              0.10     | 0.10
```

Paper Methods 写明这个 mode-specific 加权及理由。

---

### 3.3 Sub-3: MetAgent-Bench-Verification

**全新设计,Cross-cutting 评估**

#### 3.3.1 测试什么

Per-claim hallucination detection。测试 verifier 在 claim-level 上的 precision / recall。

#### 3.3.2 数据规模

40 条 spectrum(24 positive + 16 negative),从 Sub-1 中精选。每条产生 10-15 个 claims,总共约 400-700 个 claims。

#### 3.3.3 标注流程

```
Step 1: 跑 naive orchestrator → 产生 LLM narrative
Step 2: Verifier 提取 claims + 自动 verdict (Type 1-5 全部)
Step 3: 抽样人工标注(基于 GeneAgent 协议):
  - 全部 40 条用 verifier 跑
  - 随机抽 5-7 条做人工标注
  - 标注集 60-100 个 claims,2 人独立
  - 算 Cohen's κ
Step 4: 剩余条只用自动 verdict(不人工)
```

#### 3.3.4 Ground truth 分级

| Claim 类型 | Ground truth 来源 | 自动化程度 |
|---|---|---|
| Type 1 (grounded) | 比对 source_report JSON 字段 | 100% 自动 |
| Type 2 (factual) | HMDB / KEGG / ClassyFire 查询 | 90% 自动 + 10% spot check |
| Type 3 (biological) | KEGG / RaMP-DB 查询 | 90% 自动 + 10% spot check |
| Type 4 (consistency) | 文本比对 | 100% 自动 |
| Type 5 (peak-mechanistic) | **SIRIUS + CFM-ID 交叉验证(Layer F)** | **70% 自动 + 30% 人工** |

#### 3.3.5 Verdict 类别(v3 调整)

**v3 新增第五类 verdict:** `NEEDS_HUMAN_REVIEW`

Layer F cross-validation 在 SIRIUS 和 CFM-ID 不一致时不仲裁,产出 `NEEDS_HUMAN_REVIEW`。这个 verdict 在所有 metrics 里独立统计,**不能合并入 contradicted 或 unverifiable**。

```
Verdict 5 类:
  - SUPPORTED            (两工具一致,正向)
  - CONTRADICTED         (两工具一致,反向 / 单一证据)
  - UNSUPPORTED          (peak 不存在 / 工具找不到证据)
  - UNVERIFIABLE         (无法验证)
  - NEEDS_HUMAN_REVIEW   (工具不一致,escalate,v3 新增)  ← first-class
```

#### 3.3.6 评估指标

| 指标 | 含义 |
|---|---|
| Per-Type Hallucination rate | 每个 Type 的 (refuted+unsupported)/total |
| Verifier Precision (per Type) | verifier 标 contradicted 的真错占比 |
| Verifier Recall (per Type) | 真错的被 verifier 抓到的比例 |
| Verifier F1 (per Type) | 2PR/(P+R) |
| **Needs-Human-Review rate (per Type)** | **v3 新增:工具不一致触发率** |
| Cohen's κ (人工 vs verifier) | 在抽样集上 |

#### 3.3.7 Paper 核心 figure 来源

**Paper 里 Table 2 / Figure 2 占位预期:**

```
Claim Type         | Halluc | V-Prec | V-Recall | F1   | NHR
──────────────────────────────────────────────────────────────
Type 1 grounded    | 5%     | 0.95   | 0.92     | 0.93 | 0%
Type 2 factual     | 12%    | 0.88   | 0.81     | 0.84 | 1%
Type 3 biological  | 8%     | 0.85   | 0.79     | 0.82 | 2%
Type 4 consistency | 3%     | 0.98   | 0.95     | 0.96 | 0%
Type 5 mechanistic | 25%    | 0.72   | 0.65     | 0.68 | 12%
──────────────────────────────────────────────────────────────
Overall            | 11%    | 0.86   | 0.79     | 0.82 | 4%
Cohen's κ on 5-7 sample subset: 0.81
```

**Paper punchline:**

> "Type 5 (peak-mechanistic) claims exhibit the highest hallucination rate (25% baseline). Our SIRIUS+CFM-ID cross-validation Layer F reduces these to X% with verifier-precision 0.72. The 12% NEEDS_HUMAN_REVIEW rate on Type 5 is a feature, not a bug — it transparently flags cases where independent tools disagree, rather than allowing the LLM to silently arbitrate."

---

### 3.4 Sub-4: MetAgent-Bench-Mechanism

**全新设计,Cross-cutting,Type 5 专项**

#### 3.4.1 测试什么

LLM 对 fragmentation mechanism 的描述准确性。专门针对 Type 5 中最难的子类——机理性 claim。

#### 3.4.2 数据规模

60 条 spectrum(36 positive + 24 negative),精挑细选化合物类丰富 fragmentation 的:

| 化合物类 | 数量 | 主要机理 | Negative 重点 |
|---|---:|---|---|
| 黄酮类 | 15-20 | retro-Diels-Alder | RDA 负离子模式产物 |
| 脂质(LPC, LPE, PC) | 15-20 | McLafferty rearrangement | sn-cleavage |
| 糖类 | 10-15 | ring cleavage | cross-ring cleavage |
| 生物碱 | 10-15 | complex multi-step | — |
| 其他 | 5-10 | inductive cleavage | CO2 / H2O loss |

#### 3.4.3 Ground truth 来源

每条记录的 mechanism ground truth 来自:
- **文献:** PubMed / Google Scholar 搜 "[compound name] MS/MS fragmentation pathway"
- **教科书:** Mass Spectrometry of Natural Products 系列
- **专家 review:** 你 + 1-2 位 MS 背景的同事

每条记录至少 3 个 well-established mechanism claims 作为 ground truth。

#### 3.4.4 数据格式

```json
{
  "spectrum_id": "MetAgent-Bench-Mechanism-001",
  "spectrum": {},
  "ground_truth": {
    "established_mechanisms": [
      {
        "fragment_mz": 153.0182,
        "neutral_loss": 152.0473,
        "neutral_loss_formula": "C9H8N2O",
        "mechanism": "retro-Diels-Alder cleavage of C-ring",
        "literature_pmid": "..."
      }
    ]
  }
}
```

#### 3.4.5 评估流程

```
Step 1: Prompt naive orchestrator 主动产生 mechanism claims
Step 2: Verifier Layer F 识别 + 验证 mechanism claims (SIRIUS+CFM-ID)
Step 3: 比对 LLM mechanism claims 与文献 ground truth
Step 4: 计算每类化合物的 mechanism accuracy
```

#### 3.4.6 评估指标

| 指标 | 含义 |
|---|---|
| Mechanism claim count | LLM 主动产生的 mechanism claim 数 |
| Mechanism accuracy | 与文献 ground truth 一致的比例 |
| Mechanism hallucination rate by class | 每化合物类的错误率 |
| Mode-specific mechanism accuracy | positive vs negative |
| Layer F verdict distribution | SUPPORTED / CONTRADICTED / NEEDS_HUMAN_REVIEW 比例 |

#### 3.4.7 预期 punchline

> "We find that LLMs hallucinate fragmentation mechanisms most frequently for flavonoids (45% error rate on positive mode RDA mechanisms). Lipid mechanism claims have the lowest error (15%). Layer F's SIRIUS+CFM-ID cross-validation catches X% of these hallucinations, with Y% escalated to NEEDS_HUMAN_REVIEW (cases where SIRIUS and CFM-ID disagree)."

---

### 3.5 Sub-5: MetAgent-Bench-MultiTool (Optional)

**对应 MSAgent-Bench-MultiTool / Stage 1 工具融合**

#### 3.5.1 是否做的判断

如果时间充裕(Week 5 之前完成 Sub 1-4 + Sub 6),才做这个。否则跳过。

#### 3.5.2 测试什么

工具间(SIRIUS vs CFM-ID)结论不一致时的 verifier 处理策略。

#### 3.5.3 设计

- 50 条 spectrum(30 positive + 20 negative),故意挑 SIRIUS 和 CFM-ID 给出不一致候选的
- **v3 直接复用 Layer F cross-validation 的 NEEDS_HUMAN_REVIEW 机制**
- 测试两种处理策略:
  - "LLM 仲裁":naive orchestrator 让 LLM 选哪个工具的结论
  - "Layer F escalate":检测到不一致,标记 needs_human_review

#### 3.5.4 评估指标

- 各策略的最终 top-1 accuracy
- Layer F 检测到的不一致案例中,真实不一致的比例(precision)
- "LLM 仲裁选错"率 vs "escalate 后人工选对"率对比

---

### 3.6 Sub-6: MetAgent-Bench-Enrichment (v2 完全重设计)

**v3 全新设计,测试 Stage 2(化合物组 → 富集路径 narrative)**

**这是 MSAgent / SIRIUS / MIST 完全没碰的维度,paper 战略层面的核心差异化。**

#### 3.6.1 测试什么

给定一组差异代谢物,测试系统能否产出准确、可信的 pathway enrichment narrative。

具体测试 LLM 在以下方面的可靠性:

1. **Set-level 富集:** LLM 提的 top pathway 是否跟 RaMP-DB hypergeometric enrichment 的 top-3 一致
2. **Driver metabolite identification:** LLM 提的 "key drivers" 是否真正属于该 pathway
3. **Biological significance:** LLM 提的生物学意义解释是否跟 KEGG / Reactome 描述一致
4. **Pathway relationships:** LLM 提的上下游 / cross-talk 关系是否在 KEGG reaction graph 中真实存在

#### 3.6.2 Scope 限定(v3 关键决策)

**Scope: 植物次级代谢路径(plant secondary metabolism)**

理由:
- RIKEN 712 个独立化合物中,只有 171 (24%) 有 RaMP pathway 注释
- 这 171 个绝大多数集中在 anthocyanin / flavonoid / phenylpropanoid / polyphenol / terpenoid / alkaloid pathway
- 中心代谢(TCA / 糖酵解)、脂代谢、核苷酸代谢的 ground truth 在 RIKEN 中不足
- 清晰 scope 比泛泛覆盖更可信,符合 NM 期刊偏好

**Paper 中明确声明:**

> "We focus on plant secondary metabolism pathways, where RIKEN data provides high-quality identification ground truth. Extension to central / lipid / nucleotide metabolism awaits future work with broader data sources (HMDB, MoNA, GNPS-Library)."

#### 3.6.3 数据规模

50-80 个 enrichment task。

每个 task:
- 5-13 个 differentially abundant metabolites
- 1 个 ground truth 富集 pathway
- 完整的 RaMP enrichment ground truth(top-3 pathway + p-values + drivers)

总计涉及 RIKEN 化合物约 100-150 个(化合物可在多个 task 中重复)。

#### 3.6.4 Enrichment task 构造方法

**Step 1: 识别有效 pathway**

从 RaMP-DB 5,093 条 pathway 注释中筛出**有 ≥5 个 RIKEN 化合物的 pathway**。预计 30-50 个 pathway 满足条件。

**Step 2: 为每个 pathway 构造 enrichment task**

```python
def construct_enrichment_task(pathway, all_riken_compounds, seed):
    random.seed(seed)
    
    # Signal: 5-8 个属于该 pathway 的 RIKEN 化合物
    pathway_members = get_riken_compounds_in_pathway(pathway)
    n_signal = random.randint(5, min(8, len(pathway_members)))
    signal = random.sample(pathway_members, k=n_signal)
    
    # Noise: 2-5 个不属于该 pathway 的随机化合物
    non_members = [c for c in all_riken_compounds 
                   if c not in pathway_members]
    n_noise = random.randint(2, 5)
    noise = random.sample(non_members, k=n_noise)
    
    # 混合并打乱
    differential_set = signal + noise
    random.shuffle(differential_set)
    
    return {
        "task_id": f"enrich_{pathway.id}_seed{seed}",
        "differential_metabolites": differential_set,
        "ground_truth_pathway": pathway,
        "true_drivers": signal,
        "true_non_drivers": noise,
        "signal_ratio": n_signal / (n_signal + n_noise),
    }
```

**关键设计:**
- Signal 占比 60-80%(模拟真实代谢组学差异分析)
- Noise 必要——无 noise 的 task 退化为列举,失去判断意义
- 每个 pathway 用 2-3 个不同 seed 构造 task,共 50-80 个 task

**Step 3: 用 RaMP-DB 跑标准 enrichment 作 ground truth**

```python
def compute_ramp_enrichment(differential_set):
    result = ramp.enrich(
        analytes=[c.kegg_id or c.hmdb_id for c in differential_set],
        background="ramp_full"
    )
    return {
        "top_pathways": result.top_n(5),
        "p_values": {p.id: p.fdr for p in result},
        "drivers_per_pathway": {p.id: p.matched_analytes for p in result}
    }
```

#### 3.6.5 LLM Prompt 设计

**关键设计:不给 LLM 预先算好的 enrichment p-value。** 测的是 LLM 自己从化合物列表推出 pathway 富集的能力。

```
## Task: Pathway Enrichment Reasoning

A metabolomics study identified the following metabolites as
significantly differentially abundant between control and
treatment groups in a plant tissue sample:

[METABOLITE LIST: 化合物名 + SMILES + KEGG ID(如有) + HMDB ID(如有)]

Please analyze:
1. Which metabolic pathway(s) are most likely affected by the
   observed changes?
2. Which of the listed metabolites are key drivers in those
   pathways?
3. What is the biological significance of these pathway changes?
4. Are there upstream/downstream pathway relationships worth noting?

Provide reasoning in 200-400 words.
```

#### 3.6.6 Verifier 解析:4 类新 claim

```
Claim Type 6a: SET_ENRICHMENT_CLAIM
  例: "These metabolites are significantly enriched in 
       Anthocyanin biosynthesis pathway"
  验证逻辑: 
    - 提取 LLM 提的 pathway 名
    - 跟 RaMP enrichment top-3 比对
    - SUPPORTED (在 top-3) / CONTRADICTED (不在 top-10) / UNSUPPORTED (在 top-10 但不在 top-3)

Claim Type 6b: DRIVER_METABOLITE_CLAIM
  例: "Cyanidin-3-glucoside and Pelargonidin are key drivers"
  验证逻辑:
    - 提取 LLM 提的 driver 列表
    - 跟 RaMP set membership 比对(driver 是否真属于声称的 pathway)
    - 计算 precision (真 driver / LLM 提的 driver)
    - 计算 recall (LLM 提到的 / 实际 signal)

Claim Type 6c: BIOLOGICAL_SIGNIFICANCE_CLAIM
  例: "These changes suggest oxidative stress response"
  验证逻辑:
    - 已有 Type 3 (biological) layer 复用
    - 跟 KEGG / Reactome description 比对
    - 文献交叉验证

Claim Type 6d: PATHWAY_RELATIONSHIP_CLAIM
  例: "Anthocyanin biosynthesis is downstream of phenylpropanoid pathway"
  验证逻辑:
    - 跟 KEGG reaction graph 比对(有无连接)
    - 跟 RaMP pathway hierarchy 比对
```

#### 3.6.7 数据格式

```json
{
  "task_id": "enrich_smp_00029_seed_42",
  "task_type": "pathway_enrichment_reasoning",
  "differential_metabolites": [
    {
      "name": "Cyanidin-3-glucoside",
      "smiles": "...",
      "inchikey": "TUJKJAMUKRIRHC-UHFFFAOYSA-N",
      "kegg_id": "C08604",
      "hmdb_id": "HMDB0030700"
    }
  ],
  "ground_truth": {
    "primary_pathway": {
      "name": "Anthocyanin biosynthesis",
      "ramp_id": "smp_00029",
      "kegg_id": "map00942"
    },
    "ramp_enrichment_result": {
      "top_pathways": [
        {"name": "Anthocyanin biosynthesis", "fdr": 1.2e-8},
        {"name": "Flavonoid biosynthesis", "fdr": 3.4e-5},
        {"name": "Phenylpropanoid biosynthesis", "fdr": 0.001}
      ]
    },
    "true_drivers": ["Cyanidin-3-glucoside", "Pelargonidin", "..."],
    "true_non_drivers": ["unrelated_compound_1", "..."]
  },
  "llm_generated_narrative": "...",
  "extracted_claims": [
    {
      "claim_id": "001-6a-001",
      "claim_text": "These metabolites are enriched in anthocyanin biosynthesis",
      "claim_type": "SET_ENRICHMENT_CLAIM",
      "verifier_verdict": "supported",
      "ground_truth_match": true
    },
    {
      "claim_id": "001-6b-001",
      "claim_text": "Cyanidin-3-glucoside is a key driver",
      "claim_type": "DRIVER_METABOLITE_CLAIM",
      "verifier_verdict": "supported",
      "ground_truth_match": true
    }
  ]
}
```

#### 3.6.8 评估指标

**Set-level (per-task):**

| 指标 | 含义 |
|---|---|
| Top-1 pathway accuracy | LLM 提的 top pathway 是否在 RaMP top-3 |
| Top-3 pathway recall | RaMP top-3 中 LLM 提到几个 |
| False enrichment rate | LLM 提的 pathway 完全不在 RaMP top-10 的比例 |

**Claim-level (across-task):**

| 指标 | 含义 |
|---|---|
| Type 6a accuracy | set_enrichment 准确率 |
| Type 6a verifier P/R/F1 | verifier 在 set_enrichment 上表现 |
| Type 6b precision | LLM driver claim 的真 driver 占比 |
| Type 6b recall | LLM 提到的 driver 占实际 signal 比例 |
| Type 6c hallucination rate | biological significance 错误率 |
| Type 6d accuracy | pathway relationship 准确率 |

**Cross-cutting:**

| 指标 | 含义 |
|---|---|
| Overall hallucination rate | 4 类合并错误率 |
| Verifier overall F1 | 综合 F1 |
| NEEDS_HUMAN_REVIEW rate | enrichment claim 触发 review 的比例 |

#### 3.6.9 这个子集对 paper 的战略价值

**为什么 Sub-6 v2 是 paper 的关键:**

1. **完全独占:** MSAgent / SIRIUS / MIST / GeneAgent 都没做 metabolomics enrichment narrative 评测
2. **直接展示 verifier 价值:** Stage 2 narrative 是 LLM 幻觉重灾区
3. **对应代谢组学家真实工作流:** 鉴定不是终点,enrichment + 生物学解释才是
4. **方法学创新:** 把 enrichment 工具(RaMP)输出作为 ground truth,这是新的评估范式
5. **可作为社区资源:** MS 领域第一个 LLM enrichment narrative benchmark

**Paper Section X 全部数据来源于此。**

#### 3.6.10 与方向 A (pathway attribution) 和方向 C (network reasoning) 的关系

v3 决策:**主任务做 enrichment(方向 B)**,方向 A 和 C 作为辅线缩小数据规模。

| 子任务 | 类型 | 数据规模 |
|---|---|---:|
| **主任务:Pathway Enrichment Narrative** | 化合物组 → 富集路径 | 50-80 task |
| 辅线:Compound functional classification | 单化合物 → ClassyFire 类 | 100-150 化合物 |
| 辅线:Tissue localization | 单化合物 → HMDB tissue | 60 化合物 |
| 辅线:Disease association | 单化合物 → HMDB disease | 50 化合物 |

辅线任务复用 Sub-6 v1 的设计(已在 v2 协议中),不再赘述。Paper 里这些辅线作为"单化合物 vs 化合物组任务难度对比"的对照实验。

---

## 4. 与 prior work 的对比矩阵

```
                | Sub-1 | Sub-2 | Sub-3 | Sub-4 | Sub-5 | Sub-6
                | Open  | Pool  | Verif | Mech  | MultT | Enrich
─────────────────────────────────────────────────────────────────
SIRIUS          |   ✓   |   ✓   |   -   |   -   |   -   |   -
MIST            |   ✓   |   ✓   |   -   |   -   |   -   |   -
GPT-4 + prompt  |   ✓   |   ✓   |   ✓   |   ✓   |   -   |   ✓
Naive (yours)   |   ✓   |   ✓   |   ✓   |   ✓   |   ✓   |   ✓
Verified (yours)|   ✓   |   ✓   |   ✓   |   ✓   |   ✓   |   ✓
MSAgent (cited) |   ◇   |   ◇   |   -   |   -   |   ◇   |   -
GeneAgent (cited)|  -   |   -   |   ◇   |   -   |   -   |   ◇*
Cross-LLM       |   -   |   ✓   |   ✓   |   -   |   -   |   ✓

✓ : 跑实验
◇ : 引用其报告值
◇* : 方法学引用(GeneAgent 做 gene set enrichment narrative,我们做 metabolite set)
- : 不适用
```

**说明:**

- MSAgent 数字只在 Sub-1, Sub-2, Sub-5 上引用
- Sub-3, Sub-4, Sub-6 上 MSAgent 没法对比
- Sub-6 上 GeneAgent 是方法学参考(同样的 narrative-level 评估范式),不是数字对比
- Cross-LLM 实验在 Sub-2, Sub-3, Sub-6 做(对 verifier 价值最敏感)

---

## 5. 计算资源估算

### 5.1 单 method 在每个子集上的预估耗时

| Method | 单条耗时 | Sub-1 (250) | Sub-2 (250×4=1000) | Sub-3 (40) | Sub-4 (60) | Sub-5 (50) | Sub-6 (80) |
|---|---|---|---|---|---|---|---|
| SIRIUS | 30s | 2h | - | - | - | - | - |
| MIST | 5s | 0.4h | - | - | - | - | - |
| GPT-4 prompt | 30s | 2h | 8h | 0.3h | 0.5h | - | 0.7h |
| Naive (yours) | 5min | 21h | 83h | 3h | 5h | 4h | 7h |
| **Verified (yours, Layer F upgraded)** | **8min** | 33h | 133h | 5h | 8h | 7h | 11h |
| Cross-LLM × 3 | 8min | - | 250h | 16h | - | - | 32h |

**总计算时间:** 约 **665 小时 (~28 天连续运行)**

**v3 vs v2 变化:**
- Sub-6 时间略增(80 task vs 120 化合物,但每 task LLM 调用更长)
- Layer F cross-validation 增加 CFM-ID 调用,但因缓存(同 SMILES+adduct 复用)实际开销可忽略

### 5.2 实际运行策略

- GPU 服务器 24/7 跑,优先级:Sub-3 > Sub-2 > Sub-6 > Sub-1 > Sub-4 > Sub-5
- 可并行:Sub-1 SIRIUS 和 Sub-3 verifier;Sub-6 完全无 spectrum 依赖,完全独立
- 抽样:Cross-LLM 不全跑,Sub-2 只跑 50 条 × 4 levels(节省 80%)

按这个策略,实际墙钟时间 **~12 天**。

### 5.3 LLM API 成本估算

| 实验 | LLM calls | 单次成本 | 总成本 |
|---|---|---|---|
| Naive Sub-1 | 250 | MiniMax ~$0.005 | $1.25 |
| Verified Sub-1 | 250 × 5 stages | MiniMax | $6.25 |
| Naive Sub-2 | 1000 | MiniMax | $5 |
| Verified Sub-2 | 1000 × 5 | MiniMax | $25 |
| Naive Sub-6 | 80 | MiniMax | $0.4 |
| Verified Sub-6 | 80 × 5 | MiniMax | $2 |
| Cross-LLM (GPT-4) | (250 + 80) × 5 | $0.05 | $82.5 |
| Cross-LLM (Claude) | (250 + 80) × 5 | $0.04 | $66 |

**总 LLM 成本:** ~$190-240。在合理预算内。

---

## 6. 构建时间表

```
Week 2 (本周):
  ├─ v3 协议冻结 (本文档) ✓
  ├─ ClassyFire 全量分类(夜里跑,优化 compound pool)
  └─ 跟 PI 同步 v3 + Sub-6 v2

Week 3:
  ├─ Sub-1 (Open) 数据构建 + 验证 (session + 你, 2 天)
  └─ Sub-2 (Pool) 候选池生成脚本 + 数据 (session, 2-3 天)

Week 4:
  ├─ Sub-2 数据构建完成
  ├─ Sub-3 (Verification) 数据准备 + 抽样集人工标注准备
  └─ Sub-6 v2 verifier 扩展 (新增 4 类 enrichment claim layer, 2-3 天)

Week 5:
  ├─ Sub-6 v2 enrichment task 构造 (1-2 天)
  ├─ Sub-6 v2 LLM narrative 生成 + verifier 评估 (1 天)
  └─ Sub-4 (Mechanism) 文献调研启动 (slow background)

Week 6:
  ├─ Sub-3 Cohen's κ 标注完成
  ├─ Sub-4 数据完成
  └─ Sub-5 (MultiTool, 可选) — 时间允许才做

Week 7+:
  ├─ 跑全 benchmark 实验
  └─ Paper writing
```

**总构建时间:** 约 **3 周**(Week 3-5),与 benchmark 实验时间重叠。

---

## 7. 数据 release 策略

### 7.1 开源时机

bioRxiv 投稿时同步 release benchmark dataset。Paper 接收后正式 publish。

### 7.2 Release 内容

```
metagent-bench/
├── README.md
├── LICENSE (CC-BY-4.0)
├── data/
│   ├── sub1_open.jsonl                  (250 records)
│   ├── sub2_pool.jsonl                  (250 × 4 levels)
│   ├── sub3_verification.jsonl          (40 records + annotations)
│   ├── sub4_mechanism.jsonl             (60 records)
│   ├── sub5_multitool.jsonl             (50 records, optional)
│   └── sub6_enrichment.jsonl            (50-80 enrichment tasks)
├── ground_truth/
│   ├── sub3_human_annotations.jsonl
│   ├── sub6_ramp_enrichment_snapshot_2026-XX-XX.jsonl
│   └── nm002_excluded_gnps_ids.json
├── scripts/
│   ├── load_benchmark.py
│   ├── compute_metrics.py
│   ├── run_baseline.py
│   ├── refresh_sub6_ground_truth.py
│   └── apply_leakage_filter.py
└── docs/
    ├── benchmark_protocol.md            (本文档)
    └── nm002_leakage_audit.md
```

### 7.3 Hosting

- **代码:** GitHub
- **数据:** Zenodo(给 DOI,可引用)
- **互联网:** 项目主页 link 到两者

---

## 8. 验证 benchmark 质量的内部 checklist

构建完成后,在 release 前 self-check:

**Sub-1 (Open):**
- [ ] 250 条全部有完整 ground truth (SMILES + InChIKey + formula)
- [ ] 化合物类 6 类都覆盖,每类 ≥ 30 条
- [ ] 至少 90% 通过 RDKit SMILES 校验
- [ ] Mode 比例 60:40 ± 5%
- [ ] **NM-002 leakage filter 应用,排除日志归档**

**Sub-2 (Pool):**
- [ ] 每条 spectrum 4 个 level 都有 10 个候选
- [ ] Level 4 候选与 ground truth 的 Tanimoto 相似度 > 0.7
- [ ] **Negative mode 子集应用 peaks≥30 + CE≥10V 筛选**

**Sub-3 (Verification):**
- [ ] 5-7 条抽样集 Cohen's κ > 0.7
- [ ] 自动验证 Type 1-4 与人工 spot check 一致性 > 90%
- [ ] **NEEDS_HUMAN_REVIEW 在所有 metrics 中独立统计**

**Sub-4 (Mechanism):**
- [ ] 每条 spectrum 至少 3 个 well-documented mechanism
- [ ] Mechanism ground truth 至少 1 个文献 PMID 支撑

**Sub-6 (Pathway Enrichment):**
- [ ] 50-80 个 task 全部基于 ≥5 RIKEN 化合物的 pathway
- [ ] 每个 task 有完整 RaMP enrichment ground truth(top-3 + p-values + drivers)
- [ ] Signal/noise 比例在 60-80% 区间
- [ ] Verifier 4 类新 claim layer 有单元测试覆盖
- [ ] RaMP snapshot date 记录

**跨子集:**
- [ ] spectrum_id / task_id 全局唯一
- [ ] ground truth 一致(同一化合物在不同子集 SMILES 必须 identical)
- [ ] **Mode 比例报告 per-subset**

---

## 9. 与 PI 的讨论要点

跟 PI 同步时,重点说明 6 件事:

1. **Sub-6 转向 pathway enrichment 是战略升级**,不是设计修补。理由:enrichment narrative 是 LLM 真正幻觉重灾区,verifier 价值在这里最大化,且 prior work 完全没碰
2. **Scope 限定植物次级代谢是诚实选择**,不是 weakness。RIKEN 数据决定了这个 scope,paper 明确声明比泛泛 claim 更可信
3. **Mode 比例 60:40 反映现实**,不是任意决定。RIKEN 真实 59.8/40.2
4. **Layer F cross-validation 已实现完成**,带 NEEDS_HUMAN_REVIEW 机制,直接支撑 Sub-3 / Sub-4 评估
5. **NM-002 数据泄漏已修复**,benchmark 防止虚高 20-40 个百分点
6. **Sub-3/Sub-4/Sub-6 是新贡献**,可作为社区资源 release,paper 加分项

PI 可能的反对意见和应对:

- **"为什么不做中心代谢的 enrichment?"**
  → RIKEN ground truth 不足。需要扩展 HMDB / MoNA(0.5-1 周工作量)。可以作为 future work 或 paper Section 5(scope extension)讨论
- **"Sub-6 v2 比 v1 工作量大,timeline 还能赶上吗?"**
  → 主任务 + 辅线总工作量 ~3 周,timeline 紧但可控。比 v1 多 1-2 周
- **"NEEDS_HUMAN_REVIEW 是不是会让 verifier 看起来'啥也没干'?"**
  → 不会。这是诚实的不确定性表达,paper 里专门 frame 为 strength。GeneAgent 也用类似机制,被 NM 接收
- **"Sub-6 单仪器 / 单源(全 RIKEN)会不会有 robustness 问题?"**
  → Sub-6 不依赖 spectrum,化合物身份层面无 instrument bias。paper 限定 plant secondary metabolism scope 已经是 conservative

---

## 10. 风险与备选方案

| 风险 | 概率 | 应对 |
|---|---|---|
| RIKEN 化合物在 RaMP 注释不足 | 已确认 — 171/712 | 已限定 scope,接受 |
| Sub-6 enrichment task 化合物类多样性不足 | 中 | 至少覆盖 anthocyanin / flavonoid / phenylpropanoid / terpenoid / alkaloid 5 类 pathway |
| Sub-2 候选池构建 isomer 抽样困难 | 中 | RDKit 生成虚拟同分异构体 |
| Sub-3 人工标注 Cohen's κ < 0.7 | 中 | 重新培训 + 标注指南 |
| Sub-4 文献 ground truth 找不齐 | 中 | 减少到 40 条,化合物类减少 |
| RaMP-DB 版本变化导致 ground truth 漂移 | 低 | release 时 freeze snapshot,提供 refresh 脚本 |
| 计算资源不够,跑不完 665 小时 | 中 | 抽样 30%,paper 里说明 |
| MSAgent 突然 release 他们的 benchmark | 低 | 加跑 head-to-head 对比章节 |
| Sub-6 LLM 在 plant pathway 上表现意外好(无 hallucination 可测) | 低 | 增加 noise compound 比例,提升任务难度 |

---

## 11. Limitations(paper 必须明确写出)

### 11.1 RIKEN 单仪器局限

所有 Stage 1 子集数据都来自 LC-ESI-QTOF (Waters UPLC Q-Tof Premier)。无法测试跨仪器 robustness。**Future work:** 扩展到 MassBank Athens / Eawag-EAWAG (Orbitrap 数据)。

### 11.2 Sub-6 scope 限定

Sub-6 限定植物次级代谢方向。中心代谢 / 脂代谢 / 核苷酸代谢的 enrichment 推理待 future work。

### 11.3 SIRIUS sanity threshold 待 sensitivity analysis

Layer F 的 SIRIUS sanity check threshold 设为 2 atoms,基于 NM-001 单 case (citric acid C4H6N3O6 vs C6H8O7) 推断。Paper supplement 必须给出 threshold sensitivity table:

```
Threshold | False positive | False negative
   1      |    高           |   低
   2      |    中           |   中    ← current
   3      |    低           |   高
```

实际数字在 Sub-3 / Sub-4 跑完后 paper revision 时填。

### 11.4 CFM-ID negative mode 准确率局限

CFM-ID 4.4.7 在 negative mode 下 peak overlap 仅 6-20%。`evidence_score` 的 mode-specific 加权(NM-007 mitigation)是务实工程决策,Paper Methods 必须明确。

### 11.5 Negative mode 数据筛选加严

Negative mode 子集应用 peaks≥30 + CE≥10V 筛选(NM-001 mitigation),会让 negative mode 子集化合物多样性低于 positive mode。Paper Methods 明确这个筛选条件及理由。

---

## 12. 后续动作清单

```
Step 1 (本周): 跟 PI 同步本文档 v3,获取确认 ← 现在
Step 2 (本周): ClassyFire 全量分类夜里跑
Step 3 (Week 3): 派 session 构建 Sub-1
Step 4 (Week 3-4): 派 session 构建 Sub-2
Step 5 (Week 4): 
  - 派 session 扩展 verifier(Sub-6 v2 的 4 类新 claim layer)
  - 派 session 准备 Sub-3 数据
Step 6 (Week 5):
  - 派 session 构建 Sub-6 v2 enrichment task
  - 派 session 跑 Sub-6 v2 LLM + verifier
Step 7 (Week 5-6): 派 session 构建 Sub-4
Step 8 (Week 6, 可选): 派 session 构建 Sub-5
Step 9 (Week 7+): 跑全 benchmark 实验 + paper writing
```

---

## 13. Change log

| 日期 | 版本 | 变更 | 作者 |
|---|---|---|---|
| 2026-04-28 | v1 | Initial draft (5 个子集) | Wentao Wei |
| 2026-04-29 | v2 | 加入 Sub-6 BiologicalContext;Two-Stage 设计哲学;对比矩阵更新 | Wentao Wei |
| 2026-04-29 | v3 | (1) Sub-6 完全重设计为 Pathway Enrichment Reasoning,scope 限定植物次级代谢 (2) Layer F cross-validation 实现纳入协议 (3) NM-002 leakage filter 强制流程 (4) Mode 比例 70:30 → 60:40 (5) Negative mode 筛选加严 (peaks≥30, CE≥10V) (6) evidence_score mode-specific 加权 (7) NEEDS_HUMAN_REVIEW first-class verdict (8) Limitations section 新增 (9) 计算资源 + 时间表更新 | Wentao Wei |
# MetAgent-Bench: Benchmark Protocol

**文档位置:** `docs/decisions/2026-04-28_benchmark_protocol.md`

**作者:** Wentao Wei

**日期:** 2026-04-28

**状态:** Draft v2, pending PI review

**v2 主要变更:**

- 新增 Sub-6: BiologicalContext,专门评估 Stage 2(化合物 → 生物学解释)
- Section 1.3 加入 "Stage 1 vs Stage 2" 设计哲学
- Section 4 对比矩阵更新
- Section 5 计算资源估算更新
- Section 6 时间表加入 Sub-6
- Section 8 checklist 加入 Sub-6 验收项

**用途:**

- 派 benchmark construction sessions 的设计依据
- Paper Methods 章节 Evaluation 部分的素材来源
- 跟 PI 讨论 benchmark 设计的会议材料
- 回答 reviewer "为什么这么设计 benchmark" 的现成答案

---

## 1. 设计目标与原则

### 1.1 总体目标

构建一个 benchmark,使 MetAgent 框架的评估满足三个条件:

1. **可对比性:** 至少部分子集与 MSAgent (Wang et al., 2026) 同口径,便于 head-to-head 比较
2. **针对性:** 至少部分子集专门为 verifier 价值评估设计,这是 MSAgent benchmark 没有的维度
3. **公开性:** 数据来源公开 (MassBank RIKEN),benchmark 本身可以作为社区资源 release

### 1.2 设计原则

| 原则 | 实现 |
| --- | --- |
| 数据来源公开 | 全部从 MassBank RIKEN / KEGG / HMDB 筛选 |
| 数据规模与 MSAgent 相当 | 总量 600-850 条 |
| 至少 2 个子集与 MSAgent 兼容 | Sub-1 (Open), Sub-2 (Pool) |
| 至少 2 个子集为 verifier 设计 | Sub-3 (Verification), Sub-4 (Mechanism) |
| 至少 1 个子集测试 Stage 2 | Sub-6 (BiologicalContext) |
| Ground truth 多层(自动 + 人工) | 跟随 GeneAgent (Wang et al., 2024) 协议 |
| Cohen's κ 报告 | 在人工标注子集上 |

### 1.3 设计哲学:Two-Stage Identification + Biology

MetAgent 的工作本质是**两阶段任务**,但 prior work 都只关注第一阶段。Benchmark 设计必须反映这个现实。

```
Stage 1: Spectrum → Compound identification
   - 输入:MS/MS 谱图
   - 输出:候选分子 + 排序
   - 评估:top-k accuracy
   - Prior work:MSAgent, SIRIUS, MIST 都在做这个

Stage 2: Compound → Biological context
   - 输入:已鉴定的化合物
   - 输出:通路、组织富集、疾病关联、功能分类
   - 评估:per-claim biological accuracy
   - Prior work:无人系统做过

Cross-cutting: Claim-level Hallucination Detection
   - 输入:LLM narrative(可能涵盖 Stage 1 + Stage 2)
   - 输出:per-claim verdicts
   - 评估:verifier precision/recall
```

**MetAgent 的核心差异化在 Stage 2 + Cross-cutting。** Benchmark 设计反映这个定位:

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
[新增,Stage 2]                  →  Sub-6: BiologicalContext
```

**核心策略:** "Compatible (Stage 1) + Extended (Stage 2 + Cross-cutting)"

---

## 2. 数据源与筛选

### 2.1 数据源

**Stage 1 子集(Sub-1, Sub-2, Sub-5)主要来源: MassBank Europe (MassBank.eu) 的 RIKEN 子集**

理由:

- 完全公开,license 友好(CC-BY-NC)
- 全部 Level 1 鉴定(标准品验证),ground truth 可靠
- LC-ESI-MS/MS 为主,仪器多样(Q-TOF, Orbitrap)
- 已有结构化 metadata(SMILES, InChIKey, precursor m/z, adduct, instrument)
- MSAgent 也用了 RIKEN,数据源一致便于对比

**Stage 2 子集(Sub-6)主要来源: HMDB + KEGG + RaMP-DB**

理由:

- HMDB 提供化合物的组织/疾病/功能信息
- KEGG 提供通路结构
- RaMP-DB 整合多源,有现成的 ground truth
- 不需要 spectrum,只需化合物列表

**Cross-cutting 子集(Sub-3, Sub-4)主要来源: 上述子集的 spectrum + LLM 生成 + 文献**

### 2.2 筛选条件(Stage 1 子集)

所有 Stage 1 子集共享的硬性筛选条件:

| 维度 | 条件 |
| --- | --- |
| Ionization mode | `Positive or Negative ESI` |
| Instrument type | Q-TOF, Orbitrap, FT-ICR (排除 GC-EI, Triple Quad MS1) |
| MS level | MS2 |
| Precursor m/z | 100-800 Da |
| Peak count | ≥ 15 |
| 标注完整性 | SMILES + InChIKey + 分子式必备,adduct + collision energy 优选 |
| Identification level | Level 1(标准品验证)或 high-confidence Level 2 |

### 2.3 筛选条件(Stage 2 子集)

Sub-6 不需要 spectrum,但需要化合物在多个数据库都有完整信息:

| 维度 | 条件 |
| --- | --- |
| HMDB 收录 | 必须有 |
| KEGG ID | 必须有 |
| 至少 1 条 KEGG pathway 关联 | 必须 |
| 至少 1 条 HMDB tissue location | 必须 |
| 至少 1 条 HMDB disease association(可选,但强烈优选) | 优选 |
| ClassyFire 分类 | 必须 |

### 2.4 化合物类别多样性

为避免某一类化合物主导评估,按化合物类分层抽样。每子集尽量覆盖以下 6 类:

| 化合物类 | 代表化合物 | 选择理由 |
| --- | --- | --- |
| 氨基酸及衍生物 | L-phenylalanine, tryptophan | 基础代谢,HMDB 覆盖好 |
| 核苷/核苷酸 | adenosine, guanosine | 碎片有规律(碱基丢失) |
| 有机酸 | citric acid, succinic acid | 中性丢失明显 |
| 黄酮类 | quercetin, naringenin | retro-DA 机理,Sub-4 主战场 |
| 脂质(LPC/LPE) | LysoPC(16:0), LysoPE(18:1) | 高通量代谢组常见 |
| 生物碱 | caffeine, berberine | SIRIUS 表现好,Sub-2 isomer 区分 |

**抽样策略:** 每子集每类 5-15 条,确保至少 4 类有充分覆盖。

---

## 3. 六个子集详细设计

### 3.1 Sub-1: MetAgent-Bench-Open

**对应 MSAgent-Bench-Open / 测试 Stage 1**

mode-balanced (50% positive, 50% negative)

### 3.1.1 测试什么

End-to-end 鉴定准确率。给定一条 spectrum,系统从零开始检索 + 排序候选,无候选池。

### 3.1.2 数据规模

200-300 条,优先 250 条。

每化合物类约 40-50 条,确保化合物类多样性。

### 3.1.3 数据格式

每条记录包含:

```json
{
  "spectrum_id": "MetAgent-Bench-Open-001",
  "source_id": "RIKEN_BMS00001",
  "spectrum": {
    "precursor_mz": 181.0707,
    "adduct": "[M+H]+",
    "ion_mode": "positive",
    "collision_energy": 30.0,
    "instrument": "LC-ESI-Q-TOF",
    "peaks": [[100.5, 0.15], [110.2, 0.85]]
  },
  "ground_truth": {
    "compound_name": "L-tyrosine",
    "smiles": "N[C@@H](Cc1ccc(O)cc1)C(=O)O",
    "inchikey": "OUYCCCASQSFEME-QMMMGPOBSA-N",
    "molecular_formula": "C9H11NO3",
    "exact_mass": 181.0739,
    "compound_class": "amino_acid"
  },
  "metadata": {
    "msbankID_level": "1",
    "literature_pmid": "..."
  }
}
```

### 3.1.4 评估指标

| 指标 | 计算方法 |
| --- | --- |
| Top-1 accuracy | 排第一的候选 InChIKey 第一段是否匹配 ground truth |
| Top-5 accuracy | 正确候选在 top-5 内 |
| Top-10 accuracy | 正确候选在 top-10 内 |
| MRR | mean(1 / 正确答案排名) |
| Per-class accuracy | 按化合物类分别报告 top-1 |

**InChIKey 匹配口径:** 用第一段(2D 结构),宽容立体异构体差异。这是 MSAgent / SIRIUS 的标准口径。

### 3.1.5 与 MSAgent 的对应关系

设计跟 MSAgent-Bench-Open 一致。Paper 写作时:

> "Following the design of MSAgent-Bench-Open (Wang et al., 2026), we constructed Sub-1 with N spectra in unconstrained identification setting. Our subset uses MassBank RIKEN as the source, identical to MSAgent-Bench."
> 

### 3.1.6 这个子集主要评估的方法

| Method | 在这个子集上的预期表现 |
| --- | --- |
| SIRIUS | 强 baseline,top-5 ~70-85% |
| MIST | 类似 SIRIUS |
| Naive orchestrator (你的) | 弱,因为 narrative 含幻觉但 candidate ranking 由 retrieval 主导,top-5 ~70-80% |
| Verified (你的) | 与 naive 接近(rank 没变,verifier 不改 candidate),但 narrative 质量更好 |
| MSAgent (引用) | 报告值,X% |

**重要洞察:** 这个子集**不是 verifier 主战场**——因为 verifier 不改变 candidate ranking,只改变 narrative。所以 top-1 accuracy 上 naive vs verifier 差距小。这个子集的价值是**证明你的 base pipeline 跟 prior work 同水平**,不丢失 identification accuracy。

---

### 3.2 Sub-2: MetAgent-Bench-Pool

**对应 MSAgent-Bench-Pool / 测试 Stage 1**

mode-balanced (50% positive, 50% negative)

### 3.2.1 测试什么

候选区分能力,尤其是 isomer。给定 spectrum + 预构建的候选池,系统从池中选择最佳候选。

### 3.2.2 数据规模

200-300 条(可与 Sub-1 重叠 50-80%)。

每条 spectrum 配 4 个难度等级的候选池。

### 3.2.3 候选池构建

每条 spectrum 的 ground truth compound 是 C_true。构建 4 个 level 的候选池,每池 10 个候选:

**Level 1 (Easy): Mass decoys**

- 1 个 C_true + 9 个 mass 差异 >50 Da 的随机分子
- 评估 baseline 鉴定能力

**Level 2 (Medium): Same mass, different formula**

- 1 个 C_true + 9 个 monoisotopic mass 在 ±0.05 Da 内但分子式不同的分子
- 评估化学知识使用

**Level 3 (Hard): Same formula, different connectivity**

- 1 个 C_true + 9 个分子式相同但 SMILES 不同的分子
- 评估 fragmentation pattern 推理能力

**Level 4 (Very Hard): Stereoisomers / positional isomers**

- 1 个 C_true + 9 个高度相似的同分异构体(同骨架不同位置/立体)
- 评估 peak-level mechanistic 推理(verifier Type 5 主战场)

### 3.2.4 候选池生成方法

```python
def build_candidate_pool(c_true, level):
    if level == 1:
        return [c_true] + sample_random_pubchem(9, mass_diff_min=50)
    elif level == 2:
        return [c_true] + sample_pubchem_by_mass(
            9,
            target_mass=c_true.mass,
            tol=0.05,
            formula_must_differ=True
        )
    elif level == 3:
        return [c_true] + sample_pubchem_by_formula(
            9,
            formula=c_true.formula,
            exclude_inchikey=c_true.inchikey_first_block
        )
    elif level == 4:
        return [c_true] + sample_isomers(
            9,
            scaffold=c_true.scaffold,
            max_tanimoto=0.9,
            min_tanimoto=0.7
        )
```

候选池构建耗时:大约 0.5 天(让 session 写 + 你 review)。

### 3.2.5 数据格式

```json
{
  "spectrum_id": "MetAgent-Bench-Pool-001",
  "spectrum": {},
  "ground_truth": {},
  "candidate_pools": {
    "level_1": [{"smiles": "...", "inchikey": "...", "formula": "...", "mass": 0.0}],
    "level_2": [],
    "level_3": [],
    "level_4": []
  }
}
```

### 3.2.6 评估指标

| 指标 | 计算方法 |
| --- | --- |
| Top-1 by Level | 每个难度级别的 top-1 accuracy |
| Cross-level degradation | Level 1 vs Level 4 的 accuracy 降幅 |
| Per-class × Per-level | 双向分层(化合物类 × 难度) |

### 3.2.7 这个子集是 verifier 的主战场

**关键预期结果:**

```
Method               | Level 1 | Level 2 | Level 3 | Level 4
─────────────────────────────────────────────────────────────
Naive orchestrator   | 95%     | 80%     | 50%     | 30%
Verified (full)      | 96%     | 85%     | 65%     | 50%
  - 去掉 Type 5      | 95%     | 81%     | 52%     | 32%
  - 去掉 SIRIUS      | 96%     | 84%     | 60%     | 40%
  - 去掉 CFM-ID      | 96%     | 84%     | 62%     | 45%
```

(以上数字是预期假设,实际跑出来再填)

**Paper 里的 punchline:**

> "On Sub-2 Level 4 (stereoisomer/positional isomer discrimination), our verified framework improves top-1 accuracy from X% (naive) to Y%, an absolute gain of Z percentage points. Ablation analysis attributes 70% of this improvement to Type 5 (peak-mechanistic) claim verification."
> 

---

### 3.3 Sub-3: MetAgent-Bench-Verification

**全新设计,Cross-cutting 评估**

mode-balanced (50% positive, 50% negative)

### 3.3.1 测试什么

Per-claim hallucination detection。测试 verifier 在 claim-level 上的 precision / recall。

### 3.3.2 数据规模

30-50 条 spectrum,从 Sub-1 中精选(优选 LLM 容易产生丰富 narrative 的)。

每条 spectrum 上的 LLM narrative 大约产生 10-15 个 claims,总共约 400-700 个 claims。

### 3.3.3 标注流程

```
Step 1: 跑 naive orchestrator → 产生 LLM narrative
Step 2: Verifier 提取 claims + 自动 verdict (Type 1-4 全自动)
Step 3: 抽样人工标注(基于 GeneAgent 协议):
  - 全部 30-50 条用 verifier 跑
  - 随机抽 5-7 条做人工标注
  - 标注集 60-100 个 claims,2 人独立
  - 算 Cohen's κ
Step 4: 剩余 23-43 条只用自动 verdict(不人工)
```

### 3.3.4 Ground truth 分级

跟随 GeneAgent (Wang et al., 2024) 协议:

| Claim 类型 | Ground truth 来源 | 自动化程度 |
| --- | --- | --- |
| Type 1 (grounded) | 比对 source_report JSON 字段 | 100% 自动 |
| Type 2 (factual) | HMDB / KEGG / ClassyFire 查询 | 90% 自动 + 10% spot check |
| Type 3 (biological) | KEGG / RaMP-DB 查询 | 90% 自动 + 10% spot check |
| Type 4 (consistency) | 文本比对 | 100% 自动 |
| Type 5 (peak-mechanistic) | SIRIUS + CFM-ID + 人工 review | 70% 自动 + 30% 人工 |

### 3.3.5 数据格式

```json
{
  "spectrum_id": "MetAgent-Bench-Verification-001",
  "spectrum": {},
  "ground_truth": {},
  "naive_orchestrator_output": {
    "trace_id": "...",
    "llm_narrative": "...",
    "extracted_claims": [
      {
        "claim_id": "001-c001",
        "claim_text": "L-carnitine has molecular formula C7H15NO3",
        "claim_type": "Type_2_factual",
        "source_span": [100, 145]
      }
    ]
  },
  "annotations": {
    "annotator_1": {"001-c001": "supported"},
    "annotator_2": {"001-c001": "supported"},
    "consensus": {"001-c001": "supported"},
    "kappa": 0.87
  }
}
```

### 3.3.6 评估指标

| 指标 | 含义 |
| --- | --- |
| Per-Type Hallucination rate | 每个 Type 的 (refuted+unsupported)/total |
| Verifier Precision (per Type) | verifier 标 contradicted 的真错占比 |
| Verifier Recall (per Type) | 真错的被 verifier 抓到的比例 |
| Verifier F1 (per Type) | 2PR/(P+R) |
| Cohen's κ (人工 vs verifier) | 在抽样集上 |

### 3.3.7 这个子集是 paper 核心 figure 来源

**Paper 里 Table 2 / Figure 2:**

```
Claim Type         | Halluc Rate | Verifier Precision | Verifier Recall | F1
─────────────────────────────────────────────────────────────────────────────
Type 1 grounded    | 5%          | 0.95               | 0.92            | 0.93
Type 2 factual     | 12%         | 0.88               | 0.81            | 0.84
Type 3 biological  | 8%          | 0.85               | 0.79            | 0.82
Type 4 consistency | 3%          | 0.98               | 0.95            | 0.96
Type 5 mechanistic | 25%         | 0.72               | 0.65            | 0.68
─────────────────────────────────────────────────────────────────────────────
Overall            | 11%         | 0.86               | 0.79            | 0.82
Cohen's κ (verifier vs human) on 5-7 sample subset: 0.81
```

**Paper 里的 punchline:**

> "Type 5 (peak-mechanistic) claims exhibit the highest hallucination rate (25% baseline), confirming that LLMs struggle most with chemistry-grounded mechanistic reasoning. Our verifier reduces this to X% with verifier-precision 0.72."
> 

---

### 3.4 Sub-4: MetAgent-Bench-Mechanism

**全新设计,Cross-cutting 评估,Type 5 专项**

mode-balanced (50% positive, 50% negative)

### 3.4.1 测试什么

LLM 对 fragmentation mechanism 的描述准确性。专门针对 Type 5 中最难的子类——机理性 claim。

### 3.4.2 数据规模

50-80 条 spectrum,精挑细选化合物类丰富 fragmentation 的:

| 化合物类 | 数量 | 主要机理 |
| --- | --- | --- |
| 黄酮类 | 15-20 | retro-Diels-Alder |
| 脂质(LPC, LPE, PC) | 15-20 | McLafferty rearrangement, sn-cleavage |
| 糖类 | 10-15 | ring cleavage, glycosidic cleavage |
| 生物碱 | 10-15 | complex multi-step fragmentation |
| 其他 | 5-10 | inductive cleavage, alpha cleavage |

### 3.4.3 Ground truth 来源

每条记录的 mechanism ground truth 来自:

- **文献:** PubMed / Google Scholar 搜 "[compound name] MS/MS fragmentation pathway"
- **教科书:** Mass Spectrometry of Natural Products 系列
- **专家 review:** 你 + 1-2 位 MS 背景的同事

每条记录至少 3 个 well-established mechanism claims 作为 ground truth。

### 3.4.4 数据格式

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

### 3.4.5 评估流程

```
Step 1: Prompt naive orchestrator 主动产生 mechanism claims
   (在 system prompt 里加 "Please describe the fragmentation mechanism for each major peak.")
Step 2: Verifier Layer 3 (mechanism flagger) 识别 mechanism claims
Step 3: 比对 LLM mechanism claims 与 ground truth mechanisms
Step 4: 计算每类化合物的 mechanism accuracy
```

### 3.4.6 评估指标

| 指标 | 含义 |
| --- | --- |
| Mechanism claim count | LLM 主动产生的 mechanism claim 数 |
| Mechanism accuracy | 与文献 ground truth 一致的比例 |
| Mechanism hallucination rate by class | 每化合物类的错误率 |
| Verifier flagging precision | Layer 3 标记的 mechanism claim 中,实际是 mechanism 的比例 |
| Verifier flagging recall | 实际 mechanism claim 中,被 Layer 3 抓到的比例 |

### 3.4.7 Paper 里的关键发现

**预期 punchline:**

> "We find that LLMs hallucinate fragmentation mechanisms most frequently for flavonoids (45% error rate), where they correctly identify retro-Diels-Alder as a mechanism class but misattribute the specific bond cleavage. Lipid mechanism claims have the lowest error (15%), likely due to clearer training data coverage."
> 

这是一个**领域知识** finding,只有做这个子集才能得到,paper 价值很高。

---

### 3.5 Sub-5: MetAgent-Bench-MultiTool (Optional)

**对应 MSAgent-Bench-MultiTool / 测试 Stage 1 的工具融合**

mode-balanced (50% positive, 50% negative)

### 3.5.1 是否做的判断

如果时间充裕(Week 5 之前完成 Sub 1-4 + Sub 6),才做这个。否则跳过。

### 3.5.2 测试什么

工具间(SIRIUS vs CFM-ID)结论不一致时的 verifier 处理策略。

### 3.5.3 设计

- 50 条 spectrum,故意挑 SIRIUS 和 CFM-ID 给出不一致候选的
- 测试两种处理策略:
    - "LLM 仲裁":naive orchestrator 让 LLM 选哪个工具的结论
    - "Verifier escalate":Layer 2 检测到不一致,标记 needs_human_review

### 3.5.4 评估指标

- 各策略的最终 top-1 accuracy
- Verifier 检测到的不一致案例中,真实不一致的比例(precision)
- 不一致中应该选哪个工具结论的概率分析

### 3.5.5 为什么优先级低

这个子集的 finding 偏工程,不如 Sub-3 / Sub-4 / Sub-6 直接展示 verifier 价值。如果时间紧,可以放 v1 paper。

---

### 3.6 Sub-6: MetAgent-Bench-BiologicalContext

**全新设计,测试 Stage 2(化合物 → 生物学解释)**

**这是 MSAgent 完全没碰的维度,也是你工作的真正差异化体现。**

### 3.6.1 测试什么

给定一个已鉴定的化合物(SMILES + InChIKey),测试系统能否产出准确、可信的生物学语境化解释。

具体测试 LLM 在以下 6 个 Stage 2 子任务上的可靠性:

1. **通路归属:** 该化合物参与哪些 KEGG / Reactome 通路
2. **通路上下游:** 该化合物的 metabolic neighbours
3. **组织/物种特异性:** 该化合物主要在哪些组织/物种中富集
4. **疾病关联:** 该化合物跟哪些疾病相关
5. **功能分类:** 该化合物属于哪个化学/功能类别
6. **跨化合物推理:** 多化合物联合分析(同一通路的代谢物共现)

### 3.6.2 数据规模

100-150 条化合物。**注意:这个子集不需要 spectrum,只需要化合物本身。**

化合物来源:从 Sub-1 / Sub-2 中已知鉴定的化合物里选(确保质量),但**只用化合物身份信息**,跳过鉴定阶段直接测 Stage 2。

### 3.6.3 Ground truth 来源(全部自动获取)

| 子任务 | Ground truth 来源 | 工具 |
| --- | --- | --- |
| 通路归属 | KEGG + Reactome + RaMP-DB | RaMP-DB SQL query |
| 通路上下游 | KEGG reaction graph | RaMP-DB neighbour query |
| 组织富集 | HMDB tissue_locations | fetch_metabolite_info |
| 疾病关联 | HMDB disease_associations | fetch_metabolite_info |
| 功能分类 | ClassyFire | ClassyFire API |
| 跨化合物推理 | RaMP-DB co-occurrence | pathway_context tool |

**关键优势:全部 ground truth 可自动获取,无需人工标注。**

### 3.6.4 评估流程

```
Step 1: 选定化合物列表(100-150 个,from Sub-1/Sub-2)
Step 2: 对每个化合物,query 上述 6 个数据源,得到 ground truth biology
Step 3: Prompt LLM(naive)生成 biological narrative,内容覆盖 6 个子任务
   Prompt 示例: "Given the metabolite L-carnitine (SMILES: ...),
                please describe its biological context including
                pathways, tissue distribution, disease associations,
                and functional class."
Step 4: Verifier 提取 biological claims(主要是 Type 2, Type 3)
Step 5: 比对 LLM claims 与 ground truth biology
Step 6: 计算 per-task accuracy + verifier precision/recall
```

### 3.6.5 数据格式

```json
{
  "compound_id": "MetAgent-Bench-BioContext-001",
  "compound": {
    "name": "L-carnitine",
    "smiles": "C[N+](C)(C)CC(O)CC(=O)[O-]",
    "inchikey": "PHIQHXFUZVPYII-ZCFIWIBFSA-N",
    "molecular_formula": "C7H15NO3",
    "hmdb_id": "HMDB0000062",
    "kegg_id": "C00318"
  },
  "ground_truth_biology": {
    "kegg_pathways": ["hsa00071", "hsa01100"],
    "reactome_pathways": ["R-HSA-200425"],
    "hmdb_tissue_locations": ["Liver", "Skeletal muscle", "Heart"],
    "hmdb_diseases": ["Carnitine deficiency", "MCAD deficiency"],
    "classyfire_class": "Quaternary ammonium salt",
    "upstream_metabolites": ["Trimethyllysine"],
    "downstream_metabolites": ["Acetyl-L-carnitine", "Palmitoyl-L-carnitine"]
  },
  "llm_generated_narrative": "...",
  "extracted_claims": [
    {
      "claim_id": "001-bc-001",
      "claim_text": "L-carnitine participates in fatty acid β-oxidation",
      "claim_type": "pathway_attribution",
      "verifier_verdict": "supported",
      "ground_truth_match": true,
      "evidence": "Matches KEGG hsa00071"
    },
    {
      "claim_id": "001-bc-002",
      "claim_text": "L-carnitine is highly enriched in brain tissue",
      "claim_type": "tissue_localization",
      "verifier_verdict": "contradicted",
      "ground_truth_match": false,
      "evidence": "HMDB lists Liver/Skeletal muscle/Heart as primary locations"
    }
  ]
}
```

### 3.6.6 评估指标

| 指标 | 含义 |
| --- | --- |
| Pathway claim accuracy | 通路归属正确率(KEGG/Reactome 比对) |
| Tissue claim accuracy | 组织富集正确率(HMDB 比对) |
| Disease claim accuracy | 疾病关联正确率(HMDB 比对) |
| Function classification accuracy | 化合物分类正确率(ClassyFire 比对) |
| Neighbour claim accuracy | 上下游代谢物正确率(KEGG 比对) |
| Cross-compound reasoning | 跨化合物推理质量(专家盲评 5-10 例) |
| Per-subtask hallucination rate | 6 个子任务的 (refuted+unsupported)/total |
| Verifier precision/recall on Type 3 | 在 biological claims 上 verifier 的表现 |

### 3.6.7 关键预期结果

**预期 hallucination 分布:**

```
Subtask                  | Hallucination Rate | Why
─────────────────────────────────────────────────────────────
Pathway attribution      | 15%               | LLM 训练数据有
Function classification  | 8%                | LLM 训练数据有
Tissue localization      | 35%               | LLM 容易编 / 错配
Disease association      | 30%               | LLM 容易编
Neighbour metabolites    | 40%               | LLM 训练数据稀疏
Cross-compound reasoning | 25%               | 推理难
```

**Paper 里的关键发现:**

> "We observe a stark contrast between LLM performance on identification (Sub-1: top-1 X%) and biological contextualization (Sub-6: average claim accuracy Y%). LLMs hallucinate biological claims significantly more than structural claims, with tissue localization and metabolic neighbour relationships being particularly prone to fabrication. This suggests that downstream biological interpretation, not identification itself, is the bottleneck for trustworthy MS-based metabolomics interpretation."
> 

### 3.6.8 这个子集对 paper 的战略价值

**为什么这个子集是 paper 的关键:**

1. **完全独占:** MSAgent / SIRIUS / MIST 都没测,reviewer 无法说"这事 prior work 已经做了"
2. **直接展示 verifier 价值:** Stage 2 是 LLM 幻觉重灾区,verifier 在这有大空间发挥
3. **对应代谢组学家真实需求:** 鉴定不是终点,生物学解释才是
4. **Ground truth 全自动:** 不需人工标注,数据规模可以做大
5. **可作为社区资源:** 这是 MS 领域第一个 biological contextualization benchmark

**Paper Section 4.3 (Stage 2 Biological Contextualization) 全部数据来源于此。**

---

## 4. 与 prior work 的对比矩阵

```
                | Sub-1 | Sub-2 | Sub-3 | Sub-4 | Sub-5 | Sub-6
                | Open  | Pool  | Verif | Mech  | MultT | BioCt
─────────────────────────────────────────────────────────────────
SIRIUS          |   ✓   |   ✓   |   -   |   -   |   -   |   -
MIST            |   ✓   |   ✓   |   -   |   -   |   -   |   -
GPT-4 + prompt  |   ✓   |   ✓   |   ✓   |   ✓   |   -   |   ✓
Naive (yours)   |   ✓   |   ✓   |   ✓   |   ✓   |   ✓   |   ✓
Verified (yours)|   ✓   |   ✓   |   ✓   |   ✓   |   ✓   |   ✓
MSAgent (cited) |   ◇   |   ◇   |   -   |   -   |   ◇   |   -
Cross-LLM       |   -   |   ✓   |   ✓   |   -   |   -   |   ✓

✓ : 跑实验
◇ : 引用他们 paper 报告的数字
- : 不适用
```

**说明:**

- MSAgent 数字只在 Sub-1, Sub-2, Sub-5 上引用,因为这三个子集设计与 MSAgent-Bench 兼容
- Sub-3, Sub-4, Sub-6 上 MSAgent 没法对比(他们没有 verifier 也没有 Stage 2 评估),paper 里写明
- Cross-LLM 实验在 Sub-2, Sub-3, Sub-6 做(这三个对 verifier 价值最敏感)
- **Sub-6 上 GPT-4 baseline 必跑**——因为 reviewer 一定会问"会不会换 GPT-4 就不出现 Stage 2 幻觉"

---

## 5. 计算资源估算

### 5.1 单 method 在每个子集上的预估耗时

| Method | 单条耗时 | Sub-1 (250) | Sub-2 (250×4=1000) | Sub-3 (40) | Sub-4 (60) | Sub-5 (50) | Sub-6 (120) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SIRIUS | 30s | 2h | - | - | - | - | - |
| MIST | 5s | 0.4h | - | - | - | - | - |
| GPT-4 prompt | 30s | 2h | 8h | 0.3h | 0.5h | - | 1h |
| Naive (yours) | 5min | 21h | 83h | 3h | 5h | 4h | 10h |
| Verified (yours) | 8min | 33h | 133h | 5h | 8h | 7h | 16h |
| Cross-LLM × 3 | 8min | - | 250h | 16h | - | - | 48h |

**总计算时间:** 约 **675 小时 (~28 天连续运行)**

**Sub-6 增加耗时约 75 小时,但因为不需要 spectrum 处理,其中大部分是 LLM 调用,可以大量并发,实际墙钟时间增加约 1-2 天。**

### 5.2 实际运行策略

不可能 28 天串行运行。策略:

- **GPU 服务器 24/7 运行,夜里跑 batch**
- **优先级排序:** Sub-3 > Sub-2 > Sub-6 > Sub-1 > Sub-4 > Sub-5
- **可并行:** Sub-1 SIRIUS 和 Sub-3 verifier 可同时跑(不同机器/进程);Sub-6 完全无 spectrum 依赖,可独立并发跑
- **抽样:** Cross-LLM 不全跑,Sub-2 只跑 50 条 × 4 levels(节省 80%)

按这个策略,实际墙钟时间 **~12 天**(比 v1 估计多 2 天)。

### 5.3 LLM API 成本估算

| 实验 | LLM calls | 单次成本 | 总成本 |
| --- | --- | --- | --- |
| Naive Sub-1 | 250 | MiniMax ~$0.005 | $1.25 |
| Verified Sub-1 | 250 × 5 stages | MiniMax | $6.25 |
| Naive Sub-2 | 1000 | MiniMax | $5 |
| Verified Sub-2 | 1000 × 5 | MiniMax | $25 |
| **Naive Sub-6** | **120** | **MiniMax** | **$0.6** |
| **Verified Sub-6** | **120 × 5** | **MiniMax** | **$3** |
| Cross-LLM (GPT-4) | (250 + 120) × 5 | $0.05 | $92.5 |
| Cross-LLM (Claude) | (250 + 120) × 5 | $0.04 | $74 |

**总 LLM 成本:** ~$210-260。略超原预算,在合理范围。

---

## 6. 构建时间表

```
Week 2 (本周):
├─ 写本文档 v2 (你 + 我,2-3 小时)
└─ 跟 PI 确认 benchmark 设计 (会议 30min)

Week 3:
├─ MassBank RIKEN 下载 + 筛选脚本 (session, 1 天)
├─ Sub-1 (Open) 数据构建 + 验证 (session + 你, 2 天)
└─ Sub-2 (Pool) 候选池生成脚本 (session, 2 天)

Week 4:
├─ Sub-2 (Pool) 数据构建完成 (session, 2 天)
├─ Sub-3 (Verification) 数据准备 (从 Sub-1 抽,run naive orchestrator)
├─ Sub-3 抽样集人工标注 (你 + 本科生, 3 小时各)
└─ Sub-6 (BiologicalContext) 数据构建 (session, 2 天)
   - 化合物列表筛选(满足 HMDB+KEGG+ClassyFire 全覆盖)
   - 自动 ground truth 提取
   - LLM narrative 生成

Week 5:
├─ Sub-4 (Mechanism) 文献调研 + 数据构建 (你 + session, 3 天)
├─ Sub-6 完成验证 + 跨化合物推理子任务 (1 天)
└─ Sub-5 (MultiTool, 可选) (session, 2 天)
```

**总构建时间:** 约 **2.5 周**,与 benchmark 实验本身的运行时间重叠。

---

## 7. 数据 release 策略

### 7.1 开源时机

Paper 接收后立即 release。

bioRxiv 投稿时同步 release benchmark dataset(增加 paper 影响力)。

### 7.2 Release 内容

```
metagent-bench/
├── README.md
├── LICENSE (CC-BY-4.0)
├── data/
│   ├── sub1_open.jsonl              (250 records)
│   ├── sub2_pool.jsonl              (250 × 4 levels)
│   ├── sub3_verification.jsonl      (40 records + annotations)
│   ├── sub4_mechanism.jsonl         (60 records)
│   ├── sub5_multitool.jsonl         (50 records, optional)
│   └── sub6_biological_context.jsonl (120 records)
├── ground_truth/
│   ├── sub3_human_annotations.jsonl
│   └── sub6_ground_truth_snapshot_2026-XX-XX.jsonl
├── scripts/
│   ├── load_benchmark.py            (统一 loader)
│   ├── compute_metrics.py           (统一 metric 计算)
│   ├── run_baseline.py              (baseline 运行模板)
│   └── refresh_sub6_ground_truth.py (从 KEGG/HMDB 重新抓 ground truth)
└── docs/
    └── benchmark_protocol.md        (本文档)
```

**Sub-6 特别说明:** 因为 ground truth 来自动态数据库(HMDB/KEGG 偶尔更新),release 时需提供 snapshot date 和 refresh 脚本。

### 7.3 Hosting

- **代码:** GitHub
- **数据:** Zenodo(给 DOI,可引用)
- **互联网:** 项目主页 link 到两者

---

## 8. 验证 benchmark 质量的内部 checklist

构建完成后,在 release 前 self-check:

**Sub-1 (Open):**

- [ ]  250 条全部有完整 ground truth (SMILES + InChIKey + formula)
- [ ]  化合物类 6 类都覆盖,每类 ≥ 30 条
- [ ]  至少 90% 通过 RDKit SMILES 校验

**Sub-2 (Pool):**

- [ ]  每条 spectrum 4 个 level 都有 10 个候选
- [ ]  Level 4 候选与 ground truth 的 Tanimoto 相似度 > 0.7

**Sub-3 (Verification):**

- [ ]  5-7 条抽样集 Cohen's κ > 0.7
- [ ]  自动验证 Type 1-4 与人工 spot check 一致性 > 90%

**Sub-4 (Mechanism):**

- [ ]  每条 spectrum 至少 3 个 well-documented mechanism
- [ ]  Mechanism ground truth 至少 1 个文献 PMID 支撑

**Sub-6 (BiologicalContext):**

- [ ]  120 条化合物全部有 HMDB ID + KEGG ID + ClassyFire 分类
- [ ]  每条至少 1 条 KEGG pathway 关联
- [ ]  每条至少 1 条 HMDB tissue location
- [ ]  Ground truth 抓取脚本可重复执行(检查日期标记)
- [ ]  LLM 生成的 narrative 涵盖 6 个子任务(prompt 覆盖测试)

**跨子集:**

- [ ]  spectrum_id / compound_id 全局唯一
- [ ]  ground truth 一致(同一化合物在不同子集 SMILES 必须 identical)
- [ ]  每个子集 mode 平衡 ±10%

---

## 9. 与 PI 的讨论要点

跟 PI 同步时,重点说明四件事:

1. **不完全照搬 MSAgent 是策略性选择**,不是工程偷懒。理由是 MSAgent 的 Knowledge subset 粒度太粗,我们的 Sub-3/Sub-4 更精细。
2. **数据规模 600-850 条与 MSAgent 量级相当**(略多),审稿人无法用"数据不够"挑刺。
3. **Sub-3/Sub-4/Sub-6 是新贡献,可作为社区资源 release**,paper 加分项。
4. **Sub-6 是 paper 战略层面的关键** —— 它把工作定位从"鉴定工具"提升到"鉴定 + 生物学解释",直接拉开跟 MSAgent 的差距。建议 PI 重点关注这个子集的设计。

PI 可能的反对意见和应对:

- **"为什么不直接用 MSAgent 的 benchmark?"**
→ 他们没 release 数据,我们必须自建。同时我们扩展了 verifier 评估和 Stage 2 评估维度。
- **"600+ 条够吗?能 NM 接收吗?"**
→ MSAgent 自己也 500 条,他们的 paper 设计不会被 NM 嫌少。GeneAgent (NM 2024) 1106 条,但他们任务定义比我们简单。我们多 6 个子集,综合数据规模实际更大。
- **"Sub-4 文献调研工作量是不是太大?"**
→ 60 条,每条挑 3 个 mechanism,每个 mechanism 10 分钟,共 30 小时。可以分摊给学生或自己 1 周做完。
- **"Sub-6 跟 Sub-3 的 Type 3 重复吗?"**
→ 不重复。Sub-3 测的是 verifier 在所有 5 类 claim 上的能力(spectrum-driven narrative);Sub-6 测的是单独 Stage 2 任务的 LLM 表现(compound-driven narrative)。两者评估对象不同。

---

## 10. 风险与备选方案

| 风险 | 概率 | 应对 |
| --- | --- | --- |
| MassBank RIKEN 筛选后符合条件的不到 250 条 | 低 | 扩展到 MassBank 其他 contributor 子集 |
| Sub-2 候选池构建中 isomer 抽样困难 | 中 | 用 RDKit 生成虚拟同分异构体作 decoy |
| Sub-3 人工标注 Cohen's κ < 0.7 | 中 | 重新培训标注者,统一标注指南 |
| Sub-4 文献 ground truth 找不齐 | 中 | 减少到 40 条,化合物类减少为 4 类 |
| Sub-6 部分化合物 HMDB/KEGG 信息不全 | 中 | 放宽筛选(允许部分子任务 N/A),记录覆盖率 |
| Sub-6 ground truth 数据库版本变化 | 低 | 在 release 时 freeze snapshot,提供日期 |
| 计算资源不够,跑不完 675 小时 | 高 | 抽样 30%,paper 里说明 |
| MSAgent 突然 release 他们的 benchmark | 低 | 加跑 head-to-head 对比章节 |

---

## 11. 后续动作清单

```
Step 1 (本周): 跟 PI 同步本文档 v2,获取确认
Step 2 (本周): 派 session 构建 MassBank 数据加载脚本
Step 3 (Week 3): 构建 Sub-1
Step 4 (Week 3-4): 构建 Sub-2
Step 5 (Week 4): 构建 Sub-3 + 启动人工标注 + 构建 Sub-6
Step 6 (Week 5): 构建 Sub-4 + 完成 Sub-6
Step 7 (Week 5,可选): 构建 Sub-5
Step 8 (Week 6 起): 跑全部 benchmark 实验
```

---

## 12. Change log

| 日期 | 版本 | 变更 | 作者 |
| --- | --- | --- | --- |
| 2026-04-28 | v1 | Initial draft (5 个子集) | [you] |
| 2026-04-28 | v2 | 加入 Sub-6 BiologicalContext;调整设计哲学为 Two-Stage;更新对比矩阵、计算资源、时间表、checklist | [you] |
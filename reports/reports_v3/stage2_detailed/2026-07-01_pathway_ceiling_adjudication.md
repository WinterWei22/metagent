# Stage 2 pathway 上限诊断 + 23 错逐条裁定（工具 / LLM / 测量）

> 日期：2026-07-01 · run `v4_bench_eval_cascade_fix_20260629`（纯 Stage 2, perfect-id, 112 task）
> 诊断脚本：`scripts/metagent/diagnose_pathway_ceiling.py`（零 LLM，gold vs 5 工具输出 + LLM alternatives）
> matcher：SapBERT cosine ≥ 0.80 **或** token 子集/substring（`concord/lookup/pathway_name_matcher.py`）
> ⚠ 下面的三分类是**人工裁定**（在自动"gold 在不在工具里"之上），有主观；严格口径不改，仅透明并列。
> ⚠ **防指标游戏**：不放宽 threshold。父子/相邻是否计分 = 评测口径决策，需人类 sign-off，本文只报区间不改 headline。

---

## 1. 自动硬数字
112 task，raw 做错 **23**（严格命中 **79.5%**）。matcher 自动拆：
- gold 在工具输出里、没选成 primary：**15**（其中 8 个在 LLM 自己的 alternatives 里）
- gold 工具里找不到：**8**

## 2. 23 错逐条裁定（人工）

| # | gold | raw 预测 | 工具是否给出 | 裁定 |
|---|---|---|---|---|
| 1 | ABC transporters in lipid homeostasis | Malate-aspartate shuttle | 否 | **真错/工具上限**（转运体非富集通路） |
| 2 | ABC transporters in lipid homeostasis | C21-steroid hormone... | 是* | **真错/工具上限** |
| 3 | Acyl chain remodeling of CL | Amino sugar... | 否 | **工具上限**（超细粒度脂质重塑） |
| 4 | Acyl chain remodeling of DAG and TAG | Oligodendrocyte... | 否 | **工具上限**（工具给了无关项） |
| 5 | Acyl chain remodeling of DAG and TAG | Glycerolipid metabolism | 是 | 测量·父子（TAG 重塑 ⊂ 甘油脂代谢） |
| 6 | Glycine, serine and threonine metabolism | Methionine Metabolism | 是 | **真错/选择**（同为氨基酸但不同通路） |
| 7 | 7-oxo-C and 7-beta-HC pathways | Steroid biosynthesis | 否 | 测量·相邻（氧固醇 vs 类固醇合成） |
| 8 | 7-oxo-C and 7-beta-HC pathways | Bile acid biosynthesis | 否 | 测量·相邻（氧固醇 bile-acid 邻近） |
| 9 | Celecoxib Action Pathway | Arachidonic acid metabolism | 是 | 测量·同义（Celecoxib 作用于 COX/花生四烯酸位点） |
| 10 | Eicosanoid synthesis | Arachidonic acid metabolism | 是 | **测量·同义**（类花生酸=花生四烯酸衍生，同位点） |
| 11 | Eicosanoid synthesis | Arachidonic acid metabolism | 是 | **测量·同义** |
| 12 | Eicosanoid synthesis | Arachidonic acid metabolism | 是 | **测量·同义** |
| 13 | Amino Sugar Metabolism | Galactose metabolism | 是 | 测量·相邻（同为糖代谢，distinct） |
| 14 | 5-Phosphoribose 1-diphosphate biosynthesis | Pentose phosphate pathway | 是 | 测量·父子（PRPP 生物合成 ⊂/邻 PPP） |
| 15 | 5-Phosphoribose 1-diphosphate biosynthesis | Pentose phosphate pathway | 是 | 测量·父子 |
| 16 | Metabolism of amino acids and derivatives | Tyrosine metabolism | 是 | 测量·父子（gold 是宽父，raw 是具体子） |
| 17 | Sulfatase and aromatase pathway | Steroid hormone biosynthesis | 是 | 测量·相邻（sulfatase/aromatase ∈ 类固醇激素合成） |
| 18 | Steroid biosynthesis | Androgen and estrogen biosynthesis | 是 | 测量·相邻（同类固醇） |
| 19 | **Biological oxidations** | Thromboxane signalling | 是(rank-0) | **真错/选择**（工具 rank-0 FDR 2.9e-15,LLM 选窄) |
| 20 | **Biological oxidations** | Arachidonic acid metabolism | 是(rank-0) | **真错/选择**（可救） |
| 21 | **Biological oxidations** | Arachidonic acid metabolism | 是(rank-0) | **真错/选择**（可救） |
| 22 | Biological oxidations | （空） | 是 | abstain（raw 空） |
| 23 | Histidine metabolism | （空） | 是 | abstain（raw 空） |

\* #2 gold 名在工具里 matcher 命中但语义存疑,归真错。

## 3. 分类汇总（人工裁定，约数）

| 类别 | n | 性质 |
|---|---:|---|
| **测量·同义**（同位点，跨库异名，defensible） | **4**（#9-12） | 严格口径冤枉,应计分 |
| **测量·父子/相邻**（debatable，需口径决策） | **8**（#5,7,8,13,14,15,16,17,18） | 计不计分是评测政策 |
| **真错·LLM 选择**（工具给了、可救） | **3-4**（#19,20,21,+6） | pathway critic 目标 |
| **真错/工具上限**（换工具才行） | **3-4**（#1,2,3,4） | 硬 ceiling |
| **abstain**（raw 空） | **2**（#22,23） | pipeline |

## 4. 真实准确率区间（⚠ 2026-07-01 用 RaMP 权威资源复核后重大更正）

**更正**：§3 里"测量·同义 defensible → 83%"是**我的生物学判断,不是数据库事实**。用 RaMP 权威判等表 `pathway_duplicates`（180 对跨库重复通路）逐一复核：

- Eicosanoid synthesis（WP167 = RAMP_P_000053516） vs Arachidonic acid metabolism（map00590 = RAMP_P_000025679）：**不在 pathway_duplicates 里 → RaMP 认定为不同通路**。
- 其余"同义/相邻"case 同样 **pathway_duplicates 命中 0**。
- （尝试用 pathway_similarity 的 metabolite 重叠量化"相关度",但 blob 解码格式未搞对,数据作废,不引用。）

**结论：没有数据库可背书的 synonym 判等能合法把 headline 抬过 79.5%。** RaMP 把这些当**不同通路**——系统答了"生物学相邻但不同"的通路,严格看是**真 miss,不是 matcher 冤枉**。

| 口径 | 命中 | 准确率 | 依据 |
|---|---:|---:|---|
| **严格 semantic（诚实 headline）** | 89/112 | **79.5%** | 现行 |
| ~~+ 测量·同义~~ | ~~93/112~~ | ~~83.0%~~ | **撤回**：RaMP 不认这些为同义 |
| （"生物学相邻"计分，仅我判断，RaMP 不背书） | ≤101/112 | ≤90.2% | **非 defensible,不可进 headline** |

## 5. 结论 → 各问归位（复核后）
- **#1 工具上限**：真·硬 ceiling ~3-4 task（≈3%）。不是主因。
- **#2 LLM 选择**：**唯一干净可救的 ~3-4 task**——Biological oxidations 工具 **rank-0**、在 LLM alternatives 里、却没选成 primary（gold 确在工具里，非同义争议）→ **pathway critic 的靶子**。
- **#5 测量**：**被我高估了**。RaMP 权威复核后,多数"测量"case 其实是系统选了**相邻但不同**的通路（真 miss）。真实水平就在 **79.5% 附近**,不是 83–90%。
- #3 / #4：拖累 feedback,不封顶 raw。

## 6. 下一步（复核后修正）
- **A（修同义 matcher）没有合法实质**：RaMP 不背书任何 synonym 判等 → **不做 curated synonym（那是往测试集凑 + 放宽标准）**。诚实 headline 保持 79.5%。
- **直接做 B（pathway critic）**：唯一干净可救的是 #19-21 那 3-4 个"工具 rank-0 却没选中"的真选择失误。这才是真正提升系统、且无指标游戏风险的杠杆。
- 可选透明二级镜：若要报"生物学相邻"宽松数,必须显式标注"我的判断/RaMP 不背书",绝不进 headline。

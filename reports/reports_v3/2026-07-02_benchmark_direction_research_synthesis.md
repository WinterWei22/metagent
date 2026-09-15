# Benchmark 方向调研综合:需求 · 数据 · 相关工作 · 定位

> 日期：2026-07-02 · 分支 `metagent-v3-benchmark`
> 目的:为 MetAgent 投稿级 benchmark 定方向。综合 4 路调研(动机/数据×2/竞品)+ 本 session 实测。
> 诚实标注：[确认]=页面/REST/论文核实；[评估]=基于证据的判断；相关工作部分含本 session 早先竞品调研(专职 related-work agent 未交付完整报告)。

---

## 0. 一句话结论
**留在人类**(MetAgent 工具是人类通路库,微生物用不了)。**gold 锚在"已知突变/缺陷酶"上**(非循环),数据有 **3 个开放可下载源、~100+ 任务**。动机("代谢物→机制是瓶颈、富集不足")有同行评议硬证据。niche(agentic 代谢物→通路/机制、真实扰动 gold 的基准)[评估]为**空**。

---

## 1. 需求 / 动机（可引硬证据）
"从差异代谢物到机制是瓶颈,且富集工具本质不足":
- **Nguyen 2024 (Brief Bioinform 25(6):bbae498)**:代谢物列表"**fail to reveal the underlying mechanism**";"**roughly half** of known compounds can be found in pathway databases"。
- **Wieder 2021 (PLoS Comput Biol 17(9):e1009105,ORA 经典批判)**:"**4% misidentification**"就翻转通路显著性;换库(KEGG/Reactome/BioCyc)"**vastly different results**";ORA 不看拓扑;加一个化合物就大变。
- **Tsouka & Masoodi 2023 (Biomolecules 13(2):244)**:通路分析"not well standardized",边界"not harmonized",独立假设"does not reflect the reality",hub 化合物盖过其它。
- **Briefings 2023 benchmark (bbac553)**:"biological interpretation... remains a **daunting task**","**urgent need to benchmark** these approaches"(= 无标准基准)。

⚠ **双刃(必须正视)**:这些批判同时**指向 MetAgent 自己**——它编排的正是 ORA/富集工具,就继承了"库不全、误识别敏感、忽略拓扑"的天花板。与本 session 实测(pathway raw 79.5% 近上限、cascade/verifier/critic 都提不动)完全对上。**论文故事不能是"我们的富集 agent 更准",而应是"我们量化了富集-agent 的天花板,并指出突破方向(验证 + 机制/网络)"。**

## 2. 数据源（人类、非循环、可及）—— 3 支柱 + 二线

| 优先 | 源 | 规模/标签 | 可及性 | gold |
|---|---|---|---|---|
| **1 锚（规模）** | **CCLE metabolomics + DepMap 突变** | 928 系×225 代谢物,join `OmicsSomaticMutations` | [确认] `CCLE_metabolomics_20190502.csv` DepMap 直下,低摩擦 | IDH→2-HG、SDH→琥珀酸、FH→富马酸 |
| **2 患者硬 gold** | **MTBLS3873**（胶质瘤 NMR） | 62 IDH-mut vs 39 WT,2-HG | [确认] MetaboLights 开放下载 | IDH→2-HG/TCA |
| **3 多病 IEM** | **GMDP**（lccl.shinyapps.io/GMDP，DeBerardinis） | 血浆 474 人 / **65 单基因病** | [确认] shiny 可下载,开放 | 每病=缺陷酶 |
| 二线 | PPGL(395,SDHx→琥珀酸)、AML Figshare(51,IDH)、FH-RCC(77)、Zampieri 药物图谱(1520 药,HMGCR/DHODH 单靶) | — | 多为论文补充表 | 教科书级 |
| gold key | IEMbase / HMDB disease / OMIM+Sahoo / RaMP `getPathwayFromAnalyte` / Reactome ContentService | — | 除 IEMbase 外可批量 | 缺陷酶→通路映射 |

**[评估] 合计 ~100+ 非循环人类任务**,工具匹配。
⚠ **循环 caveat**:酶→通路映射用 **Reactome/RaMP**;**不要用 mummichog 自己的 MFN 推 gold 再打分 mummichog**(重引循环)。
**待核实[评估]**:CCLE 代谢∩突变重叠数、ST000548 样本标签、Zampieri accession、GMDP 下载粒度、RaMP/Reactome 路由。

## 3. 相关工作 & niche
**代谢组富集方法怎么验证**:[评估] 多用"已知扰动 case study / 模拟数据 / 文献回收",无统一标准基准(Briefings 2023 明说"urgent need to benchmark")。
**LLM/生物 agent 怎么评测**(本 session 竞品调研):
- **GeneAgent (Nat Methods 2025)**:gene set 分析,专家评(92% 决策对)+ ROUGE-L vs GPT-4(+30%);**gene 不是代谢物**。
- **MSAgent (bioRxiv 2026)**:MS 代谢组 50+ 工具 agent;评测细节未获全文。
- **MetaBench (arXiv 2510.14944)**:5 类**能力**测试(knowledge/understanding/grounding/reasoning/research),8000 题;**非 agentic 代谢物→通路解释任务**。
- **OriGene (bioRxiv 2025)**:target discovery,TRQA QA(1915 QA)。
**[评估] niche 空**:没有"**agentic 代谢物列表→被扰动通路/机制、用真实扰动(突变/KO)当非循环 gold**"的基准。这正是我们能占的空,且是"基准即贡献"(cf. MetaBench)。

## 4. 定位建议
- **任务**:人类差异代谢物 → 被扰动酶/通路(+ 机制,若走 Tier-2)。
- **gold**:已知突变/缺陷酶(CCLE/患者队列/IEM),非循环。
- **卖点(诚实)**:①首个真实-扰动锚定、非循环的代谢组解释基准(填 niche);②用它**量化 agentic 富集解释的能力与天花板**(呼应 Wieder/Nguyen 的 ORA 批判);③(若做 Tier-2)机制/反应级解释 + 稠密可核验 verifier。
- **不要讲**:"我们的富集 agent 比工具更准"(数据不支持,且被 ORA 批判反噬)。

## 5. 下一步
1. 核实 §2 的 5 个[评估]点。
2. **CCLE 可解性探针**:下 CCLE 代谢组 + DepMap 突变,验 IDH-mut 系的 2-HG 是否干净显著(像 IMPC/MSUD 那样)——确认规模锚可用。
3. 定 task schema + gold 映射(Reactome/RaMP,独立于打分器)。
4. framing 抉择(用户已倾向"人类核心"):CCLE(规模)+ MTBLS3873(患者硬 gold)+ GMDP(多病)三支柱起步。

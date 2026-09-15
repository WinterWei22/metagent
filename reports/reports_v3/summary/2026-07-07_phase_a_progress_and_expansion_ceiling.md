# Phase A 进展 + 零下载扩充上限分析

> 日期:2026-07-07 · spec `docs/decisions/2026-07-07_phase_a_benchmark_publication_grade_spec.md`
> 状态:A1(自动分级 matcher)+ 统计 完成;A2 零下载扩充**已达上限**;A4 发布待办

---

## 1. A1 自动分级 matcher(完成,已验证)

把"预测通路对/错"从人工判改为**确定性代码**:

- `scripts/metagent/pathway_match_rubric.py` — tier ∈ {EXACT, PARENT_CHILD, ADJACENT, MISS}
  - EXACT:双向全集代谢物包含 ≥ 0.9
  - PARENT_CHILD:max 包含 ≥ 0.7
  - **ADJACENT:共享 ≥ 2 个"特异"代谢物(每个出现在 ≤ 40 通路,hub 排除)** — propanoate↔BCAA 经 methylmalonate、phe↔tyr 经 fumarylacetoacetate;证据可列出
  - strict = EXACT+PARENT_CHILD;lenient 再加 ADJACENT;**分母永不剔任务**
- gold 锚 `data/benchmark/pathway_registry/gold_registry.json`:9 gold 通路跨源(kegg/hmdb/reactome/wiki,pfocr+disease 变体排除)union;predicted 吸附到 gold 概念
- 阈值按 gold-gold 重叠校准(相邻对共享 ≥3 特异物,下一对 ≤1,干净间隙);hub 过滤 + 名匹配取最近单通路是关键坑
- `score_perturbation_bench.py`(打分)+ `bench_stats.py`(bootstrap CI + 分家族 + tier 分布)
- 15 单测 + 集成测试绿

**权威可复现结果(v1.3 19 任务、3 seed)**:

| 指标 | 值 | 95% bootstrap CI |
|---|---:|---|
| **strict** | **61.4%** | 43.9–79.0% |
| **lenient** | **70.2%** | 52.6–86.0% |
| seed 波动(strict) | 52.6–68.4% | — |
| tier 分布 | exact 34 / parent_child 1 / adjacent 5 / miss 17 | — |

诚实要点:
- 自动判**比旧人工读更保守**(strict 61.4% vs 人工 68.4%):把"预测天冬/谷氨酸代谢当 TCA"正确判 miss(人工曾宽松算对)。
- **seed 间真实波动 ~16pp**(52.6–68.4%),非旧报告"零方差 13/13/13"(那是 per-task 二值人工判)。
- CI 宽(N=19)→ 印证需扩 N。

---

## 2. A2 零下载扩充:已达上限(诚实结论)

**核心约束**:非循环任务**必须有真实实测差异代谢物**。Sahoo/Recon 只给"缺陷酶→通路"映射(gold),不给实测代谢物;用它生成输入 = 又循环。故零下载只能靠**已下载的实测队列**。

**逐队列榨取结果**:

| 队列 | 已用 | 还能榨? |
|---|---|---|
| Miller 2015 ESM1(实测 z-score,21+ IEM) | 9 病 | **基本榨干**。剩余可解病种:3MCC(亮氨酸,✅ 已加,biomarker z=5.7/7.1/8.2)是唯一干净新任务;OTC(n=17 但 biomarker 是咖啡因/肠道菌混杂,不可解)、GAMT(胍基乙酸未覆盖,弃)、其余 n≤2 弱功效(HMG-CoA lyase / thymidine phosphorylase / LPI) |
| UCD(Genet Med 2019) | 4 酶(ASS1/ASL/OTC/ARG1) | mmc3 仅这 4 酶,无 CPS1/NAGS;per-patient 拆分=相关重复(循环刷 N,不可取) |
| mma_pa 队列 | (Miller 覆盖) | Tables S4-S6 = PA/MMA/cblC,全丙酸家族(已覆盖)+ 未靶向 feature 格式 |
| PPGL(Richter 2019) | 4 基因型(SDHx/FH/IDH/MDH2→TCA) | 其余基因型(RET/NF1/VHL)无干净单通路 gold |
| PKU / tyrosinemia / galactosemia | 各 1(galactose 已否决) | 已榨 |

**零下载上限 = 20 任务**(v1.3 的 19 + 3MCC)。`metagent_bench_v14.jsonl`。

**结论**:达到 N=40 **必须新下载**覆盖新家族的实测队列。这是一个真实的领域约束(干净非循环人类 IEM 队列稀缺 + 访问碎片化),不是工程缺陷。

---

## 3. 达到 N=40 的下载目标(供"我搜 + 你浏览器下载")

需 ~20 个新任务,覆盖当前缺的家族。优先级(实测 plasma/serum/urine、有诊断 biomarker、非循环酶 gold):

**A. 高价值新家族(每个若成 1-3 任务)**
1. **嘌呤代谢** — ADA-SCID(腺苷/脱氧腺苷↑)、黄嘌呤尿(XDH,黄嘌呤↑)、Lesch-Nyhan(HPRT,尿酸/次黄嘌呤)
2. **嘧啶代谢** — DPD 缺陷(尿嘧啶/胸腺嘧啶↑)、MNGIE(thymidine phosphorylase,胸苷/脱氧尿苷↑)
3. **鞘脂/溶酶体** — Fabry(lyso-Gb3)、Gaucher(glucosylsphingosine)、Niemann-Pick(lyso-SM)
4. **脂肪酸氧化(好 n)** — LCHAD / CPT-II / X-ALD(VLCFA)—— 找 n>5 的队列(Miller 的 MCAD/VLCAD n=2 太弱)
5. **肌酸** — GAMT/AGAT(胍基乙酸)—— 需明确测胍基乙酸的队列
6. **甘氨酸** — 非酮性高甘氨酸血症(GLDC,CSF/血浆甘氨酸)
7. **糖代谢(干净)** — 经典半乳糖血症(GALT,血浆 galactose-1-P/galactitol,避开 DBS)、遗传性果糖不耐(aldolase B)

**B. 最可及的批量源**
- **Metabolomics Workbench** REST(部分可下 mwTab):**ST002750(n=44 IEM)** 等大 n 研究;earlier 探明摩擦=mwTab 解析 + study 大小不一
- **已发表 IEM 代谢组学论文补充表**(JIMD / Mol Genet Metab / Metabolites 期刊)——与已用的 PPGL/UCD/PKU/tyrosinemia 同模式,supplementary xlsx 直接可用

**C. 备选(非人类但干净,若人类不够)**
- 微生物 KO(酵母 4678 / E.coli 3807 单基因缺失代谢组)—— 非人类,但非循环 + 大 N + 干净;可作独立 stratum

**建议**:先攻 A 组前 4 个新家族(嘌呤/嘧啶/鞘脂/FAO 好 n),每个补 2-4 任务 → +10-15,配合已有 20 → 30-35;再用 B 组 MW 大 n 研究补齐到 40。

---

## 3b. 新家族扩充目标(5 路研究代理,2026-07-07)

零下载虽榨干,但**开放获取论文补充**里有大量新家族数据,且多数可经 **Europe PMC / PubChem REST 自动抓取**(实测 MNGIE 的 .xls 已自动抓到并建成任务,无需浏览器下载)。关键摄取配方:untargeted 研究按 **VIP(论文自身重要性指标)排序 + 限 KEGG 注释 + p<0.01** 选 top ~12,诊断 biomarker 会浮到顶部(MNGIE 的 thymidine/deoxyuridine/thymine 排前 3),避免 top-by-FC 被脂质噪音淹没(galactosemia 教训)。

| # | 新家族 | 疾病/酶 | 来源 | 数据 | gold KEGG | 可及性 |
|---|---|---|---|---|---|---|
| 1 | **嘧啶** | MNGIE / TYMP | IJMS 2025, PMC12470823 | .xls(名+FC+p+KEGG) | map00240 | ✅ 自动抓,**已建+在跑** |
| 2 | **脂肪酸氧化** | VLCADD / ACADVL(n=15) | Metabolites 2023, PMC10301765 | s001.zip | map00071 | ✅ Europe PMC 可抓 |
| 2b | 脂肪酸氧化 | MCADD / ACADM(n=14) | IJMS 2023, PMC10253666 | 补充表 | map00071 | ⚠ 需核 |
| 3 | **嘌呤** | Lesch-Nyhan / HPRT | Orphanet JRD 2015, PMC4320826 | 开放 PDF(per-patient) | map00230 | ⚠ 需 PDF 解析 |
| 4 | **碳水/半乳糖** | 经典半乳糖血症 / GALT(189 患者!) | Mol Genet Metab 2019, PMC6414239 | 补充表 | map00052 | ⚠ 补充可及 |
| 5 | **过氧化物酶体** | Zellweger / PEX(>650 代谢物) | Genet Med 2018, PMC7605708 | 补充 | hsa04146/map00071 | ⚠ 补充可及 |
| 6 | **类固醇生成** | CAH / CYP21A2(84-117 患者) | PMC7264133 | xlsx | map00140 | ⚠ 补充可及 |
| 7 | **糖原** | GSD-I / G6PC(n=14) | JIMD, PMC9299190 | Appendix S1 | map00010 | ⚠ 补充可及 |
| 8 | 鞘脂/溶酶体 | Fabry / GLA(66 患者,188-panel) | J Pers Med 2021, PMC8468728 | 补充(86 差异物) | map00600 | ⚠ MDPI 可能 403,需浏览器 |
| (弃) | 鞘脂窄靶向 | Pettazzoni 溶酶鞘脂 5-panel | PLoS ONE 2017 | docx | map00600 | 输入太窄(全鞘脂),价值低 |

**注**:MW/MetaboLights 仓库级 IEM 数据稀缺(ST002750 = MSUD 已有 + 空表;唯一仓库命中 MTBLS12973 是 X-ALD 类器官非患者、未发表)。**故走"开放获取论文补充"路线**,多数自动抓取。gold 注册表已扩加 map00240/map00230/map00071(嘧啶/嘌呤/FAO)。

**实测数据质量约束(2026-07-07,建任务后的关键发现)**:auto-fetch 容易,但**建成干净任务受数据质量制约**。三类不可用:
- **untargeted 脂质组学**(VLCADD、Fabry):top 显著物全是复杂磷脂/氧化脂,不可解析 InChIKey **且埋掉诊断 biomarker**(VLCADD 的 C14:1 酰基肉碱不在 top 显著集)→ 不可解(galactosemia 同类)。
- **窄靶向面板**(Lesch-Nyhan 20 个嘌呤、Pettazzoni 5 个鞘脂):输入全指向 gold 通路 → **太易/近循环**,价值低。
- **biomarker 未覆盖**(CAH):61 个差异物里无类固醇 biomarker → 不可解。

**干净任务的甜点 = 广谱面板 + 好 KEGG 注释 + IEM 信号突出**(MNGIE untargeted+KEGG 注释+VIP,诊断嘧啶浮顶;Miller targeted 生化面板)。**MNGIE 是 auto-fetch 里难得的干净命中,已建成 → 21 任务**。

**到 40 的现实路径(需你浏览器下载少数付费墙广谱面板)**:
- **GALT 半乳糖**(PMC6414239,189 患者,Mol Genet Metab,**Elsevier 付费墙**,Metabolon 广谱面板)→ 碳水新家族
- **Zellweger 过氧化物酶体**(PMC7605708,Metabolon >650 命名物,广谱)→ 过氧化物酶体新家族
- **GSD-I 糖原**(PMC9299190,广谱,docx 补充)→ 糖原新家族
这三个是 Metabolon 式广谱命名面板(注释好、像 Miller),最可能建成干净任务;VLCADD/Fabry(脂质组学)、CAH(未覆盖)、Lesch-Nyhan/鞘脂(太窄)**弃**。

**当前状态**:v1.5 = **21 任务**(20 + MNGIE 嘧啶新家族),严格 **63.5%** / 宽松 **73.0%**。到 ~24-30 需上述 3 个付费墙广谱面板(你浏览器下载),我再 VIP/注释过滤建任务。

---

## 4. 待办

- **A2 续**:按 §3 下载新队列(需用户浏览器下载)→ resolve → 并入 → 跑 3 seed → 重打分
- **A4 发布包**:Datasheet for Datasets + FAIR + CC-BY-4.0(数据)/ MIT(代码)+ 公开仓库布局
- **可选**:若下载难,诚实 reframe 为"N~20-25 高质量非循环任务 + 透明记录实测数据稀缺",CI 宽如实报

---

## 5. 复现

```bash
export RAMP_DB_PATH=/data/weiwentao/llm_agent_metabolomics/ramp.sqlite
B=/data/weiwentao/llm_agent_metabolomics/bemchmark
# 打分 + scorecard
PYTHONPATH=. python scripts/metagent/bench_stats.py \
  --benchmark $B/metagent_bench_v14.jsonl \
  --runs $B/run_v13_seed1 $B/run_v13_seed2 $B/run_v13_seed3 \
  --out reports/reports_v3/scorecards/<date>_scorecard
# 单测
PYTHONPATH=. pytest tests/test_pathway_match_rubric.py tests/test_pathway_match_rubric_integration.py -q  # 15 pass
```

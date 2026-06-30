# MetAgent-Bench 数据源初步侦察报告

日期：2026-05-25  
下载根目录：`/data/weiwentao/llm_agent_metabolomics/data/landscape/`

## 1. 落袋清单

| 源 | 已落袋目录 | 已下载内容 | 大小 | License |
|---|---|---|---:|---|
| S1 Fuhrer & Sauer 2017 E. coli KO | `/data/weiwentao/llm_agent_metabolomics/data/landscape/S1_fuhrer_sauer_2017/` | Table EV1/EV2/EV4 xlsx + Table EV3 html zip | 5.1 MB | CC BY 4.0 |
| S4 Cooke 2025 simulatedPA | `/data/weiwentao/llm_agent_metabolomics/data/landscape/S4_cooke_2025/` | Zenodo code zip + Human1/Recon2.2 z-score TSV | 45 MB | code MIT; data CC BY 4.0 |
| S6 py-ssPA | `/data/weiwentao/llm_agent_metabolomics/data/landscape/S6_sspa/` | GitHub source zip + extracted tree | 40 MB extracted | GPL-3.0 |
| Huckvale 2023 KEGG benchmark | `/data/weiwentao/llm_agent_metabolomics/data/landscape/Huckvale_2023_KEGG_benchmark/` | Figshare README + ACMPP.zip | 5.2 MB | CC BY 4.0 |
| S3 ST001142 CCLE metabolomics | `/data/weiwentao/llm_agent_metabolomics/data/landscape/S3_ST001142_CCLE_IDH/` | Metabolomics Workbench mwTab text for AN001875/6/7 + metadata JSON | 2.9 MB | CC BY 4.0 |

每个目录均已写 `MANIFEST.md`，记录文件名、大小、来源 URL、license 和用途。

## 2. 核实表

| 源 | 确认 URL | License | 格式/体积 | 获取门槛 | 已下 |
|---|---|---|---|---|---|
| S1 Fuhrer & Sauer 2017 | 论文页 `https://link.springer.com/article/10.15252/msb.20167150`; supplements from `static-content.springer.com` | CC BY 4.0，论文页 Rights and permissions 明示 | xlsx + html zip；已下 5.1 MB | 无注册 | 是，补充表/metadata |
| S2 Miller 2015 IEM | PubMed `https://pubmed.ncbi.nlm.nih.gov/25875217/`; CTD 复刻数据文档 `https://search.r-project.org/CRAN/refmans/CTD/html/Miller2015.html` | 临床原始/补充数据再利用 license 未完全明确；CTD 包另行确认 | 论文补充 `jimd1029-sup-0001.xls`；CTD 文档称 1203 features x 186 plasma samples | 🔴 临床数据，需人工确认再利用边界 | 否 |
| S2 Coene 2018 IEM | Springer DOI `https://doi.org/10.1007/s10545-017-0131-6` | 未找到公共 deposit license | 未找到公开矩阵 | 🔴 临床；需人工确认 | 否 |
| S2 Bonte 2019 IEM | PMC `https://pmc.ncbi.nlm.nih.gov/articles/PMC6950026/`; OmicsDI literature stub `https://www.omicsdi.org/dataset/biostudies-literature/S-EPMC6950026` | PMC 文章可读；未见可下载矩阵 license | OmicsDI 是文献记录，不是数据 deposit | 🔴 临床；未找到矩阵 | 否 |
| S3 ST001142 CCLE+IDH/Li 2019 | MW study `https://www.metabolomicsworkbench.org/data/DRCCMetadata.php?StudyID=ST001142`; DOI `https://dx.doi.org/10.21228/M82677` | CC BY 4.0，MW REST summary | LC-MS mwTab text；928 cell lines, 124 polar + 101 lipid species；raw WIFF available but未下 | 无注册；raw 大文件未拉 | 是，mwTab + metadata |
| S3 ccRCC Reznik/Hakimi 2016 | PMC `https://pmc.ncbi.nlm.nih.gov/articles/PMC4809063/` | PMC author manuscript/Elsevier supplement license 需人工确认 | Supplement 2 xlsx 4.1 MB 等；138 paired ccRCC/normal, 877 metabolites | 无注册，但 license 需确认 | 否 |
| S3 Terunuma 2014 breast cancer | JCI supplement `https://www.jci.org/articles/view/71180/sd/1` | JCI supplement license 需人工确认 | supplemental data 593.75 KB | 无注册，但 license 需确认 | 否 |
| S4 Cooke 2025 | PMC page lists GitHub/Zenodo; Zenodo code `https://zenodo.org/records/14980037`; data `https://zenodo.org/records/13753914`; GitHub `https://github.com/juliette-cooke/simulatedPA` | code MIT; data CC BY 4.0 | zip 17.5 MB; TSV 27.9 MB + 1.0 MB | 无注册 | 是 |
| S6 ssPA | GitHub `https://github.com/cwieder/py-ssPA`; PyPI 包名 `sspa` | GPL-3.0 | source zip 5.1 MB，含 example data、pathway DB、download_pathways.py | 无注册；git clone 卡住，zip 成功 | 是 |
| Huckvale 2023 | PMC article and Figshare DOI `https://doi.org/10.6084/m9.figshare.24021480`; Figshare page `https://figshare.com/articles/journal_contribution/AtomColorMetabolitePathwayPredictor/24021480` | CC BY 4.0 | README 789 B; ACMPP.zip 5.36 MB；data.zip 255.8 MB；autoencoder.zip 3.44 GB | 无注册；大包按规则未下 | 是，小包 |
| RaMP-DB 2.0 | article/GitHub/API: `https://github.com/ncats/ramp-db`, `https://rampdb.nih.gov/`, API docs `https://ramp-api-alpha.ncats.io/__docs__/`; dump link in article `https://figshare.com/ndownloader/files/36760461` | open-source；具体 dump license 需按 repo 确认 | MySQL full dump + R package/API | 无注册；不下载全量 | 否，记录获取方式 |
| RefMet | MW RefMet page `https://workbench.sdsc.edu/databases/refmet/index.php` | MW terms/具体下载 license 需确认 | searchable/downloadable RefMet nomenclature DB | 无注册 | 否，记录获取方式 |
| metLinkR | ACS page lists GitHub `https://github.com/ncats/metLinkR` | GitHub license 需确认 | R package using RefMet + RaMP-DB | 无注册 | 否，记录获取方式 |

## 3. 闸门侦察结果

### S1 E. coli KO

可行，但不是“直接拿来就是 benchmark task”的状态。

已下载补充材料确认：

- `Table_EV1.xlsx`：KO strain/gene metadata。工作表维度显示 `Table EV1A` 约 `A2:H4330`，`Table EV1B` 约 `A1:BB7536`。
- `Table_EV3.zip`：不是平面矩阵，而是一个 HTML 汇总系统；包含 `index.html` 和 1,273 个 `details/data_<gene>.html`。页面里按 gene 给出 CLR hits、DIFF IONS、KEGG pathway by CLR、predicted metabolites 等。
- `Table_EV4.xlsx`：已有 putative ion annotation，表头含 `id/name/formula/mz/mod/score/rank/mzDelta/ion/TIC correl/average int/AUC/Z-cutoff`，工作表为 `negative mode` (`A1:M2192`) 和 `positive mode` (`A1:M1829`)。

初判：有“离子到 KEGG compound/name”的现成候选注释，不是完全从 m/z 白手注释；但注释是多候选、带 adduct/mod、score/rank/AUC 的 putative annotation。要构造成 hard task，需要下一步把 `Table_EV3` 的 gene-level differential ion/predicted metabolite/pathway HTML 结构化，再和 `Table_EV4` 做一对多注释置信度过滤。最大风险仍是注释歧义和“每个 KO 的 gold pathway”如何定义，不是数据不可得。

### S2 IEM

未找到 Miller/Coene/Bonte 对应的 MetaboLights `MTBLSxxxx` 或 Metabolomics Workbench `STxxxxxx` 公共 case/control deposit。

实质发现：

- Miller 2015 有论文补充表 `jimd1029-sup-0001.xls`，并被 CRAN `CTD` 包整理为 `Miller2015` 数据集；文档称 1203 metabolite features x 186 samples，其中 118 个 confirmed IEM。这个很有用，但属于临床数据再利用，license/伦理边界需要人工确认后才能下载并纳入。
- Bonte 2019 在 OmicsDI 有 `S-EPMC6950026` 文献记录，但它不是可下载原始矩阵 deposit。
- MetaboLights 搜索接口本次返回过宽结果，未能定位候选 MTBLS；网页搜索也未发现目标论文 deposit。

初判：S2 不能作为第一批自动落袋 task 源。Miller 2015 是可人工推进的候选，但要先解决补充数据 license、患者去标识化和是否可再分发。

## 4. 整体计划评估

目标约 450 task 可行，但第一阶段真实 hard task 不应押在 S2。

现实组合：

- S1 可支撑大量 hard task：理论上 >1,000 个 KO 页面有差异离子/预测代谢物/通路信号，但需要结构化和 gold-label 规则设计。若只选高置信度、机制清楚、注释唯一/高 AUC 的 KO，保守估计可以先做 100-200 个高质量 hard task。
- S3 ST001142 能补充癌症 genotype/metabolism 场景，但它是 cell-line association，不是单一扰动 KO；需要接入 mutation/IDH/CCLE annotation 后才能定义任务。先做 30-80 个更现实。
- S4 + S6 + Huckvale 足以撑 easy/synthetic 层。S4 自带 pathway simulation 和 z-score matrix；Huckvale 给 KEGG compound-pathway label；S6 提供 ssPA 方法和示例/通路库，适合作为工具调用/方法基线，不一定本身生成 gold tasks。
- S2 临床 IEM 暂时不能计入 450 的可靠来源，除非人工确认 Miller 2015 补充表可合法再用。

主要瓶颈：

1. S1 的 HTML/putative annotation 到 benchmark gold labels 的规则。
2. 代谢物 ID 统一：KEGG/RefMet/RaMP/HMDB/PubChem/Metabolon name 会混用。
3. 临床数据 license/再分发风险。
4. 癌症源的 context 标签：基因型、癌种、细胞系/样本背景要从外部 metadata 补齐。

## 5. 后续安排建议

建议串并行：

- 串行优先 S1：先做一个只读结构化侦察，把 `Table_EV3.zip` 的 1,273 个 gene detail HTML 抽出 gene、top differential ions、KEGG pathway by CLR、predicted metabolites；再用 `Table_EV4` 的 rank/AUC/KEGG id 过滤。这个决定 hard 档主干能否站稳。
- 并行推进 S4/Huckvale：直接设计 easy task schema，验证 metabolite list -> pathway 的 gold label 表达方式。
- 并行轻量推进 ST001142：只做 mwTab 到 named metabolites/sample metadata 的盘点，再决定是否接 CCLE mutation/IDH label。
- S2 暂停自动下载：请人工确认 Miller 2015 supplement/CTD 数据的 license 和再分发权限；确认后再落袋。

## 6. 卡点与需人工确认清单

- Miller 2015：`jimd1029-sup-0001.xls` 和 CRAN `CTD::Miller2015` 是否允许再分发、是否能用于 benchmark 输入/答案公开发布。
- Coene 2018、Bonte 2019：未找到公开矩阵 deposit；需要人工联系作者或确认是否只有论文内 summary。
- S1：是否接受 putative KEGG annotation 作为 gold metabolite ID；如果接受，要定唯一候选/多候选/置信阈值策略。
- ccRCC Reznik/Hakimi 2016 和 Terunuma 2014：补充表小而可得，但 license 需人工确认后再下载到 benchmark 源目录。
- RaMP-DB/RefMet/metLinkR：只确认了获取方式，未下载全量；下一步需要确定本项目使用哪一个作为 canonical mapping 主库。
- GitHub API 本次被限流；`py-ssPA` git clone 卡住，改用 source zip 成功。若后续需要 commit history/submodules，需在网络更稳定环境重试。


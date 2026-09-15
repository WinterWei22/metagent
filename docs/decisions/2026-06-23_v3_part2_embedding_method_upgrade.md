# V3 Part 2 — 方法升级实验设计（embedding / 结构轴）

- Date: `2026-06-23`
- Branch: `metagent-v3-benchmark`（Part 1 recall@k + driver P/R 已落地；Part 2 在此分支起）
- Scope: Stage 2。把分析/验证轴从「ID 成员关系」迁到「结构/嵌入相似 + 硬事实锚定」。
- 不动：`metagent-v2-base-b1` tag、B1 数据、14-fail floor、verifier 三档政策。

## 0. 核心原则（不变量）

- **嵌入负责召回 + 架桥，硬事实负责判决 + 审计；cosine 只当辅助证据。**
- 两个互不混淆的任务：
  - **job A — 身份统一**：靠 InChIKey 精确合并跨命名空间的同一分子（确定性、可审计）。
  - **job B — 相似/邻域**：靠指纹（ECFP/Morgan）或学习嵌入（ChemBERTa/MolFormer）做模糊召回与类富集。
- **禁踩循环陷阱**：嵌入不得用 pathway membership 当监督信号训练；用现成结构指纹/预训练化学嵌入。

## 1. 结构覆盖率分析（已完成，gating 数字）

两个脚本，按 distinct metabolite 统计，纯 audit、零 LLM：
- `scripts/metagent/v3_part2_structure_coverage.py` —— live pipeline 同款 resolver（基线）。
- `scripts/metagent/v3_part2_max_resolver_probe.py` —— **最大化离线** resolver（ChEBI 全
  namespace + MetaNetX 全桥接 + Human-GEM 全注释列），并把残差三分类。

### 1.1 最终覆盖率（离线全量结构表 + 在线最后一公里）

resolver 链：本地 ChEBI（全 namespace）→ 本地 MetaNetX sqlite → **全量 chem_xref**
（BiGG/KEGG/HMDB → MNX，580MB 本地）→ **全量 chem_prop**（MNX → SMILES，1.50M 行 /
95.9% 带 SMILES，已下载 810MB）→ **在线最后一公里**（PubChem CID/InChIKey、KEGG MOL、
BiGG Models REST database_links；全部缓存）。

| stratum | distinct | A 已解析 | B 仍缺 | C 占位符 |
|---|---:|---:|---:|---:|
| sub6_enrich | 178 | 98.9% | 1.1% | 0 |
| hmdb_ramp_membership | 617 | 97.4% | 2.6% | 0 |
| human1 | 773 | **87.2%** | 10.9% | 15 (1.9%) |
| recon22 | 363 | **83.5%** | 16.5% | 0 |
| **TOTAL** | **1931** | **90.8%** | 8.4% | 15 (0.8%) |

进展轨迹（human1 / recon22）：baseline 54.7/32.8% → +全量 chem_prop 82.9/81.3%
→ +在线最后一公里 **87.2/83.5%**。关键修复：BiGG 前缀 `biggM`/`bigg.metabolite`（非
`bigg`），修对后 BiGG→MNX 90%。在线只新增 52（PubChem CID 43 为主；BiGG InChIKey 多为带
电荷形式 -M/-O，PubChem 精确匹配失败，block14 也补不到——因 chem_prop 本就是 MetaNetX
结构源）。

### 1.2 残留 162 的本质（决定性发现）

剩余未解析**不是 crosswalk 没补全，而是 GEM 本就含一批"非单一分子"实体 + 公库无结构的冷门偶联物**：

| 类别 | n | 性质 / 处置 |
|---|---:|---|
| 聚合物/复合物/池（psyllium、guar gum、β-glucan–胆汁酸复合物、gums） | 26 | **非单分子，无 SMILES** → 同占位符，排除 |
| 泛化聚糖/糖脂（`(Gal)4(Glc)1(GlcNAc)3…`、糖鞘脂） | 8 | **非单一结构** → 排除 |
| 冷门真小分子（胆汁酸葡糖醛酸苷、脱氢胆酸…） | 62 | 真分子但公库无结构，名字常含拼写错；仅模糊名字匹配可碰，**易引入错结构（不做）** |
| BiGG 无条目/无名（模型特有 MAM） | 66 | 未知，多数模型特有，无公共结构 |

### 1.3 关于「100% 覆盖」的口径（定论）

- **真单分子结构覆盖 ≈ 90.8%（已达成）**；剩余 ~9% 的主体是 **聚合物/复合物/泛化聚糖（非单分子，
  应排除）+ 公共库根本无结构的冷门偶联物**，不是工程没做到位。
- **禁止两种造假**：① 给聚合物/虚拟节点编单分子 SMILES；② 对带拼写错的冷门名做模糊匹配硬塞结构
  —— 都违背 MetAgent "每条断言可验证、不幻觉" 原则。
- **扩展排除类 `non_single_structure`**：覆盖 (a) 无 xref 虚拟节点 15、(b) 聚合物/复合物/池 26、
  (c) 泛化聚糖/糖脂 8 = **49 个（2.5%）**，显式标注、排除出结构/嵌入轴、报告透明记录。
- **本 Part 2 采用的 100% 口径**：「**结构轴覆盖 ~91% 单分子 + 2.5% 非单分子显式排除 +
  ~6.5% 公库缺录冷门偶联物（标 `structure_unavailable`，留待外部数据）**」。字面 100% 不可达，
  且不应追求（追求即造假）。
- 数据：`reports/reports_v2/2026-06-23_v3_part2_final_coverage.md`；全量表
  `data/concord/metanetx_cache/chem_prop_full.tsv`（gitignore，记入 setup 脚本）；
  在线缓存 `data/metagent/v3_part2_coverage/lastmile_{cache,resolved}.json`。

## 2. 工作项（gated build order）

### 2A — 统一多源 ID→结构 resolver + 覆盖率补全（先做，确定性，无 LLM）
- **2A-1 离线合一**：ChEBI（全 namespace）+ MetaNetX（全桥接）+ Human-GEM（全注释列）
  三源合并，输出每 metabolite 的 canonical InChIKey + SMILES（job A 落地）。基线 77%。
- **2A-2 补全结构表**〔✅ 已下载，覆盖率已升至 88.1%〕：MetaNetX 全量 `chem_prop.tsv`
  已下载（810MB，本地 `data/concord/metanetx_cache/chem_prop_full.tsv`）。**待办**：re-ETL
  进 `metanetx.sqlite` 新增 `smiles` 列（替代当前在脚本里直接 parse 大文件），并把它 +
  chem_xref 写进 `setup_metagent_v2_env.sh` symlink（gitignore，仿 chebi/metanetx sqlite）。
- **2A-2b 最后一公里**〔✅ 已做，A=90.8%〕：PubChem CID/InChIKey + KEGG MOL + BiGG REST
  database_links，缓存落盘。新增 52；残留 162 经分类确认主体为非单分子/公库缺录（见 §1.2），
  **不再强推**（继续推即模糊名字匹配，违背反幻觉原则）。
- **2A-3 排除策略**：扩展类 `non_single_structure`（虚拟节点 + 聚合物/复合物 + 泛化聚糖 = 49 个）
  打标签排除出结构/嵌入轴；冷门偶联物（~125）标 `structure_unavailable`，留待外部数据，报告透明记录。
- **验收**：sub6 98.9% / hmdb_ramp 97.4% / human1 87.2% / recon22 83.5%（实测达成）；
  非单分子 100% 被标注而非解析。
- 这同时就是 namespace 统一的硬事实底座（verifier 可审计的合并依据）。

### 2B — 通路名语义匹配（文本嵌入，替换 token-overlap 启发式）
- 现 semantic 指标是 token overlap + curated synonym（FP 偏高，见 06-19 manual validation：
  Human1 semantic TP 仅 53%）。改为通路名 sentence-embedding cosine + 阈值。
- 验收：在 06-19 人工校验集上，semantic precision 较 token-overlap 提升且 recall 不降。
- 注意：cosine 只做候选配对，最终命中仍需硬名称/ID 锚（原则 §0）。

### 2D — verifier 升级：判「结构/嵌入是否与通路底物类一致」（在 2A 之后）
- 新增 verifier layer（**加新代码，✅ 档**，不改 B1-core）：给定 claim 的 metabolite 集合 +
  目标 pathway，用结构指纹/化学类比对「这些分子是否属于该 pathway 的底物类」。
- 复用 `reference_verifier_llm_judge_pattern` 8 项模板（prompt 契约/parser/final-iter/cost cap/trace/excerpt/HEDGED/crash）。
- 验收：在现有 supported/UV 口径上不回退；新 layer 能 land 一部分当前 UV 的结构性 claim。

### 2C — 非 ID 富集轴（最后做，覆盖暗代谢组）
- ChemRICH 式结构相似度富集（对 metabolite SET 做，p 值不依赖背景库成员表）。
- ClassyFire 化学类富集（SMILES→类，无需谱图）。CANOPUS 推迟到输入带谱图再说。
- 验收：作为新 paradigm 进 ReAct 工具池；在 sub6/hmdb_ramp 上与 ID-富集互补（命中非冗余通路）。

## 3. 待拍板（Open Questions，不阻塞 2A/2B）

1. Stage 2 输入是否引入 abundance + 原始谱图？决定 ChemRICH 有向版 + CANOPUS 可行性。
   默认：**先不引入**，2C 先做无向结构富集 + ClassyFire 类富集。
2. job B 用指纹（ECFP4，确定性、零依赖）还是预训练化学嵌入（ChemBERTa）？
   默认：**先 ECFP4 指纹**（可审计、无模型权重依赖），学习嵌入留作 2C 的对照实验。
3. 通路底物类的「类」粒度（ClassyFire superclass vs class vs subclass）？默认 class 起步。
4. 〔已定论并执行，见 §1.1/§1.2〕100% 口径 = 99.2% 真分子全解析 + 0.8% 占位符显式标注。
   MetaNetX 全量 chem_prop 已下载、覆盖率已升至 88.1%；网络可用（PubChem/KEGG REST 通，
   MetaNetX 仅需带 User-Agent 的 GET）。`ms-pred` 的 PubChem hdf5 不可用（按 formula 索引，
   缺 InChIKey 钥匙）。剩余仅 2A-2b 工程量。

## 4. 复现

```bash
# 基线 resolver 覆盖率
PYTHONPATH=. python scripts/metagent/v3_part2_structure_coverage.py
# -> reports/reports_v2/2026-06-23_v3_part2_structure_coverage.md
# -> data/metagent/v3_part2_coverage/{unresolved.csv,coverage_by_stratum.json}

# 最大化离线 resolver + A/B/C 残差三分类（朝 100% 的账）
PYTHONPATH=. python scripts/metagent/v3_part2_max_resolver_probe.py

# 在线最后一公里（PubChem/KEGG/BiGG REST，缓存）-> 残留 B 新增 52
PYTHONPATH=. python scripts/metagent/v3_part2_lastmile_rest.py

# 最终覆盖率（离线全量表 + 在线 lastmile）-> 90.8%
PYTHONPATH=. python scripts/metagent/v3_part2_final_coverage.py
# -> reports/reports_v2/2026-06-23_v3_part2_final_coverage.md
```

全量结构表（gitignore，810MB）：`data/concord/metanetx_cache/chem_prop_full.tsv`
（源 `https://www.metanetx.org/cgi-bin/mnxget/mnxref/chem_prop.tsv`，需带 User-Agent header）。

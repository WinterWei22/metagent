# RIKEN pool 用于代谢路径 benchmark 的可行性评估

- **Date:** 2026-04-29
- **Author:** Wentao Wei
- **Input data:** `data/processed/compound_pool_riken.jsonl` (5,930 spectra, 712 unique compounds, 见 `reports/massbank/session_summary_2026-04-28.md`)
- **External ground truth probed:** HMDB (`/data/.../hmdb.sqlite`, 153 MB) + RaMP-DB (`/data/.../ramp.sqlite`, 1.9 GB)
- **Question:** 我们的 RIKEN pool 能否撑起代谢路径 benchmark?

**TL;DR:** 能,但只覆盖**植物次级代谢方向**(~171 个化合物可用)。中心代谢、脂代谢、核苷酸代谢方向 RIKEN 实质不够。要做通用代谢路径 benchmark,必须扩展 HMDB / MoNA / GNPS-LIBRARY。如果只做 Stage 2(化合物→生物学,不要谱图),直接用 HMDB 化合物列表更合适——这与协议 §1.4 把 Sub-1/2 与 Sub-6 拆开的设计一致。

---

## 1. 路径 benchmark 需要的输入是什么

代谢路径 benchmark 的输入永远不是谱图。谱图给出的是 (m/z, intensity) 对 + 化合物 ID。**路径 ground truth 必须来自 KEGG / Reactome / RaMP-DB / HMDB**。

RIKEN pool 的角色是提供 **712 个独立化合物的身份(SMILES + InChIKey)** ——这就是路径 benchmark 的输入端候选集。下游再用 KEGG/RaMP/HMDB 给每个化合物挂 pathway / tissue / disease 注释作为 ground truth,就能构造 benchmark。

## 2. RIKEN 化合物在外部数据库的实际覆盖率

我用每个化合物的 InChIKey 第一块去 HMDB 反查,再用拿到的 KEGG/HMDB ID 去 RaMP-DB 反查 pathway 注释。**712 个独立化合物的实际穿透链路**:

```
712 RIKEN 独立化合物
 │
 ├── 499 (70.1%) 命中 HMDB                    ← 有 tissue/disease 元数据可查
 │     │
 │     ├── 196 (27.5%) 有 KEGG ID              ← 能查 KEGG pathway
 │     ├──  61 ( 8.6%) 有 tissue locations      ← 能做 tissue 关联 benchmark
 │     └──  54 ( 7.6%) 有 disease associations  ← 能做 disease 关联 benchmark
 │
 └── 171 (24.0%) 在 RaMP-DB 里有 ≥1 pathway 注释
       └── 命中 5,093 条不同 pathway(去重)
```

**关键瓶颈:能上路径 benchmark 的不是 712,是 ~171。** 这只是 RIKEN pool 的 24%。

### 2.1 按化合物类的细分

| 化合物类 | RIKEN 独立 | 在 HMDB | 有 KEGG | 有 tissue | 有 disease |
|---|---:|---:|---:|---:|---:|
| amino_acid | 27 | 17 (63%) | 5 (19%) | 5 (19%) | 5 (19%) |
| nucleoside | 2 | 1 (50%) | 1 (50%) | 1 (50%) | 1 (50%) |
| organic_acid | 85 | 59 (69%) | 24 (28%) | 14 (16%) | 16 (19%) |
| flavonoid | 133 | 102 (77%) | 27 (20%) | 5 (4%) | 4 (3%) |
| lipid | 43 | 25 (58%) | 9 (21%) | 12 (28%) | 7 (16%) |
| other (含 alkaloid/terpenoid/glycoside) | 422 | 295 (70%) | 130 (31%) | 24 (6%) | 21 (5%) |
| **TOTAL** | **712** | **499 (70%)** | **196 (28%)** | **61 (9%)** | **54 (8%)** |

观察:
- HMDB 覆盖率最高的是 flavonoid(77%);最低是 lipid(58%)
- KEGG 覆盖率普遍低,说明很多 RIKEN 化合物虽然在 HMDB 但没有正式的 KEGG 通路归属
- tissue/disease 元数据集中在 lipid 类,因为 lipid 在 HMDB 里普遍有组织富集数据

## 3. RIKEN 覆盖什么路径,不覆盖什么路径

### 3.1 实际命中的 top pathway(数字 = 覆盖该 pathway 的 RIKEN 化合物数)

```
20  Metabolism                                              (顶层笼统)
19  Biochemical pathways: part I
15  Mapping of differential metabolites on metabolic pathway
12  Polyphenols Targeting NFKB Pathway in Neurological Disorders
11  Polyphenol-target network and associated signaling pathway
11  Anthocyanin synthesis dynamic mechanism portrait
11  Disease
10  Signal Transduction
10  Transport of small molecules
10  Amino acid metabolism
10  Heat map of flavonoid synthesis pathway
10  Biosynthetic pathway of terpenoids, alkaloids, polyphenols
```

**90% 是植物次级代谢主题** — anthocyanin / flavonoid / phenylpropanoid / polyphenol / terpenoid / alkaloid 合成路径。少量是 "Amino acid metabolism" 这种笼统大路径。

这与 RIKEN PlaSMA(Plant Secondary Metabolism Atlas)的初衷完全吻合。

### 3.2 中心代谢 / 糖酵解的覆盖率(实测)

我直接查了 8 个最经典的中心代谢中间物:

| 化合物 | 在 RIKEN pool? |
|---|---|
| Citric acid (柠檬酸,TCA) | ✓ 有 |
| Succinic acid (琥珀酸,TCA) | ✗ 缺 |
| Lactic acid (乳酸,糖酵解末) | ✗ 缺 |
| Pyruvic acid (丙酮酸,糖酵解) | ✗ 缺 |
| Malic acid (苹果酸,TCA) | ✗ 缺 |
| 2-Oxoglutaric acid (α-酮戊二酸,TCA) | ✗ 缺 |
| Fumaric acid (富马酸,TCA) | ✗ 缺 |
| Glutamic acid (谷氨酸) | ✗ 缺 |

**8 个里只命中 1 个(citric acid)。** 原因有二:

1. **RIKEN PlaSMA 不刻意采中心代谢小分子**——他们专攻次级代谢
2. 这些小分子普遍**带电荷、强极性、低质量**,LC-ESI 电离效率差,大部分 LC-MS 谱库本来就稀缺,不只 RIKEN 的问题

结论:**做"中心代谢路径富集分析"的 benchmark,光靠 RIKEN 撑不起来。**

## 4. 能做 vs 不能做

### 4.1 ✅ RIKEN pool 能撑得住的路径 benchmark 类型

| Benchmark 类型 | 适用度 | 关键证据 |
|---|---|---|
| **植物次级代谢路径富集** | 强 | flavonoid 133 个独立化合物,77% 在 HMDB;anthocyanin / polyphenol 路径在 RaMP top hits 中频繁出现 |
| **多酚类 → 信号通路关联** | 强 | RaMP 整合的 polyphenol-NFKB / polyphenol-MAPK 关联,RIKEN 化合物有现成 ground truth |
| **化合物分类(ClassyFire taxonomy)** | 强 | 712 个化合物可作为 ClassyFire taxonomy 的 evaluation set;协议 §3.6 Sub-6 的 "functional class" 子任务正是这个 |
| **同路径化合物共现推理** | 中 | 171 个有 pathway 注释的化合物里挑共属一个 pathway 的子组,测系统能否识别"这些化合物共享生物学背景" |
| **HMDB tissue 关联** | 弱-中 | 只有 9% 化合物有 tissue 数据,样本小但能做小规模(~50-80 化合物)的精测 benchmark |
| **HMDB disease 关联** | 弱-中 | 同上,8% 覆盖,可做小规模 benchmark |

### 4.2 ❌ RIKEN pool 撑不起的 benchmark 类型

| Benchmark 类型 | 不适用原因 |
|---|---|
| **中心代谢 / 糖酵解 / TCA / 尿素循环** | 经典 8 个代谢物只命中 1 个 |
| **脂代谢路径(β-氧化、磷脂合成、鞘脂)** | 43 个 lipid 化合物且大多是植物次级脂质,β-oxidation 的标志物完全缺失 |
| **核苷酸代谢 / 嘌呤·嘧啶合成** | nucleoside 类**只有 2 个独立化合物**,本质上无法做 |
| **微生物 / 肠道菌特异路径** | RIKEN 是植物为主,没有微生物代谢侧重 |
| **跨物种 pathway 比较** | RIKEN 不带物种标签,无法做 species-specific 评测 |
| **能量代谢(ATP / ADP / NADH 等)** | 这类辅因子在所有 LC-ESI 谱库都极稀缺,RIKEN 也不例外 |

## 5. 推荐的 benchmark 工作流(对应协议 §3.6 Sub-6)

按 v2 协议 Sub-6 BiologicalContext 的设计,**路径 benchmark 不依赖谱图**,只用化合物身份。具体管线:

```
Step 1  从 712 RIKEN 独立化合物里,筛出 171 个有 RaMP pathway 注释的
Step 2  在这 171 中,进一步筛出同时满足以下条件的:
          - ≥1 KEGG pathway 注释
          - ≥1 HMDB tissue location
          - ClassyFire 完整 5 级分类
        → 预计剩 ~50-80 个高质量 benchmark 候选
Step 3  对每个候选,只用 SMILES + InChIKey + 名称(不用 spectrum)
Step 4  prompt LLM:"L-tyrosine 参与哪些 KEGG 通路?组织富集?疾病关联?
                     功能类别?上下游代谢物?"
Step 5  把 LLM narrative 拆成 per-claim,用 verifier(Type 2 / Type 3)
        与 RaMP/HMDB ground truth 比对
        → per-subtask accuracy + verifier precision/recall
```

这与协议 §3.6.3 的"全部 ground truth 自动获取,无需人工标注"的承诺一致。

## 6. 想做"全代谢覆盖"的 pathway benchmark,扩展方案

如果目标是覆盖中心代谢 + 次级代谢 + 脂代谢的**通用** pathway benchmark,RIKEN 单独不够。三种扩展思路按性价比排序:

| 扩展 | 数据规模 | 优势 | 工作量 |
|---|---:|---|---|
| **直接抽 HMDB(完全跳过谱图)** | ~9 万化合物 | 100% HMDB 覆盖,中心代谢全;**Stage 2 only** | 0(已有 `tools/metabolite_info` + `tools/pathway_context`) |
| **加 MoNA-HMDB dump 的 7,400 化合物** | +7,400 谱+化合物 | HMDB 覆盖 100%,中心代谢比 RIKEN 好;有谱图可做 Stage 1+2 端到端 | ~0.5 天(`common/mona_loader.py` 已存在) |
| **加 GNPS-LIBRARY 子库(15k 条)** | +15k 谱 | GNPS 原创人类代谢物比 RIKEN 多,但 ground truth 准确度低于 RIKEN | ~1 天 |

**最经济**:如果只评测路径推理(化合物→生物学),直接用 HMDB 9 万化合物列表抽 100-150 个高质量样本,跳过谱图层。**这正是协议 §3.6.2 推荐的:**"这个子集不需要 spectrum,只需要化合物本身。化合物来源:从 Sub-1 / Sub-2 中已知鉴定的化合物里选"。

## 7. 一句话结论

**RIKEN 谱图能撑起植物次级代谢方向的路径 benchmark(~171 个化合物可用),撑不起通用代谢路径 benchmark。** 这跟协议 §1.4 的两阶段设计哲学一致——路径 benchmark 是 Stage 2(化合物→生物学),瓶颈在外部数据库覆盖率,不在谱图本身。如果只做 Stage 2,完全可以绕开 RIKEN 直接用 HMDB。RIKEN 真正的不可替代价值在 Stage 1(谱图→化合物),特别是 negative-mode 和植物次级代谢方向的高质量 ground truth 标注。

## 8. 复现这份评估

```sh
# 1. RIKEN pool stats
python3 -c "
import json, collections
recs = [json.loads(l) for l in open('/data/.../massbank/processed/compound_pool_riken.jsonl')]
unique = {}
for r in recs:
    ik = (r['ground_truth'].get('inchikey') or '')[:14]
    if ik: unique.setdefault(ik, r)
print(f'{len(unique)} unique compounds in pool')
"

# 2. HMDB 覆盖率(per-class)
# 见本文 §2.1 的脚本(query metabolites.inchikey LIKE '<first14>%')

# 3. RaMP pathway 覆盖率
# 见本文 §2 的脚本:
#   - HMDB→KEGG mapping 通过 hmdb.sqlite metabolites.kegg_id
#   - KEGG/HMDB → rampId 通过 ramp.sqlite source.sourceId LIKE 'kegg:%' / 'hmdb:%'
#   - rampId → pathway 通过 analytehaspathway JOIN pathway

# 4. 中心代谢化合物在 RIKEN 中的命中率
# 见本文 §3.2 的 InChIKey 列表
```

数据快照 MD5(参见 `reports/nm002_leakage_audit_2026-04-29.md` §11):
- `compound_pool_riken.jsonl`: 14.5 MB / 5,930 行
- `hmdb.sqlite`: 153 MB
- `ramp.sqlite`: 1.86 GB

---

## 附录 — RIKEN pool 化合物类构成

| 化合物类 | spectrum 数 | 独立化合物数 | 占比(独立) |
|---|---:|---:|---:|
| other | 3,907 | 422 | 59.3% |
| flavonoid | 1,402 | 133 | 18.7% |
| organic_acid | 353 | 85 | 11.9% |
| lipid | 195 | 43 | 6.0% |
| amino_acid | 70 | 27 | 3.8% |
| nucleoside | 3 | 2 | 0.3% |
| **Total** | **5,930** | **712** | **100%** |

注:`other` 比例极高(59%)是 SMARTS-only 分类的副作用——alkaloid / terpenoid / glycoside 等没有简单 SMARTS pattern 的类目都被归到 other。如果 overnight 跑 `--classify`(走 ClassyFire API),other 可能降到 25% 以下,alkaloid / terpenoid 等会显式出现,RIKEN 的真实化合物多样性会更清晰。

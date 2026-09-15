# Stage 1+2 End2End 优质 case —— 完整报告内容

> 日期：2026-06-30 · run `stage2_full_v2`（完整 InChIKey）
> 标准：**Stage-2 pathway 语义命中 gold，且 Stage-1 识别并不完美**——展示端到端在含误识别输入下仍鲁棒选对通路的案例。
> 每个 case：Stage-1 识别准确率 + 喂给 Stage-2 的代谢物 → pathway 预测 → narrative → 保留的结构化 claims。
> 复现：`data/metagent/stage1_2_e2e/stage2_full_v2/path_x_full/sub6_easy_<orig>.json`

---

## Galactose metabolism（id_acc 2/7 = 29%）

- **orig task**：`e2e_enrich_mammalian_RAMP_P_000000398_seed3788203504`
- **Stage-1 识别**：2/7 谱结构正确（29%）→ 去重后 7 个代谢物喂给 Stage-2
- **gold**：Galactose Metabolism ｜ **预测 primary**：**Galactose metabolism**（n/a）→ ✅ 语义命中

**喂给 Stage-2 的（含误识别的）代谢物（7）**：MALTOSE, 2-(2-chloroacetylamino)-3-[6-(phenylmethoxy)indol-3-yl]propanoic acid CollisionEnergy:102040, Myo-inositol, GALACTITOL - 50.0 eV, Trehalose, Melibiose, HMDB:HMDB00700-975 Hydroxypropionic acid

**alternatives**：Propionate catabolism；Mitochondrial carbon flux

**Narrative**

> （narrative 文本为空；见下方 claims）

**保留的结构化 claims（8）**

- `None`（8）：
  - Mummichog m/z-direct network analysis independently recovers galactose metabolism (MUMM:galactose_metabolism)
  - galactose metabolism maps to MUMM:galactose_metabolism
  - galactose metabolism p=0.0145
  - galactose metabolism rank=5
  - Galactitol is the principal driver metabolite of galactose metabolism
  - myo-inositol is the principal driver metabolite of galactose metabolism
  - myo-inositol has InChIKey CDAISMWEOUEBRE-UHFFFAOYSA-N
  - The biological picture is one of coordinated disruption spanning propionate catabolism, mitochondrial carbon flux, and hexose/galactose metabolism

---

## Galactose Metabolism（id_acc 8/13 = 62%）

- **orig task**：`e2e_enrich_mammalian_RAMP_P_000000398_seed3271204528`
- **Stage-1 识别**：8/13 谱结构正确（62%）→ 去重后 11 个代谢物喂给 Stage-2
- **gold**：Galactose Metabolism ｜ **预测 primary**：**Galactose Metabolism**（SMP00043）→ ✅ 语义命中

**喂给 Stage-2 的（含误识别的）代谢物（11）**：5-O-Caffeoylquinic acid, Trehalose, Spectral Match to D-Mannitol from NIST14, Myo-inositol, TIRAPAZAMINE, Spectral Match to .beta.-D-Allose from NIST14, DETOMIDINE, SUCROSE, Methimazole, HMDB:HMDB00700-975 Hydroxypropionic acid, 2hydroxy_PhenylAceticAcid

**alternatives**：Nucleotide Sugars Metabolism；Galactose metabolism

**Narrative**

> Multiple pathway analysis tools converge on carbohydrate metabolism as a primary finding. RaMP ORA independently identifies Galactose Metabolism (SMPDB:SMP00043) as a top hit, with an FDR of 0.0085 and

**保留的结构化 claims（14）**

- `None`（14）：
  - RaMP ORA independently identifies Galactose Metabolism (SMPDB:SMP00043) as a top hit
  - Galactose Metabolism has FDR 0.0085
  - Galactose Metabolism has fold enrichment 249
  - Nucleotide Sugars Metabolism (SMPDB:SMP00010) flanks Galactose Metabolism in the same carbohydrate cluster
  - Mummichog confirms galactose metabolism at rank 7
  - Galactose metabolism has p-value 0.016
  - Galactose metabolism has 9/10 compound overlap
  - Trehalose is a driver carbohydrate

---

## Androgen and Estrogen Metabolism（id_acc 12/16 = 75%）

- **orig task**：`e2e_enrich_mammalian_RAMP_P_000000421_seed2128485400`
- **Stage-1 识别**：12/16 谱结构正确（75%）→ 去重后 11 个代谢物喂给 Stage-2
- **gold**：Androgen and Estrogen Metabolism ｜ **预测 primary**：**Androgen and Estrogen Metabolism**（hsa00150）→ ✅ 语义命中

**喂给 Stage-2 的（含误识别的）代谢物（11）**：0495_Testosterone, estrone [CCS=169.160888671875], 4-Androstene-3,17-dione, SUCROSE, Dehydroepiandrosterone (DHEA), Caffeine, 2-(non-1-en-1-yl)quinolin-4-ol:Series 2 HAQ C9:1, QUEBRACHITOL, Epiestradiol CollisionEnergy:102040, 2-(2-chloroacetylamino)-3-[6-(phenylmethoxy)indol-3-yl]propanoic acid CollisionEnergy:102040, 5beta-Dihydroepitestosterone; 5beta-Androstan-17alpha-ol-3-one_CE30

**Narrative**

> （narrative 文本为空；见下方 claims）

**保留的结构化 claims（10）**

- `None`（10）：
  - Steroid biosynthesis has fold-enrichment=2251
  - Androgen and Estrogen Metabolism was consistently replicated
  - Androgen and Estrogen Metabolism has pathway ID KEGG:hsa00150
  - Androgen and Estrogen Metabolism has FDR=1.8×10⁻⁸
  - Testosterone is a driver metabolite
  - Testosterone has Mummichog ID MUMGGOZAMZWBJJ
  - Testosterone has KEGG ID C00535
  - DHEA is a driver metabolite

---

## Steroid biosynthesis（id_acc 6/12 = 50%）

- **orig task**：`e2e_enrich_mammalian_RAMP_P_000053042_seed409910564`
- **Stage-1 识别**：6/12 谱结构正确（50%）→ 去重后 9 个代谢物喂给 Stage-2
- **gold**：Steroid biosynthesis ｜ **预测 primary**：**Steroid biosynthesis**（WP496）→ ✅ 语义命中

**喂给 Stage-2 的（含误识别的）代谢物（9）**：Androsterone_CE75, "17-epi-Dihydrotestosterone; 5alpha-Androstan-17alpha-ol-3-one_CE25,38,59", EPITESTOSTERONE, dehydroepiandrosterone [CCS=173.89784240722656], catechol [CCS=114.69612884521484], 4-Androstene-3,17-dione, COUMARIN, HMDB:HMDB03364-2269 Quinone, estrone [CCS=168.81260681152344]

**Narrative**

> （narrative 文本为空；见下方 claims）

**保留的结构化 claims（9）**

- `None`（9）：
  - Steroid biosynthesis is the second-ranked WikiPathways hit
  - Steroid biosynthesis has WikiPathways ID WP:WP496
  - Steroid biosynthesis has FDR = 1.02 × 10⁻⁸
  - Steroid biosynthesis is driven by DHEA, estrone, and testosterone
  - Steroid biosynthesis has fold enrichment = 2251
  - 4-androstene-3,17-dione is a driver metabolite of the enrichment
  - Estrone is a driver metabolite of the enrichment
  - Dehydroepiandrosterone is a driver metabolite of the enrichment

---

## Pyrimidine metabolism（id_acc 7/9 = 78%）

- **orig task**：`e2e_enrich_mammalian_RAMP_P_000053306_seed2915906702`
- **Stage-1 识别**：7/9 谱结构正确（78%）→ 去重后 7 个代谢物喂给 Stage-2
- **gold**：Pyrimidine metabolism ｜ **预测 primary**：**Pyrimidine metabolism**（hsa00240）→ ✅ 语义命中

**喂给 Stage-2 的（含误识别的）代谢物（7）**：L-methionine sulfoxide, Asparagine_(L-), URIDINE-5-MONOPHOSPHATE - 60.0 eV, Cytidine 5'-diphosphate, 3-Ureidopropionic acid CollisionEnergy:102040, DIHYDROURACIL - 60.0 eV, AZELAIC ACID

**Narrative**

> Treatment-group metabolomics reveals a profound perturbation of pyrimidine metabolism across three independent analytical paradigms. RaMP ORA returned KEGG:hsa00240 Pyrimidine metabolism at FDR 3.4e-5 with fold enrichment 297, identifying 2 of 52 pathway compounds hit from 7 inputs. The two driver metabolites, 5,6-dihydrouracil and N-carbamoyl-β-alanine/3-ureidopropionic acid, anchor this finding. Convergent evidence across ORA and m/z-direct paradigms identifies pyrimidine metabolism as the primary biological axis of perturbation.

**保留的结构化 claims（7）**

- `None`（7）：
  - Treatment-group metabolomics reveals a profound perturbation of pyrimidine metabolism across three independent analytical paradigms
  - RaMP ORA returned KEGG:hsa00240 Pyrimidine metabolism
  - RaMP ORA returned KEGG:hsa00240 Pyrimidine metabolism at FDR 3.4e-5
  - RaMP ORA returned KEGG:hsa00240 Pyrimidine metabolism with fold enrichment 297
  - RaMP ORA returned KEGG:hsa00240 Pyrimidine metabolism with 2 of 52 pathway compounds hit from 7 inputs
  - 5,6-dihydrouracil and N-carbamoyl-β-alanine/3-ureidopropionic acid are the two driver metabolites
  - Convergent evidence across ORA and m/z-direct paradigms identifies pyrimidine metabolism as the primary biological axis of perturbation

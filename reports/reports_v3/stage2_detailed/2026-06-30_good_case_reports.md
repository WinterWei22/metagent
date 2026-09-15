# Stage 2 优质报告 case —— 完整报告内容

> 日期：2026-06-30 · run `v4_bench_eval_cascade_fix_20260629`（cascade 默认）
> 标准：全部 claim SUPPORTED + pathway 语义命中 gold。展示 narrative 原文 + 结构化 claims + pathway 预测。
> 复现：`data/metagent/v4_bench_eval_cascade_fix_20260629/path_x_full/<task_id>.json`

---

## Androgen and Estrogen Metabolism

- **task_id**：`sub6_easy_compound_only_enrich_mammalian_RAMP_P_000000421_seed1`
- **stratum**：sub6 ｜ **工具调用（6）**：query_pathway_members, run_fella_rwr, run_metaboanalystr_psea, run_mummichog, run_ramp_enrichment, run_sspa_ora
- **gold**：Androgen and Estrogen Metabolism ｜ **预测 primary**：Androgen and Estrogen Metabolism（hsa00150）→ ✅ 语义命中

**输入差异代谢物（8）**：Warfarin, Estradiol, 3,4-Dihydroxyphenylacetaldehyde, Androstenedione, Estrone, Dehydroepiandrosterone, Dihydrotestosterone, Testosterone

**Pathway 预测**
- primary：**Androgen and Estrogen Metabolism**（hsa00150）
- alternatives：Androgen and estrogen biosynthesis and metabolism；Tyrosine metabolism

**Narrative**

> The pathway analysis reveals significant enrichment of androgen and estrogen-related metabolism. In the run_ramp_enrichment analysis, KEGG:hsa00150 (Androgen and Estrogen Metabolism) achieves rank 2 with an FDR of 4.96942e-18. Similarly, the run_mummichog analysis ranks Androgen and estrogen biosynthesis and metabolism

**结构化 claims（11，全部 SUPPORTED）**

- `pathway_enrichment`（3）：
  - run_ramp_enrichment ranks KEGG:hsa00150 (Androgen and Estrogen Metabolism) at rank 2 with fdr 4.96942e-18.
  - run_mummichog ranks MUMM:androgen_and_estrogen_biosynthesis_and_metabolism (Androgen and estrogen biosynthesis and metabolism) at rank 0 with p_value 8.40266e-05.
  - run_mummichog ranks MUMM:tyrosine_metabolism (Tyrosine metabolism) at rank 2 with p_value 0.0228552.
- `pathway_membership`（6）：
  - testosterone is a member of Androgen and Estrogen Metabolism.
  - 17β-estradiol is a member of Androgen and Estrogen Metabolism.
  - dehydroepiandrosterone is a member of Androgen and Estrogen Metabolism.
  - androst-4-ene-3,17-dione is a member of Androgen and Estrogen Metabolism.
  - estrone is a member of Androgen and Estrogen Metabolism.
  - 17β-hydroxy-5α-androstan-3-one is a member of Androgen and Estrogen Metabolism.
- `driver_metabolite`（2）：
  - testosterone drives KEGG:hsa00150.
  - 17β-estradiol drives KEGG:hsa00150.

---

## Galactose Metabolism

- **task_id**：`sub6_easy_compound_only_enrich_mammalian_RAMP_P_000000398_seed0`
- **stratum**：sub6 ｜ **工具调用（6）**：query_pathway_members, run_fella_rwr, run_metaboanalystr_psea, run_mummichog, run_ramp_enrichment, run_sspa_ora
- **gold**：Galactose Metabolism ｜ **预测 primary**：Galactose Metabolism（hsa00052）→ ✅ 语义命中

**输入差异代谢物（11）**：Dopamine, 2-Methoxyestradiol, Galactitol, myo-Inositol, Ethanolamine, Galactinol, D-Glucose, Inosine 2',3'-cyclic phosphate, Sucrose, Glycerol, Squalene

**Pathway 预测**
- primary：**Galactose Metabolism**（hsa00052）
- alternatives：Glycerophospholipid biosynthesis（R-HSA-1483206）

**Narrative**

> （该报告 narrative 文本为空；结构化 claims 见下）

**结构化 claims（11，全部 SUPPORTED）**

- `pathway_enrichment`（4）：
  - run_ramp_enrichment ranks KEGG:hsa00052 (Galactose Metabolism) at rank 0 with fdr 7.074e-15.
  - run_metaboanalystr_psea ranks KEGG:hsa00052 (Galactose Metabolism) at rank 0 with p_value 5.7666e-09.
  - run_mummichog ranks MUMM:galactose_metabolism (Galactose metabolism) at rank 5 with p_value 0.0203.
  - run_ramp_enrichment ranks REACT:R-HSA-1483206 (Glycerophospholipid biosynthesis) at rank 5 with fdr 0.000384.
- `pathway_membership`（6）：
  - galactitol is a member of Galactose Metabolism.
  - galactinol is a member of Galactose Metabolism.
  - D-glucopyranose is a member of Galactose Metabolism.
  - myo-inositol is a member of Galactose Metabolism.
  - glycerol is a member of Galactose Metabolism.
  - sucrose is a member of Galactose Metabolism.
- `driver_metabolite`（1）：
  - galactitol drives KEGG:hsa00052.

---

## Glycerolipid Metabolism

- **task_id**：`hmdb_ramp_easy_kegg_RAMP_P_000048381_rep0`
- **stratum**：hmdb_ramp ｜ **工具调用（6）**：query_pathway_members, run_fella_rwr, run_metaboanalystr_psea, run_mummichog, run_ramp_enrichment, run_sspa_ora
- **gold**：Glycerolipid Metabolism ｜ **预测 primary**：Glycerolipid Metabolism（KEGG:hsa00561）→ ✅ 语义命中

**输入差异代谢物（11）**：AICAR, Glycerol, Quinone, dipalmitoyl phosphatidate, Hydroquinone, Adenosine triphosphate, Glyceric acid, NADP, Palmitic acid, Phenobarbital, Dimethyl selenide

**Pathway 预测**
- primary：**Glycerolipid Metabolism**（KEGG:hsa00561）
- alternatives：Purine Metabolism（KEGG:hsa00230）；Fatty Acid Metabolism（MUMM:fatty_acid_metabolism）

**Narrative**

> （该报告 narrative 文本为空；结构化 claims 见下）

**结构化 claims（12，全部 SUPPORTED）**

- `pathway_enrichment`（5）：
  - run_ramp_enrichment ranks SMPDB:SMP00039 (Glycerolipid Metabolism) at rank 3 with fdr 2.40093e-17.
  - run_ramp_enrichment ranks KEGG:hsa00561 (Glycerolipid Metabolism) at rank 4 with fdr 2.40093e-17.
  - run_metaboanalystr_psea ranks KEGG:hsa00561 (Glycerolipid Metabolism) at rank 2 with p_value 0.0871.
  - run_metaboanalystr_psea ranks KEGG:hsa00230 (Purine Metabolism) at rank 0 with p_value 0.0562.
  - run_mummichog ranks MUMM:fatty_acid_metabolism (Fatty Acid Metabolism) at rank 0 with p_value 0.0178136.
- `pathway_membership`（5）：
  - glycerol is a member of Glycerolipid Metabolism.
  - 1,4-benzoquinone is a member of Glycerolipid Metabolism.
  - hydroquinone is a member of Glycerolipid Metabolism.
  - ATP is a member of Glycerolipid Metabolism.
  - hexadecanoate is a member of Glycerolipid Metabolism.
- `driver_metabolite`（2）：
  - glycerol drives KEGG:hsa00561.
  - AICAR ribonucleotide drives KEGG:hsa00230.

---

## Androgen and Estrogen Metabolism (seed 2)

- **task_id**：`sub6_easy_compound_only_enrich_mammalian_RAMP_P_000000421_seed2`
- **stratum**：sub6 ｜ **工具调用（6）**：query_pathway_members, run_fella_rwr, run_metaboanalystr_psea, run_mummichog, run_ramp_enrichment, run_sspa_ora
- **gold**：Androgen and Estrogen Metabolism ｜ **预测 primary**：Androgen and Estrogen Metabolism（hsa00140）→ ✅ 语义命中

**输入差异代谢物（10）**：Thromboxane, Dihydrotestosterone, Quinolinic acid, Dobutamine, Dehydroascorbic acid, 4-Hydroxy-2-oxoglutaric acid, Testosterone, Estradiol, Androstenedione, Dehydroepiandrosterone

**Pathway 预测**
- primary：**Androgen and Estrogen Metabolism**（hsa00140）
- alternatives：C21-steroid hormone biosynthesis and metabolism（C21_steroid_hormone_biosynthesis_and_metabolism）；Arachidonic acid metabolism（hsa00590）

**Narrative**

> Enrichment analysis using multiple computational approaches identifies significant metabolic pathway associations in the dataset. **run_ramp_enrichment** ranks the **Androgen and Estrogen Metabolism** pathway, represented by KEGG identifier hsa00140, at rank 1 with an FDR of 8.35887e-14. The same pathway, referenced by SMPDB identifier SMP00068, achieves rank 1 with an identical FDR of 8.35887e-14. **run_mummichog** analysis identifies the **C21

**结构化 claims（11，全部 SUPPORTED）**

- `pathway_enrichment`（4）：
  - run_ramp_enrichment ranks KEGG:hsa00140 (Androgen and Estrogen Metabolism) at rank 1 with fdr 8.35887e-14.
  - run_ramp_enrichment ranks SMPDB:SMP00068 (Androgen and Estrogen Metabolism) at rank 1 with fdr 8.35887e-14.
  - run_mummichog ranks MUMM:c21_steroid_hormone_biosynthesis_and_metabolism (C21-steroid hormone biosynthesis and metabolism) at rank 1 with p_value 0.00151248.
  - run_metaboanalystr_psea ranks KEGG:hsa00590 (Arachidonic acid metabolism) at rank 3 with p_value 0.2234.
- `pathway_membership`（5）：
  - 17β-hydroxy-5α-androstan-3-one is a member of Androgen and Estrogen Metabolism.
  - testosterone is a member of Androgen and Estrogen Metabolism.
  - 17β-estradiol is a member of Androgen and Estrogen Metabolism.
  - androst-4-ene-3,17-dione is a member of Androgen and Estrogen Metabolism.
  - dehydroepiandrosterone is a member of Androgen and Estrogen Metabolism.
- `driver_metabolite`（2）：
  - 17β-hydroxy-5α-androstan-3-one (dihydrotestosterone) drives KEGG:hsa00140.
  - thromboxane A₂ drives KEGG:hsa00590.

---

## Galactose Metabolism (seed 2)

- **task_id**：`sub6_easy_compound_only_enrich_mammalian_RAMP_P_000000398_seed2`
- **stratum**：sub6 ｜ **工具调用（6）**：query_pathway_members, run_fella_rwr, run_metaboanalystr_psea, run_mummichog, run_ramp_enrichment, run_sspa_ora
- **gold**：Galactose Metabolism ｜ **预测 primary**：Galactose Metabolism（hsa00052）→ ✅ 语义命中

**输入差异代谢物（10）**：Galactitol, myo-Inositol, Sucrose, Galactinol, Butanone, Guanabenz, Glycerol, 2-Ketobutyric acid, Choline, O-Phosphoethanolamine

**Pathway 预测**
- primary：**Galactose Metabolism**（hsa00052）
- alternatives：Glycerophospholipid metabolism（hsa00564）

**Narrative**

> Galactose Metabolism emerges as a significantly enriched pathway across multiple independent analytical methods. The run_ramp_enrichment analysis ranks KEGG:hsa00052 (Galactose Metabolism) at rank 2 with an FDR of 1.64e-12. The run_metaboanalystr_psea analysis ranks the same pathway at rank 0 with a p-value of 5.1556e-08. The run_mummichog analysis ranks the galactose metabolism pathway at rank 5 with a p-value of 0.00621796. In addition, Glycerophospholipid metabolism appears as a significantly enriched pathway, with run_ramp_enrichment ranking KEGG:hsa00564 (Glycerophospholipid metabolism) at rank 3 with an FDR of 3.86118e-08. Within the Galactose Metabolism pathway, specific metabolites are identified as pathway members, including galactitol, myo-inositol, sucrose, galactinol, and glycerol. Furthermore, galactitol drives the KEGG:hsa00052 pathway. These findings establish Galactose Metabolism as a robustly supported metabolic pathway in the analyzed dataset, with multiple metabolites confirmed as pathway constituents and significant enrichment demonstrated through distinct computational approaches.

**结构化 claims（10，全部 SUPPORTED）**

- `pathway_enrichment`（4）：
  - run_ramp_enrichment ranks KEGG:hsa00052 (Galactose Metabolism) at rank 2 with fdr 1.64e-12.
  - run_metaboanalystr_psea ranks KEGG:hsa00052 (Galactose Metabolism) at rank 0 with p_value 5.1556e-08.
  - run_mummichog ranks MUMM:galactose_metabolism (Galactose metabolism) at rank 5 with p_value 0.00621796.
  - run_ramp_enrichment ranks KEGG:hsa00564 (Glycerophospholipid metabolism) at rank 3 with fdr 3.86118e-08.
- `pathway_membership`（5）：
  - galactitol is a member of Galactose Metabolism.
  - myo-inositol is a member of Galactose Metabolism.
  - sucrose is a member of Galactose Metabolism.
  - galactinol is a member of Galactose Metabolism.
  - glycerol is a member of Galactose Metabolism.
- `driver_metabolite`（1）：
  - galactitol drives KEGG:hsa00052.

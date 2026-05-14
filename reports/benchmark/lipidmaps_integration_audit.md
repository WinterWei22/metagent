# LIPID MAPS Integration Audit for Sub-6 v3

Generated: 2026-05-08

## 1. Summary

| metric | v2 | v3 | delta |
|---|---:|---:|---:|
| Sub-6B mammalian tasks | 63 | 63 | 0 |
| lipid_metabolism bucket | 1 | 11 | 10 |
| amino_acid_metabolism bucket | 20 | 20 | 0 |
| central_metabolism bucket | 10 | 10 | 0 |
| nucleotide_metabolism bucket | 2 | 2 | 0 |
| other_metabolism bucket | 30 | 20 | -10 |
| unique pathways | 13 | 13 | 0 |
| LIPID MAPS pathway task share | 0% | 10/63 (15.9%) | +10 tasks |
| RaMP pathway task share | 63/63 (100.0%) | 53/63 (84.1%) | -10 tasks |

Result: **PASS for the lipid bucket target**. The lipid bucket increased from 1 to 11 tasks, meeting the accepted target of >=5 and the desired 8-15 range. Total task count stayed 63. The shift is primarily 10 LIPID MAPS/WikiPathways Lipids Portal eicosanoid tasks that were previously unavailable as usable lipid ground truth.

Historical note: `reports/benchmark/sub6_construction_report_v2.md` listed v2 buckets as amino_acid=21, central=10, lipid=1, nucleotide=4, other=27. Recomputing with the current classifier over the v2 task file gives amino_acid=20, central=10, lipid=1, nucleotide=2, other=30; the v3 comparison above uses direct task-file recomputation for consistency.

## 2. Source Breakdown

| source class | n_tasks | notes |
|---|---:|---|
| RaMP-only tasks | 53 | Ground truth from KEGG/Reactome/SMPDB/WikiPathways via RaMP |
| LIPID MAPS-only tasks | 0 | None; all retained LIPID MAPS tasks also had RaMP evidence for >=3 signal compounds |
| dual-supported tasks | 10 | LIPID MAPS ground truth plus RaMP top-pathway support |

Task source distribution in v3: kegg=36, lipidmaps=10, reactome=12, smpdb=1, wikipathways=4.

## 3. Sample Lipid Tasks

| task_id | ground_truth | source | signal compounds | RaMP cross-validation |
|---|---|---|---|---|
| `compound_only_enrich_mammalian_RAMP_P_000053042_seed9` | Steroid biosynthesis (`RAMP_P_000053042`) | wikipathways | C00280, C00468, C03917, C00535, C01227 | True |
| `compound_only_enrich_mammalian_lm_pathway_WP167_seed0` | Eicosanoid synthesis (`lm_pathway:WP167`) | lipidmaps | C00219, C00909, C04805, C04742, C14717 | True |
| `compound_only_enrich_mammalian_lm_pathway_WP167_seed1` | Eicosanoid synthesis (`lm_pathway:WP167`) | lipidmaps | C14717, C00909, C00219, C04742, C04805 | True |
| `compound_only_enrich_mammalian_lm_pathway_WP167_seed2` | Eicosanoid synthesis (`lm_pathway:WP167`) | lipidmaps | C04742, C00219, C04805, C14717, C00909 | True |
| `compound_only_enrich_mammalian_lm_pathway_WP167_seed3` | Eicosanoid synthesis (`lm_pathway:WP167`) | lipidmaps | C00219, C00909, C04805, C14717, C04742 | True |

The LIPID MAPS examples are all `lm_pathway:WP167` / Eicosanoid synthesis. This is useful for the v3 lipid bucket, but it also means the new lipid tasks are concentrated in one LIPID MAPS pathway.

## 4. Quality Gates

| gate | result | status |
|---|---:|---|
| ground_truth pathway in enrichment top-3 (RaMP OR LIPID MAPS) | 63/63 | PASS |
| duplicate signal IDs | 0 tasks | PASS |
| min unique signal compounds per task | 5 | PASS |
| pfocr ground-truth pathways | 0 | PASS |

For LIPID MAPS tasks, `ramp_enrichment_result.top_pathways` begins with the local LIPID MAPS enrichment top-3 and keeps RaMP hits after that; `lipidmaps_top_pathways` is also preserved explicitly in the payload. RaMP query logic itself was not replaced.

## 5. LIPID MAPS Coverage Statistics

| metric | value |
|---|---:|
| LMSD records loaded | 49882 |
| WikiPathways Lipids Portal unique pathway IDs | 42 |
| pathway compounds with LM_ID xrefs | 618 |
| curated v3 compounds with LMSD match | 67/250 |
| curated v3 compounds resolved to >=1 Lipids Portal pathway | 17/250 |
| lipid curated compounds with LMSD match | 26/50 |
| lipid curated compounds resolved to >=1 Lipids Portal pathway | 12/50 |
| average Lipids Portal pathways per resolved lipid compound | 3.17 |
| RaMP WikiPathways lipid-keyword pathways | 69 |
| Lipids Portal pathways overlapping RaMP-WikiPathways lipid set | 17 |
| Lipids Portal exclusive increment `|B-A|` | 25 |

Overlap decision: `|B-A|=25`, which falls in the **10-30 continue-with-limitation** band. This justified continuing D3/D4, but the audit should not claim a large independent pathway universe. The current gain comes from better LM_ID compound membership for a small number of curated lipid pathways, not from >=30 wholly new pathways.

Top LIPID MAPS pathways represented in curated v3 compounds:

| pathway | n_curated_compounds |
|---|---:|
| Eicosanoid synthesis (`lm_pathway:WP167`) | 5 |
| Eicosanoid metabolism via cyclooxygenases (COX) (`lm_pathway:WP4347`) | 3 |
| Eicosanoid metabolism via lipoxygenases (LOX) (`lm_pathway:WP4348`) | 3 |
| Eicosanoid metabolism via cytochrome P450 monooxygenases (`lm_pathway:WP4349`) | 3 |
| Eicosanoid metabolism via cyclooxygenases (COX) (`lm_pathway:WP4719`) | 3 |
| Eicosanoid metabolism via cytochrome P450 monooxygenases pathway (`lm_pathway:WP4720`) | 3 |
| Cholesterol metabolism with Bloch and Kandutsch-Russell pathways (`lm_pathway:WP4346`) | 2 |
| Cholesterol metabolism with Bloch and Kandutsch-Russell pathways (`lm_pathway:WP4718`) | 2 |
| Ergosterol biosynthesis (`lm_pathway:WP5354`) | 2 |
| Omega-3 / omega-6 fatty acid synthesis (`lm_pathway:WP4350`) | 2 |
| Omega-3 / omega-6 fatty acid synthesis (`lm_pathway:WP4723`) | 2 |
| Eicosanoid metabolism via lipooxygenases (LOX) (`lm_pathway:WP4721`) | 2 |

## 6. Provenance

- Git commit: `584253fa33318a5f38b71a4db0b627d43105ec31`
- Full build command:

```bash
PYTHONPATH=. python scripts/build_sub6/build_all.py \
    --hmdb-candidates data/processed/hmdb_candidates_npc_classified_v2.jsonl \
    --target-6b-mammalian 100 \
    --target-curated-hmdb 250 \
    --pathway-min-compounds 3 \
    --tasks-per-pathway-max 10 \
    --tasks-per-bucket-max 20 \
    --enable-lipidmaps \
    --output-dir data/benchmark/sub6/ \
    --report-path reports/benchmark/sub6_construction_report_v3_raw.md \
    --skip-spectrum-index \
    --seed 42
```

- Build wall time: 129.3s (`reports/benchmark/sub6_construction_report_v3_raw.md`).
- Data/source URLs:
  - LMSD REST export: `https://www.lipidmaps.org/rest/compound/lm_id/LM/all/download`
  - WikiPathways Lipids Portal: `https://www.wikipathways.org/communities/lipids.html`
  - WikiPathways per-pathway JSON: `https://www.wikipathways.org/wikipathways-assets/pathways/{WP_ID}/{WP_ID}.json`
- File MD5:
  - `data/benchmark/sub6/curated_hmdb_mammalian_v3.jsonl`: `3f6227a21b9a67d18e50027f832e7cd7`
  - `data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl`: `331b30a64017debe9d5ce07ed238e4f5`
  - `data/lipidmaps/lmsd_2026-05-08.tsv`: `e7d2b980ab04b8502bb77ace9a5a1951`
  - `data/lipidmaps/lipid_pathways_2026-05-08.json`: `36b332ed206a5b75088a4abea0535a6e`
  - `data/lipidmaps/overlap_check_2026-05-08.json`: `dc572feff9acb36e41ebda1010785a67`

## 7. Known Limitations / Future Work

- Lipids Portal currently contributed 42 unique pathway IDs, not >=100. The incremental set over RaMP-WikiPathways lipid-keyword pathways is 25, so this is a useful but limited additive source.
- v3 lipid tasks are concentrated in `Eicosanoid synthesis` (`WP167`): lipid bucket coverage improved to 11 tasks, but per-lipid-pathway diversity is still weak.
- LIPID MAPS / WikiPathways names are not always identical to KEGG/RaMP pathway names. Verifier Layer 6c substring/alias behavior may need a follow-up session before evaluating v3 narratives.
- Other bucket count drops from 30 to 20 because eicosanoid tasks now classify as lipid instead of other; this is intended bucket reclassification rather than broad spillover into non-lipid curation.
- Negative ion mode lipid spectra are out of scope for this data-construction session.
- Default build behavior remains unchanged unless `--enable-lipidmaps` is passed.

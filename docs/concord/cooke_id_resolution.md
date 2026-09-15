# Cooke 2025 SAMBA Tier-A — ID & Namespace Resolution (W6 D1.1)

**Recon date:** 2026-05-16
**Tier-A source:** [zenodo.org/records/13753914](https://zenodo.org/records/13753914) (CC-BY-4.0)
**Repo cross-reference:** [github.com/juliette-cooke/simulatedPA](https://github.com/juliette-cooke/simulatedPA) (MIT, `data/Human1/r_input/`)
**GEM annotation source:** [github.com/SysBioChalmers/Human-GEM](https://github.com/SysBioChalmers/Human-GEM) `model/metabolites.tsv`

## TL;DR

| Blocker | Resolved? | How |
|---------|-----------|-----|
| B-Cooke-1 metabolite ID | **Yes (2-hop)** | MAR (zscore row) → MAM (via `metab_dict.tsv`) → ChEBI (via Human-GEM `metabolites.tsv`) |
| B-Cooke-2 pathway ns | **Yes (placeholder)** | Cooke column header (`group1`…) → pathway-name (via `pathway_dict.tsv`) → emit as `HUMAN1:<slug>`. KEGG / Reactome name-fuzzy-match deferred to D4 Gate-2 metric phase. |

## B-Cooke-1 details

**Zscore TSV row index = MAR (Human1 reaction ID), not MAM (metabolite ID).** This is intentional in Cooke's design: SAMBA computes flux z-scores per reaction; exchange reactions (one reaction = one observable metabolite) are the exometabolome subset, and only those are biologically interpretable as "differential metabolite k went up under knockout j".

Two-hop chain:
1. `simulatedPA/data/Human1/r_input/metab_dict.tsv` — 1500 rows, columns `(ID, Name, metabID)` = `(MAR, common_name, MAM)`. This is **exactly the exchange-reaction subset**; non-exchange MARs are intentionally absent.
2. `Human-GEM/model/metabolites.tsv` — 8461 rows, columns `(mets, metsNoComp, metBiGGID, metKEGGID, metHMDBID, metChEBIID, metPubChemID, …)`. Compartment-tagged (MAM00001c / MAM00001e / …) but we dedupe on `metsNoComp` because annotations are compartment-invariant.

After dedupe + inner-join:
- 1500 exchange MARs total
- **694 (46.3 %)** have a ChEBI ID
- 704 (46.9 %) have a KEGG ID
- 529 (35.3 %) have an HMDB ID
- Of the **8665 MARs** in the Human1 zscore TSV, **408 (4.7 %)** are exchange-reaction MARs that resolve to a ChEBI ID

The 4.7 % is the dataset-intrinsic exometabolome ceiling — it is *not* a mapping-quality problem; it is Cooke's design choice that only ~500 of ~10 k modelled reactions correspond to externally observable metabolites.

## B-Cooke-2 details

`pathway_dict.tsv` maps perturbation column header → free-text subsystem name:
```
group1   Acyl-CoA hydrolysis
group3   Alanine, aspartate and glutamate metabolism
group8   Arachidonic acid metabolism
...
group999 (142 rows)
```

For W6 v1 we emit these as `HUMAN1:<slug>` (e.g. `HUMAN1:alanine_aspartate_and_glutamate_metabolism`). At Gate-2 metric time (D4) we will fuzzy-match these against the KEGG / Reactome / SMPDB pathway-name lists already loaded by the wrappers. Many should hit:
- "Pyrimidine metabolism" → KEGG `hsa00240` (exact name match)
- "Alanine, aspartate and glutamate metabolism" → KEGG `hsa00250` (exact)
- "Acyl-CoA hydrolysis" → no obvious KEGG/Reactome equivalent (Human1-specific) → keep `HUMAN1:` ns, Gate-2 marks as `ground_truth_unmatched` and skips per spec.

A reasonable upper bound for D4 namespace bridging: ~60-80 % of the 142 Cooke pathways will name-match a KEGG/Reactome pathway. Exact figure produced in D4 status entry.

## Task-count realisation

Sweep at threshold = `(z_threshold, min_differential)`, organism = Human1 only:

| z_threshold | min_diff=3 | min_diff=2 | min_diff=1 |
|-------------:|----------:|----------:|----------:|
| 2.0 (paper) |  19 |  26 |  41 |
| 1.5         |  23 |  30 |  44 |
| 1.0         |  30 |  49 |  68 |
| 0.5         |  75 | 110 | 117 |

At paper-canonical z=2.0 + min_diff=3 we have **19 tasks**, well under the W6 spec floor of **100 tasks**. This triggers stop-condition #3 ("Cooke ETL output 任务数 < 100 → 数据/mapping 问题").

### Root cause

- The Cooke dataset has only 119 perturbation columns (Human1 GEM) — not the "~300 × 2 GEM" the W6 spec assumed (which would have given 600 total). Recon2.2 download in progress; will combine.
- Per-perturbation z-distribution: at |z| > 2 most exchange MARs are NOT differential. Median differential count per task at z=2.0 is 5; many tasks have 0-2.
- The dataset is dataset-intrinsically sparse on the exometabolome layer.

### Options (need user sign-off before continuing)

| Option | N tasks | Trade-off |
|--------|---------|-----------|
| **A** Human1 only, z=2.0, min=3 (paper-canonical) | 19 | too few for Gate-2 stats; paper-faithful |
| **B** Human1 + Recon2.2 combined, z=2.0, min=3 | ~38-50 (pending Recon2.2 ETL) | paper-faithful, but probably still <100 |
| **C** Human1 only, z=1.0, min=2 (relaxed) | 49 | deviates from Cooke methods but stays within "differential" semantics |
| **D** Human1 only, z=0.5, min=2 (very relaxed) | 110 | hits 100 floor but no longer "differential" — these are "barely-perturbed" metabolites |
| **E** Human1 + Recon2.2, z=1.0, min=2 (relaxed combined) | TBD | likely > 100 with reasonable bio-significance |
| **F** Pivot Tier-A to a different in-silico panel | 0 → restart | drops ~1 d of W6 D1 work |

**Recommended:** option **E** — Human1 + Recon2.2 combined at z=1.0 + min=2. Rationale: keeps |z|>1 semantics ("≥ 1σ deviation from WT" — biologically defensible), combines both GEMs as W6 spec implied, and is the most likely route to ≥100 tasks without compromising the "differential metabolite" notion.

**Awaiting user decision.** Per W6 stop condition #1 the rule is "B-Cooke-1/2 unresolved > 2h → ping me" — we are at ~1h45min, B-Cooke-1/2 themselves are *resolved* (ID/namespace mapping works), the blocker is task-count tuning. Treating as soft block: continue Recon2.2 ETL, write up + ping.

## Artifacts produced

- `data/concord/tier_a_cooke/raw/Human1_zscores.tsv` (Zenodo, 27.9 MB)
- `data/concord/tier_a_cooke/raw/Recon2.2_zscores.tsv` (Zenodo, downloading)
- `data/concord/tier_a_cooke/aux/metab_dict_human1.tsv` (simulatedPA, 1500 exchange MARs)
- `data/concord/tier_a_cooke/aux/human_gem_metabolites.tsv` (Human-GEM annotation, 8461 mets)
- `data/concord/tier_a_cooke/aux/pathway_dict_human1.tsv` (simulatedPA, 142 groups)
- `data/concord/tier_a_cooke/tasks_human1.jsonl` (19 tasks at z=2.0, min=3)
- `concord/etl/cooke_etl.py` (parametric ETL)

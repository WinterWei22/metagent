# DECISIONS.md

## 2026-05-25 Autonomous Defaults

<!-- metagent-bench-autonomous-defaults -->

- D1 S1 gold pathway rule: use the deleted gene's public KEGG `eco` gene-to-pathway membership as candidate gold; keep genes with exactly one allowed metabolic KEGG pathway, or multi-pathway genes where Fuhrer EV3 CLR has exactly one significant pathway matching the allowed KEGG memberships. Require at least 5 KEGG-identified differential metabolites, EV3 AUC >= 0.70, abs(Z-score) >= 3.0, EV4 annotation rank <= 2, and EV4 AUC >= 0.70.
- D2 canonical ID strategy: preserve source IDs, normalize KEGG compound/pathway IDs first, and record RefMet -> RaMP as the planned unification layer when those resources are formally added.
- D5 easy strategy: use S4 first for easy tasks; do not build a new GEM source unless S4 leaves the easy split materially short.

## 2026-05-25 S3 Conservative Expansion

- S3 ST001142 may use DepMap 22Q2 Public Figshare article 19700056 `sample_info.csv` and `CCLE_mutations_bool_hotspot.csv` because both are CC BY 4.0 and individually below the download threshold. Full `CCLE_mutations.csv` is 258 MB and was not downloaded.
- S3 task generation is restricted to IDH1/IDH2 hotspot mutation -> 2-hydroxyglutarate, because the mechanism and ST001142 signal are directly supported. No broad mutation-to-metabolism expansion is allowed without separate evidence rules.

## 2026-05-25 S4 Recon2.2 Expansion

- S4 easy tasks include both Human1 and Recon2.2 simulated pathway knockout profiles from the same Cooke 2025 Zenodo sources. Ontology and metabolite `id_type` remain model-specific (`Human1` vs `Recon2.2`) to avoid mixing reconstruction identifiers.

## 2026-05-25 S6 ssPA Source Role

- S6 ssPA is retained as a pathway database/tool baseline source only. Its landed COVID example matrices do not provide source-level perturbed pathway ground truth, so `build/tasks_s6.jsonl` is intentionally empty.
- No S6 task may be generated from pathway enrichment output or inferred COVID biology without an explicit new gold-label rule.

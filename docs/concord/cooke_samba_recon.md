# Cooke 2025 SAMBA Benchmark — Recon (W5→W6 prep)

**Recon date:** 2026-05-16
**Time budget:** 30 min hard cap
**Mode:** schema reconnaissance only — no ETL, no full download

## Verdict: **GREEN**

Open-licence, sub-30 MB, plain TSV, single z-score table per GEM. ETL is straightforward.

## Source pointers

- **Paper:** Cooke, Wieder, Poupin, et al. "Simulated metabolic profiles reveal biases in pathway analysis methods." *Metabolomics* 21, 136 (2025). DOI [10.1007/s11306-025-02335-y](https://doi.org/10.1007/s11306-025-02335-y); preprint [bioRxiv 2025.03.27.645696](https://www.biorxiv.org/content/10.1101/2025.03.27.645696v1).
- **Code:** [github.com/juliette-cooke/simulatedPA](https://github.com/juliette-cooke/simulatedPA) (MIT licence, public clone, no auth).
- **Data:** [zenodo.org/records/13753914](https://zenodo.org/records/13753914) (CC-BY-4.0, anonymous download).

## Data schema (from Zenodo + GitHub README)

| File | Size | Format | What it is |
|------|-----:|--------|------------|
| `Human1_zscores.tsv` | 27.9 MB | TSV | per-metabolite z-scores under each Human1 pathway knockout |
| `Recon2.2_zscores.tsv` | 0.99 MB | TSV | per-metabolite z-scores under each Recon2.2 pathway knockout |

**Total dataset = 28.9 MB.** A single `git clone` of the code repo and two `curl -O` of the Zenodo files is sufficient.

### Per-task structure

- One "task" = one pathway knockout simulation (the knockout target *is* the ground-truth pathway label).
- Each task contributes a column of metabolite z-scores; high |z| → that metabolite is differentially abundant under that knockout.
- Differential-metabolite list is derived by thresholding z-scores (paper uses |z| > some cut-off; details in `src/` notebooks).
- Ground truth is **per-pathway** (the knocked-out pathway), not per-compound — i.e. for task k the "correct" answer is the single knockout-pathway ID.
- This matches our W5 D5 panel: "differential metabolite list + known perturbed pathway".

### GEMs

- **Human1 GEM** is *referenced* in the table column space (pathways come from Human1) but not a runtime dependency for parsing the z-score TSV — you only need it if you re-simulate SAMBA from scratch.
- Same for Recon2.2.
- For ConcordMet's W6 Gate-2 we only need the *output* z-scores → pathway labels, so **Human1 GEM is not required**.

## Dependencies

| Tool | Required for | Concord W6 needs? |
|------|--------------|-------------------|
| Python 3.7 + `requirements.txt` | re-run the analysis notebooks in `src/` | **No** — we just want the TSV |
| R 4.2.2 + `renv` | reproducing original PA-tool comparisons | **No** |
| Met4J ≥ 1.5.1 (Java) | network analysis in original paper | **No** |
| Cytoscape | visualisation only | **No** |
| SAMBA (separate GitLab) | regenerating z-scores from scratch | **No** — Zenodo TSVs are the SAMBA output |
| Human1 GEM | re-simulation | **No** for our use case |

**Net dependency for W6 = pandas. That's it.**

## ETL estimate

- **~0.5 day** total.
- Steps:
  1. Download two TSVs (curl, ~5 min).
  2. Parse z-score columns → per-(pathway-knockout, metabolite) z. (~30 min — pandas reshape).
  3. Per task: threshold |z| ≥ 2 (paper default) → differential metabolite list keyed by SAMBA/Recon ID; map to ChEBI via existing `concord.lookup.chebi` xref table (Human1 metabolites carry ChEBI IDs natively, Recon2.2 needs an extra `mnxref` hop already wired in `concord.etl.metanetx_etl`). (~1 h)
  4. Ground-truth pathway label = TSV column name; namespace it as `HUMAN1:` (new namespace, document in `concord/schema/enrichment.py` whitelist). (~30 min)
  5. Write `data/benchmark/cooke_samba/cooke_tasks_v1.jsonl` in the same shape as `sub6b_mammalian_tasks_v3.jsonl` (differential_metabolites + ground_truth_pathway). (~30 min)
  6. Smoke-test one task through the W5 D4 4-axis driver. (~30 min)

## Blockers

- **None hard.** Two soft ones to flag in W6 D1 status:
  - **B-Cooke-1** (LOW): TSV columns are SAMBA-internal metabolite IDs (not necessarily standard HMDB/ChEBI). Need to inspect the actual file headers to confirm the ID format — README does not specify. If they are Human1 RAVEN-style IDs, MetaNetX `mnx_xref` table likely covers them, but worth a 30-min toy check before promising the 0.5 d ETL.
  - **B-Cooke-2** (LOW): Pathway IDs in column space (knockout targets) — README does not specify whether they are Recon2.2 subsystem strings or Human1 group IDs. Need to decide a stable namespace prefix when introducing the new dataset into the W4 v0.3 schema.

Both blockers are resolved by `head -1 Human1_zscores.tsv` once the file is on disk — i.e. minutes once we start ETL, not days.

## Recommendation

GREEN to start W6 D1 ETL. Suggested order:

1. Download both TSVs.
2. Inspect headers (1 line each) to resolve B-Cooke-1 and B-Cooke-2 before writing any glue code.
3. Smoke a single task end-to-end through the existing W5 4-axis driver before scaling to "all N pathway knockouts."

Estimated W6 D1 wall ≈ 4-6 h once started.

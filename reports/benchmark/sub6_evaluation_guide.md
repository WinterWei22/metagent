# Sub-6 Evaluation Guide

**Companion to:** `reports/benchmark/sub6_construction_report.md`
**Data location:** `data/benchmark/sub6/`
**Date:** 2026-04-30
**Scope:** Mammalian-only (Plant subset removed — see construction report §10).

This guide tells you (a) what the framework is supposed to consume from
each task, (b) what counts as "correct," (c) the traps that will silently
inflate scores if not handled, and (d) where the data itself limits what
you can claim.

---

## 1. Quick start

You have **two task types** to evaluate against:

```
data/benchmark/sub6/
├── sub6b_mammalian_tasks.jsonl   20 tasks   compound-only enrichment (Stage 2 isolated)
├── sub6a_e2e_tasks.jsonl         14 tasks   end-to-end: spectra → identification → enrichment
├── curated_hmdb_mammalian.jsonl 150 records reference compound pool
└── curation_audit.md                        per-step drop counts
```

### Sub-6B (compound-only) — what your framework receives

```python
task["differential_metabolites"]  # list of CuratedCompound dicts (5-8 signal + 2-5 noise, shuffled)
                                   # each has: name, smiles, inchikey, kegg_id, hmdb_id, npc_*
```

Your framework should **not** see ``ground_truth_*`` — those are kept on
the task only for grading.

### Sub-6A (end-to-end) — what your framework receives

```python
task["differential_spectra"]      # list of 9 (avg) GNPS spectra, each with:
                                   #   peaks: list[(m/z, intensity)]
                                   #   precursor_mz, adduct, ion_mode, collision_energy
                                   #   instrument, instrument_type, source_id
                                   # NOT given: inchikey, smiles, name (your framework
                                   # has to identify them from peaks).
```

Both task types carry the **same ground-truth fields** for grading:
``ground_truth_pathway`` / ``ground_truth_signal_compounds`` /
``ground_truth_noise_compounds`` / ``ramp_enrichment_result``.

---

## 2. Data contract per task

| Field | Sub-6B has? | Sub-6A has? | Use it for |
|---|---|---|---|
| ``task_id`` | ✓ | ✓ | logging |
| ``task_type`` | ``compound_only_enrichment`` | ``end_to_end_enrichment`` | dispatch |
| ``domain`` | ``mammalian`` | ``mammalian`` | stratification (always mammalian here) |
| ``differential_metabolites`` | ✓ | None | input to model (6B) |
| ``differential_spectra`` | None | ✓ | input to model (6A) |
| ``ground_truth_pathway`` | ✓ | ✓ | grading (top-1/top-3 hit) |
| ``ground_truth_signal_compounds`` | ✓ | ✓ | grading (driver precision/recall) |
| ``ground_truth_noise_compounds`` | ✓ | ✓ | grading (false-positive driver detection) |
| ``ramp_enrichment_result.top_pathways`` | ✓ | ✓ | top-3 acceptance set (10 candidates with FDR) |
| ``id_type`` | ``"kegg"`` | ``"kegg"`` | tells you signal/noise IDs are KEGG (e.g. C00070) |
| ``signal_count`` / ``noise_count`` | ✓ | ✓ | sanity check |
| ``seed`` / ``cli_seed`` | ✓ | ✓ | reproducibility |

### `ground_truth_pathway` schema

```json
{
  "pathway_id":      "RAMP_P_000000106",
  "pathway_name":    "Tyrosine metabolism",
  "pathway_source":  "kegg",                    // kegg | reactome | smpdb | wikipathways
  "external_id":     "map00350",
  "primary_pathway_pre_aggregation": "RAMP_P_000000106"
}
```

### `ramp_enrichment_result.top_pathways[i]` schema

```json
{
  "pathway_id":              "RAMP_P_000000106",
  "pathway_name":            "Tyrosine metabolism",
  "pathway_source":          "kegg",
  "pathway_external_id":     "map00350",
  "total_pathway_compounds": 69,                // K (RaMP-wide)
  "matched_compounds":       ["C00070", "C00122", ...],  // input subset hit
  "p_value":                 1.2e-13,
  "fdr":                     2.4e-11,            // BH-corrected
  "fold_enrichment":         559.4
}
```

`top_pathways` is sorted by FDR ascending. Use `top_pathways[:3]` as the
acceptance set for top-1 / top-3 hit metrics (see §4).

---

## 3. Critical pitfalls — read before running

### 🔴 Pitfall 1: GNPS self-matching leakage (Sub-6A only)

**The problem:** `differential_spectra` are pulled from the GNPS library.
If your framework's identification stage (e.g. `tools/library_search`)
also queries GNPS, every input spectrum will trivially self-match — top-1
accuracy will inflate ~30-50 percentage points and cascade-decomposition
numbers will be meaningless.

**The fix:** before each Sub-6A task runs identification, build a
**per-task GNPS exclusion list** from the task itself:

```python
exclusion_ids = [s["source_id"] for s in task["differential_spectra"]]
# every source_id starts with "CCMSLIB..."
```

Pass `exclusion_ids` into `library_search` (analogous to the NM-002
exclusion list in `data/processed/nm002_excluded_gnps_ids.json`). The
audit field `library_membership` on each spectrum tells you which GNPS
sub-library it came from (most are `BMDMS-NP` or `GNPS-LIBRARY`); you
may want to log it for stratified reporting.

**This is non-negotiable.** Without it, Sub-6A scores cannot be
compared to Sub-6B (cascade contribution will be near zero or
even negative).

### 🟡 Pitfall 2: Compound identity space mismatch

`ground_truth_signal_compounds` is a list of **KEGG IDs**
(e.g. `["C00070", "C00122"]`), and `top_pathways[*].matched_compounds`
also use KEGG IDs. But:

* Your framework's library_search probably returns **InChIKey** or
  internal IDs.
* CuratedCompound entries in `differential_metabolites` (Sub-6B) carry
  *both* `kegg_id` and `inchikey` — convert via the dict directly.
* For Sub-6A, you must resolve KEGG ↔ InChIKey via either the curated
  compound pool (`curated_hmdb_mammalian.jsonl`) or RaMP `source` table.

**Recommended bridge:** for both task types, lift everything to **InChIKey
first-block** for comparison. The curated pool gives you the mapping for
all 150 mammalian compounds.

### 🟡 Pitfall 3: Pathway hit comparison

LLM narratives output pathway *names*, not RaMP IDs. Don't compare on
`pathway_id` — compare on **normalized name** (lowercase + collapsed
whitespace) AND optionally accept a top-3 match:

```python
def is_pathway_hit(predicted_name: str, task) -> bool:
    norm = predicted_name.lower().strip()
    top3_names = [p["pathway_name"].lower().strip()
                   for p in task["ramp_enrichment_result"]["top_pathways"][:3]]
    return any(norm in n or n in norm for n in top3_names)
```

The substring fuzz is needed because LLMs say "Tyrosine catabolism"
where the canonical name is "Tyrosine metabolism." For stricter
evaluation, also keep an exact-match column.

### 🟡 Pitfall 4: Multiple acceptable pathways per task

In `top_pathways[:3]`, the second/third entries are often biologically
*related* pathways (same compounds, related biology — e.g. `Tyrosine
metabolism (KEGG)` + `Alkaptonuria (SMPDB)` + `Dopamine beta-hydroxylase
deficiency (SMPDB)` all surface together). Treating the top-3 set as
acceptable ground truth (not just `top_pathways[0]`) is the
standard convention for enrichment benchmarks; treating only top-1
will undercount LLMs that pick a near-miss.

Report **both** "top-1 strict accuracy" and "top-3 set acceptance" so
the comparison is unambiguous.

### 🟡 Pitfall 5: Sub-6A ↔ Sub-6B pairing for cascade decomposition

The 14 Sub-6A tasks are derived from a subset of the 20 Sub-6B tasks
(those whose differential compounds had ≥3 GNPS/MassBank spectra).
**They do not pair 1-to-1.** Pair via `ground_truth_pathway.pathway_id`
plus `seed`:

```python
# Each e2e task carries a `seed` derived from its parent 6B task; the
# parent's seed survives in `ramp_enrichment_result.input_compounds`
# (same compound list).
def parents(e2e_task, mam_tasks):
    return [m for m in mam_tasks
            if m["ground_truth_pathway"]["pathway_id"]
                == e2e_task["ground_truth_pathway"]["pathway_id"]
            and m["ground_truth_signal_compounds"]
                == e2e_task["ground_truth_signal_compounds"]]
```

For cascade decomposition (`6A_error − 6B_error`), restrict the Sub-6B
denominator to the 14 paired tasks — don't compare 14 e2e against the
full 20 compound-only.

### 🟢 Pitfall 6: Negative-mode ion handling

30% of Sub-6A spectra are negative mode (`[M-H]1-`). Make sure your
identification stage handles negative mode — Sub-6A specifically tests
this since RIKEN-side NM-001 mitigation is in scope here. Check the
distribution:

```python
sum(1 for t in e2e for s in t["differential_spectra"] if s["ion_mode"] == "negative")
# 38 / 128 spectra
```

### 🟢 Pitfall 7: Collision energy is missing for ~60% of spectra

GNPS metadata has `collision_energy` populated for only 49/128 spectra
in Sub-6A. Don't gate identification on CE; treat None as "unknown."
SIRIUS works with no-CE input but with reduced accuracy.

---

## 4. Recommended metrics

### Per-task

| Metric | Definition | Notes |
|---|---|---|
| **Top-1 pathway accuracy (strict)** | Did LLM's first-mentioned pathway equal `ground_truth_pathway.pathway_name` (case-insensitive substring match)? | Strictest. |
| **Top-3 pathway acceptance** | Did LLM's top-mentioned pathway appear (substring match) in `top_pathways[:3]`? | Standard. Use this in headline numbers. |
| **Driver precision** | Of compounds LLM cited as drivers, how many are in `ground_truth_signal_compounds`? | Compare on InChIKey first-block. |
| **Driver recall** | Of `ground_truth_signal_compounds`, how many did LLM cite? | Same. |
| **False-noise rate** | Of compounds LLM cited as drivers, how many are in `ground_truth_noise_compounds`? | Hallucination indicator. |
| **Off-pathway hallucination** | LLM mentioned a pathway not in `top_pathways[:10]`? | Frame counts. |

### Aggregate (Sub-6B / Sub-6A separately)

* **Mean top-1 accuracy / top-3 acceptance**.
* **Bucket-stratified accuracy** (split by `_classify_pathway_bucket(t["ground_truth_pathway"]["pathway_name"])`):
  current data: `amino_acid_metabolism=6, lipid_metabolism=1, nucleotide_metabolism=5, other_metabolism=8`. Skip `central_metabolism` (0 tasks — see §5).
* **Cascade decomposition** (paired-only): `6A_metric − 6B_metric` on
  the 14 paired tasks.

### Per-claim (verifier track)

If you wire in a verifier (Sub-6 protocol §3.6.6), claims fall into:
`SET_ENRICHMENT` / `DRIVER_METABOLITE` / `BIOLOGICAL_SIGNIFICANCE` /
`PATHWAY_RELATIONSHIP`. The fields `top_pathways[*].matched_compounds`
+ `ground_truth_signal_compounds` cover Type 6a/6b verification
directly.

---

## 5. What this benchmark CANNOT defensibly measure

Be explicit about scope in your write-up:

* **Plant secondary metabolism.** Subset removed; RaMP non-pfocr
  coverage is empty for anthocyanin / flavonoid / phenylpropanoid.
  Don't claim plant pathway accuracy from this data.
* **Central metabolism (glycolysis / TCA / pentose phosphate).** 0 tasks.
  HMDB-Mammalian central compounds collide on broad Reactome clusters;
  the bucket router lands them in `other_metabolism`. Cannot claim
  central metabolism accuracy.
* **Lipid metabolism.** 1 task only. Treat as anecdotal.
* **End-to-end at scale.** 14 Sub-6A tasks. Treat e2e numbers as
  directional, not statistically powerful.
* **Cross-database pathway consistency.** Ground truth is **RaMP-DB
  v2025-03-06 snapshot only**. KEGG / Reactome live data may have
  drifted; report the snapshot date.

---

## 6. Run checklist

Before you launch evaluation:

- [ ] Built per-task GNPS exclusion list and threaded it into `library_search`
- [ ] Identification stage handles both positive and negative ion modes
- [ ] Pathway hit comparison uses **substring/fuzzy match on names**, not pathway IDs
- [ ] Driver compound comparison normalises everything to **InChIKey first-block**
- [ ] Per-task results saved incrementally (idempotent re-run) — Sub-6A is
      slow per task (9 spectra × identification cost)
- [ ] Cascade decomposition uses **paired** Sub-6A ↔ Sub-6B subset only
- [ ] Final report makes the §5 scope limitations explicit

---

## 7. Provenance

* **Construction commit:** `git rev-parse HEAD` from the build run (also
  stamped in `sub6_construction_report.md` §9).
* **RaMP-DB snapshot:** 2025-03-06.
* **NPClassifier batch:** see
  `reports/benchmark/npclassifier_classification_audit_2026-04-29.md`.
* **GNPS source:** `ALL_GNPS_cleaned_enriched.csv` + `ALL_GNPS_cleaned.mgf`
  (985,492 records scanned, 3,416 quality-filtered for Sub-6A).
* **MassBank source:** 12 non-RIKEN contributors (54,124 files scanned,
  177 quality-filtered for Sub-6A).

If you need to reproduce or refresh:
```bash
python -m scripts.build_sub6.build_all   # full rebuild, ~90s
```

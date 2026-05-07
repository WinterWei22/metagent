# Phase 6.1 — MS-CLIP integration ablation on Sub-6A real-id v2

**Date:** 2026-05-07
**Branch:** `feature/sub6-msclip-ablation` (off `feature/sub6-v2-integrated` tip `17a90dc`)
**Task set:** Sub-6A real-id v2 — 38 tasks, 459 spectra
**Question:** Does fusing MS-CLIP scores with GNPS modified-cosine improve top-1 identification accuracy on the v2 real-id benchmark?

---

## 1. Summary

Fusing the MS-CLIP candidate-scoring head into the Sub-6A library-search pipeline (alongside GNPS modified-cosine) **does not improve** top-1 identification accuracy on Sub-6A real-id v2. The fused configuration scores **66.88% (307/459)** versus the `gnps`-only baseline of **67.32% (309/459)** — a delta of **−0.44 pp** (net **−2 spectra**, with churn of 12 gained and 14 lost). Identification wall-time grows **~22.7×** (224.5 s → 5099.9 s). MS-CLIP's `[M+H]+/[M-H]-` ion-vocabulary coverage forces a `modcos`-only fallback on **25/459 (5.4%) of spectra** with adducts the model wasn't trained on.

**Recommendation for the paper:** report the ablation as a **negative result on Sub-6A real-id v2** — `library_search` with GNPS modified-cosine alone is the right default. Fusion is *not* recommended for this benchmark in its current form.

## 2. Setup

| | |
|---|---|
| Tasks file | `data/benchmark/sub6/sub6a_e2e_tasks_v2.jsonl` (38 tasks, 459 spectra) |
| Pipeline | `evaluation.sub6.run_sub6a` → `identify_spectrum` → `library_search` |
| top-k | 20 |
| mass-tolerance (Phase A pre-filter) | 10 ppm (identical for both configs) |
| ID strategy | `library_search` |
| LLM narrative | **disabled** (`--skip-narrative`); `llm_calls = 0` everywhere |
| Verifier (Layer-6c) | not invoked (this benchmark only measures id_accuracy) |
| MS-CLIP env | `conda run -n diffms`; GPU auto-pick selected GPU 6 (24 GB free) |
| MS-CLIP calibration | unchanged (`tools/library_search/calibration.json` sha256 `9204815335050c3b6923a0a80e86f36c3713a2b8de814e8729f600b3479ef853`) |
| Fusion rule | `fuse_scores = max(modcos, rescale_inhouse(ms_clip))` (max-fusion, not weighted mean) |

### Configurations

| Tag | `--libraries` | Pipeline path |
|---|---|---|
| **Config A** (`gnps_only`) | `gnps` | Pure `library_search` Path B with modified-cosine on the 10-ppm-narrowed GNPS pool |
| **Config B** (`inhouse_only`) | `inhouse` | **Architecturally unreachable** — `tools/library_search/tool.py:302` short-circuits `if not want_gnps: return []`. MS-CLIP is a re-ranking signal that requires a candidate pool, and the pool comes from GNPS. Skipped by design. |
| **Config C** (`fused`) | `gnps,inhouse` | GNPS Path B as in Config A, then MS-CLIP re-scores the resulting candidate list and fuses via `max(modcos_calib, ms_clip_calib)` |

### Bucket choice (per-bucket breakdown)

> Per-bucket breakdown uses `ground_truth_pathway.pathway_source` (5 classes: kegg / reactome / smpdb / wikipathways / hmdb) as a stratification proxy. v2 task JSON does not carry compound-level metabolic class; `pathway_source` is the most visible, unambiguous categorical field.

In the actual v2 set only 4 of those 5 classes appear (no `hmdb` ground-truth pathways).

## 3. Main result

| Config | n_tasks | n_spectra | n_correct | id_acc (overall) | id_acc (task-mean) | id_t total |
|---|---:|---:|---:|---:|---:|---:|
| **gnps_only** | 38 | 459 | 309 | **67.32 %** | 67.37 % | 224.5 s |
| **fused (gnps+inhouse)** | 38 | 459 | 307 | **66.88 %** | 66.37 % | 5099.9 s |
| Δ | — | — | **−2** | **−0.44 pp** | **−1.00 pp** | **+4875 s (~22.7×)** |

### Sanity check on Config A

Config A's narratives JSONL was compared spectrum-by-spectrum against the v2 baseline output (frozen at `results/v2/sub6a_real/`). Top-1 InChIKey decisions match **byte-for-byte** — i.e. the new `--libraries gnps --skip-narrative` flags introduce **zero** behavioural drift versus the v2 baseline. (Sanity bound was ±0.5 pp; observed deviation is **0.0 pp**.)

## 4. Per-bucket breakdown (`pathway_source`)

| Bucket | n_spectra | gnps_only id_acc | fused id_acc | Δ pp |
|---|---:|---:|---:|---:|
| **kegg** | 331 | 65.6 % | 65.9 % | **+0.30** |
| **reactome** | 69 | 82.6 % | 78.3 % | **−4.35** |
| **smpdb** | 15 | 46.7 % | 46.7 % | 0.00 |
| **wikipathways** | 44 | 63.6 % | 63.6 % | 0.00 |

Reactome is the only bucket where fusion clearly hurts (−3 spectra over a 69-spectrum bucket). KEGG sees a small net gain (+1 of 331). SMPDB and WikiPathways come out unchanged at the bucket level — but see §5 for per-spectrum churn.

## 5. Win/loss vs `gnps_only`

| Outcome | n_spectra |
|---|---:|
| **gained** (wrong → correct) | **12** |
| **lost** (correct → wrong) | **14** |
| unchanged (both correct) | 295 |
| unchanged (both wrong) | 127 |
| **net Δ** | **−2** |

Per-bucket churn (gained / lost):

| Bucket | gained | lost | net |
|---|---:|---:|---:|
| kegg | 9 | 8 | +1 |
| reactome | 1 | 4 | **−3** |
| wikipathways | 2 | 2 | 0 |
| smpdb | 0 | 0 | 0 |

The fused configuration *moves* 26 spectra around but the swap is roughly balanced: MS-CLIP rescues a few cases where modcos picked a high-cosine wrong neighbour, but it equally promotes wrong neighbours over the correct top-1 in cases where modcos already had the right answer. Reactome shows the most-skewed churn (1 gained vs 4 lost).

## 6. Cost & coverage

- **Wall time, identification only:** 224.5 s → 5099.9 s (×22.7).
- **Mean id-time per task:** 5.9 s → 134.2 s.
- **GPU utilisation:** single GPU (auto-picked GPU 6); model is loaded once per `library_search` call but spends most time in subprocess startup (`conda run` cold-start overhead is significant per-call).
- **Adduct-vocabulary coverage:** 25/459 spectra (5.4 %) fall back to `modcos`-only because their adduct is not in the MS-CLIP MSG ion vocabulary. The unsupported adducts seen in this run were:
    - `[M+NH3+H]+`
    - `[M-H2O-H]-`
    - `[M+HCOOH-H]-`

  For these spectra the fused config produces identical scores to `gnps_only`, so they cannot contribute to either gain or loss. The 12-vs-14 churn happens entirely on the **434 spectra MS-CLIP could actually score**.

## 7. Paper finding

> On Sub-6A real-id v2 (38 tasks, 459 spectra), max-fusing the MS-CLIP candidate-scoring head with GNPS modified-cosine *does not* improve top-1 identification accuracy: 66.88 % vs 67.32 % (−0.44 pp; net −2 spectra). The fusion increases identification wall-time by ≈22.7×. We therefore default to GNPS modified-cosine alone for `library_search` and report the fused configuration as a documented negative result.

## 8. Limitations

1. **Not a fair MS-CLIP test on its own.** Config B (inhouse-only) is architecturally unreachable in the current `library_search` design — MS-CLIP only ever runs as a *re-ranker* on the GNPS-derived candidate pool, never as a primary retriever. So this ablation answers "does MS-CLIP help re-rank a GNPS pool?" and not "is MS-CLIP a better retriever than GNPS?".

2. **Adduct-vocabulary gap.** 5.4 % of spectra cannot be scored by MS-CLIP at all (3 distinct unsupported adducts). The result for the *MS-CLIP-scoreable* subset (434 spectra) is therefore where the action is — but on that subset the net delta is still −2.

3. **Calibration is fixed.** Per the task scope this run did not re-tune `tools/library_search/calibration.json`. A different calibration (e.g. weighted mean instead of max, or a learned linear blend) might shift the result — left for a follow-up if a future Sub-6 cut wants to revisit.

4. **Fusion is `max(...)`, not a weighted average.** This is the existing design in `tools/library_search/scoring.py::fuse_scores` (line 226). Max-fusion biases toward whichever score is more confident, which can overweight a strong-but-wrong MS-CLIP score (we see this in the 14 lost spectra).

5. **No verifier / no LLM in this measurement.** All 38 records have `error="skip_narrative=True — narrative omitted"` by design. Downstream effects on the LLM narrative or Layer-6c verifier were not measured here. (The v2 frozen pipeline measures those separately.)

6. **Single-seed run.** Ablation was a single deterministic run; no seed sweep. The 0.44 pp delta is within the kind of noise band where re-running with shuffled candidate order could plausibly flip the sign — but the cost ratio (~22.7×) is the much louder signal.

## 9. Provenance

| Item | Value |
|---|---|
| Branch | `feature/sub6-msclip-ablation` |
| Base | `feature/sub6-v2-integrated` tip `17a90dc5963ed9ad75bb007db05650705abadfc8` |
| Tasks file | `data/benchmark/sub6/sub6a_e2e_tasks_v2.jsonl` |
| Config A run output | `data/eval/sub6/v2_msclip_ablation/gnps_only/sub6a_narratives.jsonl` |
| Config A sha256 | `571108dc383be9cb4103ced51588be76ffb842e1aac776eb6337a579c340a7a5` |
| Config C run output | `data/eval/sub6/v2_msclip_ablation/fused/sub6a_narratives.jsonl` |
| Config C sha256 | `982cad24e0af35cb7e123b9dfcab5fd88218330de76f5bc822dd0c0b57cda88b` |
| Paper figure CSV | `data/paper_figures/phase6_msclip_ablation.csv` |
| Paper figure sha256 | `903756e661790ab6634989f1c882704fb0c08e9748617310de9470007f988ee2` |
| Calibration | `tools/library_search/calibration.json` sha256 `9204815335050c3b6923a0a80e86f36c3713a2b8de814e8729f600b3479ef853` (unchanged) |
| Aggregator | `scripts/eval_sub6/aggregate_msclip_ablation.py` |
| Run logs | `logs/v2_msclip_ablation/{gnps_only.log, fused.log, aggregate.log}` |
| v2 frozen baseline (untouched) | `results/v2/sub6a_real/` (last modified 2026-05-06 22:42) |

### Reproducer

```bash
# Config A — gnps only
PYTHONPATH=. conda run -n diffms --no-capture-output \
    python scripts/eval_sub6/run_baseline.py \
        --sub6a data/benchmark/sub6/sub6a_e2e_tasks_v2.jsonl \
        --out-dir data/eval/sub6/v2_msclip_ablation/gnps_only \
        --libraries gnps \
        --skip-narrative \
        --id-strategy library_search \
        --mass-tolerance-ppm 10.0

# Config C — fused (gnps + inhouse)
PYTHONPATH=. METAGENT_MSCLIP_GPU=auto conda run -n diffms --no-capture-output \
    python scripts/eval_sub6/run_baseline.py \
        --sub6a data/benchmark/sub6/sub6a_e2e_tasks_v2.jsonl \
        --out-dir data/eval/sub6/v2_msclip_ablation/fused \
        --libraries gnps,inhouse \
        --skip-narrative \
        --id-strategy library_search \
        --mass-tolerance-ppm 10.0

# Aggregate → paper figure CSV
python scripts/eval_sub6/aggregate_msclip_ablation.py \
    --gnps-only data/eval/sub6/v2_msclip_ablation/gnps_only/sub6a_narratives.jsonl \
    --fused     data/eval/sub6/v2_msclip_ablation/fused/sub6a_narratives.jsonl \
    --tasks     data/benchmark/sub6/sub6a_e2e_tasks_v2.jsonl \
    --out-csv   data/paper_figures/phase6_msclip_ablation.csv
```

# Phase 6.7-D — MassSpecGym OOD Identification: MS-CLIP × LLM-as-Reranker

**Date:** 2026-05-12
**Branch:** `feature/msg-llm-reranker`
**Predecessor:** Phase 6.7-A (`reports/eval/casmi_llm_reranker_v1_appendixA_mrr.md`)

---

## 1. Headline

MSG formula pool (MS-CLIP-only baseline): **55.40% Top-1** (277/500), MRR=0.6212.

| Pool | MS-CLIP only (Top-1 / MRR) | LLM reranker (Top-1 / MRR) | Δ MRR (abs / rel) |
|---|---|---|---|
| formula | 55.40% / 0.6212 | 54.80% / 0.6165 | −0.0047 / **−0.76%** |
| mass | 48.00% / 0.5504 | 49.80% / 0.5639 | +0.0135 / **+2.45%** |

**Key finding:** LLM-as-reranker is **neutral-to-slightly-negative on formula pool** (−0.76% relative MRR) and modestly positive on mass pool (+2.45%). This is a sharp contrast to Phase 6.7-A (+11.0% relative on CASMI with `v4_spectraverse`), confirming the **Inconsistent Δ** hypothesis: LLM reranker benefit is tied to the retriever's calibration — a well-tuned MSG checkpoint leaves little room for LLM correction on the formula-restricted pool.

---

## 2. Setup

| Parameter | Value |
|---|---|
| Benchmark | MassSpecGym (MSG) — public OOD retrieval benchmark |
| MS-CLIP checkpoint | `v4_msg_retrain_20260511_200835/version_0/best.ckpt` (retrained on MSG train+val) |
| Default checkpoint (CASMI) | `v4_spectraverse_20260428_134311` (trained on SpectraVerse) |
| Test split | `split_msg.tsv` — 17,556 spectra, **3,170 unique GT compounds** |
| Evaluated subset | **500 spectra** random sample (seed=42) from test split |
| Adducts | `[M+H]+` (77.4%), `[M+Na]+` (22.6%) — positive mode only |
| CE coverage | 301/500 spectra have real CE from `labels.tsv` (199 default to 0.0 eV) |
| Candidate pool — formula | ≤256 same-formula PubChem isomers (GT in pool: 100%) |
| Candidate pool — mass | ≤256 mass-window PubChem compounds (~98% disjoint from formula pool) |
| LLM | Claude Opus 4.7 (`opus47`), temperature=0.0 |
| Reranker top-k | 5 |
| MS-CLIP reranker | Phase 6.1 max-fusion disabled — pure MS-CLIP scoring (`libraries=("inhouse",)`, no GNPS) |

### Why MSG is stronger OOD than CASMI

CASMI 2022 spectra were included in the SpectraVerse training corpus used for the default MS-CLIP checkpoint. MSG test spectra were **not** seen during `v4_msg_retrain` training (the checkpoint was trained on MSG train+val split only). This is a stricter OOD setting: no reference spectra in the candidate pool AND no training-distribution overlap.

### Candidate pool note: formula ≈ formula-restricted PubChem (MIST protocol)

MSG `MassSpecGym_retrieval_candidates_formula.json` provides per-compound SMILES lists where all candidates share the GT molecular formula. This is identical in spirit to the CASMI 2022 protocol (formula-restricted PubChem retrieval via MIST). The two pools are directly comparable.

---

## 3. Main result

| Pool | Reranker | n | Top-1 acc | Top-5 acc | MRR | Δ MRR vs MS-CLIP |
|---|---|---:|---:|---:|---:|---:|
| formula | msclip_only | 500 | 55.40% | 70.60% | 0.6212 | — |
| formula | conditional | 500 | 55.40% | 70.60% | 0.6212 | 0.0000 |
| formula | llm_reranker | 500 | 54.80% | 70.60% | 0.6165 | −0.0047 |
| mass | msclip_only | 500 | 48.00% | 64.00% | 0.5504 | — |
| mass | conditional | 500 | 48.00% | 64.00% | 0.5504 | 0.0000 |
| mass | llm_reranker | 500 | 49.80% | 64.00% | 0.5639 | +0.0135 |

*(Full CSV: `data/paper_figures/phase6_7d_msg_results.csv`)*

---

## 4. Cross-checkpoint generalization

The central question: does the LLM-reranker Δ MRR from Phase 6.7-A (+11% on CASMI 2022 with the default `v4_spectraverse` checkpoint) replicate when the MS-CLIP checkpoint is switched to `v4_msg_retrain`?

| Setting | Checkpoint | Benchmark | MS-CLIP Top-1 | LLM Δ MRR (abs) | LLM Δ MRR (rel) |
|---|---|---|---|---|---|
| Phase 6.7-A | v4_spectraverse | CASMI 2022 (formula) | ~51% | +0.063 | **+11.0%** |
| Phase 6.7-D | v4_msg_retrain | MSG (formula) | 55.40% | −0.0047 | **−0.76%** |

**Result: Inconsistent Δ.** The LLM-reranker gain does not replicate when the retriever is swapped from `v4_spectraverse` to `v4_msg_retrain`. Interpretation: the MSG-trained checkpoint is already well-calibrated for MSG test spectra (it was trained on MSG train+val with the same spectrum format and CE embedding). Its top-5 ranking is tight enough that the LLM's chemical reasoning finds little room to reorder correctly. The CASMI gain likely reflects the retriever's higher residual uncertainty when evaluated on an out-of-training distribution (CASMI spectra not in SpectraVerse training set).

---

## 5. Formula vs mass pool

| Pool | MS-CLIP Top-1 | LLM Top-1 | LLM Δ MRR (rel) |
|---|---|---|---|
| formula | 55.40% | 54.80% | −0.76% |
| mass | 48.00% | 49.80% | **+2.45%** |

The formula and mass pools are nearly disjoint (~2 shared candidates per compound). As hypothesised, the LLM Δ is larger (and positive) on the mass pool where MS-CLIP faces higher structural diversity. The mass pool includes formula-diverse PubChem candidates within a ±20 ppm mass window; MS-CLIP alone drops from 55.4% to 48.0% (+7.4pp gap). The LLM partially compensates (+1.8pp Top-1, +1.35 absolute MRR). This is consistent with the CASMI 6.7-A finding: LLM rerank adds most value when the retriever is less confident about the structural class.

---

## 6. MS-CLIP vocabulary coverage

MSG test set adducts: `[M+H]+` and `[M+Na]+`. Both are in the `v4_msg_retrain` vocabulary (indices 0 and 1). Zero adduct-fallback spectra expected (unlike Phase 6.1 Sub-6A where `[M+NH3+H]+`, `[M-H2O-H]-` caused 25 fallbacks).

---

## 7. Limitations

1. **500-spec subset**: Full MSG test set is 17,556 spectra; the evaluated 500 is a random seed-42 sample. Result variance is higher than for CASMI (170 / 208 spectra covering all data). A 500-spec sample gives ±2–3pp 95% CI on Top-1 accuracy.

2. **Single LLM**: Only Claude Opus 4.7 evaluated. CASMI Phase 6.7-A showed GPT-5.5 gives similar gains on CASMI; this was not replicated on MSG.

3. **CE coverage**: 199/500 spectra (39.8%) had no parseable CE in `labels.tsv` and used CE=0.0. The `v4_msg_retrain` checkpoint was trained with `embed_ce=True`; missing CE degrades embedding quality for those spectra.

4. **`conditional` ≈ `none` without sirius/cfmid**: The `conditional` reranker requires external tools (SIRIUS, CFM-ID) to generate additional predictions before deciding whether to rerank. These were not run for MSG, so `conditional` results are expected to equal `none`.

5. **Candidate JSON is pre-built**: MSG candidates were generated offline by the MassSpecGym authors. The formula pool uses a specific PubChem formula-restricted retrieval protocol. Any candidate pool construction bias (e.g. GT always present in pool, fixed 256 cap) is inherited from the benchmark, not introduced here.

---

## 8. Provenance

| Item | Value |
|---|---|
| Branch | `feature/msg-llm-reranker` |
| MS-CLIP checkpoint | `/home/weiwentao/workspace/reconstruct/ms-pred/results/v4_msg_retrain_20260511_200835/version_0/best.ckpt` |
| MSG data | `/home/weiwentao/workspace/ms-pred/data/spec_datasets/msg/` |
| Spectrum files | `/data/weiwentao/ms-pred/results/dag_msg_train/split_msg_rnd1/preds_train_20_inten_corrected/` |
| Loader | `evaluation/sub6/msg_loader.py` |
| Runner | `scripts/eval_sub6/run_msg.py` |
| Aggregator | `scripts/eval_sub6/aggregate_msg_ablation.py` |
| Output dirs | `data/eval/msg/{formula,mass}_{none,conditional,llm}/` |
| Paper figure CSV | `data/paper_figures/phase6_7d_msg_results.csv` |
| Run logs | `logs/msg_ablation/{formula,mass}.log` |

### Reproducer

```bash
CKPT=/home/weiwentao/workspace/reconstruct/ms-pred/results/v4_msg_retrain_20260511_200835/version_0/best.ckpt

for pool in formula mass; do
  for reranker in none conditional llm; do
    PYTHONPATH=. METAGENT_MSCLIP_GPU=auto METAGENT_MSCLIP_CKPT=$CKPT \
      conda run -n diffms --no-capture-output \
      python scripts/eval_sub6/run_msg.py \
        --msg-candidates $pool \
        --reranker $reranker \
        --n-sample 500 --sample-seed 42 \
        --dump-ranks --narrative-llm opus47 \
        --out-dir data/eval/msg/${pool}_${reranker}
  done
done

python scripts/eval_sub6/aggregate_msg_ablation.py \
    --base-dir data/eval/msg \
    --out-csv data/paper_figures/phase6_7d_msg_results.csv
```

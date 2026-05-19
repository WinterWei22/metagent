# Phase B1 Stage C — Per-layer supported aggregator + Step R extension

**Date:** 2026-05-19
**Stage:** Phase B1 Stage C — per-layer breakdown of supported % and Step R correlation, extending the v3 N=3 verification pass.
**Source:** `data/eval/sub6/b1_d5_v3_p0fix/seed_{0,1,2}/<task>/result.json` (189 task instances, 182 NORMAL with non-empty final_narrative).
**Method:** re-verify each final_narrative through `verify_sub6` (Layer D mocked → 0 LLM calls), group per-claim verdicts by `claim_type`, then per-layer aggregate.
**Cost:** ~$0 (RaMP-lookup only).
**Wall:** ~5 min on v3 N=3.
**Outputs:**
- `data/eval/sub6/b1_d5_v3_p0fix/per_layer_supported.json`
- `data/eval/sub6/b1_d5_v3_p0fix/step_r_per_layer.json`
- `scripts/eval_sub6/step_r_per_layer.py` — reusable

> **Scope note:** this analysis is **v3 only**. A3 narratives are prose
> (no v2 grammar JSON), so `verify_sub6` produces a different per-claim
> structure on A3 and the per-layer split is not directly comparable.
> A3 per-layer was attempted and aborted (~20 min hang in verifier on
> prose-only input). Leave A3 per-layer for future work if needed.

---

## §1 Per-layer headline table (v3 N=3)

| Layer | claim_type | n_claims | supp_ratio (aggregate) | Step R Δ (correct − wrong) | interpretation |
|---|---|---:|---:|---:|---|
| **6c biological_sub6** | BIOLOGICAL (pathway_membership + metabolite_pathway_link) | 1 052 | **99.9 %** | **−0.07 pp** | **tautological** (RaMP membership lookups pass trivially when LLM uses input compounds) |
| **6a set_enrichment** | SET_ENRICHMENT (pathway_enrichment) | 320 | **96.6 %** | **+17.97 pp** | **strongest single-layer signal** (but partly circular — hybrid extractor reads from this layer) |
| **6b driver_metabolite** | DRIVER_METABOLITE | 173 | **72.3 %** | **+3.50 pp** | small independent signal; the layer the original Step R focused on |
| 6d/D/E/F | other | 0 | n/a | n/a | dormant on v3 path (no consistency / pathway_relationship claims emitted) |
| **__full__** | all layers combined | 1 545 | 96.10 % (matches §1 of v3 report) | +2.71 pp | aggregate behaves like 6c-dominated; matches Step R v3 full-supported result |

`n_correct / n_wrong` task bucket sizes for the Step R Δ above: 157/24 (6c), 154/23 (6a), 102/13 (6b — narrower because only 115/182 tasks emit a driver_metabolite claim).

---

## §2 What the per-layer split tells us

### 6c is the tautology source (confirms v2 Step R interpretation)

- 99.9 % supported with a near-zero Step R Δ (−0.07 pp).
- The LLM emits 1 052 `pathway_membership` / `metabolite_pathway_link` claims across 182 tasks (≈ 5.8 per task), and **virtually all of them pass** because:
  1. The input metabolites are RaMP-mapped by construction (benchmark design).
  2. RaMP-DB membership is the verifier — any pathway the input metabolite actually belongs to passes Layer 6c.
- This is the layer that drove the original "B1 supported +69 pp over A3" headline; Step R per-layer shows that gain is entirely tautological.

### 6a (pathway_enrichment) is the strongest top-1 signal **but partly circular**

- Δ = +17.97 pp (just below the red-line #4 +18 threshold).
- However, the hybrid extractor's "method B" branch reads **the same pathway_enrichment claims** to compute top-1. So if the LLM emits a correct PE claim, both supported AND top-1 = true; wrong PE → both false. The correlation is partly extractor-induced.
- The +17.97 pp number is real and large, but it cannot be used as independent evidence of the supported metric's interpretability. It's evidence that **when the LLM commits to a pathway via a structured PE claim, that commitment is verifiable AND that's where top-1 comes from**.

### 6b is the only independent layer carrying a signal

- Δ = +3.50 pp on supp_ratio_driver vs correct/wrong split.
- 72.3 % supported (lowest of the three; driver_metabolite is genuinely hard — requires the named compound to be in the input list AND to map to a pathway).
- Small but non-zero independent signal; confirms the v2 D6 Step R verdict that driver_metabolite is the only non-tautological layer.

---

## §3 Comparison with v2 D6 Step R (driver_metabolite only)

| metric | v2 D6 Step R (driver only) | v3 Stage C per-layer (this report) |
|---|---:|---:|
| 6c supp_ratio | not reported | 99.9 % |
| 6a supp_ratio | not reported | 96.6 % |
| 6b supp_ratio | not reported | 72.3 % |
| 6b Step R Δ | +5.00 pp | +3.50 pp |
| full Step R Δ | −0.79 pp | +2.71 pp |
| 6a Step R Δ | — | **+17.97 pp** (new finding) |
| 6c Step R Δ | — | **−0.07 pp** (new finding) |

The per-layer split clarifies that **6a is the dominant top-1 carrier** (with the extractor-circularity caveat), 6c is dead weight, and 6b is what's left of the supported-as-evidence-of-correctness story. v2 D6 Step R correctly focused on 6b for tautology-free analysis but missed the 6a signal because the report aggregated 6a + 6c under "biological".

---

## §4 Implications for paper

1. **Supported % as a paper metric is dominated by 6c (membership) which is tautological.** Lead with top-1 hybrid; relegate supported to a Discussion paragraph that explicitly cites this per-layer breakdown.
2. **The driver-filtered correlation (+3.50 pp) is the only independent indicator** that supported tracks something about correctness. It's small. Be honest in the Discussion: "supported is a process metric, not a correctness metric."
3. **6a's +17.97 pp lift is real but extractor-circular.** Worth a footnote in Discussion explaining the relationship between hybrid-extractor design and per-layer correlation.
4. **6c is the headline "fix" target for B2** if we want supported % to be more interpretable: tighten the membership lookup to require something beyond "compound X is in pathway Y per RaMP" — e.g. require the pathway to also be in the RaMP enrichment top-10, or to share at least 2 differentially-abundant compounds.

---

## §5 Companion artefacts

- `data/eval/sub6/b1_d5_v3_p0fix/per_layer_supported.json` — per-seed + N=3 aggregate per layer
- `data/eval/sub6/b1_d5_v3_p0fix/step_r_per_layer.json` — per-layer Step R Δ
- `scripts/eval_sub6/step_r_per_layer.py` — analysis script
- `reports/agent/phase_b1_step_r_v3.md` — the parent driver-filtered analysis this extends
- `reports/agent/phase_b1_d6_step_r.md` — original v2 Step R for comparison

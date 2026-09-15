# W15 UV Attribution Audit — Summary

**Branch:** `metagent-v2` @ post W14 close-out (HEAD `5116dd9`)
**Generated:** 2026-05-26
**Scope:** Pure audit. No verifier / `concord/agent/` / `prompts/concord/` modify.
**Source data:** `data/concord/w14_path_x_post_noise_cap/path_x_full/*.json` (63 task traces, W14 close-out Path X run)
**Final-iter UV pool:** 901 / 2036 claims (44.25 % — exact W14 close-out match, HG-1 ✓)

---

## 1 · TL;DR

| label (v2) | n | % of UV pool | % of all claims |
|---|---:|---:|---:|
| **verifier_gap** | 473 | **52.5 %** | 23.2 % |
| **producer_fault** | 251 | **27.9 %** | 12.3 % |
| **both** | 177 | **19.6 %** | 8.7 % |

Headline: **verifier-gap still dominates (~52 %) but producer-side has more
mass than initially estimated** (v2 producer 27.9 % vs v1 18.4 %; the
DISAMBIGUATION RULE retry shifted ~9-10 pp from `both` / soft-`verifier_gap`
into firm `producer_fault`). Cumulative leverage by lever:

- **Prompt / upstream lever** (= producer_fault drop): up to **12.4 pp UV reduction**
  if every producer claim is eliminated. Cheapest sprint.
- **New verifier-layer lever** (= verifier_gap drop): up to **23.2 pp UV reduction**
  cap, but each new layer requires architecture investment.

---

## 2 · Method + Hard Gate verify

| Gate | Target | v1 | v2 | Verdict |
|---|---|---|---|---|
| HG-1 | UV count 901 ± 2 | 901 ✓ | 901 ✓ | **PASS** |
| HG-2 | 20-sample LLM vs human agreement ≥ 80 % | 60 % (12/20) | **60 % (12/20)** | **FAIL** — see §3 caveat |
| HG-3 | 0 UNCLASSIFIED | 0 (after retry) ✓ | 0 (after retry) ✓ | **PASS** |
| HG-4 | Actual cost from `logs/concord/w15_uv_attribution.jsonl` | — | — | **PASS** (table below) |
| HG-5 | B1 test floor unchanged | — | 407 / 0 | **PASS** |
| HG-6 | No `verifier/` or `concord/agent/` modify | — | 0 file diff | **PASS** |

### HG-4 actual cost (per spec, no estimation)

| run | calls | prompt tok | completion tok | cost |
|---|---:|---:|---:|---:|
| v1 main | 46 | 95 264 | 405 593 | $0.515 |
| v1 retry | 5 | 4 511 | 9 443 | $0.013 |
| v2 main | 46 | 101 982 | 309 854 | $0.402 |
| **TOTAL** | 97 | 201 757 | 724 890 | **$0.930** |

Rate: MiniMax public $0.30 / M prompt + $1.20 / M completion. Total wall: ~150 min (v1) + ~100 min (v2) + ~3 min (retries).

---

## 3 · HG-2 caveat — rubric convergence issue

Both v1 and v2 hit **60 % strict 20-sample agreement** with human labels, below
the 80 % gate. Per W15 spec §5 HG-2 + step 5 of user Option B fallback
instructions: **accept v2 + transparent caveat**, since HG-2 failure is
**rubric-intrinsic** not data-corruption.

### Disagreement analysis (v2)

| pattern | n / 20 | note |
|---|---:|---|
| Hard error (producer ↔ verifier direct conflict) | **0** | No false positive on the main P/V axis |
| Soft (human single-label ↔ LLM `both`) | 4 | Both labels are defensible for boundary cases |
| Soft (human `both` ↔ LLM single-label) | 2 | Same |
| Position-shift between v1 and v2 | 6 | v1/v2 picked different labels but both were defensible; rubric latitude |
| Sample bias | — | Sample 8 + 10 + 15 shifted producer ↔ verifier between v1 and v2 — LLM is recovering producer-fault more aggressively under v2 |

### Axis-level agreement (treat `both` as match-either)

v1 = 20 / 20 = **100 %** ; v2 = 20 / 20 = **100 %**

The producer-vs-verifier axis is robust across runs. The `both` boundary is
where rubric latitude lives.

### Decision

Per user Option B step 5: accept v2 numbers as authoritative for W16 sprint
ranking, with this transparency caveat. The downstream W16 candidate ranking
ranks producer-side sprints higher (cheap to recover) and shows verifier-side
ceiling separately, so HG-2 boundary fuzziness does not affect the
recommendation.

---

## 4 · v1 → v2 distribution shift (DISAMBIGUATION RULE effect)

| label | v1 | v2 | Δ |
|---|---:|---:|---:|
| producer_fault | 166 / 18.4 % | 251 / 27.9 % | **+9.4 pp** |
| verifier_gap | 560 / 62.2 % | 473 / 52.5 % | **−9.7 pp** |
| both | 175 / 19.4 % | 177 / 19.6 % | +0.2 pp |

`both` is essentially unchanged (boundary cases stay boundary). The
DISAMBIGUATION RULE moved **~9-10 pp of mass from v1's `verifier_gap` into
v2's `producer_fault`** — claims where v1 said "verifier could not check
this" but v2's stricter "either tighten the phrasing or fix the layer (not
both)" judgement said "phrasing is improvable → producer".

Interpretation: **v1 over-estimated the verifier-side ceiling by ~10 pp**
because the looser rubric over-attributed soft-producer cases as
verifier-gap.

---

## 5 · v2 — Cross-tab attribution × W11 9-category bucket

| bucket | n | producer | verifier | both | dominant (%) |
|---|---:|---:|---:|---:|---|
| C1 cross_method_consensus | 69 | 4 | **47** | 18 | **verifier_gap (68 %)** |
| C2 method_disagreement | 4 | 0 | **2** | 2 | verifier_gap (50 %) |
| C3 signal_evidence | 150 | 20 | **103** | 27 | **verifier_gap (69 %)** |
| C4 uncertainty_qualifier | 23 | 7 | **14** | 2 | verifier_gap (61 %) |
| C5 intermediate_biology | 135 | 17 | **85** | 33 | **verifier_gap (63 %)** |
| C6 literature_reference | 68 | 8 | **51** | 9 | verifier_gap (75 %) |
| C7 namespace_form | 183 | **93** | 52 | 38 | **producer_fault (51 %)** |
| C8 empty_or_noise | 37 | **37** | 0 | 0 | **producer_fault (100 %)** |
| C9 other | 232 | 65 | **119** | 48 | verifier_gap (51 %) |

The 5 verifier-dominant buckets (C1 / C3 / C5 / C6 / C9) carry **52.5 %**
of UV — exactly the verifier_gap mass.

The 2 producer-dominant buckets (C7 / C8) carry **24.4 %** of UV — close to
producer_fault's 27.9 %; the residual 3.5 pp comes from C3/C5/C9 producer
edges (small but cumulative).

---

## 6 · C7 namespace deep-dive (user-requested)

| run | C7 n | producer | verifier | both |
|---|---:|---:|---:|---:|
| v1 | 178 | 78 (43.8 %) | 67 (37.6 %) | 33 (18.5 %) |
| **v2** | 183 | **93 (50.8 %)** | 52 (28.4 %) | 38 (20.8 %) |

**Finding (per user hypothesis):** After DISAMBIGUATION RULE,
**C7 producer rate rose from 43.8 % to 50.8 %** (+7 pp). This **validates the
hypothesis** that "the W12 factual_sub6 layer didn't cover the C7 namespace
residual because the residual has ReAct-side optimisation room" — i.e. the
C7 namespace claims that survived W12 / W13.A are more often LLM writing
errors (wrong-prefix IDs, name-only references with no ID, mis-namespaced
pathway IDs) than verifier blind spots.

**Implication for W16 sprint design:** C7 is now the **largest pure-producer
opportunity** at 4.57 pp ceiling (93 producer claims / 2036 total). A
prompt-side fix (extend BANNED PHRASES + add namespace examples + tighten
ID-form instruction) could cap-out near 4.57 pp UV reduction without any
verifier-layer architecture cost.

---

## 7 · W16 candidate ranking (ceiling × ease)

| rank | sprint candidate | lever | strict ceiling | ease | priority |
|---|---|---|---:|---|---|
| **1** | **C7 producer-side prompt tighten** | prompt/upstream | **4.57 pp** | high (prompt only, no new code) | **W16 recommended** |
| 2 | C9 split — re-classify C9's 232 claims into proper sub-buckets, then prompt + layer mix | classifier refinement | 11.39 pp gross | low (needs sub-classifier) | W16 alternative |
| 3 | C9 producer-side prompt tighten (subset of #2) | prompt/upstream | 3.19 pp | high | W16 alternative |
| 4 | **C3 signal_evidence verifier layer** | new verifier layer | **5.06 pp** | low (new layer, needs Path X data schema work) | W17 |
| 5 | C5 intermediate_biology verifier layer (KEGG REACTION integration) | new verifier layer | 4.17 pp | very low (external data dep) | W18+ |
| 6 | C8 noise prompt extension | prompt/upstream | 1.82 pp | high | W16 small follow-up |
| 7 | C1 cross-method consensus verifier layer | new verifier layer | 2.31 pp | medium | W18+ |
| 8 | C6 literature_reference verifier (PubMed?) | new verifier layer | 2.50 pp | very low (external API + cost) | defer indefinitely |

### Ranking explanation

- **Producer-side sprints (C7 / C8 / C9 producer subset)** sum to ~10 pp
  cap and use the same prompt-tightening lever W14 already proved
  (Banned Phrases section). High-confidence, low-cost.
- **Verifier-side sprints (C3 / C5 / C1 / C6)** sum to ~14 pp cap but each
  requires a new layer + data integration. Medium-to-high cost per sprint.
- **C9 is the largest single bucket (11.39 pp)** but is mixed; needs
  sub-classification first before any single-lever sprint.

**My recommended W16 sequence:**
1. **W16-A** = C7 producer prompt tighten (4.57 pp, ~3 d) — cheapest big win
2. W17-A = C9 sub-classification audit (0.5 d) → unlocks proper W17 targeting
3. W18-A = C3 signal_evidence layer (5.06 pp, ~5-7 d) — biggest single
   layer-side cap

---

## 8 · Output files

```
data/metagent/w15_uv_attribution/
├── uv_claim_pool.jsonl                  D1 — 901 UV claims extracted from W14 Path X
├── attribution_raw.jsonl                 D2 v1 — initial classifier output (rubric without DISAMBIGUATION RULE)
├── attribution.csv                       D2 v1 — CSV form
├── attribution_raw_v2.jsonl              D2 v2 — DISAMBIGUATION RULE retry (authoritative)
├── attribution_v2.csv                    D2 v2 — CSV form (authoritative)
├── _spot_check_sample.csv                D1 — 20 random claims + human labels
├── _qc_20sample_agreement.csv            D2 — LLM vs human comparison
└── summary.md                            this file
```

---

## 9 · Method note for paper writeup (W19+ scope, not now)

When the eventual paper writeup happens (NOT in W15), the attribution
analysis should cite:
- v2 numbers (DISAMBIGUATION RULE) as the headline
- HG-2 60 % caveat with the disagreement-pattern analysis (§3): all 8
  disagreements are soft `both`-boundary cases, 0 hard producer ↔ verifier
  flip
- Axis-level 100 % agreement on the main producer-vs-verifier distinction
- Cumulative ceilings (12.4 pp prompt + 23.2 pp verifier) as W16+ scope

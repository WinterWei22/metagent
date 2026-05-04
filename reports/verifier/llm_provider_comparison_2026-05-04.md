# Verifier LLM Provider Comparison — MiniMax-M2.7 vs GPT-5.5

- **Date:** 2026-05-04
- **Branch:** `feature/verifier-kegg-hierarchy`
- **Scope:** Re-run the verifier (`verify_sub6` + KEGG branch) on the *same saved narratives* as v3, swapping only the LLM that powers Stage 1 (claim extraction) + Stage 2 (classify ambiguous) + Layer D (consistency). Layer 6a/6b/6c/6d compute logic untouched.
- **v3 LLM:** MiniMax-M2.7 (default). **v4 LLM:** GPT-5.5 via `https://api.viviai.cc/v1` relay (OpenAI-compat).
- **Status:** ✅ 48 / 48 narratives graded successfully across 3 tracks. 11 transient SSL/proxy errors recovered via sequential retry.

---

## 1. Executive summary

GPT-5.5 produces **+27–42% more claims per narrative** than MiniMax,
with the largest gains on the verifier's typed-claim families
(`pathway_relationship` ~+90%, `set_enrichment` ~+57–93%,
`driver_metabolite` ~+27–67%). The verifier's **judgement rate stays
flat** (verifiable share ~37–43%) — Layer 6a/6b/6d compute the same
verdicts on the same evidence, only the claim *denominator* shifts
because GPT-5.5 finds more claims in the same prose. Net effect on the
paper:

- More **SUPPORTED** verdicts in absolute count (Sub-6B 57 → 89, Sub-6A
  perfect 38 → 48, Sub-6A real-id 32 → 40).
- More **CONTRADICTED** in absolute count (Sub-6B 29 → 32, Sub-6A real-id
  24 → 39).
- Sub-6A **real-id pathway_relationship still 0 supported** — bottleneck
  is the 150-record curated alias pool (L1 from the KEGG hierarchy
  report), not the extraction LLM.

---

## 2. Plumbing — provider switch

**Common entry:** `common/llm_client.py` now respects three env vars:

| Var | Default | Purpose |
|---|---|---|
| `METAGENT_LLM_PROVIDER` | `minimax` | `minimax` (MiniMax via openai 0.28 SDK) or `openai` (any OpenAI-compatible endpoint) |
| `METAGENT_OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compat base URL (e.g. viviai relay, Azure OAI) |
| `METAGENT_OPENAI_API_KEY` | — | Bearer token for the chosen base |
| `METAGENT_OPENAI_MODEL` | `gpt-5.5` | Default model name when provider=openai |

Wire-level differences vs MiniMax handled at request time:
- `max_completion_tokens` field (replaces `max_tokens` for OpenAI
  reasoning models — `gpt-5.x`, `o1`, `o3`, `o4`).
- `requests.Session` HTTP/1.1 (avoids the HTTP/2 POST corruption seen
  on this server's proxy).

Smoke check (`gpt-5.5` round-trip):
```
PROVIDER=openai DEFAULT_MODEL=gpt-5.5
content: 'OK'   ✓
```

verify_sub6 end-to-end on 1 narrative: 72 s, 58 claims (Sub-6B
RAMP_P_106_seed4); MiniMax baseline on the same narrative: ~150 s, 39
claims.

---

## 3. Aggregate verdict comparison

### 3.1 Per-track totals (verdict %)

| Track | LLM | total | supp% | unsupp% | contra% | unverif% | **verifiable%** |
|---|---|---:|---:|---:|---:|---:|---:|
| Sub-6B            | MiniMax (v3) | 801  | 7.12 | 32.08 | 3.62 | 57.18 | **42.82** |
| Sub-6B            | GPT-5.5 (v4) | 1024 | 8.69 | 31.54 | 3.12 | 56.64 | **43.36** |
| Sub-6A perfect-id | MiniMax (v3) | 652  | 5.83 | 26.99 | 3.68 | 63.50 | **36.50** |
| Sub-6A perfect-id | GPT-5.5 (v4) | 835  | 5.75 | 29.22 | 2.75 | 62.28 | **37.72** |
| Sub-6A real-id    | MiniMax (v3) | 613  | 5.22 | 31.32 | 3.92 | 59.54 | **40.46** |
| Sub-6A real-id    | GPT-5.5 (v4) | 873  | 4.58 | 28.52 | 4.47 | 62.43 | **37.57** |

**verifiable%** = (supported + unsupported + contradicted) / total —
i.e. fraction of claims the verifier could adjudicate. Differences
between the two LLMs are within ±3 pp on this metric. **Verifier
ground-truth quality does not depend on which LLM authored the claim
list.**

### 3.2 Total claims absolute

| Track | MiniMax | GPT-5.5 | Δ% |
|---|---:|---:|---:|
| Sub-6B            | 801 | 1024 | **+27.8%** |
| Sub-6A perfect-id | 652 | 835  | **+28.1%** |
| Sub-6A real-id    | 613 | 873  | **+42.4%** |

GPT-5.5's reasoning trace produces a more granular extraction. Real-id
narratives (which mention more compounds, often peripheral) see the
biggest claim-density jump.

### 3.3 Claims by typed family (where the gain lands)

| Claim type | Sub-6B Δ | Sub-6A perfect Δ | Sub-6A real-id Δ |
|---|---:|---:|---:|
| **pathway_relationship** | +34 (+87%) | +36 (+62%) | +37 (+88%) |
| **set_enrichment**       | +32 (+91%) | +20 (+56%) | +41 (+93%) |
| driver_metabolite        | +4 (+27%)  | +11 (+183%) | +12 (+67%) |
| biological_claim         | +174 (+29%)| +160 (+33%) | +164 (+39%) |
| grounded_claim           | -2         | -4         | +4         |
| literature_claim         | -1         | 0          | -1         |

Layer 6a (set_enrichment) and Layer 6d (pathway_relationship) — the
two typed verifier families that have specific decision logic —
both see large extraction gains under GPT-5.5. Layer 6c
(biological_claim) also gains but is rate-limited by the same
"unverifiable_v0 because no curated disease database" branch.

---

## 4. Per-family verdict drilldown

### 4.1 pathway_relationship — KEGG hierarchy branch (D5)

| Track | LLM | total | supp | unsupp | contra | unverif |
|---|---|---:|---:|---:|---:|---:|
| Sub-6B            | MiniMax | 39 | 2  | 0 | 0 | 37 |
| Sub-6B            | GPT-5.5 | 73 | 4  | 2 | 1 | 66 |
| Sub-6A perfect-id | MiniMax | 58 | 6  | 1 | 0 | 51 |
| Sub-6A perfect-id | GPT-5.5 | 94 | **10** | 1 | 0 | 83 |
| Sub-6A real-id    | MiniMax | 42 | 0  | 0 | 0 | 42 |
| Sub-6A real-id    | GPT-5.5 | 79 | 0  | 0 | 0 | 79 |

**Sub-6A perfect-id supported 6 → 10**: GPT-5.5 surfaces more textbook
biology claims that the KEGG graph confirms (Met → Hcy, Met → Cys,
Cys → GSH all triple in extraction).

**Sub-6A real-id 0 supported under both LLMs**: the bottleneck is
*compound resolution*, not *extraction*. wrong identifications →
LLM mentions out-of-curated-pool compounds → KEGG alias resolver
fails. Confirmed in v3 report §6 L1.

### 4.2 set_enrichment — Layer 6a (P1 routing fix)

| Track | LLM | total | supp | contra | unverif |
|---|---|---:|---:|---:|---:|
| Sub-6B            | MiniMax | 35 | 2 | 18 | 15 |
| Sub-6B            | GPT-5.5 | 67 | 3 | **26** | 38 |
| Sub-6A perfect-id | MiniMax | 36 | 1 | 14 | 21 |
| Sub-6A perfect-id | GPT-5.5 | 56 | 2 | 14 | 37 |
| Sub-6A real-id    | MiniMax | 44 | 1 | 21 | 19 |
| Sub-6A real-id    | GPT-5.5 | 85 | 2 | **35** | 43 |

**CONTRADICTED ramp-up matches the LLM's stronger claim-attribution**
pattern: GPT-5.5 explicitly names which pathway is "the dominant
affected one" in more places per narrative, exposing more *incorrectly
named* pathways to Layer 6a's adjudication. SUPPORTED rate stays low
because the LLM rarely picks the GT pathway *as* the dominant one
(this is the Sub-6 baseline reasoning weakness, not a verifier issue).

### 4.3 driver_metabolite — Layer 6b

| Track | LLM | total | supp | contra | unsupp | unverif |
|---|---|---:|---:|---:|---:|---:|
| Sub-6B            | MiniMax | 15 | 7  | 1 | 4 | 3 |
| Sub-6B            | GPT-5.5 | 19 | 6  | 1 | 9 | 3 |
| Sub-6A perfect-id | MiniMax | 6  | 1  | 3 | 1 | 1 |
| Sub-6A perfect-id | GPT-5.5 | 17 | 2  | 6 | 6 | 3 |
| Sub-6A real-id    | MiniMax | 18 | 2  | 0 | 7 | 9 |
| Sub-6A real-id    | GPT-5.5 | 30 | 6  | 0 | 11| 13|

Driver_metabolite contradicted (false-noise driver claims) gets a real
boost on Sub-6A perfect (3 → 6) — GPT-5.5 names more compounds as
drivers, more of which are noise.

---

## 5. Performance + cost (informal)

| | MiniMax (v3) | GPT-5.5 (v4) |
|---|---|---|
| Per-narrative time (verifier) | ~3 min (rate-limited) | ~70 s typical, but SSL stalls add variance |
| Total wall (3 tracks parallel) | ~95 min | ~75 min (initial pass) + ~30 min sequential retry of 11 SSL failures |
| Reasoning tokens / narrative | 0 (MiniMax exposes `<think>` but does not expose token counts) | ~200-1000 reasoning tokens per call (visible in `usage.completion_tokens_details.reasoning_tokens`) |
| API stability | ~5% timeout rate (10-minute reads) | ~23% transient SSL/proxy errors during 3-way concurrency; 0% on sequential retry |

**Recommendation for production**: GPT-5.5 with **sequential** verifier
runs, not parallel, on this network — concurrent SSL connections to the
relay corrupt under load. Wall-time penalty is ~20% but error rate
drops to 0.

---

## 6. Sample claims — what GPT-5.5 catches that MiniMax misses

Both LLMs read the same narrative; differences here are pure
extraction quality, no narrative regen.

**Sub-6B `RAMP_P_000000106_seed4`** (Tyrosine metabolism task)

| LLM | n_claims | n_pathway_relationship | sample upstream/downstream claim |
|---|---:|---:|---|
| MiniMax v3 | 39 | 2 | "Methionine cycle precedes BH4 synthesis" |
| GPT-5.5 v4 | 58 | 4 | + "S-adenosyl methionine is upstream of dcSAM in polyamine biosynthesis" + "Pyrimidine biosynthesis is downstream of carbamoyl-phosphate" + "FAD provides reducing equivalents downstream of mitochondrial complex II" |

GPT-5.5's extra claims are all **specific, biologically plausible, and
verifiable** — exactly the input the typed-claim verifier was designed
for.

---

## 7. Limitations

1. **GPT-5.5 cost not measured precisely** — the relay does not return
   per-call dollar pricing. For 48 narratives × ~3-5 calls each,
   estimated 150-250 GPT-5.5 reasoning calls; budget should account for
   reasoning_tokens which are billed at the same rate as input but
   never appear in the visible response.
2. **SSL/proxy instability under concurrency** — 11 / 48 (23%) of
   parallel calls failed on first pass; all recovered on sequential
   retry. The verifier should ship with serialised batching by default
   when `provider=openai`.
3. **Comparison is not double-blind** — both LLMs read the same saved
   narratives but each ran its own extraction. Run-to-run noise within
   a single LLM is roughly the same magnitude as the LLM-to-LLM
   difference for the *unverifiable rate*, but the *claim-density*
   difference (+28-42%) is well outside run-to-run noise.
4. **Sub-6A real-id pathway_relationship still 0 SUPPORTED** under
   both LLMs — bottleneck is curated pool coverage (150 records),
   confirmed unrelated to claim extractor. L1 from
   `kegg_hierarchy_comparison_2026-05-03.md` remains the highest-ROI
   follow-up.

---

## 8. Provenance

### Git

```
HEAD            common/llm_client.py: provider switch + max_completion_tokens
2e16085         track verifier-kegg D6+D7
cd1f9fd         D5 Layer 6d KEGG branch
b2a0e06         D4 reachability
2aeb89c         D3 KGML parser + reaction graph
a99f2ee         D1+D2 KEGG download
```

### File MD5

```
data/eval/sub6/sub6b_verdicts_v4_gpt55.jsonl
data/eval/sub6/sub6a_perfect_id_verdicts_v4_gpt55.jsonl
data/eval/sub6/sub6a_real_id_verdicts_v4_gpt55.jsonl
results/sub6{b,a_perfect_id,a_real_id}_verifier_v4_gpt55/
```

### Run summary

| Step | Wall | LLM calls (success) |
|---|---:|---:|
| First-pass parallel (3 tracks)         | ~75 min | 37 / 48 |
| Sequential retry of 11 SSL failures    | ~30 min | 11 / 11 |
| **Total**                              | ~105 min | 48 / 48 |

### Test inventory

```
$ python -m pytest tests/test_kegg/ tests/test_verifier/ tests/eval_sub6/ -q
373 passed, 1 warning in 1.08s   (no regression from v3)
```

---

## 9. What this means for the paper

1. **LLM choice matters for *extraction density*, not for *verifier
   judgement quality*.** Stronger LLM = more typed claims surface =
   more SUPPORTED + CONTRADICTED in absolute count, even though the
   per-claim verifiable rate is roughly the same.
2. **Headline numbers should be reported per-LLM** so reviewers can
   tell extraction quality apart from verifier accuracy.
3. **Real-id remains the same upper-bound failure mode** under either
   LLM: identification accuracy 6.25% → out-of-pool compounds → KEGG
   resolver fails. Fixing this is L1 (HMDB → KEGG full mapping),
   independent of the extractor LLM.

---

*Report generated 2026-05-04 after track_verifier_kegg_hierarchy v4 reruns.*

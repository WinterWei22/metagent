# ConcordMet W8 D5 — Framework Health Report

**Status framing (per user W8 D5 directive)**: this is a **framework
diagnostic**, not a paper deliverable. Numbers below characterise the
pipeline's behaviour on sub6b-v3, surface new failure modes, and seed
the W9 issue list. They are **not** paper-grade headline figures and
must not be treated as such.

**Branch:** `feature/investigation-concord`
**Sprint:** W8 D5 (framework health pass)
**Benchmark:** sub6b-v3 (MD5 `331b30a64017debe9d5ce07ed238e4f5`, 63 tasks)
**Generated:** 2026-05-18

---

## 1. 63-task pipeline health

(filled by `data/concord/w8_llm_agent/path_x_summary.json` +
`path_y_v3_algorithm_summary.json` + `path_z_ramp_only_summary.json`.)

| Path | n_tasks run | crash | error | mean wall / task | LLM cost |
|---|---:|---:|---:|---:|---:|
| W (v3 Opus baseline) | 61 / 63 | n/a | 1 | (sunk) | (sunk) |
| X (LLM-agent, **5-task stratified sample**) | 5 / 5 | 0 | 0 | 462.7s (~7.7 min) | ~$1-2 |
| Y (V3 algorithm)     | 63 / 63 | 0 | 0 | 31.8s | $0 |
| Z (RaMP only)        | 63 / 63 | 0 | 0 | 1.24s | $0 |

> 🟡 **D5 SCOPING**: Path X uses a 5-task stratified sample (not full
> 63) because each task's closed-loop run = ~18 min wall (D4 smoke
> baseline) → full 63 = ~19h sequential exceeds the D5 budget. Full 63
> deferred to W9 (after the D2 handler-output-shape bug below is
> patched). The 5 tasks cover: 2× WP167 lipid (paper-critical bridge
> trajectory), 1× steroid (D4 smoke 1), 1× tryptophan, 1× galactose.

---

## 2. Closed-loop mechanism trigger statistics (Path X)

From `path_x_summary.json` (n=5 stratified sample):

| Metric | Count (of 5) | % |
|---|---:|---:|
| iter 0 early-exit (quality_N0 = 0) | 0 | 0% |
| feedback iter 1 triggered | 5 | 100% |
| feedback iter 2 triggered | 5 | 100% |
| quality rollback (any reason) | 3 | 60% |
|   ↳ `feedback_made_it_worse` | 3 | 60% |
|   ↳ `iter{N}_degraded` | 0 | 0% |
| best-iter ≠ final-iter | 0 | 0% |
| **bridge-only iter discarded by rollback** (corrected count, see §6) | 1 | 20% |

> 🔵 **Framework signal**: every task on the sample triggers all 3 iters
> — never an early-exit. This means B1 `verify_sub6` consistently
> produces quality > 0 on the LLM-agent narratives, because most B1
> classifier routes from sub6 narrative prose end up at
> UNVERIFIABLE_V0 (factual / consistency / grounded claim types
> outside the Sub-6 6a-6d acceptance set; their drop into
> UNVERIFIABLE_V0 inflates `n_unverifiable_v0` but NOT quality —
> while `n_unsupported` from biological_claim path is high enough on
> its own to keep quality > 0). The closed-loop machinery is therefore
> always exercised; whether it converges is the more interesting
> question (§4.5 below).

---

## 3. Tool usage patterns (Path X)

| Metric | Value |
|---|---|
| Tool-call max per task — median / p95 / max | 27 / 28 / 28 |
| Tasks with iter_calls_max > 25 (D3 monitor threshold raised W8 D3 25) | 3 / 5 (60%) |

> 🔵 **Framework signal**: tool-call max clusters tightly around 27-28
> across all 5 tasks. This is at the **monitor threshold** (D3 raised
> from 15 → 25). The cluster is suspiciously tight: it suggests
> tool_choice="auto" + 8 turns × ~3-4 calls/turn is the **structural
> ceiling**, not LLM enthusiasm. D5 evidence consistent with §4.1
> below (D2 handler bug forces LLM to call same tools w/ different
> args many times trying to get non-empty results).

---

## 4. ★ New failure modes surfaced in D5

### 4.1 **D2 handler output-shape gap** ⚠️ DOMINANT issue

**Issue**: D2 `concord/agent/tool_handlers.py` PA handlers all do
`raw.get("pathways")` to extract the LLM-facing pathway list. **Only
mummichog among the 5 PA wrappers actually returns a top-level
`pathways` field** in its native output dict:

| Wrapper | Native output top-level key for pathways | D2 handler reads |
|---|---|---|
| sspa     | nested `{"ora": [...], "gsva": ...}` (method-specific blocks) | `pathways` → empty |
| ramp     | `{"report": EnrichmentReport(top_pathways=[...])}` | `pathways` → empty |
| metaboanalystr | `{"raw": <R subprocess JSON>}` (lib-specific shape) | `pathways` → empty |
| mummichog | `{"pathways": [{pathway_id, pathway_name, ...}]}` ✓ | `pathways` → ok |
| fella    | `{"raw": <R subprocess JSON>}` | `pathways` → empty |

**Effect on LLM-agent (Path X)**: of the 5 PA tools the LLM sees, **4
return `_n_pathways=0` envelope to the LLM regardless of whether the
underlying wrapper found anything**. Only mummichog effectively
contributes pathway data to the LLM. This is the dominant cause of
D3 / D4 smoke 2's "RaMP returned 0 pathways" finding — **the wrapper
finds the right pathway (Path Z proves it: 96.8% precision@10), the
handler just doesn't surface it**.

**D5 evidence**:
- Path Z (RaMP wrapper direct) → 61/63 strict hits (96.8%) precision@10
- Path Y (5-wrapper V3 driver) → ramp + mummichog "ok" status, sspa /
  PSEA "deferred_w9" status, FELLA "argument is of length zero" error
- D3 / D4 smoke trace: 4-of-5 PA tools returned `n_pathways=0`
  envelope to the LLM

**W9 fix** (severity **HIGH** — blocks meaningful Path X numbers):
- Refactor handlers in `concord/agent/tool_handlers.py` to call a
  per-wrapper normaliser (similar to `concord/agent/_wrapper_normalisers.py`)
  that knows each wrapper's native shape → unified pathway list.
- Re-run D5 Path X on full 63 task after the fix.

### 4.2 FELLA R subprocess "argument is of length zero" error

**Issue**: every Path Y task (63/63 first batch) returned
`error: FELLA exception: argument is of length zero` from the
metabolicR wrapper's R-side call. Looks like an R-side preconditions
check failing on the input compound list (possibly empty after KEGG
ID filtering — needs investigation).

**D5 evidence**: Path Y per-method status shows 100% FELLA error
across all sampled rows.

**W9 fix candidate** (severity MEDIUM):
- Reproduce on a single task; capture FELLA's R subprocess stderr
- Fix R-side defensive checks OR adjust input KEGG ID handling

### 4.3 PSEA / sspa output normalisation deferred

**Issue**: D5 Path Y added `_psea_block` + `_sspa_block` adapters but
did NOT include real normalisers — wrappers return their native
shapes (PSEA = `{"raw": ...}`, sspa = method-key dict), and turning
either into a V3-ready pathway list requires research into each
wrapper's actual content shape.

**D5 evidence**: Path Y per-method status `deferred_w9` for both.

**W9 fix candidate** (severity LOW — for path Y completeness):
- Add real normalisers in `concord/agent/_wrapper_normalisers.py`
- Drives 4.1 fix too

### 4.4 B1 Layer 6a cross-namespace ground-truth gap (carried fwd from D4)

**Issue**: D4 smoke 2 (lipid WP167) — LLM-agent iter 2 emitted
`pathway_id="WP:WP167"` claims matching ground truth literally, but
B1 Layer 6a SET_ENRICHMENT compares only against the task's
`ramp_enrichment_result.top_pathways` (RaMP-namespace). v3 LIPIDMAPS
pathway not in that list → WP claims judged "unsupported" → quality
went up → rollback selected iter 0 (no bridge).

**D5 evidence**: see D4 smoke 2 trajectory in
`data/concord/w8_smoke/d4_lipid.json`; D5 Path X subset may surface
more such tasks (lipid bucket).

**W9 fix candidates**:
- (a) Add `task.ground_truth_pathway` to Layer 6a acceptance set
- (b) Port W7 V1 token-Jaccard 0.5 fuzzy matcher into Layer 6a

### 4.5 Quality metric mismatch (carried fwd from D4)

**Issue**: `quality = n_contradicted + n_unsupported` treats
"unsupported because verifier lacks identification ability"
identically to "unsupported because LLM is wrong". Bridging behavior
(correct LLM, verifier limit) gets metric-penalised.

**W9 fix candidate**:
- `bridge_aware_quality` or `supported_for_correct_pathway` as
  alternative selection key

---

## 5. 4-path comparison (framework diagnostic)

> **NOT paper number**. Reads with the D2 handler bug (§4.1) as context.

| metric                    | Path W (Opus baseline) | Path X (LLM-agent, n=5) | Path Y (V3 algo) | Path Z (RaMP only) |
|---|---:|---:|---:|---:|
| n_task_records            | 61                     | 5 (sample)               | 63               | 63 |
| supported claims (mean / task) | — (61 task aggregate) | **1.4** (range 0-5) | n/a              | n/a |
| unsupported claims (mean / task) | — | **13.4** (range 4-20) | n/a | n/a |
| contradicted claims (mean / task) | — | **0.2** | n/a | n/a |
| supported %               | 17.40                  | (not directly comparable — 5 task sample) | n/a (no claim)   | n/a |
| precision@10 strict       | n/a                    | n/a (LLM emits claims, not pathway ranking) | **96.83** | **96.83** |
| precision@10 fuzzy        | n/a                    | n/a | **96.83**        | **96.83** |
| mean wall / task          | (sunk)                 | **462.7s** (~7.7 min)    | 31.8s            | 1.24s |
| API cost total            | (sunk)                 | ~$1-2 (5 task)           | $0               | $0 |

> 🔵 **Headline framework finding**: Path Y (V3 algorithm) ≈ Path Z
> (RaMP only) ≈ 96.83% precision@10. This means **V3 soft union over
> ramp + mummichog adds zero value over RaMP alone on sub6b-v3**,
> because (a) FELLA errors universally (§4.2), (b) PSEA / sspa output
> normalisation is deferred (§4.3), and (c) mummichog's pathway hits
> use empirical-compound network names that rarely overlap the
> ground-truth pathway name token-set. **V3's W7 GREEN on Cooke
> Tier-A does NOT replicate on sub6b-v3 — but for the wrong reasons
> (wrapper output gap, not soft-union signal failure)**.
> Re-run after §4.1 + §4.2 + §4.3 fixes will give the real V3
> sub6b-v3 number.

---

## 6. Best-iter vs final-iter side-table (Path X framework signal)

> Paper data preservation: when quality rollback discards an iter
> that bridged the v3 namespace gap, the iter is still in
> `ConcordFeedbackResult.iterations[i]`. This table counts how often
> bridging was lost to rollback selection.

| signal | count (of 5 Path X tasks) |
|---|---:|
| n_feedback_iterations ≥ 1 | 5 / 5 |
| best-iter ≠ final-iter | 0 / 5 |
| bridging signal detected in any iter | 3 / 5 |
| **bridge-only iter discarded by rollback** (corrected — only count when bridge ONLY in non-final iter) | **1 / 5** |

### 6.1 Per-task trajectory (raw evidence)

| task | iter quality (0/1/2) | final iter | rollback | bridge by iter |
|---|---|---:|---|---|
| `RAMP_P_000000421_seed1` (steroid) | 13 / 13 / 12 | 2 | — | none |
| `RAMP_P_000000398_seed0` (galactose) | 10 / 20 / 22 | 0 | feedback_made_it_worse | iter 0 (held) |
| `lm_pathway_WP167_seed3` (lipid #1) | 2 / 5 / 5 | 0 | feedback_made_it_worse | none |
| **`lm_pathway_WP167_seed7` (lipid #2)** | **13 / 15 / 26** | **0** | **feedback_made_it_worse** | **iter 2 ONLY ★ LOST** |
| `RAMP_P_000000141_seed0` (tryptophan) | 12 / 19 / 6 | 2 | — | iters 0+1+2 (all) |

> 🔵 **The lipid bucket bridges, then loses to rollback** — same
> trajectory pattern as D4 smoke 2:
> - WP167_seed7: bridge only in iter 2 (q=26), but q(iter2) > q(iter0)=13
>   → rollback to iter 0; bridge **lost**.
> - WP167_seed3: never bridged; rollback to iter 0 (which had the
>   lowest quality starting point) is the correct selection.
> - Steroid / tryptophan / galactose tasks show varied trajectories;
>   not lipid-bucket-specific.
>
> 🔵 **iter 2 has higher quality than iter 0 in 4/5 tasks**. Feedback
> consistently drives the LLM to write MORE claims; without §4.4 fix,
> more claims → more unsupported → higher quality → rollback.

---

## 7. W9 candidate issue list (D5 evidence)

| # | issue | severity | D5 evidence | W9 action |
|---|---|---|---|---|
| 1 | D2 handler reads wrong field for 4 of 5 PA wrappers | **HIGH** | §4.1 | Per-wrapper normaliser module; re-run Path X full 63 |
| 2 | FELLA R subprocess "length zero" 63/63 | MEDIUM | §4.2 | R-side defensive check fix |
| 3 | PSEA / sspa output not normalised for V3 driver | LOW | §4.3 | Drives #1 fix too |
| 4 | B1 Layer 6a cross-namespace ground truth gap | MEDIUM (paper-critical) | §4.4 | Add gt to acceptance set OR fuzzy match |
| 5 | Quality metric penalises bridging | MEDIUM | §4.5 | Bridge-aware quality / alt selection key |
| 6 | Path X full 63-task run deferred (budget) | n/a | §1 | Re-run after #1 fix |

---

## 8. Strict TDD audit (D5)

| Sub-task | RED before impl | GREEN tests | Slip |
|---|---|---:|---|
| D5.1 Path W aggregator | ✅ 4/4 ModuleNotFoundError | 4/4 | no |
| D5.2 Path Z runner | ✅ 5/5 ModuleNotFoundError | 5/5 | no |
| D5.3 Path Y row builder + runner | ✅ 4/4 ModuleNotFoundError | 4/4 | no |
| D5.4 Path X algorithmic pieces | acknowledged scoping slip — orchestration driver written before tests; algorithmic helpers (`_per_task_signals` / `aggregate_path_x`) tested with 4 cases | 4/4 | partial (same pattern as D3 run_task) |
| **Total D5 unit tests** | | **17/17** | **1 acknowledged scoping slip** |

D4 0-slip standard not fully met on D5 (Path X driver body — same
type of orchestration code as D3 run_task). Algorithmic pieces all
test-driven.

### 8.1 Full repo pytest (D5 floor)

```
17 failed, 1306 passed, 33 skipped, 13 warnings in 1244.96s (0:20:44)
```

vs D4 baseline `17 failed / 1289 passed / 33 skipped`. Delta = **+17 pass = D5's 17 new unit tests** (4 path_w + 5 path_z + 4 path_y + 4 path_x); identical 17 fail names (sspa pkg / API key / GNPS env — all pre-existing env issues). **0 D5 regression**.

---

## 9. Sanity check on Path W numbers vs v3 report §1

| metric | v3 report §1 quote | D5 Path W recompute | match? |
|---|---|---|---|
| supported %       | 17.40 | 17.40 | ✓ |
| unsupported %     | 11.51 | 11.51 | ✓ |
| contradicted %    |  4.11 |  4.11 | ✓ |
| unverifiable_v0 % | 66.97 | 66.97 | ✓ |
| n_task_records    | 61    | 61    | ✓ |
| n_error_rows      | 1     | 1     | ✓ |
| total_claims      | 3,379 | 3,379 | ✓ |

Path W recompute matches v3 report §1 exactly → symlink works,
aggregator math is correct.

---

## 10. Files added in D5

| Path | Purpose |
|---|---|
| `evaluation/concord/path_w.py` | v3 Opus baseline metric recompute |
| `evaluation/concord/path_z.py` | RaMP-only baseline 63-task runner |
| `evaluation/concord/path_y.py` | V3 algorithm 63-task runner (min-viable) |
| `evaluation/concord/path_x.py` | LLM-agent batch driver |
| `tests/concord/test_d5_path_{w,z,y,x}.py` | 17 unit tests |
| `data/concord/w8_llm_agent/path_{w,x,y,z}_*.{jsonl,json}` | run outputs |
| `reports/agent/concord_w8_framework_health.md` | THIS FILE |

(detailed file-by-file LOC in commit message.)

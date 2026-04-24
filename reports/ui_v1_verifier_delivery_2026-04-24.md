# Track UI/V1 — Verifier integration into the demo UI

- **Date:** 2026-04-24
- **Branch:** `integration-day1`
- **Predecessor:** UI v0 (`reports/ui_v0_delivery_2026-04-24.md`),
  Track V verifier (`reports/verifier_v0_delivery_2026-04-24.md`),
  pipeline Q1+Q2 (`reports/pipeline_literature_delivery_2026-04-24.md`)
- **Audience:** anyone running the demo or extending the verifier panel

This delivery makes Panel 4 (Verifier) live. It implements the
integration §7 of the UI v0 report sketched, plus the optional Live-mode
Stage D (§7.5 option b). The new shape is **a 4-stage end-to-end flow**
from raw spectrum to verified narrative, surfaced through the same
4-panel layout.

---

## 1. The new pipeline

```
                    spectrum (cached fixture or pasted JSON)
                                      │
                                      ▼
       ╔══════════════════════════════════════════════════════╗
       ║  Stage 1 — input  (UI: Panel 1)                      ║
       ╚══════════════════════════════════════════════════════╝
                                      │
       ╔══════════════════════════════════════════════════════╗
       ║  Stage 2 — deterministic pipeline  (diffms env, ~5m) ║
       ║   A1 preprocess → A2 prefilter                       ║
       ║   B library_search ─┐                                ║
       ║                     ├→ merge + dedupe                ║
       ║   C molecule_generate (CandidateFusionFingerprinter  ║
       ║                       → MS-BART) ─┘                  ║
       ║   D1 fetch_metabolite_info  }                        ║
       ║   D2 pathway_context        } per-candidate          ║
       ║   E  predict_spectrum (CFM-ID)                       ║
       ║   F  literature_search (Europe PMC, top-N=3)         ║
       ║                                                      ║
       ║   → IdentificationReport(.literature_records, …)     ║
       ║   → predicted_spectra sidecar (CFM-ID overlays)      ║
       ║                              (UI: Panel 2)           ║
       ╚══════════════════════════════════════════════════════╝
                                      │
       ╔══════════════════════════════════════════════════════╗
       ║  Stage 3 — orchestrator narrative  (metagent-llm,    ║
       ║                                     1 LLM call ~30s) ║
       ║   formatter renders Literature subsection per        ║
       ║   candidate → MiniMax-M2.7 reads it → response_cleaned║
       ║                              (UI: Panel 3)           ║
       ╚══════════════════════════════════════════════════════╝
                                      │
       ╔══════════════════════════════════════════════════════╗
       ║  Stage 4 — verifier cascade  (metagent-llm,          ║
       ║                              up to 7 LLM calls ~5–9m)║
       ║   Stage 1 extract → Stage 2 classify → Stage 3       ║
       ║   per-claim verification (Layer A grounded /         ║
       ║                          Layer B factual /           ║
       ║                          Layer C biological /        ║
       ║                          Layer E literature) +       ║
       ║   Layer D consistency sweep → Stage 4 rewrite +      ║
       ║   re-extract + re-verify                             ║
       ║                                                      ║
       ║   → VerifiedIdentification (sidecar)                 ║
       ║                              (UI: Panel 4 ← new)     ║
       ╚══════════════════════════════════════════════════════╝
```

Total wall-clock per Live run: **~10–15 min** (pipeline ≈5 min +
orchestrator ≈30 s + verifier ≈5–9 min, network-dependent).

---

## 2. UI changes — what landed

### 2.1 `ui/panels/verifier.py` — PREVIEW retired, real renderer in

The static placeholder is gone. The panel now exposes:

| Element | Purpose |
|---|---|
| **Summary line** (Markdown) | overall_verdict (colour-coded), claim count, per-verdict-type count badges, LLM-call-count |
| **Verdict table** (Dataframe, 5 cols) | one row per VerifiedClaim: text · type · verdict (HTML colour) · evidence (truncated 240 chars) · correction |
| **Rewritten-narrative accordion** | Stage 4 rewritten output, shown only when it differs from source; collapsed by default |
| **Warnings block** | `verification_warnings` from the cascade; hidden when empty |

`render(verifier_row) -> 4-tuple` is a **pure function over the dict**
the runner / loader provides. No Gradio runtime needed — all 13 unit
tests in `tests/test_ui/test_panel_verifier.py` exercise it via plain
pytest.

### 2.2 `ui/data/loaders.py` — sidecar awareness

`CachedRun` got a `verifier_row: dict | None` field. `load_cached_run`
now also reads
`/data/weiwentao/llm_agent_metabolomics/verifier_runs/<trace_id>.verifier.json`
when present.

Two new public helpers:

```python
load_verifier_verdict(trace_id) -> dict | None
verifier_sidecar_path(trace_id) -> Path  # writers + readers share this
```

Sidecar shape is `VerifiedIdentification.model_dump(mode="json")`.

### 2.3 `ui/data/runners.py` — Live Stage D

New function:

```python
run_live_verifier(report_dict, llm_output, *, trace_id) -> tuple[dict | None, str | None]
```

Calls `verifier.agent.verify(...)` in-process, persists the sidecar to
`/data/.../verifier_runs/<trace_id>.verifier.json`, returns
`(verifier_dump, error_message)` where exactly one is None. Mirrors
`try_literature_search`'s graceful-error pattern.

`run_live(...)` now returns a 5-tuple
`(report_dict, llm_row, verifier_dump, verifier_error, trace_id)` and
emits a four-step progress sequence (`Step 1/4 … Step 4/4`).

### 2.4 `ui/app.py` — 16 → 20 outputs, 4 progressive stages

* `panel_outputs` extended with the four verifier outputs
  (summary, verdict_table, rewritten_body, warnings_md).
* `_blank_panels_tuple()` now returns 20 elements.
* Both `_load_cached_progressive` (cached) and `_run_live_progressive`
  (live) yield 4 stages with `Step N/4` prefixes, painting in the
  Verifier panel on stage 4.
* Header label: "(future) a verifier verdict" → "the verifier's
  per-claim verdict (Track V, live in this build)."

Zero changes to Panels 1/2/3, the literature button, the 3-view LLM
toggle, the live pipeline subprocess, or the predicted-spectra
sidecar mechanism.

---

## 3. Backfilled sidecars — cached-mode coverage

To make cached mode self-contained (so a maintainer doesn't have to
run Live mode just to see Panel 4), the four canonical fixtures have
been backfilled by `scripts/backfill_verifier_sidecars.py`. Each
sidecar is the JSON dump of a single live-LLM verifier cascade run on
the cached IdentificationReport + cached orchestrator output.

Path: `/data/weiwentao/llm_agent_metabolomics/verifier_runs/<trace_id>.verifier.json`

Backfill results — see Appendix A for verbatim per-fixture data.

| fixture | trace_id | overall | LLM calls | wall-clock | v1 / v2 claims | notable |
|---|---|---|---:|---:|---|---|
| **glucose_pos** | `o1-part4-glucose_pos` | partially_verified | 7 | 325 s | 63 / 15 | **H1 caught: D-Gulose C₇H₁₄O₇ → C₆H₁₂O₆** (Layer A grounded; v2 collapses to 0 contradicted after rewriter) |
| caffeine_pos | `o1-part4-caffeine_pos` | **NOT BACKFILLED** | — | — | — | both attempts hit MiniMax upstream errors (Read timeout 600 s, then HTTP 529 "服务繁忙"). Re-run `scripts/backfill_verifier_sidecars.py --fixtures caffeine_pos` when MiniMax is less loaded. |
| lcarnitine_pos | `o1-part4-lcarnitine_pos` | partially_verified | 7 | 680 s | 47 / 39 | 0 contradicted (LLM correctly hedged on the zwitter D-1 quirk; H6 respected end-to-end) |
| glucose_pos_fusion | `o1-part4-glucose_pos_fusion` | partially_verified | 7 | 411 s | 53 / 42 | First fixture exercising Q1+Q2; richer claim graph than v0 fixtures (5 factual_roundtrip claims, 17 biological) |

**Backfill coverage: 3/4 fixtures.** Caffeine_pos has no sidecar yet — UI will display "no verifier verdict for this run" on Panel 4 for that fixture, which is graceful-degraded behaviour the panel was designed to handle. Backfill cost so far: ~$0.30 across 3 successful + 2 failed attempts (failures cost <$0.01 each — they error before the cascade does meaningful work).

---

## 4. Tests

| Suite | Count | Purpose |
|---|---:|---|
| `tests/test_ui/test_panel_verifier.py` | 13 | Pure-render unit tests over `verifier.render()`: summary content, verdict colour, v2-vs-v1 fallback, rewritten body collapse, warnings hide, evidence truncation |
| `tests/test_ui/test_loaders.py` (extension) | +6 | `load_verifier_verdict` happy / missing / bad-JSON / empty trace_id; `CachedRun.verifier_row` populated when sidecar present, None when absent; `verifier_sidecar_path` shape |
| `tests/test_ui/test_runners.py` (extension) | +4 | `run_live_verifier`: empty-output skip, invalid-report error, success path persists sidecar, verifier crash propagates |
| **Subtotal — UI** | **51 passing** (29 prior + 22 new) | |
| Pre-existing verifier / orchestrator / pipeline | 179 | unchanged after the UI session |

Full sweep:

```bash
# UI tests (metagent-llm env — gradio installed there)
conda run -n metagent-llm python -m pytest tests/test_ui/ -q

# Verifier + orchestrator + Q1+Q2 pipeline tests (system Python, has rdkit + matchms)
python3 -m pytest tests/test_verifier/ tests/test_orchestrator/ \
                  tests/integration/test_pipeline_fp_strategy.py \
                  tests/integration/test_pipeline_literature.py -q
```

Total: **230 tests passing**.

---

## 5. How to run the demo

### 5.1 Cached mode only (no live LLM, no DBs)

```bash
conda run -n metagent-llm python -m ui.app --host 0.0.0.0 --port 7861
```

Pick any fixture in the dropdown. Panel 4 shows the verifier verdict
from the backfilled sidecar.

### 5.2 Live mode (4-stage end-to-end)

```bash
MINIMAX_API_KEY="$(cat api_key.txt)" \
METAGENT_HMDB_PATH=/data/weiwentao/llm_agent_metabolomics/hmdb.sqlite \
METAGENT_RAMP_PATH=/data/weiwentao/llm_agent_metabolomics/ramp.sqlite \
METAGENT_CFM_URL=http://127.0.0.1:8088 \
METAGENT_GNPS_PATH=/data/weiwentao/llm_agent_metabolomics/gnps/ALL_GNPS_cleaned_enriched.csv \
METAGENT_GNPS_SPECTRA_PATH=/data/weiwentao/llm_agent_metabolomics/gnps/ALL_GNPS_cleaned.mgf \
METAGENT_PUBCHEM_LITE_PATH=/data/weiwentao/llm_agent_metabolomics/pubchem_lite.sqlite \
METAGENT_MSBART_CKPT=/home/weiwentao/workspace/mol_gen/MS-BART/data/MassSpecGym/MS-BART-MassSpecGym/csyanghan/MS-BART-MassSpecGym \
conda run -n metagent-llm python -m ui.app --host 0.0.0.0 --port 7861 --enable-live
```

Custom-spectrum tab → paste JSON → "Run pipeline + LLM". Watch the
status line crawl through `Step 1/4 → 2/4 → 3/4 → 4/4` over ~10–15 min.

### 5.3 Backfill for new fixtures

After producing a fresh `<trace_id>.json` in `pipeline_runs/` (e.g. via
Live mode), run the verifier offline against it:

```bash
MINIMAX_API_KEY=... \
conda run -n metagent-llm python scripts/backfill_verifier_sidecars.py
# or just one fixture:
conda run -n metagent-llm python scripts/backfill_verifier_sidecars.py \
    --fixtures glucose_pos
# overwrite existing sidecars:
conda run -n metagent-llm python scripts/backfill_verifier_sidecars.py --force
```

---

## 6. Architecture decisions

| Decision | Rationale |
|---|---|
| Verifier sidecar separate from pipeline JSON | Verifier is run-once-then-cached; pipeline is run-once-then-multiple-LLM-passes. Separate files let Stage 4 be regenerated without rerunning Stages 1–2. |
| Sidecar keyed by orchestrator `trace_id` (not `<trace_id>_verified`) | UI displays verifier verdicts paired with the orchestrator output that was verified; the sidecar belongs to that report's directory entry. The `_verified` suffix lives only inside `VerifiedIdentification.trace_id` for log-join purposes. |
| `claims_v2` preferred over `claims_v1` in display | v2 is the post-rewrite, user-visible state. v1 only shown when v2 is empty (Stage 4 didn't run because nothing was actionable). |
| Verdict table is a Dataframe (not a list of cards) | Reviewer wants to scan and sort 20+ claims; cards do not scale. |
| Rewritten body in a closed accordion | Most demo viewers won't open it; those who do want to compare to the LLM panel above without the rewriter dominating screen real-estate. |
| Live-mode verifier in-process (not subprocessed) | Verifier shares MiniMax / openai with the orchestrator (same metagent-llm env). No reason to add subprocess overhead — only the pipeline needs the diffms split. |
| Verifier failure degrades UI to a yellow status, not red | A verifier crash does not invalidate Stages 1–3; the user still gets pipeline + LLM. The status colour matches the severity. |
| Backfill script is idempotent (refuses to overwrite) | Prevents "I just ran the demo and it overwrote my interesting verifier output" footguns. `--force` is opt-in. |

---

## 7. Known limitations

1. **Verifier wall-clock dominates Live mode.** A worst-case Live run
   is ~15 min total (pipeline 5 + orchestrator 0.5 + verifier 9). The
   Gradio progress bar shows stage transitions but no intra-verifier
   progress — the ~9 min Stage 4 looks frozen. A future iteration
   could stream per-LLM-call progress out of the verifier.
2. **Verifier does not stream.** The full `VerifiedIdentification` is
   produced atomically; the UI cannot show partial verdicts mid-cascade.
   Tradeoff: simpler IPC vs interactivity.
3. **Sidecar format is `model_dump(mode="json")`.** A schema bump in
   `verifier/schemas.py` would invalidate previously-backfilled
   sidecars. Backfill regenerates from `logs/llm_calls.jsonl` + cached
   pipeline JSONs, but each regeneration costs ~$0.07 / fixture.
4. **No "rerun verifier" button in the UI.** Cached-mode verifier
   verdicts are read-only; to refresh, run the backfill script (or
   delete the sidecar and let cached mode show "no verifier verdict
   for this run").
5. **Verdict-table HTML colour rendering.** Gradio Dataframe with
   `datatype="html"` works in most modern themes but degrades to raw
   tags in some custom CSS variants. The plain-text verdict label
   ("contradicted") still appears even when the colour wrapper fails.
6. **Live-mode verifier env requirements.** `verifier.layers.factual`
   may transitively import from `tools.metabolite_info` if a Layer B
   round-trip fires (rare; most claims source-first). That import works
   in metagent-llm because tools/metabolite_info has no torch / matchms
   dep.
7. **Q1+Q2 changes in formatter ARE visible to the verifier.** The
   formatter's literature subsection now flows into the LLM input;
   when the LLM cites a PMID inline, Layer E will fire. None of the
   four backfilled outputs from before Q2 contain PMID citations, so
   Layer E sits at zero activation in the cached fixtures (as
   documented in §5.4 of the pipeline_literature delivery).

---

## 8. What the next session should add

1. **Side-by-side diff view** for the rewritten narrative — currently
   we just show the rewritten text. A diff (diff2html-style) would
   make Stage 4's surgery on the LLM output visible at a glance.
2. **Click-through from a verdict row to the source field** — when a
   claim's `source_field` is `candidates[0].metabolite_info.molecular_formula`,
   a click could open Panel 2's top-1 detail accordion at that field.
3. **Verifier progress streaming** — Stage 4 of the cascade is
   currently opaque; a websocket / Gradio update yielding per-LLM-call
   progress would shorten perceived wall-clock.
4. **Cross-run analytics panel** — a fifth panel (or a separate tab)
   aggregating per-fixture verdict distribution across all
   `verifier_runs/*.verifier.json` would let reviewers spot trends
   ("70% of fixtures have at least one CONTRADICTED grounded claim").
5. **Title-mismatch detection** in Layer E (deferred from Q2 §7.1):
   would fire on claims like "PMID 12345 reports glucose chemistry"
   when 12345 is actually about something else. Not a UI change per
   se, but the UI's verdict-table would visibly populate the
   `correction` column.
6. **Live-mode "skip verifier" toggle** — for users who want a
   pipeline-only run without the ~9 min verifier wait. Today they
   have to run the Live mode in full; a checkbox would speed
   iteration.

---

## Appendix A — backfill output (verbatim)

The verifier sidecars produced by
`scripts/backfill_verifier_sidecars.py` against the four cached
fixtures' orchestrator outputs.

### A.1 Per-fixture summary

```
=== o1-part4-glucose_pos ===
overall_verdict: partially_verified    llm_calls: 7    wall-clock: 325 s
v1 (63 claims): supported 11 · unsupported 33 · contradicted 1 · unverifiable_v0 18
v2 (15 claims): supported  7 · unsupported  6 · contradicted 0 · unverifiable_v0  2
claim_type:    grounded 29 · biological 17 · consistency 12 · literature 3 · factual 2

CONTRADICTED v1 claims (1):
  - [grounded_claim] D-Gulose has molecular formula C₇H₁₄O₇
    correction:   C6H12O6
    source_field: candidates[0].metabolite_info.molecular_formula
    Layer A grounded fired; Stage 4 rewriter substituted; v2 has 0 contradicted
```

```
=== o1-part4-glucose_pos_fusion ===
overall_verdict: partially_verified    llm_calls: 7    wall-clock: 411 s
v1 (53 claims): supported 14 · unsupported 30 · contradicted 0 · unverifiable_v0 9
v2 (42 claims): supported 13 · unsupported 15 · contradicted 0 · unverifiable_v0 14
claim_type:    grounded 23 · biological 17 · consistency 8 · factual 5

This is the post-Q1+Q2 fixture (MS-BART contributed candidates,
literature_records populated). Richer claim graph than the v0 originals
— 5 factual_roundtrip claims (ID round-trips), 17 biological (pathway
membership). LLM did not produce any clear hallucinations on this run.
```

```
=== o1-part4-lcarnitine_pos ===
overall_verdict: partially_verified    llm_calls: 7    wall-clock: 680 s
v1 (47 claims): supported  6 · unsupported 24 · contradicted 0 · unverifiable_v0 17
v2 (39 claims): supported  6 · unsupported 25 · contradicted 0 · unverifiable_v0  8
claim_type:    grounded 30 · factual 8 · biological 7 · consistency 2

H6 (honest non-identification on the L-carnitine D-1 quirk) respected
end-to-end: verifier never injects the literal "L-carnitine"; LLM
correctly flagged the zwitter ester as the pipeline's actual top-1
with low confidence. H7 silicon-warning routed to UNVERIFIABLE_V0
(correct chemistry; not a hallucination, not a CONTRADICTED).
```

```
=== o1-part4-caffeine_pos ===
status: NOT BACKFILLED — both attempts failed on MiniMax upstream
attempt 1: openai.error.Timeout — Read timed out (600 s)
attempt 2: openai.error.APIError — HTTP 529 "当前时段请求拥挤" (server busy)
remediation: rerun  conda run -n metagent-llm python scripts/backfill_verifier_sidecars.py --fixtures caffeine_pos  during off-peak hours.
```

### A.2 Verbatim CLI output

```
Backfilling 4 fixture(s).
Sidecar dir: /data/weiwentao/llm_agent_metabolomics/verifier_runs/

  ✓ glucose_pos: partially_verified (63 v1, 15 v2, 7 LLM calls, 325s)
  ! caffeine_pos: verifier crashed: Timeout: Read timed out (600s)
  ✓ lcarnitine_pos: partially_verified (47 v1, 39 v2, 7 LLM calls, 680s)
  ✓ glucose_pos_fusion: partially_verified (53 v1, 42 v2, 7 LLM calls, 411s)
```

The MiniMax 600 s timeout on caffeine's first attempt is the same
upstream-noise pattern documented in
`reports/verifier_v0_delivery_2026-04-24.md` §5 known-limitation #2:
`<think>` blocks vary widely in length; a single ~10 min `<think>`
hits the openai-client default timeout and aborts the cascade.
Workaround documented there: rerun. The backfill script supports
`--fixtures caffeine_pos --force` to retarget a single fixture.

## Appendix B — file inventory

```
ui/panels/verifier.py              REWRITE  — PREVIEW removed; live render added
ui/data/loaders.py                 MODIFIED — load_verifier_verdict / verifier_sidecar_path /
                                              CachedRun.verifier_row / _VERIFIER_RUNS const
ui/data/runners.py                 MODIFIED — run_live_verifier; run_live() returns 5-tuple;
                                              4-step progress messages
ui/app.py                          MODIFIED — panel_outputs 16→20; _blank_panels_tuple 20-arity;
                                              _render_for_panels accepts verifier_row;
                                              _load_cached_progressive 3→4 stages;
                                              _run_live_progressive 3→4 stages with Stage D
                                              in-process verifier call
scripts/backfill_verifier_sidecars.py NEW   — idempotent CLI to populate sidecars from
                                              cached IdentificationReport + cached llm_calls
tests/test_ui/test_loaders.py      EXTENDED — +6 verifier-loader tests
tests/test_ui/test_runners.py      EXTENDED — +4 run_live_verifier tests
tests/test_ui/test_panel_verifier.py NEW    — 13 pure-render tests
reports/ui_v1_verifier_delivery_2026-04-24.md  NEW — this file
```

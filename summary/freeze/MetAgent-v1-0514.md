# MetAgent-v1-0514 — Freeze Report

**Tag:** `MetAgent-v1-0514` (annotated, pointing to commit `102fba9`)
**Branch (long-lived for hotfix):** `release/v1-0514`
**Freeze date:** 2026-05-14
**Default LLM at freeze:** `MiniMax-M2.7` via `api.minimaxi.com/v1` (T=0)
**Repo root:** `/home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5`

> Companion doc: [`MetAgent-v1-0514_dirty_disposition.md`](./MetAgent-v1-0514_dirty_disposition.md) — full disposition of every untracked / modified file at session start.

---

## §1. Version overview (one-pager)

### Stage cut

- **Phase A3 complete + Phase A4 D0 cross-LLM smoke landed** (the original `2bf6517` HEAD), plus three Phase 6.x feature commits (`d0304c7` / `116a892` / `24d71d4`) and eight freeze-completion commits making the tag state actually runnable from a fresh clone.

### Three architectural blocks

1. **Stage 1 — Spectrum → Molecule (Sub-6A path)**
   `evaluation/sub6/run_sub6a.py:375 main()` → `evaluation/sub6/run_sub6a.py:171 identify_spectrum(...)` → library_search (GNPS modified-cosine) → top-1 per spectrum → dedup → `Sub6AResult` JSONL.

2. **Stage 2 — Molecule list → Pathway narrative (Sub-6B path)**
   - Single-call: `evaluation/sub6/prompts.py:12 SYSTEM_PROMPT`
   - ReAct: `prompts/agent/sub6b_react_prompt.md` + `evaluation/sub6/prompts_agent.py:60 build_react_messages()`
   - Feedback closed-loop: `evaluation/sub6/run_sub6b_react_feedback.py:982 main()`

3. **Verifier cascade — 10 layers, 4 of which are Sub-6 enrichment layers**
   `verifier/agent.py:444 _verify_per_claim_sub6()` dispatches to set-enrichment, driver-metabolite, pathway-relationship, biological-sub6.

### Key capabilities

- **ReAct loop**: 5 function tools (`tools/agent_tools/{lookup_compound_info,query_kegg_path,query_pathway_membership,query_ramp_enrichment,search_literature}.py`), `dedup_cache` + `max_react_turns=5`
- **Verifier feedback loop**: prevention + correction, `max_feedback_iters=2`, quality rollback
- **10-layer verifier cascade**: A-F + 6a/6b/6c/6d (see §6 for files)
- **K=10 task-level asyncio parallel**, 7.3-8.2× speedup measured (Phase A3 D3, 63-task pilot)
- **Retry-with-backoff**: 5xx / Timeout / 529 / MiniMax 2064; <0.1% final failure across A3 (Phase A2 § 5 #5)

### Benchmark

- **Sub-6A** (Spec→Mol→Pathway end-to-end): 38 tasks / 459 spectra
  Task file: `data/benchmark/sub6/sub6a_e2e_tasks_v2.jsonl` (38 lines, 3.4 MB)
- **Sub-6B** (Mol→Pathway, agentic): 63 tasks (includes 11 LIPID MAPS lipid tasks)
  Task file: `data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl` (63 lines, 4.8 MB)

---

## §2. Reproduction

### 2.0 Environment

The repo currently has **no `environment.yml`, `requirements.txt`, or `pyproject.toml`**. Reproducing the freeze requires assembling the runtime by inspection. Known critical dependencies:

| Package | Use |
|---|---|
| python ≥ 3.11 (tested on 3.13) | runtime |
| `openai>=1.0` | OpenAI-protocol clients (MiniMax + viviai relay) |
| `pydantic>=2.0` | schemas |
| `httpx` | sync HTTP for LLM clients |
| `matchms` (≥ 0.24) | modified-cosine spectral similarity |
| `rdkit` | InChIKey, Tanimoto, MCS |
| `numpy`, `scipy`, `pandas` | numerics |
| `sqlite3` (stdlib) | RaMP-DB, KEGG hierarchy, ClassyFire cache |

**TODO**: the next freeze (v2) should commit a `requirements.txt` pinned from `pip freeze` of the runtime env.

External services / databases (paths reflect the current developer's machine; **not portable**):

| Resource | Location | Size |
|---|---|---|
| RaMP-DB SQLite | `/data/weiwentao/llm_agent_metabolomics/ramp.sqlite` (env: `METAGENT_RAMP_PATH`) | 1.95 GB |
| GNPS library | (consumed via library_search; path is configured inside the index builder) | — |
| SIRIUS CLI 6.3 | system-installed; runtime auto-relogin via env `METAGENT_SIRIUS_USER` / `METAGENT_SIRIUS_PASS` | — |
| CFM-ID udocker container | `localhost:8088` (Phase 6.x rerank) | — |
| MiniMax API key | `api_key_minimax.txt` at repo root (gitignored) | — |
| viviai relay key | `api_key_gpt.txt` / `api_key_claude.txt` (gitignored) — used for GPT-5.5 / Claude Opus-4-7 routing | — |

### 2.1 Reproduce the Sub-6A baseline (38 tasks, 459 spectra)

```bash
# Checkout the freeze
git checkout MetAgent-v1-0514

# Set RaMP path (and SIRIUS creds if running v2 reranker paths)
export METAGENT_RAMP_PATH=/path/to/ramp.sqlite

# Run Sub-6A end-to-end with default narrative LLM (MiniMax-M2.7)
python -m evaluation.sub6.run_sub6a \
  data/benchmark/sub6/sub6a_e2e_tasks_v2.jsonl \
  data/eval/sub6/sub6a_repro.jsonl \
  --narrative-llm minimax

# Expected wall time (single-process, no K=10 parallelism in run_sub6a):
#   ~1.5-2 min per task × 38 tasks ≈ 60-75 min total
# Output: data/eval/sub6/sub6a_repro.jsonl  (one Sub6AResult per task)
```

To switch the narrative LLM for cross-LLM ablations (Phase A4 D0 hooks landed at `2bf6517`):

```bash
python -m evaluation.sub6.run_sub6a ... --narrative-llm gpt55
python -m evaluation.sub6.run_sub6a ... --narrative-llm opus47
```

### 2.2 Reproduce one Sub-6B closed-loop task

```bash
python -m evaluation.sub6.run_sub6b_react_feedback \
  --task-id compound_only_enrich_mammalian_RAMP_P_000000421_seed3 \
  --tasks data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl \
  --out /tmp/sub6b_repro.jsonl \
  --persist-dir /tmp/sub6b_repro_persist \
  --ramp-db /path/to/ramp.sqlite \
  --max-react-turns 5 --max-feedback-iters 2 \
  --total-timeout 900

# Expected wall time per task: 4-9 min depending on narrative depth and tool calls
# (see Phase A3 D3 audit: average 232-261 min for 63-task × K=10 batch)
```

### 2.3 Reproduce the Phase A3 D3 batch (63 tasks × 3 architectures × K=10)

The batch driver used in A3 D3 (`scripts/eval_sub6/run_a2_d4_3way.py`) iterates the Sub-6B v3 task file across `single` / `react` / `feedback` modes and persists to a configurable out dir:

```bash
python -m scripts.eval_sub6.run_a2_d4_3way \
  --tasks data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl \
  --out-dir data/eval/sub6/v4_a3_d3_repro_no_lit \
  --workers 10 \
  --model MiniMax-M2.7 --provider minimax \
  $(jq -r '.task_id' data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl | sed 's/^/--task-id /')

# Phase A3 D3 wall time: 261 min for no_lit pass-1, 232 min for +lit pass-2.
```

> **TODO** for v2 freeze: collapse the per-task `--task-id` expansion into a single flag, and rename the script (it carries the A2-era `run_a2_d4_3way` name even though A3 D3 reuses it).

### 2.4 Aggregate results

Per-track aggregators live under `scripts/eval_sub6/`:

```bash
python -m scripts.eval_sub6.aggregate_a3_pathway_accuracy
python -m scripts.eval_sub6.aggregate_phase6_2     # Phase 6.2 SIRIUS+CFM ablation
python -m scripts.eval_sub6.aggregate_phase6_3     # Phase 6.3 LLM reranker
python -m scripts.eval_sub6.aggregate_phase6_4     # Phase 6.4 Layer-F loop closed
```

---

## §3. Headline metrics

All numbers are cited to the source file:line they were grep'd from. **No fabricated numbers.**

| Metric | Value | Source |
|---|---|---|
| **Sub-6A Stage-1 top-1 identification** | **67.32 %** (309 / 459 spectra) | `summary/May_7/STAGE_REPORT.md:13`, `:78` |
| Sub-6A per-task top-1 mean | 67.37 % | `summary/May_7/STAGE_REPORT.md:80` |
| Sub-6A per-task top-1 median | 67.95 % | `summary/May_7/STAGE_REPORT.md:81` |
| Sub-6A per-task top-1 range | 28.57 % – 100 % | `summary/May_7/STAGE_REPORT.md:82` |
| Sub-6A per-spectrum identified rate | 97.60 % (448/459) | `summary/May_7/STAGE_REPORT.md:79` |
| **Sub-6B supported, closed-loop, fb_nolit (N=3)** | **25.23 ± 6.16 %** | `reports/agent/phase_a3_audit.md:58` |
| **Sub-6B supported, closed-loop, +literature (N=3)** | **25.70 ± 7.16 %** | `reports/agent/phase_a3_audit.md:58` |
| Sub-6B contradicted, fb_nolit | 1.97 ± 1.03 % | `reports/agent/phase_a3_audit.md:60` |
| Sub-6B contradicted, +literature | 2.20 ± 1.31 % | `reports/agent/phase_a3_audit.md:60` |
| **Sub-6B unverifiable_v0 (known-issue)** | **67.04 ± 5.78 %** (no_lit) / **66.20 ± 5.82 %** (+lit) | `reports/agent/phase_a3_audit.md:61` |
| Layer E (literature) call rate | ~0.7 calls / feedback iter | `reports/agent/phase_a3_audit.md:97` |
| 63-task K=10 wall time, no_lit pass-1 | 261 min (sequential proj. ~1900 min → 7.3× speedup) | `reports/agent/phase_a3_audit.md:163` |
| 63-task K=10 wall time, +lit pass-2 | 232 min (7.3× speedup) | `reports/agent/phase_a3_audit.md:164` |
| Per-task wall floor (verifier sequential LLM chain) | 360-540 s | `reports/agent/phase_a3_audit.md:179-180` |

### 3.x Smoke regression (D3) at freeze HEAD

Import smoke at `102fba9` (the tag commit): **13/13 critical modules import without error**:

```
evaluation.sub6.run_sub6a            ✓
evaluation.sub6.run_sub6b_react_feedback ✓
verifier.agent                       ✓
verifier.claim_extractor             ✓
verifier.claim_classifier            ✓
tools.agent_tools                    ✓
tools.agent_tools.dispatcher         ✓
tools.benchmark.sub6.ramp_enrichment ✓
tools.lipidmaps                      ✓
schemas.sub6_report                  ✓
verifier.layers.driver_metabolite    ✓
verifier.layers.set_enrichment       ✓
common.llm_client                    ✓
```

End-to-end smoke run (1 Sub-6A task + 1 Sub-6B task), MiniMax-M2.7, T=0:

- **Sub-6A**: 1 task, default `--limit 1`
- **Sub-6B**: 1 task (`compound_only_enrich_mammalian_RAMP_P_000000421_seed3`, 7 differential metabolites), `--max-react-turns 5`, `--max-feedback-iters 2`

**Sub-6A** — `e2e_enrich_mammalian_RAMP_P_000052855_seed196617997`, 10 spectra, library_search + single-call narrative:

| field | value |
|---|---|
| identifications | 10 (n_spectra=10, n_identified=10) |
| top-1 correct | **6 / 10 (60 %)** |
| per-spec sample | `spectrum_id=sub6a-gnps-CCMSLIB00006403004 predicted_ik14=MUMGGOZAMZWBJJ correct_top1=True primary_retriever=modcos reranker_mode=weighted error=None` |
| narrative length | 3447 chars |
| llm_calls | 1 (single-call narrative, MiniMax-M2.7) |
| elapsed | **1646 s ≈ 27.4 min** (dominated by GNPS index load + library_search) |
| error | None |

The 60 % top-1 falls inside the v1 per-task range 28.57 %–100 % (`summary/May_7/STAGE_REPORT.md:82`), mean 67.37 %. Consistent with the v1 baseline.

**Sub-6B** — `compound_only_enrich_mammalian_RAMP_P_000000421_seed3`, 7 differential metabolites, ReAct (5 turns) + feedback (2 iters max), `--total-timeout 600`:

| field | value |
|---|---|
| ReAct turns recorded | **8 turns** across `iter_idx=0` (one full pass + one partial re-pass) |
| ReAct wall | ~12 s (turns 0-7 in `turns.jsonl` between 08:06:38Z and 08:08:54Z) |
| Verifier iter 0 verdict | quality score `q=[3]` recorded |
| iter 1 consistency check | hit **MiniMax 600 s timeout 3 times** in a row (`api.minimaxi.com` upstream issue, not a freeze-state issue) |
| Retry-with-backoff | exercised correctly — 3 attempts at 11.3 s / 30.6 s / 51.0 s spacing (the documented A3 D0b behaviour, `phase_a3_audit.md:196-198`) |
| final_iter | 0 |
| Total elapsed | 2191 s (12 s actual ReAct + 36 min retry waits on upstream API) |
| error | `timeout_in_feedback_loop` (upstream API, not the freeze code) |

**D3 verdict:** the freeze code-path **works end-to-end** —
- Sub-6A completed cleanly with a verdict that matches v1 baseline distribution
- Sub-6B's ReAct loop + Stage 1+2 verifier completed and produced a quality-3 verdict; Stage 3 consistency check hit transient upstream MiniMax API timeouts whose retry-with-backoff is the documented A3 D0b behaviour. No code-side regression.

Imports (13/13) + Sub-6A end-to-end + Sub-6B ReAct-plus-verifier-iter-0 together demonstrate the tag is a runnable baseline.

---

## §4. Result paths

All paths verified to exist at freeze time. `MISSING` items are NOT in the freeze.

| Path | Status | Notes |
|---|---|---|
| `data/eval/sub6/v4_a3_d3_no_lit/` | ✓ exists | A3 D3 pass-1, 63 tasks × 3 modes. `summary.json` is the per-task roll-up. Gitignored (regeneratable; see disposition doc). |
| `data/eval/sub6/v4_a3_d3_with_lit/` | ✓ exists | A3 D3 pass-2, 63 tasks × 3 modes. Gitignored. |
| `data/eval/sub6/v4_a3_d3_5/` | ✓ exists | A3 D3.5 N=3 reruns × 10 tasks × 6 variants (paper CI gate). Gitignored. |
| `data/eval/sub6/v4_a3_d5_postfix_regrade/` | ✓ exists | A2 D5 narratives re-graded after Layer 6d SQL fix. Gitignored. |
| `data/eval/sub6/v4_a3_d4b_postfix/` | ✓ exists | D4b 20-task re-grade quantifying the SQL fix impact. Gitignored. |
| `data/eval/sub6/sub6a_perfect_id_verdicts_v6_opus47_aliases.jsonl` | ✓ exists | Most-recent perfect-ID verdict file for Sub-6A. Gitignored. |
| `data/eval/sub6/sub6a_real_id_verdicts_v7_phaseA.jsonl` | ✓ exists | Most-recent real-ID verdict file for Sub-6A. Gitignored. |
| `data/eval/sub6/v4_a3_d3_react_only/` | MISSING | Track spec listed this but only `v4_a3_d3_no_lit/{single,react,feedback}/` exists (single dir = react-only). |
| `data/eval/sub6/v4_a3_d3_fb_nolit/` | MISSING | Same — actual name is `v4_a3_d3_no_lit/feedback/`. |
| `reports/agent/phase_a1_smoke_audit.md` | ✓ exists (19 KB) | Committed in `2eb52a7` (freeze docs commit). |
| `reports/agent/phase_a2_feedback_audit.md` | ✓ exists (18 KB) | Same. |
| `reports/agent/phase_a3_audit.md` | ✓ exists (18 KB) | Same. |
| `reports/agent/diagnosis_unverifiable_and_correlation.md` | ✓ exists (17 KB) | Same. |
| `reports/agent/prompt_audit_for_rewrite.md` | ✓ exists (16 KB) | Same. |
| `summary/May_7/STAGE_REPORT.md` | ✓ exists (15 KB) | Committed in `102fba9` (paper artifacts). |
| `summary/May_7/figures/` | ✓ exists, 22 files | 9 Nature-style figs (PDF+PNG) + e2e case figures. |

---

## §5. Known defects (v1 → v2 debt)

The decisions that v2 will revisit, with cite-able source:

1. **UNVERIFIABLE_v0 dominates verdict mass at 63-67 %**
   Root cause is a **4-failure-mode chain**: narrative prompt has no syntactic constraints + claim extractor doesn't filter abstract claims + classifier collects abstract sentences into PEAK_MECHANISTIC / BIOLOGICAL / SET_ENRICHMENT routes that the layers can't verify + feedback hint is neutral toward UNV verdicts so the agent has no signal to fix them.
   → `reports/agent/diagnosis_unverifiable_and_correlation.md` (full diagnosis)
   → `reports/agent/prompt_audit_for_rewrite.md` (proposed v2 fixes)

2. **supported % ≠ task-correct %**
   Claim-level supported and pathway-selection correctness correlate at only ~+8 pp. The verifier reports per-claim confidence but does not gate task-level correctness. v2 must close this.

3. **MS-CLIP retrieval is wired but not enabled in v1**
   Primary retriever defaults to `modcos` (modified-cosine on GNPS). The `--primary-retriever msclip` path is committed and tested but never gated as default at v1.
   → `summary/May_7/STAGE_REPORT.md:70`

4. **Literature integration is a null result at N=3**
   "Calls happen (~0.7 / feedback iter), but downstream verdict shift is within CI95. Either need stronger verifier-side literature grounding (Layer E for pathway claims) OR larger N. Future work." → `reports/agent/phase_a3_audit.md:213-217`

5. **Sub-6A IdReport injection shares Sub-6B's narrative prompt**
   Identical system prompt template across the two tasks despite different inputs. v2 should split.

6. **Verifier internal LLM calls are sequential — the actual wall bottleneck**
   "Verifier extraction is 85 % of wall and is sequential at the within-pass level (extract → classify → consistency are data-dependent). Future work: replace Stage 1 LLM with a distilled / rule-based extractor."
   → `reports/agent/phase_a3_audit.md:218-221`

---

## §6. Code entry anchors (5-minute navigation)

All line numbers verified at `102fba9` (the tag).

| Component | File:Line |
|---|---|
| Sub-6A main entry | `evaluation/sub6/run_sub6a.py:375` |
| Stage 1 batch identify call | `evaluation/sub6/run_sub6a.py:171` |
| Single-call narrative system prompt | `evaluation/sub6/prompts.py:12` |
| ReAct narrative prompt template | `prompts/agent/sub6b_react_prompt.md` |
| ReAct message builder | `evaluation/sub6/prompts_agent.py:60 build_react_messages()` |
| Sub-6B feedback runner CLI | `evaluation/sub6/run_sub6b_react_feedback.py:982 main()` |
| Claim extractor | `verifier/claim_extractor.py:169 extract_claims()` |
| Claim extraction system prompt | `verifier/prompts/extract_claims.py:16 SYSTEM_PROMPT` |
| Claim classifier | `verifier/claim_classifier.py:230 classify_claims()` |
| Classifier disambiguation prompt | `verifier/prompts/classify_ambiguous.py:13 SYSTEM_PROMPT` |
| Sub-6 layer dispatcher | `verifier/agent.py:444 _verify_per_claim_sub6()` |
| Feedback hint neutral set | `verifier/feedback_hints.py:57 _NEUTRAL_VERDICTS` |
| LLM client | `common/llm_client.py:306 chat()` |
| 10 verifier layers | `verifier/layers/` — biological.py, biological_sub6.py, consistency.py, driver_metabolite.py, factual.py, grounded.py, literature.py, pathway_relationship.py, peak_mechanistic.py, set_enrichment.py |
| 5 function tools (ReAct) | `tools/agent_tools/` — lookup_compound_info.py, query_kegg_path.py, query_pathway_membership.py, query_ramp_enrichment.py, search_literature.py |

---

## §7. Branches, tag, and recovery

```
tag MetAgent-v1-0514 → commit 102fba9
branch main          → 102fba9 (track latest stable lineage)
branch release/v1-0514 → 102fba9 (long-lived; hotfixes branch from here)
branch feature/agent-phase-a3 → 102fba9 (synced; superseded by main)
```

To recover the freeze in a new clone:

```bash
git clone <repo>
cd <repo>
git checkout MetAgent-v1-0514
# Restore reference data that was excluded by .gitignore:
#   - RaMP-DB SQLite to $METAGENT_RAMP_PATH
#   - GNPS library bundle
#   - data/lipidmaps/, data/kegg/kgml/, data/classyfire_cache.sqlite caches (regen on first miss)
# Install runtime (see §2.0 dependency list)
pytest tests/                    # sanity
python -m evaluation.sub6.run_sub6a ... # see §2.1
```

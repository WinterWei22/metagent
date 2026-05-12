# MetAgent — Unified closed-loop architecture

The pipeline below subsumes both `fb_nolit` (verifier-feedback only) and
`+lit` (feedback + literature steer) into a single architecture called
**MetAgent**. The literature steer is engaged automatically whenever the
verifier finds an UNSUPPORTED `BIOLOGICAL` claim — there is no separate
"with / without literature" mode at the user-facing level.

```
═══════════════════════════════════════════════════════════════════════════
INPUT: differential metabolite list  (compound names + KEGG/HMDB IDs)
═══════════════════════════════════════════════════════════════════════════
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                  ITERATION 0  (initial ReAct narrative)                 │
│                                                                         │
│   ┌────────────────────────────────────────────────────────────────┐   │
│   │            MiniMax-M2.7  ReAct turn loop  (max 5 turns)        │   │
│   │  ┌────────┐                                                    │   │
│   │  │  LLM   │ ◄─────── tools=[5 functions defined below]         │   │
│   │  │ thinks │ ───────► tool_call(name, args)                     │   │
│   │  └────────┘                  │                                 │   │
│   │       ▲                      ▼                                 │   │
│   │       │            ┌──────────────────┐                        │   │
│   │       │            │ TOOL DISPATCHER  │  (thread-local cache)  │   │
│   │       │            │ • dedup repeat   │                        │   │
│   │       │            │ • 2 KB output cap│                        │   │
│   │       │            │ • Pydantic validate                       │   │
│   │       │            └────────┬─────────┘                        │   │
│   │       │                     │                                  │   │
│   │       │   ┌────────┬────────┼─────────┬────────────┐           │   │
│   │       │   ▼        ▼        ▼         ▼            ▼           │   │
│   │       │ ┌────┐  ┌──────┐ ┌──────┐ ┌──────┐  ┌────────────┐     │   │
│   │       │ │ T1 │  │  T2  │ │  T3  │ │  T4  │  │     T5     │     │   │
│   │       │ │ramp│  │pathwy│ │ kegg │ │compd │  │ literature │     │   │
│   │       │ │enri│  │membr │ │ path │ │ info │  │  (search)  │     │   │
│   │       │ │chmt│  │      │ │ BFS  │ │      │  │            │     │   │
│   │       │ └─┬──┘  └──┬───┘ └──┬───┘ └──┬───┘  └─────┬──────┘     │   │
│   │       │   │        │        │        │            │            │   │
│   │       │   ▼        ▼        ▼        ▼            ▼            │   │
│   │       │ ┌────┐ ┌────────┐ ┌─────┐  ┌─────┐  ┌──────────┐       │   │
│   │       │ │RaMP│ │  RaMP  │ │KEGG │  │HMDB │  │EuropePMC │       │   │
│   │       │ │.sql│ │  .sql  │ │graph│  │MoNA │  │ + PubMed │       │   │
│   │       │ │    │ │pathway │ │.sql │  │PubCm│  │   REST   │       │   │
│   │       │ └────┘ └────────┘ └─────┘  └─────┘  └──────────┘       │   │
│   │       │         tool_result envelope                            │   │
│   │       └────────────────────┘                                    │   │
│   │                                                                 │   │
│   │  exit when LLM outputs no tool_calls OR max_turns/timeout       │   │
│   └────────────────────────┬───────────────────────────────────────┘   │
│                            │                                            │
│                  narrative N0 (chars ~2-3k)                             │
│                            │                                            │
└────────────────────────────┼────────────────────────────────────────────┘
                             ▼
              ┌─────────────────────────────────────────────────┐
              │            VERIFIER  v9-PhaseC                  │
              │             verify_sub6 cascade                 │
              │                                                 │
              │  Stage 1  extract_claims              [MiniMax] │
              │           narrative → atomic claims (~30/task)  │
              │                                                 │
              │  Stage 2  classify_claims     [rules + MiniMax  │
              │           (LLM only on ambiguous claims)        │
              │                                                 │
              │  Stage 3  per-claim layer dispatch (pure DB):   │
              │  ┌─────────────────────────────────────────┐    │
              │  │ 6a set_enrichment ←── RaMP-DB sqlite    │    │
              │  │                       (hypergeometric)  │    │
              │  │ 6b driver_metabolite ← curated HMDB     │    │
              │  │                        pool (jsonl)     │    │
              │  │ 6c biological_sub6  ←─ RaMP-DB sqlite   │    │
              │  │                        (pathway_context)│    │
              │  │ 6d pathway_relation ←─ KEGG reaction    │    │
              │  │                        graph sqlite     │    │
              │  │                        + RaMP pathway   │    │
              │  │                        (phrase→hsa)     │    │
              │  └─────────────────────────────────────────┘    │
              │                                                 │
              │  Stage 4  Layer D consistency         [MiniMax] │
              │           cross-claim contradiction scan        │
              │                                                 │
              │  Annotate: claim_id + feedback_hint             │
              │            (post-process,no DB)                 │
              │                                                 │
              │  ──────────────────────────────────────────     │
              │  Layers NOT routed in Sub-6 (return UNVERIF):   │
              │     A grounded / B factual (HMDB+MoNA+PubChem)  │
              │     E literature (EuropePMC/PubMed roundtrip)   │
              │     F peak_mechanistic (SIRIUS + CFM-ID)        │
              └────────────────┬────────────────────────────────┘
                               │
                  V0 = {supported / unsupported /
                        contradicted / unverifiable}
                  + per-claim feedback_hint (LLM-actionable)
                               │
                               ▼
            ┌───────────────────────────────────┐
            │  q(N0) = #contra + #unsup actionable?
            │                                   │
            │  q == 0 ──────► early exit ──┐    │
            │     OR                       │    │
            │  q > 0 ──► continue to fb    │    │
            └────────────────┬─────────────┘    │
                             │                  │
                             ▼                  │
┌──────────────────────────────────────────────┼───────────────────────┐
│         FEEDBACK ITERATIONS  (max 2)         │                       │
│                                              │                       │
│   ┌──────────────────────────────────────────┘                       │
│   │ Build feedback user message:                                     │
│   │   • CONTRADICTED claims list (id, text, evidence, hint)          │
│   │   • UNSUPPORTED claims list (id, text, evidence, hint)           │
│   │     ┌─ If claim_type=BIOLOGICAL & UNSUPPORTED:                   │
│   │     │  hint = "Call search_literature(\"<focus>\") to find       │
│   │     │          supporting papers and cite them inline (PMID),    │
│   │     │          OR drop if speculative."                          │
│   │     └─ Else: hint = retract / rephrase / qualify (subtype-spec)  │
│   │   • Original narrative N_{i-1}                                   │
│   │   • Hard rules: retract/rephrase/qualify ONLY; no new pathway    │
│   │     claims; Limitations paragraph ≤80 words                      │
│   └─────────────────────┬────────────────────────────────────────────┘
│                         │                                            │
│                         ▼                                            │
│   ┌──────────────────────────────────────────────────────────────┐   │
│   │  MiniMax-M2.7 ReAct turn loop (max ⌈5/2⌉=3 turns)            │   │
│   │  May call tools AGAIN — esp. search_literature on            │   │
│   │  unsupported BIOLOGICAL claims                               │   │
│   │  (dedup cache prevents repeat queries within task)           │   │
│   └─────────────────────┬────────────────────────────────────────┘   │
│                         │                                            │
│                  narrative N_i                                       │
│                         │                                            │
│                         ▼                                            │
│        ┌─────── verifier(N_i) ───────► V_i ─────┐                    │
│                                                  │                    │
│   if q(V_i) == 0  ─────► converged, break        │                    │
│   if i == max_iter ──► loop end                  │                    │
│   else: i += 1 ──► loop back                     │                    │
│                                                  │                    │
└──────────────────────────────────────────────────┘                    │
                                                  │                    │
                                                  ▼                    │
              ┌───────────────────────────────────────┐                │
              │      SELECTION RULE  (rollback)       │                │
              │                                       │                │
              │   compute q(N_i) = #contra + #unsup   │                │
              │   skip iters with verifier_failed     │                │
              │                                       │                │
              │   if q(N2) > q(N0): keep N0           │                │
              │       err = "feedback_made_it_worse"  │                │
              │   elif q(N2) > q(N1): keep N1         │                │
              │       err = "iter2_degraded"          │                │
              │   else: keep N2                       │                │
              └────────────────┬──────────────────────┘                │
                               │                                       │
                               ▼                                       │
                  ┌───────────────────────────┐                        │
                  │    FINAL OUTPUT            ◄───────────────────────┘
                  │  • narrative (winning iter)
                  │  • verdict (supp/contra/unsup/unverif counts)
                  │  • iterations[] (full trace)
                  │  • termination_reason
                  │  • rollback_reason (if any)
                  └────────────────────────────┘

═══════════════════════════════════════════════════════════════════════════
RUNNING INFRASTRUCTURE (cross-cutting)
═══════════════════════════════════════════════════════════════════════════

• Task pool: ThreadPoolExecutor K=10 — 10 tasks parallel, thread-local
  caches and connections

• Retry: chat-level jittered backoff (10/30/60s ± jitter) on
  Timeout / APIConnectionError / 5xx / 529 / MiniMax 2064 overload

• Persistence (TaskPersister):
  data/eval/sub6/.../persist/{task_id}/
    turns.jsonl          ← every ReAct turn (assistant msg + tool_calls)
    iterations.jsonl     ← every feedback iteration summary
    final_state.json     ← completion marker (partial detection if absent)
```

## Tool & data inventory (complete)

### Agent-side — 5 function tools in the ReAct loop

| # | tool | wrapper module | data source | round-trip cost |
|---|---|---|---|---|
| T1 | `query_ramp_enrichment` | `tools/agent_tools/query_ramp_enrichment.py` | RaMP-DB sqlite (`$RAMP_DB_PATH`) | ~50 ms (hypergeometric over ~64k pathways) |
| T2 | `query_pathway_membership` | `tools/agent_tools/query_pathway_membership.py` | RaMP-DB sqlite (`pathway_context`) | ~100 ms |
| T3 | `query_kegg_path` | `tools/agent_tools/query_kegg_path.py` | KEGG reaction graph sqlite (`data/kegg/reaction_graph.sqlite`, BFS) | ~5 ms |
| T4 | `lookup_compound_info` | `tools/agent_tools/lookup_compound_info.py` | HMDB sqlite (`$METAGENT_HMDB_PATH`) → MoNA → PubChem PUG-REST | ~50 ms (local DB) / ~2 s (PubChem) |
| T5 | `search_literature` | `tools/agent_tools/search_literature.py` | Europe PMC REST + PubMed E-utilities fallback | ~2-5 s (network) |

All 5 wrappers share:
- Pydantic input validation
- 2 KB output envelope (`truncate_to_budget`)
- Thread-local dedup cache (per-task, cleared between tasks)
- Graceful error envelope (`{"error": ..., "fallback_suggested": ...}`)

### Verifier-side — per-layer DB / LLM usage

| stage / layer | runs in Sub-6? | resource | LLM? |
|---|:---:|---|:---:|
| Stage 1 `extract_claims` | ✅ always | MiniMax-M2.7 | ✅ 1 call |
| Stage 2 `classify_claims` | ✅ when ambiguous | rules + MiniMax | ⚠️ 0-1 call |
| **Layer 6a** `set_enrichment` | ✅ for `set_enrichment` claims | RaMP enrichment result on task | ❌ |
| **Layer 6b** `driver_metabolite` | ✅ for `driver_metabolite` claims | curated HMDB pool (`data/benchmark/sub6/curated_hmdb_mammalian.jsonl`) | ❌ |
| **Layer 6c** `biological_sub6` | ✅ for `biological_claim` claims | RaMP-DB sqlite (pathway_context backend) | ❌ |
| **Layer 6d** `pathway_relationship` | ✅ for `pathway_relationship` claims | KEGG reaction graph sqlite + RaMP `pathway` table (phrase → hsa-id) | ❌ |
| Stage 4 `Layer D consistency` | ✅ when ≥2 claims | MiniMax-M2.7 | ✅ 1 call |
| Layer A `grounded` | ✗ (spectrum only) | source_report field lookup | ❌ |
| Layer B `factual` | ✗ (spectrum only) | HMDB sqlite + MoNA + PubChem | ❌ |
| Layer E `literature` | ✗ (spectrum only) | Europe PMC + PubMed round-trip | ❌ |
| Layer F `peak_mechanistic` | ✗ (spectrum only) | SIRIUS CLI + CFM-ID | ❌ |

Per-task verifier cost (Sub-6 path × 3 feedback iterations):
- MiniMax calls: **6–9** (Stage 1 × 3 + Stage 4 × 3, plus 0-3 Stage 2 if ambiguous)
- RaMP-DB sqlite reads: **~30+** (one per claim, mostly 6c)
- KEGG graph sqlite reads: **~5-15** (one per `pathway_relationship` claim)
- Curated HMDB pool: in-memory lookup (loaded once at runtime)

### Agent ↔ verifier — shared data sources

The agent's 5 tools and the verifier's 4 active Sub-6 layers query the **same underlying databases**. This is by design: the agent retrieves evidence prospectively, the verifier checks the same source retrospectively — so when the agent cites `KEGG map00270`, the verifier checks the same RaMP / KEGG table the agent used.

| agent tool | verifier counterpart layer | shared data |
|---|---|---|
| T1 `query_ramp_enrichment` | Layer 6a `set_enrichment` | RaMP-DB hypergeometric (same `compute_enrichment` code) |
| T2 `query_pathway_membership` | Layer 6c `biological_sub6` | RaMP-DB sqlite (same `pathway_context` backend) |
| T3 `query_kegg_path` | Layer 6d `pathway_relationship` | KEGG reaction graph sqlite (same BFS primitive, `tools/kegg/reachability.py`) |
| T4 `lookup_compound_info` | Layer B `factual` (not in Sub-6) | HMDB sqlite → MoNA → PubChem |
| T5 `search_literature` | Layer E `literature` (not in Sub-6) | Europe PMC + PubMed |

For Sub-6 narratives the agent uses **all 5 tools** but the verifier only activates **3 of the 5 shared data sources** (RaMP, KEGG graph, curated HMDB pool). The asymmetry is intentional: literature and compound-info lookups are tools the agent uses for narrative construction, but verifier-side literature / factual round-trip requires spectrum-centric `IdentificationReport` which Sub-6 does not produce. The shared-database design means that under A4 / spectrum benchmarks the Sub-6 verifier path would extend naturally to cover the other 2 tools.

## Pipeline-level results (D3.5 N=3 reruns × 10-task subset, mean ± CI95)

| pipeline | supported % | contradicted % |
|---|---:|---:|
| single (baseline)                  | 13.98 ± 2.00 | 5.71 ± 0.58 |
| react (prevention only)            | 20.33 ± 6.48 | 3.81 ± 0.36 |
| **MetAgent** (closed loop + literature) | **25.70 ± 7.16** | **2.20 ± 1.31** |

MetAgent vs single baseline:
- supported: **+11.72 pp** (+84 % relative)
- contradicted: **−3.51 pp** (−61 % relative, 5.71 → 2.20)

Statistical significance (D3.5 N=3 CI):
- prevention (single → react), contradicted Δ: **significant**
- correction (react → MetAgent), contradicted Δ: **significant**
- marginal literature contribution: **not significant** (kept as a
  feature anyway — it costs nothing on tasks that don't trigger it)

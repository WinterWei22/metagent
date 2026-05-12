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
│   │       │      ┌──────────────┼──────────────────┐               │   │
│   │       │      ▼              ▼                  ▼               │   │
│   │  ┌────────┐ ┌────────┐ ┌──────────┐ ┌──────────────────┐       │   │
│   │  │ramp_   │ │pathway_│ │kegg_path │ │lookup_compound + │       │   │
│   │  │enrich  │ │member  │ │  (BFS)   │ │search_literature │       │   │
│   │  │(RaMP)  │ │ (RaMP) │ │ (KEGG)   │ │(HMDB / EuropePMC)│       │   │
│   │  └────────┘ └────────┘ └──────────┘ └──────────────────┘       │   │
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
              ┌───────────────────────────────┐
              │       VERIFIER  v9-PhaseC     │
              │  (verify_sub6, 11 layers)     │
              │                               │
              │  Stage 1: extract_claims (LLM)│
              │  Stage 2: classify (LLM)      │
              │  Stage 3: per-claim layers ─┐ │
              │     6a set_enrichment    ◄──┤ │
              │     6b driver_metabolite ◄──┤ │ pure DB
              │     6c biological_sub6   ◄──┤ │ (RaMP/KEGG/HMDB)
              │     6d pathway_relation  ◄──┘ │
              │  Stage 4: Layer D consistency │
              │           (LLM)               │
              │                               │
              │  + annotate_claims:           │
              │    claim_id + feedback_hint   │
              └────────────────┬──────────────┘
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

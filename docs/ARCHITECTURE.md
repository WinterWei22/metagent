# Architecture

This document is the first thing every developer (human or agent) reads before touching code. Read it end to end before opening a PR.

## The one-paragraph summary

MetAgent reframes metabolite identification from "output one molecule with a score" to "produce an auditable report". An LLM orchestrator plans a sequence of tool calls; each tool is a narrow-waist function with a locked Pydantic contract; a verifier agent closes the loop by forward-predicting spectra from candidates and validating every factual claim (PMIDs, database IDs, peak assignments) against external sources. The output is a structured report where every statement traces to evidence.

## Design principles

1. **Schemas are law.** Every tool has a Pydantic input model and a Pydantic output model. Schemas live in `schemas/`. Tools import from `schemas/`, never the other way around. Schema changes are treated as breaking — they require an explicit decision, not a drive-by edit.

2. **Tools are narrow.** One tool = one user-meaningful intent. Not one database query. `fetch_metabolite_info(hmdb_id)` returns everything about a metabolite in one call; we do not have `get_name`, `get_formula`, `get_inchi` as separate tools. Narrowness is judged from the LLM's perspective, not the database's.

3. **Tools are independent.** A tool must not import from another tool's package. Composition happens only in the orchestrator. Shared code goes in `schemas/` or a clearly-scoped `common/` module, never tool-to-tool.

4. **Every output is structured.** Tools return Pydantic objects serialisable to JSON. No free-form strings where a field would do. The LLM reads structure more reliably than prose.

5. **Every output carries an `explain` field.** A short natural-language explanation of what the tool concluded and why. The orchestrator uses these when assembling the final report, avoiding a second inference pass.

6. **Every factual claim is verifiable.** PMIDs must resolve in Europe PMC. KEGG/HMDB IDs must resolve in their respective databases. Peak assignments must cite a predicted fragment. The verifier enforces this before the report reaches the user.

## System shape

```
            ┌─────────────────────────────────────┐
 inputs ───►│          Orchestrator (LLM)         │◄──── tool registry
            └─────────┬───────────────────────────┘
                      │   plan, call, reflect
                      ▼
    ┌─────────────────────────────────────────────────┐
    │  Tools (independently deployable)               │
    │                                                 │
    │  spectrum_preprocess   fetch_metabolite_info    │
    │  library_search        pathway_context          │
    │  molecule_generate     literature_search        │
    │                        predict_spectrum         │
    └─────────────────────────────────────────────────┘
                      │
                      ▼
            ┌─────────────────────────────────────┐
            │       Verifier (LLM + checks)       │
            │  structural / citation / ID / agent │
            └─────────────┬───────────────────────┘
                          │
                          ▼
                   Audited report
```

## Input / output at the system boundary

**Input:** one MS/MS spectrum (m/z + intensity arrays), precursor m/z, ionization mode, adduct guess, and an optional free-text context block ("this is a human liver sample, looking for bile-acid-related metabolites").

**Output:** a structured `IdentificationReport` containing ranked candidates, per-peak explanations, biological context, literature support, and a verification trace. Format is JSON; the CLI also renders markdown.

## The 7 v0 tools

Full contracts live in `TOOL_CONTRACTS.md`. One-line summary:

| Tool | Purpose |
|---|---|
| `spectrum_preprocess` | Parse, clean, and normalise raw spectrum input |
| `library_search` | Retrieve candidate molecules from reference libraries |
| `molecule_generate` | De novo generate candidates when retrieval fails |
| `fetch_metabolite_info` | Pull structured metadata for a known metabolite |
| `pathway_context` | Return pathway membership, neighbours, co-occurrence evidence |
| `predict_spectrum` | Forward-predict MS/MS from a SMILES (verification backbone) |
| `literature_search` | Search PubMed/Europe PMC, return verifiable PMIDs |

## Parallel development model

v0 is built by multiple parallel agents working on disjoint tracks. The rules:

- One agent owns one track. Tracks are defined by `tools/<name>/` directories.
- An agent may only modify files inside its track directory and its test file under `tests/tool_tests/`.
- An agent may **read** `schemas/` but may not modify it. If a schema feels wrong, stop and raise it with the maintainer.
- An agent may not import from another tool's package. Cross-tool data flow goes through the orchestrator.
- Tests must pass without any other tool being implemented. Use fixtures in `tests/fixtures/`.

See `TOOL_CONTRACTS.md` for the track assignments.

## Non-negotiables

- No reading/writing outside the track directory without explicit approval.
- No modifying `schemas/` without explicit approval.
- No `pip install` into a shared environment — each tool declares its own deps.
- No remote network calls in unit tests. Mock or skip.
- No silent fallbacks. If a tool cannot fulfil its contract, it raises, it does not return fake data.

## Out of scope for v0

- Real-time stream processing
- Multi-sample functional analysis (mummichog, GSEA)
- Wet-lab experiment recommendation loop
- UI / web service (CLI and Python API only)
- Negative ion mode is optional; positive mode must work first
- Non-human organisms are optional; human (HMDB + KEGG hsa) must work first

## Who reads what

- **Every agent**, on session start: this file + `TOOL_CONTRACTS.md`
- **Tool implementers**: their row in `TOOL_CONTRACTS.md` + their `schemas/` file
- **Orchestrator implementer**: this file + all of `TOOL_CONTRACTS.md`
- **Verifier implementer**: this file + the `predict_spectrum` and `literature_search` rows

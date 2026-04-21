# MetAgent

An LLM multi-agent system for MS/MS-based metabolite identification with built-in self-verification.

## What it does

Given an MS/MS spectrum and optional context (organism, tissue, natural-language query, reference molecules), MetAgent returns an **auditable identification report** rather than a single top-1 guess. Each report contains:

- Ranked candidate structures with per-peak structural explanation
- Biological context grounded in metabolic pathways and co-occurrence
- Literature support with verifiable PubMed IDs
- A self-verification pass that catches hallucinated citations, database IDs, and peak assignments

The system is built as a small set of well-bounded tools orchestrated by an LLM. The tools are independently deployable, independently testable, and framework-agnostic (they expose plain Python signatures plus JSON contracts — any LLM with tool-use support can drive them).

## Status

v0. Under active development. The current milestone is the minimal 7-tool stack documented in `docs/TOOL_CONTRACTS.md`.

## Layout

```
metagent/
├── schemas/              # Pydantic contracts — single source of truth
├── tools/                # One subpackage per tool, independently installable
├── orchestrator/         # LLM routing, tool registration, report assembly
├── tests/
│   ├── fixtures/         # Shared test data (spectra, SMILES, IDs)
│   └── tool_tests/       # Per-tool unit tests
├── docker/               # Dockerfiles for tools with heavy/conflicting deps
└── docs/
    ├── ARCHITECTURE.md
    ├── TOOL_CONTRACTS.md
    └── SETUP.md
```

## Getting started (developer)

1. Read `docs/ARCHITECTURE.md` for the big picture.
2. If you are implementing a tool, read `docs/TOOL_CONTRACTS.md` for the exact I/O contract.
3. Use fixtures in `tests/fixtures/` — do not fetch remote data in unit tests.

## Non-goals for v0

- No wet-lab decision loop. v0 is pure in-silico.
- No real-time streaming. One spectrum in, one report out.
- No user interface. CLI and Python API only.
- No cross-sample functional analysis (mummichog/enrichment) — reserved for later.

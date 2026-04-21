# Track D: `fetch_metabolite_info` + `pathway_context`

**Prerequisite:** read `prompts/_preamble.md` first.

## Your scope

You own TWO tools under one track because they share data backends:

- **`fetch_metabolite_info`** — metadata lookup for a single metabolite by ID. Directory: `tools/metabolite_info/`.
- **`pathway_context`** — pathway membership, neighbors, co-occurrence plausibility. Directory: `tools/pathway_context/`.

Both tools are pure lookups against local databases. Neither calls an LLM. Both are trust anchors for the verifier — hallucination-free responses are mandatory.

## The specific task

### Tool 5: `fetch_metabolite_info`

Given an identifier (HMDB, KEGG, InChIKey, SMILES, name, or `auto`-detected), return a structured metadata bundle: name, formula, exact mass, cross-refs, tissue locations, disease associations.

Backend order of preference:
1. **HMDB local dump** (primary) — download, parse XML, cache to SQLite
2. **MoNA-HMDB compound metadata** (supplement) — use `common.mona_loader.iter_mona_records()` to pull ~7400 HMDB compounds' SMILES/InChIKey/formula/classification
3. **PubChem PUG-REST** (fallback) — for compounds not in HMDB

**Read the full contract:** `docs/TOOL_CONTRACTS.md` → "Tool 5: `fetch_metabolite_info`".

### Tool 6: `pathway_context`

Given a metabolite ID (and optional co-observed metabolite list), return:
- List of pathways it belongs to (with hit counts against the co-observed set)
- Upstream/downstream neighbors in the metabolic network
- Co-occurrence plausibility score
- A templated `plausibility_summary` paragraph (NOT LLM-generated — a template)

Backend: **RaMP-DB local deployment** (SQLite dump from https://github.com/ncats/RaMP-DB). This integrates KEGG, Reactome, SMPDB, WikiPathways.

**Read the full contract:** `docs/TOOL_CONTRACTS.md` → "Tool 6: `pathway_context`".

## What goes into which file

```
tools/metabolite_info/
├── tool.py             # fetch_metabolite_info(req) -> MetaboliteInfoResponse
├── hmdb_backend.py     # HMDB local SQLite lookup
├── pubchem_backend.py  # PubChem PUG-REST fallback
├── id_detect.py        # auto-detect HMDB vs KEGG vs InChIKey vs SMILES vs name
├── errors.py           # IdentifierFormatError
├── tool_description.md
├── requirements.txt
└── example.py

tools/pathway_context/
├── tool.py             # pathway_context(req) -> PathwayContextResponse
├── ramp_backend.py     # RaMP-DB SQLite queries
├── templates.py        # plausibility_summary templates
├── errors.py           # MetaboliteNotInNetworkError, RampUnavailableError
├── tool_description.md
├── requirements.txt
└── example.py

tests/tool_tests/test_metabolite_info.py
tests/tool_tests/test_pathway_context.py
```

## Setup responsibilities (do these early)

You need to stand up two local databases:

1. **HMDB dump:** Download human metabolome XML from https://hmdb.ca/downloads → parse to SQLite. Write a `tools/metabolite_info/build_hmdb_db.py` script so it's reproducible. Schema at minimum: `hmdb_id, primary_name, molecular_formula, exact_mass, smiles, inchikey, kegg_id, chebi_id, pubchem_cid, tissue_locations_json, disease_associations_json`.

2. **RaMP-DB dump:** Download latest SQLite from https://github.com/ncats/RaMP-DB/releases. This is ready-made; no ETL needed. Document the path via env var `METAGENT_RAMP_PATH`.

Both are in the ~1-2 GB range. Don't commit them — point to them via env vars. Document the setup in `docker/ramp_db.Dockerfile` and (if you write one) `docker/hmdb.Dockerfile`.

## Test cases for `fetch_metabolite_info`

Use `tests/fixtures/hmdb_ids/expected.json` as ground truth.

1. **HMDB0000122 (glucose)** returns `found=True` with `molecular_formula="C6H12O6"`, `exact_mass≈180.06`.
2. **HMDB9999999 (fake)** returns `found=False`, empty fields.
3. **auto-detect**: `"HMDB0000122"` → detected as HMDB; `"WQZGKKKJIJFFOK-GASJEMHNSA-N"` → InChIKey; `"OC[C@H]1OC(O)..."` → SMILES; `"glucose"` → name.
4. **Cross-ref round-trip:** fetching by KEGG ID `C00031` returns `cross_refs["hmdb"] == "HMDB0000122"`.
5. **Malformed input** `""` raises `IdentifierFormatError`.
6. **No hallucination:** when HMDB doesn't have a disease association for a compound, `disease_associations = []`, NOT a fake one.

## Test cases for `pathway_context`

Use `tests/fixtures/hmdb_ids/expected.json`. Pick central metabolites (pyruvate HMDB0000243, glucose HMDB0000122).

1. **Pyruvate returns multiple pathways** from multiple sources (kegg, reactome at minimum).
2. **Co-occurrence lifts the score:** glucose with `co_observed_ids=["HMDB0000243"]` (pyruvate, real neighbor) gets higher `cooccurrence_score` than with random HMDB IDs.
3. **`neighbour_depth=0`** returns empty neighbor lists.
4. **Orphan metabolite** raises `MetaboliteNotInNetworkError` (pick an HMDB ID known to be pathway-less, or construct a test stub).
5. **`plausibility_summary` is under 120 words and contains the metabolite's name.**
6. **No LLM calls:** patch `common.llm_client.chat` to fail loudly if called. Test must pass.

## Testing without the big DBs

Provide a tiny test SQLite for each in `tests/fixtures/`:
- `tests/fixtures/hmdb_mini.sqlite` — 10 compounds
- `tests/fixtures/ramp_mini.sqlite` — same 10 compounds with a few pathways

Real-DB tests: `@pytest.mark.integration`, skip if env vars unset.

## Dependencies you can use

- `sqlite3` (stdlib)
- `lxml` — HMDB XML parsing
- `requests` — PubChem PUG-REST
- `pydantic`
- `common.mona_loader` — for MoNA metadata supplement

## Explicit non-goals

- Do NOT call an LLM for `plausibility_summary`. Use a Python f-string template.
- Do NOT call a web API at query time. Everything local (except PubChem fallback — that one call is OK).
- Do NOT invent fields. Unknown = None or `[]`.
- Do NOT do cross-species pathway analysis. v0 is `organism="hsa"` only.

## Hallucination hazard reminder

These two tools feed the verifier as **trust anchors**. If `fetch_metabolite_info` returns a disease association that isn't in HMDB, the whole verification layer is broken. Every field you return must trace to a real database row. When in doubt, return None.

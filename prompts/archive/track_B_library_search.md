# Track B: `library_search`

**Prerequisite:** read `prompts/_preamble.md` first.

## Your scope

You own exactly one tool: **`library_search`**. Directory: `tools/library_search/`.

This tool takes a preprocessed spectrum (optionally plus a pre-filtered candidate pool) and returns the top-K library matches with modified-cosine scores.

## CRITICAL FIRST ACTION — ask the maintainer

Your tool wraps an in-house retrieval model. Before you write any code, you MUST ask the maintainer:

1. **Where is the in-house retrieval model code?** (path or git URL)
2. **What's the entry point?** (module path, class name, function signature)
3. **What does it expect as input?** (mz list, intensity list, encoded embedding, spectrum dict)
4. **What does it return?** (scores, embeddings, ranked candidates)
5. **What's the training data scope?** (so `tool_description.md` can tell the LLM when it's applicable)

Do NOT guess. Do NOT start coding. Wait for these answers.

If the maintainer says "not ready, use a mock for now," implement a simple fallback that calls `matchms` modified cosine against the GNPS pool only, and mark all tests that need the real model with `@pytest.mark.requires_inhouse_model`.

## The specific task (once you have model info)

Two code paths in one function:

**Path A — with candidate_pool provided** (preferred): only compare against spectra for the candidates in the pool. Fast, focused, high precision.

**Path B — no candidate_pool** (fallback): scan all GNPS v0-usable records. Slow, broad, useful when prefilter was skipped.

Both paths run two scorers in parallel:
1. Modified cosine via `matchms.similarity.ModifiedCosine` (baseline, works for any spectrum pair)
2. In-house retrieval model (learned, higher-quality ranking when applicable)

Combine the scores into a single normalized `[0, 1]` score per candidate. Exact fusion strategy: start with simple `max(normalized_modcos, normalized_inhouse)` — **document your choice in a block comment** so it can be reviewed.

**Read the full contract:** `docs/TOOL_CONTRACTS.md` → "Tool 3: `library_search`".

## What goes into which file

- `tools/library_search/tool.py` — main `library_search(req: LibrarySearchRequest) -> LibrarySearchResponse`
- `tools/library_search/model.py` — thin wrapper around the in-house retrieval model; owns imports from the user's code
- `tools/library_search/scoring.py` — modified-cosine + fusion logic
- `tools/library_search/calibration.json` — score calibration curve for in-house model; a stub OK for v0 but must be a real JSON file
- `tools/library_search/errors.py` — `LibraryUnavailableError`, `InHouseModelError`
- `tools/library_search/tool_description.md`
- `tools/library_search/requirements.txt` — `matchms`, model's own deps (torch etc.)
- `tools/library_search/example.py`
- `tests/tool_tests/test_library_search.py`

## Score normalization rule (non-negotiable)

Every returned `Candidate.score` MUST be in `[0, 1]`. Modified cosine natively is already in `[0, 1]` — use as-is. In-house model scores must be rescaled using `calibration.json`. If the calibration file doesn't exist on first run, compute a min-max scaling over 100 library entries, cache to file, and log a warning.

## Test cases you MUST cover

1. **Glucose fixture finds glucose in top 3:** use a manually-constructed `candidate_pool` containing glucose (via PrefilteredCandidate), run with glucose's fixture spectrum.
2. **Nonsensical spectrum returns empty:** a spectrum with 3 peaks at [10, 11, 12] m/z and a precursor of 12 → no match above `min_score=0.3`.
3. **top_k=1 returns at most 1:** sanity.
4. **Sorted descending:** validated by Pydantic (the schema enforces this), but add an explicit test.
5. **All scores in [0, 1]:** sanity assert on every returned candidate.
6. **Integration test** (marked `@pytest.mark.integration`, skipped if `METAGENT_GNPS_PATH` unset): load the real GNPS dump, query with a known compound, verify retrieval.

## Testing without the in-house model

Mock the in-house model behind an interface:
```python
class InHouseRetriever(Protocol):
    def score(self, query_peaks, candidate_peaks) -> float: ...
```
In tests, inject a mock that returns fixed scores. Real model goes through the same interface.

## Dependencies you can use

- `matchms` — for ModifiedCosine, Spectrum primitives
- `torch` — for the in-house model (if that's what it uses)
- `pydantic` — schema construction
- `common.gnps_loader` — to load the GNPS pool
- `common.rdkit_utils` — SMILES validation

## Explicit non-goals

- Do NOT implement `candidate_prefilter` logic here. Consume its output; don't replicate it.
- Do NOT call an LLM. This is a pure ML/signal-processing tool.
- Do NOT hit GNPS web APIs at query time. Always use the local dump.
- Do NOT mutate `PrefilteredCandidate` objects. Treat them as read-only input.

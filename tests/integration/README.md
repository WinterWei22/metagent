# Integration tests

End-to-end tests that exercise the `A1 → A2 → (B, C)` pipeline on the
three fixture spectra under `tests/fixtures/spectra/` plus a short
negative-case suite. Owned by the integration session (not any single
track), and layered ABOVE each track's own unit tests — a track's unit
suite is where bugs in that track are caught; the integration suite is
where **cross-tool contract drift** is caught.

## Files

- `conftest.py` — loads the three JSON fixtures, registers the
  `requires_*` markers, exposes `fixture_spectrum` (parametrised) and
  `all_fixtures`, and provides env-presence fixtures.
- `test_pipeline_e2e.py` — the test file. Two flavors of positive tests
  (mocked / real-pool) plus four negative tests.
- `__init__.py` — empty, makes the dir a Python package so intra-package
  imports work cleanly.

## Running the suite

```bash
# Mocked positives + negatives only (no env setup required). This is the
# default everyone runs and what CI executes on every merge to master.
pytest tests/integration/test_pipeline_e2e.py -v

# With a real PubChem-Lite SQLite DB wired — the TestRealPoolPipeline
# class unskips and verifies the ground-truth compound appears in the
# real A2 output for each fixture.
METAGENT_PUBCHEM_LITE_PATH=/path/to/pubchem_lite.sqlite \
    pytest tests/integration/test_pipeline_e2e.py -v

# Full — real prefilter pool + real in-house model. Required to exercise
# the "truth in top-10 union for >=2/3 fixtures" contract case.
METAGENT_PUBCHEM_LITE_PATH=/path/to/pubchem_lite.sqlite \
METAGENT_GNPS_PATH=/path/to/ALL_GNPS_NO_PROPOGATED.json \
METAGENT_MSCLIP_CKPT=/path/to/best.ckpt \
    pytest tests/integration/test_pipeline_e2e.py -v --integration
```

The `--integration` flag flips env-gated tests from "skip when absent"
to "fail when absent". Use it in any environment that is supposed to
have every resource configured — a silent skip there would mask a real
regression.

## Interpreting results

| Outcome | Meaning |
|---|---|
| All pass (no skips) | Everything is wired, real models returned correct answers. |
| Passes + 4 skips | Normal dev environment — mocked flavor is green, real-resource flavor skipped. This is the expected baseline. |
| Any `FAILED` under `TestMockedPipeline::*` | A track regressed something the mocked pipeline depends on (tool post-processing, Pydantic shape, explain templating). Route to the failing tool's track. |
| Any `FAILED` under `TestRealPoolPipeline::*` | A2's real PubChem-Lite index is not returning the truth compound for a fixture's precursor. Either the DB is stale, the fixture's precursor is wrong, or A2's adduct math drifted. |
| `test_realmodel_groundtruth_top10_union_across_fixtures` fails | End-to-end integration with real models missed >1 fixture. Check upstream data quality, model checkpoints, and whether the in-house retriever / generator are configured for positive-mode LC-MS/MS. |
| Any `FAILED` under the negative tests | Something unexpectedly *accepts* invalid input — usually a contract drift in error handling. |

## Test inventory

### `TestMockedPipeline` (12 passing — 4 tests × 3 fixtures)

Shape + range contracts. Uses hand-built A2-shaped pool +
`MockInHouseRetriever` + `MockGenerator`. Runs in any env.

- `test_preprocess_produces_valid_spectrum` — quality flag sane, base peak = 1.0.
- `test_mocked_library_search_returns_candidates_in_range` — ≥1 candidate, scores in [0, 1], sorted desc.
- `test_mocked_molecule_generate_returns_valid_smiles` — ≥1 candidate, every SMILES RDKit-parses, `source="generated"`.
- `test_mocked_groundtruth_present_in_top10_union` — truth compound InChIKey appears in the union.

### `TestRealPoolPipeline` (3 tests × 3 fixtures — skipped without env)

Marked `requires_pubchem_lite`.

- `test_prefilter_returns_at_least_one_candidate` — neutral mass math
  is right, truth compound's InChIKey is in the real pool.

### Cross-fixture integration

- `test_realmodel_groundtruth_top10_union_across_fixtures` — contract
  requirement: truth in top-10 union of `library_search + molecule_generate`
  for ≥ 2 of 3 fixtures. Marked `requires_inhouse_model`.

### Negatives (4 tests, always run)

- `test_pipeline_rejects_invalid_spectrum` — 2-peak input → `InvalidSpectrumError`.
- `test_pipeline_empty_prefilter_cascades_cleanly` — empty pool → empty library_search, molecule_generate without bonus.
- `test_pipeline_nonsense_spectrum_returns_empty_from_library_search` — unrelated spectrum → no candidate clears `min_score=0.3`.
- `test_prefilter_rejects_unknown_adduct` — unknown adduct → `InvalidAdductError`.

## Scope boundaries

The integration session does NOT:

- Modify any file under `tools/{spectrum_ops,candidate_prefilter,library_search,molecule_gen}/`
  or under `schemas/`, `common/`, `docs/`, `prompts/`. If a test fails
  because of a bug in one of those places, the fix lives in the owning
  track's session, not here.
- Write new tests into any track's `tests/tool_tests/test_<track>.py`.
  This directory (`tests/integration/`) is the one place where
  multi-tool tests are allowed.
- Call the MiniMax LLM. This integration layer is deterministic by design.

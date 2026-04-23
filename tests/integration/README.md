# Integration tests

End-to-end tests that exercise the `A1 → A2 → (B, C)` pipeline on the
three fixture spectra under `tests/fixtures/spectra/`, plus the **Track D
/ E verifier-readiness** suite added later by the D-E audit session (see
`reports/integration_report_de_2026-04-23.md`). Owned by the integration
session (not any single track), and layered ABOVE each track's own unit
tests — a track's unit suite is where bugs in that track are caught; the
integration suite is where **cross-tool contract drift** is caught.

## Files

- `conftest.py` — loads the three JSON fixtures, registers the
  `requires_*` markers (A/B/C + D/E), exposes `fixture_spectrum`
  (parametrised) and `all_fixtures`, env-presence fixtures, and the
  mini-SQLite builders (`build_mini_hmdb_sqlite`,
  `build_mini_ramp_sqlite`) + CFM mock stdout helper
  (`cfm_mock_body`) consumed by the D / E tests.
- `test_pipeline_e2e.py` — A / B / C pipeline tests.
- `test_facts_d.py` — verifier-readiness tests for `fetch_metabolite_info`
  and `pathway_context`. Seven tests, each in a mock class (default,
  always runs) and a real class (gated on `requires_hmdb_db` /
  `requires_ramp_db`).
- `test_verifier_e.py` — verifier-readiness tests for `predict_spectrum`.
  Seven tests with mock / real split on `requires_cfm_id`.
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

# Track D / E — verifier-readiness suites. Mock flavour always runs.
# Wire the three env vars to unlock the real-backend tests.
METAGENT_HMDB_PATH=/data/…/hmdb.sqlite \
METAGENT_RAMP_PATH=/data/…/ramp.sqlite \
METAGENT_CFM_URL=http://127.0.0.1:8088 \
    pytest tests/integration/test_facts_d.py tests/integration/test_verifier_e.py -v
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

### Track D (`test_facts_d.py`) — verifier-readiness

Seven assertions, each split into a `*Mock` and `*Real` class. Mock
always runs; real skips when `METAGENT_HMDB_PATH` or
`METAGENT_RAMP_PATH` is unset.

- `TestMetaboliteRoundtrip{Mock,Real}` — every fixture entry round-trips.
  Strict comparison in mock, flexible in real (InChIKey connectivity
  block, tolerant formula match for zwitterions; see audit report § D-1).
- `TestNonexistentId{Mock,Real}` — fake HMDB ID / fake InChIKey / empty
  identifier: no invention, either `found=False` or `IdentifierFormatError`.
- `TestCooccurrence{Mock,Real}` — `pathway_context` score with a real
  pathway co-member > score with a random / unresolvable ID.
- `TestOrphanMetabolite{Mock,Real}` — orphan / fake ID raises
  `MetaboliteNotInNetworkError` cleanly.
- `TestTemplatedSummary{Mock,Real}` — `common.llm_client.chat` tripwire
  is installed; five real queries produce plausibility_summary under
  120 words with no LLM-smell tokens.
- `TestKeggHmdbRoundtrip{Mock,Real}` — fetch by KEGG ID, follow the
  `hmdb` cross-ref back, same compound.
- `TestCrossToolInchikeyConsistency{Mock,Real}` — `inchikey(stored_smiles)`
  computed via `common.rdkit_utils` matches the stored InChIKey (connectivity
  block). The invariant under test is self-consistency within a single
  row — not whether stereochemistry is correct.

### Track E (`test_verifier_e.py`) — verifier-readiness

Seven assertions, mock (requests_mock + canned CFM stdout) and real
(gated on `requires_cfm_id`) paths. A third, marker-less
`TestPredictRejectsInvalidSmilesBeforeNetwork` runs regardless of the
shim — the whole point is that no HTTP call happens.

- `TestPredictRoundtrip{Mock,Real}::test_glucose` / `::test_caffeine` —
  canonical fragments present (glucose 163.06, caffeine 138.07).
- `TestPredictDeterminism{Mock,Real}` — two identical requests return
  byte-identical `predicted.mz`, `predicted.intensity`, and `per_energy`.
- `TestPredictRejectsInvalidSmilesBeforeNetwork` — parametrised over
  `banana`, `C1CC`, `[X]`, `SELECT * FROM t`; tripwire on
  `cfm_client.predict`; all raise `InvalidSmilesError` with `calls=[]`.
- `TestModelVersionPresent{Mock,Real}` — `model_version` non-empty on
  success; missing `model_version` maps to `CfmUnavailableError`.
- `TestTimeoutBounded` — `requests.exceptions.Timeout` from a mock
  adapter maps synchronously to `PredictionTimeoutError` under 2 s
  wall time.
- `TestSmilesFromFetch{Mock,Real}` — `fetch_metabolite_info(HMDB0000122).smiles`
  goes into `predict_spectrum` unmodified and produces a usable spectrum.

## Skip markers for Tracks D / E

| Marker | Required resource | Skip reason when absent |
|---|---|---|
| `requires_hmdb_db` | `METAGENT_HMDB_PATH` → existing SQLite file | `HMDB SQLite not found at METAGENT_HMDB_PATH; run tools/metabolite_info/build_hmdb_db.py first.` |
| `requires_ramp_db` | `METAGENT_RAMP_PATH` → existing SQLite file | `RaMP SQLite not found at METAGENT_RAMP_PATH` |
| `requires_cfm_id` | `METAGENT_CFM_URL` → running shim with `/healthz` = 200 | `CFM-ID shim unreachable at METAGENT_CFM_URL` |
| `requires_pubchem_online` | `METAGENT_ALLOW_PUBCHEM=1` | not currently used by any test (reserved for future PubChem-round-trip cases) |

Backend smoke diagnostic:

```bash
python scripts/audit_de.py
```

Exits 0 when all three real backends are green, 1 when any tool ran in
mock-only mode (with a per-tool reason), 2 on an unexpected crash.

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

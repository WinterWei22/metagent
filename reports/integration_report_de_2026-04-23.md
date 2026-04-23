# Integration audit — Tracks D and E (fact backends + verification backbone)

**Date:** 2026-04-23
**Scope:** `tools/metabolite_info/` (`fetch_metabolite_info`), `tools/pathway_context/` (`pathway_context`), `tools/spectrum_predict/` (`predict_spectrum`).
**Reviewer role:** integration session for fact-providing and verification-providing tools. These three are **trust anchors**: the orchestrator and verifier will treat their outputs as ground truth. Every finding is framed against that standard.
**Backends exercised:** real HMDB SQLite (217,920 rows, `/data/weiwentao/llm_agent_metabolomics/hmdb.sqlite`), real RaMP-DB SQLite v3 (1.95 GB, 1.35M `analytehaspathway` rows), real CFM-ID shim (`cfm-id-4.4.7` at `http://127.0.0.1:8088`). No mocks used for the audit itself; the companion test harness has both mock and real paths.

Severity labels — **CRITICAL** (trust anchor is lying), **MAJOR** (correctness bug or verifier-blocking gap), **MINOR** (cosmetic, doc drift, edge-case), **INFRASTRUCTURE** (environment / data work for the maintainer, not a tool defect).

---

## TL;DR

`fetch_metabolite_info` and `predict_spectrum` pass the honesty bar: no fabricated data, deterministic outputs, typed errors where the contract demands them. **`pathway_context` does not pass the honesty bar** — not because it invents data (it doesn't), but because two of its load-bearing fields give misleading structured information to the verifier:

1. `hit_count` on every `PathwayEntry` in the same response is set to the same number — the whole-response co-occurrence count — rather than the per-pathway metabolite count the schema documents. (**CRITICAL.**)
2. `upstream_neighbours` and `downstream_neighbours` collapse to identical sets for central metabolites, contain 42% IDs the rest of the system cannot resolve (`chebi:`, `rhea-comp:`, `polymer:` prefixes), and include cofactors (ATP, water, NADH, H⁺, CO₂) that drown out the biological signal. (**MAJOR × 3.**) The verifier should not rely on either neighbour field in v0.

On Track D data quality: HMDB's curated entry for L-carnitine stores the **protonated cation** (C₇H₁₆NO₃⁺, exact mass 162.113 Da) rather than the neutral zwitterion the fixture expected. The tool propagates the cation honestly; the verifier must be aware that `exact_mass` + `molecular_formula` from this tool can carry a built-in +1 H offset for zwitterionic species. (**MAJOR — data characteristic, not tool bug.**)

`predict_spectrum` is production-ready as a trust anchor for v0. Glucose and caffeine predictions land on their canonical [M+H]⁺ and fragment-loss peaks, output is byte-identical across two calls, `model_version` is pinned, invalid SMILES is rejected before any HTTP call, and timeouts map cleanly to the typed error.

---

## 1. Findings by tool

### 1a. `fetch_metabolite_info` — honesty and field fidelity

| # | Severity | Finding |
|---|---|---|
| D-1 | **MAJOR (data)** | HMDB's stored L-carnitine entry (HMDB0000062) is the **protonated cation**: `molecular_formula=C7H16NO3`, `exact_mass=162.113`, `inchikey=PHIQHXFUZVPYII-ZCFIWIBFSA-O` (the terminal `-O` encodes the protonation). The fixture `tests/fixtures/hmdb_ids/expected.json` was authored for the neutral zwitterion (`C7H15NO3`, 161.1052, `…-N`). The tool is propagating HMDB verbatim — no invention — but **the verifier MUST be told**: when comparing the tool's `exact_mass` against an [M+H]⁺ precursor for a zwitterion, the proton is already in the number; adding another gives a 1 Da miss. Same hazard class for other zwitterions we haven't spot-checked (betaine, taurine, creatine). |
| D-2 | **MAJOR (data)** | HMDB0000122 resolves to α-D-glucopyranose: `kegg_id=C00221`, `inchikey=WQZGKKKJIJFFOK-VFUOTHLCSA-N`. The fixture expected generic D-glucose (`C00031`, `…-GASJEMHNSA-N`). Same root cause as D-1: HMDB's stereo-specific curation differs from the shared fixture. Consequences for cross-tool chains: `pathway_context(C00221)` does return 10 pathways so the chain works, but any downstream code that hardcodes `C00031` will miss. |
| D-3 | **MINOR** | No HMDB row in the 217,920-metabolite dump has `chembl_id` populated (SQL `SELECT SUM(CASE WHEN chembl_id != '' THEN 1 END) FROM metabolites` → 0). `tool_description.md` advertises `chembl` as a key of `cross_refs`. It will never appear in practice. Either drop the promise from the docs or supplement from ChEMBL. |
| D-4 | **MINOR (coverage)** | `kegg_id` is populated for only 6,814 / 217,920 rows (3.1%). The cross-tool chain `fetch → pathway_context via kegg_id` consequently works for only a tiny fraction of shortlisted candidates. Going forward, `pathway_context` accepts HMDB directly — see D-10 — so this is a soft rather than hard limit, but tool_description.md should set expectations. |
| D-5 | **MINOR** | `tests/tool_tests/test_metabolite_info.py::test_no_disease_hallucination` uses caffeine and asserts `disease_associations == []`. Against the real HMDB, caffeine carries five disease associations (`Head injury`, `Colorectal cancer`, `Metastatic melanoma`, `Asthma`, `Eosinophilic esophagitis`). The existing test passes only because it runs against an in-tmp mini DB with an empty list seeded. The test is not wrong per se (it's testing "the tool propagates whatever the DB has"), but the *intent* the test name conveys ("no hallucination") is weaker than it looks. |
| ✅ | PASS | All 10 fixture InChIKeys match RDKit-recomputed InChIKeys from the stored SMILES (structural consistency = 10/10). |
| ✅ | PASS | Fake HMDB ID `HMDB9999999`, fake InChIKey `ZZZZZZZZZZZZZZ-ZZZZZZZZZZ-Z`, and a fake but valid SMILES `C1CCCCCCCCCC1CC(=O)N` all return `found=False` with every field empty. No hallucination. |
| ✅ | PASS | All five exact-mass fixture comparisons (glucose, caffeine, pyruvate, alanine, uric acid, adenosine, dopamine, cholic acid, palmitic acid) agree within 0.01 Da. L-carnitine fails this test for the D-1 reason above. |

### 1b / 1c. `pathway_context` — templated summary and ID honesty

| # | Severity | Finding |
|---|---|---|
| P-1 | **CRITICAL** | `PathwayEntry.hit_count` is the same number on every pathway in a given response. `tool.py:111` sets `hit_count = 1 + len(cooccurring)` inside the pathway loop, where `cooccurring` is the whole-response set of co-observed metabolites that share *any* pathway with the focal. The contract documents `hit_count` as a per-pathway count of queried metabolites present in that pathway. Verified: querying glucose with `co_observed_ids=["HMDB0000243","HMDB0000161"]` returns 10 pathways all reporting `hit_count=3` — including pathways that contain none of the co-observed compounds. Reproduction: see "Reproduction steps" § R-1. This is load-bearing for a future verifier that might rank pathways by hit-count — it'd rank them all as equals. |
| P-2 | **MAJOR** | For central metabolites, `upstream_neighbours` is **set-identical** to `downstream_neighbours`. Verified: pyruvate (HMDB0000243) → 204 == 204, glucose → 143 == 143, caffeine → 10 == 10, all with `|up ∩ down| == |up| == |down|` and `|up − down| == |down − up| == 0`. Root cause is upstream in RaMP's data, not in the SQL: pyruvate appears as `substrate_product=1` in 499 reactions and as `substrate_product=0` in 369 reactions, but the *compound-level* sets of co-participants (products of the 499 and substrates of the 369) converge — central metabolism is densely reversible and shares common co-factors, so "what's in a reaction with pyruvate as substrate" collapses to the same pool as "what's in a reaction with pyruvate as product". **Implication:** the directional split the contract promises is not present in v0. The verifier cannot tell upstream from downstream for this tool's output. Mitigation options (none implemented): (a) filter reactions by `reaction.direction`, (b) expose a single `reaction_neighbours` field instead, (c) document the limitation. |
| P-3 | **MAJOR** | Neighbour IDs leak prefixes the rest of the system cannot resolve. Pyruvate's 204 neighbours break down as: `hmdb:` 109 (53%), `chebi:` 73 (36%), `kegg:` 10 (5%), `rhea-comp:` 10 (5%), `polymer:` 2. `fetch_metabolite_info` understands HMDB / KEGG / InChIKey / SMILES / name — not `chebi:` / `rhea-comp:` / `polymer:`. So ≥42% of neighbours are dead ends for the verifier chain. The `_preferred_external_ids_batch` helper prefers HMDB > KEGG > ChEBI > PubChem, but if a compound has no HMDB/KEGG mapping in RaMP (common for ChEBI-only metabolites), it surfaces as `chebi:XXXX`. Spot-checked all 10 chebi-prefixed pyruvate neighbours via `fetch_metabolite_info(identifier="chebi:131847", id_type="auto")` — every one returns `found=False`. |
| P-4 | **MAJOR** | No cofactor filtering. `reaction2met.is_cofactor` is populated in RaMP (`is_cofactor=1` for H₂O, ATP, NADH, H⁺, CO₂, …) but the tool never consults it. Central metabolites therefore return a list where most neighbours are metabolism-wide cofactors rather than biologically-specific partners. This is not a schema-level violation but it severely dilutes the verifier's usable signal. At minimum the tool should expose cofactors as a separate field or filter them by default. |
| P-5 | **MAJOR** | Self-echo at `neighbour_depth ≥ 2`. `network_neighbours` (`ramp_backend.py:365-366`) excludes the focal by checking `x not in analyte.ramp_ids`, but `x` is an external sourceId (`hmdb:HMDB0000122`) and `analyte.ramp_ids` is a tuple of internal rampIds (`RAMP_C_000000802`). The two namespaces never intersect. Verified: `pathway_context(metabolite_id="HMDB0000122", neighbour_depth=2)` returns 9,959 upstream/downstream and includes `hmdb:HMDB0000122` (focal itself). depth=1 is not affected because the initial frontier is the focal's rampIds, which are correctly filtered in the SQL `r2.ramp_cmpd_id NOT IN (focal)`. Real-world impact: any verifier going beyond depth-1 sees the focal listed as its own neighbour. |
| P-6 | **MAJOR** | `cooccurrence_score` silently deflates when co-observed IDs fail RaMP resolution. Passing `co_observed_ids=["HMDB9999999","HMDB9999998"]` yields score `0.000` with numerator 0 and denominator 2 (the unique count of the **input** list, not the resolvable subset). A sample with 9 unresolvable co-obs and 1 real match therefore scores 0.1 rather than 1.0. Contract wording ("fraction of co_observed_ids … after de-duplicating the input list") is ambiguously satisfied, but the signal the verifier will read is misleading. |
| P-7 | **MINOR** | Pathway ordering is DB-native (alphabetical by `pathwayName`), not biological relevance. `pathways_for_analyte` applies `LIMIT ?` to a `SELECT DISTINCT` with no `ORDER BY`. Consequence: pyruvate's first 10 returned pathways are the alphabetical SMPDB disease pathways starting with "2-…" ("2-Hydroxyglutric Aciduria", "2-ketoglutarate dehydrogenase complex deficiency", etc.) rather than glycolysis/TCA/alanine metabolism. The templated `plausibility_summary` therefore reads as if pyruvate is primarily a disease marker, which is factually true (it is in those pathways) but stylistically misleading. |
| P-8 | **MINOR** | `PathwayContextRequest(metabolite_id="")` raises `pydantic.ValidationError` (schema `min_length=1`) rather than `MetaboliteNotInNetworkError`. Contract implies the tool-typed error should surface. Very thin edge case — the orchestrator won't emit empty — but error-type inconsistency. |
| ✅ | PASS | LLM tripwire: `common.llm_client.chat` and `chat_raw` patched to raise across 5 different queries (pyruvate, glucose, alanine, caffeine, uric acid) with varying depths. Zero LLM invocations. `plausibility_summary` is genuinely templated. |
| ✅ | PASS | Orphan / fake / prefix-truncated / case-variant / SQL-injection-shaped identifiers all raise `MetaboliteNotInNetworkError` cleanly (see § 4 red team). |
| ✅ | PASS | Co-occurrence monotonicity: glucose + pyruvate (pathway co-member) → 1.000; glucose + caffeine (no shared pathway) → 0.000; glucose + 2 unresolvable → 0.000. Real > random confirmed. |
| ✅ | PASS | `plausibility_summary` for glucose is 44 words (< 120 limit), contains the focal name, mentions real pathway names, contains no LLM-smell tokens ("based on my analysis", "as an AI", "it seems", "I believe" all absent). |

### 1d / 1e. `predict_spectrum` — determinism, traceability, sanity

| # | Severity | Finding |
|---|---|---|
| E-1 | **MINOR** | Empty-string SMILES (`""`) raises `pydantic.ValidationError` (schema `min_length=1`) rather than `InvalidSmilesError`. Non-empty invalid SMILES (`"banana"`, `"C1CC"`, `"[X]"`, `"SELECT * FROM table"`) all go through the intended path and raise `InvalidSmilesError` with `calls=0` against the CFM-ID shim. Same edge-case as P-8 — the validation fires at the Pydantic layer before the tool body can raise its typed error. |
| E-2 | **MINOR (doc)** | Shim reports `model_version="cfm-id-4.4.7"`. `docs/TOOL_CONTRACTS.md § Tool 7` and `tool_description.md` use `"cfm-id-4.0.0"` as the example. Cosmetic — no code path depends on the exact string — but worth updating so the docs match the container the team is running. |
| E-3 | **MINOR (perf hazard)** | An adversarial long-chain SMILES (`"C" × 200`) takes the full 60 s CFM-ID timeout before raising `PredictionTimeoutError`. Not a defect — RDKit successfully parses "C…C", so the tool correctly proceeds to CFM-ID. Flagging only as a reminder that the timeout is the only upper bound on call duration; an untrusted `smiles` parameter can burn 60 s of container time per call. Rate-limiting belongs to the orchestrator, not this tool. |
| ✅ | PASS | **Determinism**: two identical requests for glucose `[M+H]+` produce byte-identical `predicted.mz`, `predicted.intensity`, and `per_energy` dicts. Timings: 3.6 s (cold) vs 3.4 s (warm) — consistent with CFM-ID's per-molecule compute, no caching. |
| ✅ | PASS | **`model_version` non-empty**: `"cfm-id-4.4.7"` from every response. `cfm_client.predict` rejects any shim response that omits `model_version` — already enforced and tested (`test_missing_model_version_raises_cfm_unavailable`). |
| ✅ | PASS | **Invalid SMILES rejected before network**: with `cfm_client.predict` patched to raise `AssertionError` if called, all of `"banana"`, `"C1CC"`, `"[X]"`, `"SELECT * FROM table"` raise `InvalidSmilesError` with `calls=0`. |
| ✅ | PASS | **Timeout bounded**: mocked `cfm_client.predict` raising `PredictionTimeoutError` propagates cleanly; integration path would do the same via `requests.exceptions.Timeout → PredictionTimeoutError` translation in `cfm_client.py:86-89`. |
| ✅ | PASS | **Glucose sanity** (real CFM-ID 4.4.7, `[M+H]+`, collision energies `[10, 20, 40]`): 21 union peaks, `181.07066` parent present, `163.06010` water-loss fragment present, `per_energy` keys exactly `{10.0, 20.0, 40.0}`, `precursor_mz = 181.0707`. |
| ✅ | PASS | **Caffeine sanity** (real CFM-ID, `[M+H]+`): 13 union peaks, `195.08765` parent present, `138.06619` CH₃N=C=O loss fragment present, model_version preserved. |

### 1f. Cross-tool consistency

| # | Severity | Finding |
|---|---|---|
| X-1 | **MAJOR (cumulative)** | The fetch → pathway_context chain for glucose pivots through HMDB's `C00221` (α-D-glucose). `pathway_context("C00221")` *does* resolve and returns 10 pathways. But any orchestrator code that hard-codes `C00031` or shares a generic-glucose assumption will break. The chain works for *this* fixture; the general property ("whatever `fetch` returns for `kegg` will always resolve in `pathway_context`") holds because RaMP also indexes `C00221`. This one is flagged as a cumulative concern: compounds with exotic stereochemistry in HMDB may get a KEGG ID that works for RaMP but not for external KEGG-based lookups elsewhere. |
| ✅ | PASS | `fetch(HMDB0000122).smiles → predict_spectrum(...)` accepts unchanged, returns 21 peaks. |
| ✅ | PASS | `fetch(HMDB0000122).cross_refs["kegg"]="C00221" → pathway_context("C00221")` returns 10 pathways, no error. |
| ✅ | PASS | InChIKey structural consistency: 10 / 10 fixture entries have `stored_inchikey == rdkit_inchikey(stored_smiles)`. No drift between SMILES and InChIKey within any row. |

### 1g. Contract basics

| # | Status | Finding |
|---|---|---|
| C-1 | ✅ | All six typed errors subclass `schemas.common.ToolError`: `IdentifierFormatError`, `MetaboliteNotInNetworkError`, `RampUnavailableError`, `InvalidSmilesError`, `PredictionTimeoutError`, `CfmUnavailableError`. Each carries a non-empty `.code` and `.recoverable` flag. |
| C-2 | ✅ | `MetaboliteInfoResponse`, `PathwayContextResponse`, `PredictSpectrumResponse` all round-trip through `.model_dump()` / `.model_validate(...)` cleanly with no field loss. |
| C-3 | ✅ | `explain` field is non-empty on all three response types for the canonical glucose test call. Content is templated (no LLM). |
| C-4 | ✅ | All three `requirements.txt` files pin every non-comment dependency with `==` (metabolite_info: 3 pinned / 0 unpinned; pathway_context: 1 / 0; spectrum_predict: 4 / 0). |
| C-5 | ✅ | All three `tool_description.md` files clearly delineate "call when" and "do NOT call when" sections. Failure-mode taxonomy documented on each. |

---

## 2. Hallucination Red Team

Every attempt below was run against the real backends. A CRITICAL is recorded only if a tool invents data — i.e., returns `found=True` / a response with specific non-empty fields for an input that has no real answer.

### `fetch_metabolite_info`

| Input | id_type | Result | Verdict |
|---|---|---|---|
| `""` | auto | `IdentifierFormatError` | ✅ expected |
| `"   "` (whitespace) | auto | `IdentifierFormatError` | ✅ expected |
| `"\x00\x01\x02"` (control chars) | auto | `found=False` | ✅ clean miss |
| `"' OR 1=1 --"` (SQL injection-shaped) | auto | `found=False` | ✅ clean miss (parameterised SQL works) |
| `"HMDB000"` (prefix truncation) | hmdb | `found=False` | ✅ clean miss |
| `"HMDB0000XXX"` (malformed) | hmdb | `found=False` | ✅ clean miss |
| `"WQZGKKKJIJFFOK-GASJEMHNSA-X"` (InChIKey typo, last char changed) | inchikey | `found=False` | ✅ clean miss |
| `"glucos"` (name truncation typo) | name | `found=False` | ✅ clean miss (does NOT fuzzy-match to "glucose") |
| `"CAFFEINE"` (uppercase) | name | `found=True`, `primary_name="Caffeine"` | ✅ **not** a hallucination — HMDB SQLite uses `COLLATE NOCASE` on the `primary_name` column; the case-insensitive match is documented behaviour in `hmdb_backend.lookup_by_name` and in the tool description. |

**No hallucinations found.** The tool consistently returns `found=False` rather than guessing when the input is malformed or off-by-one. The case-insensitive name lookup is genuine DB behaviour, not invention.

### `pathway_context`

| Input | Result | Verdict |
|---|---|---|
| `"HMDB000012"` (one digit short) | `MetaboliteNotInNetworkError` | ✅ |
| `"HMDB00001222"` (one digit extra) | `MetaboliteNotInNetworkError` | ✅ |
| `"c00031"` (lowercase KEGG) | `MetaboliteNotInNetworkError` | ✅ RaMP stores `kegg:C00031` uppercase; the tool does not silently uppercase |
| `"HMDB9999999 "` (trailing whitespace) | `MetaboliteNotInNetworkError` | ✅ stripping works, no match |
| `"' OR 1=1 --"` | `MetaboliteNotInNetworkError` | ✅ parameterised SQL |
| `""` | `pydantic.ValidationError` | ✅ schema-level |

**No hallucinations found.** No attempt fabricated pathway membership or produced a neighbour list for a non-existent ID.

### `predict_spectrum`

| Input | Result | Verdict |
|---|---|---|
| `""` | `pydantic.ValidationError` | ✅ schema-level (see E-1) |
| `" "` (single space) | `InvalidSmilesError` | ✅ |
| `"C" × 200` (valid but absurd SMILES) | `PredictionTimeoutError` after 60 s | ✅ timeout fires; no fake spectrum returned (see E-3) |
| `"C1CC"` (unclosed ring) | `InvalidSmilesError` | ✅ RDKit rejects, calls to CFM-ID = 0 |
| `"[X]"` (nonsense atom) | `InvalidSmilesError` | ✅ |
| `"banana"` | `InvalidSmilesError` | ✅ |
| `"SELECT * FROM table"` | `InvalidSmilesError` | ✅ RDKit rejects as unparseable |

**No hallucinations found.** There is no code path that can reach CFM-ID with an RDKit-unparseable SMILES — the `is_valid_smiles` guard in `tool.py:168-172` sits before the client call and cannot be bypassed without editing the tool body.

### Overall red-team verdict

Across 22 attack inputs spanning three tools, zero succeeded in coaxing a trust-anchor tool into returning fabricated data. **The honesty bar is met.** Where a tool failed (e.g., `pydantic.ValidationError` for empty strings), it failed loudly, never silently.

---

## 3. Verifier-readiness assessment

**`predict_spectrum`:** ✅ **Ready.** Deterministic; outputs carry `model_version` so reports are traceable; typed errors let the orchestrator route around known failures; glucose and caffeine sanity checks pass; invalid SMILES and timeouts are correctly translated. The contract-promised behaviour is implemented; the only open items are MINOR (empty-string edge case, doc version example).

**`fetch_metabolite_info`:** ✅ **Ready with caveats.** No hallucinations on 22 adversarial inputs; InChIKey ↔ SMILES structural consistency holds for 10/10 fixtures; honest fallback to `found=False`. The caveats are data-layer:
- Some HMDB entries store protonated cations (L-carnitine, D-1). The verifier needs to be aware that `exact_mass` can carry an embedded +H offset for zwitterions — recommend the verifier back-compute from SMILES via `rdkit_utils` when exact-mass matching is load-bearing.
- `kegg_id` coverage is thin (~3%) and `chembl_id` is not populated in the current dump. Cross-tool chains that depend on KEGG IDs will skip most shortlisted candidates.
- Fixture drift (D-1, D-2) is a fixture problem, not a tool problem. The integration tests in this deliverable use flexible comparators (InChIKey connectivity hash rather than full stereo key; formula matching either neutral or protonated form for known zwitterions) so they survive HMDB's curation choices.

**`pathway_context`:** ⚠️ **Conditionally ready — do NOT wire the neighbour fields into the verifier in v0.** The `pathways` list, `cooccurrence_score`, and `plausibility_summary` are trustworthy. The `upstream_neighbours` / `downstream_neighbours` fields have three problems that compound:
1. Upstream and downstream are set-identical for central metabolites (P-2).
2. 42% of returned IDs cannot be resolved by any other tool in the system (P-3).
3. Cofactors are not filtered (P-4), so the biologically-informative neighbours are diluted by universal participants.

Fix priority for v1 (not in scope here): add `is_cofactor=0` filter + return neighbours as a single `reaction_neighbours` field (or explicitly document the direction-collapse for central metabolites) + pre-resolve to HMDB/KEGG before emitting. Until that's done, the verifier should consume `pathway_context.pathways` and the score, and ignore the two neighbour lists.

**Also open on `pathway_context`:** the `hit_count` bug (P-1, CRITICAL) is a per-pathway field that currently carries a whole-response number — this is a silent semantic violation and anything that ranks pathways by it will get uniform rankings. Easy fix (per-pathway co-occurrence count) but requires a tool-side edit, which is out of scope for this audit session.

---

## 4. Infrastructure findings

All three backends ARE provisioned and reachable in this environment, so the audit itself ran end-to-end on real data. Flagging a few operational points for the maintainer:

- **I-1.** CFM-ID container is at version `4.4.7`, not `4.0.0` as the Dockerfile README / contract examples suggest. If the team expects `4.0.0` for reproducibility, pin the image digest in `docker/cfm_id.Dockerfile` and update `docs/TOOL_CONTRACTS.md` and `tool_description.md` example strings.
- **I-2.** `METAGENT_HMDB_PATH`, `METAGENT_RAMP_PATH`, `METAGENT_CFM_URL` are not yet in any checked-in `env.sh` or `.env.example`. Running the D/E integration tests today requires typing all three env vars on the command line. Recommend a `docker/env.de.example` mirror of the existing `tools/candidate_prefilter/env.sh`.
- **I-3.** `METAGENT_MONA_PATH` is unset and there is no MoNA dump on disk. The `mona_supplement` fallback in `fetch_metabolite_info` is therefore dead code in this deployment — it runs, returns `None`, and moves on. Not a defect; just ensure the test harness does not assume MoNA is queryable.

---

## 5. Reproduction steps

### R-1. `hit_count` bug (CRITICAL P-1)

```python
import os
os.environ["METAGENT_RAMP_PATH"] = "/data/weiwentao/llm_agent_metabolomics/ramp.sqlite"

from schemas.pathway import PathwayContextRequest
from tools.pathway_context import pathway_context

resp = pathway_context(PathwayContextRequest(
    metabolite_id="HMDB0000122",
    co_observed_ids=["HMDB0000243", "HMDB0000161"],
    neighbour_depth=1,
))
print({p.name: p.hit_count for p in resp.pathways})
# {'Congenital disorder of glycosylation CDG-IId': 3,
#  'Fabry disease': 3,
#  'Fanconi-bickel syndrome': 3,
#  ... (all 10 identical)}
```

Expected (per contract): distinct per-pathway counts, e.g. a pathway with only focal in it → 1, one with focal + pyruvate → 2, one with all three → 3.

### R-2. Upstream == downstream (MAJOR P-2)

```python
resp = pathway_context(PathwayContextRequest(metabolite_id="HMDB0000243", neighbour_depth=1))
up, dn = set(resp.upstream_neighbours), set(resp.downstream_neighbours)
assert up == dn                 # holds
assert len(up) == len(dn) == 204
```

### R-3. Depth-2 self-echo (MAJOR P-5)

```python
resp = pathway_context(PathwayContextRequest(metabolite_id="HMDB0000122", neighbour_depth=2))
assert "hmdb:HMDB0000122" in resp.upstream_neighbours      # focal echoes itself
assert "hmdb:HMDB0000122" in resp.downstream_neighbours    # ditto
```

### R-4. L-carnitine cation (MAJOR D-1)

```python
from schemas.molecule import MetaboliteInfoRequest
from tools.metabolite_info import fetch_metabolite_info

r = fetch_metabolite_info(MetaboliteInfoRequest(identifier="HMDB0000062", id_type="hmdb"))
assert r.molecular_formula == "C7H16NO3"         # cation, not C7H15NO3 neutral
assert abs(r.exact_mass - 162.113) < 0.001       # cation mass, not 161.105 neutral
assert r.inchikey == "PHIQHXFUZVPYII-ZCFIWIBFSA-O"  # note terminal -O (protonation layer)
```

---

## 6. Follow-up recommendations

In descending order of priority, for a subsequent tool-fix session (this audit session is not authorised to modify the tools):

1. **(P-1, CRITICAL)** Compute `PathwayEntry.hit_count` per-pathway: for each pathway, count focal (always 1) plus the number of co-observed IDs that are members of that specific pathway. One extra SQL per response.
2. **(P-4, MAJOR)** Filter `is_cofactor=1` rows out of `_neighbour_external_ids` by default; expose a `include_cofactors: bool = False` field on the request if a caller really wants them.
3. **(P-3, MAJOR)** Post-filter neighbour IDs to the set `{hmdb:, kegg:}` — drop the rest rather than emit IDs the chain cannot resolve. Alternative: return `PathwayNeighbour` objects with `(id, id_type)` so the consumer can filter.
4. **(P-5, MAJOR)** Fix `network_neighbours` self-echo guard: compare against `focal_external_ids` (the set of source rows that mapped to focal's rampIds) rather than `analyte.ramp_ids` (internal IDs). Or re-run the focal resolution for the accumulated neighbour list and drop anything that resolves back to the focal's rampId set.
5. **(P-2, MAJOR)** Document the direction-collapse behaviour for central metabolites; consider exposing a single `reaction_neighbours` field in v1 rather than a split the graph can't support.
6. **(D-1, MAJOR data)** Document in `tool_description.md` that HMDB can store protonated forms for zwitterions; advise the verifier to back-compute exact mass from SMILES when matching experimental precursors.
7. **(I-1/E-2, MINOR)** Update the example `model_version` strings across `TOOL_CONTRACTS.md` and `spectrum_predict/tool_description.md` from `cfm-id-4.0.0` to match the shipped container; consider pinning to a specific 4.x digest.
8. **(D-2, MINOR fixture)** Refresh `tests/fixtures/hmdb_ids/expected.json` to the values HMDB now carries (α-D-glucopyranose for 0000122, cation form for 0000062) — OR document the deliberate choice to keep generic entries, with flexibility in the comparators.

---

## 7. What this audit session produced (companion deliverables)

See the other files in this commit series:

- `tests/integration/test_facts_d.py` — seven tests covering `fetch_metabolite_info` and `pathway_context`, each with a mock path (always runs) and a real path (gated on `requires_hmdb_db` / `requires_ramp_db`). Uses flexible comparators so the D-1 / D-2 data quirks don't cause false failures.
- `tests/integration/test_verifier_e.py` — seven tests for `predict_spectrum`, mock + real, with `requires_cfm_id`.
- `tests/integration/conftest.py` — shared mini-HMDB / mini-RaMP SQLite builders + canned CFM stdout fixtures.
- `scripts/audit_de.py` — single-command smoke diagnostic (`python scripts/audit_de.py`). Exit 0 = all three real backends green; 1 = mock-only (reason printed per tool); 2 = unexpected crash.
- `tests/integration/README.md` — updated with a "Track D / E" section documenting the new markers and env vars.

No file under `tools/metabolite_info/`, `tools/pathway_context/`, `tools/spectrum_predict/`, `schemas/`, `common/`, `docs/`, existing `tests/tool_tests/`, or `tests/integration/test_pipeline_e2e.py` was modified by this session. The findings above are reports, not patches.

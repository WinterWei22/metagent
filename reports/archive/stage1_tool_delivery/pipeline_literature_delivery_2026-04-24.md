# Pipeline Q1 + Q2 — fingerprint fusion & literature loop delivery

- **Date:** 2026-04-24
- **Branch:** `integration-day1`
- **Scope:** `scripts/run_full_pipeline.py`, `schemas/report.py`,
  `orchestrator/formatter.py`, `verifier/`
- **Predecessor:** Track V verifier v0 delivery
  (`reports/verifier_v0_delivery_2026-04-24.md`)
- **LLM env:** `metagent-llm` (python 3.11, openai==0.28.1)
- **Pipeline env:** `diffms` (rdkit, matchms, MS-BART, SIRIUS adapter)

---

## 1. What changed and why

Two gaps surfaced after Track V landed:

**Q1 — `de novo` molecule generation never used fingerprint fusion.** The
pipeline shipped with `SiriusFingerprinter` as the default, which shells
out to a `sirius` binary. None of the v0 fixture environments have
SIRIUS installed, so Stage 3b silently degraded to `n_generated: 0` on
every run (visible in the O1 delivery report's three fixture warnings).
The class `CandidateFusionFingerprinter` — which mirrors
`MS-BART/preprocess/create_fused_fps.py` — was implemented in
`tools/molecule_gen/fingerprint.py` but **had no caller**.

**Q2 — Track F (literature) was UI-only.** `tools/literature/`,
`LiteratureSearchRequest`, `literature_search()` all existed and worked,
but `grep -r literature_search scripts/ orchestrator/ verifier/` returned
empty. The Track F output never reached the LLM, never reached the
verifier, and was not part of the analysis loop. The UI panel in
`ui/app.py` called the tool from a button — that's it.

This delivery wires both gaps end-to-end without breaking the existing
Track V verifier contract.

---

## 2. New pipeline shape

```
A1 spectrum_preprocess  →  A2 candidate_prefilter
                           ↓ pool
B  library_search   ┐
                    ├→ merge + dedupe
C  molecule_generate┘   ← fingerprint NOW comes from
                          CandidateFusionFingerprinter(library_resp.candidates)
                          NOT from SIRIUS [Q1]
                          ↓ top_k
D1 fetch_metabolite_info  }
D2 pathway_context        } per-candidate enrichment
E  predict_spectrum       }
                          ↓ sort by evidence_score
F  literature_search      } per top-N (default N=3) [Q2 NEW Stage 7]
                          ↓ records → CandidateReport.literature_records
                          ↓
IdentificationReport (now with .literature_records on each candidate)
                          ↓
orchestrator.formatter    ← renders Literature subsection per candidate
                          ↓
LLM (orchestrator.naive)  ← sees PMID/title/journal/year + abstract head
                          ↓
verifier.agent            ← Layer E literature added; LITERATURE claim type
                          ↓
VerifiedIdentification
```

---

## 3. Knobs — CLI and env

| flag | env var | default | values | effect |
|---|---|---|---|---|
| `--fp-strategy` | `METAGENT_FP_STRATEGY` | `topn_60` | `sirius`, `retrieved_only_60`, `retrieved_only_80`, `topn_60`, `topn_80` | Stage 3b fingerprint source. `sirius` = legacy path; the four fusion modes mirror MS-BART training settings |
| `--literature-top-n` | `METAGENT_LITERATURE_TOP_N` | `3` | `0` (disable) ↑ | Number of top-ranked candidates to enrich with `literature_search` |

The `topn_60` default matches MS-BART's training-time fused-fps protocol;
`retrieved_only_*` skips the MIST base term (use when no SIRIUS-style
upstream fingerprint is available). `--literature-top-n 0` skips Stage 7
entirely with a warning, useful for fast / offline runs.

---

## 4. Live end-to-end results (glucose_pos, real backends)

Single live run on 2026-04-24 against:
- HMDB sqlite (`/data/.../hmdb.sqlite`)
- RaMP sqlite (`/data/.../ramp.sqlite`)
- CFM-ID server (`http://127.0.0.1:8088`, healthy)
- MS-BART checkpoint (default path, present)
- Europe PMC (live network)
- MiniMax-M2.7 (orchestrator + verifier)

### 4.1 Pipeline (~5 min)

| metric | value |
|---|---:|
| `n_prefilter_candidates` | 206 |
| `n_library_candidates` | 5 |
| **`n_generated_candidates`** (Q1) | **5** ← MS-BART ran via fp fusion |
| Top-1 candidate | `D-Gulose` (HMDB resolved name; library tag was `Galactose`) |
| Stage 7 calls (Q2) | 3 (top-3) |
| Stage 7 successful records returned | Galactose 3 from Europe PMC (after one transient SSL retry); two long IUPAC names 0 hits each (expected — Europe PMC does not index IUPAC stereo-names) |
| Pipeline warnings | preprocess sparse · library 5 · molecule_generate 5 final · D1/D2 partial degradation (typical for de-novo SMILES not in HMDB) · literature_search 1 SSL transient |

### 4.2 Orchestrator (1 LLM call, ~22 s)

Formatter rendered the Literature subsection for D-Gulose with 3 PMID
records. LLM verbatim quote (full output in
`/tmp/q2_e2e/llm_calls.jsonl`):

> "Literature connections appear tangential (drought stress, metabolic
> tracing studies)."

The LLM **read the abstract heads and judged relevance**. It did NOT
emit any specific PMID — paraphrased instead. (See §5 — design choice.)

### 4.3 Verifier (7 LLM calls, ~9 min)

| metric | value |
|---|---:|
| `overall_verdict` | `partially_verified` |
| `llm_call_count` | 7 (within ceiling) |
| v1 claims | 48 |
| v2 claims | 21 (Stage 4 rewrite collapsed redundancies) |
| v1 verdict distribution | supported 13 · unsupported 26 · unverifiable_v0 9 · contradicted 0 |
| v1 claim_type distribution | grounded 24 · biological 17 · consistency 5 · factual 2 · **literature 0** |

**Zero CONTRADICTED v1 claims** — this run's LLM output did not contain
H1-style hallucinations. Real-world variance, not a verifier failure.

**Zero LITERATURE-type claims** — the LLM paraphrased rather than
citing; classifier requires PMID/DOI/`pubmed` anchor (§5 below). Layer E
is wired and dispatch-tested but did not activate on this seed.

---

## 5. Findings & known limitations — read these before extending

### 5.1 Q1 — fingerprint fusion behaviour

* **MS-BART checkpoint location.** `tools/molecule_gen/model.py` reads
  `METAGENT_MSBART_CKPT` env var, falling back to a hard-coded default
  path. If the checkpoint is missing, Stage 3b raises `ModelLoadError`
  caught as `ToolError` and degrades cleanly to `n_generated=0` with a
  warning. Test the path before benchmarking — silent degradation hides
  itself in the warnings list, not in the candidates count if you also
  have library hits.
* **Strategy semantics.** `topn_60` (default) does
  `score[bit] = mist_weight * base_binary[bit] + retrieved_vote[bit]`
  and takes the top-60 bits. `retrieved_only_*` drops the MIST term —
  use these when no upstream MIST/CSI fingerprint is available, which
  is currently always (we never feed `base_fingerprint`). For the
  current pipeline `topn_*` and `retrieved_only_*` produce identical
  bit lists; the distinction matters only when MIST is wired in.
* **Why fp fusion changed top-1.** O1 with SIRIUS missing showed
  D-Gulose top with no MS-BART contribution; Q1's run with MS-BART
  contributing 5 candidates produced an identical top-1 (after HMDB
  name resolution) but a richer candidate field. The fusion path does
  not replace library hits — it complements them.

### 5.2 Q2 — literature tangentiality is the dominant failure mode

* **Europe PMC indexes papers, not chemistry.** A query like `"Galactose
  mass spectrometry metabolite"` returns the 3 papers most recent and
  most-keyword-matched, which on 2026-04-24 happened to be plant
  drought stress, blood mononuclear isotope tracing, and liver
  metabolomics. None are about galactose-the-sugar's mass spectrum or
  chemistry. The verifier cannot judge "is this paper actually relevant
  to the candidate?" — it can only judge "does this PMID exist?". The
  current contract is honest about that limit.
* **Long IUPAC stereonames return 0 hits.** Candidates whose name is
  `(3R,4S,5S,6R)-6-(hydroxymethyl)oxane-2,3,4,5-tetrol` give Europe
  PMC nothing to match. The pipeline writes `literature_records: []`
  for them with no error and no warning — that's success-with-zero-
  results, not degradation.
* **Nameless candidates skip Stage 7.** When `candidate.name is None`,
  `_safe_literature_search` returns `([], <skip-note>)` rather than
  searching by raw SMILES (which produces noise in Europe PMC's
  free-text scoring). The skip note lands in `candidate.notes`.
* **Europe PMC SSL transient in diffms env.** One in N pipeline runs
  produces `SSLZeroReturnError` for a query that succeeds in a
  standalone Python process. Standalone retry of the failing query
  (3/3 trials at both `max_results=3` and `max_results=5`) succeeded.
  Best-guess root cause: matchms / matchms-related TLS state from
  earlier CFM-ID interaction in the same process. Workaround: rerun.
  Real fix: investigate session reuse in `tools/literature/` for
  diffms env compatibility.

### 5.3 Verifier — Layer E activation requires PMID/DOI anchor

* **Classifier rule (locked in `verifier/claim_classifier.py`):**
  ```python
  _LITERATURE_RE = re.compile(r"\b(?:PMID|pubmed|doi)[:\s]*\S", re.IGNORECASE)
  _BARE_DOI_RE   = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")
  ```
  A claim is routed to LITERATURE iff it contains one of these
  patterns. "Literature connections appear tangential" does NOT match
  — it's routed to GROUNDED/BIOLOGICAL by the other rules and falls
  out as UNSUPPORTED.
* **Source-first vs round-trip.** Layer E first scans
  `candidate.literature_records[*].pmid` / `.doi` for the claimed ID.
  Hit → SUPPORTED with `source_field=candidates[i].literature_records[j].pmid`.
  Miss → falls through to Europe PMC round-trip. Empty round-trip →
  CONTRADICTED (the LLM made up a PMID).
* **Title-mismatch is NOT v0.** A claim that says
  "PMID 12345 reports glucose chemistry" is verified as SUPPORTED
  whenever PMID 12345 resolves, regardless of whether the actual
  paper is about glucose. Fuzzy title-match without a chemistry-LLM
  produces too many false positives. v1 work.

### 5.4 Empirical: real LLM tangentiality dominates Layer E activation

In the live e2e run the LLM correctly judged the literature
non-relevant and paraphrased without citing. **This is desirable
behaviour** — fabricated citations are the failure mode Layer E
should catch, and an LLM that doesn't fabricate gives Layer E
nothing to do. To stress-test Layer E, the next session should:
- inject a known-bad PMID into source `literature_records` to
  prompt the LLM to cite it, OR
- measure fabrication rate over a larger fixture set and adjust
  the orchestrator prompt only if needed.

---

## 6. How to extend the verifier (Type-6 layer template)

For a future contributor adding a new claim type — say, "spectral
peak claim" verified against `experimental_spectrum.mz` — follow this
template, which factors out of Layers A/B/C/E:

### Step 1: declare the type
```python
# verifier/schemas.py
class ClaimType(str, Enum):
    ...
    SPECTRAL = "spectral_claim"
    """Type 6 — verified against experimental_spectrum peaks."""
```

### Step 2: add the layer
Create `verifier/layers/spectral.py` exposing a single
`verify_spectral(claim, source_report, *, fetcher=None) -> VerifiedClaim`.
For tool-backed layers, declare `Fetcher = Callable[[str], <Response>]`
at module top and accept it as a kwarg with `None` default. Lazy-import
the real tool inside `_default_fetcher` so test runs don't pay the
import cost. Layer A/B/C/E are all instances of this pattern.

Verdict semantics — read the layer files for examples:
* SUPPORTED: a positive match in source or via tool round-trip.
* CONTRADICTED: source actively disagrees (different value, ID does
  not resolve when claim names a subject).
* UNSUPPORTED: no anchor for verification (field shape mismatch,
  hallucinated number, ID with no subject naming).
* UNVERIFIABLE_V0: known limitation (backend coverage gap, no v0
  resolver, degraded source). Per Track V: never CONTRADICTED on a
  coverage gap. (See `verifier/layers/factual.py` for the H5 + CID
  precedent.)
* ERROR: tool raised. Surface it; do not retry.

### Step 3: classifier rule
Edit `verifier/claim_classifier.py`:
```python
_SPECTRAL_RE = re.compile(r"\b(?:peak\s+(?:at|near)|m/z\s+\d+\.\d+)\b",
                          re.IGNORECASE)

def _rule_classify(claim_text):
    if _SPECTRAL_RE.search(claim_text):
        return ClaimType.SPECTRAL
    # ... existing precedence ...
```

Update `_TYPE_LITERALS` so the LLM fallback can also return the new
type by name. Update
`verifier/prompts/classify_ambiguous.py`'s instruction list to
describe the new type for the fallback LLM.

### Step 4: agent dispatch
Edit `verifier/agent.py`:
```python
from verifier.layers import spectral as layer_f

def _verify_per_claim(...):
    ...
    elif c.claim_type == ClaimType.SPECTRAL:
        out.append(layer_f.verify_spectral(c, source_report))
    ...
```

If the layer takes a fetcher, add a `spectral_fetcher` kwarg to
`verify()` and thread it through (mirror how `fetcher` and
`literature_fetcher` are wired today).

### Step 5: tests
* `tests/test_verifier/test_layer_spectral.py` — unit, mock-backed.
  Cover SUPPORTED / CONTRADICTED / UNSUPPORTED / UNVERIFIABLE_V0 /
  ERROR (tool-raised).
* `tests/test_verifier/test_claim_classifier.py` — add parametrised
  cases for the new regex rule.
* `tests/test_verifier/test_agent_real_o1_outputs.py` — add at least
  one acceptance test using the existing `glucose_report` fixture.
* `tests/integration/test_verifier_e2e.py` — IF the new layer hits a
  real backend, add a gated live test. Otherwise the unit tests are
  sufficient.

### Step 6: budget
A tool-backed layer that only hits its source-first path costs zero
LLM calls. A layer that adds an LLM call must extend
`VerifiedIdentification.llm_call_count`'s docstring ceiling and any
test asserting on the budget. Stage 4's re-verification re-runs all
A/B/C/E layers but Layer D consistency runs once per pass (twice
total in worst case) — current ceiling is 7, see Track V delivery
§5 for the math.

---

## 7. How to extend literature verification specifically

### 7.1 Title-mismatch detection (next obvious step)
The current Layer E only checks ID existence. To catch
"PMID 12345 reports glucose chemistry" when PMID 12345 is actually
about something else:
* In `_verify_via_roundtrip_pmid`, after `resp.records[0]`, extract
  the claim's stated topic (parse claim_text) and fuzzy-match
  against `rec.title` and `rec.abstract`.
* Below some threshold → CONTRADICTED with `correction=rec.title`.
* Above threshold → SUPPORTED.
* Use Levenshtein, embedding cosine, or a small LLM call — your
  call. An LLM call would push the budget ceiling and need explicit
  documentation.

### 7.2 Smarter literature query
Current query is `f"{candidate.name} mass spectrometry metabolite"`.
Add the candidate's:
* `molecular_formula` to disambiguate isomers
* `cross_refs.get('hmdb')` to anchor to a real metabolite — Europe
  PMC indexes HMDB IDs in some records
* For zwitterion candidates, add `OR <protonated form name>` to
  catch papers that use the cation name (D-1 issue territory)

The query-templating logic is in `_literature_query_for(candidate)`
in `scripts/run_full_pipeline.py`.

### 7.3 Citation-cue prompt
The current orchestrator prompt is bare per the Track O1 contract.
A separate `orchestrator/prompt_v2.py` could add a citation-cue
("when discussing literature evidence, cite the PMID inline") and
be used by a future orchestrator track. Track O1's prompt
(`orchestrator/prompt.py`) is locked by `test_prompt_does_not_contain_
antihallucination_phrases`; any change must version-bump.

### 7.4 Layer E activation rate measurement
Layer E currently activates only on PMID/DOI-anchored claims.
Counting Layer E activations per fixture across N runs gives a
floor on LLM citation-fabrication rate. Suggest tracking:
* fraction of v1 claims classified as LITERATURE
* fraction of LITERATURE claims that resolved CONTRADICTED
* per-fixture variance

across the next 20-30 fixtures the eval session generates.

---

## 8. Files added / modified

```
schemas/report.py                              MODIFIED — added literature_records field
scripts/run_full_pipeline.py                   MODIFIED — Stage 3b fp injection + Stage 7 literature
                                                          + CLI/env knobs + 2 helpers
orchestrator/formatter.py                      MODIFIED — _literature_block per candidate
verifier/schemas.py                            MODIFIED — ClaimType.LITERATURE
verifier/claim_classifier.py                   MODIFIED — PMID/DOI rules + LITERATURE literals
verifier/agent.py                              MODIFIED — LITERATURE dispatch + literature_fetcher
verifier/prompts/classify_ambiguous.py         MODIFIED — LLM fallback prompt knows literature
verifier/layers/literature.py                  NEW       — Layer E
tests/integration/test_pipeline_fp_strategy.py NEW       — 9 tests, Q1 wiring
tests/integration/test_pipeline_literature.py  NEW       — 7 tests, Q2 Stage 7
tests/test_verifier/test_layer_literature.py   NEW       — 19 tests, Layer E
tests/test_verifier/test_claim_classifier.py   MODIFIED — +5 LITERATURE rule cases
tests/test_verifier/test_agent_real_o1_outputs.py MODIFIED — +2 acceptance tests
```

Total: 8 modified files, 4 new files. Test count: **179 passing** (109 verifier
unit + 24 orchestrator + 9 fp-strategy + 7 literature pipeline + 19 Layer E +
5 classifier + 2 acceptance + 4 prior verifier integration that already
passed). All pre-existing tests outside Q1+Q2 scope are unchanged.

---

## 9. Reproduce the live e2e run

```bash
# Pipeline (diffms env, ~5 min, real DBs)
METAGENT_HMDB_PATH=/data/weiwentao/llm_agent_metabolomics/hmdb.sqlite \
METAGENT_RAMP_PATH=/data/weiwentao/llm_agent_metabolomics/ramp.sqlite \
METAGENT_CFM_URL=http://127.0.0.1:8088 \
conda run -n diffms python scripts/run_full_pipeline.py \
  --fixture glucose_pos --output json \
  --top-k 5 --predict-top-n 3 --literature-top-n 3 \
  > /tmp/glucose.json 2>/tmp/glucose.stderr

# Orchestrator (metagent-llm env, ~30 s, 1 LLM call)
MINIMAX_API_KEY="$(cat api_key.txt)" \
conda run -n metagent-llm python -m orchestrator identify \
  --report-json /tmp/glucose.json \
  --trace-id glucose-live

# Verifier (metagent-llm env, ~9 min, 7 LLM calls)
# (no built-in CLI yet — invoke verifier.agent.verify() directly;
#  see tests/integration/test_verifier_e2e.py for a wrapper pattern)
```

Logs land in `logs/llm_calls.jsonl` joinable to the orchestrator's
`trace_id` and the verifier's `<trace_id>_verified*` derived ids.

---

## 10. What the next session should build

In rough priority order:

1. **Title-mismatch detection in Layer E** (§7.1). Currently Layer E
   only validates ID existence; a fabricated description of a real
   PMID slips through.
2. **Verifier CLI wrapper** so `verify()` can be driven by command
   line like the orchestrator. Currently you have to write a Python
   one-liner.
3. **Layer E activation-rate measurement** across 20–30 fixtures
   (§7.4). Provides the empirical baseline for citation-fabrication.
4. **Investigate diffms-env Europe PMC SSL transient** (§5.2).
   Either fix in `tools/literature/` or document the matchms-CFM-ID
   interaction.
5. **Smarter literature query templating** (§7.2). Current query is
   a single line and rejects nameless candidates outright.
6. **MIST/CSI base-fingerprint integration** so `topn_*` actually
   uses the MIST term (§5.1). Requires a separate Track M /
   MIST-style fingerprint predictor.

# Track O1 — Naive Orchestrator v0 Delivery

- **Date:** 2026-04-23
- **Branch:** `integration-day1`
- **Session commits:** `660f6f7` (Part 1) · `b54cbbe` (Part 2) · `145341b` (fix .gitignore) · `2bc192d` (Part 3) · this report (Part 4)
- **LLM env:** `metagent-llm` (python 3.11, `openai==0.28.1`, `tiktoken==0.12.0`, `pydantic==2.13.3`)
- **LLM backend:** MiniMax-M2.7 via MiniMax OpenAI-compatible endpoint (`https://api.minimaxi.com/v1`)

## 1. Summary

This session delivers the first LLM-driven component of the system: a
**naive orchestrator** that wraps a deterministic `IdentificationReport`
with exactly one MiniMax chat call per identification and returns whatever
the model produces, verbatim.

**No hallucination control was added.** The system prompt is the bare
four-point directive from the track brief. No claim extraction, no
verifier, no cascade, no retry-on-bad-output, no prompt engineering
aimed at reducing fabrication. A unit test (`test_prompt_does_not_contain_
antihallucination_phrases`) will fail loudly if a future contributor adds
phrases like "hallucinat*", "do not speculate", "cite your source", or
"only use facts" to the prompt.

The deliverable is a **measurement apparatus** — every call lands a
complete JSONL row to disk, joinable to its `NaiveIdentification` by
`trace_id`, so downstream evaluation can annotate claims by hand and
compute a baseline hallucination rate before the Verifier session
designs its verifier against measured failure modes.

## 2. LLM logging

### Where

`logs/llm_calls.jsonl` at the repo root. Overridable via
`METAGENT_LLM_LOG_PATH` env var or `common.llm_client.set_log_path(path)`.
The file is `.gitignored` (`logs/*.jsonl`) but the directory is
preserved by `logs/.gitkeep`.

### Schema (one JSON object per line)

| field | type | notes |
|---|---|---|
| `log_schema_version` | `int` | Currently `1`. Bump on breaking changes. |
| `timestamp` | `str` | UTC ISO-8601 with milliseconds, e.g. `"2026-04-23T12:25:19.263Z"` |
| `caller` | `str \| null` | Component that initiated the call, e.g. `"orchestrator.naive.identify"`. Filter on this to isolate naive-orchestrator calls once the verifier adds its own. |
| `trace_id` | `str \| null` | Opaque join key. For the orchestrator: `ident_<hash8>_<YYYYMMDDHHMMSS>` when auto-generated. |
| `model` | `str` | e.g. `"MiniMax-M2.7"` |
| `temperature` | `float` | |
| `max_tokens` | `int` | |
| `messages` | `list[dict]` | The full prompt — untruncated. Both `system` and `user` roles. |
| `response_raw` | `str \| null` | Raw assistant content **with** the `<think>...</think>` block still present if MiniMax returned one. |
| `response_cleaned` | `str \| null` | After `strip_thinking()`. This is what `chat()` returned to the caller. |
| `prompt_tokens` / `completion_tokens` / `total_tokens` / `cached_tokens` | `int \| null` | Populated from the API `usage` dict when present; falls back to a tiktoken estimate. |
| `token_source` | `"api"` / `"tiktoken_approx"` / `"none"` | Tag indicating which branch populated the token counts. |
| `base_resp_status_code` | `int \| null` | MiniMax-specific business status. `0` is success; non-zero is a backend error with HTTP 200. |
| `elapsed_ms` | `int` | Wall-clock from inside `chat_raw()`. |
| `mock` | `bool` | `true` if `set_mock()` was in effect. Filter to `false` for real-call analysis. |
| `error` | `dict \| null` | `{"type": "...", "message": "..."}` when the underlying call raised; otherwise `null`. The exception is still re-raised — logging is side-effect-only. |

### How to query

Join the `NaiveIdentification.trace_id` returned by `orchestrator.naive.identify()`
with the JSONL row of the same `trace_id`:

```python
import json
from pathlib import Path

trace_id = result.trace_id  # from identify()
row = next(
    json.loads(ln) for ln in Path("logs/llm_calls.jsonl").read_text().splitlines()
    if json.loads(ln)["trace_id"] == trace_id
)
print(row["messages"][1]["content"])   # user message (the formatter output)
print(row["response_raw"])              # includes <think> block
```

To filter to naive-orchestrator calls only (once verifier sessions add their own):

```bash
jq -c 'select(.caller == "orchestrator.naive.identify" and .mock == false)' logs/llm_calls.jsonl
```

## 3. Prompt — verbatim

This is the **exact** string passed as the `system` message for every
identification in this delivery. The `user` message is the pseudo-markdown
serialisation of the `IdentificationReport` produced by
`orchestrator.formatter.format_report_for_llm(report, top_n=5)`.

```
You are a metabolomics expert. You are given a structured identification
report produced by an automated MS/MS analysis pipeline. The report lists candidate
metabolites that may explain the experimental spectrum, along with supporting evidence
from chemical databases and in-silico spectral prediction.

Write a concise natural-language identification report that:

1. States the most likely candidate and why.
2. Discusses the top 3 candidates in order of evidence.
3. Mentions relevant pathway context where available.
4. Notes the limitations or caveats visible in the data.

Keep the report under 400 words. Write for a chemist reading it.
```

The bare phrasing is intentional. Future verifier sessions that wish
to add guard phrases must not edit this file; they should live in a
separate, version-bumped prompt on their own side. The guard test
referenced in §1 enforces this.

## 4. Three fixture outputs — verbatim

All three reports were generated on 2026-04-23 by:

```bash
# Step 1 — deterministic pipeline (diffms env, all backends live)
METAGENT_HMDB_PATH=/data/weiwentao/llm_agent_metabolomics/hmdb.sqlite \
METAGENT_RAMP_PATH=/data/weiwentao/llm_agent_metabolomics/ramp.sqlite \
METAGENT_CFM_URL=http://127.0.0.1:8088 \
conda run -n diffms python scripts/run_full_pipeline.py \
    --fixture <name> --output json > /tmp/o1/<name>.json

# Step 2 — naive orchestrator (metagent-llm env)
MINIMAX_API_KEY="$(cat api_key.txt)" \
conda run -n metagent-llm python -m orchestrator identify \
    --report-json /tmp/o1/<name>.json \
    --trace-id o1-part4-<name>
```

Each call ran against the live MiniMax endpoint, landing one row per call
in `logs/llm_calls.jsonl`. Pipeline-side degradation: `molecule_generate`
(track C) was unavailable because the `sirius` binary is not on the path;
everything else (A1 / A2 / B / D1 / D2 / E) ran with live backends.

The following outputs are **copy-pasted verbatim** from the `response_cleaned`
field of the three matching JSONL rows (`trace_id` values
`o1-part4-glucose_pos`, `o1-part4-caffeine_pos`, `o1-part4-lcarnitine_pos`).
Formatting is exactly as MiniMax returned it. **Do not edit** — the
ugliness is the data.

### 4.1 glucose_pos

- `trace_id`: `o1-part4-glucose_pos`
- `elapsed_ms`: 32142
- `prompt_tokens`: per log row; `completion_tokens`: 1152 (much of which is the `<think>` block, stripped from the output below)
- Length: 347 words, 2575 bytes

```
## Identification Report

**Precursor:** [M+H]+ at m/z 181.0707 (neutral mass 180.0634 Da)  
**Molecular Formula:** C₆H₁₂O₆ (hexose monosaccharide)

---

### Most Likely Candidate: D-Gulose (evidence_score: 0.771)

D-Gulose ranks highest by a narrow margin (0.771 vs 0.761). It is a C-3 epimer of glucose and appears in galactose-related metabolic pathways. The predicted spectral match (cosine 0.423) is the best among candidates, and its B/C score (0.860) is the highest in the list.

---

### Top Candidates

**1. D-Gulose (C₇H₁₄O₇)**  
Score: 0.771 | Cosine: 0.423  
Linked to galactose metabolism, galactosemia, and Fabry disease pathways. The pathway enrichment provides biological context supporting this identification.

**2. Glucose (C₆H₁₂O₆)**  
Score: 0.761 | Cosine: 0.423  
Identical predicted spectral similarity and formula. Glucose is a central metabolic hub, making it statistically probable in biological samples. The marginal score difference (0.01) is essentially at the discrimination threshold.

**3. D-Psicose (C₆H₁₂O₆)**  
Score: 0.639 | Cosine: 0.370  
A ketose epimer with no pathway associations in this dataset. Lower spectral agreement and lack of biological context reduce confidence.

---

### Pathway Context
Gulose maps to galactose metabolism and galactosemia pathways (SMPDB/KEGG). Glucose connects to a broader range of metabolic contexts. The presence of either suggests a sugar monitoring experiment or carbohydrate metabolism study.

---

### Limitations & Caveats

- **Low spectral similarity:** Cosine scores of 0.33–0.42 indicate poor agreement between experimental and predicted spectra. Hexose isomers fragment nearly identically, making confident differentiation from MS/MS alone very difficult.
- **Sparse data:** Only 7 peaks detected. The quality flag is "sparse," suggesting the spectrum lacks fragment diversity for robust identification.
- **Pipeline warnings:** Multiple degraded outputs were flagged; pathway and spectral prediction data may be incomplete.
- **No de novo structure:** The molecule generation step returned 0 candidates, so in-silico structural candidates were not available to supplement library hits.

---

### Conclusion
This spectrum is consistent with a C₆H₁₂O₆ hexose sugar. **D-Gulose is the top-ranked candidate**, but **glucose cannot be excluded** given the near-identical evidence scores and spectral predictions. Definitive identification would require orthogonal validation (retention time, NMR, or comparison to authentic standards) given the inherent ambiguity of hexose MS/MS fragmentation.
```

### 4.2 caffeine_pos

- `trace_id`: `o1-part4-caffeine_pos`
- `elapsed_ms`: 31901
- `completion_tokens`: 1202
- Length: 405 words, 3043 bytes

```
## Metabolite Identification Report

### Summary
The experimental spectrum (m/z 195.0877 [M+H]+, neutral mass 194.0804 Da) matches molecular formula **C8H10N4O2**. The top five candidates are structural isomers within the imidazopyrimidine/purine-dione chemical class. **Caffeine** is the most likely identification based on the available evidence.

---

### 1. Caffeine (evidence_score: 0.785) — **Most Likely**

Caffeine ranks highest primarily due to its exceptional library candidate score (B/C = 0.975) and robust cross-referencing across HMDB, KEGG, and ChEBI. The mass accuracy is excellent (<1 ppm vs. HMDB reference). Critically, Caffeine is the only candidate with meaningful pathway context: it maps to caffeine metabolism pathways in SMPDB, KEGG (map00232), and Reactome, making it biologically plausible if the sample originates from a typical biological matrix (coffee, tea, energy drinks, or human metabolism studies).

The predicted-spectrum cosine (0.316) is low, but this must be interpreted in context — the spectrum is sparse (only 5 peaks), which limits reliable spectral matching. Low cosine scores are expected for simple, low-complexity spectra.

---

### 2. Isocaffeine (evidence_score: 0.651)

A structural isomer of caffeine with identical molecular formula. It shows the highest predicted-spectrum cosine (0.439) among candidates, but lacks pathway associations and database cross-references. Without additional spectral features or biological context, it cannot be preferred over caffeine.

---

### 3. 1,3,8-Trimethyl-7H-purine-2,6-dione (evidence_score: 0.617)

Also a structural isomer (potentially the same as isocaffeine under different nomenclature). Moderate spectral match (cosine 0.338) and no pathway information. Cannot be confidently distinguished from isocaffeine without reference standards or additional data.

---

### Caveats and Limitations

1. **Sparse spectral data**: Only 5 peaks detected; MS/MS fragmentation is minimal. This severely limits spectral matching reliability — all cosine scores are low by necessity, not necessarily indicating poor match.
2. **No in-silico molecular generation**: The molecule-generation step failed (SIRIUS binary not found), so candidates were library-only.
3. **Degraded metadata for several candidates**: Pathway context and metabolite info were unavailable for 4 of 5 candidates, weakening biological contextualization.
4. **Stereochemistry/tautomerism**: The isomers listed (caffeine vs. isocaffeine) differ in methyl-group positioning; fragmentation patterns may not cleanly separate them at this collision energy with sparse data.

---

### Recommendation

If the sample context involves coffee, tea, energy supplements, or human caffeine metabolism, **caffeine is a confident identification**. If the sample is from an atypical matrix or requires absolute certainty, a reference standard comparison at the same collision energy is recommended. The other candidates cannot be excluded but are less supported by biological context and database evidence.
```

### 4.3 lcarnitine_pos

- `trace_id`: `o1-part4-lcarnitine_pos`
- `elapsed_ms`: 32732
- `completion_tokens`: 1158
- Length: 323 words, 2525 bytes

```
## Identification Report

### Most Likely Candidate
**2-[2-hydroxyethyl(methyl)amino]ethyl acetate** (CID:218057, C₇H₁₅NO₃) is the top candidate with an evidence score of 0.529. It demonstrates the highest predicted-spectrum cosine similarity (0.112) among the candidates and maintains a favorable candidate score (B/C: 0.737). The formula C₇H₁₅NO₃ matches the back-calculated neutral mass (161.1052 Da) at 5 ppm tolerance.

### Top 3 Candidates

1. **2-[2-hydroxyethyl(methyl)amino]ethyl acetate** — Contains a tertiary amine, an ester, and a hydroxyl group. The structure is synthetically plausible and consistent with mass and predicted fragments. Slightly better spectral alignment than other candidates, though all cosine values remain low.

2. **3-[2-(dimethylamino)ethoxy]propanoic acid** (evidence_score: 0.499) — Also C₇H₁₅NO₃ with a zwitterionic potential (dimethylamino + carboxylic acid). Structural isomers of #1 and #3 are difficult to distinguish by low-energy MS/MS alone.

3. **[dimethyl-(trimethylsilylamino)silyl]methane** (evidence_score: 0.499) — Contains silicon. While mass-accurate, this is an atypical organosilane unlikely to arise in biological samples. The predicted spectrum cosine is 0.000, strongly arguing against this candidate.

### Pathway Context
No pathway annotations could be retrieved due to degraded metabolite_info output for all candidates. The C₇H₁₅NO₃ formula is consistent with small-molecule intermediates or drug/metabolite fragments, but specific pathway assignment is not possible with current data.

### Limitations and Caveats
- **Spectral quality is poor**: Only 5 peaks detected; cosine similarities are uniformly low (max 0.112). This spectrum is insufficient for confident identification.
- **No metabolite metadata**: All candidates returned `found=False` for InChIKey lookups, eliminating literature, biofluid, and pathway context.
- **Formula degeneracy**: The top 5 candidates are mostly structural isomers sharing C₇H₁₅NO₃; MS/MS at 20 eV cannot reliably differentiate them.
- **Silicon-containing candidate**: Candidate #2 is chemically implausible for most biological matrices.

### Recommendation
This identification is **tentative and low-confidence**. Re-acquisition of the spectrum at higher collision energy or with improved ionization would be required to obtain a richer fragment pattern. If the sample is biological, the silicon-containing candidate should be disregarded. Additional reference standards or NMR follow-up are recommended for confirmation.
```

## 5. Quick observations

These are first-pass, non-scientific notes intended as seed material for
the Verifier session. **No fix was attempted**; every item below is a
datapoint about the bare-LLM baseline.

1. **Within-document formula inconsistency (glucose_pos, observation H1).**
   The LLM wrote `**1. D-Gulose (C₇H₁₄O₇)**` in the header of the first
   candidate block, but `**2. Glucose (C₆H₁₂O₆)**` correctly just below.
   Pipeline's own `metabolite_info.molecular_formula` for both is `C6H12O6`.
   D-Gulose is an aldohexose, so the LLM's `C₇H₁₄O₇` is wrong on its face;
   `C₆H₁₂O₆` appearing correctly in the `### Pathway Context` section of
   the same output shows the model **knows** the right formula and still
   surfaces the wrong one inside a `**bold**` header. High-value target
   for a verifier: intra-document contradictions on fields that are
   computable from the stored SMILES.

2. **Pathway names are faithfully reflected (glucose_pos).**
   "galactose metabolism, galactosemia, and Fabry disease pathways" —
   all three map to pipeline entries (`SMP00525: Fabry disease`,
   `SMP00043/map00052: Galactose Metabolism`, `SMP00182: Galactosemia`).
   Not hallucinated. This is the happier side of the same apparatus.

3. **KEGG ID passed through cleanly (caffeine_pos).** `KEGG (map00232)`
   matches the pipeline's `map00232: Caffeine metabolism` pathway entry.
   No fabrication.

4. **Unsourced numeric precision (caffeine_pos, observation H2).** LLM
   states "The mass accuracy is excellent (<1 ppm vs. HMDB reference)".
   The pipeline only surfaces a binary `mass_match_indicator` (1.0 at a
   5 ppm gate, not a live ppm value). The "<1 ppm" quantity is not in
   the data. Same pattern worth watching: LLM converts a boolean
   indicator into a specific number.

5. **Isomer naming drift (caffeine_pos).** Pipeline's candidate #2 is
   `1,3,9-trimethylpurine-2,6-dione`; LLM calls it "Isocaffeine". These
   are arguably the same molecule under chemical-naming conventions, but
   the LLM is pulling an alternate name the pipeline did not emit. Not
   a hallucination per se — document it because claim-extraction needs
   to handle this kind of rewording robustly.

6. **Honest non-recovery on the L-carnitine D-1 quirk (lcarnitine_pos).**
   The pipeline's top-1 is `2-[2-hydroxyethyl(methyl)amino]ethyl acetate`
   (not L-carnitine) because HMDB/GNPS index only the cation form and the
   fixture precursor back-calculates to the zwitterion neutral
   (161.105 Da). **The LLM did not invent L-carnitine into its output** —
   it reported the pipeline's actual top candidate with its actual low
   cosine (0.112) and called the identification "tentative and low-
   confidence". This is the well-behaved baseline on a truth-absent
   report. Compare side-by-side with §5.1 to see where fabrication
   appears and does not.

7. **"Silicon-containing candidate" is real (lcarnitine_pos).** The LLM
   flagged `[dimethyl-(trimethylsilylamino)silyl]methane` as
   "chemically implausible for most biological matrices". Pipeline
   really did return this candidate; LLM's chemistry-knowledge-driven
   warning is correct. Verifier need not flag this; the `C`/`source`
   field (`generated`) already exposes provenance.

8. **Length control is loose.** Prompt asked for "under 400 words".
   Actual lengths: 347 / 405 / 323 words. One output breached by 5
   words. Not surprising; MiniMax at `temperature=0` doesn't hard-cap
   length. Harmless for v0 — if a future prompt needs a strict cap,
   that's a different prompt's problem.

9. **Wall-clock: ~32 s per identification.** Stable across fixtures
   (31.9 / 32.1 / 32.7 s). Completion tokens ~1150–1200 each, of which
   a substantial fraction is the `<think>` block (stripped from the
   returned output but retained in `response_raw` for inspection).

## 6. Handoff to evaluation

**To whoever annotates claims next:**

Every naive-orchestrator call produced two artefacts:

1. A `NaiveIdentification` object with `trace_id`, `source_report_hash`,
   `llm_output`, `generated_at`. In this delivery the `trace_id` values
   are `o1-part4-glucose_pos`, `o1-part4-caffeine_pos`,
   `o1-part4-lcarnitine_pos`.
2. A row in `logs/llm_calls.jsonl` keyed on the same `trace_id`.

The log row's `messages[0]["content"]` is the system prompt (bare), and
`messages[1]["content"]` is the full pseudo-markdown rendering of the
pipeline's `IdentificationReport` — i.e. everything the LLM was given.
The log row's `response_raw` is the assistant message before
`</think>` stripping; `response_cleaned` is the user-visible output. The
three pipeline JSON files used here are in `/tmp/o1/{fixture}.json` on
the machine used for this run (they are not checked into the repo on
purpose — they carry `tool_versions` path+mtime signatures that are
environment-specific).

**Suggested first evaluation pass (per output):**

1. Extract every chemical-fact claim from `response_cleaned` (molecular
   formula, m/z, ppm, pathway ID, cross-ref ID, epimer/stereo
   relationship, chemical-class name).
2. Join against the corresponding pipeline row via `trace_id` →
   `messages[1]["content"]` (deterministic, not LLM).
3. Tag each claim as {supported / contradicted / unsupported}:
   - *supported* — claim appears explicitly in the formatter output
   - *contradicted* — claim disagrees with a field the formatter emitted
   - *unsupported* — claim has no anchor in the formatter output at all
     (requires an external source to verify)

The observations in §5 are your starter set. §5.1 (the D-Gulose formula)
is a contradicted claim that both the formatter output and the LLM's own
later paragraph disprove. §5.4 (the "<1 ppm" precision) is an unsupported
quantitative claim — the pipeline didn't emit that number. §5.6 is a
baseline point of reference where fabrication plausibly *could* have
occurred and did not.

The verifier session should use this ratio (supported / contradicted /
unsupported across N identifications) as its design target. A verifier
that catches §5.1-class contradictions but misses §5.4-class unsupported
quantitative claims (or vice versa) is narrow; one that catches both
without being triggered by §5.2/§5.3 (faithfully-reflected pipeline
data) is what Track O1's successor session needs to build.

Nothing in this delivery was fixed. The wrong formulas stay wrong. The
prompt stays bare. That is the contract.

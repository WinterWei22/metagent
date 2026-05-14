# Track O1: Naive orchestrator — the minimum LLM wrapper

## Who you are — and what "naive" means here

You are building the first LLM-driven component of the system. Every track before you (A through F, plus the full-pipeline integration) produced deterministic code with no LLM call. You are the boundary-crosser: the component that takes the deterministic pipeline's output and puts an LLM in front of a user.

"Naive" is a **deliberate design constraint**, not a placeholder for bad work. It means:

- No hallucination control
- No claim extraction
- No verifier
- No cascade
- No re-prompt-on-bad-output retries
- No RAG over external docs

Just: `IdentificationReport → prompt → LLM → natural-language output`. One LLM call per identification. Output whatever the LLM produces. Log everything.

**The reason for naivety is scientific**: the project needs to measure the baseline hallucination rate of the raw LLM on this task before designing a verifier. A verifier designed against imagined hallucinations is useless; a verifier designed against measured hallucinations is publishable. This session produces the measurement apparatus, not the cure.

If you feel the urge to "improve" the output by adding prompt engineering tricks, safety rails, or output validation — STOP. Your improvements are this session's pollution. Someone else (a future Verifier session) will do the cure.

## Read before doing anything

In this order:

1. `docs/ARCHITECTURE.md` — re-read the "every factual claim is verifiable" principle. Verification is future work; naive orchestrator is about SURFACING claims so they CAN be verified later.
2. `docs/LLM_INTEGRATION.md` — mandatory. The four MiniMax gotchas (Authorization header, `</think>` stripping, JSON fallback, tiktoken encoding). You will hit all four.
3. `common/llm_client.py` — read the current implementation. Note: logging is NOT implemented yet. Adding it is part of your job (§ Part 1).
4. `schemas/report.py` — the `IdentificationReport` and `CandidateReport` you consume. This is your input.
5. `scripts/run_full_pipeline.py` — the deterministic runner whose output you wrap.
6. `tests/integration/test_full_pipeline_e2e.py` — to know what a real report looks like on the three fixtures.
7. The maintainer's earlier GeneAgent script (if linked in docs). Skim it. DO NOT copy the cascade pattern — that's for Verifier. You are looking for how it structured prompts and parsed responses, as reference.

Then report back to the maintainer in 5 bullets:

- Your understanding of what a "naive" orchestrator means in this context (prove you internalized §Who you are)
- The single LLM prompt structure you propose (system + user, or just user; what sections the user message will contain)
- Your proposed LLM logging schema — every field you will capture in JSONL per call
- How you'll CLI-entry this (proposed `python -m orchestrator ...` argv)
- Your plan for the 4 deliverables below, in order

Wait for confirmation before writing code.

## Hard scope boundaries

You MAY:
- Create a new top-level package `orchestrator/`
- Modify `common/llm_client.py` ONLY to add logging (§Part 1). No other changes — do not touch the `chat()` / `chat_raw()` logic, not even to "improve" it.
- Create `tests/test_orchestrator/` for unit tests
- Create `tests/integration/test_orchestrator_e2e.py` for an end-to-end integration test (real MiniMax call, gated on API key)
- Create `logs/.gitkeep` to reserve the logs directory (the JSONL itself goes in `.gitignore`)
- Update `.gitignore` to exclude `logs/*.jsonl`

You MAY NOT:
- Modify any file under `tools/`, `schemas/`, `docs/`, `prompts/`
- Modify `common/` except for the ONE logging addition to `llm_client.py`
- Modify existing tests under `tests/tool_tests/`, `tests/integration/test_full_pipeline_e2e.py`, `tests/test_verifier/`
- Add claim extraction, verification, cascading, or any multi-step LLM flow. Exactly one `chat()` call per identification. If you find a reason to call the LLM twice in one identification, stop and ask.
- Add retry logic on LLM output format. If the LLM returns malformed output, that's data — log it and return it as-is.
- Add prompt engineering tricks aimed at reducing hallucination ("only state facts supported by the data", "do not speculate", "cite your source"). The whole point is to measure baseline rate. Prompt should instruct the LLM on FORMAT (what sections to include) but NOT on TRUTHFULNESS.
- Use any LLM other than the one `common.llm_client` is configured with. No OpenAI GPT-4 fallback. MiniMax or nothing.

## Part 1: Add JSONL logging to `common/llm_client.py`

This is the highest-value piece of work in this session. Without it, the measurements this project needs for the paper cannot happen.

Requirements:

- Every call to `chat()` or `chat_raw()` appends one line to `logs/llm_calls.jsonl` (create dir if missing; don't crash if unwritable).
- Each JSONL line is a complete self-contained record.
- Logging must be side-effect-only — if logging fails, the LLM call still returns. Wrap logging in a `try/except` that only logs the exception to stderr.
- Logging MUST NOT change the return value of `chat()` / `chat_raw()`. Test this with a before/after call.

Minimum fields per log entry (propose more in your understanding checkpoint if relevant):

```json
{
  "timestamp": "2026-04-23T14:30:05.123Z",
  "caller": "orchestrator.naive.generate_identification",  
  "trace_id": "ident_glucose_pos_20260423143005",  
  "model": "MiniMax-M2.7",
  "temperature": 0.0,
  "max_tokens": 127900,
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."}
  ],
  "response_raw": "...with </think> still in it if present...",
  "response_cleaned": "...after strip_thinking...",
  "response_tokens": 847,
  "prompt_tokens": 3241,
  "total_tokens": 4088,
  "elapsed_ms": 8421,
  "error": null
}
```

**`trace_id`** is the key mechanism. The orchestrator generates a unique ID per identification and passes it to the LLM client via a new kwarg on `chat()` / `chat_raw()`. This lets you later join an `IdentificationReport` on disk with its LLM call log line.

The `caller` field is useful for when Verifier sessions eventually add their own LLM calls — you'll be able to filter `caller=="orchestrator.naive.*"` to isolate naive-orchestrator calls in the log.

**Log the messages in full.** Do not truncate. Disk is cheap; losing the prompt when debugging a weird output is expensive.

### Test coverage for logging

- `test_llm_logger_appends_jsonl`: single call writes exactly one valid JSON line
- `test_llm_logger_doesnt_break_on_unwritable_dir`: with `logs/` read-only, chat() still returns the right value, error goes to stderr
- `test_llm_logger_captures_raw_and_cleaned_separately`: force a `</think>` in a mock response, verify both fields in the JSONL
- `test_llm_logger_preserves_return_value`: compare `chat()` output with and without a logger-provoking input; identical return

## Part 2: Naive orchestrator implementation

```
orchestrator/
├── __init__.py
├── naive.py             # top-level entry: identify(report: IdentificationReport) -> NaiveIdentification
├── prompt.py            # the one and only prompt template (system + user assembly)
├── formatter.py         # serialises IdentificationReport into the user message content
├── schemas.py           # NaiveIdentification output type (just a wrapper around the LLM string)
└── __main__.py          # CLI entry: python -m orchestrator identify --fixture glucose_pos
```

### Top-level entry

```python
# orchestrator/naive.py
def identify(report: IdentificationReport, *, trace_id: str | None = None) -> NaiveIdentification:
    trace_id = trace_id or _auto_trace_id(report)
    system_prompt = _build_system_prompt()
    user_message = _format_report_for_llm(report)
    raw = chat(
        messages=[{"role": "system", "content": system_prompt},
                  {"role": "user", "content": user_message}],
        trace_id=trace_id,
        caller="orchestrator.naive.identify",
    )
    return NaiveIdentification(
        trace_id=trace_id,
        source_report_hash=_hash(report),
        llm_output=raw,
        generated_at=datetime.utcnow(),
    )
```

That's it. No loops, no retries, no parsing.

### Output schema

```python
class NaiveIdentification(BaseModel):
    trace_id: str
    source_report_hash: str         # hash of the input IdentificationReport for join-ability later
    llm_output: str                  # raw text from LLM, post-strip_thinking
    generated_at: datetime
```

Notice: NO parsed fields. No "top_candidate", no "confidence", nothing. The whole point is to see what the LLM says, without coercing it into a structure.

### The prompt

Exactly one prompt. In `orchestrator/prompt.py`:

```python
SYSTEM_PROMPT = """You are a metabolomics expert. You are given a structured identification 
report produced by an automated MS/MS analysis pipeline. The report lists candidate 
metabolites that may explain the experimental spectrum, along with supporting evidence 
from chemical databases and in-silico spectral prediction.

Write a concise natural-language identification report that:

1. States the most likely candidate and why.
2. Discusses the top 3 candidates in order of evidence.
3. Mentions relevant pathway context where available.
4. Notes the limitations or caveats visible in the data.

Keep the report under 400 words. Write for a chemist reading it."""
```

**That's the entire prompt.** Do not add:
- "Do not hallucinate"
- "Only use facts from the data"
- "Cite your source for each claim"
- "Refuse if uncertain"

Those are post-naive interventions. This prompt stays bare. The whole project depends on you NOT "fixing" this prompt.

### The user message

`orchestrator/formatter.py` serialises the `IdentificationReport` as JSON + some lightweight decoration. One acceptable format:

```
## Experimental spectrum
- Precursor m/z: 181.0707
- Adduct: [M+H]+
- Neutral mass: 180.0634
- Peak count (after preprocess): 7
- Quality flag: sparse

## Candidates (top 5 by evidence_score)

### 1. D-Glucose (evidence_score: 0.89)
- SMILES: OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O
- Molecular formula: C6H12O6
- Source: library (ms-clip + modcos fusion)
- Library match score: 0.79
- Predicted spectrum cosine: 0.85
- Mass match: yes (0.8 ppm)
- Known pathways: Glycolysis (KEGG hsa00010, 3 hits), Pentose Phosphate (hsa00030, 1 hit)
- HMDB: HMDB0000122

### 2. D-Fructose (evidence_score: 0.72)
... etc

## Pipeline warnings
- None

## Tool versions
- cfm-id: 4.4.7
- ms-bart: MassSpecGym-v1
- ...
```

Whether to pass this as pseudo-markdown or pure JSON is your call — propose one in your understanding checkpoint, then commit. Do NOT implement both "just in case". 

**Caution on L-carnitine**: if running on L-carnitine fixture, the report will carry HMDB's zwitterion mass (162.113 Da for C7H16NO3), not the neutral mass. Pass this through as-is. Do NOT "correct" it in the formatter. That's the LLM's job to interpret, or get wrong — and getting wrong is the baseline data we need.

### CLI

```
python -m orchestrator identify --fixture glucose_pos
python -m orchestrator identify --fixture caffeine_pos --output json
python -m orchestrator identify --report-json path/to/report.json
```

Behavior:
- `--fixture NAME`: runs the full pipeline on that fixture (via `scripts/run_full_pipeline`), then feeds output to naive orchestrator, prints to stdout.
- `--report-json PATH`: skips pipeline, loads a cached report from JSON. Useful for re-running the LLM step on the same report without paying the pipeline cost again.
- `--output`: `text` (default — just the LLM output) | `json` (full `NaiveIdentification` as JSON) | `both`.
- Exit 0 on success, 1 on any exception. Prints error to stderr.

## Part 3: Tests

### Unit tests (mock path, no real LLM)

`tests/test_orchestrator/test_naive.py`:

- `test_identify_calls_llm_exactly_once`: patch `chat()` with a mock that counts calls, run `identify()`, assert 1 call
- `test_identify_passes_trace_id_to_llm_client`: mock receives `trace_id` kwarg
- `test_identify_returns_naive_identification_schema`: return value is a valid `NaiveIdentification` instance
- `test_formatter_includes_all_top_candidates`: given a report with 5 candidates, user message contains all 5
- `test_formatter_preserves_lcarnitine_zwitterion_mass`: L-carnitine report's mass is NOT silently corrected
- `test_prompt_does_not_contain_antihallucination_phrases`: literal grep on the SYSTEM_PROMPT for phrases like "hallucinate", "do not speculate", "cite your source" — if any appear, test FAILS. This is a guard against future well-meaning "fixes".

### Integration test (real LLM, gated)

`tests/integration/test_orchestrator_e2e.py`:

- `@pytest.mark.requires_minimax_key`: skip if `MINIMAX_API_KEY` unset
- `test_end_to_end_glucose`: load cached glucose IdentificationReport, run naive orchestrator, assert response is non-empty string, assert log file grew by 1 entry
- `test_end_to_end_three_fixtures_log_joinable_by_trace_id`: run on all 3 fixtures, read back the JSONL, confirm trace_ids match returned `NaiveIdentification.trace_id` values

This integration test is where you actually use budget — tens of cents. Run it exactly once before handing off.

### Test coverage for the logger (already specified in Part 1)

## Part 4: Delivery writeup

`reports/orchestrator_naive_v0_delivery_<date>.md`, 1-2 pages:

1. **Summary** — what was built, confirmation that no hallucination control was added
2. **LLM logging** — schema, where logs land, how to query
3. **Prompt** — the system prompt verbatim. This file is the version-controlled record of "what the LLM saw" for every identification going forward.
4. **Three fixture outputs** — the LLM's actual output on glucose_pos, caffeine_pos, lcarnitine_pos. Copy-paste verbatim, including any weird formatting. Do NOT edit for readability; the ugliness is the data.
5. **Quick observations** — a non-scientific first-pass note of anything surprising:
   - "On L-carnitine, the LLM said X about the mass; may be hallucinating"
   - "On caffeine, it invented a 2019 Nature paper; flagged for verifier design"
   - "Outputs are 280-350 words, well within the 400 target"
   - (Don't fix any of this, just document observations for the future Verifier session.)
6. **Handoff to evaluation** — a one-paragraph note for whoever will do the "annotate claims by hand" work next: where the logs live, how to join them to reports, what to look at.

## Exit criteria

- `pytest tests/test_orchestrator/ -v` — all unit tests pass, NO real LLM call
- `pytest tests/integration/test_orchestrator_e2e.py -v` — passes with real MiniMax key, gracefully skips without
- `pytest` across the whole repo — nothing broken
- Running `python -m orchestrator identify --fixture glucose_pos` prints a non-empty natural-language report and appends one line to `logs/llm_calls.jsonl`
- Log format validates as JSONL (each line a complete JSON object)
- The delivery writeup exists with all 6 sections populated
- Maintainer confirms the system prompt is bare (contains no hallucination-control phrasing)

## If things go sideways

- **If the LLM produces empty output or garbage on first try**: LOG IT. DO NOT retry. The orchestrator returns the garbage verbatim. This is a feature, not a bug — it's data about LLM reliability at this parameter setting.
- **If MiniMax returns 1004 or similar auth errors**: check `common/llm_client.py` Authorization header handling (see LLM_INTEGRATION.md). If the issue is client config not covered there, document and raise with maintainer — do not work around by silently switching models.
- **If the LLM output for L-carnitine is wildly wrong due to the zwitterion data quirk**: LOG IT. This is exactly the kind of measurement this session exists to capture. Your delivery writeup should call it out as a specific observation for the Verifier session.
- **If you find yourself wanting to add a "second LLM call to check the first"**: stop immediately. That IS the verifier. It is explicitly out of scope. Write a note in the delivery writeup describing the temptation and when the verifier session should address it.
- **If tests start needing 5+ different mock responses**: you're probably over-engineering. Each test should need at most one mock response. If it needs more, the code has too many LLM call sites.

## First action

Read the 7 items under "Read before doing anything". Report your 5-bullet understanding. The maintainer will especially scrutinize:

- That you understand "naive" as an intentional constraint, not a shortcut
- That your proposed prompt is bare (no anti-hallucination phrasing)
- That your logging schema captures enough for downstream evaluation
- That your single-LLM-call discipline is preserved

Your first commit should be the logging addition to `common/llm_client.py` (Part 1) — it unblocks everything else. Only after that lands should you write the orchestrator itself.
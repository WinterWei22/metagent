# LLM Integration (MiniMax-M2.7)

Read this before writing any code that talks to an LLM. The orchestrator and any tool that calls an LLM internally must route through `common/llm_client.py`, not through `openai.ChatCompletion.create` directly.

## Backend facts

- **Provider:** MiniMax via OpenAI-compatible endpoint
- **Base URL:** `https://api.minimaxi.com/v1`
- **Model:** `MiniMax-M2.7`
- **SDK:** `openai==0.28.x` (yes, the old one — that's what the existing workflow uses)
- **API key:** from env `MINIMAX_API_KEY`
- **Max output tokens:** 127900
- **Temperature:** default 0 for tool calling, LLM summaries, and verification. Only the reporter layer may use a higher temperature.

## The four MiniMax gotchas

### 1. Authorization header must be forced manually

`openai==0.28` with a custom `api_base` does not set the `Authorization` header the way MiniMax expects, and returns an opaque `1004` error. Fix: inject a `requests.Session` with an explicit bearer header. `llm_client.py` does this for you — do not bypass it.

```python
# This is done once in llm_client.py, do not repeat elsewhere:
import requests, openai
session = requests.Session()
session.headers["Authorization"] = "Bearer " + os.environ["MINIMAX_API_KEY"]
openai.requestssession = session
```

### 2. Responses contain `</think>` blocks that must be stripped

MiniMax returns chain-of-thought before the final answer, delimited by `</think>`. Every downstream parser (JSON extractor, process-name extractor, etc.) must strip this first. Use `strip_thinking()` from `common/llm_client.py`:

```python
def strip_thinking(text: str) -> str:
    if "</think>" not in text:
        return text.strip()
    return text.split("</think>", 1)[1].strip()
```

This is not optional. Skipping it makes JSON parsing randomly fail.

### 3. JSON parsing needs fallback extraction

When you ask MiniMax for a JSON list, you often get extra prose around it. Always use `extract_json_list()` from `common/llm_client.py`, which:
1. Strips thinking
2. Tries `json.loads` on the full text
3. Falls back to finding the last `[...]` or `{...}` block
4. Returns `[]` on total failure (with a warning log) — never raises

Do not write your own JSON extractor. One per codebase is enough.

### 4. Token accounting uses tiktoken with `gpt-4` encoding

MiniMax does not expose a native tokenizer. Existing scripts use `tiktoken.encoding_for_model("gpt-4")` as an approximation. It's imperfect but close enough. `llm_client.py` exposes `count_tokens(text)` using this convention — stay consistent.

## The shared client interface

`common/llm_client.py` provides exactly these:

```python
def chat(
    messages: list[dict],
    *,
    temperature: float = 0.0,
    max_tokens: int = 127900,
    model: str = "MiniMax-M2.7",
) -> str:
    """Call MiniMax, return the assistant message content (thinking stripped)."""

def chat_raw(
    messages: list[dict],
    *,
    temperature: float = 0.0,
    max_tokens: int = 127900,
    model: str = "MiniMax-M2.7",
) -> dict:
    """Same as chat() but returns the full response dict. Use when you need the
    assistant message appended to history (keep the raw form)."""

def strip_thinking(text: str) -> str: ...
def extract_json_list(text: str) -> list: ...
def extract_process_name(text: str, prefix: str = "Process:") -> str: ...
def count_tokens(text: str) -> int: ...
```

Tools that need to call the LLM must use `chat()` or `chat_raw()`. Do not import `openai` directly.

## When a tool should call the LLM (and when it shouldn't)

**Should:**
- `plausibility_summary` in `pathway_context` — NO, this uses a template, not an LLM. (Listed here as a negative to prevent confusion.)
- Any tool's `explain` field — NO, templates only.
- The orchestrator's planning, tool routing, report assembly — YES.
- The verifier's claim extraction and claim-report comparison — YES.

**Should not:**
- Any tool's core logic. `library_search` does NOT call the LLM to rank candidates — the retrieval model does. `fetch_metabolite_info` does NOT ask the LLM what glucose is — HMDB does.

The general rule: if the output is a fact, no LLM. If the output is a composition or judgement over facts, LLM.

## Message format conventions

Keep message construction boring and uniform. For a single-turn call:

```python
response = chat([
    {"role": "system", "content": "You are a precise extractor of chemical claims."},
    {"role": "user", "content": prompt},
])
```

For multi-turn (e.g. verification loops like GeneAgent's cascade), append raw assistant messages to the running history. `chat_raw()` returns the full response so you can append `response["choices"][0]["message"]` verbatim — that keeps role/content/etc. intact.

## Prompt style conventions

- Prompts live in `orchestrator/prompts/` as Python lambdas or as `.txt` templates, the same pattern as the GeneAgent codebase.
- System prompts are short and assertive: "You are a precise X." Not "Your job is to carefully...".
- When asking for JSON, say so explicitly and give a one-line example: `Only Return a list type that contain all generated claim strings, for example, ["claim_1", "claim_2"]`. This exact phrasing works well with MiniMax based on prior experiments.
- Never ask for formatted output inside the LLM response (no markdown tables, no code fences). The tool is responsible for formatting.

## Testing with an LLM backend

Unit tests MUST NOT hit the real LLM. Two patterns:

- **Deterministic mock:** `common/llm_client.py` exposes `set_mock(responses: list[str])` for tests. The mock returns items from the list in order.
- **Recorded fixtures:** For integration tests only, record real responses to `tests/fixtures/llm_responses/*.json` and replay.

If a test sees `MINIMAX_API_KEY` unset, it must skip, not fail. Use the `@pytest.mark.llm` marker for tests that require a real key.

## Cost and latency budget

- Target: one full identification report costs < $0.20 and < 60 seconds of LLM wall time.
- If your tool's LLM calls exceed ~3000 output tokens per call, reconsider the prompt.
- Orchestrator plans that require > 8 LLM round trips for a single identification need maintainer approval.

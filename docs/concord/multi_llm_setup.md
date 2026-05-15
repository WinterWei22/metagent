# Multi-LLM Setup for W11 Head-to-Head

**Purpose:** ConcordMet paper compares ≥2 LLM providers on the same multi-agent
reasoning task (per W11 spec). This doc lists the env vars + API keys + per-provider
caveats needed to run Sprint W11 evaluation.

**Status (W3 D4 hedge,2026-05-15):** wire-up structural test passed (mock-only,
4 unit tests in `tests/concord/test_llm_provider_gpt4o.py`).  
**Real API call deferred to Q-06 (see W3 status report)** — investigation
worktree has no API keys configured; real call will be triggered by user when
W11 starts.

---

## Provider matrix

| Provider | Env var to enable | Model id | Reference price (W11 budget) |
|---|---|---|---|
| **MiniMax**(default) | `METAGENT_LLM_PROVIDER=minimax` | `abab6.5-chat` | included(in-house)|
| **OpenAI / GPT-4o** | `METAGENT_LLM_PROVIDER=openai` | `gpt-4o-2024-11-20` | ~$2.50/1M in,$10/1M out(2026-Q2 quote)|
| **Claude** | `METAGENT_LLM_PROVIDER=anthropic`(W4 add) | `claude-opus-4-7` 或 `claude-sonnet-4-6` | $5/1M in,$25/1M out(2026-Q2 quote) |
| GPT-4 Turbo(legacy)| same as OpenAI(swap model arg)| `gpt-4-turbo-2024-04-09` | ~$10/1M in,$30/1M out |

---

## Setup steps

### OpenAI / GPT-4o

```bash
export METAGENT_LLM_PROVIDER=openai
export OPENAI_API_KEY="sk-..."         # 主 secret
export METAGENT_OPENAI_BASE_URL="https://api.openai.com/v1"   # 默认值,可不设
```

The `common/llm_client.py` already wires OpenAI provider when these are set.

**Cost guard**:`DEFAULT_MAX_TOKENS=16_384`(reasoning-class limit).Verify caller
passes explicit `max_tokens` for short single-turn benchmark queries.

### Anthropic / Claude(W4 task)

```bash
export METAGENT_LLM_PROVIDER=anthropic
export ANTHROPIC_API_KEY="sk-ant-..."
```

**W4 work**:add Anthropic provider branch to `common/llm_client.py:_configure_openai()`
(rename to `_configure_provider()` for clarity).Pattern same as OpenAI:lazy import +
ChatCompletion-shaped API surface via the Anthropic Messages API adapter.

---

## W3 D4 wire-up verification

```bash
cd metagent_day1_v5_investigation
PYTHONPATH=. /home/weiwentao/miniconda3/envs/mummichog_py310/bin/python \
    -m pytest tests/concord/test_llm_provider_gpt4o.py -v
```

Expected:**4 pass**(structural — no network).

---

## W11 evaluation plan(reference)

W11 head-to-head will:
1. Pick **N=60-100 tasks**(extension of N=22 unique from Session 4)
2. Run **ConcordMet pipeline + LLM coordination** with each provider
3. Compare:
   - Pathway top-10 Jaccard(across providers,same task)— measures LLM disagreement
   - Compound reconciliation accuracy(against §8 ground-truth)
   - Wall time / cost per task

**Budget pre-estimate**:
- 100 tasks × ~5K token avg per pipeline call × 3 providers ≈ 1.5M token
- @ $10/1M(GPT-4o output mix)≈ **$15-25 total** for W11 evaluation
- Approved-with-cap envelope for paper-level statistic.

---

## Q-06 escalation(2026-05-15)

**Pending user decision before W11**:
- (a) Generate dedicated OpenAI / Anthropic API keys via lab account + load into env on
  the main repo path(`api_key_gpt.txt`,`api_key_claude.txt`)
- (b) Use shared lab keys with rate-limit guard
- (c) W11 evaluator runs from a different machine with personal keys

Investigation Session 4 verified the LLM-client wire-up via mock — **no real
GPT-4o call has been made** as of W3 close.

# Cross-LLM Narrative Routing Implementation

Session: `track_EVAL_sub6_v2_cross_llm_routing`
Branch: `feature/sub6-v2-cross-llm`
Date: 2026-05-06

## 1. CLI Design

Added narrative LLM selector:

```bash
--narrative-llm {minimax|gpt55|opus47}
```

Default is `minimax`.

Mapping:

| CLI value | Provider | Model |
|---|---|---|
| `minimax` | `minimax` | `MiniMax-M2.7` |
| `gpt55` | `openai` | `gpt-5.5` |
| `opus47` | `openai` | `claude-opus-4-7` |

Entrypoints updated:

- `scripts/eval_sub6/run_baseline.py`
- `evaluation/sub6/run_sub6a.py`
- `evaluation/sub6/run_sub6b.py`

Compatibility additions in `run_baseline.py`:

- `--max-tasks` aliases existing `--limit`.
- `--output` aliases existing `--out-dir`.
- `--sub6a` / `--sub6b` can still be boolean flags, or can accept a JSONL path directly.

## 2. Routing Implementation

`common.llm_client` read `METAGENT_LLM_PROVIDER`, `METAGENT_OPENAI_MODEL`,
`METAGENT_OPENAI_BASE_URL`, `DEFAULT_MODEL`, and `DEFAULT_MAX_TOKENS` at import time.
Because `run_baseline.py` previously imported `llm_client` before CLI parsing,
changing env vars inside `main()` was not sufficient for robust same-process routing.

Implementation choice:

- Keep env vars for provenance and default viviai relay configuration.
- Add backward-compatible per-call `provider` support to `llm_client.chat()` /
  `chat_raw()`.
- Pass `model` and `provider` from Sub-6 runners into `chat()`.
- Compute provider-specific default `max_tokens` at call time when `max_tokens`
  is omitted.

`llm_client.py` was changed minimally but more than 1-2 physical lines because
both `chat()` and `chat_raw()` signatures plus the wire-level `max_tokens` /
`max_completion_tokens` branch needed to honor the per-call provider.

One retry was added around narrative LLM calls in Sub-6A/Sub-6B and enabled by
the CLIs, matching the known viviai transient SSL/relay failure profile.

Prompt templates, verifier code, and metric calculation were not changed.

## 3. Smoke Test Results

Task:

```text
compound_only_enrich_mammalian_RAMP_P_000052855_seed0
```

Commands run:

```bash
python scripts/eval_sub6/run_baseline.py \
  --sub6b data/benchmark/sub6/sub6b_mammalian_tasks_v2.jsonl \
  --narrative-llm minimax \
  --output /tmp/cross_llm_smoke/minimax/ \
  --max-tasks 1

python scripts/eval_sub6/run_baseline.py \
  --sub6b data/benchmark/sub6/sub6b_mammalian_tasks_v2.jsonl \
  --narrative-llm opus47 \
  --output /tmp/cross_llm_smoke/opus47/ \
  --max-tasks 1

python scripts/eval_sub6/run_baseline.py \
  --sub6b data/benchmark/sub6/sub6b_mammalian_tasks_v2.jsonl \
  --narrative-llm gpt55 \
  --output /tmp/cross_llm_smoke/gpt55/ \
  --max-tasks 1
```

Outputs:

| LLM | Output file | `llm_model` | Narrative chars | Wall time | SHA-256 prefix | Error |
|---|---|---|---:|---:|---|---|
| MiniMax | `/tmp/cross_llm_smoke/minimax/sub6b_narratives.jsonl` | `MiniMax-M2.7` | 4258 | 64.27s | `effeba040a71` | None |
| Opus | `/tmp/cross_llm_smoke/opus47/sub6b_narratives.jsonl` | `claude-opus-4-7` | 2806 | 15.12s | `98bce76d4ff4` | None |
| GPT-5.5 | `/tmp/cross_llm_smoke/gpt55/sub6b_narratives.jsonl` | `gpt-5.5` | 2380 | 34.68s | `12bda5627a1a` | None |

The three narrative hashes differ, so the runs did not silently collapse to
the same cached/default MiniMax narrative.

Observed retry behavior:

- Initial Opus run used the GPT key fallback and failed with relay permission
  for `claude-opus-4-7`; fallback was corrected to prefer `api_key_claude.txt`
  for Claude models, then the rerun succeeded.
- GPT-5.5 first attempt logged `KeyError: 'content'`; the built-in one retry
  succeeded.

Token footprint from `logs/llm_calls.jsonl`:

| Model | Prompt tokens | Completion tokens | Total tokens |
|---|---:|---:|---:|
| `MiniMax-M2.7` | 361 | 2398 | 2759 |
| `claude-opus-4-7` | 7653 | 856 | 8509 |
| `gpt-5.5` successful attempt | 374 | 651 | 1025 |
| `gpt-5.5` failed first attempt | 372 | 0 | 372 |

Cost estimate: exact viviai billing rates were not queried in this phase. The
measured smoke footprint is small: about 12.7k logged tokens including the
failed GPT-5.5 attempt.

## 4. Phase 3.2 Handoff

Full Sub-6B v2 63-task commands:

```bash
python scripts/eval_sub6/run_baseline.py \
  --sub6b data/benchmark/sub6/sub6b_mammalian_tasks_v2.jsonl \
  --narrative-llm minimax \
  --output data/eval/sub6/cross_llm/minimax/

python scripts/eval_sub6/run_baseline.py \
  --sub6b data/benchmark/sub6/sub6b_mammalian_tasks_v2.jsonl \
  --narrative-llm opus47 \
  --output data/eval/sub6/cross_llm/opus47/

python scripts/eval_sub6/run_baseline.py \
  --sub6b data/benchmark/sub6/sub6b_mammalian_tasks_v2.jsonl \
  --narrative-llm gpt55 \
  --output data/eval/sub6/cross_llm/gpt55/
```

For Sub-6A, replace `--sub6b ...sub6b_mammalian_tasks_v2.jsonl` with
`--sub6a data/benchmark/sub6/sub6a_e2e_tasks.jsonl`.

Rough wall-time projection from 1-task smoke:

- MiniMax: about 67 minutes for 63 tasks.
- Opus-4-7: about 16 minutes for 63 tasks.
- GPT-5.5: about 36-40 minutes for 63 tasks, allowing occasional retry.
- Sequential total: about 2 hours; relay variance may dominate.

Rough token projection from the smoke task:

- MiniMax: about 174k total tokens for 63 tasks.
- Opus-4-7: about 536k total tokens for 63 tasks.
- GPT-5.5: about 65k successful-attempt tokens, plus retry overhead.

## 5. Provenance and Diff Stat

Focused diff stat for this session:

```text
common/llm_client.py                         |  22 +-
evaluation/sub6/run_sub6a.py                 | 136 +++-
evaluation/sub6/run_sub6b.py                 | 118 ++-
scripts/eval_sub6/run_baseline.py            | 124 ++-
tests/eval_sub6/test_cross_llm_routing.py    |  mocked routing tests added
reports/eval/cross_llm_routing_implementation.md | added
```

The working tree already contained unrelated verifier/report changes before
this session; they were not reverted or edited for this work.

## 6. Acceptance Checklist

- [x] `--narrative-llm` accepted by `run_baseline.py`.
- [x] `--narrative-llm` accepted by `run_sub6a.py`.
- [x] `--narrative-llm` accepted by `run_sub6b.py`.
- [x] 1-task MiniMax smoke succeeded.
- [x] 1-task Opus-4-7 smoke succeeded.
- [x] 1-task GPT-5.5 smoke succeeded.
- [x] `llm_model` fields are correct.
- [x] Three narrative contents differ.
- [x] Unit tests pass: `pytest tests/eval_sub6 -q` => 72 passed.
- [x] Prompt templates untouched.
- [x] Verifier and metric calculation untouched.

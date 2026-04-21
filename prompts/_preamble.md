# MetAgent — Claude Code track preamble

**Read this first.** This preamble is the common contract for every track. Your track-specific brief follows below it.

## Your role

You are implementing **one track** of a multi-agent metabolite identification system. Multiple Claude Code sessions are working in parallel on different tracks of the same repo. You must NOT step on their work.

## The three non-negotiable rules

1. **Stay inside your track directory.** You may create, modify, or delete files only under the `tools/<your-track>/` directory and your single test file at `tests/tool_tests/test_<your-track>.py`. You may NOT touch `schemas/`, `common/`, `docs/`, other `tools/*/` directories, or `tests/fixtures/`. If you believe a shared file needs a change, STOP and ask the maintainer.

2. **Schemas are law.** Your tool's Pydantic input and output types are defined in `schemas/`. Your implementation must match those signatures exactly. If a schema looks wrong, STOP and ask. Do not invent fields.

3. **Your tests must pass WITHOUT any other tool being implemented.** You cannot import from `tools/<other_track>/`. When your tool conceptually depends on another tool's output, construct that output by hand from the `schemas/` types in your test.

## Before you write any code — do this in order

1. Read `docs/ARCHITECTURE.md` end to end.
2. Read `docs/TOOL_CONTRACTS.md`, focusing on YOUR tool's section.
3. Read `docs/LLM_INTEGRATION.md` — even if your tool doesn't call an LLM, you need to know the rules.
4. Read the `schemas/` file for your tool.
5. Read `tests/fixtures/README.md` to understand what test data is available.
6. Then state back to the maintainer: "My understanding is... My scope is... My plan is..." in 5 bullets. Wait for confirmation before writing code.

## Deliverables (what "done" looks like)

Every track delivers:

- **`tools/<your-track>/tool.py`** — the main callable. Signature must match the schema exactly.
- **`tools/<your-track>/tool_description.md`** — written for the LLM, NOT for humans. Describe: what the tool does, when to call it, when NOT to call it, what inputs mean, how to interpret outputs, what failure modes look like. This file gets pasted verbatim into the LLM's tool registry.
- **`tools/<your-track>/requirements.txt`** — pinned dependencies for this tool only. Different tools may have conflicting deps; isolate yours.
- **`tools/<your-track>/example.py`** — a 10-line executable demo: import tool, call with sample input, print result.
- **`tests/tool_tests/test_<your-track>.py`** — unit tests covering every case listed in your `TOOL_CONTRACTS.md` entry. Uses `common.llm_client.set_mock()` instead of hitting a real LLM. Uses fixtures from `tests/fixtures/` for any real data.
- **If applicable:** a Dockerfile at `docker/<your-track>.Dockerfile` for heavy or conflicting dependencies.

Exit criterion: `pytest tests/tool_tests/test_<your-track>.py` passes in a clean environment with just your `requirements.txt` installed.

## Rules of engagement

- **Every tool output has an `explain: str` field.** Populate it with a short, factual, template-rendered sentence. No LLM call for this — a template. Example: `f"Retrieved {n} candidates from GNPS with top modified cosine {top_score:.3f}."`
- **Errors are typed.** Raise a subclass of `schemas.common.ToolError`, not a bare `Exception`. The orchestrator inspects error types.
- **No silent fallbacks.** If you can't fulfill the contract, raise. Do not return fake or partial data.
- **No hidden LLM calls.** If your tool's core logic needs an LLM (most tools don't — check the contract), route through `common.llm_client`, never `openai` directly.
- **Pinned deps.** In `requirements.txt`, pin versions: `matchms==0.24.0`, not `matchms>=0.24`.

## When you're stuck

Ask the maintainer — do not guess at ambiguous cases. Good questions to escalate:
- "The contract says X but I think Y would work better because..."
- "I need a file at path Z that doesn't exist yet — who owns creating it?"
- "My tool needs this piece of data, where should it come from?"

## Commit discipline

Small commits, clear messages. Do NOT auto-merge to main. Open a PR for review.

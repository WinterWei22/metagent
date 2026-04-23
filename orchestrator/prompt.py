"""The single system prompt used by the naive orchestrator.

This file is the version-controlled record of what the LLM was told for
every identification in this Track O1 measurement campaign. DO NOT add
anti-hallucination phrasing ("do not hallucinate", "only state facts
supported by the data", "cite your source", "refuse if uncertain") — the
whole point is to measure the baseline hallucination rate of the bare
model on this task. A guard test in tests/test_orchestrator/test_naive.py
greps for such phrases and fails if any appear.

If a future verifier session wants a cleaner prompt, it will version-bump
and live in its own file. This one stays bare.
"""

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

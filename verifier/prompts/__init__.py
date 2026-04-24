"""Verifier prompts. Each module exposes ``SYSTEM_PROMPT`` and a ``build(...)``
function returning the user message string.

No file in this package contains anti-hallucination phrasing — the extractor
and classifier are deterministic *about claims*, but the LLM is not asked to
self-police. Verification is enforced by deterministic layers downstream.
"""

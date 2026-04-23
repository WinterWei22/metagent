"""Markdown post-processing for the LLM narrative panel (stub, Part 1).

Intentionally minimal. The orchestrator delivery explicitly says the UI
renders LLM output *verbatim* — so this module stays small. Anything
here must be non-semantic (e.g. anchor IDs for table rows, nothing that
changes the text the reviewer sees).
"""
from __future__ import annotations

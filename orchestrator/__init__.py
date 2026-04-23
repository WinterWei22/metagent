"""Naive orchestrator package (Track O1).

Minimum LLM wrapper over an IdentificationReport. Exactly one chat() call
per identification, no parsing, no retries, no anti-hallucination control.
See prompts/track_01_naive_orchestrator.md for the full brief.
"""
from orchestrator.naive import identify
from orchestrator.schemas import NaiveIdentification

__all__ = ["identify", "NaiveIdentification"]

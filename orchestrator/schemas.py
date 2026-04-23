"""Output schema for the naive orchestrator.

Minimal by design: no parsed fields, no `top_candidate`, no `confidence`.
The whole point of Track O1 is to see what the LLM says without coercing
it into a structure — the natural-language string is the data.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class NaiveIdentification(BaseModel):
    """One-shot LLM output plus the minimal metadata to join it later.

    `trace_id` matches the `trace_id` field in the corresponding row of
    logs/llm_calls.jsonl. `source_report_hash` is a deterministic digest
    of the input IdentificationReport so that reruns on the same report
    can be grouped. Together these let an evaluation pipeline correlate
    the LLM output with its prompt, the pipeline output, and the call
    record without re-running anything.
    """

    trace_id: str = Field(
        ...,
        description="Identifier shared with the JSONL log line for this call.",
    )
    source_report_hash: str = Field(
        ...,
        description=(
            "First 16 hex chars of SHA-256 over the IdentificationReport's "
            "JSON serialisation. Stable across reruns with the same report."
        ),
    )
    llm_output: str = Field(
        ...,
        description=(
            "Raw LLM text after strip_thinking(). No JSON extraction, no "
            "format coercion — if the model produced garbage, that garbage "
            "is preserved verbatim here."
        ),
    )
    generated_at: datetime = Field(
        ...,
        description="UTC timestamp at which identify() returned.",
    )

"""Top-level naive-orchestrator entry.

The entire session's design is distilled in `identify()`: build the prompt,
call the LLM once, return whatever came back. No parsing, no retries, no
anti-hallucination control, no cascade. See prompts/track_01_naive_orchestrator.md.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from common.llm_client import chat
from orchestrator.formatter import format_report_for_llm
from orchestrator.prompt import SYSTEM_PROMPT
from orchestrator.schemas import NaiveIdentification
from schemas.report import IdentificationReport


CALLER = "orchestrator.naive.identify"


def identify(
    report: IdentificationReport,
    *,
    trace_id: str | None = None,
) -> NaiveIdentification:
    """Run one LLM call over `report` and return the output verbatim.

    If `trace_id` is None, an auto trace_id of the form
    ``ident_<hash8>_<YYYYMMDDHHMMSS>`` is generated. Reruns on the same
    report with an auto trace_id will produce the same hash prefix but
    a different timestamp suffix.
    """
    report_hash = hash_report(report)
    effective_trace_id = trace_id or _auto_trace_id(report_hash)
    user_message = format_report_for_llm(report)

    llm_output = chat(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        trace_id=effective_trace_id,
        caller=CALLER,
    )
    return NaiveIdentification(
        trace_id=effective_trace_id,
        source_report_hash=report_hash,
        llm_output=llm_output,
        generated_at=datetime.now(timezone.utc),
    )


def hash_report(report: IdentificationReport) -> str:
    """Deterministic digest over the report's JSON body (first 16 hex chars)."""
    blob = report.model_dump_json().encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def _auto_trace_id(report_hash: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"ident_{report_hash[:8]}_{ts}"

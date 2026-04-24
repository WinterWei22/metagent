"""Track V — verifier package.

Designed against the eight measured hallucination notes (H1–H8) recorded in
``reports/orchestrator_naive_v0_delivery_2026-04-23.md``. Architecturally
independent from ``orchestrator/``: the public entry point ``verify()`` takes
``(llm_output, source_report, trace_id)`` — three loose values that any
caller can produce — and returns a ``VerifiedIdentification``. Verifier code
must NOT import from ``orchestrator.*``.
"""

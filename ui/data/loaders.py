"""Cached-run discovery for the UI (stub, Part 1).

Populated in the Panel 1/2/3 content commit. Intended lookup order:

    1. /data/weiwentao/llm_agent_metabolomics/pipeline_runs/<trace_id>.json
       — durable UI-managed cache (Live-mode runs land here)
    2. /tmp/o1/<fixture>.json
       — Track O1 session leftovers (not guaranteed across reboots)
    3. reports/pipeline_runs/<trace_id>.json
       — in-repo location; not recommended for large files but supported

LLM rows always come from logs/llm_calls.jsonl filtered to
caller == "orchestrator.naive.identify".
"""
from __future__ import annotations

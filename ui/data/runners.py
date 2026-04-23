"""Live-mode pipeline + LLM wrappers (stub, Part 1).

Populated in the Live-mode commit. Plan:

- Pipeline stage: subprocess `conda run -n diffms python
  scripts/run_full_pipeline.py --fixture <name> --output json`; strip the
  matchms stdout-warning prefix; persist to
  /data/weiwentao/llm_agent_metabolomics/pipeline_runs/<trace_id>.json.
- LLM stage: in-process `orchestrator.naive.identify(report)`; rely on
  its JSONL logger for the call record.

Live mode is gated on a pre-flight env check (MINIMAX_API_KEY +
METAGENT_HMDB_PATH + METAGENT_RAMP_PATH + METAGENT_CFM_URL +
METAGENT_GNPS_PATH + METAGENT_GNPS_SPECTRA_PATH +
METAGENT_PUBCHEM_LITE_PATH). Any missing var disables the toggle.
"""
from __future__ import annotations

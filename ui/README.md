# MetAgent demo UI (Track UI1)

Gradio-based local demo that wraps the naive orchestrator (Track O1) for
reviewer-facing walkthroughs. **Viewer, not a tool.** Reads cached runs
from disk by default; Live mode (pipeline + LLM) is opt-in and gated on
backend environment variables.

> **v0 layout-review build.** The four panels are shaped but empty in
> this commit — content lands in follow-up commits per maintainer review.

## Install (one-time)

UI runs in the `metagent-llm` conda env. From the repo root:

```bash
conda run -n metagent-llm pip install -r ui/requirements.txt
```

This installs Gradio 5, RDKit, matplotlib, and `socksio` (for the
SOCKS-proxied httpx used by Gradio). All other deps (openai, tiktoken,
pydantic) are already present from Track O1 Part 1.

## Launch

Basic (cached-only mode — the default):

```bash
conda run -n metagent-llm python -m ui.app
```

With Live mode enabled (requires every backend env var + MiniMax key):

```bash
METAGENT_HMDB_PATH=/data/weiwentao/llm_agent_metabolomics/hmdb.sqlite \
METAGENT_RAMP_PATH=/data/weiwentao/llm_agent_metabolomics/ramp.sqlite \
METAGENT_CFM_URL=http://127.0.0.1:8088 \
METAGENT_GNPS_PATH=/data/weiwentao/llm_agent_metabolomics/gnps/ALL_GNPS_cleaned_enriched.csv \
METAGENT_GNPS_SPECTRA_PATH=/data/weiwentao/llm_agent_metabolomics/gnps/ALL_GNPS_cleaned.mgf \
METAGENT_PUBCHEM_LITE_PATH=/data/weiwentao/llm_agent_metabolomics/pubchem_lite.sqlite \
MINIMAX_API_KEY="$(cat api_key.txt)" \
conda run -n metagent-llm python -m ui.app --enable-live
```

Pick a different port with `--port 8000`. The server binds to
`127.0.0.1`; reach it remotely via SSH tunnel, e.g.
`ssh -L 7860:localhost:7860 <server>`.

## Where data comes from

Cached-run discovery order (first hit wins):

1. `/data/weiwentao/llm_agent_metabolomics/pipeline_runs/<trace_id>.json`
   — durable UI-managed cache; Live-mode runs write here.
2. `/tmp/o1/<fixture>.json` — Track O1 Part 4 leftovers, not persistent
   across reboots.
3. `reports/pipeline_runs/<trace_id>.json` — in-repo location; supported
   but not recommended for pipeline outputs (large, environment-specific
   `tool_versions` paths).

LLM call rows always come from `logs/llm_calls.jsonl`, filtered to
`caller == "orchestrator.naive.identify"`.

## Scope

- No file upload in v0 (three fixtures are enough for the demo).
- No auth — local-only build.
- No new LLM calls from the UI layer. The "Show prompt sent to LLM"
  button displays the already-logged `messages`; it does not regenerate.
- Panel 4 (Verifier) is a PREVIEW placeholder. The verifier itself is a
  separate track scheduled for v0.2.

# MetAgent service-discovery env for predict_spectrum (Track E).
# Source this file; do not execute it.
#
# Usage (one-off, current shell only):
#
#     source /home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5/tools/spectrum_predict/env.sh
#
# Usage (persistent, all future shells):
#
#     echo 'source /home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5/tools/spectrum_predict/env.sh' >> ~/.bashrc
#     source ~/.bashrc
#
# The CFM-ID HTTP shim is NOT started by this script — launching long-lived
# services is the operator's / orchestrator's job (see docker/README_CFM.md).
# This file only exports the URL the Python tool resolves at call time.

# Where tools/spectrum_predict/cfm_client.py expects the HTTP shim.
# Change this (or `export` a different value before sourcing) to point at a
# remote CFM-ID deployment — the Python tool does not care whether the URL
# resolves to a local udocker container or to a shared service on another box.
export METAGENT_CFM_URL="${METAGENT_CFM_URL:-http://127.0.0.1:8088}"

# Sanity check: warn (don't fail) if the shim does not answer /healthz, so
# the caller still gets the export but knows the service is down. This is
# the same pattern used by tools/candidate_prefilter/env.sh.
if command -v curl >/dev/null 2>&1; then
    if ! curl -fsS --max-time 2 "${METAGENT_CFM_URL}/healthz" >/dev/null 2>&1; then
        echo "warning: METAGENT_CFM_URL=${METAGENT_CFM_URL} did not answer /healthz." >&2
        echo "         Start the shim per docker/README_CFM.md:" >&2
        echo "           python -m uvicorn docker.cfm_shim_host:app --host 127.0.0.1 --port 8088 &" >&2
    fi
fi

# MetAgent data-path env for candidate_prefilter (and library_search).
# Source this file; do not execute it.
#
# Usage (one-off, current shell only):
#
#     source /home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5/tools/candidate_prefilter/env.sh
#
# Usage (persistent, all future shells):
#
#     echo 'source /home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5/tools/candidate_prefilter/env.sh' >> ~/.bashrc
#     source ~/.bashrc
#
# Edit _DATA_ROOT below if your data directory is elsewhere.

_DATA_ROOT="/data/weiwentao/llm_agent_metabolomics"

# Local compound pool (HMDB + PubChemLite for Exposomics), built on 2026-04-22.
# See README_PUBCHEM_SETUP.md for the rebuild procedure.
export METAGENT_PUBCHEM_LITE_PATH="${_DATA_ROOT}/pubchem_lite.sqlite"

# GNPS reference library (CSV path — the cleaned_enriched variant has all
# fields candidate_prefilter needs). MGF companion is for library_search.
export METAGENT_GNPS_PATH="${_DATA_ROOT}/gnps/ALL_GNPS_cleaned_enriched.csv"

unset _DATA_ROOT

# Sanity check: warn (don't fail) if either file is missing, so the caller
# still gets the export but is alerted to a broken install.
for _var in METAGENT_PUBCHEM_LITE_PATH METAGENT_GNPS_PATH; do
    if [ ! -e "${!_var}" ]; then
        echo "warning: ${_var}=${!_var} does not exist" >&2
    fi
done
unset _var

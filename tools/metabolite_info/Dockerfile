# HMDB build image for fetch_metabolite_info.
#
# Use this image to produce the hmdb.sqlite file that the tool's runtime
# reads via METAGENT_HMDB_PATH. The container does NOT serve queries at
# runtime — the tool is imported directly by the orchestrator process.
#
# Build:
#   docker build -f tools/metabolite_info/Dockerfile -t metagent/hmdb-build .
#
# Run once to ingest (mount the XML and the target SQLite dir):
#   docker run --rm \
#       -v /data/hmdb:/data \
#       metagent/hmdb-build \
#       python -m tools.metabolite_info.build_hmdb_db \
#           --xml /data/hmdb_metabolites.xml \
#           --out /data/hmdb.sqlite
#
# The public HMDB XML lives at https://hmdb.ca/downloads — version
# 5.0 is the reference release at time of writing.

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Only this tool's deps: lxml (ingest), requests (runtime PubChem fallback),
# pydantic (schema). rdkit is NOT required by this tool.
COPY tools/metabolite_info/requirements.txt /tmp/metabolite_info_requirements.txt
RUN pip install --no-cache-dir -r /tmp/metabolite_info_requirements.txt

# Copy just the packages we need: schemas for the contract, common for the
# MoNA loader, tools/metabolite_info for the ingest + query code.
COPY schemas /app/schemas
COPY common  /app/common
COPY tools/metabolite_info /app/tools/metabolite_info

# Keep the tool importable as `tools.metabolite_info`.
RUN touch /app/tools/__init__.py

ENV PYTHONPATH=/app

CMD ["python", "-m", "tools.metabolite_info.example"]

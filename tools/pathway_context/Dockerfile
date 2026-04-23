# RaMP-DB staging image for pathway_context.
#
# The RaMP-DB release is distributed as a pre-built SQLite file, so there
# is no ingest script to run. This image simply installs the runtime
# dependencies and documents the download procedure — its CMD runs the
# tool's example.py so `docker run` sanity-checks the wiring end-to-end.
#
# Build:
#   docker build -f tools/pathway_context/Dockerfile -t metagent/pathway-context .
#
# Run with the DB mounted:
#   docker run --rm \
#       -v /data/ramp:/data/ramp \
#       -e METAGENT_RAMP_PATH=/data/ramp/ramp.sqlite \
#       metagent/pathway-context
#
# Download instructions (perform on the host, not inside the container):
#   curl -L -o /data/ramp/ramp.sqlite \
#       "https://github.com/ncats/RaMP-DB/releases/download/<VERSION>/ramp.sqlite"
# The latest release tag is the source of truth; do not pin here because
# RaMP's release cadence changes the filename occasionally.

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY tools/pathway_context/requirements.txt /tmp/pathway_context_requirements.txt
RUN pip install --no-cache-dir -r /tmp/pathway_context_requirements.txt

COPY schemas /app/schemas
COPY common  /app/common
COPY tools/pathway_context /app/tools/pathway_context

RUN touch /app/tools/__init__.py

ENV PYTHONPATH=/app

CMD ["python", "-m", "tools.pathway_context.example"]

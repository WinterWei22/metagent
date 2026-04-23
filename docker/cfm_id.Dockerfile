# CFM-ID 4.0 HTTP shim for Track E (`predict_spectrum`).
#
# The Wishart Lab ships a Docker image (`wishartlab/cfmid:latest`) that bundles
# the `cfm-predict` binary plus the pre-trained ESI+/ESI- models. It runs as a
# CLI tool — this Dockerfile layers a tiny FastAPI wrapper on top so the
# Python `tools.spectrum_predict` package can speak HTTP to it.
#
# Shim contract (must stay in sync with `tools/spectrum_predict/cfm_client.py`):
#
#   POST /predict
#     { "smiles": str, "adduct": str, "ionization_mode": "positive"|"negative",
#       "timeout_seconds": float }
#   → { "model_version": str, "cfm_stdout": str }
#
#   GET /healthz → 200 "ok"
#
# Build:
#   docker build -f docker/cfm_id.Dockerfile -t metagent/cfm-id:v0 .
#
# Run:
#   docker run --rm -d -p 8088:8088 --name metagent-cfmid metagent/cfm-id:v0
#   export METAGENT_CFM_URL=http://localhost:8088
#
# See docker/README_CFM.md for non-root deployment (udocker / podman).

FROM wishartlab/cfmid:latest

# `wishartlab/cfmid:latest` (verified 2026-04-23) is Alpine 3.12, which is
# EOL. The only Python in its repos is 3.8. We install it via apk and then
# layer FastAPI + uvicorn on top. Pin exact versions for reproducibility.
#
# Alpine 3.12 repos have been moved to the archive, so the pkg-manager URL
# has to be rewritten. If `apk update` fails in a future rebuild the mirror
# URL in /etc/apk/repositories is the first place to look.
USER root
RUN sed -i \
        -e 's|dl-cdn.alpinelinux.org/alpine|dl-cdn.alpinelinux.org/alpine-archive/v3.12|g' \
        /etc/apk/repositories 2>/dev/null \
 ; apk update \
 && apk add --no-cache python3 py3-pip ca-certificates curl \
 && rm -rf /var/cache/apk/*

# Isolate the shim's deps in a venv so they cannot collide with anything
# the base image carries (lots of Python-2-era bits still live in /usr).
# Alpine musl sometimes trips pip's manylinux detection; install from
# source is fine here because the three deps are pure-Python.
RUN python3 -m venv /opt/shim \
 && /opt/shim/bin/pip install --no-cache-dir --upgrade pip \
 && /opt/shim/bin/pip install --no-cache-dir \
        fastapi==0.115.0 \
        uvicorn==0.30.6 \
        pydantic==2.8.2

# Expose the binary's path and model directory as env vars so the shim can
# locate them without guessing. These paths were verified against the
# ``wishartlab/cfmid:latest`` image pulled on 2026-04-23 — the binary is at
# ``/opt/cfm/bin/cfm-predict`` and models live at ``/trained_models_cfmid4.0/
# [M+H]+/`` and ``.../[M-H]-/``. Update here if the base image layout changes.
ENV CFM_PREDICT_BIN=/opt/cfm/bin/cfm-predict \
    CFM_MODEL_DIR=/trained_models_cfmid4.0 \
    CFM_VERSION=cfm-id-4.4.7 \
    SHIM_PORT=8088

WORKDIR /opt/shim
COPY docker/cfm_shim.py /opt/shim/cfm_shim.py

EXPOSE 8088
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:${SHIM_PORT}/healthz || exit 1

# Run as a non-root user by default so the image behaves identically when
# launched via a rootless runtime (podman, udocker). Alpine's `adduser` is
# the BusyBox equivalent of useradd.
RUN adduser -D -s /bin/sh cfm \
 && chown -R cfm:cfm /opt/shim
USER cfm

CMD ["/opt/shim/bin/uvicorn", "cfm_shim:app", "--host", "0.0.0.0", "--port", "8088"]

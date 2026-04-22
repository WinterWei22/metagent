# SIRIUS + CSI:FingerID container for molecule_generate (Track C).
#
# Stage 1 of the Track C pipeline: spectrum -> fingerprint. The MS-BART decoder
# stage is NOT in this image; it runs in the `ms-bart` conda env on the host
# and is invoked by the tool via `conda run`.
#
# Usage from the host:
#
#   docker build -f docker/molecule_gen.Dockerfile -t metagent/sirius:v0 .
#   docker run --rm -v $PWD/.sirius-work:/work metagent/sirius:v0 \
#       sirius -i /work/query.ms -o /work/out formula fingerprint
#
# The SiriusFingerprinter adapter expects a `sirius` binary on PATH. Deploy a
# thin wrapper on the host (e.g. /usr/local/bin/sirius) that forwards argv to
# `docker run` on this image, then export METAGENT_SIRIUS_BIN pointing at it.
#
# CSI:FingerID requires a free SIRIUS account for license activation; see
# https://v6.docs.sirius-ms.io/install/ for the one-time login step. The login
# token lives under /root/.sirius and should be persisted via a named volume.

FROM eclipse-temurin:17-jre-jammy

ARG SIRIUS_VERSION=6.0.7
ARG SIRIUS_DIST_URL=https://github.com/sirius-ms/sirius/releases/download/v${SIRIUS_VERSION}/sirius-${SIRIUS_VERSION}-linux64-headless.zip

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl unzip ca-certificates \
 && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/sirius \
 && curl -L -o /tmp/sirius.zip "${SIRIUS_DIST_URL}" \
 && unzip -q /tmp/sirius.zip -d /opt \
 && rm /tmp/sirius.zip \
 && ln -s /opt/sirius/bin/sirius /usr/local/bin/sirius

VOLUME ["/root/.sirius", "/work"]
WORKDIR /work

ENTRYPOINT ["sirius"]
CMD ["--help"]

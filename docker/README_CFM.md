# CFM-ID 4.0 container — deployment guide

This image wraps the Wishart Lab's `cfm-predict` binary with a minimal
FastAPI HTTP shim so the Track E tool (`predict_spectrum`) can invoke it
over the network. The Python client in `tools/spectrum_predict/cfm_client.py`
and the shim in `docker/cfm_shim.py` share one contract — update both together.

## Shim contract

```
POST /predict   { smiles, adduct, ionization_mode, timeout_seconds }
              → { model_version, cfm_stdout }
GET  /healthz → 200 { "status": "ok", "model_version": "cfm-id-4.0.0" }
```

`cfm_stdout` is the raw text output of `cfm-predict`. The Python client does
the parsing (see `tools/spectrum_predict/parser.py`), so the shim stays
transport-only.

## Build & run (privileged Docker)

```bash
docker build -f docker/cfm_id.Dockerfile -t metagent/cfm-id:v0 .
docker run --rm -d -p 8088:8088 --name metagent-cfmid metagent/cfm-id:v0
export METAGENT_CFM_URL=http://localhost:8088
curl -fsS "$METAGENT_CFM_URL/healthz"   # expect {"status":"ok",...}
pytest tests/tool_tests/test_spectrum_predict.py -m integration
```

Build takes ~10 min the first time (the base image is ~2.5 GB). Steady-state
memory at idle is ~100 MB; per-request memory is ~300 MB per `cfm-predict`
invocation.

## Non-root deployment

If the host does not grant Docker access (typical on shared compute), pick
one of these rootless paths. The Python client does not care which runner
serves the HTTP endpoint — only that `METAGENT_CFM_URL` points somewhere
live.

### Option 1 — udocker + host-side shim (verified 2026-04-23)

The fastest path on a box where you have neither `sudo` nor `docker` group
membership. `udocker` is a pure-Python runner (not a builder), and the
`wishartlab/cfmid:latest` base image contains no Python interpreter — so
we cannot build a Dockerfile layer that adds FastAPI. Instead, run the
FastAPI shim **on the host** (`docker/cfm_shim_host.py`) and let it shell
out to `udocker run` for each prediction.

The client in `tools/spectrum_predict/cfm_client.py` cannot tell the
difference between this deployment and the native-Docker one.

One-time setup:

```bash
# Install udocker itself.
pip install --user udocker
udocker install                                        # fetches proot/runc/crun

# If Docker Hub's blob registry is blocked in your region, point udocker
# at a working mirror. (`docker.registry.cyou` worked from mainland China
# on 2026-04-23 without authentication.) On an unrestricted network, drop
# the --registry flag.
udocker pull --registry=https://docker.registry.cyou wishartlab/cfmid:latest

# Create a named container instance and select an execution mode. P1
# (proot, single-threaded) works without any host privileges and was the
# verified mode.
udocker create --name=metagent-cfmid wishartlab/cfmid:latest
udocker setup --execmode=P1 metagent-cfmid

# Smoke test — glucose [M+H]+ should return three energy blocks.
udocker run metagent-cfmid \
    /opt/cfm/bin/cfm-predict \
    "OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O" \
    0.001 \
    "/trained_models_cfmid4.0/[M+H]+/param_output.log" \
    "/trained_models_cfmid4.0/[M+H]+/param_config.txt"
```

Start the host-side shim (one process, always-on):

```bash
pip install --user -r docker/cfm_shim_host_requirements.txt
python -m uvicorn docker.cfm_shim_host:app --host 127.0.0.1 --port 8088
# In another shell:
export METAGENT_CFM_URL=http://127.0.0.1:8088
curl -fsS "$METAGENT_CFM_URL/healthz"   # { "status": "ok", ... }
pytest tests/tool_tests/test_spectrum_predict.py -v   # 15/15 including integration
```

Knobs the shim picks up from the host environment:

| Env var | Default | Meaning |
|---|---|---|
| `CFM_UDOCKER_CONTAINER` | `metagent-cfmid` | Name passed to `udocker run` |
| `CFM_UDOCKER_BIN` | `udocker` | Path to the `udocker` executable |
| `CFM_VERSION` | `cfm-id-4.4.7` | Reported in `/predict` response |
| `CFM_PREDICT_BIN_IN_CONTAINER` | `/opt/cfm/bin/cfm-predict` | Binary inside the image |
| `CFM_MODEL_DIR_IN_CONTAINER` | `/trained_models_cfmid4.0` | Model tree inside the image |

Caveats:

- `udocker` in P1 (proot) mode runs ~2× slower than native Docker. A
  single glucose prediction took ~3 s wall time on the test box; batch
  workloads should switch to native Docker or Podman.
- `udocker run --publish` is not supported in P1 mode. The host-side shim
  sidesteps this: the shim binds its own socket on the host and invokes
  the CFM-ID binary via `udocker run <container> <cmd>` — no TCP port on
  the container is needed.
- The first `udocker run` per container boot is slow (~10 s) because
  proot primes its ELF loader cache. Subsequent invocations are fast.
- udocker prints a `****** STARTING <id> ******` banner around the inner
  program's stdout. The host shim strips this before returning, so the
  Python client sees only `cfm-predict` output.

### Option 1b — udocker + in-container shim (untested)

If the base image happened to ship Python 3 + pip (wishartlab's does not
as of 2026-04-23, but future rebuilds might), you could mount
`cfm_shim.py` into the container and run uvicorn there:

```bash
udocker setup --execmode=F1 metagent-cfmid    # F-mode supports --publish
udocker run --publish=8088:8088 \
    --volume=$(pwd)/docker/cfm_shim.py:/opt/shim/cfm_shim.py \
    metagent-cfmid \
    sh -c "pip install fastapi==0.115.0 uvicorn==0.30.6 pydantic==2.8.2 \
           && uvicorn cfm_shim:app --host 0.0.0.0 --port 8088"
```

This is the same shim that the Dockerfile bakes in, just wired up by
hand. Skip this path unless you have a specific reason to avoid the
host-side shim.

### Option 2 — rootless Podman

Needs a one-time system setup (requires sudo from an administrator, but no
ongoing root privileges):

```bash
# Administrator (once):
sudo apt-get install -y podman slirp4netns fuse-overlayfs uidmap
# Make sure /etc/subuid and /etc/subgid contain entries for your user.

# User:
podman build -f docker/cfm_id.Dockerfile -t metagent/cfm-id:v0 .
podman run --rm -d -p 8088:8088 --name metagent-cfmid metagent/cfm-id:v0
export METAGENT_CFM_URL=http://localhost:8088
```

Podman runs unprivileged out of the box once the uidmap packages are present.
This is the cleanest long-term option.

### Option 3 — Apptainer / Singularity (HPC)

For HPC clusters with Apptainer:

```bash
apptainer build cfmid.sif docker://wishartlab/cfmid:latest
# The shim has to be layered in via a definition file; see
# https://apptainer.org/docs/user/latest/definition_files.html
apptainer instance start --bind ./docker/cfm_shim.py:/opt/shim/cfm_shim.py \
    cfmid.sif metagent-cfmid
# Then exec uvicorn inside the instance.
```

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `CfmUnavailableError` immediately on every call | shim not running or wrong URL | `curl $METAGENT_CFM_URL/healthz`; restart shim/container |
| `CfmUnavailableError: HTTP 500: cfm-predict binary not found` | upstream image layout changed | `udocker run metagent-cfmid ls /opt/cfm/bin` — expect `cfm-predict` |
| `CfmUnavailableError: HTTP 500: udocker container 'metagent-cfmid' not found` (host shim only) | `udocker create` was not run | re-run the `udocker create --name=metagent-cfmid …` step |
| `PredictionTimeoutError` on every molecule | shim process is running but `cfm-predict` hangs at startup | `udocker run metagent-cfmid ls /trained_models_cfmid4.0/\[M+H\]+` — the model files should exist |
| Empty `predicted.mz` | model ran but produced no peaks — rare, usually a too-simple molecule | POST to `/predict` directly with `curl` and inspect `cfm_stdout` |
| `udocker: No module named udocker` | `pip install` went to the wrong Python | `python -m pip install --user udocker`, then confirm `which udocker` |
| `udocker pull: SSL_connect: SSL_ERROR_SYSCALL` to `registry-1.docker.io` | Docker Hub blob registry unreachable (DPI / geo block) | use `--registry=https://docker.registry.cyou` (mirror) or switch networks |
| `DENIED: 🚫 ... this image is not in the allowlist` from a mirror | `wishartlab/cfmid` not on that mirror's allowlist | pick a different mirror; DaoCloud / 1Panel / NJU enforce allowlists, `docker.registry.cyou` did not (2026-04-23) |
| `Error: command not found or has no execute bit set: ['bash', ...]` from udocker | base image has no `bash` (Alpine uses BusyBox `sh`) | invoke `sh -c ...` instead of `bash -c ...` |

## Building without docker

If you cannot run `docker build` at all, a common workaround is to build the
image on a workstation that does have docker, push to a registry (Docker Hub
or a private one), then `podman pull` / `udocker pull` on the target host.
Keep the image tagged with the CFM-ID version so rollbacks are trivial.

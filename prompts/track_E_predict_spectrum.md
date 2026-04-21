# Track E: `predict_spectrum`

**Prerequisite:** read `prompts/_preamble.md` first.

## Your scope

You own exactly one tool: **`predict_spectrum`**. Directory: `tools/spectrum_predict/`.

This tool takes a SMILES and forward-predicts what its MS/MS spectrum should look like. It is the **backbone of structural self-verification**: the verifier agent compares your predicted spectrum against the experimental input to score candidate consistency.

## The specific task

Wrap **CFM-ID 4.0** in a local Docker container and expose it as a single function that takes SMILES + conditions and returns a Spectrum. Handle three collision energies (10/20/40 eV by default), merge them into a union spectrum, record the model version.

**Read the full contract:** `docs/TOOL_CONTRACTS.md` → "Tool 7: `predict_spectrum`".

## Why this track is mostly DevOps

CFM-ID is a C++ / C# codebase that's a pain to install natively. The right approach:

1. Use the official CFM-ID Docker image or build one from source.
2. Expose CFM-ID via a minimal HTTP shim inside the container (e.g. a FastAPI wrapper that accepts SMILES and runs `cfm-predict`).
3. Your Python tool calls the container's HTTP endpoint, parses output, wraps in Spectrum.
4. Timeout handling: CFM-ID sometimes hangs; enforce 60s per call and raise `PredictionTimeoutError`.

## What goes into which file

- `tools/spectrum_predict/tool.py` — main `predict_spectrum(req: PredictSpectrumRequest) -> PredictSpectrumResponse`
- `tools/spectrum_predict/cfm_client.py` — HTTP client to the CFM-ID container
- `tools/spectrum_predict/parser.py` — parse CFM-ID's output format into mz/intensity lists
- `tools/spectrum_predict/errors.py` — `InvalidSmilesError`, `PredictionTimeoutError`, `CfmUnavailableError`
- `tools/spectrum_predict/tool_description.md`
- `tools/spectrum_predict/requirements.txt` — `requests`, `rdkit`, `pydantic`
- `tools/spectrum_predict/example.py`
- `docker/cfm_id.Dockerfile` — the container definition
- `docker/README_CFM.md` — how to build and run the container
- `tests/tool_tests/test_spectrum_predict.py`

## Configuration

- `METAGENT_CFM_URL` env var — points to the running container (default `http://localhost:8088`)
- The container's Dockerfile should expose a predictable port and run on startup.
- Your Python tool should NOT try to launch the container itself. Assume it's running.

## Test cases you MUST cover

1. **Glucose prediction works:** given glucose SMILES and `[M+H]+`, `predicted.mz` is non-empty and contains peaks in the expected glucose fragment range (e.g. 163.06 for `[M+H-H2O]+`). Allow a wide tolerance — CFM-ID isn't perfect.
2. **Invalid SMILES:** `"XYZ"` raises `InvalidSmilesError` BEFORE hitting the container (validate with RDKit upfront).
3. **Timeout:** mock the HTTP client to hang → `PredictionTimeoutError` after ~60s. Use a shorter timeout in the test (5s) to keep it fast.
4. **Container down:** mock the HTTP client to refuse connection → `CfmUnavailableError`.
5. **model_version populated:** returned response always has a non-empty `model_version` string like `"cfm-id-4.0.0"`.
6. **Integration test** (`@pytest.mark.integration`): hit a real CFM-ID container with glucose, sanity-check output. Skip if `METAGENT_CFM_URL` unreachable.

## Testing without the container

Use `requests-mock` or a similar library to mock HTTP responses. Construct a realistic CFM-ID output fixture (check the CFM-ID docs for the format) and verify your parser handles it.

## Dependencies you can use

- `requests` — HTTP to CFM-ID container
- `rdkit` — SMILES validation (via `common.rdkit_utils.is_valid_smiles`)
- `pydantic` — schema

## Explicit non-goals

- Do NOT train or modify CFM-ID. You're wrapping it as-is.
- Do NOT add ICEBERG or FIORA support. v0 is CFM-ID only per the contract. ICEBERG is v1.
- Do NOT silently retry a failed prediction. If CFM-ID fails, raise.
- Do NOT cache predictions in this tool. If caching is needed, it belongs in the orchestrator or a separate cache layer.
- Do NOT call an LLM.

## Notes on the container

CFM-ID 4.0 reference: https://cfmid.wishartlab.com/ and https://bitbucket.org/wishartlab/cfm-id-code
An existing community Docker image: `docker pull wishartlab/cfmid:latest` (check it still works in 2026)

If the community image doesn't work, document what you used as a fallback. Worst case, build from source following the BitBucket README — ugly but achievable in an afternoon.

## First action

Before you write code, confirm with the maintainer:
1. Is there an existing CFM-ID container deployed somewhere I should point to?
2. Is it fine to spend a day on Docker plumbing before the Python logic?

If the maintainer says "just mock CFM-ID for now," implement the mock version end-to-end and leave the real Docker work as a follow-up PR.

# `diffms` conda env setup for `library_search`

`tools/library_search/tool.py` subprocesses ms-clip's retrieval CLI via
`conda run -n diffms ...`. This env is **one per deployment machine** and
must be built before `MSClipRetriever` can score candidates. Mirrors the
Track C (`ms-bart`) and Track A2 (`pubchem_lite`) setup docs.

## Required env vars

| Var | Default | What it points at |
|---|---|---|
| `METAGENT_MSCLIP_ENV` | `diffms` | Name of the conda env hosting ms-pred / torch. |
| `METAGENT_MSCLIP_REPO` | `/home/weiwentao/workspace/reconstruct/ms-pred` | Working directory for the subprocess (must contain the ms-pred source tree and `configs/predict_smi.yaml`). |
| `METAGENT_MSCLIP_CKPT` | `/home/weiwentao/workspace/reconstruct/ms-pred/results/v4_spectraverse_20260428_134311/version_0/best.ckpt` | PyTorch Lightning checkpoint consumed by `CLIPModel.load_from_checkpoint`. The current default supports positive **and** negative-mode adducts (spectraverse). The older positive-only `chemformer_v4_large_*` checkpoint is still loadable for regression comparisons; pass it via this env var. |
| `METAGENT_MSCLIP_TIMEOUT` | `1800` (seconds) | Per-subprocess wall-clock budget. |

## Build the env

The upstream `ms-clip` package lives at
`/home/weiwentao/workspace/reconstruct/ms-pred` and declares its
dependencies in `pyproject.toml`. The env we build must satisfy those
plus CUDA-matched torch. The recipe used on this machine (CUDA 11.8):

```bash
conda create -n diffms python=3.10 -y
conda activate diffms

# Torch must match the host CUDA; switch to +cpu, +cu121, etc. as needed.
pip install torch==2.3.1+cu118 --index-url https://download.pytorch.org/whl/cu118

# ms-clip and its deps (hydra, lightning, dgl, rdkit, pandas, h5py ...).
pip install -e /home/weiwentao/workspace/reconstruct/ms-pred
```

DGL (used by `ms_clip.data.tree_processor`) sometimes needs a manual
wheel because PyPI does not ship a CUDA build. If `import dgl` fails,
install from <https://www.dgl.ai/pages/start.html> matching the torch /
CUDA combo.

## Sanity check

From any env:

```bash
conda run -n diffms --no-capture-output python -c "
import torch, ms_clip.common.ions, ms_clip.data.tree_processor
print('torch', torch.__version__, 'cuda', torch.cuda.is_available())
print('ms_clip ions:', list(ms_clip.common.ions.ion2onehot_pos)[:3])
"
```

Expected:
```
torch 2.3.1+cu118 cuda True
ms_clip ions: ['[M+H]+', '[M+Na]+', '[M+K]+']
```

## Things that are NOT in this env

- `matchms`, `pydantic`, the MetAgent `schemas` / `common` packages. Those
  live in the orchestrator env (see `tools/library_search/requirements.txt`).
  `library_search` runs in the orchestrator env, not in `diffms`.
- MAGMa DAG JSONs, PubChem Lite, GNPS dumps. Those are data artifacts, not
  conda deps. See `tests/fixtures/README.md` and Track A2's
  `README_PUBCHEM_SETUP.md`.

## When the env is missing

`MSClipRetriever.score_candidates()` catches subprocess failures and raises
`InHouseModelError`. `library_search()` in turn logs a warning
(`"ms-clip scoring failed, continuing with modcos only"`) and falls back
to modified-cosine-only results. The caller does not have to check.

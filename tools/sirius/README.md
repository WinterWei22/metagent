## SIRIUS Setup

Download from https://github.com/sirius-ms/sirius/releases

Set env var:

```bash
METAGENT_SIRIUS_PATH=/path/to/sirius
```

SIRIUS requires a one-time login for CSI:FingerID features. This tool only
uses the `formula` sub-command for molecular formula and fragmentation-tree
output. It supports both positive and negative ionization as long as the input
`Spectrum.adduct` is a SIRIUS-supported ion type, e.g. `[M+H]+` or `[M-H]-`.
On some SIRIUS 6 builds the CLI may still require a login before any compound
tool runs; in that case the real-path tests will skip or raise a typed setup
error, while mock-path unit tests remain deterministic.

Tested on this machine:

```text
SIRIUS 6.3.4
SIRIUS lib: 5.7.0
CSI:FingerID lib: 3.0.13
```

Installed binary:

```text
/home/weiwentao/.local/bin/sirius
```

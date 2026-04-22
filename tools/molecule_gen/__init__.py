"""Track C: molecule_generate.

De novo candidate generation from an MS/MS spectrum. Two stages:
  1. spectrum -> CSI:FingerID -> molecular fingerprint
  2. fingerprint -> MS-BART -> SELFIES -> SMILES

Public entry point: `generate(req: GenerateRequest) -> GenerateResponse`.
"""
from tools.molecule_gen.tool import generate

__all__ = ["generate"]

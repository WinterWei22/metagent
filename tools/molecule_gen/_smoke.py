"""End-to-end smoke test with the real MS-BART checkpoint.

Injects a ground-truth fingerprint (parsed from the MassSpecGym test.tsv
`fps` column) via GroundTruthFingerprinter, bypasses CSI:FingerID entirely,
and exercises the full decoder path through `MSBartGenerator` (which shells
into the ms-bart conda env).

Run from repo root:
  python -m tools.molecule_gen._smoke \\
      --test-tsv /home/weiwentao/workspace/mol_gen/MS-BART/data/MassSpecGym/test/test.tsv \\
      --identifier MassSpecGymID0095843 \\
      --n-candidates 10

Exit code 0 means the runner completed and returned ≥1 RDKit-valid candidate.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys

from rdkit import Chem

from schemas import GenerateRequest, Spectrum
from tools.molecule_gen import generate
from tools.molecule_gen.fingerprint import GroundTruthFingerprinter
from tools.molecule_gen.model import MSBartGenerator


def _load_row(tsv_path: str, identifier: str | None) -> dict:
    with open(tsv_path) as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            if identifier is None or row["identifier"] == identifier:
                return row
    raise SystemExit(f"identifier {identifier!r} not found in {tsv_path}")


def _inchikey(smiles: str) -> str | None:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    return Chem.MolToInchiKey(mol)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--test-tsv", required=True)
    p.add_argument("--identifier", default=None,
                   help="If omitted, uses the first row.")
    p.add_argument("--n-candidates", type=int, default=10)
    p.add_argument("--checkpoint", default=None,
                   help="Override MS-BART checkpoint path.")
    p.add_argument("--fp-source", choices=["tsv", "oracle"], default="tsv",
                   help="'tsv' uses the MIST-predicted fps column; 'oracle' "
                        "computes the 4096-bit Morgan fingerprint from the "
                        "ground-truth SMILES.")
    args = p.parse_args()

    row = _load_row(args.test_tsv, args.identifier)
    gt_smiles = row["smiles"]
    gt_formula = row["formula"]
    gt_inchikey_short = row.get("inchikey", "")
    print(f"=== smoke test: {row['identifier']} ===")
    print(f"ground-truth SMILES : {gt_smiles}")
    print(f"ground-truth formula: {gt_formula}")
    print(f"ground-truth InChIKey (short): {gt_inchikey_short}")
    print(f"fingerprint bits    : {row['fps'].count('<fp')}")
    print()

    # Spectrum content is ignored by GroundTruthFingerprinter; we still need a
    # schema-valid object to satisfy the request.
    spectrum = Spectrum(
        mz=[100.0, 150.0, 200.0],
        intensity=[1.0, 0.5, 0.2],
        precursor_mz=float(100.0),
        adduct=row["adduct"],
        ionization_mode="positive",
        collision_energy=None,
    )
    req = GenerateRequest(
        spectrum=spectrum,
        molecular_formula=gt_formula,
        n_candidates=args.n_candidates,
        max_molecular_weight=1500.0,
    )

    if args.fp_source == "oracle":
        fp = GroundTruthFingerprinter.from_smiles(gt_smiles)
        print(f"fp source       : oracle (Morgan r=2, nBits=4096 from gt SMILES) — "
              f"{len(fp.predict(spectrum))} ON bits")
    else:
        fp = GroundTruthFingerprinter.from_token_string(row["fps"])
        print(f"fp source       : tsv fps column (MIST-predicted, threshold 0.2)")
    gen_kwargs = {}
    if args.checkpoint:
        gen_kwargs["checkpoint_path"] = args.checkpoint
    generator = MSBartGenerator(**gen_kwargs)

    resp = generate(req, generator=generator, fingerprinter=fp)

    print(f"n_generated_raw : {resp.n_generated_raw}")
    print(f"n_valid (parsed): {resp.n_valid}")
    print(f"n_returned      : {len(resp.candidates)}")
    print(f"explain         : {resp.explain}")
    print()
    print("top candidates:")
    gt_ik_full = _inchikey(gt_smiles)
    for i, c in enumerate(resp.candidates):
        ik = _inchikey(c.smiles) or ""
        match = "YES" if ik and ik.split("-")[0] == (gt_ik_full or "").split("-")[0] else "no "
        print(f"  [{i:02d}] score={c.score:.3f} match={match} {c.smiles}")

    print()
    if any(
        (_inchikey(c.smiles) or "").split("-")[0]
        == (gt_ik_full or "").split("-")[0]
        for c in resp.candidates
    ):
        print("RESULT: ground-truth InChIKey recovered in top-K.")
    else:
        print("RESULT: ground-truth not in top-K (expected occasionally at low n_candidates).")

    return 0 if len(resp.candidates) > 0 else 2


if __name__ == "__main__":
    sys.exit(main())

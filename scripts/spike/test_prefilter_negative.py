"""§2.2 — candidate_prefilter on negative fixtures.

Hits real GNPS + PubChem-Lite indices (env vars METAGENT_GNPS_PATH,
METAGENT_PUBCHEM_LITE_PATH must be set; verified in cwd's .env).
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# Source the prefilter env if present.
env_sh = ROOT / "tools" / "candidate_prefilter" / "env.sh"
if env_sh.exists():
    # crude `source`: parse "export KEY=VALUE" lines.
    for line in env_sh.read_text().splitlines():
        line = line.strip()
        if line.startswith("export "):
            kv = line[len("export "):].split("=", 1)
            if len(kv) == 2 and kv[0] not in os.environ:
                os.environ[kv[0]] = kv[1].strip('"').strip("'")

from schemas.prefilter import PrefilterRequest  # noqa: E402
from tools.candidate_prefilter.tool import prefilter  # noqa: E402

FIXTURES = [
    ("citric_acid_neg.json", "C6H8O7", "KRKNYBCHXYNGOX"),
    ("glutamyltyrosine_neg.json", None, "VVLXCWVSSLFQDS"),
]

FIXTURE_DIR = ROOT / "tests" / "fixtures" / "spectra" / "negative_mode"


def run_one(fname: str, formula: str | None, target_inchikey_prefix: str) -> dict:
    with (FIXTURE_DIR / fname).open() as f:
        fx = json.load(f)
    req = PrefilterRequest(
        precursor_mz=fx["precursor_mz"],
        adduct=fx["adduct"],
        molecular_formula=formula,
        mass_tolerance_ppm=5.0,
        pools=["gnps", "pubchem_lite"],
        max_candidates=20,
    )
    t0 = time.perf_counter()
    try:
        resp = prefilter(req)
    except Exception as e:
        return {
            "fixture": fname,
            "crashed": True,
            "error_type": type(e).__name__,
            "error_msg": str(e)[:300],
        }
    dt = time.perf_counter() - t0

    rank_of_truth = -1
    for i, c in enumerate(resp.candidates, 1):
        # InChIKey isn't directly on PrefilteredCandidate; check SMILES+source_id.
        # Fall back to name match.
        if (c.name or "").lower().find(target_inchikey_prefix.lower()) != -1:
            rank_of_truth = i
            break

    # Also compute by recomputing inchikeys via rdkit
    truth_rank_by_ik = -1
    try:
        from rdkit import Chem
        for i, c in enumerate(resp.candidates, 1):
            mol = Chem.MolFromSmiles(c.smiles)
            if mol is None:
                continue
            ik = Chem.MolToInchiKey(mol)
            if ik.startswith(target_inchikey_prefix):
                truth_rank_by_ik = i
                break
    except Exception:
        pass

    return {
        "fixture": fname,
        "crashed": False,
        "wall_seconds": round(dt, 2),
        "neutral_mass": resp.neutral_mass_computed,
        "n_total": len(resp.candidates),
        "n_by_pool": resp.n_by_pool,
        "truth_rank_by_inchikey_prefix": truth_rank_by_ik,
        "top10_summary": [
            {
                "rank": i,
                "smiles_head": (c.smiles or "")[:40],
                "name": c.name,
                "source": c.source_pool,
                "mass_err_ppm": round(c.mass_error_ppm, 3),
                "has_ref_spectrum": c.has_reference_spectrum,
            }
            for i, c in enumerate(resp.candidates[:10], 1)
        ],
        "explain": resp.explain,
    }


def main() -> None:
    print("§2.2 candidate_prefilter on negative-mode fixtures")
    print("-" * 60)
    print(f"GNPS_PATH={os.environ.get('METAGENT_GNPS_PATH')}")
    print(f"PUBCHEM_LITE_PATH={os.environ.get('METAGENT_PUBCHEM_LITE_PATH')}")
    print()
    for fname, formula, ik in FIXTURES:
        result = run_one(fname, formula, ik)
        print(f"\n{fname}  (target inchikey prefix: {ik})")
        for k, v in result.items():
            if k == "fixture":
                continue
            if k == "top10_summary":
                print(f"  {k}:")
                for row in v:
                    print(f"    {row}")
            else:
                print(f"  {k}: {v}")


if __name__ == "__main__":
    main()

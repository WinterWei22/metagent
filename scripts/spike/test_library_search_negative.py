"""§2.3 — library_search on negative-mode fixtures.

Runs prefilter + library_search in one process so we only pay the ~7 min
GNPS load once (≈930k records). Output is serialised to /tmp so
downstream spike steps (§2.4, §2.8, §2.9) can reuse the candidates.

Two fixtures:
  citric_acid_neg.json     [M-H]- (true positive present in GNPS neg subset)
  glutamyltyrosine_neg.json [M-H]- (formula-constrained because mass-only
                                    pulls 48 + 17 candidates many of which
                                    share the C14H18N2O6 mass window)
"""
from __future__ import annotations

import json
import os
import pickle
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

env_sh = ROOT / "tools" / "candidate_prefilter" / "env.sh"
if env_sh.exists():
    for line in env_sh.read_text().splitlines():
        line = line.strip()
        if line.startswith("export "):
            kv = line[len("export "):].split("=", 1)
            if len(kv) == 2 and kv[0] not in os.environ:
                os.environ[kv[0]] = kv[1].strip('"').strip("'")

from schemas import (  # noqa: E402
    LibrarySearchRequest,
    PrefilterRequest,
    Spectrum,
)
from tools.candidate_prefilter.tool import prefilter  # noqa: E402
from tools.library_search.tool import library_search  # noqa: E402

FIXTURE_DIR = ROOT / "tests" / "fixtures" / "spectra" / "negative_mode"
OUT_PICKLE = Path("/tmp/spike_neg_pipeline_artifacts.pkl")

CASES = [
    {
        "fixture": "citric_acid_neg.json",
        "formula": "C6H8O7",
        "target_inchikey_prefix": "KRKNYBCHXYNGOX",
    },
    {
        "fixture": "glutamyltyrosine_neg.json",
        "formula": "C14H18N2O6",
        "target_inchikey_prefix": "VVLXCWVSSLFQDS",
    },
]


def load_fixture(fname: str) -> dict:
    with (FIXTURE_DIR / fname).open() as f:
        return json.load(f)


def build_query_spectrum(fx: dict) -> Spectrum:
    """Construct a Spectrum directly from the fixture (skip preprocess to
    keep the script focused on library_search; preprocess already verified
    in §2.1)."""
    raw_max = max(p[1] for p in fx["peaks"])
    return Spectrum(
        mz=[p[0] for p in fx["peaks"]],
        intensity=[p[1] / raw_max for p in fx["peaks"]],
        precursor_mz=fx["precursor_mz"],
        adduct=fx["adduct"],
        ionization_mode=fx["ionization_mode"],
        collision_energy=fx.get("collision_energy"),
    )


def run_case(case: dict, sink: dict) -> None:
    fname = case["fixture"]
    fx = load_fixture(fname)

    print(f"\n=== {fname} ===")
    print(f"  precursor_mz={fx['precursor_mz']}  adduct={fx['adduct']}  "
          f"mode={fx['ionization_mode']}  CE={fx.get('collision_energy')}")

    pre_req = PrefilterRequest(
        precursor_mz=fx["precursor_mz"],
        adduct=fx["adduct"],
        molecular_formula=case["formula"],
        mass_tolerance_ppm=5.0,
        pools=["gnps", "pubchem_lite"],
        max_candidates=30,
    )
    t0 = time.perf_counter()
    pre_resp = prefilter(pre_req)
    dt_pre = time.perf_counter() - t0
    print(f"  prefilter: {len(pre_resp.candidates)} candidates "
          f"({pre_resp.n_by_pool}) wall={dt_pre:.1f}s")
    print(f"  prefilter explain: {pre_resp.explain}")

    spec = build_query_spectrum(fx)
    lib_req = LibrarySearchRequest(
        spectrum=spec,
        candidate_pool=pre_resp.candidates,
        top_k=10,
        min_score=0.0,
        libraries=["inhouse", "gnps"],
    )
    t0 = time.perf_counter()
    try:
        lib_resp = library_search(lib_req)
        crashed = False
        crash_msg = ""
    except Exception as e:
        crashed = True
        crash_msg = f"{type(e).__name__}: {str(e)[:300]}"
        lib_resp = None
    dt_lib = time.perf_counter() - t0
    print(f"  library_search: wall={dt_lib:.1f}s  crashed={crashed}")
    if crashed:
        print(f"    error: {crash_msg}")
        sink[fname] = {
            "fixture": fname,
            "prefilter_explain": pre_resp.explain,
            "prefilter_candidates": [c.model_dump() for c in pre_resp.candidates],
            "library_search_crashed": True,
            "library_search_error": crash_msg,
        }
        return

    print(f"  library_search explain: {lib_resp.explain}")
    print(f"  top-10 candidates:")
    truth_rank = -1
    target = case["target_inchikey_prefix"]
    try:
        from rdkit import Chem
        for i, c in enumerate(lib_resp.candidates, 1):
            mol = Chem.MolFromSmiles(c.smiles)
            ik = Chem.MolToInchiKey(mol) if mol else ""
            ok = ik.startswith(target)
            if ok and truth_rank < 0:
                truth_rank = i
            print(f"    rank {i}: score={c.score:.3f}  smiles={c.smiles[:50]!r}  "
                  f"name={c.name!r}  ik={ik[:14]}  truth_match={ok}")
    except Exception as e:
        print(f"    (rdkit unavailable: {e})")
        for i, c in enumerate(lib_resp.candidates, 1):
            print(f"    rank {i}: score={c.score:.3f}  name={c.name!r}")
    print(f"  truth_rank: {truth_rank}")

    sink[fname] = {
        "fixture": fname,
        "prefilter_explain": pre_resp.explain,
        "prefilter_candidates": [c.model_dump() for c in pre_resp.candidates],
        "library_search_crashed": False,
        "library_search_explain": lib_resp.explain,
        "library_search_libraries": lib_resp.libraries_searched,
        "library_search_n_compared": lib_resp.n_total_compared,
        "library_search_top_candidates": [c.model_dump() for c in lib_resp.candidates],
        "library_search_truth_rank": truth_rank,
        "library_search_wall_seconds": round(dt_lib, 2),
        "prefilter_wall_seconds": round(dt_pre, 2),
        "spectrum": spec.model_dump(),
        "fixture_data": fx,
    }


def main() -> None:
    print("§2.3 library_search on negative-mode fixtures")
    print("-" * 60)
    print(f"GNPS_PATH={os.environ.get('METAGENT_GNPS_PATH')}")
    print(f"GNPS_SPECTRA_PATH={os.environ.get('METAGENT_GNPS_SPECTRA_PATH')}")
    sink: dict = {}
    for case in CASES:
        run_case(case, sink)

    OUT_PICKLE.write_bytes(pickle.dumps(sink))
    print(f"\nartifacts saved to {OUT_PICKLE}")


if __name__ == "__main__":
    main()

"""Smoke-check the four day-1 tools: python scripts/audit_tracks.py.

Not a test. Exit 0 iff all four tools boot and run a canonical glucose
request. Library_search / molecule_generate use their Mock adapters;
candidate_prefilter runs GNPS-only against an empty lazy-loaded index,
so no DB / model / network is required.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from schemas import (
    GenerateRequest, LibrarySearchRequest, PrefilterRequest,
    PrefilteredCandidate, PreprocessRequest,
)

_SMI = "OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O"  # glucose
_POOL = [PrefilteredCandidate(
    smiles=_SMI, name="glucose", source_pool="pubchem_lite",
    source_id="HMDB0000122", molecular_formula="C6H12O6",
    exact_mass=180.0634, mass_error_ppm=0.2, has_reference_spectrum=False,
)]


def _a1():
    from tools.spectrum_ops import preprocess
    r = preprocess(PreprocessRequest(
        raw_mz=[163.0601, 145.0495, 127.0390, 109.0284, 85.0284, 73.0284, 61.0284],
        raw_intensity=[1000.0, 420.0, 380.0, 250.0, 180.0, 120.0, 90.0],
        precursor_mz=181.0707, adduct="[M+H]+", ionization_mode="positive",
        collision_energy=20.0,
    ))
    return 1, r.spectrum


def _a2(_spec):
    from tools.candidate_prefilter import prefilter
    r = prefilter(PrefilterRequest(
        precursor_mz=181.0707, adduct="[M+H]+", molecular_formula="C6H12O6",
        mass_tolerance_ppm=5.0, pools=["gnps"],
    ))
    return len(r.candidates), None


def _b(spec):
    from tools.library_search import library_search
    from tools.library_search.model import MockInHouseRetriever
    r = library_search(
        LibrarySearchRequest(spectrum=spec, candidate_pool=_POOL, top_k=5, libraries=["inhouse"]),
        retriever=MockInHouseRetriever({_SMI: 0.7}),
    )
    return len(r.candidates), None


def _c(spec):
    from tools.molecule_gen import generate
    from tools.molecule_gen.fingerprint import MockFingerprinter
    from tools.molecule_gen.model import MockGenerator
    r = generate(
        GenerateRequest(spectrum=spec, molecular_formula="C6H12O6", n_candidates=1),
        generator=MockGenerator([(_SMI, -1.0)]), fingerprinter=MockFingerprinter(),
    )
    return len(r.candidates), None


def main() -> int:
    steps = [("spectrum_preprocess", _a1), ("candidate_prefilter", _a2),
             ("library_search", _b), ("molecule_generate", _c)]
    spec, rows, failed = None, [], False
    for name, fn in steps:
        t0 = time.perf_counter()
        try:
            n, out = fn(spec) if name != "spectrum_preprocess" else fn()
            ms = (time.perf_counter() - t0) * 1000
            rows.append((name, "yes", n, ms, ""))
            if name == "spectrum_preprocess":
                spec = out
        except Exception as e:
            ms = (time.perf_counter() - t0) * 1000
            rows.append((name, "NO", 0, ms, f"{type(e).__name__}: {e}"))
            failed = True
    print(f"{'tool':<22} {'runs':<6} {'n_outputs':<10} {'elapsed_ms':<12} error")
    print("-" * 78)
    for row in rows:
        print(f"{row[0]:<22} {row[1]:<6} {row[2]:<10} {row[3]:<12.2f} {row[4]}")
    if failed:
        print("\nSOME TOOLS FAILED — see 'error' column above.", file=sys.stderr)
        return 1
    print("\nAll four tools booted and ran. Repo is alive.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

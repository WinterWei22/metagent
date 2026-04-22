"""Minimal runnable demo of candidate_prefilter.

Run from the repo root:

    METAGENT_PUBCHEM_LITE_PATH=/path/to/pubchem_lite.sqlite \\
    METAGENT_GNPS_PATH=/path/to/ALL_GNPS_NO_PROPOGATED.json \\
    python -m tools.candidate_prefilter.example

If the env vars are unset the script prints the prefilter error message
instead of crashing, so you can still sanity-check the adduct math.
"""
from schemas import PrefilterRequest
from tools.candidate_prefilter import prefilter

if __name__ == "__main__":
    req = PrefilterRequest(
        precursor_mz=181.0707,       # glucose [M+H]+
        adduct="[M+H]+",
        molecular_formula="C6H12O6",
        mass_tolerance_ppm=5.0,
    )
    resp = prefilter(req)
    print(f"neutral_mass={resp.neutral_mass_computed:.4f}  n={len(resp.candidates)}  n_by_pool={resp.n_by_pool}")
    for c in resp.candidates[:5]:
        print(f"  {c.mass_error_ppm:5.2f} ppm  {c.source_pool:12s}  {c.source_id:20s}  {c.name}")
    print(resp.explain)

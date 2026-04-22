"""Minimal runnable demo of candidate_prefilter.

Run from the repo root:

    METAGENT_PUBCHEM_LITE_PATH=/path/to/pubchem_lite.sqlite \\
    METAGENT_GNPS_PATH=/path/to/ALL_GNPS_NO_PROPOGATED.json \\
    python -m tools.candidate_prefilter.example

If the env vars are unset the script prints the resulting ToolError instead
of crashing, so you can still sanity-check the adduct reverse-calculation.
"""
from schemas import PrefilterRequest
from schemas.common import ToolError
from tools.candidate_prefilter import prefilter
from tools.candidate_prefilter.adducts import neutral_mass_from_precursor

if __name__ == "__main__":
    precursor_mz = 181.0707   # glucose [M+H]+
    adduct = "[M+H]+"

    # Step 1 — adduct reverse-calc always works; no external data needed.
    neutral = neutral_mass_from_precursor(precursor_mz, adduct)
    print(f"neutral_mass({adduct} @ {precursor_mz}) = {neutral:.4f}")

    # Step 2 — actual pool query; may fail if env vars are unset.
    req = PrefilterRequest(
        precursor_mz=precursor_mz,
        adduct=adduct,
        molecular_formula="C6H12O6",
        mass_tolerance_ppm=5.0,
    )
    try:
        resp = prefilter(req)
    except ToolError as e:
        print(f"prefilter failed ({e.code}): {e.message}")
    else:
        print(f"n={len(resp.candidates)}  n_by_pool={resp.n_by_pool}")
        for c in resp.candidates[:5]:
            print(f"  {c.mass_error_ppm:5.2f} ppm  {c.source_pool:12s}  {c.source_id:20s}  {c.name}")
        print(resp.explain)

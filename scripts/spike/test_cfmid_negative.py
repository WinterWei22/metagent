"""§2.5 — predict_spectrum (CFM-ID) on negative-mode targets.

CFM-ID is a forward-prediction tool — it takes SMILES, not an experimental
spectrum, so we feed in the ground-truth SMILES of the two RIKEN fixtures
and verify that:
  * the docker shim routes negative requests to the [M-H]- model
  * the returned spectrum has plausible peaks (precursor m/z is dominant
    or near-dominant; non-empty per-energy blocks)
  * basic sanity: no crash, model_version reports cfm-id-4.x

Targets (SMILES + adduct):
  citric acid   [M-H]-  (KRKNYBCHXYNGOX)
  glutamyltyrosine [M-H]-  (VVLXCWVSSLFQDS)

CFM-ID does not consume the experimental spectrum, so the comparison
against RIKEN's measured peaks is informational only — the spike is about
whether the negative-mode prediction path itself returns sensible output.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from schemas.spectrum import PredictSpectrumRequest  # noqa: E402
from tools.spectrum_predict.tool import predict_spectrum  # noqa: E402

FIXTURE_DIR = ROOT / "tests" / "fixtures" / "spectra" / "negative_mode"

CASES = [
    {
        "fixture": "citric_acid_neg.json",
        "smiles": "O=C(O)CC(O)(C(=O)O)CC(=O)O",
        "label": "citric acid",
    },
    {
        "fixture": "glutamyltyrosine_neg.json",
        "smiles": "O=C(O)C(N)CCC(=O)NC(C(=O)O)CC1=CC=C(O)C=C1",
        "label": "glutamyltyrosine",
    },
]


def load_observed(fname: str) -> list[tuple[float, float]]:
    with (FIXTURE_DIR / fname).open() as f:
        fx = json.load(f)
    raw_max = max(p[1] for p in fx["peaks"])
    return [(p[0], p[1] / raw_max) for p in fx["peaks"]]


def run_one(case: dict) -> dict:
    label = case["label"]
    fx_name = case["fixture"]
    req = PredictSpectrumRequest(
        smiles=case["smiles"],
        adduct="[M-H]-",
        ionization_mode="negative",
        collision_energies=[10.0, 20.0, 40.0],
        top_n_peaks=50,
    )

    t0 = time.perf_counter()
    try:
        resp = predict_spectrum(req)
    except Exception as e:
        return {
            "fixture": fx_name,
            "label": label,
            "crashed": True,
            "error_type": type(e).__name__,
            "error_msg": str(e)[:300],
            "wall_seconds": round(time.perf_counter() - t0, 2),
        }
    dt = time.perf_counter() - t0

    union_top5 = sorted(
        zip(resp.predicted.mz, resp.predicted.intensity),
        key=lambda p: -p[1],
    )[:5]

    # Compare to observed (informational): how many predicted m/z within
    # 5 ppm of an observed peak?
    observed = load_observed(fx_name)
    matches = 0
    for pmz, _pi in zip(resp.predicted.mz, resp.predicted.intensity):
        for omz, _oi in observed:
            if abs(pmz - omz) / pmz * 1e6 <= 5.0:
                matches += 1
                break
    overlap_pct = round(100.0 * matches / max(len(resp.predicted.mz), 1), 1)

    return {
        "fixture": fx_name,
        "label": label,
        "crashed": False,
        "wall_seconds": round(dt, 2),
        "model_version": resp.model_version,
        "n_union_peaks": len(resp.predicted.mz),
        "n_per_energy_blocks": {str(k): len(v.mz) for k, v in resp.per_energy.items()},
        "union_top5_by_intensity": [
            {"mz": round(mz, 4), "intensity": round(i, 3)} for mz, i in union_top5
        ],
        "predicted_precursor_mz": resp.predicted.precursor_mz,
        "predicted_ion_mode": resp.predicted.ionization_mode,
        "predicted_adduct": resp.predicted.adduct,
        "n_observed_peaks": len(observed),
        "n_predicted_peaks_with_observed_match_5ppm": matches,
        "predicted_observed_overlap_pct": overlap_pct,
        "explain": resp.explain,
    }


def main() -> None:
    print("§2.5 spectrum_predict (CFM-ID) on negative-mode targets")
    print("-" * 60)
    for case in CASES:
        print(f"\n--- {case['label']} ({case['fixture']}) ---")
        result = run_one(case)
        for k, v in result.items():
            if k == "fixture":
                continue
            if k == "union_top5_by_intensity":
                print(f"  {k}:")
                for p in v:
                    print(f"    {p}")
            else:
                print(f"  {k}: {v}")


if __name__ == "__main__":
    main()

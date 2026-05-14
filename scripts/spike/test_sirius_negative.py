"""§2.4 — SIRIUS sirius_annotate on negative-mode fixtures.

Independent diagnostic: build a Spectrum from the fixture (RIKEN-derived),
call sirius_annotate(), and report whether SIRIUS recognises the [M-H]-
ionization, returns a sensible formula, and produces a non-trivial
fragment tree.

This bypasses preprocess (already verified in §2.1) so we can isolate
SIRIUS-specific behaviour. The Spectrum is normalised to base-peak=1.0
manually.

Two modes per fixture:
  qtof preset  — RIKEN's instrument is LC-ESI-QTOF
  orbitrap     — control, to see if preset choice affects negative-mode
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from schemas.common import Spectrum  # noqa: E402
from tools.sirius.schemas import SiriusAnnotateRequest  # noqa: E402
from tools.sirius.tool import sirius_annotate  # noqa: E402
from tools.sirius.ms_writer import spectrum_to_ms_text  # noqa: E402

FIXTURE_DIR = ROOT / "tests" / "fixtures" / "spectra" / "negative_mode"
FIXTURES = ["citric_acid_neg.json", "glutamyltyrosine_neg.json"]
PRESETS = ["qtof"]  # add "orbitrap" if qtof completes


def build_spectrum(fx: dict) -> Spectrum:
    raw_max = max(p[1] for p in fx["peaks"])
    return Spectrum(
        mz=[p[0] for p in fx["peaks"]],
        intensity=[p[1] / raw_max for p in fx["peaks"]],
        precursor_mz=fx["precursor_mz"],
        adduct=fx["adduct"],
        ionization_mode=fx["ionization_mode"],
        collision_energy=fx.get("collision_energy"),
    )


def run_one(fname: str, preset: str) -> dict:
    with (FIXTURE_DIR / fname).open() as f:
        fx = json.load(f)

    spec = build_spectrum(fx)
    # Show the .ms text the wrapper would feed SIRIUS — useful for diagnosis.
    ms_text = spectrum_to_ms_text(spec, compound_id=fname.replace(".json", ""))
    ms_preview = ms_text.splitlines()[:6]

    req = SiriusAnnotateRequest(
        spectrum=spec,
        instrument_preset=preset,
        timeout_seconds=180,
    )

    t0 = time.perf_counter()
    try:
        resp = sirius_annotate(req)
    except Exception as e:
        return {
            "fixture": fname,
            "preset": preset,
            "crashed": True,
            "error_type": type(e).__name__,
            "error_msg": str(e)[:600],
            "ms_text_preview": ms_preview,
            "wall_seconds": round(time.perf_counter() - t0, 2),
        }
    dt = time.perf_counter() - t0

    return {
        "fixture": fname,
        "preset": preset,
        "crashed": False,
        "wall_seconds": round(dt, 2),
        "predicted_formula": resp.predicted_formula,
        "formula_score": resp.formula_score,
        "tree_node_count": resp.tree_node_count,
        "sirius_version": resp.sirius_version,
        "fragments_summary": [
            {
                "mz": round(f.mz_observed, 4),
                "formula": f.formula,
                "neutral_loss": f.neutral_loss_formula,
                "intensity": round(f.intensity, 3),
                "depth": f.depth,
            }
            for f in resp.fragments[:8]
        ],
        "explain": resp.explain,
        "ms_text_preview": ms_preview,
    }


def main() -> None:
    print("§2.4 SIRIUS sirius_annotate on negative-mode fixtures")
    print("-" * 60)
    for fname in FIXTURES:
        for preset in PRESETS:
            print(f"\n--- {fname} [preset={preset}] ---")
            result = run_one(fname, preset)
            for k, v in result.items():
                if k == "fragments_summary":
                    print(f"  {k}:")
                    for frag in v:
                        print(f"    {frag}")
                elif k == "ms_text_preview":
                    print(f"  {k}:")
                    for line in v:
                        print(f"    {line}")
                else:
                    print(f"  {k}: {v}")


if __name__ == "__main__":
    main()

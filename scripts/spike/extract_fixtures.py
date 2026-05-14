"""Extract two negative-mode fixtures from the RIKEN JSONL.

- citric_acid_neg.json     (MSBNK-RIKEN-PR309128, [M-H]-, 21 peaks, organic_acid)
- glutamyltyrosine_neg.json (MSBNK-RIKEN-PR309407, [M-H]-, 39 peaks, amino_acid)

Format mirrors `tests/fixtures/spectra/glucose_pos.json`.

Note: RIKEN's intensities are already normalised (base peak = 1.0). The
`peaks` field is written in [m/z, scaled_intensity] pairs where intensity
is multiplied by 1000 to match the magnitude of the existing fixtures. The
spectrum_preprocess tool re-normalises to base peak = 1.0 anyway, so the
absolute scale is not load-bearing.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JSONL = (
    "/data/weiwentao/llm_agent_metabolomics/massbank/processed/"
    "compound_pool_riken.jsonl"
)
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "spectra" / "negative_mode"

TARGETS = {
    "citric_acid_neg.json": {
        "accession": "MSBNK-RIKEN-PR309128",
        "compound_name": "citric_acid",
        "notes": (
            "Real RIKEN MS/MS spectrum, accession MSBNK-RIKEN-PR309128. "
            "RIKEN's source record is annotated 'not validated, isomer of "
            "PR000227' — the SMILES + InChIKey + neutral mass still match "
            "citric acid, so this is acceptable as a spike-test fixture but "
            "should not be treated as gold-standard for benchmark scoring. "
            "Intensities are normalised to base peak = 1.0 (RIKEN convention) "
            "and rescaled ×1000 for parity with existing fixtures."
        ),
    },
    "glutamyltyrosine_neg.json": {
        "accession": "MSBNK-RIKEN-PR309407",
        "compound_name": "glutamyltyrosine",
        "notes": (
            "Real RIKEN MS/MS spectrum, accession MSBNK-RIKEN-PR309407. "
            "Free L-tyrosine is not present in the RIKEN PlaSMA collection "
            "(plant-metabolite focus); glutamyl-tyrosine (a dipeptide "
            "containing the tyrosine residue) was selected as the closest "
            "match within the amino_acid SMARTS class. Intensities "
            "normalised + rescaled as for citric_acid_neg.json."
        ),
    },
}


def main() -> int:
    if not os.path.exists(JSONL):
        print(f"FATAL: JSONL not found: {JSONL}", file=sys.stderr)
        return 2
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

    by_accession: dict[str, dict] = {}
    needed = {meta["accession"] for meta in TARGETS.values()}

    with open(JSONL) as f:
        for line in f:
            r = json.loads(line)
            acc = r["metadata"].get("accession")
            if acc in needed:
                by_accession[acc] = r
                if len(by_accession) == len(needed):
                    break

    missing = needed - set(by_accession)
    if missing:
        print(f"FATAL: missing accessions: {missing}", file=sys.stderr)
        return 3

    for fname, meta in TARGETS.items():
        rec = by_accession[meta["accession"]]
        spectrum = rec["spectrum"]
        gt = rec["ground_truth"]

        # Ramp/stepped CE arrives normalised to None; surface that explicitly.
        ce = spectrum.get("collision_energy")
        if ce is None and rec.get("normalization_warnings"):
            warning = "; ".join(rec["normalization_warnings"])
        else:
            warning = ""

        peaks = [
            [round(mz, 6), round(intensity * 1000.0, 4)]
            for mz, intensity in zip(spectrum["mz"], spectrum["intensity"])
        ]

        fixture = {
            "compound_name": meta["compound_name"],
            "smiles": gt.get("smiles") or "",
            "inchikey": gt.get("inchikey") or "",
            "hmdb_id": "",  # RIKEN doesn't expose HMDB id in this slot
            "precursor_mz": spectrum["precursor_mz"],
            "adduct": spectrum["adduct"],
            "ionization_mode": spectrum["ionization_mode"],
            "collision_energy": ce,
            "peaks": peaks,
            "source": f"MassBank RIKEN {meta['accession']}",
            "notes": meta["notes"]
            + (f" Original CE warning: {warning}." if warning else ""),
            "ground_truth_compound_name": gt.get("primary_compound_name"),
            "ground_truth_formula": gt.get("molecular_formula"),
            "ground_truth_exact_mass": gt.get("exact_mass"),
            "compound_class": gt.get("compound_class"),
        }

        out = FIXTURE_DIR / fname
        out.write_text(json.dumps(fixture, indent=2, ensure_ascii=False) + "\n")
        print(f"  wrote {out.relative_to(ROOT)}  ({len(peaks)} peaks)")

    return 0


if __name__ == "__main__":
    sys.exit(main())

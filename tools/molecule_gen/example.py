"""10-line smoke test demoing the public `generate` API with mocks.

Run from repo root: `python -m tools.molecule_gen.example`.
"""
from schemas import GenerateRequest, Spectrum
from tools.molecule_gen import generate
from tools.molecule_gen.fingerprint import MockFingerprinter
from tools.molecule_gen.model import MockGenerator


spectrum = Spectrum(
    mz=[138.0662, 110.0713, 83.0604, 69.0447, 55.0291],
    intensity=[1.0, 0.52, 0.31, 0.18, 0.11],
    precursor_mz=195.0877,
    adduct="[M+H]+",
    ionization_mode="positive",
    collision_energy=25.0,
)
req = GenerateRequest(spectrum=spectrum, molecular_formula="C8H10N4O2", n_candidates=3)
gen = MockGenerator(
    [
        ("CN1C=NC2=C1C(=O)N(C)C(=O)N2C", -2.1),   # caffeine, matches formula
        ("c1ccccc1", -3.0),                        # benzene, wrong formula
        ("not a molecule", -4.0),                  # invalid SMILES
    ]
)
print(generate(req, generator=gen, fingerprinter=MockFingerprinter()).model_dump_json(indent=2))

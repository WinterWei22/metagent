"""Executable demo of library_search. Uses a mock in-house retriever and a
hand-built candidate pool so this runs without the real ms-clip checkpoint.

    python -m tools.library_search.example
"""
from __future__ import annotations

from schemas import LibrarySearchRequest, PrefilteredCandidate, Spectrum

from tools.library_search import library_search
from tools.library_search.model import MockInHouseRetriever


def main() -> None:
    spectrum = Spectrum(
        mz=[163.0601, 145.0495, 127.0390, 109.0284, 85.0284],
        intensity=[1.0, 0.42, 0.38, 0.25, 0.18],
        precursor_mz=181.0707,
        adduct="[M+H]+",
        ionization_mode="positive",
        collision_energy=20.0,
    )
    pool = [
        PrefilteredCandidate(
            smiles="OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O",
            name="glucose",
            source_pool="pubchem_lite",
            source_id="PUBCHEM:5793",
            molecular_formula="C6H12O6",
            exact_mass=180.06339,
            mass_error_ppm=0.5,
            has_reference_spectrum=False,
        ),
    ]
    retriever = MockInHouseRetriever(smiles_to_score={pool[0].smiles: 0.82})

    req = LibrarySearchRequest(spectrum=spectrum, candidate_pool=pool, top_k=3)
    resp = library_search(req, retriever=retriever)

    print(resp.model_dump_json(indent=2))


if __name__ == "__main__":
    main()

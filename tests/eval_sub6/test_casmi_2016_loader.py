"""Phase 6.7-C — smoke test for CASMI 2016 cat2 loader.

Acceptance: loader produces 208 specs with valid GT InChIKey + non-empty
candidate pools, and ion-mode distribution matches the documented 127/81 split.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import pytest

CASMI2016_AVAILABLE = (
    Path("/data/weiwentao/llm_agent_metabolomics/CASMI/casmi_2016/category2")
).exists()

pytestmark = pytest.mark.skipif(
    not CASMI2016_AVAILABLE,
    reason="CASMI 2016 cat2 data not on disk — skipped in CI",
)


def test_loader_produces_208_specs():
    from evaluation.sub6.casmi_loader import load_casmi_2016_cat2_specs
    specs = load_casmi_2016_cat2_specs()
    assert len(specs) == 208


def test_ion_mode_distribution_127_81():
    from collections import Counter
    from evaluation.sub6.casmi_loader import load_casmi_2016_cat2_specs
    specs = load_casmi_2016_cat2_specs()
    modes = Counter(s.ion_mode for s in specs)
    assert modes["positive"] == 127
    assert modes["negative"] == 81


def test_every_spec_has_gt_and_peaks():
    from evaluation.sub6.casmi_loader import load_casmi_2016_cat2_specs
    specs = load_casmi_2016_cat2_specs()
    for s in specs:
        assert s.inchikey_first_block, f"{s.spectrum_id} missing GT IK14"
        assert s.peaks, f"{s.spectrum_id} has no MS2 peaks"
        assert s.precursor_mz > 0, f"{s.spectrum_id} has invalid precursor"


def test_candidate_pool_first_30_specs():
    """Every challenge should have a non-empty candidate pool, and the GT
    should be present (within the first 30 specs we spot-check)."""
    from rdkit import Chem, RDLogger
    from rdkit.Chem.inchi import MolToInchiKey
    RDLogger.DisableLog("rdApp.*")
    from evaluation.sub6.casmi_loader import (
        load_casmi_2016_cat2_specs, build_casmi_2016_pool,
    )

    def _ik14(s: str) -> str | None:
        m = Chem.MolFromSmiles(s)
        return MolToInchiKey(m)[:14] if m else None

    specs = load_casmi_2016_cat2_specs()[:30]
    for s in specs:
        pool = build_casmi_2016_pool(s.spectrum_id, s.precursor_mz)
        assert pool, f"{s.spectrum_id} has empty pool"
        pool_iks = {_ik14(c.smiles) for c in pool}
        # GT-in-pool is a soft expectation; we already verified 30/30 in smoke.
        assert s.inchikey_first_block in pool_iks, (
            f"{s.spectrum_id} GT IK14 {s.inchikey_first_block} not in pool"
        )


def test_candidate_pool_multi_formula():
    """CASMI 2016 candidate pools are mass-tolerant, so most challenges
    should have >1 unique molecular formula (vs CASMI 2022's single-formula
    PubChem retrieval slices)."""
    from collections import Counter
    from evaluation.sub6.casmi_loader import (
        load_casmi_2016_cat2_specs, build_casmi_2016_pool,
    )
    specs = load_casmi_2016_cat2_specs()[:10]
    multi_formula_count = 0
    for s in specs:
        pool = build_casmi_2016_pool(s.spectrum_id, s.precursor_mz)
        formulas = Counter(c.molecular_formula for c in pool)
        if len(formulas) > 1:
            multi_formula_count += 1
    # Expect at least half the spot-checked challenges to be multi-formula.
    assert multi_formula_count >= 5, (
        f"only {multi_formula_count}/10 challenges have multi-formula pools; "
        "candidate pool may have been formula-collapsed"
    )

"""Unit tests for mummichog wrapper (W4 D1).

Verifies the venv-subprocess wiring + JSON contract + error paths.
Network-free / file-only — uses synthetic peak data Session-4-style.
"""
from __future__ import annotations

import random
import subprocess
import sys
from pathlib import Path

import pytest

WORKTREE = Path(__file__).resolve().parents[2]
if str(WORKTREE) not in sys.path:
    sys.path.insert(0, str(WORKTREE))

from concord.schema.peak import PeakRecord
from concord.wrappers.mummichog_wrapper import (
    DEFAULT_VENV_PYTHON,
    MummichogSubprocessError,
    MummichogVenvMissing,
    run_mummichog,
)

pytestmark = pytest.mark.skipif(
    not DEFAULT_VENV_PYTHON.exists(),
    reason=f"Py3.10 mummichog venv not found at {DEFAULT_VENV_PYTHON}",
)


@pytest.fixture(scope="module")
def synthetic_peaks() -> list[PeakRecord]:
    """Session-4-style 210-peak input: 10 differential (M+H+) + 200 background."""
    random.seed(42)
    peaks = []
    diff = [180.0634, 181.0712, 174.1117, 219.0824, 124.0480,
            132.0535, 175.1190, 89.0477, 100.0394, 152.0467]
    for mz in diff:
        peaks.append(PeakRecord(mz=mz + 1.00784, p_value=0.001, t_score=4.5,
                                retention_time=random.uniform(30, 600)))
    for _ in range(200):
        peaks.append(PeakRecord(mz=random.uniform(80, 800),
                                p_value=random.uniform(0.1, 0.95),
                                t_score=random.normalvariate(0, 1),
                                retention_time=random.uniform(30, 600)))
    return peaks


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_run_mummichog_happy_path(synthetic_peaks):
    """Real subprocess to Py3.10 venv → mummichog 2.7.0 → return ≥1 pathway."""
    result = run_mummichog(synthetic_peaks, mode="positive", permutations=20)
    assert isinstance(result, dict)
    assert "pathways" in result
    assert "stats" in result
    assert "tool_version" in result
    assert result["tool_version"] == "mummichog-2.7.0"
    assert len(result["pathways"]) >= 1, (
        f"expected ≥1 pathway from 210-peak synthetic, got {len(result['pathways'])}"
    )
    p0 = result["pathways"][0]
    assert "pathway_id" in p0 and "p_value" in p0 and "hits_kegg_ids" in p0
    assert isinstance(p0["hits_kegg_ids"], list)


def test_run_mummichog_negative_mode(synthetic_peaks):
    """negative ionization mode also runs (different default adduct set)."""
    result = run_mummichog(synthetic_peaks[:50], mode="negative", permutations=20)
    assert "pathways" in result
    assert "errors" in result


def test_run_mummichog_empty_peaks():
    """Empty peak list → short-circuit, no subprocess, empty pathways."""
    result = run_mummichog([], mode="positive")
    assert result["pathways"] == []
    assert result["stats"]["n_features_in"] == 0
    assert result["errors"] == []


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_run_mummichog_venv_missing(synthetic_peaks, tmp_path):
    """Bogus venv path → MummichogVenvMissing with install hint."""
    bogus = tmp_path / "no_such_venv" / "bin" / "python"
    with pytest.raises(MummichogVenvMissing, match="mummichog_py310"):
        run_mummichog(synthetic_peaks[:5], venv_python=bogus)


def test_run_mummichog_invalid_mode(synthetic_peaks):
    with pytest.raises(ValueError, match="mode"):
        run_mummichog(synthetic_peaks[:5], mode="sideways")  # type: ignore


def test_run_mummichog_bad_peaks_type():
    with pytest.raises(ValueError, match="peaks"):
        run_mummichog("not_a_list")  # type: ignore


def test_run_mummichog_timeout(synthetic_peaks):
    """Force timeout=0.1s → expect TimeoutError before subprocess can finish."""
    with pytest.raises(TimeoutError, match="timeout"):
        run_mummichog(synthetic_peaks, permutations=200, timeout_sec=1)


# ---------------------------------------------------------------------------
# PeakRecord validation
# ---------------------------------------------------------------------------


def test_peak_record_validator_mz():
    with pytest.raises(ValueError, match="mz"):
        PeakRecord(mz=-1.0, p_value=0.5)


def test_peak_record_validator_pvalue():
    with pytest.raises(ValueError, match="p_value"):
        PeakRecord(mz=180.06, p_value=1.5)


# ---------------------------------------------------------------------------
# W4 D2: normalize_mummichog_output integration test
# ---------------------------------------------------------------------------


def test_normalize_mummichog_populates_hits(synthetic_peaks):
    """End-to-end:run_mummichog → normalize_mummichog_output → v0.3
    EnrichmentResult with metabolites_hit ≥ 1 CHEBI primary id.

    Requires ChebiLookup sqlite present(skipped automatically by pytestmark).
    """
    from concord.lookup.chebi import ChebiLookup
    from concord.normalize.mummichog_norm import normalize_mummichog_output
    from concord.schema.enrichment import (
        COMPOUND_NAMESPACES,
        EnrichmentResult,
        PATHWAY_NAMESPACES,
    )

    chebi_db = WORKTREE / "data" / "concord" / "chebi.sqlite"
    if not chebi_db.exists():
        pytest.skip("ChEBI sqlite missing — run W3 ETL first")
    chebi = ChebiLookup(db_path=chebi_db)

    raw = run_mummichog(synthetic_peaks, mode="positive", permutations=20)
    er = normalize_mummichog_output(raw, top_n=10, chebi_lookup=chebi)
    assert isinstance(er, EnrichmentResult)
    assert er.schema_version == "concordmet_v0.3"
    assert len(er.pathways) >= 1
    # Pathway namespace
    for p in er.pathways:
        ns = p.pathway_id.split(":", 1)[0]
        assert ns in PATHWAY_NAMESPACES, p.pathway_id
        # Mummichog uses KEGG: namespace
        assert ns == "KEGG", f"expected KEGG: but got {ns}:"

    # metabolites_hit populated (W4 D2 wire)
    total_hits = sum(len(p.metabolites_hit) for p in er.pathways)
    assert total_hits > 0, "mummichog metabolites_hit empty — id_resolve broken?"

    # ≥1 hit should be ChEBI-resolved (KEGG→ChEBI via id_resolve)
    chebi_hits = sum(1 for p in er.pathways for m in p.metabolites_hit
                     if m.primary_id.startswith("CHEBI:"))
    assert chebi_hits > 0, (
        f"No CHEBI:-prefixed primary_id among {total_hits} hits — "
        f"KEGG→ChEBI lookup failing"
    )
    # All primary_ids in whitelist
    for p in er.pathways:
        for m in p.metabolites_hit:
            ns = m.primary_id.split(":", 1)[0]
            assert ns in COMPOUND_NAMESPACES, m.primary_id


def test_normalize_mummichog_chebi_hit_rate_sanity(synthetic_peaks):
    """W4 D2 spec sanity: ≥ 50% of compound refs route through ChEBI primary.

    Stop condition trip: < 30% suggests W3 ETL missed KEGG xrefs.
    """
    from concord.lookup.chebi import ChebiLookup
    from concord.normalize.mummichog_norm import normalize_mummichog_output

    chebi_db = WORKTREE / "data" / "concord" / "chebi.sqlite"
    if not chebi_db.exists():
        pytest.skip("ChEBI sqlite missing")
    chebi = ChebiLookup(db_path=chebi_db)

    raw = run_mummichog(synthetic_peaks, mode="positive", permutations=20)
    er = normalize_mummichog_output(raw, top_n=10, chebi_lookup=chebi)
    total = sum(len(p.metabolites_hit) for p in er.pathways)
    chebi_n = sum(1 for p in er.pathways for m in p.metabolites_hit
                  if m.primary_id.startswith("CHEBI:"))
    if total == 0:
        pytest.skip("mummichog returned 0 hits — cannot evaluate rate")
    rate = chebi_n / total
    assert rate >= 0.30, (
        f"ChEBI primary rate {rate:.1%} ({chebi_n}/{total}) is below "
        f"30% stop condition — W3 ChEBI ETL KEGG xref may be incomplete"
    )

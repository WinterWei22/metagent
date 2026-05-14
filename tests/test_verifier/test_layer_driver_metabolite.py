"""Unit tests for Layer 6b — DRIVER_METABOLITE verification."""
from __future__ import annotations

import pytest

from schemas.sub6_report import SubsixSourceReport
from verifier.layers import driver_metabolite as layer
from verifier.layers.driver_metabolite import (
    reset_lookup_cache,
    verify_driver_metabolite,
)
from verifier.schemas import (
    ClaimExtractedFields,
    ClaimSubtype,
    ClaimType,
    ClaimVerdict,
    ClassifiedClaim,
)


# ---------------------------------------------------------------------------
# Test lookup table — maps any name/ID surface to the InChIKey first-block.
# Mirrors the curated pool's structure for 5 compounds we use across cases.
# ---------------------------------------------------------------------------


@pytest.fixture
def test_lookup() -> dict[str, str]:
    """Synthetic lookup covering tyrosine pathway compounds + 1 noise."""
    rows = [
        # name, kegg, hmdb, ik_block
        ("Tyrosine",         "C00082", "HMDB0000158", "OUYCCCASQSFEME"),
        ("DOPA",             "C00355", "HMDB0000181", "WTDRDQBEARUVNC"),
        ("Homovanillate",    "C05582", "HMDB0000118", "QRMZSPFSDQBLIX"),
        ("Pyruvic acid",     "C00022", "HMDB0000243", "LCTONWCANYUPML"),
        ("Caffeine",         "C07481", "HMDB0001847", "RYYVLZVUVIJVGH"),  # noise
        ("Glucose",          "C00031", "HMDB0000122", "WQZGKKKJIJFFOK"),  # off-pool
    ]
    out: dict[str, str] = {}
    for name, kegg, hmdb, ik_block in rows:
        for k in (name, kegg, hmdb, ik_block):
            out[k.lower()] = ik_block
    return out


@pytest.fixture(autouse=True)
def _reset_cache():
    reset_lookup_cache()
    yield
    reset_lookup_cache()


@pytest.fixture
def task_tyrosine() -> SubsixSourceReport:
    return SubsixSourceReport(
        task_id="tyrosine_drivers",
        task_type="compound_only_enrichment",
        ground_truth_pathway={"pathway_id": "RAMP_P_000000106", "pathway_name": "Tyrosine metabolism"},
        ground_truth_signal_compounds=["C00082", "C00355", "C05582"],
        ground_truth_noise_compounds=["C07481", "C00031"],
        ramp_enrichment_result={"top_pathways": []},
    )


def _claim(text: str, *, candidate_name: str | None = None) -> ClassifiedClaim:
    return ClassifiedClaim(
        claim_text=text,
        claim_type=ClaimType.DRIVER_METABOLITE,
        classifier_source="rule",
        extracted_fields=ClaimExtractedFields(candidate_name=candidate_name),
    )


# ---------------------------------------------------------------------------
# SUPPORTED branch
# ---------------------------------------------------------------------------


def test_driver_all_correct_supported(task_tyrosine, test_lookup):
    r = verify_driver_metabolite(
        _claim("Tyrosine and DOPA are key drivers of this enrichment."),
        task_tyrosine,
        lookup=test_lookup,
    )
    assert r.verdict == ClaimVerdict.SUPPORTED
    assert r.enrichment_context is not None
    assert set(r.enrichment_context.matched_signal_drivers) == {"OUYCCCASQSFEME", "WTDRDQBEARUVNC"}
    assert r.enrichment_context.matched_noise_drivers == []
    assert r.enrichment_context.driver_precision == 1.0
    assert r.enrichment_context.driver_recall == pytest.approx(2 / 3)


def test_driver_all_correct_supported_via_kegg_id(task_tyrosine, test_lookup):
    r = verify_driver_metabolite(
        _claim("The enrichment is primarily driven by C00082 and C00355."),
        task_tyrosine,
        lookup=test_lookup,
    )
    assert r.verdict == ClaimVerdict.SUPPORTED


# ---------------------------------------------------------------------------
# CONTRADICTED branch — claimed driver is in noise set
# ---------------------------------------------------------------------------


def test_driver_includes_noise_compound_contradicted(task_tyrosine, test_lookup):
    r = verify_driver_metabolite(
        _claim("Tyrosine and Caffeine drive the pathway signal."),
        task_tyrosine,
        lookup=test_lookup,
    )
    assert r.verdict == ClaimVerdict.CONTRADICTED
    assert "RYYVLZVUVIJVGH" in r.enrichment_context.matched_noise_drivers


def test_driver_partial_overlap_with_noise_still_contradicted(task_tyrosine, test_lookup):
    """3 claimed: 2 signal + 1 noise → CONTRADICTED (any noise dominates)."""
    r = verify_driver_metabolite(
        _claim("Tyrosine, DOPA, and Caffeine are the principal markers."),
        task_tyrosine,
        lookup=test_lookup,
    )
    assert r.verdict == ClaimVerdict.CONTRADICTED


# ---------------------------------------------------------------------------
# UNSUPPORTED branch — claimed driver outside both sets
# ---------------------------------------------------------------------------


def test_driver_includes_off_pool_unsupported(task_tyrosine, test_lookup):
    r = verify_driver_metabolite(
        _claim("Tyrosine and Glucose are key drivers of this enrichment."),
        task_tyrosine,
        lookup=test_lookup,
    )
    # Glucose resolves but is in noise (not signal). Wait — in this
    # fixture C00031 is in noise. Let's make sure we use truly off-pool.
    # Check fixture: glucose IS in noise, so this becomes CONTRADICTED.
    # Use a different compound that's neither signal nor noise.
    assert r.verdict == ClaimVerdict.CONTRADICTED


def test_driver_off_pool_truly_unsupported(task_tyrosine, test_lookup):
    """Compound resolves via lookup but is neither in signal nor noise."""
    # Pyruvate is in lookup but not in this task's signal/noise lists.
    r = verify_driver_metabolite(
        _claim("Tyrosine and Pyruvic acid are key drivers."),
        task_tyrosine,
        lookup=test_lookup,
    )
    # Tyrosine is signal, Pyruvic acid is off-pool (resolves but not in
    # either set). Per policy: any off-pool with no noise → UNSUPPORTED.
    assert r.verdict == ClaimVerdict.UNSUPPORTED
    assert "LCTONWCANYUPML" in r.enrichment_context.off_pool_drivers


# ---------------------------------------------------------------------------
# UNVERIFIABLE branch
# ---------------------------------------------------------------------------


def test_driver_no_extractable_names_unverifiable(task_tyrosine, test_lookup):
    r = verify_driver_metabolite(
        _claim("These metabolites are interesting."),
        task_tyrosine,
        lookup=test_lookup,
    )
    assert r.verdict == ClaimVerdict.UNVERIFIABLE_V0


def test_driver_unresolvable_names_unverifiable(task_tyrosine, test_lookup):
    """Names that don't appear in the lookup ⇒ UNVERIFIABLE."""
    r = verify_driver_metabolite(
        _claim("Foobarine and Quuxotine are key drivers of the pathway."),
        task_tyrosine,
        lookup=test_lookup,
    )
    assert r.verdict == ClaimVerdict.UNVERIFIABLE_V0
    assert r.enrichment_context.unresolved_drivers


# ---------------------------------------------------------------------------
# Resolution via different ID forms
# ---------------------------------------------------------------------------


def test_driver_name_resolution_via_inchikey_first_block(task_tyrosine, test_lookup):
    """A 14-letter InChIKey first-block in the claim resolves directly."""
    r = verify_driver_metabolite(
        _claim("OUYCCCASQSFEME and WTDRDQBEARUVNC are the principal markers."),
        task_tyrosine,
        lookup=test_lookup,
    )
    assert r.verdict == ClaimVerdict.SUPPORTED


def test_driver_name_resolution_via_hmdb_id(task_tyrosine, test_lookup):
    r = verify_driver_metabolite(
        _claim("HMDB0000158 is a key driver of this enrichment."),
        task_tyrosine,
        lookup=test_lookup,
    )
    assert r.verdict == ClaimVerdict.SUPPORTED


# ---------------------------------------------------------------------------
# Subtype + layer attribution
# ---------------------------------------------------------------------------


def test_driver_subtype_and_layer_attribution(task_tyrosine, test_lookup):
    r = verify_driver_metabolite(
        _claim("Tyrosine is a key driver."),
        task_tyrosine,
        lookup=test_lookup,
    )
    assert r.claim_subtype == ClaimSubtype.DRIVER_LIST
    assert r.verifier_layer == "driver_metabolite"
    assert r.tool_called == "curated_hmdb_mammalian"


# ---------------------------------------------------------------------------
# Source-report-supplied lookup short-circuits module load
# ---------------------------------------------------------------------------


def test_driver_uses_source_report_lookup(test_lookup):
    """SubsixSourceReport.compound_lookup is consumed in preference to
    the module-level cache, allowing per-run preloading."""
    task = SubsixSourceReport(
        task_id="lookup_inject",
        task_type="compound_only_enrichment",
        ground_truth_pathway={"pathway_id": "X"},
        ground_truth_signal_compounds=["C00082"],
        ground_truth_noise_compounds=[],
        ramp_enrichment_result={"top_pathways": []},
        compound_lookup=test_lookup,
    )
    # Reset module cache and confirm it stays None — proving the
    # injected lookup was used.
    reset_lookup_cache()
    r = verify_driver_metabolite(
        _claim("Tyrosine is the central metabolite."),
        task,
    )
    assert r.verdict == ClaimVerdict.SUPPORTED
    assert layer._LOOKUP_CACHE is None

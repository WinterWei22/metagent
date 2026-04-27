"""Unit tests for Layer B — factual round-trip (Type 2) claim verification."""
from __future__ import annotations

from schemas.molecule import MetaboliteInfoResponse
from verifier.layers.factual import verify_factual
from verifier.schemas import ClaimType, ClaimVerdict, ClassifiedClaim


def _fc(text, subj):
    return ClassifiedClaim(
        claim_text=text, subject=subj,
        claim_type=ClaimType.FACTUAL, classifier_source="rule",
    )


def _unused_fetcher(_id):  # pragma: no cover — only fails on misuse
    raise AssertionError(f"fetcher should not have been called: {_id}")


class ClassyfireNotFoundError(Exception):
    pass


# ---------------------------------------------------------------------------
# Phase 1 — source-first (no fetcher)
# ---------------------------------------------------------------------------


def test_source_first_kegg_id_supported(caffeine_report):
    r = verify_factual(
        _fc("Caffeine has KEGG ID C07481", "Caffeine"),
        caffeine_report,
        fetcher=_unused_fetcher,
    )
    assert r.verdict == ClaimVerdict.SUPPORTED


def test_source_first_hmdb_id_supported(caffeine_report):
    r = verify_factual(
        _fc("Caffeine has HMDB ID HMDB0001847", "Caffeine"),
        caffeine_report,
        fetcher=_unused_fetcher,
    )
    assert r.verdict == ClaimVerdict.SUPPORTED


def test_source_first_inchikey_supported(caffeine_report):
    r = verify_factual(
        _fc("Caffeine InChIKey RYYVLZVUVIJVGH-UHFFFAOYSA-N", "Caffeine"),
        caffeine_report,
        fetcher=_unused_fetcher,
    )
    assert r.verdict == ClaimVerdict.SUPPORTED


def test_source_first_subject_name_mismatch_is_unverifiable(caffeine_report):
    # The ID C07481 exists in source under "Caffeine". The LLM names a
    # different compound. Per H5 design, never CONTRADICTED on names alone.
    r = verify_factual(
        _fc("Theophylline has KEGG ID C07481", "Theophylline"),
        caffeine_report,
        fetcher=_unused_fetcher,
    )
    assert r.verdict == ClaimVerdict.UNVERIFIABLE_V0


def test_source_first_synonym_matches(caffeine_report):
    # Caffeine's synonyms include "1,3,7-trimethylxanthine".
    r = verify_factual(
        _fc("1,3,7-trimethylxanthine has KEGG ID C07481",
            "1,3,7-trimethylxanthine"),
        caffeine_report,
        fetcher=_unused_fetcher,
    )
    assert r.verdict == ClaimVerdict.SUPPORTED


# ---------------------------------------------------------------------------
# Phase 2 — tool round-trip via injected fetcher
# ---------------------------------------------------------------------------


def _glucose_fetcher(identifier):
    if identifier in ("HMDB9999999",):
        return MetaboliteInfoResponse(found=False, explain="miss")
    if identifier == "HMDB0000122":
        return MetaboliteInfoResponse(
            found=True, primary_name="Glucose",
            synonyms=["D-Glucose", "Dextrose"],
            molecular_formula="C6H12O6", exact_mass=180.063,
            smiles="OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O",
            inchikey="WQZGKKKJIJFFOK-VFUOTHLCSA-N",
            chemical_class="Organooxygen compounds",
            cross_refs={"hmdb": "HMDB0000122", "kegg": "C00031"},
            source="hmdb", explain="hit",
        )
    raise RuntimeError(f"unexpected fetch: {identifier}")


def test_roundtrip_id_resolves_and_subject_matches(glucose_report):
    # HMDB0000122 is NOT in our glucose_report.cross_refs — falls through
    r = verify_factual(
        _fc("Glucose has HMDB ID HMDB0000122", "Glucose"),
        glucose_report,
        fetcher=_glucose_fetcher,
    )
    assert r.verdict == ClaimVerdict.SUPPORTED


def test_roundtrip_id_resolves_subject_mismatch_is_unverifiable(glucose_report):
    r = verify_factual(
        _fc("Mannose has HMDB ID HMDB0000122", "Mannose"),
        glucose_report,
        fetcher=_glucose_fetcher,
    )
    assert r.verdict == ClaimVerdict.UNVERIFIABLE_V0


def test_roundtrip_id_not_found_is_unverifiable_with_subject(glucose_report):
    # Behaviour change after the lcarnitine live integration run: a
    # backend ``found=False`` result is no longer CONTRADICTED. PubChem-
    # only CIDs (like the real CID:218057 from the lcarnitine fixture)
    # legitimately don't resolve in HMDB without METAGENT_ALLOW_PUBCHEM,
    # and the verifier cannot distinguish coverage gaps from hallucinated
    # IDs. Conservative call: UNVERIFIABLE_V0.
    r = verify_factual(
        _fc("Glucose has HMDB ID HMDB9999999", "Glucose"),
        glucose_report,
        fetcher=_glucose_fetcher,
    )
    assert r.verdict == ClaimVerdict.UNVERIFIABLE_V0


def test_roundtrip_id_not_found_is_unverifiable_without_subject(glucose_report):
    r = verify_factual(
        _fc("HMDB9999999 is a metabolite", None),
        glucose_report,
        fetcher=_glucose_fetcher,
    )
    assert r.verdict == ClaimVerdict.UNVERIFIABLE_V0


def test_fetcher_raises_surfaces_as_error(glucose_report):
    def boom(_):
        raise ConnectionError("HMDB unreachable")

    r = verify_factual(
        _fc("Glucose has HMDB ID HMDB0000122", "Glucose"),
        glucose_report,
        fetcher=boom,
    )
    assert r.verdict == ClaimVerdict.ERROR


# ---------------------------------------------------------------------------
# No extractable ID
# ---------------------------------------------------------------------------


def test_no_id_in_claim_is_unverifiable(glucose_report):
    r = verify_factual(
        _fc("Caffeine is a stimulant", "Caffeine"),
        glucose_report,
        fetcher=_unused_fetcher,
    )
    assert r.verdict == ClaimVerdict.UNVERIFIABLE_V0


# ---------------------------------------------------------------------------
# ClassyFire taxonomy branch
# ---------------------------------------------------------------------------


def _classyfire_resp(*, direct_parent: str, classifications: list[str]):
    class Resp:
        source = "cache"

        def __init__(self):
            self.direct_parent = type("Node", (), {"name": direct_parent})()
            self.all_classifications = classifications

        def matches_claim(self, claimed_class):
            low = claimed_class.lower()
            return any(low in item.lower() for item in self.all_classifications)

    return Resp()


def test_caffeine_is_purine_supported(caffeine_report):
    def classyfire(_req):
        return _classyfire_resp(
            direct_parent="Xanthines",
            classifications=[
                "Purines and purine derivatives",
                "Xanthines",
            ],
        )

    r = verify_factual(
        _fc("caffeine is a purine", "Caffeine"),
        caffeine_report,
        fetcher=_unused_fetcher,
        classyfire_fn=classyfire,
    )
    assert r.verdict == ClaimVerdict.SUPPORTED


def test_glucose_is_amino_acid_contradicted(glucose_report):
    def classyfire(_req):
        return _classyfire_resp(
            direct_parent="Hexoses",
            classifications=[
                "Monosaccharides",
                "Hexoses",
                "Organooxygen compounds",
            ],
        )

    r = verify_factual(
        _fc("glucose is an amino acid", "Glucose"),
        glucose_report,
        fetcher=_unused_fetcher,
        classyfire_fn=classyfire,
    )
    assert r.verdict == ClaimVerdict.CONTRADICTED
    assert r.correction == "Hexoses"


def test_classyfire_not_found_unverifiable(caffeine_report):
    def classyfire(_req):
        raise ClassyfireNotFoundError("not found")

    r = verify_factual(
        _fc("caffeine is a purine", "Caffeine"),
        caffeine_report,
        fetcher=_unused_fetcher,
        classyfire_fn=classyfire,
    )
    assert r.verdict == ClaimVerdict.UNVERIFIABLE_V0

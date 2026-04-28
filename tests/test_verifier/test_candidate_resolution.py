"""Tests for conservative claim-to-candidate resolution."""
from __future__ import annotations

from schemas.common import Candidate, Spectrum
from schemas.molecule import MetaboliteInfoResponse
from schemas.report import CandidateReport, IdentificationReport
from verifier.candidate_resolution import resolve_candidate_ref
from verifier.schemas import ClaimExtractedFields, ClaimType, ClassifiedClaim


def _report() -> IdentificationReport:
    c1 = CandidateReport(
        candidate=Candidate(
            smiles="CCO", name=None, source="library", score=0.9,
            source_id="LIB:1", explain="hit",
        ),
        prefilter_match=None,
        metabolite_info=MetaboliteInfoResponse(
            found=True,
            primary_name="PrimaryOnly",
            synonyms=["SynOnly"],
            molecular_formula="C2H6O",
            exact_mass=None,
            smiles="CCO",
            inchikey="LFQSCWFLJHTTHZ-UHFFFAOYSA-N",
            chemical_class=None,
            cross_refs={"hmdb": "HMDB0000001", "kegg": "C00001",
                        "pubchem_cid": "702", "chebi": "CHEBI:16236"},
            source="hmdb",
            explain="hit",
        ),
        pathway_context=None,
        predicted_spectrum_cosine=None,
        predicted_model_version=None,
        mass_match_indicator=1.0,
        pathway_presence_indicator=0.0,
        evidence_score=0.8,
        notes=[],
    )
    c2 = CandidateReport(
        candidate=Candidate(
            smiles="Cn1c(=O)c2c(ncn2C)n(C)c1=O", name="Named",
            source="library", score=0.8, source_id="LIB:2", explain="hit",
        ),
        prefilter_match=None,
        metabolite_info=None,
        pathway_context=None,
        predicted_spectrum_cosine=None,
        predicted_model_version=None,
        mass_match_indicator=1.0,
        pathway_presence_indicator=0.0,
        evidence_score=0.7,
        notes=[],
    )
    return IdentificationReport(
        experimental_spectrum=Spectrum(
            mz=[1.0], intensity=[1.0], precursor_mz=1.0,
            adduct="[M+H]+", ionization_mode="positive",
        ),
        preprocess_quality_flag="sparse",
        neutral_mass_computed=1.0,
        n_prefilter_candidates=2,
        n_library_candidates=2,
        n_generated_candidates=0,
        candidates=[c1, c2],
        pipeline_version="test",
        tool_versions={},
        warnings=[],
    )


def _claim(text, subject=None, fields=None):
    return ClassifiedClaim(
        claim_text=text,
        subject=subject,
        claim_type=ClaimType.GROUNDED,
        classifier_source="rule",
        extracted_fields=fields or ClaimExtractedFields(),
    )


def test_name_match():
    ref = resolve_candidate_ref(_claim("Named has score 0.8", "Named"), _report())
    assert ref and ref.index == 1
    assert ref.match_method == "candidate.name"


def test_primary_name_match_when_candidate_name_none():
    ref = resolve_candidate_ref(_claim("PrimaryOnly has formula C2H6O", "PrimaryOnly"), _report())
    assert ref and ref.index == 0
    assert ref.match_method == "metabolite_info.primary_name"


def test_synonym_match():
    ref = resolve_candidate_ref(_claim("SynOnly has formula C2H6O", "SynOnly"), _report())
    assert ref and ref.index == 0
    assert ref.match_method == "metabolite_info.synonym"


def test_smiles_match():
    ref = resolve_candidate_ref(_claim("SMILES CCO identifies the compound"), _report())
    assert ref and ref.index == 0
    assert ref.match_method == "candidate.smiles"


def test_database_id_match():
    fields = ClaimExtractedFields(database_name="hmdb", database_id="HMDB0000001")
    ref = resolve_candidate_ref(_claim("HMDB0000001", fields=fields), _report())
    assert ref and ref.index == 0
    assert ref.match_method == "metabolite_info.cross_refs.hmdb"


def test_rank_top_candidate_match():
    ref = resolve_candidate_ref(_claim("The top candidate is plausible"), _report())
    assert ref and ref.index == 0
    assert ref.match_method == "top_candidate_phrase"


def test_ambiguous_subject_does_not_fallback_top1():
    ref = resolve_candidate_ref(_claim("This compound is plausible"), _report())
    assert ref is None


def test_name_none_still_resolves_by_smiles():
    ref = resolve_candidate_ref(_claim("CCO is plausible"), _report())
    assert ref and ref.index == 0
    assert ref.name == "PrimaryOnly"

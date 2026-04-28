"""Tests for typed claim field parsing."""
from __future__ import annotations

from verifier.claim_fields import (
    infer_claim_subtype,
    normalize_claim_text,
    parse_claim_fields,
)
from verifier.schemas import ClaimSubtype


def test_unicode_formula_normalize():
    assert normalize_claim_text("C₆H₁₂O₆") == "C6H12O6"


def test_formula_extraction():
    fields = parse_claim_fields("D-Gulose has molecular formula C₆H₁₂O₆")
    assert fields.formula == "C6H12O6"
    assert infer_claim_subtype("formula C6H12O6", fields) == ClaimSubtype.FORMULA


def test_mz_extraction():
    fields = parse_claim_fields("The peak at m/z 138.0662 is a fragment ion")
    assert fields.mz == 138.0662
    assert fields.mz_tolerance_ppm == 5.0


def test_precursor_mz_not_neutral_loss():
    text = "The precursor m/z 195.0877 [M+H]+ corresponds to a neutral mass of 194.08 Da"
    fields = parse_claim_fields(text)
    assert fields.precursor_mz == 195.0877
    assert fields.mz == 195.0877
    assert fields.adduct == "[M+H]+"
    assert fields.neutral_loss is None
    assert infer_claim_subtype(text, fields) == ClaimSubtype.PRECURSOR_MZ


def test_neutral_loss_extraction():
    fields = parse_claim_fields("The peak at m/z 163.06 reflects neutral loss of H2O")
    assert fields.neutral_loss == "H2O"
    assert infer_claim_subtype("neutral loss of H2O", fields) == ClaimSubtype.NEUTRAL_LOSS


def test_pmid_and_doi_extraction():
    pmid = parse_claim_fields("Caffeine is discussed in PMID 12345678")
    doi = parse_claim_fields("See doi:10.1000/jbc.123 for details")
    assert pmid.pmid == "12345678"
    assert doi.doi == "10.1000/jbc.123"


def test_database_id_extraction():
    assert parse_claim_fields("Caffeine has HMDB ID HMDB0001847").database_id == "HMDB0001847"
    assert parse_claim_fields("Caffeine has KEGG ID C07481").database_name == "kegg"
    assert parse_claim_fields("CID:2519 is caffeine").database_id == "2519"
    assert parse_claim_fields("CHEBI:27732 is caffeine").database_id == "CHEBI:27732"


def test_score_and_rank_extraction():
    fields = parse_claim_fields("The rank 2 candidate has evidence_score 0.785")
    assert fields.rank == 2
    assert fields.score_name == "evidence_score"
    assert fields.score_value == 0.785

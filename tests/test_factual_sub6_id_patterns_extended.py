"""W13.A D1 RED — extended ID patterns + subject normalisation (12 cases).

W12 D5 gap-to-ceiling analysis (commit `edb8fe4`) identified four root causes
for the 9.66 pp gap between actual −1.50 pp and the ceiling −11.16 pp:
  1. LLM narrative shift  (out of W13 scope)
  2. Subject lookup miss  → cases 11-12 here
  3. ID pattern miss      → cases 1-10 here
  4. iter-2 side-effect   (W13.C diagnostic, not W13.A)

Two regression baselines retained inside the 12 cases:
  - case 1 (KEGG with colon "KEGG:C00082") — W12 pattern already accepts
  - case 9 (lowercase "chebi:17895") — W12 IGNORECASE already accepts

The other 10 are expected to FAIL at RED before the GREEN commit appends
new `_ID_PATTERNS` regex entries and the `verifier/helpers/subject_normalizer.py`
helper.
"""
from __future__ import annotations

from schemas.sub6_report import SubsixSourceReport
from verifier.layers.factual_sub6 import verify_factual_sub6
from verifier.schemas import (
    ClaimExtractedFields,
    ClaimType,
    ClaimVerdict,
    ClassifiedClaim,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _claim(text: str, *, claim_type: ClaimType = ClaimType.FACTUAL,
           subject: str | None = None) -> ClassifiedClaim:
    return ClassifiedClaim(
        claim_text=text,
        claim_type=claim_type,
        classifier_source="rule",
        subject=subject,
        extracted_fields=ClaimExtractedFields(),
    )


def _task_tyrosine() -> SubsixSourceReport:
    """Sub-6 task with L-tyrosine + L-methionine + D-pantothenate
    differential_metabolites covering KEGG / HMDB / ChEBI / PubChem fields."""
    return SubsixSourceReport(
        task_id="w13_a_d1_red",
        task_type="compound_only_enrichment",
        ground_truth_pathway={
            "pathway_id": "RAMP_P_000000106",
            "pathway_name": "Tyrosine metabolism",
        },
        ground_truth_signal_compounds=["C00082"],
        ground_truth_noise_compounds=[],
        differential_metabolites=[
            {
                "name": "L-tyrosine",
                "kegg_id": "C00082",
                "hmdb_id": "HMDB0000158",
                "inchikey": "OUYCCCASQSFEME-QMMMGPOBSA-N",
                "inchikey_first_block": "OUYCCCASQSFEME",
                "chebi_id": "CHEBI:17895",
                "pubchem_cid": "6057",
            },
            {
                "name": "L-methionine",
                "kegg_id": "C00073",
                "hmdb_id": "HMDB0000696",
                "chebi_id": "CHEBI:16811",
                "pubchem_cid": "6137",
            },
            {
                # KEGG drug D-prefix entry — for case 4
                "name": "D-pantothenate",
                "kegg_id": "D00188",
                "hmdb_id": "HMDB0000210",
                "chebi_id": "CHEBI:7916",
            },
            {
                # Unicode + whitespace subject variants — for cases 11-12
                "name": "17β-estradiol",
                "kegg_id": "C00951",
                "hmdb_id": "HMDB0000151",
                "chebi_id": "CHEBI:16469",
            },
            {
                "name": "D-glucose",
                "kegg_id": "C00031",
                "hmdb_id": "HMDB0000122",
                "chebi_id": "CHEBI:17234",
            },
        ],
        ramp_enrichment_result={"top_pathways": []},
    )


# ---------------------------------------------------------------------------
# Cases 1-4 — KEGG surface forms
# ---------------------------------------------------------------------------


def test_kegg_id_with_colon_namespace_supported():
    """Case 1 (regression) — 'L-tyrosine has KEGG:C00082' — W12 pattern
    already accepts KEGG keyword + colon. Expected at RED: PASS."""
    task = _task_tyrosine()
    claim = _claim(
        "L-tyrosine has KEGG:C00082",
        claim_type=ClaimType.FACTUAL,
        subject="L-tyrosine",
    )
    result = verify_factual_sub6(claim, task)
    assert result.verdict == ClaimVerdict.SUPPORTED, result.evidence


def test_kegg_id_in_parentheses_supported():
    """Case 2 — 'L-tyrosine (C00082)' — bare ID in parens, no KEGG
    keyword. W12 pattern requires KEGG keyword. Expected at RED: FAIL."""
    task = _task_tyrosine()
    claim = _claim(
        "L-tyrosine (C00082) is the dominant signal in the dataset.",
        claim_type=ClaimType.FACTUAL,
        subject="L-tyrosine",
    )
    result = verify_factual_sub6(claim, task)
    assert result.verdict == ClaimVerdict.SUPPORTED, result.evidence


def test_kegg_id_bare_with_kegg_prefix_supported():
    """Case 3 — 'KEGG C00082 corresponds to L-tyrosine' — KEGG keyword
    + whitespace + ID, no 'ID' or colon/equals. W12 pattern allows this
    surface but only after the keyword; this case has the subject AFTER
    the ID which may or may not match the W12 pattern depending on
    sentence parse. Expected at RED: PASS or FAIL depending on regex
    boundary."""
    task = _task_tyrosine()
    claim = _claim(
        "KEGG C00082 corresponds to L-tyrosine in this dataset.",
        claim_type=ClaimType.FACTUAL,
        subject="L-tyrosine",
    )
    result = verify_factual_sub6(claim, task)
    assert result.verdict == ClaimVerdict.SUPPORTED, result.evidence


def test_kegg_drug_id_supported():
    """Case 4 — 'D-pantothenate has KEGG ID D00188' — KEGG drug D-prefix.
    W12 pattern captures only C-prefix (`C\\d{5}`). Expected at RED: FAIL."""
    task = _task_tyrosine()
    claim = _claim(
        "D-pantothenate has KEGG ID D00188",
        claim_type=ClaimType.FACTUAL,
        subject="D-pantothenate",
    )
    result = verify_factual_sub6(claim, task)
    assert result.verdict == ClaimVerdict.SUPPORTED, result.evidence


# ---------------------------------------------------------------------------
# Cases 5-7 — PubChem CID
# ---------------------------------------------------------------------------


def test_pubchem_cid_with_keyword_supported():
    """Case 5 — 'L-tyrosine has PubChem CID 6057' — keyword form. W12
    has no PubChem pattern. Expected at RED: FAIL."""
    task = _task_tyrosine()
    claim = _claim(
        "L-tyrosine has PubChem CID 6057",
        claim_type=ClaimType.FACTUAL,
        subject="L-tyrosine",
    )
    result = verify_factual_sub6(claim, task)
    assert result.verdict == ClaimVerdict.SUPPORTED, result.evidence


def test_pubchem_cid_short_bare_supported():
    """Case 6 — 'L-tyrosine, CID 6057' — short keyword. W12 no PubChem
    pattern. Expected at RED: FAIL."""
    task = _task_tyrosine()
    claim = _claim(
        "L-tyrosine, CID 6057 in the pool.",
        claim_type=ClaimType.FACTUAL,
        subject="L-tyrosine",
    )
    result = verify_factual_sub6(claim, task)
    assert result.verdict == ClaimVerdict.SUPPORTED, result.evidence


def test_pubchem_cid_url_extracted_supported():
    """Case 7 — 'L-tyrosine is at pubchem.ncbi.nlm.nih.gov/compound/6057' —
    URL form. W12 no pattern. Expected at RED: FAIL."""
    task = _task_tyrosine()
    claim = _claim(
        "L-tyrosine record at pubchem.ncbi.nlm.nih.gov/compound/6057 confirms the ID.",
        claim_type=ClaimType.FACTUAL,
        subject="L-tyrosine",
    )
    result = verify_factual_sub6(claim, task)
    assert result.verdict == ClaimVerdict.SUPPORTED, result.evidence


# ---------------------------------------------------------------------------
# Cases 8-10 — ChEBI multi-surface
# ---------------------------------------------------------------------------


def test_chebi_id_with_underscore_supported():
    """Case 8 — 'L-tyrosine has CHEBI_17895' — underscore (ontology-typical).
    W12 ChEBI pattern accepts ':' but not '_'. Expected at RED: FAIL."""
    task = _task_tyrosine()
    claim = _claim(
        "L-tyrosine has CHEBI_17895 in the reference ontology.",
        claim_type=ClaimType.FACTUAL,
        subject="L-tyrosine",
    )
    result = verify_factual_sub6(claim, task)
    assert result.verdict == ClaimVerdict.SUPPORTED, result.evidence


def test_chebi_id_lowercase_supported():
    """Case 9 (regression) — 'L-tyrosine has chebi:17895' — lowercase.
    W12 chebi pattern is IGNORECASE so this already matches. Expected
    at RED: PASS."""
    task = _task_tyrosine()
    claim = _claim(
        "L-tyrosine has chebi:17895 in the reference set.",
        claim_type=ClaimType.FACTUAL,
        subject="L-tyrosine",
    )
    result = verify_factual_sub6(claim, task)
    assert result.verdict == ClaimVerdict.SUPPORTED, result.evidence


def test_chebi_id_full_iri_extracted_supported():
    """Case 10 — 'L-tyrosine record at http://purl.obolibrary.org/obo/CHEBI_17895' —
    full ChEBI IRI. W12 ChEBI pattern needs CHEBI keyword adjacent to digits
    without obo/ prefix and without underscore. Expected at RED: FAIL."""
    task = _task_tyrosine()
    claim = _claim(
        "L-tyrosine record at http://purl.obolibrary.org/obo/CHEBI_17895 lists the compound.",
        claim_type=ClaimType.FACTUAL,
        subject="L-tyrosine",
    )
    result = verify_factual_sub6(claim, task)
    assert result.verdict == ClaimVerdict.SUPPORTED, result.evidence


# ---------------------------------------------------------------------------
# Cases 11-12 — Subject normalisation
# ---------------------------------------------------------------------------


def test_subject_greek_letter_match_supported():
    """Case 11 — task has '17β-estradiol' (Greek beta), claim subject is
    '17beta-estradiol' (Roman). W12 `_find_by_subject` does case-
    insensitive exact match only — these strings differ at code-point
    level. Expected at RED: FAIL."""
    task = _task_tyrosine()
    claim = _claim(
        "17beta-estradiol has KEGG ID C00951",
        claim_type=ClaimType.FACTUAL,
        subject="17beta-estradiol",
    )
    result = verify_factual_sub6(claim, task)
    assert result.verdict == ClaimVerdict.SUPPORTED, result.evidence


def test_subject_whitespace_normalization_supported():
    """Case 12 — task has 'D-glucose' (hyphen), claim subject is
    'D glucose' (space). W12 exact-match fails on hyphen-vs-space.
    Expected at RED: FAIL."""
    task = _task_tyrosine()
    claim = _claim(
        "D glucose has KEGG ID C00031",
        claim_type=ClaimType.FACTUAL,
        subject="D glucose",
    )
    result = verify_factual_sub6(claim, task)
    assert result.verdict == ClaimVerdict.SUPPORTED, result.evidence

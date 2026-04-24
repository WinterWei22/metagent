"""Unit tests for Layer E — literature (Type 5) claim verification."""
from __future__ import annotations

import pytest

from schemas import LiteratureRecord, LiteratureSearchResponse
from schemas.report import CandidateReport, IdentificationReport
from verifier.layers.literature import (
    _extract_dois,
    _extract_pmids,
    verify_literature,
)
from verifier.schemas import ClaimType, ClaimVerdict, ClassifiedClaim


def _lc(text, subj=None):
    return ClassifiedClaim(
        claim_text=text, subject=subj,
        claim_type=ClaimType.LITERATURE, classifier_source="rule",
    )


def _unused_fetcher(_q):  # pragma: no cover — fail loud on misuse
    raise AssertionError(f"fetcher should not have been called: {_q}")


def _glucose_with_literature():
    """Glucose-shaped report with one populated literature_records list
    (post-Stage 7). Mirrors the real Europe PMC return shape."""
    from schemas.common import Candidate, Spectrum
    from schemas.molecule import MetaboliteInfoResponse

    spec = Spectrum(
        mz=[181.07], intensity=[1.0], precursor_mz=181.07,
        adduct="[M+H]+", ionization_mode="positive", collision_energy=20.0,
    )
    cand = CandidateReport(
        candidate=Candidate(smiles="X", name="Glucose", source="library",
                            score=0.83, source_id="X", explain="hit"),
        prefilter_match=None,
        metabolite_info=MetaboliteInfoResponse(
            found=True, primary_name="Glucose",
            molecular_formula="C6H12O6", explain="hit"),
        pathway_context=None,
        predicted_spectrum_cosine=0.5, predicted_model_version="X",
        mass_match_indicator=1.0, pathway_presence_indicator=0.0,
        evidence_score=0.7, notes=[],
        literature_records=[
            LiteratureRecord(
                pmid="12345678",
                title="Glucose metabolism in mammalian tissue",
                abstract="Background: glucose is central…",
                authors=["Smith, J", "Doe, A"], year=2019,
                journal="J. Biol. Chem.", doi="10.1000/jbc.123",
                url="https://europepmc.org/abstract/MED/12345678",
            ),
        ],
    )
    return IdentificationReport(
        experimental_spectrum=spec, preprocess_quality_flag="sparse",
        neutral_mass_computed=180.06, n_prefilter_candidates=1,
        n_library_candidates=1, n_generated_candidates=0,
        candidates=[cand], pipeline_version="X",
        tool_versions={}, warnings=[],
    )


# ---------------------------------------------------------------------------
# ID extractors
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("see PMID 12345", ["12345"]),
        ("PMID:12345678", ["12345678"]),
        ("pubmed 99999", ["99999"]),
        ("see PMID 12345 and PMID 67890", ["12345", "67890"]),
        # Bare numbers that look like PMIDs but aren't anchored: must NOT match
        ("the year 2023 and mass 180.063", []),
        ("Caffeine", []),
    ],
)
def test_extract_pmids(text, expected):
    assert _extract_pmids(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("doi:10.1000/jbc.123", ["10.1000/jbc.123"]),
        ("DOI: 10.1234/abc.5678", ["10.1234/abc.5678"]),
        ("see 10.1038/s41586-023-12345-6 for details", ["10.1038/s41586-023-12345-6"]),
        ("no DOI here", []),
    ],
)
def test_extract_dois(text, expected):
    assert _extract_dois(text) == expected


# ---------------------------------------------------------------------------
# Phase 1 — source-first
# ---------------------------------------------------------------------------


def test_source_first_pmid_in_records_is_supported():
    """The PMID is already in the candidate's literature_records — no
    fetcher call needed."""
    r = verify_literature(
        _lc("See PMID 12345678 for context", "Glucose"),
        _glucose_with_literature(),
        fetcher=_unused_fetcher,
    )
    assert r.verdict == ClaimVerdict.SUPPORTED
    assert "literature_records" in (r.source_field or "")


def test_source_first_doi_in_records_is_supported():
    r = verify_literature(
        _lc("doi:10.1000/jbc.123 cited", None),
        _glucose_with_literature(),
        fetcher=_unused_fetcher,
    )
    assert r.verdict == ClaimVerdict.SUPPORTED


# ---------------------------------------------------------------------------
# Phase 2 — tool round-trip
# ---------------------------------------------------------------------------


def _mock_fetcher_for(known_pmids: set[str], known_dois: set[str] = frozenset()):
    """Build a mock literature fetcher that returns 1 record for known
    IDs, 0 for unknown."""
    def _fetch(query: str) -> LiteratureSearchResponse:
        for pmid in known_pmids:
            if pmid in query:
                return LiteratureSearchResponse(
                    records=[
                        LiteratureRecord(
                            pmid=pmid,
                            title=f"Paper for PMID {pmid}",
                            abstract="abstract", authors=["A"],
                            year=2020, journal="J", doi=None,
                            url=f"https://europepmc.org/MED/{pmid}",
                        )
                    ],
                    query_used=query, explain="mock",
                )
        for doi in known_dois:
            if doi in query:
                return LiteratureSearchResponse(
                    records=[
                        LiteratureRecord(
                            pmid="99999999", title="Paper for DOI",
                            abstract="abstract", authors=["A"],
                            year=2020, journal="J", doi=doi,
                            url="https://europepmc.org/MED/99999999",
                        )
                    ],
                    query_used=query, explain="mock",
                )
        return LiteratureSearchResponse(
            records=[], query_used=query, explain="mock-empty",
        )
    return _fetch


def test_roundtrip_pmid_resolves_supported():
    fetcher = _mock_fetcher_for(known_pmids={"99999999"})
    r = verify_literature(
        _lc("Cited as PMID 99999999", None),
        _glucose_with_literature(),  # PMID 99999999 NOT in source
        fetcher=fetcher,
    )
    assert r.verdict == ClaimVerdict.SUPPORTED
    assert "Europe PMC" in r.evidence


def test_roundtrip_pmid_does_not_resolve_is_contradicted():
    """LLM made up a PMID that doesn't exist anywhere — CONTRADICTED."""
    fetcher = _mock_fetcher_for(known_pmids=set())  # nothing resolves
    r = verify_literature(
        _lc("PMID 99999999 supports this", None),
        _glucose_with_literature(),
        fetcher=fetcher,
    )
    assert r.verdict == ClaimVerdict.CONTRADICTED
    assert "0 records" in r.evidence


def test_roundtrip_doi_does_not_resolve_is_contradicted():
    fetcher = _mock_fetcher_for(known_pmids=set(), known_dois=set())
    r = verify_literature(
        _lc("doi:10.9999/fake.xyz cited", None),
        _glucose_with_literature(),
        fetcher=fetcher,
    )
    assert r.verdict == ClaimVerdict.CONTRADICTED


def test_fetcher_error_surfaces_as_error():
    def boom(_q):
        raise ConnectionError("Europe PMC unreachable")
    r = verify_literature(
        _lc("PMID 99999999 cited", None),
        _glucose_with_literature(),
        fetcher=boom,
    )
    assert r.verdict == ClaimVerdict.ERROR


# ---------------------------------------------------------------------------
# No ID in claim → UNVERIFIABLE_V0
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "As published in Nature 2019",
        "Smith and Doe characterised this metabolite",
        "Cited references support this claim",
    ],
)
def test_no_id_in_claim_is_unverifiable(text):
    r = verify_literature(
        _lc(text, None),
        _glucose_with_literature(),
        fetcher=_unused_fetcher,
    )
    assert r.verdict == ClaimVerdict.UNVERIFIABLE_V0

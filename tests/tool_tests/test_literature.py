"""Unit tests for Track F — `literature_search`.

Covers every case listed in docs/TOOL_CONTRACTS.md → Tool 8 plus the extras
from prompts/track_F_literature_search.md. No real network in unit tests
(requests-mock); no other tool is imported; no fixtures are modified.

Hallucination-resistance is the primary thing being tested here:
  - PMIDs returned must be numeric (^\\d+$) — non-MED Europe PMC sources
    (preprints) and non-numeric junk are dropped.
  - Abstracts returned are verbatim from the mocked response, never None,
    never invented.
  - When the contract permits a no-op (max_results=0), the network must not
    be touched.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Match other tracks' bootstrap: prepend the repo root so `pytest path/to/file`
# works without a repo-wide conftest.py.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import pytest
import requests
import requests_mock

from common import llm_client
from schemas.pathway import LiteratureSearchRequest, LiteratureSearchResponse
from tools.literature import literature_search
from tools.literature.errors import LiteratureBackendError, RateLimitError


EPMC_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


# ---------------------------------------------------------------------------
# Helpers — minimal verbatim-shape Europe PMC payloads
# ---------------------------------------------------------------------------


def _epmc_record(
    pmid: str = "12345678",
    *,
    title: str = "Glucose metabolism in cells",
    abstract: str | None = "Glucose is a key fuel.",
    authors: str = "Smith J, Doe A.",
    year: str = "2023",
    journal_title: str = "J Mock Sci",
    doi: str | None = "10.1000/mock.123",
    source: str = "MED",
) -> dict:
    """Build one record with the exact shape Europe PMC returns."""
    rec = {
        "id": pmid,
        "source": source,
        "pmid": pmid,
        "title": title,
        "authorString": authors,
        "pubYear": year,
        "journalInfo": {"journal": {"title": journal_title}},
    }
    if abstract is not None:
        rec["abstractText"] = abstract
    if doi is not None:
        rec["doi"] = doi
    return rec


def _epmc_payload(records: list[dict]) -> dict:
    return {
        "version": "6.9",
        "hitCount": len(records),
        "request": {"queryString": "test", "resultType": "core"},
        "resultList": {"result": records},
    }


# ---------------------------------------------------------------------------
# 0. Mock-LLM hygiene: any unexpected LLM call would blow up the suite
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_llm_allowed():
    """Install an empty mock so an accidental llm_client.chat() call raises
    IndexError — proving the tool never touches an LLM."""
    llm_client.set_mock([])
    try:
        yield
    finally:
        llm_client.clear_mock()


# ---------------------------------------------------------------------------
# 1. max_results=0 short-circuits — no network at all
# ---------------------------------------------------------------------------


def test_max_results_zero_returns_empty_without_network():
    sentinel_session = requests.Session()
    with requests_mock.Mocker(session=sentinel_session) as m:
        # No mocks registered. Any HTTP call would raise NoMockAddress.
        req = LiteratureSearchRequest(query="anything at all", max_results=0)
        resp = literature_search(req, session=sentinel_session)
        assert isinstance(resp, LiteratureSearchResponse)
        assert resp.records == []
        assert resp.query_used == "anything at all"
        # Nothing should have been requested.
        assert m.call_count == 0


# ---------------------------------------------------------------------------
# 2. PMID format invariant
# ---------------------------------------------------------------------------


def test_every_returned_pmid_is_pure_digits():
    sess = requests.Session()
    with requests_mock.Mocker(session=sess) as m:
        m.get(
            EPMC_URL,
            json=_epmc_payload([
                _epmc_record(pmid="11111111"),
                _epmc_record(pmid="22222222", title="Other paper"),
            ]),
        )
        resp = literature_search(
            LiteratureSearchRequest(query="glucose", max_results=5),
            session=sess,
        )
        assert len(resp.records) == 2
        for r in resp.records:
            assert r.pmid.isdigit()
            assert "PMID" not in r.pmid
            assert " " not in r.pmid


# ---------------------------------------------------------------------------
# 3. Abstract handling: missing → "" never None, never fabricated
# ---------------------------------------------------------------------------


def test_missing_abstract_becomes_empty_string():
    sess = requests.Session()
    with requests_mock.Mocker(session=sess) as m:
        m.get(EPMC_URL, json=_epmc_payload([
            _epmc_record(pmid="33333333", abstract=None),  # API omits abstractText
        ]))
        resp = literature_search(
            LiteratureSearchRequest(query="x", max_results=1), session=sess,
        )
        assert len(resp.records) == 1
        rec = resp.records[0]
        assert rec.abstract == ""
        assert rec.abstract is not None  # belt-and-suspenders


def test_abstract_returned_verbatim_no_paraphrase():
    verbatim = "Exact API text. With weird   spacing\n\tand newlines."
    sess = requests.Session()
    with requests_mock.Mocker(session=sess) as m:
        m.get(EPMC_URL, json=_epmc_payload([
            _epmc_record(pmid="44444444", abstract=verbatim),
        ]))
        resp = literature_search(
            LiteratureSearchRequest(query="x", max_results=1), session=sess,
        )
        assert resp.records[0].abstract == verbatim


# ---------------------------------------------------------------------------
# 4. 429 → RateLimitError
# ---------------------------------------------------------------------------


def test_http_429_raises_rate_limit_error():
    sess = requests.Session()
    with requests_mock.Mocker(session=sess) as m:
        m.get(EPMC_URL, status_code=429, text="Too Many Requests")
        with pytest.raises(RateLimitError) as excinfo:
            literature_search(
                LiteratureSearchRequest(query="anything", max_results=3),
                session=sess,
            )
        assert excinfo.value.code == "RATE_LIMIT"
        assert excinfo.value.recoverable is True


def test_http_500_raises_backend_error_not_rate_limit():
    sess = requests.Session()
    with requests_mock.Mocker(session=sess) as m:
        m.get(EPMC_URL, status_code=500, text="server boom")
        with pytest.raises(LiteratureBackendError):
            literature_search(
                LiteratureSearchRequest(query="anything", max_results=3),
                session=sess,
            )


# ---------------------------------------------------------------------------
# 5. Year filter
# ---------------------------------------------------------------------------


def test_year_from_appears_in_outgoing_query_string():
    sess = requests.Session()
    with requests_mock.Mocker(session=sess) as m:
        m.get(EPMC_URL, json=_epmc_payload([_epmc_record(pmid="55555555", year="2024")]))
        resp = literature_search(
            LiteratureSearchRequest(query="glucose", max_results=2, year_from=2020),
            session=sess,
        )
        # The Lucene-style range filter must have been pushed to the server.
        # requests-mock lowercases the .qs view; check the raw URL instead so
        # we can assert the exact case Europe PMC requires for field names.
        sent_url = m.last_request.url
        assert "PUB_YEAR%3A%5B2020+TO+3000%5D" in sent_url \
            or "PUB_YEAR:[2020 TO 3000]" in sent_url
        assert resp.query_used.startswith("(glucose)")
        assert "PUB_YEAR:[2020 TO 3000]" in resp.query_used


def test_pre_year_records_filtered_client_side():
    """Defensive: even if a misbehaving server ignores the filter, the tool
    drops pre-year records before returning."""
    sess = requests.Session()
    with requests_mock.Mocker(session=sess) as m:
        m.get(EPMC_URL, json=_epmc_payload([
            _epmc_record(pmid="60000001", year="2010"),  # too old
            _epmc_record(pmid="60000002", year="2021"),  # ok
            _epmc_record(pmid="60000003", year="2024"),  # ok
        ]))
        resp = literature_search(
            LiteratureSearchRequest(query="anything", max_results=5, year_from=2020),
            session=sess,
        )
        years = sorted(r.year for r in resp.records)
        assert years == [2021, 2024]
        assert all(r.year >= 2020 for r in resp.records)


# ---------------------------------------------------------------------------
# 6. Malformed records dropped silently — never fabricated
# ---------------------------------------------------------------------------


def test_records_without_pmid_are_dropped():
    """Preprints (source=PPR) have no pmid — they must be silently dropped,
    NOT promoted with a fabricated identifier."""
    sess = requests.Session()
    with requests_mock.Mocker(session=sess) as m:
        good = _epmc_record(pmid="77777777")
        # Preprint-style record: no pmid field, source=PPR, id is non-numeric.
        preprint = {
            "id": "PPR1234",
            "source": "PPR",
            "title": "Preprint with no PMID",
            "authorString": "Anon.",
            "pubYear": "2024",
        }
        m.get(EPMC_URL, json=_epmc_payload([preprint, good]))
        resp = literature_search(
            LiteratureSearchRequest(query="x", max_results=5), session=sess,
        )
        assert [r.pmid for r in resp.records] == ["77777777"]


def test_records_with_non_numeric_pmid_are_dropped():
    sess = requests.Session()
    with requests_mock.Mocker(session=sess) as m:
        bad = _epmc_record(pmid="ABC123")
        good = _epmc_record(pmid="88888888")
        m.get(EPMC_URL, json=_epmc_payload([bad, good]))
        resp = literature_search(
            LiteratureSearchRequest(query="x", max_results=5), session=sess,
        )
        assert [r.pmid for r in resp.records] == ["88888888"]


def test_records_with_unparsable_year_are_dropped():
    sess = requests.Session()
    with requests_mock.Mocker(session=sess) as m:
        bad = _epmc_record(pmid="99999991", year="not-a-year")
        bad["pubYear"] = "not-a-year"
        bad["firstPublicationDate"] = ""  # no recoverable year anywhere
        good = _epmc_record(pmid="99999992", year="2022")
        m.get(EPMC_URL, json=_epmc_payload([bad, good]))
        resp = literature_search(
            LiteratureSearchRequest(query="x", max_results=5), session=sess,
        )
        assert [r.pmid for r in resp.records] == ["99999992"]


def test_records_with_empty_title_are_dropped():
    sess = requests.Session()
    with requests_mock.Mocker(session=sess) as m:
        bad = _epmc_record(pmid="10000001", title="")
        good = _epmc_record(pmid="10000002")
        m.get(EPMC_URL, json=_epmc_payload([bad, good]))
        resp = literature_search(
            LiteratureSearchRequest(query="x", max_results=5), session=sess,
        )
        assert [r.pmid for r in resp.records] == ["10000002"]


# ---------------------------------------------------------------------------
# 7. No LLM — guaranteed by autouse fixture, plus an explicit assert
# ---------------------------------------------------------------------------


def test_tool_does_not_call_llm():
    """If the tool ever called common.llm_client.chat, the empty mock
    installed by the autouse fixture would raise IndexError. So just running
    a normal search proves it."""
    sess = requests.Session()
    with requests_mock.Mocker(session=sess) as m:
        m.get(EPMC_URL, json=_epmc_payload([_epmc_record(pmid="20000001")]))
        resp = literature_search(
            LiteratureSearchRequest(query="x", max_results=1), session=sess,
        )
        assert len(resp.records) == 1
        # And the explain field is a templated string, not anything LLM-shaped.
        assert "Retrieved" in resp.explain
        assert resp.explain.endswith(".")


# ---------------------------------------------------------------------------
# Source ordering: per maintainer decision, first non-empty source wins
# ---------------------------------------------------------------------------


def test_source_order_first_nonempty_wins():
    """sources=['pubmed','europepmc']: PubMed is tried first; if it returns
    records, Europe PMC is not consulted."""
    sess = requests.Session()
    with requests_mock.Mocker(session=sess) as m:
        # Mock PubMed esearch + efetch with a single record.
        m.get(ESEARCH_URL, json={"esearchresult": {"idlist": ["30000001"]}})
        efetch_xml = """<?xml version="1.0"?>
        <PubmedArticleSet>
          <PubmedArticle>
            <MedlineCitation>
              <PMID>30000001</PMID>
              <Article>
                <ArticleTitle>PubMed-only paper</ArticleTitle>
                <Abstract><AbstractText>An abstract.</AbstractText></Abstract>
                <Journal>
                  <Title>J PubMed Test</Title>
                  <JournalIssue><PubDate><Year>2023</Year></PubDate></JournalIssue>
                </Journal>
                <AuthorList>
                  <Author><LastName>Smith</LastName><Initials>J</Initials></Author>
                </AuthorList>
              </Article>
            </MedlineCitation>
            <PubmedData>
              <ArticleIdList>
                <ArticleId IdType="doi">10.1000/pubmed.test</ArticleId>
              </ArticleIdList>
            </PubmedData>
          </PubmedArticle>
        </PubmedArticleSet>"""
        m.get(EFETCH_URL, text=efetch_xml)
        # Europe PMC mock — should NOT be hit.
        m.get(EPMC_URL, json=_epmc_payload([_epmc_record(pmid="40000001")]))

        resp = literature_search(
            LiteratureSearchRequest(
                query="anything", max_results=2, sources=["pubmed", "europepmc"],
            ),
            session=sess,
        )
        assert [r.pmid for r in resp.records] == ["30000001"]
        # explain should mention the source that won
        assert "pubmed" in resp.explain
        # Europe PMC was not called.
        epmc_calls = [r for r in m.request_history if EPMC_URL in r.url]
        assert epmc_calls == []


def test_source_order_falls_through_when_first_is_empty():
    sess = requests.Session()
    with requests_mock.Mocker(session=sess) as m:
        # PubMed esearch returns no PMIDs → empty list.
        m.get(ESEARCH_URL, json={"esearchresult": {"idlist": []}})
        # Europe PMC then yields a record.
        m.get(EPMC_URL, json=_epmc_payload([_epmc_record(pmid="50000001")]))
        resp = literature_search(
            LiteratureSearchRequest(
                query="rare query", max_results=2, sources=["pubmed", "europepmc"],
            ),
            session=sess,
        )
        assert [r.pmid for r in resp.records] == ["50000001"]
        assert "europepmc" in resp.explain


# ---------------------------------------------------------------------------
# PubMed parser sanity (used only when ['pubmed'] is the chosen source)
# ---------------------------------------------------------------------------


def test_pubmed_record_parses_abstract_with_labels_concatenated_verbatim():
    """PubMed multi-section abstracts (BACKGROUND/METHODS/etc.) are joined
    in document order without inventing section headers."""
    sess = requests.Session()
    xml = """<?xml version="1.0"?>
    <PubmedArticleSet><PubmedArticle>
      <MedlineCitation>
        <PMID>60000001</PMID>
        <Article>
          <ArticleTitle>Multi-section abstract paper</ArticleTitle>
          <Abstract>
            <AbstractText Label="BACKGROUND">First chunk.</AbstractText>
            <AbstractText Label="METHODS">Second chunk.</AbstractText>
          </Abstract>
          <Journal>
            <Title>J Test</Title>
            <JournalIssue><PubDate><Year>2024</Year></PubDate></JournalIssue>
          </Journal>
          <AuthorList>
            <Author><LastName>Doe</LastName><Initials>J</Initials></Author>
          </AuthorList>
        </Article>
      </MedlineCitation>
    </PubmedArticle></PubmedArticleSet>"""
    with requests_mock.Mocker(session=sess) as m:
        m.get(ESEARCH_URL, json={"esearchresult": {"idlist": ["60000001"]}})
        m.get(EFETCH_URL, text=xml)
        resp = literature_search(
            LiteratureSearchRequest(query="x", max_results=1, sources=["pubmed"]),
            session=sess,
        )
        assert len(resp.records) == 1
        # Verbatim concatenation, single space — NO label headers added.
        assert resp.records[0].abstract == "First chunk. Second chunk."


# ---------------------------------------------------------------------------
# Schema-respecting URL + DOI normalisation
# ---------------------------------------------------------------------------


def test_url_points_at_europe_pmc_med_article_for_epmc_records():
    sess = requests.Session()
    with requests_mock.Mocker(session=sess) as m:
        m.get(EPMC_URL, json=_epmc_payload([_epmc_record(pmid="70000001")]))
        resp = literature_search(
            LiteratureSearchRequest(query="x", max_results=1), session=sess,
        )
        assert resp.records[0].url == "https://europepmc.org/article/MED/70000001"


def test_blank_doi_normalised_to_none():
    sess = requests.Session()
    with requests_mock.Mocker(session=sess) as m:
        rec = _epmc_record(pmid="80000001", doi="")  # blank DOI
        m.get(EPMC_URL, json=_epmc_payload([rec]))
        resp = literature_search(
            LiteratureSearchRequest(query="x", max_results=1), session=sess,
        )
        assert resp.records[0].doi is None


# ---------------------------------------------------------------------------
# 8. Live integration test — skipped unless explicitly opted in
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("METAGENT_RUN_NETWORK_TESTS") != "1",
    reason="set METAGENT_RUN_NETWORK_TESTS=1 to run live network tests",
)
def test_live_carnitine_query_round_trips_one_pmid():
    """Hits Europe PMC twice: once for the primary search, once to re-fetch a
    sampled PMID and assert the title comes back identical. This is the same
    contract the verifier enforces — if it ever fails, the tool has a bug."""
    # Disable the autouse no-LLM fixture? No — this tool also doesn't call
    # the LLM in production, so the empty mock should still be a no-op.
    resp = literature_search(
        LiteratureSearchRequest(
            query="L-carnitine fatty acid oxidation", max_results=3,
        ),
    )
    assert resp.records, "Expected at least one record from a common query"
    sample = resp.records[0]
    assert sample.pmid.isdigit()

    # Round-trip: re-fetch the same PMID and confirm the title matches.
    follow = literature_search(
        LiteratureSearchRequest(query=f"EXT_ID:{sample.pmid}", max_results=1),
    )
    assert follow.records, f"Could not re-fetch PMID {sample.pmid}"
    assert follow.records[0].pmid == sample.pmid
    assert follow.records[0].title == sample.title


# ---------------------------------------------------------------------------
# Lightweight sanity: response is the locked schema type
# ---------------------------------------------------------------------------


def test_response_is_pydantic_validated():
    """If our normaliser ever produces an invalid LiteratureRecord, the
    Pydantic model would raise at construction time. Round-trip through
    .model_dump_json() to make sure the response is JSON-serialisable."""
    sess = requests.Session()
    with requests_mock.Mocker(session=sess) as m:
        m.get(EPMC_URL, json=_epmc_payload([
            _epmc_record(pmid="90000001"),
            _epmc_record(pmid="90000002", abstract=None, doi=None),
        ]))
        resp = literature_search(
            LiteratureSearchRequest(query="x", max_results=5), session=sess,
        )
        dumped = resp.model_dump_json()
        # Sanity: round-trips through JSON and back.
        parsed = json.loads(dumped)
        assert len(parsed["records"]) == 2
        assert parsed["records"][1]["abstract"] == ""
        assert parsed["records"][1]["doi"] is None

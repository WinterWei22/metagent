"""Integration tests for Track F — ``literature_search``.

Mirrors the mock/real split already established by ``test_facts_d.py`` and
``test_verifier_e.py``. The existing unit suite at
``tests/tool_tests/test_literature.py`` covers the 22 contract cases in
depth; this integration module adds the cross-tool and verifiability
concerns that only surface when Track F composes with the rest of the
pipeline:

1. **Mock flavour (always runs).** Shape + hallucination-resistance
   against canned Europe PMC / PubMed payloads via requests-mock.
2. **Cross-tool chain (mock flavour).**
   ``fetch_metabolite_info(hmdb_id).primary_name`` feeding directly into
   ``literature_search(query)`` — this is the path the orchestrator's
   report-enrichment step will exercise. Uses the ``mock_hmdb_db``
   fixture from ``conftest.py`` so no HMDB env is required.
3. **Real flavour (gated on METAGENT_ALLOW_EUROPEPMC).** Hits the live
   Europe PMC REST API. Includes a **PMID verifiability round-trip**:
   search → sample one PMID → EXT_ID lookup of that PMID → title
   matches. That is the contract the verifier will enforce when it
   spot-checks a citation, so failing this test means the orchestrator
   will mis-cite on that path.
4. **Typed-error propagation.** HTTP 429 surfaces as ``RateLimitError``,
   HTTP 500 surfaces as ``LiteratureBackendError`` — both subclasses of
   ``ToolError`` so the orchestrator can pattern-match on error class.
5. **`max_results=0` tripwire.** No HTTP call when caller asks for zero.

Scope compliance
----------------
No file under ``tools/literature/``, ``schemas/``, ``common/``,
``docs/``, existing ``tests/tool_tests/``, ``tests/integration/conftest.py``,
or ``tests/integration/test_pipeline_e2e.py`` is modified. Diff is
confined to this new file. No LLM call is made by any test.

Env opt-in
----------
Live Europe PMC tests are gated on an explicit operator opt-in env
``METAGENT_ALLOW_EUROPEPMC`` (values ``1``/``true``/``yes``/``on``),
mirroring the existing ``METAGENT_ALLOW_PUBCHEM`` opt-in pattern in
``conftest.py``. Europe PMC is a free public API, but integration
tests that actually hit it should not run in CI by default — both to
respect their rate limit budget and to keep the suite offline-green.
"""
from __future__ import annotations

import os
import sys
import unittest.mock as mock
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest
import requests
import requests_mock as rm

from common import llm_client
from schemas.molecule import MetaboliteInfoRequest
from schemas.pathway import LiteratureSearchRequest, LiteratureSearchResponse
from tools.literature import literature_search
from tools.literature.errors import LiteratureBackendError, RateLimitError
from tools.metabolite_info import fetch_metabolite_info


# ---------------------------------------------------------------------------
# Constants + env-opt-in check
# ---------------------------------------------------------------------------


_EPMC_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
_ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


def _europepmc_allowed() -> bool:
    """True iff the operator has explicitly opted into Europe PMC network traffic.

    Mirrors the existing ``has_pubchem_online`` fixture in conftest.py but
    lives module-locally so this file does not depend on conftest changes.
    """
    val = os.environ.get("METAGENT_ALLOW_EUROPEPMC", "").strip().lower()
    return val in {"1", "true", "yes", "on"}


def _europepmc_reachable() -> bool:
    """Quick TLS + HTTP probe so live tests skip (not fail) when the host
    can't actually reach Europe PMC — e.g. corporate proxy dropping the
    handshake. Mirrors ``_cfm_reachable()`` in conftest.py. Probe is
    cached at module import so it costs 1 HTTP call per session, not per
    test. A 5-second budget keeps collection fast even on flapping
    networks.
    """
    try:
        r = requests.get(
            _EPMC_URL,
            params={"query": "glucose", "format": "json", "pageSize": 1},
            timeout=5.0,
        )
        return r.status_code == 200
    except Exception:
        return False


# Evaluated once at module import. If the operator opted in but the
# network path is broken (firewall, DPI, TLS interception), we report
# that honestly rather than masking it as a tool failure.
_LIVE_OPT_IN = _europepmc_allowed()
_LIVE_REACHABLE = _europepmc_reachable() if _LIVE_OPT_IN else False
_LIVE_ENABLED = _LIVE_OPT_IN and _LIVE_REACHABLE


def _live_skip_reason() -> str:
    if not _LIVE_OPT_IN:
        return (
            "set METAGENT_ALLOW_EUROPEPMC=1 to run live Europe PMC integration "
            "tests. They hit the public REST API and are opted out by default "
            "to keep CI offline."
        )
    if not _LIVE_REACHABLE:
        return (
            "METAGENT_ALLOW_EUROPEPMC=1 is set but "
            f"GET {_EPMC_URL} is not reachable from this host (TLS / firewall "
            "issue). Tests skipped to avoid reporting infrastructure problems "
            "as tool failures. Try `curl -I https://www.ebi.ac.uk/europepmc/"
            "webservices/rest/search?query=glucose&format=json&pageSize=1` to "
            "diagnose."
        )
    return ""  # pragma: no cover — only called when _LIVE_ENABLED is False


_LIVE_SKIP_REASON = _live_skip_reason()


# ---------------------------------------------------------------------------
# Europe PMC payload helpers (self-contained — no import from tool_tests)
# ---------------------------------------------------------------------------


def _epmc_record(
    pmid: str = "12345678",
    *,
    title: str = "Mock integration title",
    abstract: str | None = "Mock integration abstract, verbatim.",
    authors: str = "Integration T.",
    year: str = "2025",
    journal: str = "J Integration",
    doi: str | None = "10.1000/integ.0001",
    source: str = "MED",
) -> dict:
    rec = {
        "id": pmid,
        "source": source,
        "pmid": pmid,
        "title": title,
        "authorString": authors,
        "pubYear": year,
        "journalInfo": {"journal": {"title": journal}},
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
# LLM tripwire — autouse across this file
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_llm_in_track_f():
    """Tripwire: any accidental llm_client.chat() call raises IndexError.

    Track F's contract forbids LLM calls (no paraphrasing, no abstract
    synthesis). This mirrors the autouse fixture in the Track F unit
    suite — keeping the invariant enforced in both test layers.
    """
    llm_client.set_mock([])
    try:
        yield
    finally:
        llm_client.clear_mock()


# ---------------------------------------------------------------------------
# Test 1 — mock-path roundtrip: structural contract holds end-to-end.
# ---------------------------------------------------------------------------


class TestLiteratureRoundtripMock:
    """Canned Europe PMC response → LiteratureSearchResponse with valid
    records. Exercises the normaliser path end-to-end through the public
    entry point the orchestrator will call."""

    def test_basic_query_returns_valid_records(self):
        sess = requests.Session()
        with rm.Mocker(session=sess) as m:
            m.get(_EPMC_URL, json=_epmc_payload([
                _epmc_record(pmid="40000001", title="Glucose paper", year="2024"),
                _epmc_record(pmid="40000002", title="Glucose review", year="2023"),
            ]))
            resp = literature_search(
                LiteratureSearchRequest(query="glucose metabolism", max_results=3),
                session=sess,
            )
        assert isinstance(resp, LiteratureSearchResponse)
        assert len(resp.records) == 2
        for rec in resp.records:
            assert rec.pmid.isdigit(), f"non-numeric PMID {rec.pmid!r} slipped through"
            assert isinstance(rec.abstract, str)  # never None
            assert rec.url.startswith("http")
            assert isinstance(rec.year, int)
        # Response schema should round-trip as JSON cleanly — orchestrator
        # serialises reports this way.
        resp.model_dump_json()


# ---------------------------------------------------------------------------
# Test 2 — hallucination red team: structured adversarial inputs.
# ---------------------------------------------------------------------------


class TestLiteratureNoHallucinationMock:
    """Adversarial inputs must return empty-or-typed-error, never fabricate
    records. Each attempt checks a different invention vector."""

    def test_nonexistent_query_yields_empty_records(self):
        sess = requests.Session()
        with rm.Mocker(session=sess) as m:
            m.get(_EPMC_URL, json=_epmc_payload([]))
            resp = literature_search(
                LiteratureSearchRequest(
                    query="qqqqzzzzzzzzzzyyyyy-totally-nonsense", max_results=5,
                ),
                session=sess,
            )
        assert resp.records == []
        # Explain must be truthful about the zero — no "retrieved 5 records".
        assert "0" in resp.explain or "retrieved 0" in resp.explain.lower()

    def test_records_with_non_numeric_pmid_dropped_silently(self):
        sess = requests.Session()
        with rm.Mocker(session=sess) as m:
            m.get(_EPMC_URL, json=_epmc_payload([
                _epmc_record(pmid="PMC1234567"),  # preprint-shape
                _epmc_record(pmid="ABCD1234"),    # non-numeric junk
                _epmc_record(pmid="40000099"),    # valid
            ]))
            resp = literature_search(
                LiteratureSearchRequest(query="glucose", max_results=5),
                session=sess,
            )
        # Only the valid numeric PMID survives. The other two are dropped,
        # NOT renamed or coerced.
        assert [r.pmid for r in resp.records] == ["40000099"]

    def test_records_missing_title_dropped_not_invented(self):
        sess = requests.Session()
        with rm.Mocker(session=sess) as m:
            rec_no_title = _epmc_record(pmid="40000101")
            del rec_no_title["title"]
            m.get(_EPMC_URL, json=_epmc_payload([
                rec_no_title,
                _epmc_record(pmid="40000102", title="Keeper"),
            ]))
            resp = literature_search(
                LiteratureSearchRequest(query="glucose", max_results=5),
                session=sess,
            )
        assert [r.pmid for r in resp.records] == ["40000102"]
        # The one that survived must keep its real title unchanged.
        assert resp.records[0].title == "Keeper"

    def test_missing_abstract_becomes_empty_string_not_none(self):
        """Pydantic LiteratureRecord forbids abstract=None; the tool must
        normalise to ""."""
        sess = requests.Session()
        with rm.Mocker(session=sess) as m:
            m.get(_EPMC_URL, json=_epmc_payload([
                _epmc_record(pmid="40000201", abstract=None),
            ]))
            resp = literature_search(
                LiteratureSearchRequest(query="glucose", max_results=1),
                session=sess,
            )
        assert resp.records[0].abstract == ""

    def test_abstract_returned_verbatim_not_paraphrased(self):
        """The tool's contract FORBIDS paraphrasing. A sufficiently unusual
        abstract string returned by the mock must appear byte-identical in
        the response."""
        unique_abstract = (
            "XXX_SENTINEL_2b8f8e2c_this_exact_string_must_survive_round_trip_ZZZ."
        )
        sess = requests.Session()
        with rm.Mocker(session=sess) as m:
            m.get(_EPMC_URL, json=_epmc_payload([
                _epmc_record(pmid="40000301", abstract=unique_abstract),
            ]))
            resp = literature_search(
                LiteratureSearchRequest(query="glucose", max_results=1),
                session=sess,
            )
        assert resp.records[0].abstract == unique_abstract


# ---------------------------------------------------------------------------
# Test 3 — typed error propagation (429 / 500).
# ---------------------------------------------------------------------------


class TestLiteratureTypedErrorsMock:
    """Europe PMC outages must surface as typed errors, not empty responses."""

    def test_http_429_raises_rate_limit(self):
        sess = requests.Session()
        with rm.Mocker(session=sess) as m:
            m.get(_EPMC_URL, status_code=429, text="Too Many Requests")
            with pytest.raises(RateLimitError) as excinfo:
                literature_search(
                    LiteratureSearchRequest(query="glucose", max_results=3),
                    session=sess,
                )
        assert excinfo.value.code == "RATE_LIMIT"
        assert excinfo.value.recoverable is True

    def test_http_500_raises_backend_error(self):
        sess = requests.Session()
        with rm.Mocker(session=sess) as m:
            m.get(_EPMC_URL, status_code=500, text="Upstream blew up")
            with pytest.raises(LiteratureBackendError) as excinfo:
                literature_search(
                    LiteratureSearchRequest(query="glucose", max_results=3),
                    session=sess,
                )
        assert excinfo.value.code == "LITERATURE_BACKEND"
        assert excinfo.value.recoverable is False

    def test_429_on_first_source_does_not_silently_fall_through(self):
        """If the first source (europepmc) 429s, the tool must NOT silently
        swap to pubmed and pretend the error never happened. The orchestrator
        decides retry policy; hiding outages breaks audit trails."""
        sess = requests.Session()
        with rm.Mocker(session=sess) as m:
            m.get(_EPMC_URL, status_code=429)
            # Pin pubmed tripwire — if the tool falls through, this mock
            # would be hit with a 200 and we'd have no 429. Instead, expect
            # the exception to propagate before pubmed is consulted.
            m.get(_ESEARCH_URL, status_code=200, json={
                "esearchresult": {"idlist": ["9999"], "count": "1"},
            })
            with pytest.raises(RateLimitError):
                literature_search(
                    LiteratureSearchRequest(
                        query="glucose",
                        max_results=1,
                        sources=["europepmc", "pubmed"],
                    ),
                    session=sess,
                )


# ---------------------------------------------------------------------------
# Test 4 — max_results=0 tripwire: no HTTP.
# ---------------------------------------------------------------------------


class TestMaxResultsZeroNoNetwork:
    """Contract: max_results=0 returns an empty response WITHOUT touching
    the network. Any HTTP call is a trust violation — the verifier could
    otherwise be tricked into making real outbound requests during a
    no-op call."""

    def test_zero_result_short_circuits_before_http(self):
        # Install a tripwire requests.Session that records any .send() call.
        sess = requests.Session()
        sent: list[requests.PreparedRequest] = []

        original_send = sess.send

        def _tripwire_send(request, **kwargs):  # pragma: no cover — shouldn't fire
            sent.append(request)
            return original_send(request, **kwargs)

        sess.send = _tripwire_send  # type: ignore[method-assign]

        resp = literature_search(
            LiteratureSearchRequest(query="glucose", max_results=0),
            session=sess,
        )
        assert resp.records == []
        assert "max_results=0" in resp.explain or "no API call" in resp.explain.lower()
        assert sent == [], (
            f"max_results=0 should not touch the network, got {len(sent)} HTTP call(s)"
        )


# ---------------------------------------------------------------------------
# Test 5 — cross-tool chain D1 → F (mock flavour).
# ---------------------------------------------------------------------------


class TestCrossToolD1ToFMock:
    """The orchestrator's per-candidate enrichment path will chain:

        fetch_metabolite_info(hmdb_id).primary_name
          → literature_search(query=primary_name)

    Verify the plumbing works end-to-end against the mock HMDB fixture
    + a canned Europe PMC response.
    """

    def test_glucose_chain_yields_records(self, mock_hmdb_db):
        # D1 — real tool, mock backend via the conftest fixture.
        info = fetch_metabolite_info(
            MetaboliteInfoRequest(identifier="HMDB0000122", id_type="hmdb")
        )
        assert info.found is True
        assert info.primary_name  # "D-Glucose" or similar
        name = info.primary_name

        # F — real tool, canned Europe PMC response.
        sess = requests.Session()
        with rm.Mocker(session=sess) as m:
            m.get(_EPMC_URL, json=_epmc_payload([
                _epmc_record(
                    pmid="41000001",
                    title=f"{name} metabolism in liver cells",
                    abstract=f"Studies on {name} uptake.",
                ),
            ]))
            lit = literature_search(
                LiteratureSearchRequest(query=name, max_results=3),
                session=sess,
            )
        assert lit.records, "cross-tool chain must return at least one record"
        # Tool should echo exactly the query string it sent (possibly with
        # a year-filter suffix when year_from is set; not here).
        assert name.lower() in lit.query_used.lower()
        # Records' pmids must still be verifiable shape.
        assert all(r.pmid.isdigit() for r in lit.records)

    def test_caffeine_chain_propagates_empty_result(self, mock_hmdb_db):
        """If Europe PMC returns zero records, the chain still works —
        the downstream consumer gets `records=[]`, not a fabricated fallback."""
        info = fetch_metabolite_info(
            MetaboliteInfoRequest(identifier="HMDB0001847", id_type="hmdb")
        )
        assert info.found is True
        name = info.primary_name
        assert name

        sess = requests.Session()
        with rm.Mocker(session=sess) as m:
            m.get(_EPMC_URL, json=_epmc_payload([]))
            lit = literature_search(
                LiteratureSearchRequest(query=name, max_results=3),
                session=sess,
            )
        assert lit.records == []
        # Explain must say 0 / none / retrieved 0 — not invent a count.
        lowered = lit.explain.lower()
        assert "0" in lowered or "no " in lowered, (
            f"explain must reflect empty result, got {lit.explain!r}"
        )


# ---------------------------------------------------------------------------
# Test 6 — real-path: live Europe PMC, well-known metabolite query.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _LIVE_ENABLED, reason=_LIVE_SKIP_REASON)
class TestLiteratureLiveQueryReal:
    """Live Europe PMC. Opt-in via METAGENT_ALLOW_EUROPEPMC=1."""

    def test_well_known_metabolite_returns_verifiable_records(self):
        # L-carnitine has enormous literature coverage — a max_results=3
        # query reliably finds MED (PubMed) records.
        resp = literature_search(
            LiteratureSearchRequest(
                query="L-carnitine fatty acid oxidation", max_results=3,
            ),
        )
        assert resp.records, "live Europe PMC should return records for L-carnitine"
        for rec in resp.records:
            # PMID shape — verifiable.
            assert rec.pmid.isdigit(), f"live response has non-numeric PMID {rec.pmid!r}"
            # Title + journal present.
            assert rec.title
            assert rec.journal
            # Year plausible.
            assert 1970 <= rec.year <= 2100, f"year {rec.year} out of range"
            # Abstract must be a string (may be ""). Never None.
            assert isinstance(rec.abstract, str)
            # URL must resolve to MED or PubMed.
            assert "europepmc.org" in rec.url or "pubmed" in rec.url.lower(), rec.url


# ---------------------------------------------------------------------------
# Test 7 — real-path: PMID verifiability round-trip.
#
# This is the most important real-path test — it proves the contract the
# verifier will enforce: "every returned record is independently retrievable
# by PMID". Search → sample → refetch → title matches.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _LIVE_ENABLED, reason=_LIVE_SKIP_REASON)
class TestLiteraturePMIDVerifiabilityReal:
    def test_sampled_pmid_round_trips_verbatim(self):
        resp = literature_search(
            LiteratureSearchRequest(query="caffeine metabolism", max_results=3),
        )
        assert resp.records, "live query should return records"
        sample = resp.records[0]

        # Refetch by EXT_ID — Europe PMC's unique-ID lookup syntax.
        follow = literature_search(
            LiteratureSearchRequest(query=f"EXT_ID:{sample.pmid}", max_results=1),
        )
        assert follow.records, (
            f"PMID {sample.pmid} from first search could not be re-fetched — "
            "either Europe PMC dropped it in the seconds between calls (unlikely) "
            "or the tool's query_used normalisation is broken."
        )
        assert follow.records[0].pmid == sample.pmid
        assert follow.records[0].title == sample.title, (
            f"title drifted between calls: first={sample.title!r}, "
            f"refetch={follow.records[0].title!r}"
        )


# ---------------------------------------------------------------------------
# Test 8 — real-path cross-tool chain D1 → F against the live API.
#
# Gated on both METAGENT_ALLOW_EUROPEPMC (F) and the in-tmp mock HMDB
# (D1) — we do NOT also require METAGENT_HMDB_PATH because the
# mock_hmdb_db fixture seeds a deterministic mini DB for D1.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _LIVE_ENABLED, reason=_LIVE_SKIP_REASON)
class TestCrossToolD1ToFLive:
    def test_primary_name_drives_live_query(self, mock_hmdb_db):
        info = fetch_metabolite_info(
            MetaboliteInfoRequest(identifier="HMDB0000122", id_type="hmdb")
        )
        assert info.found and info.primary_name
        # Live call — should return SOMETHING for a canonical metabolite name.
        resp = literature_search(
            LiteratureSearchRequest(query=info.primary_name, max_results=2),
        )
        # Empty list is allowed by the contract ("empty list is a valid response"),
        # so we don't hard-fail; we instead assert schema validity + no invention.
        for rec in resp.records:
            assert rec.pmid.isdigit()
            assert isinstance(rec.abstract, str)
            assert rec.year >= 1900


# ---------------------------------------------------------------------------
# Test 9 — LLM tripwire survives across sources/fallbacks.
#
# If the tool ever added a "summarise if empty" LLM shortcut, the autouse
# empty mock we installed at the top of this file would raise IndexError
# the moment it tried to call chat(). This test specifically exercises
# the empty-result path — where such a shortcut would be most tempting.
# ---------------------------------------------------------------------------


class TestNoLLMOnEmptyResultMock:
    def test_empty_result_does_not_trigger_llm(self):
        sess = requests.Session()
        # Patch with a hard tripwire so even an unexpected chat_raw call
        # (if the tool ever switched away from chat()) surfaces clearly.
        def _tripwire(*a, **kw):  # pragma: no cover — only fires on regression
            raise AssertionError(
                "literature_search attempted an LLM call on empty result. "
                "This is a trust-anchor violation: the contract forbids "
                "abstract paraphrasing / record synthesis."
            )

        with mock.patch.object(llm_client, "chat", _tripwire), \
             mock.patch.object(llm_client, "chat_raw", _tripwire), \
             rm.Mocker(session=sess) as m:
            m.get(_EPMC_URL, json=_epmc_payload([]))
            # Try multiple empty-result triggering queries.
            for q in ("", "qqqzzzyyy-nonsense", "XXX'SELECT'XXX"):
                if not q:
                    # LiteratureSearchRequest enforces min_length=1, so skip
                    # the empty-string attempt at the schema layer.
                    continue
                resp = literature_search(
                    LiteratureSearchRequest(query=q, max_results=3),
                    session=sess,
                )
                assert resp.records == []


# ---------------------------------------------------------------------------
# Marker registration — lets `pytest --markers` list the opt-in reason.
# ---------------------------------------------------------------------------


def pytest_configure(config):  # pragma: no cover — pytest machinery
    """Register the opt-in marker name for visibility in --markers. We
    don't actually decorate tests with it (we use skipif instead) — this
    is purely documentation so the marker shows up in `pytest --markers`
    for anyone grep-ing for literature-related opt-ins."""
    config.addinivalue_line(
        "markers",
        "requires_europepmc_online: integration test that hits the live "
        "Europe PMC REST API. Opt-in via METAGENT_ALLOW_EUROPEPMC=1.",
    )

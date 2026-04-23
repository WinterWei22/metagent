"""Track F — `literature_search` main entry point.

Public function: `literature_search(req: LiteratureSearchRequest) -> LiteratureSearchResponse`.

Behaviour summary (full contract in docs/TOOL_CONTRACTS.md → Tool 8):
  - `max_results=0` short-circuits to an empty response without any HTTP call.
  - `req.sources` is tried in listed order. The first source that returns a
    non-empty record list wins; remaining sources are not consulted.
  - Year filter is pushed to the server (Europe PMC `PUB_YEAR:[...]` /
    PubMed `[PDAT]`); a defensive client-side filter catches any record
    that slips through.
  - Every record's `pmid` is verifiable: PubMed numeric only, URL points at
    Europe PMC's MED article page or PubMed proper.
  - Records that cannot be made schema-compliant are dropped with a warning
    log — never fabricated.
  - On HTTP 429 from any source, RateLimitError is raised; the orchestrator
    decides retry policy.
"""
from __future__ import annotations

import logging
from typing import Callable

import requests

from schemas.common import LiteratureRecord
from schemas.pathway import LiteratureSearchRequest, LiteratureSearchResponse
from tools.literature import europepmc_client, pubmed_client
from tools.literature.normalise import europepmc_to_record, pubmed_to_record

logger = logging.getLogger(__name__)


def _run_source(
    source: str,
    req: LiteratureSearchRequest,
    session: requests.Session,
) -> tuple[list[LiteratureRecord], str]:
    """Dispatch to the right client and normalise its records.

    Returns (records, query_used). `query_used` is the actual string sent to
    the API (with year filter appended if applicable).
    """
    if source == "europepmc":
        raw, q_used = europepmc_client.search(
            req.query,
            page_size=req.max_results,
            year_from=req.year_from,
            session=session,
        )
        normaliser: Callable = europepmc_to_record
    elif source == "pubmed":
        raw, q_used = pubmed_client.search(
            req.query,
            page_size=req.max_results,
            year_from=req.year_from,
            session=session,
        )
        normaliser = pubmed_to_record
    else:
        # Schema's Literal already prevents this; defensive only.
        raise ValueError(f"Unsupported literature source: {source!r}")

    records: list[LiteratureRecord] = []
    for raw_record in raw:
        rec = normaliser(raw_record)
        if rec is None:
            continue
        # Defensive client-side year filter: trust but verify.
        if req.year_from is not None and rec.year < req.year_from:
            logger.debug(
                "Dropping %s record pmid=%s year=%d (< year_from=%d)",
                source, rec.pmid, rec.year, req.year_from,
            )
            continue
        records.append(rec)
        if len(records) >= req.max_results:
            break
    return records, q_used


def literature_search(
    req: LiteratureSearchRequest,
    *,
    session: requests.Session | None = None,
) -> LiteratureSearchResponse:
    """Search PubMed/Europe PMC and return verifiable LiteratureRecord objects.

    The optional `session` parameter is exposed for testing (so tests can
    inject a `requests-mock` adapter); production callers should leave it None.
    """
    if req.max_results == 0:
        # Contract: no network when caller asks for zero results.
        return LiteratureSearchResponse(
            records=[],
            query_used=req.query,
            explain=(
                f"max_results=0; no API call made for query {req.query!r}."
            ),
        )

    sess = session or requests.Session()
    records: list[LiteratureRecord] = []
    query_used = req.query
    chosen_source = ""
    for source in req.sources:
        try:
            records, query_used = _run_source(source, req, sess)
        except Exception:
            # RateLimitError, LiteratureBackendError, anything else: surface
            # to the orchestrator. We do NOT silently swap to the next source
            # on errors — that would mask outages and produce confusing audit
            # trails. The orchestrator retries with reordered sources if it
            # wants to.
            raise
        if records:
            chosen_source = source
            break
        chosen_source = source

    explain = (
        f"Retrieved {len(records)} record(s) from {chosen_source} "
        f"for query {query_used!r}"
        + (f" (year_from={req.year_from})." if req.year_from is not None else ".")
    )
    return LiteratureSearchResponse(
        records=records,
        query_used=query_used,
        explain=explain,
    )

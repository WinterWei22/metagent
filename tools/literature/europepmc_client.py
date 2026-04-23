"""Europe PMC REST search wrapper.

Single-purpose: hit `/webservices/rest/search` with the user's query (plus an
optional year filter), return the raw `resultList.result[]` list of dicts.
Normalisation lives in `normalise.py`; this module is the network boundary.

No auth required. We pin `resultType=core` because the default returns
`abstractText=None` for every record — that would force the tool to invent
abstracts (forbidden) or return empty ones for every hit (useless). `core`
gives us the verbatim abstract that the verifier will spot-check.
"""
from __future__ import annotations

import logging
from typing import Any

import requests

from tools.literature.errors import LiteratureBackendError, RateLimitError

logger = logging.getLogger(__name__)

EPMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
DEFAULT_TIMEOUT = 15.0


def build_query(query: str, year_from: int | None) -> str:
    """Wrap the user's free-text query with a server-side year filter.

    Europe PMC accepts `PUB_YEAR:[YYYY TO YYYY]` as a Lucene-style range. We
    push the filter to the server so the page-size budget isn't blown on
    pre-filter records that we'd just throw away client-side.
    """
    q = (query or "").strip()
    if not q:
        return q
    if year_from is None:
        return q
    return f"({q}) AND PUB_YEAR:[{int(year_from)} TO 3000]"


def search(
    query: str,
    *,
    page_size: int,
    year_from: int | None = None,
    session: requests.Session | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[list[dict[str, Any]], str]:
    """Run one Europe PMC search.

    Returns (raw_results, query_used) where `raw_results` is the verbatim
    `resultList.result` list and `query_used` is the exact string sent to
    the API (so the caller can echo it in `LiteratureSearchResponse.query_used`).

    Raises:
        RateLimitError: on HTTP 429.
        LiteratureBackendError: on any other non-2xx, network failure, or
            malformed JSON.
    """
    sess = session or requests.Session()
    q = build_query(query, year_from)
    params = {
        "query": q,
        "format": "json",
        "pageSize": int(page_size),
        "resultType": "core",
    }
    try:
        resp = sess.get(EPMC_SEARCH_URL, params=params, timeout=timeout)
    except requests.RequestException as exc:
        raise LiteratureBackendError(
            f"Europe PMC request failed: {exc}"
        ) from exc

    if resp.status_code == 429:
        raise RateLimitError(
            f"Europe PMC rate-limited (HTTP 429) for query {q!r}"
        )
    if resp.status_code >= 400:
        raise LiteratureBackendError(
            f"Europe PMC returned HTTP {resp.status_code} for query {q!r}: "
            f"{resp.text[:200]}"
        )

    try:
        payload = resp.json()
    except ValueError as exc:
        raise LiteratureBackendError(
            f"Europe PMC returned non-JSON payload for query {q!r}: {exc}"
        ) from exc

    result_list = payload.get("resultList") or {}
    results = result_list.get("result") or []
    if not isinstance(results, list):
        raise LiteratureBackendError(
            f"Europe PMC resultList.result is not a list: {type(results).__name__}"
        )
    return results, q

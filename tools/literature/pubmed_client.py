"""NCBI E-utilities (PubMed) fallback wrapper.

Two endpoints in sequence:
  1. esearch.fcgi   — query → list of PMIDs
  2. efetch.fcgi    — PMIDs → MEDLINE XML (parsed for title/abstract/etc.)

Optional API key from env `NCBI_API_KEY` (raises NCBI's per-IP limit from 3 to
10 req/s — only relevant in production, ignored if unset).
"""
from __future__ import annotations

import logging
import os
from typing import Any
from xml.etree import ElementTree as ET

import requests

from tools.literature.errors import LiteratureBackendError, RateLimitError

logger = logging.getLogger(__name__)

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
DEFAULT_TIMEOUT = 15.0


def _api_key_params() -> dict[str, str]:
    key = os.environ.get("NCBI_API_KEY", "").strip()
    return {"api_key": key} if key else {}


def _esearch(
    query: str,
    *,
    page_size: int,
    year_from: int | None,
    session: requests.Session,
    timeout: float,
) -> tuple[list[str], str]:
    """Run esearch and return (pmids, query_used).

    Year filter is implemented via PubMed's `[PDAT]` (publication date) field.
    """
    q = (query or "").strip()
    if year_from is not None:
        q = f"({q}) AND {int(year_from)}:3000[PDAT]"
    params: dict[str, str | int] = {
        "db": "pubmed",
        "term": q,
        "retmode": "json",
        "retmax": int(page_size),
    }
    params.update(_api_key_params())
    try:
        resp = session.get(ESEARCH_URL, params=params, timeout=timeout)
    except requests.RequestException as exc:
        raise LiteratureBackendError(f"PubMed esearch failed: {exc}") from exc

    if resp.status_code == 429:
        raise RateLimitError(f"PubMed rate-limited (esearch) for query {q!r}")
    if resp.status_code >= 400:
        raise LiteratureBackendError(
            f"PubMed esearch HTTP {resp.status_code} for {q!r}: {resp.text[:200]}"
        )
    try:
        payload = resp.json()
    except ValueError as exc:
        raise LiteratureBackendError(
            f"PubMed esearch non-JSON for {q!r}: {exc}"
        ) from exc

    idlist = (payload.get("esearchresult") or {}).get("idlist") or []
    if not isinstance(idlist, list):
        raise LiteratureBackendError(
            f"PubMed esearch idlist not a list: {type(idlist).__name__}"
        )
    return [str(p) for p in idlist if str(p).isdigit()], q


def _efetch(
    pmids: list[str],
    *,
    session: requests.Session,
    timeout: float,
) -> str:
    """Fetch MEDLINE XML for a list of PMIDs. Returns raw XML text."""
    if not pmids:
        return ""
    params: dict[str, str] = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "rettype": "abstract",
        "retmode": "xml",
    }
    params.update(_api_key_params())
    try:
        resp = session.get(EFETCH_URL, params=params, timeout=timeout)
    except requests.RequestException as exc:
        raise LiteratureBackendError(f"PubMed efetch failed: {exc}") from exc

    if resp.status_code == 429:
        raise RateLimitError("PubMed rate-limited (efetch)")
    if resp.status_code >= 400:
        raise LiteratureBackendError(
            f"PubMed efetch HTTP {resp.status_code}: {resp.text[:200]}"
        )
    return resp.text


def _author_to_string(author_el: ET.Element) -> str:
    """Combine LastName + Initials in the conventional 'Smith J' form."""
    last = author_el.findtext("LastName") or ""
    initials = author_el.findtext("Initials") or ""
    collective = author_el.findtext("CollectiveName")
    if collective:
        return collective.strip()
    name = (last + " " + initials).strip()
    return name


def _abstract_to_string(article_el: ET.Element) -> str:
    """Concatenate <AbstractText> sections in document order. Verbatim — we do
    NOT add headings even when @Label is present, because the verifier compares
    the returned abstract to a re-fetch and added text would mismatch."""
    abstract_el = article_el.find("Abstract")
    if abstract_el is None:
        return ""
    parts: list[str] = []
    for at in abstract_el.findall("AbstractText"):
        # ET .text returns None for empty tags
        text = "".join(at.itertext()).strip()
        if text:
            parts.append(text)
    return " ".join(parts)


def _parse_pubmed_xml(xml_text: str) -> list[dict[str, Any]]:
    """Parse efetch XML into a list of dicts with the fields normalise.py expects."""
    if not xml_text.strip():
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise LiteratureBackendError(f"PubMed efetch returned malformed XML: {exc}") from exc

    out: list[dict[str, Any]] = []
    for art in root.findall(".//PubmedArticle"):
        pmid = art.findtext(".//MedlineCitation/PMID")
        article = art.find(".//MedlineCitation/Article")
        if article is None or not pmid:
            continue
        title = (article.findtext("ArticleTitle") or "").strip()
        # Pub year priority: ArticleDate > PubDate.Year > MedlineDate (free text)
        year_text = (
            article.findtext(".//ArticleDate/Year")
            or article.findtext(".//Journal/JournalIssue/PubDate/Year")
            or article.findtext(".//Journal/JournalIssue/PubDate/MedlineDate")
        )
        journal = article.findtext(".//Journal/Title") or ""
        authors_el = article.find("AuthorList")
        authors = (
            [_author_to_string(a) for a in authors_el.findall("Author")] if authors_el is not None else []
        )
        authors = [a for a in authors if a]
        # DOI lives in ArticleIdList of the surrounding PubmedData
        doi = None
        for aid in art.findall(".//PubmedData/ArticleIdList/ArticleId"):
            if (aid.get("IdType") or "").lower() == "doi":
                doi = (aid.text or "").strip() or None
                break
        out.append({
            "pmid": pmid.strip(),
            "title": title,
            "abstract": _abstract_to_string(article),
            "authors": authors,
            "year": year_text,
            "journal": journal,
            "doi": doi,
        })
    return out


def search(
    query: str,
    *,
    page_size: int,
    year_from: int | None = None,
    session: requests.Session | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[list[dict[str, Any]], str]:
    """Run a full PubMed search: esearch → efetch → parsed dicts.

    Returns (records, query_used). Records are pre-normalised dicts ready for
    `normalise.pubmed_to_record`.
    """
    sess = session or requests.Session()
    pmids, q = _esearch(
        query, page_size=page_size, year_from=year_from, session=sess, timeout=timeout,
    )
    if not pmids:
        return [], q
    xml_text = _efetch(pmids, session=sess, timeout=timeout)
    return _parse_pubmed_xml(xml_text), q

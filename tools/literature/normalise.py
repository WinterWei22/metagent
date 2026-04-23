"""Convert raw API records into validated `LiteratureRecord` objects.

Records that cannot be made schema-compliant (missing PMID / non-numeric PMID
/ unparsable year / missing title) are dropped silently with a warning log.
Per the contract, fabrication is forbidden: when in doubt, drop, never invent.
"""
from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from schemas.common import LiteratureRecord

logger = logging.getLogger(__name__)


# Europe PMC URL template for follow-up verification by the verifier agent.
EPMC_ARTICLE_URL = "https://europepmc.org/article/MED/{pmid}"
PUBMED_ARTICLE_URL = "https://pubmed.ncbi.nlm.nih.gov/{pmid}/"


def _parse_year(raw: Any) -> int | None:
    """Coerce a year-like value (int or str) into an int. Returns None on failure."""
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw
    s = str(raw).strip()
    if not s:
        return None
    # Some APIs hand back "2024 ", "2024-01-01", "2024 Jan" — take the leading 4 digits.
    digits = ""
    for ch in s:
        if ch.isdigit():
            digits += ch
            if len(digits) == 4:
                break
        elif digits:
            break
    if len(digits) != 4:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def _split_authors(author_string: str | None) -> list[str]:
    """Europe PMC concatenates authors as 'Smith J, Doe A.' — split on ', ' and trim trailing '.'."""
    if not author_string:
        return []
    s = author_string.strip().rstrip(".")
    if not s:
        return []
    return [a.strip() for a in s.split(",") if a.strip()]


def _extract_journal(raw: dict) -> str:
    """Europe PMC keeps the journal title at journalInfo.journal.title; PubMed
    XML uses different keys handled by the pubmed_client. Fall back to the
    flat journalTitle field, then to "" — schema accepts an empty string."""
    info = raw.get("journalInfo")
    if isinstance(info, dict):
        j = info.get("journal")
        if isinstance(j, dict):
            title = j.get("title") or j.get("medlineAbbreviation") or j.get("isoabbreviation")
            if title:
                return str(title).strip()
    flat = raw.get("journalTitle") or raw.get("journal")
    if flat:
        return str(flat).strip()
    return ""


def _normalise_doi(raw: Any) -> str | None:
    """Treat blank / placeholder DOI as None."""
    if not raw:
        return None
    s = str(raw).strip()
    return s if s else None


def europepmc_to_record(raw: dict) -> LiteratureRecord | None:
    """Map one Europe PMC `resultList.result[]` entry to a LiteratureRecord.

    Returns None (with a warning log) when the record cannot be made
    schema-compliant. We never fabricate fields: missing PMID → drop;
    non-numeric PMID → drop; missing title → drop; unparsable year → drop.
    Missing abstract → "" (explicit empty string, never None).
    """
    pmid_raw = raw.get("pmid")
    if not pmid_raw:
        # Preprints (source=PPR) and other non-MED sources have no PMID.
        # Silently dropping these is required by contract — the verifier
        # only trusts records it can re-fetch by PMID.
        logger.debug("Dropping Europe PMC record without pmid: id=%s source=%s",
                     raw.get("id"), raw.get("source"))
        return None
    pmid = str(pmid_raw).strip()
    if not pmid.isdigit():
        logger.warning("Dropping Europe PMC record with non-numeric pmid: %r", pmid_raw)
        return None

    title = (raw.get("title") or "").strip()
    if not title:
        logger.warning("Dropping Europe PMC record %s with empty title", pmid)
        return None

    year = _parse_year(raw.get("pubYear") or raw.get("firstPublicationDate"))
    if year is None:
        logger.warning("Dropping Europe PMC record %s with unparsable year: %r",
                       pmid, raw.get("pubYear"))
        return None

    # Verbatim abstract — never paraphrase, never invent. "" when missing.
    abstract_raw = raw.get("abstractText")
    abstract = abstract_raw if isinstance(abstract_raw, str) else ""

    try:
        return LiteratureRecord(
            pmid=pmid,
            title=title,
            abstract=abstract,
            authors=_split_authors(raw.get("authorString")),
            year=year,
            journal=_extract_journal(raw),
            doi=_normalise_doi(raw.get("doi")),
            url=EPMC_ARTICLE_URL.format(pmid=pmid),
        )
    except ValidationError as e:
        logger.warning("Dropping Europe PMC record %s: schema validation failed: %s",
                       pmid, e)
        return None


def pubmed_to_record(raw: dict) -> LiteratureRecord | None:
    """Map one normalised PubMed dict (already extracted from efetch XML by
    pubmed_client) to a LiteratureRecord. Same drop-don't-fabricate policy.

    Expected keys (produced by pubmed_client._parse_pubmed_xml):
      pmid, title, abstract, authors (list[str]), year (int|str|None),
      journal, doi.
    """
    pmid_raw = raw.get("pmid")
    if not pmid_raw:
        logger.debug("Dropping PubMed record without pmid")
        return None
    pmid = str(pmid_raw).strip()
    if not pmid.isdigit():
        logger.warning("Dropping PubMed record with non-numeric pmid: %r", pmid_raw)
        return None

    title = (raw.get("title") or "").strip()
    if not title:
        logger.warning("Dropping PubMed record %s with empty title", pmid)
        return None

    year = _parse_year(raw.get("year"))
    if year is None:
        logger.warning("Dropping PubMed record %s with unparsable year: %r",
                       pmid, raw.get("year"))
        return None

    abstract_raw = raw.get("abstract")
    abstract = abstract_raw if isinstance(abstract_raw, str) else ""

    authors = raw.get("authors") or []
    if not isinstance(authors, list):
        authors = []

    try:
        return LiteratureRecord(
            pmid=pmid,
            title=title,
            abstract=abstract,
            authors=[str(a) for a in authors if a],
            year=year,
            journal=str(raw.get("journal") or "").strip(),
            doi=_normalise_doi(raw.get("doi")),
            url=PUBMED_ARTICLE_URL.format(pmid=pmid),
        )
    except ValidationError as e:
        logger.warning("Dropping PubMed record %s: schema validation failed: %s",
                       pmid, e)
        return None

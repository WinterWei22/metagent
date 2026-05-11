"""Tool 5 — Free-text literature search over PubMed / Europe PMC.

Wraps :func:`tools.literature.tool.literature_search`.

Phase A1 wires this tool but the prompt does NOT force the LLM to call
it (per session decision Q2). Tool-call frequency in pilot data
informs whether retrieval-augmented narratives are worth the
engineering cost in phase A3.
"""
from __future__ import annotations

import logging
from typing import Any

from schemas.pathway import LiteratureSearchRequest
from tools.agent_tools.schemas import LiteratureInput, truncate_to_budget
from tools.literature import literature_search
from tools.literature.errors import LiteratureBackendError, RateLimitError

logger = logging.getLogger(__name__)

# Abstracts can be 1-2 KB on their own; cap each one before truncation logic
# kicks in. Phase A3 D1a bumped 320 → 500: the original 320-char cap was
# tuned for A1 when literature was wired-but-unused; A3 actively invites the
# agent to use literature in feedback revisions, and 320 chars was too
# terse to convey enough biological context for a useful citation. With 5
# results × 500 chars ≈ 2.5 KB, still fits the 2 KB envelope after
# truncation drops down to top-3 results when needed.
_ABSTRACT_CAP = 500


def search_literature(payload: dict[str, Any]) -> dict[str, Any]:
    """Literature search; return slim record list.

    Output shape (success):
        {
            "n_records": int,
            "query_used": str,
            "records": [
                {
                    "pmid": str,
                    "title": str,
                    "abstract_excerpt": str,   # first ~320 chars
                    "year": int,
                    "journal": str,
                    "url": str,
                },
                ...
            ],
        }
    """
    args = LiteratureInput.model_validate(payload)

    try:
        req = LiteratureSearchRequest(
            query=args.query,
            max_results=args.max_results,
            year_from=args.year_from,
        )
        resp = literature_search(req)
    except RateLimitError as exc:
        return {
            "error": f"rate_limited: {exc}",
            "fallback_suggested": (
                "the literature backend rate-limited us; try again later or "
                "skip literature evidence for this claim"
            ),
        }
    except LiteratureBackendError as exc:
        return {
            "error": f"backend_error: {exc}",
            "fallback_suggested": "drop literature evidence for this claim",
        }
    except Exception as exc:  # pragma: no cover
        logger.exception("search_literature: unexpected failure")
        return {
            "error": f"unexpected_error: {type(exc).__name__}: {exc}",
            "fallback_suggested": "retry once with a tighter query",
        }

    records: list[dict[str, Any]] = []
    for rec in resp.records:
        excerpt = (rec.abstract or "").strip()
        if len(excerpt) > _ABSTRACT_CAP:
            excerpt = excerpt[: _ABSTRACT_CAP - 3] + "..."
        records.append(
            {
                "pmid": rec.pmid,
                "title": rec.title,
                "abstract_excerpt": excerpt,
                "year": rec.year,
                "journal": rec.journal,
                "url": rec.url,
            }
        )

    out: dict[str, Any] = {
        "n_records": len(records),
        "query_used": resp.query_used,
        "records": records,
    }
    return truncate_to_budget(
        out,
        truncatable_key="records",
        more_hint=(
            "more results available; tighten the query or lower max_results"
        ),
    )

"""Track F — `literature_search`.

Public entry point: `literature_search(req: LiteratureSearchRequest) -> LiteratureSearchResponse`.
Thin, hallucination-resistant wrapper around Europe PMC REST (primary) and
NCBI E-utilities (fallback). No LLM, no caching, no paraphrasing — every
returned record is a verbatim API hit with a verifiable PMID.
"""
from tools.literature.tool import literature_search

__all__ = ["literature_search"]

"""Track D (Tool 5): fetch_metabolite_info.

Structured metabolite metadata lookup. Trust anchor for the verifier — every
field returned traces to a real database row; unknown fields stay None or [].
No LLM calls, no web calls except a strict PubChem PUG-REST fallback.

Public entry point: `fetch_metabolite_info(req: MetaboliteInfoRequest) -> MetaboliteInfoResponse`.
"""
from tools.metabolite_info.tool import fetch_metabolite_info

__all__ = ["fetch_metabolite_info"]

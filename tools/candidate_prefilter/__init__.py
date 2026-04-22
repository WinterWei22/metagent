"""Track A2: candidate_prefilter.

Fast pre-screening of the candidate pool by precursor mass (and optional
molecular formula), using local indices over GNPS (in-memory) and a
PubChem-Lite SQLite DB (v0: HMDB-only contents). Runs before library_search
and molecule_generate to narrow their search spaces.

Public entry point: `prefilter(req: PrefilterRequest) -> PrefilterResponse`.
"""
from tools.candidate_prefilter.tool import prefilter

__all__ = ["prefilter"]

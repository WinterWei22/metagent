"""Tiny live demo for literature_search. Hits Europe PMC — needs network.

Run from repo root: `python tools/literature/example.py`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from schemas.pathway import LiteratureSearchRequest  # noqa: E402
from tools.literature import literature_search  # noqa: E402

req = LiteratureSearchRequest(query="L-carnitine fatty acid oxidation", max_results=3)
resp = literature_search(req)
print(resp.explain)
for r in resp.records:
    print(f"  PMID {r.pmid} ({r.year}) {r.title[:80]}")

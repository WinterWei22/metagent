"""Public LIPID MAPS lookup client."""

from __future__ import annotations

from pathlib import Path

from .lmsd_loader import load_lmsd
from .pathway_loader import load_pathways


class LipidMapsClient:
    def __init__(self, lmsd_path: Path | str, pathway_db_path: Path | str):
        self._lmsd = load_lmsd(lmsd_path)
        self._pathways = load_pathways(pathway_db_path)

    def lookup_by_inchikey(self, inchikey: str) -> dict | None:
        """Return LMSD metadata for a full or first-block InChIKey."""
        key = (inchikey or "").strip()
        if not key:
            return None
        exact = self._lmsd["by_inchikey"].get(key)
        if exact:
            return dict(exact)
        first = key[:14]
        candidates = self._lmsd["by_first_block"].get(first) or []
        if not candidates:
            return None
        return dict(candidates[0])

    def get_lipid_pathways(self, lm_id: str) -> list[dict]:
        """Return lipid pathway records for an LMSD LM_ID."""
        return [dict(p) for p in self._pathways.get(lm_id, [])]

    def lookup_compound_to_pathways(self, inchikey: str) -> list[dict]:
        """Resolve InChIKey -> LM_ID -> WikiPathways Lipids Portal pathways."""
        rec = self.lookup_by_inchikey(inchikey)
        if not rec:
            return []
        return self.get_lipid_pathways(rec["lm_id"])

    @property
    def n_lmsd_records(self) -> int:
        return len(self._lmsd["by_lm_id"])

    @property
    def n_lipid_pathway_compounds(self) -> int:
        return len(self._pathways)

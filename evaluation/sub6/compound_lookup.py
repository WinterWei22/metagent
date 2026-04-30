"""Compound name / KEGG / InChIKey lookup table for Sub-6 evaluation.

Sub-6 ground-truth compound IDs are KEGG (e.g. ``C00070``); LLM narratives
mention compound *names*; the eval guide §3 pitfall 2 mandates lifting
everything to **InChIKey first block** for comparison. This module owns
that resolution, sourced from ``curated_hmdb_mammalian.jsonl``.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CURATED_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "data"
    / "benchmark"
    / "sub6"
    / "curated_hmdb_mammalian.jsonl"
)

_PUNCT_RE = re.compile(r"[^a-z0-9]+")


def _normalise_name(name: str) -> str:
    """Lower-case + collapse non-alphanumerics. ``L-Tyrosine`` -> ``ltyrosine``."""
    return _PUNCT_RE.sub("", name.lower())


@dataclass(frozen=True)
class CompoundEntry:
    name: str
    inchikey_first_block: str
    kegg_id: str | None


class CompoundLookup:
    """Forward + reverse lookup keyed off the curated mammalian pool.

    Built once at runner startup. ``resolve()`` accepts a name or KEGG ID
    and returns the InChIKey first block, or None when nothing matches.
    Lookup keys are case-insensitive and punctuation-insensitive on names.
    """

    def __init__(self, entries: list[CompoundEntry]) -> None:
        self._entries: list[CompoundEntry] = list(entries)
        self._by_kegg: dict[str, str] = {}
        self._by_name: dict[str, str] = {}
        self._inchikey_to_kegg: dict[str, str] = {}
        self._inchikey_to_name: dict[str, str] = {}
        for e in entries:
            if e.kegg_id:
                self._by_kegg[e.kegg_id.upper()] = e.inchikey_first_block
                self._inchikey_to_kegg.setdefault(
                    e.inchikey_first_block, e.kegg_id.upper()
                )
            self._by_name[_normalise_name(e.name)] = e.inchikey_first_block
            self._inchikey_to_name.setdefault(e.inchikey_first_block, e.name)

    @classmethod
    def from_curated(cls, path: Path | str | None = None) -> "CompoundLookup":
        """Load ``curated_hmdb_mammalian.jsonl`` (or any equivalent JSONL)."""
        p = Path(path) if path else DEFAULT_CURATED_PATH
        entries: list[CompoundEntry] = []
        with p.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                first = rec.get("inchikey_first_block")
                name = rec.get("name")
                if not first or not name:
                    continue
                entries.append(
                    CompoundEntry(
                        name=name,
                        inchikey_first_block=first,
                        kegg_id=rec.get("kegg_id"),
                    )
                )
        return cls(entries)

    # ---- forward: name / kegg -> inchikey first block --------------------

    def resolve(self, query: str) -> str | None:
        """Return the InChIKey first block matching the query, or None.

        Tries KEGG (uppercase exact) first, then normalised-name match.
        """
        if not query:
            return None
        q = query.strip()
        if q.upper() in self._by_kegg:
            return self._by_kegg[q.upper()]
        norm = _normalise_name(q)
        if norm and norm in self._by_name:
            return self._by_name[norm]
        return None

    def resolve_kegg(self, kegg_id: str) -> str | None:
        return self._by_kegg.get(kegg_id.upper().strip())

    def resolve_name(self, name: str) -> str | None:
        norm = _normalise_name(name)
        return self._by_name.get(norm) if norm else None

    # ---- reverse: inchikey first block -> kegg / name --------------------

    def kegg_for(self, inchikey_first: str) -> str | None:
        return self._inchikey_to_kegg.get(inchikey_first)

    def name_for(self, inchikey_first: str) -> str | None:
        return self._inchikey_to_name.get(inchikey_first)

    # ---- bulk helpers ----------------------------------------------------

    def kegg_to_inchikey_set(self, kegg_ids: list[str]) -> set[str]:
        """Map a list of KEGG IDs to InChIKey first blocks (drop unresolved)."""
        out: set[str] = set()
        for k in kegg_ids:
            ik = self.resolve_kegg(k)
            if ik:
                out.add(ik)
        return out

    @property
    def all_names(self) -> list[str]:
        """All canonical compound names from the curated pool."""
        return [e.name for e in self._entries]

    def __len__(self) -> int:
        return len(self._entries)

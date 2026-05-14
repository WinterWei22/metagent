"""Load LIPID MAPS LMSD tabular exports."""

from __future__ import annotations

import csv
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass(frozen=True)
class LmsdRecord:
    lm_id: str
    name: str
    systematic_name: str
    category: str
    main_class: str
    sub_class: str
    class_level4: str
    exact_mass: str
    formula: str
    inchi_key: str
    smiles: str
    kegg_id: str
    hmdb_id: str
    chebi_id: str
    pubchem_cid: str

    @property
    def inchikey_first_block(self) -> str:
        return self.inchi_key[:14]

    def to_dict(self) -> dict:
        return asdict(self)


def _norm_header(name: str) -> str:
    return (name or "").strip().lower().replace(" ", "_")


def _get(row: dict[str, str], *names: str) -> str:
    for name in names:
        value = row.get(name)
        if value is not None:
            return value.strip()
    return ""


def _iter_lmsd_rows(path: Path):
    with path.open(encoding="utf-8", errors="replace", newline="") as f:
        first = f.readline()
        # REST tabular exports start with a date line before the real header.
        if "\t" in first and "lm_id" in first.lower():
            f.seek(0)
        reader = csv.DictReader(f, delimiter="\t")
        if reader.fieldnames is None:
            return
        reader.fieldnames = [_norm_header(h) for h in reader.fieldnames]
        for row in reader:
            yield {_norm_header(k): (v or "") for k, v in row.items()}


def load_lmsd(path: Path | str) -> dict[str, dict]:
    """Load LMSD into full and first-block InChIKey indexes.

    Returns a dict with keys:
      * ``by_inchikey``: full InChIKey -> record dict
      * ``by_first_block``: first 14 chars -> list[record dict]
      * ``by_lm_id``: LM_ID -> record dict
    """
    p = Path(path)
    by_inchikey: dict[str, dict] = {}
    by_first: dict[str, list[dict]] = {}
    by_lm_id: dict[str, dict] = {}
    for row in _iter_lmsd_rows(p):
        lm_id = _get(row, "lm_id")
        ikey = _get(row, "inchi_key", "inchikey")
        if not lm_id or not ikey:
            continue
        rec = LmsdRecord(
            lm_id=lm_id,
            name=_get(row, "name"),
            systematic_name=_get(row, "sys_name", "systematic_name"),
            category=_get(row, "core", "category"),
            main_class=_get(row, "main_class"),
            sub_class=_get(row, "sub_class"),
            class_level4=_get(row, "class_level4"),
            exact_mass=_get(row, "exactmass", "exact_mass"),
            formula=_get(row, "formula"),
            inchi_key=ikey,
            smiles=_get(row, "smiles", "smile"),
            kegg_id=_get(row, "kegg_id"),
            hmdb_id=_get(row, "hmdb_id"),
            chebi_id=_get(row, "chebi_id"),
            pubchem_cid=_get(row, "pubchem_cid"),
        ).to_dict()
        by_inchikey[ikey] = rec
        by_first.setdefault(ikey[:14], []).append(rec)
        by_lm_id[lm_id] = rec
    for records in by_first.values():
        records.sort(key=lambda r: (r.get("name") or "", r.get("lm_id") or ""))
    return {
        "by_inchikey": by_inchikey,
        "by_first_block": by_first,
        "by_lm_id": by_lm_id,
    }

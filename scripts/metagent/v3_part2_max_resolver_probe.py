"""V3 Part 2 — maximal OFFLINE resolver probe.

Goal: find the true residual toward 100% structure coverage. For every benchmark
metabolite, chase EVERY available offline structural xref (ChEBI all-namespace +
MetaNetX all bridges + Human-GEM annotation columns) and try to land a SMILES.

Then split the residual into three honest buckets:
  A) resolved-now (maximal offline lands a SMILES)
  B) has-structural-xref but no local structure  -> needs network/PubChem dump
  C) no structural xref at all                   -> true GEM pseudo-metabolite
                                                    (generic pool / balance node)

Pure audit, no LLM.
"""
from __future__ import annotations

import csv
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any

from concord.lookup.chebi import ChebiLookup

ROOT = Path(__file__).resolve().parents[2]
BENCHMARK = ROOT / "data/benchmark/metagent_bench_v2/metagent_bench_easy_v3.jsonl"
HUMAN_GEM = ROOT / "data/reference/human_gem_metabolites.tsv"
METANETX = ROOT / "data/concord/metanetx.sqlite"

XREF_COLS = {
    "metKEGGID": "KEGG", "metHMDBID": "HMDB", "metChEBIID": "CHEBI",
    "metPubChemID": "PUBCHEM", "metLipidMapsID": "LIPIDMAPS",
    "metMetaNetXID": "MNX", "metBiGGID": "BIGG",
}


def stratum_of(tid: str) -> str:
    if "human1" in tid:
        return "human1"
    if "recon2" in tid:
        return "recon22"
    if tid.startswith("sub6"):
        return "sub6_enrich"
    return "hmdb_ramp_membership"


def load_gem() -> dict[str, dict[str, str]]:
    table: dict[str, dict[str, str]] = {}
    bigg_index: dict[str, str] = {}
    with HUMAN_GEM.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            mam = (row.get("mets") or "").strip()
            base = mam[:-1] if mam[-1:].islower() else mam
            entry = table.setdefault(base, {})
            for col, ns in XREF_COLS.items():
                if entry.get(ns):
                    continue
                cell = (row.get(col) or "").split(";")[0].strip()
                if cell and cell.lower() not in ("na", "nan", ""):
                    entry[ns] = cell
            bigg = entry.get("BIGG")
            if bigg and bigg not in bigg_index:
                bigg_index[bigg] = base
    table["__bigg_index__"] = bigg_index  # type: ignore[assignment]
    return table


class MaxResolver:
    def __init__(self) -> None:
        self.chebi = ChebiLookup()
        self.mnx = sqlite3.connect(f"file:{METANETX}?mode=ro", uri=True)
        self.gem = load_gem()
        self.bigg_index: dict[str, str] = self.gem.pop("__bigg_index__")  # type: ignore[assignment]

    # --- land a SMILES from a single (ns, id) candidate -----------------
    def _smiles_from_chebi_xref(self, ns: str, ext: str) -> str | None:
        rec = self.chebi.lookup_by_xref(ns, ext)
        return rec.smiles if rec and rec.smiles else None

    def _smiles_from_chebi_id(self, ext: str) -> str | None:
        try:
            rec = self.chebi.get_compound(ext)
        except ValueError:
            return None
        return rec.smiles if rec and rec.smiles else None

    def _smiles_via_mnx_id(self, mnxid: str) -> str | None:
        ch = self.mnx.execute(
            "SELECT external_id FROM mnx_xref WHERE mnx_id=? AND external_ns='CHEBI' LIMIT 1",
            (mnxid,),
        ).fetchone()
        if ch:
            s = self._smiles_from_chebi_id(ch[0])
            if s:
                return s
        return None

    def _smiles_via_mnx_xref(self, ns: str, ext: str) -> str | None:
        rows = self.mnx.execute(
            "SELECT mnx_id FROM mnx_xref WHERE external_ns=? AND external_id=? LIMIT 5",
            (ns, ext),
        ).fetchall()
        for (mnxid,) in rows:
            s = self._smiles_via_mnx_id(mnxid)
            if s:
                return s
        return None

    def candidates(self, met: dict[str, Any]) -> dict[str, str]:
        """Collect ALL structural xrefs reachable for this metabolite."""
        mid = str(met.get("id") or "")
        idt = str(met.get("id_type") or "")
        cand: dict[str, str] = {}
        if idt == "KEGG":
            cand["KEGG"] = mid
        elif idt == "HMDB":
            cand["HMDB"] = mid
        elif idt == "ChEBI":
            cand["CHEBI"] = mid
        elif idt == "PubChem":
            cand["PUBCHEM"] = mid
        elif idt == "Human1":
            cand.update(self.gem.get(mid, {}))
        elif idt == "Recon2.2":
            # bigg slug: try metanetx BiGG bridge + human-gem bigg index
            cand["BIGG"] = mid
            gem_base = self.bigg_index.get(mid)
            if gem_base:
                cand.update({k: v for k, v in self.gem.get(gem_base, {}).items()
                             if k not in cand})
        return cand

    def resolve(self, met: dict[str, Any]) -> tuple[str | None, bool]:
        """Return (smiles_or_None, had_any_structural_xref)."""
        cand = self.candidates(met)
        had_xref = bool(cand)
        # try direct chebi paths
        for ns, ext in cand.items():
            if ns == "CHEBI":
                s = self._smiles_from_chebi_id(ext)
            elif ns in ("KEGG", "HMDB", "PUBCHEM", "LIPIDMAPS"):
                s = self._smiles_from_chebi_xref(ns, ext)
            else:
                s = None
            if s:
                return s, had_xref
        # try metanetx paths
        if "MNX" in cand:
            s = self._smiles_via_mnx_id(cand["MNX"])
            if s:
                return s, had_xref
        for ns in ("HMDB", "BIGG", "LIPIDMAPS", "KEGG", "CHEBI", "PUBCHEM"):
            if ns in cand:
                s = self._smiles_via_mnx_xref(ns, cand[ns])
                if s:
                    return s, had_xref
        return None, had_xref


def main() -> int:
    r = MaxResolver()
    with BENCHMARK.open(encoding="utf-8") as handle:
        tasks = [json.loads(line) for line in handle if line.strip()]

    seen: set[tuple[str, str, str]] = set()
    buckets: dict[str, dict[str, int]] = defaultdict(
        lambda: {"n": 0, "A_resolved": 0, "B_xref_no_struct": 0, "C_no_xref": 0}
    )
    for task in tasks:
        strat = stratum_of(task["task_id"])
        for met in task["input"]["differential_metabolites"]:
            key = (strat, str(met.get("id_type")), str(met.get("id")))
            if key in seen:
                continue
            seen.add(key)
            smiles, had_xref = r.resolve(met)
            b = buckets[strat]
            b["n"] += 1
            if smiles:
                b["A_resolved"] += 1
            elif had_xref:
                b["B_xref_no_struct"] += 1
            else:
                b["C_no_xref"] += 1

    def pct(a: int, n: int) -> str:
        return f"{100.0*a/n:.1f}%" if n else "n/a"

    print(f"{'stratum':<22} {'n':>5} {'A_resolved':>12} {'B_needs_net':>12} {'C_pseudo':>10}")
    tot = {"n": 0, "A_resolved": 0, "B_xref_no_struct": 0, "C_no_xref": 0}
    for strat in ("sub6_enrich", "hmdb_ramp_membership", "human1", "recon22"):
        b = buckets[strat]
        for k in tot:
            tot[k] += b[k]
        print(f"{strat:<22} {b['n']:>5} "
              f"{b['A_resolved']:>5} {pct(b['A_resolved'],b['n']):>6} "
              f"{b['B_xref_no_struct']:>5} {pct(b['B_xref_no_struct'],b['n']):>6} "
              f"{b['C_no_xref']:>4} {pct(b['C_no_xref'],b['n']):>5}")
    print(f"{'TOTAL':<22} {tot['n']:>5} "
          f"{tot['A_resolved']:>5} {pct(tot['A_resolved'],tot['n']):>6} "
          f"{tot['B_xref_no_struct']:>5} {pct(tot['B_xref_no_struct'],tot['n']):>6} "
          f"{tot['C_no_xref']:>4} {pct(tot['C_no_xref'],tot['n']):>5}")
    print()
    print("A = maximal offline lands a SMILES (current local DBs)")
    print("B = has structural xref but no local structure -> network/PubChem dump closes it")
    print("C = no structural xref at all -> true GEM pseudo-metabolite (no single structure)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

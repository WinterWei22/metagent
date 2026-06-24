"""Generate v4 benchmark: replace id/id_type with name + SMILES + InChIKey.

Reads metagent_bench_easy_v3.jsonl and produces metagent_bench_easy_v4.jsonl.

Input  (v3): differential_metabolites = [{id, id_type, name?}, ...]
Output (v4): differential_metabolites = [{name, smiles?, inchikey?}, ...]

SMILES and InChIKey are resolved via StructureResolver (2A).  Metabolites
where no SMILES is available keep only the name field.  Coverage stats are
printed at the end.

Usage:
    PYTHONPATH=. python scripts/metagent/v4_gen_benchmark.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from concord.lookup.structure_resolver import StructureResolver, _collect_cands
from concord.lookup.chebi import ChebiLookup

_V3 = ROOT / "data/benchmark/metagent_bench_v2/metagent_bench_easy_v3.jsonl"
_V4 = ROOT / "data/benchmark/metagent_bench_v2/metagent_bench_easy_v4.jsonl"

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(s: str | None) -> str | None:
    return _HTML_TAG_RE.sub("", s).strip() if s else s


def _stratum_of(task_id: str) -> str:
    if "human1" in task_id:
        return "human1"
    if "recon2" in task_id:
        return "recon22"
    if "sub6_easy" in task_id:
        return "sub6"
    return "hmdb_ramp"


def _resolve_name(cands: dict, id_type: str, mid: str, chebi: ChebiLookup) -> str | None:
    """Try to get a display name from ChEBI xrefs."""
    kegg = cands.get("KEGG") or (mid if id_type == "KEGG" else None)
    hmdb = cands.get("HMDB") or (mid if id_type == "HMDB" else None)
    chebi_id = cands.get("CHEBI") or (mid if id_type == "ChEBI" else None)
    for ns, ext in [("CHEBI", chebi_id), ("KEGG", kegg), ("HMDB", hmdb)]:
        if not ext:
            continue
        try:
            if ns == "CHEBI":
                rec = chebi.get_compound(ext)
            else:
                rec = chebi.lookup_by_xref(ns, ext)
            if rec and rec.name:
                return _strip_html(rec.name)
        except Exception:
            pass
    return None


def main() -> None:
    resolver = StructureResolver()
    chebi = ChebiLookup()

    v3_lines = [l for l in _V3.read_text().splitlines() if l.strip()]
    print(f"Loaded {len(v3_lines)} tasks from v3")

    stats: Counter = Counter()
    out_tasks = []

    for raw in v3_lines:
        task = json.loads(raw)
        tid = task["task_id"]
        stratum = _stratum_of(tid)
        mets_in = task.get("input", {}).get("differential_metabolites", [])

        mets_out = []
        for m in mets_in:
            mid = str(m["id"])
            id_type = str(m["id_type"])

            # Resolve to SMILES + InChIKey via 2A
            res = resolver.resolve(mid, id_type, stratum=stratum)
            cands = _collect_cands(mid, id_type, resolver._gem, resolver._bigg_index)

            # Name: prefer existing, fall back to ChEBI
            name = m.get("name") or _resolve_name(cands, id_type, mid, chebi)
            if not name:
                name = mid  # last resort

            entry: dict = {"name": name}
            if res.smiles:
                entry["smiles"] = res.smiles
                stats["with_smiles"] += 1
            else:
                stats["name_only"] += 1

            if res.inchikey:
                entry["inchikey"] = res.inchikey

            mets_out.append(entry)

        new_task = {
            "task_id": tid,
            "difficulty": task.get("difficulty", "easy"),
            "ground_truth": task["ground_truth"],
            "input": {
                "context": task.get("input", {}).get("context", {}),
                "differential_metabolites": mets_out,
            },
        }
        if "provenance" in task:
            new_task["provenance"] = task["provenance"]
        out_tasks.append(new_task)
        stats["tasks"] += 1

    _V4.write_text(
        "\n".join(json.dumps(t, ensure_ascii=False) for t in out_tasks) + "\n",
        encoding="utf-8",
    )

    total_mets = stats["with_smiles"] + stats["name_only"]
    print(f"\nWrote {stats['tasks']} tasks → {_V4.name}")
    print(f"Metabolite coverage: {stats['with_smiles']}/{total_mets} "
          f"({100*stats['with_smiles']/total_mets:.1f}%) have SMILES")
    print(f"Name-only (no SMILES): {stats['name_only']}")

    # Per-task sample
    first = out_tasks[0]
    print(f"\nSample task: {first['task_id']}")
    for m in first["input"]["differential_metabolites"][:3]:
        print(f"  {m}")


if __name__ == "__main__":
    main()

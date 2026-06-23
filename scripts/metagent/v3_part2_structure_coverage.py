"""V3 Part 2 — step 0: structure-resolution coverage per stratum.

Measures the CEILING of the embedding/structure upgrade: for every differential
metabolite in the easy_v3 benchmark, can we resolve it to an InChIKey (identity
unification, job A) and a SMILES (fingerprint/structure embedding, job B)?

Resolution uses the SAME canonical resolvers the live pipeline uses:
  - KEGG / HMDB / ChEBI / PubChem ids  -> ChebiLookup.lookup_by_xref / get_compound
  - Human1 MAM ids                     -> data/reference/human_gem_metabolites.tsv
                                          (MAM -> KEGG/ChEBI/HMDB) then ChebiLookup
  - Recon2.2 BiGG ids                  -> MetaNetX BiGG->ChEBI then ChebiLookup

Pure audit, no LLM, no model rerun. Output is a per-stratum coverage table +
a per-metabolite CSV of unresolved ids (the gap list that bounds Part 2).
"""
from __future__ import annotations

import csv
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any

from concord.lookup.chebi import ChebiLookup, CompoundRecord

ROOT = Path(__file__).resolve().parents[2]
BENCHMARK = ROOT / "data/benchmark/metagent_bench_v2/metagent_bench_easy_v3.jsonl"
HUMAN_GEM = ROOT / "data/reference/human_gem_metabolites.tsv"
METANETX = ROOT / "data/concord/metanetx.sqlite"
OUT_DIR = ROOT / "data/metagent/v3_part2_coverage"
OUT_MD = ROOT / "reports/reports_v2/2026-06-23_v3_part2_structure_coverage.md"


def stratum_of(task: dict[str, Any]) -> str:
    tid = task["task_id"]
    if "human1" in tid:
        return "human1"
    if "recon2" in tid:
        return "recon22"
    if tid.startswith("sub6"):
        return "sub6_enrich"
    if tid.startswith("hmdb_ramp"):
        return "hmdb_ramp_membership"
    return "unknown"


def load_human1_crosswalk() -> dict[str, dict[str, str]]:
    """MAM id -> {kegg, chebi, hmdb} (first id per cell, namespace-stripped)."""
    table: dict[str, dict[str, str]] = {}
    with HUMAN_GEM.open(encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            mam = (row.get("mets") or "").strip()
            # mets carry compartment suffix (e.g. MAM02776c) -> strip to MAM02776
            base = mam[:-1] if mam[-1:].islower() else mam
            entry = table.setdefault(base, {"kegg": "", "chebi": "", "hmdb": ""})
            for src, col in (("kegg", "metKEGGID"), ("chebi", "metChEBIID"),
                             ("hmdb", "metHMDBID")):
                if entry[src]:
                    continue
                cell = (row.get(col) or "").split(";")[0].strip()
                if cell and cell.lower() not in ("na", "nan", ""):
                    entry[src] = cell
    return table


def load_bigg2chebi() -> dict[str, str]:
    """BiGG metabolite slug -> ChEBI numeric str via MetaNetX (Recon2.2 path)."""
    conn = sqlite3.connect(f"file:{METANETX}?mode=ro", uri=True)
    try:
        bigg = conn.execute(
            "SELECT mnx_id, external_id FROM mnx_xref WHERE external_ns='BIGG'"
        ).fetchall()
        chebi = dict(conn.execute(
            "SELECT mnx_id, external_id FROM mnx_xref WHERE external_ns='CHEBI'"
        ).fetchall())
    finally:
        conn.close()
    out: dict[str, str] = {}
    for mnx_id, bigg_met in bigg:
        if bigg_met in out:
            continue
        if mnx_id in chebi:
            out[bigg_met] = chebi[mnx_id]
    return out


def resolve(
    met: dict[str, Any],
    chebi: ChebiLookup,
    human1: dict[str, dict[str, str]],
    bigg2chebi: dict[str, str],
) -> CompoundRecord | None:
    mid = str(met.get("id") or "").strip()
    id_type = str(met.get("id_type") or "").strip()
    if not mid:
        return None
    if id_type == "KEGG":
        return chebi.lookup_by_xref("KEGG", mid)
    if id_type == "HMDB":
        return chebi.lookup_by_xref("HMDB", mid)
    if id_type == "ChEBI":
        try:
            return chebi.get_compound(mid)
        except ValueError:
            return None
    if id_type == "PubChem":
        return chebi.lookup_by_xref("PUBCHEM", mid)
    if id_type == "Human1":
        hit = human1.get(mid)
        if not hit:
            return None
        if hit["chebi"]:
            try:
                rec = chebi.get_compound(hit["chebi"])
            except ValueError:
                rec = None
            if rec:
                return rec
        if hit["kegg"]:
            rec = chebi.lookup_by_xref("KEGG", hit["kegg"])
            if rec:
                return rec
        if hit["hmdb"]:
            return chebi.lookup_by_xref("HMDB", hit["hmdb"])
        return None
    if id_type == "Recon2.2":
        # strip compartment suffix variants if present
        cid = bigg2chebi.get(mid)
        if not cid:
            return None
        try:
            return chebi.get_compound(cid)
        except ValueError:
            return None
    return None


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    chebi = ChebiLookup()
    human1 = load_human1_crosswalk()
    bigg2chebi = load_bigg2chebi()

    # de-dup at (stratum, id_type, id) level so coverage reflects distinct
    # metabolites, not task-weighted repeats.
    seen: set[tuple[str, str, str]] = set()
    stats: dict[str, dict[str, int]] = defaultdict(
        lambda: {"n": 0, "resolved": 0, "inchikey": 0, "smiles": 0}
    )
    by_type: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"n": 0, "resolved": 0, "inchikey": 0, "smiles": 0}
    )
    unresolved_rows: list[dict[str, str]] = []

    with BENCHMARK.open(encoding="utf-8") as handle:
        tasks = [json.loads(line) for line in handle if line.strip()]

    for task in tasks:
        strat = stratum_of(task)
        for met in task["input"]["differential_metabolites"]:
            id_type = str(met.get("id_type") or "")
            mid = str(met.get("id") or "")
            key = (strat, id_type, mid)
            if key in seen:
                continue
            seen.add(key)
            rec = resolve(met, chebi, human1, bigg2chebi)
            for bucket in (stats[strat], by_type[(strat, id_type)]):
                bucket["n"] += 1
                if rec is not None:
                    bucket["resolved"] += 1
                    if rec.inchikey:
                        bucket["inchikey"] += 1
                    if rec.smiles:
                        bucket["smiles"] += 1
            if rec is None or not rec.smiles:
                unresolved_rows.append({
                    "stratum": strat, "id_type": id_type, "id": mid,
                    "name": str(met.get("name") or ""),
                    "resolved": "yes" if rec else "no",
                    "has_inchikey": "yes" if (rec and rec.inchikey) else "no",
                })

    def pct(a: int, b: int) -> str:
        return f"{(100.0 * a / b):.1f}%" if b else "n/a"

    lines = [
        "# V3 Part 2 — Structure-resolution coverage (step 0)",
        "",
        f"- Date: `2026-06-23`  | Benchmark: `{BENCHMARK.name}` (easy_v3, distinct metabolites)",
        "- Resolver: same canonical path as the live pipeline (ChEBI sqlite +"
        " Human-GEM crosswalk + MetaNetX BiGG bridge). Pure audit, no LLM.",
        "- `InChIKey%` = identity-unification ceiling (job A); `SMILES%` ="
        " fingerprint/structure-embedding ceiling (job B).",
        "",
        "## Per-stratum coverage (distinct metabolites)",
        "",
        "| stratum | distinct mets | resolved% | InChIKey% | SMILES% |",
        "|---|---:|---:|---:|---:|",
    ]
    for strat in ("sub6_enrich", "hmdb_ramp_membership", "human1", "recon22"):
        s = stats[strat]
        lines.append(
            f"| {strat} | {s['n']} | {pct(s['resolved'], s['n'])} | "
            f"{pct(s['inchikey'], s['n'])} | {pct(s['smiles'], s['n'])} |"
        )
    lines += [
        "",
        "## By id_type (where the gap lives)",
        "",
        "| stratum | id_type | distinct | resolved% | InChIKey% | SMILES% |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for (strat, id_type), s in sorted(by_type.items()):
        lines.append(
            f"| {strat} | {id_type} | {s['n']} | {pct(s['resolved'], s['n'])} | "
            f"{pct(s['inchikey'], s['n'])} | {pct(s['smiles'], s['n'])} |"
        )
    lines += [
        "",
        f"Unresolved / no-SMILES metabolites: {len(unresolved_rows)} "
        f"(see `{OUT_DIR.name}/unresolved.csv`).",
        "",
        "## Reproduction",
        "",
        "```bash",
        "PYTHONPATH=. python scripts/metagent/v3_part2_structure_coverage.py",
        "```",
        "",
    ]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    csv_path = OUT_DIR / "unresolved.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["stratum", "id_type", "id", "name", "resolved", "has_inchikey"],
        )
        writer.writeheader()
        writer.writerows(unresolved_rows)

    json_path = OUT_DIR / "coverage_by_stratum.json"
    json_path.write_text(
        json.dumps({k: dict(v) for k, v in stats.items()}, indent=2),
        encoding="utf-8",
    )

    print("\n".join(lines))
    print(f"\nWrote {OUT_MD}\nWrote {csv_path}\nWrote {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

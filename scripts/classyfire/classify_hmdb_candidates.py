#!/usr/bin/env python3
"""Sample HMDB compounds by pathway domain and classify them with ClassyFire."""
from __future__ import annotations

import argparse
import json
import os
import random
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common.rdkit_utils import is_valid_smiles  # noqa: E402
from tools.benchmark.classyfire.client import (  # noqa: E402
    cache_path_for,
    classify_pool,
    inchikey_first_block,
)


DEFAULT_HMDB = Path(os.environ.get("METAGENT_HMDB_PATH", "/data/weiwentao/llm_agent_metabolomics/hmdb.sqlite"))
DEFAULT_RAMP = Path(os.environ.get("METAGENT_RAMP_PATH", "/data/weiwentao/llm_agent_metabolomics/ramp.sqlite"))
DEFAULT_OUTPUT = Path("data/processed/hmdb_candidates_classified.jsonl")
DEFAULT_CACHE_DIR = Path("data/cache/classyfire")
DEFAULT_CHECKPOINT = Path("data/processed/.classyfire_hmdb_checkpoint.json")


DOMAIN_TARGETS = {
    "central_metabolism": 60,
    "lipid_metabolism": 60,
    "nucleotide_metabolism": 60,
    "amino_acid_metabolism": 60,
    "other": 60,
}


DOMAIN_KEYWORDS = {
    "central_metabolism": [
        "tca",
        "citric acid",
        "glycolysis",
        "gluconeogenesis",
        "pentose phosphate",
        "pyruvate",
        "citrate cycle",
    ],
    "lipid_metabolism": [
        "lipid",
        "fatty acid",
        "beta-oxidation",
        "β-oxidation",
        "phospholipid",
        "sphingolipid",
        "glycerolipid",
        "bile acid",
        "steroid",
    ],
    "nucleotide_metabolism": [
        "purine",
        "pyrimidine",
        "nucleotide",
        "nucleoside",
        "riboflavin",
        "folate",
    ],
    "amino_acid_metabolism": [
        "amino acid",
        "alanine",
        "arginine",
        "aspartate",
        "cysteine",
        "glutamate",
        "glutamine",
        "glycine",
        "histidine",
        "isoleucine",
        "leucine",
        "lysine",
        "methionine",
        "phenylalanine",
        "proline",
        "serine",
        "threonine",
        "tryptophan",
        "tyrosine",
        "valine",
    ],
}


def main() -> int:
    args = _parse_args()
    candidates = _load_hmdb_candidates(args.hmdb_db, args.ramp_db)
    sampled = _stratified_sample(candidates, args.target_pool_size, seed=args.seed)
    print(
        f"Loaded {len(candidates)} HMDB pathway candidates; sampled {len(sampled)}.",
        file=sys.stderr,
    )

    def progress(idx: int, total: int, key: str, status: str) -> None:
        if idx == 1 or idx % 50 == 0 or idx == total:
            print(f"[HMDB] {idx}/{total} {key} {status}", file=sys.stderr, flush=True)

    classify_pool(
        sampled,
        cache_dir=args.cache_dir,
        request_interval_sec=args.request_interval,
        progress_callback=progress,
        checkpoint_path=args.checkpoint,
    )
    _write_output(sampled, args.cache_dir, args.output)
    print(f"Wrote {args.output}", file=sys.stderr)
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hmdb-db", type=Path, default=DEFAULT_HMDB)
    parser.add_argument("--ramp-db", type=Path, default=DEFAULT_RAMP)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--target-pool-size", type=int, default=300)
    parser.add_argument("--request-interval", type=float, default=5.5)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--seed", type=int, default=13)
    return parser.parse_args()


def _load_hmdb_candidates(hmdb_db: Path, ramp_db: Path) -> list[dict[str, Any]]:
    conn = sqlite3.connect(hmdb_db)
    conn.execute(f"ATTACH DATABASE {str(ramp_db)!r} AS ramp")
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT
            m.hmdb_id,
            m.primary_name,
            m.molecular_formula,
            m.exact_mass,
            m.smiles,
            m.inchikey,
            m.chemical_class,
            m.kegg_id,
            m.chebi_id,
            m.pubchem_cid,
            COUNT(DISTINCT p.pathwayRampId) AS pathway_count,
            GROUP_CONCAT(DISTINCT p.pathwayName) AS pathway_names
        FROM metabolites m
        JOIN ramp.source s
          ON s.sourceId = 'kegg:' || m.kegg_id
         AND s.geneOrCompound = 'compound'
        JOIN ramp.analytehaspathway ahp
          ON ahp.rampId = s.rampId
        JOIN ramp.pathway p
          ON p.pathwayRampId = ahp.pathwayRampId
        WHERE m.kegg_id IS NOT NULL AND m.kegg_id != ''
          AND m.smiles IS NOT NULL AND m.smiles != ''
          AND m.inchikey IS NOT NULL AND m.inchikey != ''
          AND m.exact_mass BETWEEN 50 AND 1000
        GROUP BY m.hmdb_id
        """
    ).fetchall()
    conn.close()

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        smiles = row["smiles"]
        inchikey = row["inchikey"]
        key = inchikey_first_block(inchikey)
        if key in seen or not is_valid_smiles(smiles):
            continue
        pathway_names = _split_pathways(row["pathway_names"])
        domain = _pathway_domain(pathway_names)
        seen.add(key)
        candidates.append(
            {
                "hmdb_id": row["hmdb_id"],
                "primary_name": row["primary_name"],
                "molecular_formula": row["molecular_formula"],
                "exact_mass": row["exact_mass"],
                "smiles": smiles,
                "inchikey": inchikey,
                "chemical_class": row["chemical_class"],
                "kegg_id": row["kegg_id"],
                "chebi_id": row["chebi_id"],
                "pubchem_cid": row["pubchem_cid"],
                "pathway_count": row["pathway_count"],
                "pathway_names": pathway_names,
                "pathway_domain": domain,
            }
        )
    return candidates


def _split_pathways(value: str | None) -> list[str]:
    if not value:
        return []
    return sorted({part.strip() for part in value.split(",") if part.strip()})


def _pathway_domain(pathway_names: list[str]) -> str:
    joined = " | ".join(pathway_names).lower()
    for domain, keywords in DOMAIN_KEYWORDS.items():
        if any(keyword.lower() in joined for keyword in keywords):
            return domain
    return "other"


def _stratified_sample(
    candidates: list[dict[str, Any]],
    target_pool_size: int,
    *,
    seed: int,
) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    by_domain: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        by_domain[candidate["pathway_domain"]].append(candidate)

    if target_pool_size != 300:
        per_domain = max(1, target_pool_size // len(DOMAIN_TARGETS))
        targets = {domain: per_domain for domain in DOMAIN_TARGETS}
        targets["other"] += target_pool_size - sum(targets.values())
    else:
        targets = DOMAIN_TARGETS

    sampled: list[dict[str, Any]] = []
    for domain, target in targets.items():
        pool = list(by_domain.get(domain) or [])
        pool.sort(key=lambda x: (-(x.get("pathway_count") or 0), x.get("hmdb_id") or ""))
        if len(pool) > target:
            top = pool[: target * 3]
            sampled.extend(rng.sample(top, target))
        else:
            sampled.extend(pool)

    if len(sampled) < target_pool_size:
        sampled_keys = {inchikey_first_block(c["inchikey"]) for c in sampled}
        remainder = [
            c for c in candidates
            if inchikey_first_block(c["inchikey"]) not in sampled_keys
        ]
        remainder.sort(key=lambda x: (-(x.get("pathway_count") or 0), x.get("hmdb_id") or ""))
        sampled.extend(remainder[: target_pool_size - len(sampled)])

    sampled.sort(key=lambda x: (x["pathway_domain"], x["hmdb_id"]))
    return sampled[:target_pool_size]


def _write_output(rows: list[dict[str, Any]], cache_dir: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w") as fh:
        for row in rows:
            out = dict(row)
            out["classyfire"] = _classyfire_payload(cache_dir, row["inchikey"])
            fh.write(json.dumps(out, sort_keys=True) + "\n")


def _classyfire_payload(cache_dir: Path, inchikey: str) -> dict[str, Any] | None:
    path = cache_path_for(cache_dir, inchikey)
    if not path.exists():
        return None
    with path.open() as fh:
        data = json.load(fh)
    if data.get("status") != "ok":
        return None
    result = dict(data["result"])
    result.pop("fetched_at", None)
    result.pop("api_version", None)
    return result


if __name__ == "__main__":
    raise SystemExit(main())

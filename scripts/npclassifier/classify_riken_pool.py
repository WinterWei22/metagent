#!/usr/bin/env python3
"""Classify the RIKEN compound pool with NPClassifier."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.benchmark.npclassifier.client import (  # noqa: E402
    cache_path_for,
    classify_pool_npc,
    inchikey_first_block,
)


DEFAULT_INPUT = Path("/data/weiwentao/llm_agent_metabolomics/massbank/processed/compound_pool_riken.jsonl")
DEFAULT_OUTPUT = Path("data/processed/compound_pool_riken_npc_classified.jsonl")
DEFAULT_CACHE_DIR = Path("data/cache/npclassifier")
DEFAULT_CHECKPOINT = Path("data/processed/.npclassifier_riken_checkpoint.json")


def main() -> int:
    args = _parse_args()
    rows = _load_jsonl(args.input)
    compounds = _unique_compounds(rows)
    print(
        f"Loaded {len(rows)} spectra; {len(compounds)} unique compounds by InChIKey first block.",
        file=sys.stderr,
    )

    def progress(idx: int, total: int, key: str, status: str) -> None:
        if idx == 1 or idx % 50 == 0 or idx == total:
            print(f"[RIKEN-NPC] {idx}/{total} {key} {status}", file=sys.stderr, flush=True)

    pool_error: BaseException | None = None
    try:
        classify_pool_npc(
            compounds,
            cache_dir=args.cache_dir,
            request_interval_sec=args.request_interval,
            progress_callback=progress,
            checkpoint_path=args.checkpoint,
        )
    except BaseException as exc:
        pool_error = exc
        print(f"classify_pool_npc aborted: {exc}", file=sys.stderr)

    npc_by_key = {
        inchikey_first_block(c["inchikey"]): _npc_payload(args.cache_dir, c["inchikey"])
        for c in compounds
    }
    _write_enriched_rows(rows, npc_by_key, args.output)

    n_ok = sum(1 for v in npc_by_key.values() if v is not None)
    print(
        f"Wrote {args.output}; {n_ok}/{len(npc_by_key)} unique compounds have NPClassifier data.",
        file=sys.stderr,
    )
    if pool_error is not None:
        print("Re-run this script to retry remaining compounds.", file=sys.stderr)
        return 1
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--request-interval", type=float, default=1.0)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    return parser.parse_args()


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open() as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _unique_compounds(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    compounds: list[dict[str, str]] = []
    for row in rows:
        gt = row.get("ground_truth") or {}
        inchikey = gt.get("inchikey")
        smiles = gt.get("smiles")
        if not inchikey or not smiles:
            continue
        key = inchikey_first_block(inchikey)
        if key in seen:
            continue
        seen.add(key)
        compounds.append(
            {
                "inchikey": inchikey,
                "smiles": smiles,
                "name": gt.get("primary_compound_name") or "",
            }
        )
    return compounds


def _npc_payload(cache_dir: Path, inchikey: str) -> dict[str, Any] | None:
    path = cache_path_for(cache_dir, inchikey)
    if not path.exists():
        return None
    with path.open() as fh:
        data = json.load(fh)
    if data.get("status") != "ok":
        return None
    result = dict(data["result"])
    result.pop("fetched_at", None)
    result.pop("api_endpoint", None)
    result.pop("smiles", None)
    result.pop("inchikey", None)
    result["superclass"] = list(result.get("superclass") or [])
    result["class_"] = list(result.get("class_") or [])
    result["pathway"] = list(result.get("pathway") or [])
    result["isglycoside"] = bool(result.get("isglycoside") or False)
    return result


def _write_enriched_rows(
    rows: list[dict[str, Any]],
    npc_by_key: dict[str, dict[str, Any] | None],
    output: Path,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w") as fh:
        for row in rows:
            gt = row.setdefault("ground_truth", {})
            inchikey = gt.get("inchikey") or ""
            gt["npclassifier"] = npc_by_key.get(inchikey_first_block(inchikey))
            fh.write(json.dumps(row, sort_keys=True) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())

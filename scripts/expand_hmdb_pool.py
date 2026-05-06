#!/usr/bin/env python3
"""Expand the HMDB NPClassifier candidate pool without overwriting v1.

This is a fallback helper for Sub-6B v2. It reuses the original HMDB
candidate loader and pathway-domain rules from
``scripts.npclassifier.classify_hmdb_candidates``; the only selection change is
that the existing v1 rows are pinned first, then additional HMDB candidates are
added round-robin across pathway-domain buckets.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.npclassifier.classify_hmdb_candidates import (  # noqa: E402
    DEFAULT_CACHE_DIR,
    DEFAULT_HMDB,
    DEFAULT_RAMP,
    DOMAIN_KEYWORDS,
    _load_hmdb_candidates,
    _npc_payload,
)
from tools.benchmark.npclassifier.client import (  # noqa: E402
    NPClassifierNetworkError,
    cache_path_for,
    classify_compound_npc,
    inchikey_first_block,
)


DEFAULT_INPUT = Path("data/processed/hmdb_candidates_npc_classified.jsonl")
DEFAULT_OUTPUT = Path("data/processed/hmdb_candidates_npc_classified_v2.jsonl")
DEFAULT_AUDIT = Path("reports/benchmark/curation/hmdb_pool_expansion_audit.md")
DEFAULT_CHECKPOINT = Path("data/processed/.npclassifier_v2_checkpoint.json")
DOMAINS = (
    "amino_acid_metabolism",
    "central_metabolism",
    "lipid_metabolism",
    "nucleotide_metabolism",
    "other",
)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    t0 = time.monotonic()
    before_cache_files = set(args.cache_dir.glob("*.json"))

    original_rows = _read_jsonl(args.input)
    all_candidates = _load_hmdb_candidates(args.hmdb_db, args.ramp_db)
    selected, selection_stats = _select_candidates(
        original_rows=original_rows,
        all_candidates=all_candidates,
        target_total=args.target_total,
        target_per_bucket=args.target_per_bucket,
    )

    classify_stats = _classify_selected(
        selected,
        cache_dir=args.cache_dir,
        checkpoint_path=args.checkpoint,
        request_interval_sec=args.request_interval,
    )

    rows = _rows_with_npc(selected, args.cache_dir)
    if len(rows) < args.target_total:
        print(
            f"ERROR: only {len(rows)} classified rows available; "
            f"target is {args.target_total}",
            file=sys.stderr,
        )
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    _write_jsonl(rows, args.output)

    after_cache_files = set(args.cache_dir.glob("*.json"))
    cache_files_added = len(after_cache_files - before_cache_files)
    elapsed = time.monotonic() - t0
    _write_audit(
        output_path=args.audit,
        original_rows=original_rows,
        v2_rows=rows,
        all_candidates=all_candidates,
        selection_stats=selection_stats,
        classify_stats=classify_stats,
        cache_files_before=len(before_cache_files),
        cache_files_after=len(after_cache_files),
        cache_files_added=cache_files_added,
        output_file=args.output,
        command=" ".join(sys.argv),
        elapsed=elapsed,
    )
    print(f"Wrote {args.output} ({len(rows)} rows)", file=sys.stderr)
    print(f"Wrote {args.audit}", file=sys.stderr)
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    p.add_argument("--hmdb-db", type=Path, default=DEFAULT_HMDB)
    p.add_argument("--ramp-db", type=Path, default=DEFAULT_RAMP)
    p.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    p.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    p.add_argument("--target-total", type=int, default=600)
    p.add_argument("--target-per-bucket", type=int, default=120)
    p.add_argument("--request-interval", type=float, default=1.0)
    return p.parse_args(argv)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _write_jsonl(rows: list[dict[str, Any]], path: Path) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")


def _select_candidates(
    *,
    original_rows: list[dict[str, Any]],
    all_candidates: list[dict[str, Any]],
    target_total: int,
    target_per_bucket: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    selected: list[dict[str, Any]] = [dict(row) for row in original_rows]
    selected_first = {_first(row) for row in selected}
    selected_kegg = {row.get("kegg_id") for row in selected if row.get("kegg_id")}
    bucket_counts = Counter(row.get("pathway_domain", "other") for row in selected)

    by_domain_unique_kegg: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_domain_duplicate_kegg: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in all_candidates:
        first = _first(row)
        if first in selected_first:
            continue
        bucket = row.get("pathway_domain") or "other"
        if row.get("kegg_id") in selected_kegg:
            by_domain_duplicate_kegg[bucket].append(row)
        else:
            by_domain_unique_kegg[bucket].append(row)

    for pools in (by_domain_unique_kegg, by_domain_duplicate_kegg):
        for bucket_rows in pools.values():
            bucket_rows.sort(
                key=lambda r: (-(r.get("pathway_count") or 0), r.get("hmdb_id") or "")
            )

    added_unique_kegg = _round_robin_add(
        selected,
        selected_first,
        selected_kegg,
        bucket_counts,
        by_domain_unique_kegg,
        target_total=target_total,
        target_per_bucket=target_per_bucket,
    )
    added_duplicate_kegg = _round_robin_add(
        selected,
        selected_first,
        selected_kegg,
        bucket_counts,
        by_domain_duplicate_kegg,
        target_total=target_total,
        target_per_bucket=target_per_bucket,
    )

    selected.sort(key=lambda r: ((r.get("pathway_domain") or "other"), r.get("hmdb_id") or ""))
    return selected, {
        "added_unique_kegg": added_unique_kegg,
        "added_duplicate_kegg": added_duplicate_kegg,
        "bucket_capacity": dict(Counter(r["pathway_domain"] for r in all_candidates)),
        "selected_bucket_counts": dict(Counter(r["pathway_domain"] for r in selected)),
    }


def _round_robin_add(
    selected: list[dict[str, Any]],
    selected_first: set[str],
    selected_kegg: set[str],
    bucket_counts: Counter,
    pools: dict[str, list[dict[str, Any]]],
    *,
    target_total: int,
    target_per_bucket: int,
) -> int:
    added = 0
    cursors = {domain: 0 for domain in DOMAINS}
    while len(selected) < target_total:
        progressed = False
        for domain in DOMAINS:
            if len(selected) >= target_total:
                break
            if bucket_counts[domain] >= target_per_bucket:
                continue
            pool = pools.get(domain) or []
            while cursors[domain] < len(pool):
                row = pool[cursors[domain]]
                cursors[domain] += 1
                first = _first(row)
                if first in selected_first:
                    continue
                selected.append(dict(row))
                selected_first.add(first)
                if row.get("kegg_id"):
                    selected_kegg.add(row["kegg_id"])
                bucket_counts[domain] += 1
                added += 1
                progressed = True
                break
        if not progressed:
            break
    return added


def _classify_selected(
    rows: list[dict[str, Any]],
    *,
    cache_dir: Path,
    checkpoint_path: Path,
    request_interval_sec: float,
) -> dict[str, Any]:
    processed = _load_processed(checkpoint_path)
    stats = Counter()
    failures: list[str] = []
    total = len(rows)
    for idx, row in enumerate(rows, start=1):
        first = _first(row)
        cache_path = cache_path_for(cache_dir, row["inchikey"])
        had_cache = cache_path.exists()
        if first in processed and had_cache:
            stats["checkpoint_skips"] += 1
            continue
        if had_cache:
            stats["cache_hits"] += 1
        else:
            stats["api_calls"] += 1
            time.sleep(request_interval_sec)
        try:
            result = classify_compound_npc(
                row.get("smiles") or "",
                row["inchikey"],
                cache_dir=cache_dir,
            )
        except NPClassifierNetworkError as exc:
            failures.append(f"{first}:network:{exc}")
            _write_processed(checkpoint_path, processed)
            raise
        if result is None:
            stats["failed"] += 1
            failures.append(first)
        else:
            stats["classified"] += 1
        processed.add(first)
        if idx == 1 or idx % 25 == 0 or idx == total:
            print(
                f"[HMDB-v2-NPC] {idx}/{total} {first} "
                f"{'cache' if had_cache else 'api'}",
                file=sys.stderr,
                flush=True,
            )
        if len(processed) % 50 == 0:
            _write_processed(checkpoint_path, processed)
    _write_processed(checkpoint_path, processed)
    out = dict(stats)
    out["failures"] = failures
    return out


def _rows_with_npc(rows: list[dict[str, Any]], cache_dir: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        npc = _npc_payload(cache_dir, row["inchikey"])
        if npc is None:
            continue
        payload = dict(row)
        payload["npclassifier"] = npc
        out.append(payload)
    return out


def _first(row: dict[str, Any]) -> str:
    return inchikey_first_block(row.get("inchikey") or "")


def _load_processed(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    return set(data.get("processed_keys") or [])


def _write_processed(path: Path, processed: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(
            {
                "processed_keys": sorted(processed),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            fh,
            sort_keys=True,
        )
    tmp.replace(path)


def _md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()
    except Exception:  # noqa: BLE001
        return "unavailable"


def _write_audit(
    *,
    output_path: Path,
    original_rows: list[dict[str, Any]],
    v2_rows: list[dict[str, Any]],
    all_candidates: list[dict[str, Any]],
    selection_stats: dict[str, Any],
    classify_stats: dict[str, Any],
    cache_files_before: int,
    cache_files_after: int,
    cache_files_added: int,
    output_file: Path,
    command: str,
    elapsed: float,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    orig_bucket = Counter(r.get("pathway_domain", "other") for r in original_rows)
    v2_bucket = Counter(r.get("pathway_domain", "other") for r in v2_rows)
    capacity = Counter(r.get("pathway_domain", "other") for r in all_candidates)
    orig_kegg = {r.get("kegg_id") for r in original_rows if r.get("kegg_id")}
    v2_kegg = {r.get("kegg_id") for r in v2_rows if r.get("kegg_id")}
    cache_hits = classify_stats.get("cache_hits", 0) + classify_stats.get("checkpoint_skips", 0)
    api_calls = classify_stats.get("api_calls", 0)
    failures = classify_stats.get("failures", [])

    lines = [
        "# HMDB Pool Expansion Audit",
        "",
        f"**Generated:** {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"**Wall time:** {elapsed:.1f}s",
        "",
        "## 1. Summary",
        "",
        "| metric | original (300) | v2 (600+) |",
        "|---|---:|---:|",
        f"| total candidates | {len(original_rows)} | {len(v2_rows)} |",
    ]
    for domain in DOMAINS:
        lines.append(f"| {domain} bucket | {orig_bucket.get(domain, 0)} | {v2_bucket.get(domain, 0)} |")
    lines += [
        f"| unique KEGG IDs | {len(orig_kegg)} | {len(v2_kegg)} |",
        f"| NPClassifier cache hits | {len(original_rows)} | {cache_hits} |",
        f"| NPClassifier API calls (new) | 0 | {api_calls} |",
        f"| API call failures | n/a | {len(failures)} |",
        "",
        "## 2. Selection Logic",
        "",
        "HMDB query and RaMP join are reused from "
        "`scripts/npclassifier/classify_hmdb_candidates.py`:",
        "",
        "```sql",
        "SELECT m.hmdb_id, m.primary_name, m.molecular_formula, m.exact_mass,",
        "       m.smiles, m.inchikey, m.chemical_class, m.kegg_id,",
        "       m.chebi_id, m.pubchem_cid,",
        "       COUNT(DISTINCT p.pathwayRampId) AS pathway_count,",
        "       GROUP_CONCAT(DISTINCT p.pathwayName) AS pathway_names",
        "FROM metabolites m",
        "JOIN ramp.source s",
        "  ON s.sourceId = 'kegg:' || m.kegg_id",
        " AND s.geneOrCompound = 'compound'",
        "JOIN ramp.analytehaspathway ahp ON ahp.rampId = s.rampId",
        "JOIN ramp.pathway p ON p.pathwayRampId = ahp.pathwayRampId",
        "WHERE m.kegg_id IS NOT NULL AND m.kegg_id != ''",
        "  AND m.smiles IS NOT NULL AND m.smiles != ''",
        "  AND m.inchikey IS NOT NULL AND m.inchikey != ''",
        "  AND m.exact_mass BETWEEN 50 AND 1000",
        "GROUP BY m.hmdb_id",
        "```",
        "",
        "Pathway-domain assignment is the existing first-match keyword rule over "
        "RaMP pathway names:",
        "",
        "```python",
        "joined = ' | '.join(pathway_names).lower()",
        "for domain, keywords in DOMAIN_KEYWORDS.items():",
        "    if any(keyword.lower() in joined for keyword in keywords):",
        "        return domain",
        "return 'other'",
        "```",
        "",
        "Domain keywords:",
        "",
        "```json",
        json.dumps(DOMAIN_KEYWORDS, indent=2, sort_keys=True),
        "```",
        "",
        "Selection pins all original 300 rows, then adds candidates round-robin "
        "across the five buckets to target 120 per bucket. New rows prefer KEGG "
        "IDs not already present in v1; duplicate KEGG rows are only used if a "
        "bucket cannot otherwise fill.",
        "",
        "## 3. Per-Bucket Sample",
        "",
    ]
    by_bucket: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in v2_rows:
        by_bucket[row.get("pathway_domain", "other")].append(row)
    for domain in DOMAINS:
        lines += [f"### {domain}", ""]
        for row in by_bucket.get(domain, [])[:5]:
            npc_path = ", ".join((row.get("npclassifier") or {}).get("pathway") or [])
            lines.append(f"- {row.get('primary_name')} (`{row.get('kegg_id')}`) — {npc_path or 'empty'}")
        lines.append("")

    lines += [
        "## 4. Coverage Gaps",
        "",
    ]
    for domain in DOMAINS:
        got = v2_bucket.get(domain, 0)
        cap = capacity.get(domain, 0)
        status = "filled" if got >= 120 else "short"
        lines.append(f"- `{domain}`: {got}/120 selected; HMDB candidate capacity {cap} ({status}).")

    lines += [
        "",
        "## 5. NPClassifier API Stats",
        "",
        f"- Cache files before: {cache_files_before}",
        f"- Cache files after: {cache_files_after}",
        f"- Cache files added: {cache_files_added}",
        f"- Cache hits/checkpoint skips: {cache_hits}",
        f"- API calls: {api_calls}",
        f"- Failed compounds: {len(failures)}",
    ]
    if failures:
        for item in failures:
            lines.append(f"  - `{item}`")

    lines += [
        "",
        "## 6. Provenance",
        "",
        f"- Git commit SHA: `{_git_commit()}`",
        f"- Output file: `{output_file}`",
        f"- File MD5: `{_md5(output_file)}`",
        f"- Wall time: {elapsed:.1f}s",
        f"- Command: `{command}`",
        "",
        "## 7. Handoff to Phase 1",
        "",
        "Phase 1 should rerun `scripts/build_sub6/build_all.py` with:",
        "",
        "```bash",
        "PYTHONPATH=. python scripts/build_sub6/build_all.py \\",
        "    --hmdb-candidates data/processed/hmdb_candidates_npc_classified_v2.jsonl \\",
        "    --target-6b-mammalian 100 \\",
        "    --target-curated-hmdb 250 \\",
        "    --pathway-min-compounds 3 \\",
        "    --tasks-per-pathway-max 10 \\",
        "    --tasks-per-bucket-max 20 \\",
        "    --output-dir data/benchmark/sub6/ \\",
        "    --report-path reports/benchmark/sub6_construction_report_v2_raw.md \\",
        "    --skip-spectrum-index \\",
        "    --seed 42",
        "```",
        "",
        "Expected Sub-6B task count by linear extrapolation is roughly "
        "`35 * 600 / 250 = 84`, but the real value depends on unique KEGG "
        "coverage after RaMP top-3 validation. Central/lipid task recovery is "
        "expected to improve if the added pool survives task-stage mammalian "
        "pathway filtering.",
        "",
        "## Acceptance Snapshot",
        "",
        f"- Original file preserved: {len(original_rows) == 300}",
        f"- v2 row count >= 500: {len(v2_rows) >= 500}",
        f"- v2 contains all original KEGG IDs: {orig_kegg.issubset(v2_kegg)}",
        f"- v2 contains all original InChIKey first-blocks: "
        f"{ {_first(r) for r in original_rows}.issubset({_first(r) for r in v2_rows}) }",
        f"- Every bucket >= 50: {all(v2_bucket.get(domain, 0) >= 50 for domain in DOMAINS)}",
        f"- Records missing npclassifier: {sum(1 for r in v2_rows if not r.get('npclassifier'))}",
    ]
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())

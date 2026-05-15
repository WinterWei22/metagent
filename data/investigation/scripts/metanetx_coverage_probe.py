"""§2.5 MetaNetX cross-ref coverage probe.

输入:`data/investigation/metanetx_cache/chem_xref.tsv`(MNXref 4.5,2025-08-13)
输出:
  1. cross-ref source 频次分布(全表)
  2. 50 个随机 metabolite × 7 主源覆盖矩阵(以 MNX ID 为锚,反查每个 source 是否命中)

主源:reactome / chebi / hmdb / kegg.compound / metacyc.compound / lipidmaps(SLM)/ bigg.metabolite

Usage:
    python data/investigation/scripts/metanetx_coverage_probe.py
"""
from __future__ import annotations

import random
import time
from collections import Counter, defaultdict
from pathlib import Path

TSV = Path(__file__).resolve().parents[1] / "metanetx_cache" / "chem_xref.tsv"

# 主源 prefix → 标准化短名(MetaNetX 输出有大小写 / 别名混合)
SOURCE_NORMALIZE = {
    "reactome":          "reactome",
    "reactomeM":         "reactome",
    "chebi":             "chebi",
    "CHEBI":             "chebi",
    "hmdb":              "hmdb",
    "HMDB":              "hmdb",
    "kegg.compound":     "kegg",
    "keggC":             "kegg",
    "metacyc.compound":  "metacyc",
    "metacycM":          "metacyc",
    "bigg.metabolite":   "bigg",
    "biggM":             "bigg",
    "SLM":               "lipidmaps",   # SwissLipids
    "slm":               "lipidmaps",
    "lipidmaps":         "lipidmaps",
    "LIPIDMAPS":         "lipidmaps",
}
PRIMARY_SOURCES = ("reactome", "chebi", "hmdb", "kegg", "metacyc", "bigg", "lipidmaps")


def parse_tsv(path: Path) -> dict[str, dict[str, list[str]]]:
    """Return {mnx_id: {source_short: [external_ids...]}}."""
    t0 = time.time()
    by_mnx: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    total = 0
    skipped = 0
    with path.open() as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            cols = line.rstrip("\n").split("\t")
            if len(cols) < 2:
                skipped += 1
                continue
            xref, mnx_id = cols[0], cols[1]
            total += 1
            if ":" in xref:
                src_raw, ext_id = xref.split(":", 1)
            else:
                src_raw, ext_id = xref, ""
            src_short = SOURCE_NORMALIZE.get(src_raw)
            if src_short:
                by_mnx[mnx_id][src_short].append(ext_id)
    print(f"Parsed {total} rows ({skipped} skipped, {len(by_mnx)} MNX entities)  "
          f"in {time.time()-t0:.1f}s")
    return by_mnx


def source_distribution(path: Path) -> None:
    """Print frequency of each source-prefix in raw chem_xref.tsv."""
    cnt = Counter()
    with path.open() as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            xref = line.split("\t", 1)[0]
            prefix = xref.split(":", 1)[0] if ":" in xref else xref
            cnt[prefix] += 1
    print("\n=== Source-prefix distribution (top 25) ===")
    for src, n in cnt.most_common(25):
        normed = SOURCE_NORMALIZE.get(src, "-")
        print(f"  {src:<22s} n={n:>8d}  -> {normed}")
    print(f"  total unique source prefixes: {len(cnt)}")


def coverage_matrix(by_mnx: dict[str, dict[str, list[str]]], n_sample: int = 50, seed: int = 42) -> None:
    """Pick n_sample random MNX entities;打印 7-source 覆盖矩阵。"""
    random.seed(seed)
    mnx_ids = list(by_mnx.keys())
    if len(mnx_ids) < n_sample:
        sample = mnx_ids
    else:
        sample = random.sample(mnx_ids, n_sample)

    print(f"\n=== Coverage matrix ({len(sample)} random MNX × {len(PRIMARY_SOURCES)} sources) ===")
    print(f"  seed={seed}")
    print(f"  {'mnx_id':<14s} | " + " | ".join(f"{s:<9s}" for s in PRIMARY_SOURCES))
    print(f"  {'-'*14} | " + " | ".join(f"{'-'*9}" for _ in PRIMARY_SOURCES))

    coverage = {s: 0 for s in PRIMARY_SOURCES}
    n_hits_dist = Counter()
    for mnx in sample:
        srcs = by_mnx[mnx]
        row = []
        n_hit = 0
        for s in PRIMARY_SOURCES:
            hits = srcs.get(s, [])
            if hits:
                coverage[s] += 1
                n_hit += 1
                row.append("✓" if len(hits) == 1 else f"✓×{len(hits)}")
            else:
                row.append("·")
        n_hits_dist[n_hit] += 1
        print(f"  {mnx:<14s} | " + " | ".join(f"{c:<9s}" for c in row))

    print(f"\n=== Per-source coverage (out of {len(sample)} sampled MNX) ===")
    for s in PRIMARY_SOURCES:
        c = coverage[s]
        pct = c / len(sample) * 100
        print(f"  {s:<10s} {c:>3d}/{len(sample)}  ({pct:5.1f}%)")

    print(f"\n=== Distribution of n-source-hit per metabolite (out of {len(PRIMARY_SOURCES)} sources) ===")
    for nh in sorted(n_hits_dist.keys()):
        n = n_hits_dist[nh]
        bar = "█" * n
        print(f"  {nh} sources: {n:>3d}  {bar}")


def main() -> None:
    if not TSV.exists():
        print(f"❌ chem_xref.tsv not found at {TSV}")
        print("   Run the curl download first (see §2.5 in report).")
        return
    print(f"Reading {TSV}  ({TSV.stat().st_size / 1024 / 1024:.1f} MB)")
    source_distribution(TSV)
    by_mnx = parse_tsv(TSV)
    coverage_matrix(by_mnx, n_sample=50, seed=42)


if __name__ == "__main__":
    main()

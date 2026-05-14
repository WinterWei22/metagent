"""§1 RIKEN inventory for negative-mode spike test.

Reads the protocol-filtered RIKEN JSONL produced by
`scripts/build_compound_pool.py` (track BENCH-MB) and prints the
breakdowns the brief asks for.

Usage:
    python scripts/spike/check_riken_negative.py [path-to-jsonl]

Default path:
    /data/weiwentao/llm_agent_metabolomics/massbank/processed/compound_pool_riken.jsonl
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict


DEFAULT_JSONL = (
    "/data/weiwentao/llm_agent_metabolomics/massbank/processed/"
    "compound_pool_riken.jsonl"
)


def main(path: str) -> None:
    if not os.path.exists(path):
        print(f"FATAL: {path} not found", file=sys.stderr)
        sys.exit(2)

    n_total = 0
    n_pos = 0
    n_neg = 0
    n_other_mode = 0

    neg_records: list[dict] = []

    with open(path) as f:
        for line in f:
            n_total += 1
            r = json.loads(line)
            mode = r["spectrum"]["ionization_mode"]
            if mode == "positive":
                n_pos += 1
            elif mode == "negative":
                n_neg += 1
                neg_records.append(r)
            else:
                n_other_mode += 1

    pct_pos = 100.0 * n_pos / n_total if n_total else 0.0
    pct_neg = 100.0 * n_neg / n_total if n_total else 0.0

    print(f"Total RIKEN records: {n_total}")
    print(f"Positive mode: {n_pos} ({pct_pos:.1f}%)")
    print(f"Negative mode: {n_neg} ({pct_neg:.1f}%)")
    if n_other_mode:
        print(f"Other / unknown mode: {n_other_mode}")
    print()

    if not neg_records:
        print("No negative-mode records found.")
        return

    print("Negative mode breakdown")
    print("-----------------------")

    instrument_counts: Counter = Counter()
    for r in neg_records:
        inst = r["metadata"].get("instrument_type") or r["metadata"].get("instrument") or "unknown"
        instrument_counts[inst] += 1
    print("\nBy instrument_type:")
    for k, v in instrument_counts.most_common():
        print(f"  {k}: {v}")

    class_counts: Counter = Counter()
    for r in neg_records:
        cls = r["ground_truth"].get("compound_class") or "unspecified"
        class_counts[cls] += 1
    print("\nBy compound_class (SMARTS-only labels per pipeline default):")
    for k, v in class_counts.most_common():
        print(f"  {k}: {v}")

    adduct_counts: Counter = Counter()
    for r in neg_records:
        adduct_counts[r["spectrum"]["adduct"]] += 1
    print("\nBy adduct:")
    for k, v in adduct_counts.most_common():
        print(f"  {k}: {v}")

    # peak count buckets (post-protocol-filter; the pipeline already
    # enforces min_peaks≥3, but the brief asks specifically about ≥15)
    n_ge_15 = sum(1 for r in neg_records if len(r["spectrum"]["mz"]) >= 15)
    n_ge_5 = sum(1 for r in neg_records if len(r["spectrum"]["mz"]) >= 5)
    print(f"\nPeak count: ≥5 → {n_ge_5}, ≥15 → {n_ge_15}")

    # SMILES + InChIKey completeness
    n_with_smiles = sum(1 for r in neg_records if r["ground_truth"].get("smiles"))
    n_with_inchikey = sum(1 for r in neg_records if r["ground_truth"].get("inchikey"))
    n_with_both = sum(
        1
        for r in neg_records
        if r["ground_truth"].get("smiles") and r["ground_truth"].get("inchikey")
    )
    print(
        f"\nGround-truth completeness:"
        f"\n  has SMILES: {n_with_smiles}"
        f"\n  has InChIKey: {n_with_inchikey}"
        f"\n  has both: {n_with_both}"
    )

    # Cross-tab class × peak-count
    print("\nNegative records with peaks≥15 broken down by class:")
    by_class_ge15: dict[str, int] = defaultdict(int)
    for r in neg_records:
        if len(r["spectrum"]["mz"]) >= 15:
            cls = r["ground_truth"].get("compound_class") or "unspecified"
            by_class_ge15[cls] += 1
    for k in sorted(by_class_ge15, key=lambda x: -by_class_ge15[x]):
        print(f"  {k}: {by_class_ge15[k]}")

    # Verdict for ~300-record-per-subset benchmark target.
    target_per_subset = 75
    target_subsets = 4
    target_total = target_per_subset * target_subsets
    qualifying = n_with_both
    if qualifying >= target_total:
        verdict = (
            f"ACHIEVABLE — {qualifying} qualifying neg-mode records "
            f">= benchmark target {target_total}."
        )
    elif qualifying >= int(0.6 * target_total):
        verdict = (
            f"MARGINAL — {qualifying} qualifying records is "
            f"{100.0*qualifying/target_total:.0f}% of {target_total}; "
            f"consider extending to other contributors."
        )
    else:
        verdict = (
            f"INSUFFICIENT — only {qualifying} qualifying records "
            f"({100.0*qualifying/target_total:.0f}% of target)."
        )
    print(f"\nVerdict (target ~{target_total}): {verdict}")


if __name__ == "__main__":
    p = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_JSONL
    main(p)

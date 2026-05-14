"""Aggregate Sub-6 verifier unverifiable_v0 verdicts by evidence prefix.

Read-only diagnostic script. Maps each unverifiable_v0 claim to one of
~10 reason buckets via evidence-text prefix matching, then prints
distribution and sampled verbatim claims per bucket.

Run:
    python -m scripts.diag.sub6_unverifiable_diag
"""
from __future__ import annotations

import json
import random
from collections import Counter, defaultdict
from pathlib import Path

random.seed(42)

# ---------------------------------------------------------------------------
# Reason buckets — keyed prefix → (layer_short, reason_key, category)
# Categories: A=data limitation, B=layer logic gap, C=extraction artifact,
#             D=by-design limitation
# ---------------------------------------------------------------------------

REASON_BUCKETS: list[tuple[str, str, str, str]] = [
    # (evidence-prefix, layer, reason_key, category A/B/C/D)
    # Layer 6c (biological_sub6) — 2 branches
    ("Disease / clinical-significance claims fall outside Sub-6 v0 scope",
     "biological_sub6", "disease_keyword_defer", "A"),
    # NOTE: biological_sub6 evidence text itself says "Free-text biological
    # role claims are out of v0 scope" → declarative v0 limitation, not an
    # extraction defect. We classify Cat D, not Cat C.
    ("Layer biological_sub6 found no pathway phrase / ID",
     "biological_sub6", "free_text_biological_role", "D"),

    # Layer 6a (set_enrichment) — 2 branches
    ("ramp_enrichment_result.top_pathways is empty",
     "set_enrichment", "top_pathways_empty", "A"),
    ("Layer 6a found no pathway ID or name in the claim",
     "set_enrichment", "no_pathway_phrase", "C"),

    # Layer 6d (pathway_relationship) — 5 branches
    ("Layer 6d could not detect a recognised relationship keyword",
     "pathway_relationship", "no_relationship_keyword", "C"),
    # IMPORTANT: keep the longer prefix first, so it wins over the
    # generic "Claim asserts a" prefix below.
    ("but RaMP-DB v2025-03-06 has no pathway-hierarchy table",
     "pathway_relationship", "ramp_no_hierarchy_table", "A"),
    ("Claim asserts a", "pathway_relationship",
     "ramp_no_hierarchy_table", "A"),  # fallback — also hierarchy-related
    ("not set and no db_path supplied",
     "pathway_relationship", "ramp_db_unavailable", "B"),
    ("Pathway resolution failed after regex + reverse-match",
     "pathway_relationship", "pathway_resolution_failed", "C"),
    ("Both pathway phrases resolved to the same RaMP id",
     "pathway_relationship", "same_pathway_pair", "C"),

    # Layer 6b (driver_metabolite) — 3 branches
    ("Layer 6b found no driver compound names / IDs",
     "driver_metabolite", "no_driver_names", "C"),
    ("None of the claimed drivers",
     "driver_metabolite", "drivers_unresolved", "C"),
    ("Driver verdict policy did not produce a definitive outcome",
     "driver_metabolite", "policy_fallback", "B"),

    # verify_sub6 dispatcher — schema mismatch declared limitation
    ("Sub-6 verifier does not support claim_type",
     "verify_sub6_dispatcher", "claim_type_unsupported", "D"),
]

CAT_LABELS = {
    "A": "Data limitation (RaMP / curated DB lacks the field)",
    "B": "Layer logic gap (data exists, layer doesn't reach it)",
    "C": "Claim-extraction artifact (claim too vague / unparseable)",
    "D": "By-design v0 limitation (declared scope)",
}


def classify_evidence(evidence: str) -> tuple[str, str, str] | None:
    if not evidence:
        return None
    for prefix, layer, key, cat in REASON_BUCKETS:
        if prefix in evidence:
            return (layer, key, cat)
    return None


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_unverifiable(path: Path) -> list[dict]:
    out = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        for c in (rec.get("claims") or []):
            if c.get("verdict") == "unverifiable_v0":
                out.append({**c, "_task": rec["task_id"]})
    return out


# ---------------------------------------------------------------------------
# Per-track aggregation
# ---------------------------------------------------------------------------


TRACKS: list[tuple[str, str]] = [
    ("Sub-6B", "data/eval/sub6/sub6b_verdicts_v2.jsonl"),
    ("Sub-6A_perfect", "data/eval/sub6/sub6a_perfect_id_verdicts_v2.jsonl"),
    ("Sub-6A_real_id", "data/eval/sub6/sub6a_real_id_verdicts.jsonl"),
]


def main() -> None:
    all_results: dict[str, dict] = {}

    for track_name, path_s in TRACKS:
        path = Path(path_s)
        if not path.is_file():
            print(f"!! {track_name}: missing {path}")
            continue
        unv = load_unverifiable(path)
        bucket_counts = Counter()
        bucket_samples = defaultdict(list)
        type_split = defaultdict(Counter)
        unmatched = []

        for c in unv:
            ev = c.get("evidence") or ""
            cls = classify_evidence(ev)
            if cls is None:
                unmatched.append(c)
                continue
            layer, key, cat = cls
            bkey = (layer, key, cat)
            bucket_counts[bkey] += 1
            bucket_samples[bkey].append(c)
            type_split[bkey][c["claim_type"]] += 1

        all_results[track_name] = {
            "total": len(unv),
            "unmatched": len(unmatched),
            "bucket_counts": bucket_counts,
            "bucket_samples": bucket_samples,
            "type_split": type_split,
        }

        print(f"\n{'='*70}")
        print(f"  {track_name}: {len(unv)} unverifiable_v0 claims")
        print(f"  unmatched (no prefix hit): {len(unmatched)}")
        print(f"{'='*70}")
        for (layer, key, cat), cnt in bucket_counts.most_common():
            pct = cnt / len(unv) * 100
            print(f"  [{cat}] {layer:24s} {key:32s} {cnt:4d}  ({pct:5.1f}%)")
        if unmatched:
            print("\n  UNMATCHED SAMPLES:")
            for c in unmatched[:5]:
                print(f"    layer={c.get('verifier_layer')}  type={c['claim_type']}")
                print(f"    text:     {c['claim_text'][:120]}")
                print(f"    evidence: {(c.get('evidence') or '')[:120]}")

        # Per claim_type breakdown by category
        print("\n  By claim_type (total per type / unverifiable per type):")
        type_cat_split = defaultdict(lambda: Counter())
        for (layer, key, cat), cnt in bucket_counts.items():
            for ct, n in type_split[(layer, key, cat)].items():
                type_cat_split[ct][cat] += n
        for ct, cat_counts in sorted(type_cat_split.items(), key=lambda x: -sum(x[1].values())):
            total = sum(cat_counts.values())
            cat_str = " ".join(f"{c}={n}" for c, n in sorted(cat_counts.items()))
            print(f"    {ct:30s} total={total:4d}  {cat_str}")

    # Cross-track summary
    print(f"\n\n{'='*70}\n  CROSS-TRACK CATEGORY SUMMARY\n{'='*70}")
    for track_name, res in all_results.items():
        cat_totals = Counter()
        for (layer, key, cat), cnt in res["bucket_counts"].items():
            cat_totals[cat] += cnt
        total = res["total"]
        print(f"\n  {track_name} (n={total}):")
        for cat in "ABCD":
            n = cat_totals.get(cat, 0)
            pct = n / total * 100 if total else 0
            print(f"    Cat {cat} {CAT_LABELS[cat]:55s}: {n:4d}  ({pct:5.1f}%)")
        if res["unmatched"]:
            pct = res["unmatched"] / total * 100
            print(f"    UNMATCHED                                                  : "
                  f"{res['unmatched']:4d}  ({pct:5.1f}%)")

    # Verbatim samples per bucket (top buckets only, across all tracks)
    print(f"\n\n{'='*70}\n  VERBATIM SAMPLES (3 per bucket, per track)\n{'='*70}")
    all_buckets = Counter()
    for res in all_results.values():
        all_buckets.update(res["bucket_counts"])
    for (layer, key, cat), _ in all_buckets.most_common(10):
        print(f"\n  --- [{cat}] {layer} / {key} ---")
        for track_name, res in all_results.items():
            samples = res["bucket_samples"].get((layer, key, cat), [])
            if not samples:
                continue
            print(f"    {track_name}:")
            for s in random.sample(samples, min(3, len(samples))):
                print(f"      • [{s['claim_type']}] {s['claim_text'][:140]}")


if __name__ == "__main__":
    main()

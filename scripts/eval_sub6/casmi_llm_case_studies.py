"""Phase 6.7 — extract 5 LLM-reranker case studies for paper.

Categories sought (1 each by default, but adjustable via --per-category):
  - llm_right_weighted_wrong  : LLM picks correct, weighted misses (LLM saves)
  - llm_right_weighted_wrong  : second example of the same direction
  - llm_wrong_weighted_right  : weighted picks correct, LLM misses (LLM regresses)
  - both_right                : LLM + weighted both pick correct (LLM justification confirms)
  - both_wrong                : neither picks correct, but LLM justification readable

Picks deterministically by spectrum_id sort within each category.

Writes data/paper_figures/phase6_7_llm_case_studies.json (one record per case,
containing spectrum_id / formula / GT SMILES / both predictions / LLM justification
+ peak_claims / confidence). Same schema as Phase 6.4 Layer F case studies.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def _load(path: Path) -> dict[str, dict]:
    return {json.loads(l)["spectrum_id"]: json.loads(l) for l in path.open()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path("data/eval/casmi"))
    ap.add_argument("--out", type=Path, default=Path("data/paper_figures/phase6_7_llm_case_studies.json"))
    args = ap.parse_args()

    w = _load(args.root / "2022_conditional" / "casmi_identifications.jsonl")
    l = _load(args.root / "2022_llm_reranker" / "casmi_identifications.jsonl")
    sids = sorted(set(w) & set(l))

    buckets: dict[str, list] = defaultdict(list)
    for s in sids:
        wr = w[s]; lr = l[s]
        wc = bool(wr.get("correct_top1"))
        lc = bool(lr.get("correct_top1"))
        if lc and not wc:
            buckets["llm_right_weighted_wrong"].append(s)
        elif wc and not lc:
            buckets["llm_wrong_weighted_right"].append(s)
        elif wc and lc:
            buckets["both_right"].append(s)
        else:
            buckets["both_wrong"].append(s)

    # Build 5 selections — 2 LLM-saves, 1 LLM-regress, 1 both-right, 1 both-wrong.
    selection_plan = [
        ("llm_right_weighted_wrong", 2),
        ("llm_wrong_weighted_right", 1),
        ("both_right", 1),
        ("both_wrong", 1),
    ]
    cases = []
    for cat, k in selection_plan:
        for sid in buckets[cat][:k]:
            wr = w[sid]; lr = l[sid]
            llm = lr.get("llm_rerank") or {}
            cases.append({
                "category": cat,
                "spectrum_id": sid,
                "formula": wr.get("casmi_formula"),
                "gt_smiles": wr.get("gt_smiles"),
                "gt_inchikey_first_block": wr.get("gt_inchikey_first_block"),
                "weighted_predicted_smiles": wr.get("predicted_smiles"),
                "weighted_predicted_ik14":   wr.get("predicted_inchikey_first_block"),
                "weighted_correct":          wr.get("correct_top1"),
                "llm_predicted_smiles":      lr.get("predicted_smiles"),
                "llm_predicted_ik14":        lr.get("predicted_inchikey_first_block"),
                "llm_correct":               lr.get("correct_top1"),
                "llm_confidence":            llm.get("confidence"),
                "llm_narrative":             llm.get("narrative"),
                "llm_peak_claims":           llm.get("peak_claims") or [],
                "llm_fallback_used":         llm.get("fallback_used"),
            })

    print(f"Bucket sizes:")
    for cat in ["llm_right_weighted_wrong", "llm_wrong_weighted_right", "both_right", "both_wrong"]:
        print(f"  {cat:<28} n={len(buckets[cat])}")
    print(f"\nSelected {len(cases)} case studies.")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(cases, indent=2, ensure_ascii=False))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

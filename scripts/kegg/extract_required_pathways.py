"""Extract KEGG pathway IDs + upstream/downstream compound pairs needed
for the verifier KEGG-hierarchy track.

Two outputs land side-by-side under ``data/kegg/``:

  required_pathway_ids.txt  — one ``hsa<NNNNN>`` per line. Covers:
    * every task's ``ground_truth_pathway.external_id`` (when source = kegg)
    * every ``ramp_enrichment_result.top_pathways[:3]`` external_id (when
      source = kegg, normalising ``hsa<NNNNN>``/``map<NNNNN>`` forms)
    * the full **mammalian metabolism core**: KEGG hsa pathway maps in the
      metabolism range ``hsa001xx`` … ``hsa011xx`` (≈ 100-150 maps),
      because Layer 6d's compound-level BFS needs the union reaction
      graph to be comprehensive enough that arbitrary compound pairs
      (e.g. "Methionine is upstream of homocysteine") have a chance of
      both endpoints appearing somewhere in the graph.

  required_compound_pairs.jsonl — one JSON per upstream/downstream claim
    found in the v2 verdicts files. Each line carries the claim text,
    the heuristic-extracted (subject, object) compound pair, the source
    track + task_id for traceability, and a resolution flag indicating
    whether both endpoints map to a KEGG compound ID via the curated
    pool (no live KEGG queries — strict offline). Pre-population audit
    for D5; the live Layer 6d will redo this extraction on its own
    claim text but reading this file is the ground-truth check.

The metabolism map range below comes from KEGG's published category
list (``br08901``); we hard-code it here rather than fetching live so
the script is offline-reproducible. Any genuine map outside the range
is still pulled in via the per-task collection above.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# Mammalian metabolism map ranges per KEGG br08901 categorisation as of
# 2026-05-01 snapshot. Each entry is (lo, hi) inclusive, hsa-prefixed.
# Together these cover:
#   001xx  carbohydrate metabolism (glycolysis, TCA, PPP, ...)
#   002xx  energy metabolism (oxidative phos, photosynthesis-irrelevant)
#   003xx  lipid metabolism (FA biosynthesis/degradation, cholesterol, ...)
#   004xx  nucleotide metabolism (purine, pyrimidine)
#   005xx  amino acid metabolism (the main 20 + cluster pathways)
#   006xx  metabolism of other amino acids (glutathione, taurine, ...)
#   007xx  glycan biosynthesis & metabolism
#   008xx  metabolism of cofactors & vitamins
#   009xx  metabolism of terpenoids & polyketides (mostly absent in mammals)
#   010xx  biosynthesis of secondary metabolites
#   011xx  xenobiotics biodegradation & metabolism (CYP450 etc.)
_METABOLISM_RANGES: list[tuple[int, int]] = [
    (10, 199),     # 00010 .. 00199 — carbohydrate, energy
    (200, 299),
    (300, 399),
    (400, 499),
    (500, 599),    # amino acid metabolism (most relevant for our benchmark)
    (600, 699),    # other amino acids — incl. glutathione (00480 falls in 4xx already)
    (700, 799),    # glycan
    (800, 899),    # cofactors / vitamins
    (900, 999),    # terpenoids
    (1000, 1099),  # secondary metabolites
    (1100, 1199),  # xenobiotics + global metabolism (e.g. 01100 metabolic pathways)
]

# Hard-coded KEGG metabolism pathway numbers (from KEGG br08901 hsa list,
# 2026-05-01 snapshot). 152 maps. Hard-coded so the script is offline.
_KEGG_METABOLISM_NUMBERS: list[int] = [
    # 00010-00199 carbohydrate / energy
    10, 20, 30, 40, 51, 52, 53, 61, 62, 71, 72, 100,
    120, 121, 130, 140, 190, 195, 196,
    # 00200-00299 energy
    220, 230, 232, 240, 250, 253, 260, 261, 270, 280, 281, 290,
    # 00300-00399 amino acid (overlap with 005xx)
    300, 310, 330, 332, 340, 350, 360, 361, 362, 363, 364, 365,
    380,
    # 00400-00499 other amino / nucleotide
    400, 401, 402, 403, 404, 405, 410, 430, 440, 450, 460, 470, 471, 472, 473,
    480, 511, 512, 513, 514, 515, 520, 521, 522, 523, 524, 525,
    # 00500-00599 lipid (overlap)
    531, 532, 533, 534, 540, 541, 542, 543, 550, 561, 562, 563, 564, 565, 571,
    572, 590, 591, 592, 600, 601, 603, 604,
    # 00600-00699 cofactor / xenobiotic
    620, 630, 633, 640, 642, 643, 650, 670, 680, 710, 720, 730, 740, 750,
    760, 770, 780, 785, 790, 791, 830, 860, 900, 910, 920, 930,
    940, 941, 942, 943, 944, 945, 950, 960, 965, 966, 970, 980, 981,
    982, 983, 984, 996, 998, 999, 1040, 1100, 1110, 1200, 1210, 1212, 1230, 1240,
    1250, 1501, 1502, 1503, 1521, 1522, 1523, 1524, 1100,
]
_KEGG_METABOLISM_NUMBERS = sorted(set(_KEGG_METABOLISM_NUMBERS))


from tools.kegg.claim_extraction import (  # noqa: E402
    _RELATIONSHIP_KEYWORDS,
    extract_compound_pair as _extract_compound_pair_impl,
)


def _normalise_kegg_id(ext_id: str | None) -> str | None:
    """Convert any of map00270 / hsa00270 / 00270 → hsa00270.

    Returns None when the input doesn't look like a KEGG map ID.
    """
    if not ext_id:
        return None
    s = str(ext_id).strip().lower()
    m = re.match(r"^(?:map|hsa|ko|path:hsa|path:map)?(\d{4,5})$", s)
    if not m:
        return None
    n = int(m.group(1))
    if n <= 0:
        return None
    return f"hsa{n:05d}"


def _collect_kegg_ids_from_tasks(task_paths: list[Path]) -> tuple[set[str], dict]:
    """Per-task KEGG IDs (GT + top3) plus a stat summary."""
    ids: set[str] = set()
    n_tasks = 0
    n_gt_kegg = 0
    n_gt_other = 0
    src_counter: dict[str, int] = defaultdict(int)

    for p in task_paths:
        with p.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                t = json.loads(line)
                n_tasks += 1
                gt = t.get("ground_truth_pathway") or {}
                if (gt.get("pathway_source") or "").lower() == "kegg":
                    kid = _normalise_kegg_id(gt.get("external_id"))
                    if kid:
                        ids.add(kid)
                        n_gt_kegg += 1
                    else:
                        n_gt_other += 1
                else:
                    n_gt_other += 1
                top = (t.get("ramp_enrichment_result") or {}).get("top_pathways") or []
                for entry in top[:3]:
                    src = (entry.get("pathway_source") or "").lower()
                    src_counter[src or "?"] += 1
                    if src != "kegg":
                        continue
                    kid = _normalise_kegg_id(entry.get("pathway_external_id"))
                    if kid:
                        ids.add(kid)
    return ids, {
        "n_tasks": n_tasks,
        "n_gt_kegg": n_gt_kegg,
        "n_gt_non_kegg": n_gt_other,
        "top3_source_counter": dict(src_counter),
    }


# ------------ compound-pair extraction -------------------------------------


def _extract_compound_pair(claim_text: str) -> tuple[str | None, str | None]:
    """Thin wrapper preserving the script's original symbol name; the
    real implementation lives in ``tools.kegg.claim_extraction``.
    """
    return _extract_compound_pair_impl(claim_text)


def _collect_compound_pairs(verdict_paths: list[Path]) -> list[dict]:
    """Pull every pathway_relationship claim (any verdict) whose evidence
    or claim_text mentions upstream/downstream/feeds, and emit (claim,
    pair) rows.
    """
    out: list[dict] = []
    for p in verdict_paths:
        if not p.exists():
            continue
        track = p.stem.replace("_verdicts", "").replace("_v2", "").replace("_v3", "")
        with p.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                tid = rec.get("task_id")
                for c in rec.get("claims") or []:
                    if c.get("claim_type") != "pathway_relationship":
                        continue
                    text = c.get("claim_text") or ""
                    text_lc = text.lower()
                    if not any(
                        k in text_lc for k in ("upstream", "downstream", "feeds into", "feed into")
                    ):
                        continue
                    a, b = _extract_compound_pair(text)
                    out.append({
                        "track": track,
                        "task_id": tid,
                        "claim_text": text,
                        "subject_phrase": a,
                        "object_phrase": b,
                    })
    return out


# ------------ entry --------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--tasks",
        nargs="+",
        default=[
            "data/benchmark/sub6/sub6b_mammalian_tasks.jsonl",
            "data/benchmark/sub6/sub6a_e2e_tasks.jsonl",
        ],
        help="Sub-6 task JSONL files",
    )
    p.add_argument(
        "--verdicts",
        nargs="+",
        default=[
            "data/eval/sub6/sub6b_verdicts_v2.jsonl",
            "data/eval/sub6/sub6a_perfect_id_verdicts_v2.jsonl",
            "data/eval/sub6/sub6a_real_id_verdicts.jsonl",
        ],
        help="Verifier verdicts JSONL — used to extract compound pairs",
    )
    p.add_argument("--output-pathways", default="data/kegg/required_pathway_ids.txt")
    p.add_argument("--output-pairs", default="data/kegg/required_compound_pairs.jsonl")
    p.add_argument(
        "--include-metabolism-core",
        action="store_true",
        default=True,
        help="Always include the mammalian metabolism core hsa map list (default on)",
    )
    p.add_argument(
        "--no-metabolism-core",
        action="store_false",
        dest="include_metabolism_core",
        help="Disable the metabolism core; emit only per-task IDs",
    )
    args = p.parse_args(argv)

    task_paths = [Path(p) for p in args.tasks]
    verdict_paths = [Path(p) for p in args.verdicts]

    # 1. KEGG pathway IDs.
    per_task_ids, stats = _collect_kegg_ids_from_tasks(task_paths)
    metab_ids: set[str] = set()
    if args.include_metabolism_core:
        for n in _KEGG_METABOLISM_NUMBERS:
            metab_ids.add(f"hsa{n:05d}")

    union = sorted(per_task_ids | metab_ids)

    out_path = Path(args.output_pathways)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        for kid in union:
            f.write(kid + "\n")

    print(f"=== KEGG pathway list ({out_path}) ===")
    print(f"  per-task IDs:        {len(per_task_ids)}  ({sorted(per_task_ids)[:6]}...)")
    print(f"  metabolism core IDs: {len(metab_ids)}")
    print(f"  union total:         {len(union)}")
    print(f"  task stats:          {stats}")
    print()

    # 2. Compound pairs.
    pairs = _collect_compound_pairs(verdict_paths)
    pp = Path(args.output_pairs)
    pp.parent.mkdir(parents=True, exist_ok=True)
    with pp.open("w") as f:
        for r in pairs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    n_resolved = sum(1 for r in pairs if r["subject_phrase"] and r["object_phrase"])
    print(f"=== compound pairs ({pp}) ===")
    print(f"  total upstream/downstream claims: {len(pairs)}")
    print(f"  pairs with both endpoints extracted: {n_resolved} ({n_resolved/len(pairs)*100:.1f}%)" if pairs else "  no claims found")

    # Print a few samples.
    print("\nFirst 5 samples:")
    for r in pairs[:5]:
        print(f"  [{r['track']}] {r['subject_phrase']!r} → {r['object_phrase']!r}")
        print(f"    {r['claim_text'][:130]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

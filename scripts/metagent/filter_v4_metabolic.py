"""
filter_v4_metabolic.py
======================
Filter ill-posed tasks from metagent_bench_easy_v4_filtered.jsonl.

Rules applied only to hmdb_ramp stratum (task_id contains "hmdb_ramp").
Other strata (human1, recon22, sub6) pass through unchanged.

Filtering logic:
  RaMP:kegg        -> KEEP ALL
  RaMP:wikipathways -> REMOVE if matches ill-posed patterns
  RaMP:reactome    -> REMOVE if matches ill-posed patterns; KEEP if classic metabolic keyword

Outputs:
  metagent_bench_easy_v4_metabolic.jsonl           - clean subset
  metagent_bench_easy_v4_metabolic_filter_log.json - detailed filter log
"""

import json
import re
import sys
from pathlib import Path

SRC = Path(
    "/home/weiwentao/workspace/llm_agent_metabolomics/metagent_v2"
    "/data/benchmark/metagent_bench_v2/metagent_bench_easy_v4_filtered.jsonl"
)
OUT_JSONL = SRC.parent / "metagent_bench_easy_v4_metabolic.jsonl"
OUT_LOG = SRC.parent / "metagent_bench_easy_v4_metabolic_filter_log.json"

# ── WikiPathways ill-posed patterns ──────────────────────────────────────────
WIKI_ILL_POSED_PATTERNS = [
    # chromosomal / CNV loci
    (re.compile(r"\bcopy number variation\b", re.I), "CNV pathway"),
    (re.compile(r"\bcnv\b", re.I), "CNV abbreviation"),
    (re.compile(r"\b\d+[pq]\d", re.I), "chromosomal locus pattern"),
    # neuropsychiatric
    (re.compile(r"\bautism\b", re.I), "autism"),
    (re.compile(r"\bADHD\b", re.I), "ADHD"),
    # drug / signaling
    (re.compile(r"\bACE inhibitor pathway\b", re.I), "ACE inhibitor pathway"),
    (re.compile(r"\b4-hydroxytamoxifen\b", re.I), "4-hydroxytamoxifen"),
    # p27 cell-cycle regulator
    (re.compile(r"\bp27\b"), "p27 regulator"),
]

# ── Reactome HIGH-PRIORITY ill-posed: checked BEFORE metabolic KEEP override ──
# These patterns override even "metabolism/biosynthesis/cycle" keywords
REACTOME_HIGH_PRIORITY_ILL_POSED = [
    # Drug ADME (drug name + ADME suffix, or ADME standalone)
    (re.compile(r"\bADME\b", re.I), "ADME (pharmacokinetics)"),
    # Specific drug names: these are pharmacology, not metabolic biochemistry
    (re.compile(
        r"\b(Abacavir|Imatinib|Gefitinib|Irinotecan|Tamoxifen|Warfarin|"
        r"Methotrexate|Thiopurine|Fluorouracil|Etoposide)\b", re.I
    ), "drug ADME/pharmacology"),
    # Neurotransmitter (catches "Neurotransmitter Release Cycle" which has "cycle")
    (re.compile(r"\bneurotransmitter\b", re.I), "neurotransmitter"),
    # ABO blood group (has "biosynthesis" but is glycoprotein antigen, not metabolic)
    (re.compile(r"\bABO blood group\b", re.I), "ABO blood group antigen"),
    # ALKBH alkylation DNA repair (not metabolic)
    (re.compile(r"ALKBH", re.I), "ALKBH alkylation repair"),
    (re.compile(r"\balkylation\b", re.I), "alkylation"),
    # Phototransduction (has "activation" → no metabolic keyword, but guard anyway)
    (re.compile(r"\bphototransduction\b", re.I), "phototransduction"),
    (re.compile(r"\bretinoid cycle\b", re.I), "retinoid cycle"),
]

# ── Reactome ill-posed patterns (checked AFTER metabolic KEEP override) ──────
REACTOME_ILL_POSED_PATTERNS = [
    # signaling pathway labels
    (re.compile(r"\bsignall?ing\b", re.I), "signaling"),
    (re.compile(r"\breceptor\b", re.I), "receptor"),
    (re.compile(r"\bkinase\b", re.I), "kinase"),
    # gene expression / transcription
    (re.compile(r"\bgene expression\b", re.I), "gene expression"),
    (re.compile(r"\btranscription\b", re.I), "transcription"),
    # synapse / neurotransmitter (covered in HIGH_PRIORITY too, belt-and-suspenders)
    (re.compile(r"\bsynaptic\b|\bsynapse\b", re.I), "synaptic"),
    # NMDA receptor
    (re.compile(r"\bNMDA\b", re.I), "NMDA receptor"),
    # ABC transport (after metabolic KEEP, so "ABC transporters in lipid homeostasis" still KEEP)
    (re.compile(r"\bABC.*(transporter|transport|mediated)\b", re.I), "ABC transporter"),
    # SLC transport
    (re.compile(r"\bSLC\b", re.I), "SLC transport"),
    # FGFR oncogenic signaling / point mutants
    (re.compile(r"FGFR", re.I), "FGFR signaling"),
    (re.compile(r"\bpoint mutant\b", re.I), "point mutant"),
    # PKN kinase → transcription
    (re.compile(r"PKN\d", re.I), "PKN kinase"),
    # SREBF / SREBP → gene expression
    (re.compile(r"\bSREBF\b|\bSREBP\b", re.I), "SREBF/SREBP gene expression"),
    # cytokines (plural or singular)
    (re.compile(r"\bcytokines?\b", re.I), "cytokine/cytokines"),
    # ADORA receptor (matches ADORA2B etc.)
    (re.compile(r"ADORA", re.I), "ADORA receptor"),
    # ADP signalling (purinergic)
    (re.compile(r"\bADP signall?ing\b", re.I), "ADP signaling"),
    # Acetylation as standalone PTM (not acetyl-CoA / acetylation in lipid context)
    (re.compile(r"^Acetylation$", re.I), "acetylation PTM (exact name)"),
    # Acetylcholine (neurotransmitter)
    (re.compile(r"\bAcetylcholine\b", re.I), "acetylcholine neurotransmitter"),
]

# ── Reactome KEEP override: classic metabolic keywords ────────────────────────
# Applied ONLY if HIGH_PRIORITY ill-posed did NOT match
METABOLIC_KEEP_PATTERNS = [
    re.compile(r"\bmetabolism\b", re.I),
    re.compile(r"\bbiosynthesis\b", re.I),
    re.compile(r"\bdegradation\b", re.I),
    re.compile(r"\bcycle\b", re.I),
    re.compile(r"\boxidation\b", re.I),
    re.compile(r"\bsynthesis\b", re.I),
    re.compile(r"\bcatabolism\b", re.I),
    re.compile(r"\bfatty acid\b", re.I),
    re.compile(r"\blipid\b", re.I),
    re.compile(r"\bglycolysis\b", re.I),
    re.compile(r"\bgluconeogenesis\b", re.I),
    re.compile(r"\bTCA\b", re.I),
    re.compile(r"\bKrebs\b", re.I),
    re.compile(r"\bamino acid\b", re.I),
    re.compile(r"\bnucleotide\b", re.I),
    re.compile(r"\bglucose\b", re.I),
    re.compile(r"\bpyruvate\b", re.I),
    re.compile(r"\bglycerol\b", re.I),
    re.compile(r"\bphospholipid\b", re.I),
    re.compile(r"\bsteroi\b", re.I),    # steroid / steroids / steroidogenesis
    re.compile(r"\bketone\b", re.I),
    re.compile(r"\bbeta-oxidation\b|\bβ.oxidation\b", re.I),
    re.compile(r"\bacyl chain remodel\b", re.I),
    re.compile(r"\bphosphoribose\b|\bphosphoribosyl\b", re.I),
]


def is_metabolic(name: str) -> bool:
    return any(p.search(name) for p in METABOLIC_KEEP_PATTERNS)


def check_wiki(name: str) -> tuple[bool, str]:
    """Return (should_remove, reason). True = remove."""
    for pattern, label in WIKI_ILL_POSED_PATTERNS:
        if pattern.search(name):
            return True, label
    return False, ""


def check_reactome(name: str) -> tuple[bool, str]:
    """Return (should_remove, reason). True = remove.

    Priority order:
    1. HIGH_PRIORITY ill-posed: removes even if metabolic keywords present
       (drug ADME, neurotransmitter release, ABO blood group, ALKBH repair, ...)
    2. Metabolic KEEP override: classic biochemistry keywords → KEEP
    3. Normal ill-posed: signaling / receptor / kinase / gene expression / ...
    """
    # 1. High-priority ill-posed (beat metabolic KEEP)
    for pattern, label in REACTOME_HIGH_PRIORITY_ILL_POSED:
        if pattern.search(name):
            return True, label
    # 2. Metabolic KEEP override
    if is_metabolic(name):
        return False, ""
    # 3. Normal ill-posed patterns
    for pattern, label in REACTOME_ILL_POSED_PATTERNS:
        if pattern.search(name):
            return True, label
    return False, ""


def classify_task(task: dict) -> tuple[str, str, bool, str]:
    """Returns (stratum, ontology, should_remove, reason)."""
    task_id = task["task_id"]
    gt = task["ground_truth"]["perturbed_pathway"]
    ontology = gt["ontology"]
    name = gt["name"]

    if "hmdb_ramp" not in task_id:
        return "other", ontology, False, "non-hmdb_ramp stratum"

    if ontology == "RaMP:kegg":
        return "hmdb_ramp", ontology, False, "KEGG always kept"

    if ontology == "RaMP:wikipathways":
        remove, reason = check_wiki(name)
        return "hmdb_ramp", ontology, remove, reason

    if ontology == "RaMP:reactome":
        remove, reason = check_reactome(name)
        return "hmdb_ramp", ontology, remove, reason

    # smpdb / lipidmaps / other
    return "hmdb_ramp", ontology, False, f"unhandled ontology kept: {ontology}"


def main():
    tasks = [json.loads(l) for l in SRC.read_text().splitlines() if l.strip()]
    print(f"Total tasks loaded: {len(tasks)}")

    kept = []
    removed = []
    log_entries = []

    # track by ontology
    stats = {
        "other_strata_kept": 0,
        "kegg_kept": 0,
        "wiki_kept": 0,
        "wiki_removed": 0,
        "reactome_kept": 0,
        "reactome_removed": 0,
        "other_onto_kept": 0,
    }

    for task in tasks:
        stratum, ontology, should_remove, reason = classify_task(task)
        gt = task["ground_truth"]["perturbed_pathway"]
        name = gt["name"]
        entry = {
            "task_id": task["task_id"],
            "stratum": stratum,
            "ontology": ontology,
            "gt_name": name,
            "decision": "REMOVE" if should_remove else "KEEP",
            "reason": reason,
        }
        log_entries.append(entry)

        if should_remove:
            removed.append(task)
            if ontology == "RaMP:wikipathways":
                stats["wiki_removed"] += 1
            elif ontology == "RaMP:reactome":
                stats["reactome_removed"] += 1
        else:
            kept.append(task)
            if stratum == "other":
                stats["other_strata_kept"] += 1
            elif ontology == "RaMP:kegg":
                stats["kegg_kept"] += 1
            elif ontology == "RaMP:wikipathways":
                stats["wiki_kept"] += 1
            elif ontology == "RaMP:reactome":
                stats["reactome_kept"] += 1
            else:
                stats["other_onto_kept"] += 1

    # ── Print removed tasks ───────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("REMOVED TASKS (ill-posed)")
    print("=" * 70)
    removed_entries = [e for e in log_entries if e["decision"] == "REMOVE"]
    for e in sorted(removed_entries, key=lambda x: (x["ontology"], x["gt_name"])):
        print(f"  [{e['ontology']}] {e['task_id']}")
        print(f"      GT: {e['gt_name']}")
        print(f"      Reason: {e['reason']}")

    # ── Print kept hmdb_ramp tasks ─────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("KEPT hmdb_ramp TASKS")
    print("=" * 70)
    kept_entries = [e for e in log_entries if e["decision"] == "KEEP" and e["stratum"] == "hmdb_ramp"]
    for e in sorted(kept_entries, key=lambda x: (x["ontology"], x["gt_name"])):
        print(f"  [{e['ontology']}] {e['task_id']}")
        print(f"      GT: {e['gt_name']}")

    # ── Statistics ────────────────────────────────────────────────────────────
    total_hmdb = sum(1 for e in log_entries if e["stratum"] == "hmdb_ramp")
    total_hmdb_kept = sum(1 for e in log_entries if e["stratum"] == "hmdb_ramp" and e["decision"] == "KEEP")
    total_hmdb_removed = sum(1 for e in log_entries if e["stratum"] == "hmdb_ramp" and e["decision"] == "REMOVE")

    print("\n" + "=" * 70)
    print("STATISTICS")
    print("=" * 70)
    print(f"Total input tasks:        {len(tasks)}")
    print(f"Non-hmdb_ramp (kept):     {stats['other_strata_kept']}")
    print(f"hmdb_ramp total:          {total_hmdb}")
    print(f"  KEGG kept:              {stats['kegg_kept']}")
    print(f"  WikiPathways kept:      {stats['wiki_kept']}")
    print(f"  WikiPathways removed:   {stats['wiki_removed']}")
    print(f"  Reactome kept:          {stats['reactome_kept']}")
    print(f"  Reactome removed:       {stats['reactome_removed']}")
    print(f"  Other ontology kept:    {stats['other_onto_kept']}")
    print(f"hmdb_ramp net kept:       {total_hmdb_kept}")
    print(f"hmdb_ramp net removed:    {total_hmdb_removed}")
    print(f"Total output tasks:       {len(kept)}")

    # ── Write outputs ─────────────────────────────────────────────────────────
    with open(OUT_JSONL, "w") as f:
        for task in kept:
            f.write(json.dumps(task) + "\n")
    print(f"\nOutput JSONL: {OUT_JSONL}")
    print(f"Output rows:  {len(kept)}")

    log_payload = {
        "stats": stats,
        "total_input": len(tasks),
        "total_output": len(kept),
        "total_removed": len(removed),
        "hmdb_ramp_total": total_hmdb,
        "hmdb_ramp_kept": total_hmdb_kept,
        "hmdb_ramp_removed": total_hmdb_removed,
        "entries": log_entries,
    }
    with open(OUT_LOG, "w") as f:
        json.dump(log_payload, f, indent=2)
    print(f"Filter log:   {OUT_LOG}")


if __name__ == "__main__":
    main()

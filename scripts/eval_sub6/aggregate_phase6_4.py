"""Phase 6.4 aggregator — Layer F activation comparison.

Compares two extractor paths on the same Config C narrative file:
  - Opus-4-7 LLM extractor (Phase 6.3 D7 result, decomposes mechanistic phrases)
  - rule-based sentence extractor (Phase 6.4, preserves compound phrases)

Writes:
  data/paper_figures/phase6_4_layerf_activation.csv

Plus a 5-case-study JSON for the paper's Layer F section.
"""
from __future__ import annotations
import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path("/home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5")
CONFIG_C_DIR = ROOT / "data/eval/sub6/v2_phase6_3/C_msclip_llm"
OUT = ROOT / "data/paper_figures"
OUT.mkdir(parents=True, exist_ok=True)


def _summarize(verdict_path: Path, label: str) -> dict:
    if not verdict_path.exists():
        return {"extractor": label, "missing": True}
    n_tasks = errors = 0
    total = Counter()
    by_type = Counter()
    peak_v = Counter()
    for line in verdict_path.open():
        rec = json.loads(line)
        n_tasks += 1
        if rec.get("error"):
            errors += 1
        for c in rec.get("claims", []):
            ct = c.get("claim_type", "")
            v = c.get("verdict")
            total[v] += 1
            by_type[ct] += 1
            if "peak_mech" in (ct or "").lower():
                peak_v[v] += 1
    return {
        "extractor": label,
        "n_tasks": n_tasks,
        "n_task_errors": errors,
        "total_claims": sum(by_type.values()),
        "grounded_claim": by_type.get("grounded_claim", 0),
        "factual_roundtrip_claim": by_type.get("factual_roundtrip_claim", 0),
        "consistency_claim": by_type.get("consistency_claim", 0),
        "biological_claim": by_type.get("biological_claim", 0),
        "pathway_relationship": by_type.get("pathway_relationship", 0),
        "peak_mechanistic_claim": by_type.get("peak_mechanistic_claim", 0),
        "layer_f_dispatched": sum(peak_v.values()),
        "layer_f_supported": peak_v.get("supported", 0),
        "layer_f_contradicted": peak_v.get("contradicted", 0),
        "layer_f_unsupported": peak_v.get("unsupported", 0),
        "layer_f_unverif": peak_v.get("unverifiable_v0", 0),
    }


def main() -> int:
    rows = [
        _summarize(CONFIG_C_DIR / "verdicts_v9_phaseC.jsonl", "opus47 (Phase 6.3 D7)"),
        _summarize(CONFIG_C_DIR / "verdicts_v9_phaseC_rulebased.jsonl", "rule-based (Phase 6.4)"),
    ]
    out = OUT / "phase6_4_layerf_activation.csv"
    fieldnames = list(rows[0].keys()) if rows else []
    # ensure both rows have same fields
    union = set()
    for r in rows: union.update(r.keys())
    fieldnames = [k for k in union if not k == "missing"] or fieldnames
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {out}")
    for r in rows:
        print(f"  {r.get('extractor')}: claims={r.get('total_claims')}, peak_mech={r.get('peak_mechanistic_claim')}, layer_f={{sup:{r.get('layer_f_supported')}, contra:{r.get('layer_f_contradicted')}, unsup:{r.get('layer_f_unsupported')}, unverif:{r.get('layer_f_unverif')}}}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

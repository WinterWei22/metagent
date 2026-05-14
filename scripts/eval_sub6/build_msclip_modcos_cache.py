"""Phase 6.5 — re-run library_search on Sub-6A real-id v2 spectra (no SIRIUS/
CFM/LLM) to recover separate modcos and msclip scores per candidate.

Calls tools.library_search.library_search() with `--libraries gnps,inhouse`
+ mass_tolerance_ppm=10, then parses the Candidate.explain string regex
to split fused score into (modcos, msclip_rescaled).

Output:
  data/cache/library_search_dual_score.jsonl

Pure read — no LLM, no SIRIUS, no CFM. ms-clip GPU + GNPS loaded once.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path("/home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5")
sys.path.insert(0, str(ROOT))

from evaluation.sub6.identification import (
    _candidate_score_components,
    task_exclusion_set,
    task_spectrum_to_schema,
)
from schemas import LibrarySearchRequest

OUT = ROOT / "data/cache/library_search_dual_score.jsonl"
OUT.parent.mkdir(parents=True, exist_ok=True)


def main() -> int:
    from tools.library_search import library_search
    tasks_path = ROOT / "data/benchmark/sub6/sub6a_e2e_tasks_v2.jsonl"

    # Resume: read previous output's spectrum_ids.
    done_sids = set()
    if OUT.exists():
        for line in OUT.open():
            try:
                rec = json.loads(line)
                done_sids.add(rec.get("spectrum_id"))
            except Exception:
                pass
    print(f"already cached: {len(done_sids)} spectra")

    n_proc = 0
    t0 = time.time()
    with OUT.open("a") as fout:
        for line in tasks_path.open():
            task = json.loads(line)
            spectra = task.get("differential_spectra") or []
            exclusion = task_exclusion_set(task)
            for sp in spectra:
                sid = str(sp.get("spectrum_id", "?"))
                if sid in done_sids:
                    continue
                try:
                    spec = task_spectrum_to_schema(sp)
                except Exception as exc:
                    fout.write(json.dumps({
                        "spectrum_id": sid, "task_id": task["task_id"],
                        "error": f"spec_conversion: {exc}",
                    }) + "\n")
                    continue
                req = LibrarySearchRequest(
                    spectrum=spec, candidate_pool=None, top_k=20, min_score=0.0,
                    libraries=["gnps", "inhouse"],
                    mass_tolerance_ppm=10.0,
                    excluded_source_ids=sorted(exclusion) or None,
                )
                try:
                    resp = library_search(req)
                except Exception as exc:
                    fout.write(json.dumps({
                        "spectrum_id": sid, "task_id": task["task_id"],
                        "error": f"library_search: {type(exc).__name__}: {exc}",
                    }) + "\n")
                    continue
                cands_out = []
                for c in (resp.candidates or [])[:10]:  # save top-10 per spec
                    sid_c = getattr(c, "source_id", None)
                    if sid_c is not None and sid_c in exclusion:
                        continue
                    mc, ms = _candidate_score_components(c)
                    cands_out.append({
                        "smiles": getattr(c, "smiles", None),
                        "name": getattr(c, "name", None),
                        "source_id": sid_c,
                        "fused_score": float(getattr(c, "score", 0.0) or 0.0),
                        "modcos": mc,
                        "msclip_rescaled": ms,
                        "explain": getattr(c, "explain", "")[:200],
                    })
                fout.write(json.dumps({
                    "spectrum_id": sid,
                    "task_id": task["task_id"],
                    "gt_inchikey_first_block": sp.get("inchikey_first_block"),
                    "n_candidates": len(cands_out),
                    "candidates": cands_out,
                }) + "\n")
                fout.flush()
                n_proc += 1
                if n_proc % 25 == 0:
                    elapsed = time.time() - t0
                    print(f"  [{n_proc}] elapsed={elapsed:.0f}s  ~{elapsed/n_proc:.1f}s/spec")
    print(f"\ndone: processed {n_proc} new spectra in {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

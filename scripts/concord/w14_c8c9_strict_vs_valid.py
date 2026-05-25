"""W14 §0 — re-classify W11 C8 + C9 (148 claims) into strict_noise vs valid_content.

W12 lesson (memory `feedback_uv_sprint_must_reclassify_first`): every UV
optimisation sprint must run a strict-vs-fuzzy re-classification on the
target W11 bucket BEFORE setting Hard Gate target. W14 inherits this
discipline.

Target buckets:

  strict_noise   — LLM filler / template / self-reference / pasted prompt
                   fragment / "see above" / "future work" / etc. W14
                   noise-pattern detection (regex in narrative + prompt
                   banned-phrase list) CAN eliminate these.

  valid_content  — W11 C9 mis-classification: actually carries information
                   the verifier could in principle judge (probably belongs
                   in C1 / C3 / C5 bucket). W14 should NOT touch these.

Output:
  data/concord/w14_uv_reclassify/c8c9_strict_vs_valid.jsonl
  data/concord/w14_uv_reclassify/ceiling_summary.json

Cost: ~$0.30 at MiniMax-M2.7. ~3 batches of 50.

Run:
    PYTHONPATH=. METAGENT_LLM_LOG_PATH=logs/concord/w14_c8c9_reclassify.jsonl \\
        python scripts/concord/w14_c8c9_strict_vs_valid.py
"""
from __future__ import annotations

import json
import re
import time
from collections import Counter
from pathlib import Path

from common.llm_client import chat


_INPUT = Path("data/concord/w11_uv_diagnosis/uv_classified.jsonl")
_OUTPUT_DIR = Path("data/concord/w14_uv_reclassify")
_BATCH = 50


_SYSTEM_PROMPT = """You are sorting biology research claims into one of two buckets.

These claims were tagged as C8 (empty_or_noise) or C9 (other) by an earlier
W11 classifier. Your job is to decide whether each claim is "true noise" that
should be DROPPED by the verifier, OR "valid content" that was mis-classified
and actually carries information.

Pick exactly ONE bucket per claim:

strict_noise
    Filler, template boilerplate, self-reference, prompt fragment, or claims
    that carry zero biological information. Examples:
      - "以上是分析结果"  ("the above is the analysis result")
      - "总结如下"        ("in summary:")
      - "future work suggests further investigation"
      - "as mentioned above"
      - "see above"
      - "进一步研究需要..."  ("further research requires...")
      - pasted prompt fragments  ("As a metabolomics analyst, ...")
      - "...." or near-empty strings
      - "in conclusion" / "to summarise"
    These claims should be DROPPED by the verifier as noise, not judged.

valid_content
    Claim carries actual biological information (metabolite name, pathway,
    enzyme, evidence) even if it was mis-classified into the C8/C9 bucket
    by the earlier W11 classifier. Examples:
      - "Tyrosine appears in 3 of 5 pathway analyses"   (cross-method)
      - "L-arginine is the precursor of nitric oxide"   (biology mechanism)
      - "MUMM:steroid_metabolism ranks first"           (pathway with namespace)
      - any claim that names a metabolite, pathway, or biological process
    These claims should NOT be dropped — they belong in some other bucket
    (C1 / C3 / C5 / C7) and are out of scope for W14.

Return strict JSON only — no prose, no markdown fences. Format:
[{"claim_id": "...", "bucket": "strict_noise" | "valid_content"}, ...]
One entry per input claim, same order, same claim_id values."""


_JSON_FENCE = re.compile(r"```(?:json)?\s*(\[.*?\])\s*```", re.DOTALL)


def _parse_response(text: str) -> list[dict]:
    m = _JSON_FENCE.search(text)
    if m:
        text = m.group(1)
    text = text.strip().lstrip("`").rstrip("`")
    if text.startswith("json\n"):
        text = text[5:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"(\[[^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*\])", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
    return []


def main() -> int:
    if not _INPUT.exists():
        print(f"ERROR: {_INPUT} missing"); return 1

    c8c9: list[dict] = []
    with _INPUT.open() as f:
        for line in f:
            d = json.loads(line)
            if d.get("category") in ("C8", "C9"):
                c8c9.append(d)
    print(f"Loaded {len(c8c9)} W11 C8+C9 claims")

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    classified: list[dict] = []
    failed = 0
    n_batches = (len(c8c9) + _BATCH - 1) // _BATCH
    t0 = time.time()
    for bi in range(n_batches):
        batch = c8c9[bi * _BATCH:(bi + 1) * _BATCH]
        user_msg = "Classify these C8/C9 claims. Return JSON list.\n\n"
        for i, c in enumerate(batch, 1):
            user_msg += f"{i}. claim_id={c['claim_id']!r}, claim_text={c['claim_text'][:400]!r}\n"
        try:
            response = chat(
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                model="MiniMax-M2.7",
                temperature=0.0,
                trace_id=f"w14_c8c9_reclassify.batch_{bi:03d}",
                caller="w14_c8c9_reclassify",
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            print(f"  batch {bi+1}/{n_batches} ERROR: {exc}")
            failed += 1
            for c in batch:
                classified.append({**c, "bucket": "UNCLASSIFIED"})
            continue

        parsed = _parse_response(response)
        cid_map = {e.get("claim_id"): e.get("bucket")
                   for e in parsed if isinstance(e, dict)}
        for c in batch:
            classified.append({**c, "bucket": cid_map.get(c["claim_id"], "UNCLASSIFIED")})
        print(f"  batch {bi+1}/{n_batches} done  elapsed={time.time()-t0:.0f}s")

    out_jsonl = _OUTPUT_DIR / "c8c9_strict_vs_valid.jsonl"
    with out_jsonl.open("w") as f:
        for c in classified:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    dist = Counter(c["bucket"] for c in classified)
    n_strict = dist.get("strict_noise", 0)
    n_valid = dist.get("valid_content", 0)
    n_unc = dist.get("UNCLASSIFIED", 0)
    w11_uv_total = 1102
    ceiling_pp = round(100 * n_strict / w11_uv_total, 2)
    target_pp = round(ceiling_pp * 0.6, 2)

    summary = {
        "n_c8c9_total": len(c8c9),
        "n_strict_noise": n_strict,
        "n_valid_content": n_valid,
        "n_unclassified": n_unc,
        "failed_batches": failed,
        "n_batches": n_batches,
        "w11_uv_total": w11_uv_total,
        "strict_noise_ceiling_pp": ceiling_pp,
        "target_pp_at_0p6_ceiling": target_pp,
        "wall_seconds": round(time.time() - t0, 1),
    }
    (_OUTPUT_DIR / "ceiling_summary.json").write_text(json.dumps(summary, indent=2))

    print()
    print("=" * 60)
    print("Re-classification distribution")
    print("=" * 60)
    print(f"  strict_noise:    {n_strict:>3} / {len(c8c9)} ({100*n_strict/len(c8c9):.1f}%)")
    print(f"  valid_content:   {n_valid:>3} / {len(c8c9)} ({100*n_valid/len(c8c9):.1f}%)")
    print(f"  UNCLASSIFIED:    {n_unc:>3} / {len(c8c9)} ({100*n_unc/len(c8c9):.1f}%)")
    print()
    print(f"  W14.A noise-pattern ceiling on W11 baseline:")
    print(f"    {n_strict} strict_noise / 1102 total UV = {ceiling_pp} pp")
    print(f"  W14 spec target (ceiling × 0.6):")
    print(f"    {target_pp} pp")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

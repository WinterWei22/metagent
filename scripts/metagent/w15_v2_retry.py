"""W15 D2 v2 — full 901-claim retry with tightened DISAMBIGUATION RULE.

Initial v1 run (commit 40c58bb) hit HG-2 60 % (12/20 strict; 100 % axis-
level). Per user Option B decision (2026-05-26), retry the FULL 901
pool with the updated rubric (DISAMBIGUATION RULE added in the same
commit as this script) and write to v2 paths so v1 stays for comparison.

Output:
  data/metagent/w15_uv_attribution/attribution_raw_v2.jsonl
  data/metagent/w15_uv_attribution/attribution_v2.csv

Cost target: ~$0.5 (matching v1 since rubric token-count is similar).
Wall target: ~25 min (46 batches × 20 claims).
"""
from __future__ import annotations

import csv
import json
import time
from collections import Counter
from pathlib import Path

from scripts.metagent.w15_uv_attribution import (
    _SYSTEM_PROMPT_W15,
    _build_user_message,
    _parse_llm_json_list,
    _BATCH_SIZE,
)


_OUT_DIR = Path("data/metagent/w15_uv_attribution")


def main() -> int:
    from common.llm_client import chat

    pool_path = _OUT_DIR / "uv_claim_pool.jsonl"
    pool = [json.loads(l) for l in pool_path.open()]
    print(f"Loaded {len(pool)} UV claims for v2 retry")

    classified: list[dict] = []
    n_batches = (len(pool) + _BATCH_SIZE - 1) // _BATCH_SIZE
    failed_batches = 0
    t0 = time.time()

    for bi in range(n_batches):
        batch = pool[bi * _BATCH_SIZE:(bi + 1) * _BATCH_SIZE]
        # Positional remap so duplicate v1:cNNN tags across tasks within a
        # batch don't collapse on LLM output (root cause of v1 batch-10
        # UNCLASSIFIED leak).
        positional_input = []
        pos_map = {}
        for pos, c in enumerate(batch):
            pos_id = f"b{bi:02d}_p{pos:02d}"
            pos_map[pos_id] = c
            positional_input.append({**c, "claim_id": pos_id})

        user_msg = _build_user_message(positional_input)
        try:
            response = chat(
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT_W15},
                    {"role": "user", "content": user_msg},
                ],
                model="MiniMax-M2.7",
                temperature=0.0,
                trace_id=f"w15_uv_attribution_v2.batch_{bi:03d}",
                caller="w15_uv_attribution_v2",
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            print(f"  batch {bi+1}/{n_batches} ERROR: {exc}")
            failed_batches += 1
            for c in batch:
                classified.append({**c, "attribution": "UNCLASSIFIED",
                                   "w11_bucket": "UNCLASSIFIED",
                                   "rationale": f"batch_error: {exc!r}"})
            continue

        parsed = _parse_llm_json_list(response)
        cid_map = {e.get("claim_id"): e for e in parsed if isinstance(e, dict)}
        for pos_id, c in pos_map.items():
            row = cid_map.get(pos_id) or {}
            classified.append({
                **c,  # original claim_id preserved
                "attribution": str(row.get("attribution", "UNCLASSIFIED")),
                "w11_bucket": str(row.get("w11_bucket", "UNCLASSIFIED")),
                "rationale": str(row.get("rationale", "")),
            })

        if (bi + 1) % 5 == 0 or (bi + 1) == n_batches:
            print(f"  batch {bi+1}/{n_batches}  fail={failed_batches}  "
                  f"elapsed={time.time()-t0:.0f}s")

    # Write v2 jsonl
    raw_path = _OUT_DIR / "attribution_raw_v2.jsonl"
    with raw_path.open("w", encoding="utf-8") as f:
        for c in classified:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"\nWrote {raw_path}")

    # Write v2 CSV
    csv_path = _OUT_DIR / "attribution_v2.csv"
    with csv_path.open("w", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["claim_id", "task_id_tail", "claim_type", "verifier_layer",
                    "attribution", "w11_bucket", "claim_text", "rationale"])
        for c in classified:
            w.writerow([c["claim_id"], c["task_id"][-25:],
                        c.get("claim_type"), c.get("verifier_layer"),
                        c.get("attribution"), c.get("w11_bucket"),
                        c.get("claim_text", "")[:300],
                        c.get("rationale", "")[:200]])
    print(f"Wrote {csv_path}")

    # Distribution
    n = len(classified)
    ctr_attr = Counter(c["attribution"] for c in classified)
    ctr_w11 = Counter(c["w11_bucket"] for c in classified)
    print()
    print(f"v2 attribution distribution (n={n}):")
    for k, v in ctr_attr.most_common():
        print(f"  {k:<20} {v:>4} ({100*v/n:.1f}%)")
    print()
    print(f"v2 W11 bucket distribution:")
    for k, v in ctr_w11.most_common():
        print(f"  {k:<20} {v:>4} ({100*v/n:.1f}%)")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

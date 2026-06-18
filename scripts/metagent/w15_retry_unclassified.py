"""W15 D2 — retry 21 UNCLASSIFIED claims from initial classifier run.

Initial classify_uv_pool() run (commit 40c58bb GREEN + classifier run)
left 21 / 901 claims labeled UNCLASSIFIED — 20 from batch 10 (full
batch dropped) + 1 from batch 19. Likely root cause: LLM produced JSON
with claim_id values that did not match the input batch's claim_ids
(claim_ids in a task often repeat across tasks since each task
re-issues v1:c000, v1:c001, ...; the LLM may have collapsed duplicates
or returned shorter list).

This retry script:
  1. Loads attribution_raw.jsonl
  2. Filters to attribution == UNCLASSIFIED (21 rows expected)
  3. Re-runs classifier in batches of 5 (smaller batch + index-based
     mapping via position rather than claim_id to avoid the duplicate-
     claim_id collapse issue)
  4. Re-writes attribution_raw.jsonl + attribution.csv

HG-3 (100 % labeled) requires this retry pass.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from scripts.metagent.w15_uv_attribution import (
    _SYSTEM_PROMPT_W15,
    _build_user_message,
    _parse_llm_json_list,
)


_OUT_DIR = Path("data/metagent/w15_uv_attribution")
_BATCH_SIZE_RETRY = 5  # smaller batch reduces LLM list-collapse risk


def main() -> int:
    from collections import Counter
    from common.llm_client import chat

    raw_path = _OUT_DIR / "attribution_raw.jsonl"
    rows = [json.loads(l) for l in raw_path.open()]

    unc_idx = [i for i, r in enumerate(rows) if r.get("attribution") == "UNCLASSIFIED"]
    print(f"Found {len(unc_idx)} UNCLASSIFIED rows to retry")
    if not unc_idx:
        print("Nothing to do.")
        return 0

    n_batches = (len(unc_idx) + _BATCH_SIZE_RETRY - 1) // _BATCH_SIZE_RETRY
    t0 = time.time()
    fixed = 0
    still_unclassified = 0
    for bi in range(n_batches):
        sub_idx = unc_idx[bi * _BATCH_SIZE_RETRY:(bi + 1) * _BATCH_SIZE_RETRY]
        # Rewrite claim_id to a positional tag so the LLM cannot collapse
        # duplicate v1:cNNN tags across tasks within the batch.
        batch_input = []
        positional_map = {}
        for pos, idx in enumerate(sub_idx):
            r = rows[idx]
            pos_id = f"retry_{bi:02d}_{pos:02d}"
            positional_map[pos_id] = idx
            batch_input.append({
                **r,
                "claim_id": pos_id,
            })

        user_msg = _build_user_message(batch_input)
        try:
            response = chat(
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT_W15},
                    {"role": "user", "content": user_msg},
                ],
                model="MiniMax-M2.7-highspeed",
                temperature=0.0,
                trace_id=f"w15_uv_attribution_retry.batch_{bi:02d}",
                caller="w15_uv_attribution_retry",
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            print(f"  retry batch {bi+1}/{n_batches} ERROR: {exc}")
            still_unclassified += len(sub_idx)
            continue

        parsed = _parse_llm_json_list(response)
        cid_map = {e.get("claim_id"): e for e in parsed if isinstance(e, dict)}
        for pos_id, orig_idx in positional_map.items():
            row = cid_map.get(pos_id) or {}
            attribution = str(row.get("attribution", "UNCLASSIFIED"))
            w11 = str(row.get("w11_bucket", "UNCLASSIFIED"))
            rationale = str(row.get("rationale", ""))
            if attribution == "UNCLASSIFIED":
                still_unclassified += 1
            else:
                fixed += 1
                rows[orig_idx]["attribution"] = attribution
                rows[orig_idx]["w11_bucket"] = w11
                rows[orig_idx]["rationale"] = rationale

        if (bi + 1) % 1 == 0:
            print(f"  retry batch {bi+1}/{n_batches}  fixed_so_far={fixed}  "
                  f"still_unc={still_unclassified}  elapsed={time.time()-t0:.0f}s")

    # Re-write raw jsonl
    with raw_path.open("w", encoding="utf-8") as f:
        for c in rows:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"\nRewrote {raw_path}  ({fixed} fixed, {still_unclassified} still UNCLASSIFIED)")

    # Re-write CSV
    import csv
    csv_path = _OUT_DIR / "attribution.csv"
    with csv_path.open("w", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["claim_id", "task_id_tail", "claim_type", "verifier_layer",
                    "attribution", "w11_bucket", "claim_text", "rationale"])
        for c in rows:
            w.writerow([c["claim_id"], c["task_id"][-25:],
                        c.get("claim_type"), c.get("verifier_layer"),
                        c.get("attribution"), c.get("w11_bucket"),
                        c.get("claim_text", "")[:300],
                        c.get("rationale", "")[:200]])
    print(f"Rewrote {csv_path}")

    # Final distribution
    print()
    ctr_attr = Counter(c["attribution"] for c in rows)
    ctr_w11 = Counter(c["w11_bucket"] for c in rows)
    n = len(rows)
    print(f"Final attribution distribution (n={n}):")
    for k, v in ctr_attr.most_common():
        print(f"  {k:<20} {v:>4} ({100*v/n:.1f}%)")
    print()
    print(f"Final W11 bucket distribution:")
    for k, v in ctr_w11.most_common():
        print(f"  {k:<20} {v:>4} ({100*v/n:.1f}%)")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

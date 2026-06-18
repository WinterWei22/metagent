"""W12 D — re-classify W11 C7 226 claims into strict_id vs fuzzy_biology.

Background:
W12 D5 Path X re-run achieved UV -1.5pp vs expected -12pp. Root-cause
analysis (W12 D5 ping) found that the factual_sub6 layer is wired
correctly but only converts 10.7 % (70 / 657) of FACTUAL/GROUNDED
claims it sees — because most aren't "X has KEGG ID Y" pure-ID claims
but biology relations / pathway statements with no extractable ID.

This script re-classifies the 226 W11 C7 namespace_form claims into two
buckets, giving a calibrated ceiling on how many of them factual_sub6
COULD reach if subject lookup + ID extraction worked perfectly:

  strict_id   — claim_text contains an explicit KEGG / HMDB / CHEBI /
                InChIKey identifier alongside a subject name; matches
                the factual_sub6._ID_PATTERNS regex surface
  fuzzy_biology — anything else: biology relations ("X is in pathway
                Y"), pathway statements ("MUMM:X is a hit"), disease
                relations, network claims

The ceiling = strict_id / 1102 is the **best-case** UV reduction
factual_sub6 can deliver. Compare against W12 D5 实际 -1.5pp to gauge
how much of the gap is "subject not in pool" vs "no ID extractable
at all".

Cost: ~$0.30 at MiniMax-M2.7-highspeed. ~12 batches of 20 claims.

Run:
    PYTHONPATH=. METAGENT_LLM_LOG_PATH=logs/concord/w12_d_reclassify.jsonl \\
        python scripts/concord/w12_d_reclassify_c7_strict_vs_fuzzy.py
"""
from __future__ import annotations

import json
import re
import time
from collections import Counter
from pathlib import Path

from common.llm_client import chat


_INPUT = Path("data/concord/w11_uv_diagnosis/uv_classified.jsonl")
_OUTPUT = Path("data/concord/w12_uv_ceiling/c7_strict_vs_fuzzy.jsonl")
_SUMMARY = Path("data/concord/w12_uv_ceiling/ceiling_summary.json")
_BATCH = 20


_SYSTEM_PROMPT = """You are sorting biology research claims into one of two buckets, both
specifically for the C7 namespace_form bucket from the W11 UV diagnosis.

Each claim was flagged as "C7 namespace_form" by an earlier classifier
because its surface form involves identifier or namespace patterns.
Your job is to decide whether each claim is amenable to verification by
a simple "extract ID + look up in metabolite pool" verifier (the new
factual_sub6 layer that landed in W12 D4).

Pick exactly ONE bucket per claim:

strict_id
    Claim contains a CONCRETE EXTRACTABLE identifier (KEGG compound ID
    like C00082, HMDB ID like HMDB0000158, ChEBI ID like CHEBI:17895,
    InChIKey first-block like OUYCCCASQSFEME) attached to a metabolite
    subject. The factual_sub6 layer extracts the ID via regex, looks
    up the subject in differential_metabolites or curated pool, and
    compares the ID to the pool's matching field. These claims are
    structurally verifiable.
    Examples:
      "L-tyrosine has KEGG ID C00082"
      "Pyruvic acid maps to KEGG compound C00022"
      "CHEBI:17895 corresponds to L-tyrosine"
      "InChIKey OUYCCCASQSFEME belongs to tyrosine"

fuzzy_biology
    Everything else in C7 — claims that mention identifier patterns or
    namespaces but ARE NOT amenable to the "extract ID + lookup"
    contract. Examples:
      - Biology relations: "Pyrocatechol appears in Disulfiram action"
      - Pathway statements: "MUMM:prostaglandin_formation_from_arachidonate
        is a third mummichog hit"
      - Network claims: "Glycerol is a network intermediate in MUMM:..."
      - Disease relations: "Disorders of transmembrane transporters
        implicates cholesterol"
      - Cross-method statements: "X appears in both ORA and Mummichog"
      These need richer verifiers (semantic, pathway-aware) than what
      factual_sub6 provides.

Return strict JSON only — no prose, no markdown fences. Format:
[{"claim_id": "...", "bucket": "strict_id" | "fuzzy_biology"}, ...]
One entry per input claim in the same order, same claim_id values."""


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
        print(f"ERROR: {_INPUT} missing")
        return 1

    c7_claims: list[dict] = []
    with _INPUT.open() as f:
        for line in f:
            d = json.loads(line)
            if d.get("category") == "C7":
                c7_claims.append(d)
    print(f"Loaded {len(c7_claims)} C7 claims")

    _OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    classified: list[dict] = []
    failed = 0
    n_batches = (len(c7_claims) + _BATCH - 1) // _BATCH
    t0 = time.time()
    for bi in range(n_batches):
        batch = c7_claims[bi * _BATCH:(bi + 1) * _BATCH]
        user_msg = "Classify these C7 claims. Return JSON list.\n\n"
        for i, c in enumerate(batch, 1):
            user_msg += f"{i}. claim_id={c['claim_id']!r}, claim_text={c['claim_text'][:400]!r}\n"

        try:
            response = chat(
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                model="MiniMax-M2.7-highspeed",
                temperature=0.0,
                trace_id=f"w12_d_reclassify.batch_{bi:03d}",
                caller="w12_d_reclassify",
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

        if (bi + 1) % 3 == 0 or (bi + 1) == n_batches:
            elapsed = time.time() - t0
            print(f"  batch {bi+1}/{n_batches}  fail={failed}  elapsed={elapsed:.0f}s")

    with _OUTPUT.open("w") as f:
        for c in classified:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    dist = Counter(c["bucket"] for c in classified)
    n_strict = dist.get("strict_id", 0)
    n_fuzzy = dist.get("fuzzy_biology", 0)
    n_unc = dist.get("UNCLASSIFIED", 0)
    total_w11_uv = 1102

    summary = {
        "n_c7_total": len(c7_claims),
        "n_strict_id": n_strict,
        "n_fuzzy_biology": n_fuzzy,
        "n_unclassified": n_unc,
        "failed_batches": failed,
        "n_batches": n_batches,
        "w11_uv_total": total_w11_uv,
        "factual_sub6_theoretical_ceiling_pp": round(100 * n_strict / total_w11_uv, 2),
        "wall_seconds": round(time.time() - t0, 1),
    }
    _SUMMARY.write_text(json.dumps(summary, indent=2))

    print()
    print("=" * 60)
    print("Re-classification distribution")
    print("=" * 60)
    print(f"  strict_id       (factual_sub6 can verify)  {n_strict:>4} ({100*n_strict/len(c7_claims):>5.1f}%)")
    print(f"  fuzzy_biology   (factual_sub6 cannot)      {n_fuzzy:>4} ({100*n_fuzzy/len(c7_claims):>5.1f}%)")
    print(f"  UNCLASSIFIED                                {n_unc:>4} ({100*n_unc/len(c7_claims):>5.1f}%)")
    print()
    print(f"  factual_sub6 ceiling on W11 baseline:  {n_strict} / 1102 = {100*n_strict/total_w11_uv:.2f}% of total UV")
    print(f"  vs W12 D5 实测 UV drop:                 -1.50 pp")
    print(f"  vs W12 D5 spec target:                  -12 pp")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

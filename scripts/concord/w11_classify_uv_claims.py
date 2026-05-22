"""W11 UV diagnosis — Step 2: LLM-assisted categorization of 1102 UV claims.

Reads data/concord/w11_uv_diagnosis/uv_claims_raw.jsonl, batches into
20-claim chunks, calls MiniMax-M2.7 to classify each claim into one of
9 categories (C1..C9), writes data/concord/w11_uv_diagnosis/uv_classified.jsonl.

The system prompt + category definitions live in
data/concord/w11_uv_diagnosis/llm_prompt_used.md (kept for reproducibility).

Cost budget: $3 ceiling per W11 spec. Estimated MiniMax-M2.7 cost ~$0.07.

Run:
    PYTHONPATH=. python scripts/concord/w11_classify_uv_claims.py
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from common.llm_client import chat


_RAW = Path("data/concord/w11_uv_diagnosis/uv_claims_raw.jsonl")
_OUT = Path("data/concord/w11_uv_diagnosis/uv_classified.jsonl")
_BATCH = 20

_SYSTEM_PROMPT = """You are classifying biology research claims into one of 9 categories.

These claims were emitted by an LLM agent doing metabolic pathway analysis on
differential metabolite lists. A downstream verifier judged them as
"unverifiable" because they did not fit the 4 supported grammar shapes
(pathway_membership / metabolite_pathway_link / pathway_enrichment /
driver_metabolite). Your job is to tell us *why* each claim slipped through.

Pick exactly ONE primary category per claim from this list:

C1 cross_method_consensus
    Claim talks about multiple pathway-analysis methods (ORA / FELLA / SSPA /
    Mummichog / RaMP) reaching the same or related conclusion.
    Examples: "ORA and FELLA both rank tyrosine metabolism in the top 3",
              "Three of five paradigms converge on glycine metabolism"

C2 method_disagreement
    Claim flags a discrepancy or differential outcome between methods.
    Examples: "ORA ranks tyrosine #1 but Mummichog does not detect it",
              "Iron shows no enrichment in Mummichog analysis"

C3 signal_evidence
    Claim cites metabolite-level numeric evidence (z-score, fold change,
    abundance, p-value, number of hits) that is not itself a pathway claim.
    Examples: "Tyrosine is elevated 2.3-fold",
              "Galactose metabolism had 11 metabolite hits"

C4 uncertainty_qualifier
    Claim is hedged with confidence / strength / preliminary language.
    Examples: "High confidence in tyrosine metabolism",
              "Weak signal for arachidonate cascade",
              "Preliminary indicator suggesting..."

C5 intermediate_biology
    Claim describes biological mechanism / upstream-downstream / reaction step
    / enzyme function — NOT a pathway-membership or driver claim.
    Examples: "Serotonin is converted to melatonin via arylalkylamine N-acetyltransferase",
              "The glycine N-methyltransferase reaction uses SAM"

C6 literature_reference
    Claim invokes prior knowledge / canonical fact / well-known mechanism.
    Examples: "Tyrosine is a known precursor to dopamine",
              "As reported in the literature, methionine cycle..."

C7 namespace_form
    Claim is structurally about pathway-membership/enrichment but uses a
    non-canonical id namespace (MUMM:, LM:, bare pathway name without ID,
    wrong-prefix HMDB/KEGG/CHEBI confusion).
    Examples: "MUMM:prostaglandin_formation_from_arachidonate places thromboxane A2...",
              "Sucrose has HMDB ID C00089"  (C-prefix is KEGG, not HMDB)

C8 empty_or_noise
    Claim is degenerate: prompt fragment, repetition of earlier text,
    near-empty, lorem-ipsum-like, or completely unrelated to the task.
    Examples: ".......", "see above", "as previously stated"

C9 other
    Claim doesn't fit any of C1-C8. Use sparingly.

Return strict JSON only — no prose, no markdown fences. Format:
[{"claim_id": "...", "primary": "C<N>"}, ...]
One entry per input claim, in the same order. Use the same claim_id values
as given in the user message."""


def _build_batch_message(batch: list[dict]) -> str:
    lines = ["Classify these claims. Return JSON list — claim_id + primary "
             "category code (one of C1, C2, ..., C9)."]
    lines.append("")
    for i, c in enumerate(batch, 1):
        lines.append(f"{i}. claim_id={c['claim_id']!r}, "
                     f"claim_text={c['claim_text'][:400]!r}")
    return "\n".join(lines)


_JSON_FENCE = re.compile(r"```(?:json)?\s*(\[.*?\])\s*```", re.DOTALL)
_JSON_OBJ = re.compile(r"(\[[^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*\])", re.DOTALL)


def _parse_response(text: str) -> list[dict]:
    """Extract JSON list from LLM response."""
    # Try fenced JSON first
    m = _JSON_FENCE.search(text)
    if m:
        text = m.group(1)
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try locating first [...] block
        m = _JSON_OBJ.search(text)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        return []


def main() -> int:
    if not _RAW.exists():
        print(f"ERROR: raw UV claims missing at {_RAW}")
        return 1

    uv = []
    with _RAW.open() as f:
        for line in f:
            uv.append(json.loads(line))
    print(f"Loaded {len(uv)} UV claims for classification")

    classified: list[dict] = []
    failed_batches = 0
    n_batches = (len(uv) + _BATCH - 1) // _BATCH

    t0 = time.time()
    for bi in range(n_batches):
        batch = uv[bi * _BATCH:(bi + 1) * _BATCH]
        user_msg = _build_batch_message(batch)
        trace_id = f"w11_uv_classify.batch_{bi:03d}"

        try:
            response = chat(
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                model="MiniMax-M2.7",
                temperature=0.0,
                trace_id=trace_id,
                caller="w11_uv_classify",
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            print(f"  batch {bi+1}/{n_batches} LLM error: {exc}")
            failed_batches += 1
            continue

        parsed = _parse_response(response)
        if len(parsed) != len(batch):
            print(f"  batch {bi+1}/{n_batches} response len mismatch: "
                  f"expected {len(batch)} got {len(parsed)}; raw={response[:200]!r}")
            failed_batches += 1
            # Still try to merge what we got by index
        cid_to_cat: dict[str, str] = {}
        for entry in parsed:
            if isinstance(entry, dict) and "claim_id" in entry and "primary" in entry:
                cid_to_cat[entry["claim_id"]] = str(entry["primary"]).upper()
        for c in batch:
            cat = cid_to_cat.get(c["claim_id"], "UNCLASSIFIED")
            classified.append({**c, "category": cat})

        if (bi + 1) % 10 == 0 or (bi + 1) == n_batches:
            elapsed = time.time() - t0
            print(f"  batch {bi+1}/{n_batches} ({100*(bi+1)/n_batches:.0f}%)  "
                  f"failed_batches={failed_batches}  elapsed={elapsed:.0f}s")

    with _OUT.open("w") as f:
        for c in classified:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"\nWrote {len(classified)} classified UV claims → {_OUT}")
    print(f"Failed batches: {failed_batches}/{n_batches}")
    print(f"Wall: {time.time() - t0:.0f}s")
    return 0 if failed_batches < n_batches // 4 else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())

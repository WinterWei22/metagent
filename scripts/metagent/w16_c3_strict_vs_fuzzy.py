"""W16 D1 - reclassify C3 signal_evidence claims.

Input:
    data/metagent/w15_uv_attribution/attribution_v2.csv

Output:
    data/metagent/w16_c3_strict_vs_fuzzy/c3_subclassification.csv
    data/metagent/w16_c3_strict_vs_fuzzy/summary.md

Run:
    PYTHONPATH=. METAGENT_LLM_LOG_PATH=logs/concord/w16_c3_strict_vs_fuzzy.jsonl \
        python scripts/metagent/w16_c3_strict_vs_fuzzy.py
"""
from __future__ import annotations

import csv
import json
import re
import time
from collections import Counter
from pathlib import Path


_INPUT = Path("data/metagent/w15_uv_attribution/attribution_v2.csv")
_OUTPUT_DIR = Path("data/metagent/w16_c3_strict_vs_fuzzy")
_BATCH_SIZE = 20
_TOTAL_W14_UV_CLAIMS = 901
_PROMPT_EXPECTED_C3 = 168
_VALID_BUCKETS = {"strict_signal_lookup", "fuzzy_signal_inference"}


_SYSTEM_PROMPT = """You are sorting MetAgent C3 signal_evidence claims into one of two buckets.

These claims were tagged as C3 signal_evidence in the W15 UV attribution audit.
Your job is to decide whether a future verifier layer could check each claim by
looking up a concrete numeric/statistical value in pathway enrichment tool
outputs.

Pick exactly ONE bucket per claim:

strict_signal_lookup
    The claim cites a concrete numeric/statistical signal that can be looked up
    in an EnrichmentResult-like tool output field. Examples include explicit
    p-values, adjusted p-values, FDR/q-values, enrichment scores, NES, impact
    scores, ranks, hit counts, or exact threshold comparisons tied to a method
    or pathway. Examples:
      - "Mummichog reports p = 0.000420 for tyrosine metabolism"
      - "ORA ranks Bile secretion first"
      - "The pathway has 5 overlapping metabolites"
      - "GSEA NES is 1.82"

fuzzy_signal_inference
    The claim is signal-like but lacks an exact lookup target, or requires
    semantic threshold reasoning rather than direct field comparison. Examples:
      - "the pathway is strongly enriched"
      - "the score is high"
      - "several tools support this pathway" with no count/rank/value
      - biology statements that mention evidence but no extractable metric

Return strict JSON only - no prose, no markdown fences. Format:
[{"claim_id": "...", "bucket": "strict_signal_lookup" | "fuzzy_signal_inference"}, ...]
One entry per input claim in the same order, same claim_id values."""


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\[.*?\])\s*```", re.DOTALL)


def load_c3_claims(csv_path: Path = _INPUT) -> list[dict[str, str]]:
    """Load W15 v2 rows labelled as C3 signal_evidence."""
    csv_path = Path(csv_path)
    with csv_path.open(newline="", encoding="utf-8") as f:
        return [row for row in csv.DictReader(f) if row.get("w11_bucket") == "C3"]


def build_positional_batch(
    batch: list[dict[str, str]],
    batch_index: int,
) -> tuple[list[dict[str, str]], dict[str, dict[str, str]]]:
    """Replace duplicate-prone claim IDs with per-batch positional IDs."""
    positional: list[dict[str, str]] = []
    pos_map: dict[str, dict[str, str]] = {}
    for pos, row in enumerate(batch):
        pos_id = f"b{batch_index:03d}_p{pos:03d}"
        pos_map[pos_id] = row
        positional.append({**row, "claim_id": pos_id})
    return positional, pos_map


def parse_llm_json_list(text: str) -> list[dict]:
    """Extract a JSON list from a bare or fenced LLM response."""
    m = _JSON_FENCE_RE.search(text)
    if m:
        text = m.group(1)
    text = text.strip().lstrip("`").rstrip("`")
    if text.startswith("json\n"):
        text = text[5:]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"(\[[^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*\])", text, re.DOTALL)
        if not m:
            return []
        try:
            parsed = json.loads(m.group(1))
        except json.JSONDecodeError:
            return []
    return parsed if isinstance(parsed, list) else []


def merge_batch_labels(
    pos_map: dict[str, dict[str, str]],
    parsed: list[dict],
) -> list[dict[str, str]]:
    """Merge LLM labels into original rows, preserving order and IDs."""
    label_by_pos = {str(row.get("claim_id")): row for row in parsed if isinstance(row, dict)}
    merged: list[dict[str, str]] = []
    for pos_id, original in pos_map.items():
        label = label_by_pos.get(pos_id) or {}
        bucket = str(label.get("bucket", "UNCLASSIFIED"))
        if bucket not in _VALID_BUCKETS:
            bucket = "UNCLASSIFIED"
        merged.append({**original, "bucket": bucket})
    return merged


def build_user_message(batch: list[dict[str, str]]) -> str:
    lines = ["Classify these C3 signal_evidence claims. Return JSON list.\n"]
    for i, row in enumerate(batch, 1):
        lines.append(
            f"{i}. claim_id={row['claim_id']!r}\n"
            f"   claim_text={row.get('claim_text', '')[:400]!r}\n"
            f"   claim_type={row.get('claim_type', '')!r}\n"
            f"   verifier_layer={row.get('verifier_layer', '')!r}\n"
            f"   attribution={row.get('attribution', '')!r}\n"
        )
    return "\n".join(lines)


def classify_c3_claims(claims: list[dict[str, str]]) -> tuple[list[dict[str, str]], int, float]:
    """Run MiniMax classification on C3 rows."""
    from common.llm_client import chat

    classified: list[dict[str, str]] = []
    failed_batches = 0
    n_batches = (len(claims) + _BATCH_SIZE - 1) // _BATCH_SIZE
    t0 = time.time()

    for batch_index in range(n_batches):
        batch = claims[batch_index * _BATCH_SIZE:(batch_index + 1) * _BATCH_SIZE]
        positional, pos_map = build_positional_batch(batch, batch_index)
        try:
            response = chat(
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": build_user_message(positional)},
                ],
                model="MiniMax-M2.7-highspeed",
                temperature=0.0,
                trace_id=f"w16_c3_strict_vs_fuzzy.batch_{batch_index:03d}",
                caller="w16_c3_strict_vs_fuzzy",
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            failed_batches += 1
            classified.extend({**row, "bucket": "UNCLASSIFIED", "rationale": repr(exc)} for row in batch)
            print(f"  batch {batch_index + 1}/{n_batches} ERROR: {exc}")
            continue

        classified.extend(merge_batch_labels(pos_map, parse_llm_json_list(response)))
        print(f"  batch {batch_index + 1}/{n_batches} done  elapsed={time.time() - t0:.0f}s")

    return classified, failed_batches, round(time.time() - t0, 1)


def summarize_classifications(
    rows: list[dict[str, str]],
    total_uv_claims: int = _TOTAL_W14_UV_CLAIMS,
    failed_batches: int = 0,
    n_batches: int | None = None,
    wall_seconds: float | None = None,
) -> dict[str, int | float | str]:
    dist = Counter(row.get("bucket", "UNCLASSIFIED") for row in rows)
    n_strict = dist.get("strict_signal_lookup", 0)
    ceiling_pp = round(100 * n_strict / total_uv_claims, 2)
    target_pp = round(ceiling_pp * 0.6, 2)
    summary: dict[str, int | float | str] = {
        "n_c3_total": len(rows),
        "n_strict_signal_lookup": n_strict,
        "n_fuzzy_signal_inference": dist.get("fuzzy_signal_inference", 0),
        "n_unclassified": dist.get("UNCLASSIFIED", 0),
        "failed_batches": failed_batches,
        "n_batches": n_batches if n_batches is not None else 0,
        "w14_uv_total": total_uv_claims,
        "strict_signal_ceiling_pp": ceiling_pp,
        "target_pp_at_0p6_ceiling": target_pp,
        "prompt_expected_c3_total": _PROMPT_EXPECTED_C3,
        "c3_total_source_note": (
            "D1 uses data/metagent/w15_uv_attribution/attribution_v2.csv as authoritative; "
            "the W16 prompt expected 168 C3 claims."
        ),
    }
    if wall_seconds is not None:
        summary["wall_seconds"] = wall_seconds
    return summary


def write_outputs(rows: list[dict[str, str]], summary: dict[str, int | float | str]) -> None:
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = _OUTPUT_DIR / "c3_subclassification.csv"
    fieldnames = [
        "claim_id",
        "task_id_tail",
        "claim_type",
        "verifier_layer",
        "attribution",
        "w11_bucket",
        "bucket",
        "claim_text",
        "rationale",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})

    summary_path = _OUTPUT_DIR / "summary.md"
    summary_path.write_text(
        "# W16 C3 Strict-vs-Fuzzy Reclassification\n\n"
        f"- Source C3 rows: {summary['n_c3_total']}\n"
        f"- strict_signal_lookup: {summary['n_strict_signal_lookup']}\n"
        f"- fuzzy_signal_inference: {summary['n_fuzzy_signal_inference']}\n"
        f"- UNCLASSIFIED: {summary['n_unclassified']}\n"
        f"- W14 UV total: {summary['w14_uv_total']}\n"
        f"- Strict signal ceiling: {summary['strict_signal_ceiling_pp']} pp\n"
        f"- Target at 0.6 ceiling: {summary['target_pp_at_0p6_ceiling']} pp\n"
        f"- Failed batches: {summary['failed_batches']} / {summary['n_batches']}\n"
        f"- Source note: {summary['c3_total_source_note']}\n",
        encoding="utf-8",
    )


def main() -> int:
    if not _INPUT.is_file():
        print(f"ERROR: missing input {_INPUT}")
        return 1

    claims = load_c3_claims(_INPUT)
    print(f"Loaded {len(claims)} C3 claims from {_INPUT}")
    classified, failed_batches, wall_seconds = classify_c3_claims(claims)
    n_batches = (len(claims) + _BATCH_SIZE - 1) // _BATCH_SIZE
    summary = summarize_classifications(
        classified,
        failed_batches=failed_batches,
        n_batches=n_batches,
        wall_seconds=wall_seconds,
    )
    write_outputs(classified, summary)

    print()
    print("=" * 60)
    print("W16 C3 reclassification")
    print("=" * 60)
    print(f"  strict_signal_lookup:    {summary['n_strict_signal_lookup']} / {summary['n_c3_total']}")
    print(f"  fuzzy_signal_inference:  {summary['n_fuzzy_signal_inference']} / {summary['n_c3_total']}")
    print(f"  UNCLASSIFIED:            {summary['n_unclassified']} / {summary['n_c3_total']}")
    print(f"  ceiling:                 {summary['strict_signal_ceiling_pp']} pp")
    print(f"  target:                  {summary['target_pp_at_0p6_ceiling']} pp")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())

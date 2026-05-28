"""W15 — MetAgent UV root-cause attribution audit.

Pure audit, no production code modify. Pulls every UNVERIFIABLE_V0 claim
from the W14 close-out Path X trace, labels each one
{producer_fault, verifier_gap, both} via MiniMax-M2.7, and produces a
CSV + summary.md with bucket-level ratio + ranked W16+ candidates.

Architecture (per W15 spec §2):

  1. extract_uv_claim_pool(trace_dir) — parses each task json
     `iterations[final_iter_idx].verification.verdict` (stringified
     pydantic VerifiedIdentification repr) and yields one dict per UV
     claim. Same regex-paren-balance approach as W11 / W13.C extractors.

  2. classify_uv_claim(claim, llm_fn) — D2 — one MiniMax call per claim
     with the §3 rubric, returns {label, rationale, evidence_pointer}.

  3. main() — D2 — drives the full pipeline:
     pool → classify each → write attribution.csv + summary.md

D1 covers (1) only — extractor + RED → GREEN. D2 adds (2)+(3) + spot
check.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable


_W14_TRACE_DIR = (
    Path(__file__).resolve().parents[2]
    / "data" / "concord" / "w14_path_x_post_noise_cap" / "path_x_full"
)


# Regex patterns borrowed from W11 extractor — paren-balance scan finds
# each VerifiedClaim(...) block; field-level regex extracts the fields
# the classifier needs.
_CLAIM_START = re.compile(r"VerifiedClaim\(")
_VERDICT_RE = re.compile(r"verdict=<ClaimVerdict\.(\w+):")
_LAYER_RE = re.compile(r"verifier_layer='([^']*)'")
_TYPE_RE = re.compile(r"claim_type=<ClaimType\.(\w+):")
_CLAIM_ID_RE = re.compile(r"claim_id='([^']*?)'")


def _scan_quoted_string(block: str, key: str) -> str | None:
    """Pydantic-repr-aware string field extractor.

    Locates ``<key>=`` in ``block`` and walks the value as a Python single-
    quoted string with backslash escapes (the form pydantic ``__repr__``
    emits). Returns the unescaped content, or ``None`` if the field is
    absent or its value is not a quoted string (e.g. ``key=None``).

    More robust than a single non-greedy regex because pydantic repr
    routinely embeds backslash-escaped quotes / newlines / unicode escapes
    that trip up `('(?:\\.|[^'\\])*?')` on long values.
    """
    needle = f"{key}="
    i = block.find(needle)
    if i < 0:
        return None
    j = i + len(needle)
    if j >= len(block) or block[j] != "'":
        return None  # not a quoted string (e.g. None, <Enum…>)
    pos = j + 1
    buf: list[str] = []
    while pos < len(block):
        ch = block[pos]
        if ch == "\\":
            # Backslash escape — keep both chars, let unicode-escape unwrap
            if pos + 1 < len(block):
                buf.append(ch)
                buf.append(block[pos + 1])
                pos += 2
                continue
            pos += 1
            continue
        if ch == "'":
            raw = "".join(buf)
            # Decode python-repr-style escapes (\n, \', \\, \uXXXX)
            try:
                return raw.encode("utf-8").decode("unicode_escape", errors="replace")
            except Exception:
                return raw
        buf.append(ch)
        pos += 1
    return None  # unterminated


def _unquote(s: str) -> str:
    """Strip pydantic repr quotes + unescape unicode."""
    if s.startswith("'") and s.endswith("'"):
        s = s[1:-1]
    return s.encode("utf-8").decode("unicode_escape", errors="replace")


def _slice_claims_v1(verdict_str: str) -> str:
    """Return the `claims_v1=[...]` slice so we don't double-count claims_v2."""
    i = verdict_str.find("claims_v1=[")
    if i < 0:
        return ""
    j = verdict_str.find("claims_v2=", i)
    return verdict_str[i:j] if j > 0 else verdict_str[i:]


def _iter_claim_blocks(verdict_str: str) -> Iterable[str]:
    """Yield each VerifiedClaim(...) block body via paren-balance scan.

    Why a hand-rolled scanner rather than ``re.findall``: pydantic repr
    contains nested parens inside quoted strings (e.g. evidence with
    "(C00082)" or "Layer 6a (substring match)"); a naive non-greedy
    regex stops at the first ')' and truncates the block. The scanner
    skips parens that occur inside a quoted string by toggling an
    in-string state, the same invariant Python's tokenizer enforces.
    """
    sl = _slice_claims_v1(verdict_str)
    for m in _CLAIM_START.finditer(sl):
        # Start right after the opening '(' of VerifiedClaim(.
        start = m.end()
        depth = 1            # nesting depth of un-escaped parens
        pos = start
        in_str = False       # currently inside a single/double-quoted string
        str_ch = ""          # which quote char opened the current string
        while pos < len(sl) and depth > 0:
            ch = sl[pos]
            if in_str:
                # Inside a string: only the matching close-quote can exit;
                # backslash + any char advances by 2 so escaped quotes
                # ("d\\'autre") don't prematurely close the string.
                if ch == "\\":
                    pos += 2
                    continue
                if ch == str_ch:
                    in_str = False
            else:
                # Outside any string: track quotes (enter string mode) and
                # parens (track nesting depth).
                if ch in ("'", '"'):
                    in_str = True
                    str_ch = ch
                elif ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        # Found the matching close-paren of this
                        # VerifiedClaim(...). Block body is [start, pos).
                        yield sl[start:pos]
                        break
            pos += 1


def _parse_block(block: str) -> dict | None:
    cid = _CLAIM_ID_RE.search(block)
    typ = _TYPE_RE.search(block)
    vrd = _VERDICT_RE.search(block)
    lyr = _LAYER_RE.search(block)
    if not (cid and vrd):
        # claim_id + verdict are minimum required for downstream attribution
        return None
    claim_text = _scan_quoted_string(block, "claim_text") or ""
    evidence = _scan_quoted_string(block, "evidence") or ""
    return {
        "claim_id": cid.group(1),
        "claim_text": claim_text,
        "claim_type": typ.group(1) if typ else None,
        "verdict": vrd.group(1),
        "verifier_layer": lyr.group(1) if lyr else None,
        "evidence": evidence,
    }


def extract_uv_claim_pool(trace_dir: Path) -> list[dict]:
    """Return a list of UV claim dicts pulled from the final iter of each
    task json under `trace_dir`.

    Each dict has fields:
      claim_id / claim_text / claim_type / verifier_layer / verdict /
      evidence / task_id

    Filter: only `verdict == "UNVERIFIABLE_V0"` survives.
    """
    trace_dir = Path(trace_dir)
    if not trace_dir.is_dir():
        raise FileNotFoundError(f"trace dir not found: {trace_dir}")

    pool: list[dict] = []
    for jpath in sorted(trace_dir.glob("*.json")):
        try:
            d = json.loads(jpath.read_text())
        except json.JSONDecodeError:
            continue
        task_id = d.get("task_id", jpath.stem)
        iters = d.get("iterations") or []
        final_idx = d.get("final_iter_idx", 0)
        if not (0 <= final_idx < len(iters)):
            continue
        verdict_str = iters[final_idx].get("verification", {}).get("verdict", "")
        if not isinstance(verdict_str, str):
            continue
        for block in _iter_claim_blocks(verdict_str):
            parsed = _parse_block(block)
            if parsed is None:
                continue
            if parsed["verdict"] != "UNVERIFIABLE_V0":
                continue
            parsed["task_id"] = task_id
            parsed["final_iter_idx"] = final_idx
            pool.append(parsed)
    return pool


# ---------------------------------------------------------------------------
# D2 — LLM classifier (attribution + W11 9-cat bucket, single pass)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_W15 = """You are auditing UV (unverifiable_v0) claims from MetAgent. For each
claim, output TWO labels.

==== Label 1: attribution (producer_fault | verifier_gap | both) ====

producer_fault: ReAct should NOT have written this claim.
  - Meta-filler / boilerplate ("In summary,", "Based on the analysis,...")
  - Template fragment leaking ("[METABOLITE]", "TBD")
  - Self-reference ("As mentioned earlier", "X is in the input set")
  - Pure hallucination with no tool-output basis
  - Prompt fragment echo
  - Wrong-namespace mis-label (e.g. "X has HMDB ID C00112" — C-prefix is KEGG)

verifier_gap: Claim is legitimate and tool-derivable, verifier cannot check.
  - No verifier layer covers this claim type / data source
  - Required external data absent (e.g. KEGG REACTION for "X converts Y to Z")
  - Cross-method consensus statements with no consensus checker
  - Statistical citations (p-values, fold changes) with no signal verifier
  - MUMM: / LM: namespace pathway claims (layers don't parse these)
  - Disease/clinical-significance claims (outside Sub-6 v0 scope per evidence)

both: Partial producer issue AND verifier can't catch even tightened form.
  - Loose phrasing AND no layer handles even the strict form
  - Mixed claims (half checkable, half not)
  - Name-only metabolite references where IDs would help BUT verifier also
    has no name-lookup

==== DISAMBIGUATION RULE (critical, W15 v2) ====

Default to a SINGLE label (producer_fault OR verifier_gap).
Only assign `both` when BOTH conditions are SIMULTANEOUSLY true:

  (a) The claim's phrasing is genuinely loose/improvable (not just
      slightly informal) — could be tightened to remove a producer
      concern; AND
  (b) Even AFTER tightening, NO current verifier layer/data source
      could check the tightened form.

If only (a) is true → producer_fault
If only (b) is true → verifier_gap
If neither         → re-examine: this should not be UV at all

==== Label 2: w11_bucket (C1..C9) ====

C1 cross_method_consensus  — claim cites multi-method agreement / convergence
C2 method_disagreement     — claim flags discrepancy between methods
C3 signal_evidence         — numeric / statistical evidence (p, fold, count)
C4 uncertainty_qualifier   — hedged language ("high confidence", "weak")
C5 intermediate_biology    — reaction step, upstream/downstream, enzyme function
C6 literature_reference    — canonical fact / "known to be" / "as reported"
C7 namespace_form          — claim with non-canonical namespace IDs (MUMM, LM,
                             wrong-prefix HMDB/KEGG/CHEBI confusion)
C8 empty_or_noise          — degenerate, near-empty, prompt fragment, repetition
C9 other                   — none of C1-C8

Output STRICT JSON list (no prose, no fences), one entry per input claim, same
order as input. Each entry: {"claim_id": "...", "attribution": "...",
"w11_bucket": "...", "rationale": "..."}.
"""

_BATCH_SIZE = 20
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\[.*?\])\s*```", re.DOTALL)


def _parse_llm_json_list(text: str) -> list[dict]:
    """Extract JSON list from LLM response (handles fenced or bare JSON)."""
    m = _JSON_FENCE_RE.search(text)
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


def _build_user_message(batch: list[dict]) -> str:
    lines = ["Classify these claims. Return JSON list — claim_id + attribution + "
             "w11_bucket + one-sentence rationale.\n"]
    for i, c in enumerate(batch, 1):
        lines.append(
            f"{i}. claim_id={c['claim_id']!r}\n"
            f"   claim_text={c['claim_text'][:300]!r}\n"
            f"   claim_type={c['claim_type']!r}\n"
            f"   verifier_layer={c['verifier_layer']!r}\n"
            f"   evidence={c['evidence'][:200]!r}\n"
        )
    return "\n".join(lines)


def classify_uv_pool(pool: list[dict]) -> list[dict]:
    """Run MiniMax classifier on the full UV pool. Returns list of dicts
    with each input claim merged with LLM-output labels.
    """
    from common.llm_client import chat
    import time

    classified: list[dict] = []
    n_batches = (len(pool) + _BATCH_SIZE - 1) // _BATCH_SIZE
    t0 = time.time()
    failed_batches = 0
    for bi in range(n_batches):
        batch = pool[bi * _BATCH_SIZE:(bi + 1) * _BATCH_SIZE]
        user_msg = _build_user_message(batch)
        try:
            response = chat(
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT_W15},
                    {"role": "user", "content": user_msg},
                ],
                model="MiniMax-M2.7",
                temperature=0.0,
                trace_id=f"w15_uv_attribution.batch_{bi:03d}",
                caller="w15_uv_attribution",
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
        for c in batch:
            row = cid_map.get(c["claim_id"]) or {}
            classified.append({
                **c,
                "attribution": str(row.get("attribution", "UNCLASSIFIED")),
                "w11_bucket": str(row.get("w11_bucket", "UNCLASSIFIED")),
                "rationale": str(row.get("rationale", "")),
            })

        if (bi + 1) % 5 == 0 or (bi + 1) == n_batches:
            print(f"  batch {bi+1}/{n_batches} done  fail={failed_batches}  "
                  f"elapsed={time.time()-t0:.0f}s")
    return classified


def main() -> int:
    """D2 entry — extract + classify + aggregate (D1 extract reused)."""
    from collections import Counter
    out_dir = (
        Path(__file__).resolve().parents[2]
        / "data" / "metagent" / "w15_uv_attribution"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    pool_path = out_dir / "uv_claim_pool.jsonl"
    if pool_path.is_file():
        pool = [json.loads(l) for l in pool_path.open()]
        print(f"Loaded {len(pool)} UV claims from cached {pool_path}")
    else:
        pool = extract_uv_claim_pool(_W14_TRACE_DIR)
        with pool_path.open("w", encoding="utf-8") as f:
            for c in pool:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
        print(f"Extracted {len(pool)} UV claims; wrote {pool_path}")

    print()
    print(f"Running MiniMax-M2.7 classifier on {len(pool)} claims...")
    classified = classify_uv_pool(pool)

    # Raw output
    raw_path = out_dir / "attribution_raw.jsonl"
    with raw_path.open("w", encoding="utf-8") as f:
        for c in classified:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"Wrote {raw_path}")

    # CSV
    import csv
    csv_path = out_dir / "attribution.csv"
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

    # Summary
    n = len(classified)
    ctr_attr = Counter(c["attribution"] for c in classified)
    ctr_w11 = Counter(c["w11_bucket"] for c in classified)
    print()
    print(f"Attribution distribution (n={n}):")
    for k, v in ctr_attr.most_common():
        print(f"  {k:<20} {v:>4} ({100*v/n:.1f}%)")
    print()
    print(f"W11 9-cat bucket distribution:")
    for k, v in ctr_w11.most_common():
        print(f"  {k:<20} {v:>4} ({100*v/n:.1f}%)")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

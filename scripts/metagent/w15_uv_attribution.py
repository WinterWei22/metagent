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
    """Yield each VerifiedClaim(...) block body via paren-balance scan."""
    sl = _slice_claims_v1(verdict_str)
    for m in _CLAIM_START.finditer(sl):
        start = m.end()
        depth = 1
        pos = start
        in_str = False
        str_ch = ""
        while pos < len(sl) and depth > 0:
            ch = sl[pos]
            if in_str:
                if ch == "\\":
                    pos += 2
                    continue
                if ch == str_ch:
                    in_str = False
            else:
                if ch in ("'", '"'):
                    in_str = True
                    str_ch = ch
                elif ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
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


def main() -> int:
    """D1 entry point — extract pool, write to disk, report count."""
    out_dir = (
        Path(__file__).resolve().parents[2]
        / "data" / "metagent" / "w15_uv_attribution"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    pool = extract_uv_claim_pool(_W14_TRACE_DIR)
    print(f"Extracted {len(pool)} UV claims from {_W14_TRACE_DIR}")

    out_path = out_dir / "uv_claim_pool.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for c in pool:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"Wrote {out_path}")

    # Brief breakdown by claim_type + verifier_layer for D1 sanity
    from collections import Counter
    type_ctr = Counter(c.get("claim_type") for c in pool)
    layer_ctr = Counter(c.get("verifier_layer") for c in pool)
    print()
    print("UV breakdown by claim_type:")
    for k, n in type_ctr.most_common():
        print(f"  {k:<25} {n:>4}")
    print()
    print("UV breakdown by verifier_layer:")
    for k, n in layer_ctr.most_common():
        print(f"  {k:<25} {n:>4}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

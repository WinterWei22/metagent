"""W11 UV diagnosis — Step 1: extract UV claims from W10 D4 trace files.

Reads data/concord/w10_d4_path_x_full/path_x_full/*.json (per-task full
ConcordFeedbackResult dumps), parses the stringified pydantic
VerifiedIdentification repr inside `iterations[final_iter_idx].verification.verdict`,
extracts each VerifiedClaim where verdict == UNVERIFIABLE_V0, and
writes raw + summary jsonl to data/concord/w11_uv_diagnosis/.

This is regex-based parsing of pydantic __repr__ output because the
W10 D4 driver dumped via dataclasses.asdict + default=str which
stringified the pydantic VerifiedIdentification. No production code
re-runs verify_sub6.

Run:
    PYTHONPATH=. python scripts/concord/w11_extract_uv_claims.py
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

_INPUT_DIR = Path("data/concord/w10_d4_path_x_full/path_x_full")
_OUTPUT_DIR = Path("data/concord/w11_uv_diagnosis")

# Match a complete VerifiedClaim(...) block by counting parens.
# Use re to find starts, then scan for matching close.
_CLAIM_START = re.compile(r"VerifiedClaim\(")


def _extract_claim_blocks(verdict_str: str) -> list[str]:
    """Return list of substrings, each being one VerifiedClaim(...) body
    (without the outer name and parens — just the inner field=value list)."""
    blocks: list[str] = []
    for m in _CLAIM_START.finditer(verdict_str):
        start = m.end()  # position right after the opening paren
        depth = 1
        i = start
        in_str = False
        str_ch = ""
        while i < len(verdict_str) and depth > 0:
            ch = verdict_str[i]
            if in_str:
                if ch == "\\":
                    i += 2
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
                        blocks.append(verdict_str[start:i])
                        break
            i += 1
    return blocks


def _split_claims_v1_only(verdict_str: str) -> str:
    """Return the verdict_str slice that holds claims_v1 only (drop
    claims_v2 to avoid double-counting the same claim_id across passes)."""
    i = verdict_str.find("claims_v1=[")
    if i < 0:
        return ""
    j = verdict_str.find("claims_v2=", i)
    if j < 0:
        return verdict_str[i:]
    return verdict_str[i:j]


# Field regexes — pydantic repr is "field=value" with value being either
# a quoted string, a <Enum.MEMBER: 'value'> shape, or None / nested object.
_FIELD_CLAIM_ID = re.compile(r"claim_id='([^']*?)'")
_FIELD_CLAIM_TEXT = re.compile(r"claim_text=('(?:\\.|[^'\\])*?')(?=,\s*claim_type=)", re.DOTALL)
_FIELD_CLAIM_TYPE = re.compile(r"claim_type=<ClaimType\.(\w+):")
_FIELD_VERDICT = re.compile(r"verdict=<ClaimVerdict\.(\w+):")
_FIELD_EVIDENCE = re.compile(r"evidence=('(?:\\.|[^'\\])*?')(?=,\s*source_field=)", re.DOTALL)
_FIELD_GRAMMAR = re.compile(r"grammar=(None|<ClaimGrammar\.(\w+):)")
_FIELD_SUBJECT = re.compile(r"subject=(None|'(?:\\.|[^'\\])*?')(?=,)", re.DOTALL)
_FIELD_FEEDBACK_HINT = re.compile(r"feedback_hint=(None|'(?:\\.|[^'\\])*?')", re.DOTALL)


def _unquote(s: str) -> str:
    """Strip pydantic-repr quotes + unescape."""
    if s.startswith("'") and s.endswith("'"):
        s = s[1:-1]
    # pydantic uses Python repr quoting; unescape via codecs
    return s.encode("utf-8").decode("unicode_escape", errors="replace")


def _parse_one_block(block: str) -> dict | None:
    m_id = _FIELD_CLAIM_ID.search(block)
    m_text = _FIELD_CLAIM_TEXT.search(block)
    m_type = _FIELD_CLAIM_TYPE.search(block)
    m_verdict = _FIELD_VERDICT.search(block)
    if not (m_id and m_text and m_verdict):
        return None
    m_evidence = _FIELD_EVIDENCE.search(block)
    m_grammar = _FIELD_GRAMMAR.search(block)
    m_subject = _FIELD_SUBJECT.search(block)
    return {
        "claim_id": m_id.group(1),
        "claim_text": _unquote(m_text.group(1)) if m_text else "",
        "claim_type": m_type.group(1) if m_type else None,
        "verdict": m_verdict.group(1),
        "evidence": _unquote(m_evidence.group(1)) if m_evidence else "",
        "grammar": (m_grammar.group(2) if m_grammar and m_grammar.group(2) else None),
        "subject": (
            _unquote(m_subject.group(1))
            if m_subject and m_subject.group(1) != "None"
            else None
        ),
    }


def _parse_task(json_path: Path) -> tuple[list[dict], dict]:
    """Return (uv_claims, stats) for one task file."""
    d = json.loads(json_path.read_text())
    task_id = d.get("task_id", json_path.stem)
    final_idx = d.get("final_iter_idx", 0)
    iters = d.get("iterations") or []
    if final_idx >= len(iters):
        return [], {"task_id": task_id, "parse_error": "no_final_iter"}

    verdict_str = iters[final_idx].get("verification", {}).get("verdict", "")
    if not isinstance(verdict_str, str):
        return [], {"task_id": task_id, "parse_error": "verdict_not_str"}

    claims_v1_slice = _split_claims_v1_only(verdict_str)
    blocks = _extract_claim_blocks(claims_v1_slice)

    uv_claims = []
    verdict_dist = Counter()
    parse_failures = 0
    for blk in blocks:
        parsed = _parse_one_block(blk)
        if parsed is None:
            parse_failures += 1
            continue
        verdict_dist[parsed["verdict"]] += 1
        if parsed["verdict"] == "UNVERIFIABLE_V0":
            uv_claims.append({
                "task_id": task_id,
                "iter_idx": final_idx,
                "gt_pathway_name": (d.get("final_react_result") or {})
                    .get("task_id"),  # placeholder; pathway looked up separately
                **parsed,
            })

    return uv_claims, {
        "task_id": task_id,
        "final_iter_idx": final_idx,
        "n_blocks_found": len(blocks),
        "n_parse_failures": parse_failures,
        "verdict_distribution": dict(verdict_dist),
    }


def main() -> int:
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    paths = sorted(_INPUT_DIR.glob("*.json"))
    print(f"Reading {len(paths)} task files from {_INPUT_DIR}")

    all_uv: list[dict] = []
    all_stats: list[dict] = []
    for p in paths:
        uv, stats = _parse_task(p)
        all_uv.extend(uv)
        all_stats.append(stats)

    # Cross-check totals
    total_uv = sum(s.get("verdict_distribution", {}).get("UNVERIFIABLE_V0", 0)
                   for s in all_stats)
    total_parse_failures = sum(s.get("n_parse_failures", 0) for s in all_stats)
    total_blocks = sum(s.get("n_blocks_found", 0) for s in all_stats)

    print()
    print(f"Total VerifiedClaim blocks parsed (claims_v1 only): {total_blocks}")
    print(f"Total UNVERIFIABLE_V0 claims extracted:              {total_uv}")
    print(f"Total parse failures (block matched but fields missed): {total_parse_failures}")

    # Cross-verify against summary jsonl aggregate
    summary_path = Path("data/concord/w10_d4_path_x_full/path_x_full63_results.jsonl")
    expected_uv = 0
    with summary_path.open() as f:
        for line in f:
            row = json.loads(line)
            pi = row.get("per_iter") or []
            idx = row.get("final_iter_idx", 0)
            if 0 <= idx < len(pi):
                expected_uv += pi[idx].get("n_unverifiable_v0", 0)
    print(f"Expected UV count from summary jsonl (final iter):    {expected_uv}")
    delta = total_uv - expected_uv
    print(f"Delta (extracted - expected):                          {delta:+d}")

    # Write outputs
    out_jsonl = _OUTPUT_DIR / "uv_claims_raw.jsonl"
    with out_jsonl.open("w") as f:
        for c in all_uv:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"\nWrote {len(all_uv)} UV claims → {out_jsonl}")

    stats_path = _OUTPUT_DIR / "extraction_stats.json"
    stats_path.write_text(json.dumps({
        "n_tasks": len(paths),
        "total_blocks_parsed": total_blocks,
        "total_uv_extracted": total_uv,
        "total_parse_failures": total_parse_failures,
        "expected_uv_from_summary": expected_uv,
        "delta": delta,
        "per_task": all_stats,
    }, indent=2, ensure_ascii=False))
    print(f"Wrote extraction stats → {stats_path}")

    # Sanity gate: stop condition #2 (UV count 800-1500)
    if total_uv < 800 or total_uv > 1500:
        print(f"\n⚠ Stop condition #2: extracted UV count {total_uv} outside [800, 1500]")
        return 1
    if abs(delta) > 50:
        print(f"\n⚠ Delta vs summary jsonl is {delta:+d} — extraction may have missed some")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

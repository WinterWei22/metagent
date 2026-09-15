from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedToolOutputClaim:
    method: str
    metric: str
    value: float | int | tuple[int, int]
    pathway_hint: str | None = None


_NUM = r"([0-9]+(?:\.[0-9]+)?(?:e[-+]?[0-9]+)?)"
_MUMM_ID_RE = re.compile(r"\b(MUMM:[A-Za-z0-9_]+)\b", re.IGNORECASE)


def parse_tool_output_claim(text: str) -> ParsedToolOutputClaim | None:
    norm = _clean(text)
    lower = norm.lower()
    methods = [m for m in ("ramp", "metaboanalystr", "mummichog", "sspa", "fella") if m in lower]
    if len(methods) != 1:
        return None
    method = methods[0]
    if "cornerstone" in lower or "converge" in lower or "confirmation" in lower:
        return None
    if method == "mummichog" and lower.startswith("mummichog"):
        method = "mummichog"

    overlap = re.search(r"overlap\s+of\s+(\d+)\s+out\s+of\s+(\d+)", lower)
    if overlap:
        return ParsedToolOutputClaim(method, "overlap", (int(overlap.group(1)), int(overlap.group(2))))

    rank = re.search(r"rank(?:ed)?\s+(\d+)", lower)
    if rank:
        return ParsedToolOutputClaim(method, "rank", int(rank.group(1)), _pathway_hint(norm))

    top_hit = re.search(r"returned\s+(.+?)\s+as\s+the\s+top\s+hit", norm, flags=re.IGNORECASE)
    if top_hit:
        return ParsedToolOutputClaim(method, "rank", 0, top_hit.group(1).strip())

    metric_match = re.search(r"\b(fdr|p\s*-?\s*value|p)\b\s*(?:of|=|is|has|produces)?\s*[:=]?\s*" + _NUM, lower)
    if metric_match:
        raw_metric = metric_match.group(1).replace(" ", "").replace("-", "")
        metric = "p_value" if raw_metric in {"p", "pvalue"} else "fdr"
        return ParsedToolOutputClaim(method, metric, float(metric_match.group(2)), _pathway_hint(norm))

    fold = re.search(r"fold[-\s]*enrichment\s+(?:of\s+)?" + _NUM, lower)
    if fold:
        return ParsedToolOutputClaim(method, "fold_enrichment", float(fold.group(1)))

    return None


def _pathway_hint(text: str) -> str | None:
    mumm = _MUMM_ID_RE.search(text)
    if mumm:
        return mumm.group(1)
    return None


def _clean(text: str) -> str:
    return (
        text.replace("Ã10â»Â¹Â¹", "e-11")
        .replace("Ã10â»â¸", "e-8")
        .replace("×10⁻¹¹", "e-11")
        .replace("×10⁻⁸", "e-8")
    )

"""Extract numeric/statistical signal mentions from Sub-6 claims."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SignalMention:
    metric: str
    value: float
    method: str | None = None
    pathway_hint: str | None = None
    operator: str = "eq"
    total: float | None = None


_NUM_RE = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?"
_WORD_NUMBERS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}
_STOP_PREFIXES = (
    "mummichog",
    "ora",
    "gsea",
    "msea",
    "qea",
    "topology",
    "pathway analysis",
    "the",
)


def extract_signal_mentions(text: str) -> list[SignalMention]:
    """Return conservative signal mentions in claim text.

    Only concrete lookup-shaped values are emitted. Qualitative claims and
    molecular formulas intentionally return an empty list.
    """
    if not text or re.search(r"\bmolecular\s+formula\b", text, re.IGNORECASE):
        return []

    mentions: list[SignalMention] = []
    mentions.extend(_extract_namespace_rank(text))
    mentions.extend(_extract_top_hits(text))
    mentions.extend(_extract_metric_values(text))
    mentions.extend(_extract_overlap_counts(text))
    mentions.extend(_extract_compound_counts(text))
    return mentions


def _extract_metric_values(text: str) -> list[SignalMention]:
    out: list[SignalMention] = []
    pat = re.compile(
        rf"\b(?P<metric>p[- ]?value|p|fdr|q[- ]?value|nes|score|impact)\b\s*"
        rf"(?P<op><=|>=|<|>|=|of\s+)?\s*(?P<value>{_NUM_RE})",
        re.IGNORECASE,
    )
    for m in pat.finditer(text):
        metric = _normalize_metric(m.group("metric"))
        operator = _normalize_operator(m.group("op") or "=")
        out.append(
            SignalMention(
                method=_infer_method(text),
                metric=metric,
                value=float(m.group("value")),
                operator=operator,
                pathway_hint=_infer_pathway_hint(text),
            )
        )
    return out


def _extract_namespace_rank(text: str) -> list[SignalMention]:
    pat = re.compile(
        r"\b(?P<method>MUMM|ORA|GSEA|MSEA|QEA|TOPOLOGY):(?P<pathway>[A-Za-z0-9_\-]+)\s+has\s+rank[-\s]*(?P<rank>\d+)",
        re.IGNORECASE,
    )
    out: list[SignalMention] = []
    for m in pat.finditer(text):
        out.append(
            SignalMention(
                method=_normalize_method(m.group("method")),
                metric="rank",
                value=float(m.group("rank")),
                pathway_hint=_clean_pathway_hint(m.group("pathway")),
            )
        )
    return out


def _extract_top_hits(text: str) -> list[SignalMention]:
    m = re.search(r"\btop[-\s]*(?P<n>\d+)\s+hits?\b", text, re.IGNORECASE)
    if not m:
        return []
    return [
        SignalMention(
            method=_infer_method(text),
            metric="rank_cutoff",
            value=float(m.group("n")),
            pathway_hint=_infer_pathway_hint(text),
        )
    ]


def _extract_overlap_counts(text: str) -> list[SignalMention]:
    pat = re.compile(
        r"\b(?P<count>\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+"
        r"metabolites?\s+overlapped\s+the\s+(?P<total>\d+)-member\s+roster\s+of\s+"
        r"(?P<pathway>[^.;]+)",
        re.IGNORECASE,
    )
    out: list[SignalMention] = []
    for m in pat.finditer(text):
        out.append(
            SignalMention(
                method=_infer_method(text),
                metric="overlap_count",
                value=float(_parse_count(m.group("count"))),
                total=float(m.group("total")),
                pathway_hint=_clean_pathway_hint(m.group("pathway")),
            )
        )
    return out


def _extract_compound_counts(text: str) -> list[SignalMention]:
    pat = re.compile(
        r"\b(?P<method>MUMM|ORA|GSEA|MSEA|QEA|TOPOLOGY):(?P<pathway>[A-Za-z0-9_\-]+)\s+"
        r"involves\s+(?P<count>\d+)\s+compounds?\b",
        re.IGNORECASE,
    )
    out: list[SignalMention] = []
    for m in pat.finditer(text):
        out.append(
            SignalMention(
                method=_normalize_method(m.group("method")),
                metric="total_compounds",
                value=float(m.group("count")),
                pathway_hint=_clean_pathway_hint(m.group("pathway")),
            )
        )
    return out


def _normalize_metric(metric: str) -> str:
    metric = metric.lower().replace("-", " ").strip()
    if metric in {"p", "p value"}:
        return "p_value"
    if metric in {"q value", "fdr"}:
        return "fdr"
    return metric.replace(" ", "_")


def _normalize_operator(op: str) -> str:
    op = op.strip().lower()
    if op in {"<", "<="}:
        return "lt"
    if op in {">", ">="}:
        return "gt"
    return "eq"


def _normalize_method(method: str | None) -> str | None:
    if not method:
        return None
    method = method.lower()
    return "mummichog" if method == "mumm" else method


def _infer_method(text: str) -> str | None:
    low = text.lower()
    if "mummichog" in low or "mumm:" in low:
        return "mummichog"
    for method in ("ora", "gsea", "msea", "qea", "topology"):
        if re.search(rf"\b{method}\b", low):
            return method
    return None


def _infer_pathway_hint(text: str) -> str | None:
    m = re.search(r"\bfor\s+([^.;]+?)\s+(?:has\s+)?(?:p[- ]?value|fdr|q[- ]?value|nes|score|impact)\b", text, re.IGNORECASE)
    if m:
        return _clean_pathway_hint(m.group(1))
    m = re.search(r"^(.+?)\s+has\s+(?:p[- ]?value|fdr|q[- ]?value|nes|score|impact)\b", text, re.IGNORECASE)
    if m:
        return _clean_pathway_hint(m.group(1))
    return None


def _clean_pathway_hint(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip().strip(" .;:,()").replace("_", " ").replace("-", " ")
    parts = cleaned.split()
    while parts and parts[0].lower() in _STOP_PREFIXES:
        parts = parts[1:]
    cleaned = " ".join(parts)
    return cleaned.lower() if cleaned else None


def _parse_count(value: str) -> int:
    low = value.lower()
    if low in _WORD_NUMBERS:
        return _WORD_NUMBERS[low]
    return int(value)

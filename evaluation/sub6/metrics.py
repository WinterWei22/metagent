"""Per-task metrics for Sub-6 baseline evaluation.

All metrics follow ``reports/benchmark/sub6_evaluation_guide.md`` §4.
Pathway comparison uses the substring fuzzy logic from §3 pitfall 3;
driver comparison normalises everything to InChIKey first-block per §3
pitfall 2.

Identification metrics (Sub-6A only) are computed in ``run_sub6a`` from
the per-spectrum log; they aren't part of TaskMetrics here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from evaluation.sub6.compound_lookup import CompoundLookup
from evaluation.sub6.pathway_extract import (
    extract_driver_mentions,
    extract_pathway_mentions,
    PathwayMention,
)

# Pathway-suffix nouns that are not biological content. Stripped before
# token-overlap so "Tyrosine catabolism" can match "Tyrosine metabolism".
_PATHWAY_SUFFIX_TOKENS = frozenset(
    {
        "pathway",
        "metabolism",
        "catabolism",
        "anabolism",
        "biosynthesis",
        "degradation",
        "cycle",
        "signalling",
        "signaling",
        "shunt",
        "fate",
    }
)
# Generic English stop-words; never carry pathway identity.
_STOP_TOKENS = frozenset(
    {"a", "an", "and", "the", "of", "in", "for", "on", "or", "to", "by"}
)
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def _content_tokens(name: str) -> set[str]:
    """Lower-cased content tokens, with pathway-suffix and stop-words removed."""
    if not name:
        return set()
    toks = {t.lower() for t in _TOKEN_RE.findall(name)}
    return {t for t in toks if t not in _PATHWAY_SUFFIX_TOKENS and t not in _STOP_TOKENS}


@dataclass
class TaskMetrics:
    """Grading output for one task.

    Sub-6A and Sub-6B share these fields. Sub-6A adds identification
    accuracy on top, attached separately by run_sub6a.
    """

    task_id: str

    # Pathway hit
    top1_pathway_strict: bool
    top3_pathway_acceptance: bool
    predicted_top_pathway: str | None  # what the LLM mentioned first

    # Driver metrics
    driver_precision: float
    driver_recall: float
    false_noise_rate: float

    # Off-pathway hallucination
    off_pathway_count: int
    off_pathway_examples: list[str] = field(default_factory=list)

    # Diagnostics (carried for the report)
    claimed_drivers: list[str] = field(default_factory=list)
    claimed_driver_inchikeys: list[str] = field(default_factory=list)
    extracted_pathways: list[str] = field(default_factory=list)


def is_pathway_hit(predicted: str, candidates: list[str]) -> bool:
    """Eval guide §3 pitfall 3: pathway-name fuzzy match.

    Two-tier rule:
      1. Case-insensitive substring on the raw names (catches "Tyrosine"
         vs "Tyrosine metabolism").
      2. Content-token subset after stripping pathway suffixes
         ("metabolism" / "catabolism" / "biosynthesis" / ...) and English
         stop-words. So "Tyrosine catabolism" matches "Tyrosine
         metabolism" because the content token set ``{tyrosine}`` is a
         subset of itself.

    The token-subset test goes both directions; whichever side has fewer
    content tokens must be a subset of the other. This is what lets
    "Methionine metabolism" match "Methionine and cysteine metabolism"
    without dragging in "Cysteine metabolism" → "Methionine metabolism".
    """
    if not predicted:
        return False
    norm = predicted.lower().strip()
    pred_tokens = _content_tokens(predicted)
    for c in candidates:
        c_norm = (c or "").lower().strip()
        if not c_norm:
            continue
        if norm in c_norm or c_norm in norm:
            return True
        c_tokens = _content_tokens(c)
        if not pred_tokens or not c_tokens:
            continue
        smaller, larger = (
            (pred_tokens, c_tokens)
            if len(pred_tokens) <= len(c_tokens)
            else (c_tokens, pred_tokens)
        )
        if smaller.issubset(larger):
            return True
    return False


def _safe_div(num: float, den: float) -> float:
    return num / den if den > 0 else 0.0


def compute_task_metrics(
    narrative: str,
    task: dict,
    lookup: CompoundLookup,
) -> TaskMetrics:
    """Apply all metrics to one task's narrative.

    ``task`` is the JSONL record (Sub-6A or Sub-6B); we read
    ``ground_truth_pathway``, ``ground_truth_signal_compounds``,
    ``ground_truth_noise_compounds``, and ``ramp_enrichment_result``.
    """
    # --- Pathway extraction ----------------------------------------------
    top_pathways = task.get("ramp_enrichment_result", {}).get("top_pathways", []) or []
    gt_name = task.get("ground_truth_pathway", {}).get("pathway_name", "") or ""
    top3_names = [p.get("pathway_name", "") for p in top_pathways[:3] if p]
    top10_names = [p.get("pathway_name", "") for p in top_pathways[:10] if p]

    known_names = list({n for n in top10_names + [gt_name] if n})
    pathway_mentions: list[PathwayMention] = extract_pathway_mentions(
        narrative, known_pathway_names=known_names
    )

    predicted_top = pathway_mentions[0].text if pathway_mentions else None

    top1_strict = bool(predicted_top) and is_pathway_hit(predicted_top, [gt_name])
    top3_accept = bool(predicted_top) and is_pathway_hit(predicted_top, top3_names)

    # Off-pathway: any mention NOT in top10 RaMP set.
    off_examples: list[str] = []
    for m in pathway_mentions:
        if not is_pathway_hit(m.text, top10_names):
            off_examples.append(m.text)
    off_count = len(off_examples)

    # --- Driver extraction ------------------------------------------------
    candidate_names = [
        c.get("name") for c in task.get("differential_metabolites", []) or [] if c.get("name")
    ]
    # Sub-6A: the input is identified compounds, not differential_metabolites.
    # Caller passes names via task.setdefault("differential_metabolites", [...])
    # before invoking compute_task_metrics; pool of names is what's known to
    # the LLM at narrative-write time.
    if not candidate_names:
        candidate_names = lookup.all_names

    claimed = extract_driver_mentions(narrative, candidate_names)
    claimed_inchikeys: list[str] = []
    for name in claimed:
        ik = lookup.resolve_name(name)
        if ik:
            claimed_inchikeys.append(ik)

    gt_signal_inchi = lookup.kegg_to_inchikey_set(
        task.get("ground_truth_signal_compounds", []) or []
    )
    gt_noise_inchi = lookup.kegg_to_inchikey_set(
        task.get("ground_truth_noise_compounds", []) or []
    )

    claimed_set = set(claimed_inchikeys)
    tp = len(claimed_set & gt_signal_inchi)
    fp_noise = len(claimed_set & gt_noise_inchi)

    precision = _safe_div(tp, len(claimed_set))
    recall = _safe_div(tp, len(gt_signal_inchi))
    false_noise = _safe_div(fp_noise, len(claimed_set))

    return TaskMetrics(
        task_id=task["task_id"],
        top1_pathway_strict=top1_strict,
        top3_pathway_acceptance=top3_accept,
        predicted_top_pathway=predicted_top,
        driver_precision=precision,
        driver_recall=recall,
        false_noise_rate=false_noise,
        off_pathway_count=off_count,
        off_pathway_examples=off_examples,
        claimed_drivers=claimed,
        claimed_driver_inchikeys=claimed_inchikeys,
        extracted_pathways=[m.text for m in pathway_mentions],
    )


def task_metrics_to_dict(m: TaskMetrics) -> dict:
    """Flat dict for JSONL / CSV emission."""
    return {
        "task_id": m.task_id,
        "top1_pathway_strict": m.top1_pathway_strict,
        "top3_pathway_acceptance": m.top3_pathway_acceptance,
        "predicted_top_pathway": m.predicted_top_pathway,
        "driver_precision": m.driver_precision,
        "driver_recall": m.driver_recall,
        "false_noise_rate": m.false_noise_rate,
        "off_pathway_count": m.off_pathway_count,
        "off_pathway_examples": list(m.off_pathway_examples),
        "claimed_drivers": list(m.claimed_drivers),
        "claimed_driver_inchikeys": list(m.claimed_driver_inchikeys),
        "extracted_pathways": list(m.extracted_pathways),
    }

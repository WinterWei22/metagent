"""Phase 6.5 — Conditional rerank gate (MSAgent-style, msclip-primary frame).

D1 analysis on Sub-6A real-id v2 found:
  - Modcos primary is in-distribution lookup (RIKEN→GNPS leakage); its 74.6%
    baseline is not OOD-representative.
  - MS-CLIP primary is the OOD-realistic baseline (56.7% on the same 458
    spectra). Within msclip primary, top1-top2 narrow gap (<0.05) covers
    59.2% of spectra and rerank delivers +12.83 pp on that bucket.

D5a grid-search (8 × 7 = 56 cells) selected the best threshold pair:

  msclip_top1 threshold = 0.0   (no top1 floor — gap is the dominant signal)
  msclip_gap threshold  = 0.05  (skip when top1 - top2 ≥ 0.05)

Resulting Config E:
  - skip rate 35.3%  (computational savings)
  - id_acc 66.96 %   (matches the modcos in-distribution leakage baseline 66.96%
                      on the same 448 spectra, i.e. the OOD-conditional
                      reranker recovers the lookup-level performance without
                      the leakage shortcut)
  - +10.3 pp vs msclip-only baseline (p < 1e-6)
  - +2.5 pp  vs Phase 6.3 B always-rerank (p=0.013)

This module gates rerank application by the MS-CLIP top1-top2 gap signal.
Default thresholds calibrated by grid search:

  SKIP rerank when:  msclip_gap (top1 - top2) >= 0.05
  TRIGGER rerank otherwise (the ~65% ambiguous fraction).

Reference:
  reports/eval/llm_reranker_v2.md §5.1 (rerank-before-after)
  data/paper_figures/phase6_5_msclip_buckets.csv
  ref_paper/MSAgent.pdf §2.2 (selective application to tools-solvable cases)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)


_EXPLAIN_MSCLIP_RE = re.compile(r"ms[-\s]?clip\s+(\d+(?:\.\d+)?)", re.IGNORECASE)
_EXPLAIN_MODCOS_RE = re.compile(r"modified\s+cosine\s+(\d+(?:\.\d+)?)", re.IGNORECASE)


def _extract_msclip(cand) -> float | None:
    """Pull msclip_rescaled from Candidate.explain string."""
    explain = getattr(cand, "explain", "") or ""
    m = _EXPLAIN_MSCLIP_RE.search(explain)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def _extract_modcos(cand) -> float | None:
    explain = getattr(cand, "explain", "") or ""
    m = _EXPLAIN_MODCOS_RE.search(explain)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


@dataclass
class GateDecision:
    should_rerank: bool
    reason: str
    msclip_top1: float | None
    msclip_gap: float | None


def should_rerank_msclip_gate(
    candidates,
    *,
    msclip_top1_threshold: float = 0.0,
    msclip_gap_threshold: float = 0.05,
) -> GateDecision:
    """Decide whether to invoke the SIRIUS+CFM-ID weighted reranker.

    Inputs:
      candidates: list of ``Candidate``-like objects, **already sorted by the
        primary signal** (msclip_rescaled descending in normal Sub-6A v2 use).

    Decision:
      - if no candidates: skip (no-op)
      - if msclip score unavailable: trigger (fail-safe — better to rerank
        than to commit to an unsignalled top-1)
      - if msclip_top1 >= threshold AND (msclip_top1 - msclip_top2) >= gap:
        skip — primary signal is confident enough
      - else: trigger
    """
    if not candidates:
        return GateDecision(False, "no_candidates", None, None)

    s1 = _extract_msclip(candidates[0])
    if s1 is None:
        return GateDecision(True, "no_msclip_signal_fail_safe_trigger", None, None)

    s2 = 0.0
    if len(candidates) > 1:
        s2_val = _extract_msclip(candidates[1])
        if s2_val is not None:
            s2 = s2_val
    gap = s1 - s2

    if s1 >= msclip_top1_threshold and gap >= msclip_gap_threshold:
        return GateDecision(False, f"msclip_high_confidence_skip (top1={s1:.3f}, gap={gap:.3f})", s1, gap)

    return GateDecision(True, f"ambiguous_trigger (top1={s1:.3f}, gap={gap:.3f})", s1, gap)

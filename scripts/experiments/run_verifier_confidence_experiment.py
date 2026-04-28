#!/usr/bin/env python
"""Minimal verifier-confidence experiment.

The script is deliberately dependency-light. It consumes existing verifier
sidecars when available, pairs them with IdentificationReport JSON files when
possible, and falls back to synthetic smoke rows so CI/developer machines can
run it without private experiment artifacts.
"""
from __future__ import annotations

import csv
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from schemas.common import Candidate, Spectrum
from schemas.report import CandidateReport, IdentificationReport
from verifier.metrics import compute_claim_metrics
from verifier.schemas import ClaimType, ClaimVerdict, VerifiedClaim, VerifiedIdentification


OUT_CSV = ROOT / "reports" / "verifier_confidence_experiment.csv"


def main() -> None:
    rows = _discover_rows()
    if not rows:
        rows = _synthetic_rows()

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_fieldnames())
        writer.writeheader()
        writer.writerows(rows)

    _print_summary(rows)


def _discover_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    report_paths = _discover_report_paths()
    reports = {p: _load_identification_report(p) for p in report_paths}
    reports = {p: r for p, r in reports.items() if r is not None}

    for sidecar_path in _discover_sidecar_paths():
        verified = _load_verified_identification(sidecar_path)
        if verified is None:
            continue
        report = _nearest_report(sidecar_path, reports)
        rows.append(_row_from_verified(verified, sidecar_path, report))

    # Include report-only rows only when there are no verifier sidecars. They
    # are useful for smoke coverage but do not carry verifier confidence.
    if not rows:
        for path, report in reports.items():
            rows.append(_row_from_report(report, path))
    return rows


def _discover_sidecar_paths() -> list[Path]:
    candidates: list[Path] = []
    for base in (ROOT / "reports", Path("/tmp")):
        if not base.exists():
            continue
        candidates.extend(base.rglob("*verifier*.json"))
        candidates.extend(base.rglob("*sidecar*.json"))
    return _unique_existing(candidates)


def _discover_report_paths() -> list[Path]:
    candidates: list[Path] = []
    for base in (ROOT / "reports", Path("/tmp")):
        if not base.exists():
            continue
        candidates.extend(base.rglob("*report*.json"))
        candidates.extend(base.rglob("*pipeline*.json"))
    return _unique_existing(candidates)


def _unique_existing(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    out: list[Path] = []
    for path in sorted(paths, key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True):
        if path.exists() and path not in seen:
            seen.add(path)
            out.append(path)
    return out


def _load_json(path: Path) -> Any | None:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="utf-8", errors="ignore")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                return None
    return None


def _load_verified_identification(path: Path) -> VerifiedIdentification | None:
    data = _load_json(path)
    if not isinstance(data, dict) or "claims_v1" not in data:
        return None
    try:
        return VerifiedIdentification.model_validate(data)
    except Exception:
        return None


def _load_identification_report(path: Path) -> IdentificationReport | None:
    data = _load_json(path)
    if not isinstance(data, dict) or "candidates" not in data or "experimental_spectrum" not in data:
        return None
    try:
        return IdentificationReport.model_validate(data)
    except Exception:
        return None


def _nearest_report(
    sidecar_path: Path,
    reports: dict[Path, IdentificationReport],
) -> IdentificationReport | None:
    if not reports:
        return None
    side_tokens = _tokens(sidecar_path.stem)
    best: tuple[int, IdentificationReport] | None = None
    for path, report in reports.items():
        score = len(side_tokens & _tokens(path.stem))
        if best is None or score > best[0]:
            best = (score, report)
    return best[1] if best and best[0] > 0 else None


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if t and t not in {"verifier", "report"}}


def _row_from_verified(
    verified: VerifiedIdentification,
    path: Path,
    report: IdentificationReport | None,
) -> dict[str, Any]:
    metrics = verified.claim_metrics or compute_claim_metrics(verified.claims_v1, verified.claims_v2)
    top = report.candidates[0] if report and report.candidates else None
    llm_conf = _extract_llm_self_confidence(
        f"{verified.source_llm_output}\n{verified.rewritten_output}"
    )
    top_name = _top_name(top)
    row = _base_row(
        trace_id=verified.trace_id,
        fixture_name=path.name,
        report=report,
        top_candidate_name=top_name,
        top_candidate_smiles=top.candidate.smiles if top else "",
    )
    row.update(
        {
            "llm_self_confidence": _fmt(llm_conf),
            "verification_confidence": _fmt(metrics.verification_confidence),
            "total_claims": metrics.total_claims,
            "supported_ratio": _fmt(metrics.supported_ratio),
            "claim_precision": _fmt(metrics.claim_precision),
            "contradiction_rate": _fmt(metrics.contradiction_rate),
            "unverifiable_rate": _fmt(metrics.unverifiable_rate),
            "overall_verdict": verified.overall_verdict,
            "correctness_proxy": _correctness_proxy(path.name, top_name, metrics, verified.overall_verdict),
            "notes": "verified_sidecar",
        }
    )
    return row


def _row_from_report(report: IdentificationReport, path: Path) -> dict[str, Any]:
    top = report.candidates[0] if report.candidates else None
    return _base_row(
        trace_id=path.stem,
        fixture_name=path.name,
        report=report,
        top_candidate_name=_top_name(top),
        top_candidate_smiles=top.candidate.smiles if top else "",
        notes="report_only_no_verifier_sidecar",
    )


def _base_row(
    *,
    trace_id: str,
    fixture_name: str,
    report: IdentificationReport | None,
    top_candidate_name: str,
    top_candidate_smiles: str,
    notes: str = "",
) -> dict[str, Any]:
    top = report.candidates[0] if report and report.candidates else None
    return {
        "trace_id": trace_id,
        "fixture_name": fixture_name,
        "top_candidate_name": top_candidate_name,
        "top_candidate_smiles": top_candidate_smiles,
        "llm_self_confidence": "",
        "verification_confidence": "",
        "total_claims": "",
        "supported_ratio": "",
        "claim_precision": "",
        "contradiction_rate": "",
        "unverifiable_rate": "",
        "overall_verdict": "",
        "top1_evidence_score": _fmt(top.evidence_score if top else None),
        "top1_predicted_cosine": _fmt(top.predicted_spectrum_cosine if top else None),
        "n_candidates": len(report.candidates) if report else "",
        "correctness_proxy": "unknown",
        "notes": notes,
    }


def _synthetic_rows() -> list[dict[str, Any]]:
    report = _synthetic_report("Glucose", "OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O")
    claims = [
        VerifiedClaim(
            claim_text="Glucose has formula C6H12O6",
            claim_type=ClaimType.GROUNDED,
            verdict=ClaimVerdict.SUPPORTED,
            evidence="synthetic support",
        ),
        VerifiedClaim(
            claim_text="Glucose is a lipid",
            claim_type=ClaimType.FACTUAL,
            verdict=ClaimVerdict.CONTRADICTED,
            evidence="synthetic contradiction",
        ),
    ]
    metrics = compute_claim_metrics(claims_v1=claims, claims_v2=claims)
    row = _base_row(
        trace_id="synthetic_glucose",
        fixture_name="synthetic",
        report=report,
        top_candidate_name="Glucose",
        top_candidate_smiles=report.candidates[0].candidate.smiles,
    )
    row.update(
        {
            "llm_self_confidence": "0.850000",
            "verification_confidence": _fmt(metrics.verification_confidence),
            "total_claims": metrics.total_claims,
            "supported_ratio": _fmt(metrics.supported_ratio),
            "claim_precision": _fmt(metrics.claim_precision),
            "contradiction_rate": _fmt(metrics.contradiction_rate),
            "unverifiable_rate": _fmt(metrics.unverifiable_rate),
            "overall_verdict": "contradicted",
            "correctness_proxy": "0",
            "notes": "synthetic_smoke",
        }
    )
    return [row]


def _synthetic_report(name: str, smiles: str) -> IdentificationReport:
    return IdentificationReport(
        experimental_spectrum=Spectrum(
            mz=[100.0, 120.0, 140.0],
            intensity=[1.0, 0.5, 0.25],
            precursor_mz=181.0707,
            adduct="[M+H]+",
            ionization_mode="positive",
            collision_energy=20.0,
        ),
        preprocess_quality_flag="sparse",
        neutral_mass_computed=180.0634,
        n_prefilter_candidates=1,
        n_library_candidates=1,
        n_generated_candidates=0,
        candidates=[
            CandidateReport(
                candidate=Candidate(
                    smiles=smiles,
                    name=name,
                    source="library",
                    score=0.9,
                    source_id="synthetic",
                    explain="synthetic smoke candidate",
                ),
                prefilter_match=None,
                metabolite_info=None,
                pathway_context=None,
                predicted_spectrum_cosine=0.8,
                predicted_model_version="synthetic",
                mass_match_indicator=1.0,
                pathway_presence_indicator=0.0,
                evidence_score=0.8,
                notes=[],
            )
        ],
        pipeline_version="synthetic",
        tool_versions={},
        warnings=[],
    )


def _top_name(top: CandidateReport | None) -> str:
    if top is None:
        return ""
    if top.candidate.name:
        return top.candidate.name
    if top.metabolite_info and top.metabolite_info.primary_name:
        return top.metabolite_info.primary_name
    return ""


def _extract_llm_self_confidence(text: str) -> float | None:
    numeric = re.search(
        r"\bconfidence(?:\s+score)?\s*[:=]\s*(\d+(?:\.\d+)?)(\s*%)?",
        text,
        re.IGNORECASE,
    )
    if numeric:
        value = float(numeric.group(1))
        if numeric.group(2) or value > 1:
            value /= 100.0
        return max(0.0, min(1.0, value))
    low = text.lower()
    if re.search(r"\bhigh confidence\b", low):
        return 0.85
    if re.search(r"\bmedium confidence\b", low):
        return 0.55
    if re.search(r"\blow confidence\b", low):
        return 0.25
    return None


def _correctness_proxy(
    fixture_name: str,
    top_candidate_name: str,
    metrics: Any,
    overall_verdict: str,
) -> str:
    low = fixture_name.lower()
    top = top_candidate_name.lower()
    for truth in ("caffeine", "glucose", "l-carnitine", "lcarnitine"):
        if truth in low:
            if not top:
                return "unknown"
            canonical = "l-carnitine" if truth == "lcarnitine" else truth
            return "1" if canonical in top else "0"
    if (
        overall_verdict in {"verified", "partially_verified"}
        and (metrics.contradiction_rate or 0.0) == 0.0
        and (metrics.claim_precision or 0.0) >= 0.8
    ):
        return "likely_correct"
    if (metrics.contradiction_rate or 0.0) > 0.1:
        return "likely_problematic"
    return "unknown"


def _print_summary(rows: list[dict[str, Any]]) -> None:
    numeric_conf = [_float_or_none(r["verification_confidence"]) for r in rows]
    numeric_conf = [v for v in numeric_conf if v is not None]
    llm_conf = [_float_or_none(r["llm_self_confidence"]) for r in rows]
    llm_conf = [v for v in llm_conf if v is not None]

    print(f"wrote: {OUT_CSV}")
    print(f"n cases: {len(rows)}")
    print(f"n with llm_self_confidence: {len(llm_conf)}")
    print(f"n with verification_confidence: {len(numeric_conf)}")

    pairs = [
        (_float_or_none(r["verification_confidence"]), _float_or_none(r["correctness_proxy"]))
        for r in rows
    ]
    pairs = [(x, y) for x, y in pairs if x is not None and y is not None]
    if len(pairs) >= 2:
        xs, ys = zip(*pairs)
        pearson = _pearson(xs, ys)
        spearman = _spearman(xs, ys)
        if pearson is None or spearman is None:
            print("Pearson/Spearman: insufficient variance in numeric correctness_proxy")
        else:
            print(f"Pearson(confidence, correctness_proxy): {_fmt(pearson)}")
            print(f"Spearman(confidence, correctness_proxy): {_fmt(spearman)}")
    else:
        print("Pearson/Spearman: insufficient numeric correctness_proxy")

    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        conf = _float_or_none(row["verification_confidence"])
        if conf is not None:
            grouped[str(row["correctness_proxy"])].append(conf)
    if grouped:
        print("average verification_confidence by correctness_proxy:")
        for key, values in sorted(grouped.items()):
            print(f"  {key}: {_fmt(mean(values))} (n={len(values)})")

    top_bad = sorted(
        rows,
        key=lambda r: _float_or_none(r["contradiction_rate"]) or 0.0,
        reverse=True,
    )[:5]
    print("top contradiction_rate cases:")
    for row in top_bad:
        print(
            f"  {row['fixture_name']}: contradiction_rate={row['contradiction_rate']} "
            f"verification_confidence={row['verification_confidence']}"
        )


def _pearson(xs: tuple[float, ...], ys: tuple[float, ...]) -> float | None:
    if len(xs) < 2:
        return None
    mx, my = mean(xs), mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den_x = math.sqrt(sum((x - mx) ** 2 for x in xs))
    den_y = math.sqrt(sum((y - my) ** 2 for y in ys))
    if den_x == 0 or den_y == 0:
        return None
    return num / (den_x * den_y)


def _spearman(xs: tuple[float, ...], ys: tuple[float, ...]) -> float | None:
    return _pearson(tuple(_ranks(xs)), tuple(_ranks(ys)))


def _ranks(values: tuple[float, ...]) -> list[float]:
    ordered = sorted((v, i) for i, v in enumerate(values))
    ranks = [0.0] * len(values)
    for rank, (_, idx) in enumerate(ordered, start=1):
        ranks[idx] = float(rank)
    return ranks


def _float_or_none(value: Any) -> float | None:
    if value in ("", None):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.6f}"


def _fieldnames() -> list[str]:
    return [
        "trace_id",
        "fixture_name",
        "top_candidate_name",
        "top_candidate_smiles",
        "llm_self_confidence",
        "verification_confidence",
        "total_claims",
        "supported_ratio",
        "claim_precision",
        "contradiction_rate",
        "unverifiable_rate",
        "overall_verdict",
        "top1_evidence_score",
        "top1_predicted_cosine",
        "n_candidates",
        "correctness_proxy",
        "notes",
    ]


if __name__ == "__main__":
    main()

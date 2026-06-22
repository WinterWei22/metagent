from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PathwayPredictionEntry:
    pathway_id: str = ""
    pathway_name: str = ""
    pathway_source: str = ""
    confidence: float | None = None
    evidence_methods: list[str] = field(default_factory=list)
    supporting_claim_indices: list[int] = field(default_factory=list)
    rationale: str = ""


@dataclass(frozen=True)
class PathwayPrediction:
    primary: PathwayPredictionEntry | None
    alternatives: list[PathwayPredictionEntry]
    abstain: bool
    abstain_reason: str | None


@dataclass(frozen=True)
class PathwayPredictionParseResult:
    ok: bool
    value: PathwayPrediction | None
    error: str = ""
    degraded: bool = False


SECOND_PASS_SYSTEM_PROMPT = (
    "You are a precise pathway prediction selector. You receive a fixed "
    "metabolomics narrative and a fixed claims[] array that has already been "
    "written by another step. Do not rewrite, add, remove, or renumber claims. "
    "Choose the most likely primary pathway only from the evidence in those "
    "claims. Return only one JSON object with keys: primary, alternatives, "
    "abstain, abstain_reason. supporting_claim_indices must be zero-based "
    "indexes into the provided claims array. confidence is only an ordering "
    "cue, not a calibrated probability."
)


STOPWORDS = {
    "and",
    "of",
    "the",
    "a",
    "an",
    "in",
    "by",
    "via",
    "pathway",
    "pathways",
    "metabolism",
    "metabolic",
    "biosynthesis",
    "synthesis",
    "degradation",
    "catabolism",
}

SYNONYM_GROUPS = [
    {"arachidonic", "eicosanoid", "prostaglandin", "leukotriene", "thromboxane"},
    {"vitamin", "riboflavin", "b2"},
    {"vitamin", "pyridoxine", "pyridoxal", "b6"},
    {"folate", "one", "carbon", "tetrahydrofolate"},
    {"tca", "tricarboxylic", "citrate"},
    {"bile", "acid", "primary"},
    {"fatty", "acid", "de", "novo"},
    {"cholesterol", "bloch", "desmosterol"},
    {"glycine", "serine", "threonine"},
    {"valine", "leucine", "isoleucine", "branched"},
    {"sphingolipid", "glycosphingolipid", "ceramide"},
]


def parse_pathway_prediction_contract(payload: dict[str, Any]) -> PathwayPredictionParseResult:
    if not isinstance(payload, dict):
        return _degraded("payload is not an object")
    claims = payload.get("claims")
    if not isinstance(claims, list):
        claims = []
    raw = payload.get("pathway_prediction")
    if raw is None:
        return _degraded("missing pathway_prediction")
    if not isinstance(raw, dict):
        return _degraded("pathway_prediction is not an object")
    if "pathway_prediction" in raw and "primary" not in raw:
        nested = raw.get("pathway_prediction")
        if not isinstance(nested, dict):
            return _degraded("nested pathway_prediction is not an object")
        raw = nested
    raw = _normalize_prediction_shape(raw)

    abstain = bool(raw.get("abstain"))
    alternatives_raw = raw.get("alternatives")
    alternatives_raw = alternatives_raw if isinstance(alternatives_raw, list) else []
    primary_raw = raw.get("primary")

    if abstain:
        if primary_raw is not None or alternatives_raw:
            return _degraded("abstain=true requires primary=null and alternatives=[]")
        reason = raw.get("abstain_reason")
        if not isinstance(reason, str) or not reason.strip():
            return _degraded("abstain=true requires non-empty abstain_reason")
        return PathwayPredictionParseResult(
            ok=True,
            value=PathwayPrediction(
                primary=None,
                alternatives=[],
                abstain=True,
                abstain_reason=reason.strip(),
            ),
        )

    if not isinstance(primary_raw, dict):
        return _degraded("pathway_prediction.primary is missing or not an object")
    primary = _parse_entry(primary_raw, "primary")
    if primary is None:
        return _degraded("pathway_prediction.primary is malformed")
    alternatives: list[PathwayPredictionEntry] = []
    for idx, alt_raw in enumerate(alternatives_raw):
        if not isinstance(alt_raw, dict):
            return _degraded(f"alternatives[{idx}] is not an object")
        alt = _parse_entry(alt_raw, f"alternatives[{idx}]")
        if alt is None:
            return _degraded(f"alternatives[{idx}] is malformed")
        alternatives.append(alt)
    primary = _sanitize_supporting_indices(primary, len(claims))
    alternatives = [
        _sanitize_supporting_indices(entry, len(claims)) for entry in alternatives
    ]
    return PathwayPredictionParseResult(
        ok=True,
        value=PathwayPrediction(
            primary=primary,
            alternatives=alternatives,
            abstain=False,
            abstain_reason=_optional_str(raw.get("abstain_reason")),
        ),
    )


def coerce_pathway_prediction_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    parsed = parse_pathway_prediction_contract(payload)
    if not parsed.ok or parsed.value is None:
        return None
    return pathway_prediction_to_dict(parsed.value)


def generate_pathway_prediction_second_pass(
    *,
    claims: list[dict[str, Any]],
    narrative_text: str,
    chat_fn: Any,
    model: str,
    provider: str,
    trace_id: str | None = None,
) -> dict[str, Any] | None:
    """Ask an LLM to choose pathway_prediction from fixed claims.

    This deliberately runs after the main ReAct final JSON is parsed so the
    extra pathway contract cannot compete with claim generation budget.
    """
    if not claims:
        return None
    payload = {
        "narrative_text": narrative_text,
        "claims": claims,
    }
    user = (
        "Given this fixed final report payload, return only the "
        "pathway_prediction JSON object. Do not include narrative_text or "
        "claims in your response.\n\n"
        f"{json.dumps(payload, ensure_ascii=False, default=str)}"
    )
    try:
        content = chat_fn(
            [
                {"role": "system", "content": SECOND_PASS_SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            temperature=0.0,
            max_tokens=2048,
            model=model,
            provider=provider,
            trace_id=trace_id,
            caller="concord.pathway_prediction.second_pass",
            response_format={"type": "json_object"},
        )
    except Exception:
        return None
    raw = _extract_json_object(content)
    if raw is None:
        return None
    try:
        prediction = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(prediction, dict):
        return None
    parsed = parse_pathway_prediction_contract({
        "narrative_text": narrative_text,
        "claims": claims,
        "pathway_prediction": prediction,
    })
    if not parsed.ok or parsed.value is None:
        return None
    return pathway_prediction_to_dict(parsed.value)


def pathway_prediction_to_dict(prediction: PathwayPrediction) -> dict[str, Any]:
    return {
        "primary": _entry_to_dict(prediction.primary) if prediction.primary else None,
        "alternatives": [_entry_to_dict(entry) for entry in prediction.alternatives],
        "abstain": prediction.abstain,
        "abstain_reason": prediction.abstain_reason,
    }


def compute_pathway_prediction_metrics(
    payload: dict[str, Any],
    *,
    ground_truth_pathway_id: str = "",
    ground_truth_pathway_name: str = "",
    supported_claim_indices: set[int] | None = None,
    claim_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parsed = parse_pathway_prediction_contract(payload)
    supported_claim_indices = supported_claim_indices or set()
    metrics: dict[str, Any] = {
        "pathway_prediction_ok": parsed.ok,
        "pathway_prediction_error": parsed.error,
        "primary_id_exact": False,
        "primary_name_exact": False,
        "primary_semantic_match": False,
        "topk_id_exact": False,
        "topk_name_exact": False,
        "topk_semantic_match": False,
        "verifier_supported_primary": False,
        "verifier_supported_topk": False,
        "abstain": False,
        "claim_metrics": dict(claim_metrics or {}),
    }
    if not parsed.ok or parsed.value is None:
        return metrics
    prediction = parsed.value
    metrics["abstain"] = prediction.abstain
    entries = [e for e in [prediction.primary, *prediction.alternatives] if e is not None]
    primary = prediction.primary
    if primary is not None:
        metrics["primary_id_exact"] = _id_exact(primary.pathway_id, ground_truth_pathway_id)
        metrics["primary_name_exact"] = _name_exact(primary.pathway_name, ground_truth_pathway_name)
        metrics["primary_semantic_match"] = pathway_semantic_match(
            ground_truth_pathway_name, primary.pathway_name
        )
        metrics["verifier_supported_primary"] = bool(
            set(primary.supporting_claim_indices) & supported_claim_indices
        )
    metrics["topk_id_exact"] = any(_id_exact(e.pathway_id, ground_truth_pathway_id) for e in entries)
    metrics["topk_name_exact"] = any(_name_exact(e.pathway_name, ground_truth_pathway_name) for e in entries)
    metrics["topk_semantic_match"] = any(
        pathway_semantic_match(ground_truth_pathway_name, e.pathway_name) for e in entries
    )
    metrics["verifier_supported_topk"] = any(
        bool(set(e.supporting_claim_indices) & supported_claim_indices) for e in entries
    )
    return metrics


def pathway_semantic_match(ground_truth_name: str, predicted_name: str) -> bool:
    """Single rubric for pathway semantic matching.

    Count as a match: exact normalized names, clear synonyms, and a primary
    biochemical subset that denotes the main cascade. Do not count broad
    merged parent classes that add extra pathway families. If the ground truth
    itself names a collection, require the prediction to cover the collection's
    named components rather than only one component.
    """
    gt_norm = norm_name(ground_truth_name)
    pred_norm = norm_name(predicted_name)
    if not gt_norm or not pred_norm:
        return False
    if gt_norm == pred_norm:
        return True
    if _is_known_broad_merge(gt_norm, pred_norm):
        return False
    if _collection_gt_undercovered(gt_norm, pred_norm):
        return False
    if len(gt_norm) >= 8 and gt_norm in pred_norm:
        return True
    if len(pred_norm) >= 8 and pred_norm in gt_norm:
        return True

    gt_tokens = tokens(ground_truth_name)
    pred_tokens = tokens(predicted_name)
    if not gt_tokens or not pred_tokens:
        return False
    if any(gt_tokens & group and pred_tokens & group for group in SYNONYM_GROUPS):
        return True
    overlap = gt_tokens & pred_tokens
    if overlap and len(overlap) / min(len(gt_tokens), len(pred_tokens)) >= 0.80:
        return True
    return False


def norm_name(value: str | None) -> str:
    text = (value or "").lower()
    text = re.sub(r"\b(?:kegg|map|hsa|rno|mmu|wp|reactome|smpdb|mumm):?\d*\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def tokens(value: str | None) -> set[str]:
    return {tok for tok in norm_name(value).split() if tok not in STOPWORDS and len(tok) > 1}


def _parse_entry(raw: dict[str, Any], label: str) -> PathwayPredictionEntry | None:
    del label
    name = _optional_str(raw.get("pathway_name"))
    pathway_id = _optional_str(raw.get("pathway_id"))
    if not name and not pathway_id:
        return None
    indices = raw.get("supporting_claim_indices")
    if indices is None:
        indices = []
    if not isinstance(indices, list) or any(
        not isinstance(idx, int) or idx < 0 for idx in indices
    ):
        return None
    methods = raw.get("evidence_methods")
    if methods is None:
        methods = []
    if not isinstance(methods, list):
        return None
    confidence = raw.get("confidence")
    confidence_float: float | None = None
    if confidence is not None:
        try:
            confidence_float = max(0.0, min(1.0, float(confidence)))
        except (TypeError, ValueError):
            confidence_float = None
    return PathwayPredictionEntry(
        pathway_id=pathway_id,
        pathway_name=name,
        pathway_source=_optional_str(raw.get("pathway_source")),
        confidence=confidence_float,
        evidence_methods=[str(method) for method in methods],
        supporting_claim_indices=list(indices),
        rationale=_optional_str(raw.get("rationale")),
    )


def _normalize_prediction_shape(raw: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(raw)
    primary = raw.get("primary")
    if isinstance(primary, str):
        normalized["primary"] = {
            "pathway_id": _optional_str(raw.get("primary_pathway_id") or raw.get("pathway_id")),
            "pathway_name": primary,
            "pathway_source": _optional_str(raw.get("primary_pathway_source") or raw.get("pathway_source")),
            "confidence": raw.get("confidence"),
            "evidence_methods": raw.get("evidence_methods") or [],
            "supporting_claim_indices": raw.get("supporting_claim_indices") or [],
            "rationale": _optional_str(raw.get("rationale")),
        }
    alternatives = normalized.get("alternatives")
    if isinstance(alternatives, list):
        normalized["alternatives"] = [
            {"pathway_name": alt, "supporting_claim_indices": []}
            if isinstance(alt, str)
            else alt
            for alt in alternatives
        ]
    return normalized


def _sanitize_supporting_indices(
    entry: PathwayPredictionEntry,
    claim_count: int,
) -> PathwayPredictionEntry:
    if claim_count <= 0:
        valid_indices: list[int] = []
    else:
        valid_indices = [
            idx for idx in entry.supporting_claim_indices if idx < claim_count
        ]
    if valid_indices == entry.supporting_claim_indices:
        return entry
    return PathwayPredictionEntry(
        pathway_id=entry.pathway_id,
        pathway_name=entry.pathway_name,
        pathway_source=entry.pathway_source,
        confidence=entry.confidence,
        evidence_methods=list(entry.evidence_methods),
        supporting_claim_indices=valid_indices,
        rationale=entry.rationale,
    )


def _entry_to_dict(entry: PathwayPredictionEntry) -> dict[str, Any]:
    return {
        "pathway_id": entry.pathway_id,
        "pathway_name": entry.pathway_name,
        "pathway_source": entry.pathway_source,
        "confidence": entry.confidence,
        "evidence_methods": list(entry.evidence_methods),
        "supporting_claim_indices": list(entry.supporting_claim_indices),
        "rationale": entry.rationale,
    }


def _optional_str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _id_exact(predicted: str, ground_truth: str) -> bool:
    return bool(predicted and ground_truth and predicted.strip() == ground_truth.strip())


def _name_exact(predicted: str, ground_truth: str) -> bool:
    return bool(norm_name(predicted) and norm_name(predicted) == norm_name(ground_truth))


def _degraded(error: str) -> PathwayPredictionParseResult:
    return PathwayPredictionParseResult(ok=False, value=None, error=error, degraded=True)


def _extract_json_object(text: str | None) -> str | None:
    if not text:
        return None
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        parsed = json.loads(stripped)
        return json.dumps(parsed, ensure_ascii=False)
    except json.JSONDecodeError:
        pass
    start = stripped.find("{")
    end = stripped.rfind("}")
    if 0 <= start < end:
        return stripped[start : end + 1]
    return None


def _is_known_broad_merge(gt_norm: str, pred_norm: str) -> bool:
    broad_pairs = [
        ("urea cycle", "urea cycle amino group metabolism"),
        ("androgen metabolism", "androgen estrogen biosynthesis metabolism"),
    ]
    return any(gt_norm == gt and pred_norm == pred for gt, pred in broad_pairs)


def _collection_gt_undercovered(gt_norm: str, pred_norm: str) -> bool:
    if " and " not in gt_norm:
        return False
    gt_tokens = tokens(gt_norm)
    pred_tokens = tokens(pred_norm)
    if len(gt_tokens) < 2:
        return False
    return not gt_tokens.issubset(pred_tokens)


def driver_pr_metrics(
    predicted_ids: set[str],
    gold_ids: set[str] | None,
) -> dict[str, Any] | None:
    """Driver precision/recall on a shared identity key (RAMP_C ids).
    Returns None for N/A strata (gold_ids is None)."""
    if gold_ids is None:
        return None
    hit = predicted_ids & gold_ids
    precision = (
        (len(hit) / len(predicted_ids))
        if predicted_ids
        else (1.0 if not gold_ids else 0.0)
    )
    recall = (len(hit) / len(gold_ids)) if gold_ids else 1.0
    return {
        "precision": precision,
        "recall": recall,
        "n_predicted": len(predicted_ids),
        "n_gold": len(gold_ids),
        "n_hit": len(hit),
    }


def pathway_recall_metrics(
    predicted_names: list[str],
    relevant_names: set[str],
    *,
    k: int = 3,
) -> dict[str, Any]:
    """recall@k / hit@k / MRR of ordered predicted pathway names against a
    relevant-name set. All comparisons are on norm_name."""
    rel = {norm_name(n) for n in relevant_names if n}
    topk = [norm_name(n) for n in predicted_names[:k] if n]
    retrieved = {n for n in topk if n in rel}
    recall_at_k = (len(retrieved) / len(rel)) if rel else 0.0
    hit_at_k = bool(retrieved)
    mrr = 0.0
    for idx, name in enumerate(topk, start=1):
        if name in rel:
            mrr = 1.0 / idx
            break
    return {
        "recall_at_k": recall_at_k,
        "hit_at_k": hit_at_k,
        "mrr": mrr,
        "n_relevant": len(rel),
        "n_predicted_considered": len(topk),
    }

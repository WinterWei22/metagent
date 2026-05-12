"""Phase 6.3: LLM-as-reranker for Sub-6A real-id v2.

Single LLM call that produces:
  (a) selected top-1 SMILES (re-ranked from top-K candidates),
  (b) free-text justification,
  (c) structured peak_claims (mz + neutral-loss assignments) for Layer F.

The justification + peak_claims fields together become the spectrum's
narrative — the LLM call is BOTH the reranker and the narrative writer
(single LLM call per spectrum, in line with Sub-6B / Sub-6A perfect tracks).

Inputs are assembled in :func:`build_reranker_messages` from a Spectrum
plus a list of candidate-evidence dicts that the upstream pipeline pulls
out of Phase 6.2's peak_evidence cache (or recomputes for new SMILES).

Output is a strict JSON schema that the parser tolerates with retry on
parse failure and a final fall-back of "selected_top1_index = 0" so a
malformed LLM response cannot kill the run.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


# Cap how many predicted-peaks we send per candidate to keep token budget
# in check. Single-spectrum prompts stay under ~3K tokens with this cap.
_CFMID_TOP_PEAKS_IN_PROMPT = 10
_EXPERIMENTAL_TOP_PEAKS_IN_PROMPT = 15


_SYSTEM_PROMPT = (
    "You are an MS/MS metabolite identification assistant. Given an "
    "experimental spectrum and a small list of candidate molecules with "
    "multi-tool evidence (modified cosine, MS-CLIP score, SIRIUS top-1 "
    "formula match, CFM-ID predicted spectrum cosine, mass match), pick "
    "the single most likely candidate and justify the choice with concrete "
    "peak-level reasoning.\n"
    "\n"
    "Always reply with a single JSON object matching this schema:\n"
    "{\n"
    "  \"selected_top1_index\": int,        // 0-based index into candidates\n"
    "  \"selected_top1_smiles\": str,\n"
    "  \"ranked_indices\": list[int],       // ALL candidate 0-based indices, in YOUR preferred order (best→worst); must be a permutation\n"
    "  \"confidence\": \"low\" | \"medium\" | \"high\",\n"
    "  \"justification\": str,              // 2-4 sentences citing concrete evidence\n"
    "  \"peak_claims\": list[str]           // each claim of form 'm/z X.XXXX corresponds to <fragment/loss>'\n"
    "}\n"
    "\n"
    "Rules:\n"
    "- Cite the candidate by its 0-based index AND the SMILES.\n"
    "- ranked_indices MUST be a permutation of ALL candidate indices (no repeats, no omissions); the first element MUST equal selected_top1_index.\n"
    "- Justification MUST reference at least one numeric SIRIUS or CFM-ID match.\n"
    "- peak_claims MUST contain >=1 entry of form 'm/z N.NNNN corresponds to "
    "loss of X' (or 'fragment of X', or 'arises from X'). These are consumed "
    "by an automated peak-mechanistic verifier.\n"
    "- Output JSON only — no markdown fences, no commentary outside the object."
)


@dataclass
class LlmRerankResult:
    selected_top1_index: int
    selected_top1_smiles: str
    confidence: str  # "low" | "medium" | "high"
    justification: str
    peak_claims: list[str]
    raw_llm_output: str
    parse_error: str | None = None
    fallback_used: bool = False
    # Phase 6.7-A: LLM's preferred ordering over the full candidate set
    # (length == len(candidates_with_evidence), permutation of 0..N-1).
    # ranked_indices[0] == selected_top1_index by validation. When the LLM
    # output omits this field or emits an invalid permutation, falls back to
    # primary-retriever order with selected_top1_index moved to position 0.
    ranked_indices: list[int] | None = None


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------


def _format_experimental_peaks(peaks: list[list[float]]) -> list[list[float]]:
    """Sort peaks by intensity desc, take top-N, round, keep format compact."""
    if not peaks:
        return []
    sorted_peaks = sorted(peaks, key=lambda p: -p[1])[:_EXPERIMENTAL_TOP_PEAKS_IN_PROMPT]
    return [[round(mz, 4), round(intensity, 4)] for mz, intensity in sorted_peaks]


def _format_cfmid_peaks(peaks: list[list]) -> list[list]:
    """Cap CFM-ID predicted peaks to top-N by intensity to bound tokens."""
    if not peaks:
        return []
    # CFM peak rows can be [mz, intensity] or [mz, intensity, smiles_or_neutral_loss]
    sorted_peaks = sorted(peaks, key=lambda p: -p[1])[:_CFMID_TOP_PEAKS_IN_PROMPT]
    out = []
    for p in sorted_peaks:
        row = [round(p[0], 4), round(p[1], 4)]
        if len(p) >= 3 and p[2]:
            row.append(p[2])
        out.append(row)
    return out


def build_reranker_messages(
    spectrum_meta: dict[str, Any],
    candidates_with_evidence: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Build the chat messages for the LLM-as-reranker call.

    Args:
      spectrum_meta: dict with keys ``spectrum_id``, ``precursor_mz``,
        ``ion_mode``, ``adduct``, ``experimental_peaks`` (list of [mz, int]).
      candidates_with_evidence: list of dicts, one per candidate; expected
        keys ``smiles``, ``name``, ``formula``, ``modcos``, ``msclip``,
        ``primary_retriever_score``, ``primary_retriever``, ``rank_after_primary``,
        ``sirius_top1_formula``, ``sirius_formula_match``, ``cfmid_top_peaks``
        (already capped by caller), ``cfmid_cosine_vs_experimental``,
        ``mass_match``.
    """
    user_payload = {
        "experimental_spectrum": {
            "spectrum_id": spectrum_meta.get("spectrum_id", ""),
            "precursor_mz": round(float(spectrum_meta.get("precursor_mz", 0.0)), 4),
            "ion_mode": spectrum_meta.get("ion_mode", ""),
            "adduct": spectrum_meta.get("adduct", ""),
            "top_peaks": _format_experimental_peaks(spectrum_meta.get("experimental_peaks", [])),
        },
        "candidates": [
            {
                "rank_after_primary": int(c.get("rank_after_primary", i)),
                "smiles": c.get("smiles", ""),
                "name": c.get("name", ""),
                "molecular_formula": c.get("formula", ""),
                "primary_retriever": c.get("primary_retriever", ""),
                "primary_retriever_score": round(float(c.get("primary_retriever_score") or 0.0), 4),
                "modcos": (None if c.get("modcos") is None else round(float(c["modcos"]), 4)),
                "msclip": (None if c.get("msclip") is None else round(float(c["msclip"]), 4)),
                "mass_match": round(float(c.get("mass_match", 0.0)), 4),
                "sirius_top1_formula": c.get("sirius_top1_formula"),
                "sirius_formula_match": bool(c.get("sirius_formula_match", False)),
                "cfmid_cosine_vs_experimental": (
                    None if c.get("cfmid_cosine_vs_experimental") is None
                    else round(float(c["cfmid_cosine_vs_experimental"]), 4)
                ),
                "cfmid_top_peaks": _format_cfmid_peaks(c.get("cfmid_top_peaks") or []),
            }
            for i, c in enumerate(candidates_with_evidence)
        ],
    }
    user_text = (
        "Identify the most likely candidate for this MS/MS spectrum.\n\n"
        f"```json\n{json.dumps(user_payload, ensure_ascii=False)}\n```\n\n"
        "Reply with a single JSON object per the schema in the system prompt."
    )
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_text},
    ]


# ---------------------------------------------------------------------------
# Output parser
# ---------------------------------------------------------------------------


_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)
# Phase 6.7 defensive additions — handle Opus-4-7 wrapping behaviors.
_THINKING_TAG_RE = re.compile(
    r"<(thinking|analysis|reasoning|scratchpad)>.*?</\1>",
    re.DOTALL | re.IGNORECASE,
)
_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def parse_reranker_response(raw: str) -> tuple[dict[str, Any] | None, str | None]:
    """Robustly extract the LLM's JSON. Returns (parsed_dict, error_msg).

    Tolerates: bare JSON, JSON wrapped in ``` fences anywhere in the
    response, JSON preceded by an Anthropic-style <thinking>...</thinking>
    block (which often itself contains a literal '{' that the greedy
    brace-finder would otherwise mis-match).
    """
    if not raw:
        return None, "empty response"
    text = raw.strip()
    # Strip Opus/Anthropic-style hidden-reasoning blocks BEFORE searching for
    # JSON — those frequently contain stray '{' that confuse brace matching.
    text = _THINKING_TAG_RE.sub("", text).strip()
    # If a fenced JSON block exists anywhere, prefer it (handles "Here is
    # the result: ```json {...} ```").
    fenced = _FENCED_JSON_RE.search(text)
    if fenced:
        try:
            return json.loads(fenced.group(1)), None
        except Exception:
            pass
    # Legacy edge-strip (`^```json … ```$`).
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    # Try direct parse.
    try:
        return json.loads(text), None
    except Exception:
        pass
    # Fallback: greedy first-to-last brace match.
    m = _JSON_BLOCK_RE.search(text)
    if not m:
        return None, "no JSON object found"
    try:
        return json.loads(m.group(0)), None
    except Exception as exc:
        return None, f"json decode failed: {exc}"


def _validate_and_normalize(
    parsed: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> tuple[LlmRerankResult | None, str | None]:
    """Coerce into LlmRerankResult or return validation error."""
    if not isinstance(parsed, dict):
        return None, "parsed JSON not a dict"
    idx = parsed.get("selected_top1_index")
    smiles = parsed.get("selected_top1_smiles")
    if not isinstance(idx, int):
        return None, f"selected_top1_index not int: {idx!r}"
    if idx < 0 or idx >= len(candidates):
        return None, f"selected_top1_index {idx} out of range 0..{len(candidates)-1}"
    if not isinstance(smiles, str) or not smiles:
        return None, "selected_top1_smiles missing"
    confidence = parsed.get("confidence", "low")
    if confidence not in ("low", "medium", "high"):
        confidence = "low"
    justification = str(parsed.get("justification", ""))
    peak_claims = parsed.get("peak_claims") or []
    if not isinstance(peak_claims, list):
        peak_claims = []
    peak_claims = [str(p) for p in peak_claims if p]
    # Phase 6.7-A: ranked_indices — full ordered permutation of candidate
    # indices. Validation tolerant (best-effort recovery rather than hard
    # fail) since the field is new and absent from older prompts.
    ranked = _coerce_ranked_indices(parsed.get("ranked_indices"), idx, len(candidates))
    return LlmRerankResult(
        selected_top1_index=idx,
        selected_top1_smiles=smiles,
        confidence=confidence,
        justification=justification,
        peak_claims=peak_claims,
        raw_llm_output="",
        ranked_indices=ranked,
    ), None


def _coerce_ranked_indices(raw, top1_idx: int, n: int) -> list[int]:
    """Return a valid permutation of ``range(n)`` derived from raw LLM output.

    Recovery rules (best-effort, never fail-out):
      - Missing / wrong-typed → primary order with top1_idx pushed to front.
      - Valid permutation → returned with top1_idx forced into position 0 if
        the LLM disagreed with its own selected_top1_index (rare).
      - Partial / duplicate-y list → de-dup keeping first occurrence, append
        missing indices in primary order; truncate to n.
    """
    if not isinstance(raw, list):
        return _primary_order_with_top1(top1_idx, n)
    seen: list[int] = []
    seen_set: set[int] = set()
    for v in raw:
        if not isinstance(v, int):
            continue
        if v < 0 or v >= n or v in seen_set:
            continue
        seen.append(v)
        seen_set.add(v)
    # Append any indices the LLM omitted, in primary order.
    for i in range(n):
        if i not in seen_set:
            seen.append(i)
            seen_set.add(i)
    # Force consistency with selected_top1_index.
    if seen and seen[0] != top1_idx:
        seen.remove(top1_idx)
        seen.insert(0, top1_idx)
    return seen


def _primary_order_with_top1(top1_idx: int, n: int) -> list[int]:
    order = [i for i in range(n) if i != top1_idx]
    return [top1_idx] + order


def llm_rerank(
    spectrum_meta: dict[str, Any],
    candidates_with_evidence: list[dict[str, Any]],
    *,
    chat_fn: Callable[..., str],
    chat_kwargs: dict[str, Any] | None = None,
    max_retries: int = 1,
) -> LlmRerankResult:
    """One LLM call (with one retry on parse failure) → LlmRerankResult.

    On unrecoverable failure the function falls back to selecting the
    primary-retriever rank-1 candidate with low confidence and an explicit
    "fallback_used=True" flag. This keeps a 459-spectrum batch from dying
    on a single malformed LLM response.
    """
    if not candidates_with_evidence:
        return LlmRerankResult(
            selected_top1_index=0, selected_top1_smiles="",
            confidence="low", justification="no candidates", peak_claims=[],
            raw_llm_output="", parse_error="no candidates", fallback_used=True,
            ranked_indices=[],
        )

    messages = build_reranker_messages(spectrum_meta, candidates_with_evidence)
    chat_kwargs = chat_kwargs or {}

    last_err: str | None = None
    raw = ""
    for attempt in range(max_retries + 1):
        try:
            raw = chat_fn(messages, **chat_kwargs)
        except Exception as exc:  # noqa: BLE001
            last_err = f"chat_fn error: {type(exc).__name__}: {exc}"
            logger.warning("llm_rerank attempt %d chat_fn failed: %s", attempt + 1, exc)
            continue
        parsed, perr = parse_reranker_response(raw)
        if parsed is None:
            last_err = perr
            logger.warning("llm_rerank attempt %d parse error: %s", attempt + 1, perr)
            continue
        result, verr = _validate_and_normalize(parsed, candidates_with_evidence)
        if result is None:
            last_err = verr
            logger.warning("llm_rerank attempt %d validation error: %s", attempt + 1, verr)
            continue
        result.raw_llm_output = raw
        return result

    # Fallback: trust primary-retriever top-1
    fallback = candidates_with_evidence[0]
    return LlmRerankResult(
        selected_top1_index=0,
        selected_top1_smiles=fallback.get("smiles", ""),
        confidence="low",
        justification=f"LLM rerank fell back to primary retriever top-1 ({fallback.get('name', '?')}); reason: {last_err}",
        peak_claims=[],
        raw_llm_output=raw,
        parse_error=last_err,
        fallback_used=True,
        ranked_indices=list(range(len(candidates_with_evidence))),
    )


def render_narrative(spectrum_meta: dict[str, Any], result: LlmRerankResult) -> str:
    """Convert the LLM reranker output into a narrative string suitable for
    the Sub-6A narratives JSONL + downstream verifier extraction."""
    lines = []
    sid = spectrum_meta.get("spectrum_id", "?")
    lines.append(f"Spectrum {sid} (precursor m/z {spectrum_meta.get('precursor_mz', '?')}).")
    lines.append(f"Selected top-1: {result.selected_top1_smiles} (confidence: {result.confidence}).")
    if result.justification:
        lines.append("Justification: " + result.justification)
    if result.peak_claims:
        lines.append("Peak-level claims:")
        for claim in result.peak_claims:
            lines.append(f"  - {claim}")
    if result.fallback_used:
        lines.append("(Note: LLM reranker fell back to primary-retriever top-1 due to a parse/validation failure.)")
    return "\n".join(lines)

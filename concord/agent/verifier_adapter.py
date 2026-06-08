"""ConcordMet ↔ B1-verifier boundary adapter (W8 D4 sub-task 1).

Three conversion functions live here, each a pure-fn pivot at the
interface between ConcordReactRunner output and B1's `verify_sub6()`
input. The pattern is "translate at the boundary, never refactor either
side" so:

  - `concord/agent/react_runner.py` stays str-typed for task_outcome
    (per W8 user decision Q4),
  - `verifier/` source is untouched (W8 architectural rule),
  - and any future B1-side type drift is absorbed here with a single
    file change.

W10 D2 P2-A: B1 D4's `verifier.schemas.TaskOutcome` enum merged into
`metagent-v2` (merge commit 8ce5ad9). The original `ConcordTaskOutcome`
shim defined here had byte-identical 4 string values and was retained
"until B1 D4 lands"; that condition is now satisfied, so
`ConcordTaskOutcome` becomes a plain alias for B1's `TaskOutcome`. All
existing callers (`task_outcome_str_to_enum`, `tests/concord/test_verifier_adapter.py`)
continue to import the name from this module unchanged.
"""
from __future__ import annotations

from typing import Any

from schemas.sub6_report import SubsixSourceReport
from verifier.schemas import TaskOutcome as ConcordTaskOutcome

from concord.agent.react_runner import ConcordReactResult


def task_outcome_str_to_enum(outcome_str: str) -> ConcordTaskOutcome:
    """Map a ConcordReactResult.task_outcome string to its typed enum.

    Case-insensitive (accepts NORMAL / Normal / normal etc.) — the
    runner emits lowercase but external callers may have persisted
    uppercase B1-style strings. Unknown strings raise ValueError rather
    than silently degrading to EMPTY_UNKNOWN, because a typo here is a
    programmer error that should surface immediately.
    """
    if not isinstance(outcome_str, str) or not outcome_str.strip():
        raise ValueError(
            f"task_outcome must be a non-empty string, got {outcome_str!r}"
        )
    normalised = outcome_str.strip().lower()
    try:
        return ConcordTaskOutcome(normalised)
    except ValueError:
        valid = sorted(o.value for o in ConcordTaskOutcome)
        raise ValueError(
            f"task_outcome {outcome_str!r} not in {valid}"
        ) from None


# ---------------------------------------------------------------------------
# (A) ConcordReactResult → B1 verifier `llm_output` (prose string)
# ---------------------------------------------------------------------------


def concord_result_to_b1_narrative(
    result: ConcordReactResult,
    task: dict[str, Any],
) -> str:
    """Return the prose narrative string B1 `verify_sub6()` consumes.

    B1's extractor reads natural language ("These metabolites are
    enriched in X (FDR=...) , Y and Z drive...") and decomposes it into
    `{claim_text, subject}` atomic claims. Passing the full grammar-v2
    JSON would confuse the extractor (it would try to parse `claim_type`
    strings as substantive claims). The structured `claims` array stays
    ConcordMet-internal — its information is *also* present in the
    prose, restated by the LLM in plain English per the system prompt.

    Empty / failed outcomes propagate as an empty string so the caller
    can short-circuit verification (B1 verify_sub6 on "" returns a
    failed-claims VerifiedIdentification, which is the correct outcome
    representation).

    Note (W10 D3 P0-C): when ``result.final_narrative_text`` is itself
    a grammar-v2 JSON object (ConcordMet's system prompt mandates this
    shape), B1's `verify_sub6` → `_extract_classify` routes through
    ``extract_claims_from_json`` for a zero-LLM-call extract path. This
    behaviour is inherited from B1 D2 commit ``2354011`` in
    ``verifier/agent.py:_extract_classify`` and regression-locked by
    ``tests/concord/test_d3_zero_llm_extract_invariant.py`` — do not
    bypass `_extract_classify`'s JSON-first routing without updating
    that test.

    `task` is accepted for symmetry / future extension (e.g. injecting
    enrichment-result context into the prose) but unused in v0.
    """
    del task  # reserved for future use
    return (result.final_narrative_text or "").strip()


# ---------------------------------------------------------------------------
# (B) sub6b-v3 task dict → SubsixSourceReport
# ---------------------------------------------------------------------------


_SUBSIX_REQUIRED_KEYS = (
    "task_id",
    "task_type",
    "ground_truth_pathway",
    "ground_truth_signal_compounds",
    "ground_truth_noise_compounds",
    "ramp_enrichment_result",
)


_SUBSIX_OPTIONAL_CARRIER_KEYS = (
    "mummichog_enrichment_result",
    "metaboanalystr_enrichment_result",
    "sspa_enrichment_result",
    "fella_enrichment_result",
)


def sub6b_task_to_subsix_source_report(
    task: dict[str, Any],
) -> SubsixSourceReport:
    """Build a B1 `SubsixSourceReport` from a sub6b-v3 task JSONL row.

    The v3 JSONL row already carries every field the schema requires,
    verbatim. This is a pydantic constructor + light hygiene:

    - `domain` defaults to "mammalian" (sub6b-v3 invariant)
    - `differential_metabolites` / `differential_spectra` are passed
      through (one is non-None per task_type)
    - `compound_lookup` left None — the benchmark runner can populate it
      later for amortised lookup; the verifier layers tolerate None and
      fall back to per-claim loads

    Required-key absence (e.g. corrupted task with missing
    ground_truth_pathway) is allowed to surface as a pydantic
    ValidationError rather than silently filling defaults, since a
    missing ground-truth signal is benchmark corruption that must halt
    the run for inspection.
    """
    missing = [k for k in _SUBSIX_REQUIRED_KEYS if k not in task]
    if missing:
        # Let pydantic produce the canonical ValidationError shape — we
        # only short-circuit here so the error mentions ALL missing
        # keys, not just the first one pydantic stops on.
        return SubsixSourceReport(**{
            k: task.get(k) for k in _SUBSIX_REQUIRED_KEYS + _SUBSIX_OPTIONAL_CARRIER_KEYS + (
                "domain", "differential_metabolites", "differential_spectra",
            )
        })

    return SubsixSourceReport(
        task_id=task["task_id"],
        task_type=task["task_type"],
        domain=task.get("domain", "mammalian"),
        ground_truth_pathway=task["ground_truth_pathway"],
        ground_truth_signal_compounds=task["ground_truth_signal_compounds"],
        ground_truth_noise_compounds=task["ground_truth_noise_compounds"],
        ramp_enrichment_result=task["ramp_enrichment_result"],
        differential_metabolites=task.get("differential_metabolites"),
        differential_spectra=task.get("differential_spectra"),
        compound_lookup=task.get("compound_lookup"),
        **{k: task.get(k) for k in _SUBSIX_OPTIONAL_CARRIER_KEYS},
    )

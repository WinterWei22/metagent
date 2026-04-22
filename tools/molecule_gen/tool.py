"""Track C entry point: `generate(req: GenerateRequest) -> GenerateResponse`.

Pipeline:
  spectrum -> Fingerprinter -> fingerprint bits
           -> Generator -> raw (smiles, seq_log_prob) pairs
           -> RDKit validation + canonicalization
           -> formula hard filter (if requested)
           -> molecular-weight filter
           -> score normalization (log-prob + formula closeness + pool bonus)
           -> sort desc, build Candidates, return GenerateResponse

Dependency injection via keyword-only `generator` and `fingerprinter` arguments
lets tests bypass the heavy real adapters. Production callers call the plain
`generate(req)` form.
"""
from __future__ import annotations

from typing import Optional

from schemas import (
    Candidate,
    GenerateRequest,
    GenerateResponse,
    PrefilteredCandidate,
)

from tools.molecule_gen.errors import NoValidCandidatesError
from tools.molecule_gen.fingerprint import (
    Fingerprinter,
    SiriusFingerprinter,
)
from tools.molecule_gen.model import (
    Generator,
    MSBartGenerator,
    RawGeneration,
)
from tools.molecule_gen.validation import (
    combine_score,
    formula_diff,
    formulas_equal,
    normalize_logprobs,
    validate_and_canonicalize,
)


def generate(
    req: GenerateRequest,
    *,
    generator: Optional[Generator] = None,
    fingerprinter: Optional[Fingerprinter] = None,
) -> GenerateResponse:
    """Run the de novo generation pipeline. See module docstring for stages."""
    if req.n_candidates == 0:
        return GenerateResponse(
            candidates=[],
            n_generated_raw=0,
            n_valid=0,
            explain="n_candidates=0 requested; no generation performed.",
        )

    fp = fingerprinter if fingerprinter is not None else SiriusFingerprinter()
    gen = generator if generator is not None else MSBartGenerator()

    fingerprint_bits = fp.predict(req.spectrum)
    raw: list[RawGeneration] = gen.sample(
        fingerprint=fingerprint_bits,
        formula=req.molecular_formula,
        n=req.n_candidates,
    )

    return _build_response(
        raw=raw,
        target_formula=req.molecular_formula,
        max_mw=req.max_molecular_weight,
        candidate_pool=req.candidate_pool,
    )


# ---------------------------------------------------------------------------
# Post-processing — pulled out so tests can hit it directly if ever needed.
# ---------------------------------------------------------------------------


def _build_response(
    *,
    raw: list[RawGeneration],
    target_formula: str | None,
    max_mw: float,
    candidate_pool: list[PrefilteredCandidate] | None,
) -> GenerateResponse:
    n_raw = len(raw)

    pool_canon: set[str] = set()
    if candidate_pool:
        for entry in candidate_pool:
            canon = validate_and_canonicalize(entry.smiles)
            if canon is not None:
                pool_canon.add(canon[0])

    # Stage 1: RDKit parse + canonicalize. Drop unparseable.
    valid: list[tuple[RawGeneration, str, str, float]] = []
    for r in raw:
        v = validate_and_canonicalize(r.smiles)
        if v is None:
            continue
        canon, form, mw = v
        valid.append((r, canon, form, mw))
    n_valid_parsed = len(valid)

    # Stage 2: MW filter.
    valid = [t for t in valid if t[3] <= max_mw]

    # Stage 3: formula hard filter when requested.
    if target_formula:
        valid = [t for t in valid if formulas_equal(t[2], target_formula)]

    if n_raw > 0 and n_valid_parsed == 0:
        raise NoValidCandidatesError(
            f"All {n_raw} generated SMILES failed RDKit parsing."
        )

    if not valid:
        explain = _render_explain(
            n_raw=n_raw,
            n_parsed=n_valid_parsed,
            n_final=0,
            target_formula=target_formula,
            max_mw=max_mw,
            top_score=None,
        )
        return GenerateResponse(
            candidates=[],
            n_generated_raw=n_raw,
            n_valid=n_valid_parsed,
            explain=explain,
        )

    # Stage 4: combined score.
    logprobs = [t[0].seq_log_prob for t in valid]
    lp_norm = normalize_logprobs(logprobs)

    if target_formula:
        mismatches = [formula_diff(t[2], target_formula) for t in valid]
    else:
        mismatches = [0] * len(valid)
    max_mismatch = max(mismatches) if mismatches else 0

    candidates: list[Candidate] = []
    for (r, canon, form, mw), lpn, mism in zip(valid, lp_norm, mismatches):
        in_pool = canon in pool_canon
        score = combine_score(
            logprob_norm=lpn,
            formula_mismatch=mism,
            max_mismatch=max_mismatch,
            in_pool=in_pool,
        )
        explain_i = (
            f"De novo generated (rank {r.rank}, formula {form}, MW {mw:.2f})."
            + (" In prefilter pool." if in_pool else "")
        )
        candidates.append(
            Candidate(
                smiles=canon,
                name=None,
                source="generated",
                score=score,
                source_id=f"msbart:rank{r.rank}",
                explain=explain_i,
            )
        )

    candidates.sort(key=lambda c: c.score, reverse=True)

    explain = _render_explain(
        n_raw=n_raw,
        n_parsed=n_valid_parsed,
        n_final=len(candidates),
        target_formula=target_formula,
        max_mw=max_mw,
        top_score=candidates[0].score,
    )
    return GenerateResponse(
        candidates=candidates,
        n_generated_raw=n_raw,
        n_valid=n_valid_parsed,
        explain=explain,
    )


def _render_explain(
    *,
    n_raw: int,
    n_parsed: int,
    n_final: int,
    target_formula: str | None,
    max_mw: float,
    top_score: float | None,
) -> str:
    pieces = [f"Generated {n_raw} raw SMILES; {n_parsed} parsed in RDKit"]
    if target_formula:
        pieces.append(f"kept {n_final} matching formula {target_formula}")
    else:
        pieces.append(f"kept {n_final} under MW {max_mw:.0f}")
    if top_score is not None:
        pieces.append(f"top score {top_score:.3f}")
    return "; ".join(pieces) + "."

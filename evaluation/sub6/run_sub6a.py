"""Sub-6A (end-to-end pathway-enrichment) runner.

For each task:
  1. Identify each query spectrum's top-1 candidate via library_search,
     filtering out the spectrum's own GNPS ID (eval guide §3 pitfall 1).
  2. Render the deduplicated identifications as a metabolite list, build
     the prompt the same way as Sub-6B, call the LLM.
  3. Emit a Sub6AResult to JSONL with both the narrative and the
     per-spectrum identification log so downstream analysis can decompose
     end-to-end errors into identification vs reasoning failures.

Idempotent: completed task_ids in the output JSONL are skipped.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from common import llm_client
from evaluation.sub6.compound_lookup import CompoundLookup
from evaluation.sub6.identification import (
    IdStrategy,
    LibSearchFn,
    SpectrumIdentification,
    identify_spectrum,
    task_exclusion_set,
)
from evaluation.sub6.io_utils import append_jsonl, load_completed_task_ids
from evaluation.sub6.prompts import build_messages

logger = logging.getLogger(__name__)


ChatFn = Callable[..., str]


@dataclass
class Sub6AResult:
    task_id: str
    narrative: str
    identified_metabolites: list[dict]  # list of {name, inchikey_first_block, ...}
    identifications: list[dict]  # asdict of every SpectrumIdentification
    n_spectra: int
    n_identified: int
    n_correct_top1: int
    identification_accuracy: float
    elapsed_seconds: float
    elapsed_id_seconds: float
    elapsed_llm_seconds: float
    llm_model: str
    llm_calls: int
    id_strategy: str = "library_search"
    error: str | None = None


def _ident_to_metabolite(ident: SpectrumIdentification) -> dict | None:
    """Convert one identification into the prompt-ready metabolite dict.

    Returns None when nothing was identified — caller decides whether to
    drop that spectrum from the prompt.
    """
    if not ident.predicted_inchikey_first_block:
        return None
    return {
        "name": ident.predicted_name or f"unknown ({ident.predicted_inchikey_first_block})",
        "inchikey_first_block": ident.predicted_inchikey_first_block,
    }


def _dedupe_metabolites(items: list[dict]) -> list[dict]:
    """Drop duplicate identifications by InChIKey first-block.

    LLM prompt should not list the same compound twice when multiple
    spectra collapse to one identity. Order: first occurrence wins.
    """
    seen: set[str] = set()
    out: list[dict] = []
    for it in items:
        ik = it.get("inchikey_first_block")
        if not ik or ik in seen:
            continue
        seen.add(ik)
        out.append(it)
    return out


def run_sub6a(
    task: dict,
    *,
    chat_fn: ChatFn | None = None,
    library_search_fn: LibSearchFn | None = None,
    model: str = llm_client.DEFAULT_MODEL,
    temperature: float = 0.0,
    caller: str = "sub6a_baseline",
    top_k: int = 20,
    strategy: IdStrategy = "library_search",
    lookup: CompoundLookup | None = None,
) -> Sub6AResult:
    """Process one Sub-6A task end-to-end.

    ``strategy="perfect_id"`` bypasses library_search entirely and uses
    each spectrum's GT InChIKey as the identification — yields the
    *upper-bound* baseline isolating LLM reasoning from identification
    accuracy. Use ``library_search`` for the real e2e number.
    """
    t_total = time.perf_counter()
    spectra = task.get("differential_spectra") or []
    exclusion = task_exclusion_set(task)

    # 1. Per-spectrum identification.
    t_id = time.perf_counter()
    ident_list: list[SpectrumIdentification] = []
    for sp in spectra:
        ident = identify_spectrum(
            sp,
            exclusion_source_ids=exclusion,
            top_k=top_k,
            library_search_fn=library_search_fn,
            strategy=strategy,
            lookup=lookup,
        )
        ident_list.append(ident)
    elapsed_id = time.perf_counter() - t_id

    # 2. Aggregate identifications -> prompt-ready list.
    metabolites = [m for m in (_ident_to_metabolite(i) for i in ident_list) if m]
    metabolites = _dedupe_metabolites(metabolites)

    n_spec = len(spectra)
    n_id = sum(1 for i in ident_list if i.predicted_inchikey_first_block)
    n_correct = sum(1 for i in ident_list if i.correct_top1 is True)
    id_acc = (n_correct / n_spec) if n_spec else 0.0

    # 3. LLM narrative.
    t_llm = time.perf_counter()
    err: str | None = None
    narrative = ""
    llm_calls = 0
    if metabolites:
        messages = build_messages(metabolites)
        chat = chat_fn or llm_client.chat
        try:
            narrative = chat(
                messages,
                temperature=temperature,
                model=model,
                trace_id=task["task_id"],
                caller=caller,
            )
            llm_calls = 1
        except Exception as exc:
            err = f"llm: {type(exc).__name__}: {exc}"
            logger.warning("Sub-6A task %s LLM failed: %s", task["task_id"], err)
    else:
        err = "no spectra identified — skipping LLM call"
    elapsed_llm = time.perf_counter() - t_llm
    elapsed_total = time.perf_counter() - t_total

    return Sub6AResult(
        task_id=task["task_id"],
        narrative=narrative,
        identified_metabolites=metabolites,
        identifications=[asdict(i) for i in ident_list],
        n_spectra=n_spec,
        n_identified=n_id,
        n_correct_top1=n_correct,
        identification_accuracy=id_acc,
        elapsed_seconds=elapsed_total,
        elapsed_id_seconds=elapsed_id,
        elapsed_llm_seconds=elapsed_llm,
        llm_model=model,
        llm_calls=llm_calls,
        id_strategy=strategy,
        error=err,
    )


def run_sub6a_batch(
    tasks_path: Path | str,
    output_path: Path | str,
    *,
    chat_fn: ChatFn | None = None,
    library_search_fn: LibSearchFn | None = None,
    model: str = llm_client.DEFAULT_MODEL,
    temperature: float = 0.0,
    caller: str = "sub6a_baseline",
    top_k: int = 20,
    limit: int | None = None,
    strategy: IdStrategy = "library_search",
    lookup: CompoundLookup | None = None,
) -> list[Sub6AResult]:
    """Iterate ``tasks_path`` (JSONL), append ``Sub6AResult`` rows to
    ``output_path``, skipping already-completed task_ids.
    """
    tasks_path = Path(tasks_path)
    output_path = Path(output_path)
    completed = load_completed_task_ids(output_path)
    logger.info(
        "Sub-6A runner: %d task_ids already in %s", len(completed), output_path
    )

    results: list[Sub6AResult] = []
    processed = 0
    with tasks_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            task = json.loads(line)
            tid = task["task_id"]
            if tid in completed:
                continue
            r = run_sub6a(
                task,
                chat_fn=chat_fn,
                library_search_fn=library_search_fn,
                model=model,
                temperature=temperature,
                caller=caller,
                top_k=top_k,
                strategy=strategy,
                lookup=lookup,
            )
            append_jsonl(output_path, asdict(r))
            results.append(r)
            processed += 1
            if limit is not None and processed >= limit:
                break
    logger.info("Sub-6A runner: processed %d tasks this run", processed)
    return results

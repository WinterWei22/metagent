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

import argparse
import json
import logging
import os
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


NARRATIVE_LLM_ROUTES: dict[str, dict[str, str | None]] = {
    "minimax": {"provider": "minimax", "model": "MiniMax-M2.7"},
    "gpt55": {"provider": "openai", "model": "gpt-5.5"},
    "opus47": {"provider": "openai", "model": "claude-opus-4-7"},
}


def resolve_narrative_llm(name: str) -> tuple[str, str]:
    route = NARRATIVE_LLM_ROUTES[name]
    return str(route["provider"]), str(route["model"])


def _chat_kwargs(provider: str | None) -> dict[str, str]:
    return {"provider": provider} if provider else {}


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
    provider: str | None = None,
    temperature: float = 0.0,
    caller: str = "sub6a_baseline",
    llm_retries: int = 0,
    top_k: int = 20,
    strategy: IdStrategy = "library_search",
    lookup: CompoundLookup | None = None,
    mass_tolerance_ppm: float | None = None,
    libraries: tuple[str, ...] = ("gnps",),
    skip_narrative: bool = False,
    rerank_with: tuple[str, ...] = (),
    rerank_top_k: int = 5,
    cfmid_cache_dir: Path | None = None,
    primary_retriever: str = "modcos",
    reranker_mode: str = "weighted",
) -> Sub6AResult:
    """Process one Sub-6A task end-to-end.

    ``strategy="perfect_id"`` bypasses library_search entirely and uses
    each spectrum's GT InChIKey as the identification — yields the
    *upper-bound* baseline isolating LLM reasoning from identification
    accuracy. Use ``library_search`` for the real e2e number.

    ``libraries`` (Phase 6.1 ablation): tuple passed through to
    ``identify_spectrum``. Default ``("gnps",)`` preserves v2 baseline
    behaviour. Set to ``("gnps", "inhouse")`` to enable MS-CLIP fusion.

    ``skip_narrative`` (Phase 6.1 ablation): when True the LLM narrative
    block is short-circuited. Identification still runs; narrative
    string is empty, llm_calls=0, elapsed_llm≈0. Used by ablation runs
    that only need id_accuracy and don't want to burn LLM budget.
    """
    t_total = time.perf_counter()
    spectra = task.get("differential_spectra") or []
    exclusion = task_exclusion_set(task)

    # 1. Per-spectrum identification.
    t_id = time.perf_counter()
    ident_list: list[SpectrumIdentification] = []
    # When reranker_mode=="llm" the LLM is invoked per-spectrum during
    # identify_spectrum (single-call-per-spectrum design — narrative is the
    # by-product of reranking). The chat function and kwargs come from the
    # task-level chat_fn/model/provider so we keep one LLM client config.
    if reranker_mode == "llm":
        chat = chat_fn or llm_client.chat
        llm_chat_kwargs = {
            "temperature": temperature,
            "model": model,
            "trace_id": task["task_id"],
            "caller": caller + ":llm_rerank",
            **_chat_kwargs(provider),
        }
    else:
        chat = None
        llm_chat_kwargs = None
    for sp in spectra:
        ident = identify_spectrum(
            sp,
            exclusion_source_ids=exclusion,
            top_k=top_k,
            libraries=tuple(libraries),
            library_search_fn=library_search_fn,
            strategy=strategy,
            lookup=lookup,
            mass_tolerance_ppm=mass_tolerance_ppm,
            rerank_with=tuple(rerank_with),
            rerank_top_k=rerank_top_k,
            cfmid_cache_dir=cfmid_cache_dir,
            primary_retriever=primary_retriever,
            reranker_mode=reranker_mode,
            llm_chat_fn=chat if reranker_mode == "llm" else None,
            llm_chat_kwargs=llm_chat_kwargs,
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
    if reranker_mode == "llm":
        # Phase 6.3 path — narrative is concatenated per-spectrum LLM rerank
        # output. The LLM was already called once per spectrum inside
        # identify_spectrum; this block stitches those outputs into the
        # task-level narrative for the verifier extractor to consume.
        chunks: list[str] = []
        for ident in ident_list:
            if ident.llm_rerank_narrative:
                chunks.append(ident.llm_rerank_narrative)
                llm_calls += 1
        narrative = "\n\n---\n\n".join(chunks)
        if not narrative:
            err = "llm_rerank produced no narratives"
    elif skip_narrative:
        # Phase 6.1 ablation path — identification only, no LLM call.
        err = "skip_narrative=True — narrative omitted"
    elif metabolites:
        messages = build_messages(metabolites)
        chat = chat_fn or llm_client.chat
        for attempt in range(llm_retries + 1):
            try:
                narrative = chat(
                    messages,
                    temperature=temperature,
                    model=model,
                    trace_id=task["task_id"],
                    caller=caller,
                    **_chat_kwargs(provider),
                )
                llm_calls = 1
                err = None
                break
            except Exception as exc:
                err = f"llm: {type(exc).__name__}: {exc}"
                logger.warning("Sub-6A task %s LLM failed: %s", task["task_id"], err)
                if attempt < llm_retries:
                    time.sleep(1.0)
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
    provider: str | None = None,
    temperature: float = 0.0,
    caller: str = "sub6a_baseline",
    llm_retries: int = 0,
    top_k: int = 20,
    limit: int | None = None,
    strategy: IdStrategy = "library_search",
    lookup: CompoundLookup | None = None,
    mass_tolerance_ppm: float | None = None,
    libraries: tuple[str, ...] = ("gnps",),
    skip_narrative: bool = False,
    rerank_with: tuple[str, ...] = (),
    rerank_top_k: int = 5,
    cfmid_cache_dir: Path | None = None,
    peak_evidence_dir: Path | None = None,
    primary_retriever: str = "modcos",
    reranker_mode: str = "weighted",
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
                provider=provider,
                temperature=temperature,
                caller=caller,
                llm_retries=llm_retries,
                top_k=top_k,
                strategy=strategy,
                lookup=lookup,
                mass_tolerance_ppm=mass_tolerance_ppm,
                libraries=tuple(libraries),
                skip_narrative=skip_narrative,
                rerank_with=tuple(rerank_with),
                rerank_top_k=rerank_top_k,
                cfmid_cache_dir=cfmid_cache_dir,
                primary_retriever=primary_retriever,
                reranker_mode=reranker_mode,
            )
            # Phase 6.2: dump peak_evidence per spectrum to disk if requested.
            if peak_evidence_dir is not None and rerank_with:
                peak_evidence_dir.mkdir(parents=True, exist_ok=True)
                for ident in r.identifications:
                    pe = ident.get("peak_evidence")
                    if pe:
                        sid = pe.get("spectrum_id") or ident.get("spectrum_id")
                        (peak_evidence_dir / f"{sid}.json").write_text(json.dumps(pe, indent=2))
            append_jsonl(output_path, asdict(r))
            results.append(r)
            processed += 1
            if limit is not None and processed >= limit:
                break
    logger.info("Sub-6A runner: processed %d tasks this run", processed)
    return results


def _resolve_api_key(provider: str, model: str) -> None:
    if provider == "openai":
        os.environ.setdefault("METAGENT_OPENAI_BASE_URL", "https://api.viviai.cc/v1")
        if os.environ.get("METAGENT_OPENAI_API_KEY"):
            return
        key_files = (
            ("api_key_claude.txt", "api_key_gpt.txt")
            if model.startswith("claude-")
            else ("api_key_gpt.txt", "api_key_claude.txt")
        )
        for name in key_files:
            candidate = Path.cwd() / name
            if candidate.is_file():
                os.environ["METAGENT_OPENAI_API_KEY"] = candidate.read_text().strip()
                return
        return
    if os.environ.get("MINIMAX_API_KEY"):
        return
    for name in ("api_key_minimax.txt", "api_key.txt"):
        candidate = Path.cwd() / name
        if candidate.is_file():
            os.environ["MINIMAX_API_KEY"] = candidate.read_text().strip()
            return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tasks", help="Sub-6A JSONL tasks file")
    parser.add_argument("output", help="Output JSONL file")
    parser.add_argument(
        "--narrative-llm",
        choices=tuple(NARRATIVE_LLM_ROUTES),
        default="minimax",
        help="LLM used to generate narratives",
    )
    parser.add_argument("--llm-model", default=None, help="Legacy explicit model override")
    parser.add_argument("--limit", "--max-tasks", type=int, default=None)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument(
        "--id-strategy",
        choices=("library_search", "perfect_id"),
        default="library_search",
    )
    parser.add_argument(
        "--curated",
        default="data/benchmark/sub6/curated_hmdb_mammalian.jsonl",
    )
    parser.add_argument("--mass-tolerance-ppm", type=float, default=None)
    parser.add_argument("--no-llm-key-check", action="store_true")
    args = parser.parse_args(argv)

    provider, model = resolve_narrative_llm(args.narrative_llm)
    if args.llm_model:
        model = args.llm_model
    if not args.no_llm_key_check:
        _resolve_api_key(provider, model)

    lookup = None
    if args.id_strategy == "perfect_id":
        lookup = CompoundLookup.from_curated(Path(args.curated))
    results = run_sub6a_batch(
        args.tasks,
        args.output,
        model=model,
        provider=provider,
        limit=args.limit,
        top_k=args.top_k,
        caller=f"sub6a_baseline_{args.id_strategy}",
        llm_retries=1,
        strategy=args.id_strategy,
        lookup=lookup,
        mass_tolerance_ppm=args.mass_tolerance_ppm,
    )
    ok = sum(1 for r in results if r.error is None)
    print(f"Sub-6A: processed {len(results)} tasks, ok={ok}, fail={len(results)-ok}")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

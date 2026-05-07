"""CLI entrypoint for Sub-6 baseline LLM evaluation runs.

    python scripts/eval_sub6/run_baseline.py --sub6b
    python scripts/eval_sub6/run_baseline.py --sub6a --limit 1
    python scripts/eval_sub6/run_baseline.py --both --out-dir data/eval/sub6

The runner is idempotent — re-running with the same output path resumes.
Set ``MINIMAX_API_KEY`` (or load from ``api_key.txt``) before invoking.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


NARRATIVE_LLM_ROUTES: dict[str, dict[str, str]] = {
    "minimax": {"provider": "minimax", "model": "MiniMax-M2.7"},
    "gpt55": {"provider": "openai", "model": "gpt-5.5"},
    "opus47": {"provider": "openai", "model": "claude-opus-4-7"},
}


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
            candidate = Path(_REPO_ROOT) / name
            if candidate.is_file():
                os.environ["METAGENT_OPENAI_API_KEY"] = candidate.read_text().strip()
                return
        return

    if os.environ.get("MINIMAX_API_KEY"):
        return
    for name in ("api_key_minimax.txt", "api_key.txt"):
        candidate = Path(_REPO_ROOT) / name
        if candidate.is_file():
            os.environ["MINIMAX_API_KEY"] = candidate.read_text().strip()
            return


def _resolve_narrative_llm(name: str) -> tuple[str, str]:
    route = NARRATIVE_LLM_ROUTES[name]
    provider = route["provider"]
    model = route["model"]
    if provider == "openai":
        os.environ["METAGENT_LLM_PROVIDER"] = "openai"
        os.environ["METAGENT_OPENAI_MODEL"] = model
        os.environ.setdefault("METAGENT_OPENAI_BASE_URL", "https://api.viviai.cc/v1")
    return provider, model


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--sub6a",
        nargs="?",
        const=True,
        default=False,
        help="Run Sub-6A tasks; optionally pass a JSONL tasks file",
    )
    p.add_argument(
        "--sub6b",
        nargs="?",
        const=True,
        default=False,
        help="Run Sub-6B tasks; optionally pass a JSONL tasks file",
    )
    p.add_argument("--both", action="store_true", help="Run both Sub-6A and Sub-6B")
    p.add_argument(
        "--tasks-dir",
        default="data/benchmark/sub6",
        help="Directory containing sub6a_e2e_tasks.jsonl / sub6b_mammalian_tasks.jsonl",
    )
    p.add_argument(
        "--out-dir",
        "--output",
        dest="out_dir",
        default="data/eval/sub6",
        help="Directory for raw narrative+identification JSONL output",
    )
    p.add_argument(
        "--narrative-llm",
        choices=tuple(NARRATIVE_LLM_ROUTES),
        default="minimax",
        help="LLM used to generate narratives",
    )
    p.add_argument("--llm-model", default=None, help="Legacy explicit model override")
    p.add_argument(
        "--limit",
        "--max-tasks",
        dest="limit",
        type=int,
        default=None,
        help="Per-track task limit",
    )
    p.add_argument("--top-k", type=int, default=20, help="Sub-6A library_search top_k")
    p.add_argument(
        "--id-strategy",
        choices=("library_search", "perfect_id"),
        default="library_search",
        help=(
            "Sub-6A identification strategy. 'perfect_id' uses each "
            "spectrum's GT InChIKey directly (upper-bound baseline, no "
            "library_search dependency)."
        ),
    )
    p.add_argument(
        "--curated",
        default="data/benchmark/sub6/curated_hmdb_mammalian.jsonl",
        help="Curated compound pool — used by Sub-6A perfect_id to recover names",
    )
    p.add_argument(
        "--no-llm-key-check",
        action="store_true",
        help="Skip the api_key.txt fallback (for tests using mocked chat)",
    )
    p.add_argument(
        "--mass-tolerance-ppm",
        type=float,
        default=None,
        help=(
            "Phase A: optional precursor-mass window (ppm) for Sub-6A "
            "library_search Path B. When set, library_search narrows the "
            "GNPS pool to records within ±tol_ppm of each query's "
            "precursor m/z BEFORE scoring/dedup. Recommended 10 (HRMS); "
            "leave unset for the original full-pool scan."
        ),
    )
    p.add_argument(
        "--output-suffix",
        default=None,
        help=(
            "Optional suffix appended to the Sub-6A narrative output "
            "filename, e.g. '_phase_a' yields sub6a_narratives_phase_a.jsonl. "
            "Used to keep variant outputs from clobbering frozen baselines."
        ),
    )
    p.add_argument(
        "--libraries",
        default=None,
        help=(
            "Phase 6.1 ablation: comma-separated retrieval libraries for "
            "library_search (e.g. 'gnps' or 'gnps,inhouse'). When unset, "
            "Sub-6A defaults to ('gnps',) — the v2 baseline behaviour. "
            "Set 'gnps,inhouse' to enable MS-CLIP fusion. Sub-6B is "
            "unaffected — its own runner does not consume this flag."
        ),
    )
    p.add_argument(
        "--skip-narrative",
        action="store_true",
        help=(
            "Phase 6.1 ablation: short-circuit the LLM narrative call after "
            "identification. Output JSONL still records identifications + "
            "id_acc; narrative is empty, llm_calls=0. Use for retrieval-"
            "ablation runs that only need id_accuracy and don't want to "
            "burn LLM API budget."
        ),
    )
    args = p.parse_args(argv)

    if not (args.sub6a or args.sub6b or args.both):
        p.error("must pass at least one of --sub6a / --sub6b / --both")

    # Parse + validate --libraries (default ("gnps",) preserves v2 baseline).
    if args.libraries:
        libraries_tuple = tuple(
            tok.strip() for tok in args.libraries.split(",") if tok.strip()
        )
        if not libraries_tuple:
            p.error("--libraries was set but parsed to an empty tuple")
        for lib in libraries_tuple:
            if lib not in ("gnps", "inhouse"):
                p.error(f"--libraries: unknown library {lib!r}; allowed: gnps, inhouse")
    else:
        libraries_tuple = ("gnps",)

    provider, model = _resolve_narrative_llm(args.narrative_llm)
    if args.llm_model:
        model = args.llm_model

    # When --skip-narrative is set there are zero LLM calls — don't require
    # a key. (Phase 6.1 ablation runs typically don't have a narrative LLM
    # key handy on the same machine that owns the GPU.)
    if not args.no_llm_key_check and not args.skip_narrative:
        _resolve_api_key(provider, model)
        key_env = "METAGENT_OPENAI_API_KEY" if provider == "openai" else "MINIMAX_API_KEY"
        if not os.environ.get(key_env):
            sys.stderr.write(f"ERROR: {key_env} not set and api key fallback not found.\n")
            return 2

    logging.basicConfig(
        level=os.environ.get("LOGLEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    tasks_dir = Path(args.tasks_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    do_b = bool(args.sub6b) or args.both
    do_a = bool(args.sub6a) or args.both

    if do_b:
        from evaluation.sub6.run_sub6b import run_sub6b_batch

        sub6b_in = (
            Path(args.sub6b)
            if isinstance(args.sub6b, str)
            else tasks_dir / "sub6b_mammalian_tasks.jsonl"
        )
        sub6b_out = out_dir / "sub6b_narratives.jsonl"
        print(
            f"=== Sub-6B: {sub6b_in} → {sub6b_out} "
            f"(limit={args.limit}, narrative_llm={args.narrative_llm}, model={model}) ==="
        )
        results = run_sub6b_batch(
            sub6b_in,
            sub6b_out,
            model=model,
            provider=provider,
            limit=args.limit,
            caller="sub6b_baseline",
            llm_retries=1,
        )
        ok = sum(1 for r in results if r.error is None)
        print(f"Sub-6B: processed {len(results)} tasks, ok={ok}, fail={len(results)-ok}")

    if do_a:
        from evaluation.sub6.compound_lookup import CompoundLookup
        from evaluation.sub6.run_sub6a import run_sub6a_batch

        sub6a_in = (
            Path(args.sub6a)
            if isinstance(args.sub6a, str)
            else tasks_dir / "sub6a_e2e_tasks.jsonl"
        )
        # Output filename embeds strategy so runs don't clobber each other.
        # --output-suffix takes precedence over the auto strategy suffix so
        # variants like Phase A can be named explicitly without losing the
        # frozen v3 'sub6a_narratives.jsonl' file.
        if args.output_suffix:
            suffix = args.output_suffix
        else:
            suffix = "_perfect_id" if args.id_strategy == "perfect_id" else ""
        sub6a_out = out_dir / f"sub6a_narratives{suffix}.jsonl"
        print(
            f"=== Sub-6A ({args.id_strategy}): {sub6a_in} → {sub6a_out} "
            f"(limit={args.limit}, top_k={args.top_k}, "
            f"mass_tolerance_ppm={args.mass_tolerance_ppm}, "
            f"libraries={libraries_tuple}, "
            f"skip_narrative={args.skip_narrative}, "
            f"narrative_llm={args.narrative_llm}, model={model}) ==="
        )
        lookup = None
        if args.id_strategy == "perfect_id":
            lookup = CompoundLookup.from_curated(Path(args.curated))
            print(f"  loaded curated pool: {len(lookup)} entries")

        results = run_sub6a_batch(
            sub6a_in,
            sub6a_out,
            model=model,
            provider=provider,
            limit=args.limit,
            top_k=args.top_k,
            caller=f"sub6a_baseline_{args.id_strategy}",
            llm_retries=1,
            strategy=args.id_strategy,
            lookup=lookup,
            mass_tolerance_ppm=args.mass_tolerance_ppm,
            libraries=libraries_tuple,
            skip_narrative=args.skip_narrative,
        )
        ok = sum(1 for r in results if r.error is None)
        print(f"Sub-6A: processed {len(results)} tasks, ok={ok}, fail={len(results)-ok}")
        for r in results:
            print(
                f"  {r.task_id}: id_acc={r.identification_accuracy:.2f} "
                f"({r.n_correct_top1}/{r.n_spectra}), "
                f"id_t={r.elapsed_id_seconds:.1f}s, llm_t={r.elapsed_llm_seconds:.1f}s, "
                f"err={r.error!r}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Phase 6.7-D — MassSpecGym OOD identification runner.

Drives identify_spectrum on MSG test-split spectra with pre-built candidate
pool injection (formula-restricted or mass-window). Mirrors run_casmi.py
but uses the MSG loader and supports switching the MS-CLIP checkpoint via
--msclip-checkpoint (sets METAGENT_MSCLIP_CKPT before any library_search
import).

Usage:
    # MS-CLIP-only baseline, formula pool
    METAGENT_MSCLIP_CKPT=.../best.ckpt \\
    python scripts/eval_sub6/run_msg.py \\
        --msg-candidates formula --reranker none \\
        --out-dir data/eval/msg/formula_msclip_only

    # LLM reranker, mass-window pool
    METAGENT_MSCLIP_CKPT=.../best.ckpt \\
    python scripts/eval_sub6/run_msg.py \\
        --msg-candidates mass --reranker llm \\
        --out-dir data/eval/msg/mass_llm
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Phase 6.7-D: MSG OOD identification")
    p.add_argument(
        "--msg-candidates", choices=["formula", "mass"], default="formula",
        help="Candidate pool type: formula-restricted (default) or mass-window.",
    )
    p.add_argument(
        "--msclip-checkpoint", default=None,
        help="Override METAGENT_MSCLIP_CKPT env var. Set to the MSG-trained "
             "checkpoint best.ckpt path. Must be set before library_search is "
             "imported (this runner handles that).",
    )
    p.add_argument("--msg-labels", type=Path, default=None,
                   help="Path to MSG labels.tsv (default: auto-resolved).")
    p.add_argument("--msg-split", type=Path, default=None,
                   help="Path to split_msg.tsv (default: auto-resolved).")
    p.add_argument("--msg-spec-dir", type=Path, default=None,
                   help="Directory of pred_<ID>.json spectrum files.")
    p.add_argument("--msg-cands-json", type=Path, default=None,
                   help="Override candidates JSON path (overrides --msg-candidates).")
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--n-sample", type=int, default=500,
                   help="Number of test spectra to evaluate. Default 500.")
    p.add_argument("--sample-seed", type=int, default=42)
    p.add_argument("--limit", type=int, default=None,
                   help="Hard cap on spectra after sampling (smoke test).")
    p.add_argument("--max-candidates", type=int, default=None,
                   help="Cap candidates per spectrum. Default: full pool (256).")
    p.add_argument("--top-k", type=int, default=20)
    p.add_argument("--min-score", type=float, default=0.0)
    p.add_argument("--reranker", choices=["weighted", "llm", "none", "conditional"],
                   default="none")
    p.add_argument("--rerank-with", type=str, default="",
                   help="Comma list of {sirius,cfmid}. Empty disables.")
    p.add_argument("--rerank-top-k", type=int, default=5)
    p.add_argument("--narrative-llm", choices=["minimax", "gpt55", "opus47"],
                   default="opus47",
                   help="LLM route when --reranker=llm.")
    p.add_argument("--llm-temperature", type=float, default=0.0)
    p.add_argument("--dump-ranks", action="store_true",
                   help="Persist top-K ranked candidates + llm ranked_indices for MRR.")
    p.add_argument("--log-level", default="INFO")
    return p.parse_args()


def main() -> int:
    args = _parse_args()

    # Set METAGENT_MSCLIP_CKPT BEFORE importing library_search so the
    # subprocess inherits the correct checkpoint path.
    if args.msclip_checkpoint:
        os.environ["METAGENT_MSCLIP_CKPT"] = args.msclip_checkpoint

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    log = logging.getLogger("run_msg")

    from evaluation.sub6.identification import identify_spectrum
    from evaluation.sub6.msg_loader import (
        DEFAULT_FORMULA_CANDS,
        DEFAULT_MASS_CANDS,
        DEFAULT_MSG_LABELS,
        DEFAULT_MSG_SPLIT,
        MSG_SPEC_DIR,
        build_msg_pool,
        load_candidates_json,
        load_msg_test_specs,
        msg_spec_to_task_dict,
    )
    from evaluation.sub6.run_sub6a import (
        NARRATIVE_LLM_ROUTES,
        _chat_kwargs,
        resolve_narrative_llm,
    )
    from common import llm_client

    args.out_dir.mkdir(parents=True, exist_ok=True)

    # Resolve paths
    labels_tsv = args.msg_labels or DEFAULT_MSG_LABELS
    split_tsv = args.msg_split or DEFAULT_MSG_SPLIT
    spec_dir = args.msg_spec_dir or MSG_SPEC_DIR

    if args.msg_cands_json:
        cands_path = args.msg_cands_json
    elif args.msg_candidates == "formula":
        cands_path = DEFAULT_FORMULA_CANDS
    else:
        cands_path = DEFAULT_MASS_CANDS

    ckpt_in_use = os.environ.get("METAGENT_MSCLIP_CKPT", "(default)")
    log.info("METAGENT_MSCLIP_CKPT = %s", ckpt_in_use)
    log.info("candidate pool = %s (%s)", args.msg_candidates, cands_path)
    log.info("reranker = %s", args.reranker)

    # Load spectra
    specs = load_msg_test_specs(
        labels_tsv, split_tsv, spec_dir,
        n_sample=args.n_sample,
        seed=args.sample_seed,
    )
    if args.limit:
        specs = specs[: args.limit]
    log.info("running %d MSG spectra", len(specs))

    # Load candidate JSON (once — large file, load into memory)
    candidates_data = load_candidates_json(cands_path)

    # LLM setup (only when reranker=llm)
    chat_fn = None
    llm_chat_kwargs: dict | None = None
    if args.reranker == "llm":
        provider, model = resolve_narrative_llm(args.narrative_llm)
        if provider == "openai":
            os.environ["METAGENT_LLM_PROVIDER"] = "openai"
            os.environ["METAGENT_OPENAI_MODEL"] = model
            os.environ.setdefault("METAGENT_OPENAI_BASE_URL", "https://api.viviai.cc/v1")
            for fname in ("api_key_claude.txt", "api_key_gpt.txt"):
                kf = Path(_REPO_ROOT) / fname
                if kf.is_file():
                    os.environ.setdefault("METAGENT_OPENAI_API_KEY", kf.read_text().strip())
                    break
        chat_fn = llm_client.chat
        llm_chat_kwargs = {
            "temperature": args.llm_temperature,
            "model": model,
            "caller": "msg_llm_reranker",
            **_chat_kwargs(provider),
        }
        log.info("LLM reranker: %s (model=%s)", args.narrative_llm, model)

    rerank_with = tuple(s for s in args.rerank_with.split(",") if s.strip())

    out_jsonl = args.out_dir / "msg_identifications.jsonl"
    n_correct = n_with_pred = n_no_pool = n_total = 0
    t0 = time.perf_counter()

    with out_jsonl.open("w") as f_out:
        for i, spec in enumerate(specs):
            t_spec = time.perf_counter()
            task_dict = msg_spec_to_task_dict(spec)

            pool = build_msg_pool(
                spec.smiles,
                candidates_data,
                spec.precursor_mz,
                gt_formula=spec.formula,
                max_candidates=args.max_candidates,
                pool_type=args.msg_candidates,
            )

            if not pool:
                log.warning("no candidate pool for %s (smiles=%.40s...)",
                            spec.spectrum_id, spec.smiles)
                n_no_pool += 1
                f_out.write(json.dumps({
                    "spectrum_id": spec.spectrum_id,
                    "msg_formula": spec.formula,
                    "gt_inchikey_first_block": spec.inchikey_first_block,
                    "gt_smiles": spec.smiles,
                    "predicted_inchikey_first_block": None,
                    "correct_top1": False,
                    "error": "no_msg_pool",
                }) + "\n")
                n_total += 1
                continue

            ident = identify_spectrum(
                task_dict,
                exclusion_source_ids=frozenset(),  # no GNPS source to exclude
                top_k=args.top_k,
                min_score=args.min_score,
                libraries=("inhouse",),
                candidate_pool=pool,
                use_gnps=False,
                primary_retriever="msclip",
                reranker_mode=args.reranker,
                rerank_with=rerank_with,
                rerank_top_k=args.rerank_top_k,
                llm_chat_fn=chat_fn,
                llm_chat_kwargs=llm_chat_kwargs,
            )
            n_total += 1
            if ident.predicted_inchikey_first_block:
                n_with_pred += 1
            if ident.correct_top1 is True:
                n_correct += 1

            # Build output record
            rec: dict = {
                "spectrum_id": spec.spectrum_id,
                "msg_pool": args.msg_candidates,
                "msg_formula": spec.formula,
                "gt_inchikey_first_block": spec.inchikey_first_block,
                "gt_smiles": spec.smiles,
                "predicted_inchikey_first_block": ident.predicted_inchikey_first_block,
                "predicted_smiles": ident.predicted_smiles,
                "predicted_score": ident.predicted_score,
                "correct_top1": ident.correct_top1,
                "n_candidates_pool": len(pool),
                "n_candidates_returned": ident.n_candidates_returned,
                "primary_retriever": ident.primary_retriever,
                "reranker_mode": ident.reranker_mode,
                "rerank_applied": list(ident.rerank_applied),
                "error": ident.error,
                "collision_energy": spec.collision_energy,
                "adduct": spec.adduct,
            }
            if ident.reranker_mode == "llm":
                rec["llm_rerank"] = {
                    "narrative": ident.llm_rerank_narrative,
                    "peak_claims": list(ident.llm_rerank_peak_claims),
                    "confidence": ident.llm_rerank_confidence,
                    "fallback_used": ident.llm_rerank_fallback_used,
                    "parse_error": ident.llm_rerank_parse_error,
                    "ranked_indices": list(ident.llm_rerank_ranked_indices or []),
                }
            if args.dump_ranks and ident.ranked_candidates:
                rec["ranked_candidates"] = list(ident.ranked_candidates)

            f_out.write(json.dumps(rec) + "\n")
            f_out.flush()

            elapsed = time.perf_counter() - t_spec
            if (i + 1) % 10 == 0 or (i + 1) == len(specs):
                log.info(
                    "spec %d/%d  %s  pool=%d  pred=%s  correct=%s  t=%.1fs",
                    i + 1, len(specs), spec.spectrum_id, len(pool),
                    ident.predicted_inchikey_first_block, ident.correct_top1, elapsed,
                )

    elapsed_total = time.perf_counter() - t0
    id_acc = (n_correct / n_total) if n_total else 0.0
    summary = {
        "benchmark": "msg",
        "msg_candidates": args.msg_candidates,
        "msclip_checkpoint": ckpt_in_use,
        "n_sample": args.n_sample,
        "sample_seed": args.sample_seed,
        "reranker_mode": args.reranker,
        "rerank_with": list(rerank_with),
        "rerank_top_k": args.rerank_top_k,
        "n_specs": n_total,
        "n_with_pred": n_with_pred,
        "n_correct": n_correct,
        "n_no_pool": n_no_pool,
        "id_acc": round(id_acc, 4),
        "elapsed_seconds": round(elapsed_total, 1),
    }
    (args.out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    log.info("=" * 60)
    log.info("MSG  pool=%s  reranker=%s", args.msg_candidates, args.reranker)
    log.info("  n=%d  correct=%d  id_acc=%.4f  elapsed=%.1fs",
             n_total, n_correct, id_acc, elapsed_total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

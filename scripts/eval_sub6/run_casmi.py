"""Phase 6.6 — CASMI 2022 / 2016 OOD identification runner.

Drives identify_spectrum on CASMI spectra with PubChem candidate-pool
injection. Writes per-spec identification JSONL + summary CSV/JSON.

CASMI is identification-only — no pathway/Sub-6A LLM narrative is run, since
the benchmark's only labelled output is the GT InChIKey/SMILES per spectrum.

Usage:
    # MS-CLIP-only baseline on CASMI 2022 (no rerank)
    python scripts/eval_sub6/run_casmi.py \
        --casmi 2022 \
        --reranker none \
        --out-dir data/eval/casmi/2022_msclip_only

    # Conditional rerank (Phase 6.5 locked threshold gap≥0.05)
    python scripts/eval_sub6/run_casmi.py \
        --casmi 2022 \
        --reranker conditional \
        --rerank-with sirius,cfmid \
        --rerank-top-k 5 \
        --out-dir data/eval/casmi/2022_conditional
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from evaluation.sub6.casmi_loader import (
    DEFAULT_CASMI_2016_CANDIDATES_DIR,
    DEFAULT_CASMI_2016_CAT2_ROOT,
    PubChemRetrievalIndex,
    build_casmi_2016_pool,
    build_pubchem_pool,
    casmi_spec_to_task_dict,
    load_casmi_2016_cat2_specs,
    load_casmi_2022_specs,
)
from evaluation.sub6.identification import identify_spectrum
from evaluation.sub6.run_sub6a import (
    NARRATIVE_LLM_ROUTES,
    _chat_kwargs,
    resolve_narrative_llm,
)
from common import llm_client

DEFAULT_CASMI_2022_ROOT = Path(
    "/data/weiwentao/llm_agent_metabolomics/CASMI/casmi_2022/preprocessed/casmi2022"
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--casmi", choices=["2022", "2016_cat2"], default="2022",
                   help="CASMI dataset to run on.")
    p.add_argument("--casmi-root", type=Path, default=None,
                   help="Override the default CASMI preprocessed root.")
    p.add_argument("--casmi-2016-candidates-dir", type=Path, default=None,
                   help="(2016 only) Per-challenge candidate CSVs directory.")
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--limit", type=int, default=None,
                   help="Cap number of spectra (smoke test). Default: all.")
    p.add_argument("--max-candidates", type=int, default=None,
                   help="Cap PubChem candidates per spectrum. Default: full pool.")
    p.add_argument("--top-k", type=int, default=20)
    p.add_argument("--min-score", type=float, default=0.0)
    p.add_argument("--primary-retriever", choices=["msclip", "modcos"], default="msclip",
                   help="modcos is meaningless for CASMI (no reference spectra) — "
                        "exposed only for ablation.")
    p.add_argument("--reranker", choices=["weighted", "llm", "none", "conditional"],
                   default="none")
    p.add_argument("--rerank-with", type=str, default="",
                   help="Comma list of {sirius,cfmid}. Empty disables rerank.")
    p.add_argument("--rerank-top-k", type=int, default=5)
    p.add_argument("--cfmid-cache-dir", type=Path, default=None)
    p.add_argument("--narrative-llm", choices=tuple(NARRATIVE_LLM_ROUTES),
                   default="opus47",
                   help="LLM route (Phase 6.3): minimax / gpt55 / opus47. Only "
                        "used when --reranker=llm.")
    p.add_argument("--llm-temperature", type=float, default=0.0)
    p.add_argument("--dump-ranks", action="store_true",
                   help="Phase 6.7-A: persist top-K ranked candidates + LLM "
                        "ranked_indices in each per-spec record (for MRR / top-K).")
    p.add_argument("--log-level", default="INFO")
    return p.parse_args()


def _resolve_llm_keys(provider: str, model: str) -> None:
    """Match run_baseline.py's API-key resolution (read api_key_*.txt)."""
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
            cand = Path(_REPO_ROOT) / name
            if cand.is_file():
                os.environ["METAGENT_OPENAI_API_KEY"] = cand.read_text().strip()
                return
        return
    # minimax
    if os.environ.get("MINIMAX_API_KEY"):
        return
    for name in ("api_key_minimax.txt", "api_key.txt"):
        cand = Path(_REPO_ROOT) / name
        if cand.is_file():
            os.environ["MINIMAX_API_KEY"] = cand.read_text().strip()
            return


def _smiles_to_ik14(smi: str | None) -> str | None:
    if not smi:
        return None
    try:
        from rdkit import Chem
        from rdkit.Chem.inchi import MolToInchiKey
        m = Chem.MolFromSmiles(smi)
        if m is None:
            return None
        ik = MolToInchiKey(m)
        return ik.split("-")[0] if ik else None
    except Exception:
        return None


def _ident_to_record(ident, *, casmi_meta: dict, gate_pe: dict | None,
                     dump_ranks: bool = False) -> dict:
    """Per-spectrum record for the output JSONL."""
    rec = {
        "spectrum_id": ident.spectrum_id,
        "casmi_dataset": casmi_meta.get("casmi_dataset"),
        "casmi_formula": casmi_meta.get("casmi_formula"),
        "gt_inchikey_first_block": ident.gt_inchikey_first_block,
        "gt_smiles": casmi_meta.get("casmi_gt_smiles"),
        "predicted_inchikey_first_block": ident.predicted_inchikey_first_block,
        "predicted_smiles": ident.predicted_smiles,
        "predicted_score": ident.predicted_score,
        "correct_top1": ident.correct_top1,
        "n_candidates_returned": ident.n_candidates_returned,
        "n_after_exclusion": ident.n_after_exclusion,
        "primary_retriever": ident.primary_retriever,
        "reranker_mode": ident.reranker_mode,
        "rerank_applied": list(ident.rerank_applied),
        "error": ident.error,
    }
    if ident.peak_evidence:
        # Strip the heavy candidates_evaluated table from per-spec records;
        # gate decisions are kept since those drive Phase 6.6 conclusions.
        pe = ident.peak_evidence
        rec["gate"] = {
            k: pe.get(k)
            for k in ("conditional_skipped", "gate_reason", "gate_msclip_top1", "gate_msclip_gap")
            if k in pe
        } or None
    # Phase 6.7 — LLM-as-reranker outputs (populated when reranker_mode='llm').
    if ident.reranker_mode == "llm":
        rec["llm_rerank"] = {
            "narrative": ident.llm_rerank_narrative,
            "peak_claims": list(ident.llm_rerank_peak_claims),
            "confidence": ident.llm_rerank_confidence,
            "fallback_used": ident.llm_rerank_fallback_used,
            "parse_error": ident.llm_rerank_parse_error,
            # Phase 6.7-A: LLM's preferred ordering over the rerank head.
            "ranked_indices": list(ident.llm_rerank_ranked_indices or []),
        }
    # Phase 6.7-A: dump post-primary-sort top-K ranked candidates for MRR.
    if dump_ranks and ident.ranked_candidates:
        rec["ranked_candidates"] = list(ident.ranked_candidates)
    return rec


def main() -> int:
    args = _parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper()),
                        format="%(asctime)s [%(levelname)s] %(message)s")
    log = logging.getLogger("run_casmi")

    if args.casmi == "2022":
        casmi_root = args.casmi_root or DEFAULT_CASMI_2022_ROOT
        if not casmi_root.exists():
            raise SystemExit(f"CASMI 2022 root not found: {casmi_root}")
        args.out_dir.mkdir(parents=True, exist_ok=True)
        log.info("loading CASMI 2022 specs from %s", casmi_root)
        specs = load_casmi_2022_specs(casmi_root)
        log.info("loading PubChem retrieval index")
        retrieval = PubChemRetrievalIndex.from_dir(casmi_root / "retrieval_hdf")
        casmi_2016_candidates_dir = None
    elif args.casmi == "2016_cat2":
        casmi_root = args.casmi_root or DEFAULT_CASMI_2016_CAT2_ROOT
        if not casmi_root.exists():
            raise SystemExit(f"CASMI 2016 cat2 root not found: {casmi_root}")
        args.out_dir.mkdir(parents=True, exist_ok=True)
        log.info("loading CASMI 2016 cat2 specs from %s", casmi_root)
        specs = load_casmi_2016_cat2_specs(casmi_root)
        retrieval = None  # CASMI 2016 uses per-challenge CSV, not a retrieval index
        casmi_2016_candidates_dir = (args.casmi_2016_candidates_dir
                                     or DEFAULT_CASMI_2016_CANDIDATES_DIR)
        if not casmi_2016_candidates_dir.exists():
            raise SystemExit(f"CASMI 2016 candidates dir not found: {casmi_2016_candidates_dir}")
    else:
        raise SystemExit(f"unsupported --casmi value: {args.casmi}")
    if args.limit:
        specs = specs[: args.limit]
    log.info("loaded %d specs", len(specs))

    rerank_with = tuple(s for s in args.rerank_with.split(",") if s.strip())

    # Phase 6.7 — LLM chat_fn / chat_kwargs (only used when reranker_mode='llm').
    chat_fn = None
    llm_chat_kwargs = None
    if args.reranker == "llm":
        provider, model = resolve_narrative_llm(args.narrative_llm)
        _resolve_llm_keys(provider, model)
        if provider == "openai":
            os.environ["METAGENT_LLM_PROVIDER"] = "openai"
            os.environ["METAGENT_OPENAI_MODEL"] = model
        chat_fn = llm_client.chat
        llm_chat_kwargs = {
            "temperature": args.llm_temperature,
            "model": model,
            "caller": "casmi_llm_reranker",
            **_chat_kwargs(provider),
        }
        log.info("LLM reranker: %s (%s, model=%s)", args.narrative_llm, provider, model)

    out_jsonl = args.out_dir / "casmi_identifications.jsonl"
    n_correct = 0
    n_with_pred = 0
    n_skip = 0
    n_total = 0
    n_no_pool = 0
    t0 = time.perf_counter()
    with out_jsonl.open("w") as f_out:
        for i, spec in enumerate(specs):
            t_spec = time.perf_counter()
            task_dict = casmi_spec_to_task_dict(spec)
            if args.casmi == "2016_cat2":
                pool = build_casmi_2016_pool(
                    spec.spectrum_id, spec.precursor_mz,
                    candidates_dir=casmi_2016_candidates_dir,
                    max_candidates=args.max_candidates,
                )
            else:
                pool = build_pubchem_pool(
                    spec.formula, spec.precursor_mz, retrieval,
                    max_candidates=args.max_candidates,
                )
            if not pool:
                log.warning("no PubChem pool for %s (formula=%s)", spec.spectrum_id, spec.formula)
                n_no_pool += 1
                rec = {
                    "spectrum_id": spec.spectrum_id,
                    "casmi_dataset": spec.dataset,
                    "casmi_formula": spec.formula,
                    "gt_inchikey_first_block": spec.inchikey_first_block,
                    "gt_smiles": spec.smiles,
                    "predicted_inchikey_first_block": None,
                    "predicted_smiles": None,
                    "correct_top1": False,
                    "error": "no_pubchem_pool",
                }
                f_out.write(json.dumps(rec) + "\n")
                n_total += 1
                continue

            ident = identify_spectrum(
                task_dict,
                exclusion_source_ids=frozenset(),  # no GNPS source — nothing to exclude
                top_k=args.top_k,
                min_score=args.min_score,
                libraries=("inhouse",),
                candidate_pool=pool,
                use_gnps=False,
                primary_retriever=args.primary_retriever,
                reranker_mode=args.reranker,
                rerank_with=rerank_with,
                rerank_top_k=args.rerank_top_k,
                cfmid_cache_dir=args.cfmid_cache_dir,
                llm_chat_fn=chat_fn,
                llm_chat_kwargs=llm_chat_kwargs,
            )
            n_total += 1
            if ident.predicted_inchikey_first_block:
                n_with_pred += 1
            if ident.correct_top1 is True:
                n_correct += 1
            if ident.peak_evidence and ident.peak_evidence.get("conditional_skipped"):
                n_skip += 1
            rec = _ident_to_record(ident, casmi_meta=task_dict, gate_pe=ident.peak_evidence,
                                   dump_ranks=args.dump_ranks)
            f_out.write(json.dumps(rec) + "\n")
            f_out.flush()

            elapsed = time.perf_counter() - t_spec
            if (i + 1) % 10 == 0 or (i + 1) == len(specs):
                log.info("spec %d/%d  %s  pool=%d  pred=%s  correct=%s  t=%.2fs",
                         i + 1, len(specs), spec.spectrum_id, len(pool),
                         ident.predicted_inchikey_first_block, ident.correct_top1, elapsed)

    elapsed_total = time.perf_counter() - t0
    id_acc = (n_correct / n_total) if n_total else 0.0
    summary = {
        "casmi_dataset": args.casmi,
        "casmi_root": str(casmi_root),
        "out_dir": str(args.out_dir),
        "primary_retriever": args.primary_retriever,
        "reranker_mode": args.reranker,
        "rerank_with": list(rerank_with),
        "rerank_top_k": args.rerank_top_k,
        "max_candidates_per_spec": args.max_candidates,
        "n_specs": n_total,
        "n_with_pred": n_with_pred,
        "n_correct": n_correct,
        "n_no_pubchem_pool": n_no_pool,
        "n_conditional_skipped": n_skip,
        "id_acc": round(id_acc, 4),
        "elapsed_seconds": round(elapsed_total, 1),
    }
    (args.out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    log.info("=" * 60)
    log.info("CASMI %s  primary=%s  reranker=%s",
             args.casmi, args.primary_retriever, args.reranker)
    log.info("  n_specs=%d  n_correct=%d  id_acc=%.4f", n_total, n_correct, id_acc)
    log.info("  conditional_skipped=%d  no_pool=%d  elapsed=%.1fs",
             n_skip, n_no_pool, elapsed_total)
    log.info("  per-spec JSONL: %s", out_jsonl)
    log.info("  summary:        %s", args.out_dir / "summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

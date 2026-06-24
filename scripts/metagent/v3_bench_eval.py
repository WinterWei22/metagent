"""V3 benchmark evaluation driver — MetAgent Stage 2 + 2A structure enrichment.

Runs MetAgent Stage 2 (ConcordReactRunner) on the new 344-task benchmark
(metagent_bench_easy_v3.jsonl) with StructureResolver pre-enrichment.

Key differences from previous eval drivers:
  1. Source:      data/benchmark/metagent_bench_v2/metagent_bench_easy_v3.jsonl
  2. Task format: new tasks wrap metabolites under input.differential_metabolites
  3. Enrichment:  StructureResolver (2A) adds inchikey_first_block + kegg_id to each
                  metabolite — critical for Human1/Recon2.2 so LLM can call RaMP with
                  KEGG IDs rather than opaque MAM/BiGG slugs
  4. Output:      status/<task_id>.json + path_x_full/<task_id>.json
                  compatible with full344_pathway_scorecard.py

Usage:
    PYTHONPATH=. METAGENT_LLM_LOG_PATH=logs/concord/v3_bench_eval_2a.jsonl \\
        python scripts/metagent/v3_bench_eval.py \\
            --stratum hmdb_ramp --limit 20 \\
            --out data/metagent/v3_bench_eval_2a

    # Score after run:
    PYTHONPATH=. python3 scripts/metagent/full344_pathway_scorecard.py \\
        --out-dir data/metagent/v3_bench_eval_2a \\
        --benchmark data/benchmark/metagent_bench_v2/metagent_bench_easy_v3.jsonl \\
        --relevant-sidecar data/benchmark/metagent_bench_v2/relevant_sets_easy_v3.json \\
        --gold-sidecar data/benchmark/metagent_bench_v2/gold_drivers_easy_v3.json \\
        --ramp /data/weiwentao/llm_agent_metabolomics/ramp.sqlite
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

_KEY_FILE = Path(__file__).resolve().parents[3] / "metagent_day1_v5/api_key_minimax.txt"


def _bootstrap_llm_env() -> None:
    """Set MINIMAX_API_KEY + METAGENT_LLM_PROVIDER from key file if not already set.

    Must be called before importing common.llm_client (which reads PROVIDER at
    module-load time). The import is deferred to after this call.
    """
    if not os.environ.get("MINIMAX_API_KEY") and _KEY_FILE.exists():
        os.environ["MINIMAX_API_KEY"] = _KEY_FILE.read_text(encoding="utf-8").strip()
        logging.info("Loaded MINIMAX_API_KEY from %s", _KEY_FILE)
    if not os.environ.get("METAGENT_LLM_PROVIDER"):
        if os.environ.get("MINIMAX_API_KEY"):
            os.environ["METAGENT_LLM_PROVIDER"] = "minimax"
        elif os.environ.get("METAGENT_OPENAI_API_KEY"):
            os.environ["METAGENT_LLM_PROVIDER"] = "openai"


_bootstrap_llm_env()

from common.llm_client import chat_with_tools as _llm_chat
from verifier.helpers.judge_cost_cap import reset_run_level_tracker
from verifier.agent import verify_sub6 as _b1_verify_sub6
from concord.agent.react_runner import ConcordReactRunner
from concord.lookup.structure_resolver import StructureResolver, _collect_cands

_BENCHMARK = Path("data/benchmark/metagent_bench_v2/metagent_bench_easy_v3.jsonl")
_TRACE_PREFIX = "v3_bench_eval_2a"
_DEFAULT_K = 5
_write_lock = threading.Lock()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(s: str | None) -> str | None:
    return _HTML_TAG_RE.sub("", s) if s else s


# ---------------------------------------------------------------------------
# Stratum helpers
# ---------------------------------------------------------------------------

def _stratum_of_task_id(task_id: str) -> str:
    if "human1" in task_id:
        return "human1"
    if "recon2" in task_id:
        return "recon22"
    if "sub6_easy" in task_id:
        return "sub6"
    return "hmdb_ramp"


# ---------------------------------------------------------------------------
# 2A metabolite enrichment
# ---------------------------------------------------------------------------

def _enrich_metabolite(
    met: dict[str, Any],
    stratum: str,
    resolver: StructureResolver,
    chebi_lookup: Any,
) -> dict[str, Any]:
    """Return enriched shallow copy of one metabolite dict.

    Adds (non-destructively):
    - inchikey_first_block   first 14 chars of InChIKey — structural identity shown in prompt
    - kegg_id                KEGG compound ID where resolvable — lets LLM call RaMP tools
    - name                   display name if missing (Human1 / Recon2.2 have none)
    """
    met = dict(met)
    mid = str(met["id"])
    id_type = str(met["id_type"])

    res = resolver.resolve(mid, id_type, stratum=stratum)
    if res.inchikey:
        met.setdefault("inchikey", res.inchikey)
        met["inchikey_first_block"] = res.inchikey[:14]

    # Cross-namespace xrefs from GEM table / direct id_type
    cands = _collect_cands(mid, id_type, resolver._gem, resolver._bigg_index)

    if id_type == "KEGG":
        met.setdefault("kegg_id", mid)
    elif cands.get("KEGG"):
        met.setdefault("kegg_id", cands["KEGG"])

    # Name enrichment for Human1 / Recon2.2 (benchmark has no name field)
    if not met.get("name") and chebi_lookup is not None:
        kegg_id = cands.get("KEGG") or (mid if id_type == "KEGG" else None)
        hmdb_id = cands.get("HMDB") or (mid if id_type == "HMDB" else None)
        rec = None
        for ns, ext in (("KEGG", kegg_id), ("HMDB", hmdb_id)):
            if not ext:
                continue
            try:
                rec = chebi_lookup.lookup_by_xref(ns, ext)
            except Exception:
                pass
            if rec:
                break
        if rec and rec.name:
            met["name"] = _strip_html(rec.name)
    met.setdefault("name", mid)  # ultimate fallback
    return met


def _normalize_task(
    raw: dict[str, Any],
    resolver: StructureResolver,
    chebi_lookup: Any,
) -> dict[str, Any]:
    """Convert new-benchmark task to runner-compatible format with 2A enrichment."""
    task_id = raw["task_id"]
    stratum = _stratum_of_task_id(task_id)
    mets_raw = raw.get("input", {}).get("differential_metabolites", [])
    enriched = [_enrich_metabolite(m, stratum, resolver, chebi_lookup) for m in mets_raw]
    return {"task_id": task_id, "differential_metabolites": enriched}


# ---------------------------------------------------------------------------
# Status file helpers
# ---------------------------------------------------------------------------

def _write_status(status_dir: Path, task_id: str, row: dict[str, Any]) -> None:
    p = status_dir / f"{task_id}.json"
    p.write_text(json.dumps(row, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _make_status(
    task: dict[str, Any],
    fb: Any | None,
    *,
    wall: float,
    crash_msg: str | None = None,
) -> dict[str, Any]:
    """Build the per-task status dict written to status/<task_id>.json."""
    task_id = task.get("task_id", "unknown")
    stratum = _stratum_of_task_id(task_id)
    ok = crash_msg is None
    row: dict[str, Any] = {
        "task_id": task_id,
        "stratum": stratum,
        "ok": ok,
        "wall_seconds": round(wall, 1),
    }
    if crash_msg:
        row["error"] = crash_msg
        return row
    if fb is None:
        row["ok"] = False
        row["error"] = "no result"
        return row
    # Extract signals from ConcordFeedbackResult
    fr = fb.final_react_result
    fv = fb.final_verdict
    signals: dict[str, Any] = {
        "task_id": task_id,
        "final_iter_idx": fb.final_iter_idx,
        "rollback_reason": fb.rollback_reason,
        "n_feedback_iterations": fb.n_feedback_iterations,
        "n_tool_calls": fr.n_distinct_tools_called,
        "tools_called": fr.tools_called,
        "termination_reason": fr.termination_reason,
        "error": fr.error,
    }
    if fv and fv.ok and fv.verdict:
        vt = fv.verdict
        try:
            totals = vt.verdicts_total or {}
        except AttributeError:
            totals = {}
        signals["n_supported"] = totals.get("SUPPORTED", 0)
        signals["n_unsupported"] = totals.get("UNSUPPORTED", 0)
        signals["n_contradicted"] = totals.get("CONTRADICTED", 0)
        signals["n_dropped"] = totals.get("DROPPED", 0)
    row["signals"] = signals
    return row


# ---------------------------------------------------------------------------
# Per-task worker
# ---------------------------------------------------------------------------

def _run_one(
    raw_task: dict[str, Any],
    runner: ConcordReactRunner,
    resolver: StructureResolver,
    chebi_lookup: Any,
    status_dir: Path,
    full_dir: Path,
    progress_lock: threading.Lock,
    counter: dict[str, int],
    n_tasks: int,
) -> dict[str, Any]:
    tid = raw_task.get("task_id", "unknown")
    t0 = time.time()
    trace_id = f"{_TRACE_PREFIX}.{tid}"

    # 2A enrichment
    try:
        task = _normalize_task(raw_task, resolver, chebi_lookup)
    except Exception as exc:
        logging.warning("[%s] 2A enrichment failed (%s), using raw metabolites", tid, exc)
        task = {
            "task_id": tid,
            "differential_metabolites": raw_task.get("input", {}).get("differential_metabolites", []),
        }

    fb = None
    crash_msg = None
    try:
        fb = runner.run_task_with_feedback(task, trace_id=trace_id)
    except Exception as exc:
        crash_msg = f"{type(exc).__name__}: {exc}"
        logging.exception("[%s] crashed: %s", tid, exc)

    wall = time.time() - t0
    status = _make_status(task, fb, wall=wall, crash_msg=crash_msg)

    # Persist status
    _write_status(status_dir, tid, status)

    # Persist full dump (ConcordFeedbackResult → dict)
    if fb is not None:
        dump = dataclasses.asdict(fb)
        dump["_enriched_metabolites"] = task["differential_metabolites"]
        (full_dir / f"{tid}.json").write_text(
            json.dumps(dump, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    # Progress log
    with progress_lock:
        counter["done"] += 1
        if crash_msg:
            counter["crash"] += 1
        done = counter["done"]
    logging.info(
        "[%d/%d] %s %.0fs ok=%s tools=%s",
        done, n_tasks, tid, wall, not crash_msg,
        status.get("signals", {}).get("n_tool_calls", "?"),
    )
    return status


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="V3 benchmark eval with 2A structure enrichment")
    p.add_argument("--benchmark", default=str(_BENCHMARK))
    p.add_argument(
        "--stratum",
        choices=["hmdb_ramp", "sub6", "human1", "recon22", "all"],
        default="hmdb_ramp",
    )
    p.add_argument("--limit", type=int, default=20, help="Max tasks per stratum")
    p.add_argument("--task-ids", nargs="*", help="Run specific task IDs only")
    p.add_argument(
        "--out", default="data/metagent/v3_bench_eval_2a",
        help="Output root (status/ and path_x_full/ created here)",
    )
    p.add_argument("--k", type=int, default=_DEFAULT_K, help="Concurrency")
    p.add_argument("--max-react-turns", type=int, default=8)
    p.add_argument("--max-feedback-iters", type=int, default=1)
    p.add_argument("--llm-model", default=None)
    p.add_argument("--llm-provider", default=None)
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    bench_path = Path(args.benchmark)
    all_tasks = [json.loads(l) for l in bench_path.read_text().splitlines() if l.strip()]
    logging.info("Loaded %d tasks from %s", len(all_tasks), bench_path)

    if args.task_ids:
        id_set = set(args.task_ids)
        tasks = [t for t in all_tasks if t["task_id"] in id_set]
    elif args.stratum == "all":
        tasks = all_tasks[: args.limit]
    else:
        tasks = [
            t for t in all_tasks if _stratum_of_task_id(t["task_id"]) == args.stratum
        ][: args.limit]

    logging.info(
        "Running %d tasks (stratum=%s limit=%d)", len(tasks), args.stratum, args.limit
    )

    out_root = Path(args.out)
    status_dir = out_root / "status"
    full_dir = out_root / "path_x_full"
    status_dir.mkdir(parents=True, exist_ok=True)
    full_dir.mkdir(parents=True, exist_ok=True)

    logging.info("Initialising StructureResolver (2A)…")
    resolver = StructureResolver()
    try:
        from concord.lookup.chebi import ChebiLookup
        chebi_lookup = ChebiLookup()
    except Exception:
        chebi_lookup = None
        logging.warning("ChEBI lookup unavailable; names may be missing for Human1/Recon2.2")

    # Resolve provider/model: CLI arg > env var > hardcoded default.
    # ConcordReactRunner defaults to "openai"/"gpt-5.5" if not supplied, so
    # we must pass them explicitly — relying on the env var alone is not enough
    # because the runner stores the value at construction time.
    _prov = args.llm_provider or os.environ.get("METAGENT_LLM_PROVIDER", "openai")
    _model = args.llm_model or (
        os.environ.get("METAGENT_MINIMAX_MODEL", "MiniMax-M2.7-highspeed")
        if _prov == "minimax"
        else os.environ.get("METAGENT_OPENAI_MODEL", "gpt-5.5")
    )
    logging.info("LLM provider=%s model=%s", _prov, _model)
    runner_kwargs: dict[str, Any] = {
        "chat_with_tools": _llm_chat,
        "verifier_fn": _b1_verify_sub6,
        "max_react_turns": args.max_react_turns,
        "max_feedback_iters": args.max_feedback_iters,
        "llm_provider": _prov,
        "llm_model": _model,
    }
    runner = ConcordReactRunner(**runner_kwargs)
    reset_run_level_tracker()

    n_tasks = len(tasks)
    progress_lock = threading.Lock()
    counter = {"done": 0, "crash": 0}
    t_start = time.time()

    with ThreadPoolExecutor(max_workers=args.k) as pool:
        futures = {
            pool.submit(
                _run_one, t, runner, resolver, chebi_lookup,
                status_dir, full_dir, progress_lock, counter, n_tasks,
            ): t["task_id"]
            for t in tasks
        }
        for fut in as_completed(futures):
            fut.result()  # propagate exceptions to main thread

    wall_total = time.time() - t_start
    n_ok = n_tasks - counter["crash"]
    logging.info(
        "Done: %d/%d ok | %d crash | %.0fs total",
        n_ok, n_tasks, counter["crash"], wall_total,
    )
    logging.info(
        "\nScore with:\n"
        "  PYTHONPATH=. python3 scripts/metagent/full344_pathway_scorecard.py \\\n"
        "    --out-dir %s \\\n"
        "    --benchmark %s \\\n"
        "    --relevant-sidecar data/benchmark/metagent_bench_v2/relevant_sets_easy_v3.json \\\n"
        "    --gold-sidecar data/benchmark/metagent_bench_v2/gold_drivers_easy_v3.json \\\n"
        "    --ramp /data/weiwentao/llm_agent_metabolomics/ramp.sqlite",
        out_root, bench_path,
    )


if __name__ == "__main__":
    main()

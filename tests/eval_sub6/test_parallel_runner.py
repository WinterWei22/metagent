"""Unit tests for evaluation/sub6/parallel_runner.py (phase A3 D0a).

Coverage:
  - sequential mode (max_workers=1) and pool mode (max_workers>=2)
  - per-task error isolation (one crash does not poison the pool)
  - input order preserved in outputs
  - dispatcher cache thread-locality (parallel tasks do NOT share cache)
  - progress callback fires once per completion
"""
from __future__ import annotations

import os
import sys
import threading
import time
from unittest.mock import patch

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import pytest

from evaluation.sub6.parallel_runner import (
    TaskOutcome,
    make_progress_logger,
    run_tasks_parallel,
)


def _stub_processor(task: dict) -> dict:
    """Pretend to do work proportional to ``task['cost_ms']``."""
    cost_ms = int(task.get("cost_ms", 10))
    time.sleep(cost_ms / 1000.0)
    return {"echo": task["task_id"], "cost_ms": cost_ms}


# ---------------------------------------------------------------------------
# Basic dispatch + ordering
# ---------------------------------------------------------------------------


class TestDispatch:
    def test_sequential_mode(self):
        tasks = [{"task_id": f"t{i}", "cost_ms": 5} for i in range(3)]
        outcomes = run_tasks_parallel(tasks, _stub_processor, max_workers=1)
        assert [o.task_id for o in outcomes] == ["t0", "t1", "t2"]
        assert all(o.error is None for o in outcomes)
        assert all(o.result == {"echo": o.task_id, "cost_ms": 5} for o in outcomes)

    def test_parallel_mode_preserves_input_order(self):
        # Task 0 sleeps longer than task 9 — pool will finish them out of
        # order, but the returned list still mirrors input order.
        tasks = [
            {"task_id": "slow", "cost_ms": 80},
            {"task_id": "fast1", "cost_ms": 5},
            {"task_id": "fast2", "cost_ms": 5},
        ]
        outcomes = run_tasks_parallel(tasks, _stub_processor, max_workers=3)
        assert [o.task_id for o in outcomes] == ["slow", "fast1", "fast2"]
        # The "slow" task did finish later (timing assertion):
        assert outcomes[0].finished_at > outcomes[1].finished_at

    def test_parallel_speeds_up_vs_sequential(self):
        # 5 tasks × 60 ms each: sequential ~300 ms; K=5 ~60-80 ms.
        # We don't assert exact ratios (CI noise), but K=5 wall must be
        # well under 2/3 of K=1 wall — that proves the pool engaged.
        tasks = [{"task_id": f"t{i}", "cost_ms": 60} for i in range(5)]
        t0 = time.perf_counter()
        run_tasks_parallel(tasks, _stub_processor, max_workers=1)
        seq = time.perf_counter() - t0
        t0 = time.perf_counter()
        run_tasks_parallel(tasks, _stub_processor, max_workers=5)
        par = time.perf_counter() - t0
        # Parallel run should be at most 2/3 of sequential.
        assert par < seq * 0.67, f"K=5 wall {par:.3f}s not < 2/3 of K=1 {seq:.3f}s"


# ---------------------------------------------------------------------------
# Per-task error isolation
# ---------------------------------------------------------------------------


class TestErrorIsolation:
    def test_single_task_crash_does_not_poison_pool(self):
        tasks = [
            {"task_id": "good1", "cost_ms": 5},
            {"task_id": "BOOM", "cost_ms": 5},
            {"task_id": "good2", "cost_ms": 5},
        ]

        def crashy(task):
            if task["task_id"] == "BOOM":
                raise RuntimeError("simulated crash")
            return _stub_processor(task)

        outcomes = run_tasks_parallel(tasks, crashy, max_workers=3)
        assert outcomes[0].error is None and outcomes[0].result["echo"] == "good1"
        assert outcomes[1].error and "RuntimeError" in outcomes[1].error
        assert outcomes[1].result is None
        assert outcomes[2].error is None and outcomes[2].result["echo"] == "good2"


# ---------------------------------------------------------------------------
# Progress callback
# ---------------------------------------------------------------------------


class TestProgressCallback:
    def test_callback_fires_per_task(self):
        tasks = [{"task_id": f"t{i}", "cost_ms": 5} for i in range(4)]
        seen: list[str] = []
        lock = threading.Lock()

        def cb(o: TaskOutcome) -> None:
            with lock:
                seen.append(o.task_id)

        run_tasks_parallel(tasks, _stub_processor, max_workers=2, on_progress=cb)
        assert sorted(seen) == ["t0", "t1", "t2", "t3"]

    def test_callback_exception_does_not_kill_pool(self):
        tasks = [{"task_id": f"t{i}", "cost_ms": 5} for i in range(3)]

        def cb(o: TaskOutcome) -> None:
            raise RuntimeError("callback always raises")

        outcomes = run_tasks_parallel(tasks, _stub_processor, max_workers=2, on_progress=cb)
        # All tasks still completed despite callback raising every time.
        assert all(o.error is None for o in outcomes)


# ---------------------------------------------------------------------------
# Dispatcher cache thread-locality (D0a critical)
# ---------------------------------------------------------------------------


class TestDispatcherCacheThreadLocality:
    """Each worker thread must see its own dispatch cache.

    Without thread-locality, task A's tool calls would cause task B to
    return cached responses from A, which is exactly the wrong semantic
    for parallel pilots.
    """

    def test_threads_have_independent_caches(self):
        from tools.agent_tools import dispatcher
        # Reset master-thread cache to a known state.
        dispatcher.reset_call_cache()

        results_per_thread: dict[int, dict] = {}
        n_calls_per_thread: dict[int, int] = {}
        lock = threading.Lock()

        def call_in_thread(payload):
            n_calls_per_thread[threading.get_ident()] = (
                n_calls_per_thread.get(threading.get_ident(), 0) + 1
            )
            return {"echo_thread": threading.get_ident(),
                    "echo_arg": payload["compound_kegg_ids"][0]}

        def worker(thread_idx: int) -> None:
            # Each thread resets its own cache and dispatches the same
            # query. With per-thread caches, each thread's first call
            # invokes the wrapper (no cache hit) and its second call
            # hits its own cache. Two threads → two wrapper invocations.
            dispatcher.reset_call_cache()
            with patch.dict(
                dispatcher.WRAPPERS,
                {"query_ramp_enrichment": call_in_thread},
            ):
                env1 = dispatcher.dispatch({
                    "name": "query_ramp_enrichment",
                    "arguments": {"compound_kegg_ids": ["C00031"]},
                })
                env2 = dispatcher.dispatch({
                    "name": "query_ramp_enrichment",
                    "arguments": {"compound_kegg_ids": ["C00031"]},
                })
            with lock:
                results_per_thread[thread_idx] = (env1, env2)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Each thread saw a fresh (uncached) first call and a cached second.
        for thread_idx, (env1, env2) in results_per_thread.items():
            assert env1["cached"] is False
            assert env2["cached"] is True

        # Wrapper was invoked once per thread (3 threads → 3 invocations),
        # not 6 (= 2 calls × 3 threads) and not 1 (= one shared cache).
        assert sum(n_calls_per_thread.values()) == 3, (
            f"expected 3 wrapper invocations (one per thread), got "
            f"{n_calls_per_thread}"
        )


# ---------------------------------------------------------------------------
# make_progress_logger — sanity smoke
# ---------------------------------------------------------------------------


class TestProgressLogger:
    def test_logger_callable_accepts_outcomes(self):
        cb = make_progress_logger(total=3, prefix="t")
        # Just call it three times; no exceptions, no assertions on output.
        for tid in ("a", "b", "c"):
            o = TaskOutcome(task_id=tid, elapsed_s=1.0)
            cb(o)

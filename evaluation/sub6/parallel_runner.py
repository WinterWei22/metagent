"""Thread-pool task runner for the A3 pilot drivers.

D5 ran 20 tasks in 600 min sequential (mean 935 s / task). The wall-time
bottleneck is verifier I/O — multiple LLM round-trips against MiniMax
plus per-claim SQLite reads. With network-bound work the GIL is
released during requests / sqlite operations, so a thread pool delivers
real concurrency without async refactoring.

Phase A3 D0a target: 5-task pilot in ≤30 min wall (= ~6 min / task
effective when K=5 saturates the pool). For 63-task v4 full run with
K=5 the linear extrapolation is ~2 h per variant, ~6 h for 3 variants
— versus ~30 h sequential.

The pool primitive is :func:`run_tasks_parallel`. It expects
``processor_fn`` to be a *blocking* callable that returns a result
record per task (the legacy ``_process_one_task`` from
``run_a2_d4_3way``); per-task exceptions are captured into the result
dict so a single-task crash does not poison the pool.

Caveats
-------

* ``tools.agent_tools.dispatcher`` was made thread-local in D0a so each
  worker has its own dedup cache. The verifier opens its own SQLite
  connection per call (no shared connection); pathway lookups go
  through ``RAMP_DB_PATH`` which is read-only.
* MiniMax rate-limit live probe: 10 short parallel chats all OK. Long
  feedback narratives may behave differently — the retry layer in
  ``common/llm_client.py`` (D0b) absorbs sporadic 5xx / 529.
* Output ordering is preserved: ``run_tasks_parallel`` returns a list
  in the same order as ``tasks``, regardless of completion order.
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

logger = logging.getLogger(__name__)


@dataclass
class TaskOutcome:
    """One task's outcome from a parallel run.

    On success ``result`` carries the processor's return value (typically
    a dict with summary + hash_pair keys, mirroring the D4 driver's
    return shape). On failure ``error`` is the formatted exception
    string and ``result`` stays None.

    ``elapsed_s`` is the wall-clock time the worker thread spent on this
    task; pool queue-wait is excluded.
    """
    task_id: str
    result: dict[str, Any] | None = None
    error: str | None = None
    elapsed_s: float = 0.0
    queued_at: float = 0.0
    started_at: float = 0.0
    finished_at: float = 0.0


def run_tasks_parallel(
    tasks: list[dict],
    processor_fn: Callable[[dict], dict],
    *,
    max_workers: int = 5,
    on_progress: Callable[[TaskOutcome], None] | None = None,
    task_id_key: str = "task_id",
) -> list[TaskOutcome]:
    """Run ``processor_fn(task)`` for each task in ``tasks`` with a thread pool.

    The pool size is bounded by ``max_workers`` (D0a default 5). Each
    task is dispatched to a free worker thread; per-task exceptions are
    caught and stored in the returned ``TaskOutcome``. The ``on_progress``
    hook fires once per task completion (in the order tasks finish, not
    the order they were submitted) and is intended for progress logging
    during long batches.

    The returned list mirrors the input order, regardless of the order
    tasks completed. Callers that want completion-order results can
    filter on ``finished_at``.

    Note on exception handling: this wrapper catches *all* Exception
    subclasses (including KeyboardInterrupt's children when raised
    inside a worker thread). The pool drains gracefully — one task's
    crash does not abort the others.
    """
    n = len(tasks)
    outcomes: list[TaskOutcome] = [
        TaskOutcome(task_id=str(t.get(task_id_key, f"task_{i}")))
        for i, t in enumerate(tasks)
    ]
    progress_lock = threading.Lock()
    completed = {"n": 0}

    def worker(index: int, task: dict) -> TaskOutcome:
        out = outcomes[index]
        out.started_at = time.perf_counter()
        try:
            result = processor_fn(task)
            out.result = result
        except BaseException as exc:  # noqa: BLE001 — we want every error captured
            out.error = f"{type(exc).__name__}: {exc}"
            logger.exception("task %s crashed inside parallel worker", out.task_id)
        finally:
            out.finished_at = time.perf_counter()
            out.elapsed_s = out.finished_at - out.started_at
        return out

    queued_at_anchor = time.perf_counter()
    for o in outcomes:
        o.queued_at = queued_at_anchor

    if max_workers <= 1:
        # Sequential — easy debug path; no pool overhead.
        for i, t in enumerate(tasks):
            o = worker(i, t)
            with progress_lock:
                completed["n"] += 1
            if on_progress:
                try:
                    on_progress(o)
                except Exception:  # pragma: no cover — progress is informational
                    logger.exception("on_progress callback raised; ignoring")
        return outcomes

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(worker, i, t): i for i, t in enumerate(tasks)}
        for fut in as_completed(futures):
            try:
                outcome = fut.result()
            except BaseException as exc:  # noqa: BLE001
                idx = futures[fut]
                outcome = outcomes[idx]
                outcome.error = f"future_unexpected: {type(exc).__name__}: {exc}"
                logger.exception("future for %s raised unexpectedly", outcome.task_id)
            with progress_lock:
                completed["n"] += 1
            if on_progress:
                try:
                    on_progress(outcome)
                except Exception:  # pragma: no cover
                    logger.exception("on_progress callback raised; ignoring")

    return outcomes


# ---------------------------------------------------------------------------
# Lightweight progress logger — drop-in for the runner's CLI
# ---------------------------------------------------------------------------


def make_progress_logger(total: int, *, prefix: str = "task") -> Callable[[TaskOutcome], None]:
    """Return a callback that logs `[i/N] task_id elapsed=...s status=...`.

    The counter is per-callback-invocation, so output is deterministic in
    completion order even though tasks finish out of submission order.
    """
    state = {"n": 0}
    lock = threading.Lock()

    def cb(o: TaskOutcome) -> None:
        with lock:
            state["n"] += 1
            i = state["n"]
        status = "OK" if o.error is None else "ERR"
        msg = f"[{i}/{total}] {prefix}={o.task_id} elapsed={o.elapsed_s:.1f}s status={status}"
        if o.error:
            msg += f" err={o.error[:80]}"
        logger.info(msg)
        # Also print so subprocess captures see progress without LOGLEVEL.
        print(msg, flush=True)

    return cb

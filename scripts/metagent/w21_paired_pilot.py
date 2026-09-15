from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from scripts.concord import w10_d4_path_x_full as path_x


def _task_id_safe(task_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in task_id)


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.exists():
        return rows
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def _run_with_per_task_timeout(args: argparse.Namespace) -> int:
    tasks = _read_jsonl(args.benchmark)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.full_dir.mkdir(parents=True, exist_ok=True)

    work_dir = args.output.parent / "_per_task_inputs"
    work_dir.mkdir(parents=True, exist_ok=True)
    per_task_rows: list[dict] = []
    any_timeout = False
    any_error = False

    for task in tasks:
        tid = str(task.get("task_id") or "unknown")
        safe_tid = _task_id_safe(tid)
        task_input = work_dir / f"{safe_tid}.jsonl"
        task_output = work_dir / f"{safe_tid}.results.jsonl"
        task_summary = work_dir / f"{safe_tid}.summary.json"
        task_full = args.full_dir / safe_tid
        task_input.write_text(
            json.dumps(task, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8",
        )
        cmd = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--benchmark", str(task_input),
            "--prompt-path", str(args.prompt_path),
            "--output", str(task_output),
            "--summary", str(task_summary),
            "--full-dir", str(task_full),
            "--llm-log", str(args.llm_log),
            "--k-concurrent", "1",
            "--judge-cost-cap-usd", str(args.judge_cost_cap_usd),
        ]
        started = time.time()
        try:
            proc = subprocess.run(
                cmd,
                cwd=Path(__file__).resolve().parents[2],
                timeout=args.per_task_timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            any_timeout = True
            per_task_rows.append({
                "task_id": tid,
                "framework_signal_timeout": True,
                "framework_signal_crash": (
                    "task_wall_timeout: exceeded "
                    f"{float(args.per_task_timeout_seconds):.1f}s"
                ),
                "wall_seconds": time.time() - started,
                "timeout_seconds": float(args.per_task_timeout_seconds),
            })
            continue

        rows = _read_jsonl(task_output)
        if rows:
            per_task_rows.extend(rows)
        else:
            any_error = True
            per_task_rows.append({
                "task_id": tid,
                "framework_signal_crash": (
                    f"task_subprocess_empty_output: returncode={proc.returncode}"
                ),
                "wall_seconds": time.time() - started,
            })
        if proc.returncode != 0:
            any_error = True

    _write_jsonl(args.output, per_task_rows)
    summary = path_x.aggregate_path_x(per_task_rows)
    summary["timeout_total"] = sum(
        1 for row in per_task_rows if row.get("framework_signal_timeout")
    )
    summary["per_task_timeout_seconds"] = float(args.per_task_timeout_seconds)
    args.summary.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return 1 if any_timeout or any_error else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--prompt-path", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--full-dir", type=Path, required=True)
    parser.add_argument("--llm-log", type=Path, required=True)
    parser.add_argument("--k-concurrent", type=int, default=1)
    parser.add_argument("--judge-cost-cap-usd", type=float, default=3.0)
    parser.add_argument("--per-task-timeout-seconds", type=float, default=None)
    args = parser.parse_args()

    if not args.prompt_path.exists():
        raise FileNotFoundError(args.prompt_path)

    if args.per_task_timeout_seconds is not None:
        return _run_with_per_task_timeout(args)

    import concord.agent.system_prompts as system_prompts

    system_prompts._PROMPT_PATH = args.prompt_path.resolve()
    system_prompts._load_template.cache_clear()

    argv = [
        "w21_paired_pilot",
        "--benchmark", str(args.benchmark),
        "--output", str(args.output),
        "--summary", str(args.summary),
        "--full-dir", str(args.full_dir),
        "--llm-log", str(args.llm_log),
        "--k-concurrent", str(args.k_concurrent),
        "--judge-cost-cap-usd", str(args.judge_cost_cap_usd),
        "--max-feedback-iters", "1",
        "--max-react-turns", "8",
    ]
    old_argv = os.sys.argv
    try:
        os.sys.argv = argv
        return path_x.main()
    finally:
        os.sys.argv = old_argv


if __name__ == "__main__":
    raise SystemExit(main())

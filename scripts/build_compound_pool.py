#!/usr/bin/env python
"""End-to-end MassBank → CompoundPool builder.

Pipes :func:`tools.benchmark.massbank_downloader.download_massbank` →
:func:`tools.benchmark.massbank_parser.parse_massbank_directory` →
:func:`tools.benchmark.massbank_normalizer.normalize_record` →
:func:`tools.benchmark.massbank_filter.filter_records` →
:func:`tools.benchmark.massbank_filter.build_compound_pool` and writes the
resulting :class:`tools.benchmark.massbank_filter.CompoundPool` to JSONL.

All log output goes to **stderr** so the output JSONL stays clean even
when the caller redirects stdout.

Example
-------
.. code-block:: shell

    python scripts/build_compound_pool.py \\
        --contributors RIKEN \\
        --ion-modes positive negative \\
        --output /data/.../massbank/processed/compound_pool_riken.jsonl \\
        --min-peaks 15 \\
        --classify
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

# Allow `python scripts/build_compound_pool.py` to find `tools.*` and `schemas.*`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.benchmark.massbank_downloader import download_massbank  # noqa: E402
from tools.benchmark.massbank_filter import (  # noqa: E402
    FilterCriteria,
    build_compound_pool,
    filter_records,
)
from tools.benchmark.massbank_normalizer import normalize_record  # noqa: E402
from tools.benchmark.massbank_parser import (  # noqa: E402
    MassBankParseError,
    parse_massbank_directory,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Build a benchmark compound pool from MassBank-data.",
    )
    p.add_argument(
        "--contributors", nargs="+", default=None,
        help="Contributor whitelist (e.g. RIKEN Eawag). Default: all.",
    )
    p.add_argument(
        "--ion-modes", nargs="+", choices=["positive", "negative"],
        default=["positive", "negative"],
        help="Ion modes to keep. Default: both.",
    )
    p.add_argument(
        "--instrument-types", nargs="+",
        default=["Q-TOF", "Orbitrap", "QFT", "FT-ICR"],
        help=(
            "Substring whitelist over MassBank's instrument_type field. "
            "Default keeps Q-TOF and Orbitrap variants."
        ),
    )
    p.add_argument(
        "--ms-level", nargs="+", default=["MS2"],
        help="MS levels to keep. Default: MS2.",
    )
    p.add_argument(
        "--min-peaks", type=int, default=15,
        help="Minimum peak count after normalisation. Default 15 (protocol §2.2).",
    )
    p.add_argument(
        "--precursor-min", type=float, default=100.0, help="Default 100.",
    )
    p.add_argument(
        "--precursor-max", type=float, default=800.0, help="Default 800.",
    )
    p.add_argument(
        "--output", "-o", required=True, type=Path,
        help="Path to write the JSONL. Parent dir created if missing.",
    )
    p.add_argument(
        "--target-dir", type=Path, default=None,
        help="MassBank cache dir. Default: $METAGENT_MASSBANK_DIR or data/raw/massbank.",
    )
    p.add_argument(
        "--classify", action="store_true",
        help="Populate compound_class via ClassyFire / SMARTS.",
    )
    p.add_argument(
        "--no-classyfire", action="store_true",
        help="With --classify: skip the network and use SMARTS only.",
    )
    p.add_argument(
        "--force-redownload", action="store_true",
        help="Ignore the download checkpoint marker.",
    )
    p.add_argument(
        "--no-git", action="store_true",
        help="Use HTTP zip download instead of git clone.",
    )
    p.add_argument(
        "--limit", type=int, default=None,
        help="Stop after N successfully parsed records — useful for smoke tests.",
    )
    p.add_argument(
        "--verbose", "-v", action="store_true", help="DEBUG-level logging.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="[%(levelname)s] %(message)s",
    )
    log = logging.getLogger("build_compound_pool")

    # 1. Download (or hit checkpoint).
    log.info("MassBank download: target=%s", args.target_dir or os.environ.get(
        "METAGENT_MASSBANK_DIR", "data/raw/massbank"))
    download = download_massbank(
        target_dir=args.target_dir,
        contributors=args.contributors,
        use_git=not args.no_git,
        force_refresh=args.force_redownload,
    )
    if download.skipped:
        log.info("MassBank download: %s (already present, skip)", download.downloaded_dir)
    else:
        log.info(
            "MassBank download: %s via %s in %.1fs",
            download.downloaded_dir, download.used_method, download.download_time_seconds,
        )

    if args.contributors:
        # Use the contributor-resolved subset to drive parse — both for
        # correctness and so the file count printed below is meaningful.
        parse_root = download.downloaded_dir
    else:
        parse_root = download.downloaded_dir

    # 2. Parse + normalise (streaming).
    log.info(
        "Parsing records from %s (contributors=%s)…",
        parse_root, args.contributors or "ALL",
    )
    n_parsed = 0
    n_parse_errors = 0
    n_parse_warnings = 0
    n_normalised = 0
    drop_reasons: dict[str, int] = {}
    normalised_stream = []

    t0 = time.monotonic()
    try:
        for rec in parse_massbank_directory(
            parse_root, contributor_filter=args.contributors,
        ):
            n_parsed += 1
            if rec.parse_warnings:
                n_parse_warnings += 1
            norm = normalize_record(rec)
            if norm is None:
                drop_reasons["normalize"] = drop_reasons.get("normalize", 0) + 1
                continue
            n_normalised += 1
            normalised_stream.append(norm)
            if args.limit is not None and n_normalised >= args.limit:
                log.info("Hit --limit %d; stopping iteration early.", args.limit)
                break
    except MassBankParseError as e:
        log.error("Fatal parse error walking %s: %s", parse_root, e)
        return 2
    elapsed = time.monotonic() - t0

    log.info(
        "Parse complete: %d files parsed, %d normalised, %d dropped at normalise stage, "
        "%d had parse warnings (%.1fs)",
        n_parsed, n_normalised, drop_reasons.get("normalize", 0), n_parse_warnings, elapsed,
    )
    if n_normalised == 0:
        log.error("No records survived normalisation. Aborting.")
        return 3

    # 3. Filter.
    criteria = FilterCriteria(
        ion_mode=args.ion_modes,
        instrument_types=args.instrument_types,
        ms_level=args.ms_level,
        min_peaks=args.min_peaks,
        precursor_mz_range=(args.precursor_min, args.precursor_max),
        contributors=args.contributors,
    )
    log.info("Filtering with criteria: %s", criteria)
    filtered = filter_records(normalised_stream, criteria)
    log.info("After filtering: %d records", len(filtered))
    if not filtered:
        log.error("0 records survived filtering. Aborting.")
        return 4

    # 4. Classify + pool.
    log.info(
        "Classification: classify=%s, use_classyfire=%s",
        args.classify, not args.no_classyfire,
    )
    pool = build_compound_pool(
        filtered, classify=args.classify, use_classyfire=not args.no_classyfire,
    )

    # 5. Save.
    log.info("Saving pool to %s", args.output)
    pool.save(args.output)

    # 6. Stats summary.
    stats = pool.stats()
    log.info("Stats summary:")
    log.info("    total: %d", stats["total"])
    log.info("    by_mode: %s", _format_kv(stats["by_mode"]))
    log.info("    by_class: %s", _format_kv(stats["by_class"]))
    log.info("    by_instrument (top 5): %s", _format_kv(_top_n(stats["by_instrument"], 5)))
    log.info("    by_contributor (top 5): %s", _format_kv(_top_n(stats["by_contributor"], 5)))
    return 0


def _format_kv(d: dict[str, int]) -> str:
    if not d:
        return "{}"
    items = sorted(d.items(), key=lambda kv: -kv[1])
    return ", ".join(f"{k}={v}" for k, v in items)


def _top_n(d: dict[str, int], n: int) -> dict[str, int]:
    items = sorted(d.items(), key=lambda kv: -kv[1])[:n]
    return dict(items)


if __name__ == "__main__":
    sys.exit(main())

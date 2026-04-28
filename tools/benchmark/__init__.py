"""Benchmark construction utilities for MetAgent-Bench.

This package wraps the MassBank-data acquisition + parsing + normalization +
filtering pipeline that feeds Sub-1..Sub-6 of the benchmark protocol
(``docs/decisions/2026-04-28_benchmark_protocol_v2.md``).

Downstream sessions consume :class:`CompoundPool` objects produced by
:func:`build_compound_pool` and never touch raw MassBank records.
"""

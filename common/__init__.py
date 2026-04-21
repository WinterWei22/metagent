"""Shared utilities for MetAgent tools and orchestrator.

Tools may import from common/ but may NOT import from other tools/ packages.
"""
from common.gnps_loader import (
    GnpsRecord,
    iter_records as iter_gnps_records,
    load_v0_usable as load_gnps_v0_usable,
    normalise_peaks,
    parse_record as parse_gnps_record,
)
from common.llm_client import (
    chat,
    chat_raw,
    clear_mock,
    count_tokens,
    extract_json_list,
    extract_process_name,
    set_mock,
    strip_thinking,
)
from common.mona_loader import (
    MonaRecord,
    iter_records as iter_mona_records,
    load_lcms_positive,
    parse_record as parse_mona_record,
    parse_spectrum_string,
)

__all__ = [
    # llm
    "chat",
    "chat_raw",
    "clear_mock",
    "count_tokens",
    "extract_json_list",
    "extract_process_name",
    "set_mock",
    "strip_thinking",
    # gnps (primary spectrum library)
    "GnpsRecord",
    "iter_gnps_records",
    "load_gnps_v0_usable",
    "normalise_peaks",
    "parse_gnps_record",
    # mona (secondary: compound metadata for track C)
    "MonaRecord",
    "iter_mona_records",
    "load_lcms_positive",
    "parse_mona_record",
    "parse_spectrum_string",
]

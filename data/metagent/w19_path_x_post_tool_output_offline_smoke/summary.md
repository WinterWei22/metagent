# W19 Tool-Output Offline Smoke

- Mode: offline replay projection; no LLM/API calls.
- Tasks inspected: 59
- Missing full dumps: 0
- Raw final claims inspected: 708
- Tasks with W19 tool-output hit: 26
- SUPPORTED: 44
- CONTRADICTED: 13
- UNVERIFIABLE_V0/unparsed/absent: 651
- Conservative upper-bound UV drop projection: 5.00pp
- Cost: $0.00, because this replay used stored W18 full dumps and deterministic carrier lookup only.

## Caveat
This is a smoke/projection artifact, not a final Path-X rerun metric. The W18 full dumps store per-claim verification as a Pydantic repr string, so this replay does not safely filter to only claims that were UV before W19.

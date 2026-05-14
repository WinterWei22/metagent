# Cases_1

Primary curated case for Stage 1 paper drafting:
- `challenge_095_case_report.md`: human-readable case report.
- `challenge_095_case_data.json`: complete extracted source records plus reconstructed CFM-ID evidence.
- `challenge_095_top5_evidence.csv`: compact top-5 comparison table.
- `challenge_095_rerank_spectrum_comparison.png`: spectrum comparison figure.
- `challenge_095_rerank_spectrum_comparison.svg`: vector version of the spectrum comparison figure.

Case choice: `Challenge-095`, because MS-CLIP and weighted reranking miss the ground truth while the LLM reranker selects it, and the LLM's main peak-level rationale passes basic mass/element checks.

Deprecated review artifact retained for traceability:
- `challenge_090_*`: earlier candidate case. It is less suitable because one LLM claim mislabeled a CNS loss as COS.

Additional curated case:
- `challenge_033_case_report.md`: second human-readable case report.
- `challenge_033_case_data.json`: complete source records plus reconstructed CFM-ID evidence.
- `challenge_033_top5_evidence.csv`: compact top-5 comparison table.
- `challenge_033_rerank_spectrum_comparison.png`: spectrum comparison figure.
- `challenge_033_rerank_spectrum_comparison.svg`: vector version of the spectrum comparison figure.


"""Sub-6 baseline LLM evaluation pipeline.

Companion to ``reports/benchmark/sub6_evaluation_guide.md``. The modules
here render compound lists into a single prompt template, call MiniMax
through ``common.llm_client``, and grade narratives against the
``ground_truth_*`` fields kept on each task. No verifier code is involved.
"""

# Dirty-tree Disposition — MetAgent-v1-0514

**Freeze date:** 2026-05-14
**Branch action:** main / feature/agent-phase-a3 / release/v1-0514 all converged to the same HEAD (the freeze tag point)
**Goal:** every untracked file at session start (224 entries) has been categorised and either committed or explicitly excluded via `.gitignore`. Working tree is clean.

## Starting state

At session start the worktree had:

- 10 modified files on `feature/agent-phase-a3` (all pre-existing local work, never committed)
- 224 untracked entries spanning runtime essentials, tests, scripts, reports, prompts, paper artifacts, eval outputs, logs, and caches
- Tag candidate `2bf6517` (current `main` HEAD) failed import for `evaluation.sub6.run_sub6b_react_feedback`, `verifier.agent`, and `tools.agent_tools` because 7 runtime-essential files lived only in the untracked working tree

## Disposition by category

### A. Modified files → 3 commits (pre-freeze, on feature/agent-phase-a3 BEFORE freeze series)

These were committed in an earlier session segment, sitting between `2bf6517` and the freeze series:

| Commit | Files | Rationale |
|---|---|---|
| `d0304c7` feat(verifier): Layer F — SIRIUS + CFM-ID cross-validation | `verifier/layers/peak_mechanistic.py`, `verifier/claim_extractor.py`, `verifier/prompts/extract_claims.py`, `tests/test_verifier/test_layer_peak_mechanistic.py` | Layer F double-voter rewrite + rule-based extractor (Phase 6.4) |
| `116a892` feat(bench): LIPID MAPS / WikiPathways Lipids fallback | `scripts/build_sub6/build_all.py`, `tools/benchmark/sub6/task_constructor.py` | LIPID MAPS source registered in benchmark constructor |
| `24d71d4` feat(eval): sub6 rerank wiring (Phase 6.2-6.5) + MSG Top-3 | `evaluation/sub6/run_sub6a.py`, `scripts/eval_sub6/run_baseline.py`, `scripts/eval_sub6/aggregate_msg_ablation.py`, `data/paper_figures/phase6_7d_msg_results.csv` | Phase 6.2/6.3/6.5 reranker CLI/runner wiring |

### B. Untracked → 8 commits (freeze series, on main)

After fast-forwarding `main` from `2bf6517` to `24d71d4` (picking up the three feature commits above), the following 8 commits were applied to bring the tag state to a runnable, fully-tracked baseline. Each commit is one logical category; no cross-cutting mixing.

| # | Commit | Subject | Files | Net LOC |
|---:|---|---|---:|---:|
| 1 | `8b44256` | chore(gitignore): block eval outputs, logs, caches, downloaded references | 1 | +37/-19 |
| 2 | `d2e48be` | feat(runtime): include untracked runtime essentials missing from 2bf6517 | 13 | +3915 |
| 3 | `e2546ad` | test: add untracked test coverage for runtime essentials + Phase 6.x | 18 | +3495 |
| 4 | `85d7ecc` | feat(scripts): batch runners, aggregators, spike regressions, paper figures | 42 | +8097 |
| 5 | `e061f00` | feat(ui): live pipeline runner + candidate/spectrum renderers | 3 | +534 |
| 6 | `2eb52a7` | docs(reports): audit trail — agent phase audits, benchmark + eval reports | 39 | +12747 |
| 7 | `3a97029` | docs(prompts): track design docs for all phases | 40 | +11591 |
| 8 | `102fba9` | docs(paper): benchmark inputs, paper figures, stage reports, paper drafts | 264 | +39963 |

**Runtime essentials in commit 2** (the previously-blocking 7 files + 6 supporting):

```
schemas/sub6_report.py                         ← verifier.agent imports
tools/benchmark/sub6/__init__.py               ← package init
tools/benchmark/sub6/ramp_enrichment.py        ← agent dispatcher imports
tools/benchmark/sub6/compound_curator.py       ← build_sub6 imports
tools/benchmark/sub6/spectrum_lookup.py        ← Sub-6A library_search imports
tools/benchmark/classyfire/{__init__,client}.py ← classyfire client
tools/lipidmaps/{__init__,client,lmsd_loader,pathway_loader}.py
verifier/layers/driver_metabolite.py           ← verifier.agent dispatch
verifier/layers/set_enrichment.py              ← verifier.agent dispatch
```

Post-commit verification: 13 of 13 key modules import cleanly at HEAD. `evaluation.sub6.run_sub6b_react_feedback` and `verifier.agent` (which failed at `2bf6517`) now resolve.

### C. Untracked → `.gitignore` (NOT committed)

The following large or regeneratable artifacts are explicitly excluded by commit `8b44256`. Their existence on disk is preserved for the current developer but they will not enter fresh clones.

| Path glob | Size | Reason |
|---|---|---|
| `data/eval/sub6/v*/` | 307 MB | Run outputs (verdicts, narratives, per-task persistence). Regeneratable from code + benchmark inputs. |
| `data/eval/sub6/sub6a_*.jsonl`, `data/eval/sub6/sub6b_*.jsonl` | ~50 MB | Aggregated verdict files for individual versioned runs. |
| `logs/` | 213 MB | Per-task log files from K=10 parallel runs. |
| `results/` | 88 MB | Older per-pool result artifacts (v1/v2/v3 baselines). |
| `data/classyfire_cache.sqlite` | 864 KB | Local cache; rehydrates from ClassyFire on first miss. |
| `data/kegg/kgml/` | 7.6 MB | KEGG XML cache. |
| `data/lipidmaps/` | 41 MB | Downloaded LMSD + WikiPathways Lipids reference data. |
| `ref_paper/MSAgent.pdf` | 21 MB | Third-party reference paper PDF. |
| `data/processed/*_npc_classified*.jsonl` | 35 MB | NPClassifier outputs; regeneratable via `scripts/classyfire/classify_*.py`. |
| `data/processed/.npclassifier_*_checkpoint.json` | ~MB | NPClassifier resume checkpoints. |

### D. Sensitive — explicit policy

| Path | Policy |
|---|---|
| `api_key_*.txt` (4 files at repo root) | Already gitignored from session start. Never staged. Used at runtime via `_resolve_api_key` reading the file content. |
| `0a73a08` snapshot commit (side branch `v3-state-snapshot-2026-05-08`, contains leaked API keys) | **Left untouched** per prior user decision (local-only, no remote exists). The 7 runtime essentials referenced from that snapshot were re-committed CLEAN in `d2e48be` from the current working tree, NOT cherry-picked from `0a73a08`. |

### E. Other branches

The user instructed "其他代码可以舍弃掉了" (other code can be discarded). The following stale branches remain in `git branch -a` but are not part of the v1 freeze lineage:

```
feature/agent-phase-a1, feature/agent-phase-a2 — superseded by main
feature/casmi-eval-stack, feature/lipidmaps, feature/sub6-msclip-ablation,
  feature/nm002-leakage-filter, feature/library-search-mass-filter,
  feature/layer6c-phrase-resolver, feature/massbank-data-pipeline,
  feature/sub6-baseline-eval, feature/sub6-fixes-p1-p2,
  feature/sub6-pathway-fix, feature/sub6-v2-* (6 variants),
  feature/subb6-v2-expand, feature/verifier-kegg-hierarchy
v3-state-snapshot-2026-05-08 — see (D), contains leaked keys; do not touch
claude/<various>             — Claude worktree branches (auto-cleaned)
```

No action taken on these branches. They may be deleted manually later; doing so will not affect the `MetAgent-v1-0514` tag.

## Verification

Working tree state immediately before tagging:

```
$ git status --short
(empty)

$ git log --oneline main -12
102fba9 docs(paper): benchmark inputs, paper figures, stage reports, paper drafts
3a97029 docs(prompts): track design docs for all phases (A1-A3, Phase 6.2-6.7D, freezes)
2eb52a7 docs(reports): audit trail — agent phase audits, benchmark + eval reports
e061f00 feat(ui): live pipeline runner + candidate/spectrum renderers
85d7ecc feat(scripts): batch runners, aggregators, spike regressions, paper figures
e2546ad test: add untracked test coverage for runtime essentials + Phase 6.x
d2e48be feat(runtime): include untracked runtime essentials missing from 2bf6517
8b44256 chore(gitignore): block eval outputs, logs, caches, downloaded references
24d71d4 feat(eval): sub6 rerank wiring (Phase 6.2-6.5) + MSG Top-3 acc
116a892 feat(bench): LIPID MAPS / WikiPathways Lipids fallback for sub6 build
d0304c7 feat(verifier): Layer F — SIRIUS + CFM-ID cross-validation for peak claims
2bf6517 feat(agent): A4 D0 — cross-LLM smoke hooks (GPT-5.5 via viviai relay)
```

Branches all at HEAD = `102fba9`:

```
$ git branch -v
  feature/agent-phase-a3 102fba9 docs(paper): benchmark inputs, ...
* main                   102fba9 docs(paper): benchmark inputs, ...
  release/v1-0514        102fba9 docs(paper): benchmark inputs, ...
```

Import smoke (13/13 modules pass at the new HEAD; logged in `MetAgent-v1-0514.md` §3). End-to-end Sub-6A + Sub-6B smoke is documented in the same file.

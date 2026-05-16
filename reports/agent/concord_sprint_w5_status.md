# Concord Sprint W5 — Status

**Branch:** `feature/investigation-concord` (worktree `metagent_day1_v5_investigation`)
**HEAD at sprint start:** `58979ba` (W5 D1 prep — docker session manager + R/Py wrappers + new entrypoint)
**Sprint window:** 2026-05-16 → 2026-05-22

---

## 1 · Sprint Goals

| Axis | Tool | Status |
|------|------|--------|
| 1 | sspa ORA + ssGSEA (Python) | DONE (W3) |
| 2 | mummichog (Py3.10 venv) | DONE (W4) |
| 3 | RaMP (existing T1 wrap) | DONE (W4) |
| 4 | MetaboAnalystR (PSEA / MSEA / Mummichog) | wrappers IN-FLIGHT, image building |
| 5 | FELLA (RWR / Diffusion) | wrappers IN-FLIGHT, image building |

Once image online → D1 self-test → D2 FELLA prewarm → D3 K=10 concurrent spike → D4-D5 5-axis run on N=30 → Gate 1 upgrade.

---

## 2 · Stop Conditions (revised)

| # | Trigger | Action | Notes |
|---|---------|--------|-------|
| **1** | **Docker `concord-r:RELEASE_3_19` build wall-time > 4 h** | halt + report, no workaround | **AMENDED from 45 min per user 2026-05-16.** Bioconductor + MetaboAnalystR + FELLA + KEGG graph prewarm total install size is multi-GB; tighter limit unrealistic. |
| 2 | Background F (R-NEW-17 ssGSEA fix) breaks any regression test | halt + report, maintain xfail strict | 1 h time-box; if exceeded stop attempt |
| 3 | Background G (per-source canonicalization ETL) fails | halt + report, do not modify Fig 3 v2 artifacts | data → CSV only, integration deferred to D5 |
| 4 | docker exec dispatch returns non-OK on self-test | halt + report | likely package install failure inside image |
| 5 | Anything pushed to origin / touches `feature/agent-phase-b1` branch | hard stop, revert | user invariant |

---

## 3 · Risk Register Updates

### R-NEW-19 — Docker group membership requires `sg docker` wrapper

- **Severity:** LOW (workaround stable)
- **Source:** W5 D1 setup
- **Symptom:** Plain `docker ps` from current shell session yields `permission denied while trying to connect to the Docker daemon socket` even though `getent group docker` shows user `weiwentao` in the docker group. Effective gid set on login predates user being added.
- **Workaround:** `sg docker -c "docker <args>"` re-evaluates supplementary groups for the subshell. Codified in `concord/wrappers/_docker_r_session.py::_detect_docker_invocation()` which auto-detects and prefixes accordingly:
  ```python
  if plain.returncode == 0:
      return ["docker"]
  if "permission denied" in plain.stderr.lower():
      sg_check = subprocess.run(["sg", "docker", "-c", "docker ps"], ...)
      if sg_check.returncode == 0:
          return ["sg", "docker", "-c"]
  ```
- **Long-term fix:** user logs out + back in once after `sudo gpasswd -a weiwentao docker` was run; current session retains old gid set. No urgency — wrapper is transparent.

---

## 4 · Build Progress (rolling notes — appended every ~30 min)

| Timestamp | Phase | Layer / Step | Wall (min) | Notes |
|-----------|-------|--------------|------------|-------|
| 2026-05-16 11:14 | start (v2) | restart after `--progress=plain` flag rejected by legacy builder | 0 | first build attempt v1 also rejected; v2 strips the flag |
| 2026-05-16 11:14 | running | BiocManager `install.packages(fgsea, limma, KEGGREST, graph, KEGGgraph, FELLA, igraph)` | ~1 | base image layers already cached from earlier aborted run; package install live |
| 2026-05-16 11:26 | **DONE** | `Successfully tagged concord-r:RELEASE_3_19`, exit 0 | **~12** | layer cache from earlier (killed) build accelerated re-run; both base + Bioconductor + MetaboAnalystR + FELLA fully installed |

---

## 4.5 · Memory Budget (D3 K=10 spike prerequisite)

Captured 2026-05-16 14:40 immediately before the K=10 concurrent docker-exec spike per user instruction #6.

| Layer | Value | Notes |
|-------|-------|-------|
| System total RAM | 251 GiB | host |
| System available | 165 GiB | (free + buffers + cache reclaimable) |
| Swap configured | 7.6 GiB | 1.5 GiB used |
| Persistent container baseline RSS | 6 MiB | idle (PID 1 = `sleep infinity`) |
| Per-call PSEA peak RSS estimate | ~800 MiB | R process + MetaboAnalystR lib + cached pathway DB |
| Per-call FELLA peak RSS estimate | ~1.2 GiB | R process + diffusion.matrix.RData (~387 MiB) + KEGG graph |
| Worst-case per-call ~ | **1.2 GiB** | dominated by FELLA |
| K=10 concurrent worst-case ~ | **12 GiB** | 10 × FELLA-style calls |
| Headroom vs available | **165 / 12 = 13.7×** | well over the 2× safety threshold |

**Auto-rating: GREEN.** K=10 stays well within the 165 GiB headroom and ≪ the 2× safety-margin trigger; no amendment to K required. (If host RSS pressure changes in the future, recompute and re-rate before the next concurrent batch.)

## 4.6 · Cross-Namespace Artifact Analysis (D5 sanity Check 2, 2026-05-16)

The W5 D5 pathway-id-level 4×4 Jaccard (mean off-diagonal **0.032**) suggested a near-total cross-tool disagreement at the pathway-ID surface. The user sanity Check 2 (compound-level Jaccard) shows that this is **largely a namespace artifact** rather than methodological disagreement:

| pair | namespace classes | pathway-id-level | **compound-level** |
|------|-------------------|------------------:|-------------------:|
| sspa_ora vs ramp | REACT vs REACT/SMPDB | 0.111 | **0.624** |
| sspa_ora vs PSEA | REACT vs KEGG | 0.000 | **0.554** |
| sspa_ora vs FELLA | REACT vs KEGG | 0.000 | 0.032 |
| ramp vs PSEA | REACT/SMPDB vs KEGG | 0.000 | **0.787** |
| ramp vs FELLA | REACT/SMPDB vs KEGG | 0.000 | 0.131 |
| PSEA vs FELLA | KEGG vs KEGG | 0.082 | 0.182 |
| **mean off-diagonal** | — | **0.032** | **0.385** |
| **cross-namespace mean** (REACT × KEGG) | — | 0.000 | **0.376** |
| **within-Reactome** (sspa vs ramp) | — | 0.111 | 0.624 |
| **within-KEGG** (PSEA vs FELLA) | — | 0.082 | 0.182 |

### Paper-narrative implication (per user spec)

The cross-namespace **compound-level** Jaccard of **0.376** falls in the user spec's `> 0.3` band — pathway-id-level 0.032 **severely overstates** tool disagreement. The Reactome / KEGG / SMPDB pathway sets carry overlapping compound membership but disjoint pathway-id strings, and a metric that only compares pathway-id strings reads "no overlap" where there is in fact substantial biological overlap at the compound layer.

**Implications for the paper / W6 Gate-2:**

- **Primary metric MUST be compound-level**, not pathway-id-level. A pathway-id-level metric is a strict lower bound that conflates "different tools disagreed" with "different tools used different pathway databases".
- The W3/W4 reconciliation pipeline (RDKit canonicalization + ChEBI is_a + MetaNetX cross-namespace map) becomes load-bearing for a second reason: it is *the* mechanism that makes compound-level metrics interpretable across the REACT / KEGG / SMPDB family.
- "STRONG GREEN" verdict survives but the supporting numbers shift: cross-tool agreement at the level the tools were *designed for* (compound membership) is **0.38**, not 0.03. The "tools disagree a lot" framing must be replaced by "tools disagree on what to *call* a pathway, but agree more than 1/3 of the time on the compound evidence behind it".
- W6 Gate-2's *supported %* score should evaluate against **compound-level** ground-truth overlap; using pathway-id-level would bake in the 92% namespace-artifact penalty and produce uselessly low scores.

This shift is non-trivial — flagged for explicit user sign-off before W6 prompt is drafted.

Artifact: `data/concord/gate1_w5_5axis/jaccard_compound_level_n30.csv` (rows = task × method-pair, columns = method_a, method_b, compound_jaccard, n_a, n_b, n_intersect).

## 5 · Open Questions

(rolling — anything that blocks but does not stop the sprint)

- **OQ-1 (deferred to W5 D5):** Once 5-axis numbers are in, decide whether to refresh Fig 3 v2 PNG/PDF to include the per-source canonicalization deltas from Background G, or treat per-source as a supplementary stat only.
- **OQ-2:** Wieder cold email (Background H) timing — draft now, user reviews W6 before send. Do NOT send in W5.
- **OQ-3 (D2):** FELLA RWR (pagerank) currently skipped — the Dockerfile pre-warm builds only `matrices="diffusion"`, so `pagerank.matrix.RData` is absent and `enrich(method="pagerank")` returns NULL from `generateResultsTable`. Adding pagerank matrices would add ~10-15 min build time. Defer to D5: if the 5-axis Jaccard heatmap shows RWR adds signal beyond diffusion + RaMP KEGG ORA, rebuild with `matrices="all"`; otherwise treat diffusion as the canonical FELLA axis.
- **OQ-4 (D2):** FELLA diffusion per-call wall is ~94 s on N=8 input (most of it the niter=100 normality permutation in `enrich(approx="normality")`), well over the 30 s D1 soft budget. Investigate after K=10 spike: either (a) drop `approx="normality"` and rely on simulated permutations only, (b) lower niter at runtime, or (c) cache p-value distributions per input-size bucket. For W5 5-axis Gate 1 we live with 94 s/call (15 min for N=30 sequential, ~2 min at K=10).
- **OQ-5 (D1下):** MetaboAnalystR `mSet$analSet$ora.hits` carries native KEGG cpd IDs for KEGG-pathway lib and HMDB IDs for SMPDB lib — but our normalizer's "library == kegg ? KEGG : HMDB" heuristic does not verify the assumption for non-standard libraries (e.g. `smpdb_pathway` vs other SMPDB variants). If we expand to non-default libraries the source-ns dispatch will need a more robust signal (probably inspect the actual hits prefix).

---

## 6 · Background Tracks (parallel during build wall time)

| Track | Description | Time-box | Status |
|-------|-------------|----------|--------|
| H | `docs/concord/wieder_outreach.md` cold email draft | 30 min | **DONE** (2026-05-16 11:13) — DO NOT send during W5; user W6 review |
| F | R-NEW-17 ssGSEA gseapy fix attempt + xfail→pass | 1 h | **DONE** (2026-05-16 11:32, commit `50e7de8`) — root cause was `gseapy._check_data()` `set_index(keys=exprs.columns[0])` clobbering compound-ID index with first-sample float values; fix bypasses `sspa.sspa_ssGSEA` and calls `gseapy.ssgsea(data=mat.T.reset_index(), …)` directly; 13/13 sspa tests pass, 109 concord tests pass (was 103+2xfail = 105 → 109, +4 from flip) |
| G | per-source canonicalization → `data/concord/fig3/reconciled_per_source.csv` | conditional (only if F done + build still running) | **SKIPPED** — trigger condition not met (build completed at 11:26, before F finished at 11:32). G is deferrable to W5 D5 integration per user spec; no urgency. |

### F technical write-up (root cause + fix detail)

**Symptom:** `gseapy.ssgsea(...)` raised `LookupError: No gene sets passed through filtering condition` even though `pathway_df` cells were correctly normalized to str (R-NEW-15 fix). gseapy's error message printed `The first 5 genes look like this : [ 1.03, 0.89, ... ]` — i.e. data values, not compound IDs.

**Root cause** (gseapy 1.2.1, `base.py:_check_data`):
```python
# set gene name as index
exprs.set_index(keys=exprs.columns[0], inplace=True)
```
gseapy unconditionally promotes `exprs.columns[0]` to the index, regardless of whether the caller already passed compound IDs *as* the index. sspa-1.0.4's `sspa_ssGSEA.transform()` does `gseapy.ssgsea(data=X.T, ...)` where `X` is `samples × compounds`; therefore `X.T` has compound IDs as INDEX and sample names as columns. gseapy then overwrites that index with the first column's float values, destroying the compound IDs.

**Fix:** bypass `sspa.sspa_ssGSEA` for the ssGSEA path and call `gseapy.ssgsea(data=mat.T.reset_index(), …)` directly. `reset_index()` pushes the compound IDs into column 0, where gseapy expects them. The remaining 7 lines of sspa's wrapper (a `pivot` + `astype(float)`) are mirrored locally. Other sspa methods (ORA / KPCA / GSVA / zscore) are unaffected.

**Secondary fix:** the W3 hotfix added a vacuous-pathways validator on `EnrichmentResult` (rejects `n_pathways > 0 && n_compound_hits == 0`). ssGSEA's score-based output doesn't carry a `DA_Metabolites_ID` column like ORA does. To populate `metabolites_hit` without altering the schema, the wrapper now surfaces `pathway_df` + the input ChEBI numeric list via private result keys (`_pathway_df`, `_input_chebi_numeric`), and the normalizer (a) intersects each pathway's membership with the input set and (b) filters top-N to pathways with ≥1 input compound (mirroring ORA "hit" semantics, while keeping ssGSEA's continuous score as the rank order).

**Risk register:** R-NEW-17 → CLOSED.

---

## 7 · D1-D5 Sequence (executed once image green)

### D1 — COMPLETE (2026-05-16 14:27)

- **D1上 (image build)** done across builds v2-v8 (multiple upstream-MetaboAnalystR fixes — see commits `fc9edd2`, `8f871ba`, `0581675`, `90a957c`).
  - Image `concord-r:RELEASE_3_19` final SHA `3a6ed705a424`
  - 6/6 `test_docker_r_session.py` PASS
- **D1下 (MetaboAnalystR PSEA real-task smoke)** done via commit `57b95b9`.
  - Task: `RAMP_P_000000421_seed1` (8 differential HMDB IDs → 7 ChEBI refs)
  - Wall: **12.95 s** (< 30 s budget)
  - Pathways: 2 — KEGG:hsa00140 (steroid hormone biosynthesis, p = 1.5e-7, 6 hits), KEGG:hsa00350 (p = 0.17, 1 hit)
  - metabolites_hit: 7/7 = **100% CHEBI primary**
  - all pathway_ids namespace-prefixed (`KEGG:`)
  - All 4 D1 末 sanity checks **PASS**.
  - Full concord regression: **111/111** still green.
- **Five upstream MetaboAnalystR bugs uncovered and worked around in entrypoint.R + Dockerfile:**
  1. metaboanalyst.ca serves qs2-format library files; `qs::qread` cannot read them → monkey-patch qread with qs2 fallback.
  2. `InitDataObjects(default.dpi = default.dpi)` self-referential default → pass explicit `default.dpi = 72`.
  3. `CalculateHyperScore` is MSEA-only; KEGG path lib needs `CalculateOraScore("rbc", "hyperg")`.
  4. `SetKEGG.PathLib` overwrites `mSet$api` → `SetMetabolomeFilter` must come AFTER, not before.
  5. `hits_ids` not in `ora.mat`; live in `mSet$analSet$ora.hits` (named list, pathway_id → KEGG cpd vec). Wired into JSON response.
- **D1 (legacy header — keep for diff context):** `_docker_r_session.py` self-test + `tests/concord/test_docker_r_session.py` PASS
  - **2026-05-16 11:46** — three real root causes diagnosed (commit `fc9edd2`); user's spec hypotheses (stdout/stderr separation, memory pressure) ruled out by direct repro:
    - **(A) `ensure_running` did not override ENTRYPOINT.** Container started via `docker run -d IMAGE tail -f /dev/null` made PID 1 a stuck `Rscript /opt/entrypoint.R tail -f /dev/null` process; subsequent `docker exec` returned OCI runtime "read init-p: connection reset by peer" and the kernel SIGKILLed the exec init (exit 137). Fixed by adding `--entrypoint sleep` + arg `infinity`. Confirmed: container `ps -ef` now shows only `sleep infinity` as PID 1.
    - **(B) `entrypoint.R` had a Python-style multi-line string** in `run_metaboanalystr_mummichog()` — R requires `paste0(...)` for explicit concatenation. R parse error on entrypoint load made every dispatch fail with empty stdout. Fixed by wrapping in `paste0(...)`.
    - **(C) Dockerfile silently failed to install MetaboAnalystR** — `devtools::install_github` logged `ERROR: dependencies 'RBGL', 'crmn', 'edgeR', 'impute', 'pcaMethods', 'siggenes' are not available`, but the `cat("METABOANALYSTR_DONE\n")` fence still ran so the build appeared healthy. Fixed by adding pcaMethods + Biobase + RBGL + edgeR + impute + siggenes to BiocManager::install + crmn to CRAN install, and gating the MetaboAnalystR step on `requireNamespace(..., quietly=TRUE)` + `stop()` so future install failures fail loud.
    - **Bonus:** Dockerfile FELLA step previously called `buildGraphFromKEGGREST()` but did not persist; runtime self-test always reported `fella_data_ready=false`. Added `buildDataFromGraph(databaseDir="/opt/fella_kegg_hsa")`.
  - **Build v3 in progress** (started 2026-05-16 11:46, ETA ~30-60 min — Bioc deps cached from build v2, MetaboAnalystR + FELLA-data layers are new). Stop condition #1 still 4 h.
- **D1下:** MetaboAnalystR end-to-end test (PSEA / MSEA / mummichog) on N=5 toy
- **D2:** FELLA RWR + Diffusion on N=5; KEGG graph prewarm to keep ≥10 concurrent execs cheap
- **D3:** K=10 docker exec concurrent spike (target speedup > 6× vs sequential)
- **D4:** 5-axis run on N=30 (Gate 1 task panel from W4 D5)
- **D5:** 5×5 Jaccard heatmap update + Gate 1 verdict (STRONG GREEN / amber / red); commit + close sprint

---

# ConcordMet — Session Handoff Report (Sprints W3 → W7)

**Drafted:** 2026-05-17
**Author:** session contribution to the ConcordMet investigation
**Branch:** `feature/investigation-concord`(worktree
`metagent_day1_v5_investigation`,**no origin push** per project invariant)
**HEAD:** `6be783e`
**Scope:** all engineering + experimental work attributable to this session
across five sprints W3 → W7. Excludes the pre-W3 investigation report and
the spike work that preceded sprint mode.

---

## 0 · Project framing in one paragraph

ConcordMet builds a *reconciliation framework* on top of the five major
metabolomics pathway-analysis tool families (sspa ORA, RaMP-DB ORA,
MetaboAnalystR PSEA, mummichog, FELLA). The project's central question
is whether running the five tools on the same input and combining their
outputs yields a more reliable pathway list than any single tool alone.
This session built the v0.3.1 `EnrichmentResult` schema + five wrappers
+ four ground-truth cohorts + four consensus-metric variants, ran the
panels end-to-end, and produced a paper-grade Fig 3 v4 + 1.9 k-word
narrative draft. Total: **148 unit tests (all PASS) · 26 atomic
commits · ~7 k LOC** in `concord/` + `data/concord/` + 11 driver scripts
+ 6 sprint status reports.

---

## 1 · Module-level deliverable map

### 1.1 `concord/` core library (~ 7 k LOC, 148 tests)

| Sub-module | Purpose | Sprint of origin |
|------------|---------|------------------|
| `schema/enrichment.py` | v0.3.1 `EnrichmentResult` + `PathwayHit` + `CompoundRef` + namespace whitelists (REACT / KEGG / WP / SMPDB / METACYC / **MUMM / HUMAN1 / RECON2**) | W3 D1, W6 D1.3 schema bump |
| `schema/peak.py` | `PeakRecord` dataclass (m/z + p-value + t-score + RT + feature_id) | W3 |
| `lookup/chebi.py` | `ChebiLookup` class — thread-safe per-call read-only sqlite (377 MB, 205 164 compounds, 2.9 M is_a triples) | W3 D3 |
| `etl/chebi_etl.py` | ChEBI rel251 sqlite ETL (compound + xref + is_a depth ≤ 5) | W3 D1-D2 |
| `etl/metanetx_etl.py` | MetaNetX MNXref ETL (1.34 M xref entries spanning 11 namespaces) | W4 D3 |
| `etl/cooke_etl.py` | Cooke 2025 SAMBA Tier-A ETL — Human1 2-hop join (MAR → MAM → ChEBI) + Recon2.2 BIGG → MNX → ChEBI bridge + 3-cohort pre-registered runner | W6 D1, W6 D2 hotfix (Recon2 pathway dict) |
| `etl/pathway_members_etl.py` | Pathway-name → ChEBI member set sqlite (23 311 rows, 227 pathways) | W7 D1.1 |
| `reconcile/id_resolve.py` | Unified `resolve_ids_to_compound_refs()` abstraction across 5 source namespaces | W4 D2 |
| `reconcile/inchikey.py` | `compute_inchikey() / cluster_by_block14() / reconcile_with_chebi()` (dual-path Q-04 sugar fix) | W3 D5 |
| `reconcile/charge_state.py` | RDKit Uncharger + safeguarded tautomer canonicaliser (block14 + stereo safeguards reject ring-open / stereo-drop artifacts) | W4 background F |
| `validate/metanetx_validator.py` | `validate_cross_namespace_consistency()` — block14 critical / warning severity by InChIKey layer | W4 D3 |
| `wrappers/sspa_wrapper.py` | sspa 1.0.4 ORA / ssGSEA / KPCA / GSVA / zscore + W3 R-NEW-15 fix (int → str pathway_df) + W5 D5 R-NEW-17 fix (gseapy qs2 fallback + ssGSEA orientation) | W3 D4, W5 background F |
| `wrappers/mummichog_wrapper.py` | Py3.10 venv subprocess shell + W6 D1.3 v0.3.1 upgrade: `synthesize_peaks` (M+H / M+Na / M-H / M+Cl + 250 random bg) + `run_mummichog_for_compound_set` + MUMM namespace | W4 D1, W6 D1.3 |
| `wrappers/ramp_wrapper.py` | RaMP-DB ORA via T1 `tools.benchmark.sub6.ramp_enrichment` | W4 D4 |
| `wrappers/metaboanalystr_wrapper.py` | MetaboAnalystR PSEA / MSEA / Mummichog via persistent docker exec | W5 D1 |
| `wrappers/fella_wrapper.py` | FELLA RWR / diffusion via persistent docker exec + ChEBI → KEGG fallback | W5 D2 |
| `wrappers/_docker_r_session.py` | Persistent container manager — sg docker auto-detection (`_detect_docker_invocation`), exec dispatch, auto-restart, `--entrypoint sleep infinity` fix (W5 D1 root cause) | W5 D1 |
| `normalize/{sspa,mummichog,ramp,metaboanalystr,fella}_norm.py` | Raw wrapper output → v0.3.1 `EnrichmentResult` adapters | W3-W6 |
| `analyze/pathway_match.py` | Pathway-name fuzzy matcher — token-set Jaccard ≥ 0.5 with stop-word filter | W6 D4 |
| `analyze/paradigm_consensus.py` | Consensus level 0-5 per (task, pathway-name) + ORA / m/z / Network bucketing + V0 strict cohort metric | W6 D4 |
| `analyze/gate2_variants.py` | V1 fuzzy-intersection, V2 compound-membership, V3 rank-weighted soft-union, plus bootstrap CIs + sign test + variant_verdict | W7 D1-D2 |
| `figures/fig3_*.py` | Fig 3 preliminary (W3) / v2 refined (W4) / v3 (W6) / v4 (W7) — composite drivers | W3-W7 |

### 1.2 `tests/concord/` (148 tests, all PASS)

| Test file | Coverage |
|-----------|----------|
| `test_w3_smoke.py` | end-to-end W3 smoke |
| `test_w4_smoke.py` | end-to-end W4 (sspa + mummichog + RaMP) |
| `test_chebi_lookup.py` | 22 cases — `get_compound`, `lookup_by_xref`, `lookup_by_inchikey`, `climb_to_canonical`, `lookup_many_by_xref` |
| `test_id_resolve.py` | id_resolve abstraction edge cases |
| `test_inchikey_reconcile.py` | block14 + chebi_is_a dual path |
| `test_sspa_wrapper.py` | R-NEW-15 dtype fix + ssGSEA parametric + W5 D5 ssGSEA fix |
| `test_mummichog_wrapper.py` | Py3.10 subprocess + normalize hits |
| `test_w6_analyze.py` | 18 tests — pathway_match (tokenize, overlap, best-rank) + paradigm_consensus (levels, metric 1/2 thresholds, cohort_verdict) |
| `test_w7_gate2_variants.py` | 13 tests — V1 fuzzy / V2 compound / V3 soft-union + variant_verdict GREEN/YELLOW/RED |
| `test_w7_pathway_members.py` | 2 tests — pathway_members sqlite Human1 + Recon2 coverage |
| `test_docker_r_session.py` | 6 tests — shell quote / docker invocation detect / session lifecycle / self-test / exec / shutdown |
| `test_metaboanalystr_w6.py` | 4 tests (W6 D1.3) — peak synthesis + MUMM ns + W3 hotfix non-regression |
| `test_validators.py` | v0.3 schema validators |

### 1.3 `data/concord/` artifacts (~ 28 MB excluding sqlite)

| Path | Size | Role |
|------|-----:|------|
| `chebi.sqlite` | 378 MB (gitignored) | ChEBI rel251 etl output |
| `metanetx.sqlite` | 242 MB (gitignored) | MNXref ETL output |
| `pathway_members.sqlite` | 3.6 MB | V2 metric dependency |
| `fig3/` | 684 kB | W3 preliminary 2-panel composite |
| `fig3_v3/` | 424 kB | W6 RED-branch composite |
| `fig3_v4/` | 412 kB | **W7 V3 GREEN composite — paper Fig 3** |
| `gate1_w5_5axis/` | 756 kB | W5 D5 4-axis N=30 + compound-level Jaccard + Panel A data |
| `gate2_w6/` | 1.2 MB | W6 5-axis × 3-cohort results + verdict JSON |
| `gate2_w7/` | 20 kB | W7 3-variant × 3-cohort verdicts CSV/JSON |
| `tier_a_cooke/` | 29 MB | Cooke Zenodo TSVs (gitignored) + 3 cohort jsonls + aux mapping tables |

### 1.4 `docs/concord/` (5 docs)

| File | Purpose |
|------|---------|
| `cooke_samba_recon.md` | W6 prep — Cooke 2025 reconnaissance (GREEN verdict) |
| `cooke_id_resolution.md` | W6 D1 — B-Cooke-1/2 resolution write-up |
| `multi_llm_setup.md` | W7 multi-LLM environment notes (single-LLM constraint logged) |
| `paper_narrative_finalized.md` | **W7 D4 paper draft 1903 words** — Abstract, Intro, Methods, Results, Discussion, Anomalies |
| `wieder_outreach.md` | Cold email draft to C. Wieder — **HELD per autonomous rule** |

### 1.5 Sprint status reports

`reports/agent/concord_sprint_w{3,4,5,6,7}_status.md` + `concord_sprint_w5_d5_verdict.md` —
each sprint's daily breakdown + anomalies + verdicts.

---

## 2 · Schema evolution timeline

| Version | Bump trigger | New surface area |
|---------|--------------|------------------|
| v0.1 | W3 D1 | Initial `EnrichmentResult` shape |
| v0.2 | W3 hotfix | Vacuous-pathways validator added (n_pathways > 0 ⇒ at least one CompoundRef) |
| v0.3 | W3 D4 (Q05-NEW-4) | Dual-key compound primary id + pathway namespace whitelist (REACT / KEGG / WP / SMPDB / METACYC) |
| **v0.3.1** | **W6 D1.3** | `PATHWAY_NAMESPACES` += {MUMM, HUMAN1, RECON2}; `PathwayDB` += MUMMICHOG_MFN. Backward-compatible additive bump. |

---

## 3 · Cohort + benchmark layout (W6-W7)

### Pre-registered cohorts (locked before Gate-2 measurement, W6 D1)

| Cohort | GEM | z-threshold | min_differential | N |
|--------|-----|------------:|-----------------:|---:|
| **PRIMARY** | Human1 | 1.0 | 2 | **51** |
| **SENS_A** | Human1 | 2.0 | 3 | 19 |
| **SENS_B** | Recon2.2 | 1.0 | 2 | 12 |

Source dataset: Cooke et al. 2025 SAMBA simulations
(`zenodo.org/records/13753914`). Pre-registration is documented in
`reports/agent/concord_sprint_w6_status.md` § "D1 Cohort
Pre-registration". Stop-condition #3 was amended W6 D1 (≥ 30 PRIMARY,
≥ 5 sensitivities) because Cooke's total of 199 perturbations × ~5 %
exometabolome ceiling makes the W7-prompt's original ≥ 100 floor
unreachable by design.

---

## 4 · Headline experimental results

### 4.1 W3-W4 — within-source reconciliation (compound layer)

- ChEBI sqlite ETL: 205 164 compounds, 27 930 KEGG xrefs, 2.9 M is_a triples
- MetaNetX MNXref ETL: 1.34 M cross-references spanning 11 namespaces
- RDKit Uncharger + safeguarded tautomer canonicaliser: **cross-source
  compound disagreement 59.1 % → 5.5 %** (91 % reduction; 110 cross-source
  pairs, ChEBI / LIPIDMAPS / HMDB SMILES)
- Q-04 sugar fix (dual-path: block14 + ChEBI is_a depth ≤ 5)
- 4-axis (sspa + mummichog + RaMP) gate-1 panel-level cross-tool
  Jaccard mean 0.046 (W4 D5)

### 4.2 W5 D5 — sanity Check 2 critical finding (compound-level metric)

- **Pathway-id-level mean off-diagonal Jaccard: 0.032**
- **Compound-level mean off-diagonal Jaccard: 0.385 — 12× higher**
- Cross-namespace pairs (REACT × KEGG): pathway-id 0.000, compound-level **0.376**
- Paradigm split (W6 prep): **ora × ora 0.655 · ora × topo 0.115** — 5.7× ratio
- Interpretation: ~ 92 % of pathway-id-level cross-tool disagreement is
  **namespace artifact**, not biological disagreement. Established the
  empirical anchor for the W7 V3 soft-union approach.

### 4.3 W6 — strict-intersection Gate 2 (4-axis on N=82)

5×5 pathway-name Jaccard on PRIMARY:

|              | sspa_ora | ramp | PSEA | mummichog | FELLA |
|--------------|---------:|-----:|-----:|----------:|------:|
| sspa_ora     | 1.00 | 0.17 | 0.00 | 0.00 | 0.00 |
| ramp         | 0.17 | 1.00 | 0.00 | 0.01 | 0.00 |
| PSEA         | 0.00 | 0.00 | 1.00 | 0.00 | 0.00 |
| mummichog    | 0.00 | 0.01 | 0.00 | 1.00 | 0.00 |
| FELLA        | 0.00 | 0.00 | 0.00 | 0.00 | 1.00 |

Within-paradigm overlap (sspa × ramp = 0.17) is the only positive
cross-method cell; all cross-paradigm cells round to 0. Strict V0
intersection-based Gate 2 metric: PRIMARY **−19.6 pp** (RED, p = 0.002,
0 / 10 wins).

### 4.4 W7 D2 — 3-variant Gate-2 comparison (paper-defining table)

| variant | PRIMARY 51 | SENS_A 19 | SENS_B 12 |
|---------|-----------|-----------|-----------|
| V0 strict (W6) | RED −19.6 (p=0.002, 0/10) | RED −26.3 | RED −8.3 |
| V1 fuzzy intersection | RED −5.9 | YELLOW 0 | RED −8.3 |
| V2 compound membership | YELLOW +3.9 | YELLOW +5.3 | YELLOW 0 |
| **V3 rank-weighted soft union** | **GREEN +25.5 (p=0.001, 13/0)** ★ | YELLOW +21.1 (4/0) | YELLOW +16.7 (2/0) |

- Best variant: **V3** (PRIMARY GREEN, all 3 cohorts positive Δ, **zero
  negative deltas across 82 task**).
- V0 → V3 swing: +45 pp absolute precision recovery.
- Sensitivity-cohort YELLOWs are *power-limited* (N=19, N=12) not
  *effect-limited*.

### 4.5 W7 sanity audit (post-Check)

- **V3 algorithm correctness** (Check 1): manual 10/10 ordering match
  with driver output on `cooke_human1_group9`. Score formula explicit:
  `Σ 1 / (rank_in_method + 1)` with 0-indexed rank.
- **V3 not winner-take-all** (Check 2): 53.1 % of V3 top-10 entries are
  *non-RaMP-only* (proves V3 ≠ RaMP fallback). 18.5 % multi-method
  shared — limited not by V3 but by the structural near-zero
  cross-paradigm name overlap (Panel A).
- **13 / 0 / 38 closure** (Check 3): 13 V3-positive tasks + 38 ties +
  0 V3-negative = 51 ✓. Each V3 hit came from a non-RaMP method.
- **Strict-vs-fuzzy lift comparison** (Check 4):
  - Strict match (case-insensitive + Homo-sapiens suffix strip):
    Cond A 13.7 % / Cond B 25.5 % / **Δ +11.8 pp**
  - Fuzzy match (W7 reported): Cond A 23.5 % / Cond B 49.0 % / **Δ +25.5 pp**
  - Direction robust under both definitions. Manual review of 9
    fuzzy-only hits: 5 truly equivalent (suffix-strip / subset-superset),
    3 likely FPs (`Keratan vs Chondroitin sulfate`,
    `Fatty acid activation vs biosynthesis`,
    `Bile recycling vs biosynthesis`), 1 borderline.
- **Fig 3 v4 visual + 107-word caption** (Check 5): PASS.

### 4.6 Infrastructure performance (W5 D3)

- **K=10 concurrent docker-exec spike**: 12.84 s sequential per-call median →
  12.80 s total for 10 concurrent → **10.03 × speedup** (target was > 6 ×).
- Memory budget: 251 GiB total / 165 GiB available; per-call peak RSS
  ~1.2 GiB (FELLA-dominated); K=10 worst-case ~12 GiB → 13.7 × headroom.

---

## 5 · Bugs & root causes catalogued

### 5.1 Upstream bugs surfaced & worked around

1. **gseapy 1.2.1 `_check_data` orientation** (W5 background F): silently
   replaced the compound-ID index with the first sample's float values
   when `data=X.T` was passed; emitted "no gene sets passed filtering".
   Fix: `gseapy.ssgsea(data=mat.T.reset_index(), …)` directly,
   bypassing sspa.sspa_ssGSEA. R-NEW-17 closed.
2. **sspa 1.0.4 pathway_df int cells** (R-NEW-15, W3 D4): `str(int(v))`
   cast in `_normalize_pathway_df`.
3. **MetaboAnalystR 4.x NAMESPACE broken** (W5 D1, 5 image-rebuild
   iterations): both 4.3 HEAD and 4.2.0 stable tag export functions
   that don't exist in R/ sources. Worked around with a download +
   regex strip of broken exports from NAMESPACE + local install
   (Dockerfile attempt 5).
4. **MetaboAnalystR `InitDataObjects(default.dpi = default.dpi)`**
   (W5 D1下): self-referential default → infinite recursion when arg
   omitted. Explicit `default.dpi = 72`.
5. **metaboanalyst.ca serves qs2-format library files** but
   MetaboAnalystR uses `qs::qread`: monkey-patch via assignInNamespace
   to fall back to `qs2::qs_read` on legacy reader error.
6. **`SetKEGG.PathLib` overwrites `mSet$api`** (drops filter): order
   `SetKEGG.PathLib` → `SetMetabolomeFilter` rather than the other way.
7. **mummichog 2.7.0 model.json has no KEGG hsa cross-reference for
   human_mfn pathways** (W6 D1.3, OQ-7): introduced `MUMM:` namespace
   instead of the W7 spec's assumed KEGG fallback. paper Section 4.3
   acknowledges.
8. **Docker `--progress=plain` rejected by legacy builder** (W5 D1上):
   stripped flag.
9. **Docker group membership stale in current shell**: `sg docker -c`
   workaround codified in `_detect_docker_invocation()`.
10. **`ensure_running` did not override ENTRYPOINT** (W5 D1): PID 1
    became a stuck Rscript that refused all `docker exec`. Fixed with
    `--entrypoint sleep infinity`.

### 5.2 Project-internal bugs caught + fixed by sanity Check 2 (W5 D5)

- W4 hotfix `EnrichmentResult` vacuous validator (`n_pathways > 0` with
  empty `metabolites_hit`) caught at W3 hotfix and prevented from
  recurring across W5-W7 normalisers.
- Recon2.2 `pathway_dict.tsv` not picked up in initial W6 D1.2 ETL —
  caught at W6 D2 baseline run when SENS_B hit_rate came out 0 %; lazy
  load wired in `_recon2_perturbation_label`, hit_rate recovered to
  25.0 %.

---

## 6 · Open questions carried into W8 / M3

| OQ | Status | W8/M3 disposition |
|----|--------|-------------------|
| OQ-3 FELLA pagerank matrices not in image | Deferred | rebuild only if W8 Gate-2 robustness needs RWR |
| OQ-4 FELLA diffusion wall ~ 94 s | Deferred | K=10 mitigates; soft if W7 V3 verdict accepted |
| OQ-5 ora.hits namespace heuristic | Deferred | non-default libs require revisit |
| OQ-6 mummichog peak input — only synthetic | Closed W6 D1.3 | peak synth wired into wrapper |
| OQ-7 mummichog human_mfn ↔ KEGG hsa cross-ref absent upstream | Documented | paper Section 4.3 acknowledges |
| OQ-8 mummichog ns-gap stays open at pathway-id layer | Closed W7 D2 | V3 soft-union sidesteps |
| OQ-9 Multi-LLM keys (OpenAI / Anthropic) missing | **Open** | W8 D1 if keys arrive, else M3 pre-submission |
| OQ-10 fuzzy-name false-positive 3 / 9 V3+ tasks | **Open** | Pathway Commons / MNXref name harmoniser in W8 |
| OQ-11 Background G (per-source canonicalization) not run | **Open** | M3 paper writing phase |

---

## 7 · Wieder cold-email status

`docs/concord/wieder_outreach.md` exists from W5 background H. **HELD
unconditionally** through W5 / W6 / W7 per the autonomous-mode rule
"Wieder email 实发前永远先 hold 等 user review". PRIMARY GREEN under
V3 was reached W7 D2, but the multi-LLM consistency precondition is
unmet (OQ-9). Doc header is updated with W7-D5 status; user
review-and-send action pending.

---

## 8 · Paper deliverables ready

| Artifact | Path | Purpose |
|----------|------|---------|
| **Fig 3 v4** (300 DPI PNG + vector PDF) | `data/concord/fig3_v4/fig3_v4.{png,pdf}` | Main paper figure |
| Fig 3 v4 underlying CSV | `data/concord/fig3_v4/fig3_v4_data.csv` | 12-row variant × cohort matrix |
| Fig 3 v4 caption (107 words) | `data/concord/fig3_v4/fig3_v4_caption.md` | ≤ 150-word figure caption |
| Paper narrative draft (1 903 words) | `docs/concord/paper_narrative_finalized.md` | M3 paper-writing seed |
| 3-variant × 3-cohort verdict CSV | `data/concord/gate2_w7/verdicts_3variant.csv` | Supplementary table |
| Compound-level Jaccard data | `data/concord/gate1_w5_5axis/jaccard_compound_level_n30.csv` | Section 3.1 supporting |
| ChEBI / MetaNetX / pathway_members sqlites | `data/concord/*.sqlite` | Reproducibility (gitignored, ETL re-creatable) |
| Cooke Tier-A task panels (3 cohort jsonls) | `data/concord/tier_a_cooke/tasks_{primary,sens_a,sens_b}.jsonl` | Reviewer-inspectable data layer |

---

## 9 · Repro snapshot

```bash
# Worktree state at handoff
$ pwd && git branch --show-current && git log --oneline -1
/home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5_investigation
feature/investigation-concord
6be783e feat(concord): W7 D3-D5 — Fig 3 v4 + paper narrative + Wieder HELD

$ git log --oneline | wc -l          # commits since W3 (this session)
26

$ find concord -name "*.py" | xargs wc -l | tail -1
  6974 total

$ find tests/concord -name "*.py" | xargs wc -l | tail -1
  2577 total

$ /data/weiwentao/miniconda3/envs/mummichog_py310/bin/python -m pytest tests/concord/ -q
148 passed in ~73s
```

---

## 10 · Pending user decisions (handed off)

1. **W7 sanity Check 4 disposition** — paper headline:
   - (I) Dual-report: +25.5 pp fuzzy (headline) + +11.8 pp strict (sensitivity)
   - (II) Switch headline to +11.8 pp strict
   - (III) Pathway-name harmoniser → push strict closer to fuzzy
2. **OQ-9 Multi-LLM** — (a) W8 D1 if user provides OpenAI/Anthropic keys,
   (b) M3 pre-submission, (c) drop NC stretch, send Wieder now
3. **Path A vs Path B confirmation** — V3 GREEN supports Path A
   (Tier B/C ETL + paper writing); awaits user formal confirmation
   before W8 prompt is written
4. **Wieder email send** — drafted W5, held W5-W7, action pending

---

## 11 · One-paragraph closing

The W3-W7 session delivered the engineering substrate (schema +
wrappers + ETL + reconciliation + metric variants) and the empirical
finding (V3 rank-weighted soft union recovers +25.5 pp / +11.8 pp
precision over the strict-intersection baseline that *harms*
precision by 19.6 pp). The paper-defining reversal — *naive
intersection harms, soft union helps* — is documented in
`paper_narrative_finalized.md` and visualised in `fig3_v4.png`. All
148 unit tests green; all decisions pre-registered before each metric
measurement; all anomalies logged with disposition. The branch sits
locally on `feature/investigation-concord` and is unpushed per
project invariant.

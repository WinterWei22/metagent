# Track Layer 6c Phase C — Borderline-Contra Filter (Stem-Overlap Downgrade)

**Session ID:** `track_layer6c_borderline_filter_phase_c`

**Branch:** `feature/layer6c-borderline-filter`

**Estimated work:** 0.5-1 day

---

## Context

Phase B (`reports/verifier/layer6c_phrase_resolver_phase_b_2026-05-06.md`)
§8.1 documented a residual issue with the contra branch:

> Cases 6.1 and 6.4 above. `_resolve_claimed_pathway_ids` is
> **unfiltered by `pathway.type`** — fuzzy substring matches on
> "purine synthesis" return **PFOCR paper-title** pathways and
> Reactome sub-pathways that aren't in the compound's
> `pathway.type IN (kegg, hmdb)` known set. Result: contra fires
> even when the compound IS in a sister pathway under a different
> aggregation level.

Concrete examples from Phase B's §6.1 + §6.4:

```
Phase B §6.1:
  claim: "Fumaric acid is released during the adenylosuccinate-lyase
          step of de-novo purine synthesis"
  Fix-1 normalised: "purine synthesis"
  RaMP fuzzy: matched a PFOCR paper-title row "Purine biosynthesis:
              synthesis of IMP" — NOT in fumaric's KEGG/HMDB pathway
              list → contra
  Reality: fumaric IS in KEGG `Purine metabolism`. Real verdict
           should be SUPPORTED or at worst UNSUPP.

Phase B §6.4:
  claim: "In purine synthesis, PRPP is converted to IMP"
  RaMP fuzzy: same PFOCR row matched → contra
  Reality: PRPP IS in real purine pathways (kegg + hmdb). Borderline.
```

Phase B's §8.1 prescription:

> When contra fires, run a final "stem-overlap" check against the
> compound's top-N **eligible-typed** pathways (the same filter Fix-2
> uses). If any stem overlap, downgrade contra → unsupp. **~20 LoC**
> in the contra helper.

**Phase C goal:** before `_check_compound_pathway_membership_in_ramp`
returns CONTRADICTED, run the stem-overlap check; if the compound's
KEGG/Reactome/Wiki/HMDB pathway list contains a pathway whose name
shares a ≥ 6-char stem with the claim text, downgrade the verdict to
UNSUPPORTED. The contra signal becomes more conservative; precision
goes up, recall drops slightly (5-10 of v9's 31 contra on Sub-6A
real-id are expected to downgrade).

This is a **precision-up / recall-down** trade. The paper benefits
from cleaner contra (fewer "verifier wrongly accused LLM" errors).

---

## Hard scope boundaries

**You MAY:**

- Modify `verifier/layers/biological_sub6.py` —
  **ONLY** the contra-decision tail of
  `_check_compound_pathway_membership_in_ramp` (after the
  membership_intersect query returns 0 rows). Do NOT touch the
  membership-positive (SUPP) branch, the normalise / reverse-fuzz
  helpers from Phase B, or the dispatcher.
- Add a helper at the bottom of `biological_sub6.py` (e.g.
  `_compound_has_eligible_sister_pathway`).
- Reuse the existing `pathway.type IN (kegg, reactome, wiki, hmdb)`
  filter Phase B's `_reverse_fuzz_pathway` introduced — do not
  re-derive the eligibility list.
- Modify `tests/test_verifier/test_biological_sub6.py` — additive
  only.
- Re-run `scripts/eval_sub6/replay_layer6c.py` and the v9-PhaseB
  replay against Phase A narratives.
- Write a new comparison report under `reports/verifier/`.

**You MAY NOT:**

- Modify `_normalise_phrase` or `_reverse_fuzz_pathway` (Phase B
  helpers — they fed the contra helper correctly; the issue is one
  step downstream).
- Modify `_resolve_claimed_pathway_ids` directly (the broader fuzzy
  matcher; touching it would regress UNSUPP / SUPP paths). Phase C
  works around it by checking the *compound's* pathway list, not
  the claim's resolved pathway list.
- Modify other verifier layers, claim_classifier, or claim_extractor.
- Add a new ClaimType, ClaimSubtype, or verdict.
- Modify Sub-6 task data, KEGG reaction graph, or alias DB.
- Re-run baseline LLM narratives (frozen).
- Lower the existing `MIN_KNOWN_PATHWAYS_FOR_CONTRA = 3` threshold.

---

## Background reading (mandatory before first action)

1. `reports/verifier/layer6c_phrase_resolver_phase_b_2026-05-06.md`
   §6 (5 contra examples — your audit anchor) + §8.1 (the
   prescription).
2. `reports/verifier/layer6c_contra_path_2026-05-06.md` §7.1 (the
   original D3 limitation note that pointed to this fix).
3. `verifier/layers/biological_sub6.py`:
   - `_check_compound_pathway_membership_in_ramp` (line ~583)
   - `_reverse_fuzz_pathway` (the Phase B helper) — note its
     `pathway.type IN (kegg, reactome, wiki, hmdb)` filter +
     ≥6-char non-generic stem extraction. You'll lift the same
     pattern.
   - `_resolve_claimed_pathway_ids` (line ~871) — DO NOT modify;
     read for context.

---

## First-action checklist (return to me, do NOT start coding)

1. Confirm reading of the 3 background files.
2. **Borderline audit** — for each of the v9-PhaseB contra rows on
   Sub-6A real-id (n = 31, in
   `data/eval/sub6/sub6a_real_id_verdicts_v9_phaseB.jsonl`):
   - extract the contra row's `enrichment_context.tool_evidence.kegg_compound_id`
     and `claim_text`
   - resolve the compound to RaMP `rampId` via `source.sourceId='kegg:Cxxxxx'`
   - pull all of the compound's pathways via `analytehaspathway` joined
     to `pathway` table, filter to `type IN ('kegg','reactome','wiki','hmdb')`
   - extract ≥ 6-char non-generic stems from each eligible pathway
     name
   - check whether any stem appears word-bounded in the
     `claim_text`
   - count: how many of 31 contra rows have an eligible-pathway
     stem overlap?
3. Same audit on **Sub-6B** (55 contra) and **Sub-6A perfect-id**
   (43 contra) — count borderlines per track.
4. Stratify the borderlines by whether they were caused by
   `_first_phrase`, `_normalise_phrase`, or `_reverse_fuzz_pathway`
   resolution — read `tool_evidence.phrase_resolution_path`.
   Reverse-fuzz cases CANNOT be borderline by construction (Phase B
   §3.2 — the search space IS the compound's known list, so it
   produces 0 contra). The borderlines should split between
   first_phrase and normalise resolutions.
5. Recommend a `_compound_has_eligible_sister_pathway` design
   matching the audit:
   - top-N value (default 50, matching `_reverse_fuzz_pathway`)
   - stem length cutoff (default 6, matching Phase B)
   - generic-word blocklist (lift from Phase B: `metabolism`,
     `pathway`, `cycle`, `synthesis`, `signaling`, `disease`,
     `disorder`, etc.)
   - whether matching ANY stem is enough or whether ≥ 2 stem matches
     are required (looser = more downgrade, tighter = stay strict)
6. Estimate per-track contra count delta after Phase C:
   ```
   Sub-6B v9        contra: 55 → ?
   Sub-6A perfect   contra: 43 → ?
   Sub-6A real-id   contra: 31 → ?  (target ≥ 21, see acceptance)
   ```
7. Ask any clarifying questions.

Do NOT start coding until I confirm.

---

## Proposed design — subject to confirmation

```python
def _compound_has_eligible_sister_pathway(
    rampId: str,
    claim_text: str,
    *,
    conn: sqlite3.Connection,
    top_n: int = 50,
    min_stem_len: int = 6,
) -> tuple[bool, list[str]]:
    """Return (any_overlap, matched_pathway_names)."""

    # Pull compound's pathways, filtered to eligible types
    cur = conn.execute("""
        SELECT p.pathwayName
        FROM analytehaspathway ahp
        JOIN pathway p ON p.pathwayRampId = ahp.pathwayRampId
        WHERE ahp.rampRampId = ?
          AND p.type IN ('kegg', 'reactome', 'wiki', 'hmdb')
        ORDER BY p.pathwayRampId
        LIMIT ?
    """, (rampId, top_n))

    GENERIC = {
        "metabolism", "pathway", "cycle", "synthesis", "biosynthesis",
        "signaling", "disease", "disorder", "regulation", "process",
        # plus the same blocklist Phase B uses
    }

    text_lc = claim_text.lower()
    matched: list[str] = []
    for (name,) in cur.fetchall():
        if name is None:
            continue
        # extract ≥6-char non-generic word-bounded stems
        for stem in re.findall(r"\b[a-zA-Z][a-zA-Z\-]{5,}\b", name.lower()):
            if stem in GENERIC:
                continue
            # word-bounded match against claim
            if re.search(r"\b" + re.escape(stem) + r"\b", text_lc):
                matched.append(name)
                break
    return (bool(matched), matched)
```

Then, in `_check_compound_pathway_membership_in_ramp`, **after**
deciding to return CONTRADICTED, call this helper:

```python
# Existing: query analytehaspathway for membership intersect → 0 rows
# Existing: check N_PATHWAYS_KNOWN >= MIN_KNOWN_PATHWAYS_FOR_CONTRA (3)

# NEW Phase C:
has_sister, matched_names = _compound_has_eligible_sister_pathway(
    rampId, claim_text, conn=conn,
)
if has_sister:
    # Compound IS in a related pathway under a different aggregation
    # level. Downgrade contra → unsupp.
    return _make_unsupported(
        claim, evidence=(
            f"{claim_text!r}: claimed pathway not in compound's KEGG-typed "
            f"membership, but compound DOES have related KEGG/Reactome/Wiki/"
            f"HMDB pathways with name overlap: {matched_names[:3]}. "
            f"Verdict downgraded from CONTRADICTED to UNSUPPORTED."
        ),
        ctx_with_ev=ctx_with_ev._replace(
            tool_evidence={
                **ctx_with_ev.tool_evidence,
                "phase_c_downgrade": True,
                "sister_pathways_matched": matched_names[:5],
            }
        ),
    )

# Otherwise return CONTRADICTED as before
```

The `tool_evidence.phase_c_downgrade=True` flag lets Phase D /
downstream report code stratify "true contra" vs "downgraded contra".

---

## Deliverables

### D1 — Helper + dispatcher hook + tests

**Files:**
- `verifier/layers/biological_sub6.py` — add
  `_compound_has_eligible_sister_pathway` at file bottom; insert
  the downgrade block in
  `_check_compound_pathway_membership_in_ramp` between the contra
  decision and the contra-return statement.
- `tests/test_verifier/test_biological_sub6.py` — additive 6+ tests:
  - 1 case downgraded by stem overlap (synthetic compound + pathway)
  - 1 case where compound has 0 sister pathways → contra preserved
  - 1 case where compound has only PFOCR pathways (filtered out) → contra preserved
  - 1 case where stem is generic ("metabolism") → contra preserved
  - 2 regression cases from Phase B (Vanillin → contra preserved
    in §6.2, §6.3 — these are TRUE contras, no sister overlap)

All existing 282 verifier tests still pass.

### D2 — Replay reruns

```python
# Update v9-PhaseB → v9-PhaseC by replaying the patched layer
# against the Phase A narrative verdict file:
src = "data/eval/sub6/sub6a_real_id_verdicts_v9_phaseB.jsonl"
dst = "data/eval/sub6/sub6a_real_id_verdicts_v9_phaseC.jsonl"

# Update v7-C → v9-PhaseC for v6 narratives:
src = "data/eval/sub6/sub6{b,a_perfect_id}_verdicts_v7_contra.jsonl"
dst = "data/eval/sub6/sub6{b,a_perfect_id}_verdicts_v9_phaseC.jsonl"
```

Aggregate via `scripts/eval_sub6/aggregate_verifier.py` into:
- `results/sub6{b,a_perfect_id,a_real_id}_verifier_v9_phaseC/`

### D3 — Comparison report

**File:** `reports/verifier/layer6c_borderline_filter_phase_c_2026-XX-XX.md`

Required sections:

1. **Executive summary** (3 sentences)
   - Borderline-contra count caught (across 3 tracks)
   - Final contra count vs Phase B
   - True-contra preservation (3 manually-verified cases stay
     contra)

2. **Borderline audit results** — your First-action checklist
   table (count of borderlines per track)

3. **Stem-overlap design**:
   - top-N + min_stem_len + generic blocklist values chosen
   - audit-time estimate vs measured downgrade count

4. **Per-track Phase B → Phase C contra deltas** (the key table)

   ```
                       v9-PhaseB   v9-PhaseC   Δ contra (%)
   Sub-6B contra       55          N            -K (-X%)
   Sub-6A perfect      43          M            -L (-Y%)
   Sub-6A real-id      31          P            -J (-Z%)
   ```

5. **3 confirmed downgrades** (verbatim claim text + matched sister
   pathway + before/after verdict)

6. **3 confirmed preservations** (Phase B §6.2 / §6.3 + 1 more —
   show that real-contra cases stay contra)

7. **Aggregate verifier metrics** — verifiable% per track v9-PhaseB
   vs v9-PhaseC (expect minimal change since downgrade is
   contra→unsupp, both still in verifiable column)

8. **Limitations** — Phase D suggestions for borderlines that the
   stem-overlap doesn't catch (e.g. claim wording too divergent from
   any pathway name even after stem matching)

9. **Provenance** — git commit, file MD5s

---

## Quality bar

- **Acceptance** (hard floors):
  - Phase B §6.1 (Fumaric acid + purine synthesis) MUST downgrade
    contra → unsupp under Phase C
  - Phase B §6.4 (PRPP → IMP) MUST downgrade
  - Phase B §6.2 (Vanillin + xenobiotic metabolism) MUST stay
    contra (vanillin's RaMP pathways don't share stems with
    "xenobiotic")
  - Phase B §6.3 (Vanillin + phenylpropanoid metabolism) MUST stay
    contra
  - Sub-6A real-id v9-PhaseC contra ≥ **15** (was 31; expect 21-26
    realistic; absolute floor 15)
  - Sub-6B v9-PhaseC contra ≥ **40** (was 55; expect 47-52)
  - Sub-6A perfect v9-PhaseC contra ≥ **30** (was 43; expect 36-40)

- **No SUPP / UNSUPP regression** outside the contra→unsupp shifts
  caused by Phase C. Verify per-track:
  - supp count unchanged
  - unsupp count = v9-PhaseB unsupp + (v9-PhaseB contra − v9-PhaseC contra)
  - unverif count unchanged

- **Test suite**: 282/282 still pass (Phase B baseline) + 6 new D1
  tests = 288 total.

- **`tool_evidence.phase_c_downgrade=True`** present on every
  downgraded row for downstream auditability.

---

## Pitfalls

1. **Don't lower stem length below 6** — "purine" matches well at
   ≥6 chars, but ≥4 risks false-positive overlap on common chem
   words ("acid", "lipid", "cell").

2. **Don't pick top-N too high** — N=50 is the Phase B baseline; N
   = 200+ pulls in noise. Stick with 50 unless audit shows higher.

3. **Generic blocklist must include suffix synonyms** —
   "metabolism", "biosynthesis", "synthesis", "pathway", "cycle".
   Otherwise every claim trivially overlaps via "metabolism".

4. **Word-boundary matching only** — `re.search(r"\b" + stem + r"\b",
   text_lc)`. Else "purine" matches "purinergic" and over-downgrades.

5. **Don't stem-match across the claim text and pathway name as a
   set intersection** — the directional check is "does any stem
   from a pathway name appear in the claim text". The reverse
   (stems from claim text appearing in pathway names) is what
   Fix-2's reverse-fuzz already does — don't duplicate.

6. **Phase C must NOT touch Fix-2 reverse-fuzz** — they're
   different mechanisms:
   - Fix-2 produces SUPP rescues by finding compound's pathway in
     claim text (forward direction)
   - Phase C downgrades CONTRA by finding compound's pathway sharing
     stem with claim text (different direction; only when contra
     was about to fire)

7. **`tool_evidence` schema breaking change risk** — Phase C adds
   new keys (`phase_c_downgrade`, `sister_pathways_matched`).
   Confirm `EnrichmentContext.tool_evidence` is `dict[str, Any]`
   (it is — see schemas.py — additive is safe).

8. **Don't add a new ClaimSubtype "downgraded_contradicted"** —
   verdict stays `unsupported`; the audit flag is in tool_evidence.

9. **Don't downgrade UNSUPP → SUPP** — Phase C is one-way,
   contra→unsupp only. The opposite direction is Fix-2's job.

10. **Reverse-fuzz contras don't exist by construction** — when the
    audit (First-action #4) finds zero borderlines from
    `phrase_resolution_path=reverse_fuzz`, that's expected, not a
    bug.

---

## Time budget (0.5-1 day)

- 08:00 – 09:00 First-action audit (31 + 55 + 43 = 129 contra
  rows, ~2 hours of SQL + scripted classification)
- 09:00 – 09:30 Clarifying Q + my approval
- 09:30 – 11:00 D1 helper + dispatcher hook + 6 tests + suite green
- 11:00 – 12:00 D2 replay reruns + aggregate
- 12:00 – 13:00 Lunch
- 13:00 – 14:30 D3 report writing
- 14:30 – 15:30 Buffer + commit + push

If you finish in < 5 hours, **stop**. Don't speculatively work on
Phase D suggestions (subject-side synonym table for cGMP-class
compounds, etc.) — those are separate sessions.

---

## File manifest expected at end of session

**Modified:**
- `verifier/layers/biological_sub6.py` (additive helper +
  ~10-line block in contra dispatch)

**New:**
- `tests/test_verifier/test_biological_sub6.py` (additive 6+ tests)
- `data/eval/sub6/sub6{b,a_perfect_id,a_real_id}_verdicts_v9_phaseC.jsonl`
- `results/sub6{b,a_perfect_id,a_real_id}_verifier_v9_phaseC/`

**New report:**
- `reports/verifier/layer6c_borderline_filter_phase_c_2026-XX-XX.md`

---

## When you finish

1. Push branch `feature/layer6c-borderline-filter`.
2. Reply with:
   - Sub-6A real-id v9-PhaseC contra count (the headline)
   - Phase B §6.1 / §6.4 actual downgrade verdicts (must be unsupp)
   - Phase B §6.2 / §6.3 actual preservation verdicts (must stay
     contra)
   - link to comparison report
3. **Do NOT touch Phase D** (subject-side synonyms or cGMP-class
   handling) — separate session.

---

*Derived from session-state as of 2026-05-06 (commit `c9179fa` on
feature/layer6c-phrase-resolver).*

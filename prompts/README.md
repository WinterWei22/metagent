# How to use these prompts

Seven prompt files + a shared preamble. Each is designed to be pasted whole into a Claude Code session as the opening instruction.

## Files

```
prompts/
├── _preamble.md                        ← shared rules. Every track includes this.
├── track_A1_spectrum_preprocess.md     ← no external model needed
├── track_A2_candidate_prefilter.md     ← needs PubChem Lite setup decision (early maintainer call)
├── track_B_library_search.md           ← needs in-house retrieval model (ask maintainer)
├── track_C_molecule_generate.md        ← needs in-house generation model (ask maintainer)
├── track_D_metabolite_and_pathway.md   ← needs HMDB + RaMP-DB setup (can start immediately with mocks)
├── track_E_predict_spectrum.md         ← needs CFM-ID Docker (can start immediately with mocks)
└── track_F_literature_search.md        ← smallest, no local data setup
```

## How to dispatch

For each track:

1. Open a **fresh** Claude Code session (do not reuse a session across tracks — context pollution).
2. **First message:** paste the contents of `_preamble.md` followed by the track-specific prompt file, separated by a blank line. That is the ONLY opening instruction. No "and by the way..." afterthoughts — if you have more context, put it into the prompt file itself before dispatching.
3. Wait for the session's **understanding checkpoint**: every preamble-following session should first read the docs and state back "my understanding is... my scope is... my plan is...". If it skips this and jumps into coding, stop it and redirect.
4. For tracks B, C, A2: the first substantive question will be "where is the in-house model / what PubChem subset should I use?". Have answers ready before you dispatch. If you don't know yet, dispatch the other tracks first.

## Suggested dispatch order

**Day 1 (you):** finalize `schemas/` and fixtures. Don't dispatch anything yet.

**Day 2 — three easiest tracks:** dispatch **F**, **A1**, **E** (with mock CFM-ID). All three are independent and have no data-setup blockers.

**Day 3 — after you confirm model locations:** dispatch **B** and **C**.

**Day 4 — after you confirm DB setup paths:** dispatch **A2** and **D**.

## Why this order

1. F, A1, E mock-first all build working code without waiting on external data or models. You get momentum and debug the orchestrator/schema contracts with real code early.
2. B and C depend on your in-house model info — don't dispatch until you've decided how to hand those off.
3. A2 and D are the data-heavy tracks (PubChem Lite, HMDB, RaMP-DB). They take calendar time regardless of session speed because of download volumes.

## Checking in on a running session

Every day, ask each session:
- "Summarise what you've produced and what's still outstanding."
- "Did you modify any file outside your track directory? `git status` please."
- "Are your tests passing? Paste the output."

If a session drifts into shared files (`schemas/`, `common/`, `docs/`, another track's directory), **stop it immediately** and revert the change. This is the single most common failure mode of parallel Claude Code sessions.

## Merging track outputs

After each track's PR comes in:
1. You (not the session) review.
2. Run the full test suite on the integration branch.
3. Merge small, focused PRs. Reject PRs that touched files outside the track's scope — ask for a revert.

## Backstop: if a session writes the wrong thing

Mistakes will happen. When you spot one:
- "Revert that change. Here is what the contract says: [paste]. Please implement to match, not to your interpretation."
- If a session repeatedly ignores the contract, close it and re-dispatch from scratch with the same prompt. Starting over is cheaper than debugging a stubborn context.

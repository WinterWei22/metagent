# Verifier T1/T2 Wiring Delivery — 2026-04-27

## What changed

The verifier now routes peak-level mechanistic claims to a new
`verifier/layers/peak_mechanistic.py` layer. The classifier detects claims
with an extractable `m/z` plus fragment / loss / cleavage terminology, stores
`peak_mz` and `neutral_loss` on the classified claim, and `agent.py` dispatches
`ClaimType.PEAK_MECHANISTIC` to the new layer.

Type 2 factual verification now has a ClassyFire branch for chemical taxonomy
claims such as "caffeine is a purine" or "glucose is an amino acid". Database
ID claims still use the existing `fetch_metabolite_info` source-first /
round-trip path. ClassyFire is only selected for name-only taxonomy claims that
match a small chemical-class vocabulary.

## Type 5 flow

1. The classifier recognizes a peak mechanistic claim and extracts `peak_mz`.
2. `verify_peak_mechanistic()` checks whether the peak exists in the
   experimental spectrum within 5 ppm.
3. If the peak exists and the top candidate has SMILES, the layer calls SIRIUS.
4. No SIRIUS fragment at that m/z gives `UNSUPPORTED`.
5. A SIRIUS fragment with matching neutral-loss formula or alias gives
   `SUPPORTED`; a neutral-loss mismatch gives `CONTRADICTED` with correction.

`SiriusNotInstalledError` and `SiriusNoFormulaError` are handled as
`UNVERIFIABLE_V0`, not pipeline crashes.

## Type 2 ClassyFire flow

ClassyFire triggers only when a factual claim has no database ID and looks like
a chemical taxonomy claim. The verifier gets SMILES from the matching
`source_report` candidate, calls ClassyFire, and uses `matches_claim()` against
the claimed class. `ClassyfireNotFoundError` maps to `UNVERIFIABLE_V0`.

## Test counts

Before this wiring, `tests/test_verifier/` had 139 passing tests in the prior
baseline run. After this wiring:

```text
conda run -n metagent-llm python -m pytest tests/test_verifier/ -q
150 passed in 0.42s
```

Focused related test run:

```text
conda run -n metagent-llm python -m pytest \
  tests/test_verifier/test_layer_peak_mechanistic.py \
  tests/test_verifier/test_layer_factual.py \
  tests/test_verifier/test_claim_classifier.py \
  tests/test_verifier/test_agent_cascade.py -q
52 passed in 0.28s
```

Whole-repo `pytest -q` did not reach test execution because collection is
blocked by existing environment issues: missing `matchms`, `requests_mock`,
`dotenv`, and RDKit compiled against an incompatible NumPy ABI.

## Known limitations

Sparse 5-7 peak fixture spectra will usually make SIRIUS return
`UNVERIFIABLE_V0` because there is not enough fragmentation evidence to build a
meaningful tree. This is expected for the current glucose / caffeine /
L-carnitine fixtures.

ClassyFire can only verify compounds with a source-report SMILES and a
ClassyFire classification. Novel or rare compounds that are not found remain
`UNVERIFIABLE_V0`.

## Example: caffeine O1 output

After this wiring, a claim like "caffeine is a purine" no longer falls through
as an unverifiable name-only factual claim. The factual layer finds caffeine's
SMILES in the source report, calls ClassyFire, and supports the claim when the
classification hierarchy contains "Purines and purine derivatives" or a more
specific descendant such as "Xanthines".

## Real-scenario follow-up

On 2026-04-27, a real caffeine run was executed end-to-end:

```text
conda run -n diffms --no-capture-output python scripts/run_full_pipeline.py \
  --fixture caffeine_pos --output json --top-k 6 --predict-top-n 2 \
  --literature-top-n 1

conda run -n metagent-llm --no-capture-output python -m orchestrator identify \
  --report-json /tmp/metagent_real_caffeine_report_20260427.clean.json \
  --output json --trace-id real_caffeine_20260427_t1t2
```

The newly generated report had 5 spectrum peaks, 6 candidates, and sparse
quality. Verifier over the real orchestrator output completed with no warnings:

```text
overall contradicted
claims_v1 47
claims_v2 34
llm_calls 7
types {'grounded_claim': 19, 'consistency_claim': 18,
       'factual_roundtrip_claim': 3, 'biological_claim': 7}
```

The first live pass exposed an over-broad Type 5 classifier rule: ordinary
precursor-adduct text like `[M+H]+` was initially routed as a peak-mechanistic
claim. The bracket pattern has been narrowed to require an additional
loss/modification (`[M+H-...]`, `[M+H+...]`), and a regression test now keeps
precursor neutral-mass claims in `GROUNDED`.

A targeted real-tool verifier run on the O1 caffeine report confirmed both new
backends:

```text
factual_roundtrip_claim supported
Caffeine is a purine
ClassyFire confirms: Xanthines (source: cache)

peak_mechanistic_claim supported
The peak at m/z 138.0662 is a fragment ion of caffeine
SIRIUS confirms fragment at m/z 138.0662
(formula C6H7N3O, neutral loss C2H3NO)
```

Final verifier suite after the classifier regression fix:

```text
conda run -n metagent-llm python -m pytest tests/test_verifier/ -q
151 passed in 0.42s
```

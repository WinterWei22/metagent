# Track UI1 — Demo UI v0 delivery / handoff

- **Date:** 2026-04-24
- **Base branch:** `integration-day1` (atop `c54d57b feat(ui): Track UI1 Part 1 — 4-panel layout stub`)
- **Status:** content wired, running on `0.0.0.0:7861`, uncommitted working tree
- **Primary audience:** the Verifier-visualisation session (Track V → UI integration)
- **Secondary audience:** anyone maintaining the demo between now and then

This doc is designed to be **self-contained** — a future developer should be
able to work from it alone, without reading the chat history.

---

## 1. What this UI is (and isn't)

A **Gradio-based local viewer** over the outputs of Tracks A–E (deterministic
pipeline), Track O1 (naive orchestrator LLM wrapper), and — on demand —
Track F (literature).

**It is a viewer.** The UI never issues its own LLM calls. Live-mode
runs (custom spectrum → pipeline + LLM) call the **existing** entry
points (`scripts.run_full_pipeline.identify` via subprocess, then
`orchestrator.naive.identify` in-process). The UI layer adds two things
of its own: (1) dependency-injected wrappers that capture pipeline
byproducts for visualisation (predicted spectra per candidate) and (2)
rendering logic.

**What's demo-facing:**
- Four-panel layout (Input · Pipeline · LLM · Verifier)
- Progressive 3-stage reveal (Panel 1 → 2 → 3 fills in sequence)
- Cached-first browsing of pre-run fixtures, Live mode opt-in
- **MS/MS mirror-plot overlay of CFM-ID predictions vs experimental**
- **Dedicated de-novo (Track C) candidate gallery**
- LLM narrative with `Rendered / Raw-with-<think> / Prompt sent to LLM` view toggle
- On-demand Track F literature query (graceful SSL failure)
- Panel 4 reserved for Track V verifier — **currently a PREVIEW placeholder**

**What it deliberately is not:**
- A production tool (no auth, no persistence beyond local cache, localhost-only by default)
- A generator (no "rewrite this output" buttons; no UI-side LLM calls)
- A shell for verifying claims — that's Track V's job; UI is the surface

---

## 2. Runtime environment

| Component | Where | Version / path |
|---|---|---|
| Python / UI | `metagent-llm` conda env | Python 3.11, gradio 5.50, rdkit-pypi 2022.9.5, matplotlib 3.10.8, socksio 1.0.0 |
| Pipeline subprocess | `diffms` conda env (via `conda run -n diffms`) | rdkit, matchms, torch, pydantic, schemas + scripts |
| MS-BART subprocess | `ms-bart` conda env (nested; invoked by Track C's MSBartGenerator) | torch 2.6, transformers 4.57 |
| CFM-ID shim | `http://127.0.0.1:8088/predict` (FastAPI wrapper over cfm-predict 4.4.7) | already running on this host |
| MiniMax LLM | `https://api.minimaxi.com/v1` via `common.llm_client` | `MiniMax-M2.7` |

Two-env split mirrors the Track O1 Part 4 flow — `metagent-llm` has
`openai + tiktoken` but not rdkit/matchms/torch, so pipeline work is
subprocessed into `diffms`.

Required env vars (for `--enable-live`):

```
MINIMAX_API_KEY           MINIMAX bearer
METAGENT_HMDB_PATH        /data/weiwentao/llm_agent_metabolomics/hmdb.sqlite
METAGENT_RAMP_PATH        /data/weiwentao/llm_agent_metabolomics/ramp.sqlite
METAGENT_CFM_URL          http://127.0.0.1:8088
METAGENT_GNPS_PATH        /data/weiwentao/llm_agent_metabolomics/gnps/ALL_GNPS_cleaned_enriched.csv
METAGENT_GNPS_SPECTRA_PATH /data/weiwentao/llm_agent_metabolomics/gnps/ALL_GNPS_cleaned.mgf
METAGENT_PUBCHEM_LITE_PATH /data/weiwentao/llm_agent_metabolomics/pubchem_lite.sqlite
METAGENT_MSBART_CKPT      /home/weiwentao/workspace/mol_gen/MS-BART/data/MassSpecGym/MS-BART-MassSpecGym/csyanghan/MS-BART-MassSpecGym
```

Tuning knobs:

- `METAGENT_UI_STAGE_DELAY` — seconds between progressive reveal stages (default 0.45)
- `METAGENT_LIVE_PIPELINE_TIMEOUT` — pipeline subprocess timeout (default 900)
- `GRADIO_TEMP_DIR` — forced to `/tmp/gradio_$uid` in `ui/app.py` to avoid clash with other users' Gradio on the host
- `--host 0.0.0.0` / `--port 7861` — `7860` is occupied by another user's Gradio on this machine

Launch:

```bash
conda run -n metagent-llm python -m ui.app --host 0.0.0.0 --port 7861 --enable-live
```

---

## 3. Layout and flow

### 3.1 Visual tree

```
┌─────────────────────────────────────────────────────────────────────────┐
│ HEADER — MetAgent — Metabolite Identification Demo                      │
│ Input: an MS/MS spectrum. Output: ranked candidates + LLM + (Verifier)  │
│ [Live mode: available / disabled (missing env vars)]                    │
├─────────────────────────────────────────────────────────────────────────┤
│ TABS (input selector)                                                   │
│   [Example spectrum (cached)]  ← dropdown of 4 fixtures                 │
│   [Custom spectrum (Live)]     ← JSON textbox + "Run pipeline + LLM"    │
├─────────────────────────────────────────────────────────────────────────┤
│ Trace ID (readonly, shows current run)                                  │
├─────────────────────────────────────────────────────────────────────────┤
│ ┌──────────────────────────┬──────────────────────────────────────────┐ │
│ │ PANEL 1 (Input — blue)   │ PANEL 2 (Pipeline — grey)                │ │
│ │ 📥 MS/MS spectrum plot   │ 🧪 Pipeline output (deterministic)       │ │
│ │ precursor/adduct/quality │   - top-5 gallery (merged B+C)           │ │
│ │                          │   - 🧬 de-novo gallery (source=generated)│ │
│ │                          │   - 🔬 overlay (experimental vs CFM-ID)  │ │
│ │                          │   - 7-col table (rank/name/source/…)     │ │
│ │                          │   - Top-1 details accordion              │ │
│ │                          │   - Pipeline execution summary (warnings)│ │
│ │                          │   - Related literature (on-demand)       │ │
│ ├──────────────────────────┼──────────────────────────────────────────┤ │
│ │ PANEL 3 (LLM — grey)     │ PANEL 4 (Verifier — grey)  [PREVIEW]     │ │
│ │ 💬 naive orchestrator    │ 🛡 Track V (v0.2)                        │ │
│ │ Radio: Rendered / Raw    │ 3-row mock verdict table                 │ │
│ │        / Prompt sent     │ Slot reserved for live integration       │ │
│ │ Footer: trace_id / model │                                          │ │
│ │         elapsed / words  │                                          │ │
│ └──────────────────────────┴──────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Data flow — Cached mode (default)

Triggered by the fixture dropdown change event:

```
fixture_dd.change → _load_cached_progressive (generator, yields 4 times)
    ├── Stage 0 · clear all panels, "Loading…"
    ├── Stage 1 · experimental.render(report) → Panel 1
    ├── Stage 2 · pipeline.render(report, predicted_spectra) → Panel 2 (all 6+ subsections)
    └── Stage 3 · llm.render_body/footer → Panel 3
```

Each yield emits the full 18-element tuple
`(*panel_outputs, trace_id_tb, status_md)`. See §5.3 for the shape.

### 3.3 Data flow — Live mode

Triggered by the "Run pipeline + LLM" button in the Custom tab:

```
run_btn.click → _run_live_progressive (generator)
    ├── Parse custom spectrum JSON → Panel 1 rendered immediately from payload
    ├── SUBPROCESS: conda run -n diffms python -m ui.data.live_pipeline_runner
    │     stdin : custom spectrum JSON
    │     env   : METAGENT_UI_LIVE_TRACE_ID=<trace_id> + all pipeline env
    │     inside: identify(
    │                 req,
    │                 library_search_fn = library_wrap,   ← captures B's hits
    │                 generate_fn       = generate_wrap,  ← injects CandidateFusionFingerprinter
    │                 predict_spectrum_fn = predict_wrap, ← captures CFM-ID predictions
    │             )
    │     stdout: IdentificationReport JSON
    │     side-effect: /data/.../pipeline_runs/<trace_id>.predicted_spectra.json
    ├── Persist report → /data/.../pipeline_runs/<trace_id>.json
    ├── Read back the side-car
    ├── orchestrator.naive.identify(report, trace_id=…)  (in-process)
    └── Read back the matching row from logs/llm_calls.jsonl → Panel 3
```

The three UI-side injections do **not** modify any `tools/` or
`scripts/` source. They are pure wrappers over the defaults.

---

## 4. File map (UI layer only)

```
ui/
├── __init__.py
├── app.py                    ← entry · gr.Blocks assembly · generators · wiring
├── README.md                 ← launch instructions
├── requirements.txt          ← pinned versions (gradio/rdkit/matplotlib/socksio)
├── assets/
│   └── style.css             ← panel border stripes (Input blue, Output grey), monospace JSON
├── panels/
│   ├── __init__.py
│   ├── experimental.py       ← Panel 1 (spectrum stem plot + metadata)
│   ├── pipeline.py           ← Panel 2 (gallery · de-novo gallery · overlay · table · detail · warnings · literature)
│   ├── llm.py                ← Panel 3 (LLM narrative · 3-view radio · footer)
│   └── verifier.py           ← Panel 4 (PREVIEW stub) ← Verifier integration slot
├── data/
│   ├── __init__.py
│   ├── loaders.py            ← CachedRun dataclass + fixture discovery + side-car loader
│   ├── runners.py            ← Live-mode coordination · literature graceful wrapper
│   └── live_pipeline_runner.py ← subprocess body run inside `diffms`
└── rendering/
    ├── __init__.py
    ├── spectrum_plot.py      ← matplotlib stem plot (Panel 1)
    ├── molecule_img.py       ← RDKit SMILES → PIL 150×150 with fallback
    ├── predict_overlay.py    ← experimental vs CFM-ID mirror plot (Panel 2)
    ├── candidate_charts.py   ← evidence-by-source charts — module retained but NOT mounted (removed per review)
    └── markdown_enhance.py   ← intentionally minimal (LLM output renders verbatim)

tests/test_ui/
├── __init__.py
├── test_app_imports.py       ← build_blocks / panel-tuple shape smoke
├── test_loaders.py           ← discovery priority / matchms-prefix strip
├── test_runners.py           ← parse_custom_spectrum_json + trace_id shape
├── test_spectrum_plot.py     ← stem plot + molecule-image fallback
└── test_charts.py            ← candidate_charts unit tests (module still exists)

reports/
└── ui_v0_delivery_2026-04-24.md  ← this file
```

**Scope containment audit** (what the session did NOT touch):

- `orchestrator/` — untouched by UI session. `orchestrator/formatter.py`
  was modified by a concurrent session to integrate Track F literature
  into the LLM user message (new `cr.literature_records` + `_literature_block`);
  UI does not depend on or interfere with that.
- `verifier/`, `tools/`, `schemas/` — untouched.
- `common/`, `docs/` — untouched.
- `scripts/` — untouched (Live pipeline calls `scripts.run_full_pipeline.identify` via dependency injection, not by editing).

---

## 5. Track → UI mapping

How every upstream track's output surfaces in the UI:

| Track | Tool | Where in UI | Rendering |
|---|---|---|---|
| A1 | `spectrum_preprocess` | Panel 1 plot + metadata | `experimental.render` · matplotlib stem + precursor/adduct/quality labels |
| A2 | `candidate_prefilter` | Panel 2 execution summary | Reported via `n_prefilter_candidates` + pool breakdown |
| **B** | `library_search` | Panel 2 top-5 gallery, table `source=library`, de-novo injection input | `pipeline._denovo_gallery` / gallery label `(library)` |
| **C** | `molecule_generate` (MS-BART) | Panel 2 🧬 de-novo gallery, table `source=generated` | Own accordion, always visible; caption names the mechanism (Fusion→MS-BART); gallery label `(generated)` |
| D1 | `fetch_metabolite_info` | Panel 2 top-1 details | HMDB cross-refs · `exact_mass` (raw, with D-1 zwitterion caveat) · chemical class |
| D2 | `pathway_context` | Panel 2 top-1 details | Pathway list with `source` (KEGG/SMPDB/Reactome) + `hit_count` |
| **E** | `predict_spectrum` (CFM-ID) | Panel 2 🔬 overlay + table cosine column | Mirror plot + dropdown picker + cosine caption; overlay consumes the Live runner's side-car (see §6) |
| **F** | `literature_search` | Panel 2 literature accordion (on-demand button) | Top-5 EuroPMC records with PMID links; graceful error on SSL failure |
| O1 | `orchestrator.naive` | Panel 3 | `response_cleaned` rendered as Markdown; toggle to `response_raw` or `messages`; footer with trace_id/model/elapsed/tokens |
| **V** | Verifier cascade (landed) | Panel 4 (currently static PREVIEW) | — (see §7 for integration plan) |

The **bold** rows are the ones where UI did substantive visualisation
work beyond verbatim display. B/C show up side-by-side in a merged +
de-novo-only dual-gallery so that C's contribution is visible even when
it ranks below top-5. E uses a mirror plot (experimental above, CFM
prediction mirrored below, classic MS/MS comparison convention).

---

## 6. The predicted-spectra side-car (important for E integration)

### 6.1 Why

`IdentificationReport` schema persists only
`predicted_spectrum_cosine: float | None` and
`predicted_model_version: str | None` per candidate. The **full
predicted spectrum** (mz/intensity arrays) is produced by CFM-ID and
consumed by `modified_cosine_score` internally, but never flows into
`CandidateReport`. UI can't re-plot a mirror overlay from the cached
report alone.

### 6.2 How UI captures it

`ui/data/live_pipeline_runner.py::_build_injected_callables()` wraps
`tools.spectrum_predict.predict_spectrum` with `predict_wrap`:

```python
def predict_wrap(req, *args, **kwargs):
    resp = _real_predict(req, *args, **kwargs)
    predicted_store[req.smiles] = resp.predicted.model_dump()
    return resp
```

After the pipeline returns, the runner dumps `predicted_store` to:

```
/data/weiwentao/llm_agent_metabolomics/pipeline_runs/<trace_id>.predicted_spectra.json
```

Shape:

```json
{
  "OCC1OC(O)C(O)C(O)C1O": {
    "mz": [61.0, 73.0, 85.0, ...],
    "intensity": [0.12, 0.34, ...],
    "precursor_mz": 181.0707,
    "adduct": "[M+H]+",
    "ionization_mode": "positive",
    "collision_energy": null
  },
  "CC(O)C(O)...": { ... },
  ...
}
```

Keyed by candidate SMILES (verbatim from the `PredictSpectrumRequest`).

### 6.3 How UI reads it

`ui/data/loaders.py::load_cached_run` fills `CachedRun.predicted_spectra`
if the side-car exists next to the run JSON. `ui/panels/pipeline.py::render`
accepts `predicted_spectra: dict | None` and builds the overlay
dropdown/plot/caption via `_build_predict_overlay`.

### 6.4 Coverage today

| Cached fixture | Report present | Side-car present | Overlay works |
|---|---|---|---|
| `glucose_pos` | ✓ | ✗ (O1 Part 4 leftover, no side-car) | Graceful "not persisted" caption |
| `caffeine_pos` | ✓ | ✗ | Same |
| `lcarnitine_pos` | ✓ | ✗ | Same |
| `glucose_pos_fusion` | ✓ | **✓ (5 entries)** | **5 overlays** (2 library + 3 generated) |

To backfill side-cars for the three O1 originals, re-run them with
`METAGENT_UI_LIVE_TRACE_ID=o1-part4-<fixture>` set for the live runner.
They were not re-run in this session because (a) they are from the Track
O1 delivery and overwriting them would drift the baseline and (b) one
bonus fixture is enough to show the overlay mechanism.

---

## 7. Verifier integration (the Track V → UI plan)

Track V's cascade is already landed (commits `5f843f8 / b6192a7 /
1997bfc / 90d31e9 / 1ef750d`). The missing piece is the UI display.

### 7.1 What Track V produces

`verifier.verify(report_llm_output, ...)` returns a
**`VerifiedIdentification`** (`verifier/schemas.py:205`):

```
VerifiedIdentification
├── trace_id: str            ← joins back to IdentificationReport + logs/llm_calls.jsonl
├── source_llm_output: str   ← the original orchestrator narrative
├── rewritten_output: str    ← Stage-4-rewritten narrative (same as source if nothing actionable)
├── claims_v1: list[VerifiedClaim]
├── claims_v2: list[VerifiedClaim]  (== v1 if no rewrite happened)
├── verified_claims: list[VerifiedClaim]  (flat; includes per-layer verdicts)
├── verification_warnings: list[str]
├── llm_call_count: int
└── generated_at: datetime

VerifiedClaim
├── claim_text: str
├── claim_type: ClaimType          (GROUNDED / FACTUAL / BIOLOGICAL / CONSISTENCY / LITERATURE)
├── verdict: ClaimVerdict          (SUPPORTED / CONTRADICTED / UNSUPPORTED / NOT_APPLICABLE)
├── evidence: str
├── source_field: str | None       (which CandidateReport field grounds this)
└── correction: str | None         (rewriter-suggested correction)
```

Track V currently **does not persist** to disk — `verify()` returns
in-memory. The delivery writeup
(`reports/verifier_v0_delivery_2026-04-24.md`) mentions
`/tmp/verifier_e2e_lastrun.jsonl` as integration test output but no
production convention yet.

### 7.2 Proposed persistence convention (to be agreed with V team)

**Mirror the pipeline side-car pattern:**

```
/data/weiwentao/llm_agent_metabolomics/verifier_runs/<trace_id>.verifier.json
```

Containing the `VerifiedIdentification.model_dump_json()` blob, one
file per run. Optional aggregate file
`/data/.../verifier_runs/index.jsonl` appending one line per run for
cross-run analytics.

UI loader would look for that path next to the existing pipeline_runs
side-cars.

### 7.3 Integration — exact changes the V-visualisation session makes

Three and only three UI files need changes. §7.4 describes the
zero-change guarantee for the others.

#### 7.3.1 `ui/data/loaders.py`

Add to the same module (adjacent to `_read_log_rows`):

```python
_VERIFIER_RUNS = Path("/data/weiwentao/llm_agent_metabolomics/verifier_runs")

def load_verifier_verdict(trace_id: str) -> dict[str, Any] | None:
    if not trace_id:
        return None
    path = _VERIFIER_RUNS / f"{trace_id}.verifier.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
```

Extend `CachedRun` dataclass with a `verifier_row` field (default
None), and fill it inside `load_cached_run` after reading the report +
log row:

```python
verifier_row = load_verifier_verdict(trace_id) if trace_id else None

return CachedRun(
    fixture=fixture,
    trace_id=trace_id or …,
    report_path=report_path,
    report=report,
    llm_row=llm_row,
    predicted_spectra=predicted_spectra,
    verifier_row=verifier_row,   # ← new
)
```

#### 7.3.2 `ui/panels/verifier.py` — swap PREVIEW for live data

Replace the current stub with:

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import gradio as gr


@dataclass
class VerifierOutputs:
    summary: gr.Markdown
    verdict_table: gr.Dataframe
    rewritten_accordion: gr.Accordion
    rewritten_body: gr.Markdown


_VERDICT_COLOUR = {
    "supported": "#059669",
    "contradicted": "#b91c1c",
    "unsupported": "#d97706",
    "not_applicable": "#6b7280",
}


def build_panel() -> tuple[gr.Column, VerifierOutputs]:
    with gr.Column(elem_classes=["metagent-panel", "metagent-output-panel"]) as col:
        gr.Markdown("### 🛡 Verifier (Track V)")
        summary = gr.Markdown()
        verdict_table = gr.Dataframe(
            headers=["Claim", "Type", "Verdict", "Evidence", "Correction"],
            datatype=["str", "str", "str", "str", "str"],
            interactive=False, wrap=True,
        )
        with gr.Accordion("Rewritten narrative (Stage 4)", open=False) as rewritten_accordion:
            rewritten_body = gr.Markdown()
    return col, VerifierOutputs(
        summary=summary,
        verdict_table=verdict_table,
        rewritten_accordion=rewritten_accordion,
        rewritten_body=rewritten_body,
    )


def render(verifier_row: dict | None) -> tuple[str, list[list[str]], str]:
    """Return (summary_md, table_rows, rewritten_md). All empty if no row."""
    if not verifier_row:
        return (
            "_(no verifier verdict for this run — Track V not yet run, or side-car missing)_",
            [],
            "",
        )
    claims = verifier_row.get("verified_claims") or verifier_row.get("claims_v1") or []
    counts = {"supported": 0, "contradicted": 0, "unsupported": 0, "not_applicable": 0}
    rows: list[list[str]] = []
    for c in claims:
        v = (c.get("verdict") or "").lower()
        counts[v] = counts.get(v, 0) + 1
        colour = _VERDICT_COLOUR.get(v, "#6b7280")
        verdict_badge = f"<span style='color:{colour};font-weight:600'>{v}</span>"
        rows.append([
            c.get("claim_text") or "",
            c.get("claim_type") or "",
            verdict_badge,
            (c.get("evidence") or "")[:300],
            (c.get("correction") or "") if c.get("correction") else "—",
        ])
    summary = (
        f"**{len(claims)} claim(s):** "
        f"<span style='color:#059669'>supported {counts['supported']}</span>  ·  "
        f"<span style='color:#b91c1c'>contradicted {counts['contradicted']}</span>  ·  "
        f"<span style='color:#d97706'>unsupported {counts['unsupported']}</span>  "
        f"· n/a {counts['not_applicable']}  "
        f"· LLM calls used: {verifier_row.get('llm_call_count', '?')}"
    )
    rewritten = verifier_row.get("rewritten_output") or ""
    source = verifier_row.get("source_llm_output") or ""
    if rewritten and rewritten != source:
        body = rewritten
    else:
        body = "_(no rewrite — all claims were supported or no actionable verdicts)_"
    return summary, rows, body
```

Remove the static `_PREVIEW_BADGE` / `_PREVIEW_ROWS` constants and all
references to them. The panel slot **keeps its position** (row 2,
right) in the layout.

#### 7.3.3 `ui/app.py` — fan verifier_row through the generators

Touch points (grep for these strings):

- `_render_for_panels` — unpack 3 more outputs from `verifier.render(run.verifier_row)` and append them to the return tuple
- `_blank_panels_tuple` — append `("", [], "")` at the end (summary_md, rows, rewritten_md)
- `_load_cached_progressive` — at each yield site, pass the 3 new values (or empties during stages 1-2, real values in stage 3 or new stage 4)
- `_run_live_progressive` — the Live mode doesn't currently invoke Track V; decide whether to (a) skip verifier in Live mode or (b) call `verifier.verify(...)` as Stage D before the final yield. Option (b) costs ≤4 LLM calls — see §7.5.
- `panel_outputs` list — append `ver_out.summary, ver_out.verdict_table, ver_out.rewritten_body` (note: the `gr.Accordion` doesn't need to be in the output list unless you want to programmatically open/close it)

Total: **3 extra outputs** per generator yield, total outputs per yield
grows from 18 → 21.

### 7.4 Zero-change guarantee

The V-visualisation session does **not** need to touch:

- `ui/panels/{experimental, pipeline, llm}.py`
- `ui/data/runners.py` (unless adding Live-mode verifier call — §7.5)
- `ui/data/live_pipeline_runner.py`
- `ui/rendering/*` (except optionally adding a new file for verdict-colour utilities)
- Any existing tests
- Any `orchestrator/` / `tools/` / `schemas/` / `common/` file

### 7.5 Live-mode Verifier — optional but recommended

If the V session chooses to also run verifier live (not just read the
side-car):

```
_run_live_progressive adds a Stage D after Stage C (LLM):
    ├── Stage A · Input         (already present)
    ├── Stage B · Pipeline      (already present — ~5 min)
    ├── Stage C · LLM           (already present — ~30 s)
    └── Stage D · Verifier      (new)
          from verifier import verify
          v = verify(trace_id, report_llm_output, report, llm_messages, …)
          persist v.model_dump_json() to /data/.../verifier_runs/<trace_id>.verifier.json
          yield panels with verifier_row filled
```

Wall-clock: +~30–60 s per live run (per Track V delivery stats).
Remember to update the `Step N/M` status messages to `/4` if you add
Stage D.

If the Track V delivery already ships a CLI, prefer subprocess-calling
it over in-process import — keeps UI's `metagent-llm` env free of
verifier's own heavy deps.

### 7.6 Panel-4 PREVIEW retirement checklist

When the V-visualisation session lands, delete:

- The yellow `_PREVIEW_BADGE` Markdown in `ui/panels/verifier.py`
- The three mock rows in `_PREVIEW_ROWS`
- This §7.6 bullet from any future delivery writeup

---

## 8. Design decisions (condensed rationale)

| Decision | Rationale |
|---|---|
| Panel 4 visible from v0 with PREVIEW badge | Hiding it would make Verifier look like a sudden new feature when it lands |
| Fixed 4-panel layout | Reviewer compares deterministic pipeline vs LLM narrative in one screen |
| Input / Output colour-stripe framing (no fill) | Dark-theme safe; auto text colour still works |
| 3-stage progressive reveal | Reviewer sees "Input → Pipeline → LLM" as a sequence |
| Cached-first; Live opt-in behind `--enable-live` + env gate | Live = 5 min; demo would hang without this split |
| Top-5 merged gallery + dedicated de-novo gallery | Track C contributes at rank 7–10 in the smoke run; easy to miss in top-5 only |
| CFM-ID overlay as mirror plot (not stacked) | Classic MS/MS spectral-match convention; reviewer eye already trained on this |
| Overlay dropdown limited to candidates with `predicted_spectrum_cosine != None` | Matches the pipeline's `predict_top_n=5` cutoff exactly; prevents empty subplots |
| Literature is on-demand button, not auto | EuroPMC SSL is flaky from this host; auto would surface confusing errors |
| No UI-side LLM calls (not even "regenerate") | Hard scope constraint; UI is window, not filter |
| UI captures predicted spectra via `predict_wrap` rather than mutating schemas | Keeps scope out of `tools/`/`schemas/`; side-car is UI-owned durable cache |
| `METAGENT_MSBART_CKPT` default baked into runners.py | Discoverable for local demo; overridable via env |
| Candidate-charts module retained but not mounted | Last review cut them; module stays so re-mounting is cheap if opinions change |
| `glucose_pos_fusion` as 4th cached fixture | Bonus demo-ready run that actually exercises Track C (the three O1 originals have C=0 due to SIRIUS absence) |

---

## 9. Reproducibility & data inventory

### 9.1 Launch command (LAN-reachable, Live enabled)

```bash
MINIMAX_API_KEY="$(cat api_key.txt)" \
METAGENT_HMDB_PATH=/data/weiwentao/llm_agent_metabolomics/hmdb.sqlite \
METAGENT_RAMP_PATH=/data/weiwentao/llm_agent_metabolomics/ramp.sqlite \
METAGENT_CFM_URL=http://127.0.0.1:8088 \
METAGENT_GNPS_PATH=/data/weiwentao/llm_agent_metabolomics/gnps/ALL_GNPS_cleaned_enriched.csv \
METAGENT_GNPS_SPECTRA_PATH=/data/weiwentao/llm_agent_metabolomics/gnps/ALL_GNPS_cleaned.mgf \
METAGENT_PUBCHEM_LITE_PATH=/data/weiwentao/llm_agent_metabolomics/pubchem_lite.sqlite \
METAGENT_MSBART_CKPT=/home/weiwentao/workspace/mol_gen/MS-BART/data/MassSpecGym/MS-BART-MassSpecGym/csyanghan/MS-BART-MassSpecGym \
conda run -n metagent-llm python -m ui.app --host 0.0.0.0 --port 7861 --enable-live
```

Open `http://192.168.208.220:7861/`.

### 9.2 Cached fixtures on disk

```
/data/weiwentao/llm_agent_metabolomics/pipeline_runs/
├── o1-part4-glucose_pos_fusion.json                     (26 KB — UI Live re-run; C=4 generated)
├── o1-part4-glucose_pos_fusion.predicted_spectra.json   (4.5 KB — 5 CFM-ID predictions)
├── live_d194c869_20260424013444.json                    (older Live ad-hoc; predate side-car wiring)
└── (O1 Part-4 originals live under /tmp/o1/ — ephemeral)

/tmp/o1/
├── glucose_pos.json           (O1 Part-4; C=0; no side-car)
├── caffeine_pos.json          (O1 Part-4; C=0; no side-car)
└── lcarnitine_pos.json        (O1 Part-4; C=0; no side-car)

logs/llm_calls.jsonl           (accumulating; rows joined by trace_id)
```

### 9.3 Trace IDs in play

```
o1-part4-glucose_pos            ← O1 Part 4, cached only, no overlay data
o1-part4-caffeine_pos           ← O1 Part 4, cached only, no overlay data
o1-part4-lcarnitine_pos         ← O1 Part 4, cached only, no overlay data
o1-part4-glucose_pos_fusion     ← UI-produced Live run; full pipeline + overlay data
live_<hash8>_<YYYYMMDDHHMMSS>   ← Format for new Live-mode runs (auto-generated by UI)
```

### 9.4 Test suite

```bash
conda run -n metagent-llm python -m pytest tests/test_ui/ -v
```

Expected: **29 passed** in ~3 s. No real LLM, no subprocess.

---

## 10. Known limitations

1. **`pydantic` was downgraded 2.13.3 → 2.12.3** by Gradio 5.50's pinned
   deps. All existing orchestrator tests still pass, but pin Gradio
   carefully if a future track needs 2.13 features.

2. **`rdkit-pypi 2022.09.5` + numpy 2.x** prints harmless `_ARRAY_API
   not found` to stderr on every molecule render. Swapping to the
   current `rdkit` wheel (drop `-pypi`) fixes it; deferred.

3. **Europe PMC SSL** is flaky from this host (SOCKS-proxy + urllib3
   SSL EOF). UI degrades gracefully with a visible error on the
   literature panel. A future mitigation could route via PubMed first.

4. **Port 7860 is taken** on this host by another user's Gradio
   ("Biomni A1 Agent"). UI binds to **7861** instead. Don't delete the
   `--port` flag.

5. **Live mode takes ~5 min** (pipeline dominates). UI's progress bar
   only reports stage boundaries, not intra-pipeline progress.

6. **`/tmp/gradio` permission clash** with the other user is worked
   around via `GRADIO_TEMP_DIR=/tmp/gradio_$uid` set in `ui/app.py`.
   Removing that line will bring back `PermissionError` in the Gallery
   component.

7. **CFM-ID overlay requires a side-car**; the three O1 originals
   don't have one. Optional mitigation: re-run them with
   `METAGENT_UI_LIVE_TRACE_ID=<trace_id>` to backfill.

8. **predict_top_n=5 skips** (pipeline default) are reported in the
   Pipeline execution summary as "N candidate(s) ran with degraded
   output" — technically true but misleading. Fix it properly by
   teaching `_render_warnings` to separate *skipped-by-design* from
   *tool-failed*; deferred.

9. **Track F literature is shown on button click only** and
   currently does **not** feed into the LLM user message. A separate
   session has added `cr.literature_records` into
   `orchestrator/formatter.py` (see §4 scope audit) — that's the
   pipeline-integrated path; the UI button is the ad-hoc query path.
   Both coexist without conflict.

10. **No git commit yet** at writeup time. Run `git add ui/ tests/test_ui/ reports/ui_v0_delivery_2026-04-24.md` and commit before handing off.

---

## 11. Outstanding for this session

- [ ] Commit the working tree (`ui/`, `tests/test_ui/`, this report).
- [ ] Resolve `rdkit-pypi` vs numpy-2 warnings by moving to `rdkit`
      (one-line change in `ui/requirements.txt`).
- [ ] Optional: backfill predicted-spectra side-cars for the three
      original O1 fixtures so their overlays also work.
- [ ] Optional: screenshots of all 4 fixtures (especially
      `glucose_pos_fusion` showing the de-novo gallery + CFM-ID
      overlay) for PI review.
- [ ] Refine the `_render_warnings` prose on predict_top_n skips (see
      §10 item 8).

None of the above blocks the Verifier-visualisation session.

---

## Appendix A — delivery snapshot

```
cached fixtures: ['glucose_pos', 'caffeine_pos', 'lcarnitine_pos', 'glucose_pos_fusion']

glucose_pos_fusion report:
  n_prefilter_candidates: 206
  n_library_candidates  : 10
  n_generated_candidates: 10
  merged + enriched     : 10  (6 library + 4 generated)

glucose_pos_fusion predicted_spectra side-car (5 entries):
  OCC1OC(O)C(O)C(O)C1O                          → 21 peaks   (rank 1, library, cos 0.381)
  C([C@@H]1[C@H]([C@@H]([C@H](C(O1)O)O)O)O)O    → 21 peaks   (rank 2, library, cos 0.381)
  CC(O)C(O)C(O)C(O)C(O)C(=O)OC1(CO)OCC(O)C(O)C1O → 43 peaks  (rank 7, generated, cos 0.337)
  CC(O)C(O)C(O)C(O)C(O)C(=O)C1(O)OCC(O)C(O)C1O  → 39 peaks   (rank 8, generated, cos 0.162)
  CC(O)C(O)C(O)C(O)C(O)C(O)C(=O)C1(O)OCC(O)C(O)… → 47 peaks  (rank 9, generated, cos 0.194)

Gradio config (running server): 1 Plot · 2 Galleries · 1 Dataframe (pipeline) · 1 Dataframe (verifier PREVIEW)
UI tests: 29 passed in 2.9 s
Working tree: 8 modified, 2 new files (+ reports/ui_v0_delivery_2026-04-24.md)
```

## Appendix B — quick grep targets for the V-visualisation session

```
# Every file that currently knows the panel_outputs shape (15 entries
# before verifier integration; to become 18 after):
$ grep -n "panel_outputs" ui/app.py

# Every _render_for_panels / _blank_panels_tuple / progressive-generator yield:
$ grep -n "exp_meta\|denovo_caption\|predict_caption" ui/app.py

# CachedRun fields (where to add verifier_row):
$ grep -n "CachedRun" ui/data/loaders.py ui/app.py ui/panels/*.py

# Verifier schema / verdict enum to map into the UI table:
$ grep -n "ClaimVerdict\|VerifiedClaim\|VerifiedIdentification" verifier/schemas.py

# Where Track V's delivery describes its run/persistence convention:
$ cat reports/verifier_v0_delivery_2026-04-24.md
```

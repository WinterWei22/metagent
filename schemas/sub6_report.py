"""Schema bridging Sub-6 task data into the verifier.

Sub-6 (pathway-enrichment narrative) tasks do not carry a spectrum +
candidate list, so they cannot use ``schemas.report.IdentificationReport``
(which is spectrum-centric). ``SubsixSourceReport`` is a parallel context
type consumed by the Sub-6 verifier layers
(``set_enrichment``, ``driver_metabolite``, ``pathway_relationship``,
``biological_sub6``) via the dedicated ``verifier.agent.verify_sub6``
entry point.

Contract:

* Tasks live in ``data/benchmark/sub6/{sub6a_e2e_tasks,sub6b_mammalian_tasks}.jsonl``
  per ``reports/benchmark/sub6_evaluation_guide.md``.
* The benchmark runner constructs one ``SubsixSourceReport`` per task by
  copying the JSONL fields verbatim plus an optional ``compound_lookup``
  resolved from ``curated_hmdb_mammalian.jsonl``. Verifier layers do not
  re-load the JSONL.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SubsixSourceReport(BaseModel):
    """Bridges one Sub-6 task into the verifier's ``source_report`` slot.

    All fields except ``differential_metabolites`` / ``differential_spectra``
    / ``compound_lookup`` mirror the corresponding JSONL keys verbatim;
    the verifier layers only ever read this object and never mutate it.
    """

    model_config = ConfigDict(protected_namespaces=())

    task_id: str = Field(..., description="See sub6 JSONL ``task_id``.")
    task_type: Literal[
        "compound_only_enrichment", "end_to_end_enrichment"
    ] = Field(
        ...,
        description=(
            "Distinguishes Sub-6B (compound input) from Sub-6A (spectra input). "
            "Sub-6 verifier layers do not branch on this; the field is "
            "carried for logging and downstream stratification."
        ),
    )
    domain: str = Field("mammalian", description="Stratification key; always 'mammalian' in v0.")

    # Ground-truth fields (used only by graders/verifiers; framework under
    # evaluation never sees these — see eval guide §1).
    ground_truth_pathway: dict[str, Any] = Field(
        ...,
        description=(
            "Canonical RaMP pathway record for the task's hidden ground "
            "truth. Keys: pathway_id, pathway_name, pathway_source, "
            "external_id, primary_pathway_pre_aggregation."
        ),
    )
    ground_truth_signal_compounds: list[str] = Field(
        ...,
        description=(
            "KEGG compound IDs that *are* drivers of the ground-truth "
            "pathway. Used by Layer 6b to detect false-noise drivers."
        ),
    )
    ground_truth_noise_compounds: list[str] = Field(
        ...,
        description=(
            "KEGG compound IDs deliberately injected as noise. A claim "
            "naming any of these as a driver is a CONTRADICTED verdict "
            "(real false positive, not just an unsupported claim)."
        ),
    )
    ramp_enrichment_result: dict[str, Any] = Field(
        ...,
        description=(
            "Full enrichment-tool output for this task. Keys: "
            "input_compounds, resolved_compounds, unresolved_compounds, "
            "background_size, n_input_resolved, top_pathways. "
            "``top_pathways`` is sorted by FDR ascending; "
            "``top_pathways[:3]`` is the acceptance set used by Layer 6a."
        ),
    )

    # Input-side: present for one task type, None for the other.
    differential_metabolites: list[dict[str, Any]] | None = Field(
        None,
        description=(
            "Sub-6B input: list of CuratedCompound dicts (5–8 signal + 2–5 "
            "noise, shuffled). Each carries name, smiles, inchikey, "
            "kegg_id, hmdb_id, npc_*. None for Sub-6A."
        ),
    )
    differential_spectra: list[dict[str, Any]] | None = Field(
        None,
        description=(
            "Sub-6A input: list of GNPS spectra (peaks, precursor_mz, "
            "adduct, ion_mode, source_id, library_membership, ...). None "
            "for Sub-6B. The Sub-6 verifier layers do not read this; the "
            "framework under evaluation does, then emits a narrative the "
            "verifier checks. Surfaced here for logging / leakage audit."
        ),
    )

    # Optional resolution lookup. The benchmark runner can populate this
    # at startup so Layer 6b doesn't reload curated_hmdb_mammalian.jsonl
    # per claim. Keys: lowercase compound names AND KEGG IDs AND HMDB IDs;
    # values: InChIKey first-block.
    compound_lookup: dict[str, str] | None = Field(
        None,
        description=(
            "Optional precomputed lookup from compound name / KEGG ID / "
            "HMDB ID (lowercased) to InChIKey first-block. When None, "
            "Layer 6b loads the curated pool itself; populating this "
            "field amortises the 150-record load over all tasks in a "
            "benchmark run. Layer 6b reads but does not write this field."
        ),
    )

    mummichog_enrichment_result: dict[str, Any] | None = Field(
        None,
        description="Optional normalized standalone Mummichog enrichment output carrier.",
    )
    metaboanalystr_enrichment_result: dict[str, Any] | None = Field(
        None,
        description="Optional nested MetaboAnalystR carrier, keyed by psea/msea/mummichog variants.",
    )
    sspa_enrichment_result: dict[str, Any] | None = Field(
        None,
        description="Optional normalized SSPA enrichment output carrier.",
    )
    fella_enrichment_result: dict[str, Any] | None = Field(
        None,
        description="Optional nested FELLA carrier, keyed by rwr/diffusion variants.",
    )

    # ------------------------------------------------------------------ #
    # Phase 6.3 Layer F adapters
    # ------------------------------------------------------------------ #
    # Layer F (peak_mechanistic) was designed against the spectrum-centric
    # ``IdentificationReport`` and reads ``source_report.experimental_spectrum``
    # and ``source_report.candidates``. To let Sub-6A real-id narratives be
    # validated by Layer F without changing the layer code, surface those two
    # fields as computed properties on SubsixSourceReport. The proxies are
    # intentionally simple — they pick the first differential spectrum and an
    # empty candidate list — sufficient to let Layer F's m/z presence check
    # run. Per-claim spectrum routing is future work (a claim asserting
    # m/z X for spectrum k currently checks against the first spectrum's
    # peaks). Documented limitation in Phase 6.3 report §10.

    @property
    def experimental_spectrum(self):
        """Adapter for verifier.layers.peak_mechanistic.

        Returns the first differential spectrum as a ``schemas.common.Spectrum``
        instance. **Always returns a Spectrum, never None** — Layer F's
        m/z-presence check (line 162) iterates ``spectrum.mz`` and would
        AttributeError on None. When the task has no usable spectrum data we
        return a zero-peak Spectrum so Layer F returns CONTRADICTED ("peak
        not found in 0-peak spectrum"), which is the correct safe default.

        Phase 6.4 fix (2026-05-09): the previous version returned None on
        empty / malformed spectra and on Spectrum() validation failure. That
        caused 12/38 task crashes in the rule-based-extractor verifier run.
        Two changes here:
          1. Always return a (possibly empty) Spectrum — never None.
          2. Normalize intensity to [0, 1] (Spectrum schema requirement) by
             dividing by the maximum, so raw intensities like 1.5e7 don't
             trigger ValidationError.
        """
        from schemas.common import Spectrum
        # Schema requires precursor_mz > 0, adduct non-empty, and at least
        # one peak. The empty placeholder uses harmless non-zero defaults +
        # a single sentinel peak at m/z=1.0 (no real claim m/z will be
        # within 5 ppm of 1.0 Da, so Layer F returns CONTRADICTED with
        # "peak not found in spectrum" — semantically a "we couldn't
        # verify" outcome, not a positive claim).
        empty = Spectrum(mz=[1.0], intensity=[1.0], precursor_mz=1.0,
                         adduct="[M+H]+", ionization_mode="positive")
        spectra = self.differential_spectra or []
        if not spectra:
            return empty
        sp = spectra[0]
        try:
            # Sub-6A v2 differential_spectra schema: peaks is a list of
            # [mz, intensity] pairs. Older formats may use separate mz /
            # intensity arrays — handle both.
            mz_list: list[float] = []
            inten_list: list[float] = []
            peaks = sp.get("peaks")
            if peaks:
                for row in peaks:
                    if isinstance(row, (list, tuple)) and len(row) >= 2:
                        mz_list.append(float(row[0]))
                        inten_list.append(float(row[1]))
            else:
                mz_list = [float(x) for x in (sp.get("mz") or [])]
                inten_list = [float(x) for x in (sp.get("intensity") or [])]
            if inten_list:
                peak_max = max(inten_list)
                if peak_max > 0:
                    inten_list = [max(0.0, min(1.0, x / peak_max)) for x in inten_list]
            # adduct cleanup: "[M+H]1+" → "[M+H]+" (Spectrum schema accepts
            # the canonical form). When adduct is missing or cannot be
            # parsed, default to mode-appropriate.
            ion_mode = sp.get("ionization_mode") or sp.get("ion_mode") or sp.get("polarity") or "positive"
            adduct = sp.get("adduct") or ("[M+H]+" if ion_mode == "positive" else "[M-H]-")
            adduct = adduct.replace("1+", "+").replace("1-", "-")
            if not mz_list:
                return empty
            return Spectrum(
                mz=mz_list,
                intensity=inten_list,
                precursor_mz=float(sp.get("precursor_mz") or 0.0),
                adduct=adduct,
                ionization_mode=ion_mode,
                collision_energy=sp.get("collision_energy"),
            )
        except Exception:  # noqa: BLE001
            return empty

    @property
    def candidates(self):
        """Adapter for verifier.layers.peak_mechanistic.

        Sub-6A v2 SubsixSourceReport does not carry per-spectrum candidates
        (those live in the per-spectrum peak_evidence JSONs). Layer F line
        850/894 falls back gracefully when this is empty — it then takes the
        candidate SMILES/formula from the claim's own ``extracted_fields``,
        which the LLM-as-reranker fills.
        """
        return []

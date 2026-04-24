"""Serialise an IdentificationReport into the user-message body.

Committed format: pseudo-markdown. See prompts/track_01_naive_orchestrator.md
for the format rationale — LLM reads structure better from headings than from
raw JSON, and human annotators reading logs later benefit too.

Important: this formatter **does not sanitise or correct the data**. If HMDB
stored L-carnitine as a cation (162.113 Da, the D-1 issue), the cation mass
flows through here verbatim. That's the baseline we need to measure; any
"correction" would be measurement pollution.
"""
from __future__ import annotations

from schemas.report import CandidateReport, IdentificationReport


DEFAULT_TOP_N = 5


def format_report_for_llm(
    report: IdentificationReport,
    *,
    top_n: int = DEFAULT_TOP_N,
) -> str:
    """Render a pseudo-markdown view of `report` suitable for user-message content."""
    lines: list[str] = []
    _section_experimental(report, lines)
    lines.append("")
    _section_candidates(report, lines, top_n=top_n)
    lines.append("")
    _section_warnings(report, lines)
    lines.append("")
    _section_tool_versions(report, lines)
    lines.append("")
    _section_pipeline_meta(report, lines, top_n=top_n)
    return "\n".join(lines).rstrip() + "\n"


# --------------------------------------------------------------------------- #
# Section builders
# --------------------------------------------------------------------------- #


def _section_experimental(report: IdentificationReport, lines: list[str]) -> None:
    spec = report.experimental_spectrum
    lines.append("## Experimental spectrum")
    lines.append(f"- Precursor m/z: {spec.precursor_mz}")
    lines.append(f"- Adduct: {spec.adduct}")
    lines.append(f"- Ionization mode: {spec.ionization_mode}")
    if spec.collision_energy is not None:
        lines.append(f"- Collision energy (eV): {spec.collision_energy}")
    lines.append(f"- Neutral mass (back-calculated from precursor): {report.neutral_mass_computed}")
    lines.append(f"- Peak count (after preprocess): {len(spec.mz)}")
    lines.append(f"- Preprocess quality flag: {report.preprocess_quality_flag}")


def _section_candidates(
    report: IdentificationReport, lines: list[str], *, top_n: int
) -> None:
    shown = report.candidates[:top_n]
    lines.append(f"## Candidates (top {len(shown)} by evidence_score)")
    if not shown:
        lines.append("")
        lines.append("_(no candidates — pipeline returned an empty list)_")
        return
    for rank, cr in enumerate(shown, start=1):
        lines.append("")
        _candidate_block(cr, rank, lines)


def _candidate_block(cr: CandidateReport, rank: int, lines: list[str]) -> None:
    cand = cr.candidate
    name = _best_name(cr) or "unknown"
    lines.append(f"### {rank}. {name} (evidence_score: {cr.evidence_score:.3f})")
    lines.append(f"- SMILES: {cand.smiles}")

    formula = _best_formula(cr)
    lines.append(f"- Molecular formula: {formula if formula else 'not available'}")

    lines.append(f"- Candidate source: {cand.source}")
    if cand.source_id:
        lines.append(f"- Source ID: {cand.source_id}")
    lines.append(f"- Candidate score (B/C): {cand.score:.3f}")

    if cr.predicted_spectrum_cosine is not None:
        cos_line = f"- Predicted-spectrum cosine vs experimental: {cr.predicted_spectrum_cosine:.3f}"
        if cr.predicted_model_version:
            cos_line += f"  (model: {cr.predicted_model_version})"
        lines.append(cos_line)
    else:
        lines.append("- Predicted-spectrum cosine vs experimental: not available")

    mass_ok = cr.mass_match_indicator >= 0.5
    lines.append(
        f"- Mass match (SMILES-derived, 5 ppm): {'yes' if mass_ok else 'no'}"
    )

    _pathway_line(cr, lines)

    if cr.metabolite_info and cr.metabolite_info.found:
        info = cr.metabolite_info
        refs = info.cross_refs or {}
        if refs:
            ref_items = ", ".join(f"{k.upper()}={v}" for k, v in refs.items())
            lines.append(f"- Cross-refs: {ref_items}")
        if info.exact_mass is not None:
            # Note: this value is recorded verbatim from HMDB; for some
            # zwitterions (e.g. L-carnitine) HMDB stores the cation form,
            # so this may disagree with the SMILES-derived neutral mass by
            # roughly 1 Da. This is intentional — see Track D-1.
            lines.append(f"- HMDB exact_mass (as stored): {info.exact_mass}")
        if info.chemical_class:
            lines.append(f"- Chemical class: {info.chemical_class}")

    _literature_block(cr, lines)

    if cr.notes:
        lines.append("- Notes:")
        for note in cr.notes:
            lines.append(f"    - {note}")


def _literature_block(cr: CandidateReport, lines: list[str]) -> None:
    """Render the candidate's literature_records (Track F output) as a
    short bulletised block. Empty list → omit entirely (no bullet);
    populated → one indented sub-bullet per record with PMID, title,
    journal/year, and the abstract head.

    Truncation rules (kept tight so the user message stays under MiniMax's
    practical context window):
      * up to 3 records per candidate (formatter-level cap; pipeline cap
        is configurable separately via literature_max_results)
      * abstract truncated to ~200 chars + ellipsis
    """
    recs = cr.literature_records
    if not recs:
        return
    shown = recs[:3]
    extra = len(recs) - len(shown)
    lines.append(f"- Literature ({len(recs)} record(s)):")
    for rec in shown:
        head = rec.abstract.strip().replace("\n", " ")
        if len(head) > 200:
            head = head[:200].rstrip() + "…"
        meta = f"{rec.journal} {rec.year}" if rec.journal else str(rec.year)
        lines.append(f"    - PMID:{rec.pmid} — {rec.title} ({meta})")
        if head:
            lines.append(f"      {head}")
    if extra > 0:
        lines.append(f"    - +{extra} more record(s) not shown")


def _pathway_line(cr: CandidateReport, lines: list[str]) -> None:
    pw = cr.pathway_context
    if pw is None or not pw.pathways:
        lines.append("- Pathways: not available")
        return
    parts: list[str] = []
    for entry in pw.pathways[:5]:
        hit_suffix = f"{entry.hit_count} hit" + ("s" if entry.hit_count != 1 else "")
        parts.append(f"{entry.name} ({entry.source} {entry.id}, {hit_suffix})")
    extra = len(pw.pathways) - 5
    tail = f"; +{extra} more" if extra > 0 else ""
    lines.append(f"- Pathways: {'; '.join(parts)}{tail}")


def _section_warnings(report: IdentificationReport, lines: list[str]) -> None:
    lines.append("## Pipeline warnings")
    if not report.warnings:
        lines.append("- (none)")
        return
    for w in report.warnings:
        lines.append(f"- {w}")


def _section_tool_versions(report: IdentificationReport, lines: list[str]) -> None:
    lines.append("## Tool versions")
    if not report.tool_versions:
        lines.append("- (not reported)")
        return
    for k, v in sorted(report.tool_versions.items()):
        lines.append(f"- {k}: {v}")


def _section_pipeline_meta(
    report: IdentificationReport, lines: list[str], *, top_n: int
) -> None:
    lines.append("## Pipeline metadata")
    lines.append(f"- Pipeline version: {report.pipeline_version}")
    lines.append(
        f"- Candidate counts — prefilter: {report.n_prefilter_candidates}, "
        f"library: {report.n_library_candidates}, "
        f"generated: {report.n_generated_candidates}, "
        f"merged/enriched: {len(report.candidates)}"
    )
    shown = min(top_n, len(report.candidates))
    lines.append(f"- Candidates shown above: top {shown}")


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def _best_name(cr: CandidateReport) -> str | None:
    if cr.metabolite_info and cr.metabolite_info.found and cr.metabolite_info.primary_name:
        return cr.metabolite_info.primary_name
    if cr.prefilter_match and cr.prefilter_match.name:
        return cr.prefilter_match.name
    if cr.candidate.name:
        return cr.candidate.name
    return None


def _best_formula(cr: CandidateReport) -> str | None:
    if cr.metabolite_info and cr.metabolite_info.found and cr.metabolite_info.molecular_formula:
        return cr.metabolite_info.molecular_formula
    if cr.prefilter_match and cr.prefilter_match.molecular_formula:
        return cr.prefilter_match.molecular_formula
    return None

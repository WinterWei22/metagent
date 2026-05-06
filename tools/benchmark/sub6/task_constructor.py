"""Construct Sub-6 enrichment tasks from curated compounds.

Two task types:

* **compound-only** (Sub-6B): differential set is a list of compounds.
  Domain ∈ {"plant", "mammalian"} discriminates the two source pools.
* **end-to-end** (Sub-6A): each Sub-6B-Plant task is rewritten with
  raw spectra in place of the compound list. Same ground truth.

Construction algorithm
----------------------
1. For each curated compound, pick its **primary pathway**:
   sort the compound's ``ramp_pathway_ids`` by
   ``(in-subset peer count desc, listing-order asc)`` and take the
   first. The peer count is a proxy for the protocol's "pathway size"
   tie-breaker — we use the curated-subset's own membership counts
   because ``CuratedCompound`` doesn't carry RaMP-wide K.
2. Group curated compounds by their primary pathway → keep only
   pathways with ≥ ``pathway_min_compounds`` members.
3. For each qualifying pathway, generate ``tasks_per_pathway``
   candidate tasks with **derived seeds**
   ``derive_seed(cli_seed, pathway_id, task_index)``.
4. Each task: ``random.sample`` ``n_signal`` from in-pathway peers and
   ``n_noise`` from out-of-pathway compounds, then shuffle.
5. Run :func:`compute_enrichment` on each candidate; keep only tasks
   where the primary pathway (or its post-aggregation representative,
   matched by compound-set overlap) appears in ``top_pathways[:3]``.
6. Stop once ``target_task_count`` tasks have been kept (or candidates
   exhausted).
"""
from __future__ import annotations

import hashlib
import json
import logging
import random
import sqlite3
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from schemas.common import ToolError

from .compound_curator import CuratedCompound, _classify_pathway_bucket
from .ramp_enrichment import (
    EnrichmentReport,
    EnrichmentResult,
    compute_enrichment,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class TaskConstructionError(ToolError):
    code = "TASK_CONSTRUCTION_ERROR"
    recoverable = False


# ---------------------------------------------------------------------------
# Mammalian pathway acceptance rules (Sub-6 Pathway-Fix session)
#
# After NPClassifier-curated HMDB candidates land, raw RaMP pathway lookups
# still surface (a) generic catch-alls like "Metabolism" or "Biochemical
# pathways: part I", (b) clinical disease entries treated as pathways in
# RaMP/SMPDB (e.g. "Alkaptonuria"), and (c) overly broad pathways with
# K > 500 compounds (no enrichment signal — they match every input set).
# We reject these and prefer KEGG / Reactome / SMPDB / WikiPathways sources.
# ---------------------------------------------------------------------------


_GENERIC_PATHWAY_BLOCKLIST: frozenset[str] = frozenset({
    "metabolism",
    "biochemical pathways",
    "biochemical pathways: part i",
    "biochemical pathways: part ii",
    "metabolic pathways",
    "disease",
})

_DISEASE_KEYWORDS: tuple[str, ...] = (
    "alkaptonuria", "deficiency", "syndrome", "disorder",
    "disease", "defect",
)

_ACCEPTABLE_MAM_SOURCES: frozenset[str] = frozenset({
    "kegg", "reactome", "smpdb", "wikipathways",
})

_DEFAULT_MAX_PATHWAY_K: int = 500


def _is_acceptable_mammalian_pathway(
    *,
    name: str,
    source: str,
    total_compounds: int,
    max_k: int = _DEFAULT_MAX_PATHWAY_K,
) -> tuple[bool, str | None]:
    """Apply mammalian pathway acceptance filter.

    Returns ``(accepted, drop_reason_or_None)``.
    """
    name_lower = (name or "").lower().strip()
    if name_lower in _GENERIC_PATHWAY_BLOCKLIST:
        return False, "generic_pathway"
    if any(kw in name_lower for kw in _DISEASE_KEYWORDS):
        return False, "disease_keyword"
    if source not in _ACCEPTABLE_MAM_SOURCES:
        return False, f"source_rejected_{source or 'unknown'}"
    if total_compounds > max_k:
        return False, "too_broad_K_gt_500"
    return True, None


def _query_pathway_total_k(
    ramp_db_path: Path | str, pathway_ids: Iterable[str],
) -> dict[str, int]:
    """Total RaMP-wide compound count per pathway (the K in hypergeom)."""
    ids = [pid for pid in pathway_ids if pid]
    if not ids:
        return {}
    p = Path(ramp_db_path)
    if not p.is_file():
        raise TaskConstructionError(f"RaMP DB not found: {p}")
    uri = f"file:{p.resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        out: dict[str, int] = {}
        chunk = 500
        for i in range(0, len(ids), chunk):
            batch = ids[i : i + chunk]
            ph = ",".join("?" for _ in batch)
            cur = conn.execute(
                f"SELECT pathwayRampId, COUNT(DISTINCT rampId) AS k "
                f"FROM analytehaspathway "
                f"WHERE rampId LIKE 'RAMP_C%' AND pathwayRampId IN ({ph}) "
                f"GROUP BY pathwayRampId",
                batch,
            )
            for r in cur:
                out[r["pathwayRampId"]] = int(r["k"])
        return out
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------


@dataclass
class EnrichmentTask:
    """A single Sub-6 evaluation task with full ground truth."""

    task_id: str
    task_type: str  # "compound_only_enrichment" | "end_to_end_enrichment"
    domain: str    # "plant" | "mammalian"

    # Inputs (exactly one populated)
    differential_metabolites: list[dict] | None  # list[CuratedCompound.to_json()]
    differential_spectra: list[dict] | None       # list of spectrum dicts

    # Ground truth
    ground_truth_pathway: dict                     # {pid, name, source, external_id}
    ground_truth_signal_compounds: list[str]       # input_ids (kegg or inchikey)
    ground_truth_noise_compounds: list[str]
    ramp_enrichment_result: dict                    # EnrichmentReport.to_json()

    # Construction metadata
    seed: int
    cli_seed: int
    signal_count: int
    noise_count: int
    signal_ratio: float
    id_type: str          # "inchikey" | "kegg"

    def to_json(self) -> dict:
        return asdict(self)


@dataclass
class TaskConstructionStats:
    n_pathways_considered: int = 0
    n_pathways_qualifying: int = 0
    n_candidate_tasks: int = 0
    n_dropped_ground_truth_not_in_top3: int = 0
    n_dropped_too_few_members: int = 0
    n_dropped_too_few_non_members: int = 0
    n_final: int = 0
    drop_reasons: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def derive_seed(cli_seed: int, pathway_id: str, task_index: int) -> int:
    """Deterministic per-task seed.

    Uses sha256 over the (cli_seed, pathway_id, task_index) tuple and
    takes the first 8 hex chars as a 32-bit unsigned int.
    """
    payload = f"{cli_seed}:{pathway_id}:{task_index}".encode()
    return int(hashlib.sha256(payload).hexdigest()[:8], 16)


def _pathway_short(pathway_id: str) -> str:
    """Short slug suitable for task_id."""
    cleaned = pathway_id.replace(":", "_").replace("/", "_")
    if len(cleaned) <= 24:
        return cleaned
    return cleaned[:8] + "_" + hashlib.sha1(pathway_id.encode()).hexdigest()[:8]


_SOURCE_RANK: dict[str, int] = {
    "kegg": 0,    # canonical KEGG pathways — most defensible benchmark targets
    "hmdb": 1,    # SMPDB (RaMP stores SMPDB under type='hmdb')
    "wiki": 2,    # WikiPathways
    "reactome": 3,  # Reactome (often broader, less benchmark-friendly)
    "pfocr": 9,   # auto-OCR — last resort
}


def _pick_primary_pathway(
    compound: CuratedCompound,
    pathway_in_subset_count: dict[str, int],
    *,
    pathway_total_k: dict[str, int] | None = None,
    acceptable_pathway_ids: set[str] | None = None,
) -> tuple[str, str, str, str | None] | None:
    """Return (pathway_id, pathway_name, pathway_source, external_id) or None.

    Selection rule:
        1. If ``acceptable_pathway_ids`` is given, only those pathways are
           candidates.
        2. Sort candidates by ``(source_rank asc, peer-count desc, K asc,
           listing-order asc)``: prefer KEGG > SMPDB > WikiPathways >
           Reactome (a curated-source ladder); within source, the
           most-popular-in-subset pathway wins; ties broken by smallest
           RaMP-wide K (most specific).
        3. ``K asc`` falls back to listing order when ``pathway_total_k``
           is None.
    """
    if not compound.ramp_pathway_ids:
        return None
    n = len(compound.ramp_pathway_ids)
    candidates: list[tuple[int, int, int, int, str]] = []
    for i in range(n):
        pid = compound.ramp_pathway_ids[i]
        if acceptable_pathway_ids is not None and pid not in acceptable_pathway_ids:
            continue
        ptype = (compound.ramp_pathway_sources[i]
                 if i < len(compound.ramp_pathway_sources) else "")
        peers = pathway_in_subset_count.get(pid, 0)
        k = pathway_total_k.get(pid, 1 << 30) if pathway_total_k else 1 << 30
        source_rank = _SOURCE_RANK.get(ptype, 5)
        candidates.append((source_rank, -peers, k, i, pid))
    if not candidates:
        return None
    candidates.sort()
    _src_rank, _peers, _k, idx, pid = candidates[0]
    name = (compound.ramp_pathway_names[idx]
            if idx < len(compound.ramp_pathway_names) else "")
    ptype = (compound.ramp_pathway_sources[idx]
             if idx < len(compound.ramp_pathway_sources) else "")
    source_label = {"kegg": "kegg", "reactome": "reactome", "wiki": "wikipathways",
                    "hmdb": "smpdb", "pfocr": "pfocr"}.get(ptype, ptype or "unknown")
    return pid, name, source_label, None


def _build_input_ids(
    compounds: list[CuratedCompound], id_type: str,
) -> list[str]:
    out: list[str] = []
    for c in compounds:
        if id_type == "kegg":
            out.append(c.kegg_id or c.inchikey)
        else:
            out.append(c.inchikey)
    return out


def _compound_identity_key(c: CuratedCompound) -> str:
    """Stable compound key for benchmark sampling de-duplication."""
    if c.kegg_id:
        return f"kegg:{c.kegg_id}"
    first = c.inchikey_first_block or c.inchikey[:14]
    return f"inchikey14:{first}"


def _dedupe_compounds(
    compounds: Iterable[CuratedCompound],
) -> list[CuratedCompound]:
    """Keep one representative per compound identity, preserving order."""
    seen: set[str] = set()
    out: list[CuratedCompound] = []
    for c in compounds:
        key = _compound_identity_key(c)
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def _make_unique_task_id(task_id: str, seen_task_ids: set[str]) -> str:
    if task_id not in seen_task_ids:
        seen_task_ids.add(task_id)
        return task_id
    n = 1
    while f"{task_id}_dup{n}" in seen_task_ids:
        n += 1
    unique = f"{task_id}_dup{n}"
    seen_task_ids.add(unique)
    return unique


def _ground_truth_in_top3(
    primary_pid: str,
    signal_input_ids: list[str],
    top_pathways: list[EnrichmentResult],
    *,
    overlap_threshold: float = 0.8,
) -> tuple[bool, EnrichmentResult | None]:
    """Return (matched, the matching top-3 pathway).

    Matches by direct ID equality OR by ≥overlap_threshold of signal_input_ids
    appearing in a top-3 pathway's matched_compounds (covers the case where
    the primary pathway was pfocr and got rolled into a PFOCR_AGG::* representative).
    """
    if not top_pathways:
        return False, None
    top3 = top_pathways[:3]
    for tp in top3:
        if tp.pathway_id == primary_pid:
            return True, tp
    if not signal_input_ids:
        return False, None
    sig = set(signal_input_ids)
    threshold = max(1, int(overlap_threshold * len(sig)))
    for tp in top3:
        if len(set(tp.matched_compounds) & sig) >= threshold:
            return True, tp
    return False, None


# ---------------------------------------------------------------------------
# Public: compound-only task construction (Sub-6B)
# ---------------------------------------------------------------------------


def construct_compound_only_tasks(
    curated_compounds: list[CuratedCompound],
    *,
    domain: Literal["plant", "mammalian"],
    target_task_count: int,
    ramp_db_path: Path | str,
    cli_seed: int,
    excluded_pathway_types: tuple[str, ...] = (),
    aggregate_pfocr: bool = True,
    signal_count_range: tuple[int, int] = (5, 8),
    noise_count_range: tuple[int, int] = (2, 5),
    pathway_min_compounds: int = 5,
    tasks_per_pathway_max: int = 3,
    tasks_per_bucket_max: int | None = 5,
    apply_mammalian_filter: bool | None = None,
    max_pathway_k: int = _DEFAULT_MAX_PATHWAY_K,
    id_type: Literal["inchikey", "kegg"] | None = None,
) -> tuple[list[EnrichmentTask], TaskConstructionStats]:
    """Construct Sub-6B tasks (compound-only enrichment).

    For ``domain="mammalian"``, the mammalian pathway acceptance filter is
    applied automatically (rejects generic / disease / broad / non-curated
    pathway sources) and tasks are round-robin'd across the 5 mammalian
    buckets defined in :func:`compound_curator._classify_pathway_bucket`.
    Pass ``apply_mammalian_filter`` explicitly to override.
    """
    stats = TaskConstructionStats()
    if id_type is None:
        id_type = "kegg" if domain == "mammalian" else "inchikey"
    if apply_mammalian_filter is None:
        apply_mammalian_filter = (domain == "mammalian")

    # Step 1: count in-subset peers per pathway
    pathway_in_subset_count: dict[str, int] = defaultdict(int)
    for c in curated_compounds:
        for pid in c.ramp_pathway_ids:
            pathway_in_subset_count[pid] += 1

    # Step 1.5 (mammalian only): pre-compute pathway-level acceptance.
    # Doing this BEFORE primary-pathway selection forces each compound to
    # pick its most-specific *acceptable* pathway as primary, instead of
    # collapsing onto generic catchalls.
    pathway_total_k: dict[str, int] = {}
    acceptable_pathway_ids: set[str] | None = None
    pathway_meta_lookup: dict[str, tuple[str, str]] = {}
    if apply_mammalian_filter and pathway_in_subset_count:
        pathway_total_k = _query_pathway_total_k(
            ramp_db_path, pathway_in_subset_count.keys(),
        )
        # Collect (name, source) for each pid from any compound that lists it
        for c in curated_compounds:
            for i, pid in enumerate(c.ramp_pathway_ids):
                if pid in pathway_meta_lookup:
                    continue
                name = (c.ramp_pathway_names[i]
                        if i < len(c.ramp_pathway_names) else "")
                src_raw = (c.ramp_pathway_sources[i]
                           if i < len(c.ramp_pathway_sources) else "")
                src_norm = {"kegg": "kegg", "reactome": "reactome",
                             "hmdb": "smpdb", "wiki": "wikipathways",
                             "pfocr": "pfocr"}.get(src_raw, src_raw)
                pathway_meta_lookup[pid] = (name, src_norm)
        acceptable_pathway_ids = set()
        for pid, (name, src_norm) in pathway_meta_lookup.items():
            ok, reason = _is_acceptable_mammalian_pathway(
                name=name, source=src_norm,
                total_compounds=pathway_total_k.get(pid, 0),
                max_k=max_pathway_k,
            )
            if ok:
                acceptable_pathway_ids.add(pid)
            else:
                stats.drop_reasons[f"pathway_filter_{reason}"] = (
                    stats.drop_reasons.get(f"pathway_filter_{reason}", 0) + 1
                )

    # Step 2: pick each compound's primary pathway (acceptance-aware)
    primary_by_compound: dict[str, tuple[str, str, str, str | None]] = {}
    for c in curated_compounds:
        primary = _pick_primary_pathway(
            c, pathway_in_subset_count,
            pathway_total_k=pathway_total_k or None,
            acceptable_pathway_ids=acceptable_pathway_ids,
        )
        if primary is not None:
            primary_by_compound[c.inchikey_first_block] = primary

    # Step 3: invert — pathway_id → list of curated compounds
    by_pathway: dict[str, list[CuratedCompound]] = defaultdict(list)
    pathway_meta: dict[str, tuple[str, str, str | None]] = {}
    for c in curated_compounds:
        primary = primary_by_compound.get(c.inchikey_first_block)
        if primary is None:
            continue
        pid, name, source, ext = primary
        by_pathway[pid].append(c)
        pathway_meta.setdefault(pid, (name, source, ext))

    stats.n_pathways_considered = len(by_pathway)

    # Step 4: pathway-min-compounds gate
    qualifying = {
        pid: members for pid, members in by_pathway.items()
        if len(members) >= pathway_min_compounds
    }
    stats.n_pathways_qualifying = len(qualifying)
    if not qualifying:
        logger.warning(
            "task_constructor: no pathways with ≥%d primary-attributed members",
            pathway_min_compounds,
        )
        return [], stats

    # Step 5: per-pathway task generation
    all_compounds_by_first: dict[str, CuratedCompound] = {
        c.inchikey_first_block: c for c in curated_compounds
    }
    out_tasks: list[EnrichmentTask] = []
    seen_task_ids: set[str] = set()
    bucket_task_count: dict[str, int] = defaultdict(int)
    pathway_to_bucket: dict[str, str] = {}

    # Order pathways: mammalian → round-robin across buckets so 5 classes are
    # represented before any single bucket fills. Plant/legacy → desc by member count.
    if apply_mammalian_filter:
        for pid in qualifying:
            pname = pathway_meta[pid][0]
            pathway_to_bucket[pid] = _classify_pathway_bucket(pname)
        bucket_to_pathways: dict[str, list[str]] = defaultdict(list)
        for pid, b in pathway_to_bucket.items():
            bucket_to_pathways[b].append(pid)
        # Within each bucket: prefer pathways with more members
        for b in bucket_to_pathways:
            bucket_to_pathways[b].sort(key=lambda p: (-len(qualifying[p]), p))
        # Round-robin across buckets (largest bucket first for tie-stability)
        bucket_keys = sorted(bucket_to_pathways.keys(),
                              key=lambda b: (-len(bucket_to_pathways[b]), b))
        pathway_order: list[str] = []
        max_depth = max((len(v) for v in bucket_to_pathways.values()), default=0)
        for d in range(max_depth):
            for b in bucket_keys:
                if d < len(bucket_to_pathways[b]):
                    pathway_order.append(bucket_to_pathways[b][d])
    else:
        pathway_order = sorted(qualifying.keys(),
                               key=lambda p: (-len(qualifying[p]), p))

    for pid in pathway_order:
        if len(out_tasks) >= target_task_count:
            break
        bucket = pathway_to_bucket.get(pid, "")
        if (apply_mammalian_filter and tasks_per_bucket_max is not None
                and bucket_task_count[bucket] >= tasks_per_bucket_max):
            continue
        members = _dedupe_compounds(qualifying[pid])
        if len(members) < max(3, pathway_min_compounds):
            stats.n_dropped_too_few_members += 1
            continue
        member_identity_keys = {_compound_identity_key(m) for m in members}
        non_members = [
            c for c in curated_compounds
            if _compound_identity_key(c) not in member_identity_keys
        ]
        non_members = _dedupe_compounds(non_members)
        sig_lo, sig_hi = signal_count_range
        noise_lo, noise_hi = noise_count_range
        if len(members) < sig_lo:
            stats.n_dropped_too_few_members += 1
            continue
        if len(non_members) < noise_lo:
            stats.n_dropped_too_few_non_members += 1
            continue

        pname, psource, pext = pathway_meta[pid]
        for task_idx in range(tasks_per_pathway_max):
            if len(out_tasks) >= target_task_count:
                break
            if (apply_mammalian_filter and tasks_per_bucket_max is not None
                    and bucket_task_count[bucket] >= tasks_per_bucket_max):
                break
            seed = derive_seed(cli_seed, pid, task_idx)
            rnd = random.Random(seed)
            n_signal = rnd.randint(sig_lo, min(sig_hi, len(members)))
            n_noise = rnd.randint(noise_lo, min(noise_hi, len(non_members)))
            signal = rnd.sample(members, n_signal)
            noise = rnd.sample(non_members, n_noise)
            differential = signal + noise
            rnd.shuffle(differential)

            input_ids = _build_input_ids(differential, id_type)
            signal_ids = _build_input_ids(signal, id_type)
            noise_ids = _build_input_ids(noise, id_type)

            stats.n_candidate_tasks += 1

            # Step 6: run enrichment + validate ground truth in top-3
            try:
                rep = compute_enrichment(
                    input_ids, id_type=id_type,  # type: ignore[arg-type]
                    ramp_db_path=ramp_db_path,
                    excluded_pathway_types=excluded_pathway_types,
                    aggregate_pfocr=aggregate_pfocr,
                    top_n=10,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "task_constructor: enrichment failed for pathway=%s seed=%s: %s",
                    pid, seed, e,
                )
                stats.drop_reasons["enrichment_failed"] = (
                    stats.drop_reasons.get("enrichment_failed", 0) + 1)
                continue

            ok, matched_top = _ground_truth_in_top3(pid, signal_ids, rep.top_pathways)
            if not ok:
                stats.n_dropped_ground_truth_not_in_top3 += 1
                logger.debug(
                    "task_constructor: pathway %s not in top-3 for seed=%s "
                    "(top-3: %s)",
                    pid, seed,
                    [(t.pathway_id, t.fdr) for t in rep.top_pathways[:3]],
                )
                continue

            # Use the post-aggregation representative as the task's ground truth
            # if the original primary was pfocr-aggregated.
            gt_pid = matched_top.pathway_id if matched_top else pid
            gt_name = matched_top.pathway_name if matched_top else pname
            gt_source = matched_top.pathway_source if matched_top else psource
            gt_external = matched_top.pathway_external_id if matched_top else pext

            # Mammalian: re-validate that the FINAL ground-truth pathway also
            # passes the acceptance filter. matched_top may be a catchall
            # (e.g. "Metabolism", K=288) that surfaced via signal-set overlap
            # even when our primary was specific.
            if apply_mammalian_filter and matched_top is not None:
                ok2, reason = _is_acceptable_mammalian_pathway(
                    name=gt_name, source=gt_source,
                    total_compounds=matched_top.total_pathway_compounds,
                    max_k=max_pathway_k,
                )
                if not ok2:
                    key = f"gt_pathway_filter_{reason}"
                    stats.drop_reasons[key] = stats.drop_reasons.get(key, 0) + 1
                    continue

            short = _pathway_short(gt_pid)
            task_id = (
                f"compound_only_enrich_{domain}_{short}_seed{task_idx}"
            )
            task_id = _make_unique_task_id(task_id, seen_task_ids)

            task = EnrichmentTask(
                task_id=task_id,
                task_type="compound_only_enrichment",
                domain=domain,
                differential_metabolites=[c.to_json() for c in differential],
                differential_spectra=None,
                ground_truth_pathway={
                    "pathway_id": gt_pid,
                    "pathway_name": gt_name,
                    "pathway_source": gt_source,
                    "external_id": gt_external,
                    "primary_pathway_pre_aggregation": pid,
                },
                ground_truth_signal_compounds=signal_ids,
                ground_truth_noise_compounds=noise_ids,
                ramp_enrichment_result=rep.to_json(),
                seed=seed,
                cli_seed=cli_seed,
                signal_count=n_signal,
                noise_count=n_noise,
                signal_ratio=n_signal / (n_signal + n_noise),
                id_type=id_type,
            )
            out_tasks.append(task)
            if apply_mammalian_filter:
                bucket_task_count[bucket] += 1

    stats.n_final = len(out_tasks)
    return out_tasks, stats


# ---------------------------------------------------------------------------
# Public: end-to-end task construction (Sub-6A)
# ---------------------------------------------------------------------------


def construct_end_to_end_tasks(
    compound_only_tasks: list[EnrichmentTask],
    *,
    cli_seed: int,
    spectrum_index: "dict[str, list]",  # first_block → list[SpectrumPayload | dict]
    spectra_per_compound_range: tuple[int, int] = (1, 2),
    min_compounds_with_spectra: int = 4,
) -> list[EnrichmentTask]:
    """Convert Sub-6B compound-only tasks into Sub-6A end-to-end tasks by
    replacing the differential compound list with raw library spectra
    (1–2 per qualifying compound) drawn from ``spectrum_index``.

    ``spectrum_index`` is keyed by InChIKey first-block (matching
    ``CuratedCompound.inchikey_first_block``). Values are lists of
    spectrum payload objects: either :class:`spectrum_lookup.SpectrumPayload`
    or pre-serialized ``dict`` form (both are accepted; ``dict`` form
    flows straight into ``EnrichmentTask.differential_spectra``).

    Tasks where fewer than ``min_compounds_with_spectra`` of the
    differential compounds have any usable library spectrum are dropped.
    """
    out: list[EnrichmentTask] = []
    spec_lo, spec_hi = spectra_per_compound_range
    for task in compound_only_tasks:
        if task.task_type != "compound_only_enrichment":
            continue
        e2e_seed = derive_seed(
            cli_seed, task.ground_truth_pathway["pathway_id"], task.seed,
        )
        rnd = random.Random(e2e_seed)
        differential_spectra: list[dict] = []
        n_compounds_with_specs = 0
        for c in task.differential_metabolites or []:
            first = c.get("inchikey_first_block") or ""
            available = spectrum_index.get(first) or []
            if not available:
                continue
            n_compounds_with_specs += 1
            n = rnd.randint(spec_lo, min(spec_hi, len(available)))
            picked = rnd.sample(available, n)
            for p in picked:
                if hasattr(p, "to_dict"):
                    differential_spectra.append(p.to_dict())
                elif isinstance(p, dict):
                    differential_spectra.append(p)
        if n_compounds_with_specs < min_compounds_with_spectra:
            logger.warning(
                "task_constructor: e2e drop %s (only %d/%d compounds have spectra)",
                task.task_id, n_compounds_with_specs,
                len(task.differential_metabolites or []),
            )
            continue
        rnd.shuffle(differential_spectra)

        short = _pathway_short(task.ground_truth_pathway["pathway_id"])
        e2e_id = f"e2e_enrich_{task.domain}_{short}_seed{task.seed}"
        e2e = EnrichmentTask(
            task_id=e2e_id,
            task_type="end_to_end_enrichment",
            domain=task.domain,
            differential_metabolites=None,
            differential_spectra=differential_spectra,
            ground_truth_pathway=task.ground_truth_pathway,
            ground_truth_signal_compounds=task.ground_truth_signal_compounds,
            ground_truth_noise_compounds=task.ground_truth_noise_compounds,
            ramp_enrichment_result=task.ramp_enrichment_result,
            seed=e2e_seed,
            cli_seed=cli_seed,
            signal_count=task.signal_count,
            noise_count=task.noise_count,
            signal_ratio=task.signal_ratio,
            id_type=task.id_type,
        )
        out.append(e2e)
    return out


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def save_tasks(tasks: Iterable[EnrichmentTask], output_path: Path | str) -> Path:
    """Write tasks to JSONL. Returns the resolved output path."""
    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for t in tasks:
            f.write(json.dumps(t.to_json(), ensure_ascii=False))
            f.write("\n")
    return p

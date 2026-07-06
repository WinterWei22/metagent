"""Phase A — graded, ontology-driven pathway matcher (A1).

Deterministic, zero-LLM scoring of a predicted pathway against a gold pathway.
Tier logic is decoupled from the RaMP data access so it is unit-testable with an
injected resolver (see tests/test_pathway_match_rubric.py). A RaMP-backed
resolver is provided for the real benchmark run.

Tiers (strict short-circuit): EXACT > PARENT_CHILD > ADJACENT > MISS.
  - strict credit  = {EXACT, PARENT_CHILD}
  - lenient credit = strict + {ADJACENT}
  - MISS is always wrong; the denominator never drops a task.
"""
from __future__ import annotations

import enum
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class MatchTier(enum.Enum):
    EXACT = "exact"
    PARENT_CHILD = "parent_child"
    ADJACENT = "adjacent"
    MISS = "miss"


STRICT_CREDIT = frozenset({MatchTier.EXACT, MatchTier.PARENT_CHILD})
LENIENT_CREDIT = STRICT_CREDIT | frozenset({MatchTier.ADJACENT})


@dataclass(frozen=True)
class PathwayEntry:
    ramp_id: str
    normalized_name: str
    metabolites: frozenset[str]


@dataclass
class MatchResult:
    tier: MatchTier
    evidence: str = ""
    jaccard: float = 0.0
    containment: float = 0.0

    @property
    def strict_credit(self) -> bool:
        return self.tier in STRICT_CREDIT

    @property
    def lenient_credit(self) -> bool:
        return self.tier in LENIENT_CREDIT


class Resolver(Protocol):
    def resolve(self, name_or_id: str) -> PathwayEntry | None: ...
    def discriminative(self, metabolite_id: str) -> bool: ...


class PathwayMatcher:
    def __init__(
        self,
        resolver: Resolver,
        tau_exact: float = 0.9,
        tau_containment: float = 0.7,
        k_specific: int = 2,
    ):
        self._resolver = resolver
        self.tau_exact = tau_exact
        self.tau_containment = tau_containment
        self.k_specific = k_specific

    def match(self, predicted: str, gold: str) -> MatchResult:
        pred = self._resolver.resolve(predicted)
        goal = self._resolver.resolve(gold)

        # EXACT fast path: both surface strings resolve to the same pathway.
        if pred is not None and goal is not None and pred.ramp_id == goal.ramp_id:
            return MatchResult(tier=MatchTier.EXACT, evidence="same ramp_id", jaccard=1.0, containment=1.0)

        if pred is None or goal is None:
            return MatchResult(tier=MatchTier.MISS, evidence="unresolved")

        a, b = pred.metabolites, goal.metabolites
        inter = a & b
        if not a or not b:
            return MatchResult(tier=MatchTier.MISS, evidence="empty metabolite set")

        jaccard = len(inter) / len(a | b)
        cont_a = len(inter) / len(a)  # fraction of pred contained in gold
        cont_b = len(inter) / len(b)  # fraction of gold contained in pred
        max_cont = max(cont_a, cont_b)

        # EXACT by metabolite identity: same pathway under different source names.
        if min(cont_a, cont_b) >= self.tau_exact:
            return MatchResult(
                tier=MatchTier.EXACT,
                evidence=f"both-way containment {cont_a:.2f}/{cont_b:.2f} >= {self.tau_exact}",
                jaccard=jaccard,
                containment=max_cont,
            )

        # PARENT_CHILD: one pathway's metabolites are largely a subset of the other's.
        if max_cont >= self.tau_containment:
            return MatchResult(
                tier=MatchTier.PARENT_CHILD,
                evidence=f"containment {max_cont:.2f} >= {self.tau_containment}",
                jaccard=jaccard,
                containment=max_cont,
            )

        # ADJACENT: pathways linked by shared SPECIFIC (non-hub) metabolites — e.g.
        # propanoate <-> BCAA degradation via methylmalonate. Hub metabolites
        # (fumarate, glutamate, ...) are excluded by resolver.discriminative().
        shared_specific = {m for m in inter if self._resolver.discriminative(m)}
        if len(shared_specific) >= self.k_specific:
            return MatchResult(
                tier=MatchTier.ADJACENT,
                evidence=f"{len(shared_specific)} shared specific metabolites: {sorted(shared_specific)}",
                jaccard=jaccard,
                containment=max_cont,
            )

        return MatchResult(tier=MatchTier.MISS, evidence=f"jaccard={jaccard:.2f} cont={max_cont:.2f}",
                           jaccard=jaccard, containment=max_cont)


# ---------------------------------------------------------------------------
# RaMP-backed resolver (integration; requires ramp.sqlite + gold registry)
# ---------------------------------------------------------------------------

_KEGG_ID_RE = re.compile(r"\b(map\d{5}|hsa\d{5}|ko\d{5})\b", re.IGNORECASE)
_EXCLUDE_DEFAULT = ("diseas", "disorder", "biomarker", "cancer", "senescence",
                    "resistance", "inhibitor", "regulat", "maturation")


def normalize_pathway_name(name: str) -> str:
    """lowercase, drop parentheticals, non-alnum -> space, collapse whitespace."""
    if not name:
        return ""
    s = name.lower()
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


class RampResolver:
    """Resolves a pathway name/KEGG-id to a metabolite set backed by RaMP-DB.

    Gold pathways resolve through the curated registry (union across sources).
    Predicted pathways resolve by KEGG id (direct) or normalized-name match.
    """

    def __init__(
        self,
        db_path: str,
        registry_path: str,
        discriminative_max_pathways: int = 5,
        exclude_substrings: tuple[str, ...] = _EXCLUDE_DEFAULT,
    ):
        self._conn = sqlite3.connect(db_path)
        self._disc_max = discriminative_max_pathways
        self._exclude = exclude_substrings
        registry = json.loads(Path(registry_path).read_text())
        self._registry = {k: v for k, v in registry.items() if not k.startswith("_")}
        self._pathway_count: dict[str, int] = {}
        self._name_index: dict[str, list[str]] = {}
        self._source_index: dict[str, str] = {}
        # Map every registry member pathwayRampId -> its gold name, so a predicted
        # pathway that resolves onto a gold's member snaps to the gold's full set.
        self._prid_to_gold: dict[str, str] = {}
        for gold, entry in self._registry.items():
            for prid in entry.get("ramp_pathway_ids", []):
                self._prid_to_gold[prid] = gold
        self._build_indexes()

    def _gold_entry(self, gold: str) -> PathwayEntry:
        entry = self._registry[gold]
        return PathwayEntry(
            ramp_id=f"GOLD::{gold}",
            normalized_name=normalize_pathway_name(gold),
            metabolites=self._metabolites(entry["ramp_pathway_ids"]),
        )

    def _build_indexes(self) -> None:
        cur = self._conn.cursor()
        for prid, typ, sid, name in cur.execute(
            "SELECT pathwayRampId, type, sourceId, pathwayName FROM pathway"
        ):
            if typ == "pfocr":
                continue
            low = (name or "").lower()
            if any(b in low for b in self._exclude):
                continue
            self._source_index.setdefault(sid, prid)
            self._name_index.setdefault(normalize_pathway_name(name), []).append(prid)
        for rid, cnt in cur.execute(
            "SELECT a.rampId, count(DISTINCT a.pathwayRampId) FROM analytehaspathway a "
            "JOIN pathway p ON a.pathwayRampId=p.pathwayRampId "
            "WHERE p.type!='pfocr' AND a.rampId LIKE 'RAMP_C%' GROUP BY a.rampId"
        ):
            self._pathway_count[rid] = cnt

    def _metabolites(self, ramp_pathway_ids: list[str]) -> frozenset[str]:
        s: set[str] = set()
        q = ("SELECT DISTINCT rampId FROM analytehaspathway "
             "WHERE pathwayRampId=? AND rampId LIKE 'RAMP_C%'")
        for prid in ramp_pathway_ids:
            s.update(r[0] for r in self._conn.execute(q, (prid,)))
        return frozenset(s)

    def resolve(self, name_or_id: str) -> PathwayEntry | None:
        if not name_or_id or not name_or_id.strip():
            return None
        raw = name_or_id.strip()

        # Gold registry (exact name).
        if raw in self._registry:
            return self._gold_entry(raw)

        # KEGG id.
        m = _KEGG_ID_RE.search(raw)
        if m and m.group(1) in self._source_index:
            prid = self._source_index[m.group(1)]
            if prid in self._prid_to_gold:  # snap onto gold concept
                return self._gold_entry(self._prid_to_gold[prid])
            return PathwayEntry(prid, normalize_pathway_name(raw), self._metabolites([prid]))

        # Normalized-name match: exact, else substring (either direction).
        norm = normalize_pathway_name(raw)
        if not norm:
            return None
        ids = self._name_index.get(norm)
        if not ids:
            hits: list[str] = []
            for key, key_ids in self._name_index.items():
                if norm in key or key in norm:
                    hits.extend(key_ids)
            ids = hits
        if not ids:
            return None
        # Snap to a gold concept if the matched pathways belong to one.
        golds = {self._prid_to_gold[p] for p in ids if p in self._prid_to_gold}
        if len(golds) == 1:
            return self._gold_entry(next(iter(golds)))
        return PathwayEntry(f"NAME::{norm}", norm, self._metabolites(ids))

    def discriminative(self, metabolite_id: str) -> bool:
        return self._pathway_count.get(metabolite_id, 10 ** 9) <= self._disc_max


def build_matcher(db_path: str, registry_path: str) -> PathwayMatcher:
    """Construct a RaMP-backed matcher with thresholds read from the registry."""
    meta = json.loads(Path(registry_path).read_text()).get("_meta", {})
    t = meta.get("thresholds", {})
    resolver = RampResolver(
        db_path,
        registry_path,
        discriminative_max_pathways=int(t.get("discriminative_max_pathways", 5)),
    )
    return PathwayMatcher(
        resolver,
        tau_exact=float(t.get("tau_exact", 0.9)),
        tau_containment=float(t.get("tau_containment", 0.7)),
        k_specific=int(t.get("k_specific", 2)),
    )

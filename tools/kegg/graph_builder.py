"""KGML parser + KEGG reaction graph builder (sqlite).

Reads the directory of cached KGML files (one per ``hsa<NNNNN>``
pathway map) produced by ``scripts/kegg/download_kgml.py`` and emits a
single sqlite database that Layer 6d queries at runtime for compound-
level (and pathway-level fallback) reachability.

Schema
------

    compounds(compound_id TEXT PRIMARY KEY,
              name        TEXT)              -- only when known (curated pool)

    reactions(reaction_id  TEXT PRIMARY KEY,
              pathway_id   TEXT NOT NULL,    -- hsa<NNNNN>; one row per
                                              -- (reaction, pathway) pair, so
                                              -- a reaction in N pathways gets
                                              -- N rows
              reversible   INTEGER NOT NULL, -- 0 / 1
              ec           TEXT)             -- nullable; KGML doesn't carry
                                              -- EC directly so this is empty
                                              -- in v0

    reaction_substrates(reaction_id TEXT,
                        compound_id TEXT,
                        PRIMARY KEY (reaction_id, compound_id))

    reaction_products(reaction_id TEXT,
                      compound_id TEXT,
                      PRIMARY KEY (reaction_id, compound_id))

    pathway_compounds(pathway_id TEXT,
                      compound_id TEXT,
                      PRIMARY KEY (pathway_id, compound_id))

    compound_aliases(alias       TEXT,        -- normalised lookup key
                                                -- (lowercase + space-collapsed)
                     compound_id TEXT,
                     source      TEXT,        -- 'name' / 'inchikey14' /
                                                -- 'hmdb' / 'kegg'
                     PRIMARY KEY (alias, compound_id))

Reaction direction handling
---------------------------

Per KGML's ``<reaction type="...">`` attribute:

* ``irreversible`` → only substrate → product edges
* ``reversible``   → both substrate → product AND product → substrate

The graph builder writes both reaction_substrates / reaction_products
verbatim from KGML (so the audit trail is preserved), and the
reachability layer adds the reverse edges at query time when reading
``reactions.reversible``. This lets us change the reversibility
semantics later without rebuilding the DB.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class KeggReaction:
    reaction_id: str            # canonical: rn:R<NNNNN>
    pathway_id: str             # hsa<NNNNN>
    substrate_compounds: tuple[str, ...]
    product_compounds: tuple[str, ...]
    reversible: bool
    enzyme_ec: tuple[str, ...] = ()


@dataclass(frozen=True)
class KeggCompound:
    compound_id: str            # canonical: cpd:C<NNNNN>
    name: str | None = None
    pathway_ids: tuple[str, ...] = ()


# ---- KGML parsing ---------------------------------------------------------


def _normalise_pathway_id(name_attr: str) -> str:
    """``path:hsa00270`` / ``hsa00270`` → ``hsa00270``."""
    s = name_attr.strip()
    if s.startswith("path:"):
        s = s[5:]
    return s


def _split_multi_id(name_attr: str) -> list[str]:
    """KGML reaction's ``name`` may carry multiple IDs separated by
    whitespace, e.g. ``name="rn:R00179 rn:R00188"``. Same for orthologs.
    """
    return [tok.strip() for tok in name_attr.split() if tok.strip()]


def parse_kgml(kgml_path: Path) -> tuple[list[KeggCompound], list[KeggReaction], str]:
    """Parse one KGML file. Returns ``(compounds, reactions, pathway_id)``.

    Compound entries lacking ``cpd:C<NNNNN>`` IDs (e.g. ``glycan``,
    ``drug``, ``map``-link entries) are silently skipped — Layer 6d
    only operates on metabolite compounds. Reactions whose substrate or
    product list is empty after filtering are also skipped.
    """
    tree = ET.parse(kgml_path)
    root = tree.getroot()
    pathway_id = _normalise_pathway_id(root.get("name", ""))
    compounds: dict[str, KeggCompound] = {}
    reactions: list[KeggReaction] = []

    # 1. Compound entries.
    for entry in root.iter("entry"):
        if entry.get("type") != "compound":
            continue
        names = _split_multi_id(entry.get("name", ""))
        for n in names:
            if not n.startswith("cpd:"):
                continue
            if n not in compounds:
                compounds[n] = KeggCompound(
                    compound_id=n,
                    name=None,
                    pathway_ids=(pathway_id,),
                )

    # 2. Reactions.
    for rxn in root.iter("reaction"):
        rxn_ids = _split_multi_id(rxn.get("name", ""))
        rxn_ids = [r for r in rxn_ids if r.startswith("rn:")]
        if not rxn_ids:
            continue
        rxn_type = rxn.get("type", "irreversible").lower()
        reversible = rxn_type == "reversible"
        substrates = tuple(
            s.get("name", "") for s in rxn.findall("substrate")
            if s.get("name", "").startswith("cpd:")
        )
        products = tuple(
            p.get("name", "") for p in rxn.findall("product")
            if p.get("name", "").startswith("cpd:")
        )
        if not substrates or not products:
            continue
        for rid in rxn_ids:
            reactions.append(KeggReaction(
                reaction_id=rid,
                pathway_id=pathway_id,
                substrate_compounds=substrates,
                product_compounds=products,
                reversible=reversible,
            ))

    return list(compounds.values()), reactions, pathway_id


# ---- alias loader ---------------------------------------------------------


def _normalise_alias(s: str) -> str:
    """Lowercase + collapse whitespace + strip surrounding punctuation.

    Used both at index time and at lookup time so a noisy
    ``"  L-Methionine  "`` resolves the same as ``"l-methionine"``.
    """
    return " ".join(str(s).strip().split()).lower()


def _name_variants(canonical: str) -> list[str]:
    """Generate deterministic spelling variants the LLM is likely to
    use even when the curated pool stores only one canonical form.

    Index-time expansion is preferable to query-time guessing because
    the alias table is the single source of truth — a downstream
    layer that prints "could not resolve" doesn't have to know about
    these heuristics.

    Variants:
      L-/D- prefix add or strip:    "L-Methionine"  ↔ "Methionine"
                                    "Methionine"    ↔ "L-Methionine"
      ic acid ↔ ate suffix:         "Pyruvic acid"  ↔ "Pyruvate"
                                    "Pyruvate"      ↔ "Pyruvic acid"

    Caller deduplicates via the (alias, compound_id) PK on insert.
    """
    out: list[str] = [canonical]
    norm = canonical.lower().strip()

    # L-/D- prefix toggle
    m_strip = re.match(r"^[ld][\-\s]+(.+)", norm)
    if m_strip:
        out.append(m_strip.group(1))
    else:
        out.append(f"l-{norm}")
        out.append(f"d-{norm}")

    # "ic acid" ↔ "ate"
    if norm.endswith("ic acid"):
        out.append(norm[: -len("ic acid")] + "ate")
    elif norm.endswith("ate"):
        out.append(norm[: -len("ate")] + "ic acid")

    return out


def load_curated_pool_aliases(curated_path: Path) -> list[tuple[str, str, str]]:
    """Yield (alias, kegg_compound_id, source) rows from the curated
    HMDB-mammalian pool. Source is ``'name'`` / ``'inchikey14'`` /
    ``'hmdb'`` / ``'kegg'``.

    We deliberately skip live KEGG ``bget`` lookups (per session-intake
    decision); the curated pool covers all 150 mammalian compounds with
    KEGG IDs.
    """
    rows: list[tuple[str, str, str]] = []
    if not curated_path.is_file():
        return rows
    with curated_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            kegg = r.get("kegg_id")
            if not kegg:
                continue
            if not kegg.startswith("cpd:"):
                # curated pool stores 'C00022' style; canonicalise.
                kegg = "cpd:" + kegg if not kegg.startswith("cpd:") else kegg
            for source, value in (
                ("name", r.get("name")),
                ("inchikey14", r.get("inchikey_first_block")),
                ("hmdb", r.get("hmdb_id")),
                ("kegg", r.get("kegg_id")),
            ):
                if not value:
                    continue
                if source == "name":
                    # Expand to deterministic variants (L-/D-, ic acid /
                    # ate) so the LLM's looser phrasing still resolves.
                    for v in _name_variants(value):
                        rows.append((_normalise_alias(v), kegg, source))
                else:
                    rows.append((_normalise_alias(value), kegg, source))
    # Dedup
    return list({(a, k, s) for a, k, s in rows})


# ---- DB build -------------------------------------------------------------


_DDL = """
CREATE TABLE IF NOT EXISTS compounds (
    compound_id TEXT PRIMARY KEY,
    name        TEXT
);
CREATE TABLE IF NOT EXISTS reactions (
    reaction_id TEXT NOT NULL,
    pathway_id  TEXT NOT NULL,
    reversible  INTEGER NOT NULL,
    ec          TEXT,
    PRIMARY KEY (reaction_id, pathway_id)
);
CREATE TABLE IF NOT EXISTS reaction_substrates (
    reaction_id TEXT NOT NULL,
    compound_id TEXT NOT NULL,
    PRIMARY KEY (reaction_id, compound_id)
);
CREATE TABLE IF NOT EXISTS reaction_products (
    reaction_id TEXT NOT NULL,
    compound_id TEXT NOT NULL,
    PRIMARY KEY (reaction_id, compound_id)
);
CREATE TABLE IF NOT EXISTS pathway_compounds (
    pathway_id  TEXT NOT NULL,
    compound_id TEXT NOT NULL,
    PRIMARY KEY (pathway_id, compound_id)
);
CREATE TABLE IF NOT EXISTS compound_aliases (
    alias       TEXT NOT NULL,
    compound_id TEXT NOT NULL,
    source      TEXT NOT NULL,
    PRIMARY KEY (alias, compound_id)
);
CREATE INDEX IF NOT EXISTS idx_reaction_substrates_compound
    ON reaction_substrates(compound_id);
CREATE INDEX IF NOT EXISTS idx_reaction_products_compound
    ON reaction_products(compound_id);
CREATE INDEX IF NOT EXISTS idx_pathway_compounds_compound
    ON pathway_compounds(compound_id);
CREATE INDEX IF NOT EXISTS idx_compound_aliases_alias
    ON compound_aliases(alias);
CREATE INDEX IF NOT EXISTS idx_reactions_pathway
    ON reactions(pathway_id);
"""


def build_reaction_graph(
    kgml_dir: Path,
    output_db: Path,
    *,
    curated_path: Path | None = None,
) -> dict:
    """Parse all KGML files in ``kgml_dir`` and write a sqlite reaction
    graph to ``output_db``. Idempotent — overwrites if the file
    already exists.

    Returns a summary dict with counts.
    """
    kgml_dir = Path(kgml_dir)
    output_db = Path(output_db)
    output_db.parent.mkdir(parents=True, exist_ok=True)

    if output_db.exists():
        output_db.unlink()  # full rebuild — small DB, no incremental needed

    conn = sqlite3.connect(output_db)
    try:
        conn.executescript(_DDL)

        all_compounds: dict[str, set[str]] = {}  # cpd_id -> {pathway_id}
        n_reactions = 0
        n_pathways = 0
        kgml_files = sorted(kgml_dir.glob("hsa*.xml"))
        for kgml in kgml_files:
            try:
                cpds, rxns, pid = parse_kgml(kgml)
            except ET.ParseError as e:
                logger.warning("skipping malformed KGML %s: %s", kgml.name, e)
                continue
            n_pathways += 1
            for c in cpds:
                all_compounds.setdefault(c.compound_id, set()).add(pid)
            # reactions
            for r in rxns:
                conn.execute(
                    "INSERT OR IGNORE INTO reactions(reaction_id, pathway_id, "
                    "reversible, ec) VALUES (?, ?, ?, ?)",
                    (r.reaction_id, r.pathway_id, int(r.reversible), None),
                )
                for sub in r.substrate_compounds:
                    conn.execute(
                        "INSERT OR IGNORE INTO reaction_substrates(reaction_id, "
                        "compound_id) VALUES (?, ?)",
                        (r.reaction_id, sub),
                    )
                for prod in r.product_compounds:
                    conn.execute(
                        "INSERT OR IGNORE INTO reaction_products(reaction_id, "
                        "compound_id) VALUES (?, ?)",
                        (r.reaction_id, prod),
                    )
                n_reactions += 1

        # Compounds + pathway membership
        for cid, pids in all_compounds.items():
            conn.execute(
                "INSERT OR IGNORE INTO compounds(compound_id, name) VALUES (?, NULL)",
                (cid,),
            )
            for pid in pids:
                conn.execute(
                    "INSERT OR IGNORE INTO pathway_compounds(pathway_id, "
                    "compound_id) VALUES (?, ?)",
                    (pid, cid),
                )

        # Aliases — populate names from curated pool, plus inchikey14/hmdb/kegg
        n_aliases = 0
        if curated_path is not None:
            alias_rows = load_curated_pool_aliases(curated_path)
            for alias, kegg_id, source in alias_rows:
                conn.execute(
                    "INSERT OR IGNORE INTO compound_aliases(alias, compound_id, "
                    "source) VALUES (?, ?, ?)",
                    (alias, kegg_id, source),
                )
                n_aliases += 1

            # Back-fill compounds.name from the curated pool's canonical
            # name field (NOT from alias variants — "l-test compound"
            # etc. are searchable but should not become the displayed
            # name).
            with curated_path.open() as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    r = json.loads(line)
                    name = r.get("name")
                    kegg = r.get("kegg_id")
                    if not name or not kegg:
                        continue
                    if not kegg.startswith("cpd:"):
                        kegg = f"cpd:{kegg}"
                    conn.execute(
                        "UPDATE compounds SET name = COALESCE(name, ?) "
                        "WHERE compound_id = ?",
                        (_normalise_alias(name), kegg),
                    )

        conn.commit()

        # Counts
        n_compounds = conn.execute("SELECT COUNT(*) FROM compounds").fetchone()[0]
        n_unique_reactions = conn.execute(
            "SELECT COUNT(DISTINCT reaction_id) FROM reactions"
        ).fetchone()[0]
        n_alias_rows = conn.execute("SELECT COUNT(*) FROM compound_aliases").fetchone()[0]

        summary = {
            "n_kgml_files": len(kgml_files),
            "n_pathways": n_pathways,
            "n_compounds": n_compounds,
            "n_unique_reactions": n_unique_reactions,
            "n_reaction_pathway_rows": n_reactions,
            "n_compound_aliases": n_alias_rows,
            "output_db": str(output_db),
        }
        logger.info("built reaction graph: %s", summary)
        return summary
    finally:
        conn.close()


# ---- CLI ------------------------------------------------------------------


def _main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--kgml-dir", default="data/kegg/kgml")
    p.add_argument("--output", default="data/kegg/reaction_graph.sqlite")
    p.add_argument(
        "--curated",
        default="data/benchmark/sub6/curated_hmdb_mammalian.jsonl",
    )
    args = p.parse_args(argv)
    logging.basicConfig(level="INFO", format="%(levelname)s %(name)s: %(message)s")
    summary = build_reaction_graph(
        kgml_dir=Path(args.kgml_dir),
        output_db=Path(args.output),
        curated_path=Path(args.curated),
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())

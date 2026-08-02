#!/usr/bin/env python3
"""
populate_gene_paralogs.py — populate dim_gene_paralog (D5b prerequisite).

D5b's buffering-candidate flag (design/gene_relatedness_design.md §6.6,
criterion (b)) needs "paralogs/homologs per an external homology source." That
data already exists, unused for this purpose, in the STRING alias files this
repo's prototype KB build already reads (prototype/script/build_kb_string.py,
$STRING_DIR): a protein's `Ensembl_EntrezGene_Paralog` alias row points at its
paralog's Entrez GeneID directly. build_kb_string.py discards those rows on
purpose (wrong join key for STRING's own protein-protein edges) — this script
is the first thing that keeps them.

One pass over `{taxid}.protein.aliases.v12.0.txt.gz`, same file/format
build_kb_string.py reads, collecting two mappings per protein:
  - its OWN Entrez GeneID  (source in Ensembl_EntrezGene / Ensembl_HGNC_entrez_id)
  - its PARALOG'S Entrez GeneID(s)  (source == Ensembl_EntrezGene_Paralog)
Both sides are resolved against this version's `gene.identifier_id` (BioGRID's
IDENTIFIER_ID column IS the Entrez GeneID — see gene.identifier_id in
scripts/staging_loader.py); pairs where either side isn't a gene loaded in this
version are dropped (paralogy is Entrez-space-wide, the warehouse is not).

Writes directly to Postgres (dim_gene_paralog) — no SQLite kb.db dependency,
unlike the prototype build_kb_* scripts this borrows the file format from.

Usage (via slurm/reticle-paralogs.sh):
  python3 populate_gene_paralogs.py --version 7 --string-dir /path/to/string
  python3 populate_gene_paralogs.py --version 7 --string-dir /path/to/string --dry-run
"""

import argparse
import gzip
import logging
import os
import sys

import psycopg2
import psycopg2.extras

from config import Config

logger = logging.getLogger("populate_gene_paralogs")

# only these two sources are "this ENSP == this Entrez GeneID"; matches
# prototype/script/build_kb_string.py's ENTREZ_SOURCES exactly (do not add
# Ensembl_EntrezGene_Paralog here — that source means the OPPOSITE: alias
# points at a *different* gene, the paralog).
ENTREZ_SOURCES = {"Ensembl_EntrezGene", "Ensembl_HGNC_entrez_id"}
PARALOG_SOURCE = "Ensembl_EntrezGene_Paralog"

ALIASES_PATTERN = "{taxid}.protein.aliases.v12.0.txt.gz"

# organism (data_load_version) -> NCBI taxonomy id, for the STRING filename
_TAXID = {"homo_sapiens": "9606", "mus_musculus": "10090"}


def parse_aliases(path):
    """Return (self_map, paralog_map): ENSP -> own Entrez id string,
    ENSP -> set of paralog Entrez id strings."""
    self_map = {}
    paralog_map = {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        f.readline()   # header
        for line in f:
            c = line.rstrip("\n").split("\t")
            if len(c) < 3:
                continue
            ensp, alias, source = c[0], c[1], c[2]
            if not alias.isdigit():
                continue
            if source in ENTREZ_SOURCES:
                self_map.setdefault(ensp, alias)   # first mapping wins (sources agree)
            elif source == PARALOG_SOURCE:
                paralog_map.setdefault(ensp, set()).add(alias)
    return self_map, paralog_map


def resolve_pairs(self_map, paralog_map, entrez_to_gene_id):
    """ENSP-keyed self/paralog Entrez maps -> deduped set of (gene_id_a<gene_id_b)
    pairs, both sides resolved to genes present in this version."""
    pairs = set()
    unresolved = 0
    for ensp, paralogs in paralog_map.items():
        self_entrez = self_map.get(ensp)
        if self_entrez is None:
            continue
        gene_a = entrez_to_gene_id.get(self_entrez)
        if gene_a is None:
            continue
        for para_entrez in paralogs:
            if para_entrez == self_entrez:
                continue
            gene_b = entrez_to_gene_id.get(para_entrez)
            if gene_b is None:
                unresolved += 1
                continue
            pairs.add((gene_a, gene_b) if gene_a < gene_b else (gene_b, gene_a))
    logger.info(f"{len(pairs):,} distinct paralog pairs resolved to loaded genes "
                f"({unresolved:,} paralog references outside this version's gene set)")
    return pairs


class GeneParalogPopulator:
    def __init__(self, version_id, string_dir, dry_run=False):
        self.version_id = version_id
        self.string_dir = string_dir
        self.dry_run = dry_run
        self.conn = None

    def connect(self):
        params = Config.get_psycopg2_params()
        params["sslmode"] = "require"
        self.conn = psycopg2.connect(**params)
        self.conn.autocommit = False
        cur = self.conn.cursor()
        cur.execute("SET statement_timeout = 0")
        cur.execute("SET work_mem = '128MB'")
        self.conn.commit()

    def resolve(self):
        cur = self.conn.cursor()
        cur.execute("SELECT organism FROM data_load_version WHERE version_id=%s", (self.version_id,))
        row = cur.fetchone()
        if not row:
            raise SystemExit(f"version_id {self.version_id} not found")
        self.organism = row[0]
        self.taxid = _TAXID.get(self.organism)
        if not self.taxid:
            raise SystemExit(f"No taxid mapping for organism '{self.organism}' (add to _TAXID)")
        cur.execute("SELECT run_id FROM etl_pipeline_run WHERE data_load_version_id=%s "
                    "ORDER BY run_id DESC LIMIT 1", (self.version_id,))
        r = cur.fetchone()
        self.run_id = r[0] if r else None
        logger.info(f"version={self.version_id} organism={self.organism} taxid={self.taxid} run_id={self.run_id}")

    def run(self):
        self.connect()
        self.resolve()

        path = os.path.join(self.string_dir, ALIASES_PATTERN.format(taxid=self.taxid))
        if not os.path.exists(path):
            raise SystemExit(f"STRING aliases file not found: {path} (set --string-dir / $STRING_DIR)")

        cur = self.conn.cursor()
        cur.execute("SELECT identifier_id, gene_id FROM gene WHERE version_id=%s", (self.version_id,))
        entrez_to_gene_id = {iid: gid for iid, gid in cur.fetchall() if iid and iid.isdigit()}
        logger.info(f"{len(entrez_to_gene_id):,} genes with a numeric Entrez identifier_id in this version")

        self_map, paralog_map = parse_aliases(path)
        logger.info(f"Parsed {path}: {len(self_map):,} self ENSP->Entrez, "
                    f"{len(paralog_map):,} ENSP with >=1 paralog alias")
        pairs = resolve_pairs(self_map, paralog_map, entrez_to_gene_id)

        if self.dry_run:
            print(f"[dry-run] would upsert {len(pairs):,} dim_gene_paralog rows (version {self.version_id}).")
            self.conn.close()
            return True

        if not pairs:
            print("No paralog pairs resolved — nothing to store.")
            self.conn.close()
            return True

        payload = [(self.version_id, self.run_id, a, b, self.organism) for a, b in pairs]
        psycopg2.extras.execute_values(cur, """
            INSERT INTO dim_gene_paralog (version_id, run_id, gene_id_a, gene_id_b, organism)
            VALUES %s
            ON CONFLICT (version_id, gene_id_a, gene_id_b) DO UPDATE SET is_current = TRUE
        """, payload, page_size=10000)
        self.conn.commit()
        logger.info(f"Upserted {len(pairs):,} dim_gene_paralog rows")
        print(f"Wrote {len(pairs):,} dim_gene_paralog rows (version {self.version_id}).")
        self.conn.close()
        return True


def main():
    ap = argparse.ArgumentParser(description="Populate dim_gene_paralog from STRING alias files (D5b prerequisite)")
    ap.add_argument("--version", type=int, required=True)
    ap.add_argument("--string-dir", default=os.getenv("STRING_DIR"),
                    help="dir holding {taxid}.protein.aliases.v12.0.txt.gz (default: $STRING_DIR)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args()
    if not args.string_dir:
        raise SystemExit("--string-dir (or $STRING_DIR) is required")

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO),
                        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    ok = GeneParalogPopulator(args.version, args.string_dir, dry_run=args.dry_run).run()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

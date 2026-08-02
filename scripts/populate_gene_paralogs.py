#!/usr/bin/env python3
"""
populate_gene_paralogs.py — populate dim_gene_paralog (D5b prerequisite).

D5b's buffering-candidate flag (design/gene_relatedness_design.md §6.6,
criterion (b)) needs "paralogs/homologs per an external homology source."

REVISION NOTE: an earlier version of this script parsed STRING's protein-alias
files' `Ensembl_EntrezGene_Paralog` source rows, on the assumption those held a
paralog's Entrez GeneID directly. Verified against the real STRING v12.0 file:
they don't — the alias column holds a sparse, oddly-suffixed symbol string
(e.g. "PDE11A-2"), and there are only 22 such rows in the entire human
proteome. Wrong premise, not a parsing bug — replaced entirely.

Correct source: Ensembl Compara's own per-organism homology export
(`Compara.<release>.protein_default.homologies.tsv.gz`, under
`$COMPARA_DIR/<organism>/`, mirroring ftp.ensembl.org's own directory layout —
see ftp.ensembl.org/pub/release-<N>/tsv/ensembl-compara/homologies/<organism>/).
One row per (gene, homologous gene) pair with an explicit `homology_type`;
same-species pairs typed `within_species_paralog` (recent duplication) or
`other_paralog` (older duplication) are kept — `gene_split` (an annotation
artifact: one ancestral gene modeled as two separate gene records, not real
biology) is excluded. Both sides are Ensembl gene IDs (ENSG.../ENSMUSG...),
resolved to Entrez GeneID via NCBI's `gene2ensembl.gz` (the same file
prototype/script/build_kb_identifiers.py already uses for this exact
cross-reference, under `$NCBI_DIR`), then to this version's internal gene_id
via `gene.identifier_id` (BioGRID's IDENTIFIER_ID column IS the Entrez GeneID
— see scripts/staging_loader.py). Human + mouse only (this warehouse's only
two organisms).

Writes directly to Postgres (dim_gene_paralog) — no SQLite kb.db dependency.

Usage (via slurm/reticle-paralogs.sh):
  python3 populate_gene_paralogs.py --version 7 --compara-dir /path/to/compara --ncbi-dir /path/to/ncbi
  python3 populate_gene_paralogs.py --version 7 --compara-dir ... --ncbi-dir ... --dry-run
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

COMPARA_RELEASE = "114"
HOMOLOGY_FILE_PATTERN = "Compara.{release}.protein_default.homologies.tsv.gz"
# within_species_paralog = recent duplication; other_paralog = older duplication.
# gene_split is deliberately excluded (annotation artifact, not real paralogy).
PARALOG_TYPES = {"within_species_paralog", "other_paralog"}

# organism (data_load_version) -> NCBI taxonomy id (gene2ensembl.gz tax_id column)
_TAXID = {"homo_sapiens": "9606", "mus_musculus": "10090"}


def load_gene2ensembl(path, taxid):
    """tax_id-filtered ENSG -> Entrez GeneID, from NCBI's gene2ensembl.gz.
    Single streaming pass; the file covers every organism NCBI tracks
    (~280MB), so this only keeps rows for the requested organism."""
    ensg_to_entrez = {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        f.readline()   # header
        for line in f:
            c = line.rstrip("\n").split("\t")
            if len(c) < 3 or c[0] != taxid:
                continue
            gene_id, ensg = c[1], c[2]
            if ensg and ensg != "-":
                ensg_to_entrez.setdefault(ensg, gene_id)   # first mapping wins
    return ensg_to_entrez


def load_paralog_pairs(path):
    """Same-species (gene_stable_id, homology_gene_stable_id) ENSG pairs from
    one organism's Compara homologies export, restricted to PARALOG_TYPES.
    Column positions are read from the file's own header (not hardcoded) so a
    column reorder in a future Compara release can't silently misalign us."""
    pairs = set()
    with gzip.open(path, "rt", encoding="utf-8") as f:
        header = f.readline().rstrip("\n").split("\t")
        idx = {name: i for i, name in enumerate(header)}
        required = ("species", "homology_type", "homology_species", "gene_stable_id", "homology_gene_stable_id")
        missing = [r for r in required if r not in idx]
        if missing:
            raise SystemExit(f"{path}: missing expected column(s) {missing} — Compara TSV format may have changed")
        i_species, i_type, i_hspecies = idx["species"], idx["homology_type"], idx["homology_species"]
        i_gene, i_hgene = idx["gene_stable_id"], idx["homology_gene_stable_id"]
        for line in f:
            c = line.rstrip("\n").split("\t")
            if len(c) <= max(i_species, i_type, i_hspecies, i_gene, i_hgene):
                continue
            if c[i_type] not in PARALOG_TYPES or c[i_species] != c[i_hspecies]:
                continue
            a, b = c[i_gene], c[i_hgene]
            if a != b:
                pairs.add((a, b) if a < b else (b, a))
    return pairs


class GeneParalogPopulator:
    def __init__(self, version_id, compara_dir, ncbi_dir, dry_run=False):
        self.version_id = version_id
        self.compara_dir = compara_dir
        self.ncbi_dir = ncbi_dir
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

        homology_path = os.path.join(self.compara_dir, self.organism,
                                      HOMOLOGY_FILE_PATTERN.format(release=COMPARA_RELEASE))
        gene2ensembl_path = os.path.join(self.ncbi_dir, "gene2ensembl.gz")
        for p in (homology_path, gene2ensembl_path):
            if not os.path.exists(p):
                raise SystemExit(f"Required file not found: {p} (set --compara-dir/$COMPARA_DIR "
                                 f"and --ncbi-dir/$NCBI_DIR)")

        cur = self.conn.cursor()
        cur.execute("SELECT identifier_id, gene_id FROM gene WHERE version_id=%s", (self.version_id,))
        entrez_to_gene_id = {iid: gid for iid, gid in cur.fetchall() if iid and iid.isdigit()}
        logger.info(f"{len(entrez_to_gene_id):,} genes with a numeric Entrez identifier_id in this version")

        ensg_to_entrez = load_gene2ensembl(gene2ensembl_path, self.taxid)
        logger.info(f"{len(ensg_to_entrez):,} ENSG->Entrez mappings for {self.organism} (tax_id {self.taxid})")

        ensg_pairs = load_paralog_pairs(homology_path)
        logger.info(f"{len(ensg_pairs):,} same-species paralog ENSG pairs "
                    f"({'+'.join(sorted(PARALOG_TYPES))}) from {os.path.basename(homology_path)}")

        pairs = set()
        unresolved = 0
        for ensg_a, ensg_b in ensg_pairs:
            entrez_a, entrez_b = ensg_to_entrez.get(ensg_a), ensg_to_entrez.get(ensg_b)
            if entrez_a is None or entrez_b is None:
                unresolved += 1
                continue
            gene_a, gene_b = entrez_to_gene_id.get(entrez_a), entrez_to_gene_id.get(entrez_b)
            if gene_a is None or gene_b is None or gene_a == gene_b:
                continue
            pairs.add((gene_a, gene_b) if gene_a < gene_b else (gene_b, gene_a))
        logger.info(f"{len(pairs):,} distinct paralog pairs resolved to loaded genes "
                    f"({unresolved:,} ENSG pairs missing a gene2ensembl mapping)")

        if self.dry_run:
            print(f"[dry-run] would upsert {len(pairs):,} dim_gene_paralog rows (version {self.version_id}).")
            self.conn.close()
            return True

        if not pairs:
            print("No paralog pairs resolved — nothing to store.")
            self.conn.close()
            return True

        payload = [(self.version_id, self.run_id, a, b, self.organism, "ensembl_compara_paralog")
                   for a, b in pairs]
        psycopg2.extras.execute_values(cur, """
            INSERT INTO dim_gene_paralog (version_id, run_id, gene_id_a, gene_id_b, organism, source)
            VALUES %s
            ON CONFLICT (version_id, gene_id_a, gene_id_b) DO UPDATE SET
                source = EXCLUDED.source, is_current = TRUE
        """, payload, page_size=10000)
        self.conn.commit()
        logger.info(f"Upserted {len(pairs):,} dim_gene_paralog rows")
        print(f"Wrote {len(pairs):,} dim_gene_paralog rows (version {self.version_id}).")
        self.conn.close()
        return True


def main():
    ap = argparse.ArgumentParser(description="Populate dim_gene_paralog from Ensembl Compara (D5b prerequisite)")
    ap.add_argument("--version", type=int, required=True)
    ap.add_argument("--compara-dir", default=os.getenv("COMPARA_DIR"),
                    help="dir holding <organism>/Compara.<release>.protein_default.homologies.tsv.gz "
                         "(default: $COMPARA_DIR)")
    ap.add_argument("--ncbi-dir", default=os.getenv("NCBI_DIR"),
                    help="dir holding gene2ensembl.gz (default: $NCBI_DIR)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args()
    if not args.compara_dir:
        raise SystemExit("--compara-dir (or $COMPARA_DIR) is required")
    if not args.ncbi_dir:
        raise SystemExit("--ncbi-dir (or $NCBI_DIR) is required")

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO),
                        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    ok = GeneParalogPopulator(args.version, args.compara_dir, args.ncbi_dir, dry_run=args.dry_run).run()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

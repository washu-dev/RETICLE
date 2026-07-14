"""
build_kb_gene.py — the gene-wiki KB's identity backbone: kb_gene + kb_gene_alias.
====================================================================================
Every other kb_* table (GO, STRING, DepMap, UniProt, PubMed) joins back to
kb_gene.gene_id (Entrez GeneID). This must run first.

kb_gene         one row per (taxid, GeneID) — symbol, type, description, location.
kb_gene_alias   every string that can resolve to a gene_id: its primary symbol,
                its synonyms, its retired symbols, and its retired GeneIDs
                (from gene_history.gz). This is what lets a user type "p53" or an
                old/retired GeneID and still land on the current TP53 record.

Full rebuild each run (small enough: ~65k genes for human+mouse), tagged with a
snapshot date so a bad run never leaves a half-built table live.

  python3 build_kb_gene.py \
      --ncbi-dir /storage3/fs1/aorvedahl-RETICLE/Active/data/ncbi \
      --out      /storage3/fs1/aorvedahl-RETICLE/Active/data/kb/kb.db \
      --taxids 9606,10090
"""
import argparse
import gzip
import os
import sqlite3
from pathlib import Path

SNAPSHOT = os.environ.get("KB_SNAPSHOT", "2026-07")

SPECIES_FILE = {
    9606: "Homo_sapiens.gene_info.gz",
    10090: "Mus_musculus.gene_info.gz",
}

# gene_info's type_of_gene is dominated (~2/3 of rows) by "biological-region" —
# regulatory elements / enhancers / imprinting-control regions (e.g. "ZRS",
# "H19-ICR"), not genes: no transcript, no protein, nothing for UniProt/GO/
# STRING/DepMap/BioGRID to attach to. Excluded by default so the identity
# table stays to the ~65k rows that are actually genes.
DEFAULT_EXCLUDE_TYPES = {"biological-region"}


def _split(field):
    """NCBI uses '-' as the null placeholder and '|' as a multi-value separator."""
    if not field or field == "-":
        return []
    return [v for v in field.split("|") if v]


def load_gene_info(path, taxid, exclude_types):
    genes, aliases = [], []
    skipped = 0
    with gzip.open(path, "rt") as f:
        header = f.readline()
        for line in f:
            c = line.rstrip("\n").split("\t")
            if len(c) < 16:
                continue
            (tax_id, gene_id, symbol, _locus_tag, synonyms, _dbxrefs, chromosome,
             map_loc, description, type_of_gene, _sym_auth, full_name,
             _nom_status, _other_desig, _mod_date, _feature_type) = c[:16]
            if type_of_gene in exclude_types:
                skipped += 1
                continue
            gene_id = int(gene_id)
            genes.append((gene_id, taxid, symbol,
                          type_of_gene if type_of_gene != "-" else None,
                          chromosome if chromosome != "-" else None,
                          map_loc if map_loc != "-" else None,
                          description if description != "-" else None,
                          full_name if full_name != "-" else None,
                          SNAPSHOT))
            aliases.append((gene_id, taxid, symbol, "symbol"))
            for syn in _split(synonyms):
                aliases.append((gene_id, taxid, syn, "synonym"))
    return genes, aliases, skipped


def load_gene_history(path, taxids, known_gene_ids):
    """Discontinued_GeneID / Discontinued_Symbol -> current GeneID, when NCBI
    recorded a replacement (GeneID column != '-') and that replacement is one
    of the genes we actually loaded."""
    want = set(taxids)
    aliases = []
    with gzip.open(path, "rt") as f:
        f.readline()
        for line in f:
            c = line.rstrip("\n").split("\t")
            if len(c) < 5:
                continue
            tax_id, gene_id, disc_id, disc_symbol, _date = c[:5]
            if tax_id == "-" or int(tax_id) not in want or gene_id == "-":
                continue
            gid = int(gene_id)
            if gid not in known_gene_ids:
                continue                       # replacement isn't in our loaded set — skip rather than dangle
            taxid = int(tax_id)
            aliases.append((gid, taxid, disc_id, "discontinued_geneid"))
            if disc_symbol != "-":
                aliases.append((gid, taxid, disc_symbol, "discontinued_symbol"))
    return aliases


def build_db(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript("""
        DROP TABLE IF EXISTS kb_gene;
        DROP TABLE IF EXISTS kb_gene_alias;
        CREATE TABLE kb_gene (
            gene_id      INTEGER PRIMARY KEY,
            taxid        INTEGER NOT NULL,
            symbol       TEXT NOT NULL,
            type_of_gene TEXT,
            chromosome   TEXT,
            map_location TEXT,
            description  TEXT,
            full_name    TEXT,
            snapshot     TEXT NOT NULL
        );
        CREATE TABLE kb_gene_alias (
            gene_id    INTEGER NOT NULL,
            taxid      INTEGER NOT NULL,
            alias      TEXT NOT NULL,
            alias_type TEXT NOT NULL,
            FOREIGN KEY (gene_id) REFERENCES kb_gene(gene_id)
        );
    """)
    return con


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ncbi-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--taxids", default="9606,10090")
    ap.add_argument("--exclude-types", default="biological-region",
                     help="comma-separated type_of_gene values to drop (empty string to keep everything)")
    args = ap.parse_args()

    taxids = [int(t) for t in args.taxids.split(",") if t.strip()]
    exclude_types = {t.strip() for t in args.exclude_types.split(",") if t.strip()}
    ncbi_dir = Path(args.ncbi_dir)

    con = build_db(args.out)
    all_genes, all_aliases, known_ids = [], [], set()

    for taxid in taxids:
        fname = SPECIES_FILE.get(taxid)
        if not fname:
            print(f"! no gene_info filename mapped for taxid {taxid}, skipping", flush=True)
            continue
        p = ncbi_dir / fname
        if not p.exists():
            print(f"! missing {p}, skipping taxid {taxid}", flush=True)
            continue
        genes, aliases, skipped = load_gene_info(p, taxid, exclude_types)
        print(f"  taxid {taxid}: {len(genes):,} genes, {len(aliases):,} symbol/synonym aliases "
              f"({skipped:,} rows dropped as {exclude_types or '(nothing excluded)'})", flush=True)
        all_genes += genes
        all_aliases += aliases
        known_ids.update(g[0] for g in genes)

    con.executemany(
        "INSERT INTO kb_gene VALUES (?,?,?,?,?,?,?,?,?)", all_genes)
    con.executemany(
        "INSERT INTO kb_gene_alias VALUES (?,?,?,?)", all_aliases)
    con.commit()

    hist_path = ncbi_dir / "gene_history.gz"
    if hist_path.exists():
        hist_aliases = load_gene_history(hist_path, taxids, known_ids)
        con.executemany("INSERT INTO kb_gene_alias VALUES (?,?,?,?)", hist_aliases)
        con.commit()
        print(f"  gene_history: {len(hist_aliases):,} retired-ID/retired-symbol aliases", flush=True)
    else:
        print(f"! missing {hist_path} — retired-ID resolution will be unavailable", flush=True)

    con.execute("CREATE INDEX ix_kga_alias ON kb_gene_alias(alias)")
    con.execute("CREATE INDEX ix_kga_gene ON kb_gene_alias(gene_id)")
    con.commit()

    n_genes = con.execute("SELECT COUNT(*) FROM kb_gene").fetchone()[0]
    n_alias = con.execute("SELECT COUNT(*) FROM kb_gene_alias").fetchone()[0]
    print(f"DONE — kb_gene: {n_genes:,} rows | kb_gene_alias: {n_alias:,} rows -> {args.out}", flush=True)

    # sanity spot-check: resolve a well-known symbol and a well-known synonym
    for probe in ("TP53", "p53"):
        row = con.execute(
            "SELECT g.gene_id, g.symbol, g.taxid FROM kb_gene_alias a "
            "JOIN kb_gene g ON g.gene_id = a.gene_id WHERE a.alias = ? LIMIT 1",
            (probe,)).fetchone()
        print(f"  probe '{probe}' -> {row}", flush=True)

    con.close()


if __name__ == "__main__":
    main()

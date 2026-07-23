"""
build_kb_string.py — STRING functional-interaction edges, keyed by Entrez GeneID.
================================================================================
STRING identifies proteins by Ensembl protein id (ENSP). To join into our KB we
first translate ENSP -> Entrez GeneID using protein.aliases, then load the edges
from protein.links.detailed.

Two subtleties that matter:
  - The ENSP->GeneID mapping must come ONLY from the exact sources
    "Ensembl_EntrezGene" / "Ensembl_HGNC_entrez_id". Other entrez-ish sources
    like "Ensembl_EntrezGene_Paralog" point at a *paralog*, not this gene —
    using them would wire edges to the wrong gene.
  - links.detailed is SPACE-separated (not tab) and lists every edge twice
    (A-B and B-A). We store one canonical row per undirected pair (a<b), which
    also dedups the mirror rows.

Edges are thresholded by combined_score (default 400 = STRING medium confidence;
700 = high) to keep the table meaningful instead of 13.7M mostly-noise edges.
The 7 evidence channels are kept so the UI can say *why* two genes are linked.

Run AFTER build_kb_gene.py.

  python3 build_kb_string.py \
      --string-dir /storage3/fs1/aorvedahl-RETICLE/Active/data/string \
      --db         /storage3/fs1/aorvedahl-RETICLE/Active/data/kb/kb.db \
      --taxids 9606,10090 --min-score 400
"""
import argparse
import gzip
import sqlite3
from pathlib import Path

# only these two sources are "this ENSP == this Entrez GeneID"; anything with
# Paralog / synonym / trans_name points elsewhere and must not be used.
ENTREZ_SOURCES = {"Ensembl_EntrezGene", "Ensembl_HGNC_entrez_id"}

ALIASES = "{taxid}.protein.aliases.v12.0.txt.gz"
LINKS = "{taxid}.protein.links.detailed.v12.0.txt.gz"


def build_tables(con):
    con.executescript("""
        DROP TABLE IF EXISTS kb_string_edge;
        CREATE TABLE kb_string_edge (
            gene_id_a      INTEGER NOT NULL,   -- canonical: gene_id_a < gene_id_b
            gene_id_b      INTEGER NOT NULL,
            combined_score INTEGER NOT NULL,
            neighborhood   INTEGER,
            fusion         INTEGER,
            cooccurence    INTEGER,
            coexpression   INTEGER,
            experimental   INTEGER,
            db_evidence    INTEGER,
            textmining     INTEGER,
            PRIMARY KEY (gene_id_a, gene_id_b)
        );
    """)


def load_ensp2gene(path, known, ensp2gene):
    """ENSP string_protein_id -> Entrez gene_id, from the exact entrez sources."""
    with gzip.open(path, "rt", encoding="utf-8") as f:
        f.readline()
        for line in f:
            c = line.rstrip("\n").split("\t")
            if len(c) < 3 or c[2] not in ENTREZ_SOURCES:
                continue
            alias = c[1]
            if alias.isdigit() and int(alias) in known:
                ensp2gene.setdefault(c[0], int(alias))   # first mapping wins (sources agree)


def load_edges(path, ensp2gene, min_score, con):
    batch = []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        f.readline()
        for line in f:
            p = line.split()                              # SPACE-separated
            if len(p) < 10:
                continue
            score = int(p[9])
            if score < min_score:
                continue
            a = ensp2gene.get(p[0])
            b = ensp2gene.get(p[1])
            if a is None or b is None or a == b:
                continue
            lo, hi = (a, b) if a < b else (b, a)
            batch.append((lo, hi, score,
                          int(p[2]), int(p[3]), int(p[4]), int(p[5]),
                          int(p[6]), int(p[7]), int(p[8])))
            if len(batch) >= 500_000:
                con.executemany(
                    "INSERT OR IGNORE INTO kb_string_edge VALUES (?,?,?,?,?,?,?,?,?,?)", batch)
                con.commit(); batch = []
    if batch:
        con.executemany(
            "INSERT OR IGNORE INTO kb_string_edge VALUES (?,?,?,?,?,?,?,?,?,?)", batch)
        con.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--string-dir", required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--taxids", default="9606,10090")
    ap.add_argument("--min-score", type=int, default=400)
    args = ap.parse_args()

    taxids = [t.strip() for t in args.taxids.split(",") if t.strip()]
    d = Path(args.string_dir)
    con = sqlite3.connect(args.db)
    if not [r for r in con.execute("PRAGMA table_info(kb_gene)")]:
        raise SystemExit("kb_gene not found — run build_kb_gene.py first")
    known = {r[0] for r in con.execute("SELECT gene_id FROM kb_gene")}
    build_tables(con)

    ensp2gene = {}
    for tax in taxids:
        p = d / ALIASES.format(taxid=tax)
        if p.exists():
            load_ensp2gene(p, known, ensp2gene)
    print(f"  ENSP -> GeneID mappings: {len(ensp2gene):,}", flush=True)

    for tax in taxids:
        p = d / LINKS.format(taxid=tax)
        if not p.exists():
            print(f"! missing {p.name}, skipping", flush=True)
            continue
        load_edges(p, ensp2gene, args.min_score, con)
        print(f"  loaded edges from {p.name}", flush=True)
        con.commit()

    con.execute("CREATE INDEX ix_kse_b ON kb_string_edge(gene_id_b)")
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM kb_string_edge").fetchone()[0]
    print(f"DONE — kb_string_edge: {n:,} edges (combined_score >= {args.min_score})", flush=True)

    # spot check: TP53 (7157) top partners by combined_score
    rows = con.execute("""
        SELECT g.symbol, e.combined_score
        FROM kb_string_edge e
        JOIN kb_gene g ON g.gene_id = CASE WHEN e.gene_id_a=7157 THEN e.gene_id_b ELSE e.gene_id_a END
        WHERE e.gene_id_a=7157 OR e.gene_id_b=7157
        ORDER BY e.combined_score DESC LIMIT 6""").fetchall()
    print(f"  TP53 top partners: {rows}", flush=True)
    con.close()


if __name__ == "__main__":
    main()

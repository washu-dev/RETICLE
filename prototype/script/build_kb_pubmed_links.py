"""
build_kb_pubmed_links.py — gene <-> PMID anchor table (kb_gene_pubmed).
======================================================================
From gene2pubmed.gz (columns: tax_id, GeneID, PubMed_ID), filtered to the
taxids and to gene_ids in kb_gene. This stores only the LINK (which papers are
about which gene) — not abstract text. It's the anchor for hybrid retrieval:
gene_id -> its PMIDs, then (later) rank those PMIDs' abstracts by embedding.
Cheap to build now even though the abstract corpus (kb_document) is paused.

Run AFTER build_kb_gene.py.

  python3 build_kb_pubmed_links.py \
      --ncbi-dir /storage3/fs1/aorvedahl-RETICLE/Active/data/ncbi \
      --db       /storage3/fs1/aorvedahl-RETICLE/Active/data/kb/kb.db \
      --taxids 9606,10090
"""
import argparse
import gzip
import sqlite3
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ncbi-dir", required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--taxids", default="9606,10090")
    args = ap.parse_args()

    taxids = {t.strip() for t in args.taxids.split(",") if t.strip()}
    con = sqlite3.connect(args.db)
    if not [r for r in con.execute("PRAGMA table_info(kb_gene)")]:
        raise SystemExit("kb_gene not found — run build_kb_gene.py first")
    known = {r[0] for r in con.execute("SELECT gene_id FROM kb_gene")}

    con.executescript("""
        DROP TABLE IF EXISTS kb_gene_pubmed;
        CREATE TABLE kb_gene_pubmed (
            gene_id INTEGER NOT NULL,
            pmid    INTEGER NOT NULL
        );
    """)

    batch, n = [], 0
    with gzip.open(Path(args.ncbi_dir) / "gene2pubmed.gz", "rt", encoding="utf-8") as f:
        f.readline()
        for line in f:
            c = line.rstrip("\n").split("\t")
            if len(c) < 3 or c[0] not in taxids:
                continue
            gid = int(c[1])
            if gid not in known:
                continue
            batch.append((gid, int(c[2])))
            if len(batch) >= 500_000:
                con.executemany("INSERT INTO kb_gene_pubmed VALUES (?,?)", batch)
                con.commit(); n += len(batch); batch = []
    if batch:
        con.executemany("INSERT INTO kb_gene_pubmed VALUES (?,?)", batch)
        con.commit(); n += len(batch)

    con.execute("CREATE INDEX ix_kgp_gene ON kb_gene_pubmed(gene_id)")
    con.execute("CREATE INDEX ix_kgp_pmid ON kb_gene_pubmed(pmid)")
    con.commit()
    print(f"DONE — kb_gene_pubmed: {n:,} gene-PMID links", flush=True)

    tp53 = con.execute("SELECT COUNT(*) FROM kb_gene_pubmed WHERE gene_id=7157").fetchone()[0]
    print(f"  TP53 (7157) linked papers: {tp53:,}", flush=True)
    con.close()


if __name__ == "__main__":
    main()

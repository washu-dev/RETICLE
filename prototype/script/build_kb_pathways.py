"""
build_kb_pathways.py — Reactome pathways per gene (kb_gene_pathway).
====================================================================
From Reactome's NCBI2Reactome.txt (lowest/leaf level, most specific), which is
keyed directly on Entrez GeneID — no mapping needed. Columns (no header):
  GeneID  Reactome_stable_id  URL  Pathway_name  Evidence_code  Species

Verbatim curated pathway membership — no interpretation. Human/mouse only.
Run AFTER build_kb_gene.py.

  python3 build_kb_pathways.py \
      --reactome /path/to/NCBI2Reactome.txt \
      --db       /storage3/fs1/aorvedahl-RETICLE/Active/data/kb/kb.db \
      --taxids 9606,10090
"""
import argparse
import sqlite3

SPECIES = {9606: "Homo sapiens", 10090: "Mus musculus"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reactome", required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--taxids", default="9606,10090")
    args = ap.parse_args()

    taxids = [int(t) for t in args.taxids.split(",") if t.strip()]
    want = {SPECIES[t] for t in taxids if t in SPECIES}
    con = sqlite3.connect(args.db)
    if not [r for r in con.execute("PRAGMA table_info(kb_gene)")]:
        raise SystemExit("kb_gene not found — run build_kb_gene.py first")
    known = {r[0] for r in con.execute("SELECT gene_id FROM kb_gene")}

    con.executescript("""
        DROP TABLE IF EXISTS kb_gene_pathway;
        CREATE TABLE kb_gene_pathway (
            gene_id   INTEGER NOT NULL,
            stable_id TEXT NOT NULL,
            name      TEXT,
            url       TEXT,
            PRIMARY KEY (gene_id, stable_id)
        );""")

    rows, seen = [], set()
    with open(args.reactome, encoding="utf-8") as f:
        for line in f:
            c = line.rstrip("\n").split("\t")
            if len(c) < 6 or not c[0].isdigit():
                continue
            if c[5] not in want:
                continue
            gid = int(c[0])
            if gid not in known:
                continue
            key = (gid, c[1])
            if key in seen:
                continue
            seen.add(key)
            rows.append((gid, c[1], c[3].strip(), c[2]))
    con.executemany("INSERT OR IGNORE INTO kb_gene_pathway VALUES (?,?,?,?)", rows)
    con.execute("CREATE INDEX ix_kgpw_gene ON kb_gene_pathway(gene_id)")
    con.commit()

    n = con.execute("SELECT COUNT(*) FROM kb_gene_pathway").fetchone()[0]
    g = con.execute("SELECT COUNT(DISTINCT gene_id) FROM kb_gene_pathway").fetchone()[0]
    print(f"DONE — kb_gene_pathway: {n:,} gene-pathway links across {g:,} genes", flush=True)
    tp = con.execute("SELECT name FROM kb_gene_pathway WHERE gene_id=7157 ORDER BY name LIMIT 5").fetchall()
    n_tp = con.execute("SELECT COUNT(*) FROM kb_gene_pathway WHERE gene_id=7157").fetchone()[0]
    print(f"  TP53: {n_tp} pathways; sample: {[x[0] for x in tp]}", flush=True)
    con.close()


if __name__ == "__main__":
    main()

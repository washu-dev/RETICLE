"""
build_kb_summary.py — attach NCBI RefSeq curated summaries to kb_gene.
======================================================================
Adds a column kb_gene.ncbi_summary and fills it from gene_summary.gz
(columns: tax_id, GeneID, Source, Summary), keyed by GeneID and filtered to
the taxids/genes already in kb_gene.

Run AFTER build_kb_gene.py (needs kb_gene to exist). Re-runnable: the column
add is guarded and the UPDATEs are idempotent. Coverage is partial by design —
RefSeq only curates summaries for a subset of genes; the rest stay NULL.

  python3 build_kb_summary.py \
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

    cols = [r[1] for r in con.execute("PRAGMA table_info(kb_gene)")]
    if not cols:
        raise SystemExit("kb_gene not found — run build_kb_gene.py first")
    if "ncbi_summary" not in cols:
        con.execute("ALTER TABLE kb_gene ADD COLUMN ncbi_summary TEXT")

    known = {r[0] for r in con.execute("SELECT gene_id FROM kb_gene")}

    path = Path(args.ncbi_dir) / "gene_summary.gz"
    updates = []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        f.readline()                                    # header
        for line in f:
            c = line.rstrip("\n").split("\t", 3)        # cap at 4 — a tab in the summary text stays intact
            if len(c) < 4:
                continue
            tax_id, gene_id, _source, summary = c
            if tax_id not in taxids:
                continue
            gid = int(gene_id)
            if gid in known and summary:
                updates.append((summary, gid))

    con.executemany("UPDATE kb_gene SET ncbi_summary = ? WHERE gene_id = ?", updates)
    con.commit()

    n_have = con.execute(
        "SELECT COUNT(*) FROM kb_gene WHERE ncbi_summary IS NOT NULL").fetchone()[0]
    n_tot = con.execute("SELECT COUNT(*) FROM kb_gene").fetchone()[0]
    print(f"DONE — {len(updates):,} summaries applied | "
          f"{n_have:,}/{n_tot:,} genes now have a summary ({100 * n_have / n_tot:.0f}%)", flush=True)

    row = con.execute(
        "SELECT symbol, substr(ncbi_summary, 1, 140) FROM kb_gene WHERE gene_id = 7157").fetchone()
    print(f"  TP53 summary -> {row}", flush=True)
    con.close()


if __name__ == "__main__":
    main()

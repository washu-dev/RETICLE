"""
build_kb_identifiers.py — external identifiers + orthologs for the gene infobox.
================================================================================
Adds, keyed strictly on Entrez GeneID (deterministic join, no fuzzy matching):
  kb_gene.ensembl_gene_id   from gene2ensembl.gz  (col3 Ensembl_gene_identifier)
  kb_gene.omim_id           from mim2gene_medgen  (MIM where type == 'gene')
  kb_gene_ortholog          from gene_orthologs.gz (human<->mouse, both directions)

Everything is a verbatim third-party identifier — no interpretation. Run AFTER
build_kb_gene.py. Re-runnable (guarded ALTER, first-wins UPDATEs, INSERT OR IGNORE).

  python3 build_kb_identifiers.py \
      --ncbi-dir /storage3/fs1/aorvedahl-RETICLE/Active/data/ncbi \
      --ortho    /path/to/gene_orthologs.gz \
      --db       /storage3/fs1/aorvedahl-RETICLE/Active/data/kb/kb.db \
      --taxids 9606,10090
"""
import argparse
import gzip
import sqlite3
from pathlib import Path


def _open(path):
    return gzip.open(path, "rt", encoding="utf-8") if str(path).endswith(".gz") else open(path, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ncbi-dir", required=True)
    ap.add_argument("--ortho", required=True, help="path to gene_orthologs.gz")
    ap.add_argument("--db", required=True)
    ap.add_argument("--taxids", default="9606,10090")
    args = ap.parse_args()

    taxids = {t.strip() for t in args.taxids.split(",") if t.strip()}
    ncbi = Path(args.ncbi_dir)
    con = sqlite3.connect(args.db)
    cols = [r[1] for r in con.execute("PRAGMA table_info(kb_gene)")]
    if not cols:
        raise SystemExit("kb_gene not found — run build_kb_gene.py first")
    for c in ("ensembl_gene_id", "omim_id"):
        if c not in cols:
            con.execute(f"ALTER TABLE kb_gene ADD COLUMN {c} TEXT")
    known = {r[0] for r in con.execute("SELECT gene_id FROM kb_gene")}

    # --- Ensembl gene id (col3, one per GeneID -> first wins) ---
    seen, ens = set(), []
    with _open(ncbi / "gene2ensembl.gz") as f:
        f.readline()
        for line in f:
            c = line.rstrip("\n").split("\t")
            if len(c) < 3 or c[0] not in taxids:
                continue
            gid = int(c[1])
            if gid in known and gid not in seen and c[2] and c[2] != "-":
                seen.add(gid); ens.append((c[2], gid))
    con.executemany("UPDATE kb_gene SET ensembl_gene_id=? WHERE gene_id=?", ens)
    con.commit()
    print(f"  ensembl_gene_id: {len(ens):,} genes", flush=True)

    # --- OMIM (rows where type == 'gene') ---
    omim = []
    with _open(ncbi / "mim2gene_medgen") as f:
        f.readline()
        for line in f:
            c = line.rstrip("\n").split("\t")
            if len(c) < 3 or c[2].strip() != "gene" or c[1] in ("-", ""):
                continue
            gid = int(c[1])
            if gid in known:
                omim.append((c[0].strip(), gid))
    con.executemany("UPDATE kb_gene SET omim_id=? WHERE gene_id=?", omim)
    con.commit()
    print(f"  omim_id: {len(omim):,} genes", flush=True)

    # --- Orthologs (human<->mouse, both directions, symbol denormalised) ---
    con.executescript("""
        DROP TABLE IF EXISTS kb_gene_ortholog;
        CREATE TABLE kb_gene_ortholog (
            gene_id          INTEGER NOT NULL,
            taxid            INTEGER NOT NULL,
            ortholog_gene_id INTEGER NOT NULL,
            ortholog_taxid   INTEGER NOT NULL,
            ortholog_symbol  TEXT,
            PRIMARY KEY (gene_id, ortholog_gene_id)
        );""")
    sym = {r[0]: r[1] for r in con.execute("SELECT gene_id, symbol FROM kb_gene")}
    pair_want = taxids
    rows = []
    with _open(args.ortho) as f:
        f.readline()
        for line in f:
            c = line.rstrip("\n").split("\t")
            if len(c) < 5 or c[2] != "Ortholog":
                continue
            t1, g1, t2, g2 = c[0], int(c[1]), c[3], int(c[4])
            if {t1, t2} != pair_want:
                continue
            for a, ta, b, tb in ((g1, int(t1), g2, int(t2)), (g2, int(t2), g1, int(t1))):
                if a in known:
                    rows.append((a, ta, b, tb, sym.get(b)))
    con.executemany("INSERT OR IGNORE INTO kb_gene_ortholog VALUES (?,?,?,?,?)", rows)
    con.execute("CREATE INDEX IF NOT EXISTS ix_ortho_gene ON kb_gene_ortholog(gene_id)")
    con.commit()
    n_ortho = con.execute("SELECT COUNT(*) FROM kb_gene_ortholog").fetchone()[0]
    print(f"  kb_gene_ortholog: {n_ortho:,} directed pairs", flush=True)

    # spot check TP53
    r = con.execute("SELECT symbol, ensembl_gene_id, omim_id FROM kb_gene WHERE gene_id=7157").fetchone()
    o = con.execute("SELECT ortholog_symbol, ortholog_gene_id, ortholog_taxid FROM kb_gene_ortholog WHERE gene_id=7157").fetchall()
    print(f"  TP53 -> ensembl={r[1]}, omim={r[2]}, ortholog={o}", flush=True)
    con.close()


if __name__ == "__main__":
    main()

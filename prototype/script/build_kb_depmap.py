"""
build_kb_depmap.py — DepMap CRISPR dependency, summarised per gene.
===================================================================
Two tables:
  kb_model            cell-line / model metadata from Model.csv
                      (model_id, cell_line_name, lineage, primary_disease, subtype).
  kb_gene_dependency  ONE row per gene summarising its Chronos gene-effect across
                      all cell lines: mean, how many lines depend on it, the most
                      dependent line, and an essentiality class.

Why a summary, not the full 1,178 x 17,916 matrix (~21M cells): the gene wiki
shows one gene at a time and wants "how essential is this gene, and where" — a
per-gene summary answers that in ~18k rows. The full per-line matrix is better
served by the existing screen-comparison feature if ever needed.

Convention: Chronos gene-effect < 0 = depletion (dependency); a line "depends"
on a gene at effect < -0.5, "strongly" at < -1.0 (DepMap's usual cutoffs).
Gene columns are "SYMBOL (EntrezID)" — the EntrezID is authoritative for joining.

Run AFTER build_kb_gene.py.

  python3 build_kb_depmap.py \
      --depmap-dir /storage3/fs1/aorvedahl-RETICLE/Active/data/depmap \
      --db         /storage3/fs1/aorvedahl-RETICLE/Active/data/kb/kb.db
"""
import argparse
import csv
import re
import sqlite3
import sys
from pathlib import Path

csv.field_size_limit(1 << 24)
GENE_COL = re.compile(r"\((\d+)\)\s*$")     # ...(EntrezID) at end of the column name

DEP_THRESHOLD = -0.5
STRONG_THRESHOLD = -1.0


def build_tables(con):
    con.executescript("""
        DROP TABLE IF EXISTS kb_model;
        DROP TABLE IF EXISTS kb_gene_dependency;
        CREATE TABLE kb_model (
            model_id        TEXT PRIMARY KEY,
            cell_line_name  TEXT,
            stripped_name   TEXT,
            model_type      TEXT,
            lineage         TEXT,
            primary_disease TEXT,
            subtype         TEXT
        );
        CREATE TABLE kb_gene_dependency (
            gene_id             INTEGER PRIMARY KEY,
            n_lines             INTEGER NOT NULL,
            mean_score          REAL,
            n_dependent         INTEGER NOT NULL,   -- effect < -0.5
            n_strong_dependent  INTEGER NOT NULL,   -- effect < -1.0
            min_score           REAL,
            most_dependent_model TEXT,
            essential_class     TEXT                -- common_essential / selective / non_essential
        );
    """)


def load_models(path, con):
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.reader(f)
        hdr = next(r)
        idx = {name: i for i, name in enumerate(hdr)}

        def g(row, col):
            i = idx.get(col)
            return row[i] if i is not None and i < len(row) and row[i] != "" else None

        rows = []
        for row in r:
            if not row:
                continue
            rows.append((g(row, "ModelID"), g(row, "CellLineName"),
                         g(row, "StrippedCellLineName"), g(row, "DepmapModelType"),
                         g(row, "OncotreeLineage"), g(row, "OncotreePrimaryDisease"),
                         g(row, "OncotreeSubtype")))
    con.executemany("INSERT OR IGNORE INTO kb_model VALUES (?,?,?,?,?,?,?)", rows)
    con.commit()
    return len(rows)


def summarise_dependency(path, known, con):
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.reader(f)
        header = next(r)
        # map each gene column index -> gene_id (only genes we know)
        col_gene = {}
        for i, name in enumerate(header[1:], start=1):
            m = GENE_COL.search(name)
            if m:
                gid = int(m.group(1))
                if gid in known:
                    col_gene[i] = gid
        # per-gene accumulators: [count, sum, n_dep, n_strong, min_score, min_model]
        acc = {gid: [0, 0.0, 0, 0, float("inf"), None] for gid in col_gene.values()}

        n_models = 0
        for row in r:
            if not row:
                continue
            model_id = row[0]
            n_models += 1
            for i, gid in col_gene.items():
                if i >= len(row):
                    continue
                v = row[i]
                if v == "" or v == "NA":
                    continue
                try:
                    s = float(v)
                except ValueError:
                    continue
                a = acc[gid]
                a[0] += 1
                a[1] += s
                if s < DEP_THRESHOLD:
                    a[2] += 1
                if s < STRONG_THRESHOLD:
                    a[3] += 1
                if s < a[4]:
                    a[4] = s
                    a[5] = model_id

    out = []
    for gid, a in acc.items():
        count, total, n_dep, n_strong, mn, mn_model = a
        if count == 0:
            continue
        frac = n_dep / count
        cls = ("common_essential" if frac >= 0.90
               else "selective" if n_dep >= 1
               else "non_essential")
        out.append((gid, count, round(total / count, 4), n_dep, n_strong,
                    round(mn, 4), mn_model, cls))
    con.executemany(
        "INSERT INTO kb_gene_dependency VALUES (?,?,?,?,?,?,?,?)", out)
    con.commit()
    return n_models, len(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--depmap-dir", required=True)
    ap.add_argument("--db", required=True)
    args = ap.parse_args()

    d = Path(args.depmap_dir)
    con = sqlite3.connect(args.db)
    if not [r for r in con.execute("PRAGMA table_info(kb_gene)")]:
        raise SystemExit("kb_gene not found — run build_kb_gene.py first")
    known = {r[0] for r in con.execute("SELECT gene_id FROM kb_gene")}
    build_tables(con)

    n_models_meta = load_models(d / "Model.csv", con)
    print(f"  kb_model: {n_models_meta:,} cell-line models", flush=True)

    n_models, n_genes = summarise_dependency(d / "CRISPRGeneEffect.csv", known, con)
    con.execute("CREATE INDEX ix_kgd_class ON kb_gene_dependency(essential_class)")
    con.commit()
    print(f"  kb_gene_dependency: {n_genes:,} genes summarised across {n_models:,} screened lines", flush=True)

    # spot checks: TP53 (tumor suppressor -> not a dependency) vs RAN (pan-essential
    # nuclear-transport GTPase; a dependency in every screened line)
    for sym, gid in (("TP53", 7157), ("RAN", 5901)):
        row = con.execute(
            "SELECT mean_score, n_dependent, n_lines, essential_class, min_score, most_dependent_model "
            "FROM kb_gene_dependency WHERE gene_id=?", (gid,)).fetchone()
        print(f"  {sym} ({gid}) -> {row}", flush=True)
    con.close()


if __name__ == "__main__":
    main()

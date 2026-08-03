"""
build_kb_screens.py — BioGRID ORCS CRISPR screen hits as structured facts.
==========================================================================
The 6th KB source, and deliberately SEPARATE from the harmonization pipeline:
it reads ONLY the raw BioGRID ORCS files (metadata JSON + per-screen .tab.txt),
never harmonized_scores / stress_facts, and stores NO directionality or
interpretation — just the raw hit + its screen's metadata + raw score values.
Meaning is left entirely to a later LLM analysis layer.

Two tables:
  kb_screen      one row per screen (metadata: cell line, condition, phenotype,
                 screen type, library, significance criteria, what each SCORE.x
                 column means, paper/PMID, ...).
  kb_screen_hit  one row per (gene, screen) where BioGRID flagged HIT=YES.
                 gene_id is the file's Entrez IDENTIFIER_ID (direct join to
                 kb_gene). Raw SCORE.1..5 kept as-is; '-' -> NULL.

We iterate the metadata's screen_ids (authoritative) and open each screen file
by constructed name — NOT a directory glob (the macOS SMB mount folds case and
lists phantom duplicates; iterating ids is robust and 1:1).

Run AFTER build_kb_gene.py.

  python3 build_kb_screens.py \
      --biogrid-dir /storage3/fs1/aorvedahl-RETICLE/Active/data/BIOGRID-ORCS-2.0.18 \
      --db          /storage3/fs1/aorvedahl-RETICLE/Active/data/kb/kb.db \
      --taxids 9606,10090
"""
import argparse
import json
import sqlite3
from pathlib import Path

VERSION = "2.0.18"
SPECIES = {
    9606: ("homo_sapiens", "screen_metadata_homo_sapiens.json"),
    10090: ("mus_musculus", "screen_metadata_musculus.json"),
}

# metadata field -> kb_screen column (kept generously; all raw, no interpretation)
META_FIELDS = [
    ("AUTHOR", "author"), ("CELL_LINE", "cell_line"), ("CELL_TYPE", "cell_type"),
    ("CONDITION_NAME", "condition_name"), ("CONDITION_DOSAGE", "condition_dosage"),
    ("PHENOTYPE", "phenotype"), ("SCREEN_TYPE", "screen_type"),
    ("SCREEN_RATIONALE", "screen_rationale"), ("SCREEN_NAME", "screen_name"),
    ("SCREEN_FORMAT", "screen_format"),
    ("LIBRARY", "library"), ("LIBRARY_TYPE", "library_type"), ("ENZYME", "enzyme"),
    ("METHODOLOGY", "methodology"), ("ANALYSIS", "analysis"),
    ("EXPERIMENTAL_SETUP", "experimental_setup"),
    ("DURATION", "duration"), ("THROUGHPUT", "throughput"),
    ("SIGNIFICANCE_CRITERIA", "significance_criteria"),
    ("NOTES", "notes"),
    ("SCORE.1_TYPE", "score1_type"), ("SCORE.2_TYPE", "score2_type"),
    ("SCORE.3_TYPE", "score3_type"), ("SCORE.4_TYPE", "score4_type"),
    ("SCORE.5_TYPE", "score5_type"), ("NUMBER_OF_HITS", "number_of_hits"),
]


def nn(v):
    """'-' and '' are BioGRID's null placeholders."""
    if v is None:
        return None
    v = v.strip()
    return v if v and v != "-" else None


def num(v):
    v = nn(v)
    if v is None:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def build_tables(con):
    cols = ", ".join(f"{c} TEXT" for _, c in META_FIELDS)
    con.executescript(f"""
        DROP TABLE IF EXISTS kb_screen;
        DROP TABLE IF EXISTS kb_screen_hit;
        CREATE TABLE kb_screen (
            screen_id INTEGER PRIMARY KEY,
            taxid     INTEGER,
            organism  TEXT,
            pmid      INTEGER,
            {cols}
        );
        CREATE TABLE kb_screen_hit (
            gene_id         INTEGER NOT NULL,
            screen_id       INTEGER NOT NULL,
            official_symbol TEXT,
            score1 REAL, score2 REAL, score3 REAL, score4 REAL, score5 REAL
        );
    """)


def parse_hits(path, screen_id, known, con):
    hits = []
    with open(path, encoding="utf-8") as f:
        f.readline()                                    # header
        for line in f:
            c = line.rstrip("\n").split("\t")
            if len(c) < 13 or c[12] != "YES":           # HIT column
                continue
            if c[2] != "ENTREZ_GENE" or not c[1].isdigit():
                continue
            gid = int(c[1])
            if gid not in known:
                continue
            hits.append((gid, screen_id, nn(c[3]),
                         num(c[7]), num(c[8]), num(c[9]), num(c[10]), num(c[11])))
    if hits:
        con.executemany(
            "INSERT INTO kb_screen_hit VALUES (?,?,?,?,?,?,?,?)", hits)
    return len(hits)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--biogrid-dir", required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--taxids", default="9606,10090")
    ap.add_argument("--limit", type=int, default=0, help="process only first N screens per taxid (0 = all; for testing)")
    args = ap.parse_args()

    taxids = [int(t) for t in args.taxids.split(",") if t.strip()]
    root = Path(args.biogrid_dir)
    con = sqlite3.connect(args.db)
    if not [r for r in con.execute("PRAGMA table_info(kb_gene)")]:
        raise SystemExit("kb_gene not found — run build_kb_gene.py first")
    known = {r[0] for r in con.execute("SELECT gene_id FROM kb_gene")}
    build_tables(con)

    meta_cols = [c for _, c in META_FIELDS]
    total_screens, total_hits, missing = 0, 0, 0

    for taxid in taxids:
        if taxid not in SPECIES:
            print(f"! no BioGRID mapping for taxid {taxid}, skipping", flush=True)
            continue
        subdir, meta_file = SPECIES[taxid]
        meta = json.load(open(root / meta_file, encoding="utf-8"))
        screen_ids = list(meta.keys())
        if args.limit:
            screen_ids = screen_ids[:args.limit]
        print(f"  taxid {taxid}: {len(screen_ids):,} screens in metadata", flush=True)

        screen_rows = []
        for sid in screen_ids:
            rec = meta[sid][0] if isinstance(meta[sid], list) else meta[sid]
            pmid = rec.get("SOURCE_ID") if str(rec.get("SOURCE_TYPE", "")).lower() == "pubmed" else None
            pmid = int(pmid) if pmid and str(pmid).isdigit() else None
            row = [int(sid), taxid, nn(rec.get("ORGANISM_OFFICIAL")), pmid]
            row += [nn(rec.get(k)) for k, _ in META_FIELDS]
            screen_rows.append(row)
        ph = ",".join("?" * (4 + len(META_FIELDS)))
        con.executemany(f"INSERT INTO kb_screen VALUES ({ph})", screen_rows)
        con.commit()

        for sid in screen_ids:
            fpath = root / subdir / f"BIOGRID-ORCS-SCREEN_{sid}-{VERSION}.screen.tab.txt"
            if not fpath.exists():
                missing += 1
                continue
            total_hits += parse_hits(fpath, int(sid), known, con)
            total_screens += 1
        con.commit()

    con.execute("CREATE INDEX ix_ksh_gene ON kb_screen_hit(gene_id)")
    con.execute("CREATE INDEX ix_ksh_screen ON kb_screen_hit(screen_id)")
    con.commit()
    print(f"DONE — kb_screen: {con.execute('SELECT COUNT(*) FROM kb_screen').fetchone()[0]:,} | "
          f"kb_screen_hit: {total_hits:,} hit rows over {total_screens:,} screens "
          f"({missing} screen files missing)", flush=True)

    # spot check: which screens is TP53 (7157) a hit in
    rows = con.execute("""
        SELECT s.screen_id, s.cell_line, s.phenotype, s.condition_name, s.pmid
        FROM kb_screen_hit h JOIN kb_screen s ON s.screen_id = h.screen_id
        WHERE h.gene_id = 7157 LIMIT 6""").fetchall()
    n = con.execute("SELECT COUNT(*) FROM kb_screen_hit WHERE gene_id=7157").fetchone()[0]
    print(f"  TP53 is a hit in {n} screens; sample:", flush=True)
    for r in rows:
        print(f"    screen {r[0]}: {r[1]} | {r[2]} | cond={r[3]} | PMID {r[4]}", flush=True)
    con.close()


if __name__ == "__main__":
    main()

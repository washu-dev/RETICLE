"""
build_kb_go.py — Gene Ontology: term dictionary + hierarchy + gene associations.
================================================================================
Builds three tables:
  kb_go_term    one row per GO term (go_id, name, namespace, definition, is_obsolete)
                parsed from go-basic.obo.
  kb_go_parent  is_a edges (go_id -> parent_id) from the obo, for roll-up/generalisation.
  kb_gene_go    gene_id <-> go_id associations from gene2go.gz, with evidence code,
                qualifier (keep "NOT ..." qualifiers — they're negative annotations),
                and category (Process/Function/Component). Filtered to the taxids and
                to gene_ids already in kb_gene.

Run AFTER build_kb_gene.py. Full rebuild of the three tables each run.

  python3 build_kb_go.py \
      --go-dir   /storage3/fs1/aorvedahl-RETICLE/Active/data/go \
      --ncbi-dir /storage3/fs1/aorvedahl-RETICLE/Active/data/ncbi \
      --db       /storage3/fs1/aorvedahl-RETICLE/Active/data/kb/kb.db \
      --taxids 9606,10090
"""
import argparse
import gzip
import sqlite3
from pathlib import Path


def parse_obo(path):
    """Yield term dicts from a go-basic.obo file (only [Term] stanzas)."""
    term, in_term = None, False
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if line == "[Term]":
                if term:
                    yield term
                term, in_term = {"parents": []}, True
                continue
            if line.startswith("[") and line.endswith("]"):
                # a non-Term stanza (e.g. [Typedef]) — flush and stop collecting
                if term:
                    yield term
                    term = None
                in_term = False
                continue
            if not in_term or term is None:
                continue
            if line.startswith("id: "):
                term["id"] = line[4:].strip()
            elif line.startswith("name: "):
                term["name"] = line[6:].strip()
            elif line.startswith("namespace: "):
                term["namespace"] = line[11:].strip()
            elif line.startswith("def: "):
                # def: "text..." [refs]  -> keep just the quoted text
                rest = line[5:].strip()
                if rest.startswith('"'):
                    end = rest.find('"', 1)
                    term["def"] = rest[1:end] if end > 0 else rest.strip('"')
            elif line.startswith("is_a: "):
                # is_a: GO:0048308 ! organelle inheritance
                term["parents"].append(line[6:].split("!")[0].strip())
            elif line.startswith("is_obsolete: true"):
                term["obsolete"] = True
    if term:
        yield term


def build_tables(con):
    con.executescript("""
        DROP TABLE IF EXISTS kb_go_term;
        DROP TABLE IF EXISTS kb_go_parent;
        DROP TABLE IF EXISTS kb_gene_go;
        CREATE TABLE kb_go_term (
            go_id       TEXT PRIMARY KEY,
            name        TEXT,
            namespace   TEXT,
            definition  TEXT,
            is_obsolete INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE kb_go_parent (
            go_id     TEXT NOT NULL,
            parent_id TEXT NOT NULL
        );
        CREATE TABLE kb_gene_go (
            gene_id   INTEGER NOT NULL,
            go_id     TEXT NOT NULL,
            evidence  TEXT,
            qualifier TEXT,
            category  TEXT
        );
    """)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--go-dir", required=True)
    ap.add_argument("--ncbi-dir", required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--taxids", default="9606,10090")
    args = ap.parse_args()

    taxids = {t.strip() for t in args.taxids.split(",") if t.strip()}
    con = sqlite3.connect(args.db)
    if not [r for r in con.execute("PRAGMA table_info(kb_gene)")]:
        raise SystemExit("kb_gene not found — run build_kb_gene.py first")
    known = {r[0] for r in con.execute("SELECT gene_id FROM kb_gene")}
    build_tables(con)

    # --- 1. ontology (go-basic.obo) ---
    terms, parents = [], []
    for t in parse_obo(Path(args.go_dir) / "go-basic.obo"):
        if "id" not in t:
            continue
        terms.append((t["id"], t.get("name"), t.get("namespace"),
                      t.get("def"), 1 if t.get("obsolete") else 0))
        for p in t["parents"]:
            parents.append((t["id"], p))
    con.executemany("INSERT OR IGNORE INTO kb_go_term VALUES (?,?,?,?,?)", terms)
    con.executemany("INSERT INTO kb_go_parent VALUES (?,?)", parents)
    con.commit()
    print(f"  kb_go_term: {len(terms):,} terms | kb_go_parent: {len(parents):,} is_a edges", flush=True)

    # --- 2. gene->GO associations (gene2go.gz, all species -> filter) ---
    assoc, n = [], 0
    with gzip.open(Path(args.ncbi_dir) / "gene2go.gz", "rt", encoding="utf-8") as f:
        f.readline()
        for line in f:
            c = line.rstrip("\n").split("\t")
            if len(c) < 8 or c[0] not in taxids:
                continue
            gid = int(c[1])
            if gid not in known:
                continue
            assoc.append((gid, c[2], c[3], c[4], c[7]))   # gene_id, GO_ID, Evidence, Qualifier, Category
            if len(assoc) >= 500_000:
                con.executemany("INSERT INTO kb_gene_go VALUES (?,?,?,?,?)", assoc)
                con.commit(); n += len(assoc); assoc = []
    if assoc:
        con.executemany("INSERT INTO kb_gene_go VALUES (?,?,?,?,?)", assoc)
        con.commit(); n += len(assoc)

    con.execute("CREATE INDEX ix_kgg_gene ON kb_gene_go(gene_id)")
    con.execute("CREATE INDEX ix_kgg_go ON kb_gene_go(go_id)")
    con.execute("CREATE INDEX ix_kgp_go ON kb_go_parent(go_id)")
    con.commit()
    print(f"  kb_gene_go: {n:,} gene-GO associations", flush=True)

    # spot check: TP53's GO terms (top few by namespace)
    rows = con.execute("""
        SELECT t.namespace, t.name, gg.evidence
        FROM kb_gene_go gg JOIN kb_go_term t ON t.go_id = gg.go_id
        WHERE gg.gene_id = 7157 ORDER BY t.namespace LIMIT 5""").fetchall()
    print("  TP53 GO sample:", flush=True)
    for r in rows:
        print(f"    {r[0][:20]:20} | {r[1]} ({r[2]})", flush=True)
    con.close()


if __name__ == "__main__":
    main()

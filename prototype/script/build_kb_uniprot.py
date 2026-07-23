"""
build_kb_uniprot.py — attach UniProt (Swiss-Prot) function / location / disease to kb_gene.
===========================================================================================
Adds columns uniprot_acc / uniprot_function / uniprot_location / uniprot_disease
to kb_gene, filled from the reviewed TSVs (fields: Entry, ..., Function [CC],
Subcellular location [CC], Involvement in disease, GeneID).

Join edge cases handled (all verified against the real files):
  - GeneID field has a trailing ';'  -> stripped
  - one entry can map to several GeneIDs (220 rows) -> annotation applied to each
  - ~2.2k entries have no GeneID -> can't join, skipped
  - 126 GeneIDs are hit by multiple entries (e.g. histone clusters) -> keep the
    entry with the longest FUNCTION text (deterministic, not last-write-wins)

Function/location/disease text is cleaned: the "FUNCTION:"/"SUBCELLULAR
LOCATION:"/"DISEASE:" prefix and the {ECO:...} curator evidence codes are
removed; inline (PubMed:...) citations are kept for provenance.

Run AFTER build_kb_gene.py. Re-runnable.

  python3 build_kb_uniprot.py \
      --uniprot-dir /storage3/fs1/aorvedahl-RETICLE/Active/data/uniprot \
      --db          /storage3/fs1/aorvedahl-RETICLE/Active/data/kb/kb.db \
      --taxids 9606,10090
"""
import argparse
import re
import sqlite3
from pathlib import Path

FILES = {9606: "uniprot_reviewed_9606.tsv", 10090: "uniprot_reviewed_10090.tsv"}
_ECO = re.compile(r"\s*\{ECO:[^{}]*\}")
_PREFIX = re.compile(r"^(FUNCTION|SUBCELLULAR LOCATION|DISEASE):\s*")


def clean(text):
    if not text:
        return None
    t = _ECO.sub("", text)
    t = _PREFIX.sub("", t).strip()
    t = re.sub(r"\s{2,}", " ", t)
    return t or None


def parse_geneids(field):
    field = field.strip().strip(";")
    out = []
    for g in field.split(";"):
        g = g.strip()
        if g.isdigit():
            out.append(int(g))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uniprot-dir", required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--taxids", default="9606,10090")
    args = ap.parse_args()

    taxids = [int(t) for t in args.taxids.split(",") if t.strip()]
    con = sqlite3.connect(args.db)
    cols = [r[1] for r in con.execute("PRAGMA table_info(kb_gene)")]
    if not cols:
        raise SystemExit("kb_gene not found — run build_kb_gene.py first")
    for col in ("uniprot_acc", "uniprot_function", "uniprot_location", "uniprot_disease"):
        if col not in cols:
            con.execute(f"ALTER TABLE kb_gene ADD COLUMN {col} TEXT")

    known = {r[0] for r in con.execute("SELECT gene_id FROM kb_gene")}

    # gene_id -> (func_len, acc, function, location, disease); keep longest function on collision
    best = {}
    for taxid in taxids:
        fname = FILES.get(taxid)
        p = Path(args.uniprot_dir) / fname if fname else None
        if not p or not p.exists():
            print(f"! missing UniProt file for taxid {taxid}, skipping", flush=True)
            continue
        with open(p, encoding="utf-8") as f:
            f.readline()
            for line in f:
                c = line.rstrip("\n").split("\t")
                if len(c) < 9:
                    continue
                acc = c[0]
                function, location, disease = clean(c[5]), clean(c[6]), clean(c[7])
                flen = len(function or "")
                for gid in parse_geneids(c[8]):
                    if gid not in known:
                        continue
                    if gid not in best or flen > best[gid][0]:
                        best[gid] = (flen, acc, function, location, disease)

    updates = [(v[1], v[2], v[3], v[4], gid) for gid, v in best.items()]
    con.executemany(
        "UPDATE kb_gene SET uniprot_acc=?, uniprot_function=?, uniprot_location=?, "
        "uniprot_disease=? WHERE gene_id=?", updates)
    con.commit()

    n_func = con.execute("SELECT COUNT(*) FROM kb_gene WHERE uniprot_function IS NOT NULL").fetchone()[0]
    n_dis = con.execute("SELECT COUNT(*) FROM kb_gene WHERE uniprot_disease IS NOT NULL").fetchone()[0]
    n_tot = con.execute("SELECT COUNT(*) FROM kb_gene").fetchone()[0]
    print(f"DONE — {len(updates):,} genes linked to UniProt | "
          f"{n_func:,} have function text, {n_dis:,} have disease info (of {n_tot:,} genes)", flush=True)

    row = con.execute(
        "SELECT symbol, uniprot_acc, substr(uniprot_function, 1, 140) FROM kb_gene WHERE gene_id=7157").fetchone()
    print(f"  TP53 -> {row}", flush=True)
    con.close()


if __name__ == "__main__":
    main()

"""
build_gene_search.py — the lookup table behind the search box's type-ahead.
==========================================================================
Suggesting genes as someone types needs two things a live query cannot give at keystroke speed.

FIRST, RANKING — and it took two signals, not one. Measured on real prefixes:

  ORDER BY symbol        "PO" -> POC1A, POC1B, POC1B-AS1, POC1B-DUSP6.  Alphabetical and useless.
  ORDER BY n_hits        "PO" -> POLR2L, POLR3A, POLR2D ... good.
                         "TP5" -> TP53RK(697 hits) ABOVE TP53(98).      Wrong, and instructively so:
                         TP53 is a tumour suppressor, so knocking it out is often ADVANTAGEOUS and
                         it is rarely a called hit, while TP53RK is quietly essential. Screen
                         volume does not measure fame.
  ORDER BY n_papers      "TP5" -> TP53 first. Correct.
                         "PO"  -> PON1(1,283 papers, 17 hits) above POLR2A. Well-studied, but not
                         what anyone typing "PO" into a CRISPR tool means.

Neither alone. The shipped score is their geometric blend, sqrt(papers+1) * sqrt(hits+1), which
rewards genes strong on BOTH — which is exactly what "a gene a CRISPR researcher would type" is.
It answers PO -> POLR2A, POLR2B; TP5 -> TP53; FANC -> FANCD2, FANCA; BRC -> BRCA1, BRCA2.

  A literature term in the ranking looks like it contradicts a product built for dark genes. It
  does not: this is the box where you type a gene you ALREADY have in mind, and you have it in
  mind because you know it. Genes you did not have in mind are surfaced by the network and the
  prediction card, not here. Dark genes stay reachable — type a few more characters and the field
  narrows to them, because there is nothing famous left to outrank them.

SECOND, SPEED. The n_hits half is a GROUP BY over kb_screen_hit's 1,895,689 rows: 1.34 s measured.
Per keystroke that is unusable. Precomputed, the whole thing is an indexed prefix scan at ~8 ms.

ALIASES ARE INCLUDED as their own rows. People type the symbol they learned, which is often the
one NCBI has since retired, and a search box that answers "no results" for a name the gene really
had is the search box's fault, not the user's. Each alias row carries the CANONICAL symbol so the
suggestion navigates to the right place, and is marked so the UI can show why it matched.

  /opt/anaconda3/bin/python3 script/build_gene_search.py
"""

import argparse
import math
import sqlite3
import time

import paths

KB = paths.PROCESSED_DATA / "kb.db"

# Only the two species the product serves. kb_gene holds nothing else, but stating it keeps the
# table honest if that ever changes.
TAXA = (9606, 10090)


def build(con, taxa):
    con.execute("DROP TABLE IF EXISTS gene_search")
    con.execute("""
        CREATE TABLE gene_search (
            gene_id  INTEGER,
            taxid    INTEGER,
            symbol   TEXT,     -- the canonical symbol; what a suggestion navigates to
            term     TEXT,     -- what the typed prefix is matched against, UPPERCASED
            is_alias INTEGER,  -- 1 when `term` is a retired or alternate name for `symbol`
            n_hits   INTEGER,  -- screens where this gene was a called hit
            n_papers INTEGER,  -- distinct PubMed ids linked to the gene
            rank     INTEGER,  -- the blended score the dropdown sorts on; see the module docstring
            name     TEXT      -- one-line descriptor for the dropdown's second line
        )
    """)

    ph = ",".join("?" * len(taxa))
    t0 = time.time()
    # One pass over each big table rather than a correlated subquery per gene.
    hits = dict(con.execute(
        "SELECT gene_id, COUNT(*) FROM kb_screen_hit GROUP BY gene_id").fetchall())
    papers = dict(con.execute(
        "SELECT gene_id, COUNT(*) FROM kb_gene_pubmed GROUP BY gene_id").fetchall())
    print(f"  hits for {len(hits):,} genes, papers for {len(papers):,}  "
          f"({time.time()-t0:.1f}s)", flush=True)

    def rank_of(gid):
        # Geometric blend: a gene has to be BOTH written about and measured to rank high, which is
        # what separates POLR2A from PON1 on "PO" and TP53 from TP53RK on "TP5".
        return int(math.sqrt(papers.get(gid, 0) + 1) * math.sqrt(hits.get(gid, 0) + 1))

    genes = con.execute(
        f"SELECT gene_id, taxid, symbol, COALESCE(full_name, description, '') "
        f"FROM kb_gene WHERE taxid IN ({ph}) AND symbol IS NOT NULL AND symbol <> ''",
        taxa).fetchall()
    rows = [(gid, tax, sym, sym.upper(), 0, hits.get(gid, 0), papers.get(gid, 0),
             rank_of(gid), name) for gid, tax, sym, name in genes]
    canonical = {gid: (tax, sym, name) for gid, tax, sym, name in genes}
    print(f"  {len(rows):,} canonical symbols", flush=True)

    seen = {(r[1], r[3]) for r in rows}          # never let an alias shadow a real symbol
    n_alias = 0
    for gid, alias in con.execute(
            f"SELECT gene_id, alias FROM kb_gene_alias WHERE taxid IN ({ph}) "
            f"AND alias IS NOT NULL AND alias <> ''", taxa):
        c = canonical.get(gid)
        if not c:
            continue                              # alias for a gene we do not carry
        tax, sym, name = c
        key = (tax, alias.upper())
        if key in seen:
            continue
        seen.add(key)
        rows.append((gid, tax, sym, alias.upper(), 1, hits.get(gid, 0),
                     papers.get(gid, 0), rank_of(gid), name))
        n_alias += 1
    print(f"  {n_alias:,} alias terms", flush=True)

    con.executemany("INSERT INTO gene_search VALUES (?,?,?,?,?,?,?,?,?)", rows)
    # (taxid, term) is the access path: every query filters species and prefixes the term.
    con.execute("CREATE INDEX ix_gs_term ON gene_search(taxid, term)")
    con.commit()
    return len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(KB))
    args = ap.parse_args()

    t0 = time.time()
    con = sqlite3.connect(args.db)
    n = build(con, TAXA)
    print(f"DONE — {n:,} search terms in {time.time()-t0:.1f}s", flush=True)

    # Same ORDER BY and the same de-duplication the endpoint uses, so this print IS what ships.
    #
    #   is_alias BEFORE rank, deliberately. With rank first, "FANC" answered BRCA1, BRCA2, RAD51 —
    #   all correct alias matches (FANCS is BRCA1, FANCD1 is BRCA2) and all wrong, because someone
    #   typing FANC wants the FANC genes. Canonical symbols come first; aliases are the fallback
    #   that rescues a retired name, not a way for a famous gene to jump a queue it is not in.
    #
    #   De-dupe by SYMBOL: a gene with three matching aliases filled three of six slots with itself.
    for q in ("PO", "FANC", "MTAP", "TP5", "BRC", "POL"):
        t = time.time()
        rows = con.execute(
            "SELECT symbol, is_alias FROM gene_search WHERE taxid=9606 AND term LIKE ? "
            "ORDER BY (term = ? AND is_alias = 0) DESC, is_alias, rank DESC, LENGTH(term), term "
            "LIMIT 40",
            (q + "%", q)).fetchall()
        out, seen_sym = [], set()
        for sym, alias in rows:
            if sym in seen_sym:
                continue
            seen_sym.add(sym)
            out.append(f"{sym}{'*' if alias else ''}")
            if len(out) == 6:
                break
        print(f"  {q:6s} {(time.time()-t)*1000:5.1f}ms  " + ", ".join(out), flush=True)
    con.close()


if __name__ == "__main__":
    main()

"""
kb_gene_profile.py — pull one gene's full profile from reticle_kb (all tables).
==============================================================================
Doubles as (a) an end-to-end acceptance test that the KB joins coherently, and
(b) the prototype of the read side of the /v1/gene API: resolve a symbol/alias
to a gene_id, then gather identity + NCBI summary + UniProt + GO + STRING
partners + DepMap dependency + PubMed count.

  python3 kb_gene_profile.py --db .../kb/kb.db --gene TP53
  python3 kb_gene_profile.py --db .../kb/kb.db --gene 7157 --taxid 9606
"""
import argparse
import sqlite3
import textwrap


def resolve(con, gene, taxid):
    if gene.isdigit():
        row = con.execute("SELECT gene_id, symbol, taxid FROM kb_gene WHERE gene_id=?",
                           (int(gene),)).fetchone()
        return row
    # prefer an exact current-symbol hit, else any alias, scoped by taxid
    row = con.execute(
        """SELECT g.gene_id, g.symbol, g.taxid
           FROM kb_gene_alias a JOIN kb_gene g ON g.gene_id = a.gene_id
           WHERE a.alias = ? AND a.taxid = ?
           ORDER BY (a.alias_type='symbol') DESC LIMIT 1""", (gene, taxid)).fetchone()
    return row


def wrap(text, width=92, indent="    "):
    if not text:
        return indent + "(none)"
    return "\n".join(textwrap.wrap(text, width=width,
                                   initial_indent=indent, subsequent_indent=indent))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--gene", required=True)
    ap.add_argument("--taxid", type=int, default=9606)
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    r = resolve(con, args.gene, args.taxid)
    if not r:
        raise SystemExit(f"could not resolve '{args.gene}' (taxid {args.taxid})")
    gid, symbol, taxid = r

    g = con.execute(
        """SELECT description, full_name, type_of_gene, chromosome, map_location,
                  ncbi_summary, uniprot_acc, uniprot_function, uniprot_location, uniprot_disease
           FROM kb_gene WHERE gene_id=?""", (gid,)).fetchone()
    (desc, full_name, gtype, chrom, maploc, summary,
     up_acc, up_func, up_loc, up_dis) = g

    print("=" * 96)
    print(f"  {symbol}  (GeneID {gid}, taxid {taxid})  —  {full_name or desc or ''}")
    print(f"  {gtype or '?'} · chr{chrom or '?'} {maploc or ''}")
    print("=" * 96)

    print("\n[NCBI summary]")
    print(wrap(summary))

    print(f"\n[UniProt {up_acc or '—'}]  function:")
    print(wrap(up_func))
    if up_loc:
        print("  location:", (up_loc[:120] + "…") if len(up_loc) > 120 else up_loc)
    if up_dis:
        print("  disease :", (up_dis[:120] + "…") if len(up_dis) > 120 else up_dis)

    # GO — a few per namespace, prefer experimental evidence
    print("\n[Gene Ontology]")
    for ns in ("molecular_function", "biological_process", "cellular_component"):
        terms = con.execute(
            """SELECT DISTINCT t.name FROM kb_gene_go gg JOIN kb_go_term t ON t.go_id=gg.go_id
               WHERE gg.gene_id=? AND t.namespace=? AND t.is_obsolete=0 LIMIT 6""",
            (gid, ns)).fetchall()
        names = ", ".join(t[0] for t in terms) or "(none)"
        print(f"  {ns.split('_')[1][:4].upper():4}: {names}")

    # STRING top partners
    print("\n[STRING partners (top 8 by combined score)]")
    partners = con.execute(
        """SELECT g2.symbol, e.combined_score
           FROM kb_string_edge e
           JOIN kb_gene g2 ON g2.gene_id = CASE WHEN e.gene_id_a=? THEN e.gene_id_b ELSE e.gene_id_a END
           WHERE e.gene_id_a=? OR e.gene_id_b=?
           ORDER BY e.combined_score DESC LIMIT 8""", (gid, gid, gid)).fetchall()
    print("    " + (", ".join(f"{s}({sc})" for s, sc in partners) or "(none)"))

    # DepMap dependency
    print("\n[DepMap CRISPR dependency]")
    dep = con.execute(
        """SELECT d.essential_class, d.mean_score, d.n_dependent, d.n_lines,
                  d.min_score, m.cell_line_name, m.lineage
           FROM kb_gene_dependency d LEFT JOIN kb_model m ON m.model_id=d.most_dependent_model
           WHERE d.gene_id=?""", (gid,)).fetchone()
    if dep:
        cls, mean, ndep, nlines, mn, cell, lin = dep
        print(f"    class: {cls} | mean effect {mean} | dependent in {ndep}/{nlines} lines")
        print(f"    most dependent: {cell or '?'} ({lin or '?'}) at {mn}")
    else:
        print("    (not in the DepMap CRISPR matrix)")

    # BioGRID CRISPR screens — raw hit facts grouped by phenotype (NO directionality)
    print("\n[BioGRID CRISPR screens]")
    n_scr = con.execute("SELECT COUNT(*) FROM kb_screen_hit WHERE gene_id=?", (gid,)).fetchone()[0]
    if n_scr:
        print(f"    hit in {n_scr} screens — by phenotype:")
        for ph, cnt, conds in con.execute(
                """SELECT s.phenotype, COUNT(*) c, GROUP_CONCAT(DISTINCT s.condition_name)
                   FROM kb_screen_hit h JOIN kb_screen s ON s.screen_id=h.screen_id
                   WHERE h.gene_id=? GROUP BY s.phenotype ORDER BY c DESC""", (gid,)):
            drugs = [x for x in (conds or "").split(",") if x and x != "None"]
            extra = (" — " + ", ".join(drugs[:5]) + ("…" if len(drugs) > 5 else "")) if drugs else ""
            print(f"      {cnt:>3}  {ph or '?'}{extra}")
    else:
        print("    (not called a hit in any screen)")

    # PubMed anchor count
    n_pmid = con.execute("SELECT COUNT(*) FROM kb_gene_pubmed WHERE gene_id=?", (gid,)).fetchone()[0]
    print(f"\n[Literature] {n_pmid:,} linked PubMed papers (anchor for future abstract retrieval)")
    print("=" * 96)
    con.close()


if __name__ == "__main__":
    main()

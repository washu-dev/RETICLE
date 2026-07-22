"""
build_stress_facts.py — distill every stress/reporter HIT into an atomic,
auditable fact (one row per gene x hit).  DETERMINISTIC — no LLM.
=====================================================================
Rationale
---------
Stress magnitudes are NOT comparable across conditions (dose / baseline /
mechanism differ), so we do not pool them onto one quantitative axis the way
fitness is harmonized.  What *is* comparable is the SIGN (resistance vs
sensitisation) together with the CONDITION.  So for stress & reporter screens
we promote each author-called hit to a structured "fact":

    gene --[direction]--> condition   (+ evidence, + provenance)

The sentence is a TEMPLATE render of these fields — the valence comes from the
already-calibrated HARMONIZED_SCORE sign (never from an LLM), the condition
from the real curated `condition_name` (never an LLM paraphrase).  An LLM only
enters later, at query time, to synthesise across retrieved facts (the RAG
layer).

Hit definition
--------------
`IS_HIT` == the authors' own significance call (BioGRID HIT column == "YES");
this is exactly the "authors' significance" rule we settled on.

Direction (calibrated axis, same one the app already shows)
-----------------------------------------------------------
HARMONIZED_SCORE > 0  -> knockout ENRICHED under the selection
HARMONIZED_SCORE < 0  -> knockout DEPLETED under the selection
  stress   : + = KO confers resistance   |  - = KO sensitises
  reporter : + = KO raises the reporter   |  - = KO lowers the reporter
(sign is already baked in during harmonisation — do NOT re-apply sign_convention)

Outputs (in the local SQLite master DB)
---------------------------------------
  * table  stress_facts       — one row per gene x stress/reporter hit
  * view   stress_consensus    — per (gene, condition_class) concordance rollup

    python3 script/build_stress_facts.py
"""

import sys
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import paths

DOMAINS = ("stress", "reporter")


def build(con):
    cur = con.cursor()
    cur.execute("DROP TABLE IF EXISTS stress_facts")
    cur.execute("""
        CREATE TABLE stress_facts (
            gene            TEXT,
            screen_id       TEXT,
            pmid            TEXT,
            author          TEXT,
            cell_line       TEXT,
            organism        TEXT,
            domain          TEXT,   -- stress | reporter
            condition_class TEXT,
            condition_name  TEXT,
            readout_type    TEXT,
            effect_sign     TEXT,   -- pos | neg  (KO enriched | depleted)
            direction       TEXT,   -- human label, domain-aware
            harmonized      REAL,
            robust_z        REAL,
            percentile      REAL,
            sentence        TEXT
        )
    """)

    # ---- prefilter: one tiny table of just the stress/reporter screens
    #      (~1,020 rows) with facets + metadata, keyed by screen_id.  This lets
    #      the 28 M-row join use a plain indexed equality instead of a CAST
    #      expression (which would defeat the index -> 28M x 2157 nested loop).
    qmarks = ",".join("?" * len(DOMAINS))
    cur.execute("DROP TABLE IF EXISTS _sr_screens")
    cur.execute(f"""
        CREATE TABLE _sr_screens AS
        SELECT c.screen_id AS screen_id, c.pmid, c.assay_domain,
               c.condition_class, c.condition_name, c.readout_type,
               m.AUTHOR AS author, m.CELL_LINE AS cell_line,
               m.ORGANISM_OFFICIAL AS organism
        FROM screen_metadata_curated c
        JOIN screen_metadata m ON m.SCREEN_ID = c.screen_id
        WHERE c.assay_domain IN ({qmarks})
    """, DOMAINS)
    cur.execute("CREATE UNIQUE INDEX idx_sr_sid ON _sr_screens(screen_id)")
    con.commit()
    nsr = cur.execute("SELECT COUNT(*) FROM _sr_screens").fetchone()[0]
    print(f"prefilter _sr_screens: {nsr} stress/reporter screens", flush=True)
    if nsr == 0:
        raise SystemExit("join key mismatch — _sr_screens is empty")

    # ---- one scan over the 28 M score table: keep author-called hits that
    #      belong to a stress/reporter screen (plain equality join -> fast).
    cur.execute("""
        INSERT INTO stress_facts
            (gene, screen_id, pmid, author, cell_line, organism, domain,
             condition_class, condition_name, readout_type,
             effect_sign, direction, harmonized, robust_z, percentile)
        SELECT
            h.GENE_SYMBOL, s.screen_id, s.pmid, s.author, s.cell_line, s.organism,
            s.assay_domain, s.condition_class, s.condition_name, s.readout_type,
            CASE WHEN COALESCE(NULLIF(h.HARMONIZED_SCORE,0), h.ROBUST_Z_SCORE, 0) >= 0
                 THEN 'pos' ELSE 'neg' END,
            CASE
              WHEN s.assay_domain='stress' AND
                   COALESCE(NULLIF(h.HARMONIZED_SCORE,0), h.ROBUST_Z_SCORE, 0) >= 0
                   THEN 'knockout confers resistance'
              WHEN s.assay_domain='stress'
                   THEN 'knockout sensitises'
              WHEN s.assay_domain='reporter' AND
                   COALESCE(NULLIF(h.HARMONIZED_SCORE,0), h.ROBUST_Z_SCORE, 0) >= 0
                   THEN 'knockout raises reporter'
              ELSE 'knockout lowers reporter'
            END,
            h.HARMONIZED_SCORE, h.ROBUST_Z_SCORE, h.PERCENTILE_SCORE
        FROM harmonized_scores h
        JOIN _sr_screens s ON h.SCREEN_ID = s.screen_id
        WHERE h.IS_HIT = 1
          -- drop non-targeting / safe-harbor / reporter controls (not real genes)
          AND h.GENE_SYMBOL NOT IN
              ('NTC','Non-Targeting','Non-Targeting-Control','NonTargeting','LacZ',
               'GFP','EGFP','Luciferase','Luc','Control','Scramble','sgNT','sgControl')
          AND h.GENE_SYMBOL NOT LIKE 'Control_%'
          AND h.GENE_SYMBOL NOT LIKE 'Control-%'
          AND h.GENE_SYMBOL NOT LIKE 'Non-Targeting%'
    """)
    con.commit()
    cur.execute("DROP TABLE _sr_screens")
    con.commit()

    # ---- render the sentence (template, in Python for clean phrasing) --------
    rows = cur.execute("""SELECT rowid, gene, domain, direction, condition_name,
                                 condition_class, author, cell_line, robust_z
                          FROM stress_facts""").fetchall()
    # NB: the raw robust-z is NOT shown — some screens have MAD~0 and produce
    # degenerate z's (thousands); the hit itself is the authors' significance call.
    upd = []
    for rid, gene, dom, direction, cond, cclass, author, cell, z in rows:
        cond = (cond or "the condition").strip()
        author = (author or "an unpublished").strip()
        cell = (cell or "cells").strip()
        if dom == "stress":
            verb = ("confers resistance to" if "resistance" in direction
                    else "sensitises cells to")
            s = (f"{gene}: knockout {verb} {cond} ({cclass}) "
                 f"— {author} screen in {cell}; author-called hit.")
        else:  # reporter
            verb = "raises" if "raises" in direction else "lowers"
            s = (f"{gene}: knockout {verb} the {cond} reporter "
                 f"— {author} screen in {cell}; author-called hit.")
        upd.append((s, rid))
    cur.executemany("UPDATE stress_facts SET sentence=? WHERE rowid=?", upd)
    con.commit()

    # ---- indexes + consensus view (method B: within-class concordance) -------
    cur.execute("CREATE INDEX idx_sf_gene ON stress_facts(gene)")
    cur.execute("CREATE INDEX idx_sf_gene_class ON stress_facts(gene, condition_class)")
    # method B — concordance at the SPECIFIC-condition grain (gene x condition_name),
    # NOT lumped across 517 different drugs.  This is the only cross-screen number
    # that is legitimately comparable: we count how many screens of the *same*
    # condition agree on direction, never averaging incomparable magnitudes.
    cur.execute("DROP VIEW IF EXISTS stress_consensus")
    cur.execute("""
        CREATE VIEW stress_consensus AS
        SELECT gene, domain, condition_class, condition_name,
               SUM(effect_sign='pos') AS n_resistance,
               SUM(effect_sign='neg') AS n_sensitising,
               COUNT(DISTINCT screen_id) AS n_screens,
               SUM(effect_sign='pos') - SUM(effect_sign='neg') AS net,
               GROUP_CONCAT(DISTINCT screen_id) AS screens
        FROM stress_facts
        GROUP BY gene, domain, condition_class, condition_name
    """)
    con.commit()
    return len(rows)


def report(con):
    cur = con.cursor()
    n = cur.execute("SELECT COUNT(*) FROM stress_facts").fetchone()[0]
    ng = cur.execute("SELECT COUNT(DISTINCT gene) FROM stress_facts").fetchone()[0]
    ns = cur.execute("SELECT COUNT(DISTINCT screen_id) FROM stress_facts").fetchone()[0]
    print(f"\nstress_facts: {n:,} facts | {ng:,} genes | {ns:,} screens")
    print("\nby domain x direction:")
    for dom, sgn, k in cur.execute("""SELECT domain, effect_sign, COUNT(*)
            FROM stress_facts GROUP BY domain, effect_sign ORDER BY domain, effect_sign"""):
        print(f"   {dom:9s} {sgn}: {k:,}")
    print("\nsample facts (sentence):")
    for (s,) in cur.execute("""SELECT sentence FROM stress_facts
            WHERE domain='stress' ORDER BY ABS(robust_z) DESC LIMIT 5"""):
        print("   •", s)
    print("\nconsensus — same gene, same specific condition, >=3 screens agreeing:")
    for g, cond, nr, nsn, nsc, net in cur.execute("""
            SELECT gene, condition_name, n_resistance, n_sensitising, n_screens, net
            FROM stress_consensus
            WHERE n_screens >= 3 AND ABS(net) = n_screens   -- fully concordant
            ORDER BY n_screens DESC LIMIT 10"""):
        lean = "resistance" if net > 0 else "sensitising"
        print(f"   {g:9s} {lean:11s} in {nsc}/{nsc} screens of  {str(cond)[:52]}")


def main():
    con = sqlite3.connect(str(paths.DB), timeout=120)
    con.execute("PRAGMA busy_timeout=120000")
    build(con)
    report(con)
    con.close()


if __name__ == "__main__":
    main()

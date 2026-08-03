"""
build_net_context.py — the discrete context taxonomy for the CRISPR gene network.
=================================================================================
"Build the context vector first — it is the invariant" (Anthony, Part IV). One row per
HUMAN screen, labelled with the coordinates we stratify edges by: assay_domain,
condition_class, mechanism bucket (for drug screens), modality (+ its sign s_m),
coverage type (FULL vs HIT_ONLY = Anthony's measured vs undefined_absent at screen
level), cell line, readout.

Reads the immutable observation source (reticle_master.db); writes the derived taxonomy
to reticle_net.db. Human only (locked v1 scope).

  /opt/anaconda3/bin/python3 script/build_net_context.py
"""
import sqlite3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from drug_mechanism import bucket

SRC = "processed_data/reticle_master.db"
NET = "processed_data/reticle_net.db"

# METHODOLOGY -> (modality, s_m sign): KO/CRISPRi deplete-negative, CRISPRa +1
MODALITY = {"Knockout": ("KO", -1), "Inhibition": ("CRISPRi", -1), "Activation": ("CRISPRa", 1)}


def main():
    src = sqlite3.connect(SRC)
    rows = src.execute("""
        SELECT m.SCREEN_ID, m.METHODOLOGY, m.CELL_LINE, m.COVERAGE_TYPE, m.SCORES_SIZE,
               c.assay_domain, c.condition_class, c.condition_name, c.readout_type
        FROM screen_metadata m
        JOIN screen_metadata_curated c ON c.screen_id = m.SCREEN_ID
        WHERE m.ORGANISM_OFFICIAL = 'Homo sapiens'
    """).fetchall()
    # Per-screen count of genes that are actually USABLE downstream, i.e. have a non-null
    # PERCENTILE_SCORE. COUNT(*) would also count rows a quarantined/degenerate screen still has
    # (screen 1742: 19,481 rows, every percentile NULL) — such a screen would then clear the
    # `n_genes >= 15000` genome-wide gate, be selected as a context screen, contribute nothing, and
    # still inflate the n_scr denominator behind the min-coverage gate.
    ngene = dict(src.execute(
        "SELECT SCREEN_ID, COUNT(PERCENTILE_SCORE) FROM harmonized_scores GROUP BY SCREEN_ID"))
    src.close()

    net = sqlite3.connect(NET)
    net.executescript("""
        DROP TABLE IF EXISTS net_screen;
        CREATE TABLE net_screen (
            screen_id       TEXT PRIMARY KEY,
            assay_domain    TEXT,
            condition_class TEXT,
            mechanism       TEXT,          -- drug mechanism bucket, or NULL
            condition_name  TEXT,
            modality        TEXT,          -- KO / CRISPRi / CRISPRa
            sm_sign         INTEGER,       -- +1 CRISPRa, -1 KO/CRISPRi (dosage sign)
            coverage_type   TEXT,          -- FULL vs HIT_ONLY (measured vs undefined_absent)
            cell_line       TEXT,
            readout_type    TEXT,
            n_genes         INTEGER
        );
    """)
    out = []
    for sid, meth, cell, cov, size, dom, cclass, cname, readout in rows:
        mod, sign = MODALITY.get(meth, (meth or "unknown", 0))
        mech = bucket(cname) if cclass == "drug" else None
        out.append((sid, dom, cclass, mech, cname, mod, sign, cov, cell, readout,
                    ngene.get(sid, 0)))
    net.executemany("INSERT OR REPLACE INTO net_screen VALUES (?,?,?,?,?,?,?,?,?,?,?)", out)
    net.execute("CREATE INDEX ix_ns_dom ON net_screen(assay_domain)")
    net.execute("CREATE INDEX ix_ns_mech ON net_screen(mechanism)")
    net.commit()

    n = net.execute("SELECT COUNT(*) FROM net_screen").fetchone()[0]
    print(f"DONE — net_screen: {n:,} human screens\n")
    for col in ("assay_domain", "modality", "coverage_type"):
        print(f"  by {col}:")
        for r in net.execute(f"SELECT {col}, COUNT(*) FROM net_screen GROUP BY {col} ORDER BY 2 DESC"):
            print(f"     {r[1]:>5}  {r[0]}")
    nmech = net.execute("SELECT COUNT(*) FROM net_screen WHERE mechanism IS NOT NULL").fetchone()[0]
    ndrug = net.execute("SELECT COUNT(*) FROM net_screen WHERE condition_class='drug'").fetchone()[0]
    print(f"\n  drug screens with a mechanism bucket: {nmech}/{ndrug}")
    print("  top mechanism buckets:")
    for r in net.execute("SELECT mechanism, COUNT(*) FROM net_screen WHERE mechanism IS NOT NULL "
                         "GROUP BY mechanism ORDER BY 2 DESC LIMIT 8"):
        print(f"     {r[1]:>4}  {r[0]}")
    net.close()


if __name__ == "__main__":
    main()

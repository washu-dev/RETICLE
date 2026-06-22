"""
RETICLE — Harmonization sanity check.

Core-essential genes (ribosome, RNA Pol II, proteasome, splicing) MUST land at
the NEGATIVE extreme (percentile ~ -1) in every viability / negative-selection
screen, regardless of the analysis method (CERES, BAGEL, Log2FC, ...).

If a method's average percentile for these genes is positive, that method's sign
convention is inverted — this is exactly the bug that flipped all CERES screens
in the previous pipeline.

Run after harmonize_scores.py:  python3 validate_harmonization.py
"""

import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths

DB = str(paths.DB)

CORE_ESSENTIAL = ["POLR2A", "POLR2L", "RPL3", "RPL4", "RPS11", "EIF4A3",
                  "PSMB3", "PSMA1", "SNRNP200", "CDK1"]

# In negative-selection viability screens, essential genes must be strongly
# negative; we fail if the per-method mean percentile is above this.
FAIL_THRESHOLD = 0.0


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    placeholders = ",".join("?" * len(CORE_ESSENTIAL))

    q = f"""
        SELECT m.ANALYSIS,
               COUNT(*)                          AS n_obs,
               ROUND(AVG(h.PERCENTILE_SCORE), 3) AS avg_pct,
               ROUND(AVG(h.HARMONIZED_SCORE), 3) AS avg_harm
        FROM harmonized_scores h
        JOIN screen_metadata m ON h.SCREEN_ID = m.SCREEN_ID
        WHERE h.GENE_SYMBOL IN ({placeholders})
          AND m.SCREEN_TYPE = 'Negative Selection'
          AND m.METHODOLOGY = 'Knockout'
          AND h.PERCENTILE_SCORE IS NOT NULL
          -- Restrict to genuine viability/proliferation screens, where core-
          -- essential genes MUST deplete. Specialized "negative selection"
          -- screens (e.g. genotoxic/UV resistance) legitimately leave essential
          -- genes mid-distribution and would otherwise be false positives.
          AND (
                LOWER(m.PHENOTYPE)         LIKE '%prolifer%'
             OR LOWER(m.PHENOTYPE)         LIKE '%viab%'
             OR LOWER(m.PHENOTYPE)         LIKE '%fitness%'
             OR LOWER(m.PHENOTYPE)         LIKE '%growth%'
             OR LOWER(m.PHENOTYPE)         LIKE '%essential%'
             OR LOWER(m.SCREEN_RATIONALE)  LIKE '%essential%'
          )
        GROUP BY m.ANALYSIS
        HAVING n_obs >= 20
        ORDER BY n_obs DESC
    """
    rows = cur.execute(q, CORE_ESSENTIAL).fetchall()

    print("Core-essential genes in KO negative-selection screens")
    print("(expect avg percentile strongly NEGATIVE, ~ -1)\n")
    print(f"{'ANALYSIS':24s} {'n':>6} {'avg_pct':>9} {'avg_harm':>10}  status")
    print("-" * 64)

    failures = []
    for analysis, n, pct, harm in rows:
        ok = pct is not None and pct < FAIL_THRESHOLD
        status = "OK" if ok else "*** INVERTED ***"
        if not ok:
            failures.append((analysis, pct))
        print(f"{(analysis or '')[:24]:24s} {n:>6} {pct!s:>9} {harm!s:>10}  {status}")

    con.close()
    print()
    if failures:
        print(f"FAIL: {len(failures)} analysis method(s) have inverted sign: "
              f"{', '.join(a for a, _ in failures)}")
        sys.exit(1)
    print("PASS: all methods place core-essential genes on the negative axis.")


if __name__ == "__main__":
    main()

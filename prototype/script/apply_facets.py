"""
apply_facets.py — write the merged facets into screen_metadata_curated.
=======================================================================
Reads processed_data/condition_facets_final.csv and applies it to the local
SQLite `screen_metadata_curated`:
  * UPDATE assay_domain   (the 107 re-classifications: immune/drug/signal -> stress, ...)
  * ADD + populate facet columns: condition_class, growth_direction,
    readout_type, sign_convention  (for the app's facet-aware labels / filters)

harmonized_scores is NOT touched — the sign check found no genuine flips, so the
28 M scores stand. Only this 2,157-row metadata table changes.

  python3 script/apply_facets.py
"""

import csv
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import paths

FINAL = paths.PROCESSED_DATA / "condition_facets_final.csv"
NEW_COLS = ["condition_class", "growth_direction", "readout_type", "sign_convention", "condition_name"]


def main():
    rows = list(csv.DictReader(open(FINAL)))
    # the specific stressor name lives in the rule-layer CSV (condition_facets.csv)
    names = {r["screen_id"]: r.get("condition_name", "")
             for r in csv.DictReader(open(paths.PROCESSED_DATA / "condition_facets.csv"))}
    con = sqlite3.connect(str(paths.DB))
    cur = con.cursor()

    have = {c[1] for c in cur.execute("PRAGMA table_info(screen_metadata_curated)")}
    for col in NEW_COLS:
        if col not in have:
            cur.execute(f"ALTER TABLE screen_metadata_curated ADD COLUMN {col} TEXT")

    # screen_id may be stored as int or text — match on the text form
    changed = matched = 0
    for r in rows:
        sid = r["screen_id"]
        cur.execute("SELECT assay_domain FROM screen_metadata_curated WHERE CAST(screen_id AS TEXT)=?", (sid,))
        old = cur.fetchone()
        if old is None:
            continue
        matched += 1
        if old[0] != r["new_domain"]:
            changed += 1
        cur.execute(
            """UPDATE screen_metadata_curated
               SET assay_domain=?, condition_class=?, growth_direction=?,
                   readout_type=?, sign_convention=?, condition_name=?
               WHERE CAST(screen_id AS TEXT)=?""",
            (r["new_domain"], r["condition_class"], r["growth_direction"],
             r["readout_type"], r["sign_convention"], names.get(sid, ""), sid))
    con.commit()

    dist = Counter(d for (d,) in cur.execute("SELECT assay_domain FROM screen_metadata_curated"))
    con.close()
    print(f"matched {matched}/{len(rows)} screens; assay_domain changed for {changed}")
    print("assay_domain now:", dict(dist.most_common()))


if __name__ == "__main__":
    main()

"""
RETICLE — Directionality repair (registry fixes + essential-gene anchor)
========================================================================
Fixes the sign-inversion bugs surfaced by auditing core-essential genes
(POLR2A, ribosome, proteasome, …) which MUST sit at the negative extreme in any
knockout viability/stress screen.

Two phases, both non-destructive (only touch affected screens):

  Phase 1 — RECOMPUTE the screens whose SCORE.k_TYPE was reclassified in
            harmonize_scores.py (Dependency score, Essentiality Score, Mean
            Depletion, and the SIG_MAG columns now detected as signed: RSA / CGI /
            CasTLE Score). Re-read raw, recompute with the fixed logic, replace rows.

  Phase 2 — ESSENTIAL-GENE ANCHOR over every fitness/stress KO screen. The score
            type name cannot encode per-screen sign conventions (Z-score, RSA,
            Mean Depletion vary by author), so the only reliable authority is the
            data: if the core-essential panel lands on the POSITIVE side, the
            screen's sign is inverted -> flip it (exact negation of harmonized /
            percentile / robust-z).

Idempotent: re-running recomputes from raw and re-checks the anchor; once a screen
is correct (essentials negative) it is left alone.

  python3 script/fix_directionality.py --dry-run
  python3 script/fix_directionality.py
"""

import argparse
import glob
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import paths
import harmonize_scores as H

CORE_ESSENTIAL = [
    # human (uppercase) + mouse orthologs (title-case); GENE_SYMBOL match is
    # case-sensitive, and each screen only contains its own organism's symbols.
    "POLR2A", "POLR2L", "RPL3", "RPL4", "RPS11", "EIF4A3",
    "PSMB3", "PSMA1", "SNRNP200", "CDK1", "RPS3", "RPL7", "SF3B1", "U2AF1", "RPL23A",
    "Polr2a", "Polr2l", "Rpl3", "Rpl4", "Rps11", "Eif4a3",
    "Psmb3", "Psma1", "Snrnp200", "Cdk1", "Rps3", "Rpl7", "Sf3b1", "U2af1", "Rpl23a",
]

# screens whose harmonization changed because the registry/clip logic was fixed
CHANGED_TYPES = ["Dependency score", "Mean Depletion", "Essentiality Score"]
CHANGED_SIGMAG = ["RSA", "CGI", "CasTLE Score"]   # now detected as signed when applicable

ANCHOR_MIN_ESS = 3     # need at least this many measured core-essential genes
ANCHOR_THRESH = 0.0    # essential-panel mean above this => inverted


def load_meta():
    meta = {}
    for _, p in paths.BIOGRID_METADATA.items():
        if p.exists():
            for sid, v in json.loads(p.read_text()).items():
                meta[str(sid)] = v[0] if isinstance(v, list) else v
    return meta


def raw_path(sid):
    hits = glob.glob(os.path.join(str(paths.RAW_BIOGRID), f"screenings/*/*SCREEN_{sid}-*"))
    return hits[0] if hits else None


def perturbation_mult(meta):
    methodology = (meta.get("METHODOLOGY") or "").upper()
    library = (meta.get("LIBRARY_TYPE") or "").upper()
    return -1 if ("ACTIVATION" in methodology or "CRISPRA" in library) else 1


def recompute_rows(sid, meta):
    """Re-harmonize one screen from raw with the (fixed) logic. Returns
    (out_df, basis, is_dir) or (None, None, None)."""
    rp = raw_path(sid)
    if not rp:
        return None, None, None
    df, col_types = H.load_screen_df(rp, meta)
    if df is None:
        return None, None, None
    s_raw, basis, is_dir = H.resolve_s_raw(df, col_types, (meta.get("SCREEN_TYPE") or "").strip())
    df["HARMONIZED_SCORE"] = s_raw * perturbation_mult(meta)
    H.add_rank_columns(df)
    df["IS_HIT"] = (df["HIT"].astype(str).str.strip().str.upper() == "YES").astype(int)
    return df, basis, is_dir


def write_rows(con, sid, df):
    con.execute("DELETE FROM harmonized_scores WHERE SCREEN_ID=?", (sid,))
    out = df[["OFFICIAL_SYMBOL", "HARMONIZED_SCORE", "PERCENTILE_SCORE",
              "ROBUST_Z_SCORE", "IS_HIT"]].copy()
    out.insert(0, "SCREEN_ID", str(sid))
    out.columns = ["SCREEN_ID", "GENE_SYMBOL", "HARMONIZED_SCORE",
                   "PERCENTILE_SCORE", "ROBUST_Z_SCORE", "IS_HIT"]
    out["GENE_SYMBOL"] = out["GENE_SYMBOL"].astype(str)
    out["IS_HIT"] = out["IS_HIT"].astype(int)
    out.to_sql("harmonized_scores", con, if_exists="append", index=False)


def essential_mean(con, sid):
    ph = ",".join("?" * len(CORE_ESSENTIAL))
    row = con.execute(
        f"""SELECT AVG(PERCENTILE_SCORE), COUNT(*) FROM harmonized_scores
            WHERE SCREEN_ID=? AND GENE_SYMBOL IN ({ph}) AND PERCENTILE_SCORE IS NOT NULL""",
        [sid] + CORE_ESSENTIAL).fetchone()
    return (row[0], row[1]) if row and row[1] else (None, 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    meta = load_meta()
    con = sqlite3.connect(str(paths.DB))

    # ---- candidate screens for Phase 1 (registry-changed types) ----
    like = " OR ".join(["SCORE_BASIS LIKE ?"] * (len(CHANGED_TYPES) + len(CHANGED_SIGMAG)))
    params = [f"%{t}%" for t in CHANGED_TYPES] + [f"%SIG_MAG({t})%" for t in CHANGED_SIGMAG]
    changed = [str(r[0]) for r in con.execute(
        f"SELECT SCREEN_ID FROM screen_metadata WHERE {like}", params).fetchall()]
    print(f"Phase 1 — recompute {len(changed)} screens (reclassified score types)")

    recomputed = 0
    for sid in changed:
        m = meta.get(sid)
        if not m:
            continue
        df, basis, is_dir = recompute_rows(sid, m)
        if df is None:
            continue
        if not args.dry_run:
            write_rows(con, sid, df)
            con.execute("UPDATE screen_metadata SET SCORE_BASIS=?, IS_DIRECTIONAL=? WHERE SCREEN_ID=?",
                        (basis, int(is_dir), sid))
        recomputed += 1
    if not args.dry_run:
        con.commit()
    print(f"          recomputed: {recomputed}")

    # ---- Phase 2: essential-gene anchor over FITNESS KO screens only ----
    # The anchor (core-essential genes MUST be strongly negative) holds for baseline
    # viability/fitness screens. It does NOT hold for STRESS screens: under an applied
    # pressure essential genes deplete in BOTH arms and cancel, so they legitimately
    # sit near 0 (the stress distribution is centred at 0, not -1). Flipping stress on
    # this basis would CREATE errors, so stress is excluded here.
    targets = [str(r[0]) for r in con.execute(
        """SELECT m.SCREEN_ID FROM screen_metadata m
           JOIN screen_metadata_curated c ON m.SCREEN_ID=c.screen_id
           WHERE m.METHODOLOGY='Knockout' AND c.assay_domain='fitness'"""
    ).fetchall()]
    print(f"\nPhase 2 — essential-gene anchor over {len(targets)} FITNESS KO screens (stress excluded)")

    flipped = []
    for sid in targets:
        em, n = essential_mean(con, sid)
        if n >= ANCHOR_MIN_ESS and em is not None and em > ANCHOR_THRESH:
            flipped.append((sid, em, n))
            if not args.dry_run:
                con.execute(
                    """UPDATE harmonized_scores
                       SET HARMONIZED_SCORE=-HARMONIZED_SCORE,
                           PERCENTILE_SCORE=-PERCENTILE_SCORE,
                           ROBUST_Z_SCORE = CASE WHEN ROBUST_Z_SCORE IS NULL THEN NULL
                                                 ELSE -ROBUST_Z_SCORE END
                       WHERE SCREEN_ID=?""", (sid,))
                con.execute(
                    "UPDATE screen_metadata SET SCORE_BASIS = SCORE_BASIS || ' [ANCHOR_FLIP]', "
                    "IS_DIRECTIONAL=1 WHERE SCREEN_ID=?", (sid,))
    if not args.dry_run:
        con.commit()

    print(f"          inverted screens flipped: {len(flipped)}")
    for sid, em, n in sorted(flipped, key=lambda x: -x[1])[:25]:
        cl = con.execute("SELECT CELL_LINE, SCORE_BASIS FROM screen_metadata WHERE SCREEN_ID=?",
                         (sid,)).fetchone()
        print(f"            screen {sid:5} ess_mean was {em:+.2f} (n={n})  {cl[0][:16]:16} | {cl[1][:46]}")

    con.close()
    print(f"\n{'(dry-run) ' if args.dry_run else ''}done. "
          f"Phase1 recomputed={recomputed}  Phase2 flipped={len(flipped)}")
    if not args.dry_run:
        print("Next: python3 script/validate_harmonization.py")


if __name__ == "__main__":
    main()

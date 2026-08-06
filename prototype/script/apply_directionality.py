"""
RETICLE — Apply Directionality Overrides (non-destructive, in-place)
====================================================================
Reads the frozen artifact processed_data/directionality_overrides.json (only the entries with
status=="auto"), RE-HARMONIZES those screens FROM THE RAW FILES, replaces their rows in
harmonized_scores in place, and updates SCORE_BASIS / IS_DIRECTIONAL in screen_metadata.

WHY NOT JUST RE-RUN harmonize_scores.py
---------------------------------------
  harmonize_scores.py's main() does os.remove() on the entire 2.2 GB database -- taking
  correlation_analysis and screen_metadata_curated with it. This script touches only the rows
  belonging to the ~100 screens an override names; the rest of the 28M rows, and every other
  table, are left alone.

IDEMPOTENCE
-----------
  Every run recomputes from the raw data under the override and REPLACEs, so repeated runs give
  the same result -- there is no "flipped twice, back where it started" hazard. Note that only
  screens with status=="auto" are processed: a screen demoted to needs_review is NOT restored to
  the AMBIGUOUS default automatically (that would need a full harmonize re-run).

RUN
---
  python3 script/apply_directionality.py --dry-run    # compute and report, write nothing
  python3 script/apply_directionality.py              # apply in place
"""

import argparse
import glob
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import paths
import harmonize_scores as H

CORE_ESSENTIAL = ["POLR2A", "POLR2L", "RPL3", "RPL4", "RPS11", "EIF4A3",
                  "PSMB3", "PSMA1", "SNRNP200", "CDK1"]

# Screens where core-essential genes are a VALID negative-end control: a knockout
# viability/proliferation/fitness screen. Only for these do we let the essential
# genes veto the LLM direction (a reporter/FACS screen leaves them mid-distribution).
_VIABILITY_KEYS = ("prolifer", "viab", "fitness", "growth", "essential", "dropout", "depletion")


def is_viability_ko(meta: dict) -> bool:
    if (meta.get("METHODOLOGY") or "").strip().lower() != "knockout":
        return False
    text = ((meta.get("PHENOTYPE") or "") + " " + (meta.get("SCREEN_RATIONALE") or "")).lower()
    return any(k in text for k in _VIABILITY_KEYS)


def load_auto_overrides():
    if not H.OVERRIDES_PATH.exists():
        sys.exit(f"{H.OVERRIDES_PATH} not found - run directionality_mapper.py to generate it first.")
    data = json.loads(H.OVERRIDES_PATH.read_text())
    return {str(s): ov for s, ov in data.get("overrides", {}).items()
            if ov.get("status") == "auto"}


def build_raw_index():
    """screen_id -> raw .tab path."""
    idx = {}
    for f in glob.glob(os.path.join(str(paths.RAW_BIOGRID), "screenings/*/*")):
        base = os.path.basename(f)
        if "SCREEN_INDEX" in base or not os.path.isfile(f):
            continue
        import re
        m = re.search(r"SCREEN_(\d+)-", base)
        if m:
            idx[m.group(1)] = f
    return idx


def load_meta():
    meta = {}
    for _, p in paths.BIOGRID_METADATA.items():
        if not p.exists():
            continue
        for sid, entries in json.loads(p.read_text()).items():
            if entries:
                meta[str(sid)] = entries[0]
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="compute and report; write nothing")
    ap.add_argument("--anchor-resolve-conflicts", action="store_true",
                    help="resolve a direction conflict in a KO viability screen using core "
                         "essential genes as deterministic ground truth: pick the sign that puts "
                         "them on the negative end, and write that decision back to overrides.json")
    args = ap.parse_args()

    overrides = load_auto_overrides()
    if not overrides:
        print("No status=='auto' entries in overrides.json - nothing to do.")
        return
    raw_idx = build_raw_index()
    meta_idx = load_meta()

    con = sqlite3.connect(str(paths.DB))
    print(f"Applying {len(overrides)} auto overrides"
          + (" (dry-run - nothing written)" if args.dry_run else "") + "\n")

    applied = skipped = 0
    conflicts = []
    anchor_updates = {}            # screen_id -> new override entry (anchor-resolved)
    for sid, ov in sorted(overrides.items(), key=lambda kv: int(kv[0])):
        raw = raw_idx.get(sid)
        meta = meta_idx.get(sid)
        if raw is None or meta is None:
            print(f"  ! screen {sid}: raw file or metadata not found - skipped")
            skipped += 1
            continue

        df, col_types = H.load_screen_df(raw, meta)
        if df is None:
            print(f"  ! screen {sid}: raw file could not be read - skipped")
            skipped += 1
            continue

        df["HARMONIZED_SCORE"], basis, is_dir = H.apply_override(df, col_types, ov)
        H.add_rank_columns(df)
        df["IS_HIT"] = (df["HIT"].astype(str).str.strip().str.upper() == "YES").astype(int)

        old = con.execute("SELECT SCORE_BASIS FROM screen_metadata WHERE SCREEN_ID=?",
                          (sid,)).fetchone()
        old_basis = old[0] if old else "?"

        # Core-essential veto gate. Only meaningful in a KO viability/proliferation screen,
        # where essential genes MUST land on the negative end. If the override puts them on the
        # positive end the direction was ruled backwards: refuse to apply, and list the screen as
        # a conflict for a human (or a different model) to settle.
        ess = df[df["OFFICIAL_SYMBOL"].astype(str).isin(CORE_ESSENTIAL)]
        ess_p = ess["PERCENTILE_SCORE"].dropna()
        ess_note = f"  ess_genes={len(ess_p)} mean_pct={ess_p.mean():.3f}" if len(ess_p) else ""
        is_conflict = (is_viability_ko(meta) and len(ess_p) >= 3 and ess_p.mean() > 0)

        mode_desc = (f"SINGLE sign={ov['sign']}" if ov["mode"] == "SINGLE"
                     else f"PAIR +{ov['positive_column']}/-{ov['negative_column']}")
        flag = "  x CONFLICT (essential genes on the positive end - refused)" if is_conflict else ""
        print(f"  screen {sid}: {mode_desc} conf={ov['confidence']:.2f}  "
              f"rows={len(df)}{ess_note}{flag}")
        print(f"      basis: {old_basis}  ->  {basis}")

        if is_conflict:
            if not args.anchor_resolve_conflicts:
                conflicts.append((sid, ess_p.mean(), mode_desc))
                skipped += 1
                continue
            # --- deterministic anchor resolution: pin essential genes to negative ---
            # is_final => the value came from a DIRECTIONAL score-semantics override, whose sign was
            # already fixed against this same essential-gene anchor during the forensic resolution
            # (see harmonize_scores.sign_is_final). Re-deriving it here would just re-litigate a
            # stronger, already-recorded decision, so keep the sign as given.
            mag, tstr, is_final = H._primary_magnitude(df, col_types, sid)
            if is_final:
                anchor_sign = 1
                df["HARMONIZED_SCORE"] = mag
                H.add_rank_columns(df)
            else:
                df["HARMONIZED_SCORE"] = mag            # try +1
                H.add_rank_columns(df)
                e2 = df[df["OFFICIAL_SYMBOL"].astype(str).isin(CORE_ESSENTIAL)]["PERCENTILE_SCORE"].dropna()
                anchor_sign = -1 if e2.mean() > 0 else 1
                df["HARMONIZED_SCORE"] = mag * anchor_sign
                H.add_rank_columns(df)
            new_ess = df[df["OFFICIAL_SYMBOL"].astype(str).isin(CORE_ESSENTIAL)]["PERCENTILE_SCORE"].dropna()
            basis = f"ANCHOR_SINGLE({tstr})xsign={anchor_sign:+d}[essential-gene ground truth]"
            is_dir = True
            anchor_updates[sid] = {
                "mode": "SINGLE", "sign": anchor_sign,
                "positive_column": None, "negative_column": None,
                "confidence": 1.0,
                "evidence": "core-essential genes pinned to negative axis (deterministic ground truth; "
                            f"overrides LLM's {mode_desc})",
                "status": "auto", "resolution": "essential-gene-anchor",
                "is_unresolved": False, "score_layout": ov.get("score_layout", {}),
                "llm_model": ov.get("llm_model"), "prompt_version": ov.get("prompt_version"),
            }
            print(f"      ↳ anchor-resolved: SINGLE sign={anchor_sign:+d}  "
                  f"ess_mean_pct now {new_ess.mean():+.3f}")

        if not args.dry_run:
            con.execute("DELETE FROM harmonized_scores WHERE SCREEN_ID=?", (sid,))
            out = df[["OFFICIAL_SYMBOL", "HARMONIZED_SCORE",
                      "PERCENTILE_SCORE", "ROBUST_Z_SCORE", "IS_HIT"]].copy()
            out.insert(0, "SCREEN_ID", str(sid))
            out.columns = ["SCREEN_ID", "GENE_SYMBOL", "HARMONIZED_SCORE",
                           "PERCENTILE_SCORE", "ROBUST_Z_SCORE", "IS_HIT"]
            out["GENE_SYMBOL"] = out["GENE_SYMBOL"].astype(str)
            out["IS_HIT"] = out["IS_HIT"].astype(int)
            out.to_sql("harmonized_scores", con, if_exists="append", index=False)
            con.execute(
                "UPDATE screen_metadata SET SCORE_BASIS=?, IS_DIRECTIONAL=? WHERE SCREEN_ID=?",
                (basis, int(is_dir), sid))
        applied += 1

    if not args.dry_run:
        con.commit()
    con.close()

    # Write the anchor decisions back into the frozen artifact, so a future harmonize rebuild
    # reproduces exactly this result
    if anchor_updates and not args.dry_run:
        data = json.loads(H.OVERRIDES_PATH.read_text())
        data["overrides"].update(anchor_updates)
        data.setdefault("_meta", {})["anchor_resolved"] = sorted(anchor_updates, key=int)
        H.OVERRIDES_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        print(f"\n-> wrote {len(anchor_updates)} anchor decisions back to {H.OVERRIDES_PATH.name}")

    print(f"\n{'(dry-run) would apply' if args.dry_run else 'applied'}: {applied}   "
          f"skipped/conflicted: {skipped}   anchor corrections: {len(anchor_updates)}")
    if conflicts:
        print(f"\nx {len(conflicts)} direction conflicts (essential genes on the positive end - not applied):")
        for sid, mp, desc in conflicts:
            print(f"    screen {sid}: {desc}  essential-gene mean_pct={mp:+.3f}")
    if not args.dry_run:
        print("\nSuggested next step: python3 script/validate_harmonization.py")


if __name__ == "__main__":
    main()

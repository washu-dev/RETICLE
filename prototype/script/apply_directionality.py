"""
RETICLE — Apply Directionality Overrides (non-destructive, in-place)
====================================================================
读取冻结产物 processed_data/directionality_overrides.json（status=="auto" 的条目），
对这些 screen **从原始文件重新 harmonize**，就地替换它们在 harmonized_scores 的行，
并更新 screen_metadata 的 SCORE_BASIS / IS_DIRECTIONAL。

为什么不直接重跑 harmonize_scores.py
-----------------------------------
  harmonize_scores.py 的 main() 会 os.remove() 整个 2.2GB 库（连 correlation_analysis
  和 screen_metadata_curated 一起删）。本脚本只动 override 涉及的那 ~100 个 screen 的
  行，28M 行里的其余部分、以及别的表，一律不碰。

幂等性
------
  每次都从原始数据按 override 重算后 REPLACE，重复运行结果一致，不存在「翻转两次又翻
  回去」的风险。注意：本脚本只处理 overrides.json 里 status=="auto" 的 screen；
  被降级为 needs_review 的 screen 不会被自动恢复成 AMBIGUOUS 默认（那需要重跑 harmonize）。

RUN
---
  python3 script/apply_directionality.py --dry-run    # 算并报告，不写库
  python3 script/apply_directionality.py              # 就地应用
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
        sys.exit(f"找不到 {H.OVERRIDES_PATH} —— 先跑 directionality_mapper.py 生成它。")
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
    ap.add_argument("--dry-run", action="store_true", help="算并报告，不写库")
    ap.add_argument("--anchor-resolve-conflicts", action="store_true",
                    help="对 KO 活力筛的方向冲突，用核心必需基因（确定性 ground truth）"
                         "定向：把符号设为使必需基因落负端的那个，并把决定写回 overrides.json")
    args = ap.parse_args()

    overrides = load_auto_overrides()
    if not overrides:
        print("overrides.json 里没有 status=='auto' 的条目，无事可做。")
        return
    raw_idx = build_raw_index()
    meta_idx = load_meta()

    con = sqlite3.connect(str(paths.DB))
    print(f"将应用 {len(overrides)} 个 auto override"
          + ("（dry-run，不写库）" if args.dry_run else "") + "\n")

    applied = skipped = 0
    conflicts = []
    anchor_updates = {}            # screen_id -> new override entry (anchor-resolved)
    for sid, ov in sorted(overrides.items(), key=lambda kv: int(kv[0])):
        raw = raw_idx.get(sid)
        meta = meta_idx.get(sid)
        if raw is None or meta is None:
            print(f"  ! screen {sid}: 找不到原始文件或 metadata，跳过")
            skipped += 1
            continue

        df, col_types = H.load_screen_df(raw, meta)
        if df is None:
            print(f"  ! screen {sid}: 原始文件读取失败，跳过")
            skipped += 1
            continue

        df["HARMONIZED_SCORE"], basis, is_dir = H.apply_override(df, col_types, ov)
        H.add_rank_columns(df)
        df["IS_HIT"] = (df["HIT"].astype(str).str.strip().str.upper() == "YES").astype(int)

        old = con.execute("SELECT SCORE_BASIS FROM screen_metadata WHERE SCREEN_ID=?",
                          (sid,)).fetchone()
        old_basis = old[0] if old else "?"

        # 核心必需基因否决闸：只在 KO 活力/增殖筛里有效。这类筛必需基因必然在负端，
        # 若 override 让它们落到正端 -> 方向被判反 -> 拒绝应用，列入冲突清单等人工/换模型。
        ess = df[df["OFFICIAL_SYMBOL"].astype(str).isin(CORE_ESSENTIAL)]
        ess_p = ess["PERCENTILE_SCORE"].dropna()
        ess_note = f"  ess_genes={len(ess_p)} mean_pct={ess_p.mean():.3f}" if len(ess_p) else ""
        is_conflict = (is_viability_ko(meta) and len(ess_p) >= 3 and ess_p.mean() > 0)

        mode_desc = (f"SINGLE sign={ov['sign']}" if ov["mode"] == "SINGLE"
                     else f"PAIR +{ov['positive_column']}/-{ov['negative_column']}")
        flag = "  ✗CONFLICT(必需基因在正端，拒绝应用)" if is_conflict else ""
        print(f"  screen {sid}: {mode_desc} conf={ov['confidence']:.2f}  "
              f"rows={len(df)}{ess_note}{flag}")
        print(f"      basis: {old_basis}  ->  {basis}")

        if is_conflict:
            if not args.anchor_resolve_conflicts:
                conflicts.append((sid, ess_p.mean(), mode_desc))
                skipped += 1
                continue
            # --- deterministic anchor resolution: pin essential genes to negative ---
            mag, tstr = H._primary_magnitude(df, col_types)
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

    # 把锚点决定写回冻结产物，保证未来重建 harmonize 时复现同一结果
    if anchor_updates and not args.dry_run:
        data = json.loads(H.OVERRIDES_PATH.read_text())
        data["overrides"].update(anchor_updates)
        data.setdefault("_meta", {})["anchor_resolved"] = sorted(anchor_updates, key=int)
        H.OVERRIDES_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        print(f"\n↳ 已把 {len(anchor_updates)} 个锚点决定写回 {H.OVERRIDES_PATH.name}")

    print(f"\n{'(dry-run) 将应用' if args.dry_run else '已应用'}: {applied}   "
          f"跳过/冲突: {skipped}   锚点纠正: {len(anchor_updates)}")
    if conflicts:
        print(f"\n✗ {len(conflicts)} 个方向冲突（必需基因落正端，未应用）:")
        for sid, mp, desc in conflicts:
            print(f"    screen {sid}: {desc}  必需基因 mean_pct={mp:+.3f}")
    if not args.dry_run:
        print("\n建议接着跑：python3 script/validate_harmonization.py")


if __name__ == "__main__":
    main()

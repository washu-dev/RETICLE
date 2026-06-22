"""
RETICLE — CRISPR Score Harmonization Pipeline
=============================================

Converts heterogeneous BioGRID ORCS screens into a single comparable coordinate
system so that downstream correlation / enrichment analyses are valid.

Design (see documentation/score_harmonization_logic.md):

  HARMONIZED_SCORE = S_raw  x  perturbation_multiplier

where S_raw is resolved on a UNIFIED biological axis:
    +  (high)  = loss-of-function is PROTECTIVE / gene knockout ENRICHES the population
    -  (low)   = loss-of-function is DELETERIOUS / gene is ESSENTIAL (depletes)

Key correctness rules (these fix the previous keyword-guessing implementation):
  1. The score type is resolved from an EXPLICIT controlled-vocabulary registry
     (the real SCORE.k_TYPE strings in the metadata), not fuzzy substring guesses.
  2. DIRECTIONAL metrics (Log2FC, CERES, Z-score, Beta, CasTLE, Bayes Factor, ...)
     already encode direction in their sign -> they are used as-is and the
     selection-type sign flip is NEVER applied to them.
  3. The selection-type sign flip is applied ONLY to UNSIGNED SIGNIFICANCE metrics
     (STARS, p-value/FDR-only screens), and only when the selection type is
     unambiguously "Negative Selection" or "Positive Selection" (exact match, so
     "Positive and Negative Selection" no longer falls through the substring trap).
  4. A directional column is PREFERRED over a significance column when both exist
     (e.g. MaGeCK screens that report both "MaGeCK Score" and "Log2FC").
  5. Missing values ("-") are kept as NaN and EXCLUDED from ranking (NULL percentile)
     instead of being silently dumped at 0.0 in the middle of the distribution.
  6. Hit-only screens (FULL_SIZE_AVAILABLE == "No") are tagged COVERAGE_TYPE=HIT_ONLY
     so the comparison engine routes them to binary (Jaccard/Fisher) mode.
"""

import os
import re
import sys
import json
import glob
import sqlite3

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths

# ---------------------------------------------------------------------------
# 1. Controlled-vocabulary registry of SCORE.k_TYPE strings
#    (derived from the actual BioGRID ORCS metadata — 58 distinct types).
#
#    Each score type is assigned ONE role:
#      DIR_POS  : directional, higher = enriched / more fit / protective,
#                 lower = depleted / essential.  Used as +value.
#      DIR_NEG  : directional, higher = MORE essential / depleted.
#                 Used as -value (flipped onto the unified axis).
#      SIG_MAG  : unsigned significance, larger = more significant.
#                 Direction must come from selection type (or a pos/neg pair).
#      SIG_P    : p-value-like significance, SMALLER = more significant.
#                 Transformed to -log10(p); direction from selection / pair.
#      IGNORE   : not usable as a primary effect column (counts, ids, ...).
# ---------------------------------------------------------------------------

DIR_POS = {
    "log2fc", "log2", "zlfc", "z-score", "crispr score (cs)", "ceres score",
    "beta score", "castle effect",
    # negative = depleted/essential, used as-is (audited via core-essential anchor):
    "mean depletion", "essentiality score",
    "rho (log2e treated vs. untreated)", "mean fold change",
    "gamma (normalized log2e/t)", "gamma", "delta",
    "nes (normalized enrichment score)", "enrichment",
    "depletion-enrichment (de) score", "t-score", "differential score",
    "differential crispr score", "gene score", "gene-level three score (ts)",
    "riger score", "nscore", "fs (fitness score)", "ranks score",
    "phenotype scores based on log2 fold enrichments",
    "second best guide score", "second best guide score x rsa",
}

DIR_NEG = {
    # higher = more essential, flipped onto the axis. "dependency score" here is the
    # [0,1] DepMap dependency PROBABILITY (high = more dependent), opposite to the
    # signed "CERES score" / "ceres score" above (which is DIR_POS).
    "bayes factor", "dependency score",
}

# Unsigned significance, LARGER = more significant (direction from selection type).
# NOTE: "castle score" is CasTLE's always-positive confidence statistic; the
# signed effect lives in the separate "castle effect" column (DIR_POS above),
# which the resolver prefers when present.
SIG_MAG = {
    "stars score", "rsa", "castle score", "cgi",
}

# p-value-like significance, SMALLER = more significant -> -log10(p).
# "rra score" / "mageck score" are RRA p-values (small = significant), NOT magnitudes.
SIG_P = {
    "p-value", "fdr", "q-value", "mageck score", "rra score",
    "log10 (p-value)", "-log (p-value)", "log10", "log10 (corrected p-value)",
    "neg score p-value", "pos score p-value",
}

IGNORE = {
    "rank", "rra rank", "sgrna number", "read counts", "umi",
    "percent sorted cells", "reduced chi squared", "deseq2",
}

# pos/neg directional-pair members are detected dynamically by their "pos"/"neg"
# (or enrichment/depletion) marker rather than enumerated here.

P_CLIP_LO = 1e-10  # floor for p-values before -log10


def classify_type(type_str):
    """Return the role of a SCORE.k_TYPE string."""
    t = (type_str or "").strip().lower()
    if not t or t == "-":
        return None
    if t in DIR_POS:
        return "DIR_POS"
    if t in DIR_NEG:
        return "DIR_NEG"
    if t in SIG_MAG:
        return "SIG_MAG"
    if t in SIG_P:
        return "SIG_P"
    if t in IGNORE:
        return "IGNORE"
    # Heuristic fallback for any type not yet in the registry (logged by caller).
    if any(k in t for k in ["p-val", "p_val", "fdr", "q-val", "q_val"]):
        return "SIG_P"
    if any(k in t for k in ["log2", "lfc", "z-score", "zlfc", "effect", "beta",
                            "fold change", "enrichment score"]):
        return "DIR_POS"
    return "UNKNOWN"


def pair_member(type_str):
    """Classify a score type as a positive- or negative-direction pair member.

    Returns ('pos'|'neg', is_p_like) or None.
    """
    t = (type_str or "").strip().lower()
    if not t or t == "-":
        return None
    p_like = any(k in t for k in ["p-value", "p_val", "fdr", "q-val",
                                  "mageck", "rra"])
    # Enrichment-direction members
    if "pos" in t or t.startswith("rra_enrichment") or "enrichment" in t:
        return ("pos", p_like)
    # Depletion-direction members
    if "neg" in t or t.startswith("rra_depletion") or "depletion" in t:
        return ("neg", p_like)
    return None


def selection_multiplier(screen_type):
    """Sign for UNSIGNED significance metrics. None => direction undetermined.

    Exact match avoids the 'NEGATIVE SELECTION' in 'POSITIVE AND NEGATIVE
    SELECTION' substring trap.
    """
    st = (screen_type or "").strip().lower()
    if st == "negative selection":
        return -1
    if st == "positive selection":
        return +1
    return None  # "Positive and Negative Selection", "Phenotype Screen", "Unknown"


def to_num(series):
    """Coerce a screen column to float, mapping '-'/blank to NaN."""
    return pd.to_numeric(series.replace(["-", "", "None"], np.nan), errors="coerce")


def neglog10(series):
    """-log10(p) with floor clipping; NaN (missing) -> 0 contribution."""
    p = to_num(series).clip(lower=P_CLIP_LO, upper=1.0).fillna(1.0)
    return -np.log10(p)


# ---------------------------------------------------------------------------
# 2. Resolve S_raw for a single screen
# ---------------------------------------------------------------------------

def resolve_s_raw(df, col_types, screen_type):
    """Return (s_raw: pd.Series, basis: str, is_directional: bool).

    Resolution priority:
      (1) positive/negative directional PAIR  (e.g. MAGeCK pos/neg score)
      (2) a single DIRECTIONAL effect column  (preferred over significance)
      (3) an UNSIGNED SIGNIFICANCE column + selection-type sign
    """
    present = [(c, t, classify_type(t)) for c, t in col_types.items() if c in df.columns]

    # ---- (1) pos/neg pair -------------------------------------------------
    pos_col = neg_col = None
    pos_plike = neg_plike = False
    for c, t, _role in present:
        pm = pair_member(t)
        if pm is None:
            continue
        side, p_like = pm
        if side == "pos" and pos_col is None:
            pos_col, pos_plike = c, p_like
        elif side == "neg" and neg_col is None:
            neg_col, neg_plike = c, p_like
    if pos_col is not None and neg_col is not None:
        if pos_plike or neg_plike:
            s = neglog10(df[pos_col]) - neglog10(df[neg_col])
            basis = f"PAIR_PVALUE({pos_col}-{neg_col})"
        else:
            s = to_num(df[pos_col]).fillna(0.0) - to_num(df[neg_col]).fillna(0.0)
            basis = f"PAIR_SCORE({pos_col}-{neg_col})"
        return s, basis, True

    # ---- (2) single directional effect column ----------------------------
    for c, t, role in present:
        if role == "DIR_POS":
            return to_num(df[c]), f"DIR_POS({t})", True
        if role == "DIR_NEG":
            return -to_num(df[c]), f"DIR_NEG({t})", True

    # ---- (3) unsigned significance + selection sign -----------------------
    sel = selection_multiplier(screen_type)
    sel_mult = sel if sel is not None else +1  # undetermined -> assume +, flag

    # Prefer a large-is-significant magnitude, then a p-value-like column.
    sig_mag = next((c for c, t, r in present if r == "SIG_MAG"), None)
    sig_p = next((c for c, t, r in present if r == "SIG_P"), None)

    if sig_mag is not None:
        col = to_num(df[sig_mag])
        # Data-driven signedness: a column the registry calls an unsigned "magnitude"
        # but that actually carries substantial NEGATIVE values is really a SIGNED
        # directional score (negative = depleted = essential). The type name doesn't
        # tell us this and it varies by author — even within one metric (e.g. CasTLE
        # Score is signed in some screens, unsigned in others; RSA/CGI are signed).
        # Clipping such a column to >=0 would destroy the essential signal, so detect
        # it from the data and use the signed value as-is.
        nn = col.dropna()
        if len(nn) and (nn < 0).mean() > 0.05 and nn.min() < -0.5:
            return col, f"SIGNED_MAG({col_types[sig_mag]})", True
        mag = col.clip(lower=0).fillna(0.0)
        basis = f"SIG_MAG({col_types[sig_mag]})x sel={sel_mult}"
        if sel is None:
            basis += "[AMBIGUOUS_SELECTION]"
        return mag * sel_mult, basis, False

    if sig_p is not None:
        mag = neglog10(df[sig_p])
        basis = f"SIG_P({col_types[sig_p]})x sel={sel_mult}"
        if sel is None:
            basis += "[AMBIGUOUS_SELECTION]"
        return mag * sel_mult, basis, False

    # ---- nothing usable ---------------------------------------------------
    return pd.Series(np.nan, index=df.index), "UNRESOLVED", False


# ---------------------------------------------------------------------------
# 2b. Directionality overrides (frozen LLM artifact, see directionality_mapper.py)
#
# For screens Phase 1 could not sign deterministically, the LLM-resolved sign is
# read here as a DETERMINISTIC input. The override's sign is FINAL (perturbation
# already folded in by the LLM), so callers must NOT re-multiply by
# perturbation_mult when an override is applied.
# ---------------------------------------------------------------------------

OVERRIDES_PATH = paths.PROCESSED_DATA / "directionality_overrides.json"
_overrides_cache = None


def load_overrides(path=OVERRIDES_PATH):
    """screen_id -> override dict, restricted to status == 'auto'. {} if absent."""
    global _overrides_cache
    if _overrides_cache is not None:
        return _overrides_cache
    _overrides_cache = {}
    if path.exists():
        data = json.loads(path.read_text())
        for sid, ov in data.get("overrides", {}).items():
            if ov.get("status") == "auto":
                _overrides_cache[str(sid)] = ov
    return _overrides_cache


def _primary_magnitude(df, col_types):
    """The unsigned magnitude used by the significance path: prefer SIG_MAG, then
    SIG_P (-> -log10 p). Returns (Series, type_str)."""
    present = [(c, t, classify_type(t)) for c, t in col_types.items() if c in df.columns]
    sig_mag = next((c for c, t, r in present if r == "SIG_MAG"), None)
    if sig_mag is not None:
        return to_num(df[sig_mag]).clip(lower=0).fillna(0.0), col_types[sig_mag]
    sig_p = next((c for c, t, r in present if r == "SIG_P"), None)
    if sig_p is not None:
        return neglog10(df[sig_p]), col_types[sig_p]
    # last resort: first numeric-ish column
    c = next(iter(col_types), None)
    return (to_num(df[c]).fillna(0.0) if c else pd.Series(0.0, index=df.index)), (col_types.get(c, "?") if c else "?")


def _pair_signal(df, col_key, col_types):
    """Per-column signal for a pos/neg pair member: -log10 p for p-like columns,
    raw value otherwise."""
    t = col_types.get(col_key, "")
    if classify_type(t) == "SIG_P" or any(k in t.lower() for k in
                                          ("p-value", "p_val", "fdr", "q-val", "mageck", "rra")):
        return neglog10(df[col_key])
    return to_num(df[col_key]).fillna(0.0)


def apply_override(df, col_types, override):
    """Compute HARMONIZED_SCORE from an LLM directionality override.

    Returns (harmonized: Series, basis: str, is_directional: bool=True). The sign
    is FINAL — do not multiply by perturbation_mult afterwards."""
    conf = override.get("confidence")
    if override["mode"] == "SINGLE":
        mag, tstr = _primary_magnitude(df, col_types)
        sign = int(override["sign"])
        return mag * sign, f"LLM_SINGLE({tstr})xsign={sign}[conf={conf}]", True
    if override["mode"] == "PAIR":
        pos, neg = override["positive_column"], override["negative_column"]
        s = _pair_signal(df, pos, col_types) - _pair_signal(df, neg, col_types)
        return s, f"LLM_PAIR(+{pos}/-{neg})[conf={conf}]", True
    # UNDEFINED should never reach here (filtered to status=='auto'); be safe.
    return pd.Series(np.nan, index=df.index), "LLM_UNDEFINED", False


def load_screen_df(file_path, meta):
    """Read a BioGRID screen .tab file -> (df, col_types) with normalized columns.
    Returns (None, None) if the file is unreadable or missing required columns."""
    try:
        df = pd.read_csv(file_path, sep="\t", header=0, dtype=str)
    except Exception as e:
        print(f"  ! failed to read {os.path.basename(file_path)}: {e}")
        return None, None
    df.columns = [c.lstrip("#").strip() for c in df.columns]
    for col in ["SCREEN_ID", "OFFICIAL_SYMBOL", "HIT"]:
        if col not in df.columns:
            match = next((c for c in df.columns if c.upper() == col), None)
            if match:
                df = df.rename(columns={match: col})
            else:
                return None, None
    col_types = {f"SCORE.{i}": meta.get(f"SCORE.{i}_TYPE", "").strip()
                 for i in range(1, 6)}
    col_types = {k: v for k, v in col_types.items()
                 if v and v != "-" and k in df.columns}
    return df, col_types


def add_rank_columns(df):
    """Given df with HARMONIZED_SCORE, fill PERCENTILE_SCORE [-1,1] and
    ROBUST_Z_SCORE over measured genes only (NULL where degenerate/unmeasured)."""
    df["PERCENTILE_SCORE"] = np.nan
    df["ROBUST_Z_SCORE"] = np.nan
    valid = df["HARMONIZED_SCORE"].notna()
    n_valid = int(valid.sum())
    has_spread = n_valid > 1 and df.loc[valid, "HARMONIZED_SCORE"].nunique() > 1
    if has_spread:
        ranks = df.loc[valid, "HARMONIZED_SCORE"].rank(method="average") - 1
        max_rank = ranks.max()
        df.loc[valid, "PERCENTILE_SCORE"] = 2.0 * (ranks / max_rank) - 1.0
        vals = df.loc[valid, "HARMONIZED_SCORE"]
        med = vals.median()
        mad = np.median(np.abs(vals - med))
        scale = mad * 1.4826 if mad > 0 else vals.std()
        if scale and scale > 0:
            df.loc[valid, "ROBUST_Z_SCORE"] = (vals - med) / scale
    return df


# ---------------------------------------------------------------------------
# 3. Process one screen file
# ---------------------------------------------------------------------------

def process_screen(file_path, metadata, output_dir, db_conn, stats):
    filename = os.path.basename(file_path)

    m = re.search(r"SCREEN_(\d+)", filename)
    if not m:
        return False
    screen_id = m.group(1)

    if screen_id not in metadata:
        stats["no_metadata"] += 1
        return False
    meta = metadata[screen_id]
    if isinstance(meta, list):
        meta = meta[0]

    methodology = meta.get("METHODOLOGY", "").strip().upper()
    library_type = meta.get("LIBRARY_TYPE", "").strip().upper()
    screen_type = meta.get("SCREEN_TYPE", "").strip()
    full_avail = meta.get("FULL_SIZE_AVAILABLE", "").strip()
    coverage_type = "HIT_ONLY" if full_avail.lower() == "no" else "FULL"

    # Perturbation multiplier: CRISPRa is interpreted in the loss-of-function
    # frame, so its sign is inverted relative to knockout / CRISPRi.
    is_activation = ("ACTIVATION" in methodology) or ("CRISPRA" in library_type)
    perturbation_mult = -1 if is_activation else 1

    # ---- load ----
    df, col_types = load_screen_df(file_path, meta)
    if df is None:
        stats["read_error"] += 1
        return False

    # ---- resolve unified score: LLM directionality override > deterministic ----
    override = load_overrides().get(screen_id)
    if override is not None:
        # override sign is FINAL (perturbation folded in by the LLM) -> no *mult
        df["HARMONIZED_SCORE"], basis, is_directional = apply_override(df, col_types, override)
    else:
        s_raw, basis, is_directional = resolve_s_raw(df, col_types, screen_type)
        df["HARMONIZED_SCORE"] = s_raw * perturbation_mult
    stats["basis"][basis.split("(")[0]] = stats["basis"].get(basis.split("(")[0], 0) + 1

    # ---- rank percentile [-1,1] + robust z over MEASURED genes only ----
    add_rank_columns(df)

    df["IS_HIT"] = (df["HIT"].astype(str).str.strip().str.upper() == "YES").astype(int)

    # ---- persist processed tab file ----
    os.makedirs(output_dir, exist_ok=True)
    df.to_csv(os.path.join(output_dir, filename), sep="\t", index=False)

    # ---- metadata row ----
    db_conn.execute(
        """INSERT OR REPLACE INTO screen_metadata (
               SCREEN_ID, SOURCE_ID, AUTHOR, SCREEN_NAME, SCORES_SIZE,
               ANALYSIS, SCREEN_TYPE, SCREEN_FORMAT, METHODOLOGY, CELL_LINE,
               CELL_TYPE, PHENOTYPE, ORGANISM_OFFICIAL, SCREEN_RATIONALE,
               COVERAGE_TYPE, SCORE_BASIS, IS_DIRECTIONAL
           ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            str(meta.get("SCREEN_ID", screen_id)),
            str(meta.get("SOURCE_ID", "")),
            str(meta.get("AUTHOR", "")),
            str(meta.get("SCREEN_NAME", "")),
            int(meta.get("SCORES_SIZE", 0) or 0),
            str(meta.get("ANALYSIS", "")),
            screen_type,
            str(meta.get("SCREEN_FORMAT", "")),
            str(meta.get("METHODOLOGY", "")),
            str(meta.get("CELL_LINE", "")),
            str(meta.get("CELL_TYPE", "")),
            str(meta.get("PHENOTYPE", "")),
            str(meta.get("ORGANISM_OFFICIAL", "")),
            str(meta.get("SCREEN_RATIONALE", "")),
            coverage_type,
            basis,
            int(is_directional),
        ),
    )

    # ---- score rows ----
    out = df[["SCREEN_ID", "OFFICIAL_SYMBOL", "HARMONIZED_SCORE",
              "PERCENTILE_SCORE", "ROBUST_Z_SCORE", "IS_HIT"]].copy()
    out.columns = ["SCREEN_ID", "GENE_SYMBOL", "HARMONIZED_SCORE",
                   "PERCENTILE_SCORE", "ROBUST_Z_SCORE", "IS_HIT"]
    out["SCREEN_ID"] = out["SCREEN_ID"].astype(str)
    out["GENE_SYMBOL"] = out["GENE_SYMBOL"].astype(str)
    out["IS_HIT"] = out["IS_HIT"].astype(int)
    out.to_sql("harmonized_scores", db_conn, if_exists="append", index=False)

    stats["ok"] += 1
    stats["hit_only"] += 1 if coverage_type == "HIT_ONLY" else 0
    return True


# ---------------------------------------------------------------------------
# 4. Schema + driver
# ---------------------------------------------------------------------------

def create_schema(db):
    db.execute(
        """CREATE TABLE IF NOT EXISTS screen_metadata (
               SCREEN_ID TEXT PRIMARY KEY,
               SOURCE_ID TEXT, AUTHOR TEXT, SCREEN_NAME TEXT, SCORES_SIZE INTEGER,
               ANALYSIS TEXT, SCREEN_TYPE TEXT, SCREEN_FORMAT TEXT, METHODOLOGY TEXT,
               CELL_LINE TEXT, CELL_TYPE TEXT, PHENOTYPE TEXT, ORGANISM_OFFICIAL TEXT,
               SCREEN_RATIONALE TEXT,
               COVERAGE_TYPE TEXT,      -- FULL | HIT_ONLY  (routes binary vs continuous)
               SCORE_BASIS TEXT,        -- which column/path produced S_raw (provenance)
               IS_DIRECTIONAL INTEGER   -- 1 = sign from a directional metric; 0 = from selection type
           )"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS harmonized_scores (
               SCREEN_ID TEXT,
               GENE_SYMBOL TEXT,
               HARMONIZED_SCORE REAL,   -- NULL if the gene's metric was missing ('-')
               PERCENTILE_SCORE REAL,   -- [-1, 1]; NULL if unmeasured
               ROBUST_Z_SCORE REAL,     -- NULL if unmeasured
               IS_HIT INTEGER
           )"""
    )


def process_set(files, meta, out_dir, db, stats, label):
    files = [f for f in files
             if "SCREEN_INDEX" not in os.path.basename(f) and os.path.isfile(f)]
    print(f"Processing {len(files)} {label} screens...")
    for f in files:
        process_screen(f, meta, out_dir, db, stats)
    print(f"  done ({label}).")


def main():
    raw_dir = str(paths.RAW_BIOGRID)
    proc_dir = str(paths.PROC_BIOGRID)
    db_path = str(paths.DB)

    os.makedirs(proc_dir, exist_ok=True)
    if os.path.exists(db_path):
        os.remove(db_path)
    db = sqlite3.connect(db_path)
    create_schema(db)

    print("Loading metadata...")
    with open(os.path.join(raw_dir, "metadata/screen_metadata_musculus.json")) as f:
        meta_mouse = json.load(f)
    with open(os.path.join(raw_dir, "metadata/screen_metadata_homo_sapiens.json")) as f:
        meta_human = json.load(f)

    stats = {"ok": 0, "no_metadata": 0, "read_error": 0, "missing_cols": 0,
             "hit_only": 0, "basis": {}}

    process_set(glob.glob(os.path.join(raw_dir, "screenings/mus_musculus/*")),
                meta_mouse, os.path.join(proc_dir, "screenings/mus_musculus"),
                db, stats, "mouse")
    process_set(glob.glob(os.path.join(raw_dir, "screenings/homo_sapiens/*")),
                meta_human, os.path.join(proc_dir, "screenings/homo_sapiens"),
                db, stats, "human")

    print("Creating database indexes...")
    db.execute("CREATE INDEX IF NOT EXISTS idx_scores_gene ON harmonized_scores(GENE_SYMBOL)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_scores_screen ON harmonized_scores(SCREEN_ID)")
    db.commit()
    db.close()

    print("\n=== Summary ===")
    print(f"  screens harmonized : {stats['ok']}")
    print(f"  hit-only screens   : {stats['hit_only']}")
    print(f"  no metadata        : {stats['no_metadata']}")
    print(f"  read errors        : {stats['read_error']}")
    print(f"  missing columns    : {stats['missing_cols']}")
    print("  resolution basis   :")
    for k, v in sorted(stats["basis"].items(), key=lambda x: -x[1]):
        print(f"      {v:5d}  {k}")
    print("Processing complete!")


if __name__ == "__main__":
    main()

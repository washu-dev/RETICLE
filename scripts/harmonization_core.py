"""
RETICLE — Harmonization core (warehouse-native port).

Pure, storage-agnostic harmonization logic ported from
prototype/script/harmonize_scores.py. It converts a screen's heterogeneous score
columns onto ONE unified biological axis so cross-screen math is valid:

    HARMONIZED_SCORE = S_raw x perturbation_multiplier
    +  (high) = loss-of-function PROTECTIVE / knockout ENRICHES
    -  (low)  = loss-of-function DELETERIOUS / gene ESSENTIAL (depletes)

This module has NO I/O except optional override loading; the caller supplies a
pandas DataFrame (built from screen_gene_raw in the warehouse) and the per-screen
score-type map + screen metadata (from the BioGRID metadata JSON). See
scripts/harmonize_warehouse.py for the driver that writes results to
fact_screen_gene / screen_harmonization.
"""

import json
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Controlled-vocabulary registry of SCORE.k_TYPE strings (58 distinct types).
#   DIR_POS : directional; higher = enriched/fit, lower = depleted/essential (+as-is)
#   DIR_NEG : directional; higher = MORE essential (flipped, -value)
#   SIG_MAG : unsigned significance, larger = more significant (direction from selection)
#   SIG_P   : p-value-like, smaller = more significant (-> -log10(p); direction from selection)
#   IGNORE  : not a usable primary effect column (counts, ids, ranks, ...)
# ---------------------------------------------------------------------------

DIR_POS = {
    "log2fc", "log2", "zlfc", "z-score", "crispr score (cs)", "ceres score",
    "beta score", "castle effect",
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
    "bayes factor", "dependency score",
}

SIG_MAG = {
    "stars score", "rsa", "castle score", "cgi",
}

SIG_P = {
    "p-value", "fdr", "q-value", "mageck score", "rra score",
    "log10 (p-value)", "-log (p-value)", "log10", "log10 (corrected p-value)",
    "neg score p-value", "pos score p-value",
}

IGNORE = {
    "rank", "rra rank", "sgrna number", "read counts", "umi",
    "percent sorted cells", "reduced chi squared", "deseq2",
}

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
    if any(k in t for k in ["p-val", "p_val", "fdr", "q-val", "q_val"]):
        return "SIG_P"
    if any(k in t for k in ["log2", "lfc", "z-score", "zlfc", "effect", "beta",
                            "fold change", "enrichment score"]):
        return "DIR_POS"
    return "UNKNOWN"


def pair_member(type_str):
    """Classify a score type as a positive-/negative-direction pair member.
    Returns ('pos'|'neg', is_p_like) or None."""
    t = (type_str or "").strip().lower()
    if not t or t == "-":
        return None
    p_like = any(k in t for k in ["p-value", "p_val", "fdr", "q-val", "mageck", "rra"])
    if "pos" in t or t.startswith("rra_enrichment") or "enrichment" in t:
        return ("pos", p_like)
    if "neg" in t or t.startswith("rra_depletion") or "depletion" in t:
        return ("neg", p_like)
    return None


def selection_multiplier(screen_type):
    """Sign for UNSIGNED significance metrics. None => direction undetermined.
    Exact match avoids the 'NEGATIVE SELECTION' in 'POSITIVE AND NEGATIVE
    SELECTION' substring trap."""
    st = (screen_type or "").strip().lower()
    if st == "negative selection":
        return -1
    if st == "positive selection":
        return +1
    return None


def to_num(series):
    """Coerce a screen column to float, mapping '-'/blank/'None' to NaN."""
    return pd.to_numeric(series.replace(["-", "", "None"], np.nan), errors="coerce")


def neglog10(series):
    """-log10(p) with floor clipping; NaN (missing) -> 0 contribution."""
    p = to_num(series).clip(lower=P_CLIP_LO, upper=1.0).fillna(1.0)
    return -np.log10(p)


def resolve_s_raw(df, col_types, screen_type):
    """Return (s_raw: pd.Series, basis: str, is_directional: bool).

    Priority: (1) pos/neg directional pair; (2) single directional column
    (preferred over significance); (3) unsigned significance + selection sign.
    """
    present = [(c, t, classify_type(t)) for c, t in col_types.items() if c in df.columns]

    # (1) pos/neg pair
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

    # (2) single directional effect column
    for c, t, role in present:
        if role == "DIR_POS":
            return to_num(df[c]), f"DIR_POS({t})", True
        if role == "DIR_NEG":
            return -to_num(df[c]), f"DIR_NEG({t})", True

    # (3) unsigned significance + selection sign
    sel = selection_multiplier(screen_type)
    sel_mult = sel if sel is not None else +1

    sig_mag = next((c for c, t, r in present if r == "SIG_MAG"), None)
    sig_p = next((c for c, t, r in present if r == "SIG_P"), None)

    if sig_mag is not None:
        col = to_num(df[sig_mag])
        # Data-driven signedness: a registry "magnitude" that actually carries
        # substantial negatives is really a SIGNED directional score.
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

    return pd.Series(np.nan, index=df.index), "UNRESOLVED", False


def add_rank_columns(df, score_col="HARMONIZED_SCORE"):
    """Given df with a harmonized-score column, fill PERCENTILE_SCORE [-1,1] and
    ROBUST_Z_SCORE over measured genes only (NULL where degenerate/unmeasured)."""
    df["PERCENTILE_SCORE"] = np.nan
    df["ROBUST_Z_SCORE"] = np.nan
    valid = df[score_col].notna()
    n_valid = int(valid.sum())
    has_spread = n_valid > 1 and df.loc[valid, score_col].nunique() > 1
    if has_spread:
        ranks = df.loc[valid, score_col].rank(method="average") - 1
        max_rank = ranks.max()
        df.loc[valid, "PERCENTILE_SCORE"] = 2.0 * (ranks / max_rank) - 1.0
        vals = df.loc[valid, score_col]
        med = vals.median()
        mad = np.median(np.abs(vals - med))
        scale = mad * 1.4826 if mad > 0 else vals.std()
        if scale and scale > 0:
            df.loc[valid, "ROBUST_Z_SCORE"] = (vals - med) / scale
    return df


# ---------------------------------------------------------------------------
# LLM directionality overrides (frozen artifact). Sign is FINAL when applied
# (perturbation folded in) -> caller must NOT re-multiply by perturbation_mult.
# ---------------------------------------------------------------------------

def load_overrides(path):
    """screen_id -> override dict, restricted to status == 'auto'. {} if absent/None."""
    if not path:
        return {}
    try:
        import os
        if not os.path.exists(path):
            return {}
        data = json.loads(open(path).read())
    except Exception:
        return {}
    out = {}
    for sid, ov in data.get("overrides", {}).items():
        if ov.get("status") == "auto":
            out[str(sid)] = ov
    return out


def _primary_magnitude(df, col_types):
    present = [(c, t, classify_type(t)) for c, t in col_types.items() if c in df.columns]
    sig_mag = next((c for c, t, r in present if r == "SIG_MAG"), None)
    if sig_mag is not None:
        return to_num(df[sig_mag]).clip(lower=0).fillna(0.0), col_types[sig_mag]
    sig_p = next((c for c, t, r in present if r == "SIG_P"), None)
    if sig_p is not None:
        return neglog10(df[sig_p]), col_types[sig_p]
    c = next(iter(col_types), None)
    return (to_num(df[c]).fillna(0.0) if c else pd.Series(0.0, index=df.index)), \
           (col_types.get(c, "?") if c else "?")


def _pair_signal(df, col_key, col_types):
    t = col_types.get(col_key, "")
    if classify_type(t) == "SIG_P" or any(k in t.lower() for k in
                                          ("p-value", "p_val", "fdr", "q-val", "mageck", "rra")):
        return neglog10(df[col_key])
    return to_num(df[col_key]).fillna(0.0)


def apply_override(df, col_types, override):
    """Compute HARMONIZED_SCORE from an LLM directionality override. Sign is FINAL."""
    conf = override.get("confidence")
    if override["mode"] == "SINGLE":
        mag, tstr = _primary_magnitude(df, col_types)
        sign = int(override["sign"])
        return mag * sign, f"LLM_SINGLE({tstr})xsign={sign}[conf={conf}]", True
    if override["mode"] == "PAIR":
        pos, neg = override["positive_column"], override["negative_column"]
        s = _pair_signal(df, pos, col_types) - _pair_signal(df, neg, col_types)
        return s, f"LLM_PAIR(+{pos}/-{neg})[conf={conf}]", True
    return pd.Series(np.nan, index=df.index), "LLM_UNDEFINED", False

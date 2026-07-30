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
#
# "log10 (p-value)" / "log10" / "log10 (corrected p-value)" / "-log (p-value)" USED to be here and
# ALL fed the same -log10(clip(x,1e-10,1)) transform. Audited 2026-07: the same label string covers
# at least 4 incompatible encodings in this corpus alone — already-negative log10(p) (RSA), already-
# positive -log10(p), a SIGNED -log10(p) whose sign IS the direction (MaGeCK two-sided screens), and
# columns that are not p-values at all (a rank-derived score, a Z-score). Feeding all of them through
# one clip+neglog10 silently collapsed 10 screens to a SINGLE distinct harmonized value across ~18k
# genes each (verified: screen 1175 -> 1 value / 1,190 genes) and left 15 more tie-saturated. These
# labels are handled per-screen via SCORE_SEMANTICS_PATH instead — see classify_type()'s AMBIGUOUS_LOG
# branch and resolve_ambiguous_log() below. Do not add a "log"-containing label back into this set.
SIG_P = {
    "p-value", "fdr", "q-value", "mageck score", "rra score",
    "neg score p-value", "pos score p-value",
}

# Substrings that mark a SCORE.k_TYPE label as "some kind of log-transformed p-value" without saying
# WHICH kind — see the SIG_P comment above. Checked before the generic p-val heuristic fallback so a
# label like "log10 (p-value)" can never slide back into SIG_P via its "p-val" substring.
_AMBIGUOUS_LOG_MARKERS = ("log10", "log 10", "-log(", "-log (", "logp", "log-p")

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
    # Checked BEFORE the p-val heuristic below: "log10 (p-value)" contains the substring "p-val"
    # and would otherwise silently fall into SIG_P and get the wrong transform (see SIG_P comment).
    if any(k in t for k in _AMBIGUOUS_LOG_MARKERS):
        return "AMBIGUOUS_LOG"
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

def resolve_s_raw(df, col_types, screen_type, screen_id=None):
    """Return (s_raw: pd.Series, basis: str, is_directional: bool).

    Resolution priority:
      (1) positive/negative directional PAIR  (e.g. MAGeCK pos/neg score)
      (2) a single DIRECTIONAL effect column  (preferred over significance)
      (3) an AMBIGUOUS_LOG column resolved via the frozen score-semantics override
      (4) an UNSIGNED SIGNIFICANCE column + selection-type sign
    """
    # ---- (0) frozen per-screen resolution wins over every heuristic below ------
    # The SCORE.k_TYPE label is unreliable per-screen (see screen_semantics_entry), so a screen
    # listed in score_semantics_overrides.json is resolved from that file and nothing else.
    entry = screen_semantics_entry(screen_id)
    if entry is not None:
        mag, basis, is_directional = apply_score_semantics(df, entry, screen_id)
        if is_directional:
            return mag, basis, True
        sel = selection_multiplier(screen_type)
        sel_mult = sel if sel is not None else +1
        tagged = basis + ("[AMBIGUOUS_SELECTION]" if sel is None else "")
        return mag * sel_mult, f"{tagged}x sel={sel_mult}", False

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

    # ---- (3) AMBIGUOUS_LOG with no frozen entry: refuse, don't guess ------------
    # Branch (0) already handled every screen that HAS an entry, so reaching here with this label
    # means the screen is unresolved — resolve_ambiguous_log raises, and process_set records it.
    amb = next((c for c, t, r in present if r == "AMBIGUOUS_LOG"), None)
    if amb is not None:
        return resolve_ambiguous_log(df, amb, screen_id)

    # ---- (4) unsigned significance + selection sign -----------------------
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
        # Closes the gap the check above leaves: a column entirely in e.g. [-0.4, 0] has min > -0.5
        # so it is not treated as signed, yet clip(lower=0) would still zero the whole screen.
        assert_probability_range(col, screen_id, col_types[sig_mag], "mag")
        mag = col.clip(lower=0).fillna(0.0)
        basis = f"SIG_MAG({col_types[sig_mag]})x sel={sel_mult}"
        if sel is None:
            basis += "[AMBIGUOUS_SELECTION]"
        return mag * sel_mult, basis, False

    if sig_p is not None:
        col = to_num(df[sig_p])
        alt = reinterpret_out_of_range_p(col, screen_id, col_types[sig_p])
        if alt is not None:
            alt_series, alt_basis, alt_dir = alt
            if alt_dir:
                return alt_series, alt_basis, True          # signed effect: sign is the direction
            tagged = alt_basis + ("[AMBIGUOUS_SELECTION]" if sel is None else "")
            return alt_series * sel_mult, f"{tagged}x sel={sel_mult}", False
        assert_probability_range(col, screen_id, col_types[sig_p], "p")
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


# ---------------------------------------------------------------------------
# 2c. Score-semantics overrides (frozen forensic artifact, see processed_data/
# score_semantics_overrides.json) — a column typed AMBIGUOUS_LOG (see SIG_P comment
# above) has no safe generic transform; it is resolved per-screen against this file
# instead of guessed at ingest.
# ---------------------------------------------------------------------------

SCORE_SEMANTICS_PATH = paths.PROCESSED_DATA / "score_semantics_overrides.json"
_score_semantics_cache = None

# Marks a basis string produced by resolve_ambiguous_log(). Callers must not string-match this
# directly — use sign_is_final() instead, which encodes the one rule that actually matters.
SEMANTICS_BASIS_PREFIX = "SEMANTICS_OVERRIDE("


def sign_is_final(basis, is_directional):
    """True when the resolved score already sits on RETICLE's FINAL axis, so the caller must NOT
    multiply by perturbation_mult.

    This holds for exactly one case: a DIRECTIONAL score-semantics override. Those columns carry
    their own sign and that sign was verified forensically against the core-essential-gene anchor
    on the raw values (see score_semantics_overrides.json), i.e. already on the post-perturbation
    axis — re-applying the CRISPRa flip would invert it.

    It does NOT hold for a NON-directional semantics override: that is an unsigned magnitude whose
    sign comes from the selection type, exactly like the SIG_MAG/SIG_P paths, so it still needs the
    perturbation flip. Nor does it hold for DIR_POS/DIR_NEG/PAIR, which measure the effect in the
    perturbation's own direction and have always been flipped."""
    return is_directional and basis.startswith(SEMANTICS_BASIS_PREFIX)


def load_score_semantics(path=SCORE_SEMANTICS_PATH):
    """screen_id -> {semantics, transform, confidence, ...}. {} if the file is absent."""
    global _score_semantics_cache
    if _score_semantics_cache is not None:
        return _score_semantics_cache
    _score_semantics_cache = {}
    if path.exists():
        data = json.loads(path.read_text())
        _score_semantics_cache = {str(sid): v for sid, v in data.get("screens", {}).items()}
    return _score_semantics_cache


def apply_score_semantics(df, entry, screen_id, col=None):
    """Apply one frozen per-screen score-semantics entry.

    Returns (magnitude: pd.Series, basis: str, is_directional: bool). `quarantine` returns an
    all-NaN magnitude: HARMONIZED_SCORE stays NaN and PERCENTILE_SCORE/ROBUST_Z_SCORE fall out via
    screen_qc, while IS_HIT is unaffected (computed independently from the raw HIT column)."""
    col = col or entry.get("column") or "SCORE.1"
    if col not in df.columns:
        raise ValueError(f"screen {screen_id}: {SCORE_SEMANTICS_PATH.name} names column {col!r}, "
                         f"which is not in this screen's file")
    x = to_num(df[col])
    if "sentinel_value" in entry:
        x = x.mask(x == entry["sentinel_value"])
    transform = entry["transform"]
    if transform == "quarantine":
        mag = pd.Series(np.nan, index=df.index)
    elif transform == "negate":
        mag = -x
    elif transform == "identity":
        mag = x
    else:
        raise ValueError(f"screen {screen_id}: unknown transform {transform!r} in {SCORE_SEMANTICS_PATH.name}")
    tag = "" if entry.get("confidence", "high") == "high" else "[POLARITY_UNVERIFIED]"
    basis = f"SEMANTICS_OVERRIDE({entry['semantics']}){tag}"
    return mag, basis, bool(entry.get("is_directional", False))


def screen_semantics_entry(screen_id):
    """The frozen per-screen resolution for this screen, or None.

    Consulted BEFORE any SCORE.k_TYPE-based classification: the label is unreliable per-screen (the
    same 'RSA'/'RRA score'/'MaGeCK Score'/'Log10 (p-value)' string means different things in
    different depositions), so a screen listed here always wins over the registry."""
    return load_score_semantics().get(str(screen_id))


def resolve_ambiguous_log(df, col, screen_id):
    """AMBIGUOUS_LOG column -> frozen resolution. Raises if the screen has no entry: a label that
    cannot be transformed generically MUST be forensically resolved (see the file's header) before
    the screen can be harmonized. Silently guessing is exactly the bug this replaces."""
    entry = screen_semantics_entry(screen_id)
    if entry is None:
        raise ValueError(
            f"screen {screen_id}: column {col!r} is an AMBIGUOUS_LOG type with no entry in "
            f"{SCORE_SEMANTICS_PATH.name} — resolve its semantics from the raw distribution "
            f"(see that file's header for the method) before harmonizing this screen.")
    return apply_score_semantics(df, entry, screen_id, col)


def reinterpret_out_of_range_p(series, screen_id, type_str):
    """A column the registry calls a p-value but whose values are NOT in (0, 1].

    Mirrors the data-driven signedness check already used on the SIG_MAG path: the label is
    unreliable per-deposition (e.g. 'MaGeCK Score' is an RRA p-value in some screens and a signed
    log2 fold-change in others, with the real p-value in a companion column), so decide from the
    data instead of the label. Returns (series, basis, is_directional) or None if the shape is not
    confidently interpretable — in which case the caller raises and the screen is reported for
    forensic resolution rather than silently mangled.

    Verified against the author's own HIT calls on all 16 screens this fires for: the signed branch
    lands hits in the extreme tail(s), and the magnitude branch lands them at the top."""
    v = series.dropna()
    if v.empty:
        return None
    lo, hi = float(v.min()), float(v.max())
    if lo >= 0 and hi <= 1.0 + 1e-9:
        return None                                    # genuinely a probability; caller proceeds
    frac_neg = float((v < 0).mean())
    if frac_neg > 0.05 and lo < -0.5:
        # Substantial negative mass with real magnitude => a SIGNED effect score. Sign is the
        # direction (negative = depleted = essential), already RETICLE's axis, so use it as-is.
        return series, f"SIGNED_EFFECT({type_str})", True
    if lo >= 0 and hi > 1.0:
        # All non-negative but out of (0,1] => a significance MAGNITUDE (larger = more significant),
        # e.g. an already -log10'd value. Unsigned: the caller applies the selection-type sign.
        return series.fillna(0.0), f"SIG_MAGNITUDE({type_str})", False
    return None


def assert_probability_range(series, screen_id, type_str, kind):
    """Guard the assumption a clip is about to make. A clip whose range does not match the column's
    actual range silently flattens an entire screen — that single failure mode produced ALL 34
    forensically-resolved screens (e.g. an all-negative log10(p) hitting clip(lower=1e-10) became the
    constant 10; a magnitude in [4.3, 26.9] hitting clip(upper=1.0) became the constant 0). Raising
    here converts that from silent corruption into a loud, actionable failure that process_set
    records per-screen."""
    v = series.dropna()
    if v.empty:
        return
    lo, hi = float(v.min()), float(v.max())
    if kind == "p":                      # about to do -log10(clip(x, 1e-10, 1))
        if lo < 0 or hi > 1.0 + 1e-9:
            raise ValueError(
                f"screen {screen_id}: column typed {type_str!r} was treated as a raw p-value but its "
                f"range is [{lo:.6g}, {hi:.6g}], outside (0, 1] — -log10(clip(...)) would collapse it. "
                f"Add a per-screen entry to {SCORE_SEMANTICS_PATH.name}.")
    elif kind == "mag":                  # about to do clip(lower=0)
        if hi <= 0:
            raise ValueError(
                f"screen {screen_id}: column typed {type_str!r} was treated as a non-negative "
                f"magnitude but its range is [{lo:.6g}, {hi:.6g}] — clip(lower=0) would zero the whole "
                f"screen. Add a per-screen entry to {SCORE_SEMANTICS_PATH.name}.")


def _primary_magnitude(df, col_types, screen_id=None):
    """The unsigned magnitude used by the significance path: prefer SIG_MAG, then
    SIG_P (-> -log10 p). Returns (Series, type_str_or_basis, is_final).

    is_final=True means the value came from the frozen score-semantics override and already has
    its final sign/meaning baked in — the caller must use it AS-IS and must NOT multiply by the
    override's sign or wrap it into an "LLM_SINGLE(...)xsign=..." basis string. This is how screens
    1098/1099 (a directional Z-score mislabeled "Log10") bypass the sign multiply entirely."""
    # A frozen per-screen entry beats every label heuristic below — see screen_semantics_entry().
    entry = screen_semantics_entry(screen_id)
    if entry is not None:
        # basis (e.g. "SEMANTICS_OVERRIDE(neglog10_p)[POLARITY_UNVERIFIED]") is returned verbatim so
        # a low-confidence tag can never be silently dropped.
        return apply_score_semantics(df, entry, screen_id)
    present = [(c, t, classify_type(t)) for c, t in col_types.items() if c in df.columns]
    # AMBIGUOUS_LOG next: this label lies about being a plain magnitude (see the SIG_P comment) and
    # must never reach the generic SIG_MAG/SIG_P branches below.
    amb = next((c for c, t, r in present if r == "AMBIGUOUS_LOG"), None)
    if amb is not None:
        return resolve_ambiguous_log(df, amb, screen_id)
    sig_mag = next((c for c, t, r in present if r == "SIG_MAG"), None)
    if sig_mag is not None:
        col = to_num(df[sig_mag])
        assert_probability_range(col, screen_id, col_types[sig_mag], "mag")
        return col.clip(lower=0).fillna(0.0), col_types[sig_mag], False
    sig_p = next((c for c, t, r in present if r == "SIG_P"), None)
    if sig_p is not None:
        col = to_num(df[sig_p])
        alt = reinterpret_out_of_range_p(col, screen_id, col_types[sig_p])
        if alt is not None:
            return alt
        assert_probability_range(col, screen_id, col_types[sig_p], "p")
        return neglog10(df[sig_p]), col_types[sig_p], False
    # last resort: first numeric-ish column
    c = next(iter(col_types), None)
    return (to_num(df[c]).fillna(0.0) if c else pd.Series(0.0, index=df.index)), (col_types.get(c, "?") if c else "?"), False


def _pair_signal(df, col_key, col_types, screen_id=None):
    """Per-column signal for a pos/neg pair member: -log10 p for p-like columns,
    raw value otherwise."""
    t = col_types.get(col_key, "")
    tl = t.lower()
    # Same trap as the main SIG_P path (see its comment): "log10 (p-value)" contains the
    # substring "p-value" and would otherwise silently hit neglog10() with the wrong sign/range.
    # No PAIR screen in this corpus currently has an ambiguous-log column (checked empirically
    # against both species' raw metadata) — this only guards against a future one arriving unnoticed.
    if any(k in tl for k in _AMBIGUOUS_LOG_MARKERS):
        mag, _basis, _directional = resolve_ambiguous_log(df, col_key, screen_id)
        return mag
    if classify_type(t) == "SIG_P" or any(k in tl for k in
                                          ("p-value", "p_val", "fdr", "q-val", "mageck", "rra")):
        return neglog10(df[col_key])
    return to_num(df[col_key]).fillna(0.0)


def apply_override(df, col_types, override, screen_id=None):
    """Compute HARMONIZED_SCORE from an LLM directionality override.

    Returns (harmonized: Series, basis: str, is_directional: bool=True). The sign
    is FINAL — do not multiply by perturbation_mult afterwards."""
    conf = override.get("confidence")
    if override["mode"] == "SINGLE":
        mag, tstr, is_final = _primary_magnitude(df, col_types, screen_id)
        if is_final:
            # Came from the frozen score-semantics override as an already-directional value
            # (e.g. screens 1098/1099: a Z-score mislabeled "Log10") — the LLM sign was derived
            # against the OLD broken magnitude and no longer applies; use the value as-is.
            return mag, f"LLM_SINGLE_BYPASSED({tstr})[llm_conf={conf}]", True
        sign = int(override["sign"])
        return mag * sign, f"LLM_SINGLE({tstr})xsign={sign}[conf={conf}]", True
    if override["mode"] == "PAIR":
        pos, neg = override["positive_column"], override["negative_column"]
        s = _pair_signal(df, pos, col_types, screen_id) - _pair_signal(df, neg, col_types, screen_id)
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


# A transform whose clipping range does not match the column's actual range silently flattens a whole
# screen: an already-log10'd p-value column (all negative) hits clip(lower=1e-10) and every gene becomes
# -log10(1e-10)=10, or clip(lower=0) and every gene becomes 0.
#
# The collapse signature is ABSOLUTE, not proportional. Measured on this corpus every screen broken this
# way had EXACTLY 1 distinct harmonized value; the next-lowest screens sit at 29-112 distinct values and
# are legitimately coarse rather than broken (mostly heavily-quantized 'CasTLE Effect' depositions). An
# earlier version of this gate used a 0.5%-of-n fraction, which wrongly excluded 7 real genome-wide
# screens (~140k gene rows) whose only sin is a coarse score grid — the corpus' own 1st percentile of the
# distinct fraction is 0.61%, so any threshold near 0.5% necessarily cuts into the legitimate tail.
# 20 sits in the wide empty gap between 1 (broken) and 29 (coarse but usable).
COLLAPSE_UNIQUE_FLOOR = 20
# Screens below this distinct fraction are REPORTED as coarse but still used: their percentiles are
# tie-heavy and weak as correlation input, which downstream should know about, but they are not corrupt.
COARSE_UNIQUE_FRAC = 0.01


def screen_qc(df):
    """Verdict on a screen's harmonized scores. Returns (ok: bool, reason: str|None).

    Quarantines only what is provably broken (a collapsed transform); merely coarse screens pass with
    a 'coarse:' note so they stay usable but visible. Pure function of the frame — the caller owns
    recording the verdict (add_rank_columns writes it into stats). This is the guard the pipeline was
    missing: a fully-flattened screen used to produce NULL percentiles and get silently dropped from
    every downstream layer with no warning at all."""
    valid = df["HARMONIZED_SCORE"].notna()
    n_valid = int(valid.sum())
    if n_valid < 2:
        return False, f"only {n_valid} measured value(s)"
    nuniq = int(df.loc[valid, "HARMONIZED_SCORE"].nunique())
    frac = nuniq / n_valid
    if nuniq <= 1:
        return False, f"all {n_valid} measured genes share ONE harmonized value (transform collapsed)"
    if n_valid >= 500 and nuniq < COLLAPSE_UNIQUE_FLOOR:
        return False, (f"only {nuniq} distinct values over {n_valid} genes — below the collapse floor "
                       f"of {COLLAPSE_UNIQUE_FLOOR}, transform almost certainly mis-typed")
    if n_valid >= 500 and frac < COARSE_UNIQUE_FRAC:
        return True, (f"coarse: {nuniq} distinct values over {n_valid} genes ({frac:.3%}) — usable but "
                      f"tie-heavy; weak as correlation input")
    return True, None


def add_rank_columns(df, screen_id=None, stats=None):
    """Given df with HARMONIZED_SCORE, fill PERCENTILE_SCORE [-1,1] and
    ROBUST_Z_SCORE over measured genes only (NULL where degenerate/unmeasured).

    Runs screen_qc() as the gate (stricter than a bare nunique>1 check — see its docstring) and, if
    `stats` is given, appends a {screen_id, reason} record to stats['quarantined_screens'] on failure.
    Previously a collapsed screen just silently produced NULL/tie-saturated percentiles with no record
    anywhere; this makes it visible in the run's printed stats."""
    df["PERCENTILE_SCORE"] = np.nan
    df["ROBUST_Z_SCORE"] = np.nan
    valid = df["HARMONIZED_SCORE"].notna()
    ok, reason = screen_qc(df)
    if stats is not None and reason:
        # ok=True with a reason means "usable but coarse" — recorded separately so a real quarantine
        # is never buried in a list of merely-coarse screens.
        key = "coarse_screens" if ok else "quarantined_screens"
        stats.setdefault(key, []).append({"screen_id": screen_id, "reason": reason})
    if ok:
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
        df["HARMONIZED_SCORE"], basis, is_directional = apply_override(df, col_types, override, screen_id)
    else:
        s_raw, basis, is_directional = resolve_s_raw(df, col_types, screen_type, screen_id)
        if sign_is_final(basis, is_directional):
            df["HARMONIZED_SCORE"] = s_raw
        else:
            df["HARMONIZED_SCORE"] = s_raw * perturbation_mult
    stats["basis"][basis.split("(")[0]] = stats["basis"].get(basis.split("(")[0], 0) + 1

    # ---- rank percentile [-1,1] + robust z over MEASURED genes only ----
    add_rank_columns(df, screen_id, stats)

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
        # Contain per-screen failures. main() deletes the whole DB before rebuilding, so an
        # uncaught exception here (e.g. resolve_ambiguous_log refusing an unrecognized log-p label,
        # which is deliberately loud) would abort the run and leave a half-built database with no
        # summary. Record it and keep going; unresolved screens are listed at the end.
        try:
            process_screen(f, meta, out_dir, db, stats)
        except Exception as e:
            stats.setdefault("failed_screens", []).append(
                {"file": os.path.basename(f), "error": f"{type(e).__name__}: {e}"})
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
    # layout-aware (RIS: BIOGRID-ORCS-2.0.18/<species>/ with json in the same dir;
    #                local: raw_data/BIOGRID/{metadata,screenings}/) — see paths.py
    with open(paths.BIOGRID_METADATA["Mus musculus"]) as f:
        meta_mouse = json.load(f)
    with open(paths.BIOGRID_METADATA["Homo sapiens"]) as f:
        meta_human = json.load(f)

    stats = {"ok": 0, "no_metadata": 0, "read_error": 0, "missing_cols": 0,
             "hit_only": 0, "basis": {}}

    process_set(glob.glob(str(paths.BIOGRID_SCREENS["Mus musculus"] / "*")),
                meta_mouse, os.path.join(proc_dir, "screenings/mus_musculus"),
                db, stats, "mouse")
    process_set(glob.glob(str(paths.BIOGRID_SCREENS["Homo sapiens"] / "*")),
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
    quarantined = stats.get("quarantined_screens", [])
    print(f"  quarantined screens: {len(quarantined)}  (collapsed — NULL percentiles, see screen_qc())")
    for q in quarantined:
        print(f"      {q['screen_id']:>6}  {q['reason']}")
    coarse = stats.get("coarse_screens", [])
    print(f"  coarse screens     : {len(coarse)}  (kept and usable, but tie-heavy)")
    for q in coarse:
        print(f"      {q['screen_id']:>6}  {q['reason']}")
    failed = stats.get("failed_screens", [])
    if failed:
        print(f"  FAILED screens     : {len(failed)}  (raised — needs attention, NOT in the DB)")
        for x in failed:
            print(f"      {x['file']}  {x['error']}")
    print("Processing complete!")


if __name__ == "__main__":
    main()

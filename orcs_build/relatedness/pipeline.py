"""Gm3558-anchored relatedness pipeline over the offline ORCS mouse archive.

Six steps (client's design), all anchored on one gene, mouse only, stdlib only:
  1 classify -> 2 harmonize (+core-essential gate) -> 3 gene x screen matrix ->
  4 channels (co-essentiality / co-hit / co-citation / contextual) ->
  5 score (effect x support x significance, BH-FDR, tier) -> 6 validate.

Guardrails: never cross organism; a pair's evidence only counts screens that measured
both genes; co-hit significance is tested only on FULL-coverage screens (where the tested
set is known); support is reported at the distinct-publication level to blunt the
pseudo-replication of same-paper replicate screens.
"""
from __future__ import annotations

import math
import re
import urllib.parse
import urllib.request
from collections import defaultdict

from . import stats
from .core_essential_mouse import is_core_essential, is_fitness_phenotype

# ---- tunable thresholds (surfaced in the manifest) ------------------------
MIN_COESS_SCREENS = 10     # min shared FULL screens for a co-essentiality edge to be computed
COESS_N_STRONG = 20        # shared-screen support required for a "strong" co-essentiality edge
COESS_N_MOD = 15           # shared-screen support required for a "moderate" co-essentiality edge
COESS_RHO = 0.5            # min |rho| to enter the co-essentiality candidate pool
COESS_HF_MAX = 0.4         # max genome-wide hit-frequency for a "specific" co-essentiality edge
COESS_Q = 0.01            # (reserved) strict BH-q reference for co-essentiality
COHIT_Q_WEAK = 0.10
COHIT_Q_MOD = 0.05
COHIT_Q_STRONG = 0.01
GATE_TOP_FRAC = 0.10       # "tail" decile for the core-essential gate
GATE_PASS_FRAC = 0.30      # >= this fraction of essentials in the tail -> gate PASS


def _to_float(s: str):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _clean_pheno(p: str) -> str:
    return re.sub(r"\s+", " ", (p or "").strip()).lower()


# ---------------------------------------------------------------------------
# Step 1 — classify screen coverage
# ---------------------------------------------------------------------------
def classify_screens(ex, classify_fn) -> dict:
    return {r.screen_id: classify_fn(ex.screen_tables[r.screen_id]) for r in ex.gene_rows}


# ---------------------------------------------------------------------------
# Step 2 — harmonize scores (hit-anchored within-screen percentile) + gate
# ---------------------------------------------------------------------------
def harmonize_scores(ex, screen_class) -> tuple[dict, dict]:
    """Return (harmonized[sid][symbol]->[0,1], report[sid]->dict) for FULL screens."""
    harmonized: dict[str, dict[str, float]] = {}
    report: dict[str, dict] = {}
    for sid, cls in screen_class.items():
        if cls["coverage"] != "FULL":
            continue
        rows = ex.screen_tables[sid]
        scored = [(r.symbol, _to_float(r.scores[0]), r.hit) for r in rows]
        scored = [(s, v, h) for (s, v, h) in scored if s and v is not None]
        if len(scored) < 50:
            continue
        vals = [v for _, v, _ in scored]
        ranks = stats._ranks(vals)                     # 1..n, ties averaged
        n = len(scored)
        pct = {scored[i][0]: (ranks[i] - 1) / (n - 1) for i in range(n)}   # 0..1, high=large score
        hit_syms = [s for s, _, h in scored if h]
        hit_med = (sorted(pct[s] for s in hit_syms)[len(hit_syms) // 2]
                   if hit_syms else 0.5)
        flip = hit_med < 0.5                            # orient so called hits sit high
        harmonized[sid] = {s: (1.0 - v if flip else v) for s, v in pct.items()}

        meta = ex.screen_meta.get(sid, {})
        pheno = meta.get("PHENOTYPE", "")
        gate = _core_essential_gate(harmonized[sid], pheno)
        report[sid] = {
            "direction": "flipped" if flip else "as-is",
            "hit_percentile_median": round(hit_med, 3),
            "n_scored": n, "score1_type": meta.get("SCORE.1_TYPE", ""),
            "phenotype": pheno, **gate,
        }
    return harmonized, report


def _core_essential_gate(hvals: dict[str, float], phenotype: str) -> dict:
    if not is_fitness_phenotype(phenotype):
        return {"gate": "N/A", "gate_detail": "non-fitness phenotype"}
    ess = [s for s in hvals if is_core_essential(s)]
    if len(ess) < 10:
        return {"gate": "N/A", "gate_detail": f"only {len(ess)} essential genes present"}
    thresh = 1.0 - GATE_TOP_FRAC
    in_tail = sum(1 for s in ess if hvals[s] >= thresh)
    frac = in_tail / len(ess)
    return {"gate": "PASS" if frac >= GATE_PASS_FRAC else "WARN",
            "gate_detail": f"{in_tail}/{len(ess)} core-essential genes in top decile ({frac:.2f})"}


# ---------------------------------------------------------------------------
# Step 3 — gene x screen matrix (harmonized percentile) for co-essentiality
# ---------------------------------------------------------------------------
def build_gene_screen_matrix(harmonized: dict) -> dict:
    """gene_symbol -> {screen_id: harmonized_percentile} over FULL screens."""
    matrix: dict[str, dict[str, float]] = defaultdict(dict)
    for sid, col in harmonized.items():
        for sym, val in col.items():
            matrix[sym][sid] = val
    return matrix


# ---------------------------------------------------------------------------
# Step 4 — channels
# ---------------------------------------------------------------------------
def _screen_sets(ex, sids):
    hit = {sid: {r.symbol for r in ex.screen_tables[sid] if r.hit and r.symbol} for sid in sids}
    present = {sid: {r.symbol for r in ex.screen_tables[sid] if r.symbol} for sid in sids}
    return hit, present


def compute_cohit(ex, target, full_sids, hit, present, pub_of):
    """Per-candidate co-hit 2x2 over FULL screens; returns dict sym -> metrics.

    Two nulls: `cohit_p` (Fisher within Gm3558's screen set) tests whether the overlap
    exceeds chance given the screen composition; `spec_p` (binomial vs the gene's own
    genome-wide hit frequency) tests whether it exceeds the gene's promiscuity — the
    defense against pan-essential 'hub' genes co-hitting everything.
    """
    tgt_hit_full = {sid for sid in full_sids if target in hit[sid]}
    candidates = set()
    for sid in tgt_hit_full:
        candidates |= hit[sid]
    candidates.discard(target)
    candidates = {c for c in candidates if c and not c.startswith("ENTREZ:")}

    out = {}
    for cand in candidates:
        shared = [sid for sid in full_sids if cand in present[sid]]
        if not shared:
            continue
        both = [sid for sid in shared if cand in hit[sid] and target in hit[sid]]
        a = len(both)
        if a == 0:
            continue
        tgt_h = sum(1 for sid in shared if target in hit[sid])
        cand_h = sum(1 for sid in shared if cand in hit[sid])
        b, c = tgt_h - a, cand_h - a
        d = len(shared) - a - b - c
        p = stats.fisher_right(a, b, c, d)
        pubs = {pub_of[sid] for sid in both}
        hf = ex.hit_frequency(cand)
        out[cand] = {
            "n_cohit": a, "n_cohit_pubs": len(pubs), "cohit_pubs": sorted(pubs),
            "n_shared_full": len(shared), "target_hits": tgt_h, "cand_hits": cand_h,
            "odds_ratio": round(stats.odds_ratio(a, b, c, d), 3),
            "jaccard": round(a / (tgt_h + cand_h - a), 3) if (tgt_h + cand_h - a) else 0.0,
            "cohit_p": p,
            "hit_freq_all": round(hf, 4),
            "spec_p": stats.binom_right(a, tgt_h, hf),
            "spec_enrichment": round((a / tgt_h) / hf, 2) if (hf > 0 and tgt_h) else None,
        }
    return out


def compute_coessentiality(matrix, target, full_sids, ex):
    """Spearman of the target's harmonized profile vs every gene, over shared FULL screens."""
    tvec = matrix.get(target, {})
    tscreens = set(tvec)
    out = {}
    for sym, col in matrix.items():
        if sym == target:
            continue
        shared = tscreens & set(col)
        if len(shared) < MIN_COESS_SCREENS:
            continue
        order = sorted(shared)
        xs = [tvec[s] for s in order]
        ys = [col[s] for s in order]
        rho = stats.spearman(xs, ys)
        if rho is None:
            continue
        out[sym] = {"rho": round(rho, 4), "n_coess": len(shared),
                    "coess_p": stats.spearman_pvalue(rho, len(shared)),
                    "hit_freq_all": round(ex.hit_frequency(sym), 4)}
    return out


def compute_cocitation(ex, target, hit, pub_of):
    """Genes hit in the same source publication as the target (across the target's screens)."""
    tgt_hit_screens = [r.screen_id for r in ex.gene_rows if r.hit]
    tgt_pubs = {pub_of[sid] for sid in tgt_hit_screens}
    genes_by_pub = defaultdict(set)
    for r in ex.gene_rows:
        pub = pub_of[r.screen_id]
        if pub in tgt_pubs:
            genes_by_pub[pub] |= hit.get(r.screen_id, set())
    for pub in genes_by_pub:
        genes_by_pub[pub].discard(target)
    out = defaultdict(lambda: {"n_shared_pubs": 0, "shared_pubs": []})
    for pub, genes in genes_by_pub.items():
        for g in genes:
            if not g or g.startswith("ENTREZ:"):
                continue
            out[g]["n_shared_pubs"] += 1
            out[g]["shared_pubs"].append(pub)
    return dict(out), sorted(tgt_pubs)


def compute_contextual(ex, target, hit):
    """Co-hit stratified by phenotype context (>=2 target hit screens per context)."""
    tgt_hits = [r.screen_id for r in ex.gene_rows if r.hit]
    ctx_screens = defaultdict(list)
    for sid in tgt_hits:
        pheno = _clean_pheno(ex.screen_meta.get(sid, {}).get("PHENOTYPE", "")) or "unspecified"
        ctx_screens[pheno].append(sid)
    ctx_screens = {k: v for k, v in ctx_screens.items() if len(v) >= 2}
    out = defaultdict(dict)
    for ctx, sids in ctx_screens.items():
        for sid in sids:
            for g in hit.get(sid, set()):
                if not g or g == target or g.startswith("ENTREZ:"):
                    continue
                out[g].setdefault(ctx, 0)
                out[g][ctx] += 1
    return dict(out), {k: len(v) for k, v in ctx_screens.items()}


# ---------------------------------------------------------------------------
# Step 5 — score, FDR, tier
# ---------------------------------------------------------------------------
def score_gene_relatedness(cohit, coess, cocit, contextual):
    # Support pre-filter: only test genes co-hit in >=2 FULL screens (never test singletons),
    # then BH-FDR over that pre-registered set — for both the within-set (Fisher) and the
    # specificity (binomial vs background) nulls.
    tested = [s for s, v in cohit.items() if v["n_cohit"] >= 2]
    ch_q = dict(zip(tested, stats.bh_fdr([cohit[s]["cohit_p"] for s in tested]))) if tested else {}
    sp_q = dict(zip(tested, stats.bh_fdr([cohit[s]["spec_p"] for s in tested]))) if tested else {}
    ce_syms = list(coess)
    ce_q = dict(zip(ce_syms, stats.bh_fdr([coess[s]["coess_p"] for s in ce_syms]))) if ce_syms else {}

    syms = set(tested) | {s for s, v in coess.items()
                          if v["rho"] >= COESS_RHO and v["n_coess"] >= MIN_COESS_SCREENS}

    relatives, nonspecific, dropped = [], [], 0
    for s in syms:
        ch = cohit.get(s)
        ce = coess.get(s)
        rec = {
            "gene": s, "is_core_essential": is_core_essential(s),
            "hit_freq_all": (ch or ce or {}).get("hit_freq_all", 0.0),
            "n_cohit": ch["n_cohit"] if ch else 0,
            "n_cohit_pubs": ch["n_cohit_pubs"] if ch else 0,
            "odds_ratio": ch["odds_ratio"] if ch else None,
            "jaccard": ch["jaccard"] if ch else None,
            "cohit_p": ch["cohit_p"] if ch else None,
            "cohit_q": ch_q.get(s),
            "spec_enrichment": ch["spec_enrichment"] if ch else None,
            "spec_q": sp_q.get(s),
            "rho": ce["rho"] if ce else None,
            "n_coess": ce["n_coess"] if ce else None,
            "coess_q": ce_q.get(s),
            "n_shared_pubs": cocit.get(s, {}).get("n_shared_pubs", 0),
            "contexts": contextual.get(s, {}),
        }
        tier, specific = _tier(rec)
        if tier is None:
            dropped += 1
            continue
        rec["tier"] = tier
        rec["strength"] = _strength(rec)
        rec["channels"] = _channels(rec)
        (relatives if specific else nonspecific).append(rec)

    keyf = lambda r: (-{"Strong": 3, "Moderate": 2, "Weak": 1}[r["tier"]],
                      -r["n_cohit_pubs"], (r["cohit_q"] if r["cohit_q"] is not None else 1.0),
                      -(r["strength"]))
    relatives.sort(key=keyf)
    nonspecific.sort(key=keyf)
    return relatives, nonspecific, dropped


def _tier(r) -> tuple[str | None, bool]:
    """Return (tier, is_specific). Tier = how many independent relatedness channels
    concur. `is_specific` = the co-hit exceeds the gene's own genome-wide promiscuity
    (spec_q), not just chance within Gm3558's fitness-loaded screen set (cohit_q)."""
    a, pubs, cq, sq, enr = (r["n_cohit"], r["n_cohit_pubs"], r["cohit_q"],
                            r["spec_q"], r["spec_enrichment"] or 0.0)
    rho, eq, hf = r["rho"], r["coess_q"], r["hit_freq_all"]

    cohit_specific = (a >= 2 and cq is not None and cq < COHIT_Q_MOD
                      and sq is not None and sq < COHIT_Q_WEAK and enr >= 1.5 and pubs >= 2)
    cohit_realish = (a >= 2 and cq is not None and cq < COHIT_Q_MOD and pubs >= 2)  # may be promiscuous
    # co-essentiality: "specific" requires strong rho, high shared-screen support, AND a
    # non-promiscuous partner (hf<0.4); "mod" is the corroborating (not standalone) bar.
    coess_specific = (rho is not None and rho >= 0.6 and eq is not None and eq < 0.05
                      and (r["n_coess"] or 0) >= COESS_N_STRONG and hf < COESS_HF_MAX)
    coess_mod = (rho is not None and rho >= 0.45 and eq is not None and eq < 0.05
                 and (r["n_coess"] or 0) >= COESS_N_MOD and hf < 0.6)

    # Tier = how many independent channels agree. Strong/Moderate need co-hit specificity
    # AND co-essentiality; a single channel is at most Weak.
    if cohit_specific and coess_specific:
        return "Strong", True
    if cohit_specific and coess_mod:
        return "Moderate", True
    if coess_specific and cohit_realish:
        return "Moderate", True
    if cohit_specific:
        return "Weak", True
    if coess_specific:
        return "Weak", True
    # co-hit is real within Gm3558's set but explained by the gene's own promiscuity
    if cohit_realish:
        return "Weak", False
    return None, False


def _strength(r) -> float:
    parts = [
        min(1.0, r["n_cohit_pubs"] / 4.0),
        min(1.0, r["n_cohit"] / 6.0),
        min(1.0, -math.log10((r["cohit_q"] or 1.0) + 1e-12) / 4.0) if r["cohit_q"] else 0.0,
        max(0.0, r["rho"] or 0.0),
        min(1.0, r["n_shared_pubs"] / 4.0),
    ]
    return round(sum(parts) / len(parts), 4)


def _channels(r) -> list[str]:
    ch = []
    if r["n_cohit"] >= 2 and r["cohit_q"] is not None:
        ch.append("co-hit")
    if r["rho"] is not None and r["rho"] >= COESS_RHO:
        ch.append("co-essentiality")
    if r["n_shared_pubs"] >= 2:
        ch.append("co-citation")
    if r["contexts"]:
        ch.append("contextual")
    return ch


# ---------------------------------------------------------------------------
# Step 6 — validate (core-essential sanity + best-effort STRING mouse)
# ---------------------------------------------------------------------------
def validate_relatedness(target, relatives, nonspecific, top_n=25) -> dict:
    top = relatives[:top_n]
    promisc = (sum(1 for r in top if r["hit_freq_all"] > 0.4) / len(top)) if top else 0.0
    string = _string_mouse_check(target, [r["gene"] for r in top[:15]])
    return {
        "n_relatives": len(relatives),
        "n_nonspecific": len(nonspecific),
        "n_strong": sum(1 for r in relatives if r["tier"] == "Strong"),
        "n_moderate": sum(1 for r in relatives if r["tier"] == "Moderate"),
        "n_weak": sum(1 for r in relatives if r["tier"] == "Weak"),
        "top_promiscuous_fraction": round(promisc, 3),
        "hub_contamination_warn": promisc > 0.5,
        "string_mouse": string,
    }


def _string_mouse_check(target, genes) -> dict:
    """Best-effort: how many top relatives STRING links to each other/target (taxid 10090)."""
    if not genes:
        return {"status": "skipped", "detail": "no genes"}
    ids = [target] + genes
    url = "https://string-db.org/api/tsv-no-header/network?" + urllib.parse.urlencode(
        {"identifiers": "%0d".join(ids), "species": "10090",
         "caller_identity": "reticle_dossier"}, safe="%")
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return {"status": "unreachable", "detail": type(e).__name__}
    edges = [ln for ln in text.splitlines() if ln.strip()]
    target_edges = sum(1 for ln in edges
                       if target.lower() in ln.lower().split("\t")[2:4] if len(ln.split("\t")) > 3)
    return {"status": "ok", "n_edges_among_top": len(edges),
            "n_edges_touching_target": target_edges,
            "note": "Gm3558 is an uncharacterized gene; sparse STRING support is expected."}


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
def run_relatedness(ex, classify_fn, target=None) -> dict:
    target = target or ex.target
    screen_class = classify_screens(ex, classify_fn)
    harmonized, harm_report = harmonize_scores(ex, screen_class)
    matrix = build_gene_screen_matrix(harmonized)

    full_sids = [sid for sid, c in screen_class.items() if c["coverage"] == "FULL"]
    all_sids = [r.screen_id for r in ex.gene_rows]
    pub_of = {}
    for sid in all_sids:
        m = ex.screen_meta.get(sid, {})
        src = (m.get("SOURCE_ID") or "").strip()
        pub_of[sid] = src if (m.get("SOURCE_TYPE", "").lower() == "pubmed" and src) else f"CUSTOM:{sid}"

    hit_all, present_all = _screen_sets(ex, all_sids)

    cohit = compute_cohit(ex, target, full_sids, hit_all, present_all, pub_of)
    coess = compute_coessentiality(matrix, target, full_sids, ex)
    cocit, tgt_pubs = compute_cocitation(ex, target, hit_all, pub_of)
    contextual, ctx_sizes = compute_contextual(ex, target, hit_all)

    relatives, nonspecific, dropped = score_gene_relatedness(cohit, coess, cocit, contextual)
    validation = validate_relatedness(target, relatives, nonspecific)

    return {
        "target": target,
        "screen_class": screen_class,
        "harmonization": harm_report,
        "n_full_screens": len(full_sids),
        "n_archive_screens": ex.n_archive_screens,
        "contexts": ctx_sizes,
        "target_hit_publications": tgt_pubs,
        "n_candidates_cohit": len(cohit),
        "n_candidates_coess": len(coess),
        "relatives": relatives,
        "nonspecific": nonspecific,
        "dropped_low_support": dropped,
        "validation": validation,
        "channels_raw": {"cohit": cohit, "coess": coess, "cocit": cocit, "contextual": contextual},
        "thresholds": {
            "MIN_COESS_SCREENS": MIN_COESS_SCREENS, "COESS_RHO": COESS_RHO,
            "COESS_Q": COESS_Q, "COHIT_Q_STRONG": COHIT_Q_STRONG,
            "COHIT_Q_MOD": COHIT_Q_MOD, "COHIT_Q_WEAK": COHIT_Q_WEAK,
        },
    }

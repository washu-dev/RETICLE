#!/usr/bin/env python3
"""
rollup_relatedness.py — D9 driver: cross-channel roll-up + evidence summary.

Combines the per-channel columns each channel driver writes (D5 coess_*, D6
cohit_*, D7 cocite_*, D8 context_*) into the unified header fields on
fact_gene_pair:

  relatedness_score      weighted, support-renormalized combination of the base
                         channels' effects (co-essentiality weighted highest)
  relatedness_tier       Strong | Moderate | Weak  (config tier_cuts.overall)
  evidence_channels      e.g. "coess,cohit,resid"  — which channels cleared support
  evidence_channel_count how many
  total_support          coess+cohit+cocite+context+resid support (breadth of evidence)
  min_fdr                best (smallest) FDR across channels (incl. resid_fdr)

A channel "contributes" to relatedness_score/relatedness_tier iff its per-channel
tier is non-NULL (it cleared support and has an effect). Weights renormalize
over the four BASE channels actually present (coess/cohit/cocite/context), so a
co-ess-only pair is scored on co-ess alone. D5b's novelty channel (resid_tier,
plus the is_antagonistic/is_buffering_candidate flags) is recorded alongside and
DOES appear in evidence_channels/evidence_channel_count/total_support/min_fdr —
design/gene_relatedness_design.md §6.7 is explicit that novelty surfaces as its
own facet — but is deliberately excluded from the relatedness_score/tier weighted
average so it never dilutes the base roll-up (a "novel" edge stays distinguishable
from a plain strong one).

Idempotent, set-based single UPDATE over (version_id, config_id). Login-node,
DB-only — no GPU/SLURM. Re-run after any channel driver adds/updates columns.

Usage:
  python3 rollup_relatedness.py --version 7 --config-id 2
  python3 rollup_relatedness.py --version 7 --config-id 2 --dry-run
"""

import argparse
import logging
import sys

import psycopg2
import psycopg2.extras

import relatedness_core as rc

logger = logging.getLogger("rollup_relatedness")

# base-channel weights (co-essentiality highest); overridable via config
# thresholds.channel_weights. Renormalized over the channels present per pair.
DEFAULT_WEIGHTS = {"coess": 0.45, "cohit": 0.25, "cocite": 0.15, "context": 0.15}
DEFAULT_OVERALL_CUTS = {"strong": 0.50, "moderate": 0.30}

# score = Σ w_i·effect_i·present_i / Σ w_i·present_i   (present_i = per-channel tier not null)
_SCORE_SUBQUERY = """
    SELECT gene_pair_id,
        ( %(w_coess)s   * COALESCE(coess_effect,0)         * (coess_tier   IS NOT NULL)::int
        + %(w_cohit)s   * COALESCE(cohit_effect_jaccard,0) * (cohit_tier   IS NOT NULL)::int
        + %(w_cocite)s  * COALESCE(cocite_effect_jaccard,0)* (cocite_tier  IS NOT NULL)::int
        + %(w_context)s * COALESCE(context_effect,0)       * (context_tier IS NOT NULL)::int )
        / NULLIF( %(w_coess)s   * (coess_tier   IS NOT NULL)::int
                + %(w_cohit)s   * (cohit_tier   IS NOT NULL)::int
                + %(w_cocite)s  * (cocite_tier  IS NOT NULL)::int
                + %(w_context)s * (context_tier IS NOT NULL)::int, 0) AS score
    FROM fact_gene_pair
    WHERE version_id = %(v)s AND config_id = %(c)s
"""

_TIER_EXPR = ("CASE WHEN sc.score >= %(strong)s THEN 'Strong' "
              "WHEN sc.score >= %(moderate)s THEN 'Moderate' ELSE 'Weak' END")

# gene_pair_id window filter, appended to the score subquery + outer UPDATE so the
# roll-up runs in chunks (progress bar + short transactions on a small RDS).
_RANGE = "\n      AND gene_pair_id >= %(lo)s AND gene_pair_id < %(hi)s"

_CHUNK = 250_000   # gene_pair_id window per committed batch


def connect():
    return rc.pg_connect()


def _progress(total, desc):
    """tqdm bar if available, else a plain-text percentage line."""
    try:
        from tqdm import tqdm
        return tqdm(total=total, desc=desc, unit="pair", unit_scale=True)
    except Exception:
        class _Bar:
            def __init__(self):
                self.n = 0
            def update(self, k):
                self.n += k
                pct = 100 * self.n / max(total, 1)
                print(f"\r  {desc}: {self.n:,}/{total:,} ({pct:5.1f}%)", end="", flush=True)
            def close(self):
                print()
        return _Bar()


def resolve_config(conn, version_id, config_id, label):
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if config_id is not None:
        cur.execute("SELECT * FROM relatedness_config WHERE config_id=%s AND data_load_version_id=%s",
                    (config_id, version_id))
    elif label is not None:
        cur.execute("SELECT * FROM relatedness_config WHERE data_load_version_id=%s AND label=%s",
                    (version_id, label))
    else:
        cur.execute("SELECT * FROM relatedness_config WHERE data_load_version_id=%s AND status='accepted'",
                    (version_id,))
    cfgs = cur.fetchall()
    if not cfgs:
        raise SystemExit(f"No matching relatedness_config for version {version_id} "
                         f"(accept one, or pass --config-id/--label)")
    if len(cfgs) > 1:
        raise SystemExit(f"{len(cfgs)} accepted configs; disambiguate with --config-id/--label")
    return cfgs[0]


def main():
    ap = argparse.ArgumentParser(description="D9 cross-channel relatedness roll-up")
    ap.add_argument("--version", type=int, required=True)
    ap.add_argument("--config-id", type=int, default=None)
    ap.add_argument("--label", default=None)
    ap.add_argument("--dry-run", action="store_true", help="report the tier distribution; write nothing")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO),
                        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    conn = connect()
    try:
        cfg = resolve_config(conn, args.version, args.config_id, args.label)
        config_id = cfg["config_id"]
        th = cfg["thresholds"] or {}
        weights = {**DEFAULT_WEIGHTS, **(th.get("channel_weights") or {})}
        cuts = {**DEFAULT_OVERALL_CUTS, **((th.get("tier_cuts") or {}).get("overall") or {})}
        params = {
            "v": args.version, "c": config_id,
            "w_coess": weights["coess"], "w_cohit": weights["cohit"],
            "w_cocite": weights["cocite"], "w_context": weights["context"],
            "strong": cuts["strong"], "moderate": cuts["moderate"],
        }
        logger.info(f"version={args.version} config_id={config_id} weights={weights} overall_cuts={cuts}")

        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM fact_gene_pair WHERE version_id=%s AND config_id=%s",
                    (args.version, config_id))
        n_pairs = cur.fetchone()[0]
        if n_pairs == 0:
            raise SystemExit(f"No fact_gene_pair rows for version {args.version} config {config_id} "
                             f"— run a channel (D5/D6) first.")
        logger.info(f"{n_pairs:,} pairs to roll up")

        if args.dry_run:
            cur.execute(f"""
                SELECT {_TIER_EXPR} AS tier, COUNT(*) AS n
                FROM ({_SCORE_SUBQUERY}) sc GROUP BY 1 ORDER BY 1
            """, params)
            print(f"[dry-run] relatedness_tier distribution (version {args.version}, config {config_id}):")
            for tier, n in cur.fetchall():
                print(f"  {tier or 'NULL':10s} {n:>12,}")
            return

        # Chunk by gene_pair_id: gives a progress bar and keeps each transaction
        # short (a single UPDATE over 10M+ rows is one long transaction — risky on
        # a small RDS). Each chunk commits independently; the roll-up is idempotent.
        cur.execute("SELECT MIN(gene_pair_id), MAX(gene_pair_id) FROM fact_gene_pair "
                    "WHERE version_id=%s AND config_id=%s", (args.version, config_id))
        lo_id, hi_id = cur.fetchone()

        ranged_update = f"""
            UPDATE fact_gene_pair f SET
                evidence_channels = concat_ws(',',
                    CASE WHEN f.coess_tier   IS NOT NULL THEN 'coess'   END,
                    CASE WHEN f.cohit_tier   IS NOT NULL THEN 'cohit'   END,
                    CASE WHEN f.cocite_tier  IS NOT NULL THEN 'cocite'  END,
                    CASE WHEN f.context_tier IS NOT NULL THEN 'context' END,
                    CASE WHEN f.resid_tier   IS NOT NULL THEN 'resid'   END,
                    CASE WHEN f.is_buffering_candidate THEN 'buffering' END),
                evidence_channel_count =
                    (f.coess_tier IS NOT NULL)::int + (f.cohit_tier IS NOT NULL)::int
                  + (f.cocite_tier IS NOT NULL)::int + (f.context_tier IS NOT NULL)::int
                  + (f.resid_tier IS NOT NULL)::int + COALESCE(f.is_buffering_candidate, FALSE)::int,
                total_support = COALESCE(f.coess_support,0) + COALESCE(f.cohit_support,0)
                  + COALESCE(f.cocite_support,0) + COALESCE(f.context_support,0) + COALESCE(f.resid_support,0),
                min_fdr = LEAST(f.coess_fdr, f.cohit_fdr, f.cocite_fdr, f.context_best_fdr, f.resid_fdr),
                relatedness_score = sc.score,
                relatedness_tier = {_TIER_EXPR},
                is_current = TRUE
            FROM ({_SCORE_SUBQUERY}{_RANGE}) sc
            WHERE f.gene_pair_id = sc.gene_pair_id
              AND f.version_id = %(v)s AND f.config_id = %(c)s
              AND f.gene_pair_id >= %(lo)s AND f.gene_pair_id < %(hi)s
        """
        bar = _progress(n_pairs, "roll-up")
        updated = 0
        start = lo_id
        while start is not None and start <= hi_id:
            cur.execute(ranged_update, {**params, "lo": start, "hi": start + _CHUNK})
            conn.commit()
            updated += cur.rowcount
            bar.update(cur.rowcount)
            start += _CHUNK
        bar.close()

        cur.execute("""SELECT relatedness_tier, COUNT(*),
                              round(AVG(evidence_channel_count),2)
                       FROM fact_gene_pair WHERE version_id=%s AND config_id=%s
                       GROUP BY relatedness_tier ORDER BY relatedness_tier""",
                    (args.version, config_id))
        logger.info(f"Rolled up {updated:,} pairs")
        print(f"Roll-up complete (version {args.version}, config {config_id}): {updated:,} pairs")
        for tier, n, avg_ch in cur.fetchall():
            print(f"  {tier:10s} {n:>12,}   (avg {avg_ch} channels)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

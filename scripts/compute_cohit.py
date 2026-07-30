#!/usr/bin/env python3
"""
compute_cohit.py — D6 driver: co-hit enrichment (Channel 2), warehouse-native, CPU.

The cheap, EXACT complement to co-essentiality. Over the selective-gene hit sets
(screen_gene_raw.hit_flag), it computes per gene pair:
  * co-hit support   n11 = # screens where BOTH are hits   (sparse Hᵀ·H)
  * Jaccard          n11 / (a_hits + b_hits − n11)
  * PMI (log2)       log2( n11·N / (a_hits·b_hits) )
  * enrichment p     one-sided hypergeometric tail (= one-sided Fisher exact),
                     then BH-FDR across the tested (support-clearing) pairs.
Writes the cohit_* columns of fact_gene_pair (upsert; leaves coess_* untouched so
D5 and D6 compose). No GPU — sparse integer co-occurrence is cheap.

Marginals use the version-global hit universe: a_hits/b_hits are each gene's total
hit count, N = total screens in the version (documented approximation vs per-pair
co-measurement — for genome-wide screens co-measurement is ~complete anyway; the
schema carries a single cohit_screens_total per pair by design).

Usage (via slurm/reticle-cohit.sh):
  python3 compute_cohit.py --version 7 --config-id 2
  python3 compute_cohit.py --version 7 --config-id 2 --dry-run
"""

import argparse
import logging
import sys
import time

import numpy as np
import psycopg2
import psycopg2.extras

from config import Config
import relatedness_core as rc

logger = logging.getLogger("compute_cohit")

COMPUTE_VERSION = "d6-cohit-1.0"


class CoHitCompute:
    def __init__(self, version_id, config_id=None, label=None, min_cohit=None,
                 fdr_alpha=None, dry_run=False):
        self.version_id = version_id
        self.config_id = config_id
        self.label = label
        self.min_cohit = min_cohit
        self.fdr_alpha = fdr_alpha
        self.dry_run = dry_run
        self.conn = None

    def connect(self):
        params = Config.get_psycopg2_params()
        params["sslmode"] = "require"
        self.conn = psycopg2.connect(**params)
        self.conn.autocommit = False
        cur = self.conn.cursor()
        cur.execute("SET statement_timeout = 0")
        cur.execute("SET work_mem = '256MB'")
        self.conn.commit()
        logger.info("Connected to database")

    def resolve(self):
        cur = self.conn.cursor()
        cur.execute("SELECT organism FROM data_load_version WHERE version_id=%s", (self.version_id,))
        row = cur.fetchone()
        if not row:
            raise SystemExit(f"version_id {self.version_id} not found")
        self.organism = row[0]

        rc_cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        if self.config_id is not None:
            rc_cur.execute("SELECT * FROM relatedness_config WHERE config_id=%s AND data_load_version_id=%s",
                           (self.config_id, self.version_id))
        elif self.label is not None:
            rc_cur.execute("SELECT * FROM relatedness_config WHERE data_load_version_id=%s AND label=%s",
                           (self.version_id, self.label))
        else:
            rc_cur.execute("SELECT * FROM relatedness_config WHERE data_load_version_id=%s AND status='accepted'",
                           (self.version_id,))
        cfgs = rc_cur.fetchall()
        if not cfgs:
            raise SystemExit(f"No matching relatedness_config for version {self.version_id} "
                             f"(accept one, or pass --config-id/--label)")
        if len(cfgs) > 1:
            raise SystemExit(f"{len(cfgs)} accepted configs; disambiguate with --config-id/--label")
        cfg = cfgs[0]
        self.config_id = cfg["config_id"]
        th = cfg["thresholds"] or {}
        self.min_cohit = self.min_cohit if self.min_cohit is not None else (th.get("min_cohit_screens") or 3)
        self.fdr_alpha = self.fdr_alpha if self.fdr_alpha is not None else th.get("fdr_alpha", 0.01)
        self.tier_cuts = (th.get("tier_cuts") or {}).get("co_hit", {"strong": 0.50, "moderate": 0.20})
        self.sel_filter = th.get("selective_gene_filter", {})

        cur.execute("SELECT run_id FROM etl_pipeline_run WHERE data_load_version_id=%s "
                    "ORDER BY run_id DESC LIMIT 1", (self.version_id,))
        r = cur.fetchone()
        if not r:
            raise SystemExit(f"No etl_pipeline_run for version {self.version_id}")
        self.run_id = r[0]

        cur.execute("SELECT COUNT(*) FROM screen WHERE version_id=%s", (self.version_id,))
        self.n_screens_total = int(cur.fetchone()[0])
        logger.info(f"version={self.version_id} organism={self.organism} config_id={self.config_id} "
                    f"run_id={self.run_id} min_cohit={self.min_cohit} N_screens={self.n_screens_total}")

    def load(self):
        cur = self.conn.cursor()
        cur.execute("""SELECT gene_id, COUNT(DISTINCT screen_id) AS m,
                              COUNT(DISTINCT screen_id) FILTER (WHERE hit_flag) AS h
                       FROM screen_gene_raw WHERE version_id=%s GROUP BY gene_id""", (self.version_id,))
        stats = cur.fetchall()
        gene_ids_all = np.array([int(g) for g, _, _ in stats], dtype=np.int64)
        n_meas = np.array([int(m) for _, m, _ in stats], dtype=np.int64)
        n_hit = np.array([int(h or 0) for _, _, h in stats], dtype=np.int64)
        cls = rc.classify_selective(
            n_meas, n_hit,
            pan_essential_rate=self.sel_filter.get("pan_essential_rate", 0.90),
            min_measured_screens=self.sel_filter.get("min_measured_screens", 2))
        self.gene_ids = gene_ids_all[cls["selective"]]
        self.n_sel = int(self.gene_ids.size)
        logger.info(f"Selective genes: {self.n_sel:,}")

        cur.execute("SELECT gene_id, gene_symbol FROM gene WHERE version_id=%s", (self.version_id,))
        sym = {int(g): s for g, s in cur.fetchall()}
        self.symbols = np.array([sym.get(int(g), "") for g in self.gene_ids], dtype=object)

        # hit (gene, screen) pairs -> selective-gene × screen binary matrix
        hg, hs = [], []
        c2 = self.conn.cursor(name="cohit_hits")
        c2.itersize = 500_000
        c2.execute("SELECT gene_id, screen_id FROM screen_gene_raw "
                   "WHERE version_id=%s AND hit_flag=TRUE", (self.version_id,))
        while True:
            rows = c2.fetchmany(500_000)
            if not rows:
                break
            hg.extend(r[0] for r in rows)
            hs.extend(r[1] for r in rows)
        c2.close()
        self.H, n_scr = rc.selective_binary_csr(np.asarray(hg, dtype=np.int64),
                                                np.asarray(hs, dtype=np.int64), self.gene_ids)
        self.a_hits = np.asarray(self.H.sum(axis=1)).ravel().astype(np.int64)
        logger.info(f"Hit matrix: {self.n_sel:,} genes × {n_scr:,} screens with selective hits "
                    f"({int(self.H.nnz):,} hits)")

    def compute_and_write(self):
        from scipy.stats import hypergeom
        t0 = time.time()
        C = (self.H @ self.H.T).tocoo()
        upper = C.row < C.col
        r = C.row[upper]; c = C.col[upper]; n11 = C.data[upper].astype(np.int64)
        keep = n11 >= self.min_cohit
        r, c, n11 = r[keep], c[keep], n11[keep]
        logger.info(f"Co-hit: {C.nnz:,} co-occurring pairs, {len(n11):,} clear support "
                    f"(≥{self.min_cohit}) in {time.time()-t0:.0f}s")
        if len(n11) == 0:
            print("No pairs cleared the co-hit support floor — lower --min-cohit.")
            return {"pairs": 0}

        ah = self.a_hits[r]; bh = self.a_hits[c]
        N = self.n_screens_total
        union = ah + bh - n11
        jaccard = n11 / np.maximum(union, 1)
        pmi = np.log2((n11.astype(np.float64) * N) / np.maximum(ah * bh, 1))
        # one-sided hypergeometric enrichment p (= one-sided Fisher), vectorized
        p = hypergeom.sf(n11 - 1, N, ah, bh)
        p = np.clip(np.nan_to_num(p, nan=1.0), 0.0, 1.0)

        # BH-FDR across the tested (support-clearing) pairs
        L = len(p)
        order = np.argsort(p)
        fdr = np.empty(L)
        prev = 1.0
        for rank in range(L, 0, -1):
            idx = order[rank - 1]
            prev = min(prev, p[idx] * L / rank)
            fdr[idx] = min(prev, 1.0)

        strong = self.tier_cuts.get("strong", 0.50)
        moderate = self.tier_cuts.get("moderate", 0.20)
        tiers = np.where(jaccard >= strong, "Strong",
                         np.where(jaccard >= moderate, "Moderate", "Weak"))

        # canonicalize each pair by gene_id (a < b), swapping marginals/symbols
        ga = self.gene_ids[r]; gb = self.gene_ids[c]
        swap = ga > gb
        gene_a = np.where(swap, gb, ga); gene_b = np.where(swap, ga, gb)
        ah_a = np.where(swap, bh, ah);   bh_b = np.where(swap, ah, bh)
        la = np.where(swap, c, r);       lb = np.where(swap, r, c)

        rows_out = [(
            self.version_id, self.run_id, self.config_id, self.organism,
            int(gene_a[i]), int(gene_b[i]), str(self.symbols[la[i]]), str(self.symbols[lb[i]]),
            float(jaccard[i]), float(pmi[i]), int(n11[i]), int(ah_a[i]), int(bh_b[i]),
            int(N), float(p[i]), float(fdr[i]), str(tiers[i]),
            str(tiers[i]), float(jaccard[i]), "cohit", 1, int(n11[i]), float(fdr[i]),
        ) for i in range(L)]

        n_strong = int((tiers == "Strong").sum())
        n_mod = int((tiers == "Moderate").sum())
        logger.info(f"Tiers: {n_strong:,} Strong, {n_mod:,} Moderate, {L-n_strong-n_mod:,} Weak")

        if self.dry_run:
            print(f"[dry-run] would upsert {L:,} co-hit pairs into fact_gene_pair "
                  f"(config_id={self.config_id})")
            return {"pairs": L}

        cur = self.conn.cursor()
        psycopg2.extras.execute_values(cur, """
            INSERT INTO fact_gene_pair
                (version_id, run_id, config_id, organism, gene_a_id, gene_b_id,
                 gene_a_symbol, gene_b_symbol,
                 cohit_effect_jaccard, cohit_effect_pmi, cohit_support, cohit_a_hits,
                 cohit_b_hits, cohit_screens_total, cohit_fisher_p, cohit_fdr, cohit_tier,
                 relatedness_tier, relatedness_score, evidence_channels, evidence_channel_count,
                 total_support, min_fdr)
            VALUES %s
            ON CONFLICT (version_id, config_id, gene_a_id, gene_b_id) DO UPDATE SET
                cohit_effect_jaccard=EXCLUDED.cohit_effect_jaccard,
                cohit_effect_pmi=EXCLUDED.cohit_effect_pmi, cohit_support=EXCLUDED.cohit_support,
                cohit_a_hits=EXCLUDED.cohit_a_hits, cohit_b_hits=EXCLUDED.cohit_b_hits,
                cohit_screens_total=EXCLUDED.cohit_screens_total,
                cohit_fisher_p=EXCLUDED.cohit_fisher_p, cohit_fdr=EXCLUDED.cohit_fdr,
                cohit_tier=EXCLUDED.cohit_tier, is_current=TRUE
        """, rows_out, page_size=10000)
        self.conn.commit()
        logger.info(f"Upserted {L:,} co-hit pairs into fact_gene_pair")
        print(f"Wrote {L:,} co-hit pairs (config_id={self.config_id}, "
              f"{n_strong:,} Strong / {n_mod:,} Moderate).")
        return {"pairs": L, "strong": n_strong, "moderate": n_mod}

    def run(self):
        self.connect()
        self.resolve()
        self.load()
        self.compute_and_write()
        self.conn.close()
        return True


def main():
    ap = argparse.ArgumentParser(description="D6 co-hit enrichment (Channel 2) — CPU, warehouse-native")
    ap.add_argument("--version", type=int, required=True)
    ap.add_argument("--config-id", type=int, default=None)
    ap.add_argument("--label", default=None)
    ap.add_argument("--min-cohit", type=int, default=None, help="min screens both are hits (default: config min_cohit_screens)")
    ap.add_argument("--fdr-alpha", type=float, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO),
                        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    ok = CoHitCompute(args.version, config_id=args.config_id, label=args.label,
                      min_cohit=args.min_cohit, fdr_alpha=args.fdr_alpha,
                      dry_run=args.dry_run).run()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

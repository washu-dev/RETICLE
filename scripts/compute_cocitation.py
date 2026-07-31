#!/usr/bin/env python3
"""
compute_cocitation.py — D7 driver: co-citation (Channel 3), warehouse-native, CPU.

The "cold-start rescue" channel: genes that are notable (hit) in screens from the
SAME publications are related even with little direct screen overlap. Over the
selective-gene × publication hit matrix (fact_screen_gene_publication, P2), it
computes per pair — via one sparse Pᵀ·P:
  * shared-publication support  n11
  * Jaccard  n11 / (a_pubs + b_pubs − n11)
  * PMI (log2)  log2( n11·N / (a_pubs·b_pubs) )
  * one-sided hypergeometric enrichment p → BH-FDR across support-clearing pairs.
Fills fact_gene_pair.cocite_* (upsert; composes with coess_*/cohit_*). No GPU.

Prereq: P2 (populate_publications.py) — fact_screen_gene_publication must be
populated, else there is nothing to correlate. Tiers on PMI (config
tier_cuts.co_citation).

Usage (via slurm/reticle-cocitation.sh):
  python3 compute_cocitation.py --version 7 --config-id 2
  python3 compute_cocitation.py --version 7 --config-id 2 --dry-run
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

logger = logging.getLogger("compute_cocitation")

COMPUTE_VERSION = "d7-cocite-1.0"


class CoCitationCompute:
    def __init__(self, version_id, config_id=None, label=None, min_copub=None,
                 fdr_alpha=None, max_store=5_000_000, dry_run=False):
        self.version_id = version_id
        self.config_id = config_id
        self.label = label
        self.min_copub = min_copub
        self.fdr_alpha = fdr_alpha
        self.max_store = max_store
        self.dry_run = dry_run
        self.conn = None

    def connect(self):
        self.conn = rc.pg_connect()

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
        self.min_copub = self.min_copub if self.min_copub is not None else (th.get("min_copub_count") or 2)
        self.fdr_alpha = self.fdr_alpha if self.fdr_alpha is not None else th.get("fdr_alpha", 0.01)
        self.tier_cuts = (th.get("tier_cuts") or {}).get("co_citation", {"strong": 2.0, "moderate": 1.0})
        self.sel_filter = th.get("selective_gene_filter", {})

        cur.execute("SELECT run_id FROM etl_pipeline_run WHERE data_load_version_id=%s "
                    "ORDER BY run_id DESC LIMIT 1", (self.version_id,))
        r = cur.fetchone()
        if not r:
            raise SystemExit(f"No etl_pipeline_run for version {self.version_id}")
        self.run_id = r[0]

        cur.execute("SELECT COUNT(*) FROM fact_screen_gene_publication WHERE version_id=%s", (self.version_id,))
        if cur.fetchone()[0] == 0:
            raise SystemExit(f"fact_screen_gene_publication empty for version {self.version_id} — "
                             f"run populate_publications.py (P2) first.")
        cur.execute("SELECT COUNT(DISTINCT publication_id) FROM fact_screen_gene_publication WHERE version_id=%s",
                    (self.version_id,))
        self.n_pubs_total = int(cur.fetchone()[0])
        logger.info(f"version={self.version_id} organism={self.organism} config_id={self.config_id} "
                    f"run_id={self.run_id} min_copub={self.min_copub} N_pubs={self.n_pubs_total}")

    def load(self):
        cur = self.conn.cursor()
        cur.execute(rc.GENE_STATS_SQL, (self.version_id,))
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

        # gene × publication (hit) links -> selective-gene × publication matrix
        pg, pp = [], []
        c2 = self.conn.cursor(name="cocite_links")
        c2.itersize = 500_000
        c2.execute("SELECT gene_id, publication_id FROM fact_screen_gene_publication "
                   "WHERE version_id=%s AND hit_flag=TRUE", (self.version_id,))
        while True:
            rows = c2.fetchmany(500_000)
            if not rows:
                break
            pg.extend(r[0] for r in rows)
            pp.extend(r[1] for r in rows)
        c2.close()
        self.P, n_pub = rc.selective_binary_csr(np.asarray(pg, dtype=np.int64),
                                                np.asarray(pp, dtype=np.int64), self.gene_ids)
        self.a_pubs = np.asarray(self.P.sum(axis=1)).ravel().astype(np.int64)
        logger.info(f"Publication matrix: {self.n_sel:,} genes × {n_pub:,} publications "
                    f"({int(self.P.nnz):,} gene-pub hits)")

    _INSERT_SQL = """
        INSERT INTO fact_gene_pair
            (version_id, run_id, config_id, organism, gene_a_id, gene_b_id,
             gene_a_symbol, gene_b_symbol,
             cocite_effect_pmi, cocite_effect_jaccard, cocite_support, cocite_a_pubs,
             cocite_b_pubs, cocite_p_value, cocite_fdr, cocite_tier,
             relatedness_tier, relatedness_score, evidence_channels, evidence_channel_count,
             total_support, min_fdr)
        VALUES %s
        ON CONFLICT (version_id, config_id, gene_a_id, gene_b_id) DO UPDATE SET
            cocite_effect_pmi=EXCLUDED.cocite_effect_pmi,
            cocite_effect_jaccard=EXCLUDED.cocite_effect_jaccard,
            cocite_support=EXCLUDED.cocite_support, cocite_a_pubs=EXCLUDED.cocite_a_pubs,
            cocite_b_pubs=EXCLUDED.cocite_b_pubs, cocite_p_value=EXCLUDED.cocite_p_value,
            cocite_fdr=EXCLUDED.cocite_fdr, cocite_tier=EXCLUDED.cocite_tier, is_current=TRUE
    """

    def compute_and_write(self):
        t0 = time.time()
        C = (self.P @ self.P.T).tocoo()
        upper = C.row < C.col
        r = C.row[upper].astype(np.int32)
        c = C.col[upper].astype(np.int32)
        n11 = C.data[upper].astype(np.int32)
        del C, upper
        keep = n11 >= self.min_copub
        r, c, n11 = r[keep], c[keep], n11[keep]
        del keep
        n_tested = n11.size
        logger.info(f"Co-citation: {n_tested:,} pairs clear support (≥{self.min_copub}) "
                    f"in {time.time()-t0:.0f}s")
        if n_tested == 0:
            print("No pairs cleared the co-publication support floor — lower --min-copub.")
            return {"pairs": 0}

        # metrics + BH-FDR over the full tested space (kept as compact numpy, never
        # as Python rows). Only SIGNIFICANT pairs are materialized/stored — the
        # 100M+ weak co-occurrences (few source publications) are noise.
        ap = self.a_pubs[r].astype(np.int64)
        bp = self.a_pubs[c].astype(np.int64)
        N = self.n_pubs_total
        pmi = np.log2((n11.astype(np.float64) * N) / np.maximum(ap * bp, 1))
        p = rc.hypergeom_sf(n11, N, ap, bp)
        del ap, bp
        fdr = rc.bh_fdr(p)

        idx = np.where(fdr <= self.fdr_alpha)[0]
        n_sig = idx.size
        capped = idx.size > self.max_store
        if capped:                                    # keep top by PMI (no silent truncation)
            idx = idx[np.argpartition(-pmi[idx], self.max_store)[:self.max_store]]
        logger.info(f"{n_tested:,} tested, {n_sig:,} pass FDR≤{self.fdr_alpha}"
                    + (f" — capped to top {self.max_store:,} by PMI" if capped else "")
                    + f"; storing {idx.size:,}")
        if idx.size == 0:
            print(f"No co-citation pairs passed FDR≤{self.fdr_alpha} — nothing to store "
                  f"(loosen --fdr-alpha / --min-copub if expected).")
            return {"pairs": 0}
        if self.dry_run:
            print(f"[dry-run] would upsert {idx.size:,} co-citation pairs "
                  f"(of {n_tested:,} tested, {n_sig:,} significant).")
            return {"pairs": int(idx.size)}

        strong = self.tier_cuts.get("strong", 2.0)
        moderate = self.tier_cuts.get("moderate", 1.0)
        cur = self.conn.cursor()
        total = n_strong = n_mod = 0
        CH = 500_000
        for s in range(0, idx.size, CH):
            j = idx[s:s + CH]
            rr = r[j]; cc = c[j]; nn = n11[j].astype(np.int64)
            aa = self.a_pubs[rr].astype(np.int64); bb = self.a_pubs[cc].astype(np.int64)
            pm = pmi[j]; pv = p[j]; ff = fdr[j]
            jac = nn / np.maximum(aa + bb - nn, 1)
            tiers = np.where(pm >= strong, "Strong", np.where(pm >= moderate, "Moderate", "Weak"))
            ga = self.gene_ids[rr]; gb = self.gene_ids[cc]
            swap = ga > gb
            gene_a = np.where(swap, gb, ga); gene_b = np.where(swap, ga, gb)
            aa_a = np.where(swap, bb, aa); bb_b = np.where(swap, aa, bb)
            la = np.where(swap, cc, rr); lb = np.where(swap, rr, cc)
            batch = [(
                self.version_id, self.run_id, self.config_id, self.organism,
                int(gene_a[i]), int(gene_b[i]), str(self.symbols[la[i]]), str(self.symbols[lb[i]]),
                float(pm[i]), float(jac[i]), int(nn[i]), int(aa_a[i]), int(bb_b[i]),
                float(pv[i]), float(ff[i]), str(tiers[i]),
                str(tiers[i]), float(jac[i]), "cocite", 1, int(nn[i]), float(ff[i]),
            ) for i in range(j.size)]
            psycopg2.extras.execute_values(cur, self._INSERT_SQL, batch, page_size=10000)
            self.conn.commit()
            total += len(batch)
            n_strong += int((tiers == "Strong").sum())
            n_mod += int((tiers == "Moderate").sum())
            logger.info(f"  {total:,}/{idx.size:,} co-citation pairs stored")
        print(f"Wrote {total:,} co-citation pairs (config_id={self.config_id}, "
              f"{n_strong:,} Strong / {n_mod:,} Moderate).")
        return {"pairs": total, "strong": n_strong, "moderate": n_mod}

    def run(self):
        self.connect()
        self.resolve()
        self.load()
        self.compute_and_write()
        self.conn.close()
        return True


def main():
    ap = argparse.ArgumentParser(description="D7 co-citation (Channel 3) — CPU, warehouse-native")
    ap.add_argument("--version", type=int, required=True)
    ap.add_argument("--config-id", type=int, default=None)
    ap.add_argument("--label", default=None)
    ap.add_argument("--min-copub", type=int, default=None, help="min shared publications (default: config min_copub_count)")
    ap.add_argument("--fdr-alpha", type=float, default=None)
    ap.add_argument("--max-store", type=int, default=5_000_000,
                    help="cap on stored pairs; if more are significant, keep the top by PMI")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO),
                        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    ok = CoCitationCompute(args.version, config_id=args.config_id, label=args.label,
                           min_copub=args.min_copub, fdr_alpha=args.fdr_alpha,
                           max_store=args.max_store, dry_run=args.dry_run).run()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

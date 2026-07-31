#!/usr/bin/env python3
"""
compute_coessentiality.py — D5 driver: co-essentiality (Channel 1), warehouse-native, GPU.

Reads an ACCEPTED relatedness_config, builds the selective-gene × FULL-screen
harmonized-percentile matrix (organism-partitioned; never cross-organism), and
computes tail-restricted Spearman ρ via masked GEMMs (cupy on GPU, numpy
fallback). Two modes:

  --histogram            compute the REAL |ρ| distribution + the true tested-pair
                         count (answers "how many pairs survive |ρ| ≥ x"); writes
                         nothing. Use this to pick --rho-min and to recalibrate
                         tier_cuts (the profiler could only estimate this).

  --build --rho-min X --top-k K
                         store pairs clearing BOTH gates (|ρ| ≥ X AND within each
                         gene's top-K partners) into fact_gene_pair.coess_* with
                         BH-FDR across the tested space. --with-evidence also
                         writes per-screen rows to dim_gene_pair_screen.

Tail-restricted Spearman (§6.1): Spearman = Pearson on per-gene ranks; a pair
uses only screens where BOTH genes are in their own tail (extremes carry the
signal; mid-distribution is noise). Implemented as 6 masked GEMMs over the
rank matrix R and tail mask T (see relatedness_core.prepare_rank_tail):
  N=T·Tᵀ  SxA=P·Tᵀ  SxB=T·Pᵀ  SxxA=Q·Tᵀ  SxxB=T·Qᵀ  Sxy=P·Pᵀ
  with P=R∘T, Q=R²∘T; then Pearson moments over the co-tail set per pair.

Usage (via slurm/reticle-coessentiality.sh):
  python3 compute_coessentiality.py --version 7 --histogram
  python3 compute_coessentiality.py --version 7 --build --rho-min 0.20 --top-k 200
"""

import argparse
import logging
import math
import os
import sys
import time

import numpy as np
import psycopg2
import psycopg2.extras

from config import Config
import relatedness_core as rc

logger = logging.getLogger("compute_coessentiality")

COMPUTE_VERSION = "d5-coess-1.0"
DEFAULT_HIST_CUTS = [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80]


class CoessentialityCompute:
    def __init__(self, version_id, mode, config_id=None, label=None, rho_min=None,
                 top_k=None, min_support=None, fdr_alpha=None, with_evidence=False,
                 block=2048, prefer_gpu=True, dry_run=False):
        self.version_id = version_id
        self.mode = mode
        self.config_id = config_id
        self.label = label
        self.rho_min = rho_min
        self.top_k = top_k
        self.min_support = min_support
        self.fdr_alpha = fdr_alpha
        self.with_evidence = with_evidence
        self.block = block
        self.dry_run = dry_run
        self.conn = None
        self.xp, self.is_gpu = rc.get_backend(prefer_gpu)

    # ---- setup -------------------------------------------------------------

    def connect(self):
        self.conn = rc.pg_connect()
        logger.info(f"Connected to database (backend={'GPU/cupy' if self.is_gpu else 'CPU/numpy'})")

    def resolve(self):
        cur = self.conn.cursor()
        cur.execute("SELECT organism FROM data_load_version WHERE version_id=%s", (self.version_id,))
        row = cur.fetchone()
        if not row:
            raise SystemExit(f"version_id {self.version_id} not found")
        self.organism = row[0]

        # accepted config for this version (or a specific one)
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
                             f"(need an accepted config — run configure_relatedness.py, or pass --config-id/--label)")
        if len(cfgs) > 1:
            raise SystemExit(f"{len(cfgs)} accepted configs for version {self.version_id}; "
                             f"disambiguate with --config-id or --label")
        cfg = cfgs[0]
        self.config = cfg
        self.config_id = cfg["config_id"]
        th = cfg["thresholds"] or {}
        self.thresholds = th
        # config-driven defaults; CLI args (if set) win
        self.tail_percentile = th.get("tail_percentile", 0.10)
        self.rho_min = self.rho_min if self.rho_min is not None else th.get("abs_rho_min", 0.20) or 0.20
        self.top_k = self.top_k if self.top_k is not None else (th.get("ann_topk") or 200)
        self.min_support = self.min_support if self.min_support is not None else th.get("min_coess_support", 5)
        self.fdr_alpha = self.fdr_alpha if self.fdr_alpha is not None else th.get("fdr_alpha", 0.01)
        self.tier_cuts = (th.get("tier_cuts") or {}).get("co_essentiality", {"strong": 0.50, "moderate": 0.30})
        self.sel_filter = th.get("selective_gene_filter", {})

        cur.execute("SELECT run_id FROM etl_pipeline_run WHERE data_load_version_id=%s "
                    "ORDER BY run_id DESC LIMIT 1", (self.version_id,))
        r = cur.fetchone()
        self.run_id = r[0] if r else None
        if self.run_id is None:
            raise SystemExit(f"No etl_pipeline_run for version {self.version_id}")
        logger.info(f"version={self.version_id} organism={self.organism} config_id={self.config_id} "
                    f"run_id={self.run_id} tail={self.tail_percentile} rho_min={self.rho_min} "
                    f"top_k={self.top_k} min_support={self.min_support} fdr_alpha={self.fdr_alpha}")

    # ---- data --------------------------------------------------------------

    def load_matrix(self):
        cur = self.conn.cursor()
        cur.execute("SELECT screen_id FROM screen_harmonization "
                    "WHERE version_id=%s AND coverage_type='FULL'", (self.version_id,))
        full_screens = sorted(int(r[0]) for r in cur.fetchall())
        if not full_screens:
            raise SystemExit("No FULL-coverage screens — co-essentiality needs continuous FULL screens")

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
        logger.info(f"Selective genes: {self.n_sel:,}  ({cls['summary']['pan_essential_dropped']:,} "
                    f"pan-essential, {cls['summary']['pan_inert_dropped']:,} pan-inert dropped)")
        if self.n_sel < 2:
            raise SystemExit("Fewer than 2 selective genes — nothing to correlate")

        # gene symbols (denormalized onto fact_gene_pair)
        cur.execute("SELECT gene_id, gene_symbol FROM gene WHERE version_id=%s", (self.version_id,))
        sym = {int(g): s for g, s in cur.fetchall()}
        self.symbols = np.array([sym.get(int(g), "") for g in self.gene_ids], dtype=object)

        gidx = {int(g): i for i, g in enumerate(self.gene_ids)}
        sidx = {s: j for j, s in enumerate(full_screens)}
        self.n_full = len(full_screens)

        # dense percentile matrix (selective genes × FULL screens), NaN = unmeasured
        mat = np.full((self.n_sel, self.n_full), np.nan, dtype=np.float32)
        cur2 = self.conn.cursor(name="coess_pct")
        cur2.itersize = 500_000
        cur2.execute("SELECT gene_id, screen_id, percentile_score FROM fact_screen_gene "
                     "WHERE version_id=%s AND percentile_score IS NOT NULL AND screen_id = ANY(%s)",
                     (self.version_id, full_screens))
        filled = 0
        while True:
            rows = cur2.fetchmany(500_000)
            if not rows:
                break
            for g, s, p in rows:
                gi = gidx.get(int(g))
                if gi is not None:
                    mat[gi, sidx[int(s)]] = p
                    filled += 1
        cur2.close()
        logger.info(f"Percentile matrix {self.n_sel:,} genes × {self.n_full:,} FULL screens "
                    f"({filled:,} measured cells, {100*filled/mat.size:.1f}% dense)")

        t0 = time.time()
        self.R, self.T = rc.prepare_rank_tail(mat, self.tail_percentile)
        logger.info(f"Rank+tail transform in {time.time()-t0:.0f}s "
                    f"(tail_percentile={self.tail_percentile})")

    # ---- correlation (tiled masked GEMM) -----------------------------------

    def _iter_blocks(self):
        xp = self.xp
        Rf = xp.asarray(self.R)
        Tf = xp.asarray(self.T)
        P = Rf * Tf
        Q = (Rf * Rf) * Tf
        Tt, Pt, Qt = Tf.T, P.T, Q.T
        for start in range(0, self.n_sel, self.block):
            end = min(start + self.block, self.n_sel)
            Tb, Pb, Qb = Tf[start:end], P[start:end], Q[start:end]
            N = Tb @ Tt
            Nsafe = xp.where(N > 0, N, 1.0)
            SxA = Pb @ Tt
            SxB = Tb @ Pt
            SxxA = Qb @ Tt
            SxxB = Tb @ Qt
            Sxy = Pb @ Pt
            mA = SxA / Nsafe
            mB = SxB / Nsafe
            cov = Sxy / Nsafe - mA * mB
            vA = SxxA / Nsafe - mA * mA
            vB = SxxB / Nsafe - mB * mB
            denom = xp.sqrt(xp.clip(vA * vB, 1e-12, None))
            rho = cov / denom
            valid = (N >= self.min_support) & (vA > 1e-9) & (vB > 1e-9)
            rho = xp.where(valid, rho, xp.nan)
            yield start, end, rho, N

    # ---- mode: histogram ---------------------------------------------------

    def run_histogram(self, cuts):
        xp = self.xp
        counts = {c: 0 for c in cuts}
        m_tests = 0
        t0 = time.time()
        for start, end, rho, N in self._iter_blocks():
            absr = xp.abs(rho)
            rows = xp.arange(start, end)[:, None]
            cols = xp.arange(self.n_sel)[None, :]
            upper = cols > rows                      # each unordered pair once
            v = xp.where(upper, absr, xp.nan)
            m_tests += int((~xp.isnan(v)).sum())
            for c in cuts:
                counts[c] += int((v >= c).sum())     # NaN >= c is False
        logger.info(f"Histogram over {self.n_sel:,} genes in {time.time()-t0:.0f}s")
        print(f"\nCo-essentiality |ρ| distribution (version {self.version_id}, config {self.config_id}, "
              f"tail={self.tail_percentile}, min_support={self.min_support}):")
        print(f"  tested pairs (support ≥ {self.min_support}): {m_tests:,}")
        for c in cuts:
            frac = 100 * counts[c] / m_tests if m_tests else 0
            print(f"  |ρ| ≥ {c:.2f}  ->  {counts[c]:>14,}  ({frac:5.2f}%)")
        print(f"\nPick --rho-min from this table, then: --build --rho-min <x> --top-k <k>")
        return {"tested_pairs": m_tests, "counts": counts}

    # ---- mode: build -------------------------------------------------------

    def run_build(self):
        xp = self.xp
        edges = []              # (a_local, b_local, rho, support)
        m_tests = 0
        t0 = time.time()
        for start, end, rho, N in self._iter_blocks():
            absr = xp.abs(rho)
            # true tested count (upper triangle) for BH denominator
            rows = xp.arange(start, end)[:, None]
            cols = xp.arange(self.n_sel)[None, :]
            m_tests += int((~xp.isnan(xp.where(cols > rows, absr, xp.nan))).sum())
            # gate 1: |ρ| floor (+ drop self on the diagonal)
            absr = xp.where(absr >= self.rho_min, absr, xp.nan)
            absr_c = rc.to_cpu(absr)
            rho_c = rc.to_cpu(rho)
            N_c = rc.to_cpu(N)
            for i in range(absr_c.shape[0]):
                a = start + i
                r = absr_c[i]
                r[a] = np.nan                        # no self-pair
                cand = np.where(~np.isnan(r))[0]
                if cand.size == 0:
                    continue
                if cand.size > self.top_k:           # gate 2: top-K partners of this gene
                    cand = cand[np.argpartition(-r[cand], self.top_k)[:self.top_k]]
                for b in cand:
                    edges.append((a, int(b), float(rho_c[i, b]), int(N_c[i, b])))
        logger.info(f"Correlation + gating in {time.time()-t0:.0f}s: {len(edges):,} directed edges, "
                    f"{m_tests:,} tested pairs")

        # dedup to canonical undirected pairs (union of each endpoint's top-K)
        best = {}
        for a, b, r, n in edges:
            gi, gj = int(self.gene_ids[a]), int(self.gene_ids[b])
            if gi == gj:
                continue
            key = (gi, gj, a, b) if gi < gj else (gj, gi, b, a)
            ga, gb, la, lb = key
            k = (ga, gb)
            if k not in best or abs(r) > abs(best[k][0]):
                best[k] = (r, n, la, lb)
        logger.info(f"Deduped to {len(best):,} undirected pairs")
        if not best:
            print("No pairs cleared both gates — lower --rho-min or raise --top-k.")
            return {"pairs": 0}

        # p-values (t-approx) + BH-FDR across the tested space
        try:
            from scipy.stats import t as tdist
            def pval(r, n):
                if n <= 2 or abs(r) >= 1.0:
                    return 0.0 if abs(r) >= 1.0 else 1.0
                tstat = abs(r) * math.sqrt((n - 2) / max(1e-12, 1 - r * r))
                return float(2 * tdist.sf(tstat, n - 2))
        except ImportError:
            def pval(r, n):                          # normal approx fallback
                if n <= 2:
                    return 1.0
                z = abs(r) * math.sqrt(n - 2)
                return float(math.erfc(z / math.sqrt(2)))

        items = list(best.items())                   # [((ga,gb),(rho,n,la,lb)), ...]
        ps = np.array([pval(v[0], v[1]) for _, v in items])
        # Benjamini-Hochberg q-values with m = total tested pairs (not just stored):
        # sort p ascending, q_(i)=p_(i)*m/i, then enforce monotonic from the top.
        L = len(items)
        m = max(m_tests, L)
        order = np.argsort(ps)                                     # ascending p
        fdr = np.empty(L)
        prev = 1.0
        for rank in range(L, 0, -1):                              # L (largest p) .. 1 (smallest)
            idx = order[rank - 1]
            prev = min(prev, ps[idx] * m / rank)
            fdr[idx] = min(prev, 1.0)

        def tier(ar):
            if ar >= self.tier_cuts.get("strong", 0.50):
                return "Strong"
            if ar >= self.tier_cuts.get("moderate", 0.30):
                return "Moderate"
            return "Weak"

        rows_out = []
        for (i, ((ga, gb), (r, n, la, lb))) in enumerate(items):
            ar = abs(r)
            tr = tier(ar)
            rows_out.append((
                self.version_id, self.run_id, self.config_id, self.organism, ga, gb,
                str(self.symbols[la]), str(self.symbols[lb]),
                ar, r, int(n), float(ps[i]), float(fdr[i]), tr,
                tr, ar, "coess", 1, int(n), float(fdr[i]),
            ))

        n_strong = sum(1 for x in rows_out if x[13] == "Strong")
        n_mod = sum(1 for x in rows_out if x[13] == "Moderate")
        logger.info(f"Tiers: {n_strong:,} Strong, {n_mod:,} Moderate, "
                    f"{len(rows_out)-n_strong-n_mod:,} Weak")

        if self.dry_run:
            print(f"[dry-run] would upsert {len(rows_out):,} pairs into fact_gene_pair "
                  f"(config_id={self.config_id})")
            return {"pairs": len(rows_out)}

        cur = self.conn.cursor()
        psycopg2.extras.execute_values(cur, """
            INSERT INTO fact_gene_pair
                (version_id, run_id, config_id, organism, gene_a_id, gene_b_id,
                 gene_a_symbol, gene_b_symbol,
                 coess_effect, coess_rho, coess_support, coess_p_value, coess_fdr, coess_tier,
                 relatedness_tier, relatedness_score, evidence_channels, evidence_channel_count,
                 total_support, min_fdr)
            VALUES %s
            ON CONFLICT (version_id, config_id, gene_a_id, gene_b_id) DO UPDATE SET
                coess_effect=EXCLUDED.coess_effect, coess_rho=EXCLUDED.coess_rho,
                coess_support=EXCLUDED.coess_support, coess_p_value=EXCLUDED.coess_p_value,
                coess_fdr=EXCLUDED.coess_fdr, coess_tier=EXCLUDED.coess_tier,
                is_current=TRUE
        """, rows_out, page_size=10000)
        self.conn.commit()
        logger.info(f"Upserted {len(rows_out):,} pairs into fact_gene_pair")
        print(f"Wrote {len(rows_out):,} co-essentiality pairs (config_id={self.config_id}, "
              f"{n_strong:,} Strong / {n_mod:,} Moderate).")
        if self.with_evidence:
            logger.info("--with-evidence set: per-screen dim_gene_pair_screen population "
                        "is deferred (heavy) — TODO D5 evidence pass.")
        return {"pairs": len(rows_out), "strong": n_strong, "moderate": n_mod}

    # ---- orchestration -----------------------------------------------------

    def run(self, hist_cuts):
        self.connect()
        self.resolve()
        self.load_matrix()
        if self.mode == "histogram":
            self.run_histogram(hist_cuts)
        else:
            self.run_build()
        self.conn.close()
        return True


def main():
    ap = argparse.ArgumentParser(description="D5 co-essentiality (Channel 1) — GPU, warehouse-native")
    ap.add_argument("--version", type=int, required=True)
    ap.add_argument("--config-id", type=int, default=None, help="specific relatedness_config (default: the accepted one)")
    ap.add_argument("--label", default=None, help="pick config by label instead of config-id")
    ap.add_argument("--histogram", action="store_true", help="report |ρ| distribution; write nothing")
    ap.add_argument("--build", action="store_true", help="store pairs to fact_gene_pair")
    ap.add_argument("--rho-min", type=float, default=None, help="|ρ| floor (default: config abs_rho_min)")
    ap.add_argument("--top-k", type=int, default=None, help="max partners per gene (default: config ann_topk)")
    ap.add_argument("--min-support", type=int, default=None, help="min co-tail screens per pair (default 5)")
    ap.add_argument("--fdr-alpha", type=float, default=None)
    ap.add_argument("--with-evidence", action="store_true", help="also populate dim_gene_pair_screen (heavy)")
    ap.add_argument("--block", type=int, default=2048, help="gene row-block size for the tiled GEMM")
    ap.add_argument("--cpu", action="store_true", help="force CPU/numpy (skip GPU)")
    ap.add_argument("--hist-cuts", default=None, help="comma-separated |ρ| cuts for --histogram")
    ap.add_argument("--dry-run", action="store_true", help="build: compute + log, write nothing")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO),
                        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    if not (args.histogram or args.build):
        ap.error("pass --histogram or --build")
    if args.histogram and args.build:
        ap.error("pick one of --histogram / --build")
    mode = "histogram" if args.histogram else "build"
    cuts = [float(x) for x in args.hist_cuts.split(",")] if args.hist_cuts else DEFAULT_HIST_CUTS

    ok = CoessentialityCompute(
        args.version, mode, config_id=args.config_id, label=args.label,
        rho_min=args.rho_min, top_k=args.top_k, min_support=args.min_support,
        fdr_alpha=args.fdr_alpha, with_evidence=args.with_evidence, block=args.block,
        prefer_gpu=not args.cpu, dry_run=args.dry_run).run(cuts)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

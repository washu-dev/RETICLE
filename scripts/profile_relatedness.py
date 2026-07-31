#!/usr/bin/env python3
"""
profile_relatedness.py — D2 driver: the gene-relatedness PROFILER.

The cheap, exact-where-it-can-be first stage of the what-if loop. It reads the
harmonized warehouse (P1) for one data load version and writes ONE
`relatedness_profile` snapshot capturing:

  * data shape       — screen counts (total / FULL / HIT_ONLY), coverage
                       distribution, selective-gene count, pan-essential /
                       pan-inert drops.
  * projection curves — threshold -> (projected candidate pairs, cost) per channel:
       - co-hit       : EXACT   (sparse Hᵀ·H over selective-gene hit sets)
       - co-citation  : EXACT   (sparse over gene×publication sets; needs P2)
       - co-essentiality : SAMPLED with a 95% CI (random selective-gene sample,
                       degree-in-the-co-measurement-graph estimator — NEVER the
                       n×n cartesian product).

The snapshot (+ its sample size and seed) makes the projection reproducible
(NFR-1). It NEVER materializes the n×n grid — that is the whole point of the
profiler: let a human pick thresholds/budget (-> relatedness_config, D3) before
D4/D5 pay for the real compute.

Prerequisite: P1 harmonization must have run for the version (screen_harmonization
populated + fact_screen_gene.percentile_score set). Errors clearly otherwise.

Usage (from scripts/, or via slurm/reticle-profile.sh):
  python3 profile_relatedness.py --version 7
  python3 profile_relatedness.py --version 7 --dry-run
  python3 profile_relatedness.py --version 7 --sample-size 600 --seed 1337
"""

import argparse
import logging
import os
import sys
import time

import numpy as np
import psycopg2
import psycopg2.extras

try:
    from scipy import sparse
except ImportError:  # pragma: no cover - environment guard
    sys.stderr.write(
        "ERROR: scipy is required by the profiler (sparse Hᵀ·H). "
        "Install it (see scripts/requirements.txt / slurm/env-setup.sh).\n")
    raise

from config import Config
import relatedness_core as rc

logger = logging.getLogger("profile_relatedness")

PROFILER_VERSION = "d2-profiler-1.0"

# Candidate threshold grids the projection curves are evaluated over. These are
# the x-axis of the what-if curves, NOT accepted thresholds — the human picks a
# point (D3). Kept here (not in config) because they only shape the profile.
DEFAULT_COHIT_GRID = [2, 3, 5, 8, 12, 20]           # min # screens both are hits
DEFAULT_COESS_GRID = [3, 5, 8, 12, 20, 30]          # min # shared FULL screens
DEFAULT_COCITE_GRID = [2, 3, 5, 8]                  # min # shared publications


class RelatednessProfiler:
    def __init__(self, version_id, sample_size=400, seed=1337,
                 pan_essential_rate=0.90, min_measured_screens=2,
                 cohit_grid=None, coess_grid=None, cocite_grid=None,
                 tail_percentile=0.10, created_by=None, dry_run=False):
        self.version_id = version_id
        self.sample_size = sample_size
        self.seed = seed
        self.pan_essential_rate = pan_essential_rate
        self.min_measured_screens = min_measured_screens
        self.cohit_grid = cohit_grid or DEFAULT_COHIT_GRID
        self.coess_grid = coess_grid or DEFAULT_COESS_GRID
        self.cocite_grid = cocite_grid or DEFAULT_COCITE_GRID
        self.tail_percentile = tail_percentile
        self.created_by = created_by or os.getenv("USER") or "profiler"
        self.dry_run = dry_run
        self.conn = None
        self.organism = None

    # ---- connection / prerequisites ---------------------------------------

    def connect(self):
        self.conn = rc.pg_connect()
        logger.info("Connected to database")

    def resolve_organism(self):
        cur = self.conn.cursor()
        cur.execute("SELECT organism FROM data_load_version WHERE version_id=%s", (self.version_id,))
        row = cur.fetchone()
        if not row:
            raise SystemExit(f"version_id {self.version_id} not found")
        self.organism = row[0]
        logger.info(f"version_id={self.version_id} organism={self.organism}")

    def check_prerequisites(self):
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM screen_harmonization WHERE version_id=%s", (self.version_id,))
        n_harm = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM fact_screen_gene "
                    "WHERE version_id=%s AND percentile_score IS NOT NULL", (self.version_id,))
        n_pct = cur.fetchone()[0]
        if n_harm == 0 or n_pct == 0:
            raise SystemExit(
                f"P1 harmonization has not run for version {self.version_id} "
                f"(screen_harmonization rows={n_harm}, harmonized fact rows={n_pct}). "
                f"Run slurm/reticle-harmonize.sh {self.version_id} first.")
        logger.info(f"Prereq OK: {n_harm} harmonized screens, {n_pct:,} harmonized fact rows")

    # ---- data loading ------------------------------------------------------

    def _fetch_pairs(self, sql, params):
        """Stream a (gene_id, screen_id) result into two int32 numpy arrays
        without holding the whole Python-object result set at once."""
        cur = self.conn.cursor(name=f"prof_{abs(hash(sql)) % 10_000}")
        cur.itersize = 200_000
        cur.execute(sql, params)
        gs, ss = [], []
        while True:
            rows = cur.fetchmany(200_000)
            if not rows:
                break
            gs.extend(r[0] for r in rows)
            ss.extend(r[1] for r in rows)
        cur.close()
        return np.asarray(gs, dtype=np.int64), np.asarray(ss, dtype=np.int64)

    def load(self):
        cur = self.conn.cursor()

        # per-screen coverage
        cur.execute("SELECT screen_id, coverage_type, genes_measured "
                    "FROM screen_harmonization WHERE version_id=%s", (self.version_id,))
        cov = cur.fetchall()
        self.full_screens = {int(s) for s, c, _ in cov if c == "FULL"}
        self.hit_only_screens = {int(s) for s, c, _ in cov if c == "HIT_ONLY"}
        self.screen_counts = {
            "total": len(cov),
            "full_coverage": len(self.full_screens),
            "hit_only": len(self.hit_only_screens),
        }
        gm = [int(g) for _, _, g in cov if g is not None]
        self.coverage_distribution = self._describe(np.asarray(gm, dtype=np.int64)) if gm else {}
        logger.info(f"Screens: {self.screen_counts}")

        # per-gene measured / hit counts -> selective classification
        cur.execute(rc.GENE_STATS_SQL, (self.version_id,))
        stats = cur.fetchall()
        self.gene_ids = np.asarray([int(g) for g, _, _ in stats], dtype=np.int64)
        n_measured = np.asarray([int(m) for _, m, _ in stats], dtype=np.int64)
        n_hits = np.asarray([int(h or 0) for _, _, h in stats], dtype=np.int64)

        # shared selective-gene rule (relatedness_core) so the profiler's
        # projections match what D5 actually builds from the same config.
        cls = rc.classify_selective(n_measured, n_hits,
                                    pan_essential_rate=self.pan_essential_rate,
                                    min_measured_screens=self.min_measured_screens)
        selective_mask = cls["selective"]
        self.selective_gene_ids = self.gene_ids[selective_mask]
        self.selective_stats = cls["summary"]
        logger.info(f"Selective genes: {self.selective_stats['selective_gene_count']:,} "
                    f"(pan-essential dropped {self.selective_stats['pan_essential_dropped']:,}, "
                    f"pan-inert dropped {self.selective_stats['pan_inert_dropped']:,})")

        # compact gene index over the selective set (shared by both matrices).
        # Sorted view lets _selective_matrix map millions of (gene,screen) rows to
        # compact row indices with vectorized searchsorted (no Python loop).
        self.n_sel = len(self.selective_gene_ids)
        self._sel_order = np.argsort(self.selective_gene_ids)
        self._sel_sorted = self.selective_gene_ids[self._sel_order]

    @staticmethod
    def _describe(arr):
        if arr.size == 0:
            return {}
        return {
            "n": int(arr.size),
            "min": int(arr.min()), "max": int(arr.max()),
            "mean": float(arr.mean()), "median": float(np.median(arr)),
            "p10": float(np.percentile(arr, 10)), "p90": float(np.percentile(arr, 90)),
        }

    def _selective_matrix(self, gene_arr, screen_arr):
        """Build a CSR (selective_gene x screen) binary matrix from (gene, screen)
        pairs, keeping only selective genes. Returns (csr, n_screens)."""
        if self.n_sel == 0 or gene_arr.size == 0:
            return sparse.csr_matrix((self.n_sel, 0), dtype=np.int32), 0
        # vectorized membership + map gene_id -> compact selective row index
        pos = np.clip(np.searchsorted(self._sel_sorted, gene_arr), 0, self.n_sel - 1)
        keep = self._sel_sorted[pos] == gene_arr
        if not keep.any():
            return sparse.csr_matrix((self.n_sel, 0), dtype=np.int32), 0
        rows = self._sel_order[pos[keep]]
        _, cols = np.unique(screen_arr[keep], return_inverse=True)
        n_cols = int(cols.max()) + 1 if cols.size else 0
        data = np.ones(rows.size, dtype=np.int32)
        M = sparse.csr_matrix((data, (rows, cols)), shape=(self.n_sel, n_cols))
        M.data[:] = 1          # collapse any accidental dupes to binary
        return M, n_cols

    # ---- projections -------------------------------------------------------

    def project_cohit(self):
        """EXACT: sparse Hᵀ·H over selective-gene hit sets -> co-hit count per
        pair -> pair volume per min_cohit_screens threshold."""
        hg, hs = self._fetch_pairs(
            "SELECT gene_id, screen_id FROM screen_gene_raw "
            "WHERE version_id=%s AND hit_flag=TRUE", (self.version_id,))
        H, n_scr = self._selective_matrix(hg, hs)
        if H.shape[1] == 0:
            return {"status": "unavailable", "reason": "no hit records"}
        C = (H @ H.T).tocoo()
        upper = C.row < C.col
        counts = C.data[upper]
        logger.info(f"Co-hit: {counts.size:,} co-occurring selective-gene pairs (nnz)")
        curve = [{
            "threshold": {"min_cohit_screens": int(t)},
            "projected_pairs": int((counts >= t).sum()),
            "projected_cost_units": int((counts >= t).sum()),   # cheap/exact channel
            "estimation_method": "EXACT",
        } for t in self.cohit_grid]
        return {"n_hit_screens": int(n_scr), "curve": curve}

    def project_cocitation(self):
        """EXACT over gene×publication sets — requires P2 (fact_screen_gene_publication
        populated). Degrades gracefully to 'unavailable' while P2 is pending."""
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM fact_screen_gene_publication WHERE version_id=%s",
                    (self.version_id,))
        if cur.fetchone()[0] == 0:
            return {"status": "unavailable", "reason": "fact_screen_gene_publication empty (P2 pending)"}
        pg, pp = self._fetch_pairs(
            "SELECT gene_id, publication_id FROM fact_screen_gene_publication "
            "WHERE version_id=%s", (self.version_id,))
        P, n_pub = self._selective_matrix(pg, pp)
        if P.shape[1] == 0:
            return {"status": "unavailable", "reason": "no selective-gene publications"}
        C = (P @ P.T).tocoo()
        upper = C.row < C.col
        counts = C.data[upper]
        curve = [{
            "threshold": {"min_copub_count": int(t)},
            "projected_pairs": int((counts >= t).sum()),
            "projected_cost_units": int((counts >= t).sum()),
            "estimation_method": "EXACT",
        } for t in self.cocite_grid]
        return {"n_publications": int(n_pub), "curve": curve}

    def project_coessentiality(self):
        """SAMPLED with a 95% CI. Builds the selective-gene × FULL-screen
        co-MEASUREMENT matrix M, samples s selective genes, and estimates, per
        min_shared_full_screens threshold, the number of qualifying pairs from the
        sampled genes' degrees in the co-measurement graph:
            projected_pairs ≈ N_sel * mean_degree / 2
        with a normal CI from the sample SE. Never forms M·Mᵀ over all N genes."""
        if not self.full_screens:
            return {"status": "unavailable", "reason": "no FULL-coverage screens"}
        mg, ms = self._fetch_pairs(
            "SELECT gene_id, screen_id FROM fact_screen_gene "
            "WHERE version_id=%s AND percentile_score IS NOT NULL "
            "AND screen_id = ANY(%s)", (self.version_id, list(self.full_screens)))
        M, n_full = self._selective_matrix(mg, ms)
        if M.shape[1] == 0 or self.n_sel < 2:
            return {"status": "unavailable", "reason": "no FULL co-measurement among selective genes"}

        rng = np.random.default_rng(self.seed)
        s = min(self.sample_size, self.n_sel)
        sample_rows = rng.choice(self.n_sel, size=s, replace=False)
        # (s x N_sel) integer co-measurement counts for the sampled genes only
        D = np.asarray((M[sample_rows] @ M.T).todense())
        D[np.arange(s), sample_rows] = 0            # exclude self-pairs

        curve = []
        for t in self.coess_grid:
            degrees = (D >= t).sum(axis=1).astype(np.float64)
            mean_deg = float(degrees.mean())
            se = float(degrees.std(ddof=1) / np.sqrt(s)) if s > 1 else 0.0
            proj = self.n_sel * mean_deg / 2.0
            half = self.n_sel * 1.96 * se / 2.0
            curve.append({
                "threshold": {"min_shared_full_screens": int(t),
                              "tail_percentile": self.tail_percentile},
                "projected_pairs": int(round(proj)),
                "projected_cost_units": int(round(proj)),   # ~1 tail-Spearman per pair (GPU-dominant)
                "estimation_method": "SAMPLED",
                "ci_low": int(round(max(0.0, proj - half))),
                "ci_high": int(round(proj + half)),
            })
        return {"n_full_screens": int(n_full), "sample": {"n_genes": int(s), "seed": int(self.seed)},
                "curve": curve}

    # ---- orchestration -----------------------------------------------------

    def run(self):
        self.connect()
        self.resolve_organism()
        self.check_prerequisites()
        t0 = time.time()
        self.load()

        logger.info("Projecting co-hit (exact)...")
        cohit = self.project_cohit()
        logger.info("Projecting co-citation (exact, if P2 available)...")
        cocite = self.project_cocitation()
        logger.info("Projecting co-essentiality (sampled + CI)...")
        coess = self.project_coessentiality()

        snapshot = {
            "screens": self.screen_counts,
            "coverage_distribution": self.coverage_distribution,
            **self.selective_stats,
            "projection_curves": {
                "co_essentiality": coess,
                "co_hit": cohit,
                "co_citation": cocite,
            },
            "cost_model": {
                "unit": "candidate pair-correlations",
                "note": "co-essentiality is the GPU-dominant cost; co-hit/co-citation are exact & cheap. "
                        "projected_cost_units == projected_pairs per channel (calibrate to wall-clock in D3).",
            },
            "profiler_version": PROFILER_VERSION,
            "elapsed_seconds": round(time.time() - t0, 1),
        }

        self._log_summary(snapshot)

        if self.dry_run:
            logger.info("[dry-run] snapshot computed, nothing written")
            self.conn.close()
            return True

        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO relatedness_profile "
            "(data_load_version_id, organism, snapshot, profiler_version, created_by) "
            "VALUES (%s,%s,%s,%s,%s) RETURNING profile_id",
            (self.version_id, self.organism, psycopg2.extras.Json(snapshot),
             PROFILER_VERSION, self.created_by))
        profile_id = cur.fetchone()[0]
        self.conn.commit()
        logger.info(f"Wrote relatedness_profile profile_id={profile_id} "
                    f"(version {self.version_id}, {self.organism})")
        self.conn.close()
        return True

    def _log_summary(self, snap):
        logger.info("=== Profile summary ===")
        logger.info(f"  screens: {snap['screens']}")
        logger.info(f"  selective genes: {snap['selective_gene_count']:,} / {snap['total_genes']:,}")
        for ch, key in (("co_essentiality", "SAMPLED"), ("co_hit", "EXACT"), ("co_citation", "EXACT")):
            block = snap["projection_curves"][ch]
            if block.get("status") == "unavailable":
                logger.info(f"  {ch}: unavailable ({block['reason']})")
                continue
            logger.info(f"  {ch} projected pairs by threshold:")
            for pt in block["curve"]:
                thr = ",".join(f"{k}={v}" for k, v in pt["threshold"].items())
                ci = (f"  [{pt['ci_low']:,}..{pt['ci_high']:,}]"
                      if "ci_low" in pt else "")
                logger.info(f"      {thr:42s} -> {pt['projected_pairs']:>12,}{ci}")


def _int_list(s):
    return [int(x) for x in s.split(",") if x.strip()]


def main():
    ap = argparse.ArgumentParser(description="D2 gene-relatedness profiler")
    ap.add_argument("--version", type=int, required=True, help="Data load version ID")
    ap.add_argument("--sample-size", type=int, default=400,
                    help="# selective genes sampled for the co-essentiality estimate")
    ap.add_argument("--seed", type=int, default=1337, help="RNG seed (recorded for reproducibility)")
    ap.add_argument("--pan-essential-rate", type=float, default=0.90,
                    help="hit-rate at/above which a gene is dropped as pan-essential")
    ap.add_argument("--min-measured-screens", type=int, default=2,
                    help="min screens a gene must be measured in to be a candidate")
    ap.add_argument("--cohit-grid", type=_int_list, default=None,
                    help="comma-separated min_cohit_screens thresholds")
    ap.add_argument("--coess-grid", type=_int_list, default=None,
                    help="comma-separated min_shared_full_screens thresholds")
    ap.add_argument("--cocite-grid", type=_int_list, default=None,
                    help="comma-separated min_copub_count thresholds")
    ap.add_argument("--tail-percentile", type=float, default=0.10,
                    help="recorded tail window (informational; does not change pair volume)")
    ap.add_argument("--created-by", default=None)
    ap.add_argument("--dry-run", action="store_true", help="compute + log, write nothing")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO),
                        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    ok = RelatednessProfiler(
        args.version, sample_size=args.sample_size, seed=args.seed,
        pan_essential_rate=args.pan_essential_rate,
        min_measured_screens=args.min_measured_screens,
        cohit_grid=args.cohit_grid, coess_grid=args.coess_grid, cocite_grid=args.cocite_grid,
        tail_percentile=args.tail_percentile, created_by=args.created_by,
        dry_run=args.dry_run).run()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

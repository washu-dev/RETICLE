#!/usr/bin/env python3
"""
compute_novelty.py — D5b driver: novelty / mechanistic-divergence (Channel 5),
warehouse-native, GPU-capable.

"Find genes that break the same rule." Reuses D5's selective-gene x FULL-screen
harmonized-percentile matrix, but instead of correlating the RAW profiles it:

  1. Fits a light additive expectation E[g,i] = mu + gene_baseline[g] +
     screen_baseline[i] + context_mean[context(i)] (context(i) = P3's
     dim_screen_context.context_key for screen i; screens with no context land
     in a shared "__none__" bucket). Single-pass, MEDIAN-centered (not
     iterative median polish, not a Gaussian process — design/gene_relatedness
     _design.md §6.6 is explicit that this is a cheap additive residualization,
     never a GP). Params persisted to dim_gene_expectation_model.
  2. Residualizes: R[g,i] = observed[g,i] - E[g,i].
  3. Re-runs the SAME tail-restricted-Spearman masked-GEMM machinery D5 uses
     (relatedness_core.prepare_rank_tail + a tiled correlation pass — code is
     duplicated from compute_coessentiality.py rather than imported, matching
     how D6/D7/D8 each own their load rather than subclassing D5) over R
     instead of the raw matrix, gated by its own rho-min/top-K/support
     thresholds, BH-FDR'd, and written to fact_gene_pair.resid_*.
  4. novelty_score contrasts resid_effect against the pair's raw coess_effect
     (0 if the pair never cleared D5's own gate) — high residual correlation
     that ISN'T explained by raw co-essentiality is the point.
  5. is_antagonistic: raw or residual rho strongly negative.
  6. is_buffering_candidate: a SEPARATE candidate search (not the residual-
     correlated pairs above — buffering pairs are expected to show LITTLE
     correlation in single-gene KO data, that's the whole point of framing it
     as a redundant-pair hypothesis, not a measured edge). Candidates are
     paralog pairs (dim_gene_paralog) where BOTH genes are individually
     near-inert (criterion a — reusing relatedness_core.classify_selective's
     pan_inert flag: zero hits across every measured screen, the same "rarely
     moves alone" signal, already computed for free) and whose per-context
     median profiles are anti-correlated (criterion c) over >= --min-shared-
     contexts contexts. Both (a) and (b) are true by construction of the
     candidate set, so buffering_basis is always "a,b,c" for a stored row —
     it is never a scored edge, only a testable-by-combinatorial-KO flag
     (see the design doc's explicit "not a measured edge" framing).

dim_gene_pair_screen residual population (design's "residuals on
dim_gene_pair_screen") is DEFERRED, same as D5's own --with-evidence pass —
this writes the header (fact_gene_pair) + model provenance
(dim_gene_expectation_model) only.

Usage (via slurm/reticle-novelty.sh):
  python3 compute_novelty.py --version 7 --config-id 2
  python3 compute_novelty.py --version 7 --config-id 2 --dry-run
"""

import argparse
import logging
import math
import sys
import time

import numpy as np
import psycopg2
import psycopg2.extras

import relatedness_core as rc

logger = logging.getLogger("compute_novelty")

COMPUTE_VERSION = "d5b-novelty-1.0"
CONTEXT_NONE_BUCKET = "__none__"


class NoveltyCompute:
    def __init__(self, version_id, config_id=None, label=None, resid_rho_min=None,
                 top_k=None, min_support=None, fdr_alpha=None, antagonistic_rho=None,
                 min_shared_contexts=None, block=2048, prefer_gpu=True, dry_run=False):
        self.version_id = version_id
        self.config_id = config_id
        self.label = label
        self.resid_rho_min = resid_rho_min
        self.top_k = top_k
        self.min_support = min_support
        self.fdr_alpha = fdr_alpha
        self.antagonistic_rho = antagonistic_rho
        self.min_shared_contexts = min_shared_contexts
        self.block = block
        self.dry_run = dry_run
        self.conn = None
        self.xp, self.is_gpu = rc.get_backend(prefer_gpu)

    def connect(self):
        self.conn = rc.pg_connect()
        logger.info(f"Connected to database (backend={'GPU/cupy' if self.is_gpu else 'CPU/numpy'})")

    @staticmethod
    def _coalesce(*vals):
        """First non-None value. Unlike dict.get(key, default), this treats a
        key present with an explicit JSON null the same as a missing key."""
        for v in vals:
            if v is not None:
                return v
        return None

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
        # _coalesce, not dict.get(key, default) chains: a JSONB threshold can be
        # PRESENT with an explicit null (e.g. this warehouse's config_id=2 has
        # "ann_topk": null, "compute_mode": "ANN_TOPK" — declared but never set).
        # dict.get(key, default) only applies its default when the key is MISSING,
        # not when it maps to null, so a two-level "th.get(a) or th.get(b, default)"
        # chain silently produces None if b is present-null — exactly what crashed
        # here (self.top_k = None, then `cand.size > self.top_k` raised TypeError).
        self.tail_percentile = self._coalesce(th.get("tail_percentile"), 0.10)
        self.resid_rho_min = self._coalesce(self.resid_rho_min, th.get("resid_rho_min"), th.get("abs_rho_min"), 0.20)
        self.top_k = self._coalesce(self.top_k, th.get("resid_top_k"), th.get("ann_topk"), 200)
        self.min_support = self._coalesce(self.min_support, th.get("resid_min_support"), th.get("min_coess_support"), 5)
        self.fdr_alpha = self._coalesce(self.fdr_alpha, th.get("fdr_alpha"), 0.01)
        tier_cuts_all = th.get("tier_cuts") or {}
        self.tier_cuts = tier_cuts_all.get("resid") or tier_cuts_all.get("co_essentiality") \
            or {"strong": 0.50, "moderate": 0.30}
        self.antagonistic_rho = self._coalesce(self.antagonistic_rho, th.get("antagonistic_rho"), 0.30)
        self.min_shared_contexts = self._coalesce(self.min_shared_contexts, th.get("min_shared_contexts"), 3)
        self.sel_filter = th.get("selective_gene_filter") or {}

        cur.execute("SELECT run_id FROM etl_pipeline_run WHERE data_load_version_id=%s "
                    "ORDER BY run_id DESC LIMIT 1", (self.version_id,))
        r = cur.fetchone()
        if not r:
            raise SystemExit(f"No etl_pipeline_run for version {self.version_id}")
        self.run_id = r[0]
        logger.info(f"version={self.version_id} organism={self.organism} config_id={self.config_id} "
                    f"run_id={self.run_id} tail={self.tail_percentile} resid_rho_min={self.resid_rho_min} "
                    f"top_k={self.top_k} min_support={self.min_support}")

    # ---- data ---------------------------------------------------------------

    def load(self):
        cur = self.conn.cursor()
        cur.execute("SELECT screen_id FROM screen_harmonization "
                    "WHERE version_id=%s AND coverage_type='FULL'", (self.version_id,))
        full_screens = sorted(int(r[0]) for r in cur.fetchall())
        if not full_screens:
            raise SystemExit("No FULL-coverage screens — the novelty channel needs continuous FULL screens")
        self.full_screens = full_screens
        n_full = len(full_screens)
        sidx = {s: j for j, s in enumerate(full_screens)}

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
        self.near_inert_gene_ids = gene_ids_all[cls["pan_inert"]]
        logger.info(f"Selective genes: {self.n_sel:,}; near-inert (pan_inert, criterion a): "
                    f"{self.near_inert_gene_ids.size:,}")
        if self.n_sel < 2:
            raise SystemExit("Fewer than 2 selective genes — nothing to correlate")

        cur.execute("SELECT gene_id, gene_symbol FROM gene WHERE version_id=%s", (self.version_id,))
        self.symbol_by_gene = {int(g): s for g, s in cur.fetchall()}
        self.symbols = np.array([self.symbol_by_gene.get(int(g), "") for g in self.gene_ids], dtype=object)

        # screen -> context_key (P3); screens with no row / no key share one bucket
        cur.execute("SELECT screen_id, context_key FROM dim_screen_context WHERE version_id=%s AND is_current=TRUE",
                    (self.version_id,))
        ctx_by_screen = {int(s): (k or CONTEXT_NONE_BUCKET) for s, k in cur.fetchall()}
        self.screen_context = np.array(
            [ctx_by_screen.get(s, CONTEXT_NONE_BUCKET) for s in full_screens], dtype=object)

        # dense percentile matrix, selective genes x FULL screens (same as D5)
        gidx = {int(g): i for i, g in enumerate(self.gene_ids)}
        mat = np.full((self.n_sel, n_full), np.nan, dtype=np.float32)
        cur2 = self.conn.cursor(name="novelty_pct")
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
        self.mat = mat
        logger.info(f"Percentile matrix {self.n_sel:,} genes x {n_full:,} FULL screens ({filled:,} measured cells)")

        # per-gene near-inert profile matrix (context anti-correlation, criterion c) —
        # a separate, usually much smaller, query since near-inert genes are pan-inert
        # (excluded from the selective matrix above).
        self.near_inert_gene_ids = np.array(sorted(set(int(g) for g in self.near_inert_gene_ids)))
        niidx = {int(g): i for i, g in enumerate(self.near_inert_gene_ids)}
        ni_mat = np.full((self.near_inert_gene_ids.size, n_full), np.nan, dtype=np.float32)
        if self.near_inert_gene_ids.size:
            cur3 = self.conn.cursor(name="novelty_ni_pct")
            cur3.itersize = 200_000
            cur3.execute("SELECT gene_id, screen_id, percentile_score FROM fact_screen_gene "
                        "WHERE version_id=%s AND percentile_score IS NOT NULL AND screen_id = ANY(%s) "
                        "AND gene_id = ANY(%s)",
                        (self.version_id, full_screens, [int(g) for g in self.near_inert_gene_ids]))
            while True:
                rows = cur3.fetchmany(200_000)
                if not rows:
                    break
                for g, s, p in rows:
                    ni_mat[niidx[int(g)], sidx[int(s)]] = p
            cur3.close()
        self.near_inert_mat = ni_mat

    # ---- Channel-5 part 1: light additive expectation model ------------------

    def fit_expectation_model(self):
        mat = self.mat
        mu = float(np.nanmedian(mat))
        gene_baseline = np.nanmedian(mat - mu, axis=1)
        gene_baseline = np.nan_to_num(gene_baseline, nan=0.0)
        resid1 = mat - mu - gene_baseline[:, None]
        screen_baseline = np.nanmedian(resid1, axis=0)
        screen_baseline = np.nan_to_num(screen_baseline, nan=0.0)
        resid2 = resid1 - screen_baseline[None, :]

        context_mean = {}
        context_groups = {}
        for key in np.unique(self.screen_context):
            cols = np.where(self.screen_context == key)[0]
            context_groups[key] = cols
            vals = resid2[:, cols]
            m = np.nanmedian(vals) if np.isfinite(vals).any() else 0.0
            context_mean[key] = 0.0 if math.isnan(m) else float(m)

        context_mean_per_screen = np.array([context_mean[k] for k in self.screen_context], dtype=np.float32)
        E = mu + gene_baseline[:, None] + screen_baseline[None, :] + context_mean_per_screen[None, :]
        R = mat - E

        raw_var = float(np.nanvar(mat - mu))
        resid_var = float(np.nanvar(R))
        var_explained = max(0.0, min(1.0, 1.0 - resid_var / raw_var)) if raw_var > 0 else 0.0
        n_obs = int(np.isfinite(mat).sum())
        logger.info(f"Expectation model: mu={mu:.4f}, {len(context_mean)} context buckets, "
                    f"{n_obs:,} observations, {100*var_explained:.1f}% variance explained")

        self.R_resid = R
        self.expectation_params = {
            "mu": mu,
            "gene_baseline": {str(int(g)): float(v) for g, v in zip(self.gene_ids, gene_baseline)},
            "screen_baseline": {str(int(s)): float(v) for s, v in zip(self.full_screens, screen_baseline)},
            "context_mean": context_mean,
            "tail_percentile": self.tail_percentile,
        }
        self.n_observations = n_obs
        self.residual_var_explained = var_explained

        # per-context screen-column groups — reused for buffering criterion (c) on
        # the near-inert gene universe (built once here, applied in run_build()).
        self.context_cols = context_groups

    def write_expectation_model(self, cur):
        cur.execute("""
            INSERT INTO dim_gene_expectation_model
                (version_id, run_id, config_id, organism, method, covariates, params,
                 n_observations, residual_var_explained, is_current)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE)
            ON CONFLICT (version_id, config_id, organism) DO UPDATE SET
                run_id=EXCLUDED.run_id, method=EXCLUDED.method, covariates=EXCLUDED.covariates,
                params=EXCLUDED.params, n_observations=EXCLUDED.n_observations,
                residual_var_explained=EXCLUDED.residual_var_explained, is_current=TRUE
        """, (self.version_id, self.run_id, self.config_id, self.organism, "additive",
              "gene_baseline,screen_baseline,context_key",
              psycopg2.extras.Json(self.expectation_params),
              self.n_observations, self.residual_var_explained))

    # ---- Channel-5 part: residual co-essentiality (tail-restricted Spearman) --

    def _iter_blocks(self, R, T):
        xp = self.xp
        Rf = xp.asarray(R)
        Tf = xp.asarray(T)
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
            mA, mB = SxA / Nsafe, SxB / Nsafe
            cov = Sxy / Nsafe - mA * mB
            vA = SxxA / Nsafe - mA * mA
            vB = SxxB / Nsafe - mB * mB
            denom = xp.sqrt(xp.clip(vA * vB, 1e-12, None))
            rho = cov / denom
            valid = (N >= self.min_support) & (vA > 1e-9) & (vB > 1e-9)
            yield start, end, xp.where(valid, rho, xp.nan), N

    @staticmethod
    def _pval(r, n):
        try:
            from scipy.stats import t as tdist
            if n <= 2 or abs(r) >= 1.0:
                return 0.0 if abs(r) >= 1.0 else 1.0
            tstat = abs(r) * math.sqrt((n - 2) / max(1e-12, 1 - r * r))
            return float(2 * tdist.sf(tstat, n - 2))
        except ImportError:                     # pragma: no cover
            if n <= 2:
                return 1.0
            z = abs(r) * math.sqrt(n - 2)
            return float(math.erfc(z / math.sqrt(2)))

    def compute_residual_edges(self):
        t0 = time.time()
        R_rank, T_tail = rc.prepare_rank_tail(self.R_resid, self.tail_percentile)
        edges, m_tests = [], 0
        for start, end, rho, N in self._iter_blocks(R_rank, T_tail):
            xp = self.xp
            absr = xp.abs(rho)
            rows = xp.arange(start, end)[:, None]
            cols = xp.arange(self.n_sel)[None, :]
            m_tests += int((~xp.isnan(xp.where(cols > rows, absr, xp.nan))).sum())
            gated = xp.where(absr >= self.resid_rho_min, absr, xp.nan)
            gated_c, rho_c, N_c = rc.to_cpu(gated), rc.to_cpu(rho), rc.to_cpu(N)
            for i in range(gated_c.shape[0]):
                a = start + i
                r = gated_c[i]
                r[a] = np.nan
                cand = np.where(~np.isnan(r))[0]
                if cand.size == 0:
                    continue
                if cand.size > self.top_k:
                    cand = cand[np.argpartition(-r[cand], self.top_k)[:self.top_k]]
                for b in cand:
                    edges.append((a, int(b), float(rho_c[i, b]), int(N_c[i, b])))
        logger.info(f"Residual correlation in {time.time()-t0:.0f}s: {len(edges):,} directed edges, "
                    f"{m_tests:,} tested pairs")

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
        logger.info(f"Deduped to {len(best):,} undirected residual-correlated pairs")

        if not best:
            return [], m_tests

        items = list(best.items())
        ps = np.array([self._pval(v[0], v[1]) for _, v in items])
        # BH-FDR over the TRUE tested-pair universe (m_tests), not just the
        # rho-gated subset that was stored — same pattern as D5's run_build().
        fdr = self._bh_with_universe(ps, max(m_tests, len(ps)))
        return list(zip(items, ps, fdr)), m_tests

    @staticmethod
    def _bh_with_universe(ps, m):
        """BH-FDR with an explicit test-universe size m (>= len(ps)); q_(i) =
        p_(i)*m/i, enforced monotonic from the top (same pattern as D5's
        run_build())."""
        L = len(ps)
        order = np.argsort(ps)
        fdr = np.empty(L)
        prev = 1.0
        for rank in range(L, 0, -1):
            idx = order[rank - 1]
            prev = min(prev, ps[idx] * m / rank)
            fdr[idx] = min(prev, 1.0)
        return fdr

    # ---- Channel-5 part: buffering-candidate flag -----------------------------

    def find_buffering_candidates(self, cur):
        cur.execute("SELECT gene_id_a, gene_id_b FROM dim_gene_paralog "
                    "WHERE version_id=%s AND is_current=TRUE", (self.version_id,))
        paralogs = cur.fetchall()
        near_inert = set(int(g) for g in self.near_inert_gene_ids)
        candidates = [(a, b) for a, b in paralogs if int(a) in near_inert and int(b) in near_inert]
        logger.info(f"{len(paralogs):,} paralog pairs, {len(candidates):,} with both genes near-inert "
                    f"(criteria a+b)")
        if not candidates:
            return []

        niidx = {int(g): i for i, g in enumerate(self.near_inert_gene_ids)}
        ni_ctx_profile = {}   # gene_id -> {context_key: median percentile}
        for g in near_inert:
            i = niidx.get(g)
            if i is None:
                continue
            row = self.near_inert_mat[i]
            prof = {}
            for key, cols in self.context_cols.items():
                v = row[cols]
                if np.isfinite(v).any():
                    prof[key] = float(np.nanmedian(v))
            ni_ctx_profile[g] = prof

        winners = []
        for a, b in candidates:
            a, b = int(a), int(b)
            pa, pb = ni_ctx_profile.get(a, {}), ni_ctx_profile.get(b, {})
            shared = set(pa) & set(pb)
            if len(shared) < self.min_shared_contexts:
                continue
            va = np.array([pa[k] for k in shared])
            vb = np.array([pb[k] for k in shared])
            if va.std() == 0 or vb.std() == 0:
                continue
            corr = float(np.corrcoef(va, vb)[0, 1])
            if corr < 0:
                ga, gb = (a, b) if a < b else (b, a)
                winners.append((ga, gb, corr, len(shared)))
        logger.info(f"{len(winners):,} buffering candidates pass criterion (c) "
                    f"(anti-correlated over >= {self.min_shared_contexts} shared contexts)")
        return winners

    # ---- write-back ------------------------------------------------------------

    def run_build(self):
        self.fit_expectation_model()
        resid_items, m_tests = self.compute_residual_edges()

        def tier(ar):
            if ar >= self.tier_cuts.get("strong", 0.50):
                return "Strong"
            if ar >= self.tier_cuts.get("moderate", 0.30):
                return "Moderate"
            return "Weak"

        cur = self.conn.cursor()

        # coess_rho for these pairs, if D5 already scored them (novelty contrast)
        pair_gene_ids = set()
        for (ga, gb), _ in [item for item, _p, _fdr in resid_items]:
            pair_gene_ids.add(ga); pair_gene_ids.add(gb)
        coess_by_pair = {}
        if resid_items:
            cur.execute("""SELECT gene_a_id, gene_b_id, coess_rho FROM fact_gene_pair
                          WHERE version_id=%s AND config_id=%s AND coess_rho IS NOT NULL
                          AND gene_a_id = ANY(%s) AND gene_b_id = ANY(%s)""",
                        (self.version_id, self.config_id, list(pair_gene_ids), list(pair_gene_ids)))
            coess_by_pair = {(int(a), int(b)): float(r) for a, b, r in cur.fetchall()}

        resid_rows = []
        sig_count = 0
        for ((ga, gb), (r, n, la, lb)), p, fdr in resid_items:
            passed = fdr <= self.fdr_alpha
            if not passed:
                continue
            sig_count += 1
            ar = abs(r)
            coess_rho = coess_by_pair.get((ga, gb))
            novelty = ar - abs(coess_rho or 0.0)
            antagonistic = (coess_rho is not None and coess_rho <= -self.antagonistic_rho) or (r <= -self.antagonistic_rho)
            resid_rows.append((
                ga, gb, str(self.symbols[la]), str(self.symbols[lb]),
                ar, r, int(n), float(p), float(fdr), tier(ar),
                float(novelty), bool(antagonistic),
            ))
        logger.info(f"{sig_count:,}/{len(resid_items):,} residual pairs pass FDR<={self.fdr_alpha}")

        buffering = self.find_buffering_candidates(cur)

        if self.dry_run:
            print(f"[dry-run] would upsert {len(resid_rows):,} residual-channel pairs + "
                  f"{len(buffering):,} buffering-candidate pairs; "
                  f"expectation model {100*self.residual_var_explained:.1f}% variance explained.")
            return {"resid_pairs": len(resid_rows), "buffering_pairs": len(buffering)}

        self.write_expectation_model(cur)
        self.conn.commit()

        # Chunked with a commit per chunk (same pattern as D6/D9 and D8's fact_gene_pair
        # write) — keeps each transaction short and gives partial progress if the
        # connection drops mid-write, instead of one long, invisible transaction.
        CH = 20_000

        if resid_rows:
            batch = [(
                self.version_id, self.run_id, self.config_id, self.organism, ga, gb, sa, sb,
                effect, rho, n, p, fdr, t, ant, novelty,
                t, effect, "resid", 1, n, fdr,
            ) for ga, gb, sa, sb, effect, rho, n, p, fdr, t, novelty, ant in resid_rows]
            _RESID_SQL = """
                INSERT INTO fact_gene_pair
                    (version_id, run_id, config_id, organism, gene_a_id, gene_b_id,
                     gene_a_symbol, gene_b_symbol,
                     resid_effect, resid_rho, resid_support, resid_p_value, resid_fdr, resid_tier,
                     is_antagonistic, novelty_score,
                     relatedness_tier, relatedness_score, evidence_channels, evidence_channel_count,
                     total_support, min_fdr)
                VALUES %s
                ON CONFLICT (version_id, config_id, gene_a_id, gene_b_id) DO UPDATE SET
                    resid_effect=EXCLUDED.resid_effect, resid_rho=EXCLUDED.resid_rho,
                    resid_support=EXCLUDED.resid_support, resid_p_value=EXCLUDED.resid_p_value,
                    resid_fdr=EXCLUDED.resid_fdr, resid_tier=EXCLUDED.resid_tier,
                    is_antagonistic=EXCLUDED.is_antagonistic, novelty_score=EXCLUDED.novelty_score,
                    is_current=TRUE
            """
            total = 0
            for s in range(0, len(batch), CH):
                chunk = batch[s:s + CH]
                psycopg2.extras.execute_values(cur, _RESID_SQL, chunk, page_size=5000)
                self.conn.commit()
                total += len(chunk)
                logger.info(f"  {total:,}/{len(batch):,} resid_* fact_gene_pair rows upserted")
            logger.info(f"Upserted {total:,} resid_* fact_gene_pair rows")

        if buffering:
            sym = self.symbol_by_gene
            batch = [(
                self.version_id, self.run_id, self.config_id, self.organism, ga, gb,
                str(sym.get(ga, "")), str(sym.get(gb, "")), True, "a,b,c",
                "Weak",
            ) for ga, gb, corr, n_ctx in buffering]
            _BUFFERING_SQL = """
                INSERT INTO fact_gene_pair
                    (version_id, run_id, config_id, organism, gene_a_id, gene_b_id,
                     gene_a_symbol, gene_b_symbol, is_buffering_candidate, buffering_basis,
                     relatedness_tier)
                VALUES %s
                ON CONFLICT (version_id, config_id, gene_a_id, gene_b_id) DO UPDATE SET
                    is_buffering_candidate=EXCLUDED.is_buffering_candidate,
                    buffering_basis=EXCLUDED.buffering_basis, is_current=TRUE
            """
            total = 0
            for s in range(0, len(batch), CH):
                chunk = batch[s:s + CH]
                psycopg2.extras.execute_values(cur, _BUFFERING_SQL, chunk, page_size=5000)
                self.conn.commit()
                total += len(chunk)
                logger.info(f"  {total:,}/{len(batch):,} buffering-candidate fact_gene_pair rows upserted")
            logger.info(f"Upserted {total:,} buffering-candidate fact_gene_pair rows")

        print(f"Wrote {len(resid_rows):,} residual-channel pairs + {len(buffering):,} buffering candidates "
              f"(config_id={self.config_id}); expectation model "
              f"{100*self.residual_var_explained:.1f}% variance explained.")
        return {"resid_pairs": len(resid_rows), "buffering_pairs": len(buffering)}

    def run(self):
        self.connect()
        self.resolve()
        self.load()
        self.run_build()
        self.conn.close()
        return True


def main():
    ap = argparse.ArgumentParser(description="D5b novelty / mechanistic-divergence (Channel 5) — GPU-capable")
    ap.add_argument("--version", type=int, required=True)
    ap.add_argument("--config-id", type=int, default=None)
    ap.add_argument("--label", default=None)
    ap.add_argument("--resid-rho-min", type=float, default=None)
    ap.add_argument("--top-k", type=int, default=None)
    ap.add_argument("--min-support", type=int, default=None)
    ap.add_argument("--fdr-alpha", type=float, default=None)
    ap.add_argument("--antagonistic-rho", type=float, default=None,
                    help="|rho| floor (raw or residual) for is_antagonistic (default: config or 0.30)")
    ap.add_argument("--min-shared-contexts", type=int, default=None,
                    help="min shared context buckets to test buffering criterion (c) (default: config or 3)")
    ap.add_argument("--block", type=int, default=2048)
    ap.add_argument("--cpu", action="store_true", help="force CPU/numpy (skip GPU)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO),
                        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    ok = NoveltyCompute(
        args.version, config_id=args.config_id, label=args.label, resid_rho_min=args.resid_rho_min,
        top_k=args.top_k, min_support=args.min_support, fdr_alpha=args.fdr_alpha,
        antagonistic_rho=args.antagonistic_rho, min_shared_contexts=args.min_shared_contexts,
        block=args.block, prefer_gpu=not args.cpu, dry_run=args.dry_run).run()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

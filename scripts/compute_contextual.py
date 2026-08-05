#!/usr/bin/env python3
"""
compute_contextual.py — D8 driver: contextual convergence (Channel 4), CPU.

Stratifies the same co-hit math as D6 (Jaccard / PMI / one-sided hypergeometric)
by the facets P3 captured in dim_screen_context (assay_domain, cell_line,
cell_type, condition, phenotype): for each facet TYPE, screens are bucketed by
their value in that facet, and co-hit is computed *within* each bucket (never
across buckets, never against the global screen set). This lets an edge state
"related under oxidative stress" rather than just "related."

Two things this deliberately reuses rather than recomputes:
  - screen -> hit matrix construction (same selective-gene filter as D6).
  - the Jaccard/PMI/hypergeometric formulas (same as compute_cohit.py, §6.2),
    just re-run per bucket with bucket-local marginals (a bucket's screens are
    its own universe N, not the whole version's screen count).

BH-FDR is corrected across the POOLED tested-pair space of each facet TYPE
(all its buckets together) — that is "the channel" for NFR-5 purposes; a pair
tested in ten tiny buckets of the same facet is one comparison stream, not ten.

Storage: one row per (pair, context_type, context_value) in
dim_gene_pair_context (drill-down), plus the single BEST context per pair
(lowest FDR, ties by Jaccard) rolled into fact_gene_pair.context_* — matching
how D5/D6/D7 each own their slice of the header row. A pair discovered only
here (no co-essentiality/co-hit/co-citation edge) still gets a fact_gene_pair
row so the FK from dim_gene_pair_context has something to point at; D9 rolls
it into evidence_channels like any other channel.

Usage (via slurm/reticle-context.sh):
  python3 compute_contextual.py --version 7 --config-id 2
  python3 compute_contextual.py --version 7 --config-id 2 --dry-run
"""

import argparse
import logging
import sys
import time

import numpy as np
import psycopg2
import psycopg2.extras

import relatedness_core as rc

logger = logging.getLogger("compute_contextual")

COMPUTE_VERSION = "d8-contextual-1.0"

ALL_CONTEXT_TYPES = ["assay_domain", "cell_line", "cell_type", "condition", "phenotype"]


class ContextualCompute:
    def __init__(self, version_id, config_id=None, label=None, context_types=None,
                 min_context_screens=None, min_cohit=None, max_values_per_type=300,
                 fdr_alpha=None, max_store=2_000_000, dry_run=False):
        self.version_id = version_id
        self.config_id = config_id
        self.label = label
        self.context_types = context_types or ALL_CONTEXT_TYPES
        self.min_context_screens = min_context_screens
        self.min_cohit = min_cohit
        self.max_values_per_type = max_values_per_type
        self.fdr_alpha = fdr_alpha
        self.max_store = max_store
        self.dry_run = dry_run
        self.conn = None

    def connect(self):
        self.conn = rc.pg_connect()
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
        self.min_context_screens = self.min_context_screens if self.min_context_screens is not None \
            else (th.get("min_context_screens") or 5)
        self.min_cohit = self.min_cohit if self.min_cohit is not None else (th.get("min_context_cohit") or 2)
        self.fdr_alpha = self.fdr_alpha if self.fdr_alpha is not None else (th.get("fdr_alpha") or 0.01)
        # dict.get(key, default) only applies its default when key is MISSING, not
        # when present-with-null (this warehouse's configs do that — e.g. ann_topk
        # null in config_id=2 — see compute_novelty.py's _coalesce for the postmortem).
        self.tier_cuts = (th.get("tier_cuts") or {}).get("context") or {"strong": 0.50, "moderate": 0.20}
        self.sel_filter = th.get("selective_gene_filter") or {}

        bad = [t for t in self.context_types if t not in ALL_CONTEXT_TYPES]
        if bad:
            raise SystemExit(f"Unknown --context-types {bad}; must be a subset of {ALL_CONTEXT_TYPES}")

        cur.execute("SELECT run_id FROM etl_pipeline_run WHERE data_load_version_id=%s "
                    "ORDER BY run_id DESC LIMIT 1", (self.version_id,))
        r = cur.fetchone()
        if not r:
            raise SystemExit(f"No etl_pipeline_run for version {self.version_id}")
        self.run_id = r[0]
        logger.info(f"version={self.version_id} organism={self.organism} config_id={self.config_id} "
                    f"run_id={self.run_id} min_context_screens={self.min_context_screens} "
                    f"min_cohit={self.min_cohit} context_types={self.context_types}")

    def load(self):
        """Same selective-gene hit matrix as D6, but keeps the screen_id <-> column
        mapping (D6 doesn't need it since it never slices columns by bucket)."""
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

        hg, hs = [], []
        c2 = self.conn.cursor(name="ctx_hits")
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

        hs_arr = np.asarray(hs, dtype=np.int64)
        self.screen_ids_unique, col_idx = np.unique(hs_arr, return_inverse=True)
        self.H, n_scr = rc.selective_binary_csr(np.asarray(hg, dtype=np.int64), col_idx, self.gene_ids)
        self.screen_to_col = {int(s): i for i, s in enumerate(self.screen_ids_unique)}
        logger.info(f"Hit matrix: {self.n_sel:,} genes × {n_scr:,} screens with selective hits "
                    f"({int(self.H.nnz):,} hits)")

        cur.execute(f"""SELECT screen_id, {', '.join(ALL_CONTEXT_TYPES)}
                       FROM dim_screen_context WHERE version_id=%s AND is_current=TRUE""",
                    (self.version_id,))
        self.context_rows = cur.fetchall()
        logger.info(f"{len(self.context_rows):,} dim_screen_context rows loaded")

    def _buckets_for_type(self, type_idx):
        """screen_id -> value for this context_type, grouped, size-filtered."""
        buckets = {}
        for row in self.context_rows:
            sid, value = row[0], row[1 + type_idx]
            if not value:
                continue
            buckets.setdefault(value, []).append(sid)
        buckets = {v: sids for v, sids in buckets.items() if len(sids) >= self.min_context_screens}
        if len(buckets) > self.max_values_per_type:
            kept = sorted(buckets, key=lambda v: -len(buckets[v]))[:self.max_values_per_type]
            dropped = len(buckets) - len(kept)
            logger.info(f"  {dropped} small/long-tail bucket values dropped "
                        f"(kept top {self.max_values_per_type} by screen count)")
            buckets = {v: buckets[v] for v in kept}
        return buckets

    def _compute_bucket(self, cols):
        """Co-hit within one screen-column subset. Compresses to genes with >=1
        hit in the bucket first — most selective genes are silent in any given
        small bucket, so this keeps the matmul cheap."""
        Hb_full = self.H[:, cols]
        active = np.asarray(Hb_full.sum(axis=1)).ravel() > 0
        if active.sum() < 2:
            return None
        active_idx = np.where(active)[0]
        Hb = Hb_full[active_idx, :]
        Cb = (Hb @ Hb.T).tocoo()
        upper = Cb.row < Cb.col
        r = active_idx[Cb.row[upper]]
        c = active_idx[Cb.col[upper]]
        n11 = Cb.data[upper].astype(np.int64)
        keep = n11 >= self.min_cohit
        if not keep.any():
            return None
        r, c, n11 = r[keep], c[keep], n11[keep]
        a_hits = np.asarray(Hb_full.sum(axis=1)).ravel().astype(np.int64)
        ai = a_hits[r]
        bi = a_hits[c]
        Nb = len(cols)
        jaccard = n11 / np.maximum(ai + bi - n11, 1)
        p = rc.hypergeom_sf(n11, Nb, ai, bi)
        pmi = np.log2((n11.astype(np.float64) * Nb) / np.maximum(ai * bi, 1))
        return r, c, n11, ai, bi, Nb, jaccard, pmi, p

    def compute_and_write(self):
        t0 = time.time()
        all_ctx = []   # list of dicts, one per significant (pair, context_type, context_value)
        for ctype in self.context_types:
            buckets = self._buckets_for_type(ALL_CONTEXT_TYPES.index(ctype))
            logger.info(f"[{ctype}] {len(buckets)} bucket values >= {self.min_context_screens} screens")
            type_rows = []
            for value, sids in buckets.items():
                cols = [self.screen_to_col[s] for s in sids if s in self.screen_to_col]
                if len(cols) < self.min_context_screens:
                    continue
                res = self._compute_bucket(np.asarray(cols, dtype=np.int64))
                if res is None:
                    continue
                r, c, n11, ai, bi, Nb, jaccard, pmi, p = res
                for i in range(r.size):
                    type_rows.append({
                        "context_type": ctype, "context_value": str(value)[:250],
                        "r": int(r[i]), "c": int(c[i]), "n11": int(n11[i]),
                        "screens_in_context": int(Nb), "jaccard": float(jaccard[i]),
                        "pmi": float(pmi[i]), "p": float(p[i]),
                    })
            if not type_rows:
                continue
            p_arr = np.array([row["p"] for row in type_rows])
            fdr_arr = rc.bh_fdr(p_arr)
            for row, fdr in zip(type_rows, fdr_arr):
                row["fdr"] = float(fdr)
            sig = [row for row in type_rows if row["fdr"] <= self.fdr_alpha]
            logger.info(f"[{ctype}] {len(type_rows):,} tested, {len(sig):,} pass FDR<={self.fdr_alpha}")
            all_ctx.extend(sig)

        if not all_ctx:
            print("No contextual pairs cleared support + FDR in any facet — nothing to store.")
            return {"pairs": 0}

        if len(all_ctx) > self.max_store:
            all_ctx.sort(key=lambda row: -row["jaccard"])
            logger.info(f"Capping {len(all_ctx):,} significant context rows to top {self.max_store:,} by Jaccard")
            all_ctx = all_ctx[:self.max_store]

        strong = self.tier_cuts.get("strong", 0.50)
        moderate = self.tier_cuts.get("moderate", 0.20)

        def tier(jac):
            return "Strong" if jac >= strong else ("Moderate" if jac >= moderate else "Weak")

        # gene_a/gene_b (actual gene_ids, ordered), one dict entry per row
        best_per_pair = {}   # (gene_a, gene_b) -> best context row (min fdr, tie-break max jaccard)
        for row in all_ctx:
            r_idx, c_idx = row["r"], row["c"]
            ga, gb = int(self.gene_ids[r_idx]), int(self.gene_ids[c_idx])
            a_idx, b_idx = (r_idx, c_idx) if ga <= gb else (c_idx, r_idx)
            if ga > gb:
                ga, gb = gb, ga
            row["gene_a"], row["gene_b"] = ga, gb
            row["gene_a_symbol"] = str(self.symbols[a_idx])
            row["gene_b_symbol"] = str(self.symbols[b_idx])
            row["tier"] = tier(row["jaccard"])
            cur_best = best_per_pair.get((ga, gb))
            if cur_best is None or (row["fdr"], -row["jaccard"]) < (cur_best["fdr"], -cur_best["jaccard"]):
                best_per_pair[(ga, gb)] = row

        logger.info(f"{len(all_ctx):,} significant context rows across {len(best_per_pair):,} distinct pairs "
                    f"({time.time()-t0:.0f}s)")

        if self.dry_run:
            print(f"[dry-run] would upsert {len(all_ctx):,} dim_gene_pair_context rows "
                  f"for {len(best_per_pair):,} pairs.")
            return {"pairs": len(best_per_pair), "context_rows": len(all_ctx)}

        cur = self.conn.cursor()

        # 1) ensure a fact_gene_pair row exists for every pair with a winning context,
        #    setting context_* (leaves coess_/cohit_/cocite_ columns untouched).
        # Chunked with a commit per chunk (same pattern as the dim_gene_pair_context
        # write below, D6, and D9's rollup) — this pair_batch can be 1M+ rows against
        # an existing 15M+ row table; one giant unchunked transaction is a long window
        # with zero progress visibility and zero partial-progress if the connection
        # drops (this table has hit exactly that failure mode before — see D6/D7's
        # OOM/9h-query fixes in git history).
        pair_batch = [(
            self.version_id, self.run_id, self.config_id, self.organism,
            b["gene_a"], b["gene_b"], b["gene_a_symbol"], b["gene_b_symbol"],
            float(b["jaccard"]), int(b["n11"]), f"{b['context_type']}:{b['context_value']}",
            float(b["fdr"]), b["tier"], b["tier"], float(b["jaccard"]), "context", 1,
            int(b["n11"]), float(b["fdr"]),
        ) for b in best_per_pair.values()]
        _PAIR_UPSERT_SQL = """
            INSERT INTO fact_gene_pair
                (version_id, run_id, config_id, organism, gene_a_id, gene_b_id,
                 gene_a_symbol, gene_b_symbol, context_effect, context_support,
                 context_best_key, context_best_fdr, context_tier,
                 relatedness_tier, relatedness_score, evidence_channels, evidence_channel_count,
                 total_support, min_fdr)
            VALUES %s
            ON CONFLICT (version_id, config_id, gene_a_id, gene_b_id) DO UPDATE SET
                context_effect=EXCLUDED.context_effect, context_support=EXCLUDED.context_support,
                context_best_key=EXCLUDED.context_best_key, context_best_fdr=EXCLUDED.context_best_fdr,
                context_tier=EXCLUDED.context_tier, is_current=TRUE
        """
        PAIR_CH = 20_000
        pair_total = 0
        for s in range(0, len(pair_batch), PAIR_CH):
            chunk = pair_batch[s:s + PAIR_CH]
            psycopg2.extras.execute_values(cur, _PAIR_UPSERT_SQL, chunk, page_size=5000)
            self.conn.commit()
            pair_total += len(chunk)
            logger.info(f"  {pair_total:,}/{len(pair_batch):,} fact_gene_pair rows upserted (context_*)")
        logger.info(f"Upserted {pair_total:,} fact_gene_pair rows (context_* columns)")

        # 2) resolve gene_pair_id for every winning pair via a temp join table
        cur.execute("CREATE TEMP TABLE IF NOT EXISTS tmp_ctx_pairs (gene_a_id INT, gene_b_id INT)")
        cur.execute("TRUNCATE tmp_ctx_pairs")
        psycopg2.extras.execute_values(
            cur, "INSERT INTO tmp_ctx_pairs (gene_a_id, gene_b_id) VALUES %s",
            list(best_per_pair.keys()), page_size=10000)
        cur.execute("""
            SELECT t.gene_a_id, t.gene_b_id, f.gene_pair_id FROM tmp_ctx_pairs t
            JOIN fact_gene_pair f ON f.version_id=%s AND f.config_id=%s
                AND f.gene_a_id=t.gene_a_id AND f.gene_b_id=t.gene_b_id
        """, (self.version_id, self.config_id))
        pair_id = {(int(a), int(b)): int(pid) for a, b, pid in cur.fetchall()}

        # 3) upsert every significant (pair, context_type, context_value) detail row
        detail_batch = [(
            pair_id[(row["gene_a"], row["gene_b"])], self.version_id, self.config_id,
            row["context_type"], row["context_value"], f"{row['context_type']}:{row['context_value']}",
            row["n11"], row["screens_in_context"], float(row["jaccard"]), float(row["pmi"]),
            float(row["p"]), float(row["fdr"]), row["tier"],
        ) for row in all_ctx if (row["gene_a"], row["gene_b"]) in pair_id]
        total = 0
        CH = 20_000
        for s in range(0, len(detail_batch), CH):
            batch = detail_batch[s:s + CH]
            psycopg2.extras.execute_values(cur, """
                INSERT INTO dim_gene_pair_context
                    (gene_pair_id, version_id, config_id, context_type, context_value, context_key,
                     cohit_count, screens_in_context, jaccard, pmi, fisher_p, fdr, tier)
                VALUES %s
                ON CONFLICT (gene_pair_id, context_type, context_value) DO UPDATE SET
                    context_key=EXCLUDED.context_key, cohit_count=EXCLUDED.cohit_count,
                    screens_in_context=EXCLUDED.screens_in_context, jaccard=EXCLUDED.jaccard,
                    pmi=EXCLUDED.pmi, fisher_p=EXCLUDED.fisher_p, fdr=EXCLUDED.fdr, tier=EXCLUDED.tier
            """, batch, page_size=10000)
            self.conn.commit()
            total += len(batch)
            logger.info(f"  {total:,}/{len(detail_batch):,} dim_gene_pair_context rows stored")

        print(f"Wrote {len(pair_batch):,} fact_gene_pair context rows, {total:,} dim_gene_pair_context "
              f"detail rows (config_id={self.config_id}).")
        return {"pairs": len(pair_batch), "context_rows": total}

    def run(self):
        self.connect()
        self.resolve()
        self.load()
        self.compute_and_write()
        self.conn.close()
        return True


def main():
    ap = argparse.ArgumentParser(description="D8 contextual convergence (Channel 4) — CPU, warehouse-native")
    ap.add_argument("--version", type=int, required=True)
    ap.add_argument("--config-id", type=int, default=None)
    ap.add_argument("--label", default=None)
    ap.add_argument("--context-types", default=None,
                    help=f"comma-separated subset of {ALL_CONTEXT_TYPES} (default: all)")
    ap.add_argument("--min-context-screens", type=int, default=None,
                    help="min screens in a bucket to compute it (default: config min_context_screens or 5)")
    ap.add_argument("--min-cohit", type=int, default=None,
                    help="min shared hits within a bucket (default: config min_context_cohit or 2)")
    ap.add_argument("--max-values-per-type", type=int, default=300,
                    help="cap on distinct bucket values processed per facet; keeps the largest by screen count")
    ap.add_argument("--fdr-alpha", type=float, default=None)
    ap.add_argument("--max-store", type=int, default=2_000_000,
                    help="cap on stored dim_gene_pair_context rows; if more are significant, keep the top by Jaccard")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO),
                        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    context_types = args.context_types.split(",") if args.context_types else None
    ok = ContextualCompute(args.version, config_id=args.config_id, label=args.label,
                           context_types=context_types, min_context_screens=args.min_context_screens,
                           min_cohit=args.min_cohit, max_values_per_type=args.max_values_per_type,
                           fdr_alpha=args.fdr_alpha, max_store=args.max_store, dry_run=args.dry_run).run()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

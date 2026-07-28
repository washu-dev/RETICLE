#!/usr/bin/env python3
"""
harmonize_warehouse.py — P1 driver: warehouse-native CRISPR score harmonization.

Reads score VALUES from screen_gene_raw (RDS) + score TYPES / screen metadata from
the BioGRID metadata JSON ($DATA_DIR), harmonizes each screen onto the unified
loss-of-function axis using harmonization_core, and writes back:
  - fact_screen_gene.harmonized_score / percentile_score / robust_z_score  (per screen,gene)
  - screen_harmonization  (per screen: coverage_type, score_basis, is_directional, ...)

I/O-bound (not GPU-relevant). Processed screen-by-screen, committed per screen,
resumable (screens already in screen_harmonization are skipped).

Usage (from scripts/, or via slurm/reticle-harmonize.sh):
  python3 harmonize_warehouse.py --version 7
  python3 harmonize_warehouse.py --version 7 --dry-run
  python3 harmonize_warehouse.py --version 7 --overrides /path/directionality_overrides.json
"""

import argparse
import logging
import os
import sys
import time

import psycopg2
import psycopg2.extras
import pandas as pd

from config import Config
import harmonization_core as hc

logger = logging.getLogger("harmonize_warehouse")

# organism (data_load_version) -> metadata JSON filename fallback
_JSON_FALLBACK = {
    "homo_sapiens": "screen_metadata_homo_sapiens.json",
    "mus_musculus": "screen_metadata_musculus.json",
}


# Canonical screen-id normalization lives in harmonization_core so the override
# map keys and these lookups can never drift apart.
_digits = hc.normalize_screen_id


def load_metadata(organism):
    """Return {digit_screen_id: meta_dict} from the BioGRID metadata JSON."""
    import json
    fname = None
    org_cfg = getattr(Config, "ORGANISMS", {}).get(organism, {})
    if isinstance(org_cfg, dict):
        fname = org_cfg.get("json_pattern")
    fname = fname or _JSON_FALLBACK.get(organism)
    if not fname:
        raise SystemExit(f"No metadata JSON mapping for organism '{organism}'")
    path = os.path.join(str(Config.DATA_DIR), fname)
    if not os.path.exists(path):
        raise SystemExit(f"Metadata JSON not found: {path} (set DATA_DIR)")
    raw = json.loads(open(path).read())
    out = {}
    items = raw.items() if isinstance(raw, dict) else enumerate(raw)
    for k, meta in items:
        if isinstance(meta, list):
            meta = meta[0] if meta else {}
        sid = _digits(meta.get("SCREEN_ID", k))
        out[sid] = meta
    logger.info(f"Loaded metadata for {len(out):,} screens from {path}")
    return out


class WarehouseHarmonizer:
    def __init__(self, version_id, overrides_path=None, dry_run=False):
        self.version_id = version_id
        self.overrides_path = overrides_path
        self.dry_run = dry_run
        self.conn = None
        self.organism = None
        self.stats = {"ok": 0, "skipped": 0, "no_metadata": 0, "hit_only": 0, "basis": {}}

    def connect(self):
        params = Config.get_psycopg2_params()
        params["sslmode"] = "require"
        self.conn = psycopg2.connect(**params)
        self.conn.autocommit = False
        cur = self.conn.cursor()
        cur.execute("SET statement_timeout = 0")
        cur.execute("SET work_mem = '128MB'")
        self.conn.commit()
        logger.info("Connected to database")

    def resolve_organism(self):
        cur = self.conn.cursor()
        cur.execute("SELECT organism FROM data_load_version WHERE version_id=%s", (self.version_id,))
        row = cur.fetchone()
        if not row:
            raise SystemExit(f"version_id {self.version_id} not found")
        self.organism = row[0]
        logger.info(f"version_id={self.version_id} organism={self.organism}")

    def run(self):
        self.connect()
        self.resolve_organism()
        metadata = load_metadata(self.organism)
        overrides = hc.load_overrides(self.overrides_path)
        if overrides:
            logger.info(f"Loaded {len(overrides)} directionality overrides")

        cur = self.conn.cursor()
        cur.execute("SELECT screen_id, biogrid_screen_id FROM screen WHERE version_id=%s ORDER BY screen_id",
                    (self.version_id,))
        screens = cur.fetchall()
        cur.execute("SELECT screen_id FROM screen_harmonization WHERE version_id=%s", (self.version_id,))
        done = {r[0] for r in cur.fetchall()}
        todo = [(sid, bid) for sid, bid in screens if sid not in done]
        logger.info(f"{len(screens)} screens, {len(done)} already harmonized, {len(todo)} to process")

        # session temp table reused for the per-screen set-based UPDATE
        if not self.dry_run:
            cur.execute("CREATE TEMP TABLE IF NOT EXISTS tmp_harm "
                        "(gene_id INT, h NUMERIC, p NUMERIC, z NUMERIC)")
            self.conn.commit()

        t0 = time.time()
        for i, (screen_id, biogrid_id) in enumerate(todo, 1):
            self._process_screen(screen_id, biogrid_id, metadata, overrides)
            if i % 100 == 0:
                logger.info(f"  {i}/{len(todo)} screens ({time.time()-t0:.0f}s)")

        logger.info("=== Summary ===")
        logger.info(f"  harmonized : {self.stats['ok']}")
        logger.info(f"  hit-only   : {self.stats['hit_only']}")
        logger.info(f"  no metadata: {self.stats['no_metadata']}")
        for k, v in sorted(self.stats["basis"].items(), key=lambda x: -x[1]):
            logger.info(f"      {v:5d}  {k}")
        self.conn.close()
        return self.stats["ok"] > 0 or len(todo) == 0

    def _process_screen(self, screen_id, biogrid_id, metadata, overrides):
        meta = metadata.get(_digits(biogrid_id))
        if not meta:
            self.stats["no_metadata"] += 1
            logger.warning(f"  screen_id={screen_id} biogrid={biogrid_id}: no metadata, skipping")
            return

        col_types = {f"SCORE.{k}": (meta.get(f"SCORE.{k}_TYPE", "") or "").strip()
                     for k in range(1, 6)}
        col_types = {k: v for k, v in col_types.items() if v and v != "-"}

        cur = self.conn.cursor()
        cur.execute("""SELECT gene_id, score_1, score_2, score_3, score_4, score_5
                       FROM screen_gene_raw WHERE version_id=%s AND screen_id=%s""",
                    (self.version_id, screen_id))
        rows = cur.fetchall()
        if not rows:
            return
        df = pd.DataFrame(rows, columns=["gene_id", "SCORE.1", "SCORE.2", "SCORE.3", "SCORE.4", "SCORE.5"])

        screen_type = (meta.get("SCREEN_TYPE", "") or "").strip()
        methodology = (meta.get("METHODOLOGY", "") or "").strip()
        library_type = (meta.get("LIBRARY_TYPE", "") or "").strip()
        full_avail = (meta.get("FULL_SIZE_AVAILABLE", "") or "").strip()
        coverage_type = "HIT_ONLY" if full_avail.lower() == "no" else "FULL"
        is_activation = ("ACTIVATION" in methodology.upper()) or ("CRISPRA" in library_type.upper())
        perturbation_mult = -1 if is_activation else 1

        override = overrides.get(_digits(biogrid_id))
        if override is not None:
            df["HARMONIZED_SCORE"], basis, is_directional = hc.apply_override(df, col_types, override)
        else:
            s_raw, basis, is_directional = hc.resolve_s_raw(df, col_types, screen_type)
            df["HARMONIZED_SCORE"] = s_raw * perturbation_mult

        hc.add_rank_columns(df)
        genes_measured = int(df["HARMONIZED_SCORE"].notna().sum())
        self.stats["basis"][basis.split("(")[0]] = self.stats["basis"].get(basis.split("(")[0], 0) + 1

        if self.dry_run:
            logger.info(f"  [dry-run] screen={screen_id} basis={basis} measured={genes_measured} "
                        f"coverage={coverage_type} pert={perturbation_mult}")
            self.stats["ok"] += 1
            self.stats["hit_only"] += 1 if coverage_type == "HIT_ONLY" else 0
            return

        # write-back: set-based UPDATE of fact_screen_gene via a temp table
        def _n(v):
            return None if (v is None or (isinstance(v, float) and v != v)) else float(v)
        payload = [(int(r.gene_id), _n(r.HARMONIZED_SCORE), _n(r.PERCENTILE_SCORE), _n(r.ROBUST_Z_SCORE))
                   for r in df.itertuples(index=False)]
        cur.execute("TRUNCATE tmp_harm")
        psycopg2.extras.execute_values(
            cur, "INSERT INTO tmp_harm (gene_id, h, p, z) VALUES %s", payload, page_size=10000)
        cur.execute("""
            UPDATE fact_screen_gene f
            SET harmonized_score = t.h, percentile_score = t.p, robust_z_score = t.z
            FROM tmp_harm t
            WHERE f.version_id = %s AND f.screen_id = %s AND f.gene_id = t.gene_id
        """, (self.version_id, screen_id))

        cur.execute("""
            INSERT INTO screen_harmonization
                (version_id, screen_id, biogrid_screen_id, coverage_type, score_basis,
                 is_directional, selection_type, methodology, library_type,
                 perturbation_mult, genes_measured, is_current)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE)
            ON CONFLICT (version_id, screen_id) DO UPDATE SET
                coverage_type=EXCLUDED.coverage_type, score_basis=EXCLUDED.score_basis,
                is_directional=EXCLUDED.is_directional, selection_type=EXCLUDED.selection_type,
                methodology=EXCLUDED.methodology, library_type=EXCLUDED.library_type,
                perturbation_mult=EXCLUDED.perturbation_mult, genes_measured=EXCLUDED.genes_measured,
                is_current=TRUE
        """, (self.version_id, screen_id, str(biogrid_id), coverage_type, basis,
              bool(is_directional), screen_type, methodology, library_type,
              int(perturbation_mult), genes_measured))
        self.conn.commit()
        self.stats["ok"] += 1
        self.stats["hit_only"] += 1 if coverage_type == "HIT_ONLY" else 0


def main():
    ap = argparse.ArgumentParser(description="Warehouse-native CRISPR score harmonization")
    ap.add_argument("--version", type=int, required=True, help="Data load version ID")
    ap.add_argument("--overrides", default=None, help="Path to directionality_overrides.json (optional)")
    ap.add_argument("--dry-run", action="store_true", help="Resolve + log, write nothing")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO),
                        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    ok = WarehouseHarmonizer(args.version, overrides_path=args.overrides, dry_run=args.dry_run).run()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

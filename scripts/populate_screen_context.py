#!/usr/bin/env python3
"""
populate_screen_context.py — P3: populate dim_screen_context.

Materializes one row per (version, screen) with the assay/condition/cell-line
facets the contextual-convergence channel (D8) buckets pairs by, and that the
Channel-5 expectation model (D5b) uses as context-group means. This is the
table migration 0014 deferred (see database/migrations/0016_dim_screen_context.sql).

Two field groups:
  1. Denormalized straight from screen_harmonization (P1, migration 0012) —
     coverage_type, score_basis, is_directional, selection_type. NOT
     recomputed here; P1 already paid for this.
  2. New extraction from the metadata JSON ($DATA_DIR, same file P1/P2 read):
     CELL_LINE, CELL_TYPE, PHENOTYPE, CONDITION_NAME(+CONDITION_DOSAGE), and
     assay_domain — a coarse fitness/stress/reporter/other class derived from
     PHENOTYPE (ported from prototype/script/llm_metadata_extractor.py's
     rule_assay_domain; still rule-only, no LLM call).

context_key is a readable, lowercased "assay_domain|condition|cell_line" label
(missing facets omitted) — not a hash — so it doubles as a human-readable
"related under X" tag and a cheap GROUP BY key for D8.

Usage (via slurm/reticle-screen-context.sh):
  python3 populate_screen_context.py --version 7
  python3 populate_screen_context.py --version 7 --dry-run
"""

import argparse
import logging
import sys

import psycopg2
import psycopg2.extras

from config import Config
import harmonization_core as hc
from harmonize_warehouse import load_metadata

logger = logging.getLogger("populate_screen_context")

# PHENOTYPE keyword rule -> assay_domain (ported from
# prototype/script/llm_metadata_extractor.py::rule_assay_domain).
_STRESS_MARKERS = ("resistance",)
_FITNESS_KEYWORDS = ("prolifer", "viab", "fitness", "growth", "essential", "tumor")
_REPORTER_KEYWORDS = (
    "protein", "peptide", "rna", "accumulation", "distribution", "transport",
    "localization", "signal transduction", "phagocyt", "autophag", "mitophag",
    "lysosome", "vesicle", "frameshift", "nonsense-mediated", "binding",
    "secretion", "differentiation", "reprogram", "migration", "cell cycle",
    "senescen", "syncytium", "pyroptosis", "lipid",
)


def rule_assay_domain(phenotype):
    """Coarse assay class (fitness/stress/reporter/other) from PHENOTYPE, plus a
    confidence in [0,1]. Governs how screens are POOLED for the contextual
    channel — never re-derives coverage_type/selection_type (those are P1's)."""
    ph = (phenotype or "").strip().lower()
    if not ph:
        return None, 0.0
    if ph.startswith("response to") or any(k in ph for k in _STRESS_MARKERS):
        return "stress", 1.0
    if any(k in ph for k in _FITNESS_KEYWORDS):
        return "fitness", 1.0
    if any(k in ph for k in _REPORTER_KEYWORDS):
        return "reporter", 1.0
    return "other", 0.5


def _clean(v):
    if v is None:
        return None
    v = str(v).strip()
    return v if v and v != "-" else None


def build_condition(meta):
    name = _clean(meta.get("CONDITION_NAME"))
    dosage = _clean(meta.get("CONDITION_DOSAGE"))
    if not name:
        return None
    return f"{name} ({dosage})" if dosage else name


def build_context_key(assay_domain, condition, cell_line):
    parts = [p.strip().lower() for p in (assay_domain, condition, cell_line) if p]
    return "|".join(parts) if parts else None


class ScreenContextPopulator:
    def __init__(self, version_id, dry_run=False):
        self.version_id = version_id
        self.dry_run = dry_run
        self.conn = None
        self.organism = None
        self.run_id = None

    def connect(self):
        params = Config.get_psycopg2_params()
        params["sslmode"] = "require"
        self.conn = psycopg2.connect(**params)
        self.conn.autocommit = False
        cur = self.conn.cursor()
        cur.execute("SET statement_timeout = 0")
        cur.execute("SET work_mem = '64MB'")
        self.conn.commit()

    def resolve(self):
        cur = self.conn.cursor()
        cur.execute("SELECT organism FROM data_load_version WHERE version_id=%s", (self.version_id,))
        row = cur.fetchone()
        if not row:
            raise SystemExit(f"version_id {self.version_id} not found")
        self.organism = row[0]
        cur.execute("SELECT run_id FROM etl_pipeline_run WHERE data_load_version_id=%s "
                    "ORDER BY run_id DESC LIMIT 1", (self.version_id,))
        r = cur.fetchone()
        if not r:
            raise SystemExit(f"No etl_pipeline_run for version {self.version_id}")
        self.run_id = r[0]
        logger.info(f"version={self.version_id} organism={self.organism} run_id={self.run_id}")

    def run(self):
        self.connect()
        self.resolve()
        metadata = load_metadata(self.organism)

        cur = self.conn.cursor()
        cur.execute("SELECT screen_id, biogrid_screen_id, organism FROM screen WHERE version_id=%s",
                    (self.version_id,))
        screens = cur.fetchall()

        cur.execute("""SELECT screen_id, coverage_type, score_basis, is_directional, selection_type
                       FROM screen_harmonization WHERE version_id=%s""", (self.version_id,))
        harmonized = {r[0]: r[1:] for r in cur.fetchall()}

        no_meta = no_harm = 0
        domain_counts = {}
        rows = []
        for screen_id, biogrid_id, screen_organism in screens:
            meta = metadata.get(hc.normalize_screen_id(biogrid_id))
            if meta is None:
                no_meta += 1
                meta = {}
            harm = harmonized.get(screen_id)
            if harm is None:
                no_harm += 1
                coverage_type = score_basis = selection_type = None
                is_directional = None
            else:
                coverage_type, score_basis, is_directional, selection_type = harm

            cell_line = _clean(meta.get("CELL_LINE"))
            cell_type = _clean(meta.get("CELL_TYPE"))
            phenotype = _clean(meta.get("PHENOTYPE"))
            condition = build_condition(meta)
            assay_domain, confidence = rule_assay_domain(phenotype)
            domain_counts[assay_domain] = domain_counts.get(assay_domain, 0) + 1
            context_key = build_context_key(assay_domain, condition, cell_line)
            context_meta = {
                "condition_dosage": _clean(meta.get("CONDITION_DOSAGE")),
                "assay_domain_confidence": confidence,
            }

            rows.append((
                self.version_id, self.run_id, screen_id, biogrid_id, screen_organism,
                assay_domain, condition, cell_line, cell_type, phenotype,
                selection_type, coverage_type, is_directional, score_basis,
                context_key, psycopg2.extras.Json(context_meta),
            ))

        logger.info(f"{len(screens)} screens: {no_meta} without metadata, {no_harm} without screen_harmonization "
                    f"(run P1 harmonize first if this is unexpectedly high)")
        logger.info(f"assay_domain distribution: {domain_counts}")

        if self.dry_run:
            print(f"[dry-run] would upsert {len(rows):,} dim_screen_context rows "
                  f"(version {self.version_id}); assay_domain distribution: {domain_counts}")
            self.conn.close()
            return True

        psycopg2.extras.execute_values(cur, """
            INSERT INTO dim_screen_context (
                version_id, run_id, screen_id, biogrid_screen_id, organism,
                assay_domain, condition, cell_line, cell_type, phenotype,
                selection_type, coverage_type, is_directional, score_basis,
                context_key, context_meta, is_current
            ) VALUES %s
            ON CONFLICT (version_id, screen_id) DO UPDATE SET
                run_id=EXCLUDED.run_id, biogrid_screen_id=EXCLUDED.biogrid_screen_id,
                organism=EXCLUDED.organism, assay_domain=EXCLUDED.assay_domain,
                condition=EXCLUDED.condition, cell_line=EXCLUDED.cell_line,
                cell_type=EXCLUDED.cell_type, phenotype=EXCLUDED.phenotype,
                selection_type=EXCLUDED.selection_type, coverage_type=EXCLUDED.coverage_type,
                is_directional=EXCLUDED.is_directional, score_basis=EXCLUDED.score_basis,
                context_key=EXCLUDED.context_key, context_meta=EXCLUDED.context_meta,
                is_current=TRUE
        """, [r + (True,) for r in rows], page_size=2000)
        self.conn.commit()
        logger.info(f"Upserted {len(rows):,} dim_screen_context rows")
        print(f"P3 complete: {len(rows):,} dim_screen_context rows (version {self.version_id}).")
        self.conn.close()
        return True


def main():
    ap = argparse.ArgumentParser(description="P3: populate dim_screen_context")
    ap.add_argument("--version", type=int, required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO),
                        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    ok = ScreenContextPopulator(args.version, dry_run=args.dry_run).run()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

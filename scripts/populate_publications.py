#!/usr/bin/env python3
"""
populate_publications.py — P2: populate publication + fact_screen_gene_publication.

The ETL's build_fact_screen_gene_publication() is a placeholder (0 rows), so the
co-citation channel (D7) has nothing to read. This fills the gap from data BioGRID
already ships: each screen's source PubMed ID lives as SOURCE_ID in the screen
metadata JSON ($DATA_DIR — the same file harmonize reads).

Steps:
  1. metadata JSON -> {screen: (pmid, citation)}     (SOURCE_ID / SOURCE)
  2. upsert one `publication` row per distinct PMID   (title = citation text stub;
     real title/abstract/journal come later from D10 PubMed fetch)
  3. insert `fact_screen_gene_publication` (version, run, screen, gene, publication,
     hit_flag) by joining screen_gene_raw to each screen's publication.

Default is HITS-ONLY (hit_flag=TRUE): a genome-wide screen "measures" every gene,
so linking non-hits to the paper would make every gene co-cited with every other
(and ~50x the rows). Hits are the notable findings co-citation + PubMed prefetch
actually care about. Use --all to store non-hit links too.

Usage (via slurm/reticle-publications.sh):
  python3 populate_publications.py --version 7
  python3 populate_publications.py --version 7 --dry-run
  python3 populate_publications.py --version 7 --all
"""

import argparse
import logging
import sys
import time

import psycopg2
import psycopg2.extras

from config import Config
import harmonization_core as hc
from harmonize_warehouse import load_metadata

logger = logging.getLogger("populate_publications")

# metadata fields that may hold the PubMed id / citation, in priority order
_PMID_FIELDS = ("SOURCE_ID", "PUBMED_ID", "PMID", "PUBMED")
_CITE_FIELDS = ("SOURCE", "CITATION", "AUTHOR")


def _first(meta, fields):
    for f in fields:
        v = meta.get(f)
        if v not in (None, "", "-"):
            return str(v).strip()
    return None


class PublicationPopulator:
    def __init__(self, version_id, include_all=False, dry_run=False):
        self.version_id = version_id
        self.include_all = include_all
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
        logger.info(f"version={self.version_id} organism={self.organism} run_id={self.run_id} "
                    f"mode={'ALL' if self.include_all else 'HITS-ONLY'}")

    def run(self):
        self.connect()
        self.resolve()
        metadata = load_metadata(self.organism)

        # screens of this version -> PMID from metadata
        cur = self.conn.cursor()
        cur.execute("SELECT screen_id, biogrid_screen_id FROM screen WHERE version_id=%s", (self.version_id,))
        screens = cur.fetchall()
        screen_pmid = {}       # screen_id -> pmid
        pmid_cite = {}         # pmid -> citation text
        no_pmid = 0
        for sid, bid in screens:
            meta = metadata.get(hc.normalize_screen_id(bid))
            pmid = _first(meta, _PMID_FIELDS) if meta else None
            if not pmid:
                no_pmid += 1
                continue
            screen_pmid[int(sid)] = pmid
            pmid_cite.setdefault(pmid, _first(meta, _CITE_FIELDS) or "")
        logger.info(f"{len(screens)} screens: {len(screen_pmid)} with a PMID, {no_pmid} without; "
                    f"{len(pmid_cite)} distinct publications")
        if not screen_pmid:
            raise SystemExit("No screen resolved a PMID from metadata — check the SOURCE_ID field / $DATA_DIR")

        if self.dry_run:
            cur.execute("SELECT COUNT(*) FROM screen_gene_raw WHERE version_id=%s"
                        + ("" if self.include_all else " AND hit_flag=TRUE"), (self.version_id,))
            n_links = cur.fetchone()[0]
            print(f"[dry-run] would upsert {len(pmid_cite):,} publications and up to {n_links:,} "
                  f"fact_screen_gene_publication rows ({'all' if self.include_all else 'hits-only'}).")
            self.conn.close()
            return True

        # 1) upsert publications, get pmid -> publication_id
        pmids = sorted(pmid_cite.keys())
        long_ids = [p for p in pmids if len(p) > 20]
        if long_ids:
            logger.info(f"{len(long_ids)} source IDs > 20 chars (non-PubMed, e.g. DOIs), "
                        f"e.g. {long_ids[:3]} — needs migration 0015 (publication.pmid VARCHAR(100))")
        payload = [(p[:100], (pmid_cite[p] or None), self.version_id) for p in pmids]
        psycopg2.extras.execute_values(cur, """
            INSERT INTO publication (pmid, title, first_referenced_version_id)
            VALUES %s
            ON CONFLICT (pmid) DO UPDATE SET
                first_referenced_version_id = COALESCE(publication.first_referenced_version_id,
                                                       EXCLUDED.first_referenced_version_id)
        """, payload, page_size=5000)
        self.conn.commit()
        cur.execute("SELECT pmid, publication_id FROM publication WHERE pmid = ANY(%s)", (pmids,))
        pmid_pubid = {p: pid for p, pid in cur.fetchall()}
        screen_pubid = {sid: pmid_pubid[p] for sid, p in screen_pmid.items() if p in pmid_pubid}
        logger.info(f"Upserted {len(pmid_pubid):,} publications")

        # 2) stream screen_gene_raw -> fact_screen_gene_publication (screen's pub).
        # The read uses a DEDICATED connection: a server-side named cursor is
        # invalidated by a COMMIT on its own connection, and we commit each write
        # batch — so reads and writes must live on separate connections.
        where = "WHERE version_id=%s" + ("" if self.include_all else " AND hit_flag=TRUE")
        read_params = Config.get_psycopg2_params()
        read_params["sslmode"] = "require"
        read_conn = psycopg2.connect(**read_params)
        read_conn.autocommit = False
        c2 = read_conn.cursor(name="p2_links")
        c2.itersize = 200_000
        c2.execute(f"SELECT screen_id, gene_id, hit_flag FROM screen_gene_raw {where}", (self.version_id,))
        batch, total, skipped = [], 0, 0
        t0 = time.time()
        ins = self.conn.cursor()
        try:
            while True:
                rows = c2.fetchmany(200_000)
                if not rows:
                    break
                for sid, gid, hit in rows:
                    pub_id = screen_pubid.get(int(sid))
                    if pub_id is None:
                        skipped += 1
                        continue
                    batch.append((self.version_id, self.run_id, int(sid), int(gid), pub_id, bool(hit)))
                if batch:
                    psycopg2.extras.execute_values(ins, """
                        INSERT INTO fact_screen_gene_publication
                            (version_id, run_id, screen_id, gene_id, publication_id, hit_flag)
                        VALUES %s
                        ON CONFLICT (version_id, screen_id, gene_id, publication_id) DO NOTHING
                    """, batch, page_size=10000)
                    self.conn.commit()
                    total += len(batch)
                    logger.info(f"  {total:,} links inserted ({time.time()-t0:.0f}s)")
                    batch = []
        finally:
            c2.close()
            read_conn.close()
        logger.info(f"Done: {total:,} fact_screen_gene_publication rows "
                    f"({skipped:,} skipped: screen had no PMID)")
        print(f"P2 complete: {len(pmid_pubid):,} publications, {total:,} screen-gene-publication links "
              f"({'all' if self.include_all else 'hits-only'}).")
        self.conn.close()
        return True


def main():
    ap = argparse.ArgumentParser(description="P2: populate publication + fact_screen_gene_publication")
    ap.add_argument("--version", type=int, required=True)
    ap.add_argument("--all", action="store_true", dest="include_all",
                    help="store non-hit links too (default: hits-only)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO),
                        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    ok = PublicationPopulator(args.version, include_all=args.include_all, dry_run=args.dry_run).run()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

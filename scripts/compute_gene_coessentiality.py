"""
Gene-gene relationship discovery from BioGRID ORCS CRISPR screens.

Stage 1 (this file, `fetch` mode): pull mouse screen_gene_raw + screen/gene
dimension rows from the warehouse once, and cache them locally as parquet so
later iterations don't re-hit the remote RDS instance.

Stage 2 (`analyze` mode): join in per-screen SCORE.1_TYPE metadata from
screen_metadata_musculus.json, bucket-normalize scores by type, build a
gene x screen matrix, and compute a co-essentiality correlation network plus
a co-hit enrichment network.

Usage:
    python compute_gene_coessentiality.py fetch
    python compute_gene_coessentiality.py analyze
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2

from config import Config

CACHE_DIR = Path(__file__).parent / "cache"
SCREEN_GENE_CACHE = CACHE_DIR / "mouse_screen_gene_raw.parquet"
SCREEN_DIM_CACHE = CACHE_DIR / "mouse_screens.parquet"
GENE_DIM_CACHE = CACHE_DIR / "mouse_genes.parquet"


def fetch():
    CACHE_DIR.mkdir(exist_ok=True)
    conn = psycopg2.connect(**Config.get_psycopg2_params())
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT version_id FROM data_load_version "
            "WHERE organism = 'mus_musculus' AND status = 'valid' AND is_current = TRUE"
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError("No current, valid mus_musculus data_load_version found")
        version_id = row[0]
        print(f"Using mus_musculus version_id={version_id}")

        print("Pulling screen dimension rows...")
        screens = pd.read_sql(
            "SELECT screen_id, biogrid_screen_id FROM screen WHERE version_id = %(v)s",
            conn, params={"v": version_id},
        )
        screens.to_parquet(SCREEN_DIM_CACHE)
        print(f"  {len(screens)} screens -> {SCREEN_DIM_CACHE}")

        print("Pulling gene dimension rows...")
        genes = pd.read_sql(
            "SELECT gene_id, identifier_id, gene_symbol FROM gene WHERE version_id = %(v)s",
            conn, params={"v": version_id},
        )
        genes.to_parquet(GENE_DIM_CACHE)
        print(f"  {len(genes)} genes -> {GENE_DIM_CACHE}")

        print("Pulling screen_gene_raw rows (this is the big one, ~1.9M rows)...")
        screen_genes = pd.read_sql(
            "SELECT screen_id, gene_id, hit_flag, score_1 "
            "FROM screen_gene_raw WHERE version_id = %(v)s",
            conn, params={"v": version_id},
        )
        screen_genes.to_parquet(SCREEN_GENE_CACHE)
        print(f"  {len(screen_genes)} rows -> {SCREEN_GENE_CACHE}")
    finally:
        conn.close()


DOMAIN_DATA_DIR = Path(__file__).parent.parent / "Domain" / "Data"


def load_screen_metadata():
    with open(DOMAIN_DATA_DIR / "screen_metadata_musculus.json") as f:
        raw = json.load(f)
    rows = []
    for biogrid_screen_id, entries in raw.items():
        e = entries[0]
        rows.append({
            "biogrid_screen_id": biogrid_screen_id,
            "score_1_type": e.get("SCORE.1_TYPE"),
            "analysis": e.get("ANALYSIS"),
            "author": e.get("AUTHOR"),
            "cell_line": e.get("CELL_LINE"),
            "screen_rationale": e.get("SCREEN_RATIONALE"),
            "pmid": e.get("SOURCE_ID"),
        })
    return pd.DataFrame(rows)


# SCORE.1_TYPE values, bucketed by what kind of transform is valid.
# "effect": signed magnitude, comparable after within-screen percentile ranking.
# "significance": p-value-like, smaller = more significant, no direction.
# "unusable": raw/unprocessed, can't be compared across screens without a reference.
SCORE_TYPE_BUCKETS = {
    "Log2FC": "effect", "Log2": "effect", "Z-score": "effect", "pos Z-score": "effect",
    "MaGeCK Score": "effect", "MAGeCK neg score": "effect", "MAGeCK pos score": "effect",
    "STARS Score": "effect", "CasTLE Score": "effect", "CasTLE Effect": "effect",
    "CRISPR Score (CS)": "effect", "Beta Score": "effect", "CERES score": "effect",
    "Depletion-Enrichment (DE) score": "effect",
    "p-Value": "significance", "FDR": "significance", "Bayes Factor": "significance",
    "Rank": "rank",
    "Read counts": "unusable",
}


def analyze():
    print("Loading cached data...")
    screen_genes = pd.read_parquet(SCREEN_GENE_CACHE)
    screens = pd.read_parquet(SCREEN_DIM_CACHE)
    genes = pd.read_parquet(GENE_DIM_CACHE)
    metadata = load_screen_metadata()

    screens = screens.merge(metadata, on="biogrid_screen_id", how="left")
    screens["bucket"] = screens["score_1_type"].map(SCORE_TYPE_BUCKETS).fillna("unknown")
    print(screens["bucket"].value_counts())

    unusable = screens[screens["bucket"].isin(["unusable", "unknown"])]
    print(f"\nExcluding {len(unusable)} screens with unusable/unknown SCORE.1_TYPE:")
    print(unusable[["biogrid_screen_id", "score_1_type", "author"]].to_string(index=False))

    usable_screens = screens[screens["bucket"].isin(["effect", "rank"])]
    df = screen_genes.merge(usable_screens[["screen_id", "bucket"]], on="screen_id", how="inner")

    # Percentile-rank score_1 within each screen so screens are comparable regardless
    # of native scale (e.g. -7..2.4 CRISPR Score vs raw MAGeCK score magnitudes).
    # Sign is preserved by ranking ascending: most-depleted gene gets rank ~0.
    df["norm_score"] = df.groupby("screen_id")["score_1"].rank(pct=True)

    print(f"\n{len(df)} gene-screen rows across {df['screen_id'].nunique()} usable screens")

    CACHE_DIR.mkdir(exist_ok=True)
    df.to_parquet(CACHE_DIR / "normalized_screen_gene.parquet")
    print(f"Saved normalized data -> {CACHE_DIR / 'normalized_screen_gene.parquet'}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "fetch"
    if mode == "fetch":
        fetch()
    elif mode == "analyze":
        analyze()
    else:
        print(f"Unknown mode: {mode}. Use 'fetch' or 'analyze'.")
        sys.exit(1)

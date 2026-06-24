# RETICLE → AWS RDS — migration runtime metrics

**Date:** 2026-06-23 · **Target:** `reticle` schema on the team AWS RDS (PostgreSQL, us-east-1) ·
**Source:** local SQLite harmonized DB · **Client:** psycopg2 `COPY` in 250k-row chunks

## Environment

| | |
|---|---|
| Server | PostgreSQL 18.3 |
| `shared_buffers` | ~185 MB |
| `maintenance_work_mem` | 64 MB |
| Instance class | small (shared team instance) |
| DB size after my load | 15 GB (team warehouse ~13 GB + my ~2.3 GB) |

## Table load (COPY)

| table | rows | size | load time | throughput |
|---|---:|---:|---:|---:|
| `screen_metadata` | 2,157 | 1 MB | 0.8 s | 2,580 rows/s |
| `screen_metadata_curated` | 2,157 | <1 MB | 0.4 s | 6,071 rows/s |
| `harmonized_scores` | 28,237,649 | 2,156 MB | 249.6 s | **113,146 rows/s · 8.6 MB/s** |

28.2 M rows in ~4 min, ~2.1 GB on disk. Healthy and reproducible.

## Index build

| index | target | size | build time | temp used |
|---|---|---:|---:|---:|
| `idx_hs_gene` | `harmonized_scores (gene_symbol)` | 197 MB | 99.9 s | ~0.58 GB |
| `idx_smc` | `screen_metadata_curated (screen_id)` | 64 kB | <1 s | — |

The `gene_symbol` B-tree needs only ~0.58 GB of transient temp-sort space. Early
attempts failed with `No space left on device` when the shared instance had < ~0.6 GB
free; after the storage bump the build completes cleanly in ~100 s. Builds were run
with `temp_file_limit` + `statement_timeout` + TCP keepalives so a temp overrun fails
cleanly instead of destabilizing the shared instance.

## Query latency — `WHERE gene_symbol = ?`

| state | gene | rows | latency |
|---|---|---:|---:|
| no index (seq scan) | TP53 | 1,581 | 14,390 ms |
| no index (seq scan) | KRAS | 1,457 | 15,099 ms |
| **with `idx_hs_gene`** | TP53 | 1,581 | **302 ms** |
| **with `idx_hs_gene`** | KRAS | 1,457 | **171 ms** |
| **with `idx_hs_gene`** | EGFR | 1,503 | **185 ms** |

The index takes per-gene lookups from ~15 s (full scan of 28 M rows) to ~0.2 s — a
**~50–90×** speedup, which is what makes the interactive web app usable on RDS.

## Status

- **Data loaded:** ✅ 3 tables in the `reticle` schema, 28.2 M rows.
- **Indexed:** ✅ `idx_hs_gene`, `idx_smc` (both valid).
- **Prototype:** reads from RDS when `AWS_DB_HOST` is set in `.env`, else local SQLite.
- Optional follow-up: `idx_hs_screen (screen_id)` if screen-keyed queries are added
  (not needed for the current gene-centric app).

_Infra-level metrics (CPU, IOPS, FreeStorageSpace) live in CloudWatch and need
team-account access to capture; the above is measured from the DB connection._

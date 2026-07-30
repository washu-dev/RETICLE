# RETICLE → AWS RDS — migration runtime metrics

- **Run (UTC):** 2026-07-30T04:14:26+00:00 → 2026-07-30T04:21:37+00:00
- **Total wall time:** 430s
- **DB size after load:** 24 GB
- **Server:** PostgreSQL 18.3
- **Tuning:** shared_buffers=189376kB, maintenance_work_mem=64MB, effective_cache_size=378752kB

## Table load

| table | rows | size | load time | throughput |
|---|---:|---:|---:|---:|
| `screen_metadata` | 2,157 | 1 MB | 1s | 2,820 rows/s · 0.9 MB/s |
| `screen_metadata_curated` | 2,157 | 1 MB | 0s | 4,885 rows/s · 1.7 MB/s |
| `harmonized_scores` | 28,237,649 | 2159 MB | 242s | 116,766 rows/s · 8.9 MB/s |

## Index build

| index | target | build time |
|---|---|---:|
| `idx_hs_gene` | `harmonized_scores(gene_symbol)` | 125s |
| `idx_hs_screen` | `harmonized_scores(screen_id)` | 59s |
| `idx_smc` | `screen_metadata_curated(screen_id)` | 0s |

## Query latency — `WHERE gene_symbol = ?` (post-index)

| gene | rows | first query | warm |
|---|---:|---:|---:|
| TP53 | 1,581 | 356 ms | 46 ms |
| KRAS | 1,457 | 150 ms | 43 ms |
| EGFR | 1,503 | 210 ms | 40 ms |
| BRCA1 | 1,589 | 198 ms | 44 ms |
| MYC | 1,534 | 227 ms | 44 ms |

_Infra-level metrics (CPU, IOPS, FreeStorageSpace) live in CloudWatch and need team-account access; the above is captured from the DB connection._

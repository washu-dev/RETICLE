# RETICLE → AWS RDS — migration runtime metrics

- **Run (UTC):** 2026-06-24T19:32:19+00:00 → 2026-06-24T19:32:21+00:00
- **Total wall time:** 1s
- **DB size after load:** 15 GB
- **Server:** PostgreSQL 18.3
- **Tuning:** shared_buffers=189376kB, maintenance_work_mem=64MB, effective_cache_size=378752kB

## Table load

| table | rows | size | load time | throughput |
|---|---:|---:|---:|---:|
| `screen_metadata` | 2,157 | 1 MB | 0s | 5,771 rows/s · 1.8 MB/s |
| `screen_metadata_curated` | 2,157 | 1 MB | 0s | 8,842 rows/s · 3.1 MB/s |

_Infra-level metrics (CPU, IOPS, FreeStorageSpace) live in CloudWatch and need team-account access; the above is captured from the DB connection._

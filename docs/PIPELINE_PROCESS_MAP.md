# RETICLE — Pipeline Process Map (oriented run order)

**Purpose.** One canonical, ordered map of the end-to-end pipeline: raw BioGRID →
warehouse → harmonization → gene-relatedness. Each stage lists the **script**
(`scripts/`), the **SLURM job** (`slurm/`), its **inputs → outputs**, and its
**prerequisite**. Follow top-to-bottom. Every stage is versioned by
`data_load_version` (`version_id`) and idempotent/resumable unless noted.

> Breadcrumb: `scripts/README.md` and `slurm/README.md` both point here. Keep this
> file the single source of run-order truth; update it when a stage changes.

```
 RAW BioGRID (.tab + screen_metadata_*.json in $DATA_DIR)
        │
 (0) STAGE ─────────────► staging_screen, staging_screen_gene          [new version_id]
        │
 (1) DEDUP (GPU/CPU) ────► deduped CSVs in $STAGING_DIR
        │
 (2) LOAD ───────────────► screen, gene, screen_gene_raw, fact_screen_gene, dim_*
        │                   (2b) FINISH/REPAIR only if a run died mid-aggregate
        │
 (3) HARMONIZE ──────────► fact_screen_gene.{harmonized,percentile,robust_z}_score,
        │                   screen_harmonization
        │   ⇧ optional: DIRECTIONALITY MAPPER (LLM) → screen_directionality (DB); re-harmonize --apply-directionality
        │
 (4+) GENE-RELATEDNESS ──► fact_gene_pair + dim_gene_pair_* + insights
        (see design/gene_relatedness_design.md — deliverables D2…D13)
```

---

## Stage-by-stage

### (0) Stage — load raw screens into staging
- **Script:** `scripts/hpc_staging_loader.py` (parallel) / `scripts/staging_loader.py` (local)
- **SLURM:** `sbatch slurm/reticle-staging.sh <organism>`  (organism = `homo_sapiens` | `mus_musculus`)
- **In → Out:** raw `.tab` + `screen_metadata_*.json` (`$DATA_DIR`) → `staging_screen`, `staging_screen_gene`; **creates a new `version_id`**.
- **Note:** grab the new `version_id` from the log (or `maintenance.py --list-versions`) — every later stage takes it.

### (1) Dedup
- **Script:** `scripts/gpu_etl_dedup_only.py` (GPU/RAPIDS, CPU-pandas fallback)
- **SLURM:** `sbatch slurm/submit-etl-job-split.sh <version_id> --gpu`  (or `--both` to chain load)
- **In → Out:** `staging_*` → deduped CSVs in **`$STAGING_DIR`** (shared filesystem — must be visible to the CPU load node).

### (2) Load into the warehouse
- **Script:** `scripts/cpu_etl_load_only.py` (split) or `scripts/hpc_etl_pipeline.py` (unified)
- **SLURM:** `sbatch slurm/submit-etl-job-split.sh <version_id> --cpu`  (or unified `slurm/reticle-etl.sh`)
- **In → Out:** deduped CSVs / staging → `screen`, `gene`, `screen_gene_raw`, then aggregates `fact_screen_gene`, `dim_screen`, `dim_gene`.
- **Batched by screen, resumable** (skips screens already loaded / aggregated).

### (2b) Finish / repair — only if a load died before aggregates
- **Script:** `scripts/finish_etl_load.py` · **SLURM:** `sbatch slurm/reticle-etl-finish.sh <version_id>`
- **When:** `screen_gene_raw` populated but `fact_screen_gene`/`dim_*` empty (run stuck `running`). Batched fact build + dims; idempotent.

### (3) Harmonize  ← P1 of gene-relatedness (backlog #9)
- **Prerequisite migration:** `database/migrations/0012_fact_screen_gene_harmonization.sql` (applied once).
- **Script:** `scripts/harmonize_warehouse.py` (uses pure `scripts/harmonization_core.py`)
- **SLURM:** `sbatch slurm/reticle-harmonize.sh <version_id> [--dry-run] [--apply-directionality]`  **(CPU — I/O-bound, no GPU benefit)**
- **In → Out:** `screen_gene_raw` score values **+** `screen_metadata_*.json` score types →
  `fact_screen_gene.{harmonized_score, percentile_score, robust_z_score}` + `screen_harmonization` (per-screen coverage/basis/direction).
- **Resumable:** skips screens already in `screen_harmonization`. Start with `--dry-run` (basis distribution, no writes).

#### (3-opt) Directionality mapper — occasional, DB-backed (warehouse-native)
- **Script:** `scripts/directionality_mapper.py` · **SLURM:** `sbatch slurm/reticle-directionality.sh <version_id>` (LLM via `scripts/llm_gateway`, config-driven model). Targets from `screen_harmonization`, metadata from `$DATA_DIR`, output to the DB — no JSON, no prototype paths.
- **Produces:** rows in **`screen_directionality`** (per `version_id, screen_id`): `mode`/`sign`/columns/`confidence`/`status` (`auto` | `needs_review` | `binary_only`). Versioned + auditable in the DB (migration `0013`).
- **Order:** run **after** a deterministic `harmonize_warehouse.py` pass has tagged ambiguous screens, then re-run **`harmonize_warehouse.py --apply-directionality`** to apply the `status='auto'` decisions. Only worth running if there ARE ambiguous screens and you choose to *rescue* them (vs exclude). `needs_review` rows await human adjudication (`SELECT … WHERE status='needs_review'`).
- **Invariant:** the override sign is FINAL (perturbation folded in) — harmonize does NOT re-apply `perturbation_mult` to overridden screens.
- **Invariant:** the override sign is FINAL (perturbation already folded in) — `harmonize_warehouse` does **not** re-apply `perturbation_mult` to overridden screens.

### (4+) Gene-relatedness scorecard
- **Design:** `design/gene_relatedness_design.md` (+ `_schema.sql`, `_architecture.drawio`, `_erd.drawio`).
- **Order (D2→D13):** profiler → what-if config → candidate generation → co-essentiality (D5, **GPU**) + co-hit + co-citation + contextual + residual/novelty (D5b) → roll-up + BH-FDR → `fact_gene_pair` → PubMed→S3 → Claude insight agent → API/UI.
- **Prereqs:** P1 harmonize (this file, stage 3) · P2 populate `fact_screen_gene_publication` · P3 capture screen-context + PMIDs at staging.

---

## Cross-cutting run conventions
- **Account/partition:** set `SBATCH_ACCOUNT` (and `SBATCH_PARTITION` if needed) as env vars — never hardcoded in `#SBATCH`.
- **Credentials:** `~/.pgpass` (mode 600). **`$DATA_DIR`** must hold `screen_metadata_*.json`; **`$STAGING_DIR`** must be shared storage for the dedup→load handoff.
- **Versioning:** one `version_id` threads every stage; `maintenance.py --list-versions` to find it.
- **GPU vs CPU:** only **dedup (1)** and **co-essentiality (D5)** benefit from GPU. Staging, load, finish, and **harmonize are CPU** (I/O-bound).

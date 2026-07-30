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
 (4) PROFILE (D2) ───────► relatedness_profile  [data shape + threshold→projected-pairs/cost curves]
        │                   (cheap, CPU; gates the what-if config before D5 pays for compute)
        │
 (5) CONFIG (D3) ────────► relatedness_config  [recommend→accept thresholds+budget; server-side cost gate]
        │                   (login-node, DB-only; produces the ACCEPTED config D4/D5 read)
        │
 (6) CO-ESSENTIALITY(D5)─► fact_gene_pair.coess_*  [tail-restricted Spearman ρ, GPU; |ρ|-floor + top-K]
        │                   (--histogram to pick the cut, then --build)
        │
 (7+) GENE-RELATEDNESS ──► + co-hit/co-citation/contextual/novelty channels + roll-up + insights
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

### (4) Profiler  ← D2 of gene-relatedness
- **Schema:** migration `0014` (`relatedness_profile`, `relatedness_config`, `fact_gene_pair`, …) — apply before running.
- **Script:** `scripts/profile_relatedness.py` · **SLURM:** `sbatch slurm/reticle-profile.sh <version_id> [--dry-run] [--sample-size N] [--seed N]`  **(CPU — exact sparse Hᵀ·H + sampled co-ess; no n×n, no GPU)**
- **Produces:** one `relatedness_profile` snapshot: data shape (screen counts, coverage dist, selective-gene count, pan-essential/pan-inert drops) + threshold→(projected pairs, cost) curves — **exact** co-hit/co-citation, **sampled+CI** co-essentiality (seed recorded → reproducible).
- **Order:** run **after** P1 harmonize (needs `screen_harmonization` + `fact_screen_gene.percentile_score`); errors clearly if harmonize hasn't run. Reads only the warehouse — **no `$DATA_DIR` needed**. Gates D3 (pick thresholds/budget → `relatedness_config`) before D4/D5 pay for real compute.

### (5) Config  ← D3 of gene-relatedness
- **Script:** `scripts/configure_relatedness.py`  **(login-node, DB-only — no SLURM, no scipy; runs in seconds)**
- **Actions:** `--list-profiles` / `--list-configs`; `--recommend --max-pairs N` (pick most-inclusive thresholds off the profile curves that fit the budget → writes a **draft** `relatedness_config`); `--accept --config-id N` (re-validate projected cost **server-side** against the stored profile, then flip draft→**accepted**). `--recommend --accept` does both.
- **Produces:** an **accepted** `relatedness_config` (thresholds + `compute_budget` + `projected_pairs`/cost, per `version × organism × label`; A/B configs coexist). This is the row **D4/D5 read**.
- **Guardrail (OWASP A04):** the budget check on `--accept` is server-authoritative — thresholds that exceed `compute_budget.max_pairs` are rejected (re-recommend tighter or set `compute_mode=ANN_TOPK`).
- **Note:** `tier_cuts` (Strong/Moderate/Weak) are seeded defaults here (the profiler measures volume, not the ρ distribution) and get **recalibrated post-D5** from the real effect-size distribution.

### (6) Co-essentiality  ← D5 (primary channel, Channel 1)
- **Script:** `scripts/compute_coessentiality.py` (shared selective/tail logic in `scripts/relatedness_core.py`) · **SLURM:** `sbatch slurm/reticle-coessentiality.sh <version> …`  **(GPU — masked-GEMM tail-restricted Spearman; `--cpu` fallback)**
- **Two passes:** `--histogram` reports the **real** |ρ| distribution + true tested-pair count (pick the cut, recalibrate `tier_cuts`); `--build --rho-min X --top-k K` stores pairs clearing **both** gates into `fact_gene_pair.coess_*` with BH-FDR (`min_support` = min co-tail screens).
- **Prereq chain:** P1 harmonize → D2 profile → **D3 accepted config** → D5. Reads only the warehouse (no `$DATA_DIR`); organism-partitioned (never cross-organism).
- **Note:** first build leaves `dim_gene_pair_screen` evidence rows unpopulated (`--with-evidence` is a deferred heavy pass); `relatedness_tier` is provisionally the co-ess tier until D9 rolls up all channels.

### (6b) Co-hit  ← D6 (Channel 2)
- **Script:** `scripts/compute_cohit.py` · **SLURM:** `sbatch slurm/reticle-cohit.sh <version> --config-id N`  **(CPU — exact sparse Hᵀ·H, no GPU)**
- **Produces:** `fact_gene_pair.cohit_*` — support `n11`, Jaccard, PMI, marginals (`a_hits`/`b_hits`/`screens_total`), one-sided hypergeometric (= Fisher) p → BH-FDR, tier. Upsert composes with D5 (leaves `coess_*` intact).
- **Runs anytime after** an accepted config exists; independent of D5 (can run in parallel). Marginal universe `N` = total screens in the version (documented approximation).

### (6c) Roll-up  ← D9 (cross-channel combine)
- **Script:** `scripts/rollup_relatedness.py`  **(login-node, DB-only — single set-based UPDATE; no GPU/SLURM)**
- **Produces:** the unified header on `fact_gene_pair` — `relatedness_score` (weighted, support-renormalized over present base channels; co-ess weighted highest), `relatedness_tier`, `evidence_channels` / `evidence_channel_count`, `total_support`, `min_fdr`.
- **Runs after** any channel driver (D5/D6/…). Idempotent — re-run whenever a channel adds/updates columns (D7/D8 slot in automatically). Weights + overall cuts are config-driven (`thresholds.channel_weights`, `tier_cuts.overall`).

### (6d) Co-citation  ← D7 (Channel 3) — needs P2 first
- **P2 populate:** `scripts/populate_publications.py` · **SLURM:** `sbatch slurm/reticle-publications.sh <version>` **(CPU, needs `$DATA_DIR`)** — reads each screen's PMID (`SOURCE_ID`) from the metadata JSON, upserts `publication`, and fills `fact_screen_gene_publication` (**hits-only** by default; `--all` for non-hits too). The ETL's `build_fact_screen_gene_publication()` is a placeholder — this replaces it.
- **D7 compute:** `scripts/compute_cocitation.py` · **SLURM:** `sbatch slurm/reticle-cocitation.sh <version> --config-id N` **(CPU — sparse Pᵀ·P over gene×publication hit sets)** — shared-pub support, Jaccard, PMI, hypergeometric p → BH-FDR into `fact_gene_pair.cocite_*` (tiers on PMI). Upsert composes with coess/cohit.
- **Order:** P2 → D7 → re-run D9 roll-up (folds co-citation into `relatedness_tier`/`evidence_channels`).

### (7+) Gene-relatedness scorecard
- **Design:** `design/gene_relatedness_design.md` (+ `_schema.sql`, `_architecture.drawio`, `_erd.drawio`).
- **Order (D2→D13):** profiler (stage 4 above) → what-if config → candidate generation → co-essentiality (D5, **GPU**) + co-hit + co-citation + contextual + residual/novelty (D5b) → roll-up + BH-FDR → `fact_gene_pair` → PubMed→S3 → Claude insight agent → API/UI.
- **Prereqs:** P1 harmonize (this file, stage 3) · P2 populate `fact_screen_gene_publication` · P3 capture screen-context + PMIDs at staging.

---

## Cross-cutting run conventions
- **Account/partition:** set `SBATCH_ACCOUNT` (and `SBATCH_PARTITION` if needed) as env vars — never hardcoded in `#SBATCH`.
- **Credentials:** `~/.pgpass` (mode 600). **`$DATA_DIR`** must hold `screen_metadata_*.json`; **`$STAGING_DIR`** must be shared storage for the dedup→load handoff.
- **Versioning:** one `version_id` threads every stage; `maintenance.py --list-versions` to find it.
- **GPU vs CPU:** only **dedup (1)** and **co-essentiality (6/D5)** benefit from GPU (`--gres=gpu:1 --partition=general-gpu`; provision `~/.rapids-gpu-venv` from the login node). Staging, load, finish, **harmonize**, **profiler (4)**, and **config (5)** are CPU.

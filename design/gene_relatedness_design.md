# RETICLE — CRISPR Gene-Relatedness Scorecard — Technical Design

**Status:** Design (architect hand-off to full-stack-developer)
**Scope:** New subsystem in the RETICLE warehouse (`reticle_biogrid`, PostgreSQL on AWS RDS, `public` schema).
**Companion artifacts (this folder):**
- `gene_relatedness_architecture.drawio` — end-to-end pipeline / data-flow.
- `gene_relatedness_erd.drawio` — entity-relationship diagram (new + referenced tables).
- `gene_relatedness_schema.sql` — DDL draft (turned into numbered migrations at implementation time).

> This document supersedes the exploratory `gene_relatedness_process.md` and
> `gene_relatedness_process_beta_aligned.md` for the **scorecard** product. Those
> remain useful as a validation harness / research appendix; where they disagree,
> the four locked decisions in §1 govern.

---

## 1. Overview & Goal

### 1.1 Goal
Measure **gene–gene relatedness observed in CRISPR screens** and expose it as a
per-gene-pair **scorecard**. Relatedness is evidenced across four channels
(co-essentiality, co-hit enrichment, co-citation, contextual convergence), each
graded on three orthogonal dimensions (effect size, support, significance), rolled
up into Strong / Moderate / Weak tiers, and enriched with an LLM-generated,
**cited** insight answering three epistemic questions per gene and per pair.

**This is not an n×n cartesian product.** Candidate pairs are *evidence-generated*
(they must share screens, hits, or publications) and *thresholded* (they must
clear a minimum support). Pairs below support are **not stored** — they are logged
as dropped so a run is reproducible and auditable.

### 1.2 The four locked design decisions (govern everything below)
1. **Home = `public` schema in `reticle_biogrid`, versioned** exactly like the
   existing warehouse (`version_id` / `run_id` lineage, `is_current` flags,
   `v_current_*` views).
2. **Thresholds are empirical, never hardcoded.** A cheap **profiler** projects
   candidate-pair volume + compute cost per threshold *without* computing n×n, a
   **what-if** loop recommends thresholds within a compute budget, the user
   accepts/modifies, and the accepted config **triggers** the metric build.
   Metric computation is **deterministic (exact ρ)** on a prefiltered
   selective-gene space; approximate top-K (ANN) pruning is a **fallback only**
   when the profiler flags the pair space exceeds budget.
3. **Versioning = per `(data_load_version × config)`.** `relatedness_profile` and
   `relatedness_config` are first-class objects; multiple what-if results coexist
   and are **A/B comparable**.
4. **LLM = Claude via the WashU Secure API** (Opus / Sonnet / Haiku now, Fable
   soon), keys in **AWS Secrets Manager**, behind a **provider-agnostic seam**.
   Tiered: Opus for deep synthesis, Sonnet default, Haiku for cheap sub-steps.

### 1.3 Glossary
| Term | Meaning |
|---|---|
| **Harmonized score** | Per-(screen,gene) value on a unified biological axis: **+** = knockout protective/enriching, **−** = gene essential/depleting. Produced by `harmonize_scores.py`, ported into `fact_screen_gene` (P1). |
| **Percentile score** | Within-screen rank of the harmonized score, in **[−1, +1]** over *measured* genes; −1 = most essential, +1 = most enriched. NULL if unmeasured. |
| **Robust z-score** | Median/MAD-standardized harmonized score (outlier-resistant). |
| **Coverage type** | Per screen: **FULL** (genome-wide, continuous scores → co-essentiality) or **HIT_ONLY** (hits only → binary co-hit). |
| **Is directional** | Screen's sign came from a directional metric (vs inferred from selection type). |
| **Selective gene** | A gene that is neither pan-essential (essential in ~all screens) nor pan-inert (never moves). Only selective genes carry relatedness signal — used to shrink the pair space quadratically. |
| **Tail-restricted correlation** | Spearman ρ computed only over observations in the *tails* of each gene's percentile profile; the mid-distribution is noise. |
| **Support** | Breadth of evidence: # shared FULL screens (co-ess), # co-hit screens (co-hit), # shared publications (co-citation). |
| **BH-FDR** | Benjamini–Hochberg false-discovery-rate correction across the **whole pair space** tested in a run. |
| **Context** | An assay domain / condition / cell line bucket (e.g. "oxidative stress") from screen metadata; lets an edge be conditioned. |
| **Config** | An accepted set of empirical thresholds + compute budget (`relatedness_config`); the unit of A/B comparison. |
| **Profile** | A profiler snapshot of data shape + threshold→pair-count/cost projection curves (`relatedness_profile`). |
| **PMI** | Pointwise mutual information — co-occurrence lift over chance. |
| **Dual grounding** | Every LLM claim cites ≥1 external PMID **and/or** an internal evidence ref (a warehouse row). |

---

## 2. Functional Requirements

- **FR-1 — Candidate generation, not cartesian.** The system SHALL generate
  candidate pairs only from shared evidence (co-measured FULL screens, co-hit
  HIT_ONLY screens, shared publications) and SHALL never materialize the n×n grid.
- **FR-2 — Four base relatedness channels.** For each stored pair the system SHALL
  compute, where evidence exists: (1) co-essentiality, (2) co-hit enrichment,
  (3) co-citation, (4) contextual convergence (§5).
- **FR-2b — Fifth novelty / mechanistic-divergence channel (additive).** For each
  stored pair with shared FULL-coverage evidence the system SHALL additionally
  compute a **residual co-essentiality** channel: correlate the two genes'
  *residual* percentile profiles (observed − expected, expectation from a light
  additive model over gene/screen/context covariates — §6.6), with the same
  effect / support / significance / tier structure and BH-FDR as the base channels,
  plus a `novelty_score` contrasting residual vs raw ρ. This SHALL NOT replace or
  alter the four base channels or the stored `fact_gene_pair` scorecard — it is
  additive attribute columns on the same header.
- **FR-2c — Anti-β flag.** The system SHALL set `is_antagonistic` when a pair's raw
  or residual ρ is strongly negative (antagonistic co-dependency).
- **FR-2d — Buffering candidate (hypothesis, not a measured edge).** The system MAY
  set `is_buffering_candidate` with a `buffering_basis` when a pair is (a)
  individually near-inert, (b) paralogs/homologs (external homology source), and
  (c) complementary/anti-correlated across contexts. This SHALL be labeled a
  hypothesis testable by combinatorial KO — single-gene ORCS screens cannot measure
  true buffering (§6.6) — and SHALL NOT be presented as a measured relatedness edge.
- **FR-3 — Three dimensions per channel.** Each channel SHALL carry effect size,
  support, and significance (p-value + BH-FDR), and a per-channel tier.
- **FR-4 — Roll-up.** The system SHALL roll channels up into an overall
  Strong / Moderate / Weak `relatedness_tier`, an `evidence_channels` summary, and
  `total_support`.
- **FR-5 — Support floor.** Pairs below the config's minimum support SHALL NOT be
  stored; each dropped pair (or dropped bucket) SHALL be counted in the run audit
  with the reason.
- **FR-6 — Organism isolation.** A pair SHALL never cross organisms; evidence SHALL
  come only from screens measuring both genes.
- **FR-7 — Empirical thresholds.** The profiler SHALL project pair volume + compute
  cost per threshold without computing n×n; the what-if loop SHALL let the user see
  projected pair count / cost live and accept or modify (§6).
- **FR-8 — Config-triggered build.** Accepting a `relatedness_config` SHALL trigger
  the deterministic metric build for that `(version, config)`.
- **FR-9 — A/B coexistence.** Multiple configs per data load SHALL coexist and be
  independently queryable and comparable.
- **FR-10 — PubMed prefetch.** For each screen the system SHALL resolve cited PMIDs,
  fetch each once via NCBI efetch/PMC, store it in S3
  (`s3://<bucket>/pubmed/<pmid>.json`), and cache facets in `dim_pubmed_article`.
- **FR-11 — Insight agent.** On demand, for each gene AND each gene-pair, the system
  SHALL produce a **structured, cited** answer to three questions: (1) established
  knowledge, (2) recognized knowledge gaps, (3) reducible/open uncertainty.
- **FR-12 — Citation contract.** Every persisted claim SHALL cite ≥1 external PMID
  and/or an internal evidence ref; unsupported claims SHALL be dropped/flagged and
  SHALL NOT be stored as `approved`.
- **FR-13 — Human curation.** A researcher SHALL be able to edit/accept/reject
  individual claims; insights SHALL be versioned with `user_annotation`,
  `annotated_by`, and `status` (draft/edited/approved/rejected).
- **FR-14 — Provenance drill-down.** Every scorecard number SHALL resolve to its
  backing rows (`dim_gene_pair_screen` / `_context` / `_publication`).

## 3. Non-Functional Requirements

- **NFR-1 Reproducibility.** A `(version, config)` build SHALL be deterministic:
  same inputs + same config + fixed random seed (for the profiler sample) → same
  stored pairs and scores. The seed is recorded in `relatedness_profile.snapshot`.
- **NFR-2 Bounded compute.** No run SHALL exceed the config's `compute_budget`; the
  profiler is the gate. The exact path is preferred; ANN top-K is the only
  approximation and only when the profiler flags budget overflow.
- **NFR-3 Idempotency / resumability.** Stages SHALL be re-runnable without
  duplicate rows (UNIQUE constraints + `is_current` supersede-on-rebuild). Long
  stages (metric compute, PubMed fetch, insight gen) SHALL checkpoint per
  screen-tile / per PMID / per entity so a failed run resumes, not restarts.
- **NFR-4 Organism isolation.** Enforced structurally: candidate generation is
  partitioned by `organism`; `fact_gene_pair.organism` is non-null; both genes are
  drawn from the same organism partition.
- **NFR-5 FDR control.** Significance SHALL be BH-corrected across the entire pair
  space of a run (per channel), not per pair; the pair-space size used for the
  correction is recorded in the run audit.
- **NFR-6 Data governance / secrets.** LLM API keys SHALL live only in AWS Secrets
  Manager and be injected as runtime env vars (12-factor III); no key in code,
  config files, or logs. PubMed content SHALL be stored server-side (S3), never
  embedded in prompts beyond the retrieved passages needed for grounding.
- **NFR-7 Auditability / provenance.** Every stage SHALL write an `etl_audit_log`
  row (rows in/out, dropped counts, duration). Every claim SHALL be traceable to a
  PMID (via `dim_pubmed_article.s3_uri`) and/or a warehouse row.
- **NFR-8 Scalability (GPU vs sparse).** Binary channels (co-hit, co-citation) use
  **sparse** integer products (Hᵀ·H over hit/pub sets) — exact and cheap.
  Co-essentiality uses **tiled/thresholded GEMM** over the selective-gene percentile
  matrix, GPU-accelerated when available (reuse of the existing HPC/SLURM GPU ETL
  path), CPU-tiled otherwise. Memory is bounded by tiling; no full dense n×n
  materialization.

---

## 4. Architecture — Pipeline stages 0–6

See `gene_relatedness_architecture.drawio`. Stages are versioned by
`(data_load_version, run_id, config_id)` and each emits an `etl_audit_log` row.

- **Stage 0 — Prerequisites / staging (P1–P3).**
  - P1: port `harmonize_scores.py` per-(screen,gene) outputs into
    `fact_screen_gene.{harmonized_score, percentile_score, robust_z_score, is_hit}`
    (backlog #9–#12).
  - P2: populate `fact_screen_gene_publication` (a 0-row stub today) with
    screen→PMID→gene links.
  - P3: materialize `dim_screen_context` (assay domain / condition / cell line /
    coverage type) and `dim_pubmed_article` cited-PMID rows during staging.
- **Stage 1 — Profiler (cheap).** Reads the harmonized facts + context, captures
  data shape, and computes threshold→(projected pairs, projected cost) curves.
  Co-hit / co-citation projections are **exact** via sparse Hᵀ·H over hit / pub
  sets; co-essentiality volume is **estimated** from a random sample of selective
  genes with a confidence band. Writes `relatedness_profile`.
- **Stage 2 — What-if config.** Recommends thresholds within the user's compute
  budget; the user sees projected pair count / cost live and accepts or modifies.
  An accepted `relatedness_config` (status → `accepted`) **triggers** Stage 3.
- **Stage 3 — Candidate generation.** Builds the evidence-generated candidate set
  (union of co-measured selective-gene pairs in shared FULL screens, co-hit pairs,
  co-cited pairs), partitioned by organism, prefiltered to selective genes
  (drop pan-essential & pan-inert). Chooses **exact** vs **ANN top-K** per the
  profiler's budget flag.
- **Stage 4 — Metric computation (4 base channels + Channel 5).** Deterministic.
  Co-essentiality via tiled/thresholded GEMM (tail-restricted |ρ|); co-hit via
  sparse Jaccard/PMI/Fisher; co-citation via sparse PMI; contextual convergence via
  co-hit stratified by `context_key`. **Stage 4b (D5b) — novelty / mechanistic
  divergence** branches off the co-essentiality matrix in parallel: fit the light
  additive expectation model, residualize, correlate residual profiles, and set the
  anti-β / buffering-candidate flags (§6.6). Emits per-channel effect/support/
  significance into staging buffers + evidence rows into `dim_gene_pair_screen`
  (incl. residuals), `_context`, `_publication`, and the fitted params into
  `dim_gene_expectation_model`.
- **Stage 5 — Roll-up & FDR.** BH-FDR per channel across the whole pair space;
  per-channel and overall tiering; support-floor drop (logged); write
  `fact_gene_pair` (+ mark prior config build `is_current = FALSE` if superseded).
- **Stage 6 — Insight & surfacing.** On-demand LLM insight agent (per gene / per
  pair) with the three-question cited output and human curation; API + UI surface
  the scorecard, evidence drill-down, and insights.

---

## 5. Data Model

Star schema in `public`, keyed by `(version_id, config_id)` for the pair fact.
See `gene_relatedness_erd.drawio` and `gene_relatedness_schema.sql`.

**Header:** `fact_gene_pair` — one row per candidate pair that cleared support, per
`(version_id, config_id, gene_a_id < gene_b_id)`, `organism` non-null. Four metric
attribute-groups (each effect / support / significance / tier) + overall roll-up.

**Evidence dimensions (provenance / drill-down):**
- `dim_gene_pair_screen` — per pair × screen: `both_measured`, `both_hit`,
  `gene_a_percentile`, `gene_b_percentile`, `in_tail`, `context_key`.
- `dim_gene_pair_context` — per pair × context: `context_type`, `context_value`,
  `cohit_count`, `jaccard`, `pmi`, `fisher_p`, `fdr`, `tier`.
- `dim_gene_pair_publication` — per pair × PMID: `publication_id`, `pmid`,
  `screen_ids`, `s3_uri`.

**Context / cache:**
- `dim_screen_context` — per (version, screen): assay/condition/cell-line/coverage.
- `dim_pubmed_article` — per PMID cache: `pmid` PK, `s3_uri`, title/year/journal/
  abstract, `fetched_at`, `fetch_status`.

**Config / provenance:** `relatedness_config`, `relatedness_profile`,
`dim_gene_expectation_model` (Channel-5 fitted expectation params per
`(version_id, config_id)`).

**Channel 5 (additive) storage.** The novelty channel adds columns to the existing
`fact_gene_pair` header (`resid_rho`, `resid_effect`, `resid_support`,
`resid_p_value`, `resid_fdr`, `resid_tier`, `novelty_score`, `is_antagonistic`,
`is_buffering_candidate`, `buffering_basis`) and residual columns to
`dim_gene_pair_screen` (`gene_a_residual`, `gene_b_residual`) — no change to the
four base channels' columns.

**Insight:** `dim_gene_insight` (per gene), `dim_gene_pair_insight` (per pair) —
identical 3-section structured-claims JSON + citations + internal_refs + model +
curation fields + `version`.

**Referenced existing tables (FK targets):** `data_load_version`,
`etl_pipeline_run`, `screen`, `gene`, `publication`, `fact_screen_gene`
(extended by P1), `fact_screen_gene_publication` (populated by P2).

> **FK reality note.** Existing derived warehouse tables enforce only
> `version_id`/`run_id` FKs (mostly `ON DELETE CASCADE`), not surrogate
> `screen_id`/`gene_id` FKs. The DDL draft declares `screen_id`/`gene_id` FKs for
> ERD clarity; implementation MAY drop them to match prod load performance, but
> MUST keep the `version_id`/`run_id`/`config_id` FKs — they carry lineage and the
> cascade semantics that make a version/config purge correct.

---

## 6. The Algorithms (four base channels + a fifth novelty channel)

All channels: **never cross organism**; evidence only from screens measuring both
genes; support floor from `relatedness_config.thresholds`; significance BH-FDR
across the whole pair space. §6.1–6.4 are the four **base** channels; §6.6 is the
additive **novelty / mechanistic-divergence** channel (Channel 5).

### 6.1 Co-essentiality (primary channel) — continuous, FULL-coverage
- **Input:** harmonized `percentile_score` profiles of the two genes across their
  **shared FULL-coverage** screens (`fact_screen_gene`, P1).
- **Formula:** **tail-restricted Spearman ρ** — restrict to observations in the
  tails of each profile (mid-distribution is noise; tail window per config
  `tail_percentile`), then Spearman correlation; store **|ρ|** as effect and signed
  `coess_rho` (negative ρ = anti-correlation, still informative).
- **Effect:** `|ρ|`. **Support:** # shared FULL screens used. **Significance:**
  permutation / asymptotic p → BH-FDR.
- **Compute:** tiled/thresholded GEMM over the selective-gene percentile matrix;
  GPU when available, CPU-tiled otherwise; ANN top-K only on budget overflow.

### 6.2 Co-hit enrichment — binary, HIT_ONLY (and hit sets generally)
- **Input:** per-screen hit sets (`is_hit`) over screens where both genes are
  eligible.
- **Formula:** **Jaccard** = |A∩B| / |A∪B|; **PMI** = log( P(A,B) / (P(A)·P(B)) );
  **Fisher's exact** on the 2×2 co-hit contingency table.
- **Effect:** Jaccard + PMI. **Support:** # screens both are hits (+ marginals
  `a_hits`, `b_hits`, `screens_total` for PMI/Fisher). **Significance:** Fisher p →
  BH-FDR.
- **Compute:** sparse Hᵀ·H (integer co-occurrence) — exact, cheap.

### 6.3 Co-citation — publication co-occurrence (cold-start rescue)
- **Input:** shared publications via `fact_screen_gene_publication` → `publication`
  → `dim_pubmed_article`.
- **Formula:** **PMI** and **Jaccard** over the genes' publication sets.
- **Effect:** PMI + Jaccard. **Support:** # shared publications (+ marginals).
  **Significance:** hypergeometric / PMI-significance p → BH-FDR.
- **Value:** rescues genes with little/no screen overlap (cold start).

### 6.4 Contextual convergence — co-hit stratified by context
- **Input:** co-hit evidence bucketed by `context_key` from `dim_screen_context`
  (assay domain / condition / cell line / cell type / phenotype).
- **Formula:** per-context Jaccard/PMI/Fisher (as §6.2) within each context bucket
  clearing support.
- **Effect / support / significance:** per context (`dim_gene_pair_context`), rolled
  into `fact_gene_pair.context_*` (strongest context = `context_best_key`).
- **Value:** lets an edge state "related **under oxidative stress**".

### 6.6 Novelty / mechanistic-divergence channel (Channel 5 — additive)
**Theme: "find genes that break the same rule."** Plain co-essentiality (§6.1)
surfaces genes that move *together* — but much of that co-movement is explained by
shared covariates (both are broadly essential, both were run in the same modality /
library / cell line). Channel 5 removes the explainable part and correlates what is
left, surfacing convergence a plain correlation network misses. It **reuses
Channel-1's gene×screen harmonized-percentile matrix (D5)** and **P3 context
metadata** (`dim_screen_context`); no new raw data.

**(1) Residual co-essentiality — the primary new signal (fully computable).**
- **Expected value.** From the same percentile matrix, fit an **expected percentile**
  `E[g,i]` from covariates: **gene baseline** (global essentiality), **screen
  baseline**, and **context-group means** (modality, library, cell_line,
  assay_domain — from `dim_screen_context`). Use a **light additive / median-polish /
  mixed-effects** model. **Explicitly NOT a Gaussian process** — the GP is the
  beta-aligned observation model we are deliberately *not* adopting here; this
  channel is a cheap additive residualization bolted onto the existing stored
  scorecard, not a switch to the GP/observation architecture. The fitted parameters
  are persisted per `(version_id, config_id)` in `dim_gene_expectation_model` for
  provenance and reproducibility.
- **Residual.** `R[g,i] = observed[g,i] − E[g,i]`, stored per pair×screen on
  `dim_gene_pair_screen.gene_a_residual` / `gene_b_residual`.
- **Effect.** `resid_effect = |resid_rho|` where `resid_rho` is the **tail-restricted
  Spearman ρ of the residual profiles** over shared FULL screens (same tail window
  as §6.1). **Support:** `resid_support` = # shared FULL screens. **Significance:**
  `resid_p_value` → `resid_fdr` (BH across the pair space). **Tier:** `resid_tier`
  via the config's empirical `tier_cuts`, exactly like the other channels.
- **novelty_score.** A contrast of `resid_rho` vs `coess_rho` (raw): a pair with
  **high residual correlation but low context-explained overlap** is convergence a
  plain co-essentiality network would miss and scores high; a pair whose correlation
  vanishes after residualization scores low (it was "explained by the rule").

**(2) Anti-β (antagonistic) — cheap flag.** `is_antagonistic = TRUE` when raw or
residual ρ is strongly negative — the genes move *oppositely* (antagonistic
co-dependency), which a magnitude-only network hides.

**(3) Buffering candidate — HONEST hypothesis flag, NOT a measured edge.**
> **Data limitation (stated plainly).** BioGRID ORCS is single-gene knockout data.
> True genetic buffering (redundancy) requires **combinatorial KO** or **LOF↔GOF
> contrasts** to observe; a single-gene screen *cannot measure it*. We therefore do
> **not** emit a measured buffering edge.

Instead, `is_buffering_candidate = TRUE` flags a pair that is (a) individually
**near-inert** (both genes rarely move alone), (b) **paralogs/homologs** per an
external homology source, and (c) **complementary / anti-correlated across
contexts**; `buffering_basis` records which of (a)/(b)/(c) fired. It is surfaced and
stored explicitly as a **hypothesis, testable by combinatorial KO** — never as a
confirmed relatedness edge.

### 6.7 Tiering & roll-up
Each channel maps (effect, support, FDR) → **Strong / Moderate / Weak / NULL** via
the config's `tier_cuts` (empirical, from the profiler — *not* hardcoded). The
overall `relatedness_tier` combines the four base channels (co-essentiality weighted
highest as the primary channel); the Channel-5 `resid_tier` / `novelty_score` and
the `is_antagonistic` / `is_buffering_candidate` flags are recorded alongside and
contribute to `evidence_channels` but do **not** dilute the base roll-up (novelty is
surfaced as its own facet so a "novel" edge is distinguishable from a strong plain
one). Sets `evidence_channels` / `evidence_channel_count` / `total_support` /
`min_fdr`. Pairs whose every channel is below support are dropped (logged).

---

## 7. The What-If Simulation Loop

**profiler → recommend → accept → trigger.** (Locked decision #2.)

1. **Profiler (cheap, exact where it can be).** Snapshot data shape (screen counts,
   coverage distribution, selective-gene count, pan-essential/pan-inert drops) and
   build **threshold → (projected pairs, projected cost)** curves:
   - Co-hit / co-citation projections are **EXACT** — sparse Hᵀ·H over hit / pub
     sets directly yields the co-occurrence count distribution per threshold.
   - Co-essentiality volume is **ESTIMATED** from a random sample of selective genes
     with a **confidence band** (`ci_low`/`ci_high`), *without* the n×n product.
   - Writes `relatedness_profile.snapshot` (incl. sample size + seed → NFR-1).
2. **Recommend.** Given the user's `compute_budget`, recommend a threshold set whose
   projected cost fits the budget with projected pair count shown.
3. **Accept / modify (live what-if).** The UI re-queries the projection curves as
   the user tweaks thresholds — projected pair count / cost update live. Result is a
   `relatedness_config` (status `draft`).
4. **Trigger.** Accepting the config (status → `accepted`) triggers Stages 3–5 for
   `(version, config)`.

**Deterministic vs approximate boundary (explicit).**
- **Stage-D metric computation is DETERMINISTIC** — exact tail-restricted ρ and
  exact sparse co-occurrence — on a **PREFILTERED selective-gene space** (drop
  pan-essential & pan-inert; quadratic reduction) with **tiled/thresholded GEMM**.
- **Approximate nearest-neighbor (top-K) pruning is a FALLBACK ONLY**, engaged
  solely when the profiler flags the pair space exceeds budget even after
  prefiltering. When engaged, `relatedness_config.thresholds.compute_mode =
  ANN_TOPK` records it, so a run's exact/approximate status is auditable.

---

## 8. Insight Subsystem (PubMed → S3 → Claude agent)

### 8.1 Batch PubMed pre-fetch
For each screen, resolve cited PMIDs → fetch once via NCBI **efetch / PMC** →
store once per PMID in **S3** (`s3://<bucket>/pubmed/<pmid>.json`) → record in
`dim_pubmed_article` (facets + `s3_uri` + `fetched_at` + `fetch_status`). Pairs link
to PMIDs via `dim_gene_pair_publication`. Idempotent per PMID (NFR-3); NCBI rate
limits respected via batching/backoff.

### 8.2 On-demand LLM insight agent
- **Provider seam (locked decision #4).** All calls go through a provider-agnostic
  interface; the concrete adapter is **Claude via the WashU Secure API**
  (models Opus / Sonnet / Haiku now, **Fable** soon). Keys from **AWS Secrets
  Manager** → runtime env (12-factor III, NFR-6). Tiering: **Opus** = deep
  synthesis, **Sonnet** = default, **Haiku** = cheap sub-steps (PMID relevance
  filtering, claim de-duplication).
- **Agency level — OPEN SUB-DECISION, default L1.** L0 = single-shot RAG,
  L1 = tool-using (retrieval + evidence lookup tools), L2 = multi-agent (researcher
  + verifier + editor). Default **L1**; recorded per insight in `agency_level`.
- **Three-question cited output.** For **each gene** and **each gene-pair**, produce
  a structured answer to:
  1. **Established knowledge** — what is known with full confidence.
  2. **Recognized knowledge gaps** — what is not yet discovered but widely regarded
     as needed for genomic domain science.
  3. **Reducible / open uncertainty** — what can be worked further.
- **Dual grounding / citation contract (FR-12).** Every claim cites ≥1 external
  **PMID** and/or an **internal evidence ref** — e.g. *"co-essential across 48
  oxidative-stress screens, ρ=0.71, FDR<0.01"* resolves to `fact_gene_pair` +
  `dim_gene_pair_screen`/`dim_gene_pair_context` rows. Unsupported claims are
  dropped/flagged, never stored as `approved`.

### 8.3 Structured, human-curatable storage
Insights persist per-gene (`dim_gene_insight`) and per-pair
(`dim_gene_pair_insight`) with the 3-section claims as JSON so a researcher can
**edit / accept / reject individual claims**. Each carries `user_annotation`,
`annotated_by`, `status` (draft/edited/approved/rejected), and a monotonic
`version` (bumped on human edit or regeneration; prior rows `is_current = FALSE`).

---

## 9. Deliverables & Sequencing (how they string together)

Legend — Artifact: what the deliverable produces. Depends-on: prior deliverable IDs.
Maps-to: prerequisite/backlog item.

| ID | Deliverable | Produces / artifact | Depends-on | Maps-to |
|----|-------------|---------------------|------------|---------|
| **P1** | Port `harmonize_scores.py` into `fact_screen_gene` harmonization columns | `harmonized_score`, `percentile_score`, `robust_z_score`, `is_hit` populated per (screen,gene) | — | backlog **#9–#12** |
| **P2** | Populate `fact_screen_gene_publication` (currently a 0-row stub) | screen→PMID→gene link rows | — | prereq **P2** |
| **P3** | Capture screen-context metadata + cited PMIDs during staging | `dim_screen_context` rows, `dim_pubmed_article` PMID stubs | P1 (staging pass) | prereq **P3** |
| **D1** | Schema DDL → numbered migrations | migrations `0012..00NN` from `gene_relatedness_schema.sql` (applied before any reader) | — (uses P1/P2 tables) | this design |
| **D2** | Profiler (cheap) | `relatedness_profile` rows: data shape + threshold→(pairs,cost) curves (exact co-hit/co-cite, sampled co-ess w/ CI) | D1, P1, P2, P3 | decision #2 |
| **D3** | What-if config service + UI | `relatedness_config` (recommend → live what-if → accept), triggers build | D2 | decision #2/#3 |
| **D4** | Candidate generation | evidence-generated, organism-partitioned, selective-gene-prefiltered candidate set (exact vs ANN per budget) | D3 | FR-1, FR-6 |
| **D5** | Co-essentiality compute (Channel 1) | tail-restricted \|ρ\| + support + p; `dim_gene_pair_screen` (FULL) | D4 | FR-2, §6.1 |
| **D5b** | Novelty / mechanistic-divergence (Channel 5) — residual co-essentiality + anti-β + buffering-candidate | light additive expectation fit → `dim_gene_expectation_model`; `resid_*` + `novelty_score` + `is_antagonistic` + `is_buffering_candidate`/`buffering_basis` on `fact_gene_pair`; residuals on `dim_gene_pair_screen` | D5, P3 | FR-2b/2c/2d, §6.6 |
| **D6** | Co-hit compute (Channel 2) | Jaccard/PMI/Fisher + support; `dim_gene_pair_screen` (hits) | D4 | FR-2, §6.2 |
| **D7** | Co-citation compute (Channel 3) | PMI/Jaccard + support; `dim_gene_pair_publication` | D4, P2 | FR-2, §6.3 |
| **D8** | Contextual convergence (Channel 4) | per-context stats; `dim_gene_pair_context` | D6, P3 | FR-2, §6.4 |
| **D9** | Roll-up & BH-FDR | per-channel + overall tiers; `fact_gene_pair` header; dropped-pair audit | D5, D5b, D6–D8 | FR-3/4/5, NFR-5 |
| **D10** | PubMed → S3 prefetch job | S3 objects `pubmed/<pmid>.json` + `dim_pubmed_article` facets | P3, D1 | FR-10 |
| **D11** | LLM provider seam + Secrets wiring | provider-agnostic client, Claude/WashU adapter, tiered models, keys from Secrets Manager | D1 | decision #4, NFR-6 |
| **D12** | Insight agent (gene + pair) | `dim_gene_insight`, `dim_gene_pair_insight` — 3-section cited claims | D9, D10, D11 | FR-11/12/13 |
| **D13** | API + UI surfacing | scorecard read APIs, evidence drill-down, what-if UI, insight review/curation UI | D3, D9, D12 | FR-9/13/14 |

**Critical path:** P1 → D1 → D2 → D3 → D4 → (D5,D6,D7) → D8 → D9 → D12 → D13.
D5b branches off D5 (also needs P3) and joins the roll-up at D9, in parallel with
D6–D8. D10/D11 run in parallel with the compute channels; D12 gates on D9+D10+D11;
D13 surfaces incrementally (what-if UI after D3, scorecard after D9, insights after
D12).

---

## 10. Principle Compliance

### 10.1 12-Factor
- **III Config / IV Backing services:** DB creds + LLM keys + S3/bucket names from
  env (via AWS Secrets Manager); RDS, S3, WashU Secure API are attached resources
  swappable by env (NFR-6).
- **VI Processes (stateless):** compute stages are stateless workers; all state in
  RDS/S3; resumability via checkpoints + UNIQUE/`is_current` (NFR-3).
- **IX Disposability:** tiled/checkpointed stages start fast, shut down clean, and
  resume on the next screen-tile / PMID / entity.
- **X Dev/prod parity & I Codebase:** one DDL draft → numbered migrations applied
  identically per environment; `run_migration.py` is the single path.
- **XI Logs:** stages emit structured `etl_audit_log` rows + stdout event streams.

### 10.2 SOLID
- **SRP:** each stage/table has one job — profiler ≠ config service ≠ candidate gen
  ≠ per-channel compute ≠ roll-up ≠ insight agent; each metric channel is its own
  module; `dim_*` tables split evidence by kind (screen / context / publication).
- **OCP:** adding a 5th channel = a new compute module + attribute-group columns,
  no change to roll-up's contract (channels register their (effect,support,FDR)).
- **LSP / ISP:** the LLM provider seam exposes a narrow `generate()` /
  `embed()` interface; Claude adapter (and a future Fable/other adapter) are
  substitutable; insight consumers depend on the claim schema, not the model.
- **DIP:** compute + insight depend on the provider-agnostic seam and on repository
  interfaces over RDS/S3, not on concrete SDKs.

### 10.3 OWASP Top-10 threat model
| Risk | Exposure | Mitigation |
|---|---|---|
| **A01 Broken access control** | Scorecard/insight read + curation APIs | Reuse RETICLE API auth (Entra SSO, per MEMORY); curation endpoints require an authenticated researcher; `annotated_by` from the token, never the request body. |
| **A02 Cryptographic failures** | LLM keys, DB creds, PubMed content | Keys only in AWS Secrets Manager → runtime env; TLS to RDS/S3/WashU API; S3 bucket private + SSE; no secrets in logs/prompts (NFR-6). |
| **A03 Injection** | SQL over version/config/gene params; **prompt injection** from PubMed abstracts into the LLM | Parameterized SQL only; Pydantic request models with `extra="forbid"` (repo convention, A04 backstop); retrieved PubMed text is treated as untrusted data, fenced/quoted in prompts, and the citation contract rejects claims not traceable to a real PMID/row. |
| **A04 Insecure design** | Config tampering to force huge/expensive runs | `compute_budget` gate + profiler projection is server-authoritative; accepted config's projected cost is validated server-side before trigger. |
| **A05 Security misconfiguration** | S3 bucket, RDS, IAM | Least-privilege IAM (read PMID prefix, write pair/insight tables); bucket public-access-blocked; Terraform-managed (repo has `terraform/`). |
| **A06 Vulnerable components** | NCBI/LLM SDKs, numpy/scipy | Pinned deps (`requirements.txt` convention); dependency scanning in CI. |
| **A08 Data integrity** | Insight tampering / fabricated citations | Dual-grounding contract: unsupported claims dropped/flagged; `status`/`version` audit trail; internal refs must resolve to live warehouse rows. |
| **A09 Logging/monitoring** | Silent metric or fetch failures | `etl_audit_log` per stage (rows in/out, dropped, duration); `fetch_status`/`fetch_error` on `dim_pubmed_article`; run status on `relatedness_config`. |
| **A10 SSRF** | NCBI/PMC + WashU API egress | Egress restricted to allowlisted NCBI + WashU hosts; PMIDs validated as integers before URL construction. |

---

## 11. Open Sub-Decisions
1. **LLM agency level — L0 / L1 / L2** (default **L1**). Revisit after a small
   grounding-accuracy eval (per-claim citation validity on ~50 hand-checked genes).
2. **S3 bucket / prefix.** Proposed `s3://reticle-pubmed-cache/pubmed/<pmid>.json`;
   confirm bucket name, region, lifecycle (Glacier after N days?), and cross-account
   access with infra-engineer.
3. **Exact tier thresholds** — deferred to the what-if profiler; only the *shape*
   (Strong/Moderate/Weak + support floor) is fixed here.
4. **Model routing table** — which sub-steps map to Haiku vs Sonnet vs Opus (and
   when Fable lands); default Sonnet, escalate to Opus for final per-pair synthesis.
5. **Surrogate FK enforcement** on `screen_id`/`gene_id` in the new tables — keep
   (design clarity) vs drop (prod parity/perf). Recommend keep in dev, benchmark
   before prod.
6. **Context vocabulary** — `assay_domain` controlled vocabulary vs emergent
   clustering (see beta-aligned doc §2); start with a coarse fixed list, refine.

---

## 12. Risks & Mitigations
| Risk | Impact | Mitigation |
|---|---|---|
| Pair space explodes despite prefilter | Blown compute budget | Profiler is the gate (NFR-2); selective-gene prefilter; ANN top-K fallback flagged in config. |
| Co-essentiality volume mis-estimated (sampled) | Under/over-budget build | Confidence band on the estimate; conservative recommend; re-profile if actual > `ci_high`. |
| P1 harmonization sign errors propagate | Wrong correlations | Reuse the audited `harmonize_scores.py` registry + LLM directionality overrides; validate against core-essential anchors (as prototype does). |
| PubMed stub (`fact_screen_gene_publication`) never populated | Co-citation channel empty | P2 is an explicit prerequisite on the critical path for D7; co-citation degrades gracefully (channel simply absent) until then. |
| Prompt injection / hallucinated citations | Bad science in insights | Dual-grounding contract + untrusted-text fencing (A03/A08); human curation before `approved`. |
| Cross-organism leakage | Biologically invalid edges | Structural partition by `organism` + non-null `fact_gene_pair.organism` (NFR-4). |
| LLM cost blowout | Budget | Tiered models (Haiku sub-steps), on-demand (not batch-all) insight generation, prompt caching where supported. |
| Stored edges go stale vs a new data load | Misleading scorecard | Per-(version,config) keying + `is_current` supersede; A/B compare old vs new (decision #3). |

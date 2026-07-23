# RETICLE — Gene-Gene Relatedness Process (Plan)

**Goal.** Turn the warehouse (`screen_gene_raw`, `fact_screen_gene`, `dim_gene`,
`fact_screen_gene_publication`) into a queryable **gene-relatedness network**:
for any two genes, *are they related, on what evidence, and how strongly.*

This plan defines **(A)** the domain criteria that mark two genes related, **(B)**
how we grade the depth/strength of each relationship, and the **intermediate
normalization** required to make heterogeneously-scored screens comparable. It
ports the proven logic in `prototype/script/` into a warehouse-native pipeline.

---

## 0. Why normalization comes first (the core problem)

`screen_gene_raw.score_1..5` are **not comparable across screens.** Each screen's
`SCORE.1_TYPE` may be Log2FC, Z-score, MAGeCK/CasTLE/STARS/CERES score, Bayes
Factor, FDR, rank, or raw read counts. Two issues:

1. **Scale** — a −7..+2 CRISPR Score and a raw MAGeCK magnitude live on different
   axes; you cannot compare or correlate them directly.
2. **Direction** — for some score types "more negative = essential" (depletion),
   for others "larger = stronger hit." Sign must be harmonized to **one
   loss-of-function axis** before any cross-screen math.

So every relatedness criterion downstream runs on a **harmonized percentile
score**, never on raw `score_1`. This is exactly the `harmonize_scores.py` +
directionality logic from the prototype, re-expressed as warehouse tables.

---

## (A) Criteria that mark two genes as related

Four complementary evidence channels. A pair may be related on one, several, or
all — we keep them **separate and typed** so the UI can say *why*.

| # | Criterion | Biological meaning | Data used | Best for |
|---|-----------|--------------------|-----------|----------|
| 1 | **Co-essentiality** | Correlated fitness/effect profiles ⇒ same pathway or complex (DepMap-style) | Harmonized percentile of `score_1` across shared screens | Genome-wide (FULL-coverage) screens |
| 2 | **Co-hit enrichment** | Called as hits together more than chance ⇒ functional convergence | `hit_flag` sets | Hit-only screens (no genome-wide ranking) |
| 3 | **Co-citation** | Reported together in the same publications | `fact_screen_gene_publication` | Literature corroboration / cold-start genes |
| 4 | **Contextual convergence** | Both hit under the same assay domain / condition / cell line | `hit_flag` × screen metadata facets | Explaining *the condition* a relationship holds in |

**Guardrails (domain rules, all channels):**
- **Never cross organism.** Human vs mouse share almost no symbols (`POLR2A` vs
  `Polr2a`) and different biology — build one network per organism (`gene.organism`).
- **Evidence only from shared measurement.** A pair is only informed by screens
  that measured *both* genes; store the intersection size so trust scales with it.
- **Tail signal.** ~80% mid-distribution genes are noise; co-essentiality signal
  is in the tails — compute a tail-restricted correlation for survivors.

---

## (B) Depth / strength of a relationship

Each stored edge carries **three orthogonal dimensions**, then a rolled-up tier.
"Strongly related" vs "barely related" = high effect **and** high support **and**
survives multiple-testing.

1. **Effect size** — how similar. Co-essentiality: |Pearson/Spearman ρ| on
   percentile profiles. Co-hit: Jaccard index. Co-citation: co-citation count /
   normalized PMI.
2. **Support** — how much evidence backs it. Number of shared screens
   (co-essentiality), shared hits (co-hit), shared publications (co-citation).
   A ρ=0.9 over 3 screens is *barely* related; ρ=0.6 over 200 is *strongly*.
3. **Significance** — could it be chance. Co-essentiality: p-value of the
   correlation; co-hit: Fisher's exact / hypergeometric p. Apply
   **Benjamini-Hochberg FDR** across the full pair space (millions of pairs) —
   this is what stops spurious edges from flooding the network.

**Confidence tier** (single label for the UI), computed only on pairs clearing
minimum support:
- **Strong** — |effect| ≥ high threshold, support ≥ high floor, FDR q < 0.01
- **Moderate** — mid thresholds, FDR q < 0.05
- **Weak / suggestive** — clears minimum support & q < 0.1 but below moderate
- (below minimum support ⇒ **not stored**, logged as dropped)

Thresholds seed from the prototype (`MIN_OVERLAP_GENES=500`, `RHO_MIN=0.30`,
`TAIL_CUTOFF=0.50`, `MIN_SHARED_HITS=3`) and are tuned against known
positive-control pairs (see step 6).

---

## The pipeline — scripts & goals

Warehouse-native, versioned like the ETL (`version_id` / `run_id`, `is_current`).
Each step is idempotent and re-runs per `data_load_version`.

### Step 1 — `classify_screen_scores.py`  → table `screen_score_profile`
**Goal:** decide, per screen, whether its `score_1` is usable and in which bucket.
- Join per-screen `SCORE.1_TYPE` (from `Domain/Data/screen_metadata_*.json`).
- Bucket via `SCORE_TYPE_BUCKETS`: `effect` | `significance` | `rank` | `unusable`.
- Assign **coverage type**: `FULL` (genome-wide ranking present) vs `HIT_ONLY`
  (only hits deposited) — routes each pair to continuous vs binary math later.
- Emit which screens are excluded and why (audit row per screen).

### Step 2 — `harmonize_scores.py`  → table `harmonized_score`
**Goal:** one comparable loss-of-function axis. For each usable `screen_gene_raw` row:
- Apply **directionality** so negative = loss-of-function/depletion across all
  screens (reuse frozen `directionality_overrides.json`; anchor on core-essential
  genes for sign validation).
- **Percentile-rank `score_1` within each screen** → `percentile_score` on a fixed
  scale (`df.groupby(screen)['score_1'].rank(pct=True)`, mapped to [−1,1]).
- Validation gate: core-essential genes (e.g. `POLR2A`, ribosomal) must land
  negative — fail the run if not (`validate_harmonization.py`).

### Step 3 — `build_gene_screen_matrix.py`  → `gene_screen_matrix_<organism>.npz`
**Goal:** dense gene × screen percentile matrix per organism (FITNESS/FULL screens).
- Require a gene appear in ≥ max(30, 11% of screens) for a reliable profile.
- Mean-impute missing, row-center, L2-normalize so **cosine == Pearson** — a
  gene's top partners become one matrix-vector product (fast enough for on-demand
  queries and full-network batch).

### Step 4a — `compute_coessentiality.py`  → `fact_gene_pair_coessential`
**Goal:** criterion 1. Pairwise-complete correlation on percentile profiles over
shared screens. Store `rho`, `tail_rho`, `n_shared_screens`, `p_value`. Keep only
|rho| ≥ RHO_MIN and overlap ≥ MIN_OVERLAP_GENES.

### Step 4b — `compute_cohit_enrichment.py`  → `fact_gene_pair_cohit`
**Goal:** criterion 2 (for HIT_ONLY screens). Jaccard + Fisher's exact on hit sets
from `hit_flag`. Store `jaccard`, `n_shared_hits`, `p_value`. Keep ≥ MIN_SHARED_HITS.

### Step 4c — `compute_cocitation.py`  → `fact_gene_pair_cocitation`
**Goal:** criterion 3. Co-occurrence in `fact_screen_gene_publication`. Store
co-citation count and normalized PMI. (Cheap; also covers cold-start genes.)

### Step 4d — `compute_contextual.py`  (optional)  → `fact_gene_pair_context`
**Goal:** criterion 4. Co-hit stratified by assay domain / condition / cell line
so an edge can be labeled *"related under oxidative stress."*

### Step 5 — `score_gene_relatedness.py`  → `fact_gene_relatedness`
**Goal:** the unified, UI-facing edge table. For each pair present in any channel:
- Run **BH-FDR** within each channel across all pairs → `q_value`.
- Normalize each channel's effect to a common 0–1 `strength` (so ρ, Jaccard, PMI
  are comparable in the UI).
- Compute the **confidence tier** (Strong/Moderate/Weak) per §(B).
- Store one row per (gene_a, gene_b, channel) plus a rolled-up `combined_score`
  and a `supporting_channels` array — this is what the API/graph queries.

### Step 6 — `validate_relatedness.py`  (QA gate, not stored)
**Goal:** confidence the numbers mean something. Check known positive controls
(protein complexes: proteasome, ribosome, mediator; canonical pathways) score
Strong, and random pairs don't. Report precision/recall vs STRING as an external
yardstick. Tune thresholds here before publishing a run.

---

## Data flow

```
screen_gene_raw ─┐
                 ├─(1) classify_screen_scores → screen_score_profile
screen metadata ─┘
        │
        └─(2) harmonize_scores → harmonized_score  ──(3) build matrix ─┐
                    │                                                   │
                    ├─(4a) coessentiality (FULL)  ─────────────────────┤
   hit_flag ────────┼─(4b) co-hit enrichment (HIT_ONLY) ───────────────┤
   publications ────┼─(4c) co-citation ────────────────────────────────┤
   facets ──────────┴─(4d) contextual ──────────────────────────────────┤
                                                                        ▼
                                     (5) score_gene_relatedness → fact_gene_relatedness
                                                                        │
                                                     (6) validate (QA gate before publish)
```

## Open decisions to confirm
- **Compute locus:** Python/pandas+scipy+numpy (matches prototype, easier stats/
  FDR) vs in-warehouse SQL/pgvector. Recommend **Python jobs writing back fact
  tables** — the correlation/FDR math is impractical in pure SQL.
- **Refresh cadence:** recompute the whole network per ETL `version_id` (simplest,
  versioned) vs incremental. Recommend full recompute — it's a batch job, not hot path.
- **Organism scope for v1:** start with `mus_musculus` (the template's target,
  smaller: ~1.9M rows) then extend to `homo_sapiens`.
```

# RETICLE — Gene-Gene Relatedness Process (Beta-Aligned Plan)

> **Companion to `gene_relatedness_process.md`.** That draft describes a
> prototype-parity co-essentiality/co-hit/co-citation network with a stored
> `fact_gene_relatedness` edge table. This version reconciles the process with
> **`reticle_beta.md`** (Path 2, ranks) and **`reticle_target.md`** (Path 1, σ).
> Where the two disagree, this document follows the beta/target. See §0 for the
> point-by-point delta.

**Goal (restated in beta terms).** Not "score how related two genes are and store
the edge." Instead: **make every screen comparable via a context vector, fit each
gene's dosage-sensitivity β̂ as a function over that context, and expose gene-gene
relationships as four contrasts computed at query time** — never stored. The
question a relationship answers is *"does one dosage-sensitivity function,
conditioned on what each experiment actually was, explain both genes — and is the
leftover (residual) shared?"*

---

## §0. Delta vs. the prototype-parity draft

| Prototype-parity draft | This (beta-aligned) plan | Beta/target basis |
|---|---|---|
| Store `fact_gene_relatedness` edge table | **Never store an edge.** Store the observation table; compute contrasts at query time | Beta Part VII |
| Relationship = co-essentiality similarity scalar | Relationship = one of **four edge types** derived from (β̂, R), the real object | Beta Parts II, VII |
| Co-hit Jaccard on `hit_flag` sets | Absence in hits-only screens is `undefined_absent` — **excluded, never zeroed**; hit/no-hit never informs an edge | Beta Part III |
| Co-citation channel | **Dropped** — imports annotation/attention bias; "the screens *are* the annotation" | Beta Part VIII |
| BH-FDR + hand-tuned Strong/Moderate/Weak tier | **No hand-tuned confidence.** Support = N shared *measured* + N distinct libraries (ranks); posterior SD only after Phase 0 σ | Beta Part XII, Target Part III |
| Screens independent | **Effective N = distinct libraries**; `library` is a coordinate; robustness tested across libraries | Beta Part IV, Target Part VII |
| Harmonize MAGeCK/STARS/… score types | Fine for the **beta** (ranks absorb it); the **target** rejects harmonization and recomputes effect+σ from guide-level counts | Target Parts IV–V |
| No context vector, no LLM | **Context vector `c_i` is the invariant, built first**; LLM fills semantic slots from methods text, never from scores | Beta Part IV |

---

## §1. The primary record is an observation, never a gene

```python
Observation = (gene_id, screen_id, e, status, c_screen)
```

- **`e` — signed rank-percentile**, normalized by library size:
  `e = sign(direction) × (1 − 2·rank / L)`, `L` = library size for that screen.
  (Normalizing by `L` is the beta's #1 build item — "probably the largest
  current noise source." Rank 132/20 000 ≠ rank 132/500.)
- **`status` ∈** `measured` · `measured_within_manifest` · `undefined_absent` ·
  `undefined_outside_manifest`.
- **`c_screen`** — foreign key to the screen's context vector (§2).

**Exclusion rule (load-bearing, free under ranks):** observations with undefined
status are *excluded* from any comparison — **never zeroed**. Every computed edge
reports N of shared `measured` observations and N distinct libraries.

### Warehouse mapping
The warehouse already stores the raw material; this is a re-expression, not a
re-collection.

| Beta object | Warehouse source |
|---|---|
| `e` | `screen_gene_raw.score_1` → per-screen rank-percentile (harmonized sign) |
| `status` | derived from screen coverage type (FULL vs HIT_ONLY) + manifest presence |
| `library`, `aggregation`, continuous slots | screen metadata + computed from score distribution |
| investigator hit call (`hit_flag`) | **retained as metadata only — must never inform an edge** |

ORCS deposition → status mapping (Beta Part III):

| ORCS deposition | status | Inference constraint |
|---|---|---|
| Whole-genome, continuous scores | `measured` | both directions (gold standard) |
| Sub-genome, hits only | `undefined_absent` for non-listed | **positive evidence only — may raise, never lower** |
| Targeted, manifest + scores | `measured_within_manifest` / `undefined_outside_manifest` | both directions, within manifest only |

---

## §2. The context vector `c_i` — the invariant, built first

One vector per screen. Four slot kinds, **not to be conflated**. Freeze the *slot
types* now (an afternoon); let vocabularies emerge from clustering the extractor's
output — do not debate an ontology up front (Beta Part IV).

1. **Mechanistic** — `modality ∈ {KO, CRISPRi, CRISPRa, base_editor}`, `sign`
   (−1 LOF / +1 GOF), `magnitude_class`. Modality has **no distance** — it is a
   *signed prior* on the expected relationship between values.
2. **Categorical** — `aggregation ∈ {guide_level, gene_level}`, **`library`**
   (Brunello, Calabrese, …). `library` is the coordinate nobody expects and
   everybody needs: two screens sharing a library are **not independent**.
3. **Continuous, computed from data (not text)** — `library_size`,
   `guides_per_gene`, `timepoint_days`, `dynamic_range`, `depth_per_guide`, `MOI`.
   More trustworthy than anything the LLM extracts.
4. **Semantic — the LLM's only job** — `pressure_semantic`, `system_semantic`,
   `compound_semantic`. Embed from prior knowledge (compound structure/MOA,
   cytokine receptor family/pathway, cell lineage). **Never embed from which genes
   scored.** The embedding must place TNF-α near IL-1β and both far from
   doxorubicin — proximity that is not derivable from the strings.

> **The LLM describes the experiment. The data describes the gene.** Enforced by
> construction: the extractor never sees an effect size.

---

## §3. The model — β̂ and the residual R

For each gene, fit dosage-sensitivity as a **function over semantic context space**
by Gaussian process:

```
E[e_{g,i}] = s_{m_i} · β_g(c_i)          # s_m = modality sign prior
```

- **β̂_g(c)** — what mechanism explains (dose-responsive requirement).
- **R_g** — the residual after conditioning on context. *Residual that survives
  semantic conditioning = unrecognized mechanism.* This is the product.
- **Lengthscale `ℓ_p`** is a free diagnostic: an inflated `ℓ_p` announces a bad
  embedding (e.g. doxorubicin placed next to TNF-α). Wire it in week one, before
  trusting anything downstream (Beta Part V).

Under the **beta**, weights `w_i ≡ 1` (unweighted). Under the **target**, `w_i =
1/σ²` with σ propagated from guide-level counts — *the statistic swaps, the schema
does not* (Target Part II).

---

## §4. Relatedness = four edge types, computed at query time

Never stored (Beta Part VII: a stored edge is "a query result with its provenance
amputated"; one deposition's blast radius is the whole graph). Each returns
**weight + N shared measured + N distinct libraries + exclusions + the query**.

| Edge | Definition | Meaning | Maps to prototype? |
|---|---|---|---|
| **β-similarity** | β̂_g(·) ≈ β̂_h(·) across pressure space | Co-dependency, likely same pathway | ≈ the prototype's co-essentiality correlation |
| **Residual similarity** | cos(r_g, r_h) high | **Anomalous in the same way** — invisible to every existing method | new |
| **Anti-β** | β̂_g ≈ −β̂_h | Antagonistic | new |
| **Buffering** | β_g ≈ 0 under LOF, large under GOF; β_h complementary | **Candidate redundant pair — testable by combinatorial KO** | new |

> The pitch is not "we can find similar genes." It is "**we can find genes that
> break the same rule.**"

**Depth / strength, honestly graded (ranks):** effect magnitude of the contrast
**plus** N shared `measured` observations **plus** N distinct libraries. There is
**no hand-tuned confidence tier.** The true support field — supported-valley
(β̂≈0, tight posterior) vs. uncharted (β̂≈0, wide posterior) — falls out of
**posterior variance**, and under ranks that is only available as a global constant
τ. High-|z|/high-R genes are **candidates, not findings**, until Phase 0 supplies
per-gene σ (Target Part III, Beta Part XII).

---

## §5. Build order (follows the beta's three-week sequence)

| # | Step | Script/goal | Why now |
|---|---|---|---|
| 1 | **Rank → rank-percentile, normalized by `L`** | rewrite the percentile step to divide by library size | largest current noise source; one line |
| 2 | **Freeze slot types** | schema for `c_i` (4 slot kinds); vocab emerges from clustering | everything inherits it |
| 3 | **`library` + `aggregation` as coordinates** | add to `c_i`; report effective N as distinct libraries | protects every downstream claim |
| 4 | **`status` field + exclusion rule** | derive 4-value status; enforce exclude-never-zero | free now, expensive later |
| 5 | **Semantic embedding** | LLM extracts pressure/system/compound from methods text | the LLM's only job |
| 6 | **Check `ℓ_p`** | fit GP, inspect lengthscale | free embedding QC, no ground truth |
| 7 | **Replicate-recovery benchmark → freeze schema** | same-compound/same-system/different-lab screens must retrieve close | the only guard against a self-confirming schema |
| 8 | **Semantic-neighbor retrieval** | "which screens are secretly asking the same question?" | fastest legible result — **ship first** |
| 9 | **β̂ / R fit; four mechanistic signatures** | GP fit + the four edge types at query time | the core |
| 10 | **Screen ingestion + surprise scoring** | pass a genome-scale screen through, hold out user screen | primary use case |
| 11 | **Pathway aggregation** | variance reduction; buffered-module detection | recovers most power ranks lose |

### Explicitly deferred to Phase 0 (target)
Per-gene σ from guide-level counts; guide-efficiency correction; the purpose-built
estimator (effect size + uncertainty, within-screen dynamic-range normalization);
`expression_under_c` as a context coordinate. **Start the Phase 0 denominator
audit in parallel** — it determines the shape of the project.

---

## §6. What the prototype-parity draft is still good for
Not the production spec, but a **validation harness**: does the beta pipeline's
β-similarity edge reproduce the correlation network the prototype already
produces on the same organism? Divergence is a bug in one of them. Keep it as an
appendix, labeled as such.

## Open decisions to confirm
- **Compute locus:** GP fit + query-time contrasts in Python (numpy/scipy/GPy or
  sklearn GP), reading the observation table; the warehouse stores observations +
  `c_i`, not edges.
- **LLM for semantic slots:** which model/gateway; extraction-validation protocol
  (~50 hand-annotated screens, per-coordinate accuracy) — a reviewer will demand it.
- **Beta scope v1 organism:** `mus_musculus` first (smaller), then `homo_sapiens`.

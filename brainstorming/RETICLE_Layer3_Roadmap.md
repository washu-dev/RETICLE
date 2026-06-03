# RETICLE — Layer 3 Technical Roadmap
### The Comparison Engine

**Scope:** Given a user's gene list, compare it against every screen in the reference set and return ranked matches with biological context, directionality agreement, and co-regulation signal. This is the statistical core that turns "here are my genes" into "here are the screens that look like yours."

**Where it runs:** Cloud serving layer, at query time. Pure NumPy/SciPy math — no ML framework, no GPU.

**Definition of done:** A user gene list (ranked or hit-list) returns a statistically-ranked list of matched screens in under a few seconds, with p-values/FDR, directionality agreement, and flagged co-regulated gene groups.

---

## Guiding Principles

1. **Two modes for two input types.** Ranked lists → correlation. Hit lists → overlap. Don't force one onto the other.
2. **The math is light; the data plumbing is the work.** Spearman across 2,000 columns is milliseconds. Getting the matrix into the right shape and handling missing data correctly is the real engineering.
3. **Directionality agreement is a first-class output,** not an afterthought. A correlated screen with *inverted* biology is a meaningful result, not noise.
4. **Co-regulation is the differentiator.** Detecting sub-significant gene groups that move together is what separates RETICLE from STRING/GSEA. Build it, but keep the MVP version simple.

---

## The Two Comparison Modes

### Mode 1 — Continuous / Rank Correlation
- **Trigger:** user uploads a ranked list with scores.
- **Method:** Spearman's rho between the user's gene-ranking vector and each screen's percentile-rank column.
- **Implementation:** vectorized — one user vector vs the genes × screens matrix. SciPy `spearmanr` or a manual rank-then-Pearson over the matrix for speed.
- **Output per screen:** rho, p-value, FDR (Benjamini-Hochberg across all screens).

### Mode 2 — Binary / Overlap
- **Trigger:** user uploads a hit list (gene names, no scores), or matches against hits-only screens.
- **Method:** Jaccard index (`|intersection| / |union|`) and Fisher's Exact Test (overlap vs expected by chance, using library size as background).
- **Output per screen:** Jaccard, Fisher p-value, FDR, shared genes.

### Mode selection
- Choose per comparison based on **both** the user input type and the target screen type. A ranked user list vs a hits-only screen falls back to overlap mode for that pair.

---

## Missing-Data Handling (the subtle part)

The three-state presence flags from Layer 5 matter here:
- `not_in_library` genes must be **excluded from the correlation** for that screen (they were never measured — not a zero, not a null effect).
- `tested_not_hit` genes are real measurements and stay in.
- Conflating these two produces false correlations — the exact failure mode flagged in Module 1.
- Spearman must operate only over genes present in **both** the user list and the screen's library.

---

## Directionality Agreement

For each correlated screen, compare the user's directionality (if known) against the screen's `biological_direction`:
- **Agree:** genes move the same biological way → straightforward biological match.
- **Disagree (inverted):** strong correlation but opposite direction → potentially the *most interesting* result (your treatment may have the opposite effect). Flag explicitly; do not discard.
- Surface agreement as a labeled dimension on every result, not a filter.

---

## Co-Regulation Detection

**Goal:** Surface gene groups that collectively signal a pathway even when individually sub-significant.

- **MVP approach:** use pathway/complex membership from `reference_pathways` (STRING/GO). For each known group, test whether its member genes cluster in the user's ranking (e.g. enrichment of the group toward the top, via a rank-based test).
- **Directional consistency:** within a candidate group, check that members move the same biological direction across matched screens.
- **Keep it simple for MVP** — pathway-anchored enrichment, not unsupervised clustering. Unsupervised co-regulation discovery is a v2 research problem.

---

## Output Contract (feeds Layer 2)

```
per matched screen:
  screen_id, biological_context_label
  statistic (rho or jaccard), p_value, fdr
  directionality_match (agree / inverted / unknown)
  shared_or_top_genes
  mode_used (correlation / overlap)
ranked by statistical strength

plus:
  co_regulated_groups (group, members, direction, enrichment_stat)
```

This structured result is what the RAG layer reads to generate rationales.

---

## Timeline Summary

Maps to the original "Weeks 5–6: RETICLE Engine Development." The core correlation/overlap math is a few days; the rest of the two weeks is missing-data handling, directionality agreement, co-regulation, FDR correction, and performance profiling against the real matrix.

---

## Open Questions for the Team

1. **Inverted-correlation semantics:** When a user's list correlates strongly but with inverted directionality, how should it rank relative to a direct match? Same magnitude, different meaning — does the UI separate them or interleave them?
2. **Co-regulation scope for MVP:** Pathway-anchored enrichment only, or attempt some lightweight unsupervised grouping? (Recommendation: pathway-anchored only for MVP.)
3. **Hits-only screens:** What fraction of the reference set will be hits-only (overlap-mode-only)? If large, correlation mode covers fewer screens than hoped — affects coverage claims.
4. **Multiple testing burden:** Across ~2,000 screens plus co-regulation tests, FDR control needs care. Is a single BH correction across all screens right, or should modes be corrected separately?
5. **Single-gene query path:** The MVP also promises single-gene queries ("which screens was my gene a hit in"). Is that a degenerate case of this engine, or a separate simpler lookup? (Likely separate, simpler — just a filtered query over `reference_gene_screen`.)

## Critique of the Existing Roadmap (Layer 3 concerns)

- **The original documents correctly name the two modes** (Spearman/Kendall for continuous, Jaccard/Fisher for overlap) — this is a genuine strength and the plan is sound here.
- **Missing-data handling is not addressed** in the source documents, yet it's the single most consequential correctness issue in this layer. The three-state presence model (defined in the plan's Phase 1) must be *used* by the comparison engine, and the documents never connect the two.
- **Directionality disagreement has no defined handling** anywhere in the source material, despite being arguably the most scientifically interesting output. The plan treats correlation as inherently positive-meaning.
- **Co-regulation is described aspirationally** ("captures subtle phenotypic signatures beyond just the top hits") but with no concrete algorithm. For MVP scoping this needs to be pinned to something buildable (pathway-anchored enrichment) rather than left open.
- **The multi-arm screen test case (#3)** requires the comparison engine to "take two datasets and infer biology based on correlations or residuals" — this is a meaningfully harder operation than single-list comparison and is not scoped in the engine plan at all.

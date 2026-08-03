# RETICLE — Context-Resolved Co-essentiality Network

*A gene–gene functional network built **purely from BioGRID CRISPR screens** — no literature, no GO, no STRING. Pre-read for discussion.*

---

## TL;DR

Two genes are connected when knocking each one out perturbs cells the **same way, screen after screen** — but only within a **matched biological context** (e.g. "related under DNA damage"). The signal is read straight out of the harmonized screen table by a **fully deterministic** pipeline (no RNG, no LLM at compute time), so every edge is reproducible and traces back to specific screen observations. Validated by recovery of known **CORUM** protein complexes (AUROC 0.68) and by context-specific behavior (a gene's neighborhood re-wires when you change context).

---

## 1. The idea

Each CRISPR screen is a stress test: knock out every gene, measure how much the cells are affected. If two genes' knockouts rise and fall **together** across many screens, they are likely acting in the same process ("same circuit"). We quantify that agreement with a correlation — the only catch is that we compare **like with like** (same context).

## 2. Data — one table, pure CRISPR

Everything derives from `harmonized_scores` (**28,237,649** rows). Each `(screen, gene)` is one number:

- **`PERCENTILE_SCORE`** ∈ [−1, +1], signed, normalized **within each screen**: −1 = knockout most deleterious (essential), 0 = no effect, +1 = knockout advantageous.
- Ranking (not raw scores) is what makes screens using different scoring methods (MaGeCK, CasTLE, Log2FC…) comparable.
- **`IS_HIT`** (0/1): author-called hit. Hits are rare — **6.7%** of all rows — the rest is the noisy middle.

This table is the single source of truth. No external annotation enters the network.

## 3. Pipeline

**Step 1 — Stratify by context.** Pooling all screens dilutes context-specific links and lets pan-essential genes correlate with everything. So we compute edges **within one context at a time**. Contexts come from a two-level, per-screen taxonomy:

- *assay_domain* (LLM-labeled once, then frozen as data): **fitness** (1068), **stress** (695), **reporter** (189) — human.
- *mechanism bucket* for drug screens (`drug_mechanism.py`, rule-based): cisplatin/etoposide/camptothecin → `DDR·genotoxic`, olaparib → `DDR·PARP`, trametinib → `MAPK`, … (360/485 drug screens bucketed into 22 mechanisms).

**Step 2 — Nodes = signal-bearing genes.** A gene joins a context's network only if it is a hit in **≥ 5** of that context's screens. Never-hit genes have flat/noise profiles (no evidence, and they pollute the graph); this drops ~half the genes.

**Step 3 — Co-essentiality correlation.** Within the context's genome-wide (FULL) screens, z-score each gene's profile and take the Pearson correlation between two genes' profiles. Centering means the question is *"when gene A is more essential than its own baseline, is gene B too?"* — so "both essential" alone does **not** imply an edge; co-*variation* does.

**Step 4 — Edge selection.** For each gene keep its **top-25** partners with correlation **r ≥ 0.15** and **≥ 20** co-measured screens (*support*, to reject lucky high correlations over few screens).

**Step 5 — Hub control via reciprocal-rank.** Pan-essential hubs correlate with many unrelated essential genes. An edge is flagged **`reciprocal`** (the clean default view) only if each gene is in the **other's** top-25 — a hub's non-specific attachment isn't mutual-best and drops out. Fully data-driven, no annotation.

Edges are stored in `net_edge` as `(gene_a, gene_b, context, strength, support, reciprocal)`. The graph is **multi-edge**: the same pair can carry different edges in different contexts.

## 4. Design decisions we tested and *rejected*

Every "smarter" idea was measured on CORUM before adoption; these failed, so the final method is the simple one (the choices are earned, not assumed):

- **Hit-anchoring** (correlate only over screens where a gene is a hit): −0.07 to −0.10 AUROC. Sparse hits make the anchor mostly one-hit-one-middle screens (dilution), and core-essential pairs lose variance (range restriction).
- **CLR / top-PC hub control** (the DepMap-standard de-noise): hurts AUROC; genome-wide it inflates edges to low-background "loner" genes and demotes true complex partners. Reciprocal-rank on the raw correlation is what works.

## 5. Validation

**Complex recovery.** Ground truth = **CORUM 5.3** human complexes (2,626 at 3–60 subunits) — biochemical membership, not literature attention. Do same-complex pairs correlate higher than different-complex pairs?

- **AUROC: fitness 0.684, DDR·genotoxic 0.661** over 7.2M gene pairs (0.5 = chance). An honest floor — CORUM only annotates a fraction of real functional relationships.

**Context-specificity** (the point of the whole thing, verifiable in the viewer). The *same* gene FANCD2:

- in **fitness** context → **4** reciprocal partners;
- in **DDR·genotoxic** context → **19** reciprocal partners = a coherent Fanconi / DNA-repair module (FANCA, FANCB, FANCC, FANCE, FANCI, RAD9A, RAD17, XRCC2, ESCO1, HELQ…).

Whether — and how — two genes connect depends on context.

## 6. Design principles

- **Pure CRISPR.** No PubMed, GO, or STRING enters the edges (the differentiator vs a literature-based network like STRING; also keeps validation clean — we test against CORUM biochemistry, never against a literature-derived network).
- **Context-resolved.** Correlation is recomputed *inside* each context, not pooled with a context label bolted on.
- **Observations are the truth; edges are derived.** Aligned with the "deposit observations, compute contrasts" framing — nothing is stored that can't be recomputed from the raw table, with provenance.
- **Deterministic & auditable.** No randomness, no LLM in edge computation → same input yields byte-identical output, and every edge traces to specific `(screen, gene, percentile)` observations.

## 7. Status

| | built |
|---|---|
| Contexts computed | `fitness` (1025 screens · 10,407 nodes · 245,807 edges / 14,274 reciprocal), `DDR·genotoxic` (89 · 2,052 · 36,005 / 15,295 reciprocal) |
| Interface | interactive web viewer — search a gene, toggle context, reciprocal-only filter, click to recenter |
| Scope | human only (v1) |

**Next:** compute the remaining mechanism contexts (DDR·PARP, MAPK, …); add a co-hit channel (Fisher) for HIT-ONLY screens; formal per-context FDR.

## Appendix — parameters & code

`hit-min = 5` · `top-k = 25` · `min-corr = 0.15` · `min-support = 20` · FULL-coverage screens only.

`drug_mechanism.py` (drug → mechanism) · `build_net_context.py` (per-screen context taxonomy) · `compute_coessential.py` (edges) · `validate_complexes.py` (CORUM AUROC).

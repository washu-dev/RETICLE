# RETICLE — Layer 4 Technical Roadmap
### The Reference Set (Storage & Serving Boundary)

**Scope:** The reference set is the boundary between the offline build world (Layers 5–6) and the online query world (Layers 1–3). This layer is about how the harmonized data is **stored, indexed, materialized, and served** so the comparison engine can query it fast. It is not new computation — it is the durable, queryable home for everything Layer 5 produced.

**Where it runs:** Postgres (system of record) on RIS or cloud; the query-serving copy lives where the comparison engine runs (cloud). Optional DuckDB / materialized views for analytical speed.

**Definition of done:** The comparison engine can pull the full gene × screen matrix (or any slice) in milliseconds; the reference set is versioned, reproducible, and refreshable without downtime.

---

## Guiding Principles

1. **One source of truth, multiple read shapes.** Postgres is canonical. Analytical reads may use a columnar copy (DuckDB / materialized view) optimized for the matrix math.
2. **Version everything.** Every reference-set build is tagged. A user result is reproducible against the exact reference version that produced it.
3. **Separate the matrix from the metadata.** The numeric gene × screen matrix (for Spearman/Jaccard) has different access patterns than the rich screen/gene metadata (for display and RAG). Store accordingly.
4. **Refresh is a swap, not an edit.** New builds are constructed alongside, validated, then atomically promoted. No partial states served to users.

---

## What the Reference Set Physically Contains

```
reference_screens          one row per approved screen
  screen_id, pmid, screen_type, selection_method, comparison, collected,
  organism, cell_type, library, library_size, algorithm,
  biological_context_label, reference_version

reference_gene_screen      the matrix (the heavy table)
  canonical_gene_id, screen_id, harmonized_score, percentile_rank,
  biological_direction, presence_status, reference_version

reference_gene_meta        per-gene annotations
  canonical_gene_id, symbol, organism, ortholog_group_id,
  publication_count, specific_go_count, darkness_components

reference_pathways         pathway / complex membership (from STRING/GO)
  canonical_gene_id, pathway_id, source, confidence
```

`reference_gene_screen` is the big one — ~human+mouse screens × tens of thousands of genes. This is the table whose access pattern dictates the storage choice.

---

## The Storage Decision

| Option | Role | Verdict |
|--------|------|---------|
| **PostgreSQL** | System of record; transactional; metadata; pgvector for RAG | **Primary — use for everything in MVP** |
| **DuckDB / columnar copy** | Fast analytical reads of the matrix for Spearman across all screens | **Add only if Postgres reads get slow** |
| Flat files (original plan) | — | **Reject** — 44M-row matrix is slow + unindexed |

**MVP recommendation:** Postgres alone, with the matrix properly indexed (composite index on `(canonical_gene_id, reference_version)` and `(screen_id, reference_version)`). Add a materialized columnar export (DuckDB/Parquet) for the comparison engine **only if** profiling shows the Spearman pass is too slow against Postgres. Don't pre-optimize.

---

## Materialization Strategy

- The comparison engine (Layer 3) needs the matrix as a dense numeric array (genes × screens) to vectorize Spearman. Provide a **materialized view or Parquet export** in exactly that shape, regenerated per reference version.
- Screen metadata and gene metadata are pulled by ID at result-render time — normal indexed Postgres lookups, no special handling.
- RAG embeddings (Layer 2) live in **pgvector** in the same Postgres instance — one fewer moving part.

---

## Versioning & Refresh

- Each Layer 5 rebuild writes a new `reference_version` tag.
- Build → validate (Layer 5 sanity suite must pass) → atomically promote the new version as "current."
- Old versions retained for reproducibility (a user can be told which version produced their result).
- BioGRID's quarterly cadence drives the natural refresh rhythm.

---

## Timeline Summary

This layer is thin in build effort — it's mostly schema design + indexing + a materialization script. Realistically folded into the tail of Weeks 3–4 (alongside Layer 5) and revisited when the comparison engine profiles its reads in Weeks 5–6.

---

## Open Questions for the Team

1. **RIS vs cloud for the serving copy:** The system of record can live on RIS, but the query-time copy needs to be where the comparison engine runs (cloud, for an always-on app). Do we replicate Postgres to cloud, or export a read-only matrix artifact (Parquet) to cloud per build? (Recommendation: export read-only artifact — simpler, cheaper, no live DB sync.)
2. **Matrix density:** With three-state presence, how do we represent `not_in_library` in the dense numeric matrix the comparison engine needs? NaN vs sentinel vs sparse representation — affects Spearman handling materially.
3. **Versioning granularity:** Do we need per-screen versioning (a single screen's metadata gets corrected) or only whole-build versioning? Per-screen is more flexible but more complex.

## Critique of the Existing Roadmap (Layer 4 concerns)

- **The original architecture document specifies flat files** ("Disk Database / Flat Files") as the repository. At 44M gene × screen rows this is a real performance liability for the comparison step and should be replaced with an indexed relational store. This is the clearest infrastructure correction needed.
- **The original plan never distinguishes the build-time store from the serve-time store.** Treating them as one entity is why the flat-file choice looks acceptable on paper — it ignores the query-latency requirement that only exists on the serving side.
- **No versioning concept exists** in the source documents. For a research tool whose database will be rebuilt repeatedly as curation improves, result reproducibility (which reference version produced this answer?) matters and is unaddressed.
- **The three-state presence model (a genuine strength of the plan) collides with the dense-matrix requirement** of the comparison engine, and the original documents don't reconcile them. How `not_in_library` is encoded numerically is an unsolved design point with real statistical consequences.

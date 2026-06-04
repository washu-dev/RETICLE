# RETICLE — Layer 6 Technical Roadmap
### Data Ingestion & Identity Resolution

**Scope:** Land every external data source as clean, parsed, independently-stored staging tables, joined to a single canonical gene identity. This layer ends at the boundary of harmonization (Layer 5) — it does *not* assign directionality, harmonize scores, or merge sources into the final reference set.

**Where it runs:** WashU RIS (batch, CPU-bound, offline). Postgres as system of record. No cloud serving dependency.

**Definition of done:** All staging tables populated and validated, canonical crosswalk built, ID resolution rate measured and accepted, every unmapped gene logged. The pipeline can be re-run reproducibly from raw downloads.

---

## Guiding Principles

1. **Bulk-download first.** Pull static reference data as files; reserve live API calls only for query-specific retrieval (paper text). Minimizes rate-limit exposure and makes rebuilds network-resilient.
2. **Stage, don't merge.** One clean table per source. Combining is Layer 5's job. Sources refresh on different cadences and must be independently re-pullable.
3. **Resolve identity before anything else.** The canonical crosswalk is the spine. Every source keys off gene identity; build it first, stamp it onto everything.
4. **Validate before proceeding.** A quality gate measures ID resolution rate and surfaces unmapped genes before Layer 5 begins. Silent join failures are the primary risk.
5. **Idempotent + reproducible.** Re-running any step produces the same result. Cache external fetches; never re-call for data already retrieved.

---

## The Ingestion DAG

```
STEP 0  Environment & infrastructure setup
            |
STEP 1  Build canonical identity crosswalk      <-- sequential, load-bearing
            |
        +---+---+---+---+                        <-- parallel fan-out
        |   |   |   |   |
STEP 2  BioGRID  GO  STRING  gene2pubmed         (stamp canonical_gene_id, stage)
        |   |   |   |   |
        +---+---+---+---+
            |
STEP 3  Validation gate (resolution rate, unmapped log)
            |
        ==> Layer 5 (harmonization) begins
```

---

## STEP 0 — Environment & Infrastructure (Week 1, days 1–2)

**Goal:** A reproducible pipeline skeleton before any data moves.

Tasks:
- Provision Postgres instance on RIS (system of record for all staging tables).
- Set up pipeline orchestration. For a 10-week MVP use **plain Python + a Makefile**, or **Prefect** if the team wants observability. Avoid Airflow (too heavy).
- Create the repo structure: one parser module per source, shared crosswalk utilities, config for paths and credentials.
- **Register for an NCBI API key** (free, raises E-utilities limit from 3 to 10 req/sec). Store in environment config, never in code.
- Set up a raw-file staging area on RIS storage (downloads land here untouched, parsers read from here).

Deliverable: empty-but-runnable pipeline; `make ingest` exists and does nothing yet.

---

## STEP 1 — Canonical Identity Crosswalk (Week 1, days 3–7)

**Goal:** A single table mapping every external ID type to one internal canonical gene ID, for human and mouse. This is the highest-priority deliverable in the entire layer.

### Why it's the spine
Every source uses a different identifier for the same gene:

| Source | Identifier type |
|--------|-----------------|
| BioGRID ORCS | Gene symbol + BioGRID ID |
| NCBI Gene | Entrez Gene ID |
| Gene Ontology (GAF) | UniProt accession |
| STRING | Ensembl protein ID (ENSP) |
| gene2pubmed | Entrez Gene ID |

Without a crosswalk these tables cannot be joined. `Acod1` / Entrez `16365` / a UniProt accession / an ENSP are all one gene wearing four badges.

### Source files (all bulk download)
- NCBI `gene_info` — Entrez IDs, official symbols, alias lists, per organism
- NCBI `gene_orthologs` — mouse ↔ human ortholog pairs
- UniProt `idmapping` — Entrez ↔ UniProt
- Ensembl `idmapping` / BioMart export — Entrez ↔ Ensembl protein

### Target schema
```
crosswalk
---------
canonical_gene_id   TEXT  PK     (internal stable ID, e.g. RETICLE_<entrez>)
entrez_id           BIGINT
symbol              TEXT
aliases             TEXT[]
uniprot_ids         TEXT[]       (can be many-to-one)
ensembl_protein_ids TEXT[]       (can be many-to-one)
biogrid_id          BIGINT
organism            TEXT         (human | mouse)
ortholog_group_id   TEXT         (links mouse <-> human counterparts)
status              TEXT         (active | deprecated | merged)
```

### Resolution logic (the messy part — budget extra time)
- Anchor canonical ID on **Entrez Gene ID** (most stable, most widely cross-referenced).
- Build a symbol+alias lookup so BioGRID symbols resolve. Handle **case-insensitivity** and **alias collisions** (a symbol that has referred to different genes over time).
- Handle **many-to-many** UniProt/Ensembl relationships explicitly — store arrays, don't silently pick one.
- Map deprecated/merged Entrez IDs forward to their current ID (`gene_history` file from NCBI).
- Build `ortholog_group_id` from `gene_orthologs` so mouse/human counterparts are linkable (needed for cross-species RAG and Darkness Rating later).

### Known hazards
- Symbol reuse across time (same symbol, different gene in old vs. new annotations).
- Many-to-many ortholog relationships (not always 1:1 mouse↔human).
- Withdrawn/merged IDs in older BioGRID screens.
- Pseudogenes and gene families with near-identical symbols.

Deliverable: populated `crosswalk` table; a reusable `resolve(external_id, id_type, organism) -> canonical_gene_id` function used by all Step 2 parsers.

---

## STEP 2 — Stage Each Source (Week 2)

Once the crosswalk exists, these run in parallel. Each parser: read raw file → parse → stamp `canonical_gene_id` via the resolver → write staging table → log unmapped rows.

### 2a. BioGRID ORCS (the primary substrate)
- **Acquire:** full pre-compiled bulk dump (open access, no license). Re-pull quarterly. Reserve REST API only for single newly-added screens between dumps.
- **Parse into two tables:**
```
stg_screens
-----------
screen_id           PK
pmid
screen_type_raw                 (KO / CRISPRa / CRISPRi — as curated, may be sparse)
cell_line
cell_type
organism
library
analysis_method                 (MAGeCK / STARS / DRUGz / ...)
significance_threshold_raw
phenotype
raw_metadata        JSONB        (keep everything; Layer 5 + LLM curation read this)

stg_screen_genes
----------------
screen_id           FK
canonical_gene_id   FK           (stamped via resolver)
gene_symbol_raw                  (preserve original for audit)
score                            (author-provided gene-level score)
score_2                          (e.g. FDR, if present)
rank
is_hit_reported     BOOLEAN      (as flagged by original authors)
```
- **Note:** stores gene-level scores, not raw sgRNA reads. Directionality and harmonization are NOT done here — `screen_type_raw` and thresholds are staged as-is for Layer 5.

### 2b. Gene Ontology
- **Acquire:** GAF files (Gene Association Format), one per organism (human, mouse), plus the OBO ontology file for the term hierarchy.
- **Parse:**
```
stg_go_annotations
------------------
canonical_gene_id   FK           (resolved from UniProt accession in GAF)
go_term_id
go_aspect                        (BP / MF / CC)
evidence_code                    (needed to filter low-quality annotations later)
go_term_specificity              (depth in ontology / IC score — for Darkness Rating)
```
- **Note:** keep evidence codes and term specificity — Layer 6 stages them; Module 6's "filter out generic terms like protein binding" logic happens in Layer 5/Darkness Rating, not here.

### 2c. STRING
- **Acquire:** per-organism bulk files (`protein.links`, `protein.info`) for human and mouse.
- **Parse:**
```
stg_string_edges
----------------
canonical_gene_id_a  FK          (resolved from ENSP)
canonical_gene_id_b  FK
combined_score                   (STRING confidence 0–1000)
organism
```
- **Note:** STRING is protein-level; resolve ENSP → canonical gene ID. Used later for pathway/complex membership in co-regulation detection.

### 2d. gene2pubmed (publication counts)
- **Acquire:** NCBI `gene2pubmed` bulk file (already Entrez-keyed — easiest source).
- **Parse:**
```
stg_gene_pubs
-------------
canonical_gene_id   FK
pmid
```
- Publication *count* per gene (for Darkness Rating) is a Layer 5 aggregation over this table — Layer 6 just lands the gene→PMID links.

### PubMed full text — explicitly NOT staged in Layer 6
Abstract/full-text retrieval is query-specific (RAG, Layer 2) and curation-specific (Methods sections, Layer 5 LLM job). These are fetched **live via E-utilities** with caching, not bulk-staged. Layer 6's only PubMed artifact is the gene→PMID link table (2d).

Deliverable: five populated staging tables, each with `canonical_gene_id` stamped and an accompanying unmapped-rows log.

---

## STEP 3 — Validation Gate (Week 2, final days)

**Goal:** Quantify ingestion quality and surface every failure before Layer 5 consumes this data. Do not proceed past a failing gate.

### Checks
1. **ID resolution rate per source** — what % of rows resolved to a canonical gene ID?
   - BioGRID symbol resolution is the critical one. Target a high rate; investigate every miss.
2. **Unmapped gene report** — full list of unresolved identifiers per source, with the raw value, so a human can triage real-genes-we-missed vs. junk/withdrawn IDs.
3. **Organism consistency** — every gene tagged human or mouse; no nulls, no cross-contamination.
4. **Referential integrity** — every `canonical_gene_id` in a staging table exists in `crosswalk`.
5. **Coverage sanity** — counts roughly match source expectations (e.g. screen count in the ballpark of BioGRID's published total for human+mouse).
6. **Spot-check anchors** — manually verify a few known genes resolve correctly across all sources (e.g. confirm Acod1/Irg1 unifies; confirm a known IFNG-pathway gene maps cleanly). Use the lab's own screen genes as test anchors.

### Output
A short validation report (auto-generated each run): resolution rates, unmapped counts, failed checks. This becomes the artifact that signs off Layer 6 as complete.

Deliverable: passing validation report; documented resolution rate; triaged unmapped list.

---

## Timeline Summary

| Week | Focus | Key deliverable |
|------|-------|-----------------|
| 1 (d1–2) | Infra setup | Runnable empty pipeline, Postgres, NCBI API key |
| 1 (d3–7) | Identity crosswalk | Populated `crosswalk` + `resolve()` function |
| 2 (early) | Source parsers | 5 staging tables, canonical IDs stamped |
| 2 (late) | Validation gate | Passing validation report; ready for Layer 5 |

This fits the front of the 10-week MVP and maps onto the existing roadmap's "Weeks 1–2: Data Ingestion." Note: the *directionality mapping* the original plan lists under Weeks 1–2 is Layer 5 work — Layer 6 deliberately stops at staging so harmonization gets clean inputs.

---

## Risks & Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| Gene ID resolution is messier than expected (eats schedule) | High | Front-load Step 1; budget extra; accept partial coverage with logged misses rather than blocking |
| BioGRID metadata too sparse for later directionality | High (Layer 5 problem, surfaces here) | Stage full `raw_metadata` JSONB so nothing is lost; LLM curation backfills in Layer 5 |
| Many-to-many ortholog / UniProt mappings mishandled | Medium | Store arrays + ortholog groups explicitly; never silently collapse |
| Source refresh cadence mismatch | Medium | Keep sources as independent staging tables; per-source re-pull |
| Flat-file storage bottleneck downstream | Medium | Use Postgres (not flat files) as system of record from the start |
| PubMed full-text paywalls | Low (deferred) | Abstracts-only for MVP; PMC full-text as v2 |

---

## What Layer 6 Explicitly Does NOT Do
- No score harmonization across MAGeCK/STARS/DRUGz (Layer 5).
- No directionality assignment (Layer 5, uses LLM curation).
- No three-state presence computation (Layer 5).
- No Darkness Rating calculation (Layer 5/6 boundary — staged inputs only).
- No merging of sources into the unified reference set (Layer 5).
- No PubMed full-text bulk ingestion (live/cached retrieval in Layers 2 & 5).

These boundaries keep ingestion clean, debuggable, and independently refreshable.

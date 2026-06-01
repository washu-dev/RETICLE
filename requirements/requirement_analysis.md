# RETICLE — Full Conversation Export
**Rationale Engine To Inform CRISPR List Entities**  
**Date:** May 31, 2026  
**Participants:** Biomedical / Gene Researcher (Domain Expert) · Software Solutions Architect  
**Source Material:** DTRC_Update2_AO.pdf — Prep meeting slides, 04/28/26

---

## Table of Contents

1. [Project Background — RETICLE Presentation Summary](#1-project-background)
2. [E2E Workflow Diagram — Build Session](#2-e2e-workflow-diagram)
3. [Input Layer Elaboration](#3-input-layer-elaboration)
4. [Software Stack & Storage Architecture](#4-software-stack--storage-architecture)
5. [Diagram Redesign — Readability Pass](#5-diagram-redesign)
6. [Domain Q&A — Researcher ↔ Architect](#6-domain-qa)
   - 6.1 [What is a Ranked Gene List?](#61-what-is-a-ranked-gene-list)
   - 6.2 [Public Screen Repositories](#62-public-screen-repositories)
   - 6.3 [Single Gene vs Multiple Genes in a Screen](#63-single-gene-vs-multiple-genes)
   - 6.4 [BioGrid ORCS Screen-Level Metadata Record](#64-biogrid-orcs-screen-level-metadata)
   - 6.5 [Data Model Structure — Deep Dive](#65-data-model-structure)
7. [Artifacts Produced](#7-artifacts-produced)

---

## 1. Project Background

### What is RETICLE?

**RETICLE** = Rationale Engine To Inform CRISPR List Entities

A tool being developed with a summer computer science student program, targeting the gap between raw CRISPR screen results and actionable biological insight — particularly for poorly characterized genes (genomic "dark matter").

### The Core Problem (Three Bottlenecks)

**Bottleneck 1 — Throughput**  
CRISPR screens produce ~20,000 simultaneous genetic experiments at once. The "screen-to-publication" pipeline is rate-limited by manual bioinformatics and one-gene-at-a-time validation.

**Bottleneck 2 — Selection Bias**  
Target prioritization favors "low-hanging fruit" — genes with existing reagents, known mechanisms, and clear publication paths. Genomic "dark matter" is systematically ignored.

**Bottleneck 3 — Repository Fragmentation**  
BioGrid ORCS and DepMap exist but lack cross-screen comparison tools. Metadata is incomplete (screen type, directionality, selection method, normalization algorithm are often missing or ambiguous).

### CRISPR/Cas9 Background (from slides)

- **Cas9** = CRISPR associated protein 9; an endonuclease that creates double-stranded DNA breaks
- Directed by sgRNA (requires PAM sequence for binding)
- DNA repair mechanisms activated:
  - **NHEJ** — Non-homologous end joining (random insertion/deletion → gene knockout)
  - **HDR** — Homology directed repair (targeted insertion)

### The Biology Context — Irg1/Acod1 and Itaconate

The presenting lab studies the **IFNγ → Irf1 → Irg1/Acod1 → Itaconate** axis in macrophages:

- **Irg1** (also called Acod1) — mitochondrial enzyme, produces itaconate from cis-aconitate in the TCA cycle
- **Itaconate** — metabolite with anti-inflammatory and pro-cell death properties
- IFNγ + TNF treatment → Irg1 upregulation → Itaconate production → macrophage cell death
- Unchecked macrophage death → **cytokine storm → multi-organ failure → death**

**Key experimental findings:**
- Irg1 KO reduces IFNγ-induced death in BV2 microglia AND BMDMs (non-essential potentiator)
- Irg1 CRISPRa (overexpression) sensitizes BV2 cells to IFNγ-induced death
- 4-octyl itaconate (OI) **promotes** cytokine-induced cell death
- Citraconate (CTA) **protects** against IFNγ+TNF death
- OI and CTA have opposing activities → shared mechanisms (SDH inhibition, cysteine alkylation, Keap1) are ruled out

### CRISPR Screen Design (from slides)

| Parameter | Detail |
|---|---|
| Library | Brie (XPRn KO) + Caprano (XPRa CRISPRa) |
| Cell types | BV2 microglia, BMDMs |
| Scale | ~80,000 sgRNAs, 4/gene, ~23k genes |
| Coverage | 500 cells/sgRNA, 3 replicates |
| Conditions | Mock, IFNγ/TNF, CTA, IFNγ/TNF/CTA |
| Sequencing | Novaseq 6000 S2 1×100bp (GPP) |
| Analysis | PoolQ → FastQC → LFC vs pDNA → Z-score/FDR → Spline residuals |

### Sunbeam Classification System

8 zones based on residual XY plot (IFNγ+TNF vs Mock vs GammaTNF+CTA vs CTA):

| Zone | Description |
|---|---|
| CTA Suppressed | Protected by CTA via direct target inhibition |
| CTA Not-Suppressed | KO protects; CTA protection independent |
| CTA Unmasked | Pro-survival role only in presence of CTA |
| CTA Licensed | Pro-death role only in presence of CTA |
| CTA Rescued | CTA complements gene deficiency |
| CTA Not-Rescued | CTA protection depends on gene activity |
| CTA Survival Switch | Switch between survival/death modes |
| CTA Death Switch | Switch between death/survival modes |

### Existing Bioinformatics Tools (from slides)

| Tool | Purpose | URL |
|---|---|---|
| NCBI Gene | Gene metadata, expression, genomic context | ncbi.nlm.nih.gov/gene |
| STRING DB | PPI networks + functional enrichment analysis | string-db.org |
| ENRICHr | 465,796 terms / 225 libraries | maayanlab.cloud/Enrichr |
| GSEA / MSigDB | Gene set enrichment analysis | gsea-msigdb.org |
| BioGrid ORCS | CRISPR screen repository | orcs.thebiogrid.org |
| DepMap | Cancer functional genomics | depmap.org |

### MVP Deliverables (from slides)

1. **Curated database** — each gene annotated with functional context from published CRISPR screens
2. **User portal** — accepts ranked gene lists, queries BioGrid ORCS, DepMap, STRING, ENRICHr, CompBIO
3. **AI hypothesis engine** — RAG-mediated literature synthesis, prioritizing dark matter genes

### Validation Test Cases (from slides)

| Test | Screen Type | Question |
|---|---|---|
| 1 | Published KO (autophagy — ground truth) | Can tool recapitulate known biology? |
| 2 | CRISPRa unpublished | Can tool handle activation directionality? |
| 3 | KO suppressor + multi-treatment unpublished | Can tool use residuals/correlations across two datasets? |

### Development Phases (from Gemini prompt in slides)

**Phase 1 — Data Harmonization (Foundation)**
- Directional uniformity: unified ±score convention
- Rank percentiles: not raw ranks
- Missing data taxonomy: not-targeted ≠ not-a-hit

**Phase 2 — LLM-Assisted Metadata Curation**
- PMID → Methods section fetch → LLM structured extraction
- JSON schema: screen_type, selection_method, control_comparison
- Human-in-the-loop approval dashboard

**Phase 3 — Comparison Engine**
- Continuous/rank mode: Spearman ρ / Kendall τ
- Binary/overlap mode: Jaccard Index / Fisher's Exact

**Phase 4 — Dark Matter Illumination**
- PubMed publication count per gene
- GO annotation density (specific terms only)
- Darkness Rating: composite 0–10 score
- Surface: high pathway correlation + high darkness = novel candidate

---

## 2. E2E Workflow Diagram

### Prompt
> Build end to end workflow and capture it into a draw.io diagram.

### Approach
Generated programmatically via Python → draw.io XML (mxfile format).

### Diagram Structure (Tab 1: "RETICLE E2E Workflow")

**Layout:** Top-to-bottom vertical flow, 1600×1870px

**Main Flow (6 vertical arrows, labeled):**
```
INPUT LAYER
    ↓ "harmonized inputs"
PHASE 1 — Data Harmonization
    ↓ "scores + 3-state matrix"
PHASE 2 — LLM Metadata Curation
    ↓ "annotated screen DB"
PHASE 3 — Comparison Engine
    ↓ "comparison results"
PHASE 4 — Dark Matter Illumination
    ↓ "darkness + candidates"
PHASE 5 — AI Hypothesis Engine
    ↓ "hypotheses + report"
OUTPUT LAYER
```

**External Sources (right column, horizontal arrows — no crossing):**
- BioGrid ORCS → Phase 1 (library gene lists)
- DepMap → Phase 1 (reference distributions)
- STRING DB → Phase 3 (PPI + enrichment)
- ENRICHr → Phase 3 (pathway annotation)
- GSEA/MSigDB → Phase 3 (ranked enrichment)

**Internal Phase Flows (horizontal within band):**
- Phase 2: PMID Fetch → LLM Parser → Human Review
- Phase 5: RAG Search → Hypothesis Generator → Report Formatter

**Design Principles Applied:**
- `arcSize=3` — subtle 3% corner radius throughout
- `verticalAlign=top;align=left` — content anchors flush, no dead space
- Three strict arrow categories: vertical main flow / horizontal external / horizontal internal
- Zero crossing arrows guaranteed by geometry

---

## 3. Input Layer Elaboration

### Prompt
> For each input in input layer, create list of attributes that should be present and type of file/data that should be provided. For each file type or input type, specify what is the purpose of the input and how it will be used by the subsequent data harmonization layer.

### Six Input Nodes

| Input | Format | Required Fields | Optional Fields | Phase 1 Target |
|---|---|---|---|---|
| 1. Ranked Gene List | CSV · TSV · Excel | gene_symbol, score | rank, fdr, mean_lfc, n_sgrna, condition | Rank Percentile + Missing Data Taxonomy |
| 2. Ranking Metric Spec | JSON · Form · CLI | metric_type, positive_means, higher_is_hit | algorithm_source, score_scale, cutoff_fdr | Directional Uniformity + Rank Percentile |
| 3. Screen Type & Library | Enum · JSON · Form | crispr_modality, library_name, selection_dir | organism, library_size, cell_coverage | Directional Uniformity (primary driver) |
| 4. Experimental Context | JSON · YAML · Form | cell_type, organism, treatment_A, treatment_B | time_point_hrs, n_replicates, passage | Missing Data Taxonomy + context filter |
| 5. Query Mode & Scope | Enum · Toggle · CLI | query_scope, comparison_mode | top_n, fdr_threshold, direction_filter | Routes → Phase 3 algorithm selector |
| 6. Comparison Dataset | CSV · TSV | gene_symbol, score_cond2, condition_label | rank_2, fdr_2, mean_lfc_2 | Rank Percentile (both) + Spline Residual |

### Domain ↔ Software Bridge

| Input | Domain Concept | Software Component | Phase 1 Target |
|---|---|---|---|
| 1 | Screen phenotype result (gene → effect magnitude) | CSV/TSV parser → Gene ID normalizer → Score ingestion | Rank Percentile + Missing Data |
| 2 | Statistical scoring convention (what does +/- mean?) | Metric Config Resolver → Direction Lookup Table Builder | Directional Uniformity + Rank Percentile |
| 3 | CRISPR biology type (KO vs CRISPRa vs CRISPRi) | Library Registry → Modality Enum → Sign Flip Dispatcher | Directional Uniformity (primary) |
| 4 | Experimental design (cell model, treatment, organism) | Context Schema Validator → BioGrid ORCS Filter Builder | Missing Data Taxonomy + Context Filter |
| 5 | Research scope (single gene vs genome-scale) | Query Router → Algorithm Selector (continuous vs binary) | Routes to Phase 3 |
| 6 | Multi-condition data (enables residual analysis) | Second CSV Ingestion → Paired Score Aligner → Spline Engine | Rank Percentile (both) + Residual Calc |

### Phase 1 Component Detail

**Directional Uniformity**
- Receives from: Input 2 (metric_type, positive_means) + Input 3 (crispr_modality, selection_dir)
- Libraries: pandas · numpy · pydantic v2
- Custom: Sign convention lookup table (~80 lines)
  - Maps (modality × selection × algorithm) → ±1 rule
  - KO + viability + depleted → +1 = gene protects cell
  - CRISPRa + enriched → +1 = gene drives phenotype
- Output: Parquet: harmonized_scores.parquet

**Rank Percentile Normalization**
- Receives from: Inputs 1, 2, 3, 5, 6 + DepMap reference distributions
- Libraries: scipy.stats (rankdata) · pyarrow · numpy · pandas
- Existing: scipy.stats.rankdata per screen group (~50-line wrapper)
- Output: Parquet: percentiles.parquet

**Missing Data Taxonomy**
- Receives from: Inputs 1, 4, 6 + BioGrid ORCS library gene lists
- Libraries: scipy.sparse · sqlalchemy · requests · diskcache
- Custom: 3-state classifier (~100 lines)
  - NOT_IN_LIB (NaN) | IN_LIB_NO_HIT (0) | IN_LIB_HIT (1)
- Output: SQLite: gene_matrix.db + scipy .npz: sparse_binary_matrix.npz

---

## 4. Software Stack & Storage Architecture

### Per-Component Python Libraries

#### Phase 1 — Data Harmonization

| Component | Key Libraries | Custom Code | Output Storage |
|---|---|---|---|
| Directional Uniformity | pandas, numpy, pydantic v2 | 🔧 ~80 lines: sign convention lookup table | Parquet (harmonized_scores) |
| Rank Percentile Norm | scipy.stats, pyarrow, numpy | ✅ ~50-line wrapper | Parquet (percentiles) |
| Missing Data Taxonomy | scipy.sparse, sqlalchemy, requests, diskcache | 🔧 ~100 lines: 3-state classifier | SQLite + scipy .npz |

#### Phase 2 — LLM Metadata Curation

| Component | Key Libraries | Custom Code | Output Storage |
|---|---|---|---|
| PMID Fetch | biopython (Bio.Entrez), metapub, tenacity, lxml | ✅/🔧 ~80 lines: methods extractor | MongoDB JSON |
| LLM Parser + Schema | anthropic SDK, instructor, pydantic v2, tiktoken | 🔧 ~150 lines: ScreenMetadata model | PostgreSQL JSONB |
| Human Review Dashboard | streamlit, sqlalchemy, alembic, pandas | 🔧 ~300 lines: state machine + audit log | PostgreSQL (approved) |

#### Phase 3 — Comparison Engine

| Component | Key Libraries | Custom Code | Output Storage |
|---|---|---|---|
| Continuous Mode (Spearman) | scipy.stats, scipy.interpolate, numpy, numba, joblib | 🔧 ~200 lines: Spline Residual Calculator | Parquet + Redis (TTL=24h) |
| Binary Mode (Jaccard/Fisher) | scipy.stats, sklearn, statsmodels, numpy | ✅ ~120-line wrapper | Parquet |
| External Integrations | gseapy, stringdb, mygene, networkx | ✅ ~100-line adapter | PostgreSQL + JSON |

#### Phase 4 — Dark Matter Illumination

| Component | Key Libraries | Custom Code | Output Storage |
|---|---|---|---|
| PubMed Count | biopython, diskcache, tenacity | ✅ ~60 lines | SQLite (gene_knowledge.db) |
| GO Annotation Density | mygene, goatools, pronto, diskcache | 🔧 ~100 lines: GO depth filter (depth ≥ 3) | SQLite |
| Darkness Rating | pandas, sklearn, numpy, pyyaml | 🔧 ~50 lines: weighted composite formula | Parquet + SQLite |
| Dark Candidates | pandas, plotly, scipy.stats | ✅ ~80 lines: 2-axis scoring | Parquet + JSON |

#### Phase 5 — AI Hypothesis Engine

| Component | Key Libraries | Custom Code | Output Storage |
|---|---|---|---|
| RAG Literature Search | langchain, chromadb, sentence-transformers, biopython | 🔧 ~200 lines: biomedical RAG pipeline | ChromaDB vector store |
| Hypothesis Generator | anthropic SDK, instructor, pydantic v2, langchain | 🔧 ~150 lines: Hypothesis schema + prompts | JSON files |
| Report Formatter | jinja2, weasyprint, plotly, pandas | 🔧 ~200 lines: 5-section Jinja2 template | PDF + HTML |

**Total estimated custom code: ~2,020 lines**

### Storage Architecture Decision Matrix

| Technology | Used For | Rationale |
|---|---|---|
| Apache Parquet | Phase 1 scores · Phase 3 matrix · Phase 4 darkness | Columnar, fast analytical reads, portable |
| SQLite | Gene knowledge DB (Phase 4) · 3-state matrix (Phase 1C) | Zero-config, portable, ≤50M rows |
| PostgreSQL + JSONB | Master screen metadata (Phase 2) · enrichment results | Flexible schema + full-text search |
| MongoDB | Raw methods text (Phase 2 pre-LLM staging) | Flexible JSON documents |
| ChromaDB / FAISS | RAG vector store (Phase 5) | Semantic similarity search |
| Redis | Session cache · Spearman top-K hot results | TTL-based, sub-millisecond reads |

### Darkness Rating Formula

```
darkness_raw = (
    w1 × (1 / log(pub_count + 1))    ← publication rarity
    w2 × (1 / (n_specific_go + 1))   ← GO annotation sparsity
    w3 × (1 / (n_crispr_hits + 1))   ← screen hit rarity
)
→ MinMaxScaler → 0.0 (well-known) to 10.0 (dark)
Default weights: w1=0.4, w2=0.4, w3=0.2 (configurable via YAML)
```

---

## 5. Diagram Redesign

### Prompt
> Redo the Reticle e2e workflow diagram and increase the readability. Avoid lines criss crossing each other or over other components. Eliminate white spaces from components, reduce the radius of the rounded corner.

### Design Rules Applied (All Three Tabs)

**Rule 1 — arcSize=3**  
3% corner radius on every cell. Near-square appearance without being harsh.

**Rule 2 — Content anchoring**  
`verticalAlign=top;align=left` on all component boxes. Zero dead space above or to the left of content.

**Rule 3 — Three strict arrow categories, geometrically guaranteed non-crossing:**

| Arrow Type | Direction | Use |
|---|---|---|
| Main flow | Straight vertical ↓ | Between phase containers (center-bottom → center-top) |
| External source | Straight horizontal → | From right-column external boxes into phase container right edge |
| Internal phase | Straight horizontal → | Between sibling components within a phase band |

**Why no crossing is possible:** Main flow arrows are at x≈640 (center of 1220px content). External arrows are at x>1250 (right of all content). These two sets of arrows never share x-space. Internal arrows are fully contained within phase bands and never extend vertically.

### Three-Tab File Structure

| Tab | Purpose | Nodes | Edges | Page Size |
|---|---|---|---|---|
| RETICLE E2E Workflow | Clean end-to-end flow | 43 | 15 | 1600×1870 |
| Input Layer Detail | 6 inputs with attribute specs + domain-software bridge | 28 | 5 | 2300×1500 |
| Software Stack & Storage | Per-component library + storage decisions | 29 | 5 | 2300×2050 |

### Follow-up Prompt
> What you did for 'RETICLE E2E Workflow', can you do the same for 'RETICLE — Input Layer Elaborated' and 'Software Stack & Storage'?

Same design rules applied consistently to all three tabs. All edge references validated (0 bad refs across all tabs).

---

## 6. Domain Q&A

*Format: The researcher answers from the biology domain. The architect asks from the software/systems perspective.*

---

### 6.1 What is a Ranked Gene List?

**Architect:** What is a Ranked Gene List?

**Researcher:**

A Ranked Gene List is the foundational output of a CRISPR screen experiment. After running the screen, you extract DNA from treated and untreated cell populations, PCR-amplify the sgRNA barcodes, sequence them, and count how many cells carrying each sgRNA survived. The analysis pipeline (MAGeCK, STARS, DRUGz) collapses the 4 sgRNAs per gene into a single gene-level score answering: *did losing this gene change survival under this condition?*

**It is always a multi-gene table.** In a genome-scale screen, every row is one gene, and there are ~18,000–23,000 rows — all genes targeted by the library, ranked from most protective knockout at the top to most sensitizing at the bottom.

**Key columns:**

| Column | Meaning |
|---|---|
| gene_symbol | Gene that was knocked out (e.g. Otulin, Acod1, Rela) |
| score | Effect size — LFC, z-score, or normalized rank. Sign = direction of effect |
| rank | Position in ordered list (rank 1 = strongest hit) |
| FDR | False discovery rate — statistical confidence |
| mean_lfc | Mean log2 fold change across 4 sgRNAs |

**Real example from GammaTNF screen:**
```
Otulin   rank 1   lfc -1.52   z-score -11.7   FDR 3.99e-27
Adam17   rank 2   lfc -1.50   z-score -9.4    FDR 5.84e-17
Rela     rank 3   lfc -1.79   z-score -7.95   FDR 1.38e-11
```

Otulin rank 1 with negative LFC = cells that lost Otulin were enriched under IFNγ stress = **losing Otulin protects against IFNγ-induced death**.

**Critical complexity for software:** The sign convention is NOT universal. Interpreting the direction requires knowing simultaneously: (1) KO vs CRISPRa vs CRISPRi, (2) viability vs FACS selection, (3) comparison direction (treated minus mock vs mock minus treated), (4) which algorithm generated the score. This is why Directional Uniformity in Phase 1 is the prerequisite for any meaningful cross-screen comparison.

---

### 6.2 Public Screen Repositories

**Architect:** Is there a collection of such screens available online?

**Researcher:**

Yes — several repositories exist. This is the data foundation RETICLE is built on.

**BioGrid ORCS** (orcs.thebiogrid.org) — Most directly relevant. Curated database of published CRISPR screen results from literature. Researchers voluntarily deposit data. Allows gene-centric queries today (which screens was gene X a hit in?). Cannot currently compare full ranked lists cross-screen. Annotation is inconsistent and often incomplete.

**DepMap** (depmap.org, Broad Institute) — Most standardized and highest quality. Genome-scale KO screens across 1,000+ cancer cell lines. Consistent methodology, CERES/Chronos algorithms, excellent metadata, REST API. Limitation: entirely cancer cell viability. Does not contain IFNγ macrophage biology. Valuable as reference for essential/non-essential gene classification.

**Other sources:**
- GenomeCRISPR — older database, less maintained
- GEO (Gene Expression Omnibus) — raw data deposited but completely unstructured, no standardization
- NCBI SRA — raw sequencing reads, requires full pipeline reprocessing
- Project Score (Wellcome Sanger) — European counterpart to DepMap, high quality

**Critical honest assessment:**

> These repositories are not clean APIs you can query in real time. They are messy, partially annotated data sources that need to be ingested, cleaned, annotated, and stored in RETICLE's own master database before they are useful. Think of it as an ETL pipeline feeding a data warehouse. BioGrid ORCS and DepMap are the source systems. RETICLE's PostgreSQL database is the warehouse.

**Key data quality problems:**
- Many screens never get deposited anywhere
- Some deposits contain only hits (200 rows) not the full genome (20,000 rows)
- Format is heterogeneous: some deposit MAGeCK output directly, others Excel with scores on sheet 3
- Missing data cannot be distinguished: absent gene = not targeted vs not a hit vs not deposited

---

### 6.3 Single Gene vs Multiple Genes in a Screen

**Architect:** Going back to the ranked gene list — do they pertain to a single gene or can they contain multiple genes? Example you shared has Otulin and Adam17 plus many more. Is that what BioGRID also contains, for example BIOGRID-ORCS-SCREEN_1866-2.0.18.screen.tab.txt?

**Researcher:**

Yes — every screen result is a table of ALL genes targeted in the experiment. In a genome-scale screen that is typically 18,000–23,000 genes. Each gene gets exactly one row. Think of it like a horse race result sheet — one sheet listing all horses in finishing order.

The specific file BIOGRID-ORCS-SCREEN_1866-2.0.18.screen.tab.txt follows this structure exactly. Each row is one gene from one screen. A genome-scale deposit would have ~18,000–23,000 rows. The SCREEN_ID column is the same value on every row — just a foreign key back to the screen-level metadata:

```
SCREEN_ID   OFFICIAL_SYMBOL   SCORE   HIT   PHENOTYPE    SYSTEMATIC_NAME
1866        OTULIN            -2.41   YES   DECREASED    ENSG00000197142
1866        ADAM17            -1.89   YES   DECREASED    ENSG00000151694
1866        RELA              -1.44   YES   DECREASED    ENSG00000173039
1866        TMEM41B            0.02   NO    NEUTRAL      ENSG00000136699
```

**The critical problem — not all files contain all genes:**

| Scenario | Row count | Implication |
|---|---|---|
| Full ranked list deposited | ~18,000–23,000 rows | Use Spearman correlation (continuous mode) |
| Hits only deposited | ~50–500 rows | Use Jaccard/Fisher (binary mode) |
| Unknown coverage | Unclear | Must inspect file + read paper |

**The 3-state missing data problem:**

A gene absent from a file could mean:
1. Gene was in library but not a hit (score exists, just not deposited)
2. Gene was not in the library at all (was never screened)
3. Researcher only deposited hits (score exists but not reported)

These three states are biologically different and require different algorithmic treatment. This is the core motivation for the 3-state taxonomy and the LIBRARY_GENE junction table in the data model.

**Data model implication:**

```
Screen (1) ────────── Screen_Genes (many)
  screen_id              screen_id (FK)
  screen_type            gene_symbol
  selection_method       score
  library_name           percentile
  coverage_type          hit_flag
    [FULL|HITS_ONLY|UNKNOWN]  direction
                          state
                            [FULL_SCORE|HIT_ONLY|NOT_IN_LIB]
```

The `coverage_type` field gates which comparison algorithm Phase 3 uses for that screen — not a user choice but a data-driven routing decision.

---

### 6.4 BioGrid ORCS Screen-Level Metadata

**Architect:** Walk me through the screen level metadata record in BioGrid ORCS.

**Researcher:**

**What BioGrid ORCS formally provides:**

```
SCREEN_ID           1866
SCREEN_NAME         "Genome-wide CRISPR screen for regulators of 
                     IFNγ-induced cell death in macrophages"
PUBMED_ID           31730851
ORGANISM            Homo sapiens
CELL_LINE           THP-1
SCREEN_TYPE         CRISPR
LIBRARY             Brunello
CONDITION           IFNγ treatment
PHENOTYPE           Cell viability
HIT_SCORE_TYPE      Z-score
```

**What you actually need to interpret the scores:**

```
Screen 1866
Modality:    KO (Cas9 knockout)
Selection:   Positive selection (survival advantage)
Comparison:  IFNγ treated (Day 5) vs Mock treated (Day 5)
Direction:   Treated minus Mock (negative LFC = protected)
Algorithm:   MAGeCK v0.5.9
Coverage:    Full genome (18,454 genes deposited)
Replicates:  3 biological replicates
Hit threshold: FDR < 0.10
Library:     Brunello (19,114 gene targets, 4 sgRNAs each)
Organism:    Human
```

**The Six Critical Gaps:**

**Gap 1 — Screen Modality Often Ambiguous**  
SCREEN_TYPE says "CRISPR" but does not reliably distinguish KO / CRISPRa / CRISPRi. These produce biologically inverted results. Must read paper.

**Gap 2 — Selection Direction Rarely Explicit**  
PHENOTYPE = "Cell viability" doesn't tell you if enriched sgRNAs mean gene loss helps or hurts. Positive vs negative selection flips the biological interpretation entirely.

**Gap 3 — Comparison Direction Often Missing**  
Treated vs Untreated, or Untreated vs Treated? If an author calculated fold change in the opposite order, every score has an opposite sign even though the biology is identical. Two screens that should look perfectly correlated appear uncorrelated.

**Gap 4 — Hit Threshold Not Standardized**  
FDR 0.05 vs FDR 0.25 produces very different hit lists. A screen calling at FDR 0.25 will always appear to share more hits with other screens — not because the biology is more similar but because more genes were called.

**Gap 5 — Library Information Incomplete**  
Library name is sometimes missing or custom. Library size is the denominator for rank percentile normalization. Library composition determines which genes were actually screened.

**Gap 6 — Replicate Information Absent**  
Two replicates vs five replicates deserve different statistical confidence even if FDR values are similar. Not captured in metadata.

**Implication for RETICLE:**  
Every screen record needs a **metadata confidence score** (0.0–1.0) indicating how complete and reliable the annotation is. This feeds into the comparison engine's weighting — not just which screens are most similar, but which similar screens you can actually trust.

The gap between what BioGrid provides and what RETICLE needs is precisely why Phase 2 (LLM metadata curation + human-in-the-loop review) is not optional — it is the foundational data quality layer that makes all downstream analysis meaningful.

---

### 6.5 Data Model Structure

**Architect:** Let's dive into the data model structure.

**Researcher:**

The data model has six first-class entities. The separation between them reflects biological distinctions, not just software convenience.

#### Core Entity Relationship

```
PUBLICATION ──── SCREEN ──── LIBRARY
                   │               │ (junction)
              METADATA_ANNOTATION  LIBRARY_GENE
                   │
            SCREEN_CONDITION (many per screen)
                   │
            SCREEN_COMPARISON (pairs of conditions)
                   │
            SCREEN_GENE_SCORE ──── GENE ──── GENE_ORTHOLOG
                   │
            RESIDUAL_ANALYSIS (optional, multi-condition)
                   │
            RESIDUAL_GENE_SCORE
```

---

#### PUBLICATION

```sql
publication_id      PK
pmid                UNIQUE, INDEXED
title               
journal             
year                
doi                 
methods_text        TEXT   -- extracted by Phase 2 LLM pipeline
full_text_available BOOLEAN
abstract_text       TEXT   -- fallback if full text unavailable
```

*Why separate:* One paper frequently reports multiple screens. Collapsing publication into screen loses the ability to navigate from paper to all its screens, and loses the methods text source tracking.

---

#### LIBRARY

```sql
library_id          PK
library_name        -- Brie | Brunello | GeCKOv2 | Caprano | custom
library_version     
organism            -- human | mouse | other
total_genes         INTEGER   -- e.g. 19,674 for Brunello
sgrnas_per_gene     INTEGER   -- typically 4 or 6
total_sgrnas        INTEGER
source              -- Addgene | GPP | custom
```

```sql
LIBRARY_GENE  (junction table)
  library_gene_id   PK
  library_id        FK → LIBRARY
  gene_id           FK → GENE
  n_sgrnas          INTEGER
```

*Why separate + junction:* Library size is the denominator for rank percentile normalization. Library composition defines what was screened — the ground truth for missing data taxonomy. The LIBRARY_GENE junction table is populated once per library and queried for every 3-state classification.

---

#### GENE

```sql
gene_id             PK
gene_symbol         INDEXED   -- e.g. OTULIN (human) or Otulin (mouse)
entrez_id           UNIQUE per organism
ensembl_id          
organism            -- human | mouse
chromosome          
gene_type           -- protein_coding | lncRNA | pseudogene | other
description         TEXT
darkness_score      FLOAT     -- 0.0 to 10.0 (Phase 4 output)
pubmed_count        INTEGER
n_specific_go_terms INTEGER
last_darkness_update DATE
```

```sql
GENE_ORTHOLOG  (cross-species mapping)
  gene_id_1    FK → GENE   -- e.g. mouse Otulin
  gene_id_2    FK → GENE   -- e.g. human OTULIN
  confidence   -- HIGH | MEDIUM | LOW
  source       -- Ensembl | NCBI | manual
```

*Why ortholog table:* Mouse screens use lowercase (Otulin, Acod1) and human screens use uppercase (OTULIN, ACOD1). These are functionally equivalent orthologs. Without this mapping, cross-species comparison treats them as unrelated genes and produces meaningless Spearman correlations.

---

#### SCREEN

```sql
screen_id               PK
biogrid_screen_id       -- external reference, nullable
depmap_screen_id        -- external reference, nullable
publication_id          FK → PUBLICATION
library_id              FK → LIBRARY
organism                -- human | mouse | other
cell_line               -- THP-1 | BV2 | HeLa | primary | etc.
cell_type               -- macrophage | microglia | cancer | T cell
screen_modality         -- KO | CRISPRa | CRISPRi
algorithm               -- MAGeCK | STARS | DRUGz | custom
algorithm_version       
coverage_type           -- FULL | HITS_ONLY | UNKNOWN
total_genes_deposited   INTEGER
annotation_source       -- BIOGRID | DEPMAP | MANUAL | LLM_EXTRACTED
annotation_confidence   FLOAT (0.0 to 1.0)
direction_verified      BOOLEAN
created_at              
updated_at              
```

*Note:* Treatment condition, comparison direction, and selection method are NOT on this table — they belong on child entities (SCREEN_CONDITION and SCREEN_COMPARISON) because one screen can have multiple conditions and multiple comparisons.

---

#### SCREEN_CONDITION

```sql
condition_id        PK
screen_id           FK → SCREEN
condition_name      -- e.g. "IFNγ+TNF", "Mock", "CTA", "IFNγ+TNF+CTA"
condition_type      -- TREATMENT | CONTROL | DRUG | COMBINATION
treatment_agent     -- e.g. "IFNγ + TNF"
concentration       -- e.g. "10 U/ml IFNγ + 10 ng/ml TNF"
timepoint_hours     -- e.g. 24
```

*Why separate:* The BV2 suppressor screen has **four conditions**: Mock, IFNγ+TNF, CTA, IFNγ+TNF+CTA. Each is a separate arm of the same experiment. Collapsing into screen loses this structure entirely.

---

#### SCREEN_COMPARISON

```sql
comparison_id           PK
screen_id               FK → SCREEN
condition_a_id          FK → SCREEN_CONDITION  -- numerator
condition_b_id          FK → SCREEN_CONDITION  -- denominator
comparison_label        -- e.g. "GammaTNF_vs_Mock"
selection_method        -- VIABILITY | FACS | DROPOUT | OTHER
selection_direction     -- POSITIVE | NEGATIVE
comparison_direction    -- A_MINUS_B | B_MINUS_A
coverage_type           -- FULL | HITS_ONLY
hit_threshold_type      -- FDR | SCORE | CUSTOM
hit_threshold_value     -- e.g. 0.10
n_replicates            INTEGER
```

*Why separate:* From four conditions, six pairwise comparisons are possible. Each produces a separate ranked gene list. The comparison is the entity that maps to the ranked gene list — not the screen.

The six comparisons from the BV2 suppressor screen:
```
GammaTNF vs Mock          ← primary screen result
GammaTNF_CTA vs CTA       ← CTA-suppressed condition
CTA vs Mock               ← drug effect alone
GammaTNF_CTA vs Mock      ← combined effect
GammaTNF_CTA vs GammaTNF  ← CTA effect on top of cytokine
CTA vs GammaTNF           ← inverse comparison
```

The spline residual analysis compares comparison 1 (GammaTNF_vs_Mock) against comparison 2 (GammaTNF_CTA_vs_CTA). This is what enables the Sunbeam zone classification.

---

#### SCREEN_GENE_SCORE

```sql
score_id                PK
comparison_id           FK → SCREEN_COMPARISON
gene_id                 FK → GENE
raw_score               FLOAT
normalized_percentile   FLOAT
rank                    INTEGER
fdr                     FLOAT
mean_lfc                FLOAT
n_sgrnas_scored         INTEGER
hit_flag                BOOLEAN
direction_flag          -- POSITIVE | NEGATIVE | NEUTRAL
adj_score               FLOAT   -- after directional uniformity
data_state              -- FULL_SCORE | HIT_ONLY | NOT_IN_LIB
```

*Scale:* A genome-scale screen with 20,000 genes and 6 comparisons generates 120,000 rows. At BioGrid ORCS scale (hundreds of screens), this table contains **tens of millions of rows**. → Apache Parquet, partitioned by screen_id.

- `adj_score` = Phase 1A output (raw_score × sign_multiplier)
- `data_state` = Phase 1C output (3-state classification from library-gene cross-reference)

---

#### RESIDUAL_ANALYSIS & RESIDUAL_GENE_SCORE

```sql
RESIDUAL_ANALYSIS
  residual_id         PK
  screen_id           FK → SCREEN
  comparison_a_id     FK → SCREEN_COMPARISON
  comparison_b_id     FK → SCREEN_COMPARISON
  analysis_label      -- e.g. "CTA_suppressor_screen"
  spline_knots        JSONB   -- spline parameters for reproducibility

RESIDUAL_GENE_SCORE
  score_id            PK
  residual_id         FK → RESIDUAL_ANALYSIS
  gene_id             FK → GENE
  score_a             FLOAT   -- from comparison A
  score_b             FLOAT   -- from comparison B
  residual_score      FLOAT
  sunbeam_zone        ENUM    -- 8 categories
  rank                INTEGER
```

**Sunbeam zone values:**
```
CTA_SUPPRESSED | CTA_NOT_SUPPRESSED | CTA_UNMASKED | CTA_LICENSED
CTA_RESCUED | CTA_NOT_RESCUED | CTA_SURVIVAL_SWITCH | CTA_DEATH_SWITCH
```

---

#### METADATA_ANNOTATION

```sql
annotation_id         PK
screen_id             FK → SCREEN
annotated_by          -- LLM | HUMAN | HYBRID
annotation_timestamp  
llm_confidence        JSONB   -- per-field confidence scores
review_status         -- PENDING | IN_REVIEW | APPROVED | REJECTED
reviewer_id           FK → USER
reviewed_at           
changes_made          JSONB
review_notes          TEXT
```

LLM confidence JSONB example:
```json
{
  "screen_modality": 0.95,
  "selection_method": 0.87,
  "comparison_direction": 0.61,
  "algorithm": 0.99,
  "coverage_type": 0.43
}
```

Low confidence on `comparison_direction` (0.43) signals the human reviewer to pay particular attention to that field.

---

#### Storage Technology Map

| Entity / Table | Technology | Rationale |
|---|---|---|
| SCREEN_GENE_SCORE, RESIDUAL_GENE_SCORE | Apache Parquet (partitioned by screen_id) | Tens of millions of rows; columnar reads for Spearman correlation |
| SCREEN, SCREEN_CONDITION, SCREEN_COMPARISON, PUBLICATION, METADATA_ANNOTATION | PostgreSQL + JSONB | Relational joins + flexible metadata fields |
| GENE, LIBRARY, LIBRARY_GENE, GENE_ORTHOLOG | SQLite (small) / PostgreSQL (production) | Reference data, read-heavy, rarely updated |
| RESIDUAL_ANALYSIS spline params + comparison cache | Redis (TTL expiry) | Hot results for repeated queries |

#### Open Architecture Questions

1. **SCREEN_GENE_SCORE at scale:** Keep in Parquet with metadata catalog, or use DuckDB for SQL semantics on Parquet files without a full database server?

2. **GENE_ORTHOLOG joins:** Handle at query time with a JOIN, or pre-compute unified canonical_gene_id at ingestion time and store it on SCREEN_GENE_SCORE?

---

## 7. Artifacts Produced

| File | Location | Description |
|---|---|---|
| RETICLE_E2E_Workflow.drawio | /RETICLE/ | 3-tab draw.io file with all diagrams |
| RETICLE_conversation_export.md | /RETICLE/ | This document |

### draw.io File Contents

**Tab 1 — RETICLE E2E Workflow**  
Clean end-to-end pipeline: 6 phases, labeled vertical arrows, external sources right column, internal phase flows. 43 nodes, 15 edges. 1600×1870px.

**Tab 2 — Input Layer Detail**  
6 input nodes with full attribute specs (required/optional fields, formats, domain context). Domain-Software Bridge: 6-column mapping (Input → Domain Concept → Software Component → Phase 1 Target). Phase 1 component detail with explicit input-to-component routing. 28 nodes, 5 edges. 2300×1500px.

**Tab 3 — Software Stack & Storage**  
5 phase sections each with: Python library list per component, custom vs existing code indicator, storage output (format + technology + schema). Storage Architecture summary panel. 29 nodes, 5 edges. 2300×2050px.

---

*End of conversation export*  
*Generated: May 31, 2026*

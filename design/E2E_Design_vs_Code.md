# RETICLE — Design vs. Code Audit

**Source of truth:** `design/E2E_Workflow.drawio` (3 tabs: E2E Workflow, Input Layer Detail, Software Stack & Storage)
**Date:** 2026-07-10

## Legend
- ✅ **Done** — implemented and matches design intent
- 🟡 **Partial** — logic exists but differs from design (format, library, scope, or backed by mock data)
- ❌ **Missing** — no implementing code found
- 🔵 **Different-by-design** — the repo solves it another way than the diagram

## Big picture

The design describes a linear 5-phase scientific pipeline with a specific storage stack
(Parquet · SQLite · PostgreSQL+JSONB · ChromaDB · Redis · MongoDB) and ~2,020 lines of custom code.

What actually exists is **three loosely-coupled surfaces plus an abandoned pair of stubs**:

| Surface | Role | Reality |
|---|---|---|
| `prototype/` | Reference science (SQLite, stdlib) | Where Phase 1/2/4 logic actually lives |
| `scripts/` + `database/` | BioGRID → PostgreSQL/RDS warehouse ETL | Ingestion/dedup/versioning — **not** the design's Phase 1 math |
| `api/` + `webapp/` + `demo/` | FastAPI + React Native Web productization | Explorer path real (RDS); main upload→query path mock-backed |
| `graph-ui/` + `graph-api/` | Documented (`GRAPH_EXPLORER.md`) | **Empty stubs — node_modules only** |

Storage divergence: none of Parquet-as-Phase-1-deliverable, MongoDB, ChromaDB, or Redis is used.
The realized store is **AWS RDS PostgreSQL** (warehouse + `reticle` schema) and **SQLite** (`reticle_master.db` in the prototype).
None of the design's headline libraries (anthropic SDK, instructor, streamlit, biopython, metapub, mygene pkg, goatools, langchain, chromadb, weasyprint, jinja2, sentence-transformers, gseapy, scipy in the API) are imported in production code.

---

## Input Layer — 6 inputs

| # | Input | Status | Where |
|---|---|---|---|
| 1 | Ranked Gene List (CSV/TSV/xlsx) | 🟡 | `webapp/src/utils/geneParser/*` (real parser + score-col detect + ID resolution via `crosswalk.min.json`); prototype reads TSV screen files (`harmonize_scores.py::load_screen_df`). **No .xlsx.** |
| 2 | Ranking Metric Spec | 🟡🔵 | Hard-coded registries, not a user spec: `harmonize_scores.py` (`DIR_POS/DIR_NEG/SIG_MAG/SIG_P`), `scripts/compute_gene_coessentiality.py::SCORE_TYPE_BUCKETS` |
| 3 | Screen Type & Library | 🟡 | `SCREEN_TYPE`/`METHODOLOGY` drive signs (`harmonize_scores.py`). "Library" = perturbation type; **no gene-library membership list** |
| 4 | Experimental Context | 🟡 | `screen_metadata` table + `classify_conditions*.py`, `llm_metadata_extractor.py`, `build_stress_facts.py` |
| 5 | Query Mode & Scope | 🟡 | `COVERAGE_TYPE=FULL\|HIT_ONLY` routes continuous vs binary; `api/models/query.py` `QueryRequest` |
| 6 | Comparison Dataset | 🟡🔵 | The harmonized BioGRID corpus itself is the comparison set; **no external user comparison dataset intake** |

---

## Phase 1 — Data Harmonization

| Deliverable | Status | Where / divergence |
|---|---|---|
| Directional Uniformity (sign lookup → adj_score + direction_flag; Parquet) | 🟡 | `prototype/script/harmonize_scores.py` (`selection_multiplier`, `perturbation_mult`, `resolve_s_raw`, `HARMONIZED_SCORE`); LLM overrides in `directionality_mapper.py`/`apply_directionality.py`/`fix_directionality.py`. **Divergence:** output is SQLite `harmonized_scores` table, not `harmonized_scores.parquet`; no pydantic v2; richer than flat lookup table |
| Rank Percentile Normalization (scipy.stats.rankdata; rank/lib_size×100; Parquet) | 🟡 | `harmonize_scores.py::add_rank_columns` uses pandas `.rank` (not `scipy.stats.rankdata`), maps to `[-1,1]` (not `[0,100]`), denominator = max measured rank (not library_size). Also `scripts/compute_gene_coessentiality.py` does a `[0,1]` per-screen pct rank. SQLite, not Parquet |
| Missing Data Taxonomy (3-state NOT_IN_LIB/NO_HIT/HIT; BioGRID cross-ref; sparse .npz + gene_matrix.db) | 🟡❌ | Only **2-state** `IS_HIT` + NaN (`harmonize_scores.py`) — conflates NOT_IN_LIB and NO_HIT. **No BioGRID library cross-ref.** Matrices built (`build_screen_matrix.py`, `build_coessential_matrix.py` → `.npz`) but dense-with-NaN, not `scipy.sparse`; **no `gene_matrix.db`** |

> **Note on `scripts/`:** `hpc_etl_pipeline.py`, `staging_loader.py`, `cpu_etl_load_only.py`, `gpu_etl_dedup_only.py`, `maintenance.py` are a **BioGRID→Postgres warehouse ETL** (staging→dedup→fact tables, versioned) — ingestion, *not* the design's harmonization. `compute_gene_coessentiality.py` is the closest to the design's normalization but is an exploratory warehouse script, not the Parquet deliverables.

---

## Phase 2 — LLM-Assisted Metadata Curation

| Deliverable | Status | Where / divergence |
|---|---|---|
| PMID Fetch & Methods Extract (biopython/metapub → PMC methods → MongoDB) | ❌🔵 | No biopython/metapub/MongoDB. `prototype/script/llm_metadata_extractor.py` is now **rule-based (no LLM/network)** over ingested BioGRID fields → SQLite `screen_metadata_curated`. NCBI access exists elsewhere (urllib, for Phase 4), not methods extraction |
| LLM Parser + Schema Validation (anthropic + instructor + pydantic → PostgreSQL JSONB) | 🟡🔵 | Uses **WashU OpenAI-compatible gateway**, not Anthropic: `llm_client.py` (`WashULLMClient`), `classify_conditions_llm.py`, `directionality_mapper.py`. Hand-rolled enum/JSON validation, **no instructor/pydantic**, no JSONB |
| Human-in-the-Loop Review (streamlit state machine) | ❌ | No streamlit. Only binary `status="needs_review"` flags on frozen JSON artifacts; no review UI or state machine |

---

## Phase 3 — Comparison Engine

| Deliverable | Status | Where / divergence |
|---|---|---|
| Continuous/Rank — Spearman/Kendall + Spline Residual → 8 Sunbeam zones (Parquet+Redis) | ❌ | **Absent in `api/`** — scipy not even a dependency. `rho` field is `AVG(percentile_score)` mislabeled (`mock_data_service.py`), or hard-coded in mock. Spline/Kendall/Sunbeam appear nowhere. Prototype has `compute_correlations.py`/`build_coessential_matrix.py` but **not ported to API** |
| Binary/Overlap — Jaccard + Fisher's exact + BH-FDR (Parquet) | ❌ | No Jaccard/Fisher/Benjamini code anywhere; `fdr` is a passive field set to `0.0`/mock |
| External Tool Integrations adapter (STRING/Enrichr/GSEA → unified schema) | 🟡 | Only **STRING** is genuinely wired (`api/services/external_sources.py::string_network/string_partners`, live HTTP). No networkx enrichment. Enrichr/gseapy/GSEA/MSigDB absent |

**External data sources:** STRING ✅ live · NCBI/PubMed ✅ live (bonus, drives Phase 4) · MyGene.info ✅ live · **BioGRID ORCS ❌** (only mock ID strings + warehouse ingestion, no live API) · **DepMap ❌** · **Enrichr/GSEA/MSigDB ❌**

---

## Phase 4 — Dark Matter Illumination

| Deliverable | Status | Where / divergence |
|---|---|---|
| PubMed Count (Bio.Entrez + diskcache → SQLite) | ✅🟡 | `external_sources.py::pubmed_count` (prototype + API), NCBI esearch via **urllib** (not biopython), cache in SQLite/`external_cache` table (not diskcache) |
| GO Annotation Density (mygene + goatools, depth≥3) | 🟡 | `external_sources.py::gene_annotation` via **MyGene.info HTTP** (not mygene pkg / goatools); counts all GO terms flat — **no depth≥3 filter** |
| Darkness Rating (w1·pub+w2·GO+w3·hits, MinMaxScaler 0–10) | 🟡 | `external_sources.py::darkness` = `10*(0.6·pub+0.4·GO)` — **2-term, missing w3·hits**; clamp not sklearn MinMaxScaler |
| Dark Candidates (2-axis corr×darkness → top_N_candidates.json) | ❌ | No backend candidate generator / `top_N_candidates.json`. The corr×darkness view exists only as **frontend viz** (`DarkGeneScatter.jsx`) on mock data |

---

## Phase 5 — AI Hypothesis Engine

| Deliverable | Status | Where |
|---|---|---|
| RAG Literature Search (langchain + chromadb + BioBERT) | ❌ | No langchain/chromadb/embeddings. `pubmed_abstracts()` docstring says "for RAG" but no vector store/retrieval |
| Hypothesis Generator (anthropic + instructor, Hypothesis schema) | ❌ | No generator/schema. "hypothesis" appears only as frontend mock strings (`GeneDetailPanel.jsx`, `mockData.js`) and a template f-string in `mock_data_service.py` |
| Report Formatter (jinja2 + weasyprint, 5-section PDF+HTML) | ❌ | No jinja2/weasyprint/PDF/report code |

> A "gene report / AI reading" surface exists in the prototype explorer (`prototype/web/app.py`, WashU-gateway LLM narrative), but it is not the design's structured Hypothesis schema or PDF report.

---

## Output Layer

| Output | Status | Where |
|---|---|---|
| Gene Report (annotation + NCBI link + tissue expression) | 🟡 | `webapp/src/components/GeneDetailPanel.jsx` (mock) + real explorer `api/services/explorer_gene.py` (RDS). **No tissue expression** anywhere |
| Screen Comparison (ranked by Spearman ρ + Sunbeam zones) | 🟡 | `MatchedScreens.jsx` labelled "Spearman ρ" but ranked by avg-percentile/mock. Real screen-similarity in explorer (`/api/screen_similar`). **No Sunbeam zones** |
| Dark Candidates shortlist | 🟡 | `DarkGeneScatter.jsx` (mock UI) + real darkness algorithm in prototype |
| Validation Tests (autophagy / CRISPRa dir / multi-cond residual) | ❌ | Only free-text "suggested validation" mock strings; no structured tests |
| Exports (TSV/JSON/PDF, volcano + network plots) | ❌ | "Export CSV" button has **no onClick handler**; no PDF/TSV/volcano. Network viz exists (cytoscape/STRING SVG) but no export |

---

## Implementation map (goal → file)

- **Directional harmonization:** `prototype/script/harmonize_scores.py`, `directionality_mapper.py`, `apply_directionality.py`, `fix_directionality.py`, `validate_harmonization.py`
- **Percentile normalization:** `prototype/script/harmonize_scores.py::add_rank_columns`; `scripts/compute_gene_coessentiality.py`
- **Gene×screen matrices:** `prototype/script/build_screen_matrix.py`, `build_coessential_matrix.py`
- **Warehouse ETL (BioGRID→Postgres):** `scripts/staging_loader.py`, `hpc_etl_pipeline.py`, `cpu_etl_load_only.py`, `gpu_etl_dedup_only.py`, `maintenance.py`, `database/`
- **Metadata curation (rule/LLM):** `prototype/script/llm_metadata_extractor.py`, `classify_conditions_llm.py`, `llm_client.py`
- **Darkness / PubMed / GO / STRING:** `prototype/script/external_sources.py`, `api/services/external_sources.py`
- **Correlations:** `prototype/script/compute_correlations.py`
- **API surface:** `api/routers/{query,genes,explorer}.py`, `api/services/{mock_data_service,explorer_gene,explorer_context,explorer_network,db_service}.py`
- **Frontend (productized):** `webapp/src/` (App.tsx, UploadPage, LoadingAnalysis, ResultsPage, MatchedScreens, DarkGeneScatter, GeneDetailPanel, GraphExplorer, explorer/ExplorerPage.tsx)
- **Frontend (mock demo):** `demo/src/`
- **Science explorer web demo:** `prototype/web/app.py`, `prototype/web/index.html`
- **Abandoned stubs:** `graph-ui/`, `graph-api/` (empty; documented in `GRAPH_EXPLORER.md`)

---

## Scorecard

| Phase | Done | Partial | Missing |
|---|---|---|---|
| Input Layer (6) | 0 | 6 | 0 |
| Phase 1 (3) | 0 | 3 | 0 (taxonomy half-missing) |
| Phase 2 (3) | 0 | 1 | 2 |
| Phase 3 (3) | 0 | 1 | 2 |
| Phase 4 (4) | 1 | 2 | 1 |
| Phase 5 (3) | 0 | 0 | 3 |
| Output (5) | 0 | 3 | 2 |

**Roughly:** Phase 1 substantially prototyped (wrong format/store), Phase 4 half-built, Phase 2 done differently (rule-based + WashU LLM, no human-review UI), **Phase 3 comparison engine and Phase 5 AI hypothesis engine essentially unbuilt**, outputs are mostly mock-backed UI with no export.
</content>
</invoke>

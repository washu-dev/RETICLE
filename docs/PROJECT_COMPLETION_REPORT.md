# RETICLE — Project Completion Report

**Date:** 2026-07-24
**Backlog source:** 30 GitHub issues (`washu-dev/RETICLE`)
**Method:** Each backlog issue audited against the actual working tree (code, migrations, prototype, webapp, api, infra) and `design/E2E_Design_vs_Code.md`.

---

## Executive summary

The **foundation, app shell, and infrastructure are built and shipped**; the **analytical & AI science is real but stranded in `prototype/` (SQLite)** and not yet productionized into the Postgres warehouse + FastAPI service. The single biggest structural gap across the whole backlog is **"productionize the prototype."**

| Bucket | Count | Issues |
|---|---|---|
| ✅ Done / shipped | 10 | #2, #4, #5, #24, #25, #29, #42, #43, #45, #51\* |
| 🟡 Partial (exists in prototype or logic-only; not productionized) | 16 | #6, #7, #8, #11, #13, #14, #15, #16, #17, #18, #19, #20, #21, #22, #46, #47 |
| ⛔ Not started | 4 | #9, #10, #12, #50 |

\* #51 is code-complete; only the Azure prod redirect-URI registration remains (external step).

**Rollup:** ~33% shipped (10/30), ~53% prototype-or-partial (16/30), ~13% untouched (4/30).

---

## Status by issue

### Foundation & data (Phase I) — solid
- ✅ **#4** Relational + JSON warehouse — versioned `staging → screen/gene/screen_gene_raw → fact/dim` schema (`database/migrations/`, `database/etl_pipeline.sql`).
- ✅ **#5** Mouse + human screens ingested (`scripts/staging_loader.py`, `scripts/hpc_staging_loader.py`). *Caveat: reads pre-downloaded files; no live BioGRID API pull.*

### Phase 1 — Harmonization (weakest area vs its P0 priority)
- ⛔ **#9** `fact_screen_gene` harmonization columns — not started; fact table has only `hit_count / hit_percentage / avg_raw_score`.
- ⛔ **#10** SQL procedures (`normalize_directional_scores`, `compute_lfc_percentiles`, `classify_missing_data`) — none exist.
- 🟡 **#11** `harmonize_scores.py` — real implementation exists but only in `prototype/script/` over SQLite; not ported to the warehouse; diverges from spec.
- ⛔ **#12** Harmonization tests — absent; only a manual `validate_harmonization.py` sanity check.

### Phases 2–5 — Curation / Comparison / Dark-matter / Hypothesis (prototype-complete, production-empty)
- 🟡 **#13** `screen_metadata_curated` — in prototype SQLite + referenced by prod code, but no `CREATE TABLE` in prod migrations.
- 🟡 **#14** `llm_metadata_extractor.py` — exists but now rule-based, no LLM; no Anthropic/Claude anywhere.
- 🟡 **#15** `correlation_analysis` + Spearman/Jaccard — implemented in Python (prototype), not SQL, not in prod schema.
- 🟡 **#16** `compute_correlations.py` — DONE as a prototype deliverable (Spearman + Jaccard + Fisher). *`scripts/compute_gene_coessentiality.py` is a different gene–gene analysis (the #46 line).*
- 🟡 **#17** `GET /api/correlations` — not in prod `api/`; prototype has adjacent `/api/screen_similar`.
- 🟡 **#18** `gene_darkness_score` table + script — no table/script; darkness computed on-demand; reserved `gene.darkness_score` column unpopulated.
- 🟡 **#19** `GET /api/dark-genes` — no standalone endpoint; dark genes ride inside `/api/query` (partly mock).
- 🟡 **#20** RAG infra — naive PubMed retrieval only; no LangChain, no vector DB/embeddings.
- 🟡 **#21** `generate_hypotheses.py` — no such file; logic inlined in prototype (real) / mock in prod.
- 🟡 **#22** `POST /api/hypotheses/generate` — not in prod; prototype has `/api/interpret`, `/api/reporter_explain`.

### Explorer analytics
- 🟡 **#46** Co-essentiality / screen-similarity matrices exist (prototype + ported `scripts/compute_gene_coessentiality.py`); endpoints prototype-only; no "EFS" artifact.
- 🟡 **#47** AI-reading endpoints exist on the WashU gateway, consumed by the webapp, served by the prototype backend; no flag-gating.

### App / API / UI / Infra — shipped
- 🟡 **#6** webapp is a deployable v0.1.0, SSO-gated, with CI/CD — but uses screen-state (not a router), and the query path is mock-backed by default.
- 🟡 **#7** "Workflow API" exists as the `/api/query` + `/api/genes` flow (no module named "workflow"; mock default).
- 🟡 **#8** LLM research bot — only prototype RAG; no production LLM endpoint. (#45's di2chat is a generic widget.)
- ✅ **#2** `demo/`, **#24** FastAPI `api/`, **#25** React `webapp/`, **#29** MAGeCK/STARS/DESeq2 gene-list parser (with tests), **#42** Explorer page merged + CloudFront, **#43** ECS deploy pipeline (resolved), **#45** di2chat widget (staging gateway).
- ✅ **#51** WashU SSO — full Entra/MSAL auth gate; pending only Azure prod redirect-URI.
- ⛔ **#50** UI unification — brainstorm only, no artifact.

---

## Cross-cutting findings

1. **Prototype ≠ production.** Nearly all Phase 1–5 science lives in `prototype/` over SQLite. "Productionize the prototype" is the meta-task behind ~16 partial issues.
2. **Backlog language is stale** — "Claude API" and "LangChain + Vector DB" vs the actual WashU OpenAI-compatible gateway (gpt-4o) + naive PubMed retrieval.
3. **Mock-data default** — `/api/query` returns mock data unless `AWS_DB_HOST` is set.
4. **`graph-ui/` & `graph-api/` are vestigial** — the Explorer lives in `webapp/`.
5. **Recent ETL hardening** (split-pipeline final-table load, batched fact build, `finish_etl_load.py`, `LOG_LEVEL` fix) hardens the #4/#5 foundation.

---

## Biggest gaps / recommended next steps (priority order)

1. **Harmonization (#9–#12)** — add fact-table columns + SQL procedures, port `harmonize_scores.py` into `scripts/` against Postgres, add a real test suite.
2. **Productionize Phase 3–5 tables/endpoints** (`correlation_analysis`, `screen_metadata_curated`, `gene_darkness_score`; `/api/correlations`, `/api/dark-genes`, `/api/hypotheses/generate`).
3. **Wire the app to live data** (retire the mock-default in `/api/query`).
4. **Close #51** (Azure redirect URI) and **reconcile stale tickets**.

---

*Generated from a code-vs-backlog audit of all 30 issues.*

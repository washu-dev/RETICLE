# RETICLE — Layer 0 Technical Roadmap
### Cross-Cutting Foundations (Infrastructure, Ops, Project Spine)

**Scope:** The concerns that span every layer and don't belong to any single one: compute environment, source control, secrets, CI, cost management, reproducibility, data governance, and the decisions that must be made before Week 1 to avoid expensive retrofits. Layer 0 is "the ground everything else stands on."

**Where it runs:** Everywhere — RIS (offline build), cloud (online serving), student laptops (dev).

**Definition of done:** A team member can clone the repo, get credentials, run the pipeline on RIS, serve the app on cloud, and reproduce a result — all documented, with costs bounded and secrets safe.

---

## Guiding Principles

1. **Boring and replaceable beats clever.** A 10-week MVP that continues after rewards choices the next cohort can pick up. Postgres, FastAPI, plain Python pipelines.
2. **The offline/online split is the master architecture fact.** RIS = build-time (Layers 5–6). Cloud = serve-time (Layers 1–3). Layer 4 is the handoff artifact. Every infra choice respects this.
3. **Decide the expensive-to-change things first.** Canonical IDs, system-of-record DB, the RIS/cloud split. Cheap to get right early, brutal to retrofit.
4. **Reproducibility is a feature.** Versioned reference sets, pinned dependencies, cached external fetches.

---

## The Compute Map

```
STUDENT LAPTOPS            WASHU RIS                     CLOUD
(dev only)                 (offline batch build)         (online serving)
- code, test small         - data ingestion (L6)         - FastAPI backend
- run subset locally       - harmonization (L5)          - comparison engine (L3)
                           - LLM Job 1 (curation)        - RAG + LLM Job 2 (L2)
                           - builds reference set        - GUI (L1)
                           - Postgres (system of record) - read-only ref-set copy
                                      |                          ^
                                      +-- ref-set artifact ------+
                                          (Parquet/replica per version)
```

---

## Cross-Cutting Concerns

### Source Control & Structure
- One repo, clear module boundaries per layer (`ingest/`, `harmonize/`, `engine/`, `rag/`, `api/`, `ui/`, `common/`).
- Shared `common/` for the canonical ID resolver — used by ingestion AND query-time input handling.

### Secrets & Credentials
- NCBI API key, LLM API keys, DB creds, WashU SSO secrets — all in environment config / a secrets manager. Never in code or notebooks.

### Dependency & Environment Reproducibility
- Pinned dependencies (lockfile). Same environment reproducible on RIS and cloud.
- Containerize the serving layer for clean cloud deploy.

### Orchestration
- MVP: plain Python + Makefile, or Prefect for observability. Not Airflow.
- The build pipeline (L6→L5→L4 artifact) is one orchestrated DAG, runnable end-to-end with one command.

### Caching (cost + reproducibility)
- Cache all external fetches by key (PMID, gene ID). Never re-call NCBI/LLM for data already retrieved. This is both a cost control and a reproducibility guarantee.

### Cost Management
- LLM Job 1: ~2,200 screens × (extraction call). Bounded, one-time-ish, cached. Estimate and cap.
- LLM Job 2: per-query, scales with usage. Set per-query context/cost ceilings.
- Cloud serving: keep the always-on footprint small; the heavy build is on RIS (already funded).

### Reproducibility & Versioning
- Reference-set versions tagged (Layer 4). Results reference the version that produced them.
- Pipeline runs logged with input data versions (BioGRID dump date, GO release, etc.).

### Data Governance
- All primary sources are open-access (BioGRID, NCBI, GO, STRING, PubMed abstracts) — low licensing risk.
- Unpublished lab screens (the test cases) are sensitive — keep access-controlled, not in the public reference set unless intended.
- WashU SSO scopes who can use the tool; the curation dashboard is internal-only.

### Monitoring (lightweight for MVP)
- Pipeline run success/failure + the Layer 5/6 validation reports.
- Query-time errors and LLM cost tracking on the serving side.

---

## Pre-Week-1 Decisions (the expensive-to-change list)

| Decision | Recommendation | Why it's Layer 0 |
|----------|----------------|-------------------|
| Canonical gene ID anchor | Entrez Gene ID | Every source + every layer keys off it |
| System of record | PostgreSQL | Replaces flat files; scales to 44M rows |
| Build vs serve split | RIS offline / cloud online | Already how the compute is shaped |
| Ref-set handoff to cloud | Read-only artifact (Parquet) per version | Avoids live DB sync complexity |
| Bulk input format | CSV/TSV `gene[,score]` | Blocks L1, L2, L3 until decided |
| LLM job separation | Distinct configs for Job 1 / Job 2 | Architectural, hard to untangle later |
| Orchestration tool | Python + Makefile (or Prefect) | Sets the shape of the whole build |

---

## Timeline Summary

Layer 0 is **not a phase — it's Week 0 plus continuous discipline.** The pre-Week-1 decisions happen before ingestion starts; the cross-cutting practices (caching, versioning, secrets) are upheld throughout. Budget explicit setup time at the start rather than letting it accrete as debt.

---

## Open Questions for the Team

1. **RIS ↔ cloud data movement:** What's the approved, secure path to move the reference-set artifact from RIS to the cloud serving environment? (Data egress policies, WashU IT constraints.)
2. **Which cloud, and who administers it?** "Certain cloud" was named — which provider, what's the account/billing structure, who owns deploy?
3. **Unpublished-data handling:** The test cases use unpublished lab screens. Are they ever part of the served reference set, or strictly local validation? Governance implications differ.
4. **Team skill mapping:** Which students own which layer? The ID resolver (L6) and the statistical engine (L3) need different strengths; staffing affects sequencing.
5. **Post-MVP ownership:** "Continues after" — who maintains the reference-set refresh cadence (quarterly BioGRID) once the summer cohort leaves?

## Critique of the Existing Roadmap (Layer 0 / project-wide concerns)

- **The source documents have no Layer 0 at all.** Infrastructure, secrets, CI, cost, reproducibility, and the RIS/cloud handoff are entirely absent. For a student-built tool meant to outlive its cohort, this is the most significant structural gap — the project plan is all application logic, no foundation.
- **Cost is never estimated.** ~2,200 LLM extraction calls plus per-query rationale generation has a real budget; the plan assumes API access without bounding spend.
- **Reproducibility is unaddressed project-wide.** No versioning, no run logging, no data-vintage tracking. A research tool whose conclusions can't be reproduced against a known database state is scientifically fragile.
- **The "continues after" reality has no handoff plan.** No documentation standard, no maintenance owner, no refresh runbook. The quarterly BioGRID update — essential to keeping RETICLE current — has no owner.
- **Sequencing optimism compounds across layers.** Each layer's plan is individually plausible but assumes clean handoffs; the source documents never model what happens when curation (the biggest unknown) overruns into the GUI window. No critical-path analysis, no contingency.
- **Strengths worth preserving:** the offline/online split maps beautifully onto the available compute (RIS/cloud), the open-access nature of all sources minimizes legal risk, and the phased application logic is genuinely well-conceived. The gaps are foundational and operational, not conceptual.

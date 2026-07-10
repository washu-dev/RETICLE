# Technical Design — Gene List Parser Upgrade (GitHub Issue #29)

**Status:** Draft for developer hand-off
**Author:** Architect (di2-saif)
**Date:** 2026-06-26
**Parent:** #6 — Turn demo website into v0.1 working app
**Milestone:** Phase II
**Diagram:** `architecture/gene-list-parser-upgrade.drawio`

---

## 0. Reality check — discrepancies between the issue and the repo

The issue text references paths that do **not** exist in the repo as written. Resolve these before coding:

| Issue says | Repo reality | Decision |
|---|---|---|
| `webapp/src/utils/parseGenes.js` | `webapp/` is an empty `.gitkeep` placeholder. The working React app is `demo/`. The parser is **inline** in `demo/src/components/UploadPage.jsx` (lines 22–30) — there is no `parseGenes.js` file yet. | Implement under `demo/src/` (current app). If/when the app is promoted to `webapp/`, the module layout ports unchanged. |
| `webapp/src/components/UploadPage.jsx` "with algorithm/organism/modality options" | Current `UploadPage.jsx` has **no** options UI and `onAnalyze` takes a **single** argument (`onAnalyze(genes)`). There is no `AnalysisOptions` object anywhere. | Introduce `AnalysisOptions` and change the callback to `onAnalyze(genes, options)`. Update `App.jsx` `handleAnalyze`. |
| `AllGenes` is "a crosswalk table … 169KB" | `AllGenes` is a single-column, **mouse** gene-symbol vocabulary: ~20,675 rows, mixed-case RIKEN-style symbols (`0610007P14Rik`, `Lgr6`, `Lhfpl1`), **no Entrez IDs, no HGNC mapping, no tab columns.** It is a library/symbol allow-list, not a crosswalk. | **Do not use `AllGenes` as the Entrez→HGNC crosswalk.** Build a real crosswalk from HGNC + NCBI gene_info + ortholog source (see §6). `AllGenes` is at most the mouse symbol allow-list that feeds the build. |
| `api/routers/genes.py`, `api/routers/query.py` | No live Python source on disk (only stale `__pycache__/*.pyc`); `api/` is committed as `.gitkeep`. There is **no running backend.** | Backend is a component to be built. This design keeps backend scope minimal (one resolve endpoint) so the feature can ship frontend-first. |

These corrections drive several design decisions below. Flagging them now so the developer does not lose time chasing nonexistent files.

---

## 1. Functional requirements

The parser, given pasted text or an uploaded file, must:

- **FR-1 — MAGeCK `gene_summary.txt`.** Accept the full multi-column, tab-separated MAGeCK gene-summary format. Recognize columns `id`, `num`, `neg|score`, `neg|p-value`, `neg|fdr`, `neg|rank`, `neg|lfc`, `pos|score`, `pos|p-value`, `pos|fdr`, `pos|rank`, `pos|lfc`. The gene identifier is the `id` column.
- **FR-2 — STARS.** Accept STARS output (columns include `Gene`, `q-value`, `p-value`, `LFC`, `Rank`; identifier is `Gene`).
- **FR-3 — DESeq2.** Accept DESeq2 results (columns include row name / `gene`, `baseMean`, `log2FoldChange`, `lfcSE`, `stat`, `pvalue`, `padj`; score is `log2FoldChange`).
- **FR-4 — Simple CSV/TSV (back-compat).** Continue to accept the current `gene_symbol, score` two-column format. **No regression** for the existing example data (`EXAMPLE_GENE_LIST` in `mockData.js`).
- **FR-5 — Format auto-detection.** Detect the format from the header row and delimiter without the user choosing it. Detection result is surfaced to the user (read-only label) so a wrong guess is visible.
- **FR-6 — Auto-select score column.** From the detected columns, pick a sensible default score column (priority: a log-fold-change column, then a score column, then the second numeric column). Expose all numeric/score-like columns as alternatives.
- **FR-7 — Score column override (UI).** Render a dropdown in `UploadPage` letting the user override the auto-selected score column. Changing it re-parses and updates the loaded-gene count.
- **FR-8 — Entrez → HGNC resolution.** When the identifier column contains numeric Entrez IDs (or Ensembl IDs), resolve to HGNC symbols. Genes that cannot be resolved are reported, not silently dropped.
- **FR-9 — Mouse → Human ortholog mapping.** When organism = Mouse, map mouse symbols to their human orthologs before the list leaves the upload step (cross-screen comparison is human-canonical). Genes with no 1:1 ortholog are reported.
- **FR-10 — Organism selection (UI).** Add an Organism control (Human | Mouse, default Human). Drives FR-9 and is carried in `AnalysisOptions`.
- **FR-11 — Output contract preserved.** The parser still emits an array consumable by the existing flow. Minimum per-gene shape stays `{ symbol: string, score: number }` (current consumers rely on `symbol`, `score`, and `genes.length`); additional fields are additive and optional.
- **FR-12 — Validation & errors.** Keep the existing guard rails: minimum gene count, clear inline error messages. Distinguish "no parsable rows" from "format detected but score column empty" from "N genes unresolved."

### Acceptance criteria (user-observable)

1. Pasting a real MAGeCK `gene_summary.txt` shows "N genes loaded", auto-selects a score column (default `neg|lfc`), and the score dropdown lists `neg|lfc, pos|lfc, neg|score, pos|score, …`.
2. Switching the score dropdown from `neg|lfc` to `pos|lfc` updates the parsed scores (sign/magnitude visibly change) without re-uploading.
3. A STARS file and a DESeq2 file each parse to the correct gene count with `LFC` / `log2FoldChange` auto-selected.
4. The current `gene_symbol, score` example still loads exactly as today.
5. A file whose `id` column is Entrez IDs (e.g. `11793`) with organism=Human shows resolved HGNC symbols; unresolved IDs are listed in a warning, count excluded.
6. A mouse file with organism=Mouse shows human ortholog symbols downstream; genes lacking an ortholog are listed in a warning.
7. `onAnalyze` receives `(genes, options)` where `options.scoreColumn` and `options.organism` reflect the UI.

---

## 2. Non-functional requirements (measurable)

| Category | Target |
|---|---|
| **Performance — parse** | Format detect + parse + score-column extraction for a 23,000-row genome-scale file completes in **< 300 ms** on a mid-tier laptop, off the main paint path (no UI freeze > 100 ms). |
| **Performance — resolution** | Local (bundled) crosswalk lookup is **O(1) per gene**, < 50 ms for 23k genes. Backend `/genes/resolve` round-trip **< 800 ms p95** for a 5,000-id batch. |
| **Payload / bundle** | Bundled crosswalk asset adds **≤ 60 KB gzipped** to the webapp (see §6 sizing). Backend request body capped at **≤ 2 MB** / **≤ 50,000 ids** per call. |
| **Availability** | Parsing and the simple/MAGeCK/STARS/DESeq2 paths work **fully offline** (no network). Only large-batch ID resolution depends on the backend; backend outage degrades to "resolved what we could, N pending" — never a hard failure of upload. |
| **Security** | All file content treated as untrusted (§8). No `eval`, no HTML injection from gene symbols, no PII. Backend validates and bounds every field. |
| **Observability** | Parser returns a structured `warnings[]` (format guessed, rows skipped, ids unresolved, orthologs missing) rendered in the UI and loggable. Backend logs per-request: id count, hit/miss counts, latency — no raw gene lists in logs by default. |
| **Accessibility** | New dropdowns are real `<label>` + `<select>` pairs, keyboard-navigable, with `aria-describedby` pointing at the detected-format hint. Color is not the only signal for warnings. |
| **Cost** | Frontend-only paths: **$0**. Backend resolve endpoint on Cloud Run with min-instances=0 and a static crosswalk file: **free-tier / low single-digit dollars per month** at demo/v0.1 traffic. No new managed DB required for v0.1 (crosswalk ships as a read-only file). |

---

## 3. Data flow — upload to `onAnalyze(genes, options)`

```
1. User drops/pastes file        -> raw: string                (UploadPage)
2. detectFormat(raw)             -> { format, delimiter,        (frontend util)
                                       columns[], headerRow }
3. suggestScoreColumn(columns,   -> { defaultColumn,            (frontend util)
        format)                       candidates[] }
4. UI renders:                                                  (UploadPage)
     - detected-format label (read-only)
     - Score Column <select> (default = defaultColumn)
     - Organism <select> (default Human)
5. parseGeneList(raw,            -> { genes: ParsedGene[],       (frontend util)
        { format, delimiter,          warnings[] }
          columns, scoreColumn })
6. resolveIdentifiers(genes,     -> { genes: ParsedGene[],       (frontend util,
        organism)                     warnings[] }                 may call backend)
       - Entrez/Ensembl -> HGNC
       - mouse symbol  -> human ortholog (if organism=Mouse)
       - bundled mini-map first; misses -> POST /genes/resolve
7. User clicks "Run RETICLE"
8. onAnalyze(genes, options)                                    (App.jsx handler)
       options = { organism, scoreColumn, detectedFormat,
                   sourceDelimiter, resolution: {resolved, unmapped} }
```

Steps 2–5 are synchronous and run on every text change (debounced ~200 ms) to keep the live "N genes loaded" indicator. Step 6's backend call (if needed) fires only on submit, not on every keystroke.

---

## 4. Where each piece of logic lives

### Design decision resolutions

**D1 — Entrez→HGNC crosswalk: bundle vs backend? → Hybrid, bundle-first.**
The premise that `AllGenes` (169 KB) is the crosswalk is wrong (§0). A real human+mouse Entrez/Ensembl→HGNC + ortholog crosswalk for all genes is multiple MB — too large to bundle. Resolution:
- **Bundle a minified mini-crosswalk** (`crosswalk.min.json`) covering only the gene universe the v0.1 demo actually touches (the example list, autophagy/IFNγ genes, and the curated screens) — target ≤ 60 KB gzipped. Covers the happy path with zero latency, fully offline.
- **Fall back to backend** `POST /genes/resolve` for ids not in the mini-map. Authoritative, full-coverage, kept server-side so the big table is never shipped to the client.
This satisfies "bundle size vs latency": common case is local and instant; rare/large cases hit the network in a single batched call.

**D2 — Ortholog mapping: frontend or backend? → Same hybrid as D1.**
Ortholog mapping is just another lookup table (`GENE_ORTHOLOG` in the data model, §6.5 of `requirements/requirement_analysis.md`). Bundle the mouse→human orthologs for the demo gene universe; defer misses to the same `/genes/resolve` endpoint (it takes `organism` and returns human-canonical symbols). Keeping mapping co-located with ID resolution avoids two round-trips and one source of drift.

**D3 — Format detection/parsing: frontend util or backend? → Stays a pure frontend util.**
Parsing MAGeCK/STARS/DESeq2 is plain delimiter + header logic, cheap (< 300 ms for 23k rows), and benefits from instant feedback (live gene count, score-column re-parse). Moving it to the backend would add latency and a hard network dependency to the core upload step for no algorithmic gain. **Only identity resolution** (which needs a large authoritative table) belongs on the backend. This keeps the feature shippable before the backend exists: parsing + the bundled mini-map alone satisfy the demo.

### Module map

| Logic | Location | Type |
|---|---|---|
| Format signatures + delimiter sniff | `demo/src/utils/geneParser/detectFormat.js` | pure frontend |
| Score-column ranking + candidates | `demo/src/utils/geneParser/scoreColumns.js` | pure frontend |
| Parse orchestrator (replaces inline parser) | `demo/src/utils/geneParser/parseGeneList.js` | pure frontend |
| Entrez/Ensembl→HGNC + mouse→human, bundle-first w/ backend fallback | `demo/src/utils/geneParser/resolveIds.js` | frontend (thin client) |
| Public barrel export | `demo/src/utils/geneParser/index.js` | — |
| Bundled mini-crosswalk asset | `demo/src/data/crosswalk.min.json` | static asset |
| Authoritative resolve endpoint | `api/routers/genes.py` → `POST /genes/resolve` | backend (FastAPI) |
| Authoritative crosswalk store | read-only file (SQLite/Parquet) loaded by the router | backend data |
| UI: score-column + organism controls | `demo/src/components/UploadPage.jsx` | frontend |
| Callback signature change | `demo/src/App.jsx` (`handleAnalyze`) | frontend |

---

## 5. Proposed function signatures

```js
// detectFormat.js
/**
 * @param {string} raw
 * @returns {{
 *   format: 'MAGECK' | 'STARS' | 'DESEQ2' | 'SIMPLE' | 'UNKNOWN',
 *   delimiter: '\t' | ',',
 *   columns: string[],     // header tokens, in order
 *   idColumn: string,      // best-guess identifier column
 *   confidence: number     // 0..1
 * }}
 */
export function detectFormat(raw) { /* ... */ }

// scoreColumns.js
/**
 * @param {string[]} columns
 * @param {'MAGECK'|'STARS'|'DESEQ2'|'SIMPLE'|'UNKNOWN'} format
 * @returns {{
 *   defaultColumn: string,
 *   candidates: { value: string, label: string }[]  // for the <select>
 * }}
 */
export function suggestScoreColumn(columns, format) { /* ... */ }

// parseGeneList.js
/**
 * @typedef {Object} ParsedGene
 * @property {string} symbol        // raw id/symbol from the file
 * @property {number} score         // value from the chosen score column
 * @property {string} [rawId]       // original identifier (Entrez/Ensembl) pre-resolution
 * @property {Object} [extra]       // other parsed columns (fdr, rank, lfc...) - optional
 *
 * @param {string} raw
 * @param {{ format?, delimiter?, columns?, idColumn?, scoreColumn: string }} opts
 * @returns {{ genes: ParsedGene[], warnings: string[] }}
 */
export function parseGeneList(raw, opts) { /* ... */ }

// resolveIds.js
/**
 * @param {ParsedGene[]} genes
 * @param {'Human'|'Mouse'} organism
 * @param {{ apiBaseUrl?: string }} [cfg]   // backend opt-in; omitted => local-only
 * @returns {Promise<{
 *   genes: ParsedGene[],                    // symbol now human HGNC where resolvable
 *   resolved: number,
 *   unmapped: { rawId: string, reason: string }[],
 *   warnings: string[]
 * }>}
 */
export async function resolveIdentifiers(genes, organism, cfg) { /* ... */ }
```

`UploadPage` keeps a synchronous `parseGenes(raw)`-style helper for the live count, but it now delegates to `detectFormat` + `parseGeneList` instead of the inline 2-column split.

### `AnalysisOptions` shape (answers design decision #4)

```js
// returned to App via onAnalyze(genes, options)
const options = {
  organism: 'Human',          // 'Human' | 'Mouse'        (new control)
  scoreColumn: 'neg|lfc',     // chosen score column       (new control, FR-6/7)
  detectedFormat: 'MAGECK',   // 'MAGECK'|'STARS'|'DESEQ2'|'SIMPLE'|'UNKNOWN'
  sourceDelimiter: '\t',      // for traceability
  resolution: {               // populated by resolveIdentifiers
    resolved: 842,
    unmapped: 5,
  },
};
```

This object did not previously exist; `scoreColumn` is the field Issue #29 asks to add, alongside the `organism` field needed for ortholog mapping. Keep it a flat, serializable object (12-factor: passes cleanly to a future backend analyze call).

---

## 6. New files to create

| File | Purpose | Notes |
|---|---|---|
| `demo/src/utils/geneParser/detectFormat.js` | Format + delimiter detection | pure, unit-testable |
| `demo/src/utils/geneParser/scoreColumns.js` | Score-column ranking | pure |
| `demo/src/utils/geneParser/parseGeneList.js` | Parse orchestrator | pure |
| `demo/src/utils/geneParser/resolveIds.js` | ID + ortholog resolution (thin client) | network optional |
| `demo/src/utils/geneParser/index.js` | Barrel export | — |
| `demo/src/data/crosswalk.min.json` | Bundled mini-crosswalk (Entrez/Ensembl→HGNC + mouse→human) for demo gene universe | ≤ 60 KB gz; generated, checked in |
| `scripts/build_crosswalk.py` | One-shot generator: HGNC complete set + NCBI gene_info + HCOP/Ensembl orthologs → mini JSON (and the full backend store) | uses `AllGenes` only as the mouse symbol allow-list |
| `api/routers/genes.py` | `POST /genes/resolve` (backend, when API is stood up) | pydantic-validated, bounded |
| `demo/src/utils/geneParser/*.test.js` | Unit tests per format + score selection + resolution fallback | for test-engineer |

**Crosswalk sizing rationale:** A full human+mouse Entrez+Ensembl→HGNC+ortholog table is several MB and must not be bundled. The mini-map is scoped to the genes the v0.1 demo can encounter (example list + curated screens + their neighborhood, low thousands of genes), which fits well under the 60 KB gz budget. Everything outside that set resolves via the backend.

---

## 7. UI change in `UploadPage.jsx`

Placement: a compact **options row directly beneath the upload zone / textarea and above the action row** (between the current line ~141 textarea block and the line ~150 action row). Two inline controls:

```
[ Detected: MAGeCK gene_summary (tab) ]   Score column [ neg|lfc  ▾ ]   Organism [ Human ▾ ]
```

- The **Score column** `<select>` is populated from `suggestScoreColumn().candidates`, default-selected to `defaultColumn`. `onChange` re-runs `parseGeneList` with the new column and refreshes the "N genes loaded" indicator.
- The **Organism** `<select>` (Human | Mouse) defaults to Human; drives ortholog mapping at submit.
- The detected-format label is read-only text (not a control) so a misdetection is visible; if `format === 'UNKNOWN'`, show a soft warning and fall back to SIMPLE parsing.
- Controls are only shown once `text` is non-empty (mirrors the existing "genes loaded" reveal). Use real `<label htmlFor>` + `<select>` for accessibility; style to match existing `--bg-2 / --border` tokens.
- `handleSubmit` becomes async: parse → `await resolveIdentifiers(...)` → `onAnalyze(genes, options)`. `App.jsx` `handleAnalyze` signature changes to `(genes, options) => { setGenes(genes); setOptions(options); setScreen('loading'); }` (add an `options` state slot).

The existing "Accepted formats" hint panel (lines ~181–196) should be updated to mention MAGeCK gene_summary / STARS / DESeq2 explicitly and corrected to say IDs are resolved via the crosswalk **service**, not a single bundled file.

---

## 8. Principle compliance

### 12-factor

- **III Config:** Backend base URL for `resolveIds` comes from an env-injected config (e.g. `import.meta.env.VITE_API_BASE_URL`), never hard-coded. Crosswalk source paths on the backend are env/config-driven.
- **IV Backing services:** `/genes/resolve` is an attachable backing service; the frontend degrades gracefully if it is absent (local-only mode). The crosswalk file is a swappable attached resource.
- **VI Processes:** All parser utils are pure and stateless; no module-level mutable cache that survives a request. Resolution state lives in the returned object, not globals.
- **X Dev/prod parity:** Same parser modules run in dev and prod; the mini-crosswalk is the same artifact everywhere; backend uses the same crosswalk build script output.

### SOLID

- **SRP:** Four single-purpose modules — `detectFormat` (what is this?), `scoreColumns` (which column?), `parseGeneList` (extract rows), `resolveIds` (canonicalize identity). The current code violates SRP by doing detect+parse inline in a React component; this splits them out and makes the component a pure consumer.
- **OCP:** Adding a new tool format (e.g. DRUGz) = adding one signature entry to `detectFormat` + one column-priority rule, no edits to the orchestrator or UI.
- **DIP:** `UploadPage` depends on the `geneParser` barrel interface, not on parsing internals; `resolveIds` depends on an injectable `apiBaseUrl`, not a hard-wired fetch target — enables a mock in tests.

### OWASP Top 10 (threat model of this design)

| Risk | Vector here | Mitigation in design |
|---|---|---|
| **A03 Injection** | Malicious gene symbols / cells rendered into DOM, or sent to backend SQL | Symbols rendered as text only (React escapes by default); never `dangerouslySetInnerHTML`. Backend treats ids as parameters/keys into a read-only lookup — no string-concatenated SQL. Validate id charset (`^[A-Za-z0-9.\-_]+$`). |
| **A04 Insecure design / DoS** | A 100 MB pasted file or 10M-row table freezes the tab or floods the API | Frontend caps file size (e.g. ≤ 25 MB) and row count before parsing; parse off the paint path. Backend caps body size (≤ 2 MB) and ids per call (≤ 50,000); reject oversize with 413. |
| **A05 Security misconfig** | Permissive CORS / verbose errors on `/genes/resolve` | CORS allow-list to the webapp origin only; generic error bodies; no stack traces to client. |
| **A06 Vulnerable components** | New parsing deps | Prefer zero new runtime deps (hand-rolled delimiter parse). If a CSV lib is added, pin and audit (config-engineer CI gate). |
| **A08 Data integrity** | Tampered bundled crosswalk shipped to users | Crosswalk is build-generated from authoritative sources via `build_crosswalk.py`, checked in with provenance; CI can re-generate and diff. |
| **A09 Logging** | Leaking researcher gene lists into logs | Backend logs counts + latency, not raw lists, by default. No PII involved, but unpublished gene lists are sensitive IP — treat as confidential. |
| **A10 SSRF** | n/a — resolve endpoint takes ids, never URLs | Endpoint accepts only an id array + enums; no fetch-by-URL behavior. |

Transport: all backend calls over HTTPS (TLS) only.

---

## 9. Dependencies & risks

**Dependencies**
- **Crosswalk data sourcing (blocking for FR-8/9 full coverage):** Need HGNC complete set + NCBI `gene_info` + HCOP/Ensembl ortholog table to build `crosswalk.min.json` and the backend store. The bundled mini-map can ship first (covers the demo); full coverage waits on the backend endpoint. The `AllGenes` mouse vocabulary is reused as the mouse allow-list only.
- **Backend stand-up (blocking for large-batch resolution only):** `/genes/resolve` requires the FastAPI `api/` to actually exist (currently placeholder). FR-1–FR-7 and the demo happy path do **not** depend on it.
- `App.jsx` and `UploadPage.jsx` edits are coupled (callback signature change) — land together.

**Risks**
- **R1 — Wrong `AllGenes` assumption (addressed):** Building the crosswalk from `AllGenes` would have produced a parser that resolves nothing. Mitigated by §0 + the real sourcing plan; flag to product-owner that the issue's premise was incorrect.
- **R2 — Score sign convention.** Auto-selecting `neg|lfc` vs `pos|lfc` changes the biological meaning (Directional Uniformity, §3 of requirement_analysis). For #29 we only *select and expose* the column; we do **not** apply sign harmonization (that is Phase 1 / a separate issue). State this boundary so downstream comparison logic owns directionality.
- **R3 — Ambiguous/ heterogeneous real files.** BioGRID deposits are messy (Excel-on-sheet-3, hits-only, custom headers). Out of scope for #29 (sgRNA-level files explicitly excluded), but `format: 'UNKNOWN'` must degrade safely to SIMPLE + warn rather than throw.
- **R4 — Ortholog ambiguity.** Mouse→human is not always 1:1. Many-to-one / no-ortholog cases must be reported in `unmapped[]`, not silently collapsed (would corrupt cross-screen correlations).
- **R5 — Bundle budget.** If the demo gene universe grows, the mini-map could exceed 60 KB gz. Mitigation: cap the mini-map to the example + curated screens and push everything else to the backend; CI size-check the asset.

---

## 10. Hand-off

- → **full-stack-developer:** Implement §4 module map + §5 signatures + §7 UI. Ship frontend + bundled mini-map first (no backend dependency for the demo path). Stand up `POST /genes/resolve` when `api/` exists; until then `resolveIds` runs local-only.
- → **product-owner:** Issue #29's premise about `AllGenes` being the crosswalk is incorrect — note for backlog. Suggest a follow-up task for building the authoritative crosswalk + ortholog store (depends on the backend and data-sourcing), and confirm directional sign-harmonization (R2) is tracked as a separate Phase 1 item.
- → **test-engineer:** Acceptance criteria in §1; NFR targets in §2; unit-test fixtures per format under `geneParser/*.test.js`.
```

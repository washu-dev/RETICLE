# RETICLE: Load Screen, Self-Description & Filtering — How It Works

A functional walkthrough of how a user loads their own screen, describes it, and
filters the comparison corpus.

The whole flow lives on one page, **`webapp/src/components/UploadPage.jsx`**,
which walks the user through 4 numbered sections top to bottom. Each section
appears only once the one before it has what it needs. On submit, the request
runs through a loading screen and results render in
**`webapp/src/components/shell/DashboardView.tsx`**.

> **Two different "screens."** `UploadPage.jsx` is where a user loads/describes
> *their own* screen. `ScreenDrawer.tsx` is the read-only viewer for a *matched
> corpus screen* (someone else's published screen) after results come back.

---

## 1. Load Screen ("Your screen")

**What the user does:** drag-and-drop a file, click to browse, paste text into
the textarea, or click **"Load example (Orvedahl screen)"**. Accepts `.csv`,
`.tsv`, `.txt`. All three inputs feed one `text` state.

**What happens the moment text lands** (`UploadPage.jsx:110-114`, debounced ~200 ms) —
all client-side, pure functions in `webapp/src/utils/geneParser/`, no network:

1. **`detectFormat(raw)`** (`detectFormat.js`) sniffs the delimiter (tab vs
   comma) and reads the header row to guess one of 7 formats:
   - `MAGECK` — pipe columns like `neg|lfc` + an `id` column
   - `STARS` — `Gene, q-value, p-value, LFC, Rank`
   - `DESEQ2` — `baseMean, log2FoldChange, padj`
   - `ORCS` — BioGRID native: `#`-prefixed header, `OFFICIAL_SYMBOL`, `SCORE.1…`
   - `RESIDUAL` — di2 z-score output: `Gene, mean_lfc, z_score, fdr, ascending_rank…`
   - `SIMPLE` — 2-column gene,score
   - `UNKNOWN` — falls back to a "WORD, number" heuristic

   Returns `{format, delimiter, columns, idColumn, hitColumn, conditionColumn, confidence}`.

2. **`suggestScoreColumn`** picks the default score column + alternatives.
3. **`parseGeneList`** turns text into `{symbol, score, isHit, extra}` objects
   (enforces a 5-gene minimum).

**The receipt — "What we read" (Section 2):** once ≥1 gene parses, a card shows
genes read, detected format, organism, direction, score column, coverage, hits
flagged, condition. A collapsible **"Fix column mapping"** lets the user override
the ID / score / hit column if detection got it wrong (`UploadPage.jsx:365-391`).

> Nothing is uploaded to a server during this stage — detection and parsing are
> entirely client-side. Data leaves the browser only on submit.

---

## 2. Self-Screen Description ("Describe your screen")

This is the **context vector** — how the user tells RETICLE what their screen
*is*. It is stored/echoed to label results.

**Auto-fill first, override anything** (`UploadPage.jsx:134-154`):
`deriveScreenSignals` (`screenSignals.js`) inspects the parsed data and pre-fills:

- **Organism** — from an `ORGANISM` column if present, else left blank.
- **Coverage** — `HITS_ONLY` if every row is a flagged hit, else `FULL`.
- **Direction** — `bidirectional` (ascending+descending rank columns, or scores
  split both signs), else `depletion` / `enrichment` from the score sign.
- **Algorithm / score column / file format** — from the detected format.

Every auto-filled field is tagged **"Auto-detected"**; once the user touches it,
it flips to **"You entered"** (`edited`/`autoFilled` Sets + `prov()`,
`UploadPage.jsx:173-177`). User edits are never overwritten by re-detection.

**Fields** (`ScreenContext` in `reticleApi.ts:13` / `api/models/query.py:9`):
always-visible chips for modality, organism, selection method, assay domain,
library coverage; then behind "Add more detail" — cell line, cell type, library,
scoring algorithm, treatment/condition, concentration, timepoint, replicates,
comparison direction, hit threshold. Vocabularies live in
`webapp/src/data/screenVocab.ts`.

> Every field is optional, and per the model docstring "not all fields drive the
> query today." The context vector is **round-tripped for display/labeling**, not
> parsed or persisted server-side — the gene list is what actually drives matching.

---

## 3. Filtering System ("Compare against" — corpus filters)

Decides **which published screens** the user's screen is compared to. Shape =
`CorpusFilters` (`query.py:38-49`). Defaults to the **entire corpus** — narrowing
is opt-in.

**Effective user-facing filters** (`UploadPage.jsx:494-537`):

| Filter | UI / JSON | `/api/corpus/count` param | Pydantic | Allowed values |
|---|---|---|---|---|
| Organism | `organism` | `organism` | `organism` | `Any`, `Human`, `Mouse` |
| Coverage | `coverage` | `coverage` | `coverage` | `Any`, `FULL` |
| Assay domain (multi) | `assayDomains[]` | `assayDomains` | `assay_domains` | `fitness`, `stress`, `reporter`, `other` |
| Modality (multi) | `modalities[]` | `modalities` | `modalities` | `KO`, `CRISPRi`, `CRISPRa`, `RNAi`, `Other` |
| Min shared genes | `minSharedGenes` | `minSharedGenes` | `min_shared_genes` | int ≥ 0 |

> `cellTypes[]` exists in the data model (backend applies it as case-insensitive
> `LIKE` matches) but has **no dedicated UI control** in this build — reachable
> only via the API.

Plus a **"Use recommended pool"** shortcut (organism from your screen + `fitness`
+ genome-wide).

**Live cohort counter** (`UploadPage.jsx:157-166`): each filter change fires a
debounced `GET /api/corpus/count`, showing "Comparing against **N** screens."

> ⚠️ The counter reflects organism / coverage / assay-domains / modalities /
> cell-types only. It does **not** reflect `minSharedGenes` — that filter is
> enforced later, in the query's `HAVING` clause (see below). Raising it won't
> move the counter, but it will trim the matched-screens list.

**How filters become SQL** (`corpus_service.py`):

- **`build_corpus_where(filters)`** turns the filter object into a parameterized
  `AND …` fragment over `screen_metadata` / `screen_metadata_curated`.
- **"Any" / empty / all-selected = no-op.** Leaving everything on (the default)
  adds no clause → full corpus. Selecting *all* assay domains or *all* modalities
  is treated the same as none, so it never accidentally excludes rows
  (`_ALL_ASSAY_DOMAINS`, `_ALL_MODALITIES`).
- Organism maps Human→`Homo sapiens`, Mouse→`Mus musculus`.
- Cell types → OR of case-insensitive `LIKE` clauses.

**How matching / ranking works** (`mock_data_service.run_query`, `mock_data_service.py:305`):

1. Size the filtered pool (`corpus_count`).
2. Find corpus screens where any query gene is a **hit** (`is_hit = 1`), with the
   corpus WHERE applied.
3. Group per screen; compute `shared_genes` (distinct shared hits), a `rho`
   aggregate, directionality.
4. `HAVING COUNT(DISTINCT gene) >= minSharedGenes`, then
   **`ORDER BY shared_genes DESC, rho DESC`**, limit 20.
5. Co-hit "dark genes" (ride-along genes in matched screens, not in the query)
   feed the "Genes worth a look" section + a network graph.

> ⚠️ **ρ and FDR are currently uncalibrated.** `fdr` is a hardcoded placeholder;
> `rho` is a raw `AVG(percentile_score)` aggregate, not a true Spearman ρ.
> `DashboardView.tsx` hides them behind a "show numbers" toggle and flags them
> with asterisks. Ranking is driven by **shared-gene count**, not ρ.

---

## The request that ties it together

On **"Compare to the corpus"** (`UploadPage.jsx:214-248`): if ≥5 genes parsed, it
resolves gene identifiers against a crosswalk, then calls
`onAnalyze(resolvedGenes, options)`. `App.tsx` stores that and switches to a
loading screen; **`LoadingAnalysis.jsx` actually fires the request** —
`runQuery(genes, options)` → `POST /api/query` (`reticleApi.ts:165`):

```json
{
  "genes": [{ "symbol": "…", "score": 0.0 }],
  "algorithm": "MAGeCK LFC",
  "organism": "Both",
  "modalities": ["KO", "CRISPRa"],
  "screenContext": { "…your description…": "…" },
  "corpusFilters": { "…your filters…": "…" }
}
```

Backend runs mock data offline or real RDS when `USE_PG` is set (same code path,
`mock_data_service.py`). The response (`QueryResponse`: stats, matchedScreens,
darkGenes, graphElements, echoed screenContext, corpusPoolSize) renders in
`DashboardView`. Clicking a matched screen there opens **`ScreenDrawer`**
(`GET /api/screen/{id}` → metadata + a per-gene raw/harmonized score table that
is itself filterable and sortable client-side).

---

## Dev notes

- **Offline mock mode** (default, `USE_PG` off) uses 6 verified real BioGRID
  screens in `api/services/reference_screens.py`, so every PubMed/BioGRID link
  resolves.
- **SSO bypass** (`REACT_APP_DEV_NO_AUTH`, non-prod builds only) reaches
  `UploadPage` without WashU login.

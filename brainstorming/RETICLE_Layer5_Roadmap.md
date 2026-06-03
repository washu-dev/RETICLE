# RETICLE — Layer 5 Technical Roadmap
### Curation, Harmonization & Reference Set Construction

**Scope:** Take the clean per-source staging tables from Layer 6 and combine them into the unified, annotated **reference set** — the harmonized gene × screen matrix with directionality labels, three-state presence flags, percentile ranks, and the inputs for Darkness Rating. This is where the biology gets encoded.

**Where it runs:** WashU RIS (batch, offline). Includes LLM API calls for metadata curation ("Job 1"). Postgres as system of record; optional DuckDB for heavy analytical reads.

**Definition of done:** A queryable reference set where every gene-in-screen has a harmonized score, a percentile rank, a biological directionality label, and an explicit presence status — and every screen has human-approved metadata. Sanity checks pass against known biology.

---

## Guiding Principles

1. **Biology lives here, not in ingestion.** Directionality, harmonization, and presence logic are the value-add. They are iterated on; keep them isolated from raw parsing.
2. **Human-in-the-loop is load-bearing, not optional.** LLM-extracted metadata must be expert-approved before it commits. Wrong directionality silently corrupts every downstream comparison.
3. **Derive, don't destroy.** Always retain raw scores alongside harmonized ones. Every derived field is reproducible from raw + rules.
4. **Validate against ground truth.** The lab's own published screens (Orvedahl 2019) are the benchmark. If RETICLE can't reproduce known biology, the harmonization is wrong.

---

## The Layer 5 DAG

```
STEP 1  Metadata curation (LLM Job 1 + human approval)   <-- fills directionality variables
            |
STEP 2  Score harmonization (cross-algorithm normalization)
            |
STEP 3  Directionality assignment (the decision tree)
            |
STEP 4  Three-state presence computation
            |
STEP 5  Percentile ranking
            |
STEP 6  Darkness Rating inputs (aggregate pubs + GO)
            |
STEP 7  Sanity checks against known biology           <-- the quality gate
            |
        ==> Reference set complete; Layer 4 materializes from it
```

---

## STEP 1 — Metadata Curation (LLM Job 1 + Human Approval)

**Goal:** Populate the four directionality variables (screen type, selection method, comparison direction, collected population) for every screen, since BioGRID's structured metadata is incomplete.

- **Input:** `stg_screens.pmid` → fetch Methods section via ENTREZ/PMC (cached, never re-fetched).
- **LLM call:** low temperature, strict JSON schema, structured output / function calling. One screen per call. Cache by PMID.
- **Schema extracted:**
```
screen_type         (KO / CRISPRa / CRISPRi)
selection_method    (viability / FACS / dropout / drug-resistance)
comparison          (treated_vs_untreated / day21_vs_day0 / condition_A_vs_B)
collected           (survivors / dead / marker_positive)
confidence          (model's self-reported confidence per field)
evidence_span       (the text the model based each field on — for audit)
```
- **Human-in-the-loop dashboard:** lightweight Streamlit app. Expert sees the extracted JSON, the evidence span, and the source text; clicks Approve / Modify. Only approved metadata commits to the Screen table.
- **Prioritize approval queue by confidence** — auto-pass high-confidence unambiguous cases for spot-review, route low-confidence to mandatory human review.

**Hazard:** ambiguous Methods sections ("cells were collected after treatment" — survivors or dead?). The model will guess. This is precisely why approval is mandatory.

---

## STEP 2 — Score Harmonization

**Goal:** Make scores comparable across screens that used MAGeCK, STARS, DRUGz, etc.

- **Do not compare raw scores across algorithms.** They have different distributions and meanings.
- **Primary harmonization = rank percentile** (Step 5), which is algorithm-agnostic. This is the robust path.
- **Optional:** within-screen z-scoring or quantile normalization for screens that report full distributions, to enable continuous comparison. Only where the full ranked list exists, not hit-only screens.
- Retain `raw_score` and `analysis_method`; write `harmonized_score` as a new field.

---

## STEP 3 — Directionality Assignment

**Goal:** Convert each gene's raw score into a canonical biological label using the decision tree.

```
inputs:  screen_type, selection_method, comparison, collected, sign(score)
output:  biological_direction in {protective_when_lost, sensitizing_when_lost, null}
```

- Implement as an explicit, testable rule table (not buried in code). Each combination of the four variables + score sign maps to one canonical direction.
- Store the rule version used, so re-runs are auditable.
- **Edge case flagged in Module 7:** multi-arm screens (e.g. the CTA suppressor screen with IFNγ/TNF vs Mock AND IFNγ/TNF+CTA vs CTA). The two-arm decision tree does not cleanly cover this. Needs an explicit multi-comparison representation — design before building.

---

## STEP 4 — Three-State Presence Computation

**Goal:** For every gene × screen, label `hit` / `tested_not_hit` / `not_in_library` — never infer absence.

- Requires the **library manifest** per screen (which genes the sgRNA library actually targeted). Source this from the library definition (Brie, Brunello, Caprano, etc.), not from the results table.
- `not_in_library` = gene absent from manifest. `tested_not_hit` = in manifest, below significance. `hit` = clears threshold.
- **Hazard:** many screens only report hits to BioGRID. If the full library results aren't available, `tested_not_hit` vs `not_in_library` may be undeterminable — flag these screens as "hits-only" so the comparison engine handles them correctly (overlap mode, not correlation mode).

---

## STEP 5 — Percentile Ranking

**Goal:** Convert raw rank to within-screen percentile so ranks are comparable across library sizes.

```
percentile_rank = rank / library_size
```
- Compute against the **actual library size** for that screen, not the number of reported genes.
- This is the workhorse normalization that makes Spearman comparison (Layer 4) meaningful.

---

## STEP 6 — Darkness Rating Inputs

**Goal:** Stage the per-gene "how unknown is this gene" inputs. (Final scoring formula deferred — see critique.)

- **Publication count:** aggregate `stg_gene_pubs` → count distinct PMIDs per canonical gene.
- **Specific GO annotation count:** from `stg_go_annotations`, count annotations after filtering generic terms (e.g. exclude "protein binding" GO:0005515 and similar low-information terms by IC/specificity threshold).
- **Cross-species normalization:** use `ortholog_group_id` so a mouse gene isn't flagged "dark" merely because its literature lives under the human ortholog's symbol.
- Store the components separately; defer the combined weighted score to a tunable formula.

---

## STEP 7 — Sanity Checks (Quality Gate)

**Goal:** Verify harmonized directionality matches known biology before the reference set is trusted.

- **Ground-truth test (from the proposal's test cases):** Does the autophagy gene set show up as *protective* against IFNγ-induced death in the Orvedahl 2019 KO screen, as published?
- **Receptor check:** Known receptor for a cytotoxic ligand should be enriched (protective when lost) in a KO survival screen and depleted in an activation screen. Verify the directionality assignment reproduces this.
- **CRISPRa directionality test:** confirm an activation screen's logic correctly inverts relative to KO.
- Automate these as a regression suite — they run on every reference-set rebuild.

---

## Timeline Summary

| Phase | Focus | Deliverable |
|-------|-------|-------------|
| Weeks 3 | Metadata curation + harmonization | Approved screen metadata; harmonized scores |
| Weeks 3–4 | Directionality + presence + percentiles | Fully annotated gene × screen records |
| Week 4 | Darkness inputs + sanity checks | Validated reference set; passing ground-truth suite |

Maps to the existing roadmap's "Weeks 3–4: Reference Set Construction & Validation."

---

## Open Questions for the Team

1. **Multi-arm screens:** How should the directionality schema represent screens with two simultaneous comparison axes (the CTA suppressor design)? This is the lab's own most valuable data and it doesn't fit the current two-arm model. Is a "comparison context" sub-record the right abstraction?
2. **Library manifests:** Do we have reliable access to the sgRNA library gene lists (Brie, Brunello, etc.) needed for three-state presence? If not, what fraction of screens degrade to "hits-only"?
3. **Harmonization depth:** Is rank percentile sufficient for the MVP, or do we need within-screen continuous normalization on day one? (Recommendation: percentile-only for MVP.)
4. **LLM approval throughput:** With 2,217 screens, how much expert time is realistically available for human-in-the-loop approval? Does the confidence-based auto-pass threshold need to be aggressive to fit the timeline?
5. **Directionality confidence:** Should the reference set store a confidence/uncertainty on each directionality label, so the comparison engine can downweight low-confidence screens rather than treating all as equal?

## Critique of the Existing Roadmap (Layer 5 concerns)

- **The original plan compresses curation, harmonization, AND validation into "Weeks 3–4."** Metadata curation alone — fetching Methods, LLM extraction, *and human approval of 2,000+ screens* — is plausibly the single largest time sink in the project. The existing plan does not budget human-approval labor at all. This is the most likely schedule-breaker.
- **Directionality is listed as a Weeks 1–2 task** in the original plan, but it depends on curated metadata (Step 1 here) which depends on clean ingestion (Layer 6). The dependency ordering in the original plan is optimistic — directionality cannot precede metadata curation.
- **No mention of the multi-arm screen problem,** despite test case #3 explicitly requiring it. The plan's own validation target exceeds the plan's implied data model.
- **"Sanity checks" are listed but not operationalized.** The original plan names the concept (receptor enrichment example) but doesn't define them as an automated regression suite tied to rebuilds. They should gate every reference-set build, not be a one-time check.
- **Darkness Rating formula is entirely unspecified** — the original documents describe the *concept* (low pubs + few GO terms) but never the weighting, refresh cadence, or species normalization. It is the project's novel contribution and the least-designed piece.

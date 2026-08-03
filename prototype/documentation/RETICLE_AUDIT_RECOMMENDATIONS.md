# RETICLE Scientific, Statistical, Bioinformatics, and Engineering Audit

**Audit date:** 2026-07-23  
**Scope:** `prototype/` documentation, generated artifacts, offline build scripts, web/API code, knowledge-base builders, network and prediction pipelines  
**Audit mode:** Read-only. This report does not modify data, models, databases, or product behavior.

---

## 1. Executive summary

RETICLE already contains a broad and coherent product concept:

- cross-screen gene fitness summaries;
- condition-specific stress and reporter evidence;
- coessential and co-hit networks;
- screen-to-screen similarity;
- Gene Wiki and external knowledge integration;
- function prediction;
- structure visualization;
- LLM-assisted interpretation.

The main scientific risk is not one isolated formula. It is the accumulation of semantic leakage across this chain:

```text
raw screen
  → score type and transformation
  → direction and perturbation modality
  → condition and assay domain
  → eligible-screen selection
  → aggregation/network/prediction
  → biological wording and LLM claim
```

If an earlier layer is wrong, a downstream edge, prediction, or sentence can be computationally reproducible but biologically incorrect.

The highest-priority work is therefore:

1. fix score semantics and missing-value behavior;
2. quarantine unresolved directionality;
3. correct condition/domain classification;
4. stop treating CRISPRa, CRISPRi, RNAi, base editing, and KO as interchangeable;
5. define centrally versioned eligible-screen sets;
6. rebuild derived networks and summaries;
7. make every LLM evidence bundle server-authoritative and snapshot-versioned;
8. only then optimize runtime and expand product claims.

---

## 2. Severity definitions

| Priority | Meaning |
|---|---|
| **P0** | Can reverse, fabricate, or materially misstate a biological conclusion. Must be fixed before treating the affected output as validated. |
| **P1** | Does not always reverse a conclusion, but materially affects calibration, ranking, reproducibility, or interpretation. |
| **P2** | Provenance, architecture, runtime, maintainability, observability, or UX issue that should be addressed for reliable deployment. |

---

## 3. Feature trust status

| Feature | Current status | Safe present-day interpretation |
|---|---:|---|
| Score harmonization | 🔴 P0 | Some score types require reprocessing before downstream use |
| Explore fitness summary | 🟠 P1 | Descriptive within-screen ranking, not calibrated essentiality |
| Stress ledger | 🔴 P0 | Screen association; resistance/sensitivity wording requires stricter semantics |
| Reporter ledger | 🔴 P0 | Reporter-readout association, not necessarily causal regulation |
| Human pooled network | 🔴 P0 | Pooled perturbation-profile similarity; not yet strict coessentiality |
| Mouse network | 🔴 P0/P1 | Exploratory and not directly comparable with the human network |
| Co-hit network | 🟠 P1 | Exploratory co-occurrence; current inferential statistics need revision |
| Screen similarity | 🟠 P1 | Query-relative similarity, not statistical significance |
| Gene Wiki / KB | 🟠 P0/P1 | Many facts are usable, but GO and provenance paths contain correctness risks |
| Function prediction | 🟠 P0/P1 | Hypothesis generation only; confidence is not calibrated |
| Structure viewer | 🟠 P1/P2 | Useful visualization with incomplete isoform/chain/coverage provenance |
| LLM interpretation | 🔴 P0 | Not trustworthy until evidence is reconstructed and validated server-side |

---

# Part I — Scientific correctness

## 4. P0 findings

### P0.1 — Different p-value encodings are transformed as if they were raw p-values

**Evidence**

- `raw p`, `log10(p)`, `-log(p)`, and similar labels are all classified as `SIG_P` in [`harmonize_scores.py`](../script/harmonize_scores.py#L93-L99).
- All `SIG_P` values then pass through the same `-log10` transform in [`harmonize_scores.py`](../script/harmonize_scores.py#L174-L177) and [`harmonize_scores.py`](../script/harmonize_scores.py#L248-L253).
- Auto overrides include screens whose source score is already `Log10 (p-value)`, for example entries in [`directionality_overrides.json`](../processed_data/directionality_overrides.json).

**Why this is wrong**

- Negative `log10(p)` values are clipped to the lower bound and can collapse toward a constant score of 10.
- Already-positive `-log10(p)` values greater than 1 are clipped to 1 and then become 0.
- Ordering, ties, percentiles, robust z-scores, correlations, and condition facts can all be corrupted.

**Recommendation**

- Define distinct typed transforms:
  - `raw_p`;
  - `log10_p`;
  - `neglog10_p`;
  - `signed_logp`;
  - `effect_size`;
  - `paired_effect`;
  - `binary_hit`.
- Store the transform name and version as explicit columns.
- Add monotonicity and known-input/known-output unit tests for every transform.
- Generate per-screen QC for raw/transformed range, unique-value fraction, tie rate, missingness, and expected sign.
- Rebuild every affected screen from its original source layout.

---

### P0.2 — Missing values are converted to neutral values and then ranked

**Evidence**

- Missing p-values are filled with 1 before `-log10`, making them 0 rather than missing: [`harmonize_scores.py`](../script/harmonize_scores.py#L174-L177).
- Missing magnitude scores can be filled with 0: [`harmonize_scores.py`](../script/harmonize_scores.py#L240-L253).
- Paired scores fill missing components with 0: [`harmonize_scores.py`](../script/harmonize_scores.py#L206-L213).
- The percentile layer can subsequently rank these imputed values: [`harmonize_scores.py`](../script/harmonize_scores.py#L352-L369).

**Why this is wrong**

An unmeasured or missing gene is not a biologically neutral gene. Treating missingness as zero inserts observations that were never measured, alters rank distributions, and creates false coverage.

**Recommendation**

- Preserve missing observations as `NULL/NaN`.
- Define a separate explicit imputation policy only where mathematically necessary.
- Do not allow imputed observations to become author-hit, percentile, stress, reporter, or network evidence.
- Track `is_measured`, `is_imputed`, and `imputation_method`.

---

### P0.3 — Condition classification can overwrite explicit treatment biology

**Evidence**

- `classify()` returns immediately when `EXPERIMENTAL_SETUP` matches and does not prioritize the explicit condition name: [`classify_conditions.py`](../script/classify_conditions.py#L85-L93).
- `Implantation to Mouse Model` becomes `in-vivo`; `in-vivo` is assigned no pressure and then fitness: [`classify_conditions.py`](../script/classify_conditions.py#L39-L62) and [`classify_conditions.py`](../script/classify_conditions.py#L96-L121).
- Screen 1802 contains Oxaliplatin but is changed from stress to fitness:
  - [`condition_facets.csv`](../processed_data/condition_facets.csv);
  - [`condition_facets_final.csv`](../processed_data/condition_facets_final.csv).
- The current artifact contains 46 in-vivo rows; all end in fitness, while 26 contain nonempty treatments.

**Why this is wrong**

Experimental setup and biological condition are orthogonal. An in-vivo tumor under Oxaliplatin, anti-PD-1, or CTLA-4 blockade is not an untreated baseline fitness screen.

**Recommendation**

- Separate:
  - experimental setup;
  - treatment/perturbagen;
  - host/model;
  - genotype;
  - dose;
  - duration;
  - treatment-control contrast;
  - readout.
- Treatment-aware rules must take precedence over generic setup labels.
- Double-curate all in-vivo, time-course, and domain-changed screens.
- Report inter-rater agreement.
- Rebuild every downstream fitness summary, screen matrix, and network after correction.
- Quantify screen turnover and edge turnover before and after the reclassification.

---

### P0.4 — Unresolved directionality remains eligible for downstream analysis

**Evidence**

- Unresolved selection direction falls back to multiplier `+1`: [`harmonize_scores.py`](../script/harmonize_scores.py#L223-L253).
- Only overrides with `status == "auto"` are loaded: [`harmonize_scores.py`](../script/harmonize_scores.py#L272-L283).
- The frozen override artifact contains 29 `needs_review` screens.
- Network construction selects non-null percentiles without direction-QC filtering: [`compute_coessential.py`](../script/compute_coessential.py#L130-L135).

**Why this is wrong**

`Needs review` currently means “eligible with an arbitrary positive convention,” rather than “excluded until resolved.” A wrong sign can reverse stress/resistance claims and alter PC1 and correlation structure.

**Recommendation**

- Set signed scores and percentiles to NULL for unresolved screens.
- Add typed columns:
  - `direction_status`;
  - `direction_source`;
  - `direction_confidence`;
  - `direction_version`.
- Enforce a pipeline invariant: no derived layer may ingest `needs_review`, ambiguous, or binary-only direction.
- Manually resolve the remaining 29 screens before production inclusion.

---

### P0.5 — CRISPRa, CRISPRi, RNAi, KO, and base editing are treated as one loss-of-function axis

**Evidence**

- CRISPRa scores are multiplied by `-1` to resemble LoF direction: [`harmonize_scores.py`](../script/harmonize_scores.py#L398-L416).
- The directionality prompt encourages final LoF-style interpretation: [`directionality_mapper.py`](../script/directionality_mapper.py#L123-L128).
- Base editing is broadly classified as KO: [`llm_metadata_extractor.py`](../script/llm_metadata_extractor.py#L126-L145).

**Why this is wrong**

Gain-of-function and loss-of-function are not generally antisymmetric. Dose response, feedback, dominant effects, isoform effects, haploinsufficiency, and edit consequence all break simple sign inversion.

**Recommendation**

- Preserve modality as a first-class axis.
- Build or summarize KO, CRISPRi, CRISPRa, RNAi, and base-editing results separately.
- Classify base-editing libraries using the actual edit design and predicted consequence.
- Only show an inferred LoF/GoF correspondence when paired data from the same gene, background, and readout support it.
- Benchmark concordance separately by modality.

---

### P0.6 — The production pooled network mixes distinct biological questions

**Evidence**

- `--all` calls a context without domain or mechanism restrictions: [`compute_coessential.py`](../script/compute_coessential.py#L123-L125).
- Screen selection filters FULL and library size but not `assay_domain` or modality: [`compute_coessential.py`](../script/compute_coessential.py#L77-L87).
- `net_screen` stores modality and context metadata, but these are not enforced during pooled computation: [`build_net_context.py`](../script/build_net_context.py#L45-L64).

**Why this is wrong**

Baseline essentiality, drug response, reporter behavior, CRISPRa, CRISPRi, and KO do not estimate the same biological quantity. Their pooled correlation has no single stable biological interpretation.

**Recommendation**

- Define the primary production network as QC-passed baseline-fitness screens only.
- Separate KO, CRISPRi, CRISPRa, and other modalities.
- Build stress contexts by canonical treatment/mechanism and preserve dose/time/model.
- Decompose each edge by study, domain, modality, and context contribution.
- Compare pooled and strict-fitness networks using edge stability, complex recovery, and cross-study replication.
- Until rebuilt, label the current product “pooled perturbation-profile similarity,” not strict coessentiality.

---

### P0.7 — Fitness verdicts mix incompatible screen universes and sampling structures

**Evidence**

- `gene_payload()` does not enforce FULL coverage, direction QC, library size, study balancing, or modality restrictions: [`app.py`](../web/app.py#L287-L345).
- `domain_block()` computes an unweighted median across screen rows and applies fixed ±0.15 cutoffs: [`app.py`](../web/app.py#L143-L159).
- Multiple screens from one paper or cell-line panel receive greater weight than independent studies.
- Author-hit rates combine incompatible author-specific thresholds.

**Why this is wrong**

A large cell-line panel can dominate the result. HIT_ONLY and focused screens do not have the same percentile universe as genome-wide FULL screens. A fixed rank threshold is not a calibrated essentiality probability.

**Recommendation**

- Restrict fitness verdicts to eligible, QC-passed, baseline FULL screens.
- Aggregate hierarchically:
  1. technical replicate;
  2. biological model/cell line;
  3. publication/study;
  4. cross-study summary.
- Report study count, model count, heterogeneity, confidence interval, and modality composition.
- Calibrate pan-essential, selective-essential, no-effect, and advantageous categories using reference essential/nonessential sets.
- Keep author-hit rate as a separate, explicitly heterogeneous metric.

---

### P0.8 — Percentile rank is presented as biological effect magnitude

**Evidence**

- Percentiles use average ranks divided by `ranks.max()`, followed by endpoint forcing: [`harmonize_scores.py`](../script/harmonize_scores.py#L352-L369).
- The UI labels `−1` as essential/lethal and `+1` as advantageous: [`index.html`](../web/index.html#L329-L351).
- Header verdicts use median percentile cutoffs: [`index.html`](../web/index.html#L511-L517).

**Why this is wrong**

- Every screen has extreme ranks even when the biological signal is weak.
- Rank is not effect size.
- Tie-heavy screens can become asymmetric.
- The reference universe differs between focused, HIT_ONLY, and genome-wide screens.

**Recommendation**

- Use a standard midrank ECDF such as `2 * (rank - 0.5) / n - 1`.
- Preserve and display tie mass.
- Call the result “within-screen low/high rank.”
- Use depleted/enriched/essential language only when native score semantics, zero point, modality, direction, and effect magnitude support it.

---

### P0.9 — Stress and reporter facts overstate sign and causality

**Evidence**

- Stress values `>= 0` become resistance; reporter values `>= 0` become raises-reporter: [`build_stress_facts.py`](../script/build_stress_facts.py#L99-L125).
- NULL/zero can fall into the positive class.
- Templates describe all modalities as “knockout”: [`build_stress_facts.py`](../script/build_stress_facts.py#L145-L157).
- The app repeats sign simplification and resolves within-paper ties as positive: [`app.py`](../web/app.py#L192-L214).
- Stress grouping uses condition name/class but omits dose, duration, cell/model, and contrast: [`app.py`](../web/app.py#L185-L190).
- Missing PMID values are replaced with per-screen identifiers and then described as independent papers.
- `other` assays can be folded into reporter evidence: [`app.py`](../web/app.py#L315-L320).

**Why this is wrong**

The same sign can mean different things for survival selection, high/low FACS gates, reporter intensity, positive selection, or CRISPRa. A reporter hit does not establish causal regulation.

**Recommendation**

- Store neutral facts first: `perturbation enriched/depleted in selected arm`.
- Translate to resistance/sensitivity only when treatment, contrast, readout, modality, and direction are all validated.
- Treat zero, NULL, and ties as unknown.
- Use the actual perturbation modality in text.
- Group by normalized treatment ID + dose + duration + cell/model + contrast + readout.
- Treat publications as clustering units, not automatically independent replication.
- Quarantine `other/unknown` assays from reporter conclusions.
- Use “associated with reporter readout for X” unless orthogonal evidence supports causal regulation.

---

### P0.10 — GO `NOT` annotations are used as positive evidence and positive ground truth

**Evidence**

- The GO builder retains qualifiers including `NOT`: [`build_kb_go.py`](../script/build_kb_go.py#L123-L140).
- Gene Wiki queries ignore the qualifier: [`app.py`](../web/app.py#L1053-L1057).
- Runtime prediction ignores the qualifier for both query-gene and supporter annotations: [`app.py`](../web/app.py#L1351-L1361).
- Prediction backtesting also ignores it: [`predict_backtest.py`](../script/predict_backtest.py#L39-L49).

**Why this is wrong**

“Gene is NOT involved in X” can be displayed, propagated, and evaluated as “Gene is involved in X.”

**Recommendation**

- Exclude `NOT` from all positive-use queries.
- Store negative annotations separately as contraindications.
- Preserve and display qualifiers and evidence codes.
- Restrict gold-standard backtests to predefined experimental evidence codes, with sensitivity analyses for IEA/ISS.
- Rebuild all affected predictions and backtests.

---

### P0.11 — LLM endpoints can manufacture RETICLE evidence

**Evidence**

- `/api/interpret` accepts and trusts the client-submitted evidence payload: [`app.py`](../web/app.py#L1604-L1611).
- `/api/reporter_explain` accepts arbitrary symbol and screen IDs: [`app.py`](../web/app.py#L1566-L1573).
- The reporter backend reads screen metadata but does not verify that the gene is a hit, that the screens are reporters, or that taxid matches: [`app.py`](../web/app.py#L937-L946).
- The prompt then asserts that the gene is an author-called hit: [`app.py`](../web/app.py#L905-L921).

**Why this is wrong**

An incorrect request, stale frontend state, or direct API caller can cause the model to present a nonexistent screen-gene relationship as RETICLE evidence.

**Recommendation**

- Clients should submit only canonical GeneID/taxid or a server-issued evidence ID.
- The server must reconstruct the complete evidence bundle from trusted tables.
- Verify hit status, assay domain, species, process normalization, and screen membership.
- Add dataset snapshot ID, evidence-bundle hash, prompt version, and model version.
- Validate model citations and evidence IDs programmatically.
- Cache only by the full versioned evidence identity.

---

### P0.12 — Gene identity resolution can leak across organisms or aliases

**Evidence**

- Explore resolves case variants and then selects the organism with the most rows: [`app.py`](../web/app.py#L287-L313).
- Numeric GeneID lookup does not enforce requested taxid: [`app.py`](../web/app.py#L1009-L1013).
- Alias collisions can be resolved by `LIMIT 1`: [`app.py`](../web/app.py#L1014-L1024).
- Harmonized observations retain gene symbol rather than a canonical stable identifier: [`harmonize_scores.py`](../script/harmonize_scores.py#L457-L465).
- Different matrix builders average or overwrite duplicate symbols differently.

**Why this is wrong**

Retired aliases, cross-species symbol collisions, paralogs, and duplicate mappings can combine distinct genes or return the wrong organism.

**Recommendation**

- Use `(taxid, Entrez GeneID)` or a stable Ensembl Gene ID as the primary key throughout.
- Keep symbols and aliases as display/search fields only.
- Return disambiguation candidates instead of arbitrary `LIMIT 1`.
- Validate taxid on numeric lookup.
- Resolve discontinued IDs explicitly.
- Preserve raw identifiers, mapping source/version, and guide multi-target information.

---

## 5. P1 statistical and bioinformatics findings

### P1.1 — Mean-imputed correlation is not a clean Pearson effect estimate

**Evidence**

[`compute_coessential.py`](../script/compute_coessential.py#L163-L194) explicitly notes that mean-imputed correlation is statistically wrong and can differ substantially from pairwise-complete correlation.

**Recommendation**

- Canonicalize gene and guide mappings first.
- Use pairwise-complete shrinkage correlation or a masked probabilistic factor model.
- Keep coverage penalty separate from effect size.
- Calibrate network confidence by coverage.

---

### P1.2 — Network FDR calibration does not match the emitted edge procedure

**Evidence**

- Thresholds are estimated from reciprocal real/null edges: [`compute_coessential.py`](../script/compute_coessential.py#L233-L265).
- Output includes both reciprocal and one-directional union edges: [`compute_coessential.py`](../script/compute_coessential.py#L270-L286).
- Only one shuffle null is used.

**Recommendation**

- Calibrate reciprocal and union selection separately.
- Run repeated block permutations and report Monte Carlo confidence intervals.
- Preserve study, domain, modality, variance, and screen-quality structure in the null.
- Use monotone q-values/local FDR rather than the first noisy ratio crossing.

---

### P1.3 — Study and batch pseudoreplication are not controlled

**Evidence**

- Coessential, co-hit, fitness summaries, and screen similarity treat many screen records as independent observations.
- Screen similarity already shows same-publication matches dominating top results: [`app.py`](../web/app.py#L756-L761).
- Same-study exclusion is based primarily on exact PMID matching.

**Recommendation**

- Create stable `study_id`, `library_id`, `replicate_group`, and `analysis_pipeline_id`.
- Aggregate replicates before cross-study analysis or use hierarchical/random-effect models.
- Require support across multiple studies for strong edge claims.
- Validate with leave-one-PMID-out or leave-one-library-out designs.
- Recompute screen-similarity background after same-study exclusion.

---

### P1.4 — PC1 removal can remove real biology as well as nuisance signal

**Evidence**

- Production network removes PC1 from the imputed matrix: [`compute_coessential.py`](../script/compute_coessential.py#L196-L215).
- Screen similarity also removes PC1: [`app.py`](../web/app.py#L701-L731).

**Recommendation**

- Preserve both raw and residualized versions.
- Model known covariates and negative controls where possible.
- Select nuisance components using held-out studies.
- Report edge sensitivity to residualization.
- Do not use CORUM improvement alone to define the preprocessing truth.

---

### P1.5 — “Genome-wide” eligibility differs by feature

**Evidence**

- Screen matrix uses a minimum near 500 genes: [`build_screen_matrix.py`](../script/build_screen_matrix.py#L30-L33).
- Network uses a much larger library-size gate: [`compute_coessential.py`](../script/compute_coessential.py#L77-L87).
- Legacy Explore coessential artifacts use a different screen pool: [`build_coessential_matrix.py`](../script/build_coessential_matrix.py#L34-L79).

**Recommendation**

Create one centrally defined, versioned eligible-screen view, for example:

```text
FULL
+ non-null distinct canonical genes ≥ configured genome-wide threshold
+ direction_qc = passed
+ transform_qc = passed
+ required domain/modality constraints
+ known study and library provenance
```

Every builder should consume the same view rather than redefining eligibility.

---

### P1.6 — Explore and Network expose different “coessentiality” algorithms

**Evidence**

- Explore reads legacy `coess_<taxid>.npz`: [`app.py`](../web/app.py#L411-L450).
- Network reads the newer context-aware `net_edge` pipeline.

**Recommendation**

- Unify both surfaces on the production network API.
- If legacy output remains, label it clearly with algorithm, snapshot, and input-screen count.

---

### P1.7 — Network node color does not use the edge universe and mean is labeled median

**Evidence**

- `_net_fitness_lean()` says median but computes `AVG`: [`app.py`](../web/app.py#L504-L522).
- STRING network coloring also computes `AVG` while returning a median-labelled field, and lacks an explicit organism constraint: [`app.py`](../web/app.py#L348-L371).
- Node-color screens are not guaranteed to match the edge context.

**Recommendation**

- Compute node summaries from exactly the context’s eligible screens.
- Use study-balanced robust medians.
- Enforce taxid.
- Rename API/UI fields to the actual statistic.

---

### P1.8 — Network UI hides important edge evidence

**Evidence**

- `support` is stored but not returned by `screen_net()`: [`app.py`](../web/app.py#L543-L562).
- UI mainly displays correlation and reciprocal state.
- “Mutual-best” actually means reciprocal top-k, not unique mutual best: [`compute_coessential.py`](../script/compute_coessential.py#L217-L242).

**Recommendation**

Display:

- support count;
- number of studies;
- context screen count;
- coverage;
- rank from each endpoint;
- reciprocal top-k status;
- estimated FDR/q;
- domain/modality composition;
- sensitivity to PC1 removal.

Rename “mutual-best” to “reciprocal top-k.”

---

### P1.9 — Co-hit inference does not control screen hit propensity

**Evidence**

- Author hit rates vary widely across screens.
- Hypergeometric testing controls gene marginals but not screen-level hit burden: [`compute_hit_only.py`](../script/compute_hit_only.py#L122-L136).
- Top-k selection prioritizes p-value rather than effect size: [`compute_hit_only.py`](../script/compute_hit_only.py#L142-L152).
- Stored q-values are not correct monotone BH q-values: [`compute_hit_only.py`](../script/compute_hit_only.py#L175-L184).

**Recommendation**

- Use degree-preserving bipartite permutations or a logistic mixed model with screen effects.
- Block permutations by domain, modality, study, and library.
- Separate effect size from significance.
- Apply proper BH/local-FDR before top-k selection.
- Separate positive-positive, negative-negative, and opposite-direction edge types.

---

### P1.10 — HIT_ONLY screen-pair Fisher tests can use the wrong gene universe

**Evidence**

Legacy correlation code uses the organism-wide union of observed symbols as the Fisher universe: [`compute_correlations.py`](../script/compute_correlations.py#L242-L280).

**Recommendation**

- Use the pair-specific common tested-gene universe when library manifests exist.
- If the universe is unknown, report descriptive Jaccard only and do not claim an inferential p-value.
- Track `universe_known` and library version.
- Deprecate or isolate the legacy analysis if it is not used by the current product.

---

### P1.11 — Node eligibility can exclude dark and conditional genes

**Evidence**

Network nodes must meet author-hit, coverage, and hit-rate gates: [`compute_coessential.py`](../script/compute_coessential.py#L145-L156).

**Recommendation**

- Separate eligibility from uncertainty.
- Allow lower-evidence nodes in an explicit evidence tier.
- Use empirical-Bayes shrinkage rather than author-hit hard gates alone.
- Evaluate recall separately for dark, newly named, low-coverage, and context-specific genes.

---

### P1.12 — Harmonization validation is too coarse

**Evidence**

- Validation aggregates by analysis/method rather than enforcing screen-level QC: [`validate_harmonization.py`](../script/validate_harmonization.py#L37-L85).
- A slightly negative average can pass.
- Coverage of CRISPRa/i, reporter, stress, paired layouts, and transformed p-values is limited.

**Recommendation**

- Validate every screen independently.
- Use large essential/nonessential reference sets.
- Report AUROC, median separation, tie rate, missingness, replicate concordance, and sign accuracy.
- Build golden fixtures by score type, modality, domain, and selection.
- Quarantine a failed screen rather than averaging it away.

---

### P1.13 — CORUM validation does not evaluate the deployed network algorithm

**Evidence**

[`validate_complexes.py`](../script/validate_complexes.py#L72-L188) tests an older correlation setup rather than the final PC1-removed, gated, reciprocal/top-k, shuffle-thresholded output.

**Recommendation**

- Validate the exact emitted edge set.
- Use held-out CORUM complexes plus independent resources such as Complex Portal and interaction maps.
- Bootstrap by complex and study.
- Report confidence intervals.
- Separate performance for dark/low-coverage genes.
- Avoid choosing parameters and evaluating them on the same benchmark.

---

### P1.14 — Function-prediction backtest does not validate the deployed fused predictor

**Evidence**

- The script defines a co-screen layer but does not add it to the evaluated layer list: [`predict_backtest.py`](../script/predict_backtest.py#L124-L140) and [`predict_backtest.py`](../script/predict_backtest.py#L222-L228).
- Runtime prediction fuses layers using a different procedure: [`app.py`](../web/app.py#L1339-L1397).

**Recommendation**

- Evaluate the exact production scoring and confidence labels.
- Use temporal GO holdout with experimental evidence only.
- Report AUPRC, precision@k, hit@k, calibration, coverage, and bootstrap confidence intervals.
- Use degree/annotation-matched nulls.
- Stratify by darkness, family, lineage, and evidence coverage.

---

### P1.15 — Function-prediction layer normalization inflates weak layers

**Evidence**

Each layer is divided by its own query-specific maximum: [`app.py`](../web/app.py#L1339-L1347).

**Why this matters**

A weak maximum DepMap correlation can receive the same normalized weight as a genuinely strong STRING signal. “High confidence” is currently based on layer/supporter counts, not a calibrated probability.

**Recommendation**

- Calibrate raw layer scores globally or within appropriate null distributions.
- Learn or validate fusion weights.
- Convert confidence categories into estimated PPV ranges.
- Do not describe layers as independent without measuring dependence.

---

### P1.16 — “Clean STRING” still has annotation-dependent selection leakage

**Evidence**

- STRING edges are first selected using the full combined score, which includes database and text-mining channels: [`build_kb_string.py`](../script/build_kb_string.py#L73-L99).
- Runtime then recalculates a clean score only inside that preselected universe: [`app.py`](../web/app.py#L1306-L1319).

**Recommendation**

- Build a separate clean-channel universe directly from raw detailed STRING data.
- Do not gate it using full combined score.
- Validate clean and full layers separately.

---

### P1.17 — Function prediction underuses GO evidence quality and hierarchy

**Evidence**

- GO term size can combine human and mouse rather than using a species-specific universe: [`app.py`](../web/app.py#L1295-L1303).
- Evidence-code quality is not used consistently.
- Only `is_a` hierarchy is parsed; important `part_of` relationships are omitted: [`build_kb_go.py`](../script/build_kb_go.py#L27-L65).
- Runtime prediction does not semantically collapse ancestor/descendant redundancy.

**Recommendation**

- Use species-specific universes.
- Distinguish experimental from computational evidence.
- Parse relevant GO relations.
- Use ontology propagation and semantic redundancy control.
- Remove root/generic terms and report GO IDs.

---

### P1.18 — Screen-similarity filtering and labeling are inconsistent

**Evidence**

- A screen can enter the “genome-wide” matrix with roughly 500 genes: [`build_screen_matrix.py`](../script/build_screen_matrix.py#L30-L83).
- The displayed measured-gene count is derived after a cross-screen gene filter.
- Landing copy says weighted correlation while runtime uses plain PC1-removed Pearson: [`index.html`](../web/index.html#L310-L315) and [`app.py`](../web/app.py#L743-L761).
- The displayed σ is a query-relative empirical z-score: [`app.py`](../web/app.py#L791-L809).

**Recommendation**

- Use the centrally defined genome-wide eligibility view.
- Preserve the true raw measured-gene count.
- Align product copy with the actual algorithm.
- Call σ a “query-relative standardized similarity score.”
- If significance is desired, use study-blocked permutations, empirical p-values, and FDR.

---

### P1.19 — Drug-mechanism grouping is too coarse and can mis-map names

**Evidence**

- Mechanisms are assigned through first substring matching, including short/general tokens: [`drug_mechanism.py`](../script/drug_mechanism.py#L14-L49).
- The current “power test” mainly shows that grouping increases sample size: [`test_mechanism_power.py`](../script/test_mechanism_power.py#L76-L103).

**Recommendation**

- Use canonical compound IDs and exact curated synonyms.
- Preserve a hierarchy: compound → target → mechanism/pathway/lesion class.
- Retain dose, duration, and model genotype.
- Validate using known compound-specific resistance genes and leave-compound-out replication.

---

### P1.20 — Mouse network is exploratory but appears product-equivalent

**Evidence**

- The script explicitly states “Not production”: [`explore_mouse_coessential.py`](../script/explore_mouse_coessential.py#L1-L17).
- It lacks the same PC1 removal and node/coverage gates used in human processing.
- It mixes assay domains.

**Recommendation**

- Label the UI as experimental or temporarily hide the network.
- Rebuild with the same algorithmic contract where appropriate.
- Calibrate with mouse-specific gold standards.
- Report bootstrap edge stability and ortholog replication without treating human as the only truth.

---

# Part II — Knowledge, evidence, and product interpretation

## 6. P1/P2 findings for Gene Wiki, KB, external sources, and RAG

### 6.1 — Gene Wiki hit counts lack denominators

**Evidence**

Fingerprint and phenotype summaries count hits but do not show the number of screens in which the gene was actually measured: [`app.py`](../web/app.py#L1090-L1101).

**Recommendation**

- Show `hits / measured eligible screens`.
- Add background-adjusted enrichment.
- Report distinct studies separately from screen records.
- Keep missing condition metadata separate from true untreated fitness.
- Prevent AI from inferring essentiality when only hit counts are available.

---

### 6.2 — GO display is arbitrary and lacks provenance

**Evidence**

GO queries use `LIMIT 8` without evidence-aware ordering: [`app.py`](../web/app.py#L1053-L1057).

**Recommendation**

- Rank experimental, specific, deeper terms above generic/computational terms.
- Show GO ID, namespace, qualifier, evidence code, source, and date/version.
- Allow access to the complete term list.

---

### 6.3 — Reactome evidence codes are discarded

**Evidence**

The source contains evidence codes, but the pathway schema/parser does not retain them: [`build_kb_pathways.py`](../script/build_kb_pathways.py#L36-L62).

**Recommendation**

- Store evidence code and species provenance.
- Distinguish direct human curation from mouse orthology-inferred membership.
- Do not imply equivalent evidence strength.

---

### 6.4 — UniProt accession selection may choose the wrong canonical product

**Evidence**

When multiple entries map to one GeneID, the builder favors the entry with the longest function text: [`build_kb_uniprot.py`](../script/build_kb_uniprot.py#L73-L99).

**Recommendation**

- Preserve one-to-many accessions.
- Use reviewed status, canonical isoform, MANE/Swiss-Prot mapping, and explicit selection rules.
- Let users inspect or choose isoforms where structure/function depends on them.

---

### 6.5 — Structure viewer does not communicate chain and residue coverage

**Evidence**

- PDBe mapping includes a chain, but the UI loads and displays the full PDB entry: [`app.py`](../web/app.py#L1255-L1262) and [`gene.html`](../web/gene.html#L593-L605).
- API failure can be presented similarly to “no structure.”

**Recommendation**

- Highlight the mapped chain.
- Display UniProt residue coverage, construct mutations, missing regions, and ligands.
- Distinguish no record, API failure, CORS failure, and cached transient failure.
- Explain that AlphaFold is a canonical monomer prediction and surface low-pLDDT/disorder caveats.

---

### 6.6 — Orthologs lack relationship type and confidence

**Evidence**

The identifier builder stores pairs/symbols but not one-to-one versus one-to-many relationship type: [`build_kb_identifiers.py`](../script/build_kb_identifiers.py#L77-L103).

**Recommendation**

- Store orthology type, confidence, source, and release.
- Do not automatically transfer functional conclusions across one-to-many relationships.

---

### 6.7 — Darkness score is an unvalidated heuristic

**Evidence**

Fixed paper/GO references, weights, and thresholds are hand-authored: [`external_sources.py`](../script/external_sources.py#L41-L44) and [`external_sources.py`](../script/external_sources.py#L240-L257).

**Recommendation**

- Rename it “RETICLE evidence-density heuristic.”
- Use exact GeneID-linked publications.
- Count unique, qualified GO annotations with evidence/depth.
- Calibrate within species and gene type.
- Distinguish fetch failure from true low evidence.
- Show components and uncertainty.

---

### 6.8 — External identity lookup is insufficiently validated

**Evidence**

MyGene and STRING are queried largely by symbol and can accept the first returned match: [`external_sources.py`](../script/external_sources.py#L112-L135) and [`external_sources.py`](../script/external_sources.py#L186-L230).

**Recommendation**

- Resolve canonical Entrez/Ensembl/STRING IDs internally first.
- Validate returned taxid and identifiers.
- Reject or disambiguate mismatches.

---

### 6.9 — RAG retrieval is gene-centric rather than claim/context-centric

**Evidence**

- Retrieval uses top gene-related abstracts, not necessarily papers relevant to the current treatment or reporter process: [`app.py`](../web/app.py#L867-L880).
- Abstracts are heavily truncated.
- Partner-based de-orphanization prompts receive partner names without the partners’ actual RETICLE profiles.
- Citation IDs are not programmatically constrained to the provided evidence.

**Recommendation**

- Retrieve by gene + condition/process + claim type.
- Pass claim-level evidence IDs.
- Validate citations against an allowlist.
- Include actual partner screen profiles before comparing behavior.
- Produce structured output such as:

```json
{
  "claim": "...",
  "evidence_ids": ["..."],
  "uncertainty": "...",
  "claim_type": "reticle_observation | external_fact | hypothesis"
}
```

---

# Part III — Runtime and software architecture

## 7. P2 runtime findings

### 7.1 — Every PostgreSQL query creates a new connection

**Evidence**

`db_fetchall()` connects and closes for each query: [`app.py`](../web/app.py#L98-L117).

`gene_wiki()` performs many sequential queries, and screen analysis reconstructs much of the Wiki payload again. A first full Wiki load can trigger roughly 39 connection handshakes based on the current call graph.

**Recommendation**

- Use a PostgreSQL connection pool.
- Use one read-only connection/transaction per request.
- Combine related Wiki queries through CTEs/JSON aggregation or a materialized gene profile.
- Remove `screen_analysis → full gene_wiki` duplication.
- Add statement timeout, connection limits, application name, and query timing.

---

### 7.2 — One page can mix incompatible local and RDS snapshots

**Evidence**

- Main data source depends on `USE_PG`: [`app.py`](../web/app.py#L81-L117).
- Screen distributions prefer local master data if present: [`app.py`](../web/app.py#L591-L689).
- KB prefers local data when a local file exists: [`app.py`](../web/app.py#L972-L985).

**Recommendation**

- Bind each deployment to one explicit snapshot.
- Require a manifest containing:
  - source releases;
  - retrieval dates;
  - checksums;
  - build parameters;
  - code commit;
  - row counts;
  - validation metrics.
- Return snapshot ID from every API.
- Fail startup if artifacts are incompatible.

---

### 7.3 — Read paths can silently create empty SQLite files

**Evidence**

Plain `sqlite3.connect()` is used for master, network, and KB read paths: [`app.py`](../web/app.py#L112), [`app.py`](../web/app.py#L480), and [`app.py`](../web/app.py#L985).

**Recommendation**

- Open SQLite with URI `mode=ro`.
- Validate required tables and schema at startup.
- Provide readiness errors listing missing artifacts.
- Never create a database from a web read path.

---

### 7.4 — RDS migration is not an atomic publication process

**Evidence**

- Migration reads schema metadata but does not preserve all constraints: [`migrate_to_rds.py`](../script/migrate_to_rds.py#L75-L82).
- It drops/recreates live tables before copy/index completion.
- It lacks full row-count/checksum validation, schema version, and `ANALYZE`.

**Recommendation**

```text
staging schema
  → load
  → constraints and indexes
  → ANALYZE
  → row-count/checksum/invariant validation
  → transactional view/table swap
  → retain previous snapshot for rollback
```

---

### 7.5 — Build documentation does not reproduce the complete app state

**Evidence**

README quick-start steps do not include the full condition merge/apply process, KB build, network build, or screen matrix build.

**Recommendation**

- Replace procedural instructions with a reproducible DAG.
- Document all required source artifacts and versions.
- Add a single build command with explicit targets.
- Make optional `.env` values empty by default and validate them on startup.

---

### 7.6 — LLM token and HTTP sessions are not reused

**Evidence**

The OAuth token is cached on the `WashULLMClient` instance: [`llm_client.py`](../script/llm_client.py#L104), but runtime endpoints instantiate new clients repeatedly: [`app.py`](../web/app.py#L873), [`app.py`](../web/app.py#L956), and [`app.py`](../web/app.py#L1204).

**Recommendation**

- Share a thread-safe token provider and HTTP session.
- Use bounded workers for LLM calls.
- Add request budgets and circuit breakers.
- Store prompt/model/evidence versions with cached outputs.

---

### 7.7 — Screen similarity recomputes full rankings during pagination

**Evidence**

- Runtime can perform SVD on first request: [`app.py`](../web/app.py#L701-L731).
- Every request rescans and reranks all screens, including load-more pagination: [`app.py`](../web/app.py#L743-L809).

**Recommendation**

- Perform PC removal and pair ranking offline.
- Serve paginated results from an indexed precomputed table.
- If on-demand computation remains, cache by snapshot/query/settings and use a single-flight lock.
- Do not perform large SVDs inside a web request.

---

### 7.8 — HTTP concurrency and request cost are unbounded

**Evidence**

- The server uses `ThreadingHTTPServer`: [`app.py`](../web/app.py#L1623).
- Endpoints contain long external and LLM calls.
- Database queries lack statement budgets.
- POST body size is not bounded.

**Recommendation**

- Move shared scientific services behind the production FastAPI layer.
- Add bounded workers, body limits, rate limits, timeouts, cancellation, and circuit breakers.
- Move heavy work to asynchronous jobs when needed.

---

### 7.9 — Caches are unbounded, unversioned, and weak under concurrency

**Evidence**

Global caches include coessential matrices, screen matrices, reporter explanations, Wiki synthesis, structure results, and GO metadata.

External SQLite cache:

- opens writable connections frequently;
- does not use WAL/single-flight;
- uses a non-thread-safe global NCBI limiter;
- does not distinguish permanent misses from transient failures;
- can trigger retry storms.

See [`external_sources.py`](../script/external_sources.py#L64-L101).

**Recommendation**

- Use bounded LRU/TTL caches.
- Include dataset, model, prompt, and evidence versions in keys.
- Add per-key single-flight locks.
- Use WAL/busy timeout for local SQLite caching.
- Support stale-if-error and short negative-cache periods.
- Do not permanently cache transient API failure as “no data.”

---

### 7.10 — Offline builders use avoidable memory-heavy patterns

**Evidence**

- Screen matrix construction stores large observation arrays as Python lists before conversion: [`build_screen_matrix.py`](../script/build_screen_matrix.py#L55-L75).
- Coessential computation reads observations into pandas and pivots a large dense matrix: [`compute_coessential.py`](../script/compute_coessential.py#L130-L140).

**Recommendation**

- Use chunked columnar ingest.
- Write memmap/Zarr/Parquet intermediates.
- Use sparse or masked structures where appropriate.
- Consider randomized/partial SVD.
- Record wall time and peak memory for every stage.

---

### 7.11 — Pipeline paths and CLI contracts are inconsistent

**Evidence**

Several flagship scripts use cwd-relative paths instead of the central path configuration:

- [`build_net_context.py`](../script/build_net_context.py#L21);
- [`compute_coessential.py`](../script/compute_coessential.py#L73);
- [`compute_hit_only.py`](../script/compute_hit_only.py#L55).

`compute_coessential.py` does not make `--all`, `--domain`, and `--mechanism` mutually exclusive and required.

**Recommendation**

- Use one configuration/path layer.
- Validate all CLI combinations.
- Make output directories snapshot-specific.
- Add query indexes matching real network access patterns.

---

### 7.12 — Frontend correctness and race issues

**Evidence**

- Network fallback calls an undefined `esc()` function: [`network.html`](../web/network.html#L212).
- Several pages can accept stale responses after a new search because requests are not cancelled or sequenced.
- External/DB text is inserted through `innerHTML` in several locations.
- 3Dmol and Cytoscape are eagerly loaded from CDNs without SRI/CSP.

**Recommendation**

- Fix the undefined fallback helper.
- Add `AbortController` and request sequence IDs.
- Use `textContent` and DOM builders for untrusted text.
- Pin and self-host critical frontend libraries or use SRI/CSP.
- Lazy-load the structure viewer.
- Stop continuous animations when hidden or settled.

---

### 7.13 — Logging and telemetry are effectively absent

**Evidence**

Default HTTP logging is disabled: [`app.py`](../web/app.py#L1415).

**Recommendation**

Capture:

- request latency and status;
- DB query count/time;
- cache hit/miss;
- external-source latency/failure;
- LLM model/token/latency;
- snapshot ID;
- screen/network builder wall time and memory;
- scientific QC failure counts.

---

### 7.14 — Dependencies are not fully reproducible

**Evidence**

- `scikit-learn` is imported by validation/backtest code but is absent from the prototype requirements.
- Requirements primarily specify lower bounds.
- Python version, dependency lock, and source-data lock are missing.

**Recommendation**

- Pin supported Python.
- Add a lockfile.
- Add missing dependencies.
- Version all source downloads and checksums.
- Store the environment identity in the snapshot manifest.

---

### 7.15 — Prototype code lacks an enforceable test and CI boundary

**Evidence**

- There is no complete `tests/` suite or pytest configuration for the prototype.
- Existing CI paths do not cover `prototype/**`.
- `test_mechanism_power.py` is an exploratory top-level script rather than an isolated unit test.

**Recommendation**

Add:

1. transform unit tests;
2. score-direction golden tests;
3. condition-classification fixtures;
4. schema and pipeline invariant tests;
5. SQLite/Postgres parity tests;
6. API provenance-contract tests;
7. browser request-race tests;
8. biological benchmark tests;
9. migration checksum tests;
10. p50/p95 runtime and memory benchmarks.

---

# Part IV — Recommended architecture

## 8. Target scientific data contract

Every observation should carry at least:

```text
snapshot_id
taxid
canonical_gene_id
display_symbol
raw_identifier
screen_id
study_id
replicate_group
library_id
modality
assay_domain
condition_id
condition_class
treatment_id
dose
duration
cell_or_model
readout
contrast
raw_score
raw_score_type
transform_name
transform_version
harmonized_score
direction_status
direction_source
direction_confidence
is_measured
is_imputed
author_hit
screen_qc_status
```

Derived features should consume versioned database views rather than restating filter rules in individual scripts:

```text
eligible_baseline_fitness_ko
eligible_baseline_fitness_crispri
eligible_stress
eligible_reporter
eligible_genomewide_similarity
eligible_binary_cohit
```

---

## 9. Recommended code boundaries

```text
prototype/
  schemas/
    observation.py
    evidence.py
    api_models.py

  repositories/
    postgres.py
    sqlite.py
    manifests.py

  services/
    identity.py
    fitness.py
    stress.py
    reporter.py
    network.py
    screen_similarity.py
    knowledge_base.py
    prediction.py
    llm_evidence.py

  pipelines/
    ingest/
    qc/
    networks/
    knowledge_base/
    publish/

  api/
    routes/
    dependencies.py

  prompts/
    interpretation/
    reporter/

  tests/
    unit/
    scientific/
    integration/
    browser/
```

The offline pipeline and web API should share the same scientific service and schema definitions. Product endpoints should not reimplement score or biological semantics independently.

---

# Part V — Validation program

## 10. Screen-level gold set

Create a double-curated, stratified set of at least 200 screens covering:

- all score layouts;
- all modalities;
- all assay domains;
- positive and negative selection;
- FULL and HIT_ONLY coverage;
- in-vivo and time-course studies;
- reporter high/low gates;
- paired positive/negative score layouts;
- raw and transformed p-values.

Two curators should independently label:

- score meaning and transform;
- biological direction;
- modality;
- treatment and contrast;
- readout;
- condition/domain;
- tested-gene universe;
- confidence and unresolved status.

Report inter-rater agreement and adjudication.

---

## 11. Per-screen QC gate

Before any screen enters a derived layer, calculate:

- library size and canonical-gene count;
- measured/missing/imputed fraction;
- unique-value fraction and tie rate;
- score range and expected sign;
- essential/nonessential separation where appropriate;
- replicate concordance;
- author-hit rate;
- direction confidence;
- condition/domain confidence;
- study/library provenance completeness.

Any unresolved or degenerate screen should be quarantined rather than silently included.

---

## 12. Network validation

- Leave-one-study-out validation.
- Cross-study edge replication.
- Separate reciprocal and union calibration.
- Multiple block permutations.
- Multiple gold standards.
- Complex-level and study-level bootstrap confidence intervals.
- Stratification by coverage, modality, domain, and gene darkness.
- Raw versus residualized network sensitivity.
- Edge turnover after condition/direction corrections.

---

## 13. Co-hit validation

- Degree-preserving bipartite null.
- Domain/modality/study/library blocked permutations.
- Correct BH/local-FDR.
- Effect size distinct from significance.
- Pair-specific tested universe.
- Separate concordant and discordant sign channels.
- Stability across author-hit definitions.

---

## 14. Function-prediction validation

- Exact production fused predictor.
- Historical/temporal GO holdout.
- Experimental evidence-only primary benchmark.
- GO `NOT` excluded from positive ground truth.
- Degree- and annotation-matched nulls.
- AUPRC, precision@k, hit@k, coverage, and calibration.
- Bootstrap confidence intervals.
- Dark-gene and low-coverage stratification.
- GO hierarchy and semantic-redundancy handling.

---

# Part VI — Implementation roadmap

## 15. Phase 0: stop incorrect conclusions — approximately 3–5 days

- [ ] Split p-value transform types and fix missing-value handling.
- [ ] Quarantine all unresolved direction screens.
- [ ] Exclude GO `NOT` from positive queries and backtests.
- [ ] Make LLM evidence server-authoritative.
- [ ] Enforce taxid + canonical GeneID resolution.
- [ ] Treat zero/NULL/ties as unknown in stress/reporter.
- [ ] Replace causal reporter wording with association wording.
- [ ] Label pooled network, prediction confidence, and mouse network as exploratory.
- [ ] Fix mean/median UI mismatches.
- [ ] Add minimum provenance and snapshot fields to API responses.

---

## 16. Phase 1: rebuild the scientific dataset — approximately 1–2 weeks

- [ ] Double-curate in-vivo, time-course, and domain-changed screens.
- [ ] Introduce typed observation and transform schemas.
- [ ] Introduce modality-specific eligible views.
- [ ] Move all features to canonical GeneID/taxid.
- [ ] Rebuild fitness summaries from eligible baseline FULL screens.
- [ ] Rebuild stress/reporter facts with neutral semantics.
- [ ] Rebuild human network with domain/modality/study controls.
- [ ] Rebuild screen-similarity matrix with consistent genome-wide eligibility.
- [ ] Rebuild GO-dependent predictions and backtests.
- [ ] Quantify screen, fact, verdict, and edge turnover.

---

## 17. Phase 2: statistical calibration — approximately 2–4 weeks

- [ ] Build the ≥200-screen gold set.
- [ ] Establish screen-level QC gates.
- [ ] Add hierarchical study-balanced fitness models.
- [ ] Replace co-hit null and q-value calculations.
- [ ] Recalibrate network reciprocal/union edge confidence.
- [ ] Run study-blocked network validation.
- [ ] Run temporal function-prediction validation.
- [ ] Calibrate product confidence labels to empirical PPV.
- [ ] Publish uncertainty, support, and sensitivity metrics.

---

## 18. Phase 3: runtime and architecture — can run alongside Phase 2

- [ ] Add PostgreSQL connection pooling and request-scoped connections.
- [ ] Batch/materialize Gene Wiki queries.
- [ ] Serve precomputed screen similarity.
- [ ] Share LLM token provider and HTTP session.
- [ ] Introduce bounded, versioned TTL caches.
- [ ] Add request budgets, cancellation, rate limits, and circuit breakers.
- [ ] Build snapshot manifests and atomic publication.
- [ ] Split `app.py` into repositories/services/API schemas.
- [ ] Add structured logging and health/readiness checks.
- [ ] Add prototype CI, scientific golden tests, and parity tests.
- [ ] Lock Python, dependencies, source releases, and checksums.

---

## 19. Recommended priority order

```text
score semantics
  → direction and condition QC
  → canonical identity and modality
  → eligible-screen contracts
  → rebuild derived layers
  → statistical validation and calibration
  → runtime optimization and architecture hardening
```

Runtime optimization should not precede scientific corrections when it would only make incorrect or unstable conclusions faster to produce and distribute.

---

## 20. Immediate highest-ROI items

If only five changes can be made first, they should be:

1. correct score transformations and missing-value behavior;
2. quarantine unresolved direction and repair condition/domain classification;
3. enforce canonical GeneID/taxid and modality-specific evidence;
4. rebuild the primary network from QC-passed baseline-fitness screens;
5. make every AI answer use a server-generated, versioned, verifiable evidence bundle.


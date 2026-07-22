# RETICLE — Path 1: The Target
### Recomputed effect sizes with propagated uncertainty

**Audience:** Team RETICLE.
**Relationship to the beta:** Same architecture. **The statistic swaps; the schema does not.** Everything built in Path 2 survives.
**Prerequisite:** Phase 0 — the denominator. *How many whole-genome screens have retrievable guide-level counts with resolvable library manifests?* **Nobody currently knows this number, and it determines the shape of the project.**

---

## Why this document exists

The beta gives us a framework. It cannot give us **truth about individual genes**, because it cannot tell a small effect that was measured precisely from a small effect that was measured badly.

That distinction is not a refinement. **It is the difference between a hypothesis-generating tool and an instrument.** And it is the difference between saying *"this gene looks quiet"* and *"this gene is quiet, and we know how confidently."*

Everything in this document follows from recovering one quantity: $\sigma_{g,i}$, the standard error of a gene's effect size in a given screen.

---

## Part I — What Phase 0 buys, precisely

| Capability | Beta (ranks) | Phase 0 |
|---|---|---|
| Semantic neighbor retrieval | ✅ | ✅ |
| Four mechanistic signatures | ✅ qualitatively | ✅ **with confidence intervals** |
| Semantic vs. contextual residual separation | ✅ | ✅ |
| Surprise detection on a user's screen | ✅ candidates | ✅ **findings** |
| Pathway-level buffered modules | ✅ | ✅ **with per-gene weighting** |
| **Buffered genes at single-gene resolution** | ⚠️ suggestive | ✅ |
| **The support field** | ❌ | ✅ |
| **Supported-valley vs. uncharted, at gene × screen resolution** | ❌ | ✅ |
| **Sensitivity in the moderate-effect regime** | ❌ inherited insensitivity | ✅ **purpose-built** |

The last row is the one that matters most and is least obvious. **Explained in Part V.**

---

## Part II — What changes in the data model

**Almost nothing.** One field.

```python
Observation = (gene_id, screen_id, e, σ, status)
                                       ^
                                       new
```

| Field | Beta | Phase 0 |
|---|---|---|
| `e` | signed rank-percentile | **effect size**, signed, normalized by screen dynamic range |
| `σ` | *(absent — global constant $\tau$)* | **standard error of `e`**, propagated from guide-level counts |
| `status` | unchanged | unchanged |
| `c` (context vector) | unchanged | unchanged |

> **This is the payoff for building the schema first.** The context vector, the status field, the exclusion rules, the four edge types, the query architecture — none of it changes. **A field is added. Everything else is inherited.**

---

## Part III — Where $\sigma$ enters the mathematics

### The null model, weighted

$$\mathbb{E}[e_{g,i}] = \beta_g \cdot s_{m_i}$$

$$\hat\beta_g = \frac{\sum_i w_i \, s_{m_i} \, e_{g,i}}{\sum_i w_i \, s_{m_i}^2}, \qquad w_i = \frac{1}{\sigma_{g,i}^2}$$

Under the beta, $w_i \equiv 1$ and this collapses to an unweighted mean. **The weighting is not cosmetic.** A gene measured across three screens — one with 10 guides at 500× depth, two with 3 guides at 80× — currently contributes those three observations equally. It should not.

**And the discrimination is sharpest exactly where we need it: the moderate-effect regime.** A large effect is large regardless of weighting. A small effect is *only* interpretable relative to its uncertainty.

### The residual, weighted

$$r_{g,i} = e_{g,i} - \hat\beta_g s_{m_i}, \qquad R_g = \frac{\sum_i w_i \, r_{g,i}^2}{\sum_i w_i}$$

**Now $R_g$ separates from noise.** Under ranks, a gene with $R = 1.2$ might be genuinely anomalous or might have four dead guides in a bad library. Under Phase 0, the two are distinguishable, because a noisy observation carries a large $\sigma$ and is *down-weighted before it can inflate the residual*.

> **$R$ becomes a claim about the gene rather than a claim about the data.**

### Worked example — why the weighting matters

Gene $g$, three screens, all `measured`. Signed effects and standard errors:

| Screen | $s_m$ | $e$ | $\sigma$ | $w = 1/\sigma^2$ |
|---|---|---|---|---|
| $\mathbf{c}_1$ | −1 | −0.40 | 0.08 | 156.3 |
| $\mathbf{c}_2$ | −1 | −0.35 | 0.09 | 123.5 |
| $\mathbf{c}_3$ | +1 | +0.90 | 0.55 | 3.31 |

**Unweighted (beta):**
$$\hat\beta = \frac{0.40 + 0.35 + 0.90}{3} = 0.55$$
Residuals: $(+0.15,\ +0.20,\ +0.35)$. $\;R = 0.061$

**Weighted (Phase 0):**
$$\hat\beta = \frac{156.3(0.40) + 123.5(0.35) + 3.31(0.90)}{156.3 + 123.5 + 3.31} = \frac{62.5 + 43.2 + 3.0}{283.1} = 0.384$$
Residuals: $(-0.016,\ +0.034,\ +0.516)$
$$R = \frac{156.3(0.00026) + 123.5(0.00116) + 3.31(0.266)}{283.1} = \frac{0.041 + 0.143 + 0.881}{283.1} = 0.0038$$

**Read what happened.** The CRISPRa observation was noisy ($\sigma = 0.55$) and pulled the unweighted fit upward, generating an apparent residual across *all three* screens. Weighted, it contributes almost nothing. $\hat\beta$ drops to 0.38 — **a consistent, precise, small effect** — and $R$ falls by a factor of 16.

**Under the beta, this gene looks mildly anomalous. Under Phase 0, it is a clean, precisely-measured, moderate-effect gene — which is to say, exactly the buffered-gene signature we are hunting.** The beta would have flagged it for the wrong reason and possibly discarded it as noise.

### The surprise score, on a user's screen

$$z_g = \frac{e_{g,\text{user}} - \hat e_{g,\text{user}}}{\sqrt{\underbrace{\text{Var}_{\text{GP}}\!\left[\hat\beta_g(\mathbf{c}_{\text{user}})\right]}_{\text{corpus can't predict}} + \underbrace{\sigma_{g,\text{user}}^2}_{\text{user measured badly}}}}$$

**Both terms, added in quadrature.** The GP variance protects against extrapolation — a gene the corpus cannot predict will not be flagged as surprising, because the prediction was never confident. **And $\sigma_{g,\text{user}}$ protects against the user's own noise**, which the beta cannot do at all.

> Under the beta, $\sigma_{g,\text{user}}$ is replaced by a single global constant $\tau$. **A gene with four dead guides and a gene measured perfectly get the same denominator.** This is why beta surprises are candidates, not findings.

### The support field falls out of the same arithmetic

| $\hat\beta$ | posterior SD | Reading |
|---|---|---|
| low | low | **Supported valley.** Established quiet. **Do not dig.** |
| low | **high** | **Uncharted.** Here be dragons. |
| high | low | Established dependency |
| any | high | **Highest-information experiment** |

**Elevation and support from the same computation.** No separate confidence heuristic, no hand-tuned score. This is propagated measurement error — what a physicist would have done from the start.

And it operationalizes the distinction the whole project rests on:

> A gene with $\hat\beta \approx 0$ across forty screens and **tight** posterior is *established quiet* — a supported valley, and we should not waste bench time there.
>
> A gene with $\hat\beta \approx 0$ across forty screens and **wide** posterior is *uncharted* — nobody has really looked, and the treasure may be there.
>
> **Under ranks these are indistinguishable.**

---

## Part IV — The estimator we actually need

**This is the scientific work, and it does not exist in the literature.**

Do not build a harmonization of MAGeCK and STARS. **Build a purpose-built estimator, applied uniformly to recomputed counts.**

### Required properties

**Guide-level, not rank-aggregated.** The signal *is* consistency across guides. Rank aggregation destroys exactly that information.

**Reports effect size and its uncertainty — not a p-value.** A p-value conflates "small and well-measured" with "small and noisy," which is precisely the distinction we exist to make. A gene at $0.2\sigma \pm 0.03$ across ten guides is a candidate. At $0.2\sigma \pm 0.4$ it is noise. **The current literature reports neither.**

**Normalized within-screen against that screen's own dynamic range.** The same absolute effect means different things in a screen whose strongest hit is $5\sigma$ versus one whose strongest is $1.5\sigma$.

**Retains directionality.**

**Propagates counting noise.** Sequencing depth per guide sets a noise floor, and low-abundance guides are disproportionately those targeting depleted genes — so counting noise biases *against* detecting depletion **in exactly the moderate regime.** This must be in the error model, not ignored.

---

## Part V — Why no deposited statistic can answer our question

**This is the argument for Phase 0, and it is stronger than "harmonization would be cleaner."**

MAGeCK RRA, MAGeCK MLE, and STARS are **not different units of the same quantity**, like Celsius and Fahrenheit. They are different statistics computed over different aspects of the data, each discarding different information, each with different sensitivity to guide-efficiency variance and library depth.

**And critically: different behavior in the moderate-effect regime.**

Rank-aggregation methods are *designed* to be robust at the top of the list. Their entire design goal is to confidently call strong hits while tolerating noisy guides. **They are therefore deliberately insensitive exactly where buffered genes live.**

> A gene with a consistent moderate effect across all four of its guides can score **worse** under RRA than a gene with one spectacular guide and three dead ones — because RRA asks *"does this gene have unusually good ranks?"*, not *"is this gene's effect consistent?"*

So we do not merely face an incomparability problem.

> **The summary statistics deposited in the literature were optimized to find the opposite of what we are looking for.**

This is the hit-call cutoff, one layer deeper. The field's *analysis conventions*, like its *reporting conventions*, are a filter tuned against buffered function. **Same blind spot, different mechanism.**

**Therefore the argument for recomputation is not aesthetic. It is: no deposited summary statistic can answer this question, because none of them was designed to.** That claim is defensible, and it is the spine of the eventual paper.

---

## Part VI — Phase 0, step by step

### Step 1 — The denominator. Start this now, in parallel with the beta.

**One student. Two weeks. One spreadsheet.**

Take the whole-genome subset of BioGRID ORCS. Resolve each screen to its publication. Classify by **data availability** — not by what ORCS deposited:

| Bin | Criterion |
|---|---|
| **Recomputable** | Guide-level raw counts in a public repo (GEO, SRA, Zenodo, supplement) **+** resolvable library manifest |
| **Partially recoverable** | Counts without manifest, or manifest without counts. *Note which piece is missing.* |
| **Gene-level aggregated counts only** | ⚠️ **Nearly useless** for a consistency-across-guides statistic. *Suspect this bin is larger than we would like.* |
| **Summary statistics only** | Not recomputable. *Note which statistic.* |
| **Hit list only** | Uncharted |

**Break each bin down by modality and by pressure type.** This matters enormously:

> Prediction to check: **essentialome-type screens will dominate; compound-treated screens will be scarce and precious.** The redundancy signal is clearest where there are many *different* pressures, not many *similar* ones.
>
> If true, the recovery effort is aimed at exactly the part of the corpus that the buffered-gene analysis most needs. **The recovery project and the science project are not sequential. They are the same project.**

**This is publishable on its own** as a data-availability audit of functional genomics. It quantifies the waste. A study section will sit up.

### Step 2 — The recomputation pipeline, validated against known answers

Take the recomputable screens. Run a uniform pipeline: counts → normalization → guide-level effect → gene-level statistic.

**Start by reproducing the *published* statistic.** If the paper reported MAGeCK RRA, our pipeline must reproduce their hit list from their counts.

> **The validation gate: if we cannot see what they saw, we have no license to claim we see what they missed.**

Expect a nontrivial failure rate. **Expect some of it to be their fault.** Distinguishing "our pipeline is broken" from "their analysis was" is itself a finding, and it is the ground truth that makes agent-driven recovery verifiable.

**Only once we reproduce published results do we have license to compute a different statistic.** This ordering is not negotiable, and it is the same principle as everything else in this project: *establish that you can see what others saw before claiming to see what they missed.*

### Step 3 — The recovery effort

Hits-only screens deposited **only the hit list. The scores existed.** They were computed, then discarded at deposition — destroyed by publication convention, not by nature. Often the library, coverage, and selection pressure *are* stated in the paper. The data may sit in a supplementary table, or in raw reads in SRA.

**Recovering them converts uncharted regions into supported ones at zero experimental cost.** This is the cheapest possible way to elevate valleys, and it is the purest expression of the thesis:

> **If the observation was made, it belongs in the record — regardless of whether the observer found it interesting.**

This is exactly an autonomous-agent task: locate paper → find supplement → parse heterogeneous tables → else fall back to SRA raw counts + library manifest → recompute.

**And it has a built-in check.** Recomputed scores must reproduce the published hit calls. Without that check, agent-driven recovery is unverifiable and worthless. With it, the failure mode is loud.

> If a meaningful fraction is recoverable, RETICLE's curation layer is not preparing data for a tool. It is **the largest recovery of unpublished negative observations in the history of functional genomics** — and the tool is what we build to demonstrate the recovery was worth doing.

### Step 4 — Where the engineering is genuinely hard

**This is the largest engineering task in the project and the least glamorous. It is where projects die.**

Heterogeneous count matrices. Inconsistent guide naming across libraries and versions. Manifests that don't match the counts. Ambiguous control definitions. Screens where the "control" arm is a different *timepoint* rather than a different *condition*.

**Tractable only because of the reproduce-the-published-hits gate.** For every screen, we have an independent answer to check against. Agents can grind through the tedium; the gate tells us when they got it wrong.

---

## Part VII — Normalization, severity-ranked

| Factor | Why it matters | Phase 0? |
|---|---|---|
| **Shared library ⇒ correlated error** | Screens sharing a library share guide-design error. **Effective N = distinct libraries, not screens.** Threatens the entire "consistent across many screens" logic. | ❌ **Fix now.** Make `library` a coordinate. Test robustness across libraries. |
| **Guide efficiency / on-target activity** | A gene whose library guides cut poorly looks like a non-hit **in every screen using that library.** Predicted efficiency is recomputable from sequence + manifest. **Likely a substantial source of false observation-dark calls.** | ✅ Requires manifest |
| **Guides per gene** (4–10, ragged in older libraries) | Directly sets the variance of any gene-level estimate. **Most severe for moderate-effect genes.** Invisible and uncorrectable under ranks. | ✅ Requires manifest |
| **Sequencing depth per guide** | Sets the counting noise floor. Low-abundance guides disproportionately target depleted genes ⇒ **biases against detecting depletion in the moderate regime.** | ✅ Requires counts |
| **Timepoint** | Slow-growth phenotypes accumulate. A buffered gene may be sub-threshold at d14 and a clear hit at d28. **Moderate effects are the most duration-sensitive.** | ❌ Fix now — continuous coordinate |
| **Dynamic range** | A given absolute effect means different things in a $5\sigma$ vs. a $1.5\sigma$ screen. | ❌ Fix now — computed from scores |
| **MOI, selection stringency** | Set dynamic range and noise floor. Usually in methods. | ❌ Fix now |
| **Expression under the screen's own conditions** | A gene not expressed cannot score. Its non-hit is **uninformative**, not quiet. | ⏸ **Pinned. See Part IX.** |

---

## Part VIII — What becomes possible

### 1. The buffered-gene paper — the flagship

**Claim, falsifiable and pre-registerable:** genes that consistently score sub-threshold across many independent whole-genome screens are enriched for real biology, relative to genes scoring sub-threshold sporadically. **Binarization at investigator-chosen cutoffs is systematically destroying recoverable signal.**

Not "underappreciated genes." Rather:

> **CRISPR screening has a structural blind spot with a name and a shape. Here it is. Here is what lives in it.**

**Small consistent effects across many contexts are the signature of buffered, redundant, network-distributed function.** Such genes *cannot* be hits, because hits are defined by large effect. The field has been blind to the class of gene that matters most for robustness, for why knockouts so often do nothing, and for polygenic disease architecture.

**Testable in silico, on existing deposited data. No bench required.**

**Pre-specify before looking:** the definition of "consistent" (or we will tune it into significance without meaning to); the null (sporadic sub-threshold genes, **matched for coverage and literature density**); the analysis plan, timestamped.

**The attached mechanistic prediction — this is what elevates it from observation to hypothesis:** if these genes are redundant, they should show **epistasis.** Combinatorial knockouts should produce the large effects that single knockouts cannot. **Predicting, from discarded data, gene pairs whose combined perturbation produces a phenotype neither produces alone.** Directly testable in the macrophage system.

*If that works even once, it is a very loud result.*

### 2. The atlas of unasked questions — the companion

Genes that never score in any screen. **Not a list — lists are cheap.** The payload is the **coverage-dark** fraction:

> **A systematic map of the selection pressures nobody has applied, and what they would likely reveal.**

Requires the darkness triple to be separable — **and that separability is itself the paper's first result**, because it requires distinguishing *observation-dark* (measured, genuinely quiet) from *coverage-dark* (never meaningfully assayed) from *uncharted* (never deposited). **Only Phase 0 can do this.**

### 3. The instrument

RETICLE's outputs become findings rather than candidates. Every prediction ships with a **falsification specification**: the exact experiment, the readout, the effect size that confirms, the effect size that refutes, and — separately — **the region between that is *uninformative*.**

> *Uninformative ≠ refuted.* Weak controls or insufficient power ⇒ the honest deposit is **uncharted**, not *supported valley.* **Most pre-registrations omit this third category. It is the supported-vs-uncharted distinction, operationalized at the bench.**

**Example:**

> *PARP1 has a redundant paralog buffering its loss under genotoxic stress.*
> → Combinatorial KO of PARP1 + PARP2 under doxorubicin produces dropout ≤ −1.5σ.
> **Refuted if** ≥ −0.5σ with adequate power. **Uninformative if** screen dynamic range < 2.0σ.

> *β(IL-1β) ≈ 1.4, posterior SD 0.89 — untested.*
> **Highest-information single experiment for this gene.** Predicted uncertainty reduction across pressure space: 0.31.

---

## Part IX — Pinned: expression as a context-conditional gene property

**Right in principle.** A gene not expressed in a cell system cannot score under KO or CRISPRi. Its non-hit is **uninformative** — not evidence of quiet. Counting it as quiet corrupts the observation-dark vs. coverage-dark distinction that Part VIII.2 depends on entirely.

**Wrong as a baseline filter.** Under cytokine stimulation an inducible immune gene can go from undetectable to thousands of TPM. A baseline profile marks it "not expressed" and **deletes the most interesting gene in the screen** — systematically removing precisely the inducible genes a cytokine-pressure screen exists to find. **Directionally wrong for exactly the screens we care about most.**

**The correct object is `expression_under_c`** — expression measured under the screen's own conditions. That makes expression a **context-conditional property of a gene**, not a property of the gene. **A new coordinate, not a filter.**

**The barrier is acquisition and applicability assessment**, not logic: locating matched expression datasets, judging their fit to each screen's exact conditions, ingesting them. Substantial effort, uncertain timeline. **Out of scope for the beta.**

Once added, it participates in the GP like any other coordinate — and, pleasingly, **a gene whose $\hat\beta$ correlates with its induced expression across screens is telling us something real about dose-dependence.**

---

## Part X — Sequencing

| When | What |
|---|---|
| **Now, parallel to the beta** | **Phase 0 denominator.** One student, two weeks, one spreadsheet. Publishable alone. **The answer determines the shape of the project.** |
| **After the beta ships** | Recomputation pipeline. **Reproduce published hits before computing anything new.** |
| **Then** | Agent-driven recovery of hits-only screens. Validated by the same gate. |
| **Then** | The purpose-built estimator. Guide-level, effect size + uncertainty, within-screen dynamic-range normalization. |
| **Then** | Buffered-gene analysis, pre-registered, with the matched null. |
| **Then** | Epistasis validation in the macrophage system. **The retrospective claim, tested prospectively.** |

**If ~200 whole-genome screens have retrievable guide-level counts, the buffered-gene analysis runs on existing deposited data alone and the recovery effort *extends* a result already established rather than gating it.** That would make the flagship paper a six-week project.

**If twelve do, this is a different project** — one that begins by *generating* the corpus rather than recovering it, and the grant says something quite different.

**Neither we nor anyone else currently knows which world we are in.**

---

## Carry-outs

1. **One field changes: $\sigma$.** Everything else in the beta is inherited. **This is why we built the schema first.**

2. **The field's summary statistics were optimized to find the opposite of what we are looking for.** Rank aggregation is *designed* to be insensitive in the moderate-effect regime. **No deposited statistic can answer our question, because none was built to.**

3. **Posterior variance is the support field.** Elevation and support fall out of the same arithmetic — no confidence heuristic, no tuning. **Supported valley vs. uncharted becomes measurable.**

4. **The reproduce-the-published-hits gate is what makes agent-driven recovery verifiable.** Without it, recovery is worthless. With it, the failure mode is loud.

5. **The denominator is unknown and it is a two-week question.** Start it now.

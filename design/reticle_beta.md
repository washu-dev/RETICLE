# RETICLE — Path 2: The Beta
### Rank-based implementation.

**Audience:** Team RETICLE
**Purpose:** A concrete framework to build against, argue with, and revise. Where something is wrong, say so.

---

## Part I — What we are building, in plain language

### The problem

Thousands of CRISPR screens have been published. Each one perturbed every gene in a genome and measured the consequence. Collectively this is the largest body of **causal** data in biology — not correlations from observational data, but the results of actually breaking things and watching what happened.

**Almost none of it is usable in aggregate.** Three reasons.

**Screens were binarized.** An investigator picks a cutoff, calls the genes above it "hits," and the rest disappears. But a gene sitting just below the cutoff in twelve independent screens is not twelve non-hits. It is a consistent, weak, real effect. **Every cutoff in the field is a filter that specifically removes redundant, buffered genes** — because a gene whose function is covered by a paralog *cannot* produce a large effect, by definition. The field has been structurally blind to exactly the class of gene that matters most for robustness, for buffering, and for why knockouts so often do nothing.

**Screen results are not comparable to each other.** A gene ranked #132 in a survival screen under cytokine stress means something categorically different from #132 in a drug-resistance screen in a different cell line under a different modality. The interpretive context — what was perturbed, what pressure, what readout — lives in the paper's methods section. **Nobody has made that context machine-readable.** BioGRID ORCS stores the scores and discards the semantics.

**Absence was confused with zero.** Many screens deposit only a hit list. A gene missing from that list might have been measured and scored zero, or might never have been in the library at all. Those are opposite facts. **No current method distinguishes them.** Every co-occurrence-based method treats absence as weak negative evidence, and is therefore learning publication convention as if it were biology.

### What RETICLE does

RETICLE reads the **papers** to recover the context the databases threw away, and uses that recovered context to make screens comparable to one another.

**The LLM never sees a gene's score.** It reads methods sections and answers structured questions: *What kind of perturbation — knockout, knockdown, overexpression? What selection pressure? What compound, if any? What cell system? What library, what timepoint?*

It knows that TNF-α and IL-1β both converge on NF-κB and are therefore related pressures, while doxorubicin damages DNA and is unrelated. **That knowledge comes from biology it learned elsewhere. It never comes from which genes scored in which screen.**

Then ordinary statistics take over. There is no neural network computing the interesting quantity. There is a weighted least-squares fit, a Gaussian process regression, and a subtraction.

> **The LLM describes the experiment. The data describes the gene.**

This separation is the architecture's defense against itself. If we let the model see effect sizes and asked it to infer which genes are anomalous, we would have built a very expensive way to generate plausible-sounding hypotheses with no grounding. The constraint is enforced by construction, not by policy.

---

### Part II — The central idea

Knocking out a required gene should hurt the cell. Overexpressing that same gene should help it. **These are numerically opposite results that mean the same thing.**

So: fit, for each gene, a single number — its **dosage sensitivity**, written $\hat\beta_g$. Then ask whether that one number, combined with what we know about each experiment, explains everything we observed.

**When it does**, the gene is well-behaved. Required, dose-responsively, exactly as mechanism predicts. Unsurprising, and that is fine — most genes are like this, and they serve as our positive controls.

**When it doesn't**, the leftover is the **residual**, $R_g$. That is where the biology is.

> **$\hat\beta$ is what mechanism explains. $R$ is what it doesn't.**

### The four signatures

| Observed pattern | $\hat\beta$ | $R$ | What it means |
|---|---|---|---|
| KO ≈ CRISPRi, anticorrelated with CRISPRa | large | ~0 | **Required, dose-responsive.** Understood. |
| KO ≈ CRISPRi, **same sign** as CRISPRa | small | **large** | **Dosage-balanced.** Too little is bad; too much is bad. Stoichiometric complex member. |
| Effect under CRISPRa **only** | moderate | large | **Sufficient, not required.** Buffered when absent, forcing when overexpressed. **A redundant gene — permanently invisible in the entire loss-of-function literature.** |
| KO ≠ CRISPRi | moderate | large | Threshold behavior — **or** incomplete knockdown. Must control. |

**The dosage-balanced case is the argument in miniature.** Its raw KO effect is a strong hit. Its raw CRISPRa effect is a strong hit. A hit list records two hits, in opposite directions, and moves on. The low $\hat\beta$ is an *artifact* of the model averaging opposite-signed deleterious effects toward zero — **the single number a hit list would assign this gene is exactly wrong.** $R$ is what says: look here.

### Worked example, so this is concrete

Four screens. Effects in σ units, normalized by each screen's dynamic range.

| Screen | modality | $s_m$ |
|---|---|---|
| $\mathbf{c}_1$ | KO | −1 |
| $\mathbf{c}_2$ | CRISPRi | −1 |
| $\mathbf{c}_3$ | CRISPRa | +1 |
| $\mathbf{c}_4$ | CRISPRa | +1 |

**Gene RIPK1** (well-behaved): $e = (-2.4,\ -2.1,\ +2.3,\ +2.2)$

$$\hat\beta = \frac{(-1)(-2.4) + (-1)(-2.1) + (+1)(2.3) + (+1)(2.2)}{4} = \frac{2.4+2.1+2.3+2.2}{4} = 2.25$$

Residuals: $(-0.15,\ +0.15,\ +0.05,\ -0.05)$. $\quad R = \frac{1}{4}\sum r_i^2 = 0.013$

**Verdict:** strongly required, all modalities agree. One parameter explains everything.

**Gene NFKBIA** (IκBα — the NF-κB inhibitor; under inflammatory survival pressure, both losing and overexpressing it should hurt): $e = (-1.8,\ -1.6,\ -2.1,\ -2.0)$

$$\hat\beta = \frac{1.8 + 1.6 - 2.1 - 2.0}{4} = -0.175$$

Residuals: $(-1.975,\ -1.775,\ -1.925,\ -1.825)$. $\quad R = 3.53$

**Verdict:** $\hat\beta \approx 0$ — the gene looks *unimportant*. $R = 3.53$, **270× RIPK1's.** Every residual is negative: do anything to this gene, in either direction, and the cell does worse.

**Now look at what a conventional pipeline reports.** In screen $\mathbf{c}_1$, both genes are strong hits (−2.4, −1.8). Both cross any cutoff. Both get the same GO annotations. In any co-occurrence network, both link to NF-κB signaling. **They are indistinguishable.**

The $(\hat\beta, R)$ decomposition separates them immediately, and the separation is mechanistic rather than statistical.

---

## Part III — The data model

### The primary record is an observation. Never a gene.

```python
Observation = (gene_id, screen_id, e, status)
```

| Field | Beta implementation |
|---|---|
| `e` | **Signed rank-percentile.** See below. |
| `status` | `measured` · `measured_within_manifest` · `undefined_absent` · `undefined_outside_manifest` |

**A gene *is* the set of observations it participates in.** There is no gene-level vector in the database. There is no stored edge. This is not a stylistic preference; Part VII explains why it is load-bearing.

### Signed rank-percentile

$$e_{g,i} = \text{sign}(\text{direction}_{g,i}) \times \left(1 - \frac{2 \cdot \text{rank}_{g,i}}{L_i}\right)$$

$L_i$ = library size for screen $i$. Sign is $+$ for enrichment, $-$ for depletion.

> **Rank 132 of 20,000 ≠ rank 132 of 500.** If the current implementation is not normalizing rank by library size, that is almost certainly the largest single source of noise in the system right now, and the fix is one line.

### `status` is load-bearing and costs nothing to implement

Absence from a hits-only screen is **undefined**, not zero.

| status | May raise association? | May lower association? |
|---|---|---|
| `measured` (whole-genome, continuous score) | ✓ | ✓ |
| `measured_within_manifest` (targeted, in library) | ✓ | ✓ within manifest |
| `undefined_absent` (hits-only screen, gene not listed) | ✓ | **✗ never** |
| `undefined_outside_manifest` (targeted, not in library) | ✗ | ✗ |

**Rule: observations with undefined status are *excluded* from any comparison. Never zeroed.**

Every computed edge must report N of shared `measured` observations. An edge over 2 shared observations and an edge over 40 are not the same object.

> This constraint is free under ranks and **must be built in now.** Retrofitting it after the beta is substantially harder than honoring it from the start, and every downstream claim depends on it.

### BioGRID ORCS data types map onto this near one-to-one

| ORCS deposition | What we have | status | Inference constraint |
|---|---|---|---|
| Whole-genome, continuous scores + investigator hit call | All genes measured and scored | `measured` | Both directions. Gold standard. |
| Sub-genome, hits only | Hits listed. **Scores of non-hits were computed and discarded.** | `undefined_absent` for everything else | **Positive evidence only.** Can raise association; can never lower it. |
| Targeted, manifest + scores | Scores within library; nothing outside | `measured_within_manifest` / `undefined_outside_manifest` | Both directions, **within manifest only** |

**The investigator's hit/no-hit binary is data about the scientist, not about the gene.** Retain it as metadata — someday it is a paper about threshold-setting and publication bias in functional genomics. **It must never inform an edge.**

---

## Part IV — The context vector $\mathbf{c}_i$

**Build this first. It is the invariant.** Whatever statistic eventually fills the effect-size slot — ranks now, recomputed guide-level estimates after Phase 0 — the schema does not change. **Nothing built here is wasted.**

One context vector per screen. Four kinds of slot, which behave differently and must not be conflated.

### 1. Mechanistic slot

```python
modality: Literal["KO", "CRISPRi", "CRISPRa", "base_editor"]
sign: int          # -1 for KO/CRISPRi, +1 for CRISPRa; per-edit for base editors
magnitude_class: Literal["null", "hypomorph", "overexpression"]
```

**Modality has no distance.** CRISPRa is not "closer to" KO than CRISPRi is. What it has is a **signed prior on the expected relationship between values** — the thing that makes $\hat\beta$ and $R$ meaningful at all.

### 2. Categorical slots

```python
aggregation: Literal["guide_level", "gene_level"]
library: str                    # e.g. "Brunello", "Calabrese", "GeCKOv2"
```

**`aggregation` is a coordinate, not a normalization.** A gene-level deposition has already had *somebody else's statistic* applied to it, with unknown properties, before we ever saw it. Treating guide-level and gene-level screens as the same is a category error. **The vector must remember the difference**, so that later we can ask: *does our signal survive restriction to guide-level screens?* If it doesn't, the signal was an artifact of someone else's aggregation choice, and we would never have known.

**`library` is the coordinate nobody expects and everybody needs.**

> **Two screens using the same Brunello library are not independent observations of a gene's dispensability.** They share guide design, and therefore they share guide-efficiency error. A gene whose Brunello guides happen to cut poorly will look like a non-hit in every Brunello screen ever run.
>
> **Effective N is closer to the number of distinct libraries than the number of screens.**

This threatens the entire "consistent across many screens" logic that Paper 2 rests on. It must be a coordinate, and every robustness claim must be tested across libraries, not screens.

### 3. Continuous slots — computed from data, not extracted from text

```python
library_size: int
guides_per_gene: float
timepoint_days: float
dynamic_range: float      # from the score distribution
depth_per_guide: float
MOI: Optional[float]
```

These are free, and they are **more trustworthy than anything the LLM extracts.** Compute them. `timepoint` matters more than it looks: slow-growth phenotypes accumulate, and a buffered gene may be sub-threshold at day 14 and a clear hit at day 28.

### 4. Semantic slots — the LLM's only job

```python
pressure_semantic: np.ndarray    # p_i
system_semantic:   np.ndarray    # y_i
compound_semantic: Optional[np.ndarray]   # x_i
```

> **Prior knowledge represents the conditions. Observation represents the response.**

Embed the **compound** from structure, known targets, mechanism of action. Embed the **cytokine** from receptor family and downstream pathway. Embed the **cell system** from lineage and origin.

**Never embed from which genes scored in those screens.** The moment the condition's representation borrows from the response, every downstream correlation is circular and the whole framework is worthless.

The embedding must place TNF-α near IL-1β (both NF-κB-convergent) and both far from doxorubicin. **That proximity is not derivable from the strings.** It comes from knowing the biology. *This is the entire justification for a semantic embedding rather than a controlled vocabulary, and it is where the LLM earns its place.*

### Slot types frozen. Vocabularies emergent.

**This is a real design decision and I want to defend it, because the instinct to do the opposite is strong.**

The temptation is: build a validated, parsimonious, shared ontology for CRISPR screen context *first*, then compute. That project has no natural endpoint. Every ontology effort in biology — GO, Cell Ontology, all of them — discovered that terminology cannot be finalized in the abstract, **because you do not know which distinctions matter until you try to compute with them.** We would spend eighteen months arguing about whether "cytotoxic" and "growth-inhibitory" are distinct coordinates, and the honest answer is: *it depends on whether treating them as distinct improves cross-screen inference*, which we cannot know until we have a corpus, a representation, and a task.

> Getting the terminology right first, then computing, **is the philosophy this project exists to reject, applied to our own metadata.**

**So:** freeze the *slot types* (one afternoon). Let the extraction agent emit free text into fixed slots. Cluster the values it produces. Fix the controlled vocabulary from **what the corpus actually contains.** Modality collapses to four or five values immediately. Aggregation to two. Coordinates then earn their place by measured improvement on a task — never by argument in a meeting.

---

## Part V — Conditioning on semantics

### The model

Constant $\hat\beta$ assumes a gene's dosage sensitivity is the same under every pressure. False, and its falsity is the point. So:

$$\mathbb{E}[e_{g,i}] = s_{m_i} \cdot \beta_g(\mathbf{c}_i)$$

$\beta_g$ is now a **function over semantic context space**, fitted by Gaussian process.

### What the GP actually does — behind the curtain

Less machinery than the framing suggests, and that is a feature.

The **kernel** measures similarity between two experimental contexts:

$$k(\mathbf{c}_i, \mathbf{c}_j) = \sigma_f^2 \exp\!\left(-\frac{\|\mathbf{p}_i - \mathbf{p}_j\|^2}{2\ell_p^2}\right) \cdot \exp\!\left(-\frac{\|\mathbf{x}_i - \mathbf{x}_j\|^2}{2\ell_x^2}\right) \cdot \delta(\mathbf{y}_i, \mathbf{y}_j)$$

The GP predicts $\beta_g$ at an unobserved context as a **kernel-weighted average of $\beta_g$ at observed contexts.** Nearby pressures contribute. Distant ones don't. Posterior variance is high wherever no observed context was nearby.

**That's it.** The residual is a subtraction. The LLM contributed exactly one thing: coordinates that make *"nearby"* mean something biological rather than lexical.

### The lengthscale is a free diagnostic — wire it in week one

$\ell_p$ is a fitted parameter and it is **interpretable**: how far in pressure space a gene's behavior travels before becoming unpredictable.

- Short $\ell_p$ → pressure-specific biology.
- Long $\ell_p$ → broad function.

> **A bad semantic embedding announces itself as an inflated lengthscale.** If the embedding places doxorubicin next to TNF-α, the GP is forced to fit a huge $\ell_p$ to explain the data. Predictions go vague. Residuals inflate uniformly.

**This is a quality check on the embedding requiring no ground truth, available on day one.** Build it before anything else. If $\ell_p$ blows up, the embedding is bad and nothing downstream means anything.

### The separation that is the whole product

| Gene archetype | Unconditioned $R$ | Conditioned $R$ | Verdict |
|---|---|---|---|
| Suppressed by a compound | 0.52 | **0.02** | **Dissolved.** Chemogenetic interaction — the compound coordinate explains it. |
| Pressure-specific | 1.62 | **0.03** | **Dissolved.** The embedding predicted *which* pressures. |
| Dosage-balanced (NFKBIA-like) | 2.77 | **1.94** | **Survives.** No property of the *conditions* accounts for it. |
| Inverted context-dependence (PARP1-like) | 1.02 | **0.94** | **Survives.** Behavior inverted relative to its semantic neighborhood. |

**On any unconditioned anomaly ranking, the pressure-specific gene and the inverted gene look identical.** The semantic model separates them completely: one dissolves, one survives.

> **Irreducible residual = the conditions do not explain it = unrecognized mechanism.**

That sentence is the product. Everything else RETICLE reports is downstream of it.

---

## Part VI — Passing a genome-scale screen through RETICLE

**This is the primary use case, and it is the one your own lab performs.** ~20,000 genes with continuous scores. Not a hit list — the full distribution.

### The inversion

A hit list asks: *which of my genes crossed a cutoff?*

RETICLE asks: **given everything the corpus knows about each gene under conditions like mine, what should I have observed — and where was I surprised?**

The output is a ranked list of **surprises**, each with an explanation of why it is surprising and an experiment that would resolve it.

### Step 1 — Locate the screen in semantic space

The user supplies methods (or fills a structured form). The LLM emits $\mathbf{c}_{\text{user}}$ by the same extraction protocol used on published papers. Continuous slots are computed from the uploaded scores.

**The screen is now a point in the same space as every corpus screen.**

### Step 2 — Retrieve semantic neighbors

$$\text{sim}(j) = k(\mathbf{c}_{\text{user}}, \mathbf{c}_j)$$

Rank corpus screens by kernel similarity. **Report which coordinates drove the match.**

> *"Your screen is nearest to Zhang 2021 (κ = 0.87 — same pressure family, different modality) and Okonkwo 2019 (κ = 0.81 — different pressure, same NF-κB convergence, same cell system)."*

**Ship this first.** It requires only the semantic layer, it works today, and *"these two screens are secretly asking the same question and nobody noticed"* is the single most legible demonstration of what RETICLE is for.

### Step 3 — Fit every gene on the corpus, holding out the user's screen

For every gene with `status = measured` in ≥ 2 corpus screens:

$$\hat\beta_g(\cdot) \;\leftarrow\; \text{GP fit over corpus observations, EXCLUDING } \mathbf{c}_{\text{user}}$$

**The hold-out is not optional.** Fit on the user's screen and then test against it, and the model predicts what it was told. This is the single easiest way to build something that looks brilliant and means nothing.

Genes with < 2 corpus observations are flagged **uncharted**. They are *not discarded* — see Step 6.

### Step 4 — Predict, then compare

$$\hat e_{g,\text{user}} = s_{m,\text{user}} \cdot \hat\beta_g(\mathbf{c}_{\text{user}})$$

**Surprise score:**

$$z_g = \frac{e_{g,\text{user}} - \hat e_{g,\text{user}}}{\sqrt{\text{Var}_{\text{GP}}\!\left[\hat\beta_g(\mathbf{c}_{\text{user}})\right] + \tau^2}}$$

> ### ⚠️ Where the rank path is weakest. Say this out loud.
>
> Under Path 1, the denominator contains the **gene-specific measurement uncertainty** $\sigma_{g,\text{user}}$, propagated from guide-level counts. **Under ranks, that quantity does not exist.** $\tau^2$ is a single global noise constant estimated once from the corpus. It cannot distinguish a gene the user measured cleanly from one measured with four dead guides.
>
> **Consequence:** a large $|z_g|$ under Path 2 may be genuine surprise, or may be noise. The GP variance term still protects against extrapolation — a gene the corpus *cannot* predict will not be flagged as surprising, because the prediction was never confident. **But nothing protects against the user's own noise.**
>
> **High-$|z|$ genes under Path 2 are candidates. They are not findings.** This is not false modesty; it is the actual epistemic status, and stating it is what makes the eventual Phase 0 result credible.

### The four quadrants

| | Corpus predicted a strong effect | Corpus predicted ~nothing |
|---|---|---|
| **User observed a strong effect** | **Confirmed dependency.** Boring in the best sense — the screen worked. *Positive controls. Report first.* | ⚠️ **Novel dependency.** The corpus says this gene shouldn't matter here. It does. |
| **User observed ~nothing** | ⚠️ **Unexpected buffering.** The corpus says this gene should matter. It didn't. *Something in this system compensates.* | **Confirmed absence.** One more observation on a supported valley. |

**Both off-diagonal quadrants are findings, and the lower-left one is invisible in every existing workflow.** A gene that *failed* to be a hit generates no output anywhere, in any tool, ever. It is exactly as informative as a novel dependency. A typical screen will produce dozens, and right now nobody would see a single one.

### Step 5 — Decompose the surprise

A large $|z_g|$ is not yet an explanation. Ask *why the prediction failed*:

**(a) Was the corpus's model of this gene already broken?** Report $R_{g,\text{conditioned}}$ from the hold-out fit. High $R$ ⇒ *the corpus never understood this gene either.* The user's screen is another datapoint on a pre-existing anomaly. Valuable. Deposit it. **But it is not the user's discovery.**

**(b) Is the user's screen far from anything the corpus has seen?** Report $\max_j k(\mathbf{c}_{\text{user}}, \mathbf{c}_j)$. If low, **the prediction was extrapolation** and the surprise may be uninformative. The honest label is *uncharted*, not *novel*.

**(c) Does the surprise have modality structure?** If the user ran CRISPRa and the corpus knows this gene only from KO screens, a large $|z|$ may be a **sufficiency/requirement split**, not a novel dependency. **RETICLE should say so explicitly** rather than let the user over-interpret a difference the framework predicts.

**(d) How many guides targeted this gene, and how ragged was the library?** Under ranks this cannot be *corrected*, but it can be *flagged*. A gene with 3 guides in a ragged library carries a wider implicit error bar than one with 10.

### Step 6 — Three separate rankings. Never one.

**A single "hit list" collapses questions that must stay separate.**

| Ranking | Sort by | Answers |
|---|---|---|
| **Confirmation** | $\hat e_g$ descending, among low-$\lvert z\rvert$ genes | *Did my screen work?* Report first — it is the QC. |
| **Discovery** | $\lvert z_g \rvert$ descending, filtered by (a)–(d) | *What did I find that the field does not know?* |
| **Information gain** | Expected reduction in $\int \text{Var}[\hat\beta_g(\mathbf{c})]\,d\mathbf{c}$ | *Which of my genes, if followed up, teaches the most?* |

> **The most valuable gene in a screen is rarely the biggest hit.** It is the gene whose result most reduced uncertainty across the space of conditions nobody has tested.

**Uncharted genes** — those with < 2 corpus observations — get their own list: *"Your screen contains the first or second measurement of these 340 genes under any pressure. Here are the ones with large effects."* **These are the highest-value depositions the user can make**, and no existing tool tells them so.

### Step 7 — Pathway aggregation. Load-bearing under ranks.

Individual $z_g$ at moderate effect is noisy, and Path 2 **cannot quantify how noisy.** Aggregating within a pathway is variance reduction, and **it is how the rank path recovers most of the power it loses.**

$$z_P \;\approx\; \frac{1}{\sqrt{|P|}}\sum_{g \in P} z_g$$

Uniform weighting, since per-gene $\sigma$ is unavailable.

**Directionality carries mechanism.** Pathway X enriched in the *negative* distribution of a KO screen and the *positive* distribution of a CRISPRa screen is **concordant**, not contradictory — that is the modality prior, applied at pathway resolution. Same residual logic, more power.

**A pathway with a coherent moderate $z$ across many genes, none individually significant, is a buffered module.** Invisible at gene resolution. Precisely the class of finding that binarization destroys.

> **Under Path 2: trust the pathway before you trust the gene.**

### Step 8 — Deposit

The user's screen re-enters the corpus as ~20,000 new observations, each carrying $\mathbf{c}_{\text{user}}$ and its status.

**Every subsequent user's predictions improve.** This is the flywheel, at the scale of a single tool interaction.

### What the user receives

```
SCREEN REPORT  [rank-based — see caveats]

Located: κ = 0.87 to nearest corpus screen (Zhang 2021)
         Semantic neighborhood: 14 screens, 6 distinct libraries
         Extrapolation warning: none

SCREEN QC
  Confirmed dependencies: 412 genes, median |z| = 0.31
  → Your screen agrees with the corpus where it should. Dynamic range 4.1σ.

DISCOVERY  (candidates — read the caveat)
  Novel dependency          23 genes   corpus predicted ~0, you saw effect
  Unexpected buffering      31 genes   corpus predicted effect, you saw ~0
  Sufficiency/requirement    9 genes   modality split, not novel dependency
  Corpus already anomalous  17 genes   high R — deposit, don't claim
  Low guide count flag       8 genes   wide implicit error bar

  ⚠ Per-gene measurement uncertainty unavailable under rank-based scoring.
    These are CANDIDATES. Individual genes are not established findings.

PATHWAY  ← trust this before the gene list
  3 buffered modules: coherent moderate z, no individual gene significant

UNCHARTED
  340 genes: first or second measurement under any pressure
  → the highest-value deposition in this screen

TOP 5 BY INFORMATION GAIN
  (not by effect size — by uncertainty reduction across pressure space)

Every prediction ships with its falsification specification.
```

**Note what is absent: a ranked hit list.** It can be generated, and it discards context. **It should never be the default view.**

---

## Part VII — Why edges cannot be stored

This is where a team trained on traditional networks will resist hardest, so let me make the argument properly. Three reasons, ascending in severity.

**1. Blast radius.** Store `edge(g, h, weight=0.83)`. Tomorrow a new screen is deposited measuring both genes under a pressure neither had seen. Both $\hat\beta$ functions refit. The similarity changes. **Your stored 0.83 is now wrong, and nothing in the graph knows it.** You would have to recompute every edge touching either gene, and every edge touching every gene that shared a screen with them, because the dynamic-range normalization shifted. **One deposition's blast radius is the entire graph.**

**2. The edge is a property of the pair *and the query*.** "Are these genes similar across all contexts?" gives one number. "Similar within cytokine pressures specifically?" gives another. "Do their residual patterns align?" — a completely different question — gives a third. "Are they buffering partners?" gives a fourth, which isn't even a similarity; it's a *complementarity*.

Which is *the* edge weight? **None.** They are four different questions, and a stored scalar has silently chosen one and discarded the ability to ask the rest.

**3. Provenance amputation.** Consider gene $g$, measured in 40 whole-genome screens, all `status = measured`. And gene $h$, appearing in 40 hits-only screens, `undefined_absent` in 38.

Compute similarity. Under any co-occurrence method, $h$'s 38 absences become zeros, $g$'s measured effects get compared against them, and out pops an edge weight. **That number is a fabrication.** It was computed over 38 undefined values.

An edge over 2 shared `measured` observations and one over 40 are not the same object. An edge across 1 library and one across 6 are not the same object. **No stored scalar can express the difference.**

> **A stored edge is a query result with its provenance amputated.** It has forgotten which observations produced it, which were excluded, how many there were, and what question was asked.

### Therefore

**Store:** the observation table. Immutable, append-only. Each row carries $\mathbf{c}$ and `status`.

**Compute:** everything else, at query time. Every edge returns *weight + N shared measured + N distinct libraries + exclusions + the query that produced it.*

**Deposit observations. Compute contrasts. Never store an edge.**

### The four edge types, computed at render time

| Edge | Definition | Meaning |
|---|---|---|
| **β-similarity** | $\hat\beta_g(\cdot) \approx \hat\beta_h(\cdot)$ across pressure space | Co-dependency, likely same pathway |
| **Residual similarity** | $\cos(\mathbf{r}_g, \mathbf{r}_h)$ high | **Anomalous in the same way.** *Invisible to every existing method.* |
| **Anti-β** | $\hat\beta_g \approx -\hat\beta_h$ | Antagonistic |
| **Buffering** | $\beta_g \approx 0$ under LOF, large under GOF; $\beta_h$ complementary | **Candidate redundant pair.** Directly testable by combinatorial perturbation. |

> **The pitch is not "we can find similar genes." It is "we can find genes that break the same rule."**

---

## Part VIII — Conventional outputs, and what each one discards

Everyone will ask for a p-value, a volcano plot, a network diagram. Generate them. **Be explicit about the loss.** Each is a *projection* of the same underlying object.

| Output | How to generate | **What it discards** |
|---|---|---|
| **p-value** | $R_g$ against a null from permuting $s_m$ within gene, or from genes matched on library and guide count | **Effect size.** Conflates "small and well-measured" with "small and noisy." *Under ranks that distinction doesn't exist anyway — so here the p-value is at least honest about a limitation the framework already has.* |
| **Ranked hit list** | Sort by $\hat\beta$ | **Context.** A gene with high $\hat\beta$ under one pressure ranks alongside a gene high everywhere. |
| **Anomaly ranking** | Sort by $R_{\text{conditioned}}$ | Effect magnitude. **This is the useful ranking, and it is not the hit list.** |
| **Network diagram** | Nodes = genes; edges computed **at render time** | **Uncertainty, N, exclusions, and the query.** Every drawn edge must carry its shared-observation count and library count. |
| **Volcano plot** | $x = \hat\beta$, $y = -\log_{10} p(R)$ | The residual **vector** — only its magnitude survives. *The direction of the anomaly is the mechanism.* |
| **GSEA-style enrichment** | Rank by $\hat\beta$ or $R$; standard machinery | Works. But report it as **corroboration, not primary** — annotation sets are attention-weighted. Run the literature-density-matched control **here**, not in the primary analysis. |

**On the confound, and why our primary analysis is clean:** testing enrichment against GO or complexes imports the attention bias of those annotations — well-studied genes are better represented in every annotation set, so a beautiful enrichment could reflect nothing but the fact that famous genes get annotated more.

**We do not have this problem in the primary analysis, because the screens *are* the annotation.** A gene's position at ranks 132, 100, 250, 59 across four independent experiments is a **measurement**, not a citation. The shared semantic features of those screens describe that gene's behavior owing nothing to whether anyone wrote a paper about it. **Existing annotations become supporting evidence, not ground truth.** The confound dissolves at its root rather than being controlled for. It re-enters only if we report GO enrichment as corroboration — so run the matched control there.

---

## Part IX — How the schema earns its complexity without confirming itself

**The trap:** if we tune the semantic representation to maximize detection of the signatures we are looking for, we have built a machine that finds what we told it to find. Same failure mode as fixed low-rank compression "discovering" that biology is low-dimensional because it was built unable to see anything else.

**The fix:** tune it against a held-out task that is **not** the discovery task.

> ### The replicate-recovery benchmark
>
> Independent screens of the **same compound** in the **same cell system**, run by **different labs**. Their gene-level results should agree, up to noise.
>
> **A semantic representation is adequate if it places genuine replicates close together and does not place unrelated screens close together.**

This is a retrieval task with a known answer. It is completely independent of whether we subsequently find buffered genes or unexpected connections. **These replicates already exist in the corpus, and nobody has ever used them as a benchmark.**

**Protocol:**
1. Fix semantic resolution against replicate recovery — structure vs. targets vs. mechanism-of-action vs. coarse class.
2. **Freeze it.**
3. *Then* run the discovery queries.
4. Ablate: remove a coordinate, see what degrades. **Coordinates earn their place by measured improvement, never by argument.**

> **If we tune the schema after seeing the discovery results, we forfeit the ability to claim anything.**

**This is fully available under Path 2 and requires no Phase 0.** It may be the single most valuable thing the team builds in the next month.

### Extraction validation — boring, cheap, and a reviewer will demand it

Not validation of the *terminology*. Validation of the **extraction**. How often does the agent misassign "cytotoxic compound, CRISPRa, K562, whole-genome," and in which direction?

**Protocol:** hand-annotate ~50 screens. Run the pipeline against them. Report per-coordinate accuracy.

Ownable end-to-end by a student. Publishable as a methods contribution. And it shares ground truth with the eventual recovery work: **for hits-only screens, recomputed scores must reproduce the published hit calls.**

---

## Part X — Three-week build order

Ordered by dependency and by ratio of value to effort.

| # | Task | Effort | Why now |
|---|---|---|---|
| 1 | **Rank → rank-percentile** (normalize by library size) | One line | Probably the largest current noise source. |
| 2 | **Freeze slot types.** Mechanistic / categorical / continuous / semantic. Vocabularies emerge from clustering. | One afternoon | Everything inherits this. Do not debate vocabulary. |
| 3 | **`library` and `aggregation` as coordinates** | Trivial | Protects every downstream claim. `library` in particular — effective N. |
| 4 | **`status` field with the four values, and the exclusion rule** | Trivial under ranks | **Free now, expensive later.** Non-negotiable. |
| 5 | **Semantic embedding** from prior knowledge about compounds, pressures, systems. **Never from screen results.** | Days | The LLM's only job. |
| 6 | **Check $\ell_p$.** Inflated lengthscale ⇒ bad embedding. | Hours | Free diagnostic, no ground truth needed. **Do this before trusting anything.** |
| 7 | **Replicate-recovery benchmark.** Tune semantic resolution. **Freeze.** | ~1 week | The only thing standing between us and a self-confirming schema. |
| 8 | **Semantic neighbor retrieval** — "which screens are secretly asking the same question?" | Days | **Fastest legible result. Ship this first.** |
| 9 | **$\hat\beta$ / $R$ fit; four mechanistic signatures** | ~1 week | The core. |
| 10 | **Screen ingestion + surprise scoring** (Part VI) | ~1 week | The primary use case. |
| 11 | **Pathway aggregation** | Days | Recovers most of the power ranks lose. Load-bearing. |

### Explicitly out of scope for the beta

**Gene expression filtering.** *(Pinned. See Part XI.)*

**Guide-efficiency correction.** Requires library manifests and sequence. Phase 0.

**Per-gene measurement uncertainty.** Requires raw counts. Phase 0. **This is the single most consequential thing we do not have.**

**The Phase 0 denominator itself** — how many whole-genome screens have retrievable guide-level counts with resolvable manifests. One student, two weeks, one spreadsheet. **Not a beta blocker, but start it in parallel**, because the answer determines whether the project's central epistemic claim is measurable at all.

---

## Part XI — Pinned: expression as a context-conditional gene property

**The idea, and why it is right in principle.** A gene not expressed in the user's cell system *cannot* score under KO or CRISPRi. Its non-hit status is therefore **uninformative** — not evidence that the gene is quiet. Counting it as evidence of quiet is a clean logical error, and it corrupts the distinction between *observation-dark* (measured, genuinely nothing) and *coverage-dark* (never meaningfully assayed).

**Why it is not in the beta.**

The obvious implementation — filter against a baseline expression profile for the cell line — is **directionally wrong for exactly the screens we care about most.** Under cytokine stimulation, an inducible immune gene can go from undetectable to thousands of transcripts per million. A baseline THP-1 profile would mark it "not expressed" and **delete the most interesting gene in the screen.** The filter would systematically remove precisely the inducible genes a cytokine-pressure screen exists to find.

**The correct object is `expression_under_c`** — expression measured under the screen's own conditions — which makes expression a **context-conditional property of a gene**, not a property of the gene. That is a new coordinate, not a filter, and it belongs in the schema eventually.

**The barrier is acquisition, not logic.** Locating matched expression datasets, assessing their applicability to each screen's exact conditions, and ingesting them is a substantial effort with an uncertain timeline. **It is not a three-week task.**

**Disposition:**
- **Beta:** do nothing. Do not filter on baseline expression. *A wrong filter is worse than no filter, because it silently destroys signal in the direction of our own hypothesis.*
- **Future:** add `expression_under_c` as a per-gene, per-screen context coordinate. It then participates in the GP like any other coordinate, and — pleasingly — a gene whose $\beta$ correlates with its induced expression across screens is telling us something real about dose-dependence.

**Pinned. Qualified. Revisit after the beta.**

---

## Part XII — What Path 2 must not claim

Say these in the paper, in the talk, and in the tool's own output — **before a reviewer says them for us.** Stating limitations plainly is what will make the eventual Phase 0 result credible.

- **We cannot distinguish "small effect, precisely measured" from "small effect, noisily measured."** High-$R$ and high-$|z|$ genes are **candidates**, not findings.

- **We cannot make the supported-valley call.** $\beta \approx 0$ with dense coverage is **ambiguous under ranks**, not *established quiet*. Only $\sigma$ can adjudicate, and $\sigma$ requires Phase 0.

- **The source corpus's rank-aggregation statistics were designed to be insensitive in the moderate-effect regime.** MAGeCK RRA is built to call strong hits confidently while tolerating noisy guides — a gene with a consistent moderate effect across all its guides can score *worse* than a gene with one spectacular guide and three dead ones. **We inherit that insensitivity.** Pathway aggregation partially compensates. It does not eliminate it.

- **Screens sharing a library are not independent observations.** Always report effective N as distinct libraries.

- **We have not applied an expression filter.** Some apparent buffering may be a gene that simply isn't expressed.

> **The honest state is: we have a promising framework and have not yet done the definitive science.** Said in exactly those words.

---

## Carry-outs

1. **The context vector is the invariant.** Build it now. Swap the statistic after Phase 0. **Nothing is wasted.**

2. **The LLM describes the experiment. The data describes the gene.** It never sees an effect size. Enforced by construction.

3. **$\hat\beta$ is what mechanism explains. $R$ is what it doesn't.** And residual that *survives semantic conditioning* is unrecognized mechanism.

4. **Modality is a signed mechanistic axis, and its residuals are biology.** This opens a class of findings — dosage balance, sufficiency without requirement — that no single modality can reveal.

5. **Screens sharing a library are not independent.** Effective N is libraries, not screens. This threatens a class of claims.

6. **Deposit observations. Compute contrasts. Never store an edge.**

7. **Ranks cost us the support field.** Everything else survives. **Phase 0 is deferred, not cancelled.**

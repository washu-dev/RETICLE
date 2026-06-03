# RETICLE — Layer 2 Technical Roadmap
### Insight Generation (RAG + LLM Rationale)

**Scope:** Take the ranked matched screens from the comparison engine and produce human-readable biological rationale — grounded in retrieved literature, not model priors. This is "Job 2" (online, at query time), distinct from the Layer 5 metadata curation ("Job 1", offline).

**Where it runs:** Cloud serving layer; calls out to LLM API (GPT/Claude/Gemini) and to pgvector for retrieval.

**Definition of done:** For a user's matched results, the system returns a cited biological rationale per gene/cluster, with explicit "insufficient evidence" handling for low-literature genes, and no unsupported claims.

---

## Guiding Principles

1. **Retrieval grounds generation.** The LLM may only assert what the retrieved context supports. This is what makes output trustworthy enough for scientific use.
2. **Job 1 and Job 2 are different code paths.** Different prompts, temperatures, validation. Curation is deterministic extraction; rationale is grounded synthesis. Never share a config.
3. **Absence of evidence is a valid output.** For genuinely uncharacterized genes (the whole point of the tool), "we don't know" beats a confident fabrication.
4. **Cite or don't claim.** Every biological assertion traces to a retrieved source or is marked as hypothesis.

---

## The RAG Pipeline

```
matched screens (from Layer 3)
     |
1. assemble retrieval targets: PMIDs of matched screens + user gene set
     |
2. retrieve: abstracts (E-utilities, cached) + embedded literature chunks (pgvector)
     |
3. construct grounded prompt: user genes + directionality + retrieved context
     |
4. LLM generates rationale with inline citations
     |
5. post-validate: every claim maps to a source; flag/strip unsupported ones
     |
     ==> rationale objects feed the GUI (Layer 1)
```

---

## Retrieval Design

- **Corpus:** abstracts of matched-screen papers (universally available via E-utilities). Full text via PMC for open-access papers as a v2 enhancement.
- **Embeddings:** chunk abstracts/results, embed, store in **pgvector** (same Postgres instance as the reference set). Retrieve top-k chunks relevant to the user's gene cluster + matched screen.
- **Caching:** abstracts and embeddings cached by PMID — fetch/embed once, reuse across all queries.

---

## Prompt & Generation (Job 2 specifics)

- **Temperature:** moderate — synthesis, not extraction. Higher than Job 1.
- **Required structure:** rationale paragraph per gene or co-regulated cluster, each claim tagged with its supporting source.
- **Mandatory guardrails:**
  - **Insufficient-evidence clause:** if retrieved context is thin for a gene, the model must say so rather than infer.
  - **Species-gap flag:** when mouse-screen hits are explained using human literature (via ortholog), flag the cross-species inference explicitly.
  - **Hypothesis labeling:** speculative connections labeled as hypotheses, not findings.

---

## Post-Generation Validation

- **Claim-to-source check:** parse the rationale; verify each biological claim has a citation to retrieved context. Strip or flag orphans.
- **Hallucination triage:** highest risk for low-literature genes (thin context → model fills gaps). These are exactly the priority "dark" genes, so the guardrail is load-bearing, not cosmetic.

---

## Single-Gene Query Path

The MVP also supports "tell me what's known about gene X functionally." This reuses the same RAG machinery: retrieve X's screen appearances (from `reference_gene_screen`) + literature, generate a grounded functional summary with the same guardrails.

---

## Timeline Summary

Maps to "Weeks 7–8: GenAI & PubMed RAG Integration." The retrieval + generation wiring is a few days; the guardrails, claim-validation, and prompt iteration consume the rest.

---

## Open Questions for the Team

1. **Which LLM, and is the choice the same for Job 1 and Job 2?** Job 1 wants reliable structured output; Job 2 wants synthesis quality. They may warrant different models.
2. **Abstract-only sufficiency:** Is an abstract enough grounding for a credible mechanistic rationale, or does the MVP need PMC full text from day one? (Recommendation: abstracts for MVP, measure quality, add full text if thin.)
3. **Claim-validation rigor:** Automated claim-to-source checking is itself hard. For MVP, is human review of generated rationales acceptable, or is automated validation required to ship?
4. **Cost ceiling:** Per-query LLM cost scales with matched-screen count and context size. What's the acceptable cost/latency per user query?
5. **Citation granularity:** Cite to the paper (PMID) level, or to the specific retrieved sentence/chunk? Sentence-level is more verifiable but more engineering.

## Critique of the Existing Roadmap (Layer 2 concerns)

- **The source documents conflate the two LLM jobs** under a single "LLM API" endpoint in the architecture diagram. Job 1 (deterministic metadata extraction) and Job 2 (grounded rationale synthesis) have opposite requirements and must not share a config or prompt. This is a real architectural risk in the existing design.
- **Hallucination is acknowledged generally but not mitigated specifically.** The plan says RAG "connects hits to what is already known," but doesn't address the central failure: for the *uncharacterized* genes the tool is built to surface, retrieved context is thinnest and fabrication risk highest. The guardrail must be explicit.
- **Cross-species inference is unaddressed.** Most screens are mouse; most literature is human. The plan retrieves literature without flagging the species gap — a silent error source.
- **No claim-validation step exists** in the source material. The plan trusts RAG to prevent hallucination structurally, but RAG reduces, not eliminates, it. A post-generation check is needed and absent.
- **The plan correctly identifies RAG as the right tool** and the human-in-the-loop curation dashboard (for Job 1) is a genuine strength. The weaknesses are all in the under-specification of safeguards, not the overall approach.

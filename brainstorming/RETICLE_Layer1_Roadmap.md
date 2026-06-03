# RETICLE — Layer 1 Technical Roadmap
### Presentation Layer (GUI, Auth, I/O)

**Scope:** The browser-based interface where researchers authenticate, submit genes (single or bulk), and receive ranked matches, rationales, directionality labels, and prioritized "dark" genes. Plus the internal curation dashboard (the human-in-the-loop UI for Layer 5 Job 1).

**Where it runs:** Cloud serving layer. Frontend + backend API.

**Definition of done:** A researcher can log in via WashU SSO, upload a gene list, and see ranked screens with biological context, rationale, and flagged unknown genes — plus an internal dashboard where an expert approves LLM-extracted metadata.

---

## Guiding Principles

1. **Ship the MVP UI fast, swap later.** Streamlit MVP → React v2 is a sane path given "continues after."
2. **One language across the stack.** FastAPI backend keeps Python end-to-end with the SciPy/LLM code.
3. **The output IS the product.** The comparison + rationale are only valuable if the UI makes directionality, evidence-strength, and darkness legible at a glance.
4. **Two surfaces, not one.** The public researcher tool and the internal curation dashboard are separate apps with separate auth.

---

## Components

### Backend API (FastAPI)
- Endpoints: submit gene list, submit single gene, fetch results, fetch rationale.
- Orchestrates: input validation → Layer 3 comparison → Layer 2 rationale → assembled response.
- Auth middleware: WashU Entra SSO via OAuth/OIDC.

### Researcher Frontend
- **MVP:** Streamlit — fastest path to a working tool.
- **v2:** React — when polish and interactivity matter.
- Views:
  - **Input:** single gene field; bulk upload (format must be specified — see open questions).
  - **Results:** ranked matched screens with biological context, statistic + FDR, directionality-agreement badge (agree / inverted / unknown), shared genes.
  - **Rationale:** the grounded biological narrative with citations.
  - **Dark genes:** prioritized list of high-darkness genes that cluster with known pathways — the headline feature.
  - **Links back to BioGRID** for each source screen.

### Internal Curation Dashboard (Layer 5 Job 1 UI)
- Separate Streamlit app, internal auth only.
- Shows LLM-extracted screen metadata + evidence span + source text; Approve / Modify per screen.
- Confidence-sorted queue so experts review the ambiguous cases first.

---

## Input Handling (the unspecified spec)

- **Single gene:** symbol or ID → resolve via canonical crosswalk → query.
- **Bulk:** ranked list (gene + score) or hit list (gene only). **Format must be pinned down** — the source documents say "format TBD," which blocks everything upstream. Recommend: CSV/TSV with `gene, score` (score optional → triggers overlap mode).
- **Gene resolution at input:** flag unrecognized symbols immediately; offer the canonical match for ambiguous ones (Acod1/Irg1).

---

## Auth

- WashU Entra SSO (OAuth/OIDC) for the researcher tool — FastAPI has libraries for this.
- Separate, stricter auth for the internal curation dashboard.

---

## Timeline Summary

Maps to "Weeks 9–10: GUI Development & Final Integration." **This is the highest-schedule-risk layer** — it sits last, and if Layers 5–6 (curation) overrun, GUI time gets compressed. Mitigation: Streamlit MVP keeps the floor low; a usable tool is achievable even in compressed time.

---

## Open Questions for the Team

1. **Bulk input format** — the single most overdue spec decision. Recommend CSV/TSV `gene[,score]`. Needs sign-off before Layer 1 (and ideally before Layer 3, which consumes it).
2. **Streamlit vs React for MVP** — Streamlit ships faster and de-risks the back-loaded timeline; React is more polished. Given "continues after," Streamlit-first is recommended.
3. **How is directionality-agreement shown?** A badge? A separate column? Inverted matches in their own section? This UI decision encodes a scientific subtlety and deserves design attention.
4. **Dark-gene presentation** — this is the product's headline. How prominent, how explained, how actionable? Underspecified everywhere.
5. **Result persistence/sharing** — can a researcher save or share a result (with its reference version)? Affects reproducibility story.

## Critique of the Existing Roadmap (Layer 1 concerns)

- **GUI is correctly scoped as a "stretch/long-term goal"** in the proposal, yet the project plan places full GUI build in Weeks 9–10 as a committed deliverable. This tension is unresolved: is the GUI MVP-critical or a stretch? The honest answer affects scheduling.
- **"Format TBD" for bulk input** appears in the architecture and is never resolved. It is a small decision that blocks the comparison engine, the API, and the frontend simultaneously. It should be decided in Week 1, not Week 9.
- **The back-loaded GUI is the project's biggest schedule risk.** Every layer's overrun compounds into this final window. The plan shows no contingency (e.g. a CLI/notebook fallback if the GUI slips).
- **The internal curation dashboard is mentioned** (human-in-the-loop, Phase 2) but not counted as GUI work in the timeline — it's a second app to build, and its labor is invisible in the current plan.
- **Single-gene query** (an MVP promise) and **bulk query** are different UX flows; the plan treats "the GUI" as monolithic and doesn't separate their complexity.
